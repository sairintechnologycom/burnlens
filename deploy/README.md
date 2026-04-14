# BurnLens Enterprise Deployment Guide

Deploy a dedicated BurnLens Cloud instance for your enterprise in 20 minutes.

## Overview

This guide covers two deployment options:

1. **AWS-Managed** (recommended for SaaS teams) — ECS + RDS + ALB
2. **Self-Hosted** — Docker Compose on your infrastructure

Both provide:
- Isolated PostgreSQL database (multi-AZ failover for AWS)
- HTTPS with TLS termination
- OpenTelemetry push to Datadog/Grafana
- Audit logging (365-day retention)
- Cost tracking dashboard
- API key authentication

---

## Option 1: AWS Managed Deployment (Terraform)

**Prerequisites:**
- AWS account with appropriate IAM permissions
- Terraform 1.0+ installed
- `terraform` command in PATH
- Pre-existing Route53 zone for your domain

**Estimated time: 15 minutes**

### Step 1: Prepare Variables

Create `deploy/terraform/customer.tfvars`:

```hcl
customer_name     = "acme-corp"  # lowercase, 32 chars max
domain            = "burnlens.acme.com"
db_password       = "SecurePassword123!@#"
region            = "us-east-1"
ecs_task_cpu      = "256"
ecs_task_memory   = "512"
rds_instance_class = "db.t3.small"
rds_allocated_storage = 20
```

⚠️ **Security**: Use a strong password. Consider using AWS Secrets Manager for rotation.

### Step 2: Deploy Infrastructure

```bash
cd deploy/terraform

# Initialize Terraform
terraform init

# Review what will be created
terraform plan -var-file=customer.tfvars

# Deploy (takes ~10 minutes)
terraform apply -var-file=customer.tfvars
```

Terraform creates:
- VPC with public/private subnets across 2 AZs
- RDS Aurora PostgreSQL cluster (multi-AZ)
- ECS Fargate cluster running API container
- Application Load Balancer with security groups
- S3 bucket for export archives
- CloudWatch logs

### Step 3: Configure HTTPS

```bash
# Get ALB DNS name
terraform output alb_dns_name
# Output: burnlens-acme-corp-1234567890.us-east-1.elb.amazonaws.com

# 1. Create ACM certificate for your domain
# Go to AWS Console → ACM → Request certificate
#   - Domain: burnlens.acme.com
#   - Wait for DNS validation

# 2. Note the certificate ARN (arn:aws:acm:...)

# 3. Add HTTPS listener to ALB (via AWS Console or Terraform)
# You can manually add via CLI:
aws elbv2 create-listener \
  --load-balancer-arn <ALB_ARN from terraform output> \
  --protocol HTTPS \
  --port 443 \
  --certificates CertificateArn=arn:aws:acm:... \
  --default-actions Type=forward,TargetGroupArn=<TG_ARN>
```

### Step 4: Update DNS

```bash
# Create Route53 record pointing to ALB
aws route53 change-resource-record-sets \
  --hosted-zone-id <YOUR_ZONE_ID> \
  --change-batch '{
    "Changes": [{
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "burnlens.acme.com",
        "Type": "CNAME",
        "TTL": 300,
        "ResourceRecords": [{"Value": "<ALB_DNS_NAME>"}]
      }
    }]
  }'
```

### Step 5: Test Deployment

```bash
# Wait 2 minutes for DNS propagation, then:
curl -I https://burnlens.acme.com/health

# Should return 200 OK

# View logs
aws logs tail /ecs/burnlens-acme-corp --follow
```

---

## Option 2: Self-Hosted Deployment (Docker Compose)

**Prerequisites:**
- Linux server (Ubuntu 20.04+) or Docker Desktop
- Docker 20.10+, Docker Compose 1.29+
- 2GB RAM, 20GB storage
- SSL certificate (self-signed OK for testing)

**Estimated time: 5 minutes**

### Step 1: Prepare Environment

```bash
# Clone deployment files
mkdir -p /opt/burnlens
cd /opt/burnlens
cp deploy/docker-compose.enterprise.yml docker-compose.yml

# Create .env file
cat > .env << 'EOF'
DOMAIN=burnlens.acme.com
DB_PASSWORD=SecurePassword123!@#
JWT_SECRET=$(openssl rand -base64 32)
OTEL_ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
SENDGRID_API_KEY=
SENDGRID_FROM_EMAIL=noreply@burnlens.acme.com
EOF

chmod 600 .env
```

### Step 2: Create Nginx Config

Create `nginx.conf`:

```nginx
user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log warn;
pid /var/run/nginx.pid;

events {
    worker_connections 1024;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" "$http_x_forwarded_for"';

    access_log /var/log/nginx/access.log main;

    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
    limit_req_zone $binary_remote_addr zone=ingest_limit:10m rate=100r/s;

    upstream burnlens_api {
        server api:8000;
    }

    # HTTP to HTTPS redirect
    server {
        listen 80;
        server_name _;
        return 301 https://$host$request_uri;
    }

    # HTTPS server
    server {
        listen 443 ssl http2;
        server_name _;

        ssl_certificate /etc/nginx/ssl/cert.pem;
        ssl_certificate_key /etc/nginx/ssl/key.pem;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;
        ssl_prefer_server_ciphers on;

        client_max_body_size 10M;

        # Health check endpoint
        location /health {
            access_log off;
            proxy_pass http://burnlens_api;
        }

        # Ingest endpoint (high rate limit)
        location /v1/ingest {
            limit_req zone=ingest_limit burst=20 nodelay;
            proxy_pass http://burnlens_api;
            proxy_read_timeout 30s;
        }

        # API endpoints (standard rate limit)
        location /api/ {
            limit_req zone=api_limit burst=10 nodelay;
            proxy_pass http://burnlens_api;
            proxy_read_timeout 10s;
        }

        # Status page (public, no auth)
        location /status {
            proxy_pass http://burnlens_api;
            access_log off;
        }

        # Everything else
        location / {
            proxy_pass http://burnlens_api;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
    }
}
```

