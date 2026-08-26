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
):
    suffix = Path(product_image.filename or "product.jpg").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, "Upload a JPG, PNG or WebP garment image")
    container = request.app.state.container
    if output_type not in {"image", "video"}:
        raise HTTPException(400, "output_type must be image or video")
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
    try:
        container.orchestrator.characters.get(character_id)
        image_template = container.character_templates.get_image_template(
            image_template_id
        )
        video_style = container.character_templates.get_video_style(video_style_id)
    except KeyError as exc:
        raise HTTPException(400, str(exc)) from exc
    state = container.runs.create(
        character_id, image_template_id, video_style_id, output_type
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
            {
                "image_template": {
                    "id": image_template["id"],
                    "name": image_template["name"],
                    "category_id": image_template["category_id"],
                    "output_kind": "task_image_template",
                },
                "video_style": {
                    "id": video_style["id"],
                    "name": video_style["name"],
                    "category_id": video_style["category_id"],
                    "output_kind": "video_style",
                },
            },
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
        }
    finally:
        await product_image.close()
