# Day 8: Concurrency Control, Isolation Levels & Write-Skew Prevention
**System:** PayScale High-Throughput Transaction Processing Engine (HTTPE)  
**Throughput Target:** 12,000+ Sustained TPS | Zero Double-Spending | Formal Correctness Proof  
**Author:** Software Engineering Intern  

---

## 1. Isolation Level Selection Across Subsystems

To balance ACID correctness with high throughput, SQL isolation levels are explicitly segregated:
+---------------------------------------------------------------------------------------------------+
| ISOLATION LEVEL SELECTION MATRIX                                                                  |
+---------------------+-------------------+---------------------+-----------------------------------+
| Subsystem Query     | Isolation Level   | Anomalies Prevented | Architectural Justification       |
+---------------------+-------------------+---------------------+-----------------------------------+
| Balance Debit/Credit| SERIALIZABLE      | All (Dirty, Non-rep,| Ensures strict conservation of    |
| & Ledger Entries    | (via OCC + Raft)  | Phantoms, Write-Skew| money; eliminates double-spending |
| Read Passbook Feed  | READ COMMITTED    | Dirty Reads         | High throughput history browsing  |
| Fraud Pre-Check     | REPEATABLE READ   | Dirty, Non-repeatable| Consistent snapshot of velocity   |
| Daily Reconciliation| SNAPSHOT ISOLATION| Dirty, Non-repeatable| Long-running analytical query     |
| & Batch Settlement  |                   | Phantoms            | without blocking live writes      |
+---------------------+-------------------+---------------------+-----------------------------------+


---

## 2. Formal Correctness Argument: Write-Skew Anomaly Elimination

### The Write-Skew Vulnerability:
Assume Account A has an available balance of 1,000 INR. The system constraint is:
$$\text{available\_balance} \ge 0$$

Two concurrent transactions ($T_1$ and $T_2$) arrive simultaneously:
- $T_1$ attempts to debit 800 INR.
- $T_2$ attempts to debit 600 INR.

Under standard Snapshot Isolation:
1. $T_1$ reads balance = 1,000 INR. Validates $1000 - 800 \ge 0$.
2. $T_2$ reads balance = 1,000 INR (same snapshot). Validates $1000 - 600 \ge 0$.
3. Both transactions commit their updates independently.
4. Resulting balance: $1000 - 800 - 600 = -400$ INR (Disastrous overdraft anomaly).

### Formal Proof of OCC Mitigation:
In PayScale HTTPE, every account row contains an atomic version counter $V \in \mathbb{N}$.

1. $T_1$ reads $(\text{balance}_0 = 1000, V_0 = 1)$.
2. $T_2$ reads $(\text{balance}_0 = 1000, V_0 = 1)$.
3. $T_1$ executes:
   $$\text{UPDATE accounts SET balance} = 200, V = 2 \text{ WHERE account\_id} = A \land V = 1 \land \text{balance} \ge 800;$$
   Since $V = 1$, the update succeeds. Rows affected = 1. Account state transitions to $(\text{balance}_1 = 200, V_1 = 2)$.
4. $T_2$ executes:
   $$\text{UPDATE accounts SET balance} = 400, V = 2 \text{ WHERE account\_id} = A \land V = 1 \land \text{balance} \ge 600;$$
   Because the database version is now $V = 2$, the predicate $V = 1$ evaluates to **FALSE**.
5. The database returns **Rows affected = 0**.
6. $T_2$ aborts and retries. During retry, it reads the updated state $(\text{balance} = 200, V = 2)$.
7. $T_2$ evaluates $200 < 600$ and safely rejects the transaction with `InsufficientFundsException`.

**Conclusion:** The version counter predicate converts non-overlapping concurrent writes into mutually exclusive serialization points, mathematically guaranteeing zero write-skew and eliminating double-spending anomalies.

---

## 3. Distributed Locking Strategy with Fencing Tokens

For coarse-grained batch operations (e.g., Merchant Cutoff Settlement or Account Freezing):

[ Client / Orchestrator ] ──(1. Acquire Lock)──> [ Redis Cluster (Redlock) ]
│
▼ (Returns Token: 1042)
[ Worker A (Token 1042) ] ──(GC Pause / Delay)──> [ Database Guard ]
│
[ Worker B (Token 1043) ] ──(Executes First)────> [ Validates Token >= Current ] -> Writes OK
│
[ Worker A Resumes ]      ──(Tries to Write)───> [ Token 1042 < 1043 ] -> REJECTED!


* **Monotonic Fencing Tokens:** Every distributed lock issued by Redis returns a monotonically increasing integer token (generated via `INCR lock:token:counter`).
* **Storage Guard:** CockroachDB checks `WHERE token > last_processed_token`.If an application thread pauses due to a long garbage collection (GC) pause and resumes after its lock expired, its stale token is rejected by the database, preventing split-brain corruption.