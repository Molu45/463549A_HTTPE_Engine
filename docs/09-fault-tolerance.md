# Day 9: Fault Tolerance, Circuit Breaker & Chaos Engineering Specifications
**System:** PayScale High-Throughput Transaction Processing Engine (HTTPE)  
**Availability Target:** 99.99% Uptime (Max 52.6 min downtime/yr) | RTO < 30s | RPO = 0  
**Author:** Software Engineering Intern  

---

## 1. Circuit Breaker Configurations & Fallback Topology

Circuit breakers isolate degrading downstream dependencies, preventing thread starvation in the payment pipeline:
+---------------------------------------------------------------------------------------------------------+
| PRODUCTION CIRCUIT BREAKER INSTANCES                                                                    |
+---------------+---------------------+-------------------+---------------+-------------------------------+
| Identifier    | Protected Subsystem | Failure Threshold | Reset Timeout | Production Fallback Behavior  |
+---------------+---------------------+-------------------+---------------+-------------------------------+
| CB-FRAUD      | Fraud Engine (gRPC) | 3 failures / 10s  | 15 seconds    | Allow with async review flag  |
| CB-NOTIFY     | Notification / SMS  | 5 failures / 30s  | 60 seconds    | Queue to retry table; proceed |
| CB-DB-PRIMARY | CockroachDB Master  | 2 failures / 5s   | 10 seconds    | Route reads to replica; pause |
| CB-DB-REPLICA | Read Replicas       | 5 failures / 10s  | 30 seconds    | Route reads to primary pool   |
| CB-CACHE      | Redis Cluster       | 3 failures / 5s   | 20 seconds    | Bypass cache; direct DB read  |
| CB-SETTLEMENT | Banking Host Switch | 2 failures / 5s   | 60 seconds    | Queue for next batch cycle    |
+---------------+---------------------+-------------------+---------------+-------------------------------+


---

## 2. Bulkhead Resource Isolation

To guarantee that background operations or batch jobs never deplete resources required for immediate P2P payments:

+-------------------------------------------------------------------------------------------------+
| BULKHEAD RESOURCE ALLOCATION MATRIX                                                             |
+--------------------------+--------------------+------------------------+------------------------+
| Workload Pool            | Dedicated Workers  | Dedicated DB Conns     | Max Queue Capacity     |
+--------------------------+--------------------+------------------------+------------------------+
| P2P Real-Time Payments   | 32 Pods (Primary)  | 1,200 Active Conns     | 5,000 requests         |
| Merchant Batch Settlement| 8 Pods (Isolated)  | 200 Active Conns       | 100,000 records        |
| Passbook / Balance Query | 12 Pods (Stateless)| 400 Replica Conns      | 2,000 requests         |
| Audit & Regulatory Export| 4 Pods (Batch)     | 100 Read-Only Conns    | 1,000 export jobs      |
+--------------------------+--------------------+------------------------+------------------------+


---

## 3. Tiered Retry Policies with Exponential Jitter

1. **Transient Network Errors:** Retried automatically up to 3 attempts using truncated exponential backoff with full jitter:
   $$T_{\text{sleep}} = \min\left(T_{\text{max}},\, T_{\text{base}} \times 2^{\text{attempt}}\right) \times \text{random}(0, 1)$$
2. **Deterministic Business Errors (e.g., Insufficient Funds):** Zero retries. Fails immediately to preserve compute capacity.
3. **Kafka Ingestion Retries:** Bounded at 5 retries with monotonic sequence verification before pushing to Dead Letter Queue (DLQ).

---

## 4. Production Chaos Engineering Experiments (5 Core Scenarios)

### CE-001: Primary Database Leaseholder Termination
* **Hypothesis:** Loss of a CockroachDB primary leaseholder node causes zero committed transaction loss and triggers Raft leader re-election within 3 seconds.
* **Blast Radius:** 1 Database Node in AZ-1 (1/12th of cluster).
* **Injection Method:** `kill -9` CockroachDB process on leaseholder during 12,000 TPS load test.
* **Success Criteria:** RPO = 0; RTO < 30 seconds; p99 latency spikes return under 100ms within 15 seconds.
* **Rollback:** Automated Docker/Kubernetes container restart via StatefulSet.

### CE-002: 500ms Synthetic Network Latency to Kafka Cluster
* **Hypothesis:** Upstream Transactional Outbox buffers events without user-facing request drops; consumer lag absorbs temporary spike.
* **Blast Radius:** Ingress communication link between Payment pods and Kafka Broker 1.
* **Injection Method:** `tc qdisc add dev eth0 root netem delay 500ms` on Broker 1.
* **Success Criteria:** Zero message loss; Producer buffers to local disk queue; Kafka consumer lag clears within 2 minutes of removal.
* **Rollback:** `tc qdisc del dev eth0 root`.

### CE-003: Redis Cluster Node Eviction & Memory Saturation
* **Hypothesis:** Single cache node eviction causes temporary cache misses, but PgBouncer connection limits prevent primary database collapse.
* **Blast Radius:** Redis Master Node 1 (16GB partition).
* **Injection Method:** Execute memory saturation script consuming 100% of maxmemory.
* **Success Criteria:** Sentinel initiates replica promotion within 2 seconds; DB connection pool does not exceed 80% saturation; p99 < 200ms during recovery.
* **Rollback:** Flush synthetic keys and restart Redis pod.

### CE-004: Sudden Loss of 50% Payment Service Compute Pods
* **Hypothesis:** Remaining 50% pods handle ingress queueing while Kubernetes Horizontal Pod Autoscaler (HPA) provisions replacement pods within 90 seconds.
* **Blast Radius:** 16 out of 32 active Payment Worker pods.
* **Injection Method:** `kubectl delete pods -l app=payment-service --grace-period=0` (50% sample).
* **Success Criteria:** User-facing HTTP 5xx error rate stays strictly under 2%; full capacity restored within 90 seconds.
* **Rollback:** Kubernetes ReplicaSet controller restores pods automatically.

### CE-005: 5-Second Clock Skew Between Microservices
* **Hypothesis:** OCC version vectors and monotonic fencing tokens prevent double-spending anomalies despite un-synchronized system clocks.
* **Blast Radius:** Worker Pod Pool B.
* **Injection Method:** Synthetically adjust local container system time forward by +5,000ms using libfaketime.
* **Success Criteria:** Zero duplicate balance debits; transactions evaluate based on monotonic integer version rather than timestamp comparison.
* **Rollback:** Unset libfaketime hook and resync NTP daemon.