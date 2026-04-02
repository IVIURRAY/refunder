# RefundAgent — Terraform root module
# TODO: Fill in provider configuration and backend before deploying.

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # TODO: Configure remote state backend (e.g. S3 + DynamoDB)
  # backend "s3" {
  #   bucket = "refundagent-terraform-state"
  #   key    = "refundagent/terraform.tfstate"
  #   region = "eu-west-1"
  # }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "eu-west-1"
}

variable "app_name" {
  description = "Application name used as a prefix for resource names"
  type        = string
  default     = "refundagent"
}

variable "inbound_email_domain" {
  description = "Domain for inbound SES email (e.g. refundagent.com)"
  type        = string
}

variable "db_password" {
  description = "Master password for the RDS PostgreSQL instance"
  type        = string
  sensitive   = true
}
