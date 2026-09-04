#!/usr/bin/env bash
# Isolated public-route sensors for CI.
#
# BUILD_FAILURE          production export did not emit expected files
# SERVER_START_FAILURE   static server did not become ready
# PAGE_ASSERTION_FAILURE Playwright public-route assertions failed
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PORT="${PW_PORT:-3500}"
HOST="127.0.0.1"
BASE_URL="http://${HOST}:${PORT}"

classify() {
  echo "::error::$1"
  echo "$1" >&2
  exit 1
}

echo "==> BUILD SENSOR"
export NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-https://api.example.test}"
if ! npm run build; then
  classify "BUILD_FAILURE"
fi

if [[ ! -d out ]] || [[ ! -f out/index.html ]]; then
  classify "BUILD_FAILURE"
fi
# Next export emits either out/demo.html or out/demo/index.html.
if [[ ! -f out/demo.html ]] && [[ ! -f out/demo/index.html ]]; then
  echo "expected public route output missing: demo" >&2
  classify "BUILD_FAILURE"
fi
if [[ ! -f out/scan.html ]] && [[ ! -f out/scan/index.html ]]; then
  echo "expected public route output missing: scan" >&2
  classify "BUILD_FAILURE"
fi
echo "BUILD SENSOR: out/ exists with public route HTML"

echo "==> SERVER START SENSOR"
node scripts/serve-static-export.mjs out "$PORT" "$HOST" &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT

ready=0
for _ in $(seq 1 30); do
  if node -e "fetch('${BASE_URL}/').then((r) => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"; then
    ready=1
    break
  fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    classify "SERVER_START_FAILURE"
  fi
  sleep 1
done
if [[ "$ready" -ne 1 ]]; then
  classify "SERVER_START_FAILURE"
fi
echo "SERVER START SENSOR: ${BASE_URL} ready"

echo "==> BROWSER SENSOR"
export PW_EXTERNAL_SERVER=1
export PW_PROD=1
export BASE_URL
export CI="${CI:-1}"
if ! npx playwright test tests/e2e/public-routes.spec.ts --project=chromium --reporter=list; then
  classify "PAGE_ASSERTION_FAILURE"
fi
echo "BROWSER SENSOR: public-routes passed"

echo "==> DASHBOARD BROWSER SENSOR"
if ! npx playwright test tests/e2e/dashboard-certification.spec.ts --project=chromium --reporter=list; then
  classify "PAGE_ASSERTION_FAILURE"
fi
echo "DASHBOARD BROWSER SENSOR: dashboard-certification passed"
