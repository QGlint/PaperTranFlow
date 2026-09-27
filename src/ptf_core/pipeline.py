"""完整 Pipeline 编排。

目录约定：
    中间过程（checkpoint/chunks/normalized/mineru 原始结果）→  .papertranflow/<名称>/
    最终结果（input.md + input.zh.md + 图片）               →  outfile/<名称>/

    parse:   PDF -> MinerU -> result.md + content_list.json (+ images)
    translate: input.md -> normalize -> chunk -> GLM -> checkpoint -> input.zh.md
    run:     parse + translate
    resume:  从 checkpoint 续跑

通过事件把进度传给 CLI。
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Callable

from ptf_config.loader import ConfigLoader
from ptf_config.models import PaperTranFlowConfig
from ptf_core.events import EventType
from ptf_core.models import Chunk
from ptf_markdown.cleanup import MarkdownCleaner
from ptf_markdown.models import MarkdownBlock, MarkdownDocument
from ptf_markdown.normalize import MarkdownNormalizer
from ptf_markdown.parser import parse_markdown
from ptf_markdown.structure import StructureRestorer
from ptf_mineru.client import MinerUClient
from ptf_output.writer import OutputWriter
from ptf_translation.checkpoint import CheckpointManager
from ptf_translation.chunker import SmartChunker
from ptf_translation.glm import GLMBackend
from ptf_translation.retry import RetryPolicy

EventHandler = Callable[[EventType, dict], None]

WORK_ROOT = ".papertranflow"
OUT_ROOT = "outfile"


def default_work_dir(input_path: Path) -> Path:
    """中间过程目录：.papertranflow/<名称>/（与输入文件同目录）。"""
    return input_path.parent / WORK_ROOT / input_path.stem


def default_out_dir(input_path: Path) -> Path:
    """结果目录：outfile/<名称>/（与输入文件同目录）。"""
    return input_path.parent / OUT_ROOT / input_path.stem


class Pipeline:
    def __init__(self, config: PaperTranFlowConfig, emit: EventHandler | None = None):
        self.config = config
        self.emit = emit or (lambda event, data: None)
        self.normalizer = MarkdownNormalizer()
        self.cleaner = MarkdownCleaner()
        self.chunker = SmartChunker(config.chunking)
        self.writer = OutputWriter(config.output.zh_suffix)

    def _fire(self, event: EventType, **data) -> None:
        self.emit(event, data)

    # ---- 解析 ----

    def parse(self, pdf_path: Path, work_dir: Path | None = None, out_dir: Path | None = None) -> tuple[Path, str]:
        """PDF -> MinerU -> 保存 result.md + content_list.json + 图片。

        中间结果放 work_dir，最终 Markdown 放 out_dir。
        返回 (输出 md 路径, content_list_json 文本)。
        """
        work_dir = work_dir or default_work_dir(pdf_path)
        out_dir = out_dir or default_out_dir(pdf_path)
        work_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)

        client = MinerUClient(self.config.mineru)
        self._fire(EventType.JOB_STARTED, path=str(pdf_path))
        self._fire(EventType.MINERU_SUBMITTED, path=str(pdf_path))

        result = client.parse(pdf_path)

        # 中间结果：mineru 原始产物
        mineru_dir = work_dir / "mineru"
        mineru_dir.mkdir(parents=True, exist_ok=True)
        (mineru_dir / "content_list.json").write_text(
            result.content_list_json or "", encoding="utf-8"
        )

        # 图片资产：只提取 markdown 实际引用的图片，落盘到 out_dir/images
        self._write_assets(result, out_dir)

        # 最终输入 Markdown 放 out_dir
        result_md = out_dir / f"{pdf_path.stem}.md"
        result_md.write_text(result.markdown, encoding="utf-8")

        # 同时保留一份 mineru 原始 markdown 到 work_dir 便于复用
        (mineru_dir / "result.md").write_text(result.markdown, encoding="utf-8")

        self._fire(EventType.MINERU_COMPLETED, path=str(result_md))
        return result_md, result.content_list_json

    @staticmethod
    def _write_assets(result, out_dir: Path) -> None:
        """把 markdown 实际引用的图片落盘到 out_dir/images（未引用的不落盘）。

        迁移自 ref/markdownchange/script/clean_images.py 的「清理无用图片」思路：
        只保留被 markdown 引用的图片，避免 out_dir 里出现无用图片。
        """
        if not result.assets:
            return
        from ptf_markdown.images import filter_assets_by_reference

        referenced = filter_assets_by_reference(result.assets, result.markdown)
        for name, data in referenced.items():
            # 防止路径穿越，只落盘 images/ 前缀的资产
            norm = name.replace("\\", "/")
            if not norm.startswith("images/"):
                continue
            target = out_dir / Path(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

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
        from ptf_markdown.serializer import serialize_markdown

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialize_markdown(document), encoding="utf-8")

    # ---- 翻译 ----

    def translate(self, md_path: Path, work_dir: Path | None = None, out_dir: Path | None = None) -> Path:
        """input.md -> input.zh.md（含 checkpoint）。

        checkpoint/chunks 放 work_dir，最终 .zh.md 放 out_dir。
        """
        text = md_path.read_text(encoding="utf-8")
        work_dir = work_dir or default_work_dir(md_path)
        out_dir = out_dir or (md_path.parent if md_path.parent.name == md_path.stem else default_out_dir(md_path))
        work_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)

        # 尝试读取 content_list.json（work_dir/mineru 或 md 同目录）
        cl_json = ""
        cl_candidates = [
            work_dir / "mineru" / "content_list.json",
            md_path.parent / "content_list.json",
        ]
        for c in cl_candidates:
            if c.is_file():
                cl_json = c.read_text(encoding="utf-8")
                break

        document = self.normalize(text, cl_json)

        checkpoint = CheckpointManager(work_dir, md_path, self.config.glm.model)

        # chunking
        result = self.chunker.chunk(document)
        chunks = result.chunks
        self._fire(EventType.CHUNKING_COMPLETED, chunks=len(chunks))

        # 保存 normalized + chunks（中间产物，放 work_dir）
        self.write_normalized(document, work_dir / "normalized.md")
        (work_dir / "chunks.json").write_text(
            json.dumps([c.to_dict() for c in chunks], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # checkpoint：优先复用已有 state（resume 场景），否则初始化
        existing_state = checkpoint.load_state()
        if existing_state is not None and checkpoint.verify_source_hash(existing_state):
            state = existing_state
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
            self._fire(EventType.CHUNK_COMPLETED, chunk_id=chunk.chunk_id, started=True)
            translated = backend.translate(
                chunk.source_text, target_lang=self.config.translation.target_lang
            )
            chunk.translated_text = translated
            chunk.status = "done"
            chunk.model = self.config.glm.model
            chunk.source_hash = chunk.compute_source_hash()
            translations[chunk.chunk_id] = translated

            checkpoint.save_chunk(chunk)
            checkpoint.mark_done(chunk.chunk_id)
            self._fire(EventType.CHUNK_COMPLETED, chunk_id=chunk.chunk_id)

        # 重组并写出最终结果到 out_dir
        self._apply_translations(document, chunks, translations)
        out_path = self.writer.write(document, md_path, out_dir=out_dir)

        # 图床上传（默认关闭）：一次批量上传 + 指定批次文件夹
        if self.config.image_host.enabled and self.config.image_host.configured:
            self._upload_images_to_host(out_path, out_dir, md_path)

        self._fire(EventType.JOB_COMPLETED, path=str(out_path))
        return out_path

    def _upload_images_to_host(self, out_path: Path, out_dir: Path, md_path: Path) -> None:
        """把 out_dir/images 下的图片批量上传到图床，并重写 out_path 的引用。

        使用 batchCommit：一次请求上传多张图并指定 folderName（图床据此建文件夹）。
        """
        from ptf_output.image_host import ImageHostUploader, rewrite_markdown_images

        images_dir = out_dir / "images"
        if not images_dir.is_dir():
            return

        images = sorted(p for p in images_dir.glob("*") if p.is_file())
        if not images:
            return

        uploader = ImageHostUploader(
            self.config.image_host.base_url, self.config.image_host.token
        )

        # 批次文件夹名：优先用论文标题（人类可读），回退到 md 文件名
        folder_name = self._batch_folder_name(out_path, md_path)
        request_id = self._batch_request_id(folder_name)

        self._fire(
            EventType.IMAGE_UPLOAD_STARTED, count=len(images), folder=folder_name
        )
        file_map = uploader.upload_batch(
            files=images,
            folder_name=folder_name,
            commit_message=f"PaperTranFlow 上传 {out_path.stem} 的 {len(images)} 张配图",
            request_id=request_id,
        )

        # 本地引用 images/xxx.jpg -> 远程 URL
        image_map = {f"images/{name}": url for name, url in file_map.items()}
        if image_map:
            text = out_path.read_text(encoding="utf-8")
            rewritten = rewrite_markdown_images(text, image_map)
            out_path.write_text(rewritten, encoding="utf-8")

        self._fire(EventType.IMAGE_UPLOAD_COMPLETED, count=len(image_map))

    @staticmethod
    def _batch_folder_name(out_path: Path, md_path: Path) -> str:
        """批次文件夹名：用 markdown 一级标题（论文标题），回退到文件名 stem。

        图床对文件夹名有约束（见图床侧 batchFolder.js）：
            每段上限 64 字符、层级上限 6 层、`: * ? " < > |` 会被清洗。
        因此过长的标题需要截断，并追加短哈希保证唯一性（避免不同论文
        因前 64 字符相同而落到同一文件夹）。
        """
        title = ""
        try:
            text = out_path.read_text(encoding="utf-8")
            doc = parse_markdown(text)
            for block in doc.blocks:
                if block.type == "heading" and block.metadata.get("level") == 1:
                    title = str(block.metadata.get("title", "")).strip()
                    if title:
                        break
        except (OSError, UnicodeDecodeError):
            pass

        if not title:
            title = md_path.stem
        return _safe_folder_name(title)

    @staticmethod
    def _batch_request_id(folder_name: str) -> str:
        """稳定 requestId（幂等键）：同一篇论文重试不会重复上传。"""
        digest = hashlib.sha1(folder_name.encode("utf-8")).hexdigest()[:12]
        return f"papertranflow-{digest}"

    def resume(self, md_path: Path, work_dir: Path | None = None) -> Path:
        """从 checkpoint 续跑。source hash 变化则拒绝。"""
        work_dir = work_dir or self._locate_work_dir(md_path)
        if work_dir is None:
            raise RuntimeError("未找到 checkpoint，无法 resume（请先运行 translate）")
        checkpoint = CheckpointManager(work_dir, md_path, self.config.glm.model)

        state = checkpoint.load_state()
        if state is None:
            raise RuntimeError("未找到 checkpoint，无法 resume（请先运行 translate）")
        if not checkpoint.verify_source_hash(state):
            raise RuntimeError("source hash 不匹配，拒绝 resume（源文件已变化）")

        return self.translate(md_path, work_dir)

    @staticmethod
    def _locate_work_dir(md_path: Path) -> Path | None:
        """根据 md 路径定位 work_dir（.papertranflow/<名称>/）。

        向上查找 .papertranflow 根，再在其中找 source_path 匹配的目录。
        """
        md_path = md_path.resolve()
        roots: list[Path] = []
        cur = md_path.parent
        while True:
            candidate = cur / WORK_ROOT
            if candidate.is_dir():
                roots.append(candidate)
            if cur.parent == cur:
                break
            cur = cur.parent

        for root in roots:
            # 扫描 state.json 匹配 source_path
            for state_path in root.glob("*/state.json"):
                try:
                    data = json.loads(state_path.read_text(encoding="utf-8"))
                    sp = data.get("source_path")
                    if sp and Path(sp).resolve() == md_path:
                        return state_path.parent
                except (json.JSONDecodeError, OSError):
                    continue
        return None

    # ---- run ----

    def run(self, pdf_path: Path, work_dir: Path | None = None, out_dir: Path | None = None) -> Path:
        work_dir = work_dir or default_work_dir(pdf_path)
        out_dir = out_dir or default_out_dir(pdf_path)
        result_md, cl_json = self.parse(pdf_path, work_dir, out_dir)
        return self.translate(result_md, work_dir, out_dir)

    # ---- 内部 ----

    @staticmethod
    def _apply_translations(
        document: MarkdownDocument,
        chunks: list[Chunk],
        translations: dict[str, str],
    ) -> None:
        """把每个 chunk 的译文放回对应 block（1:1 block 对应）。

        对 heading block：译文可能带着 LLM 自己写的 `#` 前缀（数量未必正确），
        因此这里**剥掉译文的 # 前缀，再用 structure 恢复得到的层级重新加前缀**，
        保证标题层级由 PaperTranFlow 决定（spec §13：不让 LLM 决定层级）。
        """
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
            text = " ".join(p.rstrip("\n") for p in parts if p.strip())

            if block.type == "heading":
                text = _reassert_heading_level(text, block.metadata.get("level", 1))
            block.normalized_text = text


def _reassert_heading_level(text: str, level: int) -> str:
    """剥掉标题文本里已有的 # 前缀，按 level 重新加前缀。"""
    level = max(1, min(int(level or 1), 6))
    body = re.sub(r"^\s*#{1,6}\s*", "", text).strip()
    if not body:
        return "#" * level
    return f"{'#' * level} {body}"


# 图床文件夹名约束（与图床侧 batchFolder.js 对齐）
FOLDER_SEGMENT_MAX = 64
_FOLDER_ILLEGAL = re.compile(r'[:*?"<>|\\/]+')


def _safe_folder_name(title: str) -> str:
    """把论文标题转成图床可接受的批次文件夹名。

    规则（与图床侧 batchFolder.js 对齐）：
        - 非法字符 : * ? " < > | \\ / 替换为 _
        - 折叠连续空白为单个下划线
        - 单段超过 64 字符时截断并追加短哈希（保证唯一且可读）
    """
    name = _FOLDER_ILLEGAL.sub("_", title).strip()
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"_{2,}", "_", name).strip("_.")

    if not name:
        name = "paper"

    if len(name) > FOLDER_SEGMENT_MAX:
        digest = hashlib.sha1(title.encode("utf-8")).hexdigest()[:8]
        # 预留 "_" + 8 位哈希
        keep = FOLDER_SEGMENT_MAX - len(digest) - 1
        name = f"{name[:keep].rstrip('_.')}_{digest}"

    return name
