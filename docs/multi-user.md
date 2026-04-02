# Multi-User SaaS Architecture

> Status: Planned — not built in MVP

## Overview

The MVP is a single-user personal tool. This document describes the changes required to turn RefundAgent into a multi-tenant SaaS product.

## Regulatory Prerequisites

**IMPORTANT**: Before launching a multi-user paid service that takes commission on others' claims, you must:

1. Register as a **Claims Management Company (CMC)** with the FCA, OR
2. Obtain appropriate FCA authorisation
3. Comply with the Claims Management (Conduct of Authorised Persons) Rules 2018
4. Implement compliant fee disclosure and terms of service

The FCA's CMC register is at: https://register.fca.org.uk/

Operating without CMC registration while charging for claims management services is a criminal offence under FSMA 2000.

## Architecture Changes

### Authentication — Amazon Cognito
- User pool with email/password and social login (Google, Apple)
- JWT tokens validated in API Gateway or FastAPI middleware
- User ID from Cognito sub claim used as partition key across all data

### Row-Level Security
- Add `user_id UUID NOT NULL` column to `claims` and `email_events` tables
- PostgreSQL Row-Level Security (RLS) policies enforce that users can only see their own data:
  ```sql
  ALTER TABLE claims ENABLE ROW LEVEL SECURITY;
  CREATE POLICY claims_user_isolation ON claims
    USING (user_id = current_setting('app.current_user_id')::uuid);
  ```
- Application sets `SET LOCAL app.current_user_id = '{user_id}'` at the start of each request

### OAuth Token Storage
- Users connect their Gmail/Outlook account to enable sending from their own address
- OAuth tokens (access + refresh) stored in `oauth_tokens` table
- Encrypted at rest using AWS KMS customer-managed key (CMK)
- Separate token row per user per provider
- Token refresh handled automatically on each use

### Billing — Stripe
- Stripe Checkout for subscription sign-up (£9.99/month)
- Stripe webhooks update `users.subscription_status` in real time
- Commission-based billing for EU261 claims: Stripe invoices generated on `claim.resolved` event
- Metered billing for API usage (future)

### Multi-Tenant Email Ingestion
- Each user gets a unique inbound address: `{user_slug}@claims.refundagent.com`
- SES receipt rule uses a catch-all for the `claims.` subdomain
- Lambda identifies user from the recipient address before processing

### Data Isolation
- All S3 keys prefixed with `{user_id}/` for logical isolation
- IAM policies prevent cross-user S3 access at the application level
- Consider S3 Object Ownership policies for stronger guarantees

## Schema Changes

```sql
-- Add to existing tables
ALTER TABLE claims ADD COLUMN user_id UUID NOT NULL REFERENCES users(id);
ALTER TABLE email_events ADD COLUMN user_id UUID NOT NULL REFERENCES users(id);

-- New tables
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    cognito_sub     VARCHAR(255) UNIQUE NOT NULL,
    email           VARCHAR(512) UNIQUE NOT NULL,
    display_name    VARCHAR(255),
    subscription_status VARCHAR(50) DEFAULT 'free',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE oauth_tokens (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider        VARCHAR(50) NOT NULL,  -- gmail | outlook
    access_token    TEXT NOT NULL,         -- KMS-encrypted
    refresh_token   TEXT,                  -- KMS-encrypted
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, provider)
);
```

## TODO (Multi-User)
- [ ] FCA CMC registration
- [ ] Cognito user pool + app client
- [ ] RLS policies on all tables
- [ ] KMS key for OAuth token encryption
- [ ] Stripe integration
- [ ] Per-user inbound email addresses
- [ ] Terms of service and privacy policy (legal)
