from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings
from app.orchestrator.orchestrator import Orchestrator
from app.providers.openai_image import OpenAIImageProvider
from app.providers.openai_vision import OpenAIVisionProvider
from app.providers.openai_visual_qa import OpenAIVisualQAProvider
from app.providers.openai_video import OpenAIVideoProvider
from app.providers.relay_video import RelayVideoProvider
from app.services.ffmpeg_service import FFmpegService
from app.services.relay_config import (
    CAPABILITIES,
    CAPABILITY_LABELS,
    RelayConfigStore,
    RelaySelection,
)


class RuntimeProviderManager:
    def __init__(
        self,
        settings: Settings,
        relay_config: RelayConfigStore,
        ffmpeg: FFmpegService,
    ):
        self.settings = settings
        self.relay_config = relay_config
        self.ffmpeg = ffmpeg
        self.orchestrator: Orchestrator | None = None

    def bind(self, orchestrator: Orchestrator) -> None:
        self.orchestrator = orchestrator
        if self.configured:
            self.apply()

    @property
    def configured(self) -> bool:
        return not self.relay_config.missing_capabilities()

    def apply(self) -> None:
        if self.orchestrator is None:
            raise RuntimeError("Provider manager is not bound to the orchestrator")
        selection = self.relay_config.selection()
        missing = self.relay_config.missing_capabilities(selection)
        if missing:
            labels = "、".join(
                self.relay_config.public_status()["missing_capability_labels"]
            )
            raise RuntimeError(f"API Key is not configured for {labels}")

        vision_profile = self.relay_config.profile(selection.vision_provider_id)
        video_profile = self.relay_config.profile(selection.video_provider_id)
        vision_api_key = self.relay_config.api_key(
            "vision", selection.vision_provider_id
        )
        image_api_key = self.relay_config.api_key("image", selection.image_provider_id)
        video_api_key = self.relay_config.api_key("video", selection.video_provider_id)
        assert vision_api_key and image_api_key and video_api_key

        vision = OpenAIVisionProvider(
            vision_api_key,
            selection.vision_model,
            self.settings.prompts_dir / "product_analysis.md",
            base_url=vision_profile.openai_base_url,
        )
        image = self.build_image_provider(selection)
        visual_qa = OpenAIVisualQAProvider(
            vision_api_key,
            selection.vision_model,
            self.settings.prompts_dir / "image_qa.md",
            self.settings.prompts_dir / "video_qa.md",
            base_url=vision_profile.openai_base_url,
        )
        if video_profile.video["protocol"] == "openai":
            video = OpenAIVideoProvider(
                video_api_key,
                selection.video_model,
                timeout_seconds=self.settings.relay_video_timeout_seconds,
                poll_interval=self.settings.relay_video_poll_interval_seconds,
                ffmpeg=self.ffmpeg,
            )
        else:
            video = RelayVideoProvider(
                video_api_key,
                video_profile,
                selection.video_model,
                timeout_seconds=self.settings.relay_video_timeout_seconds,
                poll_interval=self.settings.relay_video_poll_interval_seconds,
                ffmpeg=self.ffmpeg,
            )

        self.orchestrator.analyzer.provider = vision
        self.orchestrator.image_provider = image
        self.orchestrator.image_qa.provider = visual_qa
        self.orchestrator.video_provider = video
        self.orchestrator.video_qa.provider = visual_qa
        self.orchestrator.prompts.video_generated_environment = True
        self.settings.provider_mode = "real"
        self.settings.vision_provider = "openai"
        self.settings.image_provider = "openai"
        self.settings.video_provider = "relay"
        self.settings.openai_vision_model = selection.vision_model
        self.settings.openai_image_model = selection.image_model
        self.settings.relay_id = selection.video_provider_id
        self.settings.relay_video_model = selection.video_model

    def build_image_provider(
        self, selection: RelaySelection | None = None
    ) -> OpenAIImageProvider:
        """Build the image capability without requiring vision or video keys."""
        selection = selection or self.relay_config.selection()
        profile = self.relay_config.profile(selection.image_provider_id)
        api_key = self.relay_config.api_key(
            "image", selection.image_provider_id
        )
        if not api_key:
            raise RuntimeError(
                f"{profile.label} 换装图片 API Key 尚未配置"
            )
        protocol = profile.data.get("image", {}).get("protocol")
        return OpenAIImageProvider(
            api_key,
            selection.image_model,
            base_url=profile.openai_base_url,
            async_generation=protocol == "kuaipao_async",
            json_reference_generation=protocol == "kuaipao_json_reference",
            timeout_seconds=self.settings.relay_video_timeout_seconds,
            poll_interval=self.settings.relay_video_poll_interval_seconds,
        )

    def clear_active_key(self, capability: str = "video") -> None:
        selection = self.relay_config.selection()
        self.relay_config.delete_api_key(
            capability, selection.provider_id(capability)
        )
        self.deactivate()

    def deactivate(self) -> None:
        self.settings.provider_mode = "unconfigured"
        self.settings.vision_provider = "unconfigured"
        self.settings.image_provider = "unconfigured"
        self.settings.video_provider = "unconfigured"

    async def test_connection(
        self,
        selection: RelaySelection | None = None,
        capability: str | None = None,
    ) -> dict[str, Any]:
        selection = selection or self.relay_config.selection()
        capabilities = [capability] if capability else list(CAPABILITIES)
        missing = [
            item
            for item in capabilities
            if not self.relay_config.api_key(item, selection.provider_id(item))
        ]
        if missing:
            status = self.relay_config.public_status()["capabilities"]
            labels = "、".join(
                f"{status[item]['provider_label']} {item} API Key" for item in missing
            )
            return {"connected": False, "message": f"请先保存 {labels}"}
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                connected_labels = []
                for item in capabilities:
                    provider_id = selection.provider_id(item)
                    profile = self.relay_config.profile(provider_id)
                    api_key = self.relay_config.api_key(item, provider_id)
                    path = str(profile.data["connection_test_path"])
                    url = f"{profile.api_root}/{path.lstrip('/')}"
                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Accept": "application/json",
                    }
                    response = await client.get(url, headers=headers)
                    if response.status_code in {401, 403}:
                        return {
                            "connected": False,
                            "message": f"{profile.label} {item} API Key 无效或无权限",
                        }
                    if response.status_code >= 500:
                        return {
                            "connected": False,
                            "message": (
                                f"{profile.label} {item} 暂时不可用"
                                f"（HTTP {response.status_code}）"
                            ),
                        }
                    available_models = self._available_model_ids(response)
                    selected_model = selection.model(item)
                    if available_models and selected_model not in available_models:
                        return {
                            "connected": False,
                            "capability": item,
                            "provider_id": provider_id,
                            "model": selected_model,
                            "message": (
                                f"{profile.label} {CAPABILITY_LABELS[item]} API Key "
                                f"所属模型分组不包含 {selected_model}；请为该 API "
                                "使用包含当前模型的独立 Key，或更换为该 Key 可用的模型。"
                            ),
                        }
                    connected_labels.append(f"{profile.label} {item}")
            message = f"{' + '.join(connected_labels)} 连接成功"
            if "video" in capabilities:
                message = (
                    f"{' + '.join(connected_labels)} 模型目录连接成功；"
                    "实际生成通道仍以任务创建结果为准"
                )
            return {"connected": True, "message": message}
        except httpx.HTTPError as exc:
            return {"connected": False, "message": f"连接失败：{type(exc).__name__}"}

    @staticmethod
    def _available_model_ids(response: httpx.Response) -> set[str]:
        """Return model ids only when the endpoint actually returned a model catalog."""
        if response.status_code != 200:
            return set()
        try:
            payload = response.json()
        except ValueError:
            return set()
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            return set()
        return {
            str(item["id"])
            for item in payload["data"]
            if isinstance(item, dict) and item.get("id")
        }
