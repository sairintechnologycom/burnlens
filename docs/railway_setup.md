# Deploying BurnLens on Railway

## Prerequisites

- A [Railway](https://railway.app) account
- A GitHub fork of the BurnLens repository
- At least one AI provider API key (OpenAI, Anthropic, or Google)

## Step-by-step deployment

### 1. Create a Railway project

1. Go to [Railway Dashboard](https://railway.app/dashboard)
2. Click **New Project** > **Deploy from GitHub repo**
3. Select your forked BurnLens repository

### 2. Create a persistent volume

SQLite requires a persistent filesystem. Railway containers are ephemeral, so the database must live on a Volume.

1. In your Railway service, click **+ New** > **Volume**
2. Set the mount path to `/data`
3. Railway will attach the volume to your service automatically

**Important:** Without a volume, your database will be wiped on every deploy.

### 3. Set environment variables

In your Railway service settings, add these environment variables:

| Variable | Value | Required |
|----------|-------|----------|
| `PORT` | `8420` | Set automatically by Railway |
| `BURNLENS_DB_PATH` | `/data/burnlens.db` | Yes |
| `OPENAI_API_KEY` | `sk-...` | At least one provider key |
| `ANTHROPIC_API_KEY` | `sk-ant-...` | At least one provider key |
| `GOOGLE_API_KEY` | `AI...` | At least one provider key |
| `ALLOWED_ORIGINS` | `https://your-app.up.railway.app` | Recommended |
| `LOG_LEVEL` | `info` | No (default: info) |

### 4. Deploy

Railway auto-deploys on push to your main branch. The build uses Nixpacks (auto-detected from `pyproject.toml`).

### 5. Verify

Once deployed, check the health endpoint:

```bash
curl https://your-app.up.railway.app/health
```

Expected response:
```json
{"status": "ok", "version": "0.3.1", "db": "connected"}
```

## Configuring your SDK

Point your AI SDK to the Railway-hosted proxy:

```bash
export OPENAI_BASE_URL=https://your-app.up.railway.app/proxy/openai/v1
export ANTHROPIC_BASE_URL=https://your-app.up.railway.app/proxy/anthropic
```

## Backup strategy

- Railway Volumes persist across deploys and restarts
- Volumes do NOT survive volume deletion
- For backups, periodically use `burnlens export` to download CSV data
- Consider `burnlens login` to enable cloud sync to burnlens.app for offsite backup

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Health check failing | Ensure `BURNLENS_DB_PATH` points to the volume mount (`/data/...`) |
| Database lost on redeploy | Attach a Volume mounted at `/data` |
| 502 errors | Check Railway logs; ensure provider API keys are set |
| CORS errors | Set `ALLOWED_ORIGINS` to your frontend domain |
