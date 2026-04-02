# Phase 2: Outbound Claims Automation

> Status: Planned — not built in MVP

## Overview

Phase 2 adds the ability for RefundAgent to automatically send claim letters to merchants on the user's behalf, monitor for replies, and schedule automated chasers.

## Architecture

### Claim Intake
- FastAPI endpoint: `POST /api/v1/claims` accepts structured claim data
- Alternative: continue email ingestion (Phase 1) as primary intake
- Validation against vertical-specific schemas (EU261 requires flight details, car rental requires rental agreement ref)

### Claim Letter Generation
- Amazon Bedrock (Claude) generates a formal claim letter per vertical:
  - **EU261/UK261**: Cites regulation article numbers, calculates compensation tier (£220/£350/£520) based on route distance, includes flight details and delay duration
  - **Retail**: References Consumer Rights Act 2015, includes order details, itemises refund amount
  - **Car rental**: Challenges damage charge with supporting arguments, cites CRA 2015 for misrepresentation
- Letters stored as DOCX and PDF in S3 for audit trail

### Outbound Email Sending
- Primary: Gmail API or Microsoft Graph API using stored OAuth tokens (allows sending from user's own address)
- Fallback: AWS SES for sending from claims@{domain}
- OAuth tokens stored encrypted in RDS using AWS KMS customer-managed key
- Thread management: `In-Reply-To` and `References` headers preserved so replies land in same thread

### Thread Monitoring (Inbound Reply Handling)
- Existing Phase 1 ingestion pipeline handles replies
- Reply matching: extract `In-Reply-To` header → look up `email_events.message_id` → link to existing claim
- Classification of reply drives status transition (acknowledged → in_review → resolved/rejected)

### Chase Scheduler
- EventBridge rule fires Lambda daily at 08:00 UTC
- Lambda queries `claims.next_action_at <= NOW()` for PENDING/ACKNOWLEDGED claims
- Generates and sends a chase letter (shorter, more assertive tone)
- Updates `next_action_at` to +14 days
- After 3 chase attempts: escalate to CEDR/ADR or MCOL (small claims)

## Data Model Changes
- `outbound_emails` table: stores sent email metadata, linked to claim
- `claims.chase_count` counter: tracks how many chasers have been sent
- `oauth_tokens` table: stores encrypted Gmail/Outlook tokens per user (Phase 3 multi-user)

## TODO (Phase 2)
- [ ] FastAPI intake endpoint
- [ ] Bedrock claim letter generation per vertical
- [ ] Gmail API integration
- [ ] Chase scheduler Lambda + EventBridge rule
- [ ] Reply thread matching