### Step 3: Create SSL Certificate

```bash
# For production: use Let's Encrypt (Certbot)
# For testing: use self-signed

mkdir -p ssl

# Self-signed (valid 1 year, testing only)
openssl req -x509 -newkey rsa:4096 -nodes \
  -keyout ssl/key.pem -out ssl/cert.pem -days 365 \
  -subj "/C=US/ST=State/L=City/O=Org/CN=burnlens.acme.com"

# Production: use Let's Encrypt Certbot
# sudo certbot certonly --standalone -d burnlens.acme.com
# Then copy /etc/letsencrypt/live/burnlens.acme.com/{cert,privkey}.pem to ssl/
```

### Step 4: Launch Containers

```bash
# Pull latest images
docker-compose pull

# Start services (detached)
docker-compose up -d

# Wait for healthy status
docker-compose ps

# Check logs
docker-compose logs -f api
```

### Step 5: Initialize Database

```bash
# Run migrations (done automatically in container startup)
docker-compose exec api python -m burnlens_cloud.cli migrate

# Create first workspace (optional, for testing)
docker-compose exec api python -c "
from burnlens_cloud.auth import generate_api_key
print(f'API Key: {generate_api_key()}')
"
```

### Step 6: Test Deployment

```bash
# Test health check
curl -k https://localhost/health

# Test ingest endpoint
curl -k -X POST https://localhost/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{"api_key": "sk_test", "records": []}'

# View logs
docker-compose logs -f api
```

---

## Connecting OSS Proxies

Once deployed, connect BurnLens OSS proxies to send cost data:

```bash
# On your local machine running OSS proxy
export BURNLENS_CLOUD_ENDPOINT="https://burnlens.acme.com"
export BURNLENS_API_KEY="<api_key_from_dashboard>"

# Start proxy (uses cloud sync)
burnlens start

# Or with environment
BURNLENS_CLOUD_ENDPOINT=https://burnlens.acme.com burnlens start
```

---

## OpenTelemetry Configuration

To push cost data to Datadog/Grafana:

1. Go to dashboard: `https://burnlens.acme.com/dashboard`
2. Click **Settings** → **OpenTelemetry**
3. Enter:
   - **Endpoint**: `https://http-intake.logs.datadoghq.com/v1/traces`
   - **API Key**: Your Datadog API key
4. Click **Test Connection**
5. Spans flow automatically on next ingest

---

## Monitoring & Maintenance

### View Status
```bash
# AWS
aws ecs describe-services --cluster burnlens-acme-corp --services burnlens-acme-corp

# Docker Compose
docker-compose ps
docker-compose logs api
```

### Backup Database
```bash
# AWS (automatic daily snapshots via Terraform)
# Manual backup:
aws rds create-db-cluster-snapshot --db-cluster-identifier burnlens-acme-corp --db-cluster-snapshot-identifier backup-$(date +%Y%m%d)

# Docker Compose (daily cron):
docker exec burnlens-postgres pg_dump -U burnlens burnlens | gzip > /backups/burnlens-$(date +%Y%m%d).sql.gz
```

### Scale Database
```bash
# AWS (via Terraform)
# Update rds_instance_class in customer.tfvars, then:
terraform apply -var-file=customer.tfvars

# Docker Compose (manual)
# Edit docker-compose.yml, increase postgres resources, then:
docker-compose up -d
```

### Update API
```bash
# AWS (ECS auto-updates on push to registry)
# Manual: aws ecs update-service --cluster burnlens-acme-corp --service burnlens-acme-corp --force-new-deployment

# Docker Compose
docker-compose pull
docker-compose up -d api
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `Cannot connect to API` | Check security groups (AWS) or firewall rules. Check nginx logs: `docker logs burnlens-nginx` |
| `Database connection timeout` | Check RDS security group allows ECS security group on port 5432 |
| `High API latency` | Scale ECS task (increase CPU/memory) or RDS instance |
| `Disk full` | Docker: `docker system prune -a`. AWS: Increase EBS volume size |
| `OTEL spans not appearing` | Verify endpoint reachable: `curl -H "Authorization: Bearer <key>" https://otel.endpoint/health` |

---

## Cost Estimates

**AWS (monthly):**
- ECS Fargate: $10-30 (depends on task size)
- RDS Aurora: $50-200 (db.t3.small to medium)
- NAT Gateway: $30
- Load Balancer: $20
- **Total: ~$110-280/month**

**Self-Hosted (monthly):**
- Server: $20-100 (cloud VPS or on-premises)
- Backup storage: $5-10
- **Total: ~$25-110/month**

---

## Support

For issues:
1. Check logs: `aws logs tail /ecs/burnlens-acme-corp` or `docker-compose logs`
2. Review dashboard: `https://burnlens.acme.com/status`
3. Email support: support@burnlens.app

---

**Next: Configure OpenTelemetry** → [See OpenTelemetry Setup](../docs/otel-setup.md)
