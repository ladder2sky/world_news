"""
重试与错误处理模块
"""
import time
import functools
from typing import Callable, Any

from loguru import logger

import settings

def retry_with_backoff(max_retries: int = None, initial_delay: float = None):
    """
    指数退避重试装饰器
    
    Args:
        max_retries: 最大重试次数
        initial_delay: 初始延迟时间（秒）
    
    Returns:
        装饰器函数
    """
    max_retries = max_retries or settings.MAX_RETRIES
    initial_delay = initial_delay or settings.RETRY_DELAY
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    if attempt < max_retries:
                        delay = initial_delay * (2 ** attempt)
                        logger.warning(
                            f"Retry {attempt + 1}/{max_retries} for {func.__name__} "
                            f"after {delay}s: {e}"
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"All {max_retries + 1} attempts failed for {func.__name__}: {e}"
                        )
            
            raise last_exception
        
        return wrapper
    return decorator

class RetryHandler:
    """重试处理器类"""
    
    def __init__(self, max_retries: int = None, initial_delay: float = None):
        """
        初始化重试处理器
        
        Args:
            max_retries: 最大重试次数
            initial_delay: 初始延迟时间（秒）
        """
        self.max_retries = max_retries or settings.MAX_RETRIES
        self.initial_delay = initial_delay or settings.RETRY_DELAY
    
    def execute(self, func: Callable, *args, **kwargs) -> Any:
        """
        执行函数，失败时自动重试
        
        Args:
            func: 要执行的函数
            *args: 函数位置参数
            **kwargs: 函数关键字参数
            
        Returns:
            函数返回值
            
        Raises:
            Exception: 所有重试失败后抛出最后一次异常
        """
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                
                if attempt < self.max_retries:
                    delay = self.initial_delay * (2 ** attempt)
                    logger.warning(
                        f"Retry {attempt + 1}/{self.max_retries} for {func.__name__} "
                        f"after {delay}s: {e}"
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        f"All {self.max_retries + 1} attempts failed for {func.__name__}: {e}"
                    )
        
        raise last_exception
