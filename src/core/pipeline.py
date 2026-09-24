"""完整 Pipeline 编排。

    parse:   PDF -> MinerU -> result.md + content_list.json (+ normalized.md)
    translate: input.md -> normalize -> chunk -> GLM -> checkpoint -> input.zh.md
    run:     parse + translate
    resume:  从 checkpoint 续跑

通过事件把进度传给 CLI。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Callable

from config.loader import ConfigLoader
from config.models import PaperFlowConfig
from core.events import EventType
from core.models import Chunk
from markdown.cleanup import MarkdownCleaner
from markdown.models import MarkdownBlock, MarkdownDocument
from markdown.normalize import MarkdownNormalizer
from markdown.parser import parse_markdown
from markdown.structure import StructureRestorer
from mineru.client import MinerUClient
from output.writer import OutputWriter
from translation.checkpoint import CheckpointManager
from translation.chunker import SmartChunker
from translation.glm import GLMBackend
from translation.retry import RetryPolicy

EventHandler = Callable[[EventType, dict], None]


class Pipeline:
    def __init__(self, config: PaperFlowConfig, emit: EventHandler | None = None):
        self.config = config
        self.emit = emit or (lambda event, data: None)
        self.normalizer = MarkdownNormalizer()
        self.cleaner = MarkdownCleaner()
        self.chunker = SmartChunker(config.chunking)
        self.writer = OutputWriter(config.output.zh_suffix)

    def _fire(self, event: EventType, **data) -> None:
        self.emit(event, data)

    # ---- 解析 ----

    def parse(self, pdf_path: Path, job_dir: Path | None = None) -> tuple[Path, str]:
        """PDF -> MinerU -> 保存 result.md + content_list.json。返回 (result_md, content_list_json)。"""
        client = MinerUClient(self.config.mineru)
        self._fire(EventType.JOB_STARTED, path=str(pdf_path))
        self._fire(EventType.MINERU_SUBMITTED, path=str(pdf_path))

        result = client.parse(pdf_path)

        mineru_dir = (job_dir / "mineru") if job_dir else pdf_path.parent
        mineru_dir.mkdir(parents=True, exist_ok=True)
        result_md = mineru_dir / "result.md"
        result_md.write_text(result.markdown, encoding="utf-8")
        if result.content_list_json:
            (mineru_dir / "content_list.json").write_text(
                result.content_list_json, encoding="utf-8"
            )

        self._fire(EventType.MINERU_COMPLETED, path=str(result_md))
        return result_md, result.content_list_json

    # ---- 标准化 ----

    def normalize(self, markdown_text: str, content_list_json: str = "") -> MarkdownDocument:
        self._fire(EventType.NORMALIZATION_STARTED)
        document = parse_markdown(markdown_text)

        restorer = StructureRestorer(content_list_json)
        restorer.restore(document)

        self.normalizer.normalize(document)
        self.cleaner.clean(document)

        self._fire(EventType.NORMALIZATION_COMPLETED, blocks=len(document.blocks))
        return document

    def write_normalized(self, document: MarkdownDocument, path: Path) -> None:
        from markdown.serializer import serialize_markdown

        path.write_text(serialize_markdown(document), encoding="utf-8")

    # ---- 翻译 ----

    def translate(self, md_path: Path, job_dir: Path | None = None) -> Path:
        """input.md -> input.zh.md（含 checkpoint）。"""
        text = md_path.read_text(encoding="utf-8")
        # 尝试读取同目录 mineru/content_list.json（若存在）
        cl_json = ""
        cl_candidates = [
            md_path.parent / "mineru" / "content_list.json",
            md_path.parent / "content_list.json",
        ]
        for c in cl_candidates:
            if c.is_file():
                cl_json = c.read_text(encoding="utf-8")
                break

        document = self.normalize(text, cl_json)

        job_dir = job_dir or (md_path.parent / ".paperflow" / "jobs" / md_path.stem)
        checkpoint = CheckpointManager(job_dir, md_path, self.config.glm.model)

        # chunking
        result = self.chunker.chunk(document)
        chunks = result.chunks
        self._fire(EventType.CHUNKING_COMPLETED, chunks=len(chunks))

        # 保存 normalized + chunks
        self.write_normalized(document, job_dir / "normalized.md")
        (job_dir / "chunks.json").write_text(
            json.dumps([c.to_dict() for c in chunks], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # checkpoint：优先复用已有 state（resume 场景），否则初始化
        existing_state = checkpoint.load_state()
        if existing_state is not None and checkpoint.verify_source_hash(existing_state):
            state = existing_state
            # 确保 chunk_ids 与本次 chunking 结果一致
            if state.chunk_ids != [c.chunk_id for c in chunks]:
                state.chunk_ids = [c.chunk_id for c in chunks]
            checkpoint.adopt_state(state)
        else:
            state = checkpoint.init_state([c.chunk_id for c in chunks])

        backend = GLMBackend(self.config.glm, RetryPolicy(
            max_retries=self.config.translation.max_retries,
            backoff_base=self.config.translation.backoff_base,
        ))

        done_map: dict[str, str] = {}
        for cid in state.done_chunk_ids:
            saved = checkpoint.load_chunk(cid)
            if saved and saved.status == "done":
                done_map[cid] = saved.translated_text

        self._fire(EventType.TRANSLATION_STARTED, chunks=len(chunks))

        translations: dict[str, str] = dict(done_map)
        for chunk in chunks:
            if chunk.chunk_id in done_map:
                self._fire(EventType.CHUNK_COMPLETED, chunk_id=chunk.chunk_id, resumed=True)
                continue
            # 串行翻译
            self._fire(EventType.CHUNK_COMPLETED, chunk_id=chunk.chunk_id, started=True)
            translated = backend.translate(
                chunk.source_text, target_lang=self.config.translation.target_lang
            )
            chunk.translated_text = translated
            chunk.status = "done"
            chunk.model = self.config.glm.model
            chunk.source_hash = chunk.compute_source_hash()
            translations[chunk.chunk_id] = translated

            # 立即 checkpoint
            checkpoint.save_chunk(chunk)
            checkpoint.mark_done(chunk.chunk_id)
            self._fire(EventType.CHUNK_COMPLETED, chunk_id=chunk.chunk_id)

        # 重组
        self._apply_translations(document, chunks, translations)
        out_path = self.writer.write(document, md_path)

        self._fire(EventType.JOB_COMPLETED, path=str(out_path))
        return out_path

    def resume(self, md_path: Path, job_dir: Path | None = None) -> Path:
        """从 checkpoint 续跑。source hash 变化则拒绝。"""
        job_dir = job_dir or self._locate_job_dir(md_path)
        if job_dir is None:
            raise RuntimeError("未找到 checkpoint，无法 resume（请先运行 translate）")
        checkpoint = CheckpointManager(job_dir, md_path, self.config.glm.model)

        state = checkpoint.load_state()
        if state is None:
            raise RuntimeError("未找到 checkpoint，无法 resume（请先运行 translate）")
        if not checkpoint.verify_source_hash(state):
            raise RuntimeError("source hash 不匹配，拒绝 resume（源文件已变化）")

        return self.translate(md_path, job_dir)

    @staticmethod
    def _locate_job_dir(md_path: Path) -> Path | None:
        """根据 md 路径定位 job 目录。

        向上查找 .paperflow/jobs 根，再在其中找 source_path 匹配的 job。
        也兼容直接以 md 名命名的默认 job 目录。
        """
        md_path = md_path.resolve()
        # 向上收集所有 .paperflow/jobs 根（最近的优先）
        roots: list[Path] = []
        cur = md_path.parent
        while True:
            candidate = cur / ".paperflow" / "jobs"
            if candidate.is_dir():
                roots.append(candidate)
            if cur.parent == cur:
                break
            cur = cur.parent

        for jobs_root in roots:
            # 默认命名目录
            default = jobs_root / md_path.stem
            if (default / "state.json").is_file():
                return default
            # 扫描 state.json 匹配 source_path
            for state_path in jobs_root.glob("*/state.json"):
                try:
                    data = json.loads(state_path.read_text(encoding="utf-8"))
                    sp = data.get("source_path")
                    if sp and Path(sp).resolve() == md_path:
                        return state_path.parent
                except (json.JSONDecodeError, OSError):
                    continue
        return None

    # ---- run ----

    def run(self, pdf_path: Path, job_dir: Path | None = None) -> Path:
        job_dir = job_dir or (pdf_path.parent / ".paperflow" / "jobs" / pdf_path.stem)
        result_md, cl_json = self.parse(pdf_path, job_dir)
        return self.translate(result_md, job_dir)

    # ---- 内部 ----

    @staticmethod
    def _apply_translations(
        document: MarkdownDocument,
        chunks: list[Chunk],
        translations: dict[str, str],
    ) -> None:
        """把每个 chunk 的译文放回对应 block（1:1 block 对应）。

        chunk 与 block 对齐：每个 chunk 对应一个可翻译 block。
        若某 block 因超长被拆成多个 chunk（共享 block_id），则按顺序拼接译文。
        """
        # 收集每个 block_id 的译文片段（保持 chunk 顺序）
        block_translations: dict[str, list[str]] = {}
        for chunk in chunks:
            translated = translations.get(chunk.chunk_id)
            if translated is None:
                continue
            for bid in chunk.block_ids:
                block_translations.setdefault(bid, []).append(translated)

        for block in document.blocks:
            parts = block_translations.get(block.block_id)
            if not parts:
                continue
            # 拼接（超长段落拆分的多个子块译文）
            block.normalized_text = " ".join(p.rstrip("\n") for p in parts if p.strip())
