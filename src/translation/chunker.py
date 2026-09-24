"""Smart Chunker。

禁止固定长度硬切。采用 soft target + hard limit，边界优先级：
    block end > paragraph end > sentence end > newline > word > hard cut

基于 MarkdownBlock 列表分组，绝不切割 code fence / LaTeX block / table /
list block / blockquote（这些作为原子 block，要么整体进某个 chunk，要么保持完整）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from config.models import ChunkingConfig
from core.models import Chunk
from markdown.models import MarkdownBlock, MarkdownDocument

_SENTENCE_END = re.compile(r"[.!?。！？]\s*$")


@dataclass
class ChunkResult:
    chunks: list[Chunk] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class SmartChunker:
    def __init__(self, config: ChunkingConfig):
        self.target = config.target
        self.hard_limit = config.hard_limit

    def chunk(self, document: MarkdownDocument) -> ChunkResult:
        blocks = document.blocks
        chunks: list[Chunk] = []
        warnings: list[str] = []
        counter = 0

        current: list[MarkdownBlock] = []
        current_size = 0

        def flush() -> None:
            nonlocal current, current_size, counter
            if not current:
                return
            counter += 1
            text = self._join_blocks(current)
            chunk = Chunk(
                chunk_id=f"chunk-{counter:06d}",
                block_ids=[b.block_id for b in current],
                source_text=text,
            )
            chunk.source_hash = chunk.compute_source_hash()
            chunks.append(chunk)
            current = []
            current_size = 0

        for block in blocks:
            text = block.normalized_text or block.source_text
            size = len(text.encode("utf-8"))

            # 原子不可切 block（代码/公式/表格/图片/分割线）——若单块超 hard limit，
            # 允许超限并告警（保持完整，spec §22）。
            if block.type in ("code", "math", "image", "thematic_break", "table"):
                if current:
                    # 若放不下，先结算当前 chunk
                    if current_size + size > self.hard_limit:
                        flush()
                current.append(block)
                current_size += size
                if size > self.hard_limit:
                    warnings.append(
                        f"{block.block_id} ({block.type}) 超过 hard limit，保持完整"
                    )
                continue

            # 可切 block（heading/paragraph/list/blockquote/raw）
            if current_size + size > self.hard_limit:
                # 尝试把当前 block 拆到接近 target（仅对 paragraph/raw 做句/行切分）
                if block.type in ("paragraph", "raw") and size > self.hard_limit:
                    flush()  # 先结算已有
                    for sub in self._split_oversized(block):
                        current.append(sub)
                        current_size += len((sub.normalized_text or sub.source_text).encode("utf-8"))
                        if current_size > self.hard_limit:
                            flush()
                    continue
                flush()
            current.append(block)
            current_size += size

            # soft target：接近 target 时，若下一个边界更优则结算
            if current_size >= self.target:
                flush()

        flush()
        return ChunkResult(chunks=chunks, warnings=warnings)

    def _split_oversized(self, block: MarkdownBlock) -> list[MarkdownBlock]:
        """对超过 hard limit 的段落按句子/换行拆分（保持 Markdown 不损坏）。"""
        text = block.normalized_text or block.source_text
        sentences = self._split_sentences(text)
        subs: list[MarkdownBlock] = []
        # 复用同一 block_id 附加序号，避免与 checkpoint 冲突
        for i, s in enumerate(sentences):
            b = MarkdownBlock(
                block_id=f"{block.block_id}#{i}",
                type=block.type,
                source_text=s,
                normalized_text=s,
                metadata=dict(block.metadata),
            )
            subs.append(b)
        return subs if subs else [block]

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        parts = re.split(r"(?<=[.!?。！？])\s+", text)
        parts = [p for p in parts if p.strip()]
        return parts if parts else [text]

    @staticmethod
    def _join_blocks(blocks: list[MarkdownBlock]) -> str:
        texts = []
        for b in blocks:
            t = (b.normalized_text or b.source_text).rstrip("\n")
            if t:
                texts.append(t)
        return "\n\n".join(texts)
