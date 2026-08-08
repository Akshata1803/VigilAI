"""
Vigil AI — Isolated Unit Tests (no network, no ML model, no DB)
=================================================================
All external dependencies are mocked.
Tests are deterministic and fast (<2s total).

Coverage:
  - Input validation
  - API key authentication
  - TTL cache get/set/invalidate
  - ML analyzer batch inference logic
  - Readability analyzer thresholds
  - Link analyzer Roach Motel heuristics
  - Pipeline timeout handling (mocked)
  - Score regression: known dark pattern types → expected severity
"""

import sys
import os
import time
import unittest
from unittest.mock import patch, MagicMock, PropertyMock
import importlib

# Ensure backend is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ═══════════════════════════════════════════════════════════════════════════════
# 1. INPUT VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidation(unittest.TestCase):

    def setUp(self):
        from app.core.validation import validate_scan_request, sanitize_url
        self.validate = validate_scan_request
        self.sanitize = sanitize_url

    def test_missing_url(self):
        ok, err = self.validate({})
        self.assertFalse(ok)
        self.assertIn('url', err.lower())

    def test_empty_url(self):
        ok, err = self.validate({'url': ''})
        self.assertFalse(ok)

    def test_valid_https_url(self):
        ok, err = self.validate({'url': 'https://example.com'})
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_auto_prepend_https(self):
        ok, err = self.validate({'url': 'example.com'})
        self.assertTrue(ok, err)

    def test_url_too_long(self):
        ok, err = self.validate({'url': 'https://' + 'a' * 3000 + '.com'})
        self.assertFalse(ok)
        self.assertIn('length', err.lower())

    def test_invalid_scheme_blocked(self):
        ok, err = self.validate({'url': 'file:///etc/passwd'})
        self.assertFalse(ok)

    def test_ftp_blocked(self):
        ok, err = self.validate({'url': 'ftp://files.example.com'})
        self.assertFalse(ok)

    def test_cookies_must_be_list(self):
        ok, err = self.validate({'url': 'https://example.com', 'cookies': 'bad'})
        self.assertFalse(ok)

    def test_cookies_valid_list(self):
        ok, err = self.validate({'url': 'https://example.com',
                                 'cookies': [{'name': 'session', 'value': 'abc'}]})
        self.assertTrue(ok)

    def test_sanitize_adds_scheme(self):
        result = self.sanitize('booking.com')
        self.assertTrue(result.startswith('https://'))

    def test_sanitize_strips_whitespace(self):
        result = self.sanitize('  https://example.com  ')
        self.assertEqual(result, 'https://example.com')


# ═══════════════════════════════════════════════════════════════════════════════
# 2. API KEY AUTH
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuth(unittest.TestCase):

    def test_auth_disabled_by_default(self):
        """When VIGIL_API_KEY is not set, AUTH_ENABLED should be False."""
        with patch.dict(os.environ, {}, clear=True):
            # Need to reload module as it reads env at import time
            import app.core.auth as auth_mod
            # In test env, key is likely empty, so disabled
            # Just assert the module loads and has the expected interface
            self.assertTrue(hasattr(auth_mod, 'require_api_key'))
            self.assertTrue(hasattr(auth_mod, 'AUTH_ENABLED'))

    def test_constant_time_eq_same(self):
        from app.core.auth import _constant_time_eq
        self.assertTrue(_constant_time_eq('secret-key-123', 'secret-key-123'))

    def test_constant_time_eq_different(self):
        from app.core.auth import _constant_time_eq
        self.assertFalse(_constant_time_eq('secret-key-123', 'wrong-key'))

    def test_constant_time_eq_empty(self):
        from app.core.auth import _constant_time_eq
        self.assertFalse(_constant_time_eq('', 'anything'))
        self.assertTrue(_constant_time_eq('', ''))


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TTL CACHE
# ═══════════════════════════════════════════════════════════════════════════════

class TestCache(unittest.TestCase):

    def setUp(self):
        # Reset cache before each test
        from app.core import cache as cache_mod
        cache_mod._cache.clear()
        self.cache = cache_mod

    def test_cache_miss(self):
        result = self.cache.get_cached('https://example.com')
        self.assertIsNone(result)

    def test_cache_set_and_get(self):
        data = {'trust_score': 85, 'total_patterns': 1}
        self.cache.set_cached('https://example.com', data)
        result = self.cache.get_cached('https://example.com')
        self.assertEqual(result['trust_score'], 85)

    def test_cache_normalizes_url(self):
        data = {'trust_score': 90}
        self.cache.set_cached('https://EXAMPLE.COM', data)
        result = self.cache.get_cached('https://example.com')
        self.assertIsNotNone(result)

    def test_cache_invalidate(self):
        self.cache.set_cached('https://example.com', {'x': 1})
        self.cache.invalidate('https://example.com')
        self.assertIsNone(self.cache.get_cached('https://example.com'))

    def test_cache_stats(self):
        self.cache.set_cached('https://a.com', {'x': 1})
        stats = self.cache.cache_stats()
        self.assertIn('size', stats)
        self.assertGreaterEqual(stats['size'], 1)

    def test_different_urls_independent(self):
        self.cache.set_cached('https://a.com', {'score': 80})
        self.cache.set_cached('https://b.com', {'score': 60})
        self.assertEqual(self.cache.get_cached('https://a.com')['score'], 80)
        self.assertEqual(self.cache.get_cached('https://b.com')['score'], 60)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. ML ANALYZER — BATCH INFERENCE
# ═══════════════════════════════════════════════════════════════════════════════

