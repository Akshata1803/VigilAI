"""
Vigil AI — Advanced Analyzer
==============================
Detects structural dark patterns that require HTML + DOM + URL inspection
rather than individual element scanning:

  1. Redirect / affiliate funnel chains
     — download pages that route through ad-networks or affiliate trackers
       before delivering content

  2. JavaScript content gating
     — pages that require JS interaction (not login) to reveal core content,
       hiding pricing, terms or cancellation behind modals/accordions

  3. Meta-refresh & auto-redirect traps
     — <meta http-equiv="refresh"> used to bypass back-button navigation

  4. Fake download / software bundling signals
     — download button pointing to a third-party host, installer wrapper patterns

  5. Hidden cancellation obstruction
     — cancellation / unsubscribe links buried in footer or absent entirely

NOTE on cloaking:
  Full content-cloaking detection (bot UA vs browser UA diff) requires dual-scan
  infrastructure not yet in the crawler. The checks below use single-scan signals.
  When dual-scan is added, add: content diff analysis here.
"""

import re


class AdvancedAnalyzer:

    # ── Ad-network / affiliate redirect patterns ───────────────────────────────
    _REDIRECT_DOMAINS = re.compile(
        r'(ad-network|doubleclick|clickbank|adf\.ly|linkbucks|shorte\.st'
        r'|go2cloud|afftrack|shareasale|cj\.com|pepperjam|rakuten'
        r'|track\.|redirect\.|go\.|click\.|out\.)', re.I
    )

    # ── Software bundler / PUA installer signal phrases ────────────────────────
    _BUNDLER_SIGNALS = re.compile(
        r'(download\s+manager|download\s+helper|install\s+now|free\s+download'
        r'|download\s+accelerator|recommended\s+software|custom\s+installer'
        r'|bundled\s+with|includes\s+offers|optional\s+offers)', re.I
    )

    # ── Subscription upsell on product / shop pages ───────────────────────────
    _UPSELL_SIGNALS = re.compile(
        r'(subscribe\s+and\s+save|add\s+(apple|amazon|google)\s+(one|prime|pass)'
        r'|free\s+trial.*auto.*renew|auto.?renew|enroll\s+in|sign\s+up\s+for\s+free'
        r'|start\s+(your\s+)?(free\s+)?trial|cancel\s+anytime|no\s+commitment'
        r'|\$\d+\.?\d*/\s*(month|year|mo|yr))', re.I
    )

    # ── Product / shop page signals ──────────────────────────────────────────
    _PRODUCT_PAGE_SIGNALS = (
        '/shop/', '/buy/', '/store/', '/product/', '/cart', '/checkout',
        'add to cart', 'add to bag', 'buy now', 'in stock', 'out of stock',
        'choose your', 'select your',
    )

    # ── JS gate signals: modals and accordion hiding pricing/terms ─────────────
    _JS_GATE_SELECTORS = [
        'modal', 'accordion', 'collapse', 'hidden', 'toggle', 'overlay',
        'show-more', 'read-more', 'expand',
    ]

    # ── Cancellation obstruction keywords ─────────────────────────────────────
    _CANCEL_KEYWORDS = re.compile(
        r'(cancel|unsubscribe|close\s+account|delete\s+account'
        r'|end\s+subscription|stop\s+subscription|opt.?out)', re.I
    )

    # ── Meta-refresh detection ─────────────────────────────────────────────────
    _META_REFRESH = re.compile(
        r'<meta[^>]+http-equiv=["\']refresh["\'][^>]*content=["\'](\d+)', re.I
    )

    def analyze(self, dom_data, html_content, text_content, scan_data):
        """
        Run all advanced structural checks.
        Returns list of finding dicts compatible with the rest of the pipeline.
        """
        findings = []

        if not html_content and not dom_data:
            return findings

        html_lower = (html_content or '').lower()
        url        = (scan_data or {}).get('url', '') if scan_data else ''

        findings += self._check_redirect_funnel(dom_data, html_content, url)
        findings += self._check_meta_refresh_trap(html_content)
        findings += self._check_fake_download(dom_data, html_content, text_content, url)
        findings += self._check_cancellation_obstruction(dom_data, html_lower, text_content)
        findings += self._check_js_content_gating(dom_data, html_lower)
        findings += self._check_subscription_upsell(dom_data, html_lower, text_content, url)

        return findings

    # ── 1. Redirect / affiliate funnel ─────────────────────────────────────────
    def _check_redirect_funnel(self, dom_data, html_content, page_url):
        findings = []
        if not dom_data:
            return findings

        links = dom_data.get('links', [])
        flagged = []
        for link in links:
            href = link.get('href', '')
            text = link.get('text', '').lower()
            if not href:
                continue
            # External link that goes through an ad/affiliate network
            is_external  = href.startswith('http') and not self._same_domain(href, page_url)
            is_ad_chain  = bool(self._REDIRECT_DOMAINS.search(href))
            is_dl_anchor = any(kw in text for kw in ('download', 'get it', 'get now', 'free'))
            if is_external and is_ad_chain and is_dl_anchor:
                flagged.append(href)

        if flagged:
            findings.append({
                'type':           'Dark Download Funnel',
                'category':       'misdirection',
                'severity':       'HIGH',
                'confidence':     0.82,
                'signal_strength':'strong',
                'description':    (
                    'Download link(s) route through an ad-network or affiliate tracker '
                    'before delivering content. Users may be exposed to unwanted software, '
                    'redirects, or data collection before receiving the expected file.'
                ),
                'evidence':       f'Affiliate/ad-network redirect detected: {flagged[0][:120]}',
                'element':        'a[href] (download link)',
                'recommendation': (
                    'Host downloads directly. If using an affiliate link, disclose it clearly '
                    'and do not route through ad-network intermediaries (FTC Native Advertising Guidelines).'
                ),
                'legal_refs':     ['FTC Native Advertising Guidelines', 'FTC Act §5'],
            })
        return findings

    # ── 2. Meta-refresh auto-redirect trap ────────────────────────────────────
    def _check_meta_refresh_trap(self, html_content):
        findings = []
        if not html_content:
            return findings

        match = self._META_REFRESH.search(html_content)
        if match:
            delay = int(match.group(1))
            # Delay of 0–5 seconds is an aggressive redirect; longer delays are less hostile
            if delay <= 5:
                findings.append({
                    'type':           'Meta-Refresh Auto-Redirect',
                    'category':       'obstruction',
                    'severity':       'HIGH',
                    'confidence':     0.88,
                    'signal_strength':'strong',
                    'description':    (
                        f'Page auto-redirects after {delay}s via <meta http-equiv="refresh">. '
                        'This bypasses the browser back button, trapping users in a navigation loop '
                        '— a roach motel obstruction pattern.'
                    ),
                    'evidence':       f'<meta http-equiv="refresh" content="{delay}; ...">',
                    'element':        'meta[http-equiv="refresh"]',
                    'recommendation': (
                        'Remove meta-refresh redirects. Use server-side 301/302 redirects for '
                        'legitimate redirects; do not use them to prevent back-navigation (EU CRD Art. 9).'
                    ),
                    'legal_refs':     ['EU Consumer Rights Directive Art. 9', 'FTC ROSCA Act'],
                })
        return findings

    # ── 3. Fake download / bundler signals ────────────────────────────────────
    def _check_fake_download(self, dom_data, html_content, text_content, page_url):
        findings = []
        combined = (html_content or '') + ' ' + (text_content or '')

        has_bundler_signal = bool(self._BUNDLER_SIGNALS.search(combined))
        if not has_bundler_signal:
            return findings

        # Corroborate: there must also be a download link to a third-party host
        links = (dom_data or {}).get('links', [])
        has_external_dl = any(
            link.get('href', '').startswith('http')
            and not self._same_domain(link.get('href', ''), page_url)
            and any(kw in link.get('text', '').lower() for kw in ('download', 'install', 'get'))
            for link in links
        )

        if has_bundler_signal and has_external_dl:
            findings.append({
                'type':           'Potential Software Bundling / PUA',
                'category':       'hidden_costs',
                'severity':       'HIGH',
                'confidence':     0.75,
                'signal_strength':'moderate',
                'description':    (
                    'Page contains language associated with software bundlers or Potentially '
                    'Unwanted Applications (PUA): optional offers, bundled software, or custom '
                    'installers combined with a third-party download link.'
                ),
                'evidence':       f'Bundler language + external download link detected.',
                'element':        'a[href] + page text',
                'recommendation': (
                    'Do not bundle third-party software without explicit, separate consent for '
                    'each component. Pre-checked bundled offers violate GDPR Art. 7 and FTC Act §5.'
                ),
                'legal_refs':     ['GDPR Art. 7', 'FTC Act §5', 'EU UCPD Art. 7'],
            })
        return findings

    # ── 4. Cancellation obstruction ───────────────────────────────────────────
    # ── Phone-gate cancellation obstruction ─────────────────────────────────
    _PHONE_GATE_PATTERNS = re.compile(
        r'(cancel\s*(by\s*)?(call|calling|phone|telephone|contact)|'
        r'to\s*cancel.*call|call\s*us\s*to\s*cancel|'
        r'cancell?ation\s*(must\s*be\s*)?by\s*(phone|calling|written\s*notice|mail|letter)|'
        r'written\s*notice.*cancel|cancel.*written\s*notice|'
        r'30.day\s*(written\s*)?notice|notice\s*period\s*required)',
        re.I
    )

    def _check_cancellation_obstruction(self, dom_data, html_lower, text_content):
        findings = []
        combined = html_lower + ' ' + (text_content or '').lower()

        # Only relevant if this looks like a subscription / account page
        is_subscription_page = any(kw in combined for kw in [
            'subscription', 'billing', 'your plan', 'manage plan',
            'account settings', 'my account', 'membership',
            'plan', 'plans', 'subscribe', 'upgrade', 'free trial',
            'pro', 'premium', 'pricing', 'current plan',
        ])
        if not is_subscription_page:
            return findings

        has_cancel_keyword = bool(self._CANCEL_KEYWORDS.search(combined))
        if not has_cancel_keyword:
            # Cancellation keyword absent entirely on a subscription page
            findings.append({
                'type':           'Hidden Cancellation Path',
                'category':       'obstruction',
                'severity':       'HIGH',
                'confidence':     0.78,
                'signal_strength':'moderate',
                'description':    (
                    'This page appears to be a subscription or billing management page '
                    'but contains no visible cancellation, unsubscribe, or account-deletion path. '
                    'Users cannot exercise their right to exit without contacting support.'
                ),
                'evidence':       'Subscription context detected; no cancel/unsubscribe link found in page text.',
                'element':        'Page-level (missing cancel link)',
                'recommendation': (
                    'Provide a clearly labelled, self-service cancellation link on account/billing pages. '
                    'Requiring users to call or email to cancel violates FTC ROSCA and EU Consumer Rights Directive.'
                ),
                'legal_refs':     ['FTC ROSCA Act', 'EU Consumer Rights Directive Art. 9', 'UK CRA 2015'],
            })
        else:
            # Cancel keyword present — check if it's buried only in footer / fine print
            links = (dom_data or {}).get('links', [])
            footer_only = all(
                any(cls in str(link.get('classes', '')).lower() for cls in ('footer', 'legal', 'small', 'fine'))
                for link in links
                if self._CANCEL_KEYWORDS.search(link.get('text', ''))
            ) and any(self._CANCEL_KEYWORDS.search(link.get('text', '')) for link in links)

            if footer_only:
                findings.append({
                    'type':           'Buried Cancellation Link',
                    'category':       'obstruction',
                    'severity':       'MEDIUM',
                    'confidence':     0.72,
                    'signal_strength':'moderate',
                    'description':    (
                        'Cancellation or unsubscribe link found only in footer or fine-print area. '
                        'Deliberately obscuring the exit path is a roach motel dark pattern.'
                    ),
                    'evidence':       'Cancel link present only in footer/legal classes.',
                    'element':        'footer a (cancel link)',
                    'recommendation': (
                        'Place the cancellation option prominently in account/billing settings, '
                        'not only in footer legal links (FTC ROSCA Act).'
                    ),
                    'legal_refs':     ['FTC ROSCA Act', 'EU Consumer Rights Directive Art. 9'],
                })
        # Phone-gate: cancellation requires calling or written notice (obstruction)
        combined_text = html_lower + ' ' + (text_content or '').lower()
        if self._PHONE_GATE_PATTERNS.search(combined_text):
            # Only flag on subscription/billing pages
            is_billing_page = any(kw in combined_text for kw in [
                'subscription', 'billing', 'plan', 'membership', '/month', 'per month',
                'trial', 'renew', 'payment', 'account settings',
            ])
            if is_billing_page:
                findings.append({
                    'type':           'Phone-Gate Cancellation',
                    'category':       'obstruction',
                    'severity':       'HIGH',
                    'confidence':     0.82,
                    'signal_strength':'moderate',
                    'description':    (
                        'Cancellation of a subscription or service requires calling customer '
                        'support or providing written notice. Deliberately avoiding self-service '
                        'cancellation is a roach motel obstruction pattern.'
                    ),
                    'evidence':       'Cancellation requires phone/written notice — no self-service path detected.',
                    'element':        'Page text (cancellation policy)',
                    'recommendation': (
                        'Provide a self-service cancellation option in account settings. '
                        'FTC ROSCA Act and EU Consumer Rights Directive Art. 9 require cancellation '
                        'to be as easy as sign-up.'
                    ),
                    'legal_refs':     ['FTC ROSCA Act', 'EU Consumer Rights Directive Art. 9', 'UK CRA 2015'],
                })

        return findings

    # ── 5. JS content gating ──────────────────────────────────────────────────
    def _check_js_content_gating(self, dom_data, html_lower):
        findings = []
        if not dom_data:
            return findings

        # Look for pricing or terms content hidden inside JS-toggle containers
        pricing_in_collapsed = False
        for selector in self._JS_GATE_SELECTORS:
            if selector in html_lower:
                # Check if pricing/fees keywords appear near the JS gate
                pattern = re.compile(
                    rf'({selector})[^{{}}]{{0,300}}(price|fee|cost|charge|total|\$|€|£|per month|per year)',
                    re.I | re.S
                )
                if pattern.search(html_lower):
                    pricing_in_collapsed = True
                    break

        if pricing_in_collapsed:
            findings.append({
                'type':           'Pricing Hidden Behind JS Gate',
                'category':       'hidden_costs',
                'severity':       'MEDIUM',
                'confidence':     0.68,
                'signal_strength':'moderate',
                'description':    (
                    'Pricing or fee information appears to be hidden inside a collapsible, '
                    'modal, or JS-toggled container. Users may not see the full cost '
                    'before committing to an action.'
                ),
                'evidence':       'Price/fee keywords found within JS-gate UI element (modal/accordion/collapse).',
                'element':        'JS-gated container (modal/accordion)',
                'recommendation': (
                    'Display all material pricing information clearly before any purchase commitment. '
                    'Hiding fees in collapsed sections may violate EU Price Indication Directive '
                    'and FTC Act §5 (clear and conspicuous disclosure).'
                ),
                'legal_refs':     ['EU Price Indication Directive', 'FTC Act §5', 'ASA Guidelines'],
            })
        return findings

    # ── 6. Subscription upsell on product/shop pages ─────────────────────────
    def _check_subscription_upsell(self, dom_data, html_lower, text_content, url):
        """Detect subscription or trial upsells embedded inside product/shop pages."""
        findings = []
        combined = html_lower + ' ' + (text_content or '').lower()
        url_lower = (url or '').lower()

        # Is this a product / shop / cart page?
        is_product_page = any(signal in combined or signal in url_lower
                              for signal in self._PRODUCT_PAGE_SIGNALS)
        if not is_product_page:
            return findings

        match = self._UPSELL_SIGNALS.search(combined)
        if not match:
            return findings

        snippet = match.group(0)[:100]
        findings.append({
            'type':           'Subscription Upsell on Product Page',
            'category':       'forced_continuity',
            'severity':       'HIGH',
            'confidence':     0.78,
            'signal_strength':'strong',
            'description':    (
                'A subscription, trial enrolment, or auto-renewing service is being '
                'promoted or pre-selected within a product purchase flow. Users intending '
                'a one-time purchase may unknowingly commit to a recurring charge — '
                'a Forced Continuity dark pattern.'
            ),
            'evidence':       f'Subscription upsell signal detected: "{snippet}"',
            'element':        'Product / checkout page (subscription offer)',
            'recommendation': (
                'Subscription enrolment must be presented as a clearly separate, opt-in '
                'decision with explicit price and renewal terms disclosed before checkout. '
                'Pre-selecting subscriptions or hiding auto-renewal terms violates FTC ROSCA '
                'and EU Consumer Rights Directive Art. 9.'
            ),
            'legal_refs':     [
                'FTC ROSCA Act', 'EU Consumer Rights Directive Art. 9',
                'GDPR Art. 7', 'FTC Act §5',
            ],
        })
        return findings

    # ── Utility ───────────────────────────────────────────────────────────────
    @staticmethod
    def _same_domain(url, page_url):
        """Return True if url is on the same registered domain as page_url."""
        if not url or not page_url:
            return False
        try:
            from urllib.parse import urlparse
            def apex(u):
                host = urlparse(u).netloc.lower().removeprefix('www.')
                parts = host.split('.')
                return '.'.join(parts[-2:]) if len(parts) >= 2 else host
            return apex(url) == apex(page_url)
        except Exception:
            return False
