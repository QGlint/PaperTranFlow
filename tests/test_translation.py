"""翻译、重试、checkpoint、resume 测试。"""
import json
import os
import sys
from pathlib import Path

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, SRC)

from ptf_core.models import Chunk
from ptf_translation.checkpoint import CheckpointManager
from ptf_translation.retry import RetryPolicy


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


def test_retry_delay_capped_by_max_delay():
    p = RetryPolicy(backoff_base=2.0, initial_delay=60.0, max_delay=120.0)
    assert p.delay(0) == 60.0
    assert p.delay(1) == 120.0   # 120 封顶
    assert p.delay(5) == 120.0


def test_rate_limit_delay_longer_than_normal():
    """限流（1302/1305）退避应比普通错误更长。"""
    p = RetryPolicy(backoff_base=2.0, initial_delay=2.0, rate_limit_base=10.0)
    assert p.is_rate_limit(1302) is True
    assert p.is_rate_limit(1305) is True
    assert p.is_rate_limit(500) is False
    assert p.rate_limit_delay(0) == 10.0
    assert p.rate_limit_delay(0) > p.delay(0)


def test_delay_for_picks_rate_limit_backoff():
    # 关掉抖动以便精确断言基础值
    p = RetryPolicy(initial_delay=2.0, rate_limit_base=10.0, overload_base=30.0,
                    jitter_ratio=0.0)
    assert p.delay_for(0, 1302) == 10.0   # 速率限制
    assert p.delay_for(0, 1305) == 30.0   # 平台过载（更长）
    assert p.delay_for(0, 500) == 2.0     # 普通错误


def test_glm_rate_limit_codes_retryable():
    """依官方错误码表：1302/1305 可重试；1234 网络错误可重试。"""
    p = RetryPolicy()
    assert p.is_retryable(1302) is True   # 用户速率限制 (429)
    assert p.is_retryable(1305) is True   # 平台服务过载 (429)
    assert p.is_retryable(1234) is True   # 网络错误 (500)
    assert p.is_retryable(1200) is True   # API 调用失败 (500)
    assert p.is_retryable(1230) is True   # 流程出错 (500)
    # 不可重试
    assert p.is_retryable(401) is False
    assert p.is_retryable(400) is False


def test_glm_non_retryable_business_codes():
    """内容安全(1301)与额度耗尽(1308/1310/1316)不应重试（重试无意义）。"""
    p = RetryPolicy()
    assert p.is_retryable(1301) is False   # 内容安全审核 (400)
    assert p.is_retryable(1308) is False   # 使用上限 (429)
    assert p.is_retryable(1310) is False   # 周/月上限
    assert p.is_retryable(1316) is False   # 5 小时上限
    assert p.is_retryable(1317) is False   # 7 天上限


def test_overload_backoff_longer_than_rate_limit():
    """1305（平台过载）退避应比 1302（速率限制）更长。"""
    p = RetryPolicy(rate_limit_base=10.0, overload_base=30.0, jitter_ratio=0.0)
    assert p.is_overload(1305) is True
    assert p.is_overload(1302) is False
    assert p.delay_for(0, 1305) == 30.0
    assert p.delay_for(0, 1302) == 10.0
    assert p.delay_for(0, 500) == p.initial_delay
    assert p.delay_for(0, 1305) > p.delay_for(0, 1302)


def test_jitter_adds_randomness():
    """抖动应让等待时间落在 [base, base*(1+ratio)] 区间内。"""
    p = RetryPolicy(overload_base=30.0, max_delay=1000.0, jitter_ratio=0.5)
    vals = [p.delay_for(0, 1305) for _ in range(50)]
    assert all(30.0 <= v <= 45.0 for v in vals)
    assert len(set(round(v, 6) for v in vals)) > 1  # 不是固定值


def test_jitter_disabled_gives_exact_value():
    p = RetryPolicy(overload_base=30.0, jitter_ratio=0.0)
    assert p.delay_for(0, 1305) == 30.0
    assert p.delay_for(1, 1305) == 60.0


def test_sleep_interval_disabled_when_zero():
    """request_interval=0 时不应阻塞（测试用）。"""
    import time

    p = RetryPolicy(request_interval=0.0)
    t0 = time.monotonic()
    p.sleep_interval()
    assert time.monotonic() - t0 < 0.05


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
