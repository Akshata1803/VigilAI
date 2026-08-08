"""
Vigil AI — PRODUCTION Scan Routes (v3.0)
==========================================
Full production hardening:
  - API key authentication
  - Strict input validation + payload size limits
  - TTL result caching (5-min, configurable)
  - Parallel analyzer execution
  - Graceful error handling
  - Health, readiness, and metrics endpoints
  - No information leakage in error responses
"""

import json
import time
import threading
import traceback

from flask import Blueprint, request, jsonify, current_app, Response

# ── Core New Architecture ─────────────────────────────────────────────────────
from app.analyzers.base import AnalysisContext
from app.analyzers.adapters import create_default_analyzers
from app.engine.pipeline import DetectionPipeline
from app.engine.fusion import FusionEngine
from app.engine.decision import RiskDecisionEngine
from app.engine.temporal import TemporalSmoother
from app.core.config import Config
from app.core.logger import get_logger, set_correlation_id
from app.core.metrics import MetricsCollector
from app.core.exceptions import ScanError
from app.core.auth import require_api_key, AUTH_ENABLED
from app.core.cache import get_cached, set_cached, cache_stats, invalidate
from app.core.validation import validate_scan_request, sanitize_url

# ── Existing Services ─────────────────────────────────────────────────────────
from app.services.scanner import WebsiteScanner
from app.services.decision_engine import HarmAwareDecisionEngine
from app.services.findings_aggregator import FindingsAggregator
from app.services.behavioral_scorer import BehavioralScorer
from app.services.report_generator import ReportGenerator
from app.services.database import save_scan, get_history, get_scan, get_stats, get_category_counts
from app.services.ml_analyzer import MLAnalyzer

from app.extensions import limiter

logger = get_logger('vigil.routes.scan')
scan_bp = Blueprint('scan', __name__)

# ── Singletons (initialized once, reused across requests) ─────────────────────
_pipeline: DetectionPipeline = None
_pipeline_lock = threading.Lock()
_temporal = TemporalSmoother()
_fusion = FusionEngine()
_risk_engine = RiskDecisionEngine()
_metrics = MetricsCollector()

# Warm the ML model in background at startup
MLAnalyzer.preload()


def _get_pipeline() -> DetectionPipeline:
    """Lazy-initialize the detection pipeline (double-checked locking)."""
    global _pipeline
    if _pipeline is not None:
        return _pipeline
    with _pipeline_lock:
        if _pipeline is not None:
            return _pipeline
        _pipeline = DetectionPipeline()
        _pipeline.register_many(create_default_analyzers())
        logger.info("Detection pipeline initialized with all analyzers")
    return _pipeline


# ═══════════════════════════════════════════════════════════════════════════════
# HEALTH / READINESS / METRICS
# ═══════════════════════════════════════════════════════════════════════════════

@scan_bp.route('/health', methods=['GET'])
def health_check():
    """Liveness probe — always returns 200 if process is alive."""
    return jsonify({'status': 'healthy', 'timestamp': time.time()}), 200


@scan_bp.route('/ready', methods=['GET'])
def readiness_check():
    """Readiness probe — checks DB and ML model are initialized."""
    checks = {}
    ok = True

    # Check ML model
    checks['ml_model'] = 'loaded' if MLAnalyzer._model_loaded else 'loading'

    # Check DB (lazy pool initializes on first use, just try a query)
    try:
        from app.services.database import get_stats
        get_stats()
        checks['database'] = 'ok'
    except Exception as e:
        checks['database'] = f'error: {str(e)}'
        ok = False

    # Check pipeline
    checks['pipeline'] = 'ready' if _pipeline is not None else 'not_initialized'

    status = 200 if ok else 503
    return jsonify({'ready': ok, 'checks': checks, 'timestamp': time.time()}), status


@scan_bp.route('/metrics', methods=['GET'])
@require_api_key
def metrics():
    """Internal metrics endpoint — requires API key."""
    return jsonify({
        'metrics': _metrics.get_summary(),
        'cache': cache_stats(),
        'auth_enabled': AUTH_ENABLED,
        'timestamp': time.time(),
    }), 200


# ═══════════════════════════════════════════════════════════════════════════════
# FULL SCAN
# ═══════════════════════════════════════════════════════════════════════════════

