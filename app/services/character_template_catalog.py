from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class CharacterTemplateCatalog:
    def __init__(self, config_path: Path):
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        self.source: dict[str, Any] = dict(payload["source"])
        self._templates = {
            str(item["id"]): dict(item) for item in payload["templates"]
        }

    def list_public(self) -> list[dict[str, Any]]:
        return [
            {key: value for key, value in item.items() if key != "prompt"}
            for item in self._templates.values()
        ]

    def get(self, template_id: str) -> dict[str, Any]:
        try:
            return dict(self._templates[template_id])
        except KeyError as exc:
            raise KeyError(f"Character image template not found: {template_id}") from exc

