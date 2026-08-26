from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes_generate
from app.db.database import Database
from app.orchestrator import orchestrator
from app.providers.base.image_provider import ImageProvider
from app.providers.base.video_provider import VideoProvider
from app.services.character_template_catalog import CharacterTemplateCatalog
from app.services.asset_manager import AssetManager
from app.services.generation_prompt_builder import GenerationPromptBuilder
from app.services.run_manager import RunManager


ROOT = Path(__file__).resolve().parents[1]


def builder() -> GenerationPromptBuilder:
    catalog = CharacterTemplateCatalog(
        ROOT / "config" / "awesome_style_library.json",
        ROOT / "config" / "character_image_templates.json",
    )
    return GenerationPromptBuilder(catalog)


def test_builder_compiles_prompt_input_and_keeps_style_channels_separate():
    plan = builder().build(
        "daily-life-fashion",
        "video-cat-photo",
        "video",
        "Natural morning light and a relaxed weekend mood.",
    )

    assert plan.builder == "generation_prompt_builder"
    assert plan.output_type == "video"
    assert plan.image_template.id == "daily-life-fashion"
    assert plan.video_style.id == "video-cat-photo"
    assert "TASK IMAGE TEMPLATE" in plan.image_prompt_addition
    assert "VIDEO STYLE" not in plan.image_prompt_addition
    assert "VIDEO STYLE" in plan.video_prompt_addition
    assert "TASK IMAGE TEMPLATE" not in plan.video_prompt_addition
    assert "Natural morning light" in plan.task_image.prompt
    assert "lower priority than identity" in plan.task_image.prompt
    assert plan.public_metadata()["prompt_input_applied"] is True


def test_builder_rejects_invalid_or_oversized_inputs():
    service = builder()

    with pytest.raises(ValueError, match="output_type"):
        service.build("realistic-photography", "video-cat-photo", "audio")
    with pytest.raises(ValueError, match="exceeds"):
        service.build(
            "realistic-photography",
            "video-cat-photo",
            "image",
            "x" * 2001,
        )
    with pytest.raises(KeyError, match="Image template"):
        service.build("missing", "video-cat-photo", "image")


def test_identity_only_template_prompt_does_not_expect_a_garment_reference():
    plan = builder().build(
        "realistic-photography",
        "video-cat-photo",
        "image",
        reference_mode="identity_only",
    )

    assert plan.reference_mode == "identity_only"
    assert "Image 2 is the garment" not in plan.task_image.prompt
    assert "the only human identity reference" in plan.task_image.prompt


def test_prompt_builder_sits_before_handler_without_changing_provider_contracts():
    handler_source = inspect.getsource(routes_generate.generate)
    orchestrator_source = inspect.getsource(orchestrator.Orchestrator)

    assert "generation_prompts.build" in handler_source
    assert "generation_prompt_plan.json" in handler_source
    assert "CharacterTemplateCatalog" not in orchestrator_source
    assert list(inspect.signature(ImageProvider.generate_keyframe).parameters) == [
        "self",
        "character_refs",
        "product_image",
        "prompt",
        "output_path",
    ]
    assert list(inspect.signature(VideoProvider.generate_video).parameters) == [
        "self",
        "start_frame",
        "prompt",
        "duration",
        "output_path",
    ]


def test_generate_handler_persists_builder_plan_without_calling_provider(tmp_path: Path):
    assets = AssetManager(tmp_path / "workspace")
    runs = RunManager(Database(tmp_path / "app.db"), assets)

    class Runner:
        submitted: tuple[str, str] | None = None

        async def submit(self, run_id: str, action: str = "execute") -> None:
            self.submitted = (run_id, action)

    runner = Runner()
    container = SimpleNamespace(
        generation_prompts=builder(),
        orchestrator=SimpleNamespace(
            characters=SimpleNamespace(get=lambda character_id: {"id": character_id})
        ),
        settings=SimpleNamespace(
            vision_provider="mock",
            image_provider="mock",
            video_provider="mock",
            openai_api_key="",
            runway_secret="",
            allow_mock_generation=True,
        ),
        provider_manager=SimpleNamespace(configured=False),
        relay_config=SimpleNamespace(),
        runs=runs,
        assets=assets,
        runner=runner,
    )
    app = FastAPI()
    app.state.container = container
    app.include_router(routes_generate.router, prefix="/api/v1")

    response = TestClient(app).post(
        "/api/v1/generate",
        files={"product_image": ("garment.png", b"not-decoded-by-handler", "image/png")},
        data={
            "character_id": "asian_girl_001",
            "image_template_id": "daily-life-fashion",
            "video_style_id": "video-cat-photo",
            "output_type": "video",
            "prompt_input": "Soft morning light",
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["prompt_builder"] == "generation_prompt_builder"
    assert payload["prompt_input_applied"] is True
    assert runner.submitted == (payload["run_id"], "execute")
    plan = assets.read_json(
        payload["run_id"], "prompts/generation_prompt_plan.json"
    )
    assert plan["prompt_input"] == "Soft morning light"
    assert plan["image_template"]["id"] == "daily-life-fashion"
    assert plan["video_style"]["id"] == "video-cat-photo"
