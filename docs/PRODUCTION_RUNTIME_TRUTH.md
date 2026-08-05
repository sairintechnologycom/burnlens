# BurnLens production deployment authority and runtime truth

**Assessment date:** 2026-08-04
**Scope:** read-only repository, public-endpoint, GitHub, Railway CLI, and AWS
inventory evidence. No deployment configuration, infrastructure, application
behaviour, flags, migrations, or cloud resources were changed.

## Evidence labels

| Label | Meaning |
| --- | --- |
| **Verified** | Directly observed from the named platform or public endpoint. |
| **Repository indication** | Checked-in source describes the behaviour; it does not prove it is live. |
| **Inference** | Strong conclusion drawn from verified facts plus source. |
| **Unknown** | Cannot be established safely with present access/evidence. |

## Authoritative current-production architecture

```text
Azure DevOps main (repository indication: mirror pipeline)
        |
        v
GitHub main
  |                         |
  | GitHub Actions           | Vercel production deployment
  | deploy-railway.yml       v
  | (verified workflow)    burnlens.app frontend
  v                         |
Railway burnlens-proxy <----+ HTTPS / browser requests
one replica, asia-southeast1-eqsg3
  ^
  | Vercel host rewrite for api.burnlens.app (verified)
  |
clients / local proxy ----> api.burnlens.app
                              |
                              v
                       Railway Postgres service
                       (database service verified; application binding inferred)

GitHub Actions hourly cron ----> POST api.burnlens.app/cron/evaluate-alerts
(verified workflow and successful recent runs)
```

### Verified facts

| Area | Current evidence |
| --- | --- |
| Public frontend | `https://burnlens.app` responds through Vercel. Public response headers identify Vercel. |
| Public API route | `https://api.burnlens.app/health` returns `200 {"status":"ok"}`. Its response carries Vercel and Railway-edge headers. |
| API reverse proxy | [`frontend/vercel.json`](../frontend/vercel.json) rewrites all `api.burnlens.app` paths to the Railway service domain. The Railway direct `/health` endpoint also returns `200`. |
| Backend runtime | Railway production has a successful `burnlens-proxy` service deployment, created 2026-07-20 16:22:30 UTC, in `asia-southeast1-eqsg3`, using Railpack and one replica. The active image digest begins `sha256:d259e4cff969`. |
| Database service | The same Railway production project has one successful PostgreSQL service, also in `asia-southeast1-eqsg3`, with a persistent database volume. No ClickHouse, Redpanda, or object-storage service exists in that project. |
| Public operational status | `https://api.burnlens.app/api/status` reports Ingest API, Dashboard API, and Cloud Sync operational at the time of inspection. This is application status, not a replacement for infrastructure monitoring. |
| Deployment workflow | [`deploy-railway.yml`](../.github/workflows/deploy-railway.yml) deploys service `burnlens-proxy` to Railway `production` from `main`, after backend tests and frontend test/build gates. |
| Frontend deployment | GitHub deployment metadata records a Vercel production deployment from commit `94491f271b894945f5225cf9d20d5424c1e6de27` on 2026-07-23. |
| Alert scheduler | [`cron-evaluate-alerts.yml`](../.github/workflows/cron-evaluate-alerts.yml) calls the production cron endpoint hourly; recent GitHub runs were successful. |

### What is inferred, not verified

