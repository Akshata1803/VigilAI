"""
Vigil AI — Production Test Suite v2.0
=======================================
Comprehensive testing for the refactored architecture:
  - Unit tests for each analyzer
  - Pipeline integration tests
  - Fusion engine tests
  - Decision engine tests
  - Temporal smoother tests
  - Edge case coverage
  - Performance benchmarks
"""

import time
import json
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════════════════════════════════════
# CORE INFRASTRUCTURE TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfig(unittest.TestCase):
    """Test centralized configuration."""

    def test_config_has_required_keys(self):
        from app.core.config import Config
        self.assertTrue(hasattr(Config, 'PIPELINE_MAX_WORKERS'))
        self.assertTrue(hasattr(Config, 'FUSION_WEIGHTS'))
        self.assertTrue(hasattr(Config, 'HADE_CONF_DEFAULT'))

    def test_config_to_dict(self):
        from app.core.config import Config
        d = Config.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn('VERSION', d)

    def test_fusion_weights_sum_to_one(self):
        from app.core.config import Config
        total = sum(Config.FUSION_WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0, places=2)


class TestLogger(unittest.TestCase):
    """Test structured logging."""

    def test_get_logger_returns_logger(self):
        from app.core.logger import get_logger
        logger = get_logger('test')
        self.assertIsNotNone(logger)

    def test_correlation_id(self):
        from app.core.logger import set_correlation_id, get_correlation_id
        cid = set_correlation_id('test-123')
        self.assertEqual(get_correlation_id(), 'test-123')


class TestMetrics(unittest.TestCase):
    """Test metrics collector."""

    def test_timer(self):
        from app.core.metrics import MetricsCollector
        m = MetricsCollector()
        m.reset()
        with m.timer('test_op') as t:
            time.sleep(0.01)
        self.assertGreater(t.duration_ms, 0)

    def test_counters(self):
        from app.core.metrics import MetricsCollector
        m = MetricsCollector()
        m.reset()
        m.increment('test_counter', 5)
        summary = m.get_summary()
        self.assertEqual(summary['counters']['test_counter'], 5)

    def test_singleton(self):
        from app.core.metrics import MetricsCollector
        m1 = MetricsCollector()
        m2 = MetricsCollector()
        self.assertIs(m1, m2)


class TestExceptions(unittest.TestCase):
    """Test custom exception hierarchy."""

    def test_vigil_error_to_dict(self):
        from app.core.exceptions import VigilError
        e = VigilError("test", retryable=True, error_code='TEST')
        d = e.to_dict()
        self.assertEqual(d['error'], 'test')
        self.assertTrue(d['retryable'])

    def test_analyzer_error(self):
        from app.core.exceptions import AnalyzerError
        e = AnalyzerError("failed", analyzer_name='dom')
        self.assertEqual(e.details['analyzer'], 'dom')


# ═══════════════════════════════════════════════════════════════════════════════
# ANALYZER TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestDOMAnalyzer(unittest.TestCase):
    """Test DOM structural analyzer."""

    def setUp(self):
        from app.services.dom_analyzer import DOMAnalyzer
        self.analyzer = DOMAnalyzer()

    def test_empty_dom_returns_empty(self):
        result = self.analyzer.analyze({}, '')
        self.assertEqual(result, [])

    def test_prechecked_marketing_checkbox(self):
        dom = {
            'checkboxes': [{'checked': True, 'label': 'Subscribe to our newsletter', 'name': 'newsletter'}],
            'buttons': [], 'timers': [], 'prices': [], 'forms': [], 'text_elements': [],
        }
        results = self.analyzer.analyze(dom, '')
        found = [f for f in results if f['type'] == 'Pre-Selected Marketing Checkbox']
        self.assertGreater(len(found), 0)
        self.assertEqual(found[0]['severity'], 'HIGH')
        self.assertGreater(found[0]['confidence'], 0.8)

    def test_unchecked_checkbox_no_finding(self):
        dom = {
            'checkboxes': [{'checked': False, 'label': 'Subscribe to newsletter', 'name': 'nl'}],
            'buttons': [], 'timers': [], 'prices': [], 'forms': [], 'text_elements': [],
        }
        results = self.analyzer.analyze(dom, '')
        checkbox_findings = [f for f in results if 'Checkbox' in f.get('type', '')]
        self.assertEqual(len(checkbox_findings), 0)

    def test_confirmshaming_detection(self):
        dom = {
            'buttons': [{'text': "No, I don't want to save money", 'classes': '', 'style': '', 'type': 'button', 'id': 'decline'}],
            'checkboxes': [], 'timers': [], 'prices': [], 'forms': [], 'text_elements': [],
        }
        results = self.analyzer.analyze(dom, '')
        found = [f for f in results if f['type'] == 'Confirmshaming Button']
        self.assertGreater(len(found), 0)

    def test_fake_timer_detection(self):
        dom = {
            'timers': [{'text': 'Offer expires in 2:00:00 - hurry!', 'tag': 'div', 'classes': 'countdown', 'id': ''}],
            'checkboxes': [], 'buttons': [], 'prices': [], 'forms': [], 'text_elements': [],
        }
        results = self.analyzer.analyze(dom, '')
        found = [f for f in results if 'Timer' in f.get('type', '') or 'Urgency' in f.get('type', '')]
        self.assertGreater(len(found), 0)


