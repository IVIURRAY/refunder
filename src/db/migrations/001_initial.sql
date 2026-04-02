-- Initial database schema for RefundAgent
-- Run this against a blank PostgreSQL database to set up the schema.
--
-- Usage:
--   psql -U refundagent -d refundagent -f src/db/migrations/001_initial.sql

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TYPE claim_vertical AS ENUM (
    'eu261',
    'uk261',
    'retail',
    'car_rental',
    'subscription',
    'unknown'
);

CREATE TYPE claim_status AS ENUM (
    'detected',
    'pending',
    'acknowledged',
    'in_review',
    'resolved',
    'rejected',
    'escalated',
    'closed'
);

CREATE TABLE claims (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    merchant        VARCHAR(255) NOT NULL,
    vertical        claim_vertical NOT NULL DEFAULT 'unknown',
    amount          NUMERIC(10, 2),
    currency        CHAR(3) DEFAULT 'GBP',
    reference       VARCHAR(255),
    description     TEXT,
    status          claim_status NOT NULL DEFAULT 'detected',
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_updated    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    next_action_at  TIMESTAMPTZ,
    resolved_at     TIMESTAMPTZ,
    resolved_amount NUMERIC(10, 2),
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE email_events (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    claim_id            UUID REFERENCES claims(id) ON DELETE SET NULL,
    message_id          VARCHAR(512) UNIQUE NOT NULL,
    s3_key              TEXT NOT NULL,
    sender              VARCHAR(512),
    subject             TEXT,
    received_at         TIMESTAMPTZ NOT NULL,
    direction           VARCHAR(10) DEFAULT 'inbound',
    classification      VARCHAR(50),
    extracted_data      JSONB DEFAULT '{}',
    processing_status   VARCHAR(20) DEFAULT 'pending',
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_claims_status ON claims(status);
CREATE INDEX idx_claims_merchant ON claims(merchant);
CREATE INDEX idx_claims_vertical ON claims(vertical);
CREATE INDEX idx_email_events_claim_id ON email_events(claim_id);
CREATE INDEX idx_email_events_message_id ON email_events(message_id);
CREATE INDEX idx_email_events_processing_status ON email_events(processing_status);
