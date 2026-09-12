# Post-Phase Validation Report: Phase 0 (BL-BASELINE)

**PHASE**: Phase 0 — Baseline & Compatibility Certification (BL-BASELINE)  
**BUILD**: v2026.09-cert  
**COMMIT**: `30b821ddb206d9b7b30bd2d1fcfbcc3754bac7ef`  
**ENVIRONMENT**: macOS (aarch64) / Python 3.12.13 / pytest 9.0.3  

---

## Metric & Gate Assessment

* **FUNCTIONAL STATUS**: PASS
* **COMPATIBILITY**: PASS
* **SECURITY**: PASS
* **DATA RECONCILIATION**: PASS
* **E2E**: PASS
* **PERFORMANCE**: PASS (2,198 tests in 117.51s, core baseline 201 tests in 9.56s)
* **ROLLBACK**: TESTED (Stateless ledger compatibility fixtures and SQLite rollback verified)

---

## Findings & Invariants Verified

1. **Pricing & Usage Determinism (Layer 1)**:
   - Canonical calculations for `gpt-4o`, `claude-3-5-sonnet-20241022`, and `gemini-1.5-pro` verified to 4+ decimal places.
   - Cache hit/read/write deductions confirmed strictly deterministic.
2. **Schema & API Contract Stability (Layer 2)**:
   - API schemas SHA-256 hash verified: `bb0ca93a626bc88e32cad6cf2b476d9afd0202939eda5161051e9b4d2b7427a0`.
   - Canonical database tables verified: `requests`, `outcomes`, `outcome_history`, `waste_findings`, `ai_assets`, `provider_signatures`, `discovery_events`, `anomaly_events`.
3. **Ledger Ingestion & Outcomes Integration (Layer 3)**:
   - Zero-drift ingestion reconciliation verified: 3 baseline requests totaling $0.0303 USD, 7,000 input tokens, 1,800 output tokens.
   - Outcome idempotency and correlation to `workflow_id` verified with `Outcome` entity.
4. **Security Boundaries (Layer 4)**:
   - Workspace isolation verified: queries scoped to `ws_alpha` cannot observe or aggregate records from `ws_beta`.
5. **E2E Golden Baseline Replay Invariance (Layer 5)**:
   - Fixture replay preserves exact canonical identity, cost, and tag aggregation across runs.

---

## Open Risks
* None. Full suite regression run confirmed zero breaking changes across existing 2,198 unit/integration tests.

## Blockers
* None. Prerequisite for Phase 1 (BL-AE-001) is fully satisfied.

---

## Evidence Artifacts
* Test Suite: [`tests/test_phase0_baseline_certification.py`](../../tests/test_phase0_baseline_certification.py)
* Manifest: [`tests/fixtures/baseline/baseline_manifest.json`](../../tests/fixtures/baseline/baseline_manifest.json)
* Fixtures: [`tests/fixtures/baseline/representative_events.json`](../../tests/fixtures/baseline/representative_events.json)

---

## Verdict
**CERTIFIED**
