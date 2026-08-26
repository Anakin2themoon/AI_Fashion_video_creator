from pathlib import Path
from app.domain.models import ProductAnalysis, StoryboardShot


class PromptBuilder:
    def __init__(self, prompts_dir: Path, video_generated_environment: bool = False):
        self.prompts_dir = prompts_dir
        self.video_generated_environment = video_generated_environment

    def image_prompt(
        self,
        analysis: ProductAnalysis,
        scene: dict,
        shot: StoryboardShot,
        motion: dict,
        attempt: int = 1,
        image_template: dict | None = None,
    ) -> str:
        template = (self.prompts_dir / "keyframe_generation.md").read_text(encoding="utf-8")
        scene_description = ", ".join(scene["environment"]) + "; " + scene["lighting"]
        if self.video_generated_environment:
            scene_description = "clean neutral light-gray studio; no contextual environment or fantasy background"
        result = template.format(
            scene_description=scene_description,
            framing=shot.framing,
            pose=motion["description"],
            product_focus=", ".join(shot.product_focus),
        )
        result += f"\nVisible garment facts: {', '.join(analysis.visible_details)}. Max body rotation: 55 degrees."
        if image_template:
            result += (
                "\nTASK IMAGE TEMPLATE (independent from video style): "
                + image_template["art_direction"]
                + " Adapt this template's visual language to one coherent 9:16 fashion keyframe; "
                "do not turn the task keyframe into a multi-page document or replace the selected garment."
            )
        if attempt == 2:
            result += "\nEXTRA LOCK: prioritize exact identity and garment fidelity above pose aesthetics."
        elif attempt >= 3:
            result += "\nLOW RISK: simplify the pose, keep arms clear, face front, and minimize occlusion."
        return result

    def video_prompt(
        self,
        shot: StoryboardShot,
        motion: dict,
        scene: dict | None = None,
        video_style: dict | None = None,
    ) -> str:
        template = (self.prompts_dir / "video_generation.md").read_text(encoding="utf-8")
        result = template.format(motion_description=motion["description"], camera_motion=shot.camera_motion)
        if video_style:
            result += (
                " VIDEO STYLE (independent from the task image template): "
                + video_style["art_direction"]
            )
        if self.video_generated_environment and scene:
            environment = ", ".join(scene["environment"])
            result += (
                f" The video model must generate the environment around the subject: {environment}; {scene['lighting']}."
                " It must look like an authentic contemporary East Asian everyday-life location, with realistic scale,"
                " materials, daylight, urban details and ordinary human activity. No fantasy architecture, no runway stage,"
                " no western luxury cliché. Preserve the exact same location design, color palette, architecture, furniture"
                " and daylight continuity across every shot in this sequence. The person, face, hair and already-fitted clothing"
                " are locked to the first frame;"
                " never redesign, recolor, restyle, remove or add any garment, armor panel, accessory, pattern or logo."
            )
        return result[:1000]
