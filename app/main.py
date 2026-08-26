from contextlib import asynccontextmanager
import base64
import hashlib
import hmac
import json
import time
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from app.config import Settings, get_settings
from app.api.dependencies import build_container
from app.api.routes_generate import router as generate_router
from app.api.routes_runs import router as runs_router
from app.api.routes_system import router as system_router
from app.api.routes_provider_config import router as provider_config_router
from app.api.routes_character_templates import router as character_templates_router


COOKIE_NAME = "ai_fashion_session"
SESSION_SECONDS = 24 * 60 * 60


def _session_key(username: str, password: str, session_secret: str = "") -> bytes:
    material = session_secret or f"ai-fashion-webui\0{username}\0{password}"
    return hashlib.sha256(material.encode("utf-8")).digest()


def create_session(username: str, password: str, session_secret: str = "") -> str:
    payload = json.dumps({"sub": username, "exp": int(time.time()) + SESSION_SECONDS}, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=")
    signature = hmac.new(_session_key(username, password, session_secret), encoded, hashlib.sha256).digest()
    return f"{encoded.decode()}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def verify_session(token: str | None, username: str, password: str, session_secret: str = "") -> bool:
    if not token:
        return False
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected = hmac.new(_session_key(username, password, session_secret), encoded.encode(), hashlib.sha256).digest()
        supplied = base64.urlsafe_b64decode(supplied_signature + "=" * (-len(supplied_signature) % 4))
        if not hmac.compare_digest(expected, supplied):
            return False
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        return payload.get("sub") == username and int(payload.get("exp", 0)) > int(time.time())
    except (ValueError, TypeError, json.JSONDecodeError):
        return False


class LoginRequest(BaseModel):
    username: str
    password: str


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    container = build_container(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        container.runs.mark_interrupted()
        await container.runner.start()
        yield
        await container.runner.stop()

    app = FastAPI(title="AI Fashion Video Director", version="0.1.0", lifespan=lifespan)
    app.state.container = container
    public_auth_paths = {"/api/v1/auth/login", "/api/v1/auth/session", "/api/v1/auth/logout"}

    def is_protected_request(request: Request) -> bool:
        path = request.url.path
        api_path = path.removeprefix("/api/v1").removeprefix("/api/v4")
        if path.startswith(("/media", "/docs", "/redoc", "/openapi.json")):
            return True
        if api_path.startswith("/runs"):
            return True
        if api_path == "/generate":
            return True
        if api_path.startswith("/provider-config") and api_path != "/provider-config/catalog":
            return True
        if api_path.startswith(("/runtime-config", "/settings")):
            return True
        return False

    @app.middleware("http")
    async def require_webui_session(request: Request, call_next):
        protected = is_protected_request(request)
        if (
            settings.webui_auth_enabled
            and protected
            and request.url.path not in public_auth_paths
            and request.method != "OPTIONS"
            and not verify_session(
                request.cookies.get(COOKIE_NAME),
                settings.webui_username,
                settings.webui_password,
                settings.webui_session_secret,
            )
        ):
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        return await call_next(request)

    app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    @app.post("/api/v1/auth/login")
    async def login(payload: LoginRequest, request: Request):
        valid = (
            not settings.webui_auth_enabled
            or (
                hmac.compare_digest(payload.username, settings.webui_username)
                and hmac.compare_digest(payload.password, settings.webui_password)
            )
        )
        if not valid:
            return JSONResponse({"detail": "用户名或密码错误"}, status_code=401)
        response = JSONResponse({"authenticated": True, "username": settings.webui_username})
        response.set_cookie(
            COOKIE_NAME,
            create_session(settings.webui_username, settings.webui_password, settings.webui_session_secret),
            max_age=SESSION_SECONDS,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
            path="/",
        )
        return response

    @app.get("/api/v1/auth/session")
    async def auth_session(request: Request):
        authenticated = not settings.webui_auth_enabled or verify_session(
            request.cookies.get(COOKIE_NAME), settings.webui_username, settings.webui_password, settings.webui_session_secret
        )
        return {"authenticated": authenticated, "username": settings.webui_username if authenticated else None}

    @app.post("/api/v1/auth/logout")
    async def logout():
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(COOKIE_NAME, path="/")
        return response
    app.include_router(generate_router, prefix="/api/v1")
    app.include_router(generate_router, prefix="/api/v4")
    app.include_router(runs_router, prefix="/api/v1")
    app.include_router(system_router, prefix="/api/v1")
    app.include_router(provider_config_router, prefix="/api/v1")
    app.include_router(provider_config_router, prefix="/api/v4")
    app.include_router(character_templates_router, prefix="/api/v1")
    app.mount("/media", StaticFiles(directory=str(settings.workspace_dir)), name="media")

    @app.get("/health")
    async def health():
        return {"status": "ok", "provider_mode": settings.provider_mode}
    return app


app = create_app()
