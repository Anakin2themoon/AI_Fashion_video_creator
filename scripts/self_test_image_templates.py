from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from time import monotonic
from typing import Any

import httpx
from PIL import Image


async def generate_one(
    client: httpx.AsyncClient,
    api_root: str,
    template: dict[str, Any],
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    started = monotonic()
    result: dict[str, Any] = {
        "template_id": template["id"],
        "template_name": template["name"],
        "category_id": template["category_id"],
        "status": "FAILED",
    }
    try:
        async with semaphore:
            response = await client.post(
                f"{api_root}/image-templates/{template['id']}/generate",
                json={"character_id": "asian_girl_001"},
            )
        response.raise_for_status()
        payload = response.json()
        media_url = "http://127.0.0.1:8000" + payload["image_url"]
        media = await client.get(media_url)
        media.raise_for_status()
        with Image.open(BytesIO(media.content)) as image:
            image.verify()
        with Image.open(BytesIO(media.content)) as image:
            width, height = image.size
            image_format = image.format
        result.update(
            {
                "status": "PASS",
                "generation_id": payload["generation_id"],
                "model": payload["model"],
                "image_url": payload["image_url"],
                "format": image_format,
                "width": width,
                "height": height,
                "bytes": len(media.content),
            }
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["elapsed_seconds"] = round(monotonic() - started, 2)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


async def run(api_root: str, concurrency: int, output_root: Path) -> int:
    timeout = httpx.Timeout(60.0, read=1000.0, write=60.0, pool=1000.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        catalog_response = await client.get(f"{api_root}/style-catalog")
        catalog_response.raise_for_status()
        catalog = catalog_response.json()
        templates = catalog["image_templates"]
        semaphore = asyncio.Semaphore(concurrency)
        results = await asyncio.gather(
            *(
                generate_one(client, api_root, template, semaphore)
                for template in templates
            )
        )

    category_ids = {item["id"] for item in catalog["categories"]}
    covered_categories = {
        result["category_id"] for result in results if result["status"] == "PASS"
    }
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "test_kind": "image_templates_only",
        "video_invoked": False,
        "api_root": api_root,
        "source": catalog["source"],
        "category_count": len(category_ids),
        "template_count": len(templates),
        "passed": sum(item["status"] == "PASS" for item in results),
        "failed": sum(item["status"] != "PASS" for item in results),
        "all_categories_covered": covered_categories == category_ids,
        "covered_category_ids": sorted(covered_categories),
        "results": results,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    report_path = output_root / "summary.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"REPORT={report_path.resolve()}", flush=True)
    return 0 if report["failed"] == 0 and report["all_categories_covered"] else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--api-root", default="http://127.0.0.1:8000/api/v1"
    )
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("workspace")
        / "image_template_selftest"
        / datetime.now().strftime("%Y%m%d_%H%M%S"),
    )
    args = parser.parse_args()
    return asyncio.run(run(args.api_root.rstrip("/"), args.concurrency, args.output))


if __name__ == "__main__":
    raise SystemExit(main())
