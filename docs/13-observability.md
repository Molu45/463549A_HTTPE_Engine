# Day 13: Observability, Distributed Tracing & Alerting Architecture
**System:** PayScale High-Throughput Transaction Processing Engine (HTTPE)  
**Throughput Target:** 12,000+ Sustained TPS | p99 < 100ms | 99.99% Availability SLA  
**Observability Stack:** Prometheus, Grafana, OpenTelemetry (OTel), Jaeger, Grafana Loki  
**Author:** Software Engineering Intern  

---

## 1. The Four Golden Signals (SRE Framework)

To guarantee end-to-end visibility across 12,000 sustained TPS, the engine instruments the four core golden signals at every layer:
+---------------------------------------------------------------------------------------------------------+
| FOUR GOLDEN SIGNALS INSTRUMENTATION MATRIX                                                              |
+-----------+-----------------------------------+--------------------+------------------------------------+
| Signal    | Metric Name                       | Target / Baseline  | Critical SLA Breach Threshold      |
+-----------+-----------------------------------+--------------------+------------------------------------+
| Latency   | http_request_duration_seconds     | p99 < 65ms         | p99 > 100ms for > 60 seconds       |
| Traffic   | http_requests_total (Rate)        | 12,000 TPS         | Drop > 40% (Traffic Cliff)         |
| Errors    | http_requests_total{status=~"5.."} | Error Rate < 0.01% | Error Rate > 0.1% for > 30 seconds |
| Saturation| container_cpu_usage_ratio         | 50% - 65%          | CPU > 85% or DB Conns > 90% Pool   |
+-----------+-----------------------------------+--------------------+------------------------------------+


---

## 2. P1–P4 Incident Classification & Alerting Matrix

+-------------------------------------------------------------------------------------------------------------+
| INCIDENT SEVERITY & RESPONSE RUNBOOK MATRIX                                                                 |
+----------+-------------------------------------+-----------------+---------------+--------------------------+
| Severity | Trigger Condition                   | Response SLA    | Notification  | Primary Runbook Action   |
+----------+-------------------------------------+-----------------+---------------+--------------------------+
| P1       | Overall API Error Rate > 2% OR      | < 5 minutes     | PagerDuty,    | 1. Auto-drain failing AZ |
|          | Database consensus unavailable      |                 | Phone Call,   | 2. Trip ingress shedder  |
|          | (Complete Outage / RPO risk)        |                 | War-Room Bot  | 3. Promote standby node  |
+----------+-------------------------------------+-----------------+---------------+--------------------------+
| P2       | p99 Latency > 100ms for > 2 mins OR | < 15 minutes    | PagerDuty SMS,| 1. Scale HPA pods +50%   |
|          | Kafka Consumer Lag > 10,000 msgs OR |                 | Slack #sre    | 2. Inspect slow queries  |
|          | Circuit breaker CB-FRAUD tripped    |                 |               | 3. Verify Redis latency  |
+----------+-------------------------------------+-----------------+---------------+--------------------------+
| P3       | Single pod crash-looping OR         | < 1 hour        | Slack Alerts, | 1. Review container logs |
|          | Cache miss rate increases > 15% OR  |                 | Email Digest  | 2. Inspect memory leaks  |
|          | Asynchronous webhook retry rate > 5%|                 |               | 3. Tune pod resource limits|
+----------+-------------------------------------+-----------------+---------------+--------------------------+
| P4       | Disk utilization > 75% on cold store| < 24 hours      | Jira Ticket,  | 1. Run partition drop job|
|          | Non-critical SSL cert expires < 30d |                 | Email Report  | 2. Rotate cert / secrets |
+----------+-------------------------------------+-----------------+---------------+--------------------------+


---

## 3. Distributed Tracing Strategy (OpenTelemetry & W3C Trace Context)

Because transactions cross multiple distributed boundaries (API Gateway -> Payment Pod -> Redis -> Kafka -> Saga Orchestrator -> CockroachDB Shards), distributed tracing is mandatory for root-cause isolation.

1. **W3C Trace Context Propagation:**
   - Every inbound payment request generates or preserves standard `traceparent` headers (`traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01`).
   - The trace ID is injected into HTTP headers, Kafka message metadata headers, and database session comments (`/* trace_id=... */`).
2. **Adaptive Head-Based Sampling:**
   - Standard successful transactions are sampled at 1% to minimize network and disk overhead.
   - All transactions resulting in HTTP 4xx, 5xx, circuit breaker trips, or latencies exceeding 80ms are forced to 100% trace capture (Tail-Based Sampling Rule).

---

## 4. Structured JSON Logging Standards (PCI-DSS Compliant)

All microservices emit structured single-line JSON logs to `stdout`, ingested by Vector/Fluentbit into Grafana Loki:

```json
{
  "timestamp": "2026-09-15T12:35:00.120Z",
  "level": "INFO",
  "service": "payment-processing-service",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "span_id": "00f067aa0ba902b7",
  "transaction_id": "018f2d5e-7a1b-789a-bcde-0123456789aa",
  "idempotency_key": "018f2d5e-7a1b-789a-bcde-0123456789ab",
  "action": "DEBIT_PROCESSED",
  "amount": 2500.00,
  "currency": "INR",
  "duration_ms": 14.2,
  "source_account_masked": "ACC-***-89aa",
  "status": "ACCEPTED"
}
PII & Cardholder Masking: Account numbers, phone numbers, and customer names are automatically masked (ACC-***-89aa) prior to logging to adhere to DPDP Act 2023 and PCI-DSS requirements.