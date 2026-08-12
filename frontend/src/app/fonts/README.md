# Vendored fonts

Self-hosted so the production build has **no build-time network dependency**.

`next/font/google` fetches font metadata from Google while building. When a CI
runner could not reach it, Turbopack surfaced the failure as
`Module not found: Can't resolve '@vercel/turbopack-next/internal/font/google/font'`
rather than as a network error — reddening `deploy-railway`'s `verify` job and
`public-routes-smoke`, and blocking backend-only deploys that had nothing to do
with the frontend.

| File | Family | Weights |
|---|---|---|
| `Manrope-400-800.woff2` | Manrope (variable) | 400–800 |
| `DMMono-300/400/500.woff2` | DM Mono (static) | 300, 400, 500 |

These are the **latin** subsets, the same ones `subsets: ["latin"]` was
requesting before — not the full families, so the byte cost is unchanged.

Both are licensed under the SIL Open Font License 1.1; the license texts are
alongside the files (`OFL-Manrope.txt`, `OFL-DMMono.txt`) and must ship with
them.

## Updating

Re-fetch the same subsets and overwrite in place:

```bash
curl -sA "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0 Safari/537.36" \
  "https://fonts.googleapis.com/css2?family=Manrope:wght@400..800&family=DM+Mono:wght@300;400;500&display=swap"
```

Take the `src: url(...)` from each `/* latin */` block. A browser User-Agent is
required — Google serves ttf to unknown clients and woff2 only to modern ones.
