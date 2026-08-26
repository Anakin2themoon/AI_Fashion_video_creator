from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_IMAGE_TEMPLATE_ID = "realistic-photography"
DEFAULT_VIDEO_STYLE_ID = "video-cat-photo"


VIDEO_ADAPTATIONS = {
    "cat-photo": "photorealistic Asian daily-life fashion footage, consistent face and body, faithful garment construction and fabric texture, natural full-body motion, believable lens behavior, soft cinematic daylight, and restrained film grain",
}


class CharacterTemplateCatalog:
    """Focused photorealistic fashion try-on image and video catalog."""

    def __init__(self, config_path: Path, legacy_overrides_path: Path | None = None):
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        self.source: dict[str, Any] = {
            "name": "AI Fashion Try-on Core",
            "repository": "https://github.com/Anakin2themoon/AI_Fashion_video_creator",
            "upstream": str(payload.get("repository", "https://github.com/freestylefly/awesome-gpt-image-2")),
            "license": "MIT",
            "version": payload.get("version", 1),
            "category_count": len(payload["categories"]),
            "upstream_template_count": len(payload["templates"]),
        }
        self._categories: dict[str, dict[str, Any]] = {}
        self._category_by_value: dict[str, str] = {}
        for raw in payload["categories"]:
            category = dict(raw)
            category["name"] = category["title"]["zh"]
            category["name_en"] = category["title"]["en"]
            category["summary"] = category["description"]["zh"]
            category["cover"] = self._category_cover(category["cover"])
            self._categories[category["id"]] = category
            self._category_by_value[category["value"]] = category["id"]

        self._templates: dict[str, dict[str, Any]] = {}
        for raw in payload["templates"]:
            template = self._adapt_template(dict(raw), None)
            self._templates[template["id"]] = template

        self._video_styles = {
            f"video-{category_id}": self._build_video_style(category)
            for category_id, category in self._categories.items()
        }

    def public_catalog(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "defaults": {
                "image_template_id": DEFAULT_IMAGE_TEMPLATE_ID,
                "video_style_id": DEFAULT_VIDEO_STYLE_ID,
            },
            "categories": self.list_categories(),
            "image_templates": self.list_public(),
            "video_styles": self.list_video_styles(),
        }

    def list_categories(self) -> list[dict[str, Any]]:
        keys = ("id", "value", "name", "name_en", "summary", "cover")
        return [{key: item[key] for key in keys} for item in self._categories.values()]

    def list_public(self) -> list[dict[str, Any]]:
        return [self._without_private(item) for item in self._templates.values()]

    def list_video_styles(self) -> list[dict[str, Any]]:
        return [self._without_private(item) for item in self._video_styles.values()]

    def get(self, template_id: str) -> dict[str, Any]:
        return self.get_image_template(template_id)

    def get_image_template(self, template_id: str) -> dict[str, Any]:
        try:
            return dict(self._templates[template_id])
        except KeyError as exc:
            raise KeyError(f"Image template not found: {template_id}") from exc

    def get_video_style(self, style_id: str) -> dict[str, Any]:
        try:
            return dict(self._video_styles[style_id])
        except KeyError as exc:
            raise KeyError(f"Video style not found: {style_id}") from exc

    def task_image_prompt(self, template_id: str) -> str:
        template = self.get_image_template(template_id)
        return (
            "REFERENCE ROLES ARE STRICT. Image 1 is the only human identity reference. "
            "Image 2 is the garment or fashion-theme reference and may contain another person, props, text, "
            "effects or a background. Preserve the exact adult face, hair, skin and body proportions from image 1. "
            "Extract and transfer ONLY garment or armor panels that are fitted directly on the torso, shoulders, arms, "
            "waist, hips or legs, including their material, seams, colors and silhouette. If an element is not clearly "
            "body-worn clothing, leave it out. NEVER transfer the source person's face, hair, skin, body or pose. "
            "NEVER transfer wings, wing attachments, capes floating behind the body, helmet, horns, mask, sword, weapon, "
            "handheld object, butterfly, creature, floating decoration, glow effect, source scenery, source background, "
            "source lighting, text or logo. Generate a new background appropriate to the selected template. "
            f"Create one complete {template['name_en']} output. {template['art_direction']} "
            "The selected woman wearing the transferred garment must remain the recurring visual anchor in every "
            "panel or view. Keep her identity, garment colors, garment silhouette, materials and construction details "
            "consistent throughout. Use professional composition and correct anatomy. No identity drift, no unrelated "
            "people, no invented clothing, no copied branding, no watermark, no gibberish text, no deformed hands or feet."
        )

    def _adapt_template(
        self, raw: dict[str, Any], override: dict[str, Any] | None
    ) -> dict[str, Any]:
        category_id = self._category_by_value[raw["category"]]
        guidance = self._localized_lines(raw.get("guidance", {}).get("en", []))
        pitfalls = self._localized_lines(raw.get("pitfalls", {}).get("en", []))
        template = {
            **raw,
            "name": raw["title"]["zh"],
            "name_en": raw["title"]["en"],
            "summary": raw["description"]["zh"],
            "category_id": category_id,
            "cover": self._template_cover(raw["cover"]),
            "aspect_ratio": self._aspect_ratio(category_id, raw["id"]),
            "size": self._size(category_id, raw["id"]),
            "art_direction": (
                f"Selected image template: {raw['title']['en']}. "
                f"Category: {raw['category']}. {raw['description']['en']} "
                f"{guidance} Avoid: {pitfalls}"
            ),
        }
        if raw["id"] == "realistic-photography":
            template["art_direction"] = (
                "Selected image template: Premium Studio Fashion Try-on. Create one photorealistic full-body fashion "
                "portrait on a clean premium studio set. Make the transferred garment silhouette, construction, seams, "
                "materials and fine texture crisp and easy to inspect. Use natural skin texture, accurate anatomy, soft "
                "commercial lighting and restrained styling without accessories that hide the garment."
            )
        elif raw["id"] == "daily-life-fashion":
            template["art_direction"] = (
                "Selected image template: Asian Daily-life Fashion Try-on. Create one believable full-body fashion "
                "portrait in a contemporary Asian everyday environment. Use natural movement, realistic daylight, "
                "subtle environmental depth and premium lifestyle photography while keeping every garment detail fully "
                "readable. No tourist landmark, fantasy scenery, unrelated prop or dramatic visual effect."
            )
        template["prompt"] = self._standalone_prompt(template)
        if override:
            for key in ("prompt", "aspect_ratio", "size", "summary"):
                if override.get(key):
                    template[key] = override[key]
        return template

    def _build_video_style(self, category: dict[str, Any]) -> dict[str, Any]:
        style_id = f"video-{category['id']}"
        return {
            "id": style_id,
            "category_id": category["id"],
            "name": "亚洲日常写实时装片",
            "name_en": "Photorealistic Asian Daily-life Fashion Film",
            "summary": "围绕同一人物和上传衣服，生成真实亚洲日常环境中的高清 18 秒时装视频。",
            "cover": category["cover"],
            "art_direction": "Selected video style: "
            + VIDEO_ADAPTATIONS[category["id"]]
            + ". Keep the source character identity and fitted garment unchanged.",
        }

    def _standalone_prompt(self, template: dict[str, Any]) -> str:
        prompt_name = template["name_en"]
        return (
            f"Create one polished {prompt_name} image using the uploaded adult East Asian woman "
            "as the only human identity reference. Preserve her exact recognizable face, facial proportions, "
            "adult age, natural skin texture, long straight black hair and body proportions. Keep her current "
            "current clothing recognizable; never replace her with another person. "
            + template["art_direction"]
            + " Make the recurring woman and the selected garment the only visual anchors. Use a coherent premium "
            "fashion composition, correct anatomy, realistic skin and fabric, and consistent identity. No unrelated "
            "person or object, no watermark, no copied brand, no text, no deformed hands or feet. Output one complete image."
        )

    @staticmethod
    def _localized_lines(value: Any) -> str:
        if isinstance(value, list):
            return " ".join(str(item) for item in value)
        return str(value or "")

    @staticmethod
    def _template_cover(value: str) -> str:
        return "/assets/style-library/" + Path(value).name

    @staticmethod
    def _category_cover(value: str) -> str:
        return "/assets/style-library/" + Path(value).name

    @staticmethod
    def _aspect_ratio(category_id: str, template_id: str) -> str:
        return "2:3"

    @staticmethod
    def _size(category_id: str, template_id: str) -> str:
        return (
            "1024x1536"
            if CharacterTemplateCatalog._aspect_ratio(category_id, template_id) == "2:3"
            else "1024x1024"
        )

    @staticmethod
    def _without_private(item: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in item.items()
            if key not in {"prompt", "art_direction", "guidance", "pitfalls", "useWhen"}
        }
