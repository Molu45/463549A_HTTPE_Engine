# Day 1: Scenario Analysis & Bottleneck Remediation Strategy
**System:** PayScale Financial Technologies  
**Target Milestone:** 10x Scale Redesign (1,200 TPS → 12,000+ TPS)  
**Author:** Software Engineering Intern  

---

## 1. Executive Scenario Analysis

PayScale Financial Technologies operates as a Series-B neo-banking platform in Mumbai, currently catering to 12 million monthly active users (MAU) and handling a daily volume of 28 million transactions with an infrastructure capacity capped at 1,200 TPS. Marketing has committed to an aggressive Diwali festive sale featuring widespread cashback incentives, instant merchant settlements, and high-frequency flash discounts. This initiative will expand transaction volume to 85 million daily operations and drive sustained throughput requirements to 12,000 TPS, with 15-minute bursts reaching 18,000 TPS.

The current technical architecture is fundamentally inadequate to sustain this load. It relies on a monolithic PostgreSQL 15 primary database, a single-node RabbitMQ message queue, an 8-instance EC2 application tier, and an unclustered 16GB Redis instance. Under simulated peak traffic, the system demonstrates widespread resource exhaustion, query queue depths exceeding 500 requests, and cross-AZ latency degradation.

Compounding this engineering challenge are strict regulatory and business constraints:
1. **Regulatory Mandates:** RBI's Data Localization Directives and Master Directions on Digital Payment Security require zero offshore data storage and a mandatory 2-year hot data retention policy.
2. **Availability & Latency SLA:** The system must achieve 99.99% availability (maximum allowable downtime of 52.6 minutes/year) while maintaining an end-to-end p99 transaction latency strictly under 100ms (and median p50 latency under 30ms).
3. **Financial Durability:** Transactions must guarantee strict ACID semantics, exactly-once processing (zero double debits or synthetic balance generation), and automated rollback/compensation within 30 seconds.
4. **Capital Expenditure Ceiling:** All infrastructure enhancements, compute allocations, and managed streaming services must fit within a hard financial cap of $45,000 per month.

Transforming PayScale requires moving away from monolithic point-fixes toward a distributed, horizontally partitioned architecture capable of linear throughput scaling.

---

## 2. Deep Dive: Top 5 Bottlenecks & Strategic Mitigations

Based on the Locust 50,000 concurrent user benchmark report, the following five critical architectural failure points must be systematically mitigated:
+---------------------------------------------------------------------------------------------+
| TOP ARCHITECTURAL BOTTLENECK REMEDIATION                                                    |
+--------+-----------------------+----------+-------------------------------------------------+
| ID     | Component             | Severity | Core Root Cause & Strategic Remedy              |
+--------+-----------------------+----------+-------------------------------------------------+
| BN-001 | PostgreSQL Primary    | CRITICAL | Max connection pool exhaustion (max: 200)       |
|        |                       |          | Strategy: Hash sharding + PgBouncer pools       |
+--------+-----------------------+----------+-------------------------------------------------+
| BN-002 | RabbitMQ Broker       | CRITICAL | Single-node queue consumer backlog lag >30s     |
|        |                       |          | Strategy: Partitioned Apache Kafka cluster      |
+--------+-----------------------+----------+-------------------------------------------------+
| BN-006 | DB Row-Level Locks    | CRITICAL | Pessimistic locking deadlocks (15% failure rate)|
|        |                       |          | Strategy: Versioned OCC + Redis pre-checks      |
+--------+-----------------------+----------+-------------------------------------------------+
| BN-003 | Application Servers   | CRITICAL | Thread pool exhaustion; 40% request timeouts    |
|        |                       |          | Strategy: Async I/O runtime (Go) + K8s HPA      |
+--------+-----------------------+----------+-------------------------------------------------+
| BN-004 | Redis Cache Layer     | MEDIUM   | Single-node 16GB evictions (Hit drop: 92%->61%) |
|        |                       |          | Strategy: 6-node Redis Cluster with memory TTL  |
+--------+-----------------------+----------+-------------------------------------------------+


### 1. Bottleneck BN-001: PostgreSQL Connection Pool Exhaustion
* **Observation:** Connection limit saturation at 1,800 TPS with active connection spikes exceeding the configured limit of 200, generating query queue depths above 500.
* **Root Cause:** A single primary database instance processing simultaneous balance checks, transactional debits, and ledger logs synchronously holds open socket connections across incoming application worker threads.
* **Proposed Solution:**
  * Implement connection pooling using **PgBouncer** in transaction-pooling mode to multiplex thousands of client connections over a bounded pool of database sockets.
  * Horizontally partition the accounts and ledger entities across a distributed database cluster using **hash-based sharding** on `account_id`, offloading read-heavy queries to read-replicas.

### 2. Bottleneck BN-002: Message Queue Ingestion Lag (RabbitMQ)
* **Observation:** Single-node broker exhibits severe message acknowledgment backlogs, resulting in downstream consumer lag exceeding 30 seconds at only 2,000 TPS.
* **Root Cause:** RabbitMQ maintains complex queue index state management and synchronous disk write overhead under heavy message volume, which collapses under write bursts.
* **Proposed Solution:**
  * Migrate from RabbitMQ to a multi-broker **Apache Kafka** cluster.
  * Partition payment events by `hash(account_id)` across dedicated partitions to guarantee strict chronological ordering per account while horizontally distributing parallel consumption across worker groups.

### 3. Bottleneck BN-006: Database Row Contention & Deadlock Spikes
* **Observation:** 15% deadlock failure rate on the `accounts` table during concurrent balance updates.
* **Root Cause:** The existing engine utilizes pessimistic row locking (`SELECT ... FOR UPDATE`). When multiple transactions attempt to debit or credit the same accounts simultaneously (e.g., flash sales or merchant pools), circular lock wait conditions trigger cascading rollbacks.
* **Proposed Solution:**
  * Replace pessimistic locking with **Optimistic Concurrency Control (OCC)** using an atomic version counter column (`version = version + 1`).
  * Introduce Redis-based distributed balance reservations to short-circuit insufficient funds prior to touching database rows.

### 4. Bottleneck BN-003: Application Tier Thread Pool Saturation
* **Observation:** Application servers experience complete thread pool exhaustion, resulting in a 40% request timeout failure rate.
* **Root Cause:** Blocking synchronous I/O operations in the monolith cause worker threads to remain blocked waiting on downstream database queries and message broker acknowledgments.
* **Proposed Solution:**
  * Implement an asynchronous microservices execution model using high-efficiency lightweight concurrency primitives (e.g., **Go goroutines**).
  * Deploy stateless payment processing pods behind an API Gateway and Application Load Balancer governed by Kubernetes Horizontal Pod Autoscaling (HPA) scaling between 8 and 64 pods based on CPU and request queue metrics.

### 5. Bottleneck BN-004: Cache Memory Exhaustion & Cache Miss Surges
* **Observation:** Cache hit ratio plummets from 92% to 61% under peak stress due to aggressive memory evictions on the single 16GB Redis node.
* **Root Cause:** A single-instance cache storing idempotency keys, session state, and account balances exhausts available RAM, triggering evictions of hot account keys and generating an operational stampede on the PostgreSQL database.
* **Proposed Solution:**
  * Transition to a multi-node **Redis Cluster** (6 nodes across 3 availability zones, providing 96GB aggregate memory).
  * Configure segmented memory policies: strict 24-hour TTLs on client idempotency keys, separate keyspaces