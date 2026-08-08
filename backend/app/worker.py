"""
Vigil AI — Async Task Worker (Self-Contained)
================================================
In-memory async scan task queue using Python's ThreadPoolExecutor.

No external dependencies required (no Redis, no Celery).
Works out of the box on any OS.

Architecture:
  - API receives scan request → returns task_id immediately
  - ThreadPoolExecutor runs the scan in a background thread
  - Client polls /api/scan/status/<task_id> for results
  - Results stored in-memory with TTL auto-cleanup (1 hour)

Thread Safety:
  - All task state mutations are protected by threading.Lock
  - Task store is a dict keyed by UUID task IDs
  - Stale results are purged every 60s by a daemon cleanup thread
"""

import uuid
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from app.core.logger import get_logger

_logger = get_logger('vigil.worker')

# ── Task States (same contract as previous Celery implementation) ─────────────
PENDING = 'PENDING'
SCANNING = 'SCANNING'
ANALYZING = 'ANALYZING'
CALIBRATING = 'CALIBRATING'
SUCCESS = 'SUCCESS'
FAILURE = 'FAILURE'


@dataclass
class TaskState:
    """In-memory representation of an async scan task."""
    task_id: str
    state: str = PENDING
    progress: int = 0
    stage: str = ''
    url: str = ''
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None


