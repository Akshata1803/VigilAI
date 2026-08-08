"""
Vigil AI — Performance Metrics Collector
==========================================
Lightweight metrics system for tracking:
  - Analyzer execution times
  - Pipeline throughput
  - Finding counts per engine
  - Error rates
  - Memory usage snapshots

Thread-safe singleton pattern for concurrent access.
"""

import time
import threading
from collections import defaultdict
from typing import Dict, List, Optional


class MetricsCollector:
    """Thread-safe singleton metrics collector for the detection pipeline."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._timings: Dict[str, List[float]] = defaultdict(list)
        self._counters: Dict[str, int] = defaultdict(int)
        self._gauges: Dict[str, float] = {}
        self._errors: Dict[str, int] = defaultdict(int)
        self._data_lock = threading.Lock()

    # ── Timing ─────────────────────────────────────────────────────────────────

    def start_timer(self, name: str) -> float:
        """Start a timer, returns the start timestamp."""
        return time.perf_counter()

    def stop_timer(self, name: str, start_time: float) -> float:
        """Stop a timer and record the duration in milliseconds."""
        duration_ms = (time.perf_counter() - start_time) * 1000
        with self._data_lock:
            self._timings[name].append(duration_ms)
            # Keep only last 100 measurements to bound memory
            if len(self._timings[name]) > 100:
                self._timings[name] = self._timings[name][-100:]
        return duration_ms

    class Timer:
        """Context manager for measuring execution time."""

        def __init__(self, metrics: 'MetricsCollector', name: str):
            self.metrics = metrics
            self.name = name
            self.start = 0.0
            self.duration_ms = 0.0

        def __enter__(self):
            self.start = self.metrics.start_timer(self.name)
            return self

        def __exit__(self, *exc):
            self.duration_ms = self.metrics.stop_timer(self.name, self.start)

    def timer(self, name: str) -> 'Timer':
        """Create a context-manager timer.

        Usage:
            with metrics.timer('dom_analyzer') as t:
                result = analyzer.run(data)
            print(f"Took {t.duration_ms:.1f}ms")
        """
        return self.Timer(self, name)

    # ── Counters ───────────────────────────────────────────────────────────────

    def increment(self, name: str, value: int = 1):
        """Increment a counter."""
        with self._data_lock:
            self._counters[name] += value

    def record_error(self, analyzer_name: str):
        """Record an analyzer error."""
        with self._data_lock:
            self._errors[analyzer_name] += 1

    # ── Gauges ─────────────────────────────────────────────────────────────────

    def set_gauge(self, name: str, value: float):
        """Set a gauge value (last-write-wins)."""
        with self._data_lock:
            self._gauges[name] = value

    # ── Reporting ──────────────────────────────────────────────────────────────

    def get_summary(self) -> Dict:
        """Get a snapshot of all collected metrics."""
        with self._data_lock:
            timing_summary = {}
            for name, values in self._timings.items():
                if values:
                    timing_summary[name] = {
                        'count': len(values),
                        'avg_ms': round(sum(values) / len(values), 2),
                        'min_ms': round(min(values), 2),
                        'max_ms': round(max(values), 2),
                        'last_ms': round(values[-1], 2),
                    }

            return {
                'timings': timing_summary,
                'counters': dict(self._counters),
                'gauges': dict(self._gauges),
                'errors': dict(self._errors),
            }

    def get_pipeline_stats(self) -> Dict:
        """Get pipeline-specific performance stats for API response."""
        summary = self.get_summary()
        pipeline_time = summary['timings'].get('pipeline_total', {})
        return {
            'pipeline_total_ms': pipeline_time.get('last_ms', 0),
            'analyzer_timings': {
                k: v.get('last_ms', 0)
                for k, v in summary['timings'].items()
                if k.startswith('analyzer_')
            },
            'total_scans': summary['counters'].get('scans_completed', 0),
            'total_errors': sum(summary['errors'].values()),
        }

    def reset(self):
        """Reset all metrics (for testing)."""
        with self._data_lock:
            self._timings.clear()
            self._counters.clear()
            self._gauges.clear()
            self._errors.clear()
