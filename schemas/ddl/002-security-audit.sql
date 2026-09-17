-- PayScale High-Throughput Transaction Processing Engine (HTTPE)
-- Security, Compliance & Immutable Audit Log DDL Definitions

-- 1. Security Audit Trail (Cryptographically Chained)
CREATE TABLE security_audit_log (
    audit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_name VARCHAR(100) NOT NULL,
    entity_id UUID NOT NULL,
    action_type VARCHAR(50) NOT NULL CHECK (action_type IN ('INSERT', 'UPDATE', 'DELETE', 'ACCESS_PII', 'MANUAL_OVERRIDE')),
    performed_by VARCHAR(150) NOT NULL,
    source_ip VARCHAR(45) NOT NULL,
    prev_state_hash CHAR(64),
    curr_state_hash CHAR(64) NOT NULL,
    payload_snapshot JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_audit_entity ON security_audit_log(entity_name, entity_id);
CREATE INDEX idx_audit_created ON security_audit_log(created_at DESC);

-- 2. Encryption Key Rotation Metadata
CREATE TABLE security_key_rotations (
    key_id VARCHAR(100) PRIMARY KEY,
    key_version INTEGER NOT NULL,
    algorithm VARCHAR(50) NOT NULL DEFAULT 'AES-256-GCM',
    kms_key_arn VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL CHECK (status IN ('ACTIVE', 'RETIRED', 'REVOKED')),
    activated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    retired_at TIMESTAMPTZ
);

-- 3. Suspicious Activity Reports (SAR / AML Flagged Events)
CREATE TABLE suspicious_activity_logs (
    sar_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id UUID NOT NULL,
    account_id UUID NOT NULL,
    flag_type VARCHAR(100) NOT NULL CHECK (flag_type IN ('VELOCITY_BREACH', 'HIGH_VALUE_THRESHOLD', 'BLACKLIST_HIT', 'STRUCTURING_DETECTED')),
    risk_score NUMERIC(5, 2) NOT NULL,
    regulatory_reported BOOLEAN NOT NULL DEFAULT FALSE,
    reviewed_by VARCHAR(150),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_sar_account ON suspicious_activity_logs(account_id, created_at DESC);
CREATE INDEX idx_sar_unreported ON suspicious_activity_logs(regulatory_reported) WHERE regulatory_reported = FALSE;