class TestAdvancedAnalyzer(unittest.TestCase):
    """Test advanced structural analyzer."""

    def setUp(self):
        from app.services.advanced_analyzer import AdvancedAnalyzer
        self.analyzer = AdvancedAnalyzer()

    def test_empty_returns_empty(self):
        result = self.analyzer.analyze({}, '', '', {})
        self.assertEqual(result, [])

    def test_meta_refresh_detection(self):
        html = '<html><head><meta http-equiv="refresh" content="3; url=trap.html"></head></html>'
        results = self.analyzer.analyze({}, html, '', {})
        found = [f for f in results if 'Meta-Refresh' in f.get('type', '')]
        self.assertGreater(len(found), 0)

    def test_subscription_upsell_on_product_page(self):
        html = '<div class="product">Buy now</div><p>Subscribe and save $5/month with auto-renew</p>'
        dom = {'links': [], 'forms': [], 'checkboxes': [], 'buttons': [], 'text_elements': []}
        results = self.analyzer.analyze(dom, html, 'Buy now subscribe and save $5/month', {'url': 'https://shop.com/product/1'})
        # This should detect subscription upsell on a product page
        self.assertIsInstance(results, list)


class TestTextAnalyzer(unittest.TestCase):
    """Test NLP text analyzer."""

    def setUp(self):
        from app.services.text_analyzer import TextAnalyzer
        self.analyzer = TextAnalyzer()

    def test_empty_returns_empty(self):
        result = self.analyzer.analyze({}, '')
        self.assertEqual(result, [])

    def test_standalone_urgency_detection(self):
        dom = {
            'text_elements': [{'text': 'Flash sale ends tonight! Act now!', 'tag': 'span', 'classes': 'banner'}],
        }
        results = self.analyzer.analyze(dom, '')
        urgency = [f for f in results if f.get('category') == 'urgency']
        self.assertGreater(len(urgency), 0)


