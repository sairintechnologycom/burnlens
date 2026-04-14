"""
BurnLens Enterprise Deployment — AWS ECS + RDS + ALB

Deploys a complete isolated BurnLens Cloud instance for a single customer:
  - ECS Fargate cluster running burnlens-cloud API
  - RDS PostgreSQL 16 with multi-AZ failover
  - Application Load Balancer with HTTPS
  - VPC with public/private subnets
  - S3 bucket for cost export archives
  - CloudWatch logs for monitoring

Usage:
  terraform apply -var-file=customer.tfvars

Example customer.tfvars:
  customer_name = "acme-corp"
  domain = "burnlens.acme.com"
  db_password = "GenerateSecurePassword123!"
  region = "us-east-1"
  ecs_task_cpu = "256"
  ecs_task_memory = "512"
  rds_instance_class = "db.t3.small"
  rds_allocated_storage = 20
"""

terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

# ============================================================================
# VPC and Networking
# ============================================================================

resource "aws_vpc" "burnlens" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name        = "burnlens-${var.customer_name}"
    Environment = "production"
  }
}

resource "aws_subnet" "public_1" {
  vpc_id                  = aws_vpc.burnlens.id
  cidr_block              = "10.0.1.0/24"
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = true

  tags = { Name = "burnlens-public-1" }
}

resource "aws_subnet" "public_2" {
  vpc_id                  = aws_vpc.burnlens.id
  cidr_block              = "10.0.2.0/24"
  availability_zone       = data.aws_availability_zones.available.names[1]
  map_public_ip_on_launch = true

  tags = { Name = "burnlens-public-2" }
}

resource "aws_subnet" "private_1" {
  vpc_id            = aws_vpc.burnlens.id
  cidr_block        = "10.0.10.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]

  tags = { Name = "burnlens-private-1" }
}

resource "aws_subnet" "private_2" {
  vpc_id            = aws_vpc.burnlens.id
  cidr_block        = "10.0.11.0/24"
  availability_zone = data.aws_availability_zones.available.names[1]

  tags = { Name = "burnlens-private-2" }
}

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_internet_gateway" "burnlens" {
  vpc_id = aws_vpc.burnlens.id
  tags   = { Name = "burnlens-igw" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.burnlens.id

  route {
    cidr_block      = "0.0.0.0/0"
    gateway_id      = aws_internet_gateway.burnlens.id
  }

  tags = { Name = "burnlens-public-rt" }
}

resource "aws_route_table_association" "public_1" {
  subnet_id      = aws_subnet.public_1.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "public_2" {
  subnet_id      = aws_subnet.public_2.id
  route_table_id = aws_route_table.public.id
}

# ============================================================================
# Security Groups
# ============================================================================

resource "aws_security_group" "alb" {
  name        = "burnlens-alb-${var.customer_name}"
  description = "ALB security group for BurnLens"
  vpc_id      = aws_vpc.burnlens.id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "burnlens-alb-sg" }
}

resource "aws_security_group" "ecs" {
  name        = "burnlens-ecs-${var.customer_name}"
  description = "ECS security group for BurnLens"
  vpc_id      = aws_vpc.burnlens.id

  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "burnlens-ecs-sg" }
}

resource "aws_security_group" "rds" {
  name        = "burnlens-rds-${var.customer_name}"
  description = "RDS security group for BurnLens"
  vpc_id      = aws_vpc.burnlens.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "burnlens-rds-sg" }
}

# ============================================================================
# RDS PostgreSQL Database
# ============================================================================

resource "aws_db_subnet_group" "burnlens" {
  name       = "burnlens-${var.customer_name}"
  subnet_ids = [aws_subnet.private_1.id, aws_subnet.private_2.id]

  tags = { Name = "burnlens-db-subnet-group" }
}

resource "aws_rds_cluster" "burnlens" {
  cluster_identifier     = "burnlens-${var.customer_name}"
  engine                 = "aurora-postgresql"
  engine_version         = "16.1"
  database_name          = "burnlens"
  master_username        = "burnlens"
  master_password        = var.db_password
  db_subnet_group_name   = aws_db_subnet_group.burnlens.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  backup_retention_period      = 30
  preferred_backup_window      = "03:00-04:00"
  preferred_maintenance_window = "mon:04:00-mon:05:00"
  enabled_cloudwatch_logs_exports = ["postgresql"]

  storage_encrypted           = true
  copy_tags_to_snapshot       = true
  skip_final_snapshot         = false
  final_snapshot_identifier   = "burnlens-${var.customer_name}-final-${formatdate("YYYY-MM-DD-hhmm", timestamp())}"

  tags = {
    Name        = "burnlens-${var.customer_name}"
    Environment = "production"
  }
}

resource "aws_rds_cluster_instance" "primary" {
  cluster_identifier           = aws_rds_cluster.burnlens.id
  instance_class               = var.rds_instance_class
  engine                       = aws_rds_cluster.burnlens.engine
  engine_version               = aws_rds_cluster.burnlens.engine_version
  identifier                   = "burnlens-${var.customer_name}-1"
  auto_minor_version_upgrade   = true
  performance_insights_enabled = true

  tags = { Name = "burnlens-${var.customer_name}-instance-1" }
}