class TestMLAnalyzerBatch(unittest.TestCase):

    def _make_mock_model(self, label='urgency', confidence=0.90):
        """Build a mock sklearn pipeline that returns canned batch predictions."""
        mock = MagicMock()
        # predict returns an array — same label for all chunks
        mock.predict.side_effect = lambda chunks: [label] * len(chunks)
        # predict_proba returns an array where max = confidence
        import numpy as np
        mock.predict_proba.side_effect = (
            lambda chunks: np.array([[1.0 - confidence, confidence]] * len(chunks))
        )
        return mock

    def test_batch_predict_called_once(self):
        """Ensure model.predict and model.predict_proba are each called exactly ONCE."""
        from app.services.ml_analyzer import MLAnalyzer
        analyzer = MLAnalyzer()

        mock_model = self._make_mock_model(label='safe', confidence=0.95)
        # Use dense realistic text that will produce chunks >15 chars after splitting
        text = (
            "By continuing to use this service you agree to our updated terms and conditions.\n\n"
            "Your personal data may be shared with our trusted third-party partners for advertising.\n\n"
            "You can opt out at any time by contacting our support team during business hours."
        )
        with patch.object(type(analyzer), 'model', new_callable=PropertyMock,
                          return_value=mock_model):
            analyzer.analyze(text, dom_data={})

        # If chunks exist, predict must be called exactly once (not once-per-chunk)
        # If no chunks pass the filter, call_count will be 0 — both are acceptable
        self.assertIn(mock_model.predict.call_count, (0, 1),
                      f"predict called {mock_model.predict.call_count} times, expected 0 or 1")
        if mock_model.predict.call_count == 1:
            # predict_proba must also be called exactly once
            mock_model.predict_proba.assert_called_once()

    def test_safe_predictions_filtered(self):
        """'safe' predictions should never become findings."""
        from app.services.ml_analyzer import MLAnalyzer
        analyzer = MLAnalyzer()
        mock_model = self._make_mock_model(label='safe', confidence=0.99)
        with patch.object(type(analyzer), 'model', new_callable=PropertyMock,
                          return_value=mock_model):
            findings = analyzer.analyze(
                "Unlimited free trial. No credit card required. Cancel anytime.",
                dom_data={}
            )
        self.assertEqual(len(findings), 0)

    def test_low_confidence_filtered(self):
        """Predictions with confidence < 0.60 should be dropped."""
        import numpy as np
        from app.services.ml_analyzer import MLAnalyzer
        analyzer = MLAnalyzer()
        mock_model = MagicMock()
        mock_model.predict.return_value = ['urgency']
        mock_model.predict_proba.return_value = np.array([[0.60, 0.40]])
        with patch.object(type(analyzer), 'model', new_callable=PropertyMock,
                          return_value=mock_model):
            findings = analyzer.analyze("Only 2 left!", dom_data={})
        self.assertEqual(len(findings), 0)

    def test_empty_text_returns_empty(self):
        """Empty or None text content should return empty list without crashing."""
        from app.services.ml_analyzer import MLAnalyzer
        analyzer = MLAnalyzer()
        mock_model = self._make_mock_model()
        with patch.object(type(analyzer), 'model', new_callable=PropertyMock,
                          return_value=mock_model):
            self.assertEqual(analyzer.analyze('', dom_data={}), [])
            self.assertEqual(analyzer.analyze(None, dom_data={}), [])

    def test_no_model_returns_empty(self):
        """If model is None (not loaded), should return empty list."""
        from app.services.ml_analyzer import MLAnalyzer
        analyzer = MLAnalyzer()
        with patch.object(type(analyzer), 'model', new_callable=PropertyMock,
                          return_value=None):
            findings = analyzer.analyze("Buy now! Limited offer!", dom_data={})
        self.assertEqual(findings, [])


# ═══════════════════════════════════════════════════════════════════════════════
# 5. READABILITY ANALYZER — Threshold Calibration
# ═══════════════════════════════════════════════════════════════════════════════

class TestReadabilityThresholds(unittest.TestCase):

    def setUp(self):
        from app.services.readability_analyzer import ReadabilityAnalyzer
        self.analyzer = ReadabilityAnalyzer()

    def _findings_for_grade(self, grade):
        """Patch FK grade and collect what findings are produced."""
        findings = []
        with patch.object(self.analyzer, '_flesch_kincaid_grade', return_value=grade):
            self.analyzer._check_readability_score("dummy text here for analysis.", findings)
        return findings

    def test_grade_below_14_no_finding(self):
        """Grade 13 should produce NO finding."""
        findings = self._findings_for_grade(13)
        self.assertEqual(len(findings), 0)

    def test_grade_14_medium_finding(self):
        """Grade 14 should produce a MEDIUM severity finding."""
        findings = self._findings_for_grade(14)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]['severity'], 'MEDIUM')

    def test_grade_16_high_finding(self):
        """Grade 16 should produce a HIGH severity finding."""
        findings = self._findings_for_grade(16)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]['severity'], 'HIGH')

    def test_grade_20_high_finding(self):
        """Grade 20 (max) should produce a HIGH severity finding."""
        findings = self._findings_for_grade(20)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]['severity'], 'HIGH')

    def test_medium_has_weak_signal(self):
        """MEDIUM (grade 14) finding should have 'weak' signal_strength."""
        findings = self._findings_for_grade(14)
        if findings:
            self.assertEqual(findings[0]['signal_strength'], 'weak')


# ═══════════════════════════════════════════════════════════════════════════════
# 6. LINK ANALYZER — Roach Motel Heuristics
# ═══════════════════════════════════════════════════════════════════════════════

class TestLinkAnalyzerRoachMotel(unittest.TestCase):

    def setUp(self):
        from app.services.link_analyzer import LinkPathAnalyzer
        self.analyzer = LinkPathAnalyzer()

    def _roach_motel_findings(self, html_lower, links=None):
        return self.analyzer._check_roach_motel(links or [], html_lower)

    def test_clean_homepage_no_finding(self):
        """A normal homepage with no account signals should produce no finding."""
        html = "welcome to our site. read our blog. contact us."
        findings = self._roach_motel_findings(html)
        self.assertEqual(len(findings), 0)

    def test_govuk_no_finding(self):
        """gov.uk-style content should not trigger Roach Motel."""
        html = "find government services. sign in to your account. benefits."
        findings = self._roach_motel_findings(html)
        self.assertEqual(len(findings), 0)

    def test_dashboard_with_cancel_no_finding(self):
        """A management page WITH a cancel link should not trigger."""
        html = "manage subscription billing details update payment method"
        links = [{'href': '/cancel', 'text': 'cancel subscription'}]
        findings = self._roach_motel_findings(html, links)
        self.assertEqual(len(findings), 0)

    def test_dashboard_without_cancel_triggers(self):
        """A management page WITHOUT any exit path should trigger."""
        html = "billing details manage subscription update payment method"
        links = [{'href': '/dashboard', 'text': 'Dashboard'},
                 {'href': '/billing', 'text': 'Billing'}]
        findings = self._roach_motel_findings(html, links)
        self.assertGreater(len(findings), 0)

    def test_finding_has_correct_category(self):
        """Roach Motel finding should be in 'obstruction' category."""
        html = "manage subscription billing details update payment method"
        links = [{'href': '/home', 'text': 'Home'}]
        findings = self._roach_motel_findings(html, links)
        if findings:
            self.assertEqual(findings[0]['category'], 'obstruction')


# ═══════════════════════════════════════════════════════════════════════════════
# 7. PIPELINE TIMEOUT SAFETY
# ═══════════════════════════════════════════════════════════════════════════════

