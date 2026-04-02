# Phase 3: Merchant Form Automation

> Status: Planned — not built in MVP

## Overview

Phase 3 adds a browser automation agent that can navigate to merchant websites and submit claim forms automatically, handling cases where merchants do not accept email claims.

## Architecture

### Browser Agent
- Playwright-based automation running on **ECS Fargate** (not Lambda — form filling is too long-running for 15-minute Lambda limit)
- Task triggered by EventBridge or Step Functions when a claim reaches PENDING with `form_required: true` in metadata
- Screenshots captured at each step and stored to S3 for audit trail

### Merchant Form Profiles
- DynamoDB table: `merchant_form_profiles`
  - `merchant_id` (partition key)
  - `form_url`: Starting URL for the claim form
  - `field_mappings`: JSON mapping ClaimData fields to CSS selectors
  - `submit_selector`: CSS selector for the submit button
  - `confirmation_selector`: CSS selector indicating successful submission
- Profiles maintained manually initially; could be auto-discovered in future

### Bedrock Tool-Use Agent
- Claude claude-sonnet-4-20250514 with tool use controls Playwright
- Tools available to the agent:
  - `navigate(url)` — navigate to URL
  - `click(selector)` — click element
  - `fill(selector, value)` — fill form field
  - `screenshot()` — capture current page state
  - `extract_text(selector)` — extract text from element
- Agent receives claim data and form profile, reasons step-by-step through form completion

### Evidence Upload
- AWS Textract extracts text and key-value pairs from PDF attachments (boarding passes, rental agreements)
- Extracted data populates form fields that require document values (e.g. exact flight time from boarding pass)

### Error Handling
- On form submission failure: capture screenshot, store error to claim metadata, alert user via email
- Retry up to 3 times with exponential backoff
- After 3 failures: fall back to email claim (Phase 2 flow)

## Data Model Changes
- `claims.form_required: bool` — whether form automation should be attempted
- `claims.form_submitted_at: timestamptz` — when the form was last submitted
- `form_submissions` table: audit log of each form automation attempt

## TODO (Phase 3)
- [ ] ECS Fargate task definition for Playwright
- [ ] DynamoDB merchant form profiles schema
- [ ] Bedrock tool-use agent implementation
- [ ] Textract PDF extraction integration
- [ ] Step Functions orchestration for multi-step form flows
