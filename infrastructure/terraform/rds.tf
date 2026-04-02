# RDS PostgreSQL instance for RefundAgent

resource "aws_db_instance" "main" {
  identifier           = "${var.app_name}-db"
  engine               = "postgres"
  engine_version       = "15.4"
  instance_class       = "db.t3.micro"
  allocated_storage    = 20
  storage_encrypted    = true

  db_name  = "refundagent"
  username = "refundagent"
  password = var.db_password

  skip_final_snapshot    = false
  final_snapshot_identifier = "${var.app_name}-final-snapshot"
  deletion_protection    = true

  backup_retention_period = 7
  backup_window           = "02:00-03:00"
  maintenance_window      = "Mon:03:00-Mon:04:00"

  # TODO: Configure VPC, subnet group, and security group
  # vpc_security_group_ids = [aws_security_group.rds.id]
  # db_subnet_group_name   = aws_db_subnet_group.main.name

  tags = {
    Application = var.app_name
  }
}