@scan_bp.route('/scan', methods=['POST'])
@require_api_key
@limiter.limit("5 per minute; 50 per hour")
def scan_website():
    """
    Production scan: strict validation → cache check → parallel analyzers
    → HADE → fusion → temporal smoothing → report.

    Security:
      - API key required (if VIGIL_API_KEY is set)
      - Payload size validated
      - URL validated and sanitized
      - Errors returned without stack traces
    """
    correlation_id = set_correlation_id()
    scan_start = time.perf_counter()

    # ── Payload size guard (32KB max) ────────────────────────────────────
    if request.content_length and request.content_length > 32 * 1024:
        return jsonify({'error': 'Request payload too large (max 32KB)', 'status': 'error'}), 413

    data = request.get_json(silent=True) or {}

    # ── Strict input validation ──────────────────────────────────────────
    valid, err = validate_scan_request(data)
    if not valid:
        return jsonify({'error': err, 'status': 'error'}), 400

    url = sanitize_url(data['url'])
    session_cookies = data.get('cookies')
    local_storage = data.get('local_storage')
    force_refresh = data.get('force_refresh', False)

    # ── Cache check ──────────────────────────────────────────────────────
    if not force_refresh and not session_cookies:
        cached = get_cached(url)
        if cached:
            cached['_cached'] = True
            cached['_cache_hit'] = True
            logger.info(f"Cache HIT for {url}")
            return jsonify(cached), 200

    try:
        # ── STEP 1: Fetch & Parse ────────────────────────────────────────
        screenshot_dir = current_app.config.get('SCREENSHOT_DIR', 'static/screenshots')
        logger.info(f"Scan initiated for {url}", extra={'url': url, 'scan_id': correlation_id})

        with _metrics.timer('scanner'):
            scanner = WebsiteScanner(screenshot_dir=screenshot_dir)
            scan_data = scanner.scan(url, session_cookies=session_cookies,
                                     local_storage=local_storage)

        if scan_data.get('status') == 'error':
            logger.warning(f"Scan fetch failed for {url}: {scan_data.get('error')}")
            return jsonify({
                'error': f"Could not reach website: {scan_data.get('error')}",
                'tip': 'Check the URL and ensure the site is publicly accessible.',
                'status': 'error',
            }), 400

        # ── STEP 2: Build analysis context ──────────────────────────────
        context = AnalysisContext(scan_data)

        # ── STEP 3: Parallel analyzer execution ─────────────────────────
        pipeline = _get_pipeline()
        with _metrics.timer('pipeline_execution'):
            pipeline_result = pipeline.process(context)

        # ── STEP 4: Behavioral compound scoring (pre-HADE) ───────────────
        # Run behavioral scorer on RAW pipeline findings to detect compound patterns.
        # HADE will then calibrate ALL findings (pipeline + behavioral + dynamic) in ONE pass.
        with _metrics.timer('behavioral_scorer'):
            behavioral_scorer = BehavioralScorer()
            behavioral_findings = behavioral_scorer.analyze(
                pipeline_result.all_findings,
                scan_data['html_content'],
                scan_data['dom_data'],
            )
            for f in behavioral_findings:
                f['_engine'] = 'behavioral'

        # Collect dynamic findings from scanner
        dynamic = scan_data.get('dynamic_findings', [])
        for f in dynamic:
            f.setdefault('_engine', 'behavioral')

        # ── STEP 5: SINGLE HADE pass on ALL findings ─────────────────────
        # FIX C-4: Previously ran HADE twice (on pipeline, then on behavioral+dynamic).
        # This caused inconsistent stats and double-processing.
        # Now: merge everything FIRST, then run HADE ONCE.
        all_pre_hade = pipeline_result.all_findings + behavioral_findings + dynamic
        hade = HarmAwareDecisionEngine()
        with _metrics.timer('hade_calibration'):
            all_hade_calibrated = hade.evaluate(all_pre_hade)
        hade_stats = hade.get_stats(all_pre_hade, all_hade_calibrated)

        # ── STEP 6: Fusion engine ─────────────────────────────────────────
        with _metrics.timer('fusion'):
            all_fused = _fusion.fuse(all_hade_calibrated)

        # ── STEP 7: Aggregation (consensus + dedup) ───────────────────────
        with _metrics.timer('aggregation'):
            aggregator = FindingsAggregator()
            all_findings_clean = aggregator.aggregate(
                all_fused,
                page_text=scan_data.get('text_content', ''),
            )

        # ── STEP 8: Generate report ───────────────────────────────────────
        dom_clean      = [f for f in all_findings_clean if f.get('_engine') == 'dom']
        text_clean     = [f for f in all_findings_clean if f.get('_engine') == 'text']
        visual_clean   = [f for f in all_findings_clean if f.get('_engine') == 'visual']
        advanced_clean = [f for f in all_findings_clean
                          if f.get('_engine') in ('advanced', 'cookie', 'link',
                                                   'readability', 'behavioral', 'ml')]

        report_gen = ReportGenerator()
        report = report_gen.generate_report(
            scan_data, dom_clean, text_clean, visual_clean, advanced_clean,
        )

        # ── STEP 9: Temporal smoothing ────────────────────────────────────
        domain = scan_data.get('domain', '')
        smoothed_score = _temporal.smooth_trust_score(domain, report['trust_score'])
        if smoothed_score != report['trust_score']:
            report['trust_score_raw'] = report['trust_score']
            report['trust_score'] = smoothed_score
            report['grade'] = report_gen._get_grade(smoothed_score)
            report['risk_level'] = report_gen._get_risk_level(smoothed_score)
        _temporal.record(domain, report['trust_score'], all_findings_clean)

        # ── STEP 10: Risk assessment ──────────────────────────────────────
        risk_assessment = _risk_engine.assess(all_findings_clean)
        report['risk_assessment'] = risk_assessment.to_dict()

        # ── STEP 11: Enrich analysis breakdown ────────────────────────────
        report['analysis_breakdown'].update(pipeline_result.to_breakdown_dict())
        report['analysis_breakdown']['raw_findings']         = len(all_pre_hade)
        report['analysis_breakdown']['after_hade']           = len(all_hade_calibrated)
        report['analysis_breakdown']['after_fusion']         = len(all_fused)
        report['analysis_breakdown']['after_aggregation']    = len(all_findings_clean)
        report['analysis_breakdown']['dropped_by_hade']      = hade_stats['dropped_count']
        report['analysis_breakdown']['dropped_by_filter']    = len(all_hade_calibrated) - len(all_findings_clean)
        report['analysis_breakdown']['hade_critical_boosted']= hade_stats['critical_count']
        report['analysis_breakdown']['hade_upgraded']        = hade_stats['upgraded_count']
        report['analysis_breakdown']['hade_downgraded']      = hade_stats['downgraded_count']
        report['analysis_breakdown']['behavioral_findings']  = len(behavioral_findings)
        report['analysis_breakdown']['fusion_scan_score']    = _fusion.calculate_scan_fusion_score(all_fused)

        # Performance metrics
        total_scan_ms = (time.perf_counter() - scan_start) * 1000
        report['performance'] = {
            'total_ms':       round(total_scan_ms, 1),
            'pipeline_ms':    round(pipeline_result.total_duration_ms, 1),
            'analyzer_timings': pipeline_result.timing_breakdown,
            'correlation_id': correlation_id,
        }

        # Temporal trend
        trend = _temporal.get_trend(domain)
        if trend:
            report['temporal_trend'] = trend

        # ── STEP 13: Persist ──────────────────────────────────────────────
        save_scan(report)

        # ── STEP 14: Cache result (only for non-authenticated scans) ──────
        if not session_cookies:
            set_cached(url, report)

        logger.info(
            f"Scan COMPLETE: {url} → score={report['trust_score']}, "
            f"findings={report['total_patterns']}, time={total_scan_ms:.0f}ms",
            extra={'scan_id': report['scan_id'], 'url': url,
                   'duration_ms': round(total_scan_ms, 1)},
        )

        return jsonify(report)

    except Exception as e:
        logger.error(
            f"Pipeline failure on {url}: {type(e).__name__}: {str(e)[:200]}",
            extra={'url': url},
        )
        # Never leak stack traces to API consumers
        return jsonify({
            'error': 'Scan failed due to an internal error.',
            'status': 'error',
            'request_id': correlation_id,
            'retryable': not isinstance(e, ScanError) or getattr(e, 'retryable', True),
        }), 500


