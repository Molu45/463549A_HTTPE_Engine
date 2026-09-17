# Day 3: High-Level System Architecture Design (HLD)
**System:** PayScale High-Throughput Transaction Processing Engine (HTTPE)  
**Throughput Target:** 12,000 Sustained TPS (18,000 Burst) | Latency: p99 < 100ms | SLA: 99.99% Availability  
**Regulatory Boundary:** Reserve Bank of India (RBI) Data Localization & On-Premises Compliance  

---

## 1. Architectural Topology Overview

The PayScale HTTPE architecture transitions the legacy monolithic payments application into a distributed, event-driven, horizontally scalable microservices ecosystem. The design decouples network ingress, synchronous authorization, asynchronous ledger persistence, and audit logging into isolated failure domains governed by circuit breakers and bulkhead resource allocation.

[ Client Applications / POS / Webhooks ]
│
▼ (TLS 1.3 / mTLS)
[ API Gateway Layer (Kong / Envoy) ]
│
▼ (L7 Layer Balancing)
[ Application Load Balancers (AWS NLB/ALB) ]
│
┌─────────────┴────────────────────────┐
▼                                      ▼
[ Payment Processing Service ]    [ Account Service ]
│            │                            │
│ (Sync)     │ (Idempotency / Locks)      │ (Balance Validations)
▼            ▼                            ▼
[ Fraud SVC ] [ Redis Cluster (96GB) ] ────┘
│
│ (Async Event Ingestion / Outbox)
▼
[ Apache Kafka Cluster (3 Brokers / 36 Partitions) ]
│
├───────────────────────┬────────────────────────┐
▼                       ▼                        ▼
[ Transaction        [ Reconciliation         [ Notification
Orchestrator ]       Service ]                Service ]
│                       │                        │
▼                       ▼                        ▼
[ CockroachDB Cluster ] [ Analytics Store ]   [ Push / SMS / Webhooks ]
(12 Nodes / Sharded)


---

## 2. Specification of the 13 Architecture Components

### Component 1: API Gateway Layer
* **Responsibility:** Ingress enforcement point handling SSL/TLS 1.3 termination, client rate limiting (token bucket algorithm), JWT authentication, request schema validation, and traffic routing.
* **Interfaces:** Ingress from client devices (HTTPS / WSS); Egress to Application Load Balancer / internal VPC service mesh via mTLS.
* **Technology Choice & Justification:** **Kong Gateway (Open Source)** with Lua plugins. Built on OpenResty/Nginx, Kong delivers sub-millisecond routing latency, processes over 40,000 RPS per node, and offers high Redis-backed rate limiting integration.
* **Scaling Strategy:** Autoscaled across 4 to 12 stateless c6i.xlarge instances based on active connection load[cite: 1].
* **Failure Handling:** Active-active multi-AZ routing; healthy nodes absorb traffic if an AZ fails; returns HTTP 429 for rate limit breaches and HTTP 503 during gateway degradation[cite: 1].

### Component 2: Load Balancer
* **Responsibility:** Layer 7 request distribution, health check polling, connection pooling, and connection draining[cite: 1].
* **Interfaces:** Sits between Kong API Gateway and internal Kubernetes ingress controllers[cite: 1].
* **Technology Choice & Justification:** **AWS Network Load Balancer (NLB) fronting Application Load Balancer (ALB)**. NLB terminates millions of concurrent TCP flows with ultra-low latency, passing traffic to ALB for path-based HTTP/2 routing[cite: 1].
* **Scaling Strategy:** Managed elasticity handling automated burst expansions up to 100,000 concurrent sessions without pre-warming requirements[cite: 1].
* **Failure Handling:** Cross-zone load balancing with continuous sub-second health checks; unhealthy targets are removed within 5 seconds without dropping persistent in-flight connections[cite: 1].

