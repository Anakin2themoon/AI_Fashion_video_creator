from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_IMAGE_TEMPLATE_ID = "realistic-photography"
DEFAULT_VIDEO_STYLE_ID = "video-cat-photo"


VIDEO_ADAPTATIONS = {
    "cat-ui": "live-action fashion footage with restrained editorial interface overlays, clean grids, and precise modern framing",
    "cat-infographic": "clear visual storytelling, ordered compositions, deliberate camera moves, and subtle diagram-like spatial rhythm without readable overlay text",
    "cat-poster": "bold campaign composition, graphic negative space, decisive silhouettes, and premium fashion-poster color blocking",
    "cat-product": "commercial product-first fashion film, crisp garment materials, controlled highlights, and clear clothing detail",
    "cat-brand": "coherent campaign palette, recognizable recurring visual motifs, premium brand-film continuity, and minimal visual clutter",
    "cat-architecture": "architecture-led cinematography with strong lines, spatial depth, realistic materials, and human-scale movement",
    "cat-photo": "photorealistic editorial photography, natural skin texture, believable lens behavior, soft cinematic daylight, and restrained film grain",
    "cat-illustration": "live-action footage with a refined illustrative color language and art-directed composition while keeping the person and garment photorealistic",
    "cat-character": "identity-led character cinematography with consistent face, hair, body proportions, costume details, and readable full-body motion",
    "cat-scene": "cinematic narrative continuity, motivated camera movement, environmental storytelling, and clear emotional beats",
    "cat-history": "classical visual rhythm, restrained traditional color harmony, graceful movement, and historically inspired composition without changing the selected garment",
    "cat-document": "clean chapter-like visual structure, stable framing, ordered shot progression, and publication-grade composition without text overlays",
    "cat-other": "experimental but controlled creative direction, coherent material logic, and one consistent visual system across all shots",
}


class CharacterTemplateCatalog:
    """Full awesome-gpt-image-2 category/template catalog adapted for fashion use."""

    def __init__(self, config_path: Path, legacy_overrides_path: Path | None = None):
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        self.source: dict[str, Any] = {
            "name": "awesome-gpt-image-2",
            "repository": "https://github.com/270438469/awesome-gpt-image-2",
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

        overrides: dict[str, dict[str, Any]] = {}
        extensions: list[dict[str, Any]] = []
        if legacy_overrides_path and legacy_overrides_path.exists():
            legacy = json.loads(legacy_overrides_path.read_text(encoding="utf-8"))
            upstream_ids = {raw["id"] for raw in payload["templates"]}
            for item in legacy.get("templates", []):
                if item["id"] in upstream_ids:
                    overrides[item["id"]] = dict(item)
                else:
                    extensions.append(dict(item))

        self._templates: dict[str, dict[str, Any]] = {}
        for raw in payload["templates"]:
            template = self._adapt_template(dict(raw), overrides.get(raw["id"]))
            self._templates[template["id"]] = template
        for raw in extensions:
            template = self._adapt_extension(raw)
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
        if raw["id"] == "street-accident-moment":
            template["art_direction"] = (
                "Selected image template: Safe Candid Street Moment Photography. "
                "Create a believable spontaneous everyday street-fashion moment with natural phone-camera framing, "
                "subtle motion blur and documentary realism. The moment is completely safe: no accident, collision, "
                "injury, distress, violence, dangerous behavior or damaged property. Avoid staged advertising light."
            )
        template["prompt"] = self._standalone_prompt(template)
        if override:
            for key in ("prompt", "aspect_ratio", "size", "summary"):
                if override.get(key):
                    template[key] = override[key]
        return template

    def _adapt_extension(self, raw: dict[str, Any]) -> dict[str, Any]:
        category_id = "cat-character"
        return {
            **raw,
            "name_en": "4x4 Action Breakdown Sheet",
            "category": self._categories[category_id]["value"],
            "category_id": category_id,
            "cover": "/assets/style-library/case347.jpg",
            "styles": ["Character", "Pose", "Infographic"],
            "scenes": ["Story", "Fashion"],
            "tags": ["Character", "Motion", "Reference"],
            "art_direction": "Selected image template: 4x4 Action Breakdown Sheet. Keep exactly 16 ordered panels, identity, outfit, proportions and hairstyle consistent.",
            "source_extension": True,
        }

    def _build_video_style(self, category: dict[str, Any]) -> dict[str, Any]:
        style_id = f"video-{category['id']}"
        return {
            "id": style_id,
            "category_id": category["id"],
            "name": f"{category['name']}视频风格",
            "name_en": f"{category['name_en']} Video Style",
            "summary": category["summary"],
            "cover": category["cover"],
            "art_direction": "Selected video style: "
            + VIDEO_ADAPTATIONS[category["id"]]
            + ". Keep the source character identity and fitted garment unchanged.",
        }

    def _standalone_prompt(self, template: dict[str, Any]) -> str:
        prompt_name = (
            "Safe Candid Street Moment Photography"
            if template["id"] == "street-accident-moment"
            else template["name_en"]
        )
        return (
            f"Create one polished {prompt_name} image using the uploaded adult East Asian woman "
            "as the only human identity reference. Preserve her exact recognizable face, facial proportions, "
            "adult age, natural skin texture, long straight black hair and body proportions. Keep her current "
            "simple white tank top, black leggings and nude heels recognizable unless the selected template "
            "requires a stylized material translation; never replace her with another person. "
            + template["art_direction"]
            + " Make the recurring woman the clear visual anchor even in interface, diagram, product, brand, "
            "architecture, publication or scene layouts. Use a coherent premium composition, readable hierarchy, "
            "correct anatomy and consistent identity. No extra human identity, no watermark, no copied brand, "
            "no gibberish text, no deformed hands or feet. Output one complete image."
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
        return "/assets/style-library/category-covers/" + Path(value).name

    @staticmethod
    def _aspect_ratio(category_id: str, template_id: str) -> str:
        if template_id in {"action-breakdown-sheet", "infographic-engine"}:
            return "1:1"
        if category_id in {"cat-poster", "cat-photo", "cat-character", "cat-history"}:
            return "2:3"
        return "1:1"

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
