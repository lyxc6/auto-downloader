"""重试策略"""

from typing import ClassVar


class RetryPolicy:
    """重试策略"""

    # 可重试的HTTP状态码
    RETRYABLE_STATUS_CODES: ClassVar[set[int]] = {429, 500, 502, 503, 504}

    # 不可重试的HTTP状态码
    NON_RETRYABLE_STATUS_CODES: ClassVar[set[int]] = {400, 401, 403, 404, 405, 410}

    @staticmethod
    def get_retry_config(status_code: int | None) -> dict:
        """根据状态码获取重试配置"""
        if status_code is None:
            # 网络错误，可重试
            return {
                "max_retries": 3,
                "base_delay": 1.0,
                "max_delay": 10.0,
                "exponential_base": 2,
            }

        if status_code in RetryPolicy.NON_RETRYABLE_STATUS_CODES:
            # 不可重试错误
            return {
                "max_retries": 0,
                "base_delay": 0,
                "max_delay": 0,
                "exponential_base": 1,
            }

        if status_code in RetryPolicy.RETRYABLE_STATUS_CODES:
            # 可重试错误
            if status_code == 429:
                # 限流错误，使用更长的延迟
                return {
                    "max_retries": 5,
                    "base_delay": 2.0,
                    "max_delay": 30.0,
                    "exponential_base": 2,
                }
            else:
                # 服务器错误
                return {
                    "max_retries": 3,
                    "base_delay": 1.0,
                    "max_delay": 10.0,
                    "exponential_base": 2,
                }

        # 未知错误，保守重试
        return {
            "max_retries": 2,
            "base_delay": 1.0,
            "max_delay": 5.0,
            "exponential_base": 2,
        }

    @staticmethod
    def calculate_delay(attempt: int, config: dict) -> float:
        """计算重试延迟"""
        delay = config["base_delay"] * (config["exponential_base"] ** attempt)
        return min(delay, config["max_delay"])
