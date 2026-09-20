"""Application performance telemetry.

Self-contained: counters, gauges and latency timers with percentiles, plus a
rolling window of recent operations. No external metrics stack required, but the
same numbers are exposed in Prometheus text format at ``/metrics`` so an
organisation that already has Grafana can scrape it.

Every HTTP request, storage round-trip and graph query is timed through
:func:`track`, which is what the "application performance" KPI page reads.
"""

from __future__ import annotations

import os
import platform
import threading
import time
from collections import deque
from contextlib import contextmanager
from typing import Any, Iterator

try:  # POSIX only; Windows has no `resource` module at all.
    import resource
except ImportError:  # pragma: no cover - exercised on Windows
    resource = None  # type: ignore[assignment]

_START_TIME = time.time()


class _Timer:
    """Latency samples for one operation, with a bounded reservoir."""

    __slots__ = ("count", "total_ms", "max_ms", "min_ms", "errors", "samples")

    def __init__(self, window: int = 512) -> None:
        self.count = 0
        self.total_ms = 0.0
        self.max_ms = 0.0
        self.min_ms = float("inf")
        self.errors = 0
        self.samples: deque[float] = deque(maxlen=window)

    def record(self, duration_ms: float, failed: bool) -> None:
        self.count += 1
        self.total_ms += duration_ms
        self.max_ms = max(self.max_ms, duration_ms)
        self.min_ms = min(self.min_ms, duration_ms)
        self.samples.append(duration_ms)
        if failed:
            self.errors += 1

    def snapshot(self) -> dict[str, Any]:
        ordered = sorted(self.samples)

        def percentile(fraction: float) -> float:
            if not ordered:
                return 0.0
            index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
            return round(ordered[index], 3)

        return {
            "count": self.count,
            "errors": self.errors,
            "error_rate": round(self.errors / self.count, 4) if self.count else 0.0,
            "avg_ms": round(self.total_ms / self.count, 3) if self.count else 0.0,
            "min_ms": round(self.min_ms, 3) if self.count else 0.0,
            "p50_ms": percentile(0.50),
            "p95_ms": percentile(0.95),
            "p99_ms": percentile(0.99),
            "max_ms": round(self.max_ms, 3),
        }


