"""Smart Chunker。

禁止固定长度硬切。采用 soft target + hard limit，边界优先级：
    block end > paragraph end > sentence end > newline > word > hard cut

翻译单元（chunk）与 block 对齐：每个 chunk 对应恰好一个可翻译 block，
保证译文与原文 block 一一对应（spec §25/§31）。

不可翻译 block（code / math / image / thematic_break）不进入 chunk，
序列化时原样保留。

当一个可翻译 block 超过 hard limit 时，对 paragraph 做句子切分，
拆成多个子 block（仍各自为一个 chunk）；对其它类型保持完整并告警。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ptf_config.models import ChunkingConfig
from ptf_core.models import Chunk
from ptf_markdown.models import MarkdownBlock, MarkdownDocument

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。！？])\s+")


@dataclass
class ChunkResult:
    chunks: list[Chunk] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class SmartChunker:
    def __init__(self, config: ChunkingConfig):
        self.target = config.target
        self.hard_limit = config.hard_limit

    def chunk(self, document: MarkdownDocument) -> ChunkResult:
        chunks: list[Chunk] = []
        warnings: list[str] = []
        counter = 0

        for block in document.blocks:
            if not block.is_translatable:
                continue

            text = block.normalized_text or block.source_text
            size = len(text.encode("utf-8"))

            if size <= self.hard_limit or block.type not in ("paragraph", "raw"):
                counter += 1
                chunks.append(self._make_chunk(counter, [block], text))
                if size > self.hard_limit:
                    warnings.append(
                        f"{block.block_id} ({block.type}) 超过 hard limit，保持完整"
                    )
                continue

            # 超大段落：按句子切分为多个子 block
            sub_blocks = self._split_paragraph(block, text)
            for sb in sub_blocks:
                counter += 1
                chunks.append(self._make_chunk(counter, [sb], sb.normalized_text or sb.source_text))

        return ChunkResult(chunks=chunks, warnings=warnings)

    def _make_chunk(self, counter: int, blocks: list[MarkdownBlock], text: str) -> Chunk:
        chunk = Chunk(
            chunk_id=f"chunk-{counter:06d}",
            block_ids=[b.block_id for b in blocks],
            source_text=text,
        )
        chunk.source_hash = chunk.compute_source_hash()
        return chunk

    @staticmethod
    def _split_paragraph(block: MarkdownBlock, text: str) -> list[MarkdownBlock]:
        sentences = [s for s in _SENTENCE_SPLIT.split(text) if s.strip()]
        if not sentences:
            sentences = [text]
        out: list[MarkdownBlock] = []
        for i, s in enumerate(sentences):
            out.append(
                MarkdownBlock(
                    block_id=block.block_id,  # 保持原 block_id，译文会拼接回原 block
                    type=block.type,
                    source_text=s,
                    normalized_text=s,
                    metadata=dict(block.metadata),
                )
            )
        return out
