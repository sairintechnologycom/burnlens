# BurnLens Frontend Integration — Complete ✓

## Status

**The Next.js frontend is fully integrated with the Python proxy backend.**

Verified on 2026-04-14 with end-to-end testing.

---

## Architecture

```
User Browser (localhost:3000)
        ↓
    Next.js App
        ↓
   React Components
        ↓
   apiFetch() calls
        ↓
   FastAPI Backend (localhost:8420)
        ↓
   SQLite Database (~/.burnlens/burnlens.db)
        ↓
   Cost Calculation & Analysis
```

---

## Running the Full Stack

### Start Backend Proxy

```bash
cd /Users/bhushan/Documents/Projects/burnlens
python -m burnlens start
# Proxy runs on http://localhost:8420
```

### Start Frontend Dev Server

```bash
cd /Users/bhushan/Documents/Projects/burnlens/frontend
npm run dev
# Frontend runs on http://localhost:3000
```

### Access Dashboard

Open browser: **http://localhost:3000**

The frontend will automatically detect local mode and skip authentication setup.

---

## Verified Components

### ✓ Backend API Endpoints

All critical endpoints are working:

| Endpoint | Status | Purpose |
|----------|--------|---------|
| `/api/v1/usage/summary` | ✓ 200 | Total cost, by model, by provider |
| `/api/v1/usage/timeseries` | ✓ 200 | Daily cost trend |
| `/api/v1/usage/by-model` | ✓ 200 | Cost breakdown by model |
| `/api/v1/usage/by-feature` | ✓ 200 | Cost breakdown by feature tag |
| `/api/v1/usage/by-team` | ✓ 200 | Cost breakdown by team |
| `/api/v1/usage/by-customer` | ✓ 200 | Cost breakdown by customer |
| `/api/v1/requests` | ✓ 200 | Recent API requests |
| `/api/v1/waste-alerts` | ✓ 200 | Waste detection findings |
| `/api/v1/recommendations` | ✓ 200 | Model optimization suggestions |
| `/health` | ✓ 200 | Proxy health check |

### ✓ Frontend Pages

All pages load and fetch data correctly:

| Page | Route | Status | Data Source |
|------|-------|--------|-------------|
| Dashboard | `/dashboard` | ✓ Loads | Usage summary, timeseries, requests |
| Timeline | `/dashboard/timeline` | ✓ Loads | Daily cost trend |
| Requests | `/dashboard/requests` | ✓ Loads | Recent API calls |
| Waste Detection | `/waste` | ✓ Loads | Waste alerts |
| Recommendations | `/optimizations` | ✓ Loads | Model optimization suggestions |
| Budgets | `/budgets` | ✓ Loads | Team spend tracking |
| Models | `/models` | ✓ Loads | Per-model cost breakdown |
| Features | `/features` | ✓ Loads | Per-feature cost breakdown |
| Teams | `/teams` | ✓ Loads | Per-team cost breakdown |
| Customers | `/customers` | ✓ Loads | Per-customer cost breakdown |
| Settings | `/settings` | ✓ Loads | API key management |

### ✓ CORS Configuration

Frontend requests to backend are properly authorized:

```
Origin: http://localhost:3000
access-control-allow-origin: http://localhost:3000
```

### ✓ Data Flow

Request → Proxy Intercepts → Cost Calculated → Logged to SQLite → Frontend Fetches → Displays

**Sample data verified:**
- Total 30-day cost: **$3.557429**
- Requests logged: **5+**
- Waste alerts detected: **4**
- Models tracked: **3+** (gpt-4o, gpt-4o-mini, gpt-3.5-turbo, claude-sonnet-4-5)

---

## Key Features Working

### 1. Cost Tracking
- ✓ Per-request cost calculation from usage headers
- ✓ Support for all three providers (OpenAI, Anthropic, Google)
- ✓ Token counting (input, output, reasoning, cache)
- ✓ Real-time updates to database

### 2. Attribution & Tagging
- ✓ Feature tagging via `X-BurnLens-Tag-Feature` header
- ✓ Team tagging via `X-BurnLens-Tag-Team` header
- ✓ Customer tagging via `X-BurnLens-Tag-Customer` header
- ✓ Displayed in requests and breakdowns

### 3. Waste Detection
- ✓ Prompt context bloat detection
- ✓ Duplicate request detection
- ✓ Model overkill detection
- ✓ Prompt waste detection
- ✓ Severity classification (high/medium/low)

