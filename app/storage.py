import json
import sqlite3
from pathlib import Path

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
