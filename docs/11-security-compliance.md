# Day 11: Security Architecture, Compliance & Data Protection
**System:** PayScale High-Throughput Transaction Processing Engine (HTTPE)  
**Regulatory Directives:** RBI Data Localization (2018), DPDP Act 2023, PCI-DSS v4.0  
**Target Availability & Security:** Zero Data Leakage | End-to-End Encryption | 2-Year Retention  
**Author:** Software Engineering Intern  

---

## 1. Regulatory Compliance Framework

### 1.1 Reserve Bank of India (RBI) Data Localization Compliance
Under the RBI Directive on Storage of Payment System Data:
- **Domestic Territorial Boundary:** All end-to-end payment transaction processing data, consumer identifiers, card numbers, transaction logs, and ledger states must reside exclusively on domestic computing infrastructure.
- **Physical Datacenter Enforcement:** HTTPE compute nodes, CockroachDB storage ranges, Apache Kafka brokers, and Redis clusters are provisioned inside the AWS Mumbai region (`ap-south-1`) with a hot standby in AWS Hyderabad (`ap-south-2`).
- **Overseas Processing Boundaries:** No transaction data, telemetry payload, or backup snapshot crosses Indian geographical boundaries.

### 1.2 Digital Personal Data Protection (DPDP) Act 2023
- **Data Minimization:** APIs strictly redact sensitive PII (Personally Identifiable Information) before dispatching events to analytical or notification consumers.
- **Right to Erasure vs. Financial Auditability:** Non-financial user identifiers support pseudonymous anonymization upon account termination, while financial accounting ledgers remain permanently retained to satisfy statutory audit mandates.

---

## 2. Encryption Strategy: Data in Transit & Data at Rest
+-------------------------------------------------------------------------------------------------+
| ENCRYPTION ARCHITECTURE SPECIFICATION                                                           |
+---------------------+-------------------+---------------------+---------------------------------+
| Layer Boundary      | Encryption Method | Key Management      | Protocol / Standard             |
+---------------------+-------------------+---------------------+---------------------------------+
| Client -> Gateway   | TLS 1.3 Strict    | Automated Let's     | ECDHE-RSA-AES256-GCM-SHA384     |
|                     |                   | Encrypt / AWS ACM   | (Zero TLS 1.0/1.1/1.2 fallback) |
| Inter-Service Mesh  | Mutual TLS (mTLS) | HashiCorp Vault CA  | SPIFFE / SPIRE x509 SVIDs       |
| Database at Rest    | AES-256-GCM       | AWS KMS / Envelope  | Automated 90-day key rotation   |
| Field-Level (PII)   | AES-256 (TINK)    | Application Master  | Deterministic & Random AES-GCM  |
| Event Bus at Rest   | EBS Volume Crypto | Customer Managed    | AWS KMS KMS-CMK-KAFKA-MUMBAI    |
+---------------------+-------------------+---------------------+---------------------------------+


### Field-Level Sensitive Data Encryption (Envelope Encryption):
Critical columns such as `phone_number`, `national_id_hash`, and banking account numbers are encrypted at the Go application runtime layer using Google Tink before persisting to CockroachDB:
$$\text{Ciphertext} = \text{AES-GCM-256}(\text{Plaintext}, \text{DEK})$$
Data Encryption Keys (DEKs) are dynamically retrieved from HashiCorp Vault using an encrypted Master Key (KEK) and cached in memory with a 60-minute rotation lifecycle.

---

## 3. Role-Based Access Control (RBAC) Matrix

To observe the Principle of Least Privilege across human operators and machine microservice identities:

+-------------------------------------------------------------------------------------------------+
| RBAC ACCESS CONTROL MATRIX                                                                      |
+-----------------------+------------------+------------------+------------------+----------------+
| Role / Principal      | Accounts & Bal.  | Transactions     | Ledger Entries   | Admin / Infra  |
+-----------------------+------------------+------------------+------------------+----------------+
| Payment Service Pod   | Read / Update    | Create / Read    | Create (Append)  | None           |
| Saga Orchestrator     | Read / Update    | Read / Update    | Create (Append)  | None           |
| Reconciliation Worker | Read Only        | Read Only        | Read Only        | None           |
| Audit Compliance Svc  | Read Only        | Read Only        | Read (Immutable) | Export Vault   |
| Support Engineering   | Masked Read (PII)| Masked Read (PII)| No Access        | No Access      |
| SecOps / SRE Admin    | No Direct Data   | No Direct Data   | No Direct Data   | Cluster Config |
+-----------------------+------------------+------------------+------------------+----------------+


---

## 4. Immutable Audit Trail & WORM Storage

1. **Tamper-Evident Ledger Integrity:** Every balance change triggers an immutable row in `security_audit_log` with an SHA-256 HMAC signature linking each entry to the preceding transaction hash (cryptographic hash chain).
2. **WORM Storage Architecture:** Audit events older than 48 hours are automatically batched into Parquet archives and streamed to an AWS S3 bucket with **S3 Object Lock enabled in Compliance Mode**.
3. **Immutability Guarantee:** Once locked in Compliance Mode, no user—including the AWS account root user—can overwrite or delete transaction history for the mandatory 2-year statutory retention period.
