from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from app.services.character_template_catalog import CharacterTemplateCatalog
from app.services.generation_prompt_builder import GenerationPromptBuilder


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "workspace" / "prompt_builder_selftest" / "latest",
    )
    args = parser.parse_args()

    catalog = CharacterTemplateCatalog(
        ROOT / "config" / "awesome_style_library.json",
        ROOT / "config" / "character_image_templates.json",
    )
    builder = GenerationPromptBuilder(catalog)
    public = catalog.public_catalog()
    results = []
    failures = []
    for image_template in public["image_templates"]:
        for video_style in public["video_styles"]:
            for output_type in ("image", "video"):
                case_id = (
                    f"{image_template['id']}|{video_style['id']}|{output_type}"
                )
                try:
                    plan = builder.build(
                        image_template["id"],
                        video_style["id"],
                        output_type,
                        "Natural morning light and a relaxed everyday mood.",
                    )
                    assert plan.image_template.id == image_template["id"]
                    assert plan.video_style.id == video_style["id"]
                    assert "TASK IMAGE TEMPLATE" in plan.image_prompt_addition
                    assert "VIDEO STYLE" not in plan.image_prompt_addition
                    assert "VIDEO STYLE" in plan.video_prompt_addition
                    assert "TASK IMAGE TEMPLATE" not in plan.video_prompt_addition
                    assert plan.prompt_input in plan.task_image.prompt
                    results.append(case_id)
                except Exception as exc:  # pragma: no cover - report path
                    failures.append(
                        {"case": case_id, "error": f"{type(exc).__name__}: {exc}"}
                    )

    report = {
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "test_kind": "prompt_builder_only",
        "provider_invoked": False,
        "image_provider_invoked": False,
        "video_provider_invoked": False,
        "category_count": len(public["categories"]),
        "image_template_count": len(public["image_templates"]),
        "video_style_count": len(public["video_styles"]),
        "output_type_count": 2,
        "expected_cases": (
            len(public["image_templates"])
            * len(public["video_styles"])
            * 2
        ),
        "passed": len(results),
        "failed": len(failures),
        "failures": failures,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    report_path = args.output / "summary.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))
    print(report_path.resolve())
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
