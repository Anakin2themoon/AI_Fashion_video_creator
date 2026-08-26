from pathlib import Path

from app.domain.models import ProductAnalysis, StoryboardShot
from app.services.character_template_catalog import CharacterTemplateCatalog
from app.services.prompt_builder import PromptBuilder


ROOT = Path(__file__).resolve().parents[1]


def catalog() -> CharacterTemplateCatalog:
    return CharacterTemplateCatalog(
        ROOT / "config" / "awesome_style_library.json",
        ROOT / "config" / "character_image_templates.json",
    )


def test_full_upstream_catalog_and_independent_video_styles():
    public = catalog().public_catalog()

    assert public["source"]["category_count"] == 13
    assert public["source"]["upstream_template_count"] == 22
    assert len(public["categories"]) == 13
    assert len(public["image_templates"]) == 23
    assert len(public["video_styles"]) == 13
    assert {item["category_id"] for item in public["image_templates"]} == {
        item["id"] for item in public["categories"]
    }
    assert all("prompt" not in item for item in public["image_templates"])
    assert all(item["id"].startswith("video-cat-") for item in public["video_styles"])


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
    image_template = styles.get_image_template("poster-layout-system")
    video_style = styles.get_video_style("video-cat-scene")

    image_prompt = builder.image_prompt(
        analysis, scene, shot, motion, image_template=image_template
    )
    video_prompt = builder.video_prompt(
        shot, motion, scene, video_style=video_style
    )

    assert "TASK IMAGE TEMPLATE" in image_prompt
    assert image_template["art_direction"] in image_prompt
    assert "VIDEO STYLE" not in image_prompt
    assert "VIDEO STYLE" in video_prompt
    assert "cinematic narrative continuity" in video_prompt
    assert "TASK IMAGE TEMPLATE" not in video_prompt
