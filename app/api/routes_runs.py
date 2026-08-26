import asyncio
import json
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse


router = APIRouter(tags=["runs"])


def load_optional(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def run_payload(request: Request, run_id: str) -> dict:
    container = request.app.state.container
    try:
        state = container.runs.get(run_id)
    except KeyError as exc:
        raise HTTPException(404, "Run not found") from exc
    root = container.assets.run_dir(run_id)
    prefix = f"/media/runs/{run_id}"
    output_prefix = f"/media/outputs/{run_id}"
    input_file = next((root / "input").glob("product.*"), None)
    shots = []
    storyboard = load_optional(root / "analysis" / "storyboard.json")
    product_analysis = load_optional(root / "analysis" / "product_analysis.json")
    analysis_mode = (product_analysis or {}).get("analysis_mode")
    if state.output_type == "image":
        generation_mode = f"image_template_{state.image_template_id}"
        output_kind = "task_image_template"
        is_real_output = True
    elif analysis_mode == "human_reviewed_theme_reference":
        generation_mode = "reviewed_theme_tryon"
        output_kind = "18s_curated_camera_motion"
        is_real_output = True
    elif container.settings.image_provider == "openai":
        if container.settings.video_provider in {"runway", "relay"}:
            model = (
                container.relay_config.selection().video_model
                if container.settings.video_provider == "relay"
                else container.settings.runway_video_model
            )
            generation_mode = f"ai_theme_tryon_{model}"
            output_kind = "18s_generated_daily_life_motion"
        else:
            generation_mode = "ai_theme_tryon"
            output_kind = "18s_camera_motion"
        is_real_output = True
    else:
        generation_mode = "mock_demo"
        output_kind = "pipeline_demo_only"
        is_real_output = False
    for shot in (storyboard or {}).get("shots", []):
        shot_id = shot["shot_id"]
        shots.append({**shot,
            "keyframe_url": f"{prefix}/keyframes/{shot_id}.png" if (root / "keyframes" / f"{shot_id}.png").exists() else None,
            "video_url": f"{prefix}/videos/{shot_id}.mp4" if (root / "videos" / f"{shot_id}.mp4").exists() else None,
            "image_qa": load_optional(root / "image_qa" / f"{shot_id}.json"),
            "video_qa": load_optional(root / "video_qa" / f"{shot_id}.json"),
            "attempts": state.shot_attempts.get(shot_id, {"keyframe": 0, "video": 0}),
        })
    image_output = next((root / "task_images").glob("*.png"), None)
    return {
        **state.model_dump(mode="json"),
        "input_url": f"{prefix}/input/{input_file.name}" if input_file else None,
        "product_analysis": product_analysis,
        "scene_decision": load_optional(root / "analysis" / "scene_decision.json"),
        "motion_decision": load_optional(root / "analysis" / "motion_decision.json"),
        "generation_styles": load_optional(root / "analysis" / "generation_styles.json"),
        "storyboard": storyboard, "shots": shots,
        "image_output_url": (
            f"{prefix}/task_images/{image_output.name}" if image_output else None
        ),
        "image_generation_manifest": load_optional(
            root / "task_images" / "generation_manifest.json"
        ),
        "final_video_url": f"{output_prefix}/final.mp4" if (container.assets.workspace / "outputs" / run_id / "final.mp4").exists() else None,
        "output_directory": str((container.assets.workspace / "outputs" / run_id).resolve()),
        "generation_mode": generation_mode,
        "output_kind": output_kind,
        "is_real_output": is_real_output,
    }


@router.get("/runs")
async def list_runs(request: Request):
    return [state.model_dump(mode="json") for state in request.app.state.container.runs.list()]


@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request):
    return run_payload(request, run_id)


@router.get("/runs/{run_id}/result")
async def get_result(run_id: str, request: Request):
    payload = run_payload(request, run_id)
    return {
        "status": payload["status"],
        "final_video_url": payload["final_video_url"],
        "image_output_url": payload["image_output_url"],
        "output_type": payload["output_type"],
    }


