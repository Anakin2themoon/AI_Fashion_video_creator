import shutil
import tempfile
from pathlib import Path
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile


router = APIRouter(tags=["generation"])
ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


@router.post("/generate", status_code=202)
async def generate(
    request: Request,
    product_image: UploadFile = File(...),
    character_id: str = Form("asian_girl_001"),
    image_template_id: str = Form("realistic-photography"),
    video_style_id: str = Form("video-cat-photo"),
    output_type: str = Form("video"),
    prompt_input: str = Form(""),
):
    suffix = Path(product_image.filename or "product.jpg").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, "Upload a JPG, PNG or WebP garment image")
    container = request.app.state.container
    try:
        prompt_plan = container.generation_prompts.build(
            image_template_id,
            video_style_id,
            output_type,
            prompt_input,
        )
        container.orchestrator.characters.get(character_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    legacy_runway_ready = (
        container.settings.vision_provider == "openai"
        and container.settings.image_provider == "openai"
        and bool(container.settings.openai_api_key)
        and container.settings.video_provider == "runway"
        and bool(container.settings.runway_secret)
    )
    if output_type == "image":
        selection = container.relay_config.selection()
        if not container.relay_config.api_key(
            "image", selection.image_provider_id
        ):
            raise HTTPException(503, "请先配置独立的换装图片 API Key")
        preflight = await container.provider_manager.test_connection(
            capability="image"
        )
        if not preflight.get("connected"):
            raise HTTPException(
                503,
                "换装图片 API 预检失败："
                + str(preflight.get("message", "连接失败")),
            )
        container.orchestrator.image_provider = (
            container.provider_manager.build_image_provider(selection)
        )
    else:
        if (
            not container.provider_manager.configured
            and not legacy_runway_ready
            and not container.settings.allow_mock_generation
        ):
            missing = container.relay_config.public_status()["missing_capability_labels"]
            raise HTTPException(
                503,
                f"真实生成 API 尚未完整配置：缺少 {'、'.join(missing)} API Key。"
                "生产任务禁止使用 Mock 或静态 FFmpeg 视频。",
            )
        if container.provider_manager.configured:
            preflight = await container.provider_manager.test_connection()
            if not preflight.get("connected"):
                raise HTTPException(
                    503,
                    "真实生成 API 预检失败："
                    + str(preflight.get("message", "连接失败")),
                )
    state = container.runs.create(
        character_id,
        prompt_plan.image_template.id,
        prompt_plan.video_style.id,
        prompt_plan.output_type,
    )
    input_path = container.assets.run_dir(state.run_id) / "input" / f"product{suffix}"
    try:
        with input_path.open("wb") as handle:
            while True:
                chunk = await product_image.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        if input_path.stat().st_size > 20 * 1024 * 1024:
            container.runs.delete(state.run_id)
            raise HTTPException(413, "Image exceeds 20 MB")
        container.assets.write_json(
            state.run_id,
            "analysis/generation_styles.json",
            prompt_plan.public_metadata(),
        )
        container.assets.write_json(
            state.run_id,
            "prompts/generation_prompt_plan.json",
            prompt_plan,
        )
        await container.runner.submit(
            state.run_id,
            "execute_image" if output_type == "image" else "execute",
        )
        return {
            "run_id": state.run_id,
            "status": state.status,
            "image_template_id": state.image_template_id,
            "video_style_id": state.video_style_id,
            "output_type": state.output_type,
            "prompt_builder": prompt_plan.builder,
            "prompt_input_applied": bool(prompt_plan.prompt_input),
        }
    finally:
        await product_image.close()
