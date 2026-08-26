from pathlib import Path

from app.domain.models import ProductAnalysis, StoryboardShot
from app.services.character_template_catalog import CharacterTemplateCatalog
from app.services.generation_prompt_builder import GenerationPromptBuilder
from app.services.prompt_builder import PromptBuilder


ROOT = Path(__file__).resolve().parents[1]


def catalog() -> CharacterTemplateCatalog:
    return CharacterTemplateCatalog(
        ROOT / "config" / "awesome_style_library.json",
        ROOT / "config" / "character_image_templates.json",
    )


def test_focused_fashion_catalog_and_independent_video_style():
    public = catalog().public_catalog()

    assert public["source"]["category_count"] == 1
    assert public["source"]["upstream_template_count"] == 2
    assert len(public["categories"]) == 1
    assert len(public["image_templates"]) == 2
    assert len(public["video_styles"]) == 1
    assert {item["category_id"] for item in public["image_templates"]} == {
        item["id"] for item in public["categories"]
    }
    assert all("prompt" not in item for item in public["image_templates"])
    assert all(item["id"].startswith("video-cat-") for item in public["video_styles"])


def test_only_core_fashion_showcase_assets_remain():
    asset_root = ROOT / "frontend" / "assets"
    remaining = {
        path.relative_to(asset_root).as_posix()
        for path in asset_root.rglob("*")
        if path.is_file()
    }

    assert remaining == {
        "style-library/fashion-daily-life.png",
        "style-library/fashion-studio.png",
    }
    for item in catalog().public_catalog()["image_templates"]:
        assert (ROOT / "frontend" / item["cover"].removeprefix("/")).is_file()


def test_task_image_prompt_excludes_non_garment_theme_elements():
    prompt = catalog().task_image_prompt("realistic-photography")

    for excluded in (
        "wings",
        "helmet",
        "horns",
        "mask",
        "sword",
        "weapon",
        "butterfly",
        "source background",
    ):
        assert excluded in prompt
    assert "ONLY garment or armor panels" in prompt


def test_image_template_and_video_style_are_added_to_different_prompts():
    styles = catalog()
    generation_builder = GenerationPromptBuilder(styles)
    builder = PromptBuilder(ROOT / "prompts", video_generated_environment=True)
    analysis = ProductAnalysis(
        category="dress",
        primary_color="black",
        visible_details=["purple armor panels"],
    )
    shot = StoryboardShot(
        shot_id="S01",
        duration=3,
        shot_type="hero",
        framing="full_body",
        motion_id="M01",
        camera_motion="static",
        keyframe_type="hero",
        product_focus=["silhouette"],
    )
    scene = {
        "environment": ["modern apartment"],
        "lighting": "soft daylight",
    }
    motion = {"description": "relaxed standing pose"}
    plan = generation_builder.build("daily-life-fashion", "video-cat-photo", "video")

    image_prompt = builder.image_prompt(
        analysis,
        scene,
        shot,
        motion,
        prompt_addition=plan.image_prompt_addition,
    )
    video_prompt = builder.video_prompt(
        shot,
        motion,
        scene,
        prompt_addition=plan.video_prompt_addition,
    )

    assert "TASK IMAGE TEMPLATE" in image_prompt
    assert "Selected image template: Asian Daily-life Fashion Try-on" in image_prompt
    assert "VIDEO STYLE" not in image_prompt
    assert "VIDEO STYLE" in video_prompt
    assert "photorealistic Asian daily-life fashion footage" in video_prompt
    assert "TASK IMAGE TEMPLATE" not in video_prompt