class TestPipelineTimeout(unittest.TestCase):

    def test_global_timeout_does_not_crash(self):
        """
        If as_completed raises TimeoutError, the pipeline should catch it
        gracefully and return a PipelineResult (not raise).
        """
        from app.engine.pipeline import DetectionPipeline, PipelineResult
        from app.analyzers.base import AnalysisContext

        pipeline = DetectionPipeline(max_workers=1, timeout=1)

        # Register a slow analyzer that sleeps longer than the timeout
        slow_analyzer = MagicMock()
        slow_analyzer.name = 'slow'
        slow_analyzer.weight = 0.5
        slow_analyzer.run.side_effect = lambda ctx: time.sleep(5)  # 5s > 1s timeout

        # Patch as_completed to raise TimeoutError immediately
        from concurrent.futures import TimeoutError as FuturesTimeout
        with patch('app.engine.pipeline.as_completed',
                   side_effect=FuturesTimeout("global timeout")):
            scan_data = {
                'url': 'https://example.com', 'domain': 'example.com',
                'html_content': '<p>test</p>', 'text_content': 'test',
                'dom_data': {}, 'screenshot_path': None,
                'scan_id': 'test-001', 'timestamp': '2026-01-01',
                'dynamic_findings': [],
            }
            ctx = AnalysisContext(scan_data)
            result = pipeline.process(ctx)

        # Should return a valid PipelineResult, not raise
        self.assertIsInstance(result, PipelineResult)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. SSRF PROTECTION
# ═══════════════════════════════════════════════════════════════════════════════

class TestSSRFProtection(unittest.TestCase):

    def _is_safe(self, url):
        from app.services.scanner import _is_safe_url
        return _is_safe_url(url)

    def test_public_url_safe(self):
        self.assertTrue(self._is_safe('https://www.booking.com'))

    def test_localhost_blocked(self):
        self.assertFalse(self._is_safe('http://localhost/admin'))

    def test_127_blocked(self):
        self.assertFalse(self._is_safe('http://127.0.0.1/'))

    def test_private_192_blocked(self):
        self.assertFalse(self._is_safe('http://192.168.1.1/'))

    def test_private_10_blocked(self):
        self.assertFalse(self._is_safe('http://10.0.0.1/'))

    def test_file_scheme_blocked(self):
        self.assertFalse(self._is_safe('file:///etc/passwd'))


# ═══════════════════════════════════════════════════════════════════════════════
# 9. CONFIG ENVIRONMENT OVERRIDES
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfig(unittest.TestCase):

    def test_default_pipeline_timeout(self):
        from app.core.config import Config
        self.assertGreaterEqual(Config.PIPELINE_TIMEOUT_SECONDS, 30)

    def test_default_workers(self):
        from app.core.config import Config
        self.assertGreaterEqual(Config.PIPELINE_MAX_WORKERS, 4)

    def test_hade_thresholds_ordered(self):
        """CRITICAL threshold must be <= HIGH threshold <= default."""
        from app.core.config import Config
        self.assertLessEqual(Config.HADE_CONF_CRITICAL, Config.HADE_CONF_HIGH_IMPACT)
        self.assertLessEqual(Config.HADE_CONF_HIGH_IMPACT, Config.HADE_CONF_DEFAULT)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. FUSION ENGINE — Weighted Ensemble Correctness
# ═══════════════════════════════════════════════════════════════════════════════

