# Cloudflare deployment

Production hostname: `https://aifactorycreator.org`

This application is published through a Cloudflare Tunnel and protected by its own signed-cookie WebUI authentication. Do not attach a Cloudflare Access self-hosted application to this hostname: visitors must reach the WebUI login page directly. The backend contains provider credentials and generation endpoints that can consume paid API quota, so port `8000` must not be exposed directly to the Internet.

## Required routing

Configure the tunnel rules in this order:

1. Hostname `aifactorycreator.org`, path `^/(api|media|health|docs|redoc|openapi\.json)(/.*)?$` → `http://127.0.0.1:8000`
2. Hostname `aifactorycreator.org`, no path → `http://127.0.0.1:3000`
3. Catch-all → HTTP 404

`config.example.yml` contains the equivalent configuration for a locally managed tunnel. Never commit the tunnel token, tunnel credentials JSON, API keys, or the real user profile path.

The deployed Windows host uses a remotely managed tunnel. Its ingress rules are stored in Cloudflare, while the connector receives only a token from a user-private file outside this repository. The connector is registered in the current user's Windows startup key so it reconnects after sign-in. On an administrator-managed host, installing `cloudflared` as a Windows service is preferred because it can start before interactive sign-in.

The current-user startup entry should also check ports `8000` and `3000` and start the FastAPI backend and static Web UI only when they are not already listening, so both origins recover after sign-in without creating duplicate processes.

Example current-user startup command (the token file itself must remain outside the repository):

```powershell
"C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel run --token-file "C:\Users\<user>\.cloudflared\ai-fashion-local.token"
```

## WebUI authentication

Set `WEBUI_AUTH_ENABLED=true`, `WEBUI_USERNAME`, and `WEBUI_PASSWORD` only in the ignored local `.env` file. The backend issues a signed HttpOnly, Secure cookie after login and protects API, media, and API documentation routes. Never commit the real password or session secret. The Cloudflare Zero Trust application list must not contain an Access application targeting `aifactorycreator.org`.

## Validation

Before starting the connector, verify locally:

```powershell
Invoke-WebRequest http://127.0.0.1:3000/ -UseBasicParsing
Invoke-RestMethod http://127.0.0.1:8000/health
```

For a locally managed tunnel, validate the configuration:

```powershell
cloudflared tunnel ingress validate
cloudflared tunnel ingress rule https://aifactorycreator.org/
cloudflared tunnel ingress rule https://aifactorycreator.org/api/v1/system/status
```

After publication, verify:

- `/` serves the WebUI login page directly over HTTPS without a Cloudflare Access redirect.
- An unauthenticated `/api/v1/system/status` request returns HTTP 401.
- A valid WebUI login sets an HttpOnly, Secure cookie.
- Authenticated `/api/v1/style-catalog` and `/api/v1/system/status` requests return JSON.
- Existing generated images and videos load from `/media/...`.