class AsyncTaskWorker:
    """
    Self-contained async task executor.

    Manages a thread pool and an in-memory task store.
    Provides the same state/progress contract as the previous
    Celery+Redis implementation, with zero external dependencies.
    """

    def __init__(self, max_workers: int = 4, result_ttl_seconds: int = 3600):
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix='vigil-scan',
        )
        self._tasks: Dict[str, TaskState] = {}
        self._lock = threading.Lock()
        self._result_ttl = result_ttl_seconds

        # Background cleanup thread — purges completed tasks older than TTL
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            daemon=True,
            name='vigil-task-cleanup',
        )
        self._cleanup_thread.start()
        _logger.info(
            f"AsyncTaskWorker initialized: max_workers={max_workers}, "
            f"result_ttl={result_ttl_seconds}s"
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def submit(self, url: str, cookies: list = None, scan_options: dict = None) -> str:
        """
        Submit a scan task for async execution.

        Returns the task_id immediately. The scan runs in a background thread.
        """
        task_id = str(uuid.uuid4())
        task = TaskState(task_id=task_id, url=url)

        with self._lock:
            self._tasks[task_id] = task

        self._executor.submit(self._run_scan, task_id, url, cookies or [], scan_options or {})
        _logger.info(f"[{task_id}] Async scan queued for {url}")
        return task_id

    def get_status(self, task_id: str) -> Optional[TaskState]:
        """Get the current state of a task. Returns None if task not found."""
        with self._lock:
            return self._tasks.get(task_id)

    def update_state(self, task_id: str, state: str, progress: int = 0,
                     stage: str = '', url: str = ''):
        """Update task state (called from within the scan thread)."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.state = state
                task.progress = progress
                task.stage = stage
                if url:
                    task.url = url

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run_scan(self, task_id: str, url: str, cookies: list, scan_options: dict):
        """
        Execute the full scan pipeline in a background thread.

        Mirrors the exact 5-phase flow from the previous Celery task:
          Phase 1: Browser scan (Playwright)
          Phase 2: Pipeline analysis (9 engines)
          Phase 3: HADE calibration
          Phase 4: Fusion + Aggregation
          Phase 5: Report generation + persistence
        """
        start = time.time()
        _logger.info(f"[{task_id}] Scan started for {url}")

        try:
            # Import here to avoid circular imports and keep worker lightweight
            from app.services.scanner import WebsiteScanner
            from app.analyzers.base import AnalysisContext
            from app.analyzers.adapters import create_default_analyzers
            from app.engine.pipeline import DetectionPipeline
            from app.engine.fusion import FusionEngine
            from app.engine.decision import RiskDecisionEngine
            from app.services.decision_engine import HarmAwareDecisionEngine
            from app.services.findings_aggregator import FindingsAggregator
            from app.services.behavioral_scorer import BehavioralScorer
            from app.services.report_generator import ReportGenerator
            from app.services.database import save_scan

            # ── Phase 1: Browser scan ────────────────────────────────────────
            self.update_state(task_id, SCANNING, progress=10,
                              stage='browser_scan', url=url)

            scanner = WebsiteScanner()
            scan_data = scanner.scan(url, session_cookies=cookies or None)

            if not scan_data or scan_data.get('status') == 'error':
                self._complete_with_error(
                    task_id, start,
                    scan_data.get('error', 'Scanner returned no data — site may be unreachable.'),
                    url,
                )
                return

            # ── Phase 2: Pipeline analysis ───────────────────────────────────
            self.update_state(task_id, ANALYZING, progress=40,
                              stage='pipeline_analysis', url=url)

            context = AnalysisContext(scan_data)
            pipeline = DetectionPipeline()
            pipeline.register_many(create_default_analyzers())
            pipeline_result = pipeline.process(context)

            # Behavioral scoring
            behavioral_scorer = BehavioralScorer()
            behavioral_findings = behavioral_scorer.analyze(
                pipeline_result.all_findings,
                scan_data.get('html_content', ''),
                scan_data.get('dom_data', {}),
            )
            for f in behavioral_findings:
                f['_engine'] = 'behavioral'

            dynamic = scan_data.get('dynamic_findings', [])
            for f in dynamic:
                f.setdefault('_engine', 'behavioral')

            # ── Phase 3: HADE calibration ────────────────────────────────────
            self.update_state(task_id, CALIBRATING, progress=70,
                              stage='hade_calibration', url=url)

            all_pre_hade = pipeline_result.all_findings + behavioral_findings + dynamic
            hade = HarmAwareDecisionEngine()
            all_hade_calibrated = hade.evaluate(all_pre_hade)
            hade_stats = hade.get_stats(all_pre_hade, all_hade_calibrated)

            # ── Phase 4: Fusion + Aggregation ────────────────────────────────
            fusion = FusionEngine()
            all_fused = fusion.fuse(all_hade_calibrated)

            aggregator = FindingsAggregator()
            all_findings_clean = aggregator.aggregate(
                all_fused,
                page_text=scan_data.get('text_content', ''),
            )

            # ── Phase 5: Report generation ───────────────────────────────────
            dom_clean = [f for f in all_findings_clean if f.get('_engine') == 'dom']
            text_clean = [f for f in all_findings_clean if f.get('_engine') == 'text']
            visual_clean = [f for f in all_findings_clean if f.get('_engine') == 'visual']
            advanced_clean = [f for f in all_findings_clean
                              if f.get('_engine') in ('advanced', 'cookie', 'link',
                                                       'readability', 'behavioral', 'ml')]

            report_gen = ReportGenerator()
            report = report_gen.generate_report(
                scan_data, dom_clean, text_clean, visual_clean, advanced_clean,
            )

            # Risk assessment
            risk_engine = RiskDecisionEngine()
            risk_assessment = risk_engine.assess(all_findings_clean)
            report['risk_assessment'] = risk_assessment.to_dict()

            # Enrich analysis breakdown
            report['analysis_breakdown'].update(pipeline_result.to_breakdown_dict())
            report['analysis_breakdown']['raw_findings'] = len(all_pre_hade)
            report['analysis_breakdown']['after_hade'] = len(all_hade_calibrated)
            report['analysis_breakdown']['after_fusion'] = len(all_fused)
            report['analysis_breakdown']['after_aggregation'] = len(all_findings_clean)
            report['analysis_breakdown']['dropped_by_hade'] = hade_stats['dropped_count']
            report['analysis_breakdown']['dropped_by_filter'] = len(all_hade_calibrated) - len(all_findings_clean)
            report['analysis_breakdown']['hade_critical_boosted'] = hade_stats['critical_count']
            report['analysis_breakdown']['hade_upgraded'] = hade_stats['upgraded_count']
            report['analysis_breakdown']['hade_downgraded'] = hade_stats['downgraded_count']
            report['analysis_breakdown']['behavioral_findings'] = len(behavioral_findings)
            report['analysis_breakdown']['fusion_scan_score'] = fusion.calculate_scan_fusion_score(all_fused)

            # Save to database
            save_scan(report)

            elapsed = round(time.time() - start, 2)
            report['scan_id'] = report.get('scan_id', task_id)
            report['async'] = True
            report['elapsed_seconds'] = elapsed

            _logger.info(
                f"[{task_id}] Async scan completed in {elapsed}s — "
                f"{report.get('total_patterns', 0)} patterns found"
            )

            # Mark SUCCESS
            with self._lock:
                task = self._tasks.get(task_id)
                if task:
                    task.state = SUCCESS
                    task.progress = 100
                    task.stage = 'complete'
                    task.result = report
                    task.completed_at = time.time()

        except Exception as e:
            elapsed = round(time.time() - start, 2)
            _logger.error(f"[{task_id}] Async scan failed after {elapsed}s: {e}")
            self._complete_with_error(task_id, start, f'Scan failed: {type(e).__name__}', url)

    def _complete_with_error(self, task_id: str, start: float, error: str, url: str):
        """Mark a task as failed with an error message."""
        elapsed = round(time.time() - start, 2)
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.state = FAILURE
                task.progress = 0
                task.error = error
                task.completed_at = time.time()
                task.result = {
                    'scan_id': task_id,
                    'status': 'error',
                    'error': error,
                    'url': url,
                    'elapsed_seconds': elapsed,
                }

    def _cleanup_loop(self):
        """Periodically purge completed tasks older than TTL."""
        while True:
            time.sleep(60)
            now = time.time()
            expired = []
            with self._lock:
                for tid, task in self._tasks.items():
                    if task.completed_at and (now - task.completed_at) > self._result_ttl:
                        expired.append(tid)
                for tid in expired:
                    del self._tasks[tid]
            if expired:
                _logger.info(f"Task cleanup: purged {len(expired)} expired task(s)")


# ── Module-level singleton ────────────────────────────────────────────────────
# Shared across the Flask application. Initialized once at import time.
task_worker = AsyncTaskWorker(max_workers=4, result_ttl_seconds=3600)