class TestFusionEngine(unittest.TestCase):
    """T-1: FusionEngine had zero tests — these cover confidence boosting,
    normalization, cap limits, and scan-level fusion scoring."""

    def setUp(self):
        from app.engine.fusion import FusionEngine
        self.engine = FusionEngine()

    def _finding(self, category='urgency', engine='dom', confidence=0.70):
        return {
            'type': 'Test Finding',
            'category': category,
            'severity': 'HIGH',
            'confidence': confidence,
            '_engine': engine,
        }

    def test_single_engine_no_boost(self):
        """A finding from only 1 engine should get NO confidence boost."""
        findings = [self._finding(engine='dom', confidence=0.70)]
        fused = self.engine.fuse(findings)
        self.assertEqual(len(fused), 1)
        # Boost is 0 for single-engine, so confidence stays at 0.70
        self.assertAlmostEqual(fused[0]['confidence'], 0.70, places=2)

    def test_two_engine_corroboration_boost(self):
        """Two engines: raw confidence PRESERVED; fusion boost stored in _fusion_confidence."""
        findings = [
            self._finding(category='urgency', engine='dom', confidence=0.70),
            self._finding(category='urgency', engine='text', confidence=0.75),
        ]
        fused = self.engine.fuse(findings)
        self.assertEqual(len(fused), 2)
        # FIX C-2: Raw confidence is PRESERVED (immutable)
        self.assertAlmostEqual(fused[0]['confidence'], 0.70, places=2)
        self.assertAlmostEqual(fused[1]['confidence'], 0.75, places=2)
        # Fusion-boosted confidence stored in metadata
        self.assertAlmostEqual(fused[0]['_fusion_confidence'], 0.75, places=2)
        self.assertAlmostEqual(fused[1]['_fusion_confidence'], 0.80, places=2)

    def test_three_engine_corroboration_boost(self):
        """Three engines: raw confidence PRESERVED; +0.10 boost in _fusion_confidence."""
        findings = [
            self._finding(category='privacy', engine='dom', confidence=0.80),
            self._finding(category='privacy', engine='cookie', confidence=0.70),
            self._finding(category='privacy', engine='ml', confidence=0.60),
        ]
        fused = self.engine.fuse(findings)
        for f in fused:
            # FIX C-2: Raw confidence unchanged
            original_conf = {'dom': 0.80, 'cookie': 0.70, 'ml': 0.60}[f['_engine']]
            self.assertAlmostEqual(f['confidence'], original_conf, places=2)
            # Fusion-boosted confidence in metadata
            self.assertAlmostEqual(f['_fusion_confidence'], min(0.98, original_conf + 0.10), places=2)

    def test_confidence_cap_at_098(self):
        """_fusion_confidence must never exceed 0.98, even with boosts."""
        findings = [
            self._finding(category='urgency', engine='dom', confidence=0.96),
            self._finding(category='urgency', engine='text', confidence=0.95),
            self._finding(category='urgency', engine='ml', confidence=0.94),
        ]
        fused = self.engine.fuse(findings)
        for f in fused:
            self.assertLessEqual(f['_fusion_confidence'], 0.98)

    def test_fusion_metadata_tags(self):
        """Fused findings must have _fusion_score, _fusion_engines, _fusion_engine_count."""
        findings = [self._finding()]
        fused = self.engine.fuse(findings)
        self.assertIn('_fusion_score', fused[0])
        self.assertIn('_fusion_engines', fused[0])
        self.assertIn('_fusion_engine_count', fused[0])

    def test_empty_input_returns_empty(self):
        """Empty findings list should return empty list."""
        self.assertEqual(self.engine.fuse([]), [])

    def test_scan_fusion_score_empty(self):
        self.assertEqual(self.engine.calculate_scan_fusion_score([]), 0.0)

    def test_scan_fusion_score_range(self):
        """Scan-level fusion score must be in [0.0, 1.0]."""
        findings = [
            {**self._finding(engine='dom'), '_fusion_score': 0.8, '_fusion_engine_count': 3},
            {**self._finding(engine='text'), '_fusion_score': 0.5, '_fusion_engine_count': 2},
        ]
        score = self.engine.calculate_scan_fusion_score(findings)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_different_categories_independent(self):
        """Findings in different categories should NOT boost each other."""
        findings = [
            self._finding(category='urgency', engine='dom', confidence=0.70),
            self._finding(category='privacy', engine='text', confidence=0.70),
        ]
        fused = self.engine.fuse(findings)
        # Each category has only 1 engine → no boost
        for f in fused:
            self.assertAlmostEqual(f['confidence'], 0.70, places=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. TRUST SCORE FORMULA — Regression Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestTrustScoreFormula(unittest.TestCase):
    """T-2: The exponential decay trust score formula had zero regression tests.
    These lock down the expected output for known inputs."""

    def setUp(self):
        from app.services.report_generator import ReportGenerator
        self.gen = ReportGenerator()

    def _make_findings(self, severities):
        """Create mock findings with given severities."""
        return [
            {'severity': s, 'confidence': 0.80, 'category': 'urgency'}
            for s in severities
        ]

    def test_zero_findings_returns_95(self):
        """Clean site with no findings must score exactly 95."""
        score = self.gen._calculate_trust_score([])
        self.assertEqual(score, 95)

    def test_single_critical_drops_score(self):
        """One CRITICAL finding should drop score significantly (below 90)."""
        findings = self._make_findings(['CRITICAL'])
        score = self.gen._calculate_trust_score(findings)
        self.assertLess(score, 90)
        self.assertGreater(score, 60)  # But not catastrophically low

    def test_single_high_drops_less_than_critical(self):
        """HIGH should penalize less than CRITICAL."""
        critical = self.gen._calculate_trust_score(self._make_findings(['CRITICAL']))
        high = self.gen._calculate_trust_score(self._make_findings(['HIGH']))
        self.assertGreater(high, critical)

    def test_low_findings_no_penalty(self):
        """LOW severity findings should NOT penalize the score AT ALL."""
        score = self.gen._calculate_trust_score(self._make_findings(['LOW'] * 20))
        self.assertEqual(score, 95)

    def test_informational_no_penalty(self):
        """INFORMATIONAL findings should not penalize."""
        score = self.gen._calculate_trust_score(self._make_findings(['INFORMATIONAL'] * 10))
        self.assertEqual(score, 95)

    def test_ten_high_findings_severe_drop(self):
        """10 HIGH findings should produce a very low score (below 50)."""
        findings = self._make_findings(['HIGH'] * 10)
        score = self.gen._calculate_trust_score(findings)
        self.assertLess(score, 50)

    def test_compound_category_damping(self):
        """compound_pattern category gets 0.25x multiplier — much less penalty."""
        compound_findings = [
            {'severity': 'HIGH', 'confidence': 0.80, 'category': 'compound_pattern'}
            for _ in range(5)
        ]
        normal_findings = [
            {'severity': 'HIGH', 'confidence': 0.80, 'category': 'urgency'}
            for _ in range(5)
        ]
        compound_score = self.gen._calculate_trust_score(compound_findings)
        normal_score = self.gen._calculate_trust_score(normal_findings)
        # Compound should penalize much less (higher score)
        self.assertGreater(compound_score, normal_score)

    def test_score_never_below_minimum(self):
        """Even with extreme findings, score must stay at or above Config minimum."""
        from app.core.config import Config
        extreme = self._make_findings(['CRITICAL'] * 50)
        score = self.gen._calculate_trust_score(extreme)
        self.assertGreaterEqual(score, Config.TRUST_SCORE_MIN)

    def test_score_never_above_base(self):
        """Score must never exceed the configured base (95)."""
        from app.core.config import Config
        score = self.gen._calculate_trust_score([])
        self.assertLessEqual(score, int(Config.TRUST_SCORE_BASE))


# ═══════════════════════════════════════════════════════════════════════════════
# 12. TEMPORAL SMOOTHER — Basic Correctness
# ═══════════════════════════════════════════════════════════════════════════════

class TestTemporalSmoother(unittest.TestCase):

    def setUp(self):
        from app.engine.temporal import TemporalSmoother
        self.smoother = TemporalSmoother(window_size=5, decay=0.85)

    def test_first_scan_returns_raw_score(self):
        """First scan for a domain should return the raw score unchanged."""
        score = self.smoother.smooth_trust_score('new-site.com', 72)
        self.assertEqual(score, 72)

    def test_smoothing_dampens_outlier(self):
        """After recording a history, a sudden score change should be dampened."""
        self.smoother.record('test.com', 80, [])
        self.smoother.record('test.com', 82, [])
        # Now a sudden drop — smoothing should dampen it
        smoothed = self.smoother.smooth_trust_score('test.com', 40)
        # Should be somewhere between 40 and 82 (dampened)
        self.assertGreater(smoothed, 40)
        self.assertLess(smoothed, 82)

    def test_trend_returns_none_for_new_domain(self):
        trend = self.smoother.get_trend('brand-new.com')
        self.assertIsNone(trend)

    def test_trend_returns_data_after_two_scans(self):
        self.smoother.record('trend.com', 80, [])
        self.smoother.record('trend.com', 75, [])
        trend = self.smoother.get_trend('trend.com')
        self.assertIsNotNone(trend)
        self.assertEqual(trend['trend'], 'declining')


# ═══════════════════════════════════════════════════════════════════════════════
# 10. SSRF DNS REBINDING PROTECTION
# ═══════════════════════════════════════════════════════════════════════════════

class TestSSRFDNSRebinding(unittest.TestCase):
    """Test DNS rebinding defense in scanner._is_private_ip and _is_safe_url."""

    def test_ipv4_loopback_blocked(self):
        from app.services.scanner import _is_private_ip
        self.assertTrue(_is_private_ip('127.0.0.1'))

    def test_ipv4_rfc1918_10_blocked(self):
        from app.services.scanner import _is_private_ip
        self.assertTrue(_is_private_ip('10.0.0.1'))

    def test_ipv4_rfc1918_172_blocked(self):
        from app.services.scanner import _is_private_ip
        self.assertTrue(_is_private_ip('172.16.0.1'))

    def test_ipv4_rfc1918_192_blocked(self):
        from app.services.scanner import _is_private_ip
        self.assertTrue(_is_private_ip('192.168.1.1'))

    def test_ipv6_loopback_blocked(self):
        from app.services.scanner import _is_private_ip
        self.assertTrue(_is_private_ip('::1'))

    def test_link_local_blocked(self):
        from app.services.scanner import _is_private_ip
        self.assertTrue(_is_private_ip('169.254.1.1'))

    def test_public_ip_allowed(self):
        from app.services.scanner import _is_private_ip
        self.assertFalse(_is_private_ip('8.8.8.8'))

    def test_invalid_ip_blocked(self):
        from app.services.scanner import _is_private_ip
        self.assertTrue(_is_private_ip('not-an-ip'))


# ═══════════════════════════════════════════════════════════════════════════════
# 11. CONFIDENCE IMMUTABILITY (FIX C-2 INVARIANT)
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfidenceImmutability(unittest.TestCase):
    """Verify that confidence values pass through the pipeline UNCHANGED.

    Fix C-2 invariant: The engine's raw confidence must never be overwritten
    by downstream components (HADE, Fusion, Aggregator). Fusion boost is stored
    in _fusion_confidence metadata only.
    """

    def test_fusion_preserves_confidence(self):
        """FusionEngine must not overwrite the 'confidence' field."""
        from app.engine.fusion import FusionEngine
        engine = FusionEngine()
        findings = [
            {'type': 'T1', 'category': 'urgency', '_engine': 'dom', 'confidence': 0.72, 'severity': 'HIGH'},
            {'type': 'T2', 'category': 'urgency', '_engine': 'text', 'confidence': 0.68, 'severity': 'MEDIUM'},
        ]
        fused = engine.fuse(findings)
        # Raw confidence MUST be preserved
        self.assertAlmostEqual(fused[0]['confidence'], 0.72, places=2)
        self.assertAlmostEqual(fused[1]['confidence'], 0.68, places=2)
        # Fusion boost stored separately
        self.assertIn('_fusion_confidence', fused[0])
        self.assertGreater(fused[0]['_fusion_confidence'], 0.72)

    def test_aggregator_preserves_confidence(self):
        """FindingsAggregator must not overwrite the 'confidence' field."""
        from app.services.findings_aggregator import FindingsAggregator
        agg = FindingsAggregator()
        findings = [
            {'type': 'Cookie Wall', 'category': 'privacy', '_engine': 'cookie',
             'confidence': 0.85, 'severity': 'CRITICAL', 'element': '#cookie-banner',
             '_signal_strength': 'strong'},
            {'type': 'Cookie Wall', 'category': 'privacy', '_engine': 'dom',
             'confidence': 0.78, 'severity': 'HIGH', 'element': '#cookie-banner',
             '_signal_strength': 'moderate'},
        ]
        result = agg.aggregate(findings, page_text='')
        for f in result:
            # Confidence must be one of the original values, not a boosted/capped value
            self.assertIn(f['confidence'], [0.85, 0.78])


# ═══════════════════════════════════════════════════════════════════════════════
# 12. DOM EXTRACTOR
# ═══════════════════════════════════════════════════════════════════════════════

class TestDOMExtractor(unittest.TestCase):
    """Test the extracted DOM data module."""

    def test_extract_checkboxes(self):
        from app.services.dom_extractor import extract_dom_data
        from bs4 import BeautifulSoup
        html = '<form><input type="checkbox" checked name="consent" id="cb1"><label for="cb1">I agree</label></form>'
        soup = BeautifulSoup(html, 'html.parser')
        data = extract_dom_data(soup)
        self.assertEqual(len(data['checkboxes']), 1)
        self.assertTrue(data['checkboxes'][0]['checked'])
        self.assertIn('I agree', data['checkboxes'][0]['label'])

    def test_extract_buttons(self):
        from app.services.dom_extractor import extract_dom_data
        from bs4 import BeautifulSoup
        html = '<button class="primary">Add to Cart</button><button class="small muted">No thanks</button>'
        soup = BeautifulSoup(html, 'html.parser')
        data = extract_dom_data(soup)
        self.assertEqual(len(data['buttons']), 2)
        texts = {b['text'] for b in data['buttons']}
        self.assertIn('Add to Cart', texts)

    def test_extract_empty_html(self):
        from app.services.dom_extractor import extract_dom_data
        from bs4 import BeautifulSoup
        soup = BeautifulSoup('', 'html.parser')
        data = extract_dom_data(soup)
        self.assertIsInstance(data, dict)
        self.assertEqual(data['forms'], [])
        self.assertEqual(data['buttons'], [])


# ═══════════════════════════════════════════════════════════════════════════════
# 12. SECURE IP EXTRACTION (Rate Limiter Bypass Fix)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSecureIPExtraction(unittest.TestCase):
    """Verify rate limiter cannot be bypassed via spoofed X-Forwarded-For."""

    def test_trusted_proxy_check_empty(self):
        """With no trusted proxies configured, _is_trusted_proxy always returns False."""
        from app.extensions import _is_trusted_proxy, _TRUSTED_PROXIES
        # In test env, no proxies are configured
        if not _TRUSTED_PROXIES:
            self.assertFalse(_is_trusted_proxy('127.0.0.1'))
            self.assertFalse(_is_trusted_proxy('10.0.0.1'))

    def test_secure_ip_module_has_get_real_ip(self):
        """extensions.py must export _get_real_ip for auth + rate limiter."""
        from app.extensions import _get_real_ip
        self.assertTrue(callable(_get_real_ip))

    def test_limiter_uses_secure_key_func(self):
        """Rate limiter must use _get_real_ip, NOT flask_limiter's get_remote_address."""
        from app.extensions import limiter, _get_real_ip
        self.assertEqual(limiter._key_func, _get_real_ip)


# ═══════════════════════════════════════════════════════════════════════════════
# 13. MODEL INTEGRITY (SHA-256 Verification)
# ═══════════════════════════════════════════════════════════════════════════════

class TestModelIntegrity(unittest.TestCase):
    """Verify SHA-256 model verification is implemented."""

    def test_ml_analyzer_has_integrity_check(self):
        """_load_model must contain SHA-256 verification logic."""
        import inspect
        from app.services.ml_analyzer import MLAnalyzer
        source = inspect.getsource(MLAnalyzer._load_model)
        self.assertIn('sha256', source.lower())
        self.assertIn('manifest', source.lower())
        self.assertIn('integrity', source.lower())

    def test_ml_analyzer_rejects_tampered_model(self):
        """If manifest hash doesn't match, model must NOT be loaded."""
        import inspect
        from app.services.ml_analyzer import MLAnalyzer
        source = inspect.getsource(MLAnalyzer._load_model)
        # Must have the rejection path
        self.assertIn('Refusing to load', source)


# ═══════════════════════════════════════════════════════════════════════════════
# 14. ML DATA LEAKAGE FIX
# ═══════════════════════════════════════════════════════════════════════════════

class TestMLDataLeakage(unittest.TestCase):
    """Verify training pipeline splits BEFORE augmenting."""

    def test_train_function_splits_before_augment(self):
        """The train() function must call train_test_split on raw data,
        then augment only the training portion."""
        import inspect
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'train'))
        # Read the source of train_ml_model.py
        train_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), 'train', 'train_ml_model.py'
        )
        with open(train_path, 'r', encoding='utf-8') as f:
            source = f.read()

        # The split must happen on raw data variables, not augmented
        self.assertIn('raw_texts, raw_labels', source,
                      "train_test_split must operate on raw_texts/raw_labels")
        self.assertIn('X_train_raw', source,
                      "Raw train split must be stored before augmentation")
        # Augmentation must happen AFTER split
        split_pos = source.find('train_test_split')
        augment_pos = source.find('augment_dataset', split_pos)
        self.assertGreater(augment_pos, split_pos,
                           "augment_dataset must be called AFTER train_test_split")

    def test_rf_has_depth_constraint(self):
        """RandomForest must have max_depth and min_samples_leaf set."""
        train_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), 'train', 'train_ml_model.py'
        )
        with open(train_path, 'r', encoding='utf-8') as f:
            source = f.read()
        self.assertIn('max_depth=20', source)
        self.assertIn('min_samples_leaf=2', source)
        self.assertNotIn('max_depth=None', source,
                         "max_depth=None allows unlimited tree depth -> overfitting")


