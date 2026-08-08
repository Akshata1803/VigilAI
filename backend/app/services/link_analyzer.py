class LinkPathAnalyzer:
    """
    Detects roach motel / journey obstruction patterns by analysing the link
    graph and page-level signals.

    Checks
    ------
    1. Dark Download Funnel  — download link routed through ad/affiliate network
    2. Roach Motel           — easy sign-up, no delete/cancel account path visible
    3. Missing Delete Route  — subscription/account pages with no delete option
    """

    # Known ad / affiliate tracker domain fragments
    _AD_DOMAINS = (
        'ad-network', 'affiliate', 'tracker', 'doubleclick', 'clickbank',
        'adf.ly', 'linkbucks', 'shorte.st', 'go2cloud', 'afftrack',
        'shareasale', 'cj.com', 'pepperjam', 'rakuten',
    )

    # Keywords that strongly signal this is an account/subscription management dashboard
    _ACCOUNT_SIGNALS = (
        'manage plan', 'account settings', 'billing details', 
        'manage subscription', 'payment information', 'update payment method',
    )

    # Keywords that represent a self-service exit path
    _EXIT_KEYWORDS = (
        'delete account', 'close account', 'cancel subscription',
        'unsubscribe', 'deactivate', 'cancel membership', 'opt out', 'opt-out',
    )

    def analyze(self, dom_data, html_content, url):
        findings = []
        links = dom_data.get('links', []) if isinstance(dom_data, dict) else []
        html_lower = (html_content or '').lower()

        findings += self._check_dark_download_funnel(links)
        findings += self._check_roach_motel(links, html_lower)

        return findings

    # ── 1. Dark Download Funnel ────────────────────────────────────────────────
    def _check_dark_download_funnel(self, links):
        findings = []
        for link in links:
            href = link.get('href', '').lower()
            if 'download' not in href:
                continue
            is_internal = href.startswith('/') or href.startswith('#')
            has_ad = any(ad in href for ad in self._AD_DOMAINS)
            if not is_internal and has_ad:
                findings.append({
                    'type': 'Dark Download Funnel',
                    'category': 'misdirection',
                    'severity': 'HIGH',
                    'confidence': 0.85,
                    'signal_strength': 'moderate',
                    'description': (
                        'A download link passes through an external ad-network or affiliate '
                        'tracker before delivering the file. Users may be tracked, profiled, '
                        'or redirected to unwanted content without disclosure.'
                    ),
                    'evidence': f'Download link routes through ad network: {href[:200]}',
                    'element': 'Download Link',
                    'recommendation': (
                        'Serve downloads directly from your own CDN or domain. '
                        'If affiliate tracking is required, disclose it clearly to users '
                        'per FTC Endorsement Guidelines.'
                    ),
                    'legal_refs': ['FTC Act §5', 'FTC Endorsement Guidelines', 'EU UCPD Art. 7'],
                })
        return findings

    # ── 2. Roach Motel — easy in, impossible out ───────────────────────────────
    def _check_roach_motel(self, links, html_lower):
        findings = []

        # Only check pages that look like subscription / account management
        is_account_page = any(kw in html_lower for kw in self._ACCOUNT_SIGNALS)
        if not is_account_page:
            return findings

        # Check if ANY self-service exit path exists in visible link text
        all_link_text = ' '.join(
            link.get('text', '').lower() for link in links
        ) + ' ' + html_lower

        has_exit_path = any(kw in all_link_text for kw in self._EXIT_KEYWORDS)

        if not has_exit_path:
            findings.append({
                'type': 'Roach Motel — No Exit Path',
                'category': 'obstruction',
                'severity': 'HIGH',
                'confidence': 0.80,
                'signal_strength': 'strong',
                'description': (
                    'This appears to be an account or subscription management page, '
                    'but provides no self-service option to cancel, delete, or deactivate '
                    'the account. Users can easily sign up but cannot easily leave — '
                    'a classic "Roach Motel" dark pattern.'
                ),
                'evidence': (
                    'Account/subscription context detected. No "delete account", '
                    '"cancel subscription" or "close account" link found in page.'
                ),
                'element': 'Page-level (missing exit/cancel link)',
                'recommendation': (
                    'Provide a clearly labelled self-service account deletion or subscription '
                    'cancellation option. FTC ROSCA Act and GDPR Art. 17 (Right to Erasure) '
                    'require cancellation to be as easy as sign-up.'
                ),
                'legal_refs': [
                    'FTC ROSCA Act', 'GDPR Art. 17', 'EU Consumer Rights Directive Art. 9',
                ],
            })

        return findings
