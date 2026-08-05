# Event-identity deployment parity design

## Checked-in deployment truth

```text
Azure DevOps main
  -> mirrors to GitHub
     -> CI tests
     -> Railway workflow deploys burnlens-proxy (declared production path)

AWS enterprise Terraform (separate template; actual use unconfirmed)
  Internet -> ALB/WAF -> ECS Fargate API (desired_count=1)
                         -> Aurora PostgreSQL writer/reader endpoint
                         -> S3 exports
                         -> CloudWatch Logs + ECS Container Insights

Compose-only topology (not AWS Terraform)
  API -> PostgreSQL + Redpanda + ClickHouse + Nginx
```

The AWS template defines VPC, two public and two private subnets, ALB/ECS/RDS security groups, Aurora PostgreSQL 16.1 with one instance and Performance Insights, one ECS task, S3 exports, CloudWatch Logs, WAF, and an HTTP listener. It has no HTTPS listener resource, alarm resources, broker/ClickHouse resources, stream environment/secrets, migration task, or remote Terraform backend. Terraform state location and whether any template has been applied are unknown. The task definition uses an image tag (`latest`) and a reader endpoint in the application database secret; both require deployment-owner review before any canary.

`terraform fmt -check deploy/terraform` currently fails before provider initialization: `main.tf`, `variables.tf`, and `outputs.tf` use Python-style `"""` headers, which are invalid HCL; `main.tf` also repeats `requires_compatibilities`. Therefore this template is not currently executable IaC and cannot be treated as deployment parity until a separately approved baseline repair is validated.

The deployed AWS account is not inspectable with current credentials: `sts:GetCallerIdentity` succeeds, while `ecs:ListClusters` is denied. No secret values were requested or retrieved.

## Confirmed gaps to the tested topology

| Tested or application capability | AWS Terraform | Required action before use |
| --- | --- | --- |
| PostgreSQL identity ledger/migrations | Aurora exists, no migration process | operator-run migration task/runbook with writer endpoint |
| `EVENT_IDENTITY_ENABLED` | absent | default false in task configuration |
| Required production `PII_MASTER_KEY` | absent, while application refuses production startup without it | add a metadata-only-reviewed secret reference before treating the task definition as deployable |
| Workspace canary allowlist | absent from application/config | add, test, and inject as non-secret configuration |
| Redpanda/identity topic | absent | do not enable streaming in initial canary |
| ClickHouse queue/MV | absent | do not enable streaming in initial canary |
| Outbox worker/claim coordination | absent | deferred with streaming topology |
| Monitoring/alarming | logs/Container Insights only | add metric emitter/extraction, alarms, notification owner |
| Multiple API tasks | `desired_count=1` | retain only for bounded PostgreSQL canary; no rolling claim |

## Minimum AWS read-only access matrix

| Class | Actions | Purpose |
| --- | --- | --- |
| Mandatory inventory | `ecs:ListClusters`, `ecs:DescribeClusters`, `ecs:ListServices`, `ecs:DescribeServices`, `ecs:DescribeTaskDefinition`, `ecs:ListTasks`, `ecs:DescribeTasks` | actual API deployment, revision, desired/running count, deployment history |
| Mandatory operational evidence | `rds:DescribeDBClusters`, `rds:DescribeDBInstances`, `rds:DescribeDBClusterSnapshots`, `elasticloadbalancing:DescribeLoadBalancers`, `elasticloadbalancing:DescribeTargetGroups`, `elasticloadbalancing:DescribeTargetHealth`, `ec2:DescribeVpcs`, `ec2:DescribeSubnets`, `ec2:DescribeSecurityGroups`, `logs:DescribeLogGroups`, `logs:DescribeLogStreams`, `logs:FilterLogEvents`, `cloudwatch:ListMetrics`, `cloudwatch:GetMetricData`, `cloudwatch:DescribeAlarms` | topology, health, latency/errors, existing alarms |
| Mandatory metadata only | `iam:GetRole`, `iam:ListAttachedRolePolicies`, `iam:ListRolePolicies`, `secretsmanager:DescribeSecret`, `ssm:DescribeParameters`, `codepipeline:ListPipelines`, `codepipeline:GetPipeline`, `codepipeline:ListPipelineExecutions`, `codebuild:ListProjects`, `codebuild:BatchGetBuilds` | task permissions, secret references, pipeline provenance |
| Optional troubleshooting | `rds:DescribeDBLogFiles`, `rds:DownloadDBLogFilePortion`, `cloudwatch:GetMetricStatistics`, `application-autoscaling:DescribeScalableTargets`, `application-autoscaling:DescribeScalingPolicies` | database and scaling diagnosis |
| Explicitly prohibited | `secretsmanager:GetSecretValue`, `ssm:GetParameter` with decryption, IAM policy mutation, ECS/RDS/CloudWatch write actions | no secret retrieval or environment mutation |

## Authorized operator command pack

Run with placeholders only; do not print task environment or secret values.

```bash
aws ecs list-clusters
aws ecs list-services --cluster <cluster>
aws ecs describe-services --cluster <cluster> --services <service>
aws ecs describe-task-definition --task-definition <family-or-arn>
aws ecs list-tasks --cluster <cluster> --service-name <service>
aws ecs describe-tasks --cluster <cluster> --tasks <task-arn...>
aws rds describe-db-clusters --db-cluster-identifier <cluster>
aws rds describe-db-instances --db-instance-identifier <instance>
aws elbv2 describe-load-balancers --names <name>
aws elbv2 describe-target-groups --load-balancer-arn <arn>
aws elbv2 describe-target-health --target-group-arn <arn>
aws logs describe-log-groups --log-group-name-prefix /ecs/burnlens-
aws cloudwatch describe-alarms
aws cloudwatch list-metrics --namespace AWS/ECS
aws iam get-role --role-name <task-role>
aws iam list-attached-role-policies --role-name <task-role>
aws secretsmanager describe-secret --secret-id <secret-arn>
aws ssm describe-parameters --parameter-filters Key=Name,Option=BeginsWith,Values=/burnlens/
```

