#!/bin/bash
set -e

echo "=== BurnLens Local E2E Test ==="
echo ""

CLOUD_URL="http://localhost:8000"
PROXY_URL="http://localhost:8420"

# ── Preflight checks ──────────────────────────────────────────
echo "0. Preflight checks..."
if ! curl -sf "$CLOUD_URL/health" > /dev/null 2>&1; then
  echo "   FAIL: Cloud API not running at $CLOUD_URL"
  echo "   Run: cd packages/cloud && ENVIRONMENT=development burnlens-cloud"
  exit 1
fi
echo "   Cloud API: OK"

if ! docker exec burnlens-postgres-1 pg_isready -U burnlens -q 2>/dev/null; then
  echo "   FAIL: PostgreSQL not running"
  echo "   Run: docker compose up -d postgres redis"
  exit 1
fi
echo "   PostgreSQL: OK"

if ! docker exec burnlens-redis-1 redis-cli ping > /dev/null 2>&1; then
  echo "   FAIL: Redis not running"
  exit 1
fi
echo "   Redis: OK"
echo ""

# ── 1. Register an org ────────────────────────────────────────
echo "1. Registering org..."
RESPONSE=$(curl -sf -X POST "$CLOUD_URL/api/v1/orgs/register" \
  -H "Content-Type: application/json" \
  -d '{"name": "E2E Test Org", "email": "e2e@test.com"}')
API_KEY=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['api_key'])")
ORG_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['org_id'])")
echo "   API key: ${API_KEY:0:20}..."
echo "   Org ID:  $ORG_ID"
echo ""

# ── 2. Verify org profile ────────────────────────────────────
echo "2. Verifying org profile..."
PROFILE=$(curl -sf "$CLOUD_URL/api/v1/orgs/me" -H "X-API-Key: $API_KEY")
TIER=$(echo "$PROFILE" | python3 -c "import sys,json; print(json.load(sys.stdin)['tier'])")
if [ "$TIER" != "free" ]; then
  echo "   FAIL: Expected tier=free, got $TIER"
  exit 1
fi
echo "   PASS: tier=$TIER"
echo ""

# ── 3. Ingest test data directly (simulates sync) ────────────
echo "3. Ingesting test data via /api/v1/ingest..."
INGEST_RESP=$(curl -sf -X POST "$CLOUD_URL/api/v1/ingest" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "records": [
      {
        "timestamp": "2026-04-11T08:00:00Z",
        "provider": "openai",
        "model": "gpt-4o",
        "input_tokens": 500,
        "output_tokens": 200,
        "cost_usd": "0.0045",
        "duration_ms": 1200,
        "status_code": 200,
        "tag_feature": "chat",
        "tag_team": "engineering"
      },
      {
        "timestamp": "2026-04-11T08:01:00Z",
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "input_tokens": 1000,
        "output_tokens": 500,
        "cost_usd": "0.012",
        "duration_ms": 2300,
        "status_code": 200,
        "tag_feature": "code-review",
        "tag_team": "platform"
      },
      {
        "timestamp": "2026-04-11T08:02:00Z",
        "provider": "openai",
        "model": "gpt-4o-mini",
        "input_tokens": 200,
        "output_tokens": 100,
        "cost_usd": "0.0003",
        "duration_ms": 450,
        "status_code": 200,
        "tag_feature": "chat",
        "tag_team": "engineering"
      }
    ]
  }')
INSERTED=$(echo "$INGEST_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['inserted'])")
if [ "$INSERTED" != "3" ]; then
  echo "   FAIL: Expected 3 inserted, got $INSERTED"
  exit 1
fi
echo "   PASS: $INSERTED records inserted"
echo ""

# ── 4. Verify usage summary ──────────────────────────────────
echo "4. Checking usage summary..."
SUMMARY=$(curl -sf "$CLOUD_URL/api/v1/usage/summary?days=1" \
  -H "X-API-Key: $API_KEY")
REQUESTS=$(echo "$SUMMARY" | python3 -c "import sys,json; print(json.load(sys.stdin)['total_requests'])")
COST=$(echo "$SUMMARY" | python3 -c "import sys,json; print(json.load(sys.stdin)['total_cost'])")

if [ "$REQUESTS" -gt "0" ]; then
  echo "   PASS: $REQUESTS requests, \$$COST total cost"
else
  echo "   FAIL: No requests visible in cloud"
  exit 1
fi
echo ""

# ── 5. Verify by-feature endpoint ────────────────────────────
echo "5. Checking by-feature breakdown..."
FEATURES=$(curl -sf "$CLOUD_URL/api/v1/usage/by-feature?days=1" \
  -H "X-API-Key: $API_KEY")
