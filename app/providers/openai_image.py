import asyncio
import base64
import hashlib
import json
import mimetypes
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import httpx

from app.domain.models import Asset
from app.providers.base.image_provider import ImageProvider


class OpenAIImageProvider(ImageProvider):
    """High-fidelity identity + outfit/theme editing with GPT Image."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-image-2",
        base_url: str | None = None,
        client: Any | None = None,
        async_generation: bool = False,
        json_reference_generation: bool = False,
        timeout_seconds: int = 900,
        poll_interval: float = 5.0,
        transport_attempts: int = 3,
        transport_backoff_seconds: float = 5.0,
        http_client: httpx.Client | None = None,
    ):
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required when IMAGE_PROVIDER=openai")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.client = client
        self.async_generation = async_generation
        self.json_reference_generation = json_reference_generation
        self.timeout_seconds = timeout_seconds
        self.poll_interval = poll_interval
        self.transport_attempts = max(1, transport_attempts)
        self.transport_backoff_seconds = max(0.0, transport_backoff_seconds)
        self.http_client = http_client

    async def generate_keyframe(
        self,
        character_refs: list[Path],
        product_image: Path,
        prompt: str,
        output_path: Path,
    ) -> Asset:
        return await asyncio.to_thread(
            self._generate, character_refs, product_image, prompt, output_path
        )

    async def generate_from_references(
        self,
        reference_images: list[Path],
        prompt: str,
        output_path: Path,
        size: str = "1024x1536",
    ) -> Asset:
        if not reference_images:
            raise ValueError("At least one reference image is required")
        return await asyncio.to_thread(
            self._generate_reference_image,
            reference_images,
            prompt,
            output_path,
            size,
        )

    def _generate_reference_image(
        self,
        reference_images: list[Path],
        prompt: str,
        output_path: Path,
        size: str,
    ) -> Asset:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "Install the openai package to use IMAGE_PROVIDER=openai"
            ) from exc

        references = list(reference_images)
        if self.json_reference_generation and len(references) > 2:
            references = references[:2]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if self.json_reference_generation:
            return self._generate_json_references(
                references, prompt, output_path, size
            )
        if self.async_generation:
            return self._generate_async_references(
                references, prompt, output_path, size
            )

        client = self.client
        if client is None:
            kwargs = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            client = OpenAI(**kwargs)
        with ExitStack() as stack:
            inputs = [stack.enter_context(path.open("rb")) for path in references]
            result = client.images.edit(
                model=self.model,
                image=inputs,
                prompt=prompt,
                size=size,
                quality="high",
            )
        first = result.data[0]
        encoded = getattr(first, "b64_json", None)
        if encoded:
            output_path.write_bytes(base64.b64decode(encoded))
        else:
            url = getattr(first, "url", None)
            if not url:
                raise RuntimeError("Image relay returned neither b64_json nor URL")
            response = httpx.get(url, timeout=120, follow_redirects=True)
            response.raise_for_status()
            output_path.write_bytes(response.content)
        return Asset(path=str(output_path), media_type="image/png")

    def _generate_json_references(
        self,
        references: list[Path],
        prompt: str,
        output_path: Path,
        size: str,
    ) -> Asset:
        if not self.base_url:
            raise RuntimeError("JSON reference generation requires a base URL")
        return self._generate_relay_references(
            references, prompt, output_path, size, async_mode=False
        )

    def _generate_async_references(
        self,
        references: list[Path],
        prompt: str,
        output_path: Path,
        size: str,
    ) -> Asset:
        if not self.base_url:
            raise RuntimeError("Async image generation requires a base URL")
        return self._generate_relay_references(
            references, prompt, output_path, size, async_mode=True
        )

    def _generate_relay_references(
        self,
        references: list[Path],
        prompt: str,
        output_path: Path,
        size: str,
        async_mode: bool,
    ) -> Asset:
        attempt_dir = self._create_attempt_dir(output_path)
        prompt = prompt[:4000]
        endpoint = "/images/generations/async" if async_mode else "/images/generations"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "n": 1,
            "size": size,
            "quality": "high" if async_mode else "auto",
            "image": [self._data_uri(path) for path in references],
            "response_format": "url",
        }
        if not async_mode:
            payload["watermark"] = False
        manifest = [
            {
                "role": "character_identity_reference",
                "name": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            }
            for path in references
        ]
        (attempt_dir / "final_prompt.txt").write_text(prompt, encoding="utf-8")
        self._write_json(attempt_dir / "input_manifest.json", {"inputs": manifest})
        self._write_json(
            attempt_dir / "final_request.json",
            {
                "method": "POST",
                "endpoint": endpoint,
                "model": self.model,
                "size": size,
                "quality": payload["quality"],
                "response_format": "url",
                "reference_count": len(references),
                "references": manifest,
            },
        )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        client = self.http_client or httpx.Client(
            timeout=httpx.Timeout(60.0, read=140.0), follow_redirects=True
        )
        owns_client = self.http_client is None
        try:
            response = self._post_with_retry(
                client,
                f"{self.base_url.rstrip('/')}{endpoint}",
                headers,
                payload,
                attempt_dir,
            )
            result = self._safe_json(response)
            self._write_json(attempt_dir / "provider_response.json", result)
            item = self._first_image_result(result)
            if item is None and async_mode:
                task_id = result.get("id") or result.get("task_id") or result.get("taskId")
                if not task_id:
                    raise RuntimeError("Async image API returned neither task id nor image")
                result = self._poll_image_task(client, str(task_id), headers, attempt_dir)
                item = self._first_image_result(result)
            if item is None:
                raise RuntimeError("Character template task completed without an image")
            self._write_image_result(client, item, output_path)
            return Asset(path=str(output_path), media_type="image/png")
        except Exception as exc:
            self._write_json(
                attempt_dir / "image_gate.json",
                {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"},
            )
            raise
        finally:
            if owns_client:
                client.close()

    def _generate(
        self,
        character_refs: list[Path],
        product_image: Path,
        prompt: str,
        output_path: Path,
    ) -> Asset:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install the openai package to use IMAGE_PROVIDER=openai") from exc

        preferred_names = (
            "identity_face.png",
            "fullbody_front.png",
            "fullbody_45.png",
            "fullbody_side.png",
            "face_front.png",
            "body_front.png",
            "body_45.png",
            "body_side.png",
            "fullbody_neutral.png",
        )
        identity_refs = [
            next((path for path in character_refs if path.name == name), None)
            for name in preferred_names
        ]
        identity_refs = [path for path in identity_refs if path is not None]
        if not identity_refs:
            # Backward-compatible fallback for custom characters with one independent reference.
            identity_refs = [
                next(
                    (path for path in character_refs if path.name != "reference_sheet.png"),
                    character_refs[0],
                )
            ]
        if self.json_reference_generation and len(identity_refs) > 2:
            identity_refs = identity_refs[:2]
        product_index = len(identity_refs) + 1
        identity_role = (
            "Images 1 through " + str(len(identity_refs)) + " are independent human identity references. "
            if len(identity_refs) > 1
            else "Image 1 is the human identity sheet. "
        )
        strict_prompt = (
            "REFERENCE ROLES ARE STRICT. " + identity_role
            + f"Image {product_index} is the outfit or visual fashion theme reference. It may contain another person, "
            "helmet, mask, wings, weapons, handheld props, jewelry, butterflies, scenery, text or special "
            "effects. Transfer ONLY the wearable clothing layers fitted directly on the torso, shoulders, "
            "arms, waist, hips and legs, including body-worn garment/armor panels and their visible colors, "
            "materials, seams and silhouette. NEVER transfer the source person's face, head, hair, skin, "
            "body shape or pose. NEVER add a helmet, mask, horns, wings, sword, weapon, handheld object, "
            "floating object, butterfly, creature, logo, text, source background or fantasy effect. "
            "Create one coherent photorealistic fashion frame: keep the exact adult model identity from "
            "image 1 and replace only her white tank top and black leggings with the extracted body-worn "
            "outfit. Do not paste either source image and do not make a collage or model sheet. Keep the "
            "face and hair fully unobstructed.\n\n"
            + prompt
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if self.json_reference_generation:
            return self._generate_json_reference(
                identity_refs, product_image, strict_prompt, output_path
            )
        if self.async_generation:
            return self._generate_async(
                identity_refs, product_image, strict_prompt, output_path
            )
        client = self.client
        if client is None:
            kwargs = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            client = OpenAI(**kwargs)
        with ExitStack() as stack:
            inputs = [stack.enter_context(path.open("rb")) for path in identity_refs]
            inputs.append(stack.enter_context(product_image.open("rb")))
            result = client.images.edit(
                model=self.model,
                image=inputs,
                prompt=strict_prompt,
                size="1024x1536",
                quality="high",
            )
        first = result.data[0]
        encoded = getattr(first, "b64_json", None)
        if encoded:
            output_path.write_bytes(base64.b64decode(encoded))
        else:
            url = getattr(first, "url", None)
            if not url:
                raise RuntimeError("Image relay returned neither b64_json nor URL")
            response = httpx.get(url, timeout=120, follow_redirects=True)
            response.raise_for_status()
            output_path.write_bytes(response.content)
        return Asset(path=str(output_path), media_type="image/png")

    def _generate_json_reference(
        self,
        identity_refs: list[Path],
        product_image: Path,
        strict_prompt: str,
        output_path: Path,
    ) -> Asset:
        if not self.base_url:
            raise RuntimeError("JSON reference generation requires a base URL")
        references = [*identity_refs, product_image]
        attempt_dir = self._create_attempt_dir(output_path)
        prompt = strict_prompt[:4000]
        payload = {
            "model": self.model,
            "prompt": prompt,
            "n": 1,
            "size": "1024x1536",
            "quality": "auto",
            "image": [self._data_uri(path) for path in references],
            "response_format": "url",
            "watermark": False,
        }
        (attempt_dir / "final_prompt.txt").write_text(prompt, encoding="utf-8")
        manifest = self._reference_manifest(identity_refs, product_image)
        self._write_json(attempt_dir / "input_manifest.json", {"inputs": manifest})
        self._write_json(
            attempt_dir / "final_request.json",
            {
                "method": "POST",
                "endpoint": "/images/generations",
                "model": self.model,
                "size": payload["size"],
                "quality": payload["quality"],
                "response_format": payload["response_format"],
                "watermark": False,
                "reference_count": len(references),
                "references": manifest,
            },
        )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        client = self.http_client or httpx.Client(
            timeout=httpx.Timeout(60.0, read=140.0), follow_redirects=True
        )
        owns_client = self.http_client is None
        try:
            response = self._post_with_retry(
                client,
                f"{self.base_url.rstrip('/')}/images/generations",
                headers,
                payload,
                attempt_dir,
            )
            result = self._safe_json(response)
            self._write_json(attempt_dir / "provider_response.json", result)
            item = self._first_image_result(result)
            if item is None:
                raise RuntimeError("Reference image API completed without an image result")
            self._write_image_result(client, item, output_path)
            return Asset(path=str(output_path), media_type="image/png")
        except Exception as exc:
            self._write_json(
                attempt_dir / "image_gate.json",
                {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"},
            )
            raise
        finally:
            if owns_client:
                client.close()

    def _post_with_retry(
        self,
        client: httpx.Client,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        attempt_dir: Path,
    ) -> httpx.Response:
        """Retry relay transport failures without regenerating completed shots."""
        events_path = attempt_dir / "transport_events.jsonl"
        for attempt in range(1, self.transport_attempts + 1):
            try:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                self._append_jsonl(
                    events_path,
                    {"attempt": attempt, "status": "success", "http_status": response.status_code},
                )
                return response
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                status = (
                    exc.response.status_code
                    if isinstance(exc, httpx.HTTPStatusError)
                    else None
                )
                retryable = status is None or status == 429 or status >= 500
                self._append_jsonl(
                    events_path,
                    {
                        "attempt": attempt,
                        "status": "retrying" if retryable and attempt < self.transport_attempts else "failed",
                        "http_status": status,
                        "error_type": type(exc).__name__,
                    },
                )
                if not retryable or attempt >= self.transport_attempts:
                    raise
                time.sleep(self.transport_backoff_seconds * attempt)
        raise RuntimeError("Image relay transport retry loop ended unexpectedly")

    def _generate_async(
        self,
        identity_refs: list[Path],
        product_image: Path,
        strict_prompt: str,
        output_path: Path,
    ) -> Asset:
        if not self.base_url:
            raise RuntimeError("Async image generation requires a base URL")
        references = [*identity_refs, product_image]
        attempt_dir = self._create_attempt_dir(output_path)
        prompt = strict_prompt[:4000]
        payload = {
            "model": self.model,
            "prompt": prompt,
            "n": 1,
            "size": "1024x1536",
            "quality": "high",
            "image": [self._data_uri(path) for path in references],
            "response_format": "url",
        }
        (attempt_dir / "final_prompt.txt").write_text(prompt, encoding="utf-8")
        manifest = [
            {
                "role": "identity_reference" if index < len(identity_refs) else "outfit_reference",
                "name": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            }
            for index, path in enumerate(references)
        ]
        self._write_json(attempt_dir / "input_manifest.json", {"inputs": manifest})
        self._write_json(
            attempt_dir / "final_request.json",
            {
                "method": "POST",
                "endpoint": "/images/generations/async",
                "model": self.model,
                "size": payload["size"],
                "quality": payload["quality"],
                "response_format": payload["response_format"],
                "reference_count": len(references),
                "references": manifest,
            },
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        client = self.http_client or httpx.Client(
            timeout=httpx.Timeout(60.0, read=120.0), follow_redirects=True
        )
        owns_client = self.http_client is None
        try:
            response = client.post(
                f"{self.base_url.rstrip('/')}/images/generations/async",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = self._safe_json(response)
            self._write_json(attempt_dir / "provider_response.json", result)
            item = self._first_image_result(result)
            if item is None:
                task_id = result.get("id") or result.get("task_id") or result.get("taskId")
                if not task_id:
                    raise RuntimeError("Async image API returned neither task id nor image")
                result = self._poll_image_task(client, str(task_id), headers, attempt_dir)
                item = self._first_image_result(result)
            if item is None:
                raise RuntimeError("Async image task completed without an image result")
            encoded = item.get("b64_json")
            if encoded:
                output_path.write_bytes(base64.b64decode(encoded))
            else:
                url = item.get("url")
                if not url:
                    raise RuntimeError("Async image result returned neither b64_json nor URL")
                download_headers = (
                    {"Authorization": f"Bearer {self.api_key}"}
                    if str(url).startswith(self.base_url.rstrip("/"))
                    else {}
                )
                media = client.get(str(url), headers=download_headers)
                media.raise_for_status()
                output_path.write_bytes(media.content)
            return Asset(path=str(output_path), media_type="image/png")
        except Exception as exc:
            self._write_json(
                attempt_dir / "image_gate.json",
                {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"},
            )
            raise
        finally:
            if owns_client:
                client.close()

    def _poll_image_task(
        self,
        client: httpx.Client,
        task_id: str,
        headers: dict[str, str],
        attempt_dir: Path,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout_seconds
        last_event: tuple[str, Any] | None = None
        events_path = attempt_dir / "task_events.jsonl"
        while time.monotonic() < deadline:
            response = client.get(
                f"{self.base_url.rstrip('/')}/images/generations/async/{task_id}",
                headers=headers,
            )
            response.raise_for_status()
            result = self._safe_json(response)
            status = str(result.get("status", "")).lower()
            progress = result.get("progress")
            event = (status, progress)
            if event != last_event:
                with events_path.open("a", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {"status": status, "progress": progress},
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                last_event = event
            if status in {"completed", "succeeded", "success"}:
                self._write_json(attempt_dir / "provider_response.json", result)
                return result
            if status in {"failed", "error", "cancelled", "canceled"}:
                error = result.get("error") or result.get("message") or status
                raise RuntimeError(f"Async image task {task_id} failed: {error}")
            if status and status not in {
                "queued",
                "pending",
                "processing",
                "in_progress",
                "running",
                "created",
            }:
                raise RuntimeError(
                    f"Async image task {task_id} returned unknown status: {status}"
                )
            time.sleep(self.poll_interval)
        raise TimeoutError(f"Async image task {task_id} exceeded {self.timeout_seconds}s")

    def _create_attempt_dir(self, output_path: Path) -> Path:
        root = output_path.parents[1] / "image_requests"
        root.mkdir(parents=True, exist_ok=True)
        count = len(list(root.glob(f"{output_path.stem}_*"))) + 1
        safe_model = "".join(
            char if char.isalnum() or char in "-_" else "_" for char in self.model
        )
        attempt = root / f"{output_path.stem}_{count:02d}_{safe_model}"
        attempt.mkdir(parents=True, exist_ok=False)
        return attempt

    def _reference_manifest(
        self, identity_refs: list[Path], product_image: Path
    ) -> list[dict[str, Any]]:
        references = [*identity_refs, product_image]
        return [
            {
                "role": (
                    "identity_reference"
                    if index < len(identity_refs)
                    else "outfit_reference"
                ),
                "name": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            }
            for index, path in enumerate(references)
        ]

    def _write_image_result(
        self, client: httpx.Client, item: dict[str, Any], output_path: Path
    ) -> None:
        encoded = item.get("b64_json")
        if encoded:
            output_path.write_bytes(base64.b64decode(encoded))
            return
        url = item.get("url")
        if not url:
            raise RuntimeError("Image result returned neither b64_json nor URL")
        download_headers = (
            {"Authorization": f"Bearer {self.api_key}"}
            if self.base_url and str(url).startswith(self.base_url.rstrip("/"))
            else {}
        )
        media = client.get(str(url), headers=download_headers)
        media.raise_for_status()
        output_path.write_bytes(media.content)

    @staticmethod
    def _data_uri(path: Path) -> str:
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    @staticmethod
    def _safe_json(response: httpx.Response) -> dict[str, Any]:
        payload = response.json()
        return payload if isinstance(payload, dict) else {"data": payload}

    @staticmethod
    def _first_image_result(payload: dict[str, Any]) -> dict[str, Any] | None:
        data = payload.get("data")
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and (item.get("url") or item.get("b64_json")):
                    return item
        return None

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _append_jsonl(path: Path, payload: Any) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
