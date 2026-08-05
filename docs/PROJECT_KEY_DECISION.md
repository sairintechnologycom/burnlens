# Project key decision — Workstream 0D

Decision: **do not promote `app_id` to a canonical cloud Project key.**

`workspaces` is the cloud tenant and authorization boundary.  The local
`RequestRecord` can carry optional `app_id`, but cloud sync's allowlist does
not send it and cloud `request_records` does not retain it.  The only current
`project` field is optional discovery metadata on local `AiAsset`, not a
foreign key, billing scope, API contract, or frontend grouping.

Therefore `app_id` is not proven stable, tenant-scoped, or present across proxy,
scanner, direct cloud, and streaming ingestion paths.  It currently means an
application hint, not an approved billing boundary, organizational group, or
deployment.  It must not affect authorization.

For a future approved Workload/Run phase, introduce an explicit workspace-scoped
Project entity with a separately reviewed alias table for optional historical
`app_id` values.  A Workload should initially belong to one Project; support for
many-to-many membership should wait for a concrete product requirement.  Do not
backfill historical `app_id` values automatically: preserve them as unverified
aliases and require tenant-admin confirmation before any attribution use.