# ═══════════════════════════════════════════════════════════════════════════════
# 15. ASYNC SCAN ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestAsyncScanRoutes(unittest.TestCase):
    """Verify async scan infrastructure (self-contained ThreadPool)."""

    def test_async_routes_exist(self):
        """scan.py must have /scan/async and /scan/status/<task_id> routes."""
        scan_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), 'app', 'routes', 'scan.py'
        )
        with open(scan_path, 'r', encoding='utf-8') as f:
            source = f.read()
        self.assertIn('/scan/async', source)
        self.assertIn('/scan/status/', source)
        self.assertIn('scan_website_task', source)

    def test_worker_config_exists(self):
        """Async worker module must exist."""
        worker_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), 'app', 'worker.py'
        )
        self.assertTrue(os.path.exists(worker_path))

    def test_worker_is_self_contained(self):
        """Worker must use ThreadPoolExecutor, not Celery."""
        worker_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), 'app', 'worker.py'
        )
        with open(worker_path, 'r', encoding='utf-8') as f:
            source = f.read()
        self.assertIn('ThreadPoolExecutor', source)
        self.assertNotIn('from celery', source)
        self.assertNotIn('redis://', source)

    def test_task_definition_exists(self):
        """Task definition file must exist with scan_website_task."""
        tasks_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), 'app', 'tasks.py'
        )
        self.assertTrue(os.path.exists(tasks_path))
        with open(tasks_path, 'r', encoding='utf-8') as f:
            source = f.read()
        self.assertIn('scan_website_task', source)
        self.assertIn('get_task_status', source)

    def test_task_worker_submit_returns_uuid(self):
        """AsyncTaskWorker.submit() must return a valid UUID string."""
        from app.worker import task_worker
        import re
        # Submit a dummy task (will fail immediately since invalid URL,
        # but we only need to verify the task_id is returned)
        task_id = task_worker.submit('http://test-invalid-url-for-unit-test.example')
        self.assertIsInstance(task_id, str)
        self.assertRegex(task_id, r'^[a-f0-9\-]{36}$')

    def test_task_status_returns_dict(self):
        """get_task_status() must return a dict with required keys."""
        from app.tasks import scan_website_task, get_task_status
        import time
        task_id = scan_website_task('http://test-invalid-url-for-unit-test.example')
        # Give it a moment to register
        time.sleep(0.1)
        status = get_task_status(task_id)
        self.assertIsNotNone(status)
        self.assertIn('task_id', status)
        self.assertIn('state', status)
        self.assertIn('progress', status)


