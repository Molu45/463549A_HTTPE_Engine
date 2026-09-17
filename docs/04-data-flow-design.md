# Day 4: Critical Data Flow Design & Sequence Specifications
**Target Throughput:** 12,000+ Sustained TPS | End-to-End p99 < 100ms  
**Author:** Software Engineering Intern  

---

## 1. Asynchronous vs. Synchronous Communication Demarcation

To process 12,000 TPS under a 100ms p99 budget, network paths are strictly separated:

+-------------------------------------------------------------------------------------------------+
| COMMUNICATION PATH SEPARATION                                                                   |
+----------------------+-------------+--------------------+---------------------------------------+
| Subsystem Flow       | Mode        | Protocol           | SLA / Timeout Budget                  |
+----------------------+-------------+--------------------+---------------------------------------+
| API Gateway -> Ingress| Synchronous | HTTPS (TLS 1.3)    | 3 - 5 ms                              |
| Idempotency Check    | Synchronous | Redis RESP (Local) | 1 - 2 ms                              |
| Pre-Auth Fraud Check | Synchronous | Internal gRPC      | 15 ms (Bounded by CB-FRAUD)           |
| Message Publishing   | Asynchronous| Kafka Producer     | 2 - 5 ms (Outbox Buffer)              |
| Saga Orchestration   | Asynchronous| Kafka Consumer     | Continuous (Batch commits)            |
| Sharded Ledger Write | Synchronous | PostgreSQL Wire    | 8 - 15 ms (CockroachDB Raft quorum)   |
| External Webhooks    | Asynchronous| HTTPS Push (Worker)| Background (Decoupled from user path) |
+----------------------+-------------+--------------------+---------------------------------------+


---

## 2. P2P Payment Transaction Flow (Narrative)

### 2.1 Happy Path
1. **Ingress:** Client submits a payment request with a client-generated UUIDv7 `Idempotency-Key`. The Kong API Gateway performs TLS termination, JWT validation, and verifies token-bucket rate limits per user tier.
2. **Idempotency Acquisition:** The Payment Processing Service executes an atomic `SET key "PROCESSING" NX EX 86400` in Redis Cluster[cite: 1].
3. **Synchronous Fraud Evaluation:** A gRPC request queries the Fraud Engine. If velocity checks and model evaluations complete within 15ms without violation, execution proceeds[cite: 1].
4. **Decoupling Event Production:** Payment Service produces a `txn.initiated` event to Apache Kafka partitioned by `hash(source_account_id)` with `acks=all`[cite: 1]. The client receives an immediate `202 Accepted` response with the `txn_id`[cite: 1].
5. **Orchestration & Ledger Debit:** The Saga Orchestrator consumes the event and issues an OCC SQL update:
   `UPDATE accounts SET available_balance = available_balance - :amt, version = version + 1 WHERE account_id = :src AND version = :cur_ver AND available_balance >= :amt;`[cite: 1]
6. **Credit & Double-Entry Post:** Upon successful debit, the destination account balance is incremented and two balanced rows are inserted into `ledger_entries`[cite: 1]. Kafka emits `txn.completed` to trigger notification workers[cite: 1].

### 2.2 Failure Scenarios & Compensation Logic
- **Scenario A: Insufficient Funds / Version Skew:**
  If the debit query returns zero affected rows, the transaction aborts immediately. Redis idempotency status updates to `FAILED_INSUFFICIENT_FUNDS`. A `txn.failed` event is emitted. No money is debited[cite: 1].
- **Scenario B: Fraud Engine Timeout (>15ms):**
  The `CB-FRAUD` circuit breaker trips after 3 consecutive timeouts, falling back to heuristic rule checks and queuing the transaction for post-processing manual fraud review without blocking authorization[cite: 1].
- **Scenario C: Destination Credit Failure (Partial Failure):**
  If the source debit succeeds but the destination shard is unavailable or account is frozen, the Orchestrator initiates compensating transaction:
  `UPDATE accounts SET available_balance = available_balance + :amt, version = version + 1 WHERE account_id = :src;`[cite: 1]
  This guarantees automatic reversal within the 30-second SLA[cite: 1].

---

## 3. Batch Merchant Settlement Data Flow

1. Scheduled every 24 hours (or on-demand during cutoff windows), the Settlement Service acquires a distributed lock in Redis (`lock:settlement:batch`) to prevent duplicate runs[cite: 1].
2. It queries up to 100,000 eligible completed merchant transactions from CockroachDB using cursor-based pagination[cite: 1].
3. Transactions are aggregated per merchant, netting fees (MDR) and tax deductions (TDS).
4. Payout chunks (1,000 txns each) are dispatched to partner banking gateways via ISO 8583 switches[cite: 1].
5. Upon receiving the interbank UTR (Unique Transaction Reference), double-entry records move funds from the internal Settlement Escrow pool to the Merchant Settlement account[cite: 1].

---

## 4. System Failover Flow & Zero-Data-Loss Guarantees

1. CockroachDB nodes maintain Raft consensus groups across three Availability Zones (AZ-1, AZ-2, AZ-3)[cite: 1].
2. If the primary leaseholder in AZ-1 dies, follower nodes in AZ-2 and AZ-3 detect missing heartbeats within 1.5 seconds[cite: 1].
3. A Raft leader election promotes a follower node to leaseholder in <3 seconds[cite: 1].
4. PgBouncer detects the severed socket, drains failed connections, and reroutes queries to the healthy leaseholder node within 5 seconds[cite: 1].
5. In-flight uncommitted transactions receive an error and auto-retry with exponential backoff; committed transactions remain durable (RTO < 30s, RPO = 0)[cite: 1].