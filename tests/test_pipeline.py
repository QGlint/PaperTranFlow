"""Pipeline 端到端测试（用 mock backend，不依赖真实 API）。"""
import os
import sys
from pathlib import Path

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, SRC)

from ptf_config.models import (
    ChunkingConfig,
    GLMConfig,
    MinerUConfig,
    OutputConfig,
    PaperTranFlowConfig,
    TranslationConfig,
)
from ptf_core.pipeline import Pipeline
from ptf_markdown.models import MarkdownBlock, MarkdownDocument


class _MockBackend:
    """把英文文本替换为固定中文标记，模拟翻译。"""

    def __init__(self):
        self.calls = 0

    def translate(self, text, target_lang="简体中文"):
        self.calls += 1
        return f"译[{text[:20]}]"


def _cfg():
    return PaperTranFlowConfig(
        mineru=MinerUConfig(token="x"),
        glm=GLMConfig(api_key="x", model="glm-4.7-flash"),
        translation=TranslationConfig(),
        chunking=ChunkingConfig(target=5000, hard_limit=6500),
        output=OutputConfig(zh_suffix=".zh.md"),
    )


def test_apply_translations_one_to_one():
    """译文与 block 一一对应：block 数量/顺序不变。"""
    doc = MarkdownDocument(blocks=[
        MarkdownBlock("b1", "heading", "# Intro"),
        MarkdownBlock("b2", "paragraph", "hello world"),
        MarkdownBlock("b3", "math", "$$\nx\n$$"),
        MarkdownBlock("b4", "paragraph", "second paragraph"),
    ])
    from ptf_core.models import Chunk

    chunks = [
        Chunk("c1", ["b1"], "# Intro"),
        Chunk("c2", ["b2"], "hello world"),
        Chunk("c3", ["b4"], "second paragraph"),
    ]
    translations = {"c1": "# 引言", "c2": "你好世界", "c3": "第二段"}
    Pipeline._apply_translations(doc, chunks, translations)

    assert doc.blocks[0].normalized_text == "# 引言"
    assert doc.blocks[1].normalized_text == "你好世界"
    # math block 原样保留（未翻译，normalized_text 保持空，序列化时回退 source_text）
    assert doc.blocks[2].source_text == "$$\nx\n$$"
    assert doc.blocks[2].normalized_text == ""
    assert doc.blocks[3].normalized_text == "第二段"
    assert len(doc.blocks) == 4


def test_translate_end_to_end(tmp_path, monkeypatch):
    """完整 translate 流程（mock backend）产生 .zh.md，结构对应。"""
    md = tmp_path / "input.md"
    md.write_text(
        "# Introduction\n\nThis is a paragraph.\n\n$$\nx^2\n$$\n\n## Background\n\nAnother paragraph.\n",
        encoding="utf-8",
    )
    cfg = _cfg()
    pipeline = Pipeline(cfg)

    # 注入 mock backend
    import ptf_core.pipeline as cp

    monkeypatch.setattr(cp, "GLMBackend", lambda *a, **k: _MockBackend())

    out = pipeline.translate(md, work_dir=tmp_path / "work", out_dir=tmp_path / "out")
    assert out.name == "input.zh.md"
    text = out.read_text(encoding="utf-8")
    # heading 被翻译
    assert "引言" in text or "译[" in text
    # 公式原样保留
    assert "x^2" in text
    # block 数量/顺序保持：两个 heading + 两个段落 + 一个公式
    assert text.count("# ") >= 2
