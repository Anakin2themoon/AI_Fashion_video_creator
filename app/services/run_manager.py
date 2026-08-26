from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from app.db.database import Database
from app.domain.enums import TERMINAL_STATUSES
from app.domain.models import RunState
from app.services.asset_manager import AssetManager


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


DEFAULT_STEPS = {
    "product_analysis": "pending", "scene_router": "pending", "motion_router": "pending",
    "storyboard": "pending", "keyframe_generation": "pending", "image_qa": "pending",
    "video_generation": "pending", "video_qa": "pending", "composition": "pending"
}


class RunManager:
    def __init__(self, db: Database, assets: AssetManager):
        self.db = db
        self.assets = assets

    def create(
        self,
        character_id: str = "asian_girl_001",
        image_template_id: str = "realistic-photography",
        video_style_id: str = "video-cat-photo",
        output_type: str = "video",
    ) -> RunState:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid4().hex[:6]
        now = utc_now()
        state = RunState(run_id=run_id, status="CREATED", character_id=character_id,
                         image_template_id=image_template_id, video_style_id=video_style_id, progress=0,
                         output_type=output_type,
                         current_step="Created", created_at=now, updated_at=now, steps=dict(DEFAULT_STEPS))
        self.assets.create_run(run_id)
        self._persist(state)
        self.event(run_id, "RUN_CREATED", status="CREATED")
        return state

    def get(self, run_id: str) -> RunState:
        path = self.assets.run_dir(run_id) / "state.json"
        if not path.exists():
            raise KeyError(run_id)
        return RunState.model_validate_json(path.read_text(encoding="utf-8"))

    def update(self, run_id: str, status: str, progress: int, current_step: str, step: str | None = None, step_status: str | None = None, error: str | None = None) -> RunState:
        state = self.get(run_id)
        state.status = status
        state.progress = progress
        state.current_step = current_step
        state.updated_at = utc_now()
        state.error = error
        if step:
            state.steps[step] = step_status or "running"
        self._persist(state)
        self.event(run_id, "STATE_CHANGED", status=status, progress=progress, step=current_step)
        return state

    def increment_attempt(self, run_id: str, shot_id: str, kind: str) -> int:
        state = self.get(run_id)
        state.shot_attempts.setdefault(shot_id, {"keyframe": 0, "video": 0})
        state.shot_attempts[shot_id][kind] += 1
        state.updated_at = utc_now()
        self._persist(state)
        return state.shot_attempts[shot_id][kind]

    def event(self, run_id: str, event_type: str, **payload) -> None:
        event = {"time": utc_now(), "type": event_type, **payload}
        events_path = self.assets.run_dir(run_id) / "logs" / "events.jsonl"
        events_path.parent.mkdir(parents=True, exist_ok=True)
        with events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        with self.db.connect() as conn:
            conn.execute("INSERT INTO events(run_id,timestamp,event_type,payload) VALUES(?,?,?,?)",
                         (run_id, event["time"], event_type, json.dumps(event, ensure_ascii=False)))

    def list(self) -> list[RunState]:
        states = []
        for path in sorted((self.assets.workspace / "runs").glob("*/state.json"), reverse=True):
            try:
                states.append(RunState.model_validate_json(path.read_text(encoding="utf-8")))
            except Exception:
                continue
        return states

    def delete(self, run_id: str) -> None:
        run_dir = self.assets.run_dir(run_id)
        if not run_dir.exists():
            raise KeyError(run_id)
        shutil.rmtree(run_dir)
        output = self.assets.workspace / "outputs" / run_id
        if output.exists():
            shutil.rmtree(output)
        with self.db.connect() as conn:
            conn.execute("DELETE FROM events WHERE run_id=?", (run_id,))
            conn.execute("DELETE FROM shots WHERE run_id=?", (run_id,))
            conn.execute("DELETE FROM runs WHERE run_id=?", (run_id,))

    def mark_interrupted(self) -> list[str]:
        changed = []
        for state in self.list():
            if state.status not in TERMINAL_STATUSES and state.status != "CREATED":
                self.update(state.run_id, "INTERRUPTED", state.progress, "Interrupted; ready to resume")
                changed.append(state.run_id)
        return changed

    def events(self, run_id: str, after_id: int = 0) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT id,payload FROM events WHERE run_id=? AND id>? ORDER BY id", (run_id, after_id)).fetchall()
        return [{"id": row["id"], **json.loads(row["payload"])} for row in rows]

    def _persist(self, state: RunState) -> None:
        self.assets.write_json(state.run_id, "state.json", state)
        with self.db.connect() as conn:
            conn.execute("""INSERT INTO runs(run_id,status,progress,current_step,character_id,created_at,updated_at,error)
              VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET status=excluded.status,progress=excluded.progress,
              current_step=excluded.current_step,updated_at=excluded.updated_at,error=excluded.error""",
              (state.run_id, state.status, state.progress, state.current_step, state.character_id,
               state.created_at, state.updated_at, state.error))
