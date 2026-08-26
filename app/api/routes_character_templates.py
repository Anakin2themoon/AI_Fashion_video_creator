from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.providers.openai_image import OpenAIImageProvider


router = APIRouter(tags=["character-templates"])


class CharacterTemplateRequest(BaseModel):
    character_id: str = "asian_girl_001"
    prompt_input: str = ""


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


@router.post("/character-templates/{template_id}/generate")
@router.post("/image-templates/{template_id}/generate")
async def generate_character_template(
    template_id: str,
    payload: CharacterTemplateRequest,
    request: Request,
):
    container = request.app.state.container
    try:
        prompt_plan = container.generation_prompts.build(
            template_id,
            container.character_templates.public_catalog()["defaults"][
                "video_style_id"
            ],
            "image",
            payload.prompt_input,
            reference_mode="identity_only",
        )
        template = prompt_plan.image_template
        references = container.orchestrator.characters.reference_paths(
            payload.character_id
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(404, str(exc)) from exc

    provider = container.orchestrator.image_provider
    if not isinstance(provider, OpenAIImageProvider):
        raise HTTPException(503, "请先配置真实换装图片 API")

    generation_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    output_dir = (
        container.assets.workspace
        / "image_templates"
        / template_id
        / generation_id
    )
    output_path = output_dir / f"{template_id}.png"
    try:
        await provider.generate_from_references(
            references,
            prompt_plan.task_image.prompt,
            output_path,
            size=prompt_plan.task_image.size,
        )
    except Exception as exc:
        raise HTTPException(
            502, f"人物模板生成失败：{type(exc).__name__}: {exc}"
        ) from exc

    relative = output_path.relative_to(container.assets.workspace).as_posix()
    result = {
        "generation_id": generation_id,
        "template_id": template_id,
        "template_name": template.name,
        "category_id": template.category_id,
        "output_kind": "image_template",
        "character_id": payload.character_id,
        "model": provider.model,
        "image_url": f"/media/{relative}",
        "prompt_builder": prompt_plan.builder,
        "prompt_input_applied": bool(prompt_plan.prompt_input),
    }
    (output_dir / "generation_prompt_plan.json").write_text(
        prompt_plan.model_dump_json(indent=2), encoding="utf-8"
    )
    (output_dir / "generation_manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
