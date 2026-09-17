-- PayScale High-Throughput Transaction Processing Engine (HTTPE)
-- Complete Production DDL Schema Definition (PostgreSQL 16 / CockroachDB)

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Users Entity
CREATE TABLE users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    phone_number VARCHAR(20) NOT NULL UNIQUE,
    kyc_status VARCHAR(50) NOT NULL DEFAULT 'PENDING' CHECK (kyc_status IN ('PENDING', 'VERIFIED', 'REJECTED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 2. Accounts Entity (Sharded & Versioned for OCC)
CREATE TABLE accounts (
    account_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    account_type VARCHAR(50) NOT NULL CHECK (account_type IN ('SAVINGS', 'CURRENT', 'WALLET', 'MERCHANT', 'SETTLEMENT_POOL')),
    currency CHAR(3) NOT NULL DEFAULT 'INR',
    available_balance NUMERIC(18, 4) NOT NULL DEFAULT 0.0000 CHECK (available_balance >= 0),
    ledger_balance NUMERIC(18, 4) NOT NULL DEFAULT 0.0000,
    version BIGINT NOT NULL DEFAULT 1,
    status VARCHAR(50) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'FROZEN', 'SUSPENDED', 'CLOSED')),
    tier VARCHAR(50) NOT NULL DEFAULT 'BASIC' CHECK (tier IN ('BASIC', 'PREMIUM', 'MERCHANT')),
    shard_key INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_accounts_shard_routing ON accounts(shard_key, account_id);
CREATE INDEX idx_accounts_user_lookup ON accounts(user_id);

-- 3. Transactions Entity (Partitioned by Month)
CREATE TABLE transactions (
    transaction_id UUID NOT NULL DEFAULT gen_random_uuid(),
    idempotency_key VARCHAR(128) NOT NULL,
    transaction_type VARCHAR(50) NOT NULL CHECK (transaction_type IN ('P2P', 'MERCHANT_PAYMENT', 'SETTLEMENT', 'REVERSAL', 'FEE')),
    source_account_id UUID REFERENCES accounts(account_id),
    destination_account_id UUID REFERENCES accounts(account_id),
    amount NUMERIC(18, 4) NOT NULL CHECK (amount > 0),
    status VARCHAR(50) NOT NULL CHECK (status IN ('INITIATED', 'PROCESSING', 'COMPLETED', 'FAILED', 'REVERSED')),
    saga_id UUID NOT NULL,
    failure_reason VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}',
    PRIMARY KEY (transaction_id, created_at)
) PARTITION BY RANGE (created_at);

CREATE UNIQUE INDEX idx_txn_idempotency_created ON transactions(idempotency_key, created_at);
CREATE INDEX idx_txn_saga ON transactions(saga_id);
CREATE INDEX idx_txn_source_history ON transactions(source_account_id, created_at DESC);
CREATE INDEX idx_txn_dest_history ON transactions(destination_account_id, created_at DESC);

-- 4. Ledger Entries Entity (Strict Double-Entry Bookkeeping)
CREATE TABLE ledger_entries (
    entry_id UUID NOT NULL DEFAULT gen_random_uuid(),
    transaction_id UUID NOT NULL,
    account_id UUID NOT NULL REFERENCES accounts(account_id),
    entry_type VARCHAR(20) NOT NULL CHECK (entry_type IN ('DEBIT', 'CREDIT')),
    amount NUMERIC(18, 4) NOT NULL CHECK (amount > 0),
    balance_after NUMERIC(18, 4) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (entry_id, created_at)
) PARTITION BY RANGE (created_at);

CREATE INDEX idx_ledger_account_time ON ledger_entries(account_id, created_at DESC);
CREATE INDEX idx_ledger_txn ON ledger_entries(transaction_id);

-- 5. Transaction Events Entity (Saga State Logging)
CREATE TABLE transaction_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id UUID NOT NULL,
    saga_id UUID NOT NULL,
    from_state VARCHAR(50) NOT NULL,
    to_state VARCHAR(50) NOT NULL,
    payload JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_events_saga ON transaction_events(saga_id, created_at);

-- 6. Fraud Rules Entity
CREATE TABLE fraud_rules (
    rule_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_name VARCHAR(100) NOT NULL,
    rule_type VARCHAR(50) NOT NULL,
    threshold_value NUMERIC(18, 4) NOT NULL,
    action VARCHAR(50) NOT NULL CHECK (action IN ('ALLOW', 'FLAG_MANUAL_REVIEW', 'BLOCK')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 7. Merchant Settlements Entity
CREATE TABLE merchant_settlements (
    settlement_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_account_id UUID NOT NULL REFERENCES accounts(account_id),
    batch_id UUID NOT NULL,
    gross_amount NUMERIC(18, 4) NOT NULL CHECK (gross_amount >= 0),
    mdr_fee NUMERIC(18, 4) NOT NULL DEFAULT 0.0000,
    net_amount NUMERIC(18, 4) NOT NULL CHECK (net_amount >= 0),
    status VARCHAR(50) NOT NULL CHECK (status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')),
    bank_utr VARCHAR(100),
    settled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_settlement_merchant ON merchant_settlements(merchant_account_id, created_at DESC);
CREATE INDEX idx_settlement_batch ON merchant_settlements(batch_id);

-- 8. Notification Log Entity
CREATE TABLE notification_log (
    notification_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id UUID NOT NULL,
    recipient_id UUID NOT NULL,
    channel VARCHAR(20) NOT NULL CHECK (channel IN ('SMS', 'PUSH', 'WEBHOOK', 'EMAIL')),
    status VARCHAR(50) NOT NULL CHECK (status IN ('QUEUED', 'SENT', 'FAILED', 'RETRYING')),
    retry_count INTEGER NOT NULL DEFAULT 0,
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_notify_txn_channel ON notification_log(transaction_id, channel);