"""
Vigil AI — Abstract Base Analyzer
===================================
All analyzers MUST inherit from BaseAnalyzer and implement the `execute()` method.

Provides:
  - Unified `.run()` contract with automatic timing, error handling, metrics
  - Built-in confidence scoring framework
  - Graceful degradation on failure (returns empty findings, not crash)
  - Automatic engine tagging of findings
  - Retry logic for transient failures

This replaces the scattered, inconsistent analyzer interfaces throughout the codebase.
"""

import time
import traceback
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from app.core.logger import get_logger
from app.core.metrics import MetricsCollector
from app.core.exceptions import AnalyzerError


class BaseAnalyzer(ABC):
    """
    Abstract base class for all detection analyzers.

    Subclasses implement `execute()` which receives the analysis context
    and returns a list of finding dicts.

    The public `.run()` method wraps `execute()` with:
      - Automatic timing and metrics
      - Error boundary (never crashes the pipeline)
      - Engine tagging on all findings
      - Structured logging

    Usage:
        class DOMAnalyzer(BaseAnalyzer):
            name = 'dom'

            def execute(self, context: AnalysisContext) -> List[Dict]:
                findings = []
                # ... detection logic ...
                return findings

        analyzer = DOMAnalyzer()
        result = analyzer.run(context)
    """

    # Subclasses MUST set this
    name: str = 'unknown'

    # Default weight in fusion engine (overridable per-analyzer)
    weight: float = 1.0

    # Maximum retries on transient failure
    max_retries: int = 1

    def __init__(self):
        self.logger = get_logger(f'vigil.analyzer.{self.name}')
        self.metrics = MetricsCollector()
        self._last_run_ms: float = 0.0
        self._last_findings_count: int = 0

    def run(self, context: 'AnalysisContext') -> 'AnalyzerResult':
        """
        Public entry point. Wraps execute() with timing, error handling, and metrics.

        Returns an AnalyzerResult containing findings and metadata.
        NEVER raises — returns empty result on failure.
        """
        start = time.perf_counter()
        findings: List[Dict] = []
        error: Optional[str] = None
        retries = 0

        while retries <= self.max_retries:
            try:
                findings = self.execute(context)
                break  # Success
            except Exception as e:
                retries += 1
                error = str(e)
                if retries <= self.max_retries:
                    self.logger.warning(
                        f"Analyzer {self.name} failed (attempt {retries}/{self.max_retries + 1}): {e}"
                    )
                    time.sleep(0.1 * retries)  # Brief backoff
                else:
                    self.logger.error(
                        f"Analyzer {self.name} FAILED after {retries} attempts: {e}\n"
                        f"{traceback.format_exc()[-300:]}"
                    )
                    self.metrics.record_error(self.name)

        # Tag all findings with engine source
        for f in findings:
            f['_engine'] = self.name

        # Record metrics
        duration_ms = (time.perf_counter() - start) * 1000
        self._last_run_ms = duration_ms
        self._last_findings_count = len(findings)
        self.metrics.stop_timer(f'analyzer_{self.name}', start)
        self.metrics.increment(f'findings_{self.name}', len(findings))

        if findings:
            self.logger.info(
                f"{self.name}: {len(findings)} finding(s) in {duration_ms:.0f}ms",
                extra={'analyzer': self.name, 'duration_ms': round(duration_ms, 1),
                       'findings_count': len(findings)},
            )

        return AnalyzerResult(
            analyzer_name=self.name,
            findings=findings,
            duration_ms=duration_ms,
            error=error,
        )

    @abstractmethod
    def execute(self, context: 'AnalysisContext') -> List[Dict]:
        """
        Implement detection logic here.

        Args:
            context: AnalysisContext containing all scan data

        Returns:
            List of finding dicts with keys:
              type, category, severity, confidence, signal_strength,
              description, evidence, element, recommendation, legal_refs
        """
        raise NotImplementedError

    # ── Helper: Confidence scoring ─────────────────────────────────────────────

    @staticmethod
    def calculate_confidence(signals: List[float], weights: Optional[List[float]] = None) -> float:
        """
        Calculate weighted confidence score from multiple signal strengths.

        Args:
            signals: List of signal values (0.0 to 1.0)
            weights: Optional weights per signal (default: equal)

        Returns:
            Confidence score clamped to [0.0, 1.0]
        """
        if not signals:
            return 0.0

        if weights is None:
            weights = [1.0] * len(signals)

        total_weight = sum(weights)
        if total_weight == 0:
            return 0.0

        weighted_sum = sum(s * w for s, w in zip(signals, weights))
        score = weighted_sum / total_weight
        return max(0.0, min(1.0, round(score, 3)))


class AnalysisContext:
    """
    Data bag passed to all analyzers.
    Contains everything an analyzer needs — no reaching back into scanner/routes.
    Note: No __slots__ — allows dynamic attrs like _verified_findings (FIX M-1).
    """

    def __init__(self, scan_data: Dict):
        self.scan_id = scan_data.get('scan_id', '')
        self.url = scan_data.get('url', '')
        self.domain = scan_data.get('domain', '')
        self.html_content = scan_data.get('html_content', '')
        self.text_content = scan_data.get('text_content', '')
        self.dom_data = scan_data.get('dom_data', {})
        self.screenshot_path = scan_data.get('screenshot_path')
        self.page_title = scan_data.get('page_title', '')
        self.scan_state = scan_data.get('scan_state', 'unknown')
        self.dynamic_findings = scan_data.get('dynamic_findings', [])
        self.session_cookies = scan_data.get('session_cookies')

    def to_dict(self) -> Dict:
        # CQ-2 FIX: No __slots__ on this class — use __dict__
        return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}


class AnalyzerResult:
    """Result from a single analyzer run."""

    __slots__ = ('analyzer_name', 'findings', 'duration_ms', 'error')

    def __init__(self, analyzer_name: str, findings: List[Dict],
                 duration_ms: float, error: Optional[str] = None):
        self.analyzer_name = analyzer_name
        self.findings = findings
        self.duration_ms = duration_ms
        self.error = error

    @property
    def success(self) -> bool:
        return self.error is None

    @property
    def count(self) -> int:
        return len(self.findings)

    def __repr__(self):
        status = 'OK' if self.success else f'ERR: {self.error[:50]}'
        return f'<AnalyzerResult {self.analyzer_name}: {self.count} findings, {self.duration_ms:.0f}ms [{status}]>'