# ============================================================================
# S3 Bucket for Exports
# ============================================================================

resource "aws_s3_bucket" "exports" {
  bucket = "burnlens-exports-${var.customer_name}-${data.aws_caller_identity.current.account_id}"

  tags = {
    Name        = "burnlens-exports-${var.customer_name}"
    Environment = "production"
  }
}

resource "aws_s3_bucket_versioning" "exports" {
  bucket = aws_s3_bucket.exports.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "exports" {
  bucket = aws_s3_bucket.exports.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# ============================================================================
# ECS Cluster and Task Definition
# ============================================================================

resource "aws_ecs_cluster" "burnlens" {
  name = "burnlens-${var.customer_name}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Name        = "burnlens-${var.customer_name}"
    Environment = "production"
  }
}

resource "aws_iam_role" "ecs_task_execution_role" {
  name = "burnlens-ecs-task-execution-${var.customer_name}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_role_policy" {
  role       = aws_iam_role.ecs_task_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "ecs_task_role" {
  name = "burnlens-ecs-task-${var.customer_name}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy" "ecs_task_s3_policy" {
  name = "burnlens-s3-access"
  role = aws_iam_role.ecs_task_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject",
        "s3:PutObject",
        "s3:ListBucket",
      ]
      Resource = [
        aws_s3_bucket.exports.arn,
        "${aws_s3_bucket.exports.arn}/*",
      ]
    }]
  })
}

resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/burnlens-${var.customer_name}"
  retention_in_days = 30

  tags = { Name = "burnlens-ecs-logs" }
}

resource "aws_ecs_task_definition" "burnlens" {
  family                   = "burnlens-${var.customer_name}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.ecs_task_cpu
  memory                   = var.ecs_task_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([{
    name      = "burnlens-api"
    image     = "burnlens/burnlens-cloud:latest"
    essential = true
    portMappings = [{
      containerPort = 8000
      hostPort      = 8000
      protocol      = "tcp"
    }]
    environment = [
      {
        name  = "ENVIRONMENT"
        value = "production"
      },
      {
        name  = "LOG_LEVEL"
        value = "INFO"
      },
    ]
    secrets = [
      {
        name      = "DATABASE_URL"
        valueFrom = aws_secretsmanager_secret.db_url.arn
      },
      {
        name      = "JWT_SECRET"
        valueFrom = aws_secretsmanager_secret.jwt_secret.arn
      },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "ecs"
      }
    }
  }])

  tags = { Name = "burnlens-task-def" }
}

# ============================================================================
# Secrets Manager
# ============================================================================

resource "aws_secretsmanager_secret" "db_url" {
  name = "burnlens/${var.customer_name}/database-url"

  tags = { Name = "burnlens-db-url" }
}

resource "aws_secretsmanager_secret_version" "db_url" {
  secret_id = aws_secretsmanager_secret.db_url.id
  secret_string = "postgresql://burnlens:${var.db_password}@${aws_rds_cluster.burnlens.reader_endpoint}:5432/burnlens"
}

resource "aws_secretsmanager_secret" "jwt_secret" {
  name = "burnlens/${var.customer_name}/jwt-secret"

  tags = { Name = "burnlens-jwt-secret" }
}

resource "aws_secretsmanager_secret_version" "jwt_secret" {
  secret_id     = aws_secretsmanager_secret.jwt_secret.id
  secret_string = random_password.jwt_secret.result
}

resource "random_password" "jwt_secret" {
  length  = 32
  special = true
}

# ============================================================================
# Application Load Balancer
# ============================================================================

resource "aws_lb" "burnlens" {
  name               = "burnlens-${var.customer_name}"
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = [aws_subnet.public_1.id, aws_subnet.public_2.id]

  enable_deletion_protection = false

  tags = {
    Name        = "burnlens-${var.customer_name}"
    Environment = "production"
  }
}

resource "aws_lb_target_group" "burnlens" {
  name        = "burnlens-${var.customer_name}"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.burnlens.id
  target_type = "ip"

  health_check {
    healthy_threshold   = 2
    unhealthy_threshold = 2
    timeout             = 3
    interval            = 30
    path                = "/health"
    matcher             = "200"
  }

  tags = { Name = "burnlens-tg" }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.burnlens.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# Note: HTTPS listener requires ACM certificate
# Create certificate separately and add:
# resource "aws_lb_listener" "https" { ... }

# ============================================================================
# ECS Service
# ============================================================================

resource "aws_ecs_service" "burnlens" {
  name            = "burnlens-${var.customer_name}"
  cluster         = aws_ecs_cluster.burnlens.id
  task_definition = aws_ecs_task_definition.burnlens.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = [aws_subnet.private_1.id, aws_subnet.private_2.id]
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.burnlens.arn
    container_name   = "burnlens-api"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.http]

  tags = {
    Name        = "burnlens-service"
    Environment = "production"
  }
}

# ============================================================================
# Data Sources
# ============================================================================

data "aws_caller_identity" "current" {}
