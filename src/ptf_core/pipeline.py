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
    """中间过程目录：.papertranflow/<标题>/（与输入文件同目录）。"""
    from ptf_output.naming import extract_title, safe_folder_name

    return input_path.parent / WORK_ROOT / safe_folder_name(extract_title(input_path.stem))


def default_out_dir(
    input_path: Path,
    category: str = "",
    sub_category: str = "",
) -> Path:
    """结果目录。

    默认（未指定 category/sub_category）：
        outfile/                     <- 直接放 outfile 下，不建子文件夹
    指定了 category 或 sub_category：
        outfile/<一级>/[<二级>/]<标题>/
    """
    from ptf_output.naming import extract_title, guess_category, safe_folder_name

    base = input_path.parent / OUT_ROOT
    if not category and not sub_category:
        return base

    level1 = category or guess_category(input_path.stem, str(input_path))
    out = base / safe_folder_name(level1, max_len=32)
    if sub_category:
        out = out / safe_folder_name(sub_category, max_len=32)
    return out / safe_folder_name(extract_title(input_path.stem))


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
        out_dir = out_dir or default_out_dir(
            pdf_path,
            category=self.config.image_host.category,
            sub_category=self.config.image_host.sub_category,
        )
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

        # 图片资产：只提取 markdown 实际引用的图片
        #   - 落盘到 out_dir/images（结果交付）
        #   - 同时缓存到 work_dir/mineru/images（复用，避免重跑 MinerU）
        self._write_assets(result, out_dir, mineru_dir / "images")

        # 最终输入 Markdown 放 out_dir，文件名用「去作者的标题」
        from ptf_output.naming import extract_title, safe_file_name

        doc_name = safe_file_name(extract_title(pdf_path.stem))
        result_md = out_dir / f"{doc_name}.md"
        result_md.write_text(result.markdown, encoding="utf-8")

        # 同时保留一份 mineru 原始 markdown 到 work_dir 便于复用
        (mineru_dir / "result.md").write_text(result.markdown, encoding="utf-8")

        self._fire(EventType.MINERU_COMPLETED, path=str(result_md))
        return result_md, result.content_list_json

    @staticmethod
    def _write_assets(result, out_dir: Path, cache_dir: Path | None = None) -> None:
        """把 markdown 实际引用的图片落盘（未引用的不落盘）。

        迁移自 ref/markdownchange/script/clean_images.py 的「清理无用图片」思路：
        只保留被 markdown 引用的图片，避免输出目录出现无用图片。

        同时可缓存一份到 cache_dir（work_dir），便于后续复用。
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
            for base in (out_dir, cache_dir):
                if base is None:
                    continue
                target = base / Path(name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)

    def _restore_images_from_cache(self, out_dir: Path, work_dir: Path) -> int:
        """out_dir 缺图时，从 work_dir/mineru/images 恢复（重跑不用重新调 MinerU）。"""
        cache = work_dir / "mineru" / "images"
        if not cache.is_dir():
            return 0
        count = 0
        for src in cache.glob("*"):
            if not src.is_file():
                continue
            dst = out_dir / "images" / src.name
            if dst.is_file():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
            count += 1
        return count

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
        # 未指定 out_dir 时，就地输出到 md 所在目录（md 已在正确位置）
        out_dir = out_dir or md_path.parent
        work_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)

        # 若 out_dir 缺图，从 work_dir 缓存恢复（重跑无需重新调 MinerU）
        self._restore_images_from_cache(out_dir, work_dir)

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

        retry_policy = RetryPolicy(
            max_retries=self.config.translation.max_retries,
            backoff_base=self.config.translation.backoff_base,
            request_interval=self.config.translation.request_interval,
        )
        backend = GLMBackend(self.config.glm, retry_policy)

        done_map: dict[str, str] = {}
        for cid in state.done_chunk_ids:
            saved = checkpoint.load_chunk(cid)
            if saved and saved.status == "done":
                done_map[cid] = saved.translated_text

        self._fire(EventType.TRANSLATION_STARTED, chunks=len(chunks))

        translations: dict[str, str] = dict(done_map)
        first_request = True
        for chunk in chunks:
            if chunk.chunk_id in done_map:
                self._fire(EventType.CHUNK_COMPLETED, chunk_id=chunk.chunk_id, resumed=True)
                continue
            # 主动避让：两次实际请求之间保持最小间隔（严格串行，无并发）
            if not first_request:
                retry_policy.sleep_interval()
            first_request = False

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

        # 批次文件夹名：三级路径 category/[sub_category/]标题
        folder_name = self._batch_folder_name(md_path)
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

    def _batch_folder_name(self, md_path: Path) -> str:
        """图床批次文件夹名：三级路径「一级/二级?/标题」。

        一级（category）：paper / Manual 等，默认自动判断，可 CLI 覆盖
        二级（sub_category）：类别，为空则省略这一级
        三级：去作者/年份的英文文件名

        图床侧 batchFolder.js 约束：每段上限 64 字符、层级上限 6 层、
        非法字符 : * ? " < > | 会被清洗。
        """
        from ptf_output.naming import extract_title, guess_category, safe_folder_name

        # 三级：去作者/年份的文件名（英文，与本地文件名一致）
        title = extract_title(md_path.stem)

        # 一级类别
        category = self.config.image_host.category or guess_category(
            md_path.stem, str(md_path)
        )

        # 拼三级路径（每段单独安全化）
        segs = [safe_folder_name(category, max_len=32)]
        if self.config.image_host.sub_category:
            segs.append(safe_folder_name(self.config.image_host.sub_category, max_len=32))
        segs.append(safe_folder_name(title))
        return "/".join(segs)

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
        out_dir = out_dir or default_out_dir(
            pdf_path,
            category=self.config.image_host.category,
            sub_category=self.config.image_host.sub_category,
        )
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

        防御：GLM 有时对短文本（如单行标题）返回空译文；此时**保留原文**，
        避免出现空的 `##` 这类残缺标题污染输出。
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

            # 译文为空（或只剩 # 前缀）时保留原文，避免残缺标题/丢内容
            if not _has_translatable_content(text):
                continue

            if block.type == "heading":
                text = _reassert_heading_level(text, block.metadata.get("level", 1))
            elif block.type == "paragraph":
                # 保持块形态：段落译文内部的空行折叠为单个换行。
                # 否则 LLM 偶尔插入的空行会让该 block 在重新解析时裂成多块，
                # 破坏「源与译 block 一一对应」。
                text = _collapse_blank_lines(text)
            block.normalized_text = text


def _collapse_blank_lines(text: str) -> str:
    """把译文内部的连续空行折叠为单个换行（保持单块形态）。

    仅处理普通文本 block；math/code 等不可翻译 block 不走这里。
    """
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    # 多个空白行 -> 单个换行；行尾空白去除
    t = re.sub(r"\n[ \t]*\n+", "\n", t)
    return t.strip("\n")


def _has_translatable_content(text: str) -> bool:
    """判断译文是否包含实际内容（排除空串、纯空白、只有 # 前缀的情况）。"""
    body = re.sub(r"^[\s#>*\-`]*", "", text or "").strip()
    return bool(body)


def _reassert_heading_level(text: str, level: int) -> str:
    """剥掉标题文本里已有的 # 前缀，按 level 重新加前缀。"""
    level = max(1, min(int(level or 1), 6))
    body = re.sub(r"^\s*#{1,6}\s*", "", text).strip()
    if not body:
        return "#" * level
    return f"{'#' * level} {body}"
