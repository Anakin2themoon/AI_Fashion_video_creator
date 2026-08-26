from dataclasses import dataclass
from app.config import Settings
from app.db.database import Database
from app.services.config_loader import ConfigLoader
from app.services.asset_manager import AssetManager
from app.services.run_manager import RunManager
from app.services.character_registry import CharacterRegistry
from app.services.character_template_catalog import CharacterTemplateCatalog
from app.services.prompt_builder import PromptBuilder
from app.services.ffmpeg_service import FFmpegService
from app.agents.product_analyzer import ProductAnalyzer
from app.agents.scene_router import SceneRouter
from app.agents.motion_router import MotionRouter
from app.agents.storyboard_generator import StoryboardGenerator
from app.agents.image_qa import ImageQA
from app.agents.video_qa import VideoQA
from app.providers.mock.mock_vision import MockVisionProvider
from app.providers.mock.mock_image import MockImageProvider
from app.providers.mock.mock_video import MockVideoProvider
from app.providers.mock.mock_composer import FFmpegComposer
from app.providers.openai_image import OpenAIImageProvider
from app.providers.openai_vision import OpenAIVisionProvider
from app.providers.openai_visual_qa import OpenAIVisualQAProvider
from app.providers.runway_video import RunwayVideoProvider
from app.services.secret_store import EncryptedSecretStore
from app.services.relay_config import RelayConfigStore
from app.services.provider_manager import RuntimeProviderManager
from app.orchestrator.retry_policy import RetryPolicy
from app.orchestrator.orchestrator import Orchestrator
from app.orchestrator.job_runner import LocalJobRunner


@dataclass
class Container:
    settings: Settings
    assets: AssetManager
    runs: RunManager
    orchestrator: Orchestrator
    runner: LocalJobRunner
    ffmpeg: FFmpegService
    db: Database
    secrets: EncryptedSecretStore
    relay_config: RelayConfigStore
    provider_manager: RuntimeProviderManager
    character_templates: CharacterTemplateCatalog


def build_container(settings: Settings) -> Container:
    loader = ConfigLoader(settings.config_dir)
    assets = AssetManager(settings.workspace_dir)
    db = Database(settings.workspace_dir / "app.db")
    secrets = EncryptedSecretStore(db, settings.workspace_dir / ".secrets" / "master.key")
    relay_config = RelayConfigStore(db, settings.config_dir / "provider_relays.json", secrets)
    runs = RunManager(db, assets)
    ffmpeg = FFmpegService(settings.ffmpeg_path, settings.ffprobe_path)
    if settings.vision_provider == "openai" and settings.openai_api_key:
        vision = OpenAIVisionProvider(
            settings.openai_api_key,
            settings.openai_vision_model,
            settings.prompts_dir / "product_analysis.md",
        )
    elif settings.vision_provider in {"mock", "openai", "unconfigured"}:
        vision = MockVisionProvider()
    else:
        raise RuntimeError(f"Unsupported VISION_PROVIDER: {settings.vision_provider}")
    if settings.image_provider == "openai" and settings.openai_api_key:
        image = OpenAIImageProvider(settings.openai_api_key, settings.openai_image_model)
    elif settings.image_provider in {"mock", "openai", "unconfigured"}:
        image = MockImageProvider()
    else:
        raise RuntimeError(f"Unsupported IMAGE_PROVIDER: {settings.image_provider}")
    if settings.video_provider in {"mock", "ffmpeg_camera", "relay", "unconfigured"}:
        video = MockVideoProvider(ffmpeg)
    elif settings.video_provider == "runway":
        video = RunwayVideoProvider(
            settings.runway_secret,
            settings.runway_video_model,
            settings.runway_timeout_seconds,
            ffmpeg=ffmpeg,
        )
    else:
        raise RuntimeError(f"Unsupported VIDEO_PROVIDER: {settings.video_provider}")
    composer = FFmpegComposer(ffmpeg)
    analyzer = ProductAnalyzer(vision)
    scene_router = SceneRouter(loader.load("scene_library.json"), loader.load("scene_router.json"))
    motion_router = MotionRouter(loader.load("motion_library.json"), loader.load("motion_router.json"))
    storyboard = StoryboardGenerator(loader.load("storyboard_template.json"))
    qa_rules = loader.load("qa_rules.json")
    visual_qa = None
    if settings.vision_provider == "openai" and settings.openai_api_key:
        visual_qa = OpenAIVisualQAProvider(
            settings.openai_api_key,
            settings.openai_vision_model,
            settings.prompts_dir / "image_qa.md",
            settings.prompts_dir / "video_qa.md",
        )
    orchestrator = Orchestrator(
        analyzer, scene_router, motion_router, storyboard, image, ImageQA(qa_rules["image"], visual_qa),
        video, VideoQA(qa_rules["video"], visual_qa, ffmpeg), composer, CharacterRegistry(settings.character_dir),
        PromptBuilder(settings.prompts_dir, video_generated_environment=settings.video_provider == "runway"), assets, runs, RetryPolicy(),
        settings.max_concurrent_image_tasks, settings.max_concurrent_video_tasks,
    )
    provider_manager = RuntimeProviderManager(settings, relay_config, ffmpeg)
    provider_manager.bind(orchestrator)
    character_templates = CharacterTemplateCatalog(
        settings.config_dir / "character_image_templates.json"
    )
    return Container(
        settings,
        assets,
        runs,
        orchestrator,
        LocalJobRunner(orchestrator, settings.max_concurrent_runs),
        ffmpeg,
        db,
        secrets,
        relay_config,
        provider_manager,
        character_templates,
    )
