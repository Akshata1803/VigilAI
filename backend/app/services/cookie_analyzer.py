import re
from bs4 import BeautifulSoup


class CookieConsentAnalyzer:
    """Analyzes cookie consent banners for GDPR compliance issues."""

    # Word-boundary patterns to avoid matching 'acceptable', 'management', etc.
    _ACCEPT_PATTERNS = re.compile(
        r'\b(accept\s*(all|cookies)?|allow\s*(all|cookies)?|i\s*agree|got\s*it|okay|ok)\b',
        re.IGNORECASE
    )
    _REJECT_PATTERNS = re.compile(
        r'\b(reject\s*(all|cookies)?|decline\s*(all|cookies)?|deny|refuse|no\s*thanks)\b',
        re.IGNORECASE
    )
    _SETTINGS_PATTERNS = re.compile(
        r'\b(manage|customize|preferences|settings|cookie\s*settings|more\s*options)\b',
        re.IGNORECASE
    )
    _COOKIE_CONTEXT = re.compile(
        r'\b(cookies?|consent|gdpr|privacy\s*notice|we\s*(use|value)\s*cookies?|tracking)\b',
        re.IGNORECASE
    )

    # Tracking scripts that fire without waiting for user consent
    _TRACKING_SCRIPT_PATTERNS = [
        (r'google-analytics\.com/analytics\.js', 'Google Analytics (UA)'),
        (r'googletagmanager\.com/gtag/js', 'Google Tag Manager / GA4'),
        (r'gtag\s*\(\s*["\']config', 'Google gtag()'),
        (r'connect\.facebook\.net.*fbevents\.js', 'Meta Pixel'),
        (r'fbq\s*\(\s*["\']init', 'Meta Pixel fbq()'),
        (r'static\.hotjar\.com', 'Hotjar'),
        (r'clarity\.ms', 'Microsoft Clarity'),
        (r'fullstory\.com', 'FullStory'),
        (r'cdn\.segment\.com', 'Segment'),
        (r'cdn\.amplitude\.com', 'Amplitude'),
        (r'bat\.bing\.com', 'Bing UET'),
        (r'snap\.licdn\.com', 'LinkedIn Insight'),
        (r'static\.ads-twitter\.com', 'Twitter/X Pixel'),
        (r'tiktok\.com/i18n/pixel', 'TikTok Pixel'),
    ]

    def analyze(self, dom_data, html_content):
        findings = []
        if not html_content:
            return findings

        # Extract visible text from HTML (strip scripts/styles for accurate matching)
        soup = BeautifulSoup(html_content, 'html.parser')
        for tag in soup(['script', 'style', 'meta', 'link']):
            tag.decompose()
        visible_text = soup.get_text(separator=' ', strip=True)

        has_accept   = bool(self._ACCEPT_PATTERNS.search(visible_text))
        has_reject   = bool(self._REJECT_PATTERNS.search(visible_text))
        has_settings = bool(self._SETTINGS_PATTERNS.search(visible_text))
        has_cookie_context = bool(self._COOKIE_CONTEXT.search(visible_text))

        subtype = None
        severity = 'MEDIUM'
        description = ''
        recommendation = ''

        if has_accept and not has_reject and not has_settings and has_cookie_context:
            subtype = 'accept_only'
            severity = 'CRITICAL'
            description = (
                'Cookie banner only offers an Accept option with no reject or settings alternative. '
                'This is a "cookie wall" — GDPR requires freely given, informed, and unambiguous consent, '
                'which is impossible without a genuine refusal option.'
            )
            recommendation = (
                'Add a clearly visible "Reject All" or "Decline" button of equal prominence to "Accept". '
                'GDPR Art. 7 requires consent to be as easy to withdraw as to give.'
            )
        elif has_accept and has_settings and not has_reject and has_cookie_context:
            subtype = 'hidden_reject'
            severity = 'MEDIUM'
            description = (
                'Cookie banner offers Accept and Settings options but no direct Reject button. '
                'Users must navigate settings to reject — a friction tactic that inflates consent rates.'
            )
            recommendation = (
                'Provide a prominent "Reject All" button alongside "Accept" at the banner level, '
                'without requiring multi-step navigation.'
            )
        elif not has_reject and not has_settings and has_cookie_context:
            subtype = 'cookie_wall'
            severity = 'HIGH'
            description = (
                'A cookie or consent reference exists on this page but no reject or manage option '
                'was detected. This may constitute a cookie wall, blocking access unless users accept.'
            )
            recommendation = (
                'Ensure users can access the service even after declining non-essential cookies. '
                'Cookie walls are illegal under GDPR in many EU jurisdictions.'
            )

        if subtype:
            is_critical_subtype = subtype in ('accept_only', 'cookie_wall')
            category = 'cookie_wall' if is_critical_subtype else 'privacy'

            findings.append({
                'type': 'COOKIE_MANIPULATION',
                'category': category,
                'subtype': subtype,
                'severity': severity,
                'confidence': 0.82,
                'signal_strength': 'strong',
                '_is_critical': is_critical_subtype,
                'description': description,
                'evidence': f'Cookie banner detected as: {subtype}. Only "accept" or equivalent found.',
                'element': 'Cookie Banner / Consent Dialog',
                'recommendation': recommendation,
                'legal_refs': ['GDPR Art. 7', 'GDPR Recital 32', 'EU ePrivacy Directive Art. 5(3)'],
            })

        # ── Tracking-before-consent detection ──────────────────────────────────
        # Check for tracking scripts loading in raw HTML before any consent gate
        detected_trackers = []
        for pattern, tracker_name in self._TRACKING_SCRIPT_PATTERNS:
            if re.search(pattern, html_content, re.I):
                detected_trackers.append(tracker_name)

        # Only flag if: trackers present AND (no reject option OR no consent banner at all)
        if detected_trackers and (not has_reject or not has_cookie_context):
            unique_trackers = list(dict.fromkeys(detected_trackers))[:5]  # Dedupe, max 5
            findings.append({
                'type': 'Tracking Before Consent',
                'category': 'privacy',
                'severity': 'HIGH',
                'confidence': 0.85,
                'signal_strength': 'strong',
                '_is_critical': True,
                'description': (
                    f'Detected {len(unique_trackers)} tracking script(s) loading unconditionally '
                    f'without waiting for user consent: {", ".join(unique_trackers)}. '
                    'Under GDPR and the ePrivacy Directive, non-essential tracking requires '
                    'prior informed consent.'
                ),
                'evidence': f'Trackers loading before consent: {", ".join(unique_trackers)}',
                'element': 'script (tracking)',
                'recommendation': (
                    'Defer all non-essential tracking scripts until the user has explicitly '
                    'consented. Use a Consent Management Platform (CMP) that blocks scripts '
                    'by default and only fires after opt-in.'
                ),
                'legal_refs': [
                    'GDPR Art. 6', 'GDPR Recital 32',
                    'EU ePrivacy Directive Art. 5(3)',
                    'CNIL Guidelines on Cookies',
                ],
            })

        return findings

