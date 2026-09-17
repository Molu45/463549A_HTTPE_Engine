\# Day 5: Database Schema Design \& Partitioning Strategy

\*\*Engine Target:\*\* 12,000+ Sustained TPS | ACID Guarantees | Zero Double-Spending  

\*\*Storage Architecture:\*\* Sharded CockroachDB / PostgreSQL 16 Distributed Cluster  

\*\*Author:\*\* Software Engineering Intern  



\---



\## 1. Schema Architecture \& Entity Design

The database layer is engineered around strict \*\*double-entry bookkeeping\*\* principles, immutable transactional audit logs, and atomic concurrency controls.



\### Core Relational Entities:

1\. \*\*`users`:\*\* Customer identity entity maintaining KYC verification status and compliance profile data.

2\. \*\*`accounts`:\*\* Balance-bearing entity containing separate `available\_balance` (for immediate authorization) and `ledger\_balance` (for actual settled accounting). Equipped with a monotonic `version` counter for Optimistic Concurrency Control (OCC).

3\. \*\*`transactions`:\*\* Master financial transaction record partitioned monthly by `created\_at`. Contains unique `idempotency\_key` (24h TTL) to guarantee exactly-once execution.

4\. \*\*`ledger\_entries`:\*\* Append-only dual-entry accounting records. For every completed transaction, two rows are generated (`DEBIT` for source, `CREDIT` for destination), ensuring total system debits strictly equal total system credits (`Conservation of Money`).

5\. \*\*`transaction\_events`:\*\* State audit transitions tracking Saga orchestrator workflow execution from `INITIATED` through `COMPLETED` or `REVERSED`.

6\. \*\*`fraud\_rules`:\*\* Configurable threshold and velocity rule definitions evaluated synchronously within the 15ms authorization SLA.

7\. \*\*`merchant\_settlements`:\*\* Batch settlement records capturing MDR deduction, nodal escrow movements, and external interbank UTR identifiers.

8\. \*\*`notification\_log`:\*\* Asynchronous webhook and push delivery tracking with exponential retry counters.



\---



\## 2. Time-Based Partitioning Strategy (RBI Compliance)

India's RBI mandates a minimum of \*\*2 years of hot queryable transactional data\*\* retained on domestic infrastructure. At 85 million daily transactions, the engine accumulates \~31 billion records annually.



To maintain sub-10ms query performance without degrading B-Tree index depths:

\* \*\*Partition Key:\*\* Monthly range partitioning on `created\_at` (`PARTITION BY RANGE (created\_at)`).

\* \*\*Partition Pruning:\*\* Queries specifying date filters isolate execution strictly to the target month's child partition, skipping scans over billions of older records.

\* \*\*Archival Lifecyle:\*\* Partitions older than 24 months are systematically detached and migrated to compressed columnar storage (AWS S3 Glacier WORM) for regulatory audit retention.



\---



\## 3. High-Throughput Indexing Strategy



+-------------------------------------------------------------------------------------------------+

| COMPREHENSIVE INDEXING SPECIFICATION                                                            |

+---------------------+-------------------------------+-------------------------------------------+

| Target Table        | Index Definition              | Performance \& Architectural Purpose       |

+---------------------+-------------------------------+-------------------------------------------+

| accounts            | (shard\_key, account\_id)       | Rapid single-shard partition routing      |

| accounts            | (user\_id)                     | Sub-millisecond account profile lookup    |

| transactions        | (idempotency\_key, created\_at) | Unique conflict detection on payment retry|

| transactions        | (source\_account\_id, created\_at| Reverse-chronological user passbook feed  |

| transactions        | (saga\_id)                     | Saga state correlation \& compensation     |

| ledger\_entries      | (account\_id, created\_at DESC) | Instant statement \& balance reconciliation|

| ledger\_entries      | (transaction\_id)              | Double-entry validation lookup            |

| merchant\_settlements| (batch\_id)                    | Fast retrieval for 100k settlement batches|

+---------------------+-------------------------------+-------------------------------------------+

