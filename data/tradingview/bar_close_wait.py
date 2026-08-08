from __future__ import annotations

import math
import re
import time

from data.base import KlineBar

_TIMEFRAME_SECONDS_RE = re.compile(r"^(\d+)([mhdw])$", re.IGNORECASE)

_TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
    "1d": 24 * 60 * 60,
}


def timeframe_to_seconds(timeframe: str) -> int | None:
    tf = str(timeframe or "").strip()
    if not tf:
        return None
    if tf in _TIMEFRAME_SECONDS:
        return _TIMEFRAME_SECONDS[tf]
    m = _TIMEFRAME_SECONDS_RE.match(tf)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    if unit == "m":
        return n * 60
    if unit == "h":
        return n * 3600
    if unit == "d":
        return n * 86400
    if unit == "w":
        return n * 7 * 86400
    return None


def seconds_until_bar_closes(
    ts_open_ms: int,
    timeframe: str,
    *,
    now_ms: int | None = None,
) -> int | None:
    duration_s = timeframe_to_seconds(timeframe)
    if duration_s is None:
        return None
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    duration_ms = duration_s * 1000
    elapsed_ms = int(now_ms) - int(ts_open_ms)
    if elapsed_ms == 0:
        return duration_s

    remainder_ms = elapsed_ms % duration_ms
    if remainder_ms == 0:
        return 0 if elapsed_ms > 0 else duration_s

    remaining_ms = duration_ms - remainder_ms
    return int(math.ceil(remaining_ms / 1000))


def reference_now_ms(
    *,
    now_ms: int | None = None,
    data_source: object | None = None,
) -> int:
    if now_ms is not None:
        return int(now_ms)
    local_ms = int(time.time() * 1000)
    if data_source is not None:
        server_time_ms = getattr(data_source, "server_time_ms", None)
        if callable(server_time_ms):
            t = server_time_ms()
            if t is not None:
                server_ms = int(t)
                if local_ms - server_ms < 60_000:
                    return server_ms
    return local_ms