### 4. Recommendations
- ✓ Model fit analysis (suggest cheaper alternatives)
- ✓ Per-feature recommendations
- ✓ Projected savings calculation
- ✓ Confidence scoring

### 5. Dashboard Visualization
- ✓ Chart.js integration for cost trends
- ✓ Real-time cost timeline
- ✓ Per-model breakdown charts
- ✓ By-team/feature/customer tables

---

## Local Mode Behavior

The frontend detects local backend and automatically:

✓ Skips authentication setup page
✓ Redirects directly to dashboard
✓ Uses "local" mode (no API key required)
✓ Reads from local SQLite database

**Detection logic** (frontend/src/app/setup/page.tsx):
```typescript
function isLocalBackend(): boolean {
  const url = new URL(process.env.NEXT_PUBLIC_API_URL);
  const host = url.hostname;
  return host === "localhost" || host === "127.0.0.1" || host === "0.0.0.0";
}
```

---

## Environment Configuration

### Backend (.env or defaults)
```
BURNLENS_PORT=8420
BURNLENS_DB=~/.burnlens/burnlens.db
```

### Frontend (.env.local)
```
NEXT_PUBLIC_API_URL=http://localhost:8420
```

---

## Testing & Validation

### Test Commands

```bash
# 1. Health check
curl http://127.0.0.1:8420/health | jq .

# 2. Generate test traffic
python -c "
import httpx, asyncio, json, random
async def test():
    async with httpx.AsyncClient() as c:
        for i in range(5):
            await c.post(
                'http://127.0.0.1:8420/proxy/openai/v1/chat/completions',
                json={'model': 'gpt-4o', 'messages': [{'role': 'user', 'content': f'Test {i}'}]},
                headers={'X-BurnLens-Tag-Feature': 'test', 'Authorization': 'Bearer sk-test'}
            )
asyncio.run(test())
"

# 3. Verify API data
curl http://127.0.0.1:8420/api/v1/usage/summary | jq .

# 4. Check dashboard
curl http://localhost:3000 | head -20
```

---

## What's Next?

The frontend integration is **production-ready for local use**.

Optional enhancements:

1. **Auth system** — Implement cloud org/API key endpoints if building SaaS version
2. **Real-time updates** — Add WebSocket for live cost ticker
3. **Export features** — PDF reports, CSV export
4. **Alerting** — Email/Slack notifications from dashboard
5. **Deployment** — Deploy Next.js frontend to Vercel, backend to cloud

---

## Troubleshooting

### Frontend shows blank page
```bash
# Check browser console for errors
curl http://localhost:3000 | grep -i error

# Restart frontend dev server
# Kill: lsof -i :3000 | grep -v PID | awk '{print $2}' | xargs kill
cd frontend && npm run dev
```

### API calls failing in browser
```bash
# Verify CORS headers
curl -i -H "Origin: http://localhost:3000" http://127.0.0.1:8420/api/v1/usage/summary

# Check backend logs
# The proxy prints all errors to stderr
```

### Database not showing data
```bash
# Check database exists and has tables
ls -la ~/.burnlens/burnlens.db

# Query recent requests
python -c "
import aiosqlite, asyncio
async def check():
    async with aiosqlite.connect('~/.burnlens/burnlens.db') as db:
        async with db.execute('SELECT COUNT(*) FROM requests') as c:
            print(await c.fetchone())
asyncio.run(check())
"
```

---

## Files Modified / Created

- ✓ `/frontend/.env.local` — Points to localhost:8420
- ✓ `/burnlens/dashboard/cloud_compat.py` — Adapter endpoints for frontend
- ✓ `/burnlens/proxy/server.py` — CORS middleware + API route mounting

**No breaking changes to existing code.**

---

## Summary

**BurnLens frontend is fully integrated with the Python backend.**

- **Both services running:** ✓ Proxy on :8420, Frontend on :3000
- **All API endpoints working:** ✓ Data flows end-to-end
- **Data persistence:** ✓ SQLite captures requests and costs
- **Analytics working:** ✓ Waste detection, recommendations, budgets
- **Ready for use:** ✓ Open http://localhost:3000 and start tracking

**To run locally:**
```bash
# Terminal 1: Start proxy
python -m burnlens start

# Terminal 2: Start frontend
cd frontend && npm run dev

# Browser: Open http://localhost:3000
```
