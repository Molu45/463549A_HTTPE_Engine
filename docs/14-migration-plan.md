# Day 14: Zero-Downtime Migration Plan (Strangler Fig Pattern)
**System:** PayScale High-Throughput Transaction Processing Engine (HTTPE)  
**Migration Strategy:** Strangler Fig Application Pattern + Dual-Write CDC + Shadow Traffic Validation  
**Target Downtime:** 0 Minutes (Zero Scheduled Maintenance Window)  
**Author:** Software Engineering Intern  

---

## 1. Migration Architecture & Phase Breakdown

The transition from the legacy monolithic system (Single PostgreSQL 15 + RabbitMQ) to the new distributed architecture (CockroachDB + Apache Kafka) executes across four isolated phases over a 6-week window:
[ Phase 1: Dual-Write & CDC ] ──> [ Phase 2: Shadow Traffic ] ──> [ Phase 3: Canary Cutover ] ──> [ Phase 4: Monolith Retirement ]


---

## 2. Phase-by-Phase Execution Protocol

### Phase 1: Historical Data Ingestion & Continuous CDC Replication (Weeks 1-2)
1. **Historical Snapshot Export:** A consistent read snapshot of all user accounts and balances is extracted from the legacy PostgreSQL database using `pg_dump` with `--serializable-deferrable`.
2. **Bulk Ingestion:** The dataset is bulk loaded into CockroachDB shards using parallel `IMPORT INTO` pipelines.
3. **Live CDC Synchronization:** A Debezium Change Data Capture (CDC) pipeline captures all subsequent updates in legacy PostgreSQL WAL and replicates them into CockroachDB with sub-500ms lag.

### Phase 2: Dual-Writing & Shadow Traffic Verification (Weeks 3-4)
1. **Gateway Dual-Write Ingress:** The Kong API Gateway is configured with a traffic-mirroring plugin (`proxy-mirror`).
2. **Execution:** 100% of live production transaction traffic hits the legacy application (primary authority) and is simultaneously duplicated asynchronously to the new HTTPE engine (shadow execution).
3. **Automated Reconciliation Diff:** A reconciliation worker compares responses from both engines:
   - Verifies debit/credit balance outcomes match down to 4 decimal places.
   - Evaluates latency profiles (confirming new engine achieves p99 < 100ms vs legacy 1.2s).
   - Zero discrepancy threshold required for 14 continuous days.

### Phase 3: Canary Traffic Routing & Progressive Cutover (Week 5)
Traffic is progressively shifted to make HTTPE the primary system of record:
- **Canary Stage 1 (Day 1):** 5% of low-risk P2P wallet transfers routed to HTTPE.
- **Canary Stage 2 (Day 3):** 25% of all retail transactions shifted. Reverse-CDC feeds legacy PostgreSQL to ensure rollback capability.
- **Canary Stage 3 (Day 5):** 75% of total payment volume shifted.
- **Canary Stage 4 (Day 7):** 100% of payment and merchant settlement traffic shifted to HTTPE.

### Phase 4: Monolith Retirement & Legacy Decommissioning (Week 6)
1. Disable reverse-CDC synchronization.
2. Terminate legacy RabbitMQ message brokers and drain residual queues.
3. Take final cold snapshot of legacy PostgreSQL database and archive to S3 Glacier WORM.
4. Decommission legacy compute instances, achieving full operational cost savings.

---

## 3. Rollback & Emergency Abort Criteria

A rollback to the legacy system can be executed within $< 60\text{ seconds}$ at any point during Phase 3 if any of the following triggers occur:
1. P2P transaction error rate on HTTPE exceeds $0.1\%$ for $> 60\text{ seconds}$.
2. A single financial balance mismatch is detected between ledger entries and account balances.
3. p99 transaction latency exceeds $150\text{ms}$ under peak loads.

**Rollback Action:** The Kong Gateway canary routing weight is instantlyflipped to $100\%$ legacy with zero database corruption, enabled by the continuous reverse-CDC pipeline.