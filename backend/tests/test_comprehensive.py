"""
Vigil AI — Comprehensive Test Suite (100+ Tests)
==================================================
Covers: All 9 engines, false positives/negatives, edge cases,
HADE pipeline, aggregator consensus, report scoring, and
full integration paths.

Run: cd backend && python -m pytest tests/test_comprehensive.py -v --tb=short
"""
import sys
import os
import math
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.dom_analyzer import DOMAnalyzer
from app.services.text_analyzer import TextAnalyzer
from app.services.cookie_analyzer import CookieConsentAnalyzer
from app.services.readability_analyzer import ReadabilityAnalyzer
from app.services.visual_analyzer import VisualAnalyzer
from app.services.advanced_analyzer import AdvancedAnalyzer
from app.services.behavioral_scorer import BehavioralScorer
from app.services.ml_analyzer import MLAnalyzer
from app.services.link_analyzer import LinkPathAnalyzer
from app.services.decision_engine import HarmAwareDecisionEngine
from app.services.findings_aggregator import FindingsAggregator
from app.services.report_generator import ReportGenerator
from app.services.scanner import WebsiteScanner
from app.services.dom_extractor import extract_dom_data
from app.services.database import save_scan, get_scan, get_history, get_stats
from bs4 import BeautifulSoup


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _empty_dom():
    return {
        'checkboxes': [], 'timers': [], 'prices': [], 'forms': [],
        'buttons': [], 'links': [], 'text_elements': [],
        'cookie_banners': [], 'close_buttons': [], 'modals': [], 'popups': []
    }

def _scan_data(url='https://test.com', scan_state='unknown'):
    return {
        'scan_id': 'test-001', 'url': url, 'domain': 'test.com',
        'page_title': 'Test', 'timestamp': '2026-01-01',
        'screenshot_path': None, 'scan_state': scan_state,
        'html_content': '', 'text_content': '', 'dom_data': _empty_dom(),
        'dynamic_findings': []
    }

def _run_full_pipeline(dom_findings=None, text_findings=None, visual_findings=None,
                       advanced_findings=None, scan_data=None):
    """Simulate the full HADE → Aggregator → Report pipeline."""
    dom_findings = dom_findings or []
    text_findings = text_findings or []
    visual_findings = visual_findings or []
    advanced_findings = advanced_findings or []
    sd = scan_data or _scan_data()

    for f in dom_findings: f['_engine'] = 'dom'
    for f in text_findings: f['_engine'] = 'text'
    for f in visual_findings: f['_engine'] = 'visual'
    for f in advanced_findings: f['_engine'] = 'advanced'

    all_raw = dom_findings + text_findings + visual_findings + advanced_findings
    hade = HarmAwareDecisionEngine()
    all_hade = hade.evaluate(all_raw)

    behavioral = BehavioralScorer().analyze(all_hade, '', {})
    for f in behavioral: f['_engine'] = 'behavioral'
    all_combined = all_hade + behavioral

    all_hade2 = hade.evaluate(all_combined)
    agg = FindingsAggregator()
    clean = agg.aggregate(all_hade2, page_text=sd.get('text_content', ''))

    dom_c = [f for f in clean if f.get('_engine') == 'dom']
    text_c = [f for f in clean if f.get('_engine') == 'text']
    vis_c = [f for f in clean if f.get('_engine') == 'visual']
    adv_c = [f for f in clean if f.get('_engine') not in ('dom', 'text', 'visual')]

    rg = ReportGenerator()
    report = rg.generate_report(sd, dom_c, text_c, vis_c, adv_c)
    return report, clean


# ═══════════════════════════════════════════════════════════════════════════════
#  1. DOM ANALYZER — FALSE POSITIVES
# ═══════════════════════════════════════════════════════════════════════════════

class TestDomFalsePositives:
    def setup_method(self):
        self.da = DOMAnalyzer()

    def test_remember_me_checkbox_not_flagged(self):
        dom = {**_empty_dom(), 'checkboxes': [{'checked': True, 'label': 'Remember me', 'name': 'rem'}]}
        assert self.da.analyze(dom, '') == []

    def test_accept_terms_checkbox_not_flagged(self):
        """'I accept the terms' is NOT marketing — must not flag."""
        dom = {**_empty_dom(), 'checkboxes': [{'checked': True, 'label': 'I accept the terms of service', 'name': 'tos'}]}
        # This should NOT match marketing keywords
        r = self.da.analyze(dom, '')
        marketing = [f for f in r if 'Marketing' in f.get('type', '')]
        assert len(marketing) == 0, "False positive: flagged 'accept terms' as marketing"

    def test_unchecked_newsletter_checkbox_not_flagged(self):
        dom = {**_empty_dom(), 'checkboxes': [{'checked': False, 'label': 'Subscribe to newsletter', 'name': 'nl'}]}
        assert self.da.analyze(dom, '') == []

    def test_single_price_not_drip_pricing(self):
        dom = {**_empty_dom(), 'prices': [{'text': '$29.99', 'classes': 'price'}]}
        r = self.da.analyze(dom, '')
        drip = [f for f in r if 'Drip' in f.get('type', '')]
        assert len(drip) == 0, "False positive: single price flagged as drip pricing"

    def test_two_prices_not_drip_pricing(self):
        dom = {**_empty_dom(), 'prices': [
            {'text': '$29.99', 'classes': 'price'},
            {'text': '$19.99', 'classes': 'price'}
        ]}
        r = self.da.analyze(dom, '')
        drip = [f for f in r if 'Drip' in f.get('type', '')]
        assert len(drip) == 0, "False positive: 2 prices flagged as drip (needs 3+)"

    def test_normal_button_not_confirmshaming(self):
        dom = {**_empty_dom(), 'buttons': [
            {'text': 'No thanks', 'classes': '', 'style': '', 'type': 'button', 'id': 'btn1'}
        ]}
        r = self.da.analyze(dom, '')
        shame = [f for f in r if r and 'confirmshaming' in f.get('category', '')]
        assert len(shame) == 0, "False positive: 'No thanks' flagged as confirmshaming"

    def test_timer_without_urgency_keywords_not_flagged(self):
        dom = {**_empty_dom(), 'timers': [{'text': 'Session timer: 30:00', 'tag': 'div', 'classes': 'timer'}]}
        r = self.da.analyze(dom, '')
        assert len(r) == 0, "False positive: session timer flagged as urgency"


