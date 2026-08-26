from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.main import create_app
from app.services.relay_config import RelaySelection


@pytest.mark.asyncio
async def test_real_generation_requires_all_three_configured_apis(tmp_path: Path):
    root = Path(__file__).resolve().parent.parent
    app = create_app(
        Settings(
            workspace_dir=tmp_path / "workspace",
            character_dir=root / "characters",
            provider_mode="real",
            vision_provider="openai",
            image_provider="openai",
            openai_api_key="test-openai-key",
            video_provider="ffmpeg_camera",
            allow_mock_generation=False,
            webui_auth_enabled=False,
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        status = await client.get("/api/v1/system/status")
        response = await client.post(
            "/api/v1/generate",
            files={"product_image": ("garment.png", b"not-read-before-guard", "image/png")},
        )

    assert status.status_code == 200
    assert status.json()["generation_ready"] is False
    assert response.status_code == 503
    assert "真实生成 API 尚未完整配置" in response.json()["detail"]
    assert "生产任务禁止使用 Mock" in response.json()["detail"]


@pytest.mark.asyncio
async def test_provider_names_cannot_bypass_real_generation_gate(tmp_path: Path):
    root = Path(__file__).resolve().parent.parent
    app = create_app(
        Settings(
            workspace_dir=tmp_path / "workspace",
            character_dir=root / "characters",
            provider_mode="real",
            vision_provider="openai",
            image_provider="openai",
            video_provider="relay",
            allow_mock_generation=False,
            webui_auth_enabled=False,
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/generate",
            files={"product_image": ("garment.png", b"blocked-before-read", "image/png")},
        )

    assert response.status_code == 503
    assert "视觉分析" in response.json()["detail"]
    assert "换装图片" in response.json()["detail"]
    assert "视频生成" in response.json()["detail"]


@pytest.mark.asyncio
async def test_real_generation_rejects_model_group_mismatch_before_creating_run(
    tmp_path: Path, monkeypatch
):
    root = Path(__file__).resolve().parent.parent
    app = create_app(
        Settings(
            workspace_dir=tmp_path / "workspace",
            character_dir=root / "characters",
            provider_mode="real",
            vision_provider="unconfigured",
            image_provider="unconfigured",
            video_provider="unconfigured",
            allow_mock_generation=False,
            webui_auth_enabled=False,
        )
    )
    container = app.state.container
    selection = RelaySelection()
    container.relay_config.save(selection)
    for capability in ("vision", "image", "video"):
        container.relay_config.set_api_key(
            capability, selection.provider_id(capability), "same-video-group-key"
        )
    container.provider_manager.apply()

    async def failed_preflight(*_args, **_kwargs):
        return {
            "connected": False,
            "message": "快跑科技 视觉分析 API Key 所属模型分组不包含 gpt-5.6-sol",
        }

    monkeypatch.setattr(container.provider_manager, "test_connection", failed_preflight)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/generate",
            files={"product_image": ("garment.png", b"blocked-before-run", "image/png")},
        )
        runs = await client.get("/api/v1/runs")

    assert response.status_code == 503
    assert "真实生成 API 预检失败" in response.json()["detail"]
    assert "gpt-5.6-sol" in response.json()["detail"]
    assert runs.json() == []
