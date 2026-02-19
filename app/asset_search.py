from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from app.models import DesignSpec
from app.straive_client import StraiveClient

logger = logging.getLogger(__name__)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


class AssetCatalog:
    def __init__(self, db_path: str, assets_dir: str) -> None:
        self.db_path = db_path
        self.assets_dir = Path(assets_dir)
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS asset_metadata (
                    asset_path TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    product_type TEXT,
                    material TEXT,
                    closure_type TEXT,
                    design_style TEXT,
                    size_or_volume TEXT,
                    tags TEXT,
                    summary TEXT,
                    metadata_json TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    def list_assets(self) -> list[Path]:
        files: list[Path] = []
        for p in self.assets_dir.rglob("*"):
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                files.append(p)
        return sorted(files)

    async def index_assets(
        self,
        straive: StraiveClient,
        force_reindex: bool = False,
        api_key_override: str | None = None,
    ) -> tuple[int, int]:
        assets = self.list_assets()
        deleted = self._prune_deleted_assets(assets)
        if deleted:
            logger.info("Pruned %s deleted asset metadata rows.", deleted)
        indexed = 0
        for asset in assets:
            if not force_reindex and self._has_asset(asset) and not self._asset_needs_reindex(asset):
                continue
            metadata = await straive.describe_packaging_asset(asset, api_key_override=api_key_override)
            self._upsert_metadata(asset, metadata)
            indexed += 1
        return indexed, len(assets)

    def metadata_count(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM asset_metadata").fetchone()
        return int(row["c"]) if row else 0

    def list_catalog(self, limit: int = 300) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT asset_path, filename, product_type, material, closure_type, design_style,
                       size_or_volume, tags, summary, metadata_json, updated_at
                FROM asset_metadata
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            metadata_obj: dict[str, Any] | None = None
            raw_metadata = row["metadata_json"]
            if raw_metadata:
                try:
                    parsed = json.loads(raw_metadata)
                    metadata_obj = parsed if isinstance(parsed, dict) else None
                except Exception:
                    metadata_obj = None
            out.append(
                {
                    "asset_rel_path": self._relative_asset_path(row["asset_path"]),
                    "filename": row["filename"],
                    "product_type": row["product_type"],
                    "material": row["material"],
                    "closure_type": row["closure_type"],
                    "design_style": row["design_style"],
                    "size_or_volume": row["size_or_volume"],
                    "tags": row["tags"],
                    "summary": row["summary"],
                    "metadata_json": metadata_obj,
                    "updated_at": row["updated_at"],
                }
            )
        return out

    def _has_asset(self, asset: Path) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM asset_metadata WHERE asset_path = ?",
                (str(asset),),
            ).fetchone()
        return row is not None

    def _asset_needs_reindex(self, asset: Path) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT product_type, material, closure_type, design_style, size_or_volume
                FROM asset_metadata
                WHERE asset_path = ?
                """,
                (str(asset),),
            ).fetchone()
        if not row:
            return True
        required_cols = ["product_type", "material", "closure_type", "design_style", "size_or_volume"]
        for col in required_cols:
            value = row[col]
            if value is None or str(value).strip() == "":
                return True
        return False

    def _prune_deleted_assets(self, existing_assets: list[Path]) -> int:
        # Normalize all on-disk assets to absolute paths so we can compare reliably
        # even if DB rows were written with relative paths in earlier sessions.
        existing_resolved = {str(p.resolve()) for p in existing_assets}
        with self._conn() as conn:
            rows = conn.execute("SELECT asset_path FROM asset_metadata").fetchall()
            stale_paths: list[str] = []
            for row in rows:
                raw_path = row["asset_path"]
                try:
                    resolved = str(Path(raw_path).resolve())
                except Exception:
                    resolved = raw_path
                if resolved not in existing_resolved and not Path(raw_path).is_file():
                    stale_paths.append(raw_path)

            if stale_paths:
                conn.executemany(
                    "DELETE FROM asset_metadata WHERE asset_path = ?",
                    [(p,) for p in stale_paths],
                )
                conn.commit()
            return len(stale_paths)

    def _upsert_metadata(self, asset: Path, metadata: dict[str, Any]) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO asset_metadata(
                    asset_path, filename, product_type, material, closure_type, design_style,
                    size_or_volume, tags, summary, metadata_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(asset_path) DO UPDATE SET
                    filename=excluded.filename,
                    product_type=excluded.product_type,
                    material=excluded.material,
                    closure_type=excluded.closure_type,
                    design_style=excluded.design_style,
                    size_or_volume=excluded.size_or_volume,
                    tags=excluded.tags,
                    summary=excluded.summary,
                    metadata_json=excluded.metadata_json,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    str(asset),
                    asset.name,
                    metadata.get("product_type"),
                    metadata.get("material"),
                    metadata.get("closure_type"),
                    metadata.get("design_style"),
                    metadata.get("size_or_volume"),
                    ", ".join(metadata.get("tags", [])),
                    metadata.get("summary"),
                    json.dumps(metadata),
                ),
            )
            conn.commit()

    def find_matches(self, spec: DesignSpec, min_score: int = 2, limit: int = 5) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM asset_metadata").fetchall()
        if not rows:
            return []

        scored: list[tuple[int, sqlite3.Row]] = []
        for row in rows:
            score = self._score_row(spec, row)
            if score >= min_score:
                scored.append((score, row))

        scored.sort(key=lambda x: x[0], reverse=True)
        out: list[dict[str, Any]] = []
        for score, row in scored[:limit]:
            out.append(
                {
                    "asset_path": row["asset_path"],
                    "asset_rel_path": self._relative_asset_path(row["asset_path"]),
                    "filename": row["filename"],
                    "product_type": row["product_type"],
                    "material": row["material"],
                    "closure_type": row["closure_type"],
                    "design_style": row["design_style"],
                    "size_or_volume": row["size_or_volume"],
                    "summary": row["summary"],
                    "tags": row["tags"],
                    "score": score,
                }
            )
        return out

    def find_best_match(self, spec: DesignSpec) -> dict[str, Any] | None:
        matches = self.find_matches(spec=spec, min_score=2, limit=1)
        return matches[0] if matches else None

    def _relative_asset_path(self, raw_path: str) -> str:
        p = Path(raw_path).resolve()
        try:
            return str(p.relative_to(self.assets_dir.resolve()))
        except Exception:
            return p.name

    @staticmethod
    def _score_row(spec: DesignSpec, row: sqlite3.Row) -> int:
        score = 0
        if spec.product_type and row["product_type"] and spec.product_type in row["product_type"]:
            score += 4
        if spec.intended_material and row["material"] and spec.intended_material in row["material"]:
            score += 3
        if spec.closure_type and row["closure_type"] and spec.closure_type in row["closure_type"]:
            score += 3
        if spec.design_style and row["design_style"] and spec.design_style in row["design_style"]:
            score += 2
        if spec.size_or_volume and row["size_or_volume"] and spec.size_or_volume in row["size_or_volume"]:
            score += 1
        return score
