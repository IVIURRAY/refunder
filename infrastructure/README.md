# RefundAgent Infrastructure

This directory contains Terraform configuration stubs for deploying RefundAgent to AWS.

These are MVP stubs — they define the infrastructure shape but require completion before production deployment.

## Components

- **ses.tf** — SES inbound email receipt rules
- **s3.tf** — Raw email storage bucket
- **lambda.tf** — Processing Lambda function + SQS trigger
- **rds.tf** — PostgreSQL RDS instance

## Prerequisites

- Terraform >= 1.5
- AWS CLI configured with appropriate permissions
- SES domain verified in your target region

## Deployment

```bash
terraform init
terraform plan -var-file=terraform.tfvars
terraform apply -var-file=terraform.tfvars
```
