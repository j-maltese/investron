import asyncio
import time


class RateLimiter:
    """Simple async rate limiter using a token bucket approach."""

    def __init__(self, max_requests: int, per_seconds: float):
        self.max_requests = max_requests
        self.per_seconds = per_seconds
        self._semaphore = asyncio.Semaphore(max_requests)
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self):
        """Wait until a request slot is available."""
        async with self._lock:
            now = time.monotonic()
            # Remove timestamps older than the window
            self._timestamps = [
                t for t in self._timestamps if now - t < self.per_seconds
            ]
            if len(self._timestamps) >= self.max_requests:
                # Wait until the oldest request exits the window
                sleep_time = self.per_seconds - (now - self._timestamps[0])
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
            self._timestamps.append(time.monotonic())


# SEC EDGAR: 10 requests per second
edgar_rate_limiter = RateLimiter(max_requests=8, per_seconds=1.0)  # Conservative

# yfinance: 1 request per second (courtesy)
yfinance_rate_limiter = RateLimiter(max_requests=1, per_seconds=1.0)
