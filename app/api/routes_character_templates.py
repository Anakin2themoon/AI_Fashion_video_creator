from __future__ import annotations

from fastapi import APIRouter, Request


router = APIRouter(tags=["character-templates"])


@router.get("/character-templates")
async def list_character_templates(request: Request):
    container = request.app.state.container
    return {
        "source": container.character_templates.source,
        "templates": container.character_templates.list_public(),
    }


@router.get("/style-catalog")
async def style_catalog(request: Request):
    return request.app.state.container.character_templates.public_catalog()
