"""Terraform variables for BurnLens enterprise deployment."""

variable "customer_name" {
  description = "Customer identifier (lowercase, no spaces). Used in resource names."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9-]{1,32}$", var.customer_name))
    error_message = "customer_name must be lowercase alphanumeric with hyphens, max 32 chars."
  }
}

variable "domain" {
  description = "Customer's domain for HTTPS (e.g., burnlens.acme.com). Requires pre-existing Route53 zone."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9.-]+\\.[a-z]{2,}$", var.domain))
    error_message = "domain must be a valid domain name."
  }
}

variable "db_password" {
  description = "Master password for RDS PostgreSQL. Must be 8-128 chars, contain uppercase, lowercase, digit, special char."
  type        = string
  sensitive   = true

  validation {
    condition = (
      length(var.db_password) >= 8 &&
      can(regex("[A-Z]", var.db_password)) &&
      can(regex("[a-z]", var.db_password)) &&
      can(regex("[0-9]", var.db_password)) &&
      can(regex("[!@#$%^&*()_+=-]", var.db_password))
    )
    error_message = "db_password must be 8+ chars with uppercase, lowercase, digit, and special character."
  }
}

variable "region" {
  description = "AWS region to deploy to"
  type        = string
  default     = "us-east-1"

  validation {
    condition     = can(regex("^[a-z]{2}-[a-z]+-\\d{1}$", var.region))
    error_message = "region must be a valid AWS region."
  }
}

variable "ecs_task_cpu" {
  description = "ECS task CPU (256, 512, 1024, 2048, etc.). Must match memory."
  type        = string
  default     = "256"

  validation {
    condition     = contains(["256", "512", "1024", "2048", "4096"], var.ecs_task_cpu)
    error_message = "ecs_task_cpu must be 256, 512, 1024, 2048, or 4096."
  }
}

variable "ecs_task_memory" {
  description = "ECS task memory (512, 1024, 2048, etc.). Must match CPU."
  type        = string
  default     = "512"

  validation {
    condition     = contains(["512", "1024", "2048", "4096", "8192"], var.ecs_task_memory)
    error_message = "ecs_task_memory must be 512, 1024, 2048, 4096, or 8192."
  }
}

variable "rds_instance_class" {
  description = "RDS instance type (db.t3.small, db.t3.medium, db.t3.large, etc.)"
  type        = string
  default     = "db.t3.small"

  validation {
    condition     = can(regex("^db\\.[a-z0-9]+(\\.(small|medium|large|xlarge|2xlarge))?$", var.rds_instance_class))
    error_message = "rds_instance_class must be a valid RDS instance type."
  }
}

variable "rds_allocated_storage" {
  description = "Initial RDS storage allocation in GB (min 20, max 65536)"
  type        = number
  default     = 20

  validation {
    condition     = var.rds_allocated_storage >= 20 && var.rds_allocated_storage <= 65536
    error_message = "rds_allocated_storage must be between 20 and 65536 GB."
  }
}

variable "tags" {
  description = "Additional tags to apply to all resources"
  type        = map(string)
  default     = {}
}
