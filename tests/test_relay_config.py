import json
from pathlib import Path

import pytest

from app.config import ROOT
from app.db.database import Database
from app.services.relay_config import RelayConfigStore, RelaySelection
from app.services.secret_store import EncryptedSecretStore


def build_store(tmp_path: Path) -> RelayConfigStore:
    db = Database(tmp_path / "app.db")
    secrets = EncryptedSecretStore(db, tmp_path / "master.key")
    return RelayConfigStore(db, ROOT / "config" / "provider_relays.json", secrets)


def test_capabilities_have_independent_provider_catalogs(tmp_path: Path):
    store = build_store(tmp_path)
    catalog = store.public_catalog()["capabilities"]

    vision = {item["id"]: item for item in catalog["vision"]["providers"]}
    image = {item["id"]: item for item in catalog["image"]["providers"]}
    video = {item["id"]: item for item in catalog["video"]["providers"]}

    assert set(vision) == {"kuaipao", "openai"}
    assert set(image) == {"kuaipao", "openai"}
    assert set(video) == {"kuaipao", "notoken", "openai"}
    assert vision["kuaipao"]["base_url"] == "https://kuaipao.pro/v1"
    assert image["kuaipao"]["models"] == [
        "gpt-image-1.5",
        "gpt-image-2",
        "gpt-image-2-1k",
        "gpt-image-2-2k",
        "gpt-image-2-4k",
        "gpt-image-2-4k-超分",
        "nana-banana-2",
        "nano-banana-2",
        "nano-banana-2-1k",
    ]
    assert video["kuaipao"]["models"] == [
        "doubao-seedance-2.0-1080p",
        "doubao-seedance-2.0-480p",
        "doubao-seedance-2.0-720p",
        "doubao-seedance-2.0-fast-480p",
        "doubao-seedance-2.0-fast-720p",
        "doubao-seedance-2.0-mini",
        "doubao-seedance-2.0-mini-480p",
        "doubao-seedance-2.0-mini-720p",
        "doubao-seedance-2.5-480p",
        "doubao-seedance-2.5-720p",
        "grok-imagine-video",
        "grok-imagine-video-1.5-preview",
        "sora-2",
        "sora-2-12s",
        "sora-2-8s",
        "veo_3_1",
        "veo_3_1-fast",
    ]
    assert [group["label"] for group in video["kuaipao"]["model_groups"]] == [
        "Seedance",
        "Grok Video",
        "Sora",
        "Veo",
    ]
    assert video["notoken"]["models"] == ["seedance-2.0"]


def test_provider_model_and_key_are_independent_per_capability(tmp_path: Path):
    store = build_store(tmp_path)
    selected = store.save(
        RelaySelection(
            vision_provider_id="kuaipao",
            vision_model="gpt-5.6-sol",
            image_provider_id="openai",
            image_model="gpt-image-2",
            video_provider_id="notoken",
            video_model="seedance-2.0",
        )
    )
    store.set_api_key("vision", "kuaipao", "VISION-KEY-1111")
    store.set_api_key("image", "openai", "IMAGE-KEY-2222")

    waiting = store.public_status()
    assert waiting["missing_capabilities"] == ["video"]
    assert selected.vision_provider_id == "kuaipao"
    assert selected.image_provider_id == "openai"
    assert selected.video_provider_id == "notoken"
    assert waiting["capabilities"]["vision"]["api_key_masked"].endswith("1111")
    assert waiting["capabilities"]["image"]["api_key_masked"].endswith("2222")

    store.set_api_key("video", "notoken", "VIDEO-KEY-3333")
    ready = store.public_status()
    assert ready["all_api_keys_configured"] is True
    assert store.api_key("vision", "kuaipao") == "VISION-KEY-1111"
    assert store.api_key("image", "openai") == "IMAGE-KEY-2222"
    assert store.api_key("video", "notoken") == "VIDEO-KEY-3333"
    assert "VISION-KEY" not in str(ready)
    assert "IMAGE-KEY" not in str(ready)
    assert "VIDEO-KEY" not in str(ready)


def test_legacy_single_relay_selection_and_key_are_migrated(tmp_path: Path):
    db = Database(tmp_path / "app.db")
    secrets = EncryptedSecretStore(db, tmp_path / "master.key")
    secrets.set("relay:kuaipao:api_key", "LEGACY-KP-KEY")
    secrets.set("relay:notoken:api_key", "LEGACY-NT-KEY")
    legacy = {
        "relay_id": "notoken",
        "vision_model": "gpt-5.6-sol",
        "image_model": "gpt-image-2",
        "video_model": "seedance-2.0",
    }
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?)",
            (RelayConfigStore.SETTINGS_KEY, json.dumps(legacy)),
        )

    store = RelayConfigStore(
        db, ROOT / "config" / "provider_relays.json", secrets
    )
    selected = store.selection()

    assert selected.vision_provider_id == "kuaipao"
    assert selected.image_provider_id == "kuaipao"
    assert selected.video_provider_id == "notoken"
    assert store.api_key("vision", "kuaipao") == "LEGACY-KP-KEY"
    assert store.api_key("image", "kuaipao") == "LEGACY-KP-KEY"
    assert store.api_key("video", "notoken") == "LEGACY-NT-KEY"
    assert secrets.get("relay:kuaipao:api_key") is None


def test_relay_rejects_provider_that_does_not_support_capability(tmp_path: Path):
    store = build_store(tmp_path)
    with pytest.raises(ValueError, match="does not support"):
        store.save(
            RelaySelection(
                vision_provider_id="notoken",
                vision_model="gpt-5.6-sol",
            )
        )