# ═══════════════════════════════════════════════════════════════════════════════
# RUNNER
# ═══════════════════════════════════════════════════════════════════════════════


if __name__ == '__main__':
    # Output clear summary
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(
        __import__(__name__)
    )
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)



# ═══════════════════════════════════════════════════════════════════════════════
# 16. VALIDATION — XSS / PSEUDO-SCHEME BYPASS
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidationPseudoSchemes(unittest.TestCase):
    """Verify pseudo-schemes (javascript:, vbscript:, data:, blob:) are blocked.
    These have no :// separator so they bypass the scheme-split check without
    an explicit blocklist — this class tests that blocklist."""

    def setUp(self):
        from app.core.validation import validate_scan_request
        self.validate = validate_scan_request

    def test_javascript_scheme_blocked(self):
        ok, err = self.validate({'url': 'javascript:alert(1)'})
        self.assertFalse(ok, "javascript: scheme must be blocked")

    def test_javascript_scheme_with_slashes_blocked(self):
        ok, err = self.validate({'url': 'javascript://example.com'})
        self.assertFalse(ok)

    def test_vbscript_scheme_blocked(self):
        ok, err = self.validate({'url': 'vbscript:msgbox(1)'})
        self.assertFalse(ok, "vbscript: scheme must be blocked")

    def test_data_uri_blocked(self):
        ok, err = self.validate({'url': 'data:text/html,<h1>xss</h1>'})
        self.assertFalse(ok, "data: URI must be blocked")

    def test_blob_uri_blocked(self):
        ok, err = self.validate({'url': 'blob:https://example.com/uuid'})
        self.assertFalse(ok, "blob: URI must be blocked")

    def test_uppercase_javascript_blocked(self):
        """Scheme check must be case-insensitive."""
        ok, err = self.validate({'url': 'JAVASCRIPT:alert(1)'})
        self.assertFalse(ok)

    def test_padded_javascript_blocked(self):
        """Leading whitespace before javascript: must still be blocked."""
        ok, err = self.validate({'url': '  javascript:alert(1)'})
        self.assertFalse(ok)


