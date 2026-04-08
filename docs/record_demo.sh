#!/usr/bin/env bash
# record_demo.sh — Fire sample API calls through BurnLens for demo screenshots.
#
# Prerequisites:
#   pip install burnlens
#   export OPENAI_API_KEY=sk-...
#
# Usage:
#   bash docs/record_demo.sh

set -euo pipefail

PORT=8420
PROXY="http://127.0.0.1:${PORT}/proxy/openai/v1/chat/completions"

echo "==> Starting BurnLens..."
burnlens start --no-env &
BURNLENS_PID=$!
sleep 2

# Ensure cleanup on exit
trap "echo '==> Stopping BurnLens...'; kill $BURNLENS_PID 2>/dev/null; wait $BURNLENS_PID 2>/dev/null" EXIT

echo "==> Sending 5 sample requests..."

# 1. Chat feature, backend team
curl -s "$PROXY" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "X-BurnLens-Tag-Feature: chat" \
  -H "X-BurnLens-Tag-Team: backend" \
  -H "X-BurnLens-Tag-Customer: acme-corp" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"Say hello in one word."}]}' \
  -o /dev/null
echo "  [1/5] chat / backend / acme-corp (gpt-4o-mini)"

# 2. Search feature, backend team
curl -s "$PROXY" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "X-BurnLens-Tag-Feature: search" \
  -H "X-BurnLens-Tag-Team: backend" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"What is the capital of France? One word."}]}' \
  -o /dev/null
echo "  [2/5] search / backend (gpt-4o)"

# 3. Summarize feature, data team
curl -s "$PROXY" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "X-BurnLens-Tag-Feature: summarize" \
  -H "X-BurnLens-Tag-Team: data" \
  -H "X-BurnLens-Tag-Customer: globex" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"Summarize: The quick brown fox jumps over the lazy dog."}]}' \
  -o /dev/null
echo "  [3/5] summarize / data / globex (gpt-4o-mini)"

# 4. Chat feature, frontend team (larger prompt)
curl -s "$PROXY" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "X-BurnLens-Tag-Feature: chat" \
  -H "X-BurnLens-Tag-Team: frontend" \
  -d '{"model":"gpt-4o","messages":[{"role":"system","content":"You are a helpful assistant."},{"role":"user","content":"Explain recursion in one sentence."}]}' \
  -o /dev/null
echo "  [4/5] chat / frontend (gpt-4o)"

# 5. Code review feature, backend team
curl -s "$PROXY" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "X-BurnLens-Tag-Feature: code-review" \
  -H "X-BurnLens-Tag-Team: backend" \
  -H "X-BurnLens-Tag-Customer: acme-corp" \
  -d '{"model":"gpt-3.5-turbo","messages":[{"role":"user","content":"Review: def add(a,b): return a+b"}]}' \
  -o /dev/null
echo "  [5/5] code-review / backend / acme-corp (gpt-3.5-turbo)"

echo ""
echo "==> Done! Open http://127.0.0.1:${PORT}/ui and take a screenshot."
echo "    Press Ctrl+C to stop BurnLens."

# Wait so the user can take the screenshot
wait $BURNLENS_PID
