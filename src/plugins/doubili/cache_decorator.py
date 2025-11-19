"""
缓存装饰器模块

提供TTL缓存功能，用于缓存HTTP请求结果，减少重复请求。
遵循Python缓存最佳实践，支持内存限制和自动清理。
"""

import time
from collections import OrderedDict
from functools import wraps
from typing import Any, TypeVar
from collections.abc import Callable

from nonebot import logger

F = TypeVar("F", bound=Callable[..., Any])


class CacheEntry:
    """缓存条目"""

    def __init__(self, result: Any, ttl: int):
        self.result = result
        self.expiry_time = time.time() + ttl
        self.access_count = 1


class MemoryCache:
    """内存缓存管理器

    特性：
    - LRU淘汰策略（基于OrderedDict）
    - 自动过期清理
    - 内存上限控制
    - 线程安全（基于GIL）
    """

    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self.cache: OrderedDict[str, CacheEntry] = OrderedDict()

    def get(self, key: str, current_time: float | None = None) -> Any | None:
        """获取缓存值

        Returns:
            缓存值（未过期）
            None（缓存不存在或已过期）
        """
        if current_time is None:
            current_time = time.time()

        if key not in self.cache:
            return None

        entry = self.cache[key]

        # 检查是否过期
        if current_time > entry.expiry_time:
            del self.cache[key]
            return None

        # 更新访问顺序（LRU）
        entry.access_count += 1
        self.cache.move_to_end(key)

        return entry.result

    def set(self, key: str, value: Any, ttl: int) -> None:
        """设置缓存值

        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒）
        """
        # 如果缓存已满，删除最久未使用的
        if len(self.cache) >= self.max_size:
            oldest_key = next(iter(self.cache))
            del self.cache[oldest_key]
            logger.debug(f"缓存已满，淘汰最久未使用的键: {oldest_key}")

        self.cache[key] = CacheEntry(value, ttl)
        logger.debug(f"设置缓存: {key} (TTL={ttl}s)")

    def clear_expired(self) -> int:
        """清理过期缓存

        Returns:
            清理的条目数量
        """
        current_time = time.time()
        expired_keys = [
            key for key, entry in self.cache.items() if current_time > entry.expiry_time
        ]

        for key in expired_keys:
            del self.cache[key]

        if expired_keys:
            logger.debug(f"清理 {len(expired_keys)} 个过期缓存条目")

        return len(expired_keys)

    def clear(self) -> None:
        """清空所有缓存"""
        self.cache.clear()
        logger.info("清空所有缓存")


def cache_http_result(ttl: int = 300, max_cache_size: int = 100):
    """HTTP请求结果缓存装饰器

    缓存函数的返回值，支持TTL过期和LRU淘汰。

    Args:
        ttl: 缓存过期时间（秒），默认5分钟
        max_cache_size: 最大缓存条目数，默认100

    Returns:
        装饰器函数

    示例：
        @cache_http_result(ttl=600, max_cache_size=50)
        async def get_video_info(video_id: str):
            # 发起HTTP请求
            return response.json()
    """

    cache = MemoryCache(max_size=max_cache_size)

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # 生成缓存键（基于函数名和参数）
            key_parts = [func.__name__]
            key_parts.extend(str(arg) for arg in args)
            key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
            cache_key = ":".join(key_parts)

            # 尝试从缓存获取
            current_time = time.time()
            cached_result = cache.get(cache_key, current_time)

            if cached_result is not None:
                logger.debug(f"缓存命中: {cache_key}")
                return cached_result

            # 执行原函数
            result = await func(*args, **kwargs)

            # 只缓存成功的结果（不缓存异常）
            if result is not None and not isinstance(result, Exception):
                cache.set(cache_key, result, ttl)
                logger.debug(f"缓存设置: {cache_key} (TTL={ttl}s)")

            return result

        # 将缓存管理器附加到函数，便于测试和清理
        wrapper._cache = cache  # type: ignore
        wrapper.cache_clear = cache.clear  # type: ignore

        return wrapper  # type: ignore

    return decorator
