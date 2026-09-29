"""GLM 错误处理测试：业务错误码必须优先于 HTTP 状态码。

背景：GLM 的 1302（速率限制）/1305（平台过载）都以 HTTP 429 返回。
若只取 HTTP 状态码，会丢失限流语义，退避过短导致持续撞墙。
"""
import os
import sys

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, SRC)

from ptf_translation.glm import _business_code, _error_text, _parse_json
from ptf_translation.retry import RetryPolicy


class _FakeResp:
    def __init__(self, payload, text=""):
        self._payload = payload
        self.text = text or (str(payload) if payload is not None else "")

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def test_business_code_extracted_from_nested_error():
    body = {"error": {"code": "1305", "message": "该模型当前访问量过大"}}
    assert _business_code(body) == 1305


def test_business_code_extracted_from_top_level():
    assert _business_code({"code": "1302"}) == 1302
    assert _business_code({"msgCode": "1302"}) == 1302


def test_business_code_none_when_absent():
    assert _business_code({"choices": []}) is None
    assert _business_code(None) is None


def test_error_text_prefers_message():
    body = {"error": {"code": "1305", "message": "平台过载"}}
    assert "平台过载" in _error_text(body, _FakeResp(body))


def test_parse_json_tolerates_invalid():
    assert _parse_json(_FakeResp(None)) is None


def test_retry_policy_uses_business_code_for_backoff():
    """1305 应比 1302 退避更长；两者都比普通错误长。"""
    p = RetryPolicy(initial_delay=2.0, rate_limit_base=10.0, overload_base=30.0,
                    jitter_ratio=0.0)
    assert p.delay_for(0, 1305) == 30.0
    assert p.delay_for(0, 1302) == 10.0
    assert p.delay_for(0, 500) == 2.0
    # 若退化成 HTTP 429，会得到 2s（错误行为）
    assert p.delay_for(0, 429) == 2.0
