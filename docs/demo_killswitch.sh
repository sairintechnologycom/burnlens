#!/usr/bin/env bash
# docs/demo_killswitch.sh — CODE-2 daily hard-cap demo.
#
# Runs in a sandboxed config + DB, pins a $0.05 daily cap on a test key,
# fires real one-token requests through the proxy, and shows the 429
# response body when the kill-switch trips.
#
# Usage:
#   PROVIDER=openai    OPENAI_API_KEY=sk-…    ./docs/demo_killswitch.sh
#   PROVIDER=anthropic ANTHROPIC_API_KEY=sk-…  ./docs/demo_killswitch.sh
#
# Optional env: LABEL (default: demo-killswitch), CAP (default: 0.05),
# PORT (default: 8420), MODEL (provider-specific default).
#
# Requires: burnlens, curl, jq (jq is optional — falls back to raw cat).

set -euo pipefail

PROVIDER="${PROVIDER:-openai}"
LABEL="${LABEL:-demo-killswitch}"
CAP="${CAP:-0.05}"
PORT="${PORT:-8420}"

case "$PROVIDER" in
  openai)
    : "${OPENAI_API_KEY:?OPENAI_API_KEY env var required for PROVIDER=openai}"
    RAW_KEY="$OPENAI_API_KEY"
    MODEL="${MODEL:-gpt-4o-mini}"
    URL_PATH="/proxy/openai/v1/chat/completions"
    AUTH_HEADER="Authorization: Bearer $RAW_KEY"
    BODY="{\"model\":\"$MODEL\",\"max_tokens\":1,\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}"
    ;;
  anthropic)
    : "${ANTHROPIC_API_KEY:?ANTHROPIC_API_KEY env var required for PROVIDER=anthropic}"
    RAW_KEY="$ANTHROPIC_API_KEY"
    MODEL="${MODEL:-claude-haiku-4-5-20251001}"
    URL_PATH="/proxy/anthropic/v1/messages"
    AUTH_HEADER="x-api-key: $RAW_KEY"
    BODY="{\"model\":\"$MODEL\",\"max_tokens\":1,\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}"
    ;;
  *)
    echo "Unsupported PROVIDER='$PROVIDER' (expected: openai | anthropic)" >&2
    exit 1
    ;;
esac

SANDBOX="$(mktemp -d -t burnlens-demo-XXXXXX)"
CONFIG="$SANDBOX/burnlens.yaml"
DB="$SANDBOX/burnlens.db"
LOG="$SANDBOX/proxy.log"
PROXY_PID=""

cleanup() {
  if [[ -n "$PROXY_PID" ]] && kill -0 "$PROXY_PID" 2>/dev/null; then
    kill "$PROXY_PID" 2>/dev/null || true
    wait "$PROXY_PID" 2>/dev/null || true
  fi
  # Leave the sandbox on disk if the user wants to inspect it.
  if [[ "${KEEP_SANDBOX:-0}" != "1" ]]; then
    rm -rf "$SANDBOX"
  else
    echo "Sandbox kept at: $SANDBOX"
  fi
}
trap cleanup EXIT INT TERM

cat >"$CONFIG" <<EOF
db_path: $DB
port: $PORT
host: 127.0.0.1
log_level: WARNING
alerts:
  api_key_budgets:
    keys:
      $LABEL:
        daily_usd: $CAP
    reset_timezone: UTC
EOF

echo "================================================================"
echo " BurnLens daily-cap kill-switch demo"
echo "================================================================"
echo "  Provider:  $PROVIDER"
echo "  Model:     $MODEL"
echo "  Label:     $LABEL"
echo "  Daily cap: \$$CAP"
echo "  Sandbox:   $SANDBOX"
echo "================================================================"
echo

# 1. Register the test key.
burnlens key register --config "$CONFIG" \
  --label "$LABEL" --provider "$PROVIDER" --key "$RAW_KEY" >/dev/null
echo "✓ Registered '$LABEL' (raw key never written to disk)."

# 2. Boot the proxy in the background.
( burnlens start --config "$CONFIG" --no-env >"$LOG" 2>&1 ) &
PROXY_PID=$!

echo -n "✓ Proxy booting"
for _ in $(seq 1 50); do
  if curl -fsS "http://127.0.0.1:$PORT/api/summary" >/dev/null 2>&1; then
    echo " — up on http://127.0.0.1:$PORT"
    break
  fi
  echo -n "."
  sleep 0.2
done
if ! curl -fsS "http://127.0.0.1:$PORT/api/summary" >/dev/null 2>&1; then
  echo
  echo "❌ Proxy failed to boot. Tail:"
  tail -20 "$LOG"
  exit 1
fi
echo

# 3. Fire up to 10 real one-token requests until the 429 fires.
TRIPPED=0
for i in $(seq 1 10); do
  printf "  request %2d: " "$i"
  RESP_BODY="$SANDBOX/resp.$i.json"
  STATUS=$(curl -sS -o "$RESP_BODY" -w "%{http_code}" \
    -H "$AUTH_HEADER" \
    -H "content-type: application/json" \
    -H "anthropic-version: 2023-06-01" \
    -d "$BODY" \
    "http://127.0.0.1:$PORT$URL_PATH" || echo "000")

  if [[ "$STATUS" == "429" ]]; then
    echo "HTTP 429 — kill-switch fired"
    echo
    echo "🛑 429 response body:"
    if command -v jq >/dev/null 2>&1; then
      jq . "$RESP_BODY"
    else
      cat "$RESP_BODY"; echo
    fi
    TRIPPED=1
    break
  else
    echo "HTTP $STATUS"
  fi
  sleep 0.3
done

echo
if [[ "$TRIPPED" -eq 0 ]]; then
  echo "ℹ️  10 calls completed without tripping the cap — model + cap"
  echo "    combination didn't cross \$$CAP. Try a pricier model or a"
  echo "    smaller CAP, e.g. CAP=0.001 ./docs/demo_killswitch.sh"
  echo
fi

# 4. Show the per-key roll-up — same data the dashboard renders.
echo "📊 Today's spend (same payload as /api/keys-today):"
burnlens keys --config "$CONFIG"
echo

# 5. Hand-off to the dashboard for the screenshot.
echo "================================================================"
echo " ✅ Key blocked — open http://127.0.0.1:$PORT/ui to see the panel"
echo "================================================================"
echo "   📸 Screenshot tip: open the dashboard, scroll to the"
echo "      'API Keys — today's spend' card, capture the CRITICAL row"
echo "      with its 'Resets at 00:00 UTC' badge for the landing page GIF."
echo
echo "   The proxy stays up until you press Ctrl+C."
echo "   Set KEEP_SANDBOX=1 to retain the SQLite DB after exit."
echo

wait "$PROXY_PID"
