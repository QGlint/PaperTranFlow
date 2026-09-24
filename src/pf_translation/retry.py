"""重试策略（RetryPolicy）。

区分可重试（429/500/502/503/504/timeout/连接重置）与不可重试
（401/403/参数错误/凭据错误），采用 exponential backoff。
"""
from __future__ import annotations

import time
from dataclasses import dataclass

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
NON_RETRYABLE_STATUS = {400, 401, 403, 404, 422}

# GLM 业务错误码：可重试（负载过高/限流等瞬态错误）
RETRYABLE_GLM_CODES = {1305, 1301, 1302, 1303, 1304}


@dataclass
class RetryPolicy:
    max_retries: int = 3
    backoff_base: float = 2.0
    # 首轮退避秒数
    initial_delay: float = 2.0

    def is_retryable(self, status_code: int | None, error: BaseException | None = None) -> bool:
        if status_code in NON_RETRYABLE_STATUS:
            return False
        if status_code in RETRYABLE_STATUS:
            return True
        if status_code in RETRYABLE_GLM_CODES:
            return True
        # 网络/超时类错误可重试
        if error is not None:
            return True
        return False

    def delay(self, attempt: int) -> float:
        """第 attempt 次（0-based）重试前的退避秒数。"""
        return self.initial_delay * (self.backoff_base ** attempt)

    def sleep(self, attempt: int) -> None:
        time.sleep(self.delay(attempt))

    def overload_delay(self, attempt: int) -> float:
        """GLM 负载过高（1305）时的更长退避。"""
        return self.initial_delay * 4 * (self.backoff_base ** attempt)
