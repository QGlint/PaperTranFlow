"""核心数据结构：Job / Chunk / State。"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Chunk:
    """一个待翻译/已翻译的 chunk。"""

    chunk_id: str
    block_ids: list[str]
    source_text: str
    translated_text: str = ""
    source_hash: str = ""
    status: str = "pending"  # pending | done | failed
    model: str = ""

    def compute_source_hash(self) -> str:
        return hashlib.sha256(self.source_text.encode("utf-8", errors="replace")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "block_ids": self.block_ids,
            "source_hash": self.source_hash or self.compute_source_hash(),
            "source_text": self.source_text,
            "translation": self.translated_text,
            "status": self.status,
            "model": self.model,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Chunk":
        c = cls(
            chunk_id=data["chunk_id"],
            block_ids=data.get("block_ids", []),
            source_text=data.get("source_text", ""),
            translated_text=data.get("translation", ""),
            source_hash=data.get("source_hash", ""),
            status=data.get("status", "pending"),
            model=data.get("model", ""),
        )
        return c


@dataclass
class JobState:
    """checkpoint 顶层状态。"""

    source_path: str = ""
    source_hash: str = ""
    model: str = ""
    status: str = "running"
    chunk_ids: list[str] = field(default_factory=list)
    done_chunk_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "source_hash": self.source_hash,
            "model": self.model,
            "status": self.status,
            "chunk_ids": self.chunk_ids,
            "done_chunk_ids": self.done_chunk_ids,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobState":
        return cls(
            source_path=data.get("source_path", ""),
            source_hash=data.get("source_hash", ""),
            model=data.get("model", ""),
            status=data.get("status", "running"),
            chunk_ids=data.get("chunk_ids", []),
            done_chunk_ids=data.get("done_chunk_ids", []),
        )
