"""重试策略（RetryPolicy）。

区分可重试（429/500/502/503/504/timeout/连接重置）与不可重试
（401/403/参数错误/凭据错误），采用 exponential backoff。
"""
from __future__ import annotations

import time
from dataclasses import dataclass

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
NON_RETRYABLE_STATUS = {400, 401, 403, 404, 422}


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
        # 网络/超时类错误可重试
        if error is not None:
            return True
        return False

    def delay(self, attempt: int) -> float:
        """第 attempt 次（0-based）重试前的退避秒数。"""
        return self.initial_delay * (self.backoff_base ** attempt)

    def sleep(self, attempt: int) -> None:
        time.sleep(self.delay(attempt))
