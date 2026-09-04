#!/usr/bin/env node
/**
 * Static-export server for Next.js `output: "export"` (distDir: out).
 *
 * Clean-URL mapping matches Vercel / `serve`: /demo -> out/demo.html.
 * Uses only Node built-ins so Playwright server-start does not hit the
 * network to fetch `serve`, and so the production build is not part of
 * the server-start timeout.
 *
 * Exit 2 = BUILD_FAILURE (export directory missing).
 * Exit 1 = SERVER_START_FAILURE.
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(process.argv[2] || "out");
const port = Number(process.argv[3] || 3500);
const host = process.argv[4] || "127.0.0.1";

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".ico": "image/x-icon",
  ".webp": "image/webp",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".txt": "text/plain; charset=utf-8",
  ".xml": "application/xml",
  ".map": "application/json",
};

function failBuild(message) {
  console.error(`BUILD_FAILURE: ${message}`);
  process.exit(2);
}

if (!fs.existsSync(root) || !fs.statSync(root).isDirectory()) {
  failBuild(`static export directory not found: ${root}. Run npm run build first.`);
}
if (!fs.existsSync(path.join(root, "index.html"))) {
  failBuild(`index.html missing under ${root}. Production build did not emit a static export.`);
}

function safeJoin(base, urlPath) {
  const decoded = decodeURIComponent((urlPath || "/").split("?")[0].split("#")[0]);
  const joined = path.normalize(path.join(base, decoded));
  const prefix = base.endsWith(path.sep) ? base : base + path.sep;
  if (joined !== base && !joined.startsWith(prefix)) return null;
  return joined;
}

function resolveFile(urlPath) {
  const target = safeJoin(root, urlPath);
  if (!target) return null;
  try {
    if (fs.existsSync(target) && fs.statSync(target).isFile()) return target;
    if (fs.existsSync(target) && fs.statSync(target).isDirectory()) {
      const index = path.join(target, "index.html");
      if (fs.existsSync(index) && fs.statSync(index).isFile()) return index;
    }
    const html = target.endsWith(".html") ? target : `${target}.html`;
    if (fs.existsSync(html) && fs.statSync(html).isFile()) return html;
  } catch {
    return null;
  }
  return null;
}

const server = http.createServer((req, res) => {
  const file = resolveFile(req.url || "/");
  if (!file) {
    res.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
    res.end("Not found");
    return;
  }
  const type = MIME[path.extname(file).toLowerCase()] || "application/octet-stream";
  res.writeHead(200, { "content-type": type });
  fs.createReadStream(file).pipe(res);
});

server.on("error", (err) => {
  console.error(`SERVER_START_FAILURE: ${err.message}`);
  process.exit(1);
});

server.listen(port, host, () => {
  console.log(`static export server listening on http://${host}:${port} root=${root}`);
});
