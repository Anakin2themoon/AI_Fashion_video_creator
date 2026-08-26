from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class ProductAnalysis(BaseModel):
    category: str
    subcategory: str | None = None
    primary_color: str
    secondary_colors: list[str] = Field(default_factory=list)
    sleeve: str | None = None
    neckline: str | None = None
    length: str | None = None
    fit: str | None = None
    material_guess: str | None = None
    style_tags: list[str] = Field(default_factory=list)
    season_tags: list[str] = Field(default_factory=list)
    occasion_tags: list[str] = Field(default_factory=list)
    visible_details: list[str] = Field(default_factory=list)
    unknown_details: list[str] = Field(default_factory=list)
    source_view: Literal["front", "back", "side", "unknown"] = "unknown"
    confidence: float = 0.0


class SceneScore(BaseModel):
    scene_id: str
    style_match: float
    occasion_match: float
    color_match: float
    season_match: float
    ecommerce_utility: float
    final_score: float


class SceneDecision(BaseModel):
    primary_scene: str
    backup_scene: str | None = None
    confidence: float
    rankings: list[SceneScore]
    reason: str


class MotionDecision(BaseModel):
    motion_ids: list[str]
    rejected_motion_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class StoryboardShot(BaseModel):
    shot_id: str
    duration: float
    shot_type: str
    framing: str
    motion_id: str
    camera_motion: str
    keyframe_type: str
    product_focus: list[str]
    prompt_context: dict[str, Any] = Field(default_factory=dict)


class Storyboard(BaseModel):
    scene_id: str
    character_id: str
    aspect_ratio: str = "9:16"
    target_duration: float = 18
    shots: list[StoryboardShot]


class QAResult(BaseModel):
    shot_id: str
    scores: dict[str, float]
    issues: list[str] = Field(default_factory=list)
    status: Literal["PASS", "FAIL"]
    attempt: int = 1
    fallback_used: bool = False


class Asset(BaseModel):
    path: str
    media_type: str
    duration: float | None = None


class Character(BaseModel):
    id: str
    gender: str
    appearance: str
    visual_age: str
    style: str
    hair: str
    skin: str
    body: str
    default_shoes: str
    identity_lock: bool
    references: dict[str, str]


class RunState(BaseModel):
    run_id: str
    status: str
    character_id: str = "asian_girl_001"
    image_template_id: str = "realistic-photography"
    video_style_id: str = "video-cat-photo"
    output_type: Literal["image", "video"] = "video"
    progress: int = 0
    current_step: str = "Created"
    created_at: str
    updated_at: str
    error: str | None = None
    steps: dict[str, str] = Field(default_factory=dict)
    shot_attempts: dict[str, dict[str, int]] = Field(default_factory=dict)