### Component 3: Transaction Orchestrator
* **Responsibility:** Centralized coordinator executing the Saga state machine for multi-step P2P payments and batch merchant settlements, ensuring forward execution or automated compensation within 30 seconds[cite: 1].
* **Interfaces:** Consumes transaction events from Kafka `txn.initiated`; issues commands to Payment, Account, and Ledger worker instances[cite: 1].
* **Technology Choice & Justification:** **Custom Go Orchestrator Engine using Temporal.io**. Delivers deterministic event-driven distributed state machines with persistent workflow logs and zero resource wastage[cite: 1].
* **Scaling Strategy:** Scaled to 8 instances (4 vCPU, 16GB RAM) partitioned according to Kafka topic assignment[cite: 1].
* **Failure Handling:** Employs exponential backoff retries; publishes to Dead Letter Queue (DLQ) if compensation fails after 5 retries; triggers administrative paging[cite: 1].

### Component 4: Payment Processing Service
* **Responsibility:** Core payment validation, currency integrity checks, merchant fee computation, and dispatch of debit/credit requests[cite: 1].
* **Interfaces:** Ingress via API Gateway (HTTP/gRPC); calls Redis for idempotency and Fraud Service for pre-authorization[cite: 1].
* **Technology Choice & Justification:** **Go (Golang 1.22+)**. Minimal heap overhead, garbage collection pauses strictly <1ms, and native concurrency (goroutines) capable of processing 15,000+ internal operations per node[cite: 1].
* **Scaling Strategy:** Kubernetes HPA scaling horizontally between 12 and 48 pods based on CPU utilization (>65%) and request queue depth[cite: 1].
* **Failure Handling:** Stateless pods restart via Kubernetes; client retries are deduplicated via the Idempotency Engine[cite: 1].

### Component 5: Account Service
* **Responsibility:** Account balance state management, tier enforcement, account status lookups (ACTIVE, FROZEN), and optimistic concurrency version tracking[cite: 1].
* **Interfaces:** Ingress from Payment Processing Service via gRPC; directly queries CockroachDB account ranges[cite: 1].
* **Technology Choice & Justification:** **Go Microservice with PgBouncer connection pooling**. Provides sub-3ms lookups using prepared statements and localized shard caches[cite: 1].
* **Scaling Strategy:** 6 dedicated instances (4 vCPU, 8GB RAM) scaled based on database read replica load[cite: 1].
* **Failure Handling:** If primary shard leadership transitions, PgBouncer transparently reroutes retried transactions to the newly elected Raft range leaseholder[cite: 1].

### Component 6: Notification Service
* **Responsibility:** Real-time push alerts, transaction receipt generation, webhook dispatch to partner merchants, and SMS notifications[cite: 1].
* **Interfaces:** Consumes finalized events from Kafka `txn.completed` and `txn.failed`; dispatches external HTTPS webhooks and Firebase Cloud Messaging (FCM) alerts[cite: 1].
* **Technology Choice & Justification:** **Node.js / Go worker pools with AWS SNS/SES integration**. Async I/O engine prevents external webhook response lag from holding critical compute capacity[cite: 1].
* **Scaling Strategy:** 3 worker nodes auto-scaling to 10 nodes during festive sale notification surges[cite: 1].
* **Failure Handling:** Webhooks employ an exponential backoff schedule (1s, 5s, 30s, 5m, 1h); failed deliveries are logged to `notification_log` for manual replay[cite: 1].

### Component 7: Fraud Detection Service
* **Responsibility:** Real-time pre-authorization velocity checks, transaction rule verification, device fingerprinting, and blacklisted account prevention within a strict 15ms latency SLA[cite: 1].
* **Interfaces:** Synchronous gRPC endpoint called by Payment Processing Service[cite: 1].
* **Technology Choice & Justification:** **Go microservice evaluating compiled rule sets + ONNX Runtime machine learning inferences** backed by Redis feature stores[cite: 1].
* **Scaling Strategy:** 4 dedicated compute instances (8 vCPU, 32GB RAM) running optimized memory-mapped model weights[cite: 1].
* **Failure Handling:** Governed by `CB-FRAUD` circuit breaker; if downstream latency exceeds 15ms for 3 consecutive executions, circuit breaker opens and falls back to passive rule validation with an asynchronous review flag[cite: 1].

