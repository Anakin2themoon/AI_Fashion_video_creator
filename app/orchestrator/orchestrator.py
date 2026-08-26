import asyncio
import hashlib
import json
from pathlib import Path
from app.agents.product_analyzer import ProductAnalyzer
from app.agents.scene_router import SceneRouter
from app.agents.motion_router import MotionRouter
from app.agents.storyboard_generator import StoryboardGenerator
from app.agents.image_qa import ImageQA
from app.agents.video_qa import VideoQA
from app.domain.enums import RunStatus
from app.domain.models import ProductAnalysis, SceneDecision, MotionDecision, Storyboard
from app.orchestrator.retry_policy import RetryPolicy
from app.orchestrator.state_machine import PROGRESS
from app.providers.base.image_provider import ImageProvider
from app.providers.base.video_provider import VideoProvider
from app.providers.openai_image import OpenAIImageProvider
from app.providers.base.composer_provider import ComposerProvider
from app.services.asset_manager import AssetManager
from app.services.character_registry import CharacterRegistry
from app.services.generation_prompt_builder import GenerationPromptBuilder
from app.services.prompt_builder import PromptBuilder
from app.services.run_manager import RunManager


class Orchestrator:
    def __init__(self, analyzer: ProductAnalyzer, scene_router: SceneRouter, motion_router: MotionRouter,
                 storyboard_generator: StoryboardGenerator, image_provider: ImageProvider, image_qa: ImageQA,
                 video_provider: VideoProvider, video_qa: VideoQA, composer: ComposerProvider,
                 characters: CharacterRegistry, prompts: PromptBuilder, assets: AssetManager,
                 runs: RunManager, retry: RetryPolicy, generation_prompts: GenerationPromptBuilder,
                 image_limit: int = 2, video_limit: int = 1):
        self.analyzer = analyzer
        self.scene_router = scene_router
        self.motion_router = motion_router
        self.storyboard_generator = storyboard_generator
        self.image_provider = image_provider
        self.image_qa = image_qa
        self.video_provider = video_provider
        self.video_qa = video_qa
        self.composer = composer
        self.characters = characters
        self.prompts = prompts
        self.assets = assets
        self.runs = runs
        self.retry = retry
        self.generation_prompts = generation_prompts
        self.image_semaphore = asyncio.Semaphore(image_limit)
        self.video_semaphore = asyncio.Semaphore(video_limit)

    async def execute_image(self, run_id: str) -> None:
        """Generate one selected task image template without invoking video."""
        try:
            state = self.runs.get(run_id)
            run_dir = self.assets.run_dir(run_id)
            product_image = next((run_dir / "input").glob("product.*"), None)
            if product_image is None:
                raise FileNotFoundError("Run has no product input")
            if not isinstance(self.image_provider, OpenAIImageProvider):
                raise RuntimeError("Real image provider is not configured")
            references = self.characters.reference_paths(state.character_id)
            identity_reference = next(
                (path for path in references if path.name == "identity_face.png"),
                references[0],
            )
            prompt_plan = self._prompt_plan(run_id)
            template = prompt_plan["image_template"]
            task_image = prompt_plan["task_image"]
            prompt = str(task_image["prompt"])
            output = run_dir / "task_images" / f"{state.image_template_id}.png"
            (run_dir / "prompts" / "task_image_prompt.txt").write_text(
                prompt, encoding="utf-8"
            )
            self._state(
                run_id,
                RunStatus.KEYFRAMES_GENERATING,
                f"Generating image template {template['name']}",
                "keyframe_generation",
                "running",
            )
            async with self.image_semaphore:
                await self.image_provider.generate_from_references(
                    [identity_reference, product_image],
                    prompt,
                    output,
                    size=str(task_image["size"]),
                )
            from PIL import Image

            with Image.open(output) as generated:
                generated.verify()
            with Image.open(output) as generated:
                width, height = generated.size
                image_format = generated.format
            self.assets.write_json(
                run_id,
                "task_images/generation_manifest.json",
                {
                    "output_kind": "task_image_template",
                    "image_template_id": state.image_template_id,
                    "image_template_name": template["name"],
                    "image_category_id": template["category_id"],
                    "video_style_id": state.video_style_id,
                    "video_invoked": False,
                    "model": self.image_provider.model,
                    "file": output.name,
                    "format": image_format,
                    "width": width,
                    "height": height,
                    "bytes": output.stat().st_size,
                    "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                },
            )
            self._state(
                run_id,
                RunStatus.KEYFRAMES_READY,
                "Task image template ready",
                "keyframe_generation",
                "done",
            )
            self._state(
                run_id,
                RunStatus.COMPLETED,
                "Image ready; video was not invoked",
                "composition",
                "done",
            )
            self.runs.event(
                run_id,
                "RUN_COMPLETED",
                image=f"/media/runs/{run_id}/task_images/{output.name}",
                video_invoked=False,
            )
        except Exception as exc:
            self.runs.update(
                run_id,
                RunStatus.FAILED.value,
                self.runs.get(run_id).progress,
                "Image generation failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            self.runs.event(
                run_id,
                "RUN_FAILED",
                error=f"{type(exc).__name__}: {exc}",
            )

    async def execute(self, run_id: str) -> None:
        try:
            state = self.runs.get(run_id)
            run_dir = self.assets.run_dir(run_id)
            input_candidates = list((run_dir / "input").glob("product.*"))
            if not input_candidates:
                raise FileNotFoundError("Run has no product input")
            product_image = input_candidates[0]
            character_id = state.character_id
            self.characters.get(character_id)

            analysis_path = run_dir / "analysis" / "product_analysis.json"
            if analysis_path.exists():
                analysis = ProductAnalysis.model_validate_json(analysis_path.read_text(encoding="utf-8"))
            else:
                self._state(run_id, RunStatus.PRODUCT_ANALYZING, "Analyzing visible garment facts", "product_analysis", "running")
                analysis = await self.analyzer.analyze(product_image)
                self.assets.write_json(run_id, "analysis/product_analysis.json", analysis)
                self._state(run_id, RunStatus.PRODUCT_ANALYZED, "Product analysis complete", "product_analysis", "done")

            scene_path = run_dir / "analysis" / "scene_decision.json"
            if scene_path.exists():
                scene = SceneDecision.model_validate_json(scene_path.read_text(encoding="utf-8"))
            else:
                self._state(run_id, RunStatus.SCENE_ROUTING, "Scoring configured scenes", "scene_router", "running")
                scene = self.scene_router.route(analysis)
                self.assets.write_json(run_id, "analysis/scene_decision.json", scene)
                self.runs.event(run_id, "SCENE_SELECTED", scene=scene.primary_scene, backup=scene.backup_scene)
                self._state(run_id, RunStatus.SCENE_SELECTED, f"Scene {scene.primary_scene} selected", "scene_router", "done")

            motion_path = run_dir / "analysis" / "motion_decision.json"
            if motion_path.exists():
                motions = MotionDecision.model_validate_json(motion_path.read_text(encoding="utf-8"))
            else:
                self._state(run_id, RunStatus.MOTION_ROUTING, "Selecting safe garment motions", "motion_router", "running")
                motions = self.motion_router.route(analysis, scene)
                self.assets.write_json(run_id, "analysis/motion_decision.json", motions)
                self._state(run_id, RunStatus.MOTIONS_SELECTED, "Safe motions selected", "motion_router", "done")

            storyboard_path = run_dir / "analysis" / "storyboard.json"
            if storyboard_path.exists():
                storyboard = Storyboard.model_validate_json(storyboard_path.read_text(encoding="utf-8"))
            else:
                self._state(run_id, RunStatus.STORYBOARD_BUILDING, "Building five-shot storyboard", "storyboard", "running")
                storyboard = self.storyboard_generator.build(analysis, scene, motions, character_id)
                self.assets.write_json(run_id, "analysis/storyboard.json", storyboard)
                self._state(run_id, RunStatus.STORYBOARD_READY, "Five-shot storyboard ready", "storyboard", "done")

            scene_config = next(item for item in self.scene_router.scenes if item["id"] == scene.primary_scene)
            motion_map = self.motion_router.motions
            self._state(run_id, RunStatus.KEYFRAMES_GENERATING, "Generating keyframes", "keyframe_generation", "running")
            for shot in storyboard.shots:
                if not (run_dir / "keyframes" / f"{shot.shot_id}.png").exists() or not self._qa_passed(run_dir / "image_qa" / f"{shot.shot_id}.json"):
                    await self.generate_keyframe(run_id, shot.shot_id, analysis, storyboard, scene_config, motion_map, product_image)
            self._state(run_id, RunStatus.KEYFRAMES_READY, "All keyframes ready", "keyframe_generation", "done")
            self._state(run_id, RunStatus.IMAGE_QA_PASSED, "All keyframes passed QA", "image_qa", "done")

            self._state(run_id, RunStatus.VIDEOS_GENERATING, "Generating shot videos", "video_generation", "running")
            for shot in storyboard.shots:
                if not (run_dir / "videos" / f"{shot.shot_id}.mp4").exists() or not self._qa_passed(run_dir / "video_qa" / f"{shot.shot_id}.json"):
                    await self.generate_video(run_id, shot.shot_id, storyboard, motion_map)
            self._state(run_id, RunStatus.VIDEOS_READY, "All shot videos ready", "video_generation", "done")
            self._state(run_id, RunStatus.VIDEO_QA_PASSED, "All shot videos passed QA", "video_qa", "done")
            await self.compose(run_id, storyboard)
        except Exception as exc:
            self.runs.update(run_id, RunStatus.FAILED.value, self.runs.get(run_id).progress,
                             "Pipeline failed", error=f"{type(exc).__name__}: {exc}")
            self.runs.event(run_id, "RUN_FAILED", error=f"{type(exc).__name__}: {exc}")

    async def generate_keyframe(self, run_id: str, shot_id: str, analysis: ProductAnalysis | None = None,
                                storyboard: Storyboard | None = None, scene_config: dict | None = None,
                                motion_map: dict | None = None, product_image: Path | None = None, force: bool = False) -> Path:
        run_dir = self.assets.run_dir(run_id)
        if storyboard is None:
            storyboard = Storyboard.model_validate(self.assets.read_json(run_id, "analysis/storyboard.json"))
        shot = next(item for item in storyboard.shots if item.shot_id == shot_id)
        if analysis is None:
            analysis = ProductAnalysis.model_validate(self.assets.read_json(run_id, "analysis/product_analysis.json"))
        if scene_config is None:
            scene_config = next(item for item in self.scene_router.scenes if item["id"] == storyboard.scene_id)
        if motion_map is None:
            motion_map = self.motion_router.motions
        if product_image is None:
            product_image = next((run_dir / "input").glob("product.*"))
        output = run_dir / "keyframes" / f"{shot_id}.png"
        for local_attempt in range(1, self.retry.max_image_attempts + 1):
            attempt = self.runs.increment_attempt(run_id, shot_id, "keyframe")
            prompt_plan = self._prompt_plan(run_id)
            prompt = self.prompts.image_prompt(
                analysis,
                scene_config,
                shot,
                motion_map[shot.motion_id],
                local_attempt,
                prompt_addition=str(prompt_plan["image_prompt_addition"]),
            )
            (run_dir / "prompts" / f"{shot_id}_image_prompt.txt").write_text(prompt, encoding="utf-8")
            self.runs.event(run_id, "STEP_STARTED", step="KEYFRAME_GENERATION", shot=shot_id, attempt=attempt)
            async with self.image_semaphore:
                await self.image_provider.generate_keyframe(self.characters.reference_paths(storyboard.character_id), product_image, prompt, output)
            self._state(run_id, RunStatus.IMAGE_QA, f"Checking keyframe {shot_id}", "image_qa", "running")
            identity_refs = self.characters.reference_paths(storyboard.character_id)
            identity_reference = next(
                (path for path in identity_refs if path.name == "reference_sheet.png"),
                identity_refs[0],
            )
            expected_scene = ", ".join(scene_config["environment"]) + "; " + scene_config["lighting"]
            if self.prompts.video_generated_environment:
                expected_scene = "clean neutral light-gray studio"
            qa = await self.image_qa.evaluate(
                shot_id, output, attempt, identity_reference, product_image,
                analysis.visible_details, expected_scene,
            )
            self.assets.write_json(run_id, f"image_qa/{shot_id}.json", qa)
            if qa.status == "PASS":
                return output
            self.runs.event(run_id, "SHOT_RETRY", shot=shot_id, kind="keyframe", attempt=attempt + 1)
        raise RuntimeError(f"Keyframe {shot_id} failed after retries")

    async def generate_video(self, run_id: str, shot_id: str, storyboard: Storyboard | None = None,
                             motion_map: dict | None = None, force: bool = False) -> Path:
        run_dir = self.assets.run_dir(run_id)
        if storyboard is None:
            storyboard = Storyboard.model_validate(self.assets.read_json(run_id, "analysis/storyboard.json"))
        if motion_map is None:
            motion_map = self.motion_router.motions
        shot = next(item for item in storyboard.shots if item.shot_id == shot_id)
        scene_config = next(item for item in self.scene_router.scenes if item["id"] == storyboard.scene_id)
        output = run_dir / "videos" / f"{shot_id}.mp4"
        for _ in range(self.retry.max_video_attempts):
            attempt = self.runs.increment_attempt(run_id, shot_id, "video")
            prompt_plan = self._prompt_plan(run_id)
            prompt = self.prompts.video_prompt(
                shot,
                motion_map[shot.motion_id],
                scene_config,
                prompt_addition=str(prompt_plan["video_prompt_addition"]),
            )
            (run_dir / "prompts" / f"{shot_id}_video_prompt.txt").write_text(prompt, encoding="utf-8")
            self.runs.event(run_id, "STEP_STARTED", step="VIDEO_GENERATION", shot=shot_id, attempt=attempt)
            async with self.video_semaphore:
                await self.video_provider.generate_video(run_dir / "keyframes" / f"{shot_id}.png", prompt, shot.duration, output)
            self._state(run_id, RunStatus.VIDEO_QA, f"Checking video {shot_id}", "video_qa", "running")
            analysis = ProductAnalysis.model_validate(
                self.assets.read_json(run_id, "analysis/product_analysis.json")
            )
            qa = await self.video_qa.evaluate(
                shot_id, output, attempt,
                run_dir / "keyframes" / f"{shot_id}.png",
                run_dir / "video_qa" / f"{shot_id}_frames",
                analysis.visible_details,
                ", ".join(scene_config["environment"]) + "; " + scene_config["lighting"],
            )
            self.assets.write_json(run_id, f"video_qa/{shot_id}.json", qa)
            if qa.status == "PASS":
                return output
            self.runs.event(run_id, "SHOT_RETRY", shot=shot_id, kind="video", attempt=attempt + 1)
        raise RuntimeError(f"Video {shot_id} failed after retries")

    async def compose(self, run_id: str, storyboard: Storyboard | None = None) -> Path:
        run_dir = self.assets.run_dir(run_id)
        if storyboard is None:
            storyboard = Storyboard.model_validate(self.assets.read_json(run_id, "analysis/storyboard.json"))
        self._state(run_id, RunStatus.COMPOSING, "Composing final vertical video", "composition", "running")
        clips = [run_dir / "videos" / f"{shot.shot_id}.mp4" for shot in storyboard.shots]
        final = run_dir / "final" / "final.mp4"
        await self.composer.compose(clips, final)
        self.assets.publish(run_id)
        self._state(run_id, RunStatus.COMPLETED, "Final video ready", "composition", "done")
        self.runs.event(run_id, "RUN_COMPLETED", final_video=f"/media/outputs/{run_id}/final.mp4")
        return final

    def _state(self, run_id: str, status: RunStatus, current: str, step: str, step_status: str) -> None:
        self.runs.update(run_id, status.value, PROGRESS[status.value], current, step, step_status)

    def _prompt_plan(self, run_id: str) -> dict:
        """Load the handler-built plan, rebuilding only for legacy unfinished runs."""
        plan_path = self.assets.run_dir(run_id) / "prompts" / "generation_prompt_plan.json"
        if plan_path.exists():
            return json.loads(plan_path.read_text(encoding="utf-8"))
        state = self.runs.get(run_id)
        plan = self.generation_prompts.build(
            state.image_template_id,
            state.video_style_id,
            state.output_type,
        )
        self.assets.write_json(
            run_id, "prompts/generation_prompt_plan.json", plan
        )
        return plan.model_dump(mode="json")

    @staticmethod
    def _qa_passed(path: Path) -> bool:
        if not path.exists():
            return False
        try:
            return str(json.loads(path.read_text(encoding="utf-8")).get("status", "")).upper() == "PASS"
        except (OSError, json.JSONDecodeError):
            return False
