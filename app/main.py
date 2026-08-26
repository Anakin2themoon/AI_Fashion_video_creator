from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.config import Settings, get_settings
from app.api.dependencies import build_container
from app.api.routes_generate import router as generate_router
from app.api.routes_runs import router as runs_router
from app.api.routes_system import router as system_router
from app.api.routes_provider_config import router as provider_config_router
from app.api.routes_character_templates import router as character_templates_router


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
    app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
                       allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
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
