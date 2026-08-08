"""
Vigil AI — Visual Analyzer
Checks DOM element styling for visual dark patterns: contrast manipulation,
small fine-print, visually disguised ads, and deceptive button misdirection.
Does NOT require a screenshot — operates on inline styles and class names.
"""

import re


class VisualAnalyzer:
    """Detects visual/CSS-based dark pattern signals from DOM styling."""

    # CSS classes or keywords that suggest reduced visibility (fine print)
    FINE_PRINT_KEYWORDS = ['fine-print', 'fine_print', 'disclaimer', 'footnote',
                           'text-xs', 'text-xxs', 'small-print', 'legal-text',
                           'caption', 'helper', 'muted', 'subdued']

    # Ad disguise patterns — editorial/content wrapper class names
    AD_DISGUISE_KEYWORDS = ['sponsored', 'native-ad', 'partner-content', 'promoted',
                            'advertisement', 'advertorial', 'paid-placement']

    # Urgency color abuse — red/orange styling on non-error elements
    # Only match actual reds/oranges: #e[0-5]xxxx, #f[0-9a]xxxx — NOT grays like #eee, #ede
    URGENCY_COLOR_STYLES = [r'color\s*:\s*red', r'color\s*:\s*#e[0-5][0-9a-f]',
                             r'color\s*:\s*#f[0-9a][0-9a-f]',
                             r'background.*:.*red', r'background.*#e[0-5][0-9a-f]']

    def analyze(self, screenshot_path, dom_data):
        findings = []
        if not dom_data:
            return findings

        self._check_fine_print(dom_data, findings)
        self._check_disguised_ads(dom_data, findings)
        self._check_button_misdirection(dom_data, findings)
        self._check_urgency_colors(dom_data, findings)
        return findings

    # ── Checks ────────────────────────────────────────────────────────────────

    def _check_fine_print(self, dom_data, findings):
        """Detect important terms hidden in abnormally small text."""
        legal_keywords = ['fee', 'charge', 'subscription', 'cancel', 'renewal',
                          'binding', 'arbitration', 'waiver', 'liability', 'terms']
        for link in dom_data.get('links', []):
            if link.get('font_size_hint') == 'small':
                text = link.get('text', '').lower()
                if any(kw in text for kw in legal_keywords):
                    findings.append({
                        'type': 'Fine Print Legal Link',
                        'category': 'visual_obstruction',
                        'severity': 'MEDIUM',
                        'confidence': 0.78,
                        'signal_strength': 'moderate',
                        'description': (
                            'A legally significant link (fees, cancellation, terms) is styled '
                            'in small text, reducing its visibility to users.'
                        ),
                        'evidence': f'Small-text link: "{link.get("text", "")[:150]}"',
                        'element': f'a.{link.get("classes","").replace(" ",".")}',
                        'recommendation': (
                            'Legal and fee-related disclosures must be presented in a size '
                            'equal to the surrounding text. WCAG 2.1 SC 1.4.3 requires '
                            'adequate contrast and readability for all text.'
                        ),
                        'legal_refs': ['WCAG 2.1 SC 1.4.3', 'FTC Clear and Conspicuous Standard'],
                    })

    def _check_disguised_ads(self, dom_data, findings):
        """Detect ads styled to look like organic editorial content."""
        seen = set()
        for el in dom_data.get('text_elements', []):
            classes = el.get('classes', '').lower()
            for kw in self.AD_DISGUISE_KEYWORDS:
                if kw in classes and kw not in seen:
                    seen.add(kw)
                    findings.append({
                        'type': 'Disguised Advertisement',
                        'category': 'disguised_ads',
                        'severity': 'MEDIUM',
                        'confidence': 0.80,
                        'signal_strength': 'moderate',
                        'description': (
                            f'An element with class "{kw}" appears to present advertising '
                            'content as editorial or navigation, violating FTC disclosure rules.'
                        ),
                        'evidence': f'Element class: {classes[:200]}',
                        'element': f'{el.get("tag","div")}.{classes.replace(" ",".")}',
                        'recommendation': (
                            'Sponsored or paid content must be clearly labelled as '
                            '"Advertisement" or "Sponsored" in a visually distinct way '
                            'per FTC Native Advertising Guidelines.'
                        ),
                        'legal_refs': ['FTC Native Advertising Guidelines', 'ASA CAP Rule 2.1'],
                    })

    def _check_button_misdirection(self, dom_data, findings):
        """Detect visually muted/hidden decline buttons vs visually dominant accept buttons."""
        buttons = dom_data.get('buttons', [])
        accept_keywords = ['accept', 'agree', 'buy', 'subscribe', 'sign up', 'join', 'confirm']
        reject_keywords = ['no thanks', 'decline', 'cancel', 'reject', 'skip', "i'll pass"]

        accept_prominent = 0
        reject_muted = 0

        for btn in buttons:
            text = btn.get('text', '').lower()
            style = btn.get('style', '').lower()
            classes = btn.get('classes', '').lower()

            if any(kw in text for kw in accept_keywords):
                # Check if it is styled prominently (button, primary, etc.)
                if any(kw in classes or kw in style for kw in ['primary', 'btn-primary', 'btn-success', 'cta']):
                    accept_prominent += 1

            if any(kw in text for kw in reject_keywords):
                if any(kw in classes or kw in style for kw in ['link', 'ghost', 'text-only', 'muted', 'faded', 'secondary']):
                    reject_muted += 1

        if accept_prominent >= 1 and reject_muted >= 1:
            findings.append({
                'type': 'Button Visual Misdirection',
                'category': 'visual_misdirection',
                'severity': 'MEDIUM',
                'confidence': 0.75,
                'signal_strength': 'moderate',
                'description': (
                    'Consent acceptance button is visually dominant while the decline '
                    'option is styled as a muted link or ghost button, creating a '
                    'visual hierarchy that pressures users toward acceptance.'
                ),
                'evidence': (
                    f'{accept_prominent} prominent accept button(s) paired with '
                    f'{reject_muted} muted/link-styled decline option(s).'
                ),
                'element': 'Button pair (visual hierarchy)',
                'recommendation': (
                    'Consent accept and decline options must have equivalent visual weight. '
                    'A visually dominant accept vs. hidden decline fails GDPR Art. 7.'
                ),
                'legal_refs': ['GDPR Art. 7', 'WCAG 2.1 SC 1.4.3', 'FTC Clear and Conspicuous Standard'],
            })

    def _check_urgency_colors(self, dom_data, findings):
        """Detect overuse of red/orange urgency coloring on non-error text."""
        urgency_count = 0
        for btn in dom_data.get('buttons', []):
            style = btn.get('style', '').lower()
            if any(re.search(p, style) for p in self.URGENCY_COLOR_STYLES):
                urgency_count += 1
        for el in dom_data.get('text_elements', []):
            classes = el.get('classes', '').lower()
            if 'urgent' in classes or 'danger' in classes or 'alert' in classes:
                urgency_count += 1

        if urgency_count >= 3:
            findings.append({
                'type': 'Urgency Color Saturation',
                'category': 'visual_urgency',
                'severity': 'LOW',
                'confidence': 0.68,
                'signal_strength': 'moderate',
                'description': (
                    f'{urgency_count} elements use red/orange urgency coloring. '
                    'Overuse of urgency colors outside genuine error/warning contexts '
                    'is a psychological pressure tactic.'
                ),
                'evidence': f'{urgency_count} urgency-colored elements detected.',
                'element': 'Multiple elements',
                'recommendation': (
                    'Reserve red/orange colors for genuine alerts and errors. '
                    'Using urgency colors for promotional content violates ASA CAP Rule 3.1.'
                ),
                'legal_refs': ['ASA CAP Rule 3.1', 'FTC .com Disclosures'],
            })
