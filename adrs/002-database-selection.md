# ADR-001: Selection of Apache Kafka as Primary Event Streaming Broker

## Status
Accepted

## Context
PayScale Financial Technologies requires a messaging infrastructure capable of sustaining 12,000 transactions per second with peak bursts of 18,000 TPS. The existing single-node RabbitMQ message broker collapsed under load testing at 2,000 TPS, generating consumer acknowledgment backlogs exceeding 30 seconds and inducing thread pool timeouts across downstream payment workers. The messaging layer must enforce strict partition-level message ordering (per account), support consumer replayability, ensure durable zero-data-loss commit guarantees, and comply with RBI data localization constraints within an aggregate $45,000/month infrastructure budget.

## Decision
We select **Apache Kafka (version 3.7+ running KRaft mode)** deployed in a 3-broker multi-AZ cluster inside the AWS Mumbai (`ap-south-1`) region.

### Topology and Configuration:
- **Cluster Size:** 3 brokers running on `m6i.2xlarge` compute instances (8 vCPUs, 32 GB RAM per node).
- **Consensus:** KRaft metadata quorum eliminating external Apache ZooKeeper dependencies.
- **Replication & Durability:** 
  - `replication.factor=3`
  - `min.insync.replicas=2`
  - `acks=all` on transactional payment producers.
- **Partitioning Strategy:** Topics are partitioned by `hash(account_id)` across 36 partitions to guarantee sequential transaction ordering for any single account while distributing horizontal load equally across consumer worker pools.
- **Storage:** Dedicated io2 Block Express volumes delivering 20,000 IOPS with log retention capped at 7 days for transaction topics.

## Alternatives Considered

### 1. RabbitMQ (Clustered with Quorum Queues)
- *Pros:* Rich AMQP routing keys, low latency under moderate load, existing team familiarity.
- *Cons:* Quorum queues experience steep RAM and CPU consumption beyond 3,500 TPS. Lacks native partitioned horizontal consumer distribution and append-only disk efficiency, leading to broker choke points.

### 2. AWS SQS FIFO
- *Pros:* Fully managed serverless model, zero cluster management overhead.
- *Cons:* Hard throughput limit of 3,000 TPS (with 10-message batching) per FIFO queue. Extremely cost-prohibitive at 85 million transactions per day (exceeding $18,000/month solely in API polling costs).

## Consequences
### Positive Outcomes:
- Linear horizontal scalability: Adding partitions and consumers directly increases processing throughput without cluster reconfiguration.
- Zero data loss: `min.insync.replicas=2` guarantees committed transactions survive an entire Availability Zone outage.
- Replayability: Enables financial event-sourcing and audit verification by rewinding consumer offsets.

### Negative / Trade-Offs:
- Higher operational learning curve compared to standard message queues.
- Client applications must implement the Outbox Pattern or transactional producers to prevent duplicate messages.

## Compliance
- **RBI Data Localization:** All Kafka brokers, persistent block volumes, and replication channels reside exclusively within AWS Mumbai (`ap-south-1`).
- **PCI-DSS:** Inter-broker communication and client connections enforce TLS 1.3 encryption with SASL/SCRAM authentication.