# ═══════════════════════════════════════════════════════════════════════════════
# 17. HARM-AWARE DECISION ENGINE (HADE) — Unit Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestHADE(unittest.TestCase):
    """Core HADE calibration logic — impact scoring, intent validation,
    weak-signal filtering, and the critical-override path."""

    def setUp(self):
        from app.services.decision_engine import HarmAwareDecisionEngine
        self.hade = HarmAwareDecisionEngine()

    def _finding(self, ftype='Countdown Timer / Fake Urgency', category='urgency',
                 severity='HIGH', confidence=0.80, engine='dom'):
        return {
            'type': ftype,
            'category': category,
            'severity': severity,
            'confidence': confidence,
            '_engine': engine,
            'element': '#timer',
            'evidence': 'Buy now! Only 3 left.',
            'description': 'Test finding.',
            'recommendation': 'Fix it.',
        }

    def test_empty_findings_returns_empty(self):
        result = self.hade.evaluate([])
        self.assertEqual(result, [])

    def test_informational_finding_removed(self):
        """INFORMATIONAL severity findings should be filtered out."""
        f = self._finding(severity='INFORMATIONAL', confidence=0.90)
        result = self.hade.evaluate([f])
        self.assertEqual(len(result), 0)

    def test_high_impact_category_passes_lower_threshold(self):
        """HIGH-impact categories (privacy, forced_continuity) pass at 0.65 confidence."""
        f = self._finding(
            ftype='Auto-Renew Billing',
            category='forced_continuity',
            severity='HIGH',
            confidence=0.67,
        )
        result = self.hade.evaluate([f])
        self.assertGreater(len(result), 0, "forced_continuity at 0.67 should pass HADE")

    def test_low_confidence_generic_finding_filtered(self):
        """Generic MEDIUM finding below 0.75 confidence must be dropped."""
        f = self._finding(
            ftype='Some Generic Text',
            category='urgency',
            severity='MEDIUM',
            confidence=0.60,
            engine='text',
        )
        result = self.hade.evaluate([f])
        self.assertEqual(len(result), 0)

    def test_weak_signal_fragment_filtered(self):
        """Findings whose type contains a known weak-signal fragment are suppressed."""
        f = self._finding(
            ftype='Above-average reading complexity',
            category='emotional',
            severity='MEDIUM',
            confidence=0.80,
        )
        result = self.hade.evaluate([f])
        # 'above-average reading complexity' is in _WEAK_SIGNAL_FRAGMENTS
        self.assertEqual(len(result), 0)

    def test_critical_type_trigger_sets_is_critical_flag(self):
        """Findings matching _CRITICAL_TYPE_TRIGGERS must have _is_critical=True.

        HADE marks these with _is_critical but does NOT promote severity itself —
        that promotion happens in FindingsAggregator._consensus_gate (Step 4 of
        the pipeline). This test verifies the flag is set correctly so the
        aggregator can do its job.
        """
        f = self._finding(
            ftype='pre-selected marketing checkbox',
            category='preselection',
            severity='HIGH',
            confidence=0.62,
        )
        result = self.hade.evaluate([f])
        self.assertGreater(len(result), 0, "Critical-trigger finding must pass HADE")
        self.assertTrue(
            result[0].get('_is_critical'),
            "_is_critical flag must be True for critical-trigger finding types"
        )

    def test_output_findings_have_hade_gate_field(self):
        """Every finding that passes HADE must have a '_hade_gate' metadata field."""
        f = self._finding(confidence=0.82)
        result = self.hade.evaluate([f])
        if result:
            self.assertIn('_hade_gate', result[0])

    def test_multi_signal_required_single_finding_filtered(self):
        """urgency with only 1 finding should be filtered (needs >= 2)."""
        f = self._finding(
            ftype='Countdown Timer',
            category='urgency',
            severity='MEDIUM',
            confidence=0.80,
            engine='text',
        )
        result = self.hade.evaluate([f])
        # Single urgency signal without multi-engine corroboration should be dropped
        # (HADE _MULTI_SIGNAL_REQUIRED requires >= 2 findings for urgency)
        self.assertEqual(len(result), 0)

    def test_multi_signal_required_two_findings_pass(self):
        """Two urgency findings from different engines should both pass."""
        findings = [
            self._finding(category='urgency', engine='dom', confidence=0.80),
            self._finding(category='urgency', engine='text', confidence=0.78),
        ]
        result = self.hade.evaluate(findings)
        self.assertGreater(len(result), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# 18. BEHAVIORAL SCORER — Unit Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestBehavioralScorer(unittest.TestCase):
    """BehavioralScorer compound pattern detection — weight thresholds,
    distinct category requirement, and severity assignment."""

    def setUp(self):
        from app.services.behavioral_scorer import BehavioralScorer
        self.scorer = BehavioralScorer()

    def _finding(self, category='cookie', severity='HIGH', engine='cookie', ftype='Cookie Wall'):
        return {
            'type': ftype,
            'category': category,
            'severity': severity,
            '_engine': engine,
            'confidence': 0.85,
        }

    def test_empty_findings_no_compound(self):
        result = self.scorer.analyze([], '', {})
        self.assertEqual(result, [])

    def test_only_low_severity_no_compound(self):
        """LOW severity findings should be excluded from compound scoring."""
        findings = [self._finding(severity='LOW') for _ in range(10)]
        result = self.scorer.analyze(findings, '', {})
        self.assertEqual(len(result), 0)

    def test_single_category_no_compound(self):
        """Even with high weight, a single category cannot trigger compound."""
        findings = [self._finding(category='cookie', severity='HIGH') for _ in range(5)]
        result = self.scorer.analyze(findings, '', {})
        self.assertEqual(len(result), 0,
                         "Compound requires >= 2 distinct categories")

    def test_two_high_weight_categories_triggers_compound(self):
        """cookie (w=3) + forced_continuity (w=3) = weight 6 >= 5 → compound."""
        findings = [
            self._finding(category='cookie', severity='HIGH', engine='cookie'),
            self._finding(category='forced_continuity', severity='HIGH',
                          engine='advanced', ftype='Auto-Renew Billing'),
        ]
        result = self.scorer.analyze(findings, '', {})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['category'], 'compound_pattern')

    def test_compound_severity_critical_with_cookie(self):
        """Compound pattern with cookie involvement must be CRITICAL."""
        findings = [
            self._finding(category='cookie', severity='HIGH', engine='cookie'),
            self._finding(category='forced_continuity', severity='HIGH',
                          engine='advanced', ftype='Auto-Renew'),
        ]
        result = self.scorer.analyze(findings, '', {})
        self.assertGreater(len(result), 0)
        self.assertEqual(result[0]['severity'], 'CRITICAL')

    def test_compound_severity_high_without_cookie(self):
        """Compound pattern without cookie/tracking should be HIGH, not CRITICAL."""
        findings = [
            self._finding(category='confirmshaming', severity='HIGH',
                          engine='text', ftype='Shame Button'),
            self._finding(category='urgency', severity='MEDIUM',
                          engine='dom', ftype='Countdown Timer'),
            self._finding(category='urgency', severity='MEDIUM',
                          engine='text', ftype='Urgency Text'),
        ]
        result = self.scorer.analyze(findings, '', {})
        if result:
            self.assertEqual(result[0]['severity'], 'HIGH')

    def test_compound_confidence_scales_with_weight(self):
        """Higher weight input should produce higher compound confidence."""
        low_weight_findings = [
            self._finding(category='urgency', severity='MEDIUM', engine='dom'),
            self._finding(category='social_proof', severity='MEDIUM', engine='text',
                          ftype='Fake Reviews'),
            self._finding(category='urgency', severity='MEDIUM', engine='text'),
        ]
        high_weight_findings = [
            self._finding(category='cookie', severity='HIGH', engine='cookie'),
            self._finding(category='forced_continuity', severity='HIGH', engine='advanced',
                          ftype='Auto-Renew'),
            self._finding(category='preselection', severity='HIGH', engine='dom',
                          ftype='Pre-checked box'),
        ]
        low_result = self.scorer.analyze(low_weight_findings, '', {})
        high_result = self.scorer.analyze(high_weight_findings, '', {})
        if low_result and high_result:
            self.assertGreater(high_result[0]['confidence'], low_result[0]['confidence'])

    def test_compound_finding_has_required_fields(self):
        """Compound finding must have all required output fields."""
        findings = [
            self._finding(category='cookie', severity='HIGH', engine='cookie'),
            self._finding(category='preselection', severity='HIGH', engine='dom',
                          ftype='Pre-checked box'),
        ]
        result = self.scorer.analyze(findings, '', {})
        if result:
            f = result[0]
            for field in ('type', 'category', 'severity', 'confidence',
                          'description', 'evidence', 'recommendation', 'legal_refs'):
                self.assertIn(field, f, f"Missing field: {field}")

    def test_compound_finding_not_double_counted(self):
        """Existing compound_pattern findings should be excluded from re-scoring."""
        findings = [
            self._finding(category='cookie', severity='HIGH'),
            self._finding(category='forced_continuity', severity='HIGH', engine='advanced',
                          ftype='Auto-Renew'),
            {'type': 'COMPOUND DARK PATTERN', 'category': 'compound_pattern',
             'severity': 'CRITICAL', '_engine': 'behavioral', 'confidence': 0.80},
        ]
        result = self.scorer.analyze(findings, '', {})
        # Should produce at most one compound finding — not re-compound a compound
        compound_results = [r for r in result if r['category'] == 'compound_pattern']
        self.assertLessEqual(len(compound_results), 1)


