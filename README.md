# RefundAgent

AI-powered refund claims automation. Detects, files, and tracks refund claims across flights (EU261/UK261), retail, and car rentals — automatically from your email.

## Architecture

```
Email forwarded to claims@{domain}
          │
          ▼
    ┌─────────────┐
    │  AWS SES    │  Receives inbound email
    └──────┬──────┘
           │ Store raw email (.eml)
           ▼
    ┌─────────────┐
    │    AWS S3   │  refundagent-raw-emails/{YYYY}/{MM}/{DD}/{message-id}.eml
    └──────┬──────┘
           │ SES receipt rule triggers
           ▼
    ┌─────────────┐
    │  AWS SQS    │  Buffer + dead letter queue (max 3 retries, 14-day DLQ)
    └──────┬──────┘
           │ Triggers
           ▼
    ┌─────────────────────────────────┐
    │         AWS Lambda              │
    │  src/ingestion/ses_handler.py   │
    │                                 │
    │  1. Fetch email from S3         │
    │  2. Parse headers/body/attchmts │
    │  3. Store attachments to S3     │
    │  4. Create email_events record  │
    │  5. Classify via Bedrock        │
    │  6. Extract claim data          │
    │  7. Upsert claim record         │
    │  8. Update email_events record  │
    └──────┬──────────────────────────┘
           │
           ├──────────────────────────┐
           ▼                          ▼
    ┌─────────────┐          ┌──────────────────┐
    │  Amazon     │          │  AWS RDS          │
    │  Bedrock    │          │  PostgreSQL        │
    │  (Claude)   │          │                   │
    │             │          │  claims           │
    │  classify   │          │  email_events     │
    │  extract    │          └──────────────────┘
    └─────────────┘
           │
           ▼
    ┌─────────────┐
    │  CLI Tool   │  refundagent claims list / show / update-status
    └─────────────┘
```

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- PostgreSQL 14+ (local) or AWS RDS
- AWS account with:
  - SES domain verified
  - Bedrock access enabled (Claude claude-sonnet-4-20250514 model)
  - S3 bucket created
  - Lambda execution role with S3 + Bedrock + RDS permissions

## Local Setup

### 1. Clone and install

```bash
git clone <repo-url>
cd refundagent
uv sync
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your values
```

Key variables to set:

| Variable | Description |
|---|---|
| `DB_HOST` | PostgreSQL host (use `localhost` for local dev) |
| `DB_PASSWORD` | Database password |
| `RAW_EMAILS_BUCKET` | S3 bucket name for raw emails |
| `INBOUND_EMAIL_DOMAIN` | Domain for inbound SES email |
| `AWS_ACCESS_KEY_ID` | AWS credentials (omit in Lambda — uses IAM role) |

### 3. Set up the database

```bash
createdb refundagent
psql -U refundagent -d refundagent -f src/db/migrations/001_initial.sql
```

### 4. Run the CLI

```bash
uv run refundagent claims list
```

### 5. Run tests

```bash
uv run pytest tests/ -v
uv run pytest tests/ --cov=src --cov-report=term-missing
```

## How to Use

### Set up email forwarding

1. Create a forwarding rule in your email client to forward refund-related emails to `claims@{your-domain}`
2. Or, set up Gmail filters to auto-forward emails matching keywords like `refund`, `compensation`, `claim`

### CLI Commands

```bash
# List all active claims
uv run refundagent claims list

# Filter by status
uv run refundagent claims list --status pending
uv run refundagent claims list --status resolved

# Show full details of a claim
uv run refundagent claims show <claim-uuid>

# Manually update a claim status
uv run refundagent claims update-status <claim-uuid> escalated

# List recent email events
uv run refundagent emails list
uv run refundagent emails list --limit 50

# Show a specific email event and its extracted data
uv run refundagent emails show <event-uuid>

# Reprocess a raw email from S3
uv run refundagent process 2024/04/15/message-id.eml
```

### Test Lambda locally

```bash
uv run python scripts/invoke_local.py
# Or with a custom fixture:
uv run python scripts/invoke_local.py path/to/ses_event.json
```

## AWS Deployment

### 1. Deploy infrastructure

```bash
cd infrastructure/terraform
terraform init
terraform apply \
  -var="inbound_email_domain=yourdomain.com" \
  -var="db_password=<secure-password>"
```

### 2. Build and upload Lambda package

```bash
# From project root
uv export --no-dev --format requirements-txt > /tmp/requirements.txt
pip install -r /tmp/requirements.txt -t lambda_package/
cp -r src lambda_package/
cd lambda_package && zip -r ../lambda_package.zip . && cd ..
aws lambda update-function-code \
  --function-name refundagent-email-processor \
  --zip-file fileb://lambda_package.zip
```

### 3. Configure Lambda environment variables

Set all variables from `.env.example` as Lambda environment variables (use AWS Secrets Manager or Parameter Store for sensitive values in production).

