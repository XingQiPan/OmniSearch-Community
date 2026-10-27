"""线程安全的滑动窗口限流器。

单进程内足够精确，且不引入 Redis 依赖；多实例部署时把 RPM 校验换成
Redis ZSET 即可，接口保持不变。
"""
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._ops = 0

    def hit(self, identity: str, limit: int, window_sec: int = 60) -> Tuple[bool, int, int]:
        """消耗一次窗口配额。

        返回 ``(allowed, remaining, reset_in_sec)``。``limit <= 0`` 表示不限流。
        """
        if limit <= 0:
            return True, -1, 0
        now = time.time()
        cutoff = now - window_sec
        with self._lock:
            bucket = self._hits[identity]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                reset_in = max(1, int(bucket[0] + window_sec - now) + 1)
                return False, 0, reset_in
            bucket.append(now)
            remaining = max(0, limit - len(bucket))
            reset_in = max(1, int(bucket[0] + window_sec - now) + 1) if bucket else window_sec
            self._ops += 1
            if self._ops % 2000 == 0:
                self._prune(cutoff)
            return True, remaining, reset_in

    def peek(self, identity: str, limit: int, window_sec: int = 60) -> Tuple[int, int]:
        """只读查询剩余额度，不消耗配额。"""
        if limit <= 0:
            return -1, 0
        now = time.time()
        cutoff = now - window_sec
        with self._lock:
            bucket = self._hits.get(identity)
            if not bucket:
                return limit, window_sec
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            reset_in = max(1, int(bucket[0] + window_sec - now) + 1) if bucket else window_sec
            return max(0, limit - len(bucket)), reset_in

    def _prune(self, cutoff: float) -> None:
        empty = []
        for key, bucket in self._hits.items():
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if not bucket:
                empty.append(key)
        for key in empty:
            self._hits.pop(key, None)


limiter = SlidingWindowLimiter()