### Component 8: Reconciliation Service
* **Responsibility:** Continuous double-entry bookkeeping verification, matching inter-service balances, and detecting transactional anomalies[cite: 1].
* **Interfaces:** Daily batch queries on CockroachDB cold read replicas and Kafka event log replays[cite: 1].
* **Technology Choice & Justification:** **Apache Spark / Python worker batch scripts** executing off-peak balance sum checks (`Sum(Debits) == Sum(Credits)`)[cite: 1].
* **Scaling Strategy:** Scheduled on-demand ephemeral Kubernetes batch jobs running across 3 worker nodes[cite: 1].
* **Failure Handling:** Any discrepancy generates an immediate P1 alert to financial compliance and freezes the affected merchant settlement pipeline[cite: 1].

### Component 9: Audit & Compliance Service
* **Responsibility:** Immutable ledger archiving, PII data masking, SAR (Suspicious Activity Report) generation, and RBI compliance reporting[cite: 1].
* **Interfaces:** Consumes all topics from Kafka; pushes encrypted audit logs to append-only cloud block storage[cite: 1].
* **Technology Choice & Justification:** **Custom Append-Only Ingestion Service + AWS S3 Glacier (Vault Lock Mode)** with WORM (Write Once, Read Many) configuration[cite: 1].
* **Scaling Strategy:** 2 dedicated workers running continuous log aggregation streams[cite: 1].
* **Failure Handling:** Local NVMe buffer queues store logs during network interruptions, flushing once object storage confirms write locks[cite: 1].

### Component 10: Message Queue / Event Bus
* **Responsibility:** High-throughput decoupled event transport, chronological transaction ordering, and event sourcing backbone[cite: 1].
* **Interfaces:** Receives events from Payment Service Outbox; consumed by Orchestrator, Ledger, Notification, and Audit workers[cite: 1].
* **Technology Choice & Justification:** **Apache Kafka (3-node cluster, KRaft mode, 36 partitions)**. Ensures zero-copy data streaming and strict sequential delivery per account key[cite: 1].
* **Scaling Strategy:** Managed partition scaling; consumer group auto-balancing across worker pods[cite: 1].
* **Failure Handling:** Minimum in-sync replicas (`min.insync.replicas=2`) with `acks=all` ensures zero message loss during broker termination[cite: 1].

### Component 11: Database Layer
* **Responsibility:** Fully ACID-compliant persistent storage for user accounts, transaction states, and double-entry general ledger entries[cite: 1].
* **Interfaces:** Connects to Account Service, Transaction Orchestrator, and Settlement Services via PgBouncer[cite: 1].
* **Technology Choice & Justification:** **CockroachDB (12-node cluster across 3 AZs)**. Provides distributed Serializable ACID isolation, automated Range sharding, and native Raft consensus[cite: 1].
* **Scaling Strategy:** Horizontal addition of storage and compute nodes with automated range rebalancing[cite: 1].
* **Failure Handling:** Loss of any single node or entire AZ triggers Raft leader re-election within 3 seconds, fulfilling RTO < 30s and RPO = 0[cite: 1].

### Component 12: Cache Layer
* **Responsibility:** Distributed idempotency key checks (24-hour TTL), Redis Redlock concurrency controls, and real-time rate limiter token buckets[cite: 1].
* **Interfaces:** Ingress from API Gateway and Payment Processing Service[cite: 1].
* **Technology Choice & Justification:** **Redis Cluster 7.0 (6 nodes: 3 primary, 3 replica, 96GB aggregate RAM)**. Sub-millisecond data manipulation and atomic Lua execution[cite: 1].
* **Scaling Strategy:** Resharding hash slots across additional master-replica pairs[cite: 1].
* **Failure Handling:** Automated Redis Sentinel / Cluster master failover within 2 seconds; persistent AOF (Append Only File) every second[cite: 1].

### Component 13: Observability Stack
* **Responsibility:** Real-time metrics collection, distributed request tracing, centralized structured logging, and automated P1-P4 alerting[cite: 1].
* **Interfaces:** Scrapes telemetry endpoints from all microservices, databases, and Kafka brokers[cite: 1].
* **Technology Choice & Justification:** **Prometheus + Grafana + OpenTelemetry (OTel) + Loki**. Industry standard for cloud-native distributed tracing and telemetry[cite: 1].
* **Scaling Strategy:** Dedicated 3-instance monitoring cluster running decoupled from transactional compute capacity[cite: 1].
* **Failure Handling:** High-availability Thanos sidecars buffering telemetry during ingestion interruptions[cite: 1].