# ═══════════════════════════════════════════════════════════════════════════════
#  2. DOM ANALYZER — FALSE NEGATIVES
# ═══════════════════════════════════════════════════════════════════════════════

class TestDomFalseNegatives:
    def setup_method(self):
        self.da = DOMAnalyzer()

    def test_newsletter_checkbox_detected(self):
        dom = {**_empty_dom(), 'checkboxes': [{'checked': True, 'label': 'Subscribe to newsletter', 'name': 'sub'}]}
        assert len(self.da.analyze(dom, '')) >= 1

    def test_promotional_checkbox_detected(self):
        dom = {**_empty_dom(), 'checkboxes': [{'checked': True, 'label': 'Send me promotional offers', 'name': 'promo'}]}
        assert len(self.da.analyze(dom, '')) >= 1

    def test_subscription_checkbox_detected(self):
        dom = {**_empty_dom(), 'checkboxes': [{'checked': True, 'label': 'Start your free trial membership', 'name': 'trial'}]}
        r = self.da.analyze(dom, '')
        assert len(r) >= 1
        assert any('Subscription' in f.get('type', '') for f in r)

    def test_upsell_checkbox_detected(self):
        dom = {**_empty_dom(), 'checkboxes': [{'checked': True, 'label': 'Add insurance protection', 'name': 'ins'}]}
        r = self.da.analyze(dom, '')
        assert len(r) >= 1

    def test_drip_pricing_three_prices(self):
        dom = {**_empty_dom(), 'prices': [
            {'text': '$9.99', 'classes': 'price'},
            {'text': '$2.99 fee', 'classes': 'price'},
            {'text': '$1.50 tax', 'classes': 'price'}
        ]}
        # Drip pricing requires checkout/cart context to avoid FP on comparison pages
        html = '<div class="cart"><h2>Your Order</h2></div>'
        r = self.da.analyze(dom, html)
        assert any('Drip' in f.get('type', '') for f in r)

    def test_confirmshaming_guilting_text(self):
        dom = {**_empty_dom(), 'buttons': [
            {'text': "No, I don't want to save money", 'classes': '', 'style': '', 'type': 'button', 'id': 'decline'}
        ]}
        r = self.da.analyze(dom, '')
        assert any('confirmshaming' in f.get('category', '') for f in r)

    def test_basket_sneaking_cart_hidden_field(self):
        dom = {**_empty_dom(), 'forms': [
            {'inputs': [{'type': 'hidden', 'value': 'add-to-cart', 'name': 'cart_action'}], 'text': ''}
        ]}
        r = self.da.analyze(dom, '')
        assert any('Basket' in f.get('type', '') for f in r)

    def test_urgency_timer_with_keyword(self):
        dom = {**_empty_dom(), 'timers': [
            {'text': 'Hurry! Limited offer ends soon', 'tag': 'div', 'classes': 'countdown'}
        ]}
        r = self.da.analyze(dom, '')
        assert len(r) >= 1
        assert r[0]['category'] == 'urgency'


# ═══════════════════════════════════════════════════════════════════════════════
#  3. TEXT ANALYZER — FALSE POSITIVES
# ═══════════════════════════════════════════════════════════════════════════════

class TestTextFalsePositives:
    def setup_method(self):
        self.ta = TextAnalyzer()

    def test_generic_urgency_no_context_suppressed(self):
        dom = {'text_elements': [{'text': 'Limited time deal on our blog', 'tag': 'p', 'classes': ''}]}
        r = self.ta.analyze(dom, 'Limited time deal on our blog')
        assert len(r) == 0, f"False positive: {len(r)} findings for generic phrase"

    def test_last_chance_headline_no_number(self):
        dom = {'text_elements': [{'text': 'Last chance to read this article', 'tag': 'h2', 'classes': ''}]}
        assert self.ta.analyze(dom, 'Last chance to read this article') == []

    def test_selling_fast_no_price_context(self):
        dom = {'text_elements': [{'text': 'Our new album is selling fast', 'tag': 'p', 'classes': ''}]}
        assert self.ta.analyze(dom, 'Our new album is selling fast') == []

    def test_numeric_mention_without_action_context(self):
        dom = {'text_elements': [{'text': 'Only 5 copies of this edition were printed', 'tag': 'p', 'classes': ''}]}
        r = self.ta.analyze(dom, 'Only 5 copies of this edition were printed')
        assert len(r) == 0, "False positive: numeric statement without commerce context"

    def test_empty_text_elements(self):
        assert self.ta.analyze({'text_elements': []}, '') == []


