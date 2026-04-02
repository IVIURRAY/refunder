# SES inbound email configuration
# TODO: Domain must be verified in SES before this will work.

resource "aws_ses_receipt_rule_set" "main" {
  rule_set_name = "${var.app_name}-inbound"
}

resource "aws_ses_receipt_rule" "store_and_notify" {
  name          = "${var.app_name}-store-and-notify"
  rule_set_name = aws_ses_receipt_rule_set.main.rule_set_name
  recipients    = ["claims@${var.inbound_email_domain}"]
  enabled       = true
  scan_enabled  = true

  s3_action {
    bucket_name       = aws_s3_bucket.raw_emails.bucket
    object_key_prefix = ""
    position          = 1
  }

  # TODO: Add SNS/SQS action to trigger Lambda after S3 store
}

resource "aws_ses_active_receipt_rule_set" "main" {
  rule_set_name = aws_ses_receipt_rule_set.main.rule_set_name
}
