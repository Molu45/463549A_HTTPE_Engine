# ADR-004: Hybrid Communication Pattern for High-Throughput Ingress & Processing

## Status
Accepted

## Context
PayScale's transaction engine must handle 12,000 sustained TPS with a strict end-to-end p99 latency budget of <100ms. In a purely synchronous REST-based microservices architecture, a single P2P payment would require chained HTTP calls across the API Gateway, Fraud Service, Account Service, Ledger Service, and Notification Service. Chained synchronous I/O introduces tight operational coupling, compounding latency (where aggregate p99 is the sum of all downstream latencies), and risks catastrophic thread-pool exhaustion during downstream service degradation. Conversely, a purely asynchronous model prevents returning immediate deterministic authorization acknowledgments to end-user clients.

## Decision
We implement a **Hybrid Synchronous Ingress / Asynchronous Event-Driven Processing Architecture**.

### Structural Breakdown:
- **Synchronous Critical Path (Ingress & Pre-Flight):** Client to API Gateway, Redis Idempotency verification, and Pre-Authorization Fraud evaluation operate synchronously via HTTP/2 and gRPC with a strict SLA budget bounded at 25ms.
- **Asynchronous Execution Path (Processing & Persistence):** As soon as pre-flight checks pass, the transaction event is published to Apache Kafka via an atomic transactional outbox pattern. The client receives an immediate `202 Accepted` response with an immutable tracking identifier (`txn_id`).
- **Asynchronous Downstream Subsystems:** Saga orchestration, multi-shard ledger balance mutations, merchant fee computations, compliance audit logging, and external customer notifications are handled entirely asynchronously by partitioned Kafka consumer groups.

## Alternatives Considered

### 1. Purely Synchronous Microservices (Chained REST/gRPC)
- *Pros:* Simpler mental model; single linear call stack.
- *Cons:* Severe latency cascade; if the Notification or Audit service experiences a 500ms lag, worker threads across the upstream Payment Service block, causing 40% request timeouts (as observed in Bottleneck BN-003).

### 2. Purely Asynchronous Messaging (Fire-and-Forget Ingress)
- *Pros:* Maximum ingress throughput decoupling.
- *Cons:* Inability to return immediate client-side validation errors (e.g., malformed payloads, rate-limit violations, or obvious fraud blocks), causing poor user experience and unbounded message queues filled with invalid requests.

## Consequences
### Positive Outcomes:
- **Strict Latency Isolation:** The synchronous customer path terminates in <25ms, well within the 100ms p99 SLA.
- **Resilience to Downstream Outages:** If the downstream Ledger or Notification databases suffer degradation, inbound transactions are buffered safely on Kafka's append-only log without dropping client traffic.
- **Independent Elasticity:** Ingress API pods and backend persistence workers scale independently according to traffic type.

### Negative / Trade-Offs:
- Clients must use WebSocket connections or polling hooks to receive real-time terminal settlement updates.
- Requires robust distributed tracing (OpenTelemetry W3C trace contexts injected into Kafka headers) to trace end-to-end transaction lifecycles.

## Compliance
- **RBI Data Integrity Mandates:** Decoupled Kafka events combined with the Transactional Outbox pattern guarantee that financial events are committed to disk before returning success, preventing phantom transaction losses.