## Terraform adaptation plan — not implemented

For the selected PostgreSQL-only model, change only after ADR approval:

1. Repair and validate the existing Terraform baseline first: valid HCL comments, duplicate attributes, provider declarations, remote-state/locking decision, and a deployment-image provenance decision. Add variables for immutable API image digest, `event_identity_enabled` defaulting to `false`, and a non-secret workspace allowlist reference. Do not expose API keys or database passwords in Terraform output.
2. Add those non-secret environment variables to the ECS task and use Secrets Manager references only for existing secret values. Use the Aurora **writer** endpoint for ingest/migrations.
3. Add an explicit one-off migration ECS task definition or CI operator step that runs `python -m burnlens_cloud.migrations.runner postgres`; do not run this concurrently with application startup.
4. Add deployment configuration for a bounded one-task internal canary. Do not claim rolling compatibility; migration occurs before enablement and code stays disabled until verified.
5. Add deployed metric extraction/emission and CloudWatch alarms before enabling the allowlist. Required namespace: `BurnLens/EventIdentity`; dimensions limited to `environment` and non-sensitive `workspace_id` only where access-controlled.
6. Add alarm destination/owner as required variables (for example, an existing SNS topic ARN); fail Terraform planning if canary monitoring has no destination.

Full streaming remains a later, separate Terraform design: managed/self-hosted broker choice, ClickHouse ownership, private network/security groups, TLS/auth, identity topic, queue/MV migration, consumer and lag monitoring, reconciliation job, dead-letter operations, and either a worker or safe leased claims are all required.

## ECS and outbox decision

Select **Model 3** only for the first PostgreSQL-only internal canary. It avoids outbox draining and safely limits blast radius, but it does not prove rolling deployments. For streaming, do not select Model 1 until outbox leasing/claiming and multi-instance validation exist; prefer Model 2 (two API tasks plus a dedicated outbox worker) after the streaming infrastructure is represented in IaC and tested.

## Monitoring and alarms design

Metric collection must be deployed, not inferred from SQL documents. For PostgreSQL-only canary, emit structured application metrics/log events from the ingest transaction and derive CloudWatch metrics or use a deployed collector:

| Metric | Source | Threshold / owner |
| --- | --- | --- |
| canonical ingest success/failure | `/v1/ingest` result | failure above baseline; API on-call |
| exact replay / conflict replay | identity transaction result | conflict increase above baseline; finance + API on-call |
| PostgreSQL/ClickHouse count/cost delta | scheduled reconciliation | any non-zero during controlled canary; finance owner |
| migration failure | migration task exit/log | any failure; deployment owner |
| pending/oldest outbox, failed attempts, dead letters, delivery latency | `stream_ingest_outbox` collector | deferred until streaming; oldest >300 s, any dead letter |
| broker/consumer/MV lag | broker/ClickHouse metrics | deferred until streaming |

Alarm actions must target an existing SNS/PagerDuty/Slack integration chosen by the deployment owner, with `CLOUD_EVENT_IDENTITY_OPERATIONS.md` as the incident runbook. No destination is evidenced in repository source today.

## Production-representative evidence plan

Use a restored, sanitized Aurora snapshot in an isolated account/VPC, or a read-only production clone plus separate writable clone. Do not use local fixtures. The owner must set quantitative scale from real inventory before execution: request-record row count, table/index size, workspace distribution, 95th-percentile ingest concurrency, provider/model cardinality, and timestamp retention distribution. Redact API keys, emails, endpoint credentials, prompt hashes, and tags containing customer data; preserve workspace cardinality, cost, provider/model, timestamp, and source-ID distributions. Destroy the clone and snapshots under the normal retention policy after signed-off evidence capture.

Capture migration duration, duplicate-preflight duration, lock/blocked statements, concurrent ingest p50/p95/p99, transaction retries, identity-ledger contention, index growth, Aurora CPU/I/O/waits, dashboard p50/p95/p99, and reconciliation execution time. A generated dataset is acceptable only when its measured distributions match the approved inventory baselines.

## Deployed validation and rollback

Validation order: inventory evidence; clone migration; old code plus additive schema; new disabled code; no-ID contract/dashboard/export parity; one-workspace identity event/exact replay/conflict; reconciliation; alarm delivery; disablement; restart/re-enable recovery; then rollback drill. For streaming later, add broker and ClickHouse outage, duplicate delivery, consumer recovery, lag, and source-ID preservation.

Rollback is configuration-first: remove the workspace from the allowlist or set `EVENT_IDENTITY_ENABLED=false`, deploy the previously approved image, keep additive schema/data, and reconcile already accepted identity rows. Never delete event identities or cost records as rollback.

## Cost and security implications

PostgreSQL-only adds a partial index and small ledger rows, but no broker/ClickHouse or worker cost. Full streaming adds broker, ClickHouse, network/TLS, storage, monitoring, and on-call cost. Keep Aurora/RDS and broker access private, scope task roles to metadata/metric publishing only, use secret references instead of values, deny broad egress where feasible, and restrict operational identity metrics by workspace.

## Files proposed for a later approved implementation

- `deploy/terraform/main.tf`, `variables.tf`, `outputs.tf`
- a new Terraform alarms/monitoring module or file
- ECS migration task definition and deployment workflow
- `burnlens_cloud/config.py`, `ingest.py`, and feature-allowlist tests
- deployed metric emitter/collector and alert tests
- deployment and runbook documentation

No infrastructure is provisioned by this document.