# ═══════════════════════════════════════════════════════════════════════════════
# QUICK SCAN — Lightweight, cookie + DOM only
# ═══════════════════════════════════════════════════════════════════════════════

@scan_bp.route('/scan/quick', methods=['POST'])
@require_api_key
@limiter.limit("10 per minute; 100 per hour")
def quick_scan():
    """
    Lightweight scan using only DOM + Cookie + Advanced analyzers.
    Returns in ~5-10s vs 45-50s for full scan.
    """
    correlation_id = set_correlation_id()

    if request.content_length and request.content_length > 32 * 1024:
        return jsonify({'error': 'Request payload too large', 'status': 'error'}), 413

    data = request.get_json(silent=True) or {}
    valid, err = validate_scan_request(data)
    if not valid:
        return jsonify({'error': err, 'status': 'error'}), 400

    url = sanitize_url(data['url'])

    try:
        screenshot_dir = current_app.config.get('SCREENSHOT_DIR', 'static/screenshots')
        scanner = WebsiteScanner(screenshot_dir=screenshot_dir)
        scan_data = scanner.scan(url)

        if scan_data.get('status') == 'error':
            return jsonify({'error': scan_data.get('error', 'Scan failed'), 'status': 'error'}), 400

        context = AnalysisContext(scan_data)

        from app.analyzers.adapters import (
            DOMAnalyzerAdapter, CookieAnalyzerAdapter, AdvancedAnalyzerAdapter
        )
        quick_pipeline = DetectionPipeline(max_workers=3, timeout=20)
        quick_pipeline.register_many([
            DOMAnalyzerAdapter(),
            CookieAnalyzerAdapter(),
            AdvancedAnalyzerAdapter(),
        ])
        result = quick_pipeline.process(context)

        hade = HarmAwareDecisionEngine()
        calibrated = hade.evaluate(result.all_findings)

        # FIX D-1: Quick scan was skipping FusionEngine — breaks _fusion_score metadata
        fused = _fusion.fuse(calibrated)

        aggregator = FindingsAggregator()
        clean = aggregator.aggregate(fused, page_text=scan_data.get('text_content', ''))

        return jsonify({
            'scan_id':       scan_data.get('scan_id'),
            'url':           url,
            'domain':        scan_data.get('domain'),
            'findings':      clean,
            'total_patterns': len(clean),
            'scan_type':     'quick',
            'analyzers_used': ['dom', 'cookie', 'advanced'],
            'status':        'success',
        })

    except Exception as e:
        logger.error(f"Quick scan failure on {url}: {type(e).__name__}: {str(e)[:200]}")
        return jsonify({'error': 'Quick scan failed.', 'status': 'error'}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# SCAN METRICS / HISTORY / DB ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@scan_bp.route('/scan/metrics', methods=['GET'])
@require_api_key
def scan_metrics():
    """Return pipeline performance metrics (requires API key)."""
    return jsonify({
        'pipeline_metrics': _metrics.get_summary(),
        'cache': cache_stats(),
        'timestamp': time.time(),
    })


@scan_bp.route('/history', methods=['GET'])
def scan_history():
    page  = max(1, int(request.args.get('page', 1)))
    limit = min(50, max(1, int(request.args.get('limit', 10))))
    try:
        history = get_history(page=page, limit=limit)
        return jsonify(history)
    except Exception as e:
        logger.error(f"History retrieval failed: {e}")
        return jsonify({'error': 'Could not retrieve history.', 'status': 'error'}), 500


@scan_bp.route('/scan/<scan_id>', methods=['GET'])
def get_scan_by_id(scan_id: str):
    if not scan_id or len(scan_id) > 64:
        return jsonify({'error': 'Invalid scan ID.', 'status': 'error'}), 400
    try:
        result = get_scan(scan_id)
        if not result:
            return jsonify({'error': 'Scan not found.', 'status': 'error'}), 404
        return jsonify(result)
    except Exception as e:
        logger.error(f"Scan retrieval failed for {scan_id}: {e}")
        return jsonify({'error': 'Could not retrieve scan.', 'status': 'error'}), 500


@scan_bp.route('/stats', methods=['GET'])
def scan_stats():
    try:
        stats = get_stats()
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Stats retrieval failed: {e}")
        return jsonify({'error': 'Could not retrieve stats.', 'status': 'error'}), 500


@scan_bp.route('/categories', methods=['GET'])
def category_counts():
    try:
        counts = get_category_counts()
        return jsonify(counts)
    except Exception as e:
        logger.error(f"Category retrieval failed: {e}")
        return jsonify({'error': 'Could not retrieve category data.', 'status': 'error'}), 500


@scan_bp.route('/scan/cache/invalidate', methods=['POST'])
@require_api_key
def invalidate_cache():
    """Manually invalidate cache entry for a URL."""
    data = request.get_json(silent=True) or {}
    url = data.get('url', '').strip()
    if not url:
        return jsonify({'error': 'URL required.', 'status': 'error'}), 400
    invalidate(url)
    return jsonify({'status': 'ok', 'invalidated': url})


# ═══════════════════════════════════════════════════════════════════════════════
# ASYNC SCAN ENDPOINTS (Self-Contained ThreadPool — No External Dependencies)
# ═══════════════════════════════════════════════════════════════════════════════

@scan_bp.route('/scan/async', methods=['POST'])
@require_api_key
def scan_async():
    """
    Submit a scan to the async task queue.

    Returns immediately with a task_id for polling.
    Uses an in-memory ThreadPoolExecutor — no Redis/Celery required.

    Response:
        {
            "status": "queued",
            "task_id": "<uuid>",
            "poll_url": "/api/scan/status/<task_id>"
        }
    """
    data = request.get_json(silent=True) or {}

    ok, err = validate_scan_request(data)
    if not ok:
        return jsonify({'error': err, 'status': 'error'}), 400

    url = sanitize_url(data['url'])
    cookies = data.get('cookies', [])

    try:
        from app.tasks import scan_website_task
        task_id = scan_website_task(url=url, cookies=cookies)
        logger.info(f"Async scan queued: task_id={task_id}, url={url}")
        return jsonify({
            'status': 'queued',
            'task_id': task_id,
            'poll_url': f'/api/scan/status/{task_id}',
            'url': url,
        }), 202

    except Exception as e:
        logger.error(f"Failed to queue async scan: {e}")
        return jsonify({
            'error': 'Async task queue error.',
            'status': 'error',
            'fallback': 'Use POST /api/scan for synchronous scanning.',
        }), 503


@scan_bp.route('/scan/status/<task_id>', methods=['GET'])
def scan_status(task_id):
    """
    Poll the status of an async scan task.

    States:
      - PENDING:     Task queued, not yet picked up by a worker
      - SCANNING:    Playwright browser scan in progress
      - ANALYZING:   Pipeline analysis running
      - CALIBRATING: HADE + Fusion calibration
      - SUCCESS:     Complete — result available
      - FAILURE:     Task crashed
    """
    # Validate task_id format (UUID)
    import re
    if not re.match(r'^[a-f0-9\-]{36}$', task_id):
        return jsonify({'error': 'Invalid task ID format.', 'status': 'error'}), 400

    try:
        from app.tasks import get_task_status
        status = get_task_status(task_id)

        if status is None:
            return jsonify({
                'task_id': task_id,
                'state': 'PENDING',
                'progress': 0,
                'message': 'Task not found or expired.',
            }), 404

        response = {
            'task_id': task_id,
            'state': status['state'],
        }

        if status['state'] == 'PENDING':
            response['progress'] = 0
            response['message'] = 'Scan queued — waiting for available worker.'

        elif status['state'] in ('SCANNING', 'ANALYZING', 'CALIBRATING'):
            response['progress'] = status.get('progress', 0)
            response['stage'] = status.get('stage', 'unknown')
            response['url'] = status.get('url', '')

        elif status['state'] == 'SUCCESS':
            response['progress'] = 100
            response['result'] = status.get('result')

        elif status['state'] == 'FAILURE':
            response['progress'] = 0
            response['error'] = status.get('error', 'Unknown error')

        return jsonify(response)

    except Exception as e:
        logger.error(f"Status check failed for task {task_id}: {e}")
        return jsonify({
            'error': 'Could not retrieve task status.',
            'status': 'error',
        }), 500