@router.get("/runs/{run_id}/download")
async def download_result(run_id: str, request: Request):
    container = request.app.state.container
    try:
        state = container.runs.get(run_id)
    except KeyError as exc:
        raise HTTPException(404, "Run not found") from exc
    if state.output_type == "image":
        result = next((container.assets.run_dir(run_id) / "task_images").glob("*.png"), None)
        media_type = "image/png"
        filename = f"ai-fashion-{run_id}.png"
    else:
        result = container.assets.workspace / "outputs" / run_id / "final.mp4"
        media_type = "video/mp4"
        filename = f"ai-fashion-{run_id}-18s.mp4"
    if result is None or not result.exists():
        raise HTTPException(409, "Result is not ready")
    return FileResponse(result, media_type=media_type, filename=filename)


@router.post("/runs/{run_id}/resume", status_code=202)
async def resume(run_id: str, request: Request):
    container = request.app.state.container
    try:
        state = container.runs.get(run_id)
    except KeyError as exc:
        raise HTTPException(404, "Run not found") from exc
    if state.status == "COMPLETED":
        return {"run_id": run_id, "status": "COMPLETED"}
    container.runs.update(run_id, "INTERRUPTED", state.progress, "Queued for resume", error=None)
    await container.runner.resume(run_id)
    return {"run_id": run_id, "status": "QUEUED"}


@router.post("/runs/{run_id}/shots/{shot_id}/retry-keyframe", status_code=202)
async def retry_keyframe(run_id: str, shot_id: str, request: Request):
    if shot_id not in {f"S{i:02d}" for i in range(1, 6)}:
        raise HTTPException(400, "Invalid shot id")
    request.app.state.container.runs.get(run_id)
    await request.app.state.container.runner.retry_step(run_id, "retry_keyframe", shot_id)
    return {"run_id": run_id, "shot_id": shot_id, "action": "retry_keyframe", "status": "QUEUED"}


@router.post("/runs/{run_id}/shots/{shot_id}/retry-video", status_code=202)
async def retry_video(run_id: str, shot_id: str, request: Request):
    if shot_id not in {f"S{i:02d}" for i in range(1, 6)}:
        raise HTTPException(400, "Invalid shot id")
    request.app.state.container.runs.get(run_id)
    await request.app.state.container.runner.retry_step(run_id, "retry_video", shot_id)
    return {"run_id": run_id, "shot_id": shot_id, "action": "retry_video", "status": "QUEUED"}


@router.post("/runs/{run_id}/compose", status_code=202)
async def compose(run_id: str, request: Request):
    request.app.state.container.runs.get(run_id)
    await request.app.state.container.runner.retry_step(run_id, "compose")
    return {"run_id": run_id, "action": "compose", "status": "QUEUED"}


@router.delete("/runs/{run_id}", status_code=204)
async def delete_run(run_id: str, request: Request):
    await request.app.state.container.runner.cancel(run_id)
    try:
        request.app.state.container.runs.delete(run_id)
    except KeyError as exc:
        raise HTTPException(404, "Run not found") from exc


@router.post("/runs/{run_id}/open-output")
async def open_output(run_id: str, request: Request):
    container = request.app.state.container
    container.runs.get(run_id)
    path = (container.assets.workspace / "outputs" / run_id).resolve()
    if not path.exists():
        raise HTTPException(409, "Output is not ready")
    opened = False
    if os.name == "nt":
        try:
            os.startfile(str(path))
            opened = True
        except OSError:
            opened = False
    return {"path": str(path), "opened": opened}


@router.get("/runs/{run_id}/events")
async def events(run_id: str, request: Request):
    container = request.app.state.container
    container.runs.get(run_id)
    async def stream():
        last_id = 0
        while True:
            if await request.is_disconnected():
                break
            items = container.runs.events(run_id, last_id)
            for item in items:
                last_id = item["id"]
                yield f"id: {last_id}\nevent: progress\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
            state = container.runs.get(run_id)
            if state.status in {"COMPLETED", "FAILED"} and not items:
                yield f"event: close\ndata: {json.dumps({'status': state.status})}\n\n"
                break
            if not items:
                yield ": keepalive\n\n"
            await asyncio.sleep(0.5)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control":"no-cache", "X-Accel-Buffering":"no"})