class Telemetry:
    """Process-wide metrics registry."""

    def __init__(self, recent_window: int = 200) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}
        self._timers: dict[str, _Timer] = {}
        self._recent: deque[dict[str, Any]] = deque(maxlen=recent_window)
        self.started_at = _START_TIME

    # -- recording ----------------------------------------------------------
    def increment(self, name: str, amount: int = 1, **labels: Any) -> None:
        key = _key(name, labels)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + amount

    def gauge(self, name: str, value: float, **labels: Any) -> None:
        with self._lock:
            self._gauges[_key(name, labels)] = float(value)

    def observe(self, name: str, duration_ms: float, *, failed: bool = False, **labels: Any) -> None:
        key = _key(name, labels)
        with self._lock:
            timer = self._timers.get(key)
            if timer is None:
                timer = self._timers[key] = _Timer()
            timer.record(duration_ms, failed)
            self._recent.append(
                {
                    "at": time.time(),
                    "operation": key,
                    "duration_ms": round(duration_ms, 3),
                    "ok": not failed,
                }
            )

    @contextmanager
    def track(self, name: str, **labels: Any) -> Iterator[dict[str, Any]]:
        """Time a block; records an error sample if it raises."""
        context: dict[str, Any] = {}
        started = time.perf_counter()
        failed = False
        try:
            yield context
        except Exception:
            failed = True
            raise
        finally:
            self.observe(name, (time.perf_counter() - started) * 1000.0, failed=failed, **labels)

    # -- reading ------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counters = dict(self._counters)
            gauges = dict(self._gauges)
            timers = {name: timer.snapshot() for name, timer in self._timers.items()}
            recent = list(self._recent)

        requests = sum(v for k, v in counters.items() if k.startswith("http.requests"))
        errors = sum(v for k, v in counters.items() if k.startswith("http.errors"))
        uptime = time.time() - self.started_at
        window = [r for r in recent if r["at"] > time.time() - 60]

        return {
            "uptime_seconds": round(uptime, 1),
            "started_at": _iso(self.started_at),
            "counters": counters,
            "gauges": gauges,
            "operations": dict(sorted(timers.items())),
            "summary": {
                "requests_total": requests,
                "errors_total": errors,
                "error_rate": round(errors / requests, 4) if requests else 0.0,
                "requests_per_minute_1m": len([r for r in window if r["operation"].startswith("http.")]),
                "avg_latency_ms_1m": round(sum(r["duration_ms"] for r in window) / len(window), 3) if window else 0.0,
                "slowest_operation": max(timers.items(), key=lambda kv: kv[1]["p95_ms"], default=("", {}))[0],
            },
            "process": self.process_stats(),
            "recent": recent[-50:],
        }

    def process_stats(self) -> dict[str, Any]:
        cpu_user, cpu_system = self._cpu_times()
        return {
            "pid": os.getpid(),
            "threads": threading.active_count(),
            "cpu_user_seconds": cpu_user,
            "cpu_system_seconds": cpu_system,
            "max_rss_mb": self._peak_memory_mb(),
        }

    @staticmethod
    def _cpu_times() -> tuple[float, float]:
        """User/system CPU seconds. ``os.times()`` is portable; ``resource`` is not."""
        times = os.times()
        return round(times.user, 3), round(times.system, 3)

    @staticmethod
    def _peak_memory_mb() -> float | None:
        """Peak resident set size in MB, or None where the platform offers no cheap way to ask."""
        if resource is not None:  # Linux, macOS and other POSIX systems
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            # ru_maxrss is KiB on Linux, bytes on macOS.
            rss_kib = peak if platform.system() != "Darwin" else peak / 1024
            return round(rss_kib / 1024, 2)
        if platform.system() == "Windows":
            return Telemetry._windows_peak_memory_mb()
        return None  # pragma: no cover - unknown platform, no crash either way

    @staticmethod
    def _windows_peak_memory_mb() -> float | None:  # pragma: no cover - needs a Windows runner
        """Peak working set via the Win32 API, using only the stdlib (ctypes)."""
        try:
            import ctypes
            from ctypes import wintypes

            class ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(ProcessMemoryCounters)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ok = ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
            if not ok:
                return None
            return round(counters.PeakWorkingSetSize / (1024 * 1024), 2)
        except Exception:
            return None

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._timers.clear()
            self._recent.clear()

    # -- export -------------------------------------------------------------
    def prometheus(self) -> str:
        """Render the registry in Prometheus text exposition format."""
        snapshot = self.snapshot()
        lines: list[str] = []
        for name, value in sorted(snapshot["counters"].items()):
            lines.append(f"{_prom_name(name)} {value}")
        for name, value in sorted(snapshot["gauges"].items()):
            lines.append(f"{_prom_name(name)} {value}")
        for name, stats in snapshot["operations"].items():
            base = _prom_name(name)
            lines.append(f"{base}_count {stats['count']}")
            lines.append(f"{base}_errors {stats['errors']}")
            for quantile in ("p50", "p95", "p99"):
                lines.append(f'{base}_latency_ms{{quantile="{quantile[1:]}"}} {stats[quantile + "_ms"]}')
        process = snapshot["process"]
        lines.append(f"setm_uptime_seconds {snapshot['uptime_seconds']}")
        lines.append(f"setm_max_rss_mb {process['max_rss_mb']}")
        lines.append(f"setm_threads {process['threads']}")
        return "\n".join(lines) + "\n"


def _key(name: str, labels: dict[str, Any]) -> str:
    if not labels:
        return name
    rendered = ",".join(f"{k}={v}" for k, v in sorted(labels.items()) if v not in (None, ""))
    return f"{name}[{rendered}]" if rendered else name


def _prom_name(key: str) -> str:
    base = key.split("[", 1)[0].replace(".", "_").replace("-", "_")
    labels = key[len(key.split("[", 1)[0]) :].strip("[]")
    metric = f"setm_{base}"
    if not labels:
        return metric
    rendered = ",".join(f'{k}="{v}"' for k, v in (pair.split("=", 1) for pair in labels.split(",") if "=" in pair))
    return f"{metric}{{{rendered}}}"


def _iso(epoch: float) -> str:
    import datetime as dt

    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


#: The registry the application uses. Tests may build their own.
telemetry = Telemetry()