# ═══════════════════════════════════════════════════════════════════════════════
#  4. TEXT ANALYZER — FALSE NEGATIVES
# ═══════════════════════════════════════════════════════════════════════════════

class TestTextFalseNegatives:
    def setup_method(self):
        self.ta = TextAnalyzer()

    def test_numeric_scarcity_with_price(self):
        dom = {'text_elements': [{'text': 'Only 2 rooms left! Book now for $99/night', 'tag': 'div', 'classes': ''}]}
        r = self.ta.analyze(dom, 'Only 2 rooms left! Book now for $99/night')
        assert len(r) >= 1

    def test_numeric_scarcity_with_cta(self):
        dom = {'text_elements': [{'text': 'Only 3 left in stock - order now', 'tag': 'span', 'classes': ''}]}
        r = self.ta.analyze(dom, 'Only 3 left in stock - order now')
        assert len(r) >= 1

    def test_social_proof_with_price(self):
        dom = {'text_elements': [{'text': '15 people viewing this $49.99 item', 'tag': 'span', 'classes': ''}]}
        r = self.ta.analyze(dom, '15 people viewing this $49.99 item')
        assert len(r) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
#  5. COOKIE ANALYZER — FP / FN
# ═══════════════════════════════════════════════════════════════════════════════

class TestCookieFP:
    def setup_method(self):
        self.ca = CookieConsentAnalyzer()

    def test_accept_reject_both_present_no_finding(self):
        html = '<div>We use cookies. <button>Accept all</button> <button>Reject all</button></div>'
        assert self.ca.analyze({}, html) == []

    def test_no_cookie_context_no_finding(self):
        html = '<div><button>Accept</button><button>Decline</button></div>'
        r = self.ca.analyze({}, html)
        # No cookie/consent/gdpr context → should not flag
        assert len(r) == 0, "False positive: flagged accept button without cookie context"

    def test_page_with_no_banner_no_finding(self):
        html = '<html><body><p>Welcome to our site</p></body></html>'
        assert self.ca.analyze({}, html) == []


class TestCookieFN:
    def setup_method(self):
        self.ca = CookieConsentAnalyzer()

    def test_accept_only_is_critical(self):
        html = '<div class="cookie-banner">We use cookies. <button>Accept all cookies</button></div>'
        r = self.ca.analyze({}, html)
        assert len(r) == 1
        assert r[0]['severity'] == 'CRITICAL'

    def test_hidden_reject_detected(self):
        html = '<div class="cookie-consent">We use cookies. Accept cookies <a>Manage cookie settings</a></div>'
        r = self.ca.analyze({}, html)
        assert len(r) == 1
        assert r[0]['subtype'] == 'hidden_reject'

    def test_empty_html_no_crash(self):
        assert self.ca.analyze({}, '') == []
        assert self.ca.analyze({}, None) == []


# ═══════════════════════════════════════════════════════════════════════════════
#  6. VISUAL ANALYZER — FP / FN
# ═══════════════════════════════════════════════════════════════════════════════

class TestVisualFP:
    def setup_method(self):
        self.va = VisualAnalyzer()

    def test_no_buttons_no_misdirection(self):
        dom = {**_empty_dom()}
        assert self.va.analyze(None, dom) == []

    def test_two_equal_buttons_no_misdirection(self):
        dom = {**_empty_dom(), 'buttons': [
            {'text': 'Accept', 'classes': 'btn-primary cta', 'style': '', 'type': 'button', 'id': ''},
            {'text': 'Decline', 'classes': 'btn-primary cta', 'style': '', 'type': 'button', 'id': ''},
        ]}
        r = self.va.analyze(None, dom)
        misdirection = [f for f in r if 'misdirection' in f.get('category', '')]
        assert len(misdirection) == 0

    def test_two_urgent_elements_below_threshold(self):
        dom = {**_empty_dom(), 'buttons': [
            {'text': 'Buy', 'classes': '', 'style': 'color: red', 'type': 'button', 'id': ''},
            {'text': 'Act', 'classes': '', 'style': 'color: red', 'type': 'button', 'id': ''},
        ]}
        r = self.va.analyze(None, dom)
        urgency = [f for f in r if 'urgency' in f.get('category', '').lower()]
        assert len(urgency) == 0, "False positive: only 2 urgency elements (threshold is 3)"


