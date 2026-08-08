"""
Vigil AI — DOM Structural Analyzer
Detects structural dark patterns: pre-checked boxes, drip pricing, countdown timers,
sneaky opt-ins, fake urgency elements, un-closable popups, and more.
"""

import re


class DOMAnalyzer:
    """Checks HTML DOM structure for dark pattern signals."""

    def analyze(self, dom_data, html_content):
        findings = []
        if not dom_data:
            return findings

        self._check_preselected_checkboxes(dom_data, findings)
        self._check_fake_timers(dom_data, findings)
        self._check_drip_pricing(dom_data, html_content, findings)
        self._check_hidden_fields(dom_data, html_content, findings)
        self._check_deceptive_buttons(dom_data, findings)
        return findings

    # ── Checks ────────────────────────────────────────────────────────────────

    def _check_preselected_checkboxes(self, dom_data, findings):
        """Pre-checked consent/marketing/subscription boxes = GDPR Art. 7 violation."""
        # Marketing and consent opt-ins (GDPR Art. 7)
        marketing_keywords = [
            'newsletter', 'subscribe', 'promotional', 'offers', 'marketing',
            'partner', 'third party', 'agree', 'consent', 'email me', 'sms',
            'updates', 'news', 'communication', 'data sharing', 'share my data',
        ]
        # Subscription / billing enrolment — pre-checking these is a forced_continuity dark pattern
        subscription_keywords = [
            'trial', '/month', 'per month', 'monthly', '/year', 'per year',
            'membership', 'plan', 'subscription', 'renew', 'auto-renew',
            'free delivery', 'premium', 'plus', 'pro plan',
        ]
        # Upsell add-ons (basket sneaking via checkbox)
        upsell_keywords = [
            'add ', 'include ', 'protection', 'insurance', 'warranty', 'upgrade',
            'delivery', 'add-on', 'optional', 'bundle', 'extra', 'boost',
        ]

        for cb in dom_data.get('checkboxes', []):
            if not cb.get('checked'):
                continue
            label = cb.get('label', '').lower()
            elem  = f'input[type=checkbox][name="{cb.get("name","")}"]'

            if any(kw in label for kw in marketing_keywords):
                findings.append({
                    'type': 'Pre-Selected Marketing Checkbox',
                    'category': 'preselection',
                    'severity': 'HIGH',
                    'confidence': 0.92,
                    'signal_strength': 'strong',
                    'description': (
                        'A consent or marketing checkbox is pre-checked by default, '
                        'silently opting users into data sharing without explicit action.'
                    ),
                    'evidence': f'Checkbox pre-checked: "{cb.get("label", "")[:200]}"',
                    'element': elem,
                    'recommendation': (
                        'GDPR Art. 7 requires affirmative consent. '
                        'All marketing and consent checkboxes must default to unchecked.'
                    ),
                    'legal_refs': ['GDPR Art. 7', 'GDPR Art. 7(4)', 'EU ePrivacy Directive Art. 5(3)'],
                })
            elif any(kw in label for kw in subscription_keywords):
                findings.append({
                    'type': 'Pre-Selected Subscription Enrolment',
                    'category': 'forced_continuity',
                    'severity': 'HIGH',
                    'confidence': 0.90,
                    'signal_strength': 'strong',
                    'description': (
                        'A recurring subscription or trial is pre-selected by default. '
                        'Users may be enrolled in a paid plan without realising it.'
                    ),
                    'evidence': f'Subscription checkbox pre-checked: "{cb.get("label", "")[:200]}"',
                    'element': elem,
                    'recommendation': (
                        'Subscription enrolment must never be pre-checked. '
                        'Users must explicitly opt in to any recurring billing. '
                        'FTC ROSCA Act requires clear disclosure and affirmative consent.'
                    ),
                    'legal_refs': ['FTC ROSCA Act', 'GDPR Art. 7', 'EU Consumer Rights Directive Art. 9'],
                })
            elif any(kw in label for kw in upsell_keywords):
                findings.append({
                    'type': 'Pre-Selected Upsell / Add-On',
                    'category': 'preselection',
                    'severity': 'MEDIUM',
                    'confidence': 0.80,
                    'signal_strength': 'strong',
                    'description': (
                        'An add-on, upgrade or upsell is pre-selected by default, '
                        'increasing the total cost without explicit user consent.'
                    ),
                    'evidence': f'Upsell checkbox pre-checked: "{cb.get("label", "")[:200]}"',
                    'element': elem,
                    'recommendation': (
                        'Add-ons and optional extras must default to unchecked. '
                        'EU Consumer Rights Directive Art. 22 prohibits pre-ticked boxes for extras.'
                    ),
                    'legal_refs': ['EU Consumer Rights Directive Art. 22', 'FTC Act §5'],
                })

    def _check_fake_timers(self, dom_data, findings):
        """Countdown timers and fake scarcity urgency."""
        for timer in dom_data.get('timers', []):
            text = timer.get('text', '').lower()
            if any(kw in text for kw in ['limited', 'offer', 'deal', 'sale', 'expire', 'hurry', 'left']):
                findings.append({
                    'type': 'Countdown Timer / Fake Urgency',
                    'category': 'urgency',
                    'severity': 'MEDIUM',
                    'confidence': 0.78,
                    'signal_strength': 'strong',
                    'description': (
                        'A countdown timer or scarcity element detected, designed to '
                        'pressure users into rapid decisions.'
                    ),
                    'evidence': f'Timer element ({timer.get("tag","")}.{timer.get("classes","")}): "{timer.get("text","")[:150]}"',
                    'element': f'{timer.get("tag", "div")}.{timer.get("classes", "")}',
                    'recommendation': (
                        'Ensure countdown timers reflect genuine, verifiable constraints. '
                        'Evergreen "limited time" timers that reset on page reload violate FTC guidelines.'
                    ),
                    'legal_refs': ['ASA CAP Code Rule 3.1', 'FTC Act §5'],
                })

    def _check_drip_pricing(self, dom_data, html_content, findings):
        """Multiple price elements may indicate drip pricing — only in checkout/cart context."""
        prices = dom_data.get('prices', [])
        if len(prices) >= 3:
            # Require checkout/cart/booking context to avoid false positives on pricing pages
            html_lower = (html_content or '').lower()
            checkout_signals = [
                'checkout', 'cart', 'basket', 'order summary', 'subtotal',
                'shipping', 'tax', 'booking', 'payment', 'proceed to',
                'your order', 'order total', 'service fee', 'processing fee',
            ]
            has_checkout_context = any(sig in html_lower for sig in checkout_signals)
            if not has_checkout_context:
                return  # Legitimate pricing/comparison page — skip

            price_texts = [p.get('text', '') for p in prices[:5]]
            findings.append({
                'type': 'Potential Drip Pricing',
                'category': 'hidden_costs',
                'severity': 'MEDIUM',
                'confidence': 0.70,
                'signal_strength': 'moderate',
                'description': (
                    'Multiple price elements detected in a checkout/cart context. Hidden fees '
                    'or charges may be revealed late in the checkout process (drip pricing).'
                ),
                'evidence': f'Price elements: {price_texts}',
                'element': 'Multiple price elements',
                'recommendation': (
                    'Display the full total cost — including taxes, fees, and shipping — '
                    'before users commit to purchase.'
                ),
                'legal_refs': ['EU Price Indication Directive', 'FTC Act §5'],
            })

    def _check_hidden_fields(self, dom_data, html_content, findings):
        """Detect hidden inputs that auto-add items to a cart."""
        html_lower = html_content.lower() if html_content else ''
        for form in dom_data.get('forms', []):
            for inp in form.get('inputs', []):
                if inp.get('type') == 'hidden' and inp.get('value'):
                    val = inp.get('value', '').lower()
                    name = inp.get('name', '').lower()
                    if any(kw in name or kw in val for kw in ['cart', 'add', 'product', 'item', 'upsell']):
                        findings.append({
                            'type': 'Basket Sneaking (Hidden Field)',
                            'category': 'hidden_costs',
                            'severity': 'HIGH',
                            'confidence': 0.80,
                            'signal_strength': 'strong',
                            'description': (
                                'A hidden form field may be silently adding products or '
                                'services to the cart without explicit user consent.'
                            ),
                            'evidence': f'Hidden input name="{inp.get("name","")}" value="{inp.get("value","")[:100]}"',
                            'element': f'input[type=hidden][name="{inp.get("name","")}"]',
                            'recommendation': (
                                'Remove any pre-populated hidden cart fields. '
                                'All cart additions require explicit user action.'
                            ),
                            'legal_refs': ['FTC Act §5', 'EU Consumer Rights Directive'],
                        })

    def _check_deceptive_buttons(self, dom_data, findings):
        """Detect confirmshaming and misdirection button patterns."""
        shame_keywords = [
            "no, i don't want", "no thanks, i prefer", "no, i'll pay full price",
            "no, i hate savings", "no, i'll pass", "i don't want to save",
            "no thanks, i don't want", "no thanks, i'd rather", "no thanks, i prefer not",
            "no, i don't need", "no thanks, i don't need"
        ]
        # NOTE: 'reject' intentionally excluded — plain Reject/Reject all is GDPR-required, not confirmshaming.
        # button is a LEGITIMATE, GDPR-required decline option, not confirmshaming.
        # Confirmshaming requires guilt-laden phrasing (e.g. "No, I hate savings").
        for btn in dom_data.get('buttons', []):
            text = btn.get('text', '').lower()
            if any(kw in text for kw in shame_keywords):
                findings.append({
                    'type': 'Confirmshaming Button',
                    'category': 'confirmshaming',
                    'severity': 'HIGH',
                    'confidence': 0.88,
                    'signal_strength': 'strong',
                    'description': (
                        'A decline button uses guilt-tripping language to psychologically '
                        'shame users for opting out.'
                    ),
                    'evidence': f'Button text: "{btn.get("text", "")[:200]}"',
                    'element': f'button#{btn.get("id","")}'.rstrip('#'),
                    'recommendation': (
                        'Replace confirmshaming copy with neutral decline text like "No thanks" '
                        'or "Close" that does not manipulate through guilt.'
                    ),
                    'legal_refs': ['FTC Act §5', 'EU Unfair Commercial Practices Directive'],
                })
