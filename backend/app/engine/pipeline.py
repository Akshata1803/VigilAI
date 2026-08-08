"""
Vigil AI — Detection Pipeline Engine
=======================================
Orchestrates parallel analyzer execution using ThreadPoolExecutor.

BEFORE (scan.py):
    Sequential, ~8 analyzers run one-by-one = ~8× latency
    No error isolation: one crash kills the whole scan

AFTER (pipeline.py):
    Parallel execution with configurable worker pool
    Error-isolated: failed analyzers return empty results, others continue
    Automatic timing and metrics collection
    Configurable timeouts per analyzer

Pipeline Flow:
    [Input: AnalysisContext]
         |
    [Parallel Analyzer Pool]
    |-- DOMAnalyzer         -|
    |-- TextAnalyzer         |
    |-- VisualAnalyzer       |-- ThreadPoolExecutor
    |-- AdvancedAnalyzer     |
    |-- CookieAnalyzer       |
    |-- LinkAnalyzer         |
    |-- ReadabilityAnalyzer  |
    |-- MLAnalyzer          -|
         |
    [Merge Results]
         |
    [BehavioralScorer (compound detection)]
         |
    [SINGLE HADE Pass (all findings)]
         |
    [Fusion Engine]
         |
    [FindingsAggregator]
         |
    [Output: Clean Findings]
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from typing import Dict, List, Optional

from app.analyzers.base import BaseAnalyzer, AnalysisContext, AnalyzerResult
from app.core.config import Config
from app.core.logger import get_logger, set_correlation_id
from app.core.metrics import MetricsCollector
from app.core.exceptions import PipelineError


logger = get_logger('vigil.pipeline')


class DetectionPipeline:
    """
    Parallel analyzer orchestration engine.

    Usage:
        pipeline = DetectionPipeline()
        pipeline.register(DOMAnalyzerAdapter())
        pipeline.register(TextAnalyzerAdapter())
        ...
        results = pipeline.process(context)
    """

    def __init__(self, max_workers: Optional[int] = None, timeout: Optional[int] = None):
        self.analyzers: Dict[str, BaseAnalyzer] = {}
        self.max_workers = max_workers or Config.PIPELINE_MAX_WORKERS
        self.timeout = timeout or Config.PIPELINE_TIMEOUT_SECONDS
        self.metrics = MetricsCollector()

    def register(self, analyzer: BaseAnalyzer) -> 'DetectionPipeline':
        """Register an analyzer in the pipeline. Returns self for chaining."""
        self.analyzers[analyzer.name] = analyzer
        logger.info(f"Pipeline: registered analyzer '{analyzer.name}' (weight={analyzer.weight})")
        return self

    def register_many(self, analyzers: List[BaseAnalyzer]) -> 'DetectionPipeline':
        """Register multiple analyzers at once."""
        for a in analyzers:
            self.register(a)
        return self

    def process(self, context: AnalysisContext) -> 'PipelineResult':
        """
        Execute all registered analyzers in parallel and collect results.

        Args:
            context: AnalysisContext with all scan data

        Returns:
            PipelineResult containing all findings, timing info, and error details

        Never raises — PipelineResult.errors will contain any analyzer failures.
        """
        correlation_id = set_correlation_id()
        pipeline_start = time.perf_counter()

        logger.info(
            f"Pipeline START: {len(self.analyzers)} analyzers, "
            f"max_workers={self.max_workers}, timeout={self.timeout}s",
            extra={'scan_id': context.scan_id, 'url': context.url},
        )

        results: Dict[str, AnalyzerResult] = {}
        errors: Dict[str, str] = {}

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all analyzers concurrently
            future_to_name = {
                executor.submit(analyzer.run, context): name
                for name, analyzer in self.analyzers.items()
            }

            # Collect results as they complete (with timeout)
            try:
                for future in as_completed(future_to_name, timeout=self.timeout):
                    name = future_to_name[future]
                    try:
                        result = future.result(timeout=Config.ANALYZER_TIMEOUT_SECONDS)
                        results[name] = result
                        if result.error:
                            errors[name] = result.error
                    except TimeoutError:
                        error_msg = f"Analyzer '{name}' timed out after {Config.ANALYZER_TIMEOUT_SECONDS}s"
                        logger.error(error_msg)
                        errors[name] = error_msg
                        results[name] = AnalyzerResult(name, [], 0.0, error_msg)
                        self.metrics.record_error(name)
                    except Exception as e:
                        error_msg = f"Analyzer '{name}' crashed: {str(e)}"
                        logger.error(error_msg)
                        errors[name] = error_msg
                        results[name] = AnalyzerResult(name, [], 0.0, error_msg)
                        self.metrics.record_error(name)
            except TimeoutError:
                logger.warning(f"Pipeline globally timed out after {self.timeout}s")
                # Remaining pending missing analyzers are handled below

        # Handle missing analyzers (if as_completed timed out globally)
        for name in self.analyzers:
            if name not in results:
                error_msg = f"Analyzer '{name}' did not complete within pipeline timeout"
                errors[name] = error_msg
                results[name] = AnalyzerResult(name, [], 0.0, error_msg)

        # Build pipeline result
        pipeline_duration = (time.perf_counter() - pipeline_start) * 1000
        self.metrics.stop_timer('pipeline_total', pipeline_start)
        self.metrics.increment('scans_completed')

        pipeline_result = PipelineResult(
            results=results,
            errors=errors,
            total_duration_ms=pipeline_duration,
            correlation_id=correlation_id,
        )

        logger.info(
            f"Pipeline DONE: {pipeline_result.total_findings} findings from "
            f"{pipeline_result.successful_count}/{len(self.analyzers)} analyzers "
            f"in {pipeline_duration:.0f}ms "
            f"({pipeline_result.failed_count} errors)",
            extra={'scan_id': context.scan_id, 'duration_ms': round(pipeline_duration, 1)},
        )

        return pipeline_result


class PipelineResult:
    """Aggregated result from all analyzer executions."""

    def __init__(self, results: Dict[str, AnalyzerResult], errors: Dict[str, str],
                 total_duration_ms: float, correlation_id: str = ''):
        self.results = results
        self.errors = errors
        self.total_duration_ms = total_duration_ms
        self.correlation_id = correlation_id

    @property
    def all_findings(self) -> List[Dict]:
        """Flatten all findings from all analyzers into a single list."""
        findings = []
        for result in self.results.values():
            findings.extend(result.findings)
        return findings

    @property
    def findings_by_engine(self) -> Dict[str, List[Dict]]:
        """Group findings by engine name."""
        return {name: result.findings for name, result in self.results.items()}

    @property
    def total_findings(self) -> int:
        return sum(r.count for r in self.results.values())

    @property
    def successful_count(self) -> int:
        return sum(1 for r in self.results.values() if r.success)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results.values() if not r.success)

    @property
    def timing_breakdown(self) -> Dict[str, float]:
        """Per-analyzer timing in ms."""
        return {name: round(r.duration_ms, 1) for name, r in self.results.items()}

    def get_findings_for(self, engine_name: str) -> List[Dict]:
        """Get findings for a specific engine."""
        result = self.results.get(engine_name)
        return result.findings if result else []

    def to_breakdown_dict(self) -> Dict:
        """Generate analysis breakdown for the report."""
        breakdown = {}
        for name, result in self.results.items():
            breakdown[f'{name}_findings'] = result.count
            breakdown[f'{name}_time_ms'] = round(result.duration_ms, 1)
            if result.error:
                breakdown[f'{name}_error'] = result.error
        breakdown['pipeline_total_ms'] = round(self.total_duration_ms, 1)
        breakdown['analyzers_total'] = len(self.results)
        breakdown['analyzers_succeeded'] = self.successful_count
        breakdown['analyzers_failed'] = self.failed_count
        return breakdown

    def __repr__(self):
        return (
            f'<PipelineResult: {self.total_findings} findings, '
            f'{self.successful_count}/{len(self.results)} OK, '
            f'{self.total_duration_ms:.0f}ms>'
        )
