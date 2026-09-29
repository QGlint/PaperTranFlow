"""重试策略（RetryPolicy）与请求节流。

设计（严格单线程串行，避让限流）：
    - concurrency 恒为 1（串行），不做并发
    - 每次请求之间有最小间隔（request_interval），主动避让
    - 可重试错误（429/5xx/超时/网络）用 exponential backoff
    - GLM 限流类业务错误（1302 速率限制 / 1305 负载过高）用更长的退避
      （rate_limit_base 起步，倍增至上限），并允许更多次重试

区分：
    可重试  : 429 500 502 503 504 / 网络超时 / GLM 1301-1305
    不可重试: 400 401 403 404 422（参数或凭据错误，重试无意义）
"""
from __future__ import annotations

import time
from dataclasses import dataclass

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
NON_RETRYABLE_STATUS = {400, 401, 403, 404, 422}

# ---- GLM（智谱）业务错误码 ----
# 依据官方错误码表：https://docs.bigmodel.cn/cn/faq/api-code
#
# 可重试（瞬态，稍后可能成功）:
#   1200/1230/1234  服务内部错误、流程出错、网络错误（HTTP 500）
#   1302            用户速率限制（HTTP 429）—— 需延长退避
#   1305            平台服务过载（HTTP 429）—— 需延长退避
#
# 不可重试（重试无意义，浪费配额）:
#   1301            内容安全审核未通过（HTTP 400）—— 同一输入重试仍会失败
#   1308/1310/1316-1321  已达使用上限（HTTP 429）—— 需等额度重置，不宜狂重试
#   1000-1222       鉴权/参数/模型类错误
GLM_RATE_LIMIT_CODES = {1302}           # 用户速率限制
GLM_OVERLOAD_CODES = {1305}             # 平台服务过载
GLM_TRANSIENT_CODES = {1200, 1230, 1234}  # 服务内部错误 / 网络错误
# 空响应（由 GLM 后端合成的伪码）：模型偶发返回空内容，应重试
GLM_EMPTY_RESPONSE_CODE = 1300
# 使用上限类（额度耗尽）：不重试
GLM_QUOTA_CODES = {1308, 1310, 1316, 1317, 1318, 1319, 1320, 1321}
# 内容安全（不重试）
GLM_CONTENT_FILTER_CODES = {1301}

GLM_RETRYABLE_CODES = (
    GLM_RATE_LIMIT_CODES
    | GLM_OVERLOAD_CODES
    | GLM_TRANSIENT_CODES
    | {GLM_EMPTY_RESPONSE_CODE}
)
# 兼容旧名
RETRYABLE_GLM_CODES = GLM_RETRYABLE_CODES


@dataclass
class RetryPolicy:
    """限流退避策略（依智谱官方速率限制文档）。

    官方建议（https://docs.bigmodel.cn/cn/api/rate-limit）：
        1302（账户速率限制）：降低并发、增加请求队列/排队、避免请求过于密集
        1305（平台服务过载）：稍后重试、**增加重试间隔，避免立即高频重试**
        通用原则：使用请求队列或并发池；避免瞬时「洪峰式」请求；
                  **避免固定间隔的高频重试**

    因此本实现：
        - 严格串行（并发恒为 1），天然满足「降低并发」
        - 请求之间加入**带抖动的间隔**（避免固定节奏）
        - 退避加入**随机抖动**（jitter），打散重试节奏，避免同步撞墙
        - 1305 退避显著长于 1302（平台过载需更久恢复）
    """

    max_retries: int = 2
    backoff_base: float = 2.0
    # 首轮退避秒数（普通可重试错误）
    initial_delay: float = 2.0
    # 限流类错误的起步退避
    # 1302（自身频率过快）用 rate_limit_base；1305（平台过载）用 overload_base
    rate_limit_base: float = 10.0
    overload_base: float = 30.0
    # 退避上限，避免无限等待
    max_delay: float = 300.0
    # 每次请求前的最小间隔（主动避让限流）
    request_interval: float = 3.0
    # 抖动比例：实际等待 = 基础值 * (1 + uniform(0, jitter_ratio))
    # 用于打散重试节奏（官方明确建议避免「固定间隔的高频重试」）
    jitter_ratio: float = 0.3

    def is_retryable(self, status_code: int | None, error: BaseException | None = None) -> bool:
        if status_code in NON_RETRYABLE_STATUS:
            return False
        # 额度耗尽 / 内容安全：重试无意义，直接失败（避免浪费配额）
        if status_code in GLM_QUOTA_CODES or status_code in GLM_CONTENT_FILTER_CODES:
            return False
        if status_code in RETRYABLE_STATUS:
            return True
        if status_code in GLM_RETRYABLE_CODES:
            return True
        # 网络/超时类错误可重试
        if error is not None:
            return True
        return False

    def is_rate_limit(self, status_code: int | None) -> bool:
        """是否属于「请求过频/负载过高」类限流。"""
        return status_code in GLM_RATE_LIMIT_CODES or status_code in GLM_OVERLOAD_CODES

    def is_overload(self, status_code: int | None) -> bool:
        """是否属于平台级过载（1305）—— 需更长退避。"""
        return status_code in GLM_OVERLOAD_CODES

    def _jitter(self, seconds: float) -> float:
        """给等待时间加随机抖动，避免固定节奏。"""
        import random

        if seconds <= 0 or self.jitter_ratio <= 0:
            return max(seconds, 0.0)
        return seconds * (1.0 + random.uniform(0.0, self.jitter_ratio))

    def delay(self, attempt: int) -> float:
        """第 attempt 次（0-based）重试前的退避秒数（普通错误）。"""
        return min(self.initial_delay * (self.backoff_base ** attempt), self.max_delay)

    def rate_limit_delay(self, attempt: int) -> float:
        """速率限制（1302）退避：起步 rate_limit_base，指数增长，带上限。"""
        return min(self.rate_limit_base * (self.backoff_base ** attempt), self.max_delay)

    def overload_delay(self, attempt: int) -> float:
        """平台过载（1305）退避：起步 overload_base（更长），带上限。"""
        return min(self.overload_base * (self.backoff_base ** attempt), self.max_delay)

    def delay_for(self, attempt: int, status_code: int | None = None) -> float:
        """按错误类型选择退避时长（含抖动）。

        1305（平台过载）> 1302（速率限制）> 普通错误
        """
        if self.is_overload(status_code):
            base = self.overload_delay(attempt)
        elif self.is_rate_limit(status_code):
            base = self.rate_limit_delay(attempt)
        else:
            base = self.delay(attempt)
        return min(self._jitter(base), self.max_delay)

    def sleep(self, attempt: int, status_code: int | None = None) -> None:
        time.sleep(self.delay_for(attempt, status_code))

    def sleep_interval(self) -> None:
        """请求之间的间隔（带抖动，主动避让）。

        官方建议避免「固定间隔的高频重试」，因此这里加入抖动，
        打散请求节奏，降低被判定为密集请求的概率。
        """
        if self.request_interval > 0:
            time.sleep(self._jitter(self.request_interval))