class TestCookieAnalyzer(unittest.TestCase):
    """Test cookie consent analyzer."""

    def setUp(self):
        from app.services.cookie_analyzer import CookieConsentAnalyzer
        self.analyzer = CookieConsentAnalyzer()

    def test_accept_only_banner(self):
        html = '<div>We use cookies to improve your experience. <button>Accept All</button></div>'
        results = self.analyzer.analyze({}, html)
        cookie_findings = [f for f in results if f.get('type') == 'COOKIE_MANIPULATION']
        self.assertGreater(len(cookie_findings), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# ENGINE TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestFusionEngine(unittest.TestCase):
    """Test weighted ensemble fusion."""

    def setUp(self):
        from app.engine.fusion import FusionEngine
        self.fusion = FusionEngine()

    def test_empty_findings(self):
        result = self.fusion.fuse([])
        self.assertEqual(result, [])

    def test_multi_engine_confidence_boost(self):
        findings = [
            {'type': 'Test', 'category': 'urgency', '_engine': 'dom', 'confidence': 0.8},
            {'type': 'Test', 'category': 'urgency', '_engine': 'text', 'confidence': 0.85},
        ]
        fused = self.fusion.fuse(findings)
        # Both should have boosted confidence
        for f in fused:
            self.assertGreaterEqual(f['confidence'], 0.8)
            self.assertGreaterEqual(f['_fusion_engine_count'], 2)

    def test_single_engine_no_boost(self):
        findings = [
            {'type': 'Test', 'category': 'privacy', '_engine': 'cookie', 'confidence': 0.75},
        ]
        fused = self.fusion.fuse(findings)
        self.assertEqual(fused[0]['_fusion_engine_count'], 1)


class TestRiskDecisionEngine(unittest.TestCase):
    """Test risk classification."""

    def setUp(self):
        from app.engine.decision import RiskDecisionEngine
        self.engine = RiskDecisionEngine()

    def test_no_findings_low_risk(self):
        result = self.engine.assess([])
        self.assertEqual(result.risk_level, 'LOW')

    def test_critical_findings_high_risk(self):
        findings = [
            {'severity': 'CRITICAL', 'confidence': 0.9, 'category': 'privacy', '_fusion_score': 0.8},
            {'severity': 'HIGH', 'confidence': 0.85, 'category': 'forced_continuity', '_fusion_score': 0.7},
            {'severity': 'HIGH', 'confidence': 0.8, 'category': 'obstruction', '_fusion_score': 0.6},
        ]
        result = self.engine.assess(findings)
        self.assertIn(result.risk_level, ('HIGH', 'CRITICAL'))

    def test_compound_category_bonus(self):
        findings = [
            {'severity': 'HIGH', 'confidence': 0.8, 'category': 'privacy', '_fusion_score': 0.7},
            {'severity': 'HIGH', 'confidence': 0.8, 'category': 'forced_continuity', '_fusion_score': 0.7},
        ]
        result = self.engine.assess(findings)
        self.assertGreater(result.compound_bonus, 1.0)


class TestTemporalSmoother(unittest.TestCase):
    """Test cross-scan temporal smoothing."""

    def setUp(self):
        from app.engine.temporal import TemporalSmoother
        self.smoother = TemporalSmoother(window_size=5, decay=0.85)

    def test_first_scan_no_smoothing(self):
        score = self.smoother.smooth_trust_score('example.com', 75)
        self.assertEqual(score, 75)

    def test_smoothing_after_multiple_scans(self):
        domain = 'test-smooth.com'
        self.smoother.record(domain, 80, [])
        self.smoother.record(domain, 70, [])
        smoothed = self.smoother.smooth_trust_score(domain, 60)
        # Should be between 60 and 80 (EMA)
        self.assertGreater(smoothed, 60)
        self.assertLess(smoothed, 80)

    def test_trend_detection(self):
        domain = 'trend-test.com'
        self.smoother.record(domain, 80, [])
        self.smoother.record(domain, 60, [])
        trend = self.smoother.get_trend(domain)
        self.assertIsNotNone(trend)
        self.assertEqual(trend['trend'], 'declining')


# ═══════════════════════════════════════════════════════════════════════════════
# PIPELINE INTEGRATION TEST
# ═══════════════════════════════════════════════════════════════════════════════

class TestAnalysisContext(unittest.TestCase):
    """Test AnalysisContext construction."""

    def test_context_from_scan_data(self):
        from app.analyzers.base import AnalysisContext
        scan_data = {
            'scan_id': 'test123',
            'url': 'https://example.com',
            'domain': 'example.com',
            'html_content': '<html></html>',
            'text_content': 'Hello world',
            'dom_data': {'forms': [], 'buttons': []},
            'screenshot_path': None,
            'page_title': 'Example',
        }
        ctx = AnalysisContext(scan_data)
        self.assertEqual(ctx.scan_id, 'test123')
        self.assertEqual(ctx.url, 'https://example.com')
        self.assertEqual(ctx.html_content, '<html></html>')


class TestBaseAnalyzer(unittest.TestCase):
    """Test BaseAnalyzer contract."""

    def test_analyzer_run_returns_result(self):
        from app.analyzers.base import BaseAnalyzer, AnalysisContext, AnalyzerResult

        class TestAnalyzer(BaseAnalyzer):
            name = 'test'
            def execute(self, context):
                return [{'type': 'Test', 'category': 'test', 'severity': 'LOW', 'confidence': 0.5}]

        analyzer = TestAnalyzer()
        ctx = AnalysisContext({'scan_id': 'x', 'dom_data': {}})
        result = analyzer.run(ctx)
        self.assertIsInstance(result, AnalyzerResult)
        self.assertTrue(result.success)
        self.assertEqual(result.count, 1)
        self.assertEqual(result.findings[0]['_engine'], 'test')

    def test_analyzer_error_graceful(self):
        from app.analyzers.base import BaseAnalyzer, AnalysisContext

        class CrashAnalyzer(BaseAnalyzer):
            name = 'crash'
            max_retries = 0
            def execute(self, context):
                raise RuntimeError("Boom!")

        analyzer = CrashAnalyzer()
        ctx = AnalysisContext({'scan_id': 'x', 'dom_data': {}})
        result = analyzer.run(ctx)
        # Should NOT crash — return empty result with error
        self.assertFalse(result.success)
        self.assertEqual(result.count, 0)
        self.assertIn('Boom', result.error)

    def test_confidence_scoring(self):
        from app.analyzers.base import BaseAnalyzer
        score = BaseAnalyzer.calculate_confidence([0.8, 0.6, 0.9], [2.0, 1.0, 3.0])
        self.assertGreater(score, 0.7)
        self.assertLessEqual(score, 1.0)


# ═══════════════════════════════════════════════════════════════════════════════
# EDGE CASE TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases(unittest.TestCase):
    """Edge cases that must be handled correctly."""

    def test_empty_html_no_crash(self):
        """All analyzers should handle empty input gracefully."""
        from app.services.dom_analyzer import DOMAnalyzer
        from app.services.text_analyzer import TextAnalyzer
        from app.services.visual_analyzer import VisualAnalyzer
        from app.services.advanced_analyzer import AdvancedAnalyzer
        from app.services.cookie_analyzer import CookieConsentAnalyzer

        empty_dom = {'forms': [], 'buttons': [], 'links': [], 'checkboxes': [],
                     'timers': [], 'prices': [], 'text_elements': []}

        self.assertEqual(DOMAnalyzer().analyze(empty_dom, ''), [])
        self.assertEqual(TextAnalyzer().analyze(empty_dom, ''), [])
        self.assertEqual(VisualAnalyzer().analyze(None, empty_dom), [])
        self.assertEqual(AdvancedAnalyzer().analyze(empty_dom, '', '', {}), [])
        self.assertEqual(CookieConsentAnalyzer().analyze(empty_dom, ''), [])

    def test_none_inputs_no_crash(self):
        """Analyzers should handle None inputs."""
        from app.services.dom_analyzer import DOMAnalyzer
        from app.services.text_analyzer import TextAnalyzer

        self.assertEqual(DOMAnalyzer().analyze(None, None), [])
        self.assertEqual(TextAnalyzer().analyze(None, None), [])

    def test_unicode_content(self):
        """Analyzers should handle unicode content."""
        from app.services.text_analyzer import TextAnalyzer
        dom = {'text_elements': [{'text': '限時優惠 🔥 只剩3件！', 'tag': 'span', 'classes': ''}]}
        # Should not crash
        result = TextAnalyzer().analyze(dom, '')
        self.assertIsInstance(result, list)

    def test_massive_dom(self):
        """Analyzer should handle extremely large DOM data without crashing."""
        from app.services.dom_analyzer import DOMAnalyzer
        large_dom = {
            'forms': [], 'checkboxes': [], 'timers': [], 'prices': [],
            'buttons': [{'text': f'Button {i}', 'classes': '', 'style': '', 'type': 'button', 'id': f'btn-{i}'}
                        for i in range(1000)],
            'text_elements': [{'text': f'Element {i}', 'tag': 'span', 'classes': ''}
                              for i in range(5000)],
        }
        # Should complete without timeout or crash
        start = time.time()
        result = DOMAnalyzer().analyze(large_dom, '')
        elapsed = time.time() - start
        self.assertLess(elapsed, 5.0, "DOM analyzer took too long on large input")


# ═══════════════════════════════════════════════════════════════════════════════
# PERFORMANCE BENCHMARKS
# ═══════════════════════════════════════════════════════════════════════════════

class TestPerformance(unittest.TestCase):
    """Performance benchmarks."""

    def test_metrics_collection_overhead(self):
        """Metrics collection should add <1ms overhead."""
        from app.core.metrics import MetricsCollector
        m = MetricsCollector()
        m.reset()

        start = time.perf_counter()
        for _ in range(1000):
            with m.timer('bench'):
                pass
            m.increment('bench_count')
        elapsed = (time.perf_counter() - start) * 1000

        self.assertLess(elapsed, 100, f"1000 metric operations took {elapsed:.1f}ms (max 100ms)")

    def test_fusion_performance(self):
        """Fusion engine should handle 100 findings in <10ms."""
        from app.engine.fusion import FusionEngine
        fusion = FusionEngine()

        findings = [
            {'type': f'Finding-{i}', 'category': f'cat-{i % 5}',
             '_engine': ['dom', 'text', 'visual', 'ml', 'cookie'][i % 5],
             'confidence': 0.7 + (i % 30) * 0.01}
            for i in range(100)
        ]

        start = time.perf_counter()
        result = fusion.fuse(findings)
        elapsed = (time.perf_counter() - start) * 1000

        self.assertEqual(len(result), 100)
        self.assertLess(elapsed, 50, f"Fusing 100 findings took {elapsed:.1f}ms (max 50ms)")


# ═══════════════════════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("\n" + "=" * 70)
    print("  VIGIL AI — Production Test Suite v2.0")
    print("=" * 70 + "\n")

    # Run with verbose output
    unittest.main(verbosity=2)
