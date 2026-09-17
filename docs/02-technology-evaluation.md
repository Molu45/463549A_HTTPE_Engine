# Day 2: Technology Evaluation & Comparative Analysis
**System:** PayScale High-Throughput Transaction Processing Engine (HTTPE)  
**Target:** 12,000+ Sustained TPS | p99 < 100ms | 99.99% Availability  

---

## 1. Evaluation Methodology & Scoring Framework
All competing technologies were assessed on a normalized 1-5 scale across five critical enterprise vectors:
- **Performance & Latency (Weight: 30%):** Sub-millisecond latency consistency and sustained throughput capability.
- **Operational Complexity (Weight: 20%):** Maintenance overhead, cluster management, partition rebalancing, and failover reliability.
- **Cost Efficiency (Weight: 20%):** Compute/storage resource consumption aligned with the $45,000/month budget ceiling.
- **Team Compatibility (Weight: 15%):** Alignment with existing core backend engineering skill sets.
- **Ecosystem & Support (Weight: 15%):** Tooling maturity, client libraries, monitoring agents, and cloud support within Indian data centers.

---

## 2. Message Broker Evaluation Matrix
+-----------------------------------------------------------------------------------------------+
| MESSAGE QUEUE EVALUATION MATRIX                                                               |
+------------------------+--------+--------------------+--------------------+-------------------+
| Evaluation Criterion   | Weight | Apache Kafka       | RabbitMQ (Current) | AWS SQS (FIFO)    |
+------------------------+--------+--------------------+--------------------+-------------------+
| Performance (12k+ TPS) | 30%    | 5.0 (Partitioned)  | 2.0 (Chokes >2k)   | 3.0 (3k TPS cap)  |
| Operational Complexity | 20%    | 3.5 (KRaft Cluster)| 4.0 (Simpler)      | 5.0 (Serverless)  |
| Cost Efficiency        | 20%    | 4.5 (High Density) | 2.5 (Resource hog) | 2.0 ($0.50/M msgs)|
| Team Compatibility     | 15%    | 4.0 (Event-Driven) | 4.5 (Existing)     | 4.0 (Standard)    |
| Ecosystem & Support    | 15%    | 5.0 (FinTech Def.) | 4.0 (Mature AMQP)  | 4.5 (AWS Native)  |
+------------------------+--------+--------------------+--------------------+-------------------+
| Weighted Total         | 100%   | 4.45 / 5.00        | 3.05 / 5.00        | 3.40 / 5.00       |
+------------------------+--------+--------------------+--------------------+-------------------+


### Analysis & Verdict:
- **RabbitMQ:** Failed during baseline load tests (lag >30s at 2,000 TPS) due to synchronous disk writes and memory-heavy queue indices.
- **AWS SQS FIFO:** Hard-capped at 3,000 TPS with batching (300 TPS without batching), making it completely ineligible for a 12,000 TPS engine.
- **Apache Kafka (Selected):** Handles over 100k TPS per broker via sequential append-only disk I/O, zero-copy OS transfers (`sendfile`), and horizontal partition distribution.

---

## 3. Distributed Database Evaluation Matrix

+-----------------------------------------------------------------------------------------------+
| DATABASE EVALUATION MATRIX                                                                    |
+------------------------+--------+--------------------+--------------------+-------------------+
| Evaluation Criterion   | Weight | CockroachDB        | PostgreSQL + Citus | TiDB              |
+------------------------+--------+--------------------+--------------------+-------------------+
| ACID & Correctness     | 30%    | 5.0 (Raft Consensus| 4.5 (2PC Overhead) | 4.5 (Raft-based)  |
| Throughput / Scale     | 20%    | 4.5 (Multi-master) | 4.0 (Coord. Bottl.)| 4.5 (Horizontal)  |
| Operational Simplicity | 20%    | 4.5 (Auto-sharding)| 2.5 (Manual maint.)| 3.5 (Complex PD)  |
| Cost & Resource Footpr.| 15%    | 3.5 (Higher CPU)   | 4.5 (Lightweight)  | 3.5 (Multi-layer) |
| RBI Compliance / Loc.  | 15%    | 5.0 (On-prem/AWS)  | 5.0 (Standard)     | 4.0 (Niche support|
+------------------------+--------+--------------------+--------------------+-------------------+
| Weighted Total         | 100%   | 4.55 / 5.00        | 4.05 / 5.00        | 4.10 / 5.00       |
+------------------------+--------+--------------------+--------------------+-------------------+


### Analysis & Verdict:
- **PostgreSQL + Citus:** Requires complex manual shard management, and the central coordinator node represents an acute single-point-of-failure at high TPS.
- **CockroachDB (Selected):** Native serializable transactions, automatic range-based sharding with Raft consensus, zero single-point-of-failure, and multi-region resilience adhering strictly to RBI data localization.

---

## 4. In-Memory Caching Layer Evaluation Matrix

+-----------------------------------------------------------------------------------------------+
| CACHE LAYER EVALUATION MATRIX                                                                 |
+------------------------+--------+--------------------+--------------------+-------------------+
| Evaluation Criterion   | Weight | Redis Cluster      | Memcached          | Hazelcast IMDG    |
+------------------------+--------+--------------------+--------------------+-------------------+
| Throughput & Latency   | 30%    | 5.0 (Sub-ms)       | 5.0 (Multi-thread) | 4.5 (Java GC lag) |
| Financial Data Structs | 25%    | 5.0 (Lua, Hash, Set| 2.0 (Simple String)| 4.5 (Rich objects)|
| High Availability/HA   | 20%    | 4.5 (Auto-failover)| 2.0 (No repl built)| 4.5 (Distributed) |
| Cost / Memory Density  | 15%    | 4.0 (96GB / 6 node)| 4.5 (Very dense)   | 3.0 (Enterprise $$|
| Persistence & Locks    | 10%    | 5.0 (Redlock, AOF) | 1.0 (No persist.)  | 4.5 (ACID store)  |
+------------------------+--------+--------------------+--------------------+-------------------+
| Weighted Total         | 100%   | 4.75 / 5.00        | 3.10 / 5.00        | 4.25 / 5.00       |
+------------------------+--------+--------------------+--------------------+-------------------+


### Analysis & Verdict:
- **Redis Cluster (Selected):** Chosen for its atomic Lua scripting capabilities (critical for atomic balance reservations), Redis Redlock for distributed concurrency, and sub-millisecond execution for idempotency validation.