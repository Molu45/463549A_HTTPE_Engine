# Day 7: Apache Kafka Message Queue Topology & Streaming Architecture
**System:** PayScale High-Throughput Transaction Processing Engine (HTTPE)  
**Throughput Target:** 12,000+ Sustained TPS (18,000 Peak) | Zero Data Loss (RPO=0)  
**Author:** Software Engineering Intern  

---

## 1. Topic Topology, Partitions & Retention Specification

To deliver predictable partition throughput, strict account-level ordering, and data isolation, Kafka topics are segregated across functional lifecycle stages:
+-------------------------------------------------------------------------------------------------------------+
| KAFKA TOPIC ARCHITECTURE & TOPOLOGY                                                                         |
+--------------------------+------------+------------+---------------+--------------------+-------------------+
| Topic Name               | Partitions | Repl. Fact | Cleanup Policy| Retention Period   | Compaction Key    |
+--------------------------+------------+------------+---------------+--------------------+-------------------+
| txn.payment.initiated    | 36         | 3          | delete        | 7 days (168h)      | source_account_id |
| txn.payment.completed    | 36         | 3          | delete        | 7 days (168h)      | source_account_id |
| txn.payment.failed       | 18         | 3          | delete        | 14 days (336h)     | source_account_id |
| txn.merchant.settlement  | 12         | 3          | compact,delete| 30 days (720h)     | merchant_id       |
| txn.audit.trail          | 36         | 3          | compact       | 730 days (2 Years) | transaction_id    |
| txn.dead.letter.queue    | 6          | 3          | delete        | 30 days (720h)     | saga_id           |
+--------------------------+------------+------------+---------------+--------------------+-------------------+


### Partition Sizing & Throughput Calculation Proof:
- **Target Sustained Load:** 12,000 TPS.
- **Target Burst Load (Diwali Peak):** 18,000 TPS.
- **Average JSON Message Size:** ~800 Bytes (including tracing headers and metadata).
- **Target Peak Data Ingestion Rate:**
  $$\text{Data Ingestion} = 18,000 \text{ msgs/sec} \times 800 \text{ bytes} \approx 14.4 \text{ MB/sec}$$
- **Single Partition Throughput Capability:** A standard Kafka partition backed by EBS io2 drives reliably handles 1,000 msgs/sec (or ~2-4 MB/sec) sustained with consumer ACK round-trips.
- **Required Partitions:**
  $$\text{Partitions} = \frac{18,000 \text{ Peak TPS}}{1,000 \text{ TPS/Partition}} = 18 \text{ Partitions}$$
- **Safety Over-Provisioning:** We provision **36 partitions** for high-volume topics (`txn.payment.initiated` and `txn.payment.completed`). This provides a 2x throughput headroom (supporting up to 36,000 TPS) and distributes evenly across a 3-broker cluster ($36 / 3 = 12 \text{ partition leaders per broker}$).

---

## 2. Consumer Group Topology & Worker Alignment

To prevent consumer lag from exceeding 1,000 messages under peak load, consumer group instances are strictly balanced against partition topology:

+-------------------------------------------------------------------------------------------------+
| CONSUMER GROUP SPECIFICATION                                                                    |
+----------------------------+-----------------------+------------------+-------------------------+
| Consumer Group ID          | Target Subscribed Topic| Total Consumers | Avg Processing Latency  |
+----------------------------+-----------------------+------------------+-------------------------+
| cg-saga-orchestrators      | txn.payment.initiated | 36 Workers (1:1) | 12 - 18ms / message     |
| cg-ledger-persisters       | txn.payment.completed | 18 Workers (1:2) | 15 - 25ms (Batch write) |
| cg-notification-dispatchers| txn.payment.completed | 12 Workers (1:3) | 5 - 10ms (Async HTTP)   |
| cg-audit-archivers         | txn.audit.trail       | 6 Workers (1:6)  | 30ms (S3 chunk writer)  |
+----------------------------+-----------------------+------------------+-------------------------+


* **1:1 Assignment for Core Orchestration:** The `cg-saga-orchestrators` consumer group deploys 36 active worker pods matching the 36 topic partitions. Each worker handles exactly 1 partition, preventing consumer thread contention and eliminating group rebalancing churn.

---

## 3. Exactly-Once Semantics (EOS) via Transactional Outbox Pattern

Direct dual-writes (simultaneously updating the database and publishing to Kafka) inevitably cause financial data inconsistency if either network call drops mid-flight. To guarantee exactly-once delivery across distributed boundaries:

[ Inbound Transaction ] ──> [ CockroachDB Local Transaction ]
├─ 1. Write 'transactions' Record
└─ 2. Insert into 'outbox_events'
│ (Atomic Commit)
▼
[ Debezium CDC Engine / Poller ]
│ (Extracts WAL log)
▼
[ Apache Kafka (idempotent producer) ]
(enable.idempotence=true, acks=all)


1. **Atomic Local Commit:** The application writes the transaction record and inserts an event record into a local `outbox_events` table inside the **same atomic database transaction**.
2. **Change Data Capture (CDC):** A high-performance Debezium CDC connector reads CockroachDB's write-ahead log (WAL) and streams changes to Kafka.
3. **Idempotent Kafka Producer:** Kafka producers are initialized with `enable.idempotence=true`, `max.in.flight.requests.per.connection=5`, and `acks=all`. Kafka assigns a unique Producer ID (PID) and monotonic sequence numbers, rejecting duplicate broker writes caused by network retries.

---

## 4. Dead Letter Queue (DLQ) & Retry Policies

When message processing encounters unrecoverable faults (poison messages or persistent shard timeouts), poison messages must not halt partition consumption:

[ Message from 'txn.payment.initiated' ]
│
▼ (Try 1)
[ Worker Execution ]
│
(Fails: Transient Error)
▼
[ Backoff Topic: retry.1 (Delay: 1s) ]
│
(Fails: 3 Retries Exhausted)
▼
[ Backoff Topic: retry.2 (Delay: 5s) ]
│
(Fails: Unrecoverable Schema/Logic Error)
▼
[ Push to 'txn.dead.letter.queue' ] ──> [ P1 Alert & Admin Dashboard ]


* **Retry Strategy:** Transient failures (database connection drop, lock retry exhaustion) route through two tiered retry topics with exponential backoff delays (1s, then 5s).
* **DLQ Routing:** If a transaction fails after 3 total attempts, it is routed to `txn.dead.letter.queue` along with error stack traces and payload metadata.
* **Alerting SLA:** A consumer lag on `txn.dead.letter.queue` > 10 messages triggers an immediate P2 pager alert, allowing the Site Reliability team to replay messages via administrative CLI tools once upstream components recover.