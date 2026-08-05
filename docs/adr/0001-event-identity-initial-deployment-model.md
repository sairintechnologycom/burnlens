# ADR 0001: Use PostgreSQL-only identity for the first deployed canary

**Status:** Proposed — requires deployment-owner approval.

## Context

The repository contains three incompatible deployment descriptions: the active cloud GitHub workflow deploys `burnlens-proxy` to Railway; the cloud README describes historic Vercel behavior; and `deploy/terraform` is an enterprise AWS template. The AWS template creates Aurora PostgreSQL, one ECS API task, an ALB, S3, and CloudWatch Logs. It does not create or reference Redpanda, ClickHouse, stream credentials, identity topics, a worker, CloudWatch alarms, or an event-identity feature flag.

The application can run with `STREAMING_ENABLED=false`; dashboard endpoints then use PostgreSQL. The cost is calculated before cloud ingest and PostgreSQL remains the financial record of authority.

## Decision

For the first deployed internal event-identity canary, choose **Option A: PostgreSQL-only event identity** and **Model 3: one API task, streaming disabled**.

This is deliberately not a rolling-deployment or high-availability claim. It is a bounded internal canary model: apply additive PostgreSQL migrations, deploy new code with `EVENT_IDENTITY_ENABLED=false`, preserve no-ID clients, then enable an approved workspace allowlist only after the required code/config support exists. The feature must be disabled to roll back; additive data remains.

## Alternatives

| Option | Repository change | Operational risk | Time to trustworthy canary |
| --- | --- | --- | --- |
| A. PostgreSQL-only | allowlist, migration runner, structured metrics/alarm extraction, deployment config | Lowest; no broker/outbox/ClickHouse dependency | Shortest |
| B. Full streaming identity | all of A plus broker/ClickHouse ownership, network paths, auth, topic/MV lifecycle, worker/claiming, lag/reconciliation monitoring | High; absent from AWS IaC and current deployed inventory is unknown | Blocked on infrastructure parity |

Option B is required only when production dashboards demonstrably depend on ClickHouse or PostgreSQL capacity evidence requires streaming. Compose-only Redpanda/ClickHouse is not production evidence.

## Consequences

- Identity-bearing records are idempotent in PostgreSQL; cost is never recalculated.
- The outbox is not exercised in this canary because streaming remains disabled.
- A global feature flag alone is insufficient: a workspace allowlist is a required follow-up before enablement.
- The one-task model cannot certify mixed-version, rolling replacement, concurrent draining, or zero-interruption deployment. Those are separate prerequisites for Option B or multi-task operation.
- Do not approve Workload/Run work from this ADR.
