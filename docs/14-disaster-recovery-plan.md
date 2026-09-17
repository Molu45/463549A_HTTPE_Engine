# Day 14: Disaster Recovery & Business Continuity Plan (DRP)
**System:** PayScale High-Throughput Transaction Processing Engine (HTTPE)  
**Regulatory Directives:** RBI Cyber Security Framework & Master Direction on Operational Resilience  
**Key Recovery Targets:** RTO < 30 Seconds | RPO = 0 (Zero Financial Data Loss) | Availability: 99.99%  
**Author:** Software Engineering Intern  

---

## 1. Disaster Recovery Topology & Recovery Objectives
+---------------------------------------------------------------------------------------------------------+
| RECOVERY TARGETS & TIERS                                                                                |
+---------------------+-------------------------------+---------------------------------------------------+
| Metric              | SLA Commitment                | Architectural Enforcement Mechanism               |
+---------------------+-------------------------------+---------------------------------------------------+
| Recovery Point (RPO)| RPO = 0 (Strict Zero Loss)   | Multi-AZ Raft Synchronous Replication + Kafka acks=all |
| Recovery Time (RTO) | RTO < 30 Seconds              | Automated Raft Leader Election (<3s) + Health Drains|
| Primary Datacenter  | AWS Mumbai (ap-south-1)       | 3 Availability Zones (AZ-1, AZ-2, AZ-3)           |
| Secondary DR Region | AWS Hyderabad (ap-south-2)    | Warm standby asynchronous replication (RBI compliant)|
+---------------------+-------------------------------+---------------------------------------------------+


---

## 2. Multi-Zone High Availability & Regional Failover Architecture

### 2.1 Intra-Region Multi-AZ Failover (Primary Defense)
- **Database (CockroachDB):** 12 nodes deployed evenly (4 nodes per AZ across 3 AZs in `ap-south-1`). Each data range holds 3 replicas. Sudden total destruction of an entire AZ leaves 2/3 replicas alive, maintaining synchronous Raft quorum without dropping in-flight transactional commits ($RPO = 0$).
- **Message Bus (Apache Kafka):** 3-broker cluster with `min.insync.replicas=2` and `replication.factor=3`. A single AZ loss does not halt partition ingestion.
- **Compute (EKS Pods):** Kubernetes Pod Anti-Affinity guarantees Payment Service pods are evenly spread across AZs. If AZ-1 fails, AWS ALB automatically removes dead nodes within 5 seconds.

### 2.2 Inter-Region Disaster Recovery (Catastrophic Defense)
- In the event of catastrophic regional network blackouts across western India (Mumbai), a warm standby cluster in AWS Hyderabad (`ap-south-2`) is activated.
- **Asynchronous Data Replication:** CockroachDB Change Data Capture (CDC) streams encrypted transaction batches to Hyderabad read-replicas with a bounded latency lag of $< 1000\text{ms}$.
- **Failover SLA:** DNS cutover via AWS Route 53 Application Recovery Controller (ARC) executes within 120 seconds.

---

## 3. Automated Backup Cadence & Vault Immutability

+-------------------------------------------------------------------------------------------------+
| BACKUP CADENCE SPECIFICATION                                                                    |
+---------------------+--------------------+--------------------+---------------------------------+
| Data Subsystem      | Backup Frequency   | Retention Period   | Storage Target & Encryption     |
+---------------------+--------------------+--------------------+---------------------------------+
| CockroachDB Hot WAL | Continuous Stream  | 7 Days             | Dedicated S3 NVMe Bucket (AES-256|
| CockroachDB Full    | Daily at 02:00 IST | 90 Days            | AWS S3 Standard (Vault Lock)    |
| Audit Ledger Vault  | Real-Time Append   | 730 Days (2 Years) | AWS S3 Glacier (WORM Mode)      |
| Kafka Topic State   | Daily Snapshot     | 30 Days            | S3 Encrypted Snapshot           |
| Redis Cluster Dump  | Hourly Snapshot    | 24 Hours           | Ephemeral S3 Storage            |
+---------------------+--------------------+--------------------+---------------------------------+


---

## 4. Disaster Recovery Runbooks (Operational Step-by-Step)

### Runbook RB-01: AZ-1 Outage Incident
1. **Detection:** Prometheus triggers alert `CockroachDBNodeDown` (4 nodes down simultaneously in AZ-1).
2. **Automated Quorum Verification:** Raft clusters in AZ-2 and AZ-3 elect new range leaseholders within 1.5 seconds.
3. **Ingress Rerouting:** AWS Network Load Balancer marks AZ-1 health targets failed; drops ingress traffic to AZ-1 within 5 seconds.
4. **Auto-Remediation:** Kubernetes Cluster Autoscaler spins up 16 replacement Payment Service pods in AZ-2 and AZ-3.
5. **Operator Check:** Verify Grafana dashboard golden signals; confirm p99 returns $< 100\text{ms}$.

### Runbook RB-02: Total Regional Failover to Hyderabad
1. **Trigger Condition:** Unrecoverable failure of AWS `ap-south-1` confirmed by AWS status dashboard and internal monitoring.
2. **Authorization:** P1 incident commander and Chief Technology Officer (CTO) issue mutual authorization token.
3. **Routing Transition:** Execute Route 53 ARC routing control flip (`aws route53-recovery-control-config update-routing-control-states --states ...`).
4. **Database Promotion:** Promote Hyderabad CockroachDB standby cluster to standalone primary read-write cluster.
5. **Kafka Activation:** Enable producers on Hyderabad Kafka cluster; resumetransaction ingestion.