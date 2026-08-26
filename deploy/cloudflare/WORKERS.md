# Cloudflare Workers deployment

This repository uses a hybrid Workers deployment because the generation backend needs long-running jobs, SQLite, persistent media files, and FFmpeg. Cloudflare Workers serves the WebUI at the edge and forwards backend paths to the existing Cloudflare Tunnel origin.

## Request routing

- `/`, frontend assets, and SPA routes: Cloudflare Workers Static Assets
- `/api/*`, `/media/*`, `/health`, `/docs/*`, `/redoc/*`, and `/openapi.json`: Worker proxy to `https://origin.aifactorycreator.org`
- `origin.aifactorycreator.org`: Cloudflare Tunnel to `http://127.0.0.1:8000` on the Windows host

The public site remains same-origin, so authentication cookies and generated-media downloads work without frontend environment changes.

## GitHub Workers Builds

Use these settings when connecting Cloudflare Workers Builds:

- Repository: `Anakin2themoon/AI_Fashion_video_creator`
- Production branch: `main`
- Worker name: `ai-fashion-video-creator`
- Root directory: repository root
- Build command: leave empty
- Deploy command: `npx wrangler deploy`

Cloudflare then deploys every push to `main`. The Worker configuration is in `wrangler.jsonc`; it contains no API keys or WebUI credentials.

## Local verification

```powershell
npm install
npm test
npx wrangler deploy --dry-run
pytest -q
```

## Full cloud migration boundary

The current FastAPI generation service cannot run unchanged in a free Worker. A later fully cloud-native migration would replace local SQLite and media storage with D1/R2, move durable job orchestration to Queues or Workflows, and replace or externalize FFmpeg processing. Cloudflare Containers can host the existing container shape more directly, but require a paid Workers plan and durable storage design.
