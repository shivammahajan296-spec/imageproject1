import json
import sqlite3
from pathlib import Path
from typing import Any

from app.models import SessionState


class SessionStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    def get_or_create(self, session_id: str) -> SessionState:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT state_json FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row:
            return SessionState.model_validate_json(row["state_json"])
        state = SessionState(session_id=session_id)
        self.save(state)
        return state

    def save(self, state: SessionState) -> None:
        payload = state.model_dump_json()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO sessions(session_id, state_json, updated_at)
                VALUES(?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(session_id)
                DO UPDATE SET state_json = excluded.state_json, updated_at = CURRENT_TIMESTAMP
                """,
                (state.session_id, payload),
            )
            conn.commit()

    def as_dict(self, session_id: str) -> dict:
        state = self.get_or_create(session_id)
        return json.loads(state.model_dump_json())

    def save_checkpoint(self, session_id: str, label: str | None = None) -> tuple[int, str]:
        state = self.get_or_create(session_id)
        payload = state.model_dump_json()
        checkpoint_label = (label or f"STEP {state.step} checkpoint").strip()[:120]
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO session_checkpoints(session_id, label, state_json, created_at)
                VALUES(?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (session_id, checkpoint_label, payload),
            )
            row = conn.execute(
                "SELECT created_at FROM session_checkpoints WHERE id = ?",
                (cur.lastrowid,),
            ).fetchone()
            conn.commit()
        return int(cur.lastrowid), str(row["created_at"]) if row else ""

    def progress_snapshot(self) -> dict[str, list[dict[str, Any]]]:
        with self._conn() as conn:
            session_rows = conn.execute(
                "SELECT session_id, state_json, updated_at FROM sessions ORDER BY updated_at DESC"
            ).fetchall()
            checkpoint_rows = conn.execute(
                "SELECT id, session_id, label, state_json, created_at FROM session_checkpoints ORDER BY created_at DESC LIMIT 100"
            ).fetchall()

        approved_designs: list[dict[str, Any]] = []
        in_progress: list[dict[str, Any]] = []
        for row in session_rows:
            raw = json.loads(row["state_json"])
            step = int(raw.get("step", 1))
            approved = bool(raw.get("cadquery_code")) or step >= 7
            item = {
                "session_id": row["session_id"],
                "step": step,
                "updated_at": row["updated_at"],
                "approved": approved,
                "baseline_decision": raw.get("baseline_decision"),
                "design_summary": raw.get("design_summary"),
            }
            if approved:
                approved_designs.append(item)
            else:
                in_progress.append(item)

        checkpoints: list[dict[str, Any]] = []
        for row in checkpoint_rows:
            raw = json.loads(row["state_json"])
            checkpoints.append(
                {
                    "checkpoint_id": int(row["id"]),
                    "session_id": row["session_id"],
                    "label": row["label"],
                    "created_at": row["created_at"],
                    "step": int(raw.get("step", 1)),
                }
            )

        return {
            "in_progress": in_progress,
            "approved_designs": approved_designs,
            "checkpoints": checkpoints,
        }
