from collections import defaultdict
import threading
import time
from typing import Any, Dict


class MetricsRegistry:
    """
    Thread-safe Operational Metrics Registry for Synesis.
    Tracks production counters, histograms, and rates without external dependencies.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: Dict[str, int] = defaultdict(int)
        self._gauges: Dict[str, float] = {}
        self._timers: Dict[str, list] = defaultdict(list)
        self._start_time = time.time()

    def increment(self, metric_name: str, value: int = 1, labels: Dict[str, str] = None) -> None:
        """Increment a counter metric."""
        with self._lock:
            key = self._format_key(metric_name, labels)
            self._counters[key] += value

    def set_gauge(self, metric_name: str, value: float, labels: Dict[str, str] = None) -> None:
        """Set an instantaneous gauge metric."""
        with self._lock:
            key = self._format_key(metric_name, labels)
            self._gauges[key] = float(value)

    def record_timing(self, metric_name: str, duration_ms: float, labels: Dict[str, str] = None) -> None:
        """Record an execution duration in milliseconds."""
        with self._lock:
            key = self._format_key(metric_name, labels)
            self._timers[key].append(duration_ms)
            # Keep bounded window of last 100 timings
            if len(self._timers[key]) > 100:
                self._timers[key].pop(0)

    def _format_key(self, metric_name: str, labels: Dict[str, str] = None) -> str:
        if not labels:
            return metric_name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{metric_name}{{{label_str}}}"

    def _sum_counter(self, name: str) -> int:
        total = 0
        for k, v in self._counters.items():
            if k == name or k.startswith(f"{name}{{"):
                total += v
        return total

    def get_snapshot(self) -> Dict[str, Any]:
        """Return a point-in-time snapshot of all recorded metrics."""
        with self._lock:
            uptime = time.time() - self._start_time
            # Standard metric names
            return {
                "uptime_seconds": round(uptime, 2),
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "summary": {
                    "ingestion_events_total": self._sum_counter("ingestion_events_total"),
                    "ingestion_failures_total": self._sum_counter("ingestion_failures_total"),
                    "connector_api_errors_total": self._sum_counter("connector_api_errors_total"),
                    "connector_rate_limits_total": self._sum_counter("connector_rate_limits_total"),
                    "processing_jobs_total": self._sum_counter("processing_jobs_total"),
                    "processing_failures_total": self._sum_counter("processing_failures_total"),
                    "llm_runs_total": self._sum_counter("llm_runs_total"),
                    "llm_failures_total": self._sum_counter("llm_failures_total"),
                    "state_changes_total": self._sum_counter("state_changes_total"),
                    "conflicts_total": self._sum_counter("conflicts_total"),
                    "agent_runs_total": self._sum_counter("agent_runs_total"),
                    "meet_subscription_created_total": self._sum_counter("meet_subscription_created_total"),
                    "meet_subscription_renewed_total": self._sum_counter("meet_subscription_renewed_total"),
                    "meet_events_received_total": self._sum_counter("meet_events_received_total"),
                    "meet_events_duplicate_total": self._sum_counter("meet_events_duplicate_total"),
                    "meet_transcript_persisted_total": self._sum_counter("meet_transcript_persisted_total"),
                    "meet_sync_failed_total": self._sum_counter("meet_sync_failed_total"),
                },
            }

    def reset_for_tests(self) -> None:
        """Reset registry state between test runs."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._timers.clear()
            self._start_time = time.time()


# Singleton operational metrics registry
metrics = MetricsRegistry()
