"""翻译、重试、checkpoint、resume 测试。"""
import json
import os
import sys
from pathlib import Path

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, SRC)

from pf_core.models import Chunk
from pf_translation.checkpoint import CheckpointManager
from pf_translation.retry import RetryPolicy


def test_retry_policy():
    p = RetryPolicy(max_retries=3)
    assert p.is_retryable(429) is True
    assert p.is_retryable(500) is True
    assert p.is_retryable(502) is True
    assert p.is_retryable(503) is True
    assert p.is_retryable(504) is True
    assert p.is_retryable(401) is False
    assert p.is_retryable(403) is False
    assert p.is_retryable(400) is False
    # 网络错误可重试
    assert p.is_retryable(None, error=ConnectionError()) is True


def test_retry_delay_exponential():
    p = RetryPolicy(max_retries=3, backoff_base=2.0, initial_delay=2.0)
    assert p.delay(0) == 2.0
    assert p.delay(1) == 4.0
    assert p.delay(2) == 8.0


def test_checkpoint_save_load(tmp_path):
    src = tmp_path / "input.md"
    src.write_text("hello world", encoding="utf-8")
    cm = CheckpointManager(tmp_path / "job", src, "glm-4.7-flash")

    state = cm.init_state(["chunk-000001", "chunk-000002"])
    assert state.source_hash == cm.source_hash

    c = Chunk(chunk_id="chunk-000001", block_ids=["b1"], source_text="hi")
    c.status = "done"
    c.translated_text = "你好"
    cm.save_chunk(c)
    cm.mark_done("chunk-000001")

    loaded = cm.load_chunk("chunk-000001")
    assert loaded is not None
    assert loaded.translated_text == "你好"
    assert loaded.status == "done"

    state2 = cm.load_state()
    assert state2 is not None
    assert "chunk-000001" in state2.done_chunk_ids


def test_checkpoint_reject_changed_source(tmp_path):
    src = tmp_path / "input.md"
    src.write_text("v1", encoding="utf-8")
    cm = CheckpointManager(tmp_path / "job", src, "glm-4.7-flash")
    state = cm.init_state(["chunk-000001"])

    # 修改源文件
    src.write_text("v2 different", encoding="utf-8")
    cm2 = CheckpointManager(tmp_path / "job", src, "glm-4.7-flash")
    assert cm2.verify_source_hash(state) is False