FEATURE_COUNT=$(echo "$FEATURES" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")
if [ "$FEATURE_COUNT" -gt "0" ]; then
  echo "   PASS: $FEATURE_COUNT features found"
else
  echo "   FAIL: No feature breakdown"
  exit 1
fi
echo ""

# ── 6. Test tier enforcement (free → 402 on by-team) ─────────
echo "6. Testing tier enforcement..."
TEAM_CODE=$(curl -so /dev/null -w "%{http_code}" \
  "$CLOUD_URL/api/v1/usage/by-team?days=7" \
  -H "X-API-Key: $API_KEY")
if [ "$TEAM_CODE" = "402" ]; then
  echo "   PASS: Free tier correctly blocked from team breakdown (HTTP 402)"
else
  echo "   FAIL: Expected 402, got $TEAM_CODE"
  exit 1
fi
echo ""

# ── 7. Upgrade to team tier ───────────────────────────────────
echo "7. Upgrading to team tier via test-upgrade..."
curl -sf "$CLOUD_URL/api/v1/billing/test-upgrade?org_id=$ORG_ID&tier=team" > /dev/null
TEAM_CODE=$(curl -so /dev/null -w "%{http_code}" \
  "$CLOUD_URL/api/v1/usage/by-team?days=7" \
  -H "X-API-Key: $API_KEY")
if [ "$TEAM_CODE" = "200" ]; then
  echo "   PASS: Team tier unlocked correctly (HTTP 200)"
else
  echo "   FAIL: Expected 200 after upgrade, got $TEAM_CODE"
  exit 1
fi
echo ""

# ── 8. Verify team breakdown data ────────────────────────────
echo "8. Checking team breakdown data..."
TEAMS=$(curl -sf "$CLOUD_URL/api/v1/usage/by-team?days=1" \
  -H "X-API-Key: $API_KEY")
TEAM_COUNT=$(echo "$TEAMS" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")
if [ "$TEAM_COUNT" -gt "0" ]; then
  echo "   PASS: $TEAM_COUNT teams found"
else
  echo "   FAIL: No team data after upgrade"
  exit 1
fi
echo ""

# ── 9. Privacy check: no prompt content in cloud DB ──────────
echo "9. Privacy audit — checking for prompt content in cloud DB..."
PROMPT_HITS=$(docker exec burnlens-postgres-1 psql -U burnlens -d burnlens -t -A -c \
  "SELECT COUNT(*) FROM request_log WHERE
     tags_json::text LIKE '%prompt%'
     OR tags_json::text LIKE '%Hello%'
     OR tags_json::text LIKE '%content%'")
PROMPT_HITS=$(echo "$PROMPT_HITS" | tr -d '[:space:]')
if [ "$PROMPT_HITS" = "0" ]; then
  echo "   PASS: Zero prompt content found in cloud database"
else
  echo "   FAIL: Found $PROMPT_HITS rows with possible prompt content"
  exit 1
fi
echo ""

# ── 10. Webhook idempotency ──────────────────────────────────
echo "10. Testing webhook idempotency..."
curl -sf -X POST "$CLOUD_URL/api/v1/billing/webhook" \
  -H "Content-Type: application/json" \
  -d "{\"id\":\"e2e_wh_001\",\"event\":\"payment.succeeded\",\"metadata\":{\"org_id\":\"$ORG_ID\",\"tier\":\"enterprise\"}}" > /dev/null
REPLAY=$(curl -sf -X POST "$CLOUD_URL/api/v1/billing/webhook" \
  -H "Content-Type: application/json" \
  -d "{\"id\":\"e2e_wh_001\",\"event\":\"payment.succeeded\",\"metadata\":{\"org_id\":\"$ORG_ID\",\"tier\":\"enterprise\"}}")
REPLAY_STATUS=$(echo "$REPLAY" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
if [ "$REPLAY_STATUS" = "already_processed" ]; then
  echo "   PASS: Duplicate webhook correctly rejected"
else
  echo "   FAIL: Expected already_processed, got $REPLAY_STATUS"
  exit 1
fi
echo ""

# ── Summary ──────────────────────────────────────────────────
echo "==========================================="
echo "  All 10 E2E checks passed!"
echo "==========================================="
echo ""
echo "To test the frontend:"
echo "  1. cd frontend && npm run dev"
echo "  2. Open http://localhost:3000/setup"
echo "  3. Enter API key: $API_KEY"
echo ""
