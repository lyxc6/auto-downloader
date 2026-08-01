"""重试策略"""

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class RetryConfig:
    """重试配置"""

    max_retries: int  # 最大重试次数
    base_delay: float  # 基础延迟（秒）
    max_delay: float  # 最大延迟（秒）
    exponential_base: int  # 指数退避底数


class RetryPolicy:
    """重试策略"""

    # 可重试的HTTP状态码
    RETRYABLE_STATUS_CODES: ClassVar[set[int]] = {429, 500, 502, 503, 504}

    # 不可重试的HTTP状态码
    NON_RETRYABLE_STATUS_CODES: ClassVar[set[int]] = {400, 401, 403, 404, 405, 410}

    # 网络错误（连接失败/超时等），可重试
    _NETWORK_ERROR_CONFIG: ClassVar[RetryConfig] = RetryConfig(
        max_retries=3, base_delay=1.0, max_delay=10.0, exponential_base=2
    )

    # 不可重试错误
    _NON_RETRYABLE_CONFIG: ClassVar[RetryConfig] = RetryConfig(
        max_retries=0, base_delay=0, max_delay=0, exponential_base=1
    )

    # 限流错误（429），使用更长的延迟
    _RATE_LIMITED_CONFIG: ClassVar[RetryConfig] = RetryConfig(
        max_retries=3, base_delay=2.0, max_delay=30.0, exponential_base=2
    )

    # 服务器错误（500/502/503/504）
    _SERVER_ERROR_CONFIG: ClassVar[RetryConfig] = RetryConfig(
        max_retries=3, base_delay=1.0, max_delay=10.0, exponential_base=2
    )

    # 未知错误，保守重试
    _UNKNOWN_ERROR_CONFIG: ClassVar[RetryConfig] = RetryConfig(
        max_retries=2, base_delay=1.0, max_delay=5.0, exponential_base=2
    )

    @staticmethod
    def get_retry_config(status_code: int | None) -> RetryConfig:
        """根据状态码获取重试配置"""
        if status_code is None:
            # 网络错误，可重试
            return RetryPolicy._NETWORK_ERROR_CONFIG

        if status_code in RetryPolicy.NON_RETRYABLE_STATUS_CODES:
            # 不可重试错误
            return RetryPolicy._NON_RETRYABLE_CONFIG

        if status_code in RetryPolicy.RETRYABLE_STATUS_CODES:
            # 限流错误，使用更长的延迟（重试次数由调用方预算决定）
            if status_code == 429:
                return RetryPolicy._RATE_LIMITED_CONFIG
            # 服务器错误
            return RetryPolicy._SERVER_ERROR_CONFIG

        # 未知错误，保守重试
        return RetryPolicy._UNKNOWN_ERROR_CONFIG

    @staticmethod
    def calculate_delay(attempt: int, config: RetryConfig) -> float:
        """计算重试延迟（指数退避，封顶 max_delay）"""
        delay = config.base_delay * (config.exponential_base**attempt)
        return min(delay, config.max_delay)
