"""Checkpoint 管理。

每个 chunk 成功后立即落盘 state.json + chunks/<chunk_id>.json。
resume 时校验 source hash，跳过已完成 chunk，已成功 chunk 绝不重调 GLM。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ptf_core.models import Chunk, JobState


def compute_source_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class CheckpointManager:
    def __init__(self, job_dir: Path, source_path: Path, model: str):
        self.job_dir = job_dir
        self.chunks_dir = job_dir / "chunks"
        self.chunks_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = job_dir / "state.json"
        self.source_path = source_path
        self.source_hash = compute_source_hash(source_path)
        self.model = model
        self._state: JobState | None = None

    # ---- state ----

    def load_state(self) -> JobState | None:
        if not self.state_path.is_file():
            return None
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return JobState.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            return None

    def init_state(self, chunk_ids: list[str]) -> JobState:
        state = JobState(
            source_path=str(self.source_path),
            source_hash=self.source_hash,
            model=self.model,
            status="running",
            chunk_ids=chunk_ids,
            done_chunk_ids=[],
        )
        self._state = state
        self._write_state()
        return state

    def adopt_state(self, state: JobState) -> None:
        """复用已加载的 state（resume 场景），使后续 mark_done 生效。"""
        self._state = state
        self._write_state()

    def _write_state(self) -> None:
        if self._state is None:
            return
        self.state_path.write_text(
            json.dumps(self._state.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def mark_done(self, chunk_id: str) -> None:
        if self._state is None:
            return
        if chunk_id not in self._state.done_chunk_ids:
            self._state.done_chunk_ids.append(chunk_id)
        if len(self._state.done_chunk_ids) == len(self._state.chunk_ids):
            self._state.status = "completed"
        self._write_state()

    # ---- chunk ----

    def save_chunk(self, chunk: Chunk) -> None:
        path = self.chunks_dir / f"{chunk.chunk_id}.json"
        path.write_text(
            json.dumps(chunk.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_chunk(self, chunk_id: str) -> Chunk | None:
        path = self.chunks_dir / f"{chunk_id}.json"
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Chunk.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            return None

    def verify_source_hash(self, state: JobState) -> bool:
        return state.source_hash == self.source_hash