### 4. Run database migration

```bash
# Connect to RDS and run the migration
psql -h <rds-endpoint> -U refundagent -d refundagent \
  -f src/db/migrations/001_initial.sql
```

### 5. Verify SES domain

Follow the [AWS SES domain verification guide](https://docs.aws.amazon.com/ses/latest/dg/creating-identities.html) to verify your domain and configure inbound MX records.

## Configuration Reference

All configuration is loaded from environment variables (or `.env` file locally).

| Variable | Default | Description |
|---|---|---|
| `AWS_REGION` | `eu-west-1` | AWS region |
| `AWS_ACCESS_KEY_ID` | — | AWS key (omit in Lambda) |
| `AWS_SECRET_ACCESS_KEY` | — | AWS secret (omit in Lambda) |
| `RAW_EMAILS_BUCKET` | `refundagent-raw-emails` | S3 bucket for raw emails |
| `INBOUND_EMAIL_DOMAIN` | `refundagent.com` | Domain for inbound email |
| `DB_HOST` | `localhost` | PostgreSQL hostname |
| `DB_PORT` | `5432` | PostgreSQL port |
| `DB_NAME` | `refundagent` | Database name |
| `DB_USER` | `refundagent` | Database username |
| `DB_PASSWORD` | `changeme` | Database password |
| `DB_POOL_SIZE` | `5` | SQLAlchemy connection pool size |
| `BEDROCK_MODEL_ID` | `anthropic.claude-sonnet-4-20250514-v1:0` | Bedrock model to use |
| `BEDROCK_REGION` | `eu-west-1` | Bedrock API region |
| `APP_NAME` | `refundagent` | Application name (used in S3 prefixes) |
| `LOG_LEVEL` | `INFO` | Logging level |
| `ENVIRONMENT` | `development` | `development` \| `staging` \| `production` |

## Vertical-Specific Notes

### EU261 / UK261 — Flight Delay Compensation

**Regulation**: EU Regulation 261/2004 (EU flights) / UK Retained Regulation 261/2004 (UK flights post-Brexit)

**Eligibility**:
- Flight departed from an EU/UK airport, OR operated by an EU/UK carrier from any airport
- Delay > 3 hours at destination
- Cancellation with < 14 days notice
- Denied boarding due to overbooking

**Compensation tiers** (per passenger, one-way):

| Route distance | Delay | Compensation |
|---|---|---|
| ≤1,500km | >3h | £220 / €250 |
| 1,500–3,500km | >3h | £350 / €400 |
| >3,500km | >3h | £520 / €600 |
| >3,500km | 3–4h | £260 / €300 |

**Extraordinary circumstances** (no compensation): severe weather, ATC strikes, security risks, hidden manufacturing defects.

**Claim process**: Contact airline directly first → if rejected/ignored for 8 weeks → escalate to CAA (UK), national enforcement body (EU), or CEDR (alternative dispute resolution).

### Retail — E-Commerce Refunds

**Key legislation**: Consumer Rights Act 2015 (UK)

- Right to full refund within 30 days for faulty goods
- Right to repair/replace after 30 days (up to 6 months)
- 14-day cooling-off period for online purchases (Consumer Contracts Regulations)

**Escalation path**: Merchant → card chargeback (Section 75 CCA for £100–£30,000, chargeback for smaller amounts) → Trading Standards → Small Claims Court

### Car Rental — Damage Disputes

**Common disputes**: Damage charges for pre-existing damage, fuel charges, toll fees, deposit delays.

**Key protections**:
- Document condition at pickup with timestamped photos
- Damage charges must be substantiated with evidence
- Credit card collision damage waiver may cover disputes

**Escalation path**: Rental company complaints → British Vehicle Rental and Leasing Association (BVRLA) conciliation service → Small Claims Court

## Roadmap

### Phase 2 — Outbound Claims (Planned)
- Automatic claim letter generation (EU261, retail, car rental templates) via Bedrock
- Send from user's own email address via Gmail API / Microsoft Graph
- Reply monitoring and thread linking
- Automated chase emails with escalating tone
- See [docs/phase2-outbound-claims.md](docs/phase2-outbound-claims.md)

### Phase 3 — Form Automation (Planned)
- Playwright browser agent on ECS Fargate
- Per-merchant form profiles in DynamoDB
- Bedrock tool-use agent controls form filling
- PDF evidence extraction via Textract
- See [docs/phase3-form-automation.md](docs/phase3-form-automation.md)

### Multi-User SaaS (Planned)
- Cognito authentication
- Row-level security in RDS
- Stripe subscription billing
- FCA/CMC registration required before launch
- See [docs/multi-user.md](docs/multi-user.md)

## Regulatory Notice

The MVP is a **personal tool for single-user use only**. Operating this service commercially — taking commission on claims filed on behalf of other people — requires FCA authorisation as a Claims Management Company (CMC). See [docs/multi-user.md](docs/multi-user.md) for details.
