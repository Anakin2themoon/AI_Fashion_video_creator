from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.services.character_template_catalog import CharacterTemplateCatalog


class PromptSelection(BaseModel):
    id: str
    name: str
    category_id: str
    output_kind: Literal["task_image_template", "video_style"]


class TaskImagePrompt(BaseModel):
    prompt: str
    size: str


class GenerationPromptPlan(BaseModel):
    """Immutable prompt contract passed to the existing generate pipeline."""

    schema_version: str = "1.0"
    builder: str = "generation_prompt_builder"
    output_type: Literal["image", "video"]
    reference_mode: Literal["identity_and_garment", "identity_only"]
    prompt_input: str = ""
    image_template: PromptSelection
    video_style: PromptSelection
    task_image: TaskImagePrompt
    image_prompt_addition: str
    video_prompt_addition: str

    def public_metadata(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "builder": self.builder,
            "output_type": self.output_type,
            "reference_mode": self.reference_mode,
            "prompt_input": self.prompt_input,
            "prompt_input_applied": bool(self.prompt_input),
            "image_template": self.image_template.model_dump(mode="json"),
            "video_style": self.video_style.model_dump(mode="json"),
        }


class GenerationPromptBuilder:
    """Compile UI prompt inputs without changing image/video provider contracts."""

    MAX_PROMPT_INPUT_LENGTH = 2000

    def __init__(self, catalog: CharacterTemplateCatalog):
        self.catalog = catalog

    def build(
        self,
        image_template_id: str,
        video_style_id: str,
        output_type: str,
        prompt_input: str = "",
        reference_mode: str = "identity_and_garment",
    ) -> GenerationPromptPlan:
        if output_type not in {"image", "video"}:
            raise ValueError("output_type must be image or video")
        if reference_mode not in {"identity_and_garment", "identity_only"}:
            raise ValueError(
                "reference_mode must be identity_and_garment or identity_only"
            )
        normalized_input = prompt_input.strip()
        if len(normalized_input) > self.MAX_PROMPT_INPUT_LENGTH:
            raise ValueError(
                f"prompt_input exceeds {self.MAX_PROMPT_INPUT_LENGTH} characters"
            )

        image_template = self.catalog.get_image_template(image_template_id)
        video_style = self.catalog.get_video_style(video_style_id)
        user_direction = self._user_direction(normalized_input)
        image_addition = (
            "TASK IMAGE TEMPLATE (independent from video style): "
            + image_template["art_direction"]
            + " Adapt this template's visual language to one coherent 9:16 fashion keyframe; "
            "do not turn the task keyframe into a multi-page document or replace the selected garment."
            + user_direction
        )
        video_addition = (
            "VIDEO STYLE (independent from the task image template): "
            + video_style["art_direction"]
            + user_direction
        )
        return GenerationPromptPlan(
            output_type=output_type,
            reference_mode=reference_mode,
            prompt_input=normalized_input,
            image_template=PromptSelection(
                id=image_template["id"],
                name=image_template["name"],
                category_id=image_template["category_id"],
                output_kind="task_image_template",
            ),
            video_style=PromptSelection(
                id=video_style["id"],
                name=video_style["name"],
                category_id=video_style["category_id"],
                output_kind="video_style",
            ),
            task_image=TaskImagePrompt(
                prompt=(
                    self.catalog.task_image_prompt(image_template_id)
                    if reference_mode == "identity_and_garment"
                    else str(image_template["prompt"])
                )
                + user_direction,
                size=str(image_template["size"]),
            ),
            image_prompt_addition=image_addition,
            video_prompt_addition=video_addition,
        )

    @staticmethod
    def _user_direction(prompt_input: str) -> str:
        if not prompt_input:
            return ""
        return (
            " USER CREATIVE DIRECTION (lower priority than identity, garment fidelity, safety, "
            "selected image template and selected video style): "
            + prompt_input
            + " This direction must never override identity lock, garment-only transfer rules, "
            "anatomy, safety or the selected output type."
        )