* Canonical cloud cost persistence is Railway PostgreSQL. It is the only live database service found, and the application requires `DATABASE_URL` ([`config.py`](../burnlens_cloud/config.py#L9)). The deployed environment-variable binding was intentionally not read because it would expose secret values.
* Dashboards currently query PostgreSQL. No production ClickHouse or Redpanda service exists, and the source defaults `STREAMING_ENABLED` to `false` ([`config.py`](../burnlens_cloud/config.py#L90-L106)). Runtime flag values remain unknown.
* The active backend source is likely commit `6f0f22615821f6a76b5424077444618700012618`: the successful Railway workflow for that commit ended two minutes before the active Railway deployment was created. Railway's active-deployment metadata exposes an image digest, not a source SHA, so this is not an exact version proof.

### Unknown runtime facts

* Exact backend commit, semantic application version, migration level, and running feature-flag values.
* Railway variable names and bindings, database writer/reader endpoint, connection-pool runtime settings, backup/PITR policy, and retention-job execution evidence.
* DNS-provider ownership, Vercel project ownership/configuration beyond public behaviour, and the exact TLS certificate-management configuration.
* Export-store implementation and production retention of exported files.
* Named operational owners and approval roles.

## Production-domain routing evidence

| Route | Result | Classification |
| --- | --- | --- |
| `burnlens.app` | Vercel response headers; frontend health path is not an API health endpoint (`404`). | **Verified:** Vercel frontend/TLS edge. |
| `api.burnlens.app/health` | `200` from the health endpoint; Vercel and Railway-edge headers. | **Verified:** Vercel forwards the production API hostname to Railway. |
| `burnlens-proxy-production.up.railway.app/health` | `200 {"status":"ok"}`. | **Verified:** Railway service is directly reachable. |
| DNS target control plane | Public DNS returned A records; no CNAME was observed. | **Unknown:** DNS provider, record ownership, and exact Vercel configuration. |
| TLS | HSTS is emitted by Vercel configuration and observed at the public domains. | **Verified:** TLS terminates at the public edge; **unknown:** certificate-management owner. |

The checked-in host rewrite is the strongest repository-level routing evidence: [`frontend/vercel.json`](../frontend/vercel.json#L3-L8). Its API route is a Vercel edge rewrite, not evidence that FastAPI runs on Vercel.

## GitHub deployment workflow assessment

| Item | Finding |
| --- | --- |
| Deploying workflow | [`Deploy burnlens_cloud to Railway`](../.github/workflows/deploy-railway.yml#L1). |
| Trigger | Push to `main` when backend/deployment paths change, or manual dispatch ([lines 3-12](../.github/workflows/deploy-railway.yml#L3)). A frontend-only change does not invoke this backend workflow. |
| Test gate | Python 3.12, `pytest tests/`, Node 20, frontend `npm test` and `npm run build` ([lines 18-43](../.github/workflows/deploy-railway.yml#L18)). |
| Deployment | Railway CLI 5.26.0 runs `railway up --service burnlens-proxy --environment production --ci --detach` ([lines 45-58](../.github/workflows/deploy-railway.yml#L45)). Railway/Railpack creates the build artifact; no image tag is pinned by the workflow. |
| Environment / approvals | Workflow uses GitHub environment `production`; current GitHub environment metadata has no protection rules. Therefore this workflow has no repository-configured manual approval gate. |
| Secrets / variables | Names only: `RAILWAY_TOKEN` and optional `BURNLENS_HEALTH_URL` ([lines 55-65](../.github/workflows/deploy-railway.yml#L55)). Secret values were not accessed. |
| Migration / rollback | No migration command, deployment artifact promotion, or rollback command is defined in the workflow. Railway retains deployment history; the exercised rollback process is **unknown**. |
| Upstream source | [`azure-pipelines.yml`](../azure-pipelines.yml#L1) indicates Azure DevOps mirrors `main` to GitHub. The pipeline's current enablement/run history was not verified. |

## Railway assessment

| Topic | Finding |
| --- | --- |
| Checked-in service definition | No `railway.json`, `railway.toml`, Dockerfile, or Nixpacks config is checked in. [`Procfile`](../Procfile) defines an equivalent Uvicorn command, but the active service is built by Railpack. |
| Console-managed state | Railway project/environment, service domains, region, replica count, volumes, variables, build selection, and deployment configuration are console/platform state. The repository alone cannot fully recreate production. |
| API service | One `burnlens-proxy` replica; restart policy `ON_FAILURE` with up to 10 retries; no explicit service health-check path, pre-deploy command, or drain/overlap configuration was present in deployment metadata. |
| Database | One Railway PostgreSQL service with a persistent `/var/lib/postgresql/data` volume. Its binding to the API is inferred rather than directly inspected. |
| Cron | No Railway cron schedule was present for the API. The active scheduled alert invocation is GitHub Actions. |
| Redpanda / ClickHouse | Not provisioned in the discovered Railway production project. Their repository support and Compose definitions are not production evidence. |

## Vercel-reference classification

| Reference | Classification | Evidence |
| --- | --- | --- |
| [`frontend/vercel.json`](../frontend/vercel.json) | **Active frontend production and API-edge routing** | Public headers, production GitHub deployment record, and host rewrite. |
| [`frontend/README.md`](../frontend/README.md) | **Frontend-only production indication** | Describes Vercel frontend and Railway infrastructure; public routing supports it. |
| Vercel preview-origin support in backend | **Preview deployment support** | It permits Vercel preview frontend origins; it does not locate the backend runtime. |
| Vercel claims in [`burnlens_cloud/README.md`](../burnlens_cloud/README.md) | **Legacy documentation** | The file labels older deployment instructions historical and conflicts with verified Railway backend runtime. |
| Azure-pipeline comment that Vercel watches GitHub | **Repository indication** | Accurate for frontend deployment intent; incomplete for the separately triggered Railway backend workflow. |

## AWS Terraform classification

**Classification: reference enterprise template, not verified active production IaC.**

* [`deploy/terraform/main.tf`](../deploy/terraform/main.tf#L1) is an enterprise customer template, not a verified account deployment definition.
* Terraform validation fails before provider planning: `main.tf`, `variables.tf`, and `outputs.tf` begin with Python-style triple-quoted text, which is invalid HCL; `main.tf` also duplicates an ECS task-definition argument.
* It defines an intended VPC, ALB, ECS/Fargate, RDS, S3, and CloudWatch model, but no Redpanda, ClickHouse, event-identity streaming path, state backend, migration execution, or CI/CD invocation.
* Read-only AWS identity access was available, but ECS inventory access was denied. There is no repository or platform evidence that its resources serve `burnlens.app` or `api.burnlens.app`.

AWS is therefore not required evidence for the current production authority decision. It must not be treated as an executable or deployed production source of truth.

## Live-version record

| Component | Evidence | Result |
| --- | --- | --- |
| Local checkout | Git `main` is `94491f271b894945f5225cf9d20d5424c1e6de27`, dated 2026-07-23. | **Verified local repository state.** |
| Frontend | GitHub/Vercel production deployment records the same SHA. | **Verified deployed frontend SHA.** |
| Backend | Active Railway deployment was created 2026-07-20 16:22:30 UTC with image digest beginning `sha256:d259e4cff969`. | **Verified image/deployment identity.** |
| Backend source SHA | Successful Railway workflow `29759144642` deployed `6f0f22615821f6a76b5424077444618700012618` just before the active deployment. | **Inference only.** |
| Database engine | Railway PostgreSQL service reports template image version 18. | **Verified service image version; not an application migration level.** |
| Runtime flags | No secret/variable values read. The event-identity work is uncommitted locally and necessarily absent from the active July deployment. | **Event identity is not live; all other flag values unknown.** |

## Live persistence and operational path

```text
Cloud ingest request
  -> Vercel API host rewrite
  -> Railway FastAPI burnlens-proxy (one instance)
  -> Railway PostgreSQL canonical storage (inferred DATABASE_URL binding)
  -> PostgreSQL dashboard queries (inferred; no deployed ClickHouse/Redpanda)
  -> export persistence: unknown
```

The application expects PostgreSQL through `DATABASE_URL` ([`config.py`](../burnlens_cloud/config.py#L9)) and initializes an async connection pool in [`database.py`](../burnlens_cloud/database.py). Existing cloud code has startup DDL; the active production migration process cannot be verified from the workflow or Railway deployment metadata. Application retention code exists, but its scheduled execution and database backup policy are **unknown**.

## Monitoring and ownership

| Area | Evidence / required role |
| --- | --- |
| Application health | Public `/health` and `/api/status` endpoints are operational. |
| Deployment evidence | GitHub Actions and Railway deployment history are available. |
| Infrastructure monitoring | No provisioned metrics/alarms, notification destination, or on-call ownership was found in the checked-in Railway deployment model. Railway log capability exists, but alert configuration was not evidenced. |
| Deployment owner | Required: Railway project deployer and GitHub Actions production-environment maintainer. Named owner unknown. |
| Database owner | Required: Railway PostgreSQL administrator responsible for backups, access, and migrations. Named owner unknown. |
| Incident / rollback approver | Required: production-change approver with Railway deployment rollback authority. Unknown. |
| Security / secrets owner | Required: owner of Railway variables and GitHub secrets/environments. Unknown. |

## Authorized operator evidence packs

Never paste secret values, database URLs, tokens, or account identifiers into tickets or this document.

### Railway (production project member; read-only)

```sh
# Inventory, region, service domains, replica count, volumes, and active deployments.
railway status --json
railway deployment list --service burnlens-proxy --environment production --json
railway deployment list --service Postgres --environment production --json
```

In the Railway UI, capture redacted screenshots or an export of:

1. Production project/environment and both service settings.
2. API deployment source commit/deployment ID, replica count, region, health check, restart, and pre-deploy command.
3. Variable **names and reference bindings only**; do not use CLI variable listing if it prints values.
4. PostgreSQL connection/binding metadata, backup/PITR policy, storage use, and maintenance settings.
5. Redacted system/deployment logs and service health. Do not export request bodies or credentials.

### GitHub (repository read access)

```sh
gh api 'repos/sairintechnologycom/burnlens/actions/workflows/deploy-railway.yml/runs?per_page=20'
gh api 'repos/sairintechnologycom/burnlens/actions/workflows/cron-evaluate-alerts.yml/runs?per_page=20'
gh api 'repos/sairintechnologycom/burnlens/deployments?environment=production&per_page=50'
gh api 'repos/sairintechnologycom/burnlens/environments'
```

In GitHub Settings, a repository administrator should record environment protection rules, required reviewers, and secret/variable **names only**. The command pack deliberately does not read secrets.

### AWS (only if AWS later becomes a proven target)

Use the read-only inventory matrix in [`EVENT_IDENTITY_DEPLOYMENT_PARITY.md`](EVENT_IDENTITY_DEPLOYMENT_PARITY.md). Do not request secret-value access. AWS inventory is not a gate for the current Railway production topology.

## Conflicting-documentation register and corrections to make later

| Conflict | Current truth | Recommended correction (not applied in this workstream) |
| --- | --- | --- |
| Backend Vercel deployment instructions | Backend runs on Railway; Vercel fronts the frontend/API host rewrite. | Mark backend Vercel instructions historical and link this record. |
| AWS Terraform portrayed as deployable platform | It is invalid and unverified template code. | Label it explicitly as a non-production reference; do not advertise it as deployment IaC until repaired and adopted. |
| Redpanda/ClickHouse Compose support | Compose-only; absent from Railway production project. | Label as local/enterprise topology only, not current production. |
| "Railway cron" source commentary | GitHub Actions calls the cron endpoint on schedule. | Describe GitHub Actions as scheduler and Railway as endpoint host. |
| Azure mirror comment | It explains Vercel source flow but omits Railway's path-filtered deploy workflow. | Document independent frontend and backend deployment triggers. |
| Repository deployment completeness | Essential Railway settings live in the console. | Add a non-secret deployment manifest/runbook recording required console state. |

## Event-identity initial-target compatibility

The proposed initial target is compatible **in principle** with the verified topology:

```text
Cloud ingest -> Railway FastAPI -> Railway PostgreSQL canonical cost + identity ledger
                               -> PostgreSQL dashboards
STREAMING_ENABLED=false; EVENT_IDENTITY_ENABLED=false by default
```

It matches the live one-instance, PostgreSQL-only deployment and does not require deploying absent Redpanda or ClickHouse infrastructure. It is not an authorization to enable or deploy event identity. Before any bounded internal-workspace canary, the following facts must be evidenced: deployed code/version; Railway variable and allowlist configuration; versioned migration operator/rollback process; database backup/recovery owner; and monitoring/alert ownership. A single instance permits only a bounded canary; it proves neither HA nor rolling deployment.

## Unresolved access dependencies

1. Railway read-only console evidence for variable names/bindings, exact backend commit, backup policy, migration history, and log/alert configuration.
2. GitHub environment administrator evidence for production-change approvers and secret/variable metadata.
3. Named owners for deployment, database, security, monitoring, incident response, and rollback.
4. A redacted database metadata report establishing connection endpoint types, active migration level, storage capacity, and retention/backup configuration.
5. Vercel project/DNS ownership evidence if domain or TLS change authority is needed.

## Decision basis

The serving frontend, API route, backend platform/service, region, replica count, active image identity, and live PostgreSQL service are now directly evidenced. The deployment authority remains incomplete because the actual backend source SHA, runtime configuration, database binding/backup/migration state, monitoring ownership, rollback authority, and console-managed configuration are not yet evidenced.

**PRODUCTION DEPLOYMENT AUTHORITY PARTIALLY ESTABLISHED**
