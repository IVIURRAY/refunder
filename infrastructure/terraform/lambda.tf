# Lambda function for SES email processing

resource "aws_sqs_queue" "email_processing" {
  name                       = "${var.app_name}-email-processing"
  visibility_timeout_seconds = 60
  message_retention_seconds  = 86400  # 1 day

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.email_processing_dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_sqs_queue" "email_processing_dlq" {
  name                      = "${var.app_name}-email-processing-dlq"
  message_retention_seconds = 1209600  # 14 days
}

resource "aws_lambda_function" "email_processor" {
  function_name = "${var.app_name}-email-processor"
  runtime       = "python3.11"
  handler       = "src.ingestion.ses_handler.handler"
  timeout       = 30
  memory_size   = 256

  # TODO: Upload deployment package
  filename = "lambda_package.zip"

  environment {
    variables = {
      RAW_EMAILS_BUCKET    = aws_s3_bucket.raw_emails.bucket
      INBOUND_EMAIL_DOMAIN = var.inbound_email_domain
      # TODO: Add DB and Bedrock env vars
    }
  }

  # TODO: Attach appropriate IAM role with S3, Bedrock, RDS permissions
}

resource "aws_lambda_event_source_mapping" "sqs_trigger" {
  event_source_arn = aws_sqs_queue.email_processing.arn
  function_name    = aws_lambda_function.email_processor.arn
  batch_size       = 1
}
