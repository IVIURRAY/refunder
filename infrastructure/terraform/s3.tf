# S3 bucket for raw email storage

resource "aws_s3_bucket" "raw_emails" {
  bucket = "${var.app_name}-raw-emails"

  tags = {
    Application = var.app_name
    Purpose     = "raw-email-storage"
  }
}

resource "aws_s3_bucket_versioning" "raw_emails" {
  bucket = aws_s3_bucket.raw_emails.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "raw_emails" {
  bucket = aws_s3_bucket.raw_emails.id

  rule {
    id     = "expire-old-emails"
    status = "Enabled"

    expiration {
      days = 365
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "raw_emails" {
  bucket = aws_s3_bucket.raw_emails.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Allow SES to write to this bucket
resource "aws_s3_bucket_policy" "raw_emails" {
  bucket = aws_s3_bucket.raw_emails.id
  policy = data.aws_iam_policy_document.ses_s3_write.json
}

data "aws_iam_policy_document" "ses_s3_write" {
  statement {
    principals {
      type        = "Service"
      identifiers = ["ses.amazonaws.com"]
    }
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.raw_emails.arn}/*"]
  }
}