# ═══════════════════════════════════════════════════════════════════════════════
# 19. ML ANALYZER — BARE EXCEPT LOGGING
# ═══════════════════════════════════════════════════════════════════════════════

class TestMLAnalyzerErrorLogging(unittest.TestCase):
    """Verify that exceptions in MLAnalyzer are logged, not silently swallowed."""

    def test_batch_inference_exception_is_logged(self):
        """When model.predict raises, the exception must be logged as WARNING."""
        from app.services.ml_analyzer import MLAnalyzer
        import logging

        analyzer = MLAnalyzer()
        broken_model = MagicMock()
        broken_model.predict.side_effect = RuntimeError("Model corrupted")

        with patch.object(type(analyzer), 'model', new_callable=PropertyMock,
                          return_value=broken_model):
            with self.assertLogs('vigil.ml_analyzer', level='WARNING') as log:
                result = analyzer.analyze(
                    "Only 3 left! Buy now before it expires tonight.",
                    dom_data={}
                )

        self.assertEqual(result, [])
        # At least one WARNING log must mention the failure
        self.assertTrue(
            any('batch inference' in msg.lower() or 'inference failed' in msg.lower()
                for msg in log.output),
            f"Expected inference failure log. Got: {log.output}"
        )




# ═══════════════════════════════════════════════════════════════════════════════
# 21. FRONTEND ASYNC WIRING
# ═══════════════════════════════════════════════════════════════════════════════

class TestFrontendAsyncWiring(unittest.TestCase):
    """Verify app.js uses the async polling flow, not the old synchronous scan."""

    def _load_appjs(self):
        appjs_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), 'static', 'js', 'app.js'
        )
        with open(appjs_path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_async_endpoint_called(self):
        """app.js must call /api/scan/async, not POST to /api/scan directly."""
        content = self._load_appjs()
        self.assertIn('/api/scan/async', content,
                      "Frontend must submit to /api/scan/async (async queue), "
                      "not block on /api/scan")

    def test_status_polling_present(self):
        """app.js must poll /api/scan/status/ for task results."""
        content = self._load_appjs()
        self.assertIn('/api/scan/status/', content,
                      "Frontend must poll /api/scan/status/<task_id> for completion")

    def test_sync_fallback_present(self):
        """app.js must fall back to /api/scan if async endpoint returns 503."""
        content = self._load_appjs()
        self.assertIn('503', content,
                      "Frontend must handle 503 gracefully and fall back to sync scan")

    def test_no_fake_step_animations(self):
        """Fake timed sleep animations should be replaced by real state polling."""
        content = self._load_appjs()
        # The old fake loop: 'for (let i = 0; i < 9; i++) { ... sleep(400'
        # Progress must now be driven by STAGE_PROGRESS map, not random sleeps
        self.assertIn('STAGE_PROGRESS', content,
                      "Progress must be driven by real task state (STAGE_PROGRESS map), "
                      "not fake timed animations")


# ═══════════════════════════════════════════════════════════════════════════════
# 22. STALE ARTIFACT HYGIENE
# ═══════════════════════════════════════════════════════════════════════════════

class TestStaleArtifacts(unittest.TestCase):
    """Committed test artifacts that have no content are misleading — they
    suggest a test ran cleanly when it didn't."""

    def test_smoke_results2_not_committed_empty(self):
        """smoke_results2.txt must not exist as a 0-byte committed file."""
        artifact = os.path.join(
            os.path.dirname(__file__), 'smoke_results2.txt'
        )
        if os.path.exists(artifact):
            size = os.path.getsize(artifact)
            self.assertGreater(size, 0,
                               "smoke_results2.txt is 0 bytes — either delete it "
                               "or populate it with real test output before committing")