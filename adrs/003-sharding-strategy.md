# ADR-003: Distributed Database Sharding Strategy & Key Selection

## Status
Accepted

## Context
PayScale's transaction engine must scale from 1,200 TPS to 12,000 sustained TPS (18,000 peak) across 35 million projected accounts generating 85 million daily transactions. A single PostgreSQL database failed at 1,800 TPS due to connection pool exhaustion and locking bottlenecks. The target datastore must horizontally distribute compute and I/O while minimizing cross-shard distributed transactions, preventing hot spots during flash merchant sales, maintaining zero data loss (RPO = 0), and adhering to RBI domestic data storage rules within a $45,000/month infrastructure budget.

## Decision
We implement a **Virtual Node Consistent Hashing Sharding Architecture** across a 4-shard CockroachDB cluster (12 physical nodes deployed 3x across 3 Availability Zones in AWS Mumbai), using `account_id` as the primary distribution shard key.

### Key Architecture Components:
- **Primary Shard Key:** `account_id` (UUIDv7). Provides uniform mathematical distribution across the hash space and prevents sequential allocation skew.
- **Shard Routing Formula:** `shard_id = MurmurHash3(account_id) % Total_Virtual_Nodes`.
- **Cross-Shard Transactions:** Executed using the **Saga Pattern** with compensating actions orchestrated by an asynchronous state engine, eliminating the latency and lock-holding penalties of distributed Two-Phase Commit (2PC).
- **Topology:** 4 logical database shards, each provisioned with 3 physical replicas (1 primary leaseholder + 2 followers across AZ-1, AZ-2, and AZ-3) with `replication_factor = 3`.

## Alternatives Considered

### 1. Hash-Based Sharding on `user_id`
- *Pros:* Collocates all accounts owned by a single user on one shard.
- *Cons:* Severe skew and hot partitions when aggregate business accounts or marketplace merchants process millions of inbound transactions from disparate users.

### 2. Geographic / Range-Based Sharding (e.g., State/City boundaries)
- *Pros:* Satisfies regional data locality instincts.
- *Cons:* Extreme load imbalance; metro clusters (e.g., Mumbai, Delhi, Bengaluru) experience >70% of festive sale traffic, causing individual shard meltdown while regional shards sit idle.

### 3. Distributed Two-Phase Commit (2PC) for Cross-Shard Transfers
- *Pros:* Atomic database-level guarantee.
- *Cons:* Holds distributed row locks across network partitions; introduces latency tail spikes (>180ms p99) under high concurrency, which violates the <100ms p99 SLA.

## Consequences
### Positive Outcomes:
- **Linear Scaling:** Throughput increases horizontally by provisioning additional storage ranges and compute shards.
- **Lock Isolation:** Intra-account transactions execute locally on a single shard leaseholder within 8-12ms.
- **Zero Data Loss:** Raft quorum across 3 AZs ensures immediate durability and automatic leaseholder re-election in <3 seconds.

### Negative / Trade-Offs:
- Inter-account P2P transfers require multi-step Saga coordination and eventual consistency reconciliation within a 500ms window.
- Shard rebalancing during future expansions requires virtual node remapping.

## Compliance
- **RBI Data Localization Directive (2018):** All shards, backup replicas, and failover targets reside within the AWS `ap-south-1` (Mumbai) cluster.
- **Audit Compliance:** Double-entry ledger entries are partitioned across shards using the source account shard ID to ensure strict audit trace locality.