class TestVisualFN:
    def setup_method(self):
        self.va = VisualAnalyzer()

    def test_button_misdirection_detected(self):
        dom = {**_empty_dom(), 'buttons': [
            {'text': 'Accept All', 'classes': 'btn-primary cta', 'style': '', 'type': 'button', 'id': ''},
            {'text': 'No thanks', 'classes': 'ghost muted', 'style': '', 'type': 'button', 'id': ''},
        ]}
        r = self.va.analyze(None, dom)
        assert len(r) == 1
        assert r[0]['category'] == 'visual_misdirection'

    def test_fine_print_legal_link(self):
        dom = {**_empty_dom(), 'links': [
            {'text': 'cancellation fee terms', 'href': '/terms', 'classes': 'small fine-print', 'style': '', 'font_size_hint': 'small'}
        ]}
        r = self.va.analyze(None, dom)
        assert any('Fine Print' in f.get('type', '') for f in r)

    def test_disguised_ad(self):
        dom = {**_empty_dom(), 'text_elements': [
            {'text': 'Top picks from our team', 'tag': 'div', 'classes': 'sponsored native-ad'}
        ]}
        r = self.va.analyze(None, dom)
        assert any('Disguised' in f.get('type', '') for f in r)


# ═══════════════════════════════════════════════════════════════════════════════
#  7. ADVANCED ANALYZER — FP / FN
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdvancedFP:
    def setup_method(self):
        self.aa = AdvancedAnalyzer()
        self.sd = {'url': 'https://example.com'}

    def test_internal_link_not_redirect_funnel(self):
        dom = {**_empty_dom(), 'links': [{'href': 'https://example.com/download', 'text': 'Download'}]}
        r = self.aa.analyze(dom, '', '', self.sd)
        assert not any('Dark Download' in f.get('type', '') for f in r)

    def test_meta_refresh_long_delay_not_flagged(self):
        html = '<html><head><meta http-equiv="refresh" content="60;url=https://example.com"></head></html>'
        r = self.aa.analyze({}, html, '', self.sd)
        assert not any('Meta-Refresh' in f.get('type', '') for f in r)

    def test_no_subscription_context_no_cancel_flag(self):
        html = '<html><body><p>Welcome to our blog about cats</p></body></html>'
        r = self.aa.analyze(_empty_dom(), html, 'Welcome to our blog about cats', self.sd)
        cancel = [f for f in r if 'Cancel' in f.get('type', '')]
        assert len(cancel) == 0, "False positive: cancel obstruction on non-subscription page"


class TestAdvancedFN:
    def setup_method(self):
        self.aa = AdvancedAnalyzer()
        self.sd = {'url': 'https://example.com'}

    def test_redirect_funnel_detected(self):
        dom = {**_empty_dom(), 'links': [{'href': 'https://ad-network.com/track?id=1', 'text': 'Download Now'}]}
        r = self.aa.analyze(dom, '', '', self.sd)
        assert any('Dark Download' in f.get('type', '') for f in r)

    def test_meta_refresh_trap_detected(self):
        html = '<html><head><meta http-equiv="refresh" content="3;url=https://trap.com"></head></html>'
        r = self.aa.analyze({}, html, '', self.sd)
        assert any('Meta-Refresh' in f.get('type', '') for f in r)

    def test_phone_gate_detected(self):
        html = 'Manage your subscription here. To cancel, you must call us at 1-800-TRAP.'
        r = self.aa.analyze(_empty_dom(), html, html, self.sd)
        assert any('Phone-Gate' in f.get('type', '') for f in r)

    def test_hidden_cancellation_path(self):
        html = '<p>Your subscription plan details. Billing monthly at $9.99/month.</p>'
        r = self.aa.analyze(_empty_dom(), html, html, self.sd)
        assert any('Cancel' in f.get('type', '') for f in r)

    def test_subscription_upsell_on_shop_page(self):
        html = '<div class="product">Add to cart $29.99 Subscribe and save 10%</div>'
        sd = {'url': 'https://example.com/shop/product-1'}
        r = self.aa.analyze(_empty_dom(), html, html, sd)
        assert any('Subscription Upsell' in f.get('type', '') for f in r)


# ═══════════════════════════════════════════════════════════════════════════════
#  8. READABILITY ANALYZER
# ═══════════════════════════════════════════════════════════════════════════════

class TestReadabilityFP:
    def setup_method(self):
        self.ra = ReadabilityAnalyzer()

    def test_short_text_no_findings(self):
        assert self.ra.analyze({}, '', 'Hello.') == []

    def test_normal_prose_no_findings(self):
        text = 'We value your privacy. You can control your data through our settings page. '
        assert self.ra.analyze({}, '', text) == []


class TestReadabilityFN:
    def setup_method(self):
        self.ra = ReadabilityAnalyzer()

    def test_forced_arbitration_detected(self):
        text = ('By using this service you waive your right to a class action lawsuit '
                'and agree to binding arbitration. ') * 5
        r = self.ra.analyze({}, '', text)
        arb = [f for f in r if 'Arbitration' in f.get('type', '')]
        assert len(arb) >= 1

    def test_complex_legalese_flagged(self):
        text = ('Notwithstanding the aforementioned provisions, the indemnification obligations '
                'shall survive in perpetuity pursuant to the severability clause hereinafter. ') * 10
        r = self.ra.analyze({}, '', text)
        assert len(r) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
#  9. LINK ANALYZER
# ═══════════════════════════════════════════════════════════════════════════════

class TestLinkAnalyzerFP:
    def setup_method(self):
        self.la = LinkPathAnalyzer()

    def test_internal_download_safe(self):
        dom = {'links': [{'href': '/download/file.pdf', 'text': 'Download'}]}
        assert self.la.analyze(dom, '', 'https://t.com') == []

    def test_same_domain_link_safe(self):
        dom = {'links': [{'href': 'https://t.com/about', 'text': 'About us'}]}
        assert self.la.analyze(dom, '', 'https://t.com') == []


class TestLinkAnalyzerFN:
    def setup_method(self):
        self.la = LinkPathAnalyzer()

    def test_ad_network_download_flagged(self):
        dom = {'links': [{'href': 'https://ad-network.com/download?affiliate=x', 'text': 'Download'}]}
        r = self.la.analyze(dom, '', 'https://t.com')
        assert len(r) == 1
        assert r[0]['category'] == 'misdirection'


# ═══════════════════════════════════════════════════════════════════════════════
#  10. BEHAVIORAL SCORER
# ═══════════════════════════════════════════════════════════════════════════════

class TestBehavioralFP:
    def setup_method(self):
        self.bs = BehavioralScorer()

    def test_empty_no_compound(self):
        assert self.bs.analyze([], '', {}) == []

    def test_single_category_no_compound(self):
        findings = [{'type': 'U1', 'category': 'urgency', 'severity': 'MEDIUM', 'confidence': 0.8, '_engine': 'text'}]
        assert self.bs.analyze(findings, '', {}) == []

    def test_two_same_category_no_compound(self):
        findings = [
            {'type': 'U1', 'category': 'urgency', 'severity': 'MEDIUM', 'confidence': 0.8, '_engine': 'text'},
            {'type': 'U2', 'category': 'urgency', 'severity': 'MEDIUM', 'confidence': 0.7, '_engine': 'dom'},
        ]
        assert self.bs.analyze(findings, '', {}) == []


class TestBehavioralFN:
    def setup_method(self):
        self.bs = BehavioralScorer()

    def test_three_high_harm_triggers_compound(self):
        findings = [
            {'type': 'CW', 'category': 'cookie', 'severity': 'CRITICAL', 'confidence': 0.9, '_engine': 'c'},
            {'type': 'PC', 'category': 'preselection', 'severity': 'HIGH', 'confidence': 0.9, '_engine': 'd'},
            {'type': 'HF', 'category': 'hidden_costs', 'severity': 'HIGH', 'confidence': 0.9, '_engine': 'd'},
        ]
        r = self.bs.analyze(findings, '', {})
        assert len(r) == 1
        assert r[0]['type'] == 'COMPOUND DARK PATTERN'


# ═══════════════════════════════════════════════════════════════════════════════
#  11. HADE (DECISION ENGINE) — COMPREHENSIVE
# ═══════════════════════════════════════════════════════════════════════════════

class TestHADEComprehensive:
    def setup_method(self):
        self.hade = HarmAwareDecisionEngine()

    def test_empty_returns_empty(self):
        assert self.hade.evaluate([]) == []

    def test_low_confidence_dropped(self):
        findings = [{'type': 'x', 'category': 'urgency', 'severity': 'MEDIUM', 'confidence': 0.3, '_engine': 'text'}]
        assert self.hade.evaluate(findings) == []

    def test_low_impact_dropped(self):
        findings = [{'type': 'generic pattern', 'category': 'compound_pattern',
                     'severity': 'LOW', 'confidence': 0.5, '_engine': 'behavioral'}]
        assert self.hade.evaluate(findings) == []

    def test_critical_type_force_upgraded(self):
        findings = [{'type': 'Pre-Selected Marketing Checkbox', 'category': 'preselection',
                     'severity': 'MEDIUM', 'confidence': 0.85, '_engine': 'dom'}]
        r = self.hade.evaluate(findings)
        assert len(r) > 0
        assert r[0]['severity'] in ('HIGH', 'CRITICAL')

    def test_cookie_wall_critical_passes(self):
        findings = [{'type': 'COOKIE_MANIPULATION', 'category': 'cookie_wall',
                     'severity': 'CRITICAL', 'confidence': 0.82, '_engine': 'cookie', '_is_critical': True}]
        r = self.hade.evaluate(findings)
        assert len(r) >= 1
        assert r[0]['severity'] == 'CRITICAL'

    def test_informational_passes_through(self):
        findings = [{'type': 'Info', 'category': 'informational',
                     'severity': 'INFORMATIONAL', 'confidence': 0.9, '_engine': 'ml'}]
        r = self.hade.evaluate(findings)
        assert len(r) == 1

    def test_medium_impact_weak_intent_downgraded(self):
        findings = [{'type': 'Something', 'category': 'nagging', 'severity': 'HIGH',
                     'confidence': 0.8, '_engine': 'visual'}]
        r = self.hade.evaluate(findings)
        if r:
            assert r[0]['severity'] in ('MEDIUM', 'LOW'), "Expected downgrade for weak intent"

    def test_high_impact_strong_intent_upgraded(self):
        findings = [{'type': 'Pre-Selected Marketing Checkbox', 'category': 'preselection',
                     'severity': 'LOW', 'confidence': 0.85, '_engine': 'dom'}]
        r = self.hade.evaluate(findings)
        assert len(r) > 0
        assert r[0]['severity'] in ('HIGH', 'CRITICAL')

    def test_stats_keys_present(self):
        raw = [{'type': 'x', 'category': 'urgency', 'severity': 'MEDIUM', 'confidence': 0.8, '_engine': 'text'}]
        accepted = self.hade.evaluate(raw)
        stats = self.hade.get_stats(raw, accepted)
        for key in ['dropped_count', 'critical_count', 'upgraded_count', 'downgraded_count']:
            assert key in stats

    def test_singleton_urgency_dropped_by_multi_signal(self):
        """Single urgency signal should be dropped by multi-signal gate."""
        findings = [{'type': 'Urgency', 'category': 'urgency', 'severity': 'MEDIUM',
                     'confidence': 0.8, '_engine': 'text'}]
        r = self.hade.evaluate(findings)
        urgency = [f for f in r if f.get('category') == 'urgency']
        assert len(urgency) == 0, "Single urgency signal should be dropped by multi-signal gate"

    def test_weak_signal_fragment_dropped(self):
        findings = [{'type': 'above-average reading complexity score', 'category': 'readability',
                     'severity': 'MEDIUM', 'confidence': 0.8, '_engine': 'readability'}]
        r = self.hade.evaluate(findings)
        assert len(r) == 0, "Weak signal fragment should be filtered"


# ═══════════════════════════════════════════════════════════════════════════════
#  12. FINDINGS AGGREGATOR — COMPREHENSIVE
# ═══════════════════════════════════════════════════════════════════════════════

class TestAggregatorComprehensive:
    def setup_method(self):
        self.agg = FindingsAggregator()

    def test_empty_returns_empty(self):
        assert self.agg.aggregate([]) == []

    def test_low_confidence_filtered(self):
        findings = [{'type': 'x', 'category': 'urgency', 'severity': 'MEDIUM', 'confidence': 0.3, '_engine': 'text'}]
        assert self.agg.aggregate(findings) == []

    def test_critical_failsafe_single_engine_passes(self):
        findings = [{'type': 'COOKIE_MANIPULATION', 'category': 'cookie_wall',
                     'severity': 'CRITICAL', 'confidence': 0.82, '_engine': 'cookie'}]
        r = self.agg.aggregate(findings)
        assert len(r) >= 1

    def test_multi_engine_consensus_passes(self):
        findings = [
            {'type': 'urgency_a', 'category': 'urgency', 'severity': 'MEDIUM', 'confidence': 0.8,
             '_engine': 'text', 'element': 'span.badge'},
            {'type': 'urgency_b', 'category': 'urgency', 'severity': 'MEDIUM', 'confidence': 0.75,
             '_engine': 'dom', 'element': 'div.timer'},
        ]
        r = self.agg.aggregate(findings)
        assert len(r) >= 1, "Multi-engine consensus should pass"

    def test_single_weak_ml_dropped(self):
        findings = [{'type': 'ML something', 'category': 'urgency', 'severity': 'MEDIUM', 'confidence': 0.7,
                     '_engine': 'ml', 'element': 'Page text (ML statistical prediction)',
                     '_signal_strength': 'weak'}]
        r = self.agg.aggregate(findings)
        ml_only = [f for f in r if f.get('_engine') == 'ml']
        assert len(ml_only) == 0, "Single weak ML signal should be dropped"

    def test_per_category_cap_enforced(self):
        findings = []
        for i in range(10):
            findings.append({
                'type': f'urgency_{i}', 'category': 'urgency', 'severity': 'CRITICAL',
                'confidence': 0.9, '_engine': 'dom' if i % 2 == 0 else 'text',
                'element': f'div.urgency-{i}', '_is_critical': True
            })
        r = self.agg.aggregate(findings)
        urgency = [f for f in r if f.get('category') == 'urgency']
        assert len(urgency) <= 4, f"Per-category cap exceeded: {len(urgency)}"

    def test_booking_context_strong_signal_passes(self):
        page_text = 'Hotel room booking for $199/night. Check-in. Check-out. Reserve your room.'
        findings = [{'type': 'Scarcity', 'category': 'urgency', 'severity': 'MEDIUM', 'confidence': 0.78,
                     '_engine': 'text', 'element': 'span.rooms-left', '_signal_strength': 'strong'}]
        r = self.agg.aggregate(findings, page_text=page_text)
        assert len(r) >= 1, "Strong signal in booking context should pass"


# ═══════════════════════════════════════════════════════════════════════════════
#  13. REPORT GENERATOR — SCORING TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestReportScoring:
    def setup_method(self):
        self.rg = ReportGenerator()
        self.sd = _scan_data()

    def test_clean_site_score_95(self):
        r = self.rg.generate_report(self.sd, [], [], [])
        assert r['trust_score'] == 95

    def test_one_high_reduces_score(self):
        dom = [{'type': 'X', 'category': 'preselection', 'severity': 'HIGH',
                'confidence': 0.9, 'description': 'x', 'evidence': 'x',
                'element': 'x', 'recommendation': 'x'}]
        r = self.rg.generate_report(self.sd, dom, [], [])
        assert r['trust_score'] < 95

    def test_critical_finding_severe_penalty(self):
        dom = [{'type': 'Cookie Wall', 'category': 'cookie_wall', 'severity': 'CRITICAL',
                'confidence': 0.9, 'description': 'x', 'evidence': 'x',
                'element': 'x', 'recommendation': 'x'}]
        r = self.rg.generate_report(self.sd, dom, [], [])
        assert r['trust_score'] < 80

    def test_informational_no_penalty(self):
        dom = [{'type': 'Info', 'category': 'informational', 'severity': 'INFORMATIONAL',
                'confidence': 0.9, 'description': 'x', 'evidence': 'x',
                'element': 'x', 'recommendation': 'x'}]
        r = self.rg.generate_report(self.sd, dom, [], [])
        assert r['trust_score'] == 95

    def test_low_severity_no_penalty(self):
        dom = [{'type': 'Low', 'category': 'social_proof', 'severity': 'LOW',
                'confidence': 0.9, 'description': 'x', 'evidence': 'x',
                'element': 'x', 'recommendation': 'x'}]
        r = self.rg.generate_report(self.sd, dom, [], [])
        assert r['trust_score'] == 95

    def test_unauthenticated_caps_at_85(self):
        sd = _scan_data(scan_state='unauthenticated')
        r = self.rg.generate_report(sd, [], [], [])
        assert r['trust_score'] <= 85

    def test_authenticated_clean_reaches_95(self):
        sd = _scan_data(scan_state='authenticated')
        r = self.rg.generate_report(sd, [], [], [])
        assert r['trust_score'] == 95

    def test_grade_letter_A_plus(self):
        r = self.rg.generate_report(self.sd, [], [], [])
        assert r['grade']['letter'] == 'A+'

    def test_required_report_keys(self):
        r = self.rg.generate_report(self.sd, [], [], [])
        for key in ['scan_id', 'url', 'domain', 'trust_score', 'grade', 'risk_level',
                     'findings', 'summary', 'compliance_flags', 'category_breakdown']:
            assert key in r, f"Missing key: {key}"

    def test_risk_level_mapping(self):
        """Test all 4 thresholds."""
        for score, expected in [(95, 'LOW'), (75, 'MODERATE'), (50, 'HIGH'), (20, 'CRITICAL')]:
            rl = self.rg._get_risk_level(score)
            assert rl['level'] == expected, f"Score {score} → {rl['level']}, expected {expected}"

    def test_unauthenticated_summary_note(self):
        sd = _scan_data(scan_state='unauthenticated')
        findings = [{'type': 'T', 'category': 'urgency', 'severity': 'MEDIUM',
                     'confidence': 0.9, 'description': 'x', 'evidence': 'x',
                     'element': 'x', 'recommendation': 'x'}]
        r = self.rg.generate_report(sd, findings, [], [])
        assert 'limited scan' in r['summary'].lower() or 'Limited scan' in r['summary']

    def test_many_findings_score_never_below_5(self):
        findings = [{'type': f'F{i}', 'category': 'privacy', 'severity': 'CRITICAL',
                     'confidence': 0.99, 'description': 'x', 'evidence': 'x',
                     'element': 'x', 'recommendation': 'x'} for i in range(50)]
        r = self.rg.generate_report(self.sd, findings, [], [])
        assert r['trust_score'] >= 5, f"Score went below floor: {r['trust_score']}"


# ═══════════════════════════════════════════════════════════════════════════════
#  14. FULL PIPELINE INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestFullPipeline:

    def test_clean_site_pipeline(self):
        """Zero findings → score 95, grade A+."""
        report, _ = _run_full_pipeline()
        assert report['trust_score'] == 95
        assert report['grade']['letter'] == 'A+'
        assert report['total_patterns'] == 0

    def test_single_critical_cookie_wall_pipeline(self):
        """Cookie wall should survive HADE + aggregator → appears in report."""
        cookie = [{'type': 'COOKIE_MANIPULATION', 'category': 'cookie_wall',
                   'severity': 'CRITICAL', 'confidence': 0.82,
                   'description': 'Accept only', 'evidence': 'Cookie wall',
                   'element': 'Cookie Banner', 'recommendation': 'Add reject',
                   '_is_critical': True}]
        report, clean = _run_full_pipeline(advanced_findings=cookie)
        assert report['total_patterns'] >= 1
        assert report['trust_score'] < 95

    def test_preselected_checkbox_pipeline(self):
        """Pre-checked checkbox survives full pipeline."""
        dom = [{'type': 'Pre-Selected Marketing Checkbox', 'category': 'preselection',
                'severity': 'HIGH', 'confidence': 0.92, 'signal_strength': 'strong',
                'description': 'Checkbox pre-checked', 'evidence': 'Pre-checked',
                'element': 'input[type=checkbox]', 'recommendation': 'Uncheck'}]
        report, clean = _run_full_pipeline(dom_findings=dom)
        assert report['total_patterns'] >= 1

    def test_weak_ml_signal_filtered_in_pipeline(self):
        """ML-only weak urgency signal should NOT appear in final report."""
        ml = [{'type': 'ML urgency', 'category': 'urgency', 'severity': 'MEDIUM',
               'confidence': 0.72, 'description': 'Generic', 'evidence': 'text',
               'element': 'Page text (ML statistical prediction)', 'recommendation': 'Review'}]
        report, clean = _run_full_pipeline(advanced_findings=ml)
        ml_urgency = [f for f in report['findings'] if 'ML urgency' in f.get('type', '')]
        assert len(ml_urgency) == 0, "Weak ML signal leaked into final report"


# ═══════════════════════════════════════════════════════════════════════════════
#  15. SCANNER — DOM EXTRACTION (Playwright-free)
# ═══════════════════════════════════════════════════════════════════════════════

