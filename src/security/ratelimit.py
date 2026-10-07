# In-memory sliding-window rate limiter. Standard library only.
# ponytail: lives in one process's memory, so limits reset on restart and are not shared between
# workers; move the counters to Redis or the gateway if the app ever runs as several processes.

import collections  # deque per key.
import threading  # The counters are shared by uvicorn's threads.
import time  # Monotonic clock for the window.


class SlidingWindow:
    """Counts requests per key over the last `window` seconds."""

    def __init__(self):
        self.hits = collections.defaultdict(collections.deque)  # key -> times of recent requests
        self.lock = threading.Lock()

    def hit(self, key, limit, window):
        """Record one request for key. Returns 0 if allowed, or the whole seconds to wait (Retry-After)."""
        now = time.monotonic()
        with self.lock:
            times = self.hits[key]
            while times and times[0] <= now - window:  # Forget requests older than the window.
                times.popleft()
            if len(times) >= limit:
                return max(1, int(times[0] + window - now) + 1)
            times.append(now)
            if len(self.hits) > 10000:  # Keep memory bounded: drop keys with no recent requests.
                for k in [k for k, v in self.hits.items() if not v]:
                    del self.hits[k]
            return 0

    def reset(self):
        """Forget every counter (used by the self-checks)."""
        with self.lock:
            self.hits.clear()


LIMITER = SlidingWindow()  # The one limiter the app uses.