class TestScannerExtraction:
    def setup_method(self):
        self.scanner = WebsiteScanner(screenshot_dir='static/screenshots')

    def test_extract_returns_all_keys(self):
        soup = BeautifulSoup('<html><body><p>Hello</p></body></html>', 'lxml')
        dom = extract_dom_data(soup)
        for key in ['checkboxes', 'timers', 'prices', 'forms', 'buttons', 'links', 'text_elements']:
            assert key in dom

    def test_extract_empty_page(self):
        soup = BeautifulSoup('<html><body></body></html>', 'lxml')
        dom = extract_dom_data(soup)
        assert all(isinstance(v, list) for v in dom.values())

    def test_extract_prechecked_checkbox(self):
        html = '<html><body><input type="checkbox" name="marketing" checked><label for="marketing">Subscribe</label></body></html>'
        soup = BeautifulSoup(html, 'lxml')
        dom = extract_dom_data(soup)
        checked = [c for c in dom['checkboxes'] if c.get('checked')]
        assert len(checked) >= 1

    def test_extract_prices(self):
        html = '<html><body><span class="price">$29.99</span><span class="price">$4.99 fee</span></body></html>'
        soup = BeautifulSoup(html, 'lxml')
        dom = extract_dom_data(soup)
        assert len(dom['prices']) >= 2

    def test_extract_timers(self):
        html = '<html><body><div class="countdown">Offer ends in 10:00</div></body></html>'
        soup = BeautifulSoup(html, 'lxml')
        dom = extract_dom_data(soup)
        assert len(dom['timers']) >= 1

    def test_dom_diff_detects_new_timers(self):
        before = BeautifulSoup('<html><body><p>Normal</p></body></html>', 'lxml')
        after = BeautifulSoup('<html><body><p>Normal</p><div class="countdown">Act now! 05:00</div></body></html>', 'lxml')
        b, a = extract_dom_data(before), extract_dom_data(after)
        assert len(a['timers']) - len(b['timers']) == 1

    def test_dom_diff_no_change_no_finding(self):
        html = '<html><body><p>Static</p></body></html>'
        b = extract_dom_data(BeautifulSoup(html, 'lxml'))
        a = extract_dom_data(BeautifulSoup(html, 'lxml'))
        assert (len(a['timers']) - len(b['timers'])) == 0
        assert (len(a['prices']) - len(b['prices'])) == 0


# ═══════════════════════════════════════════════════════════════════════════════
#  16. DATABASE TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestDatabaseOps:
    def test_save_and_retrieve(self):
        report = {
            'scan_id': 'pytest-comp-001', 'url': 'https://pytest.com', 'domain': 'pytest.com',
            'trust_score': 77, 'grade': {'letter': 'B'}, 'risk_level': {'label': 'Moderate Risk'},
            'total_patterns': 3, 'timestamp': '2026-03-31', 'findings': []
        }
        save_scan(report)
        r = get_scan('pytest-comp-001')
        assert r is not None
        assert r['trust_score'] == 77

    def test_history_returns_list(self):
        assert isinstance(get_history(), list)

    def test_stats_keys(self):
        s = get_stats()
        for key in ['total_scans', 'avg_trust_score', 'high_risk_count']:
            assert key in s


# ═══════════════════════════════════════════════════════════════════════════════
#  17. ML ANALYZER — EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════════

class TestMLEdgeCases:
    def setup_method(self):
        self.ml = MLAnalyzer()

    def test_empty_text_no_crash(self):
        assert self.ml.analyze('') == []

    def test_none_text_no_crash(self):
        assert self.ml.analyze(None) == []

    def test_very_short_text_ignored(self):
        assert self.ml.analyze('Hi.') == []

    def test_dom_data_none_no_crash(self):
        """ML with None dom_data must not crash even if model predicts."""
        r = self.ml.analyze('This is a test sentence that is long enough.', dom_data=None)
        assert isinstance(r, list)


# ═══════════════════════════════════════════════════════════════════════════════
#  18. EDGE CASES ACROSS ALL ENGINES
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_dom_analyzer_none_input(self):
        assert DOMAnalyzer().analyze(None, '') == []

    def test_dom_analyzer_empty_dict(self):
        assert DOMAnalyzer().analyze({}, '') == []

    def test_visual_analyzer_none_inputs(self):
        assert VisualAnalyzer().analyze(None, None) == []

    def test_cookie_analyzer_none_html(self):
        assert CookieConsentAnalyzer().analyze({}, None) == []

    def test_cookie_analyzer_empty_html(self):
        assert CookieConsentAnalyzer().analyze({}, '') == []

    def test_advanced_analyzer_all_none(self):
        assert AdvancedAnalyzer().analyze(None, None, None, None) == []

    def test_behavioral_empty_everything(self):
        assert BehavioralScorer().analyze([], '', {}) == []

    def test_hade_empty(self):
        assert HarmAwareDecisionEngine().evaluate([]) == []

    def test_aggregator_empty(self):
        assert FindingsAggregator().aggregate([]) == []

    def test_report_no_findings_has_summary(self):
        r = ReportGenerator().generate_report(_scan_data(), [], [], [])
        assert 'no dark patterns' in r['summary'].lower()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
