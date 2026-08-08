"""
Vigil AI — Readability Analyzer
Implements Flesch-Kincaid grade level, jargon density, and forced arbitration detection.
Deliberately complex ToS language is a recognised dark pattern (GDPR Art. 12).
"""

import re
import math


class ReadabilityAnalyzer:
    """Measures text readability and detects deliberately dense legal language."""

    # Legal / compliance jargon that inflates complexity
    JARGON_WORDS = {
        'notwithstanding', 'aforementioned', 'hereinafter', 'indemnify', 'indemnification',
        'arbitration', 'jurisdiction', 'waiver', 'irrevocable', 'perpetual', 'sublicense',
        'pursuant', 'severability', 'liquidated damages', 'force majeure', 'ipso facto',
        'inter alia', 'mutatis mutandis', 'bona fide', 'privity', 'estoppel',
        'unconscionable', 'tortious', 'breach', 'remedies', 'limitation of liability',
    }

    FORCED_ARBITRATION_PATTERNS = [
        re.compile(r'waive.*class.*action'),
        re.compile(r'binding.*arbitration'),
        re.compile(r'mandatory.*arbitration'),
        re.compile(r'arbitration.*agreement'),
        re.compile(r'dispute.*resolution.*arbitration'),
        re.compile(r'you.*waive.*right.*to.*jury'),
    ]

    # Pre-compiled price hike patterns (FIX H-3)
    PRICE_HIKE_PATTERNS = [
        re.compile(r'after\s+\d+\s+(month|year|week)s?,?\s+(price|rate|subscription)\s+(increase|goes?\s+up|rises?\s+to|will\s+be)'),
        re.compile(r'introductory\s+price.*after'),
        re.compile(r'then\s+\$[\d.]+\s*/?\s*(month|year|week)'),
        re.compile(r'price\s+increases?\s+to\s+\$[\d.]+'),
        re.compile(r'regular\s+price\s+of\s+\$[\d.]+'),
        re.compile(r'full\s+price.*after\s+(trial|introductory|promo)'),
    ]

    # Pre-compiled exit fee patterns (FIX H-3)
    EXIT_FEE_PATTERNS = [
        re.compile(r'early\s+(cancellation|termination)\s+fee'),
        re.compile(r'cancellation\s+fee'),
        re.compile(r'termination\s+fee'),
        re.compile(r'50%\s+of\s+remaining'),
        re.compile(r'cancel.*fee\s+applies'),
        re.compile(r'exit\s+fee'),
        re.compile(r'break\s+(clause|fee)'),
    ]

    def analyze(self, dom_data, html_content, text_content):
        findings = []
        if not text_content or len(text_content) < 200:
            return findings

        self._check_readability_score(text_content, findings)
        self._check_jargon_density(text_content, findings)
        self._check_forced_arbitration(text_content, findings)
        self._check_price_hike_clause(text_content, findings)
        self._check_exit_fee_clause(text_content, findings)
        return findings

    # ── Checks ────────────────────────────────────────────────────────────────

    def _syllable_count(self, word):
        """Approximate syllable count using vowel-group heuristic."""
        word = word.lower().strip(".,!?;:")
        if len(word) <= 3:
            return 1
        count = len(re.findall(r'[aeiouy]+', word))
        if word.endswith('e'):
            count -= 1
        return max(count, 1)

    def _flesch_kincaid_grade(self, text):
        """Compute Flesch-Kincaid Grade Level."""
        sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
        words = re.findall(r"[a-zA-Z']+", text)
        if not sentences or not words:
            return 0
        num_s = len(sentences)
        num_w = len(words)
        num_syl = sum(self._syllable_count(w) for w in words)
        # FK Grade = 0.39*(words/sentences) + 11.8*(syllables/words) - 15.59
        grade = 0.39 * (num_w / num_s) + 11.8 * (num_syl / num_w) - 15.59
        return round(grade, 1)

    def _check_readability_score(self, text, findings):
        grade = self._flesch_kincaid_grade(text)
        if grade >= 16:
            findings.append({
                'type': 'Deliberately Complex Legal Language',
                'category': 'obstruction',
                'severity': 'HIGH',
                'confidence': 0.82,
                'signal_strength': 'moderate',
                'description': (
                    f'Flesch-Kincaid Grade Level: {grade} (equivalent to post-graduate reading). '
                    'Deliberately dense Terms of Service or Privacy Policy text makes informed '
                    'consent impossible for average users.'
                ),
                'evidence': f'FK Grade Level: {grade}/20 (college graduate+ required to comprehend)',
                'element': 'Page text (readability analysis)',
                'recommendation': (
                    'Rewrite key consent and terms language to a Grade 8–10 reading level. '
                    'GDPR Art. 12 requires information be in "clear and plain language".'
                ),
                'legal_refs': ['GDPR Art. 12', 'FTC Plain Writing Guidelines', 'EU Consumer Rights Directive'],
            })
        elif grade >= 14:
            findings.append({
                'type': 'Above-Average Reading Complexity',
                'category': 'obstruction',
                'severity': 'MEDIUM',
                'confidence': 0.70,
                'signal_strength': 'weak',
                'description': (
                    f'Flesch-Kincaid Grade Level: {grade} (college level). '
                    'Consent language complexity may impede average user comprehension.'
                ),
                'evidence': f'FK Grade Level: {grade}/20',
                'element': 'Page text (readability analysis)',
                'recommendation': (
                    'Consider simplifying key legal and consent sections to Grade 8–10 level.'
                ),
                'legal_refs': ['GDPR Art. 12'],
            })

    def _check_jargon_density(self, text, findings):
        words = re.findall(r"[a-zA-Z']+", text.lower())
        if not words:
            return
        jargon_hits = [w for w in words if w in self.JARGON_WORDS]
        # Also check 2-word phrases
        text_lower = text.lower()
        multi_word_hits = [
            phrase for phrase in ['liquidated damages', 'force majeure', 'limitation of liability',
                                  'inter alia', 'ipso facto', 'mutatis mutandis', 'binding arbitration',
                                  'class action waiver']
            if phrase in text_lower
        ]
        density = len(jargon_hits) / max(len(words) / 1000, 0.5)  # floor at 500 words to avoid inflation on short text
        if density > 5 or len(multi_word_hits) >= 2:
            findings.append({
                'type': 'High Legal Jargon Density',
                'category': 'obstruction',
                'severity': 'MEDIUM',
                'confidence': 0.75,
                'signal_strength': 'moderate',
                'description': (
                    f'Legal jargon density: {density:.1f} terms per 1000 words. '
                    f'Found: {", ".join(set(jargon_hits[:8] + multi_word_hits))}. '
                    'Excessive legalese obstructs informed user decisions.'
                ),
                'evidence': f'Jargon terms detected: {", ".join(set(jargon_hits[:10] + multi_word_hits))}',
                'element': 'Page text (jargon density analysis)',
                'recommendation': (
                    'Replace technical legal terms with plain-language equivalents '
                    'in user-facing consent, ToS, and privacy sections.'
                ),
                'legal_refs': ['GDPR Art. 12', 'FTC Plain Writing Guidelines'],
            })

    def _check_forced_arbitration(self, text, findings):
        text_lower = text.lower()
        for pattern in self.FORCED_ARBITRATION_PATTERNS:
            if pattern.search(text_lower):
                findings.append({
                    'type': 'Forced Arbitration / Class Action Waiver',
                    'category': 'obstruction',
                    'severity': 'HIGH',
                    'confidence': 0.88,
                    'signal_strength': 'moderate',
                    'description': (
                        'Text contains language waiving user rights to class action lawsuits '
                        'or mandating binding arbitration, severely limiting legal recourse.'
                    ),
                    'evidence': 'Arbitration / class-action waiver language detected in page text.',
                    'element': 'Page text (arbitration detection)',
                    'recommendation': (
                        'Forced arbitration clauses are increasingly challenged by regulators. '
                        'Ensure users are clearly informed of rights being waived and that '
                        'waivers are genuinely consensual per FTC ROSCA guidelines.'
                    ),
                    'legal_refs': ['FTC ROSCA Act', 'EU Consumer Rights Directive Art. 9', 'EU UCPD Art. 6'],
                })
                break  # One finding is sufficient per page

    def _check_price_hike_clause(self, text, findings):
        """Detect introductory pricing that hides a future price increase."""
        text_lower = text.lower()
        for pat in self.PRICE_HIKE_PATTERNS:
            if pat.search(text_lower):
                findings.append({
                    'type':           'Introductory Price / Hidden Future Hike',
                    'category':       'hidden_costs',
                    'severity':       'HIGH',
                    'confidence':     0.82,
                    'signal_strength':'moderate',
                    'description':    (
                        'Pricing uses an introductory rate that increases significantly '
                        'after a set period. The true ongoing cost is buried in fine print.'
                    ),
                    'evidence':       'Introductory price with future price hike clause detected in page text.',
                    'element':        'Page text (pricing fine print)',
                    'recommendation': (
                        'The full, ongoing price must be displayed as prominently as the '
                        'introductory offer. EU Price Indication Directive and FTC Act §5 '
                        'require clear disclosure of the total cost of a subscription.'
                    ),
                    'legal_refs':     ['EU Price Indication Directive', 'FTC Act §5', 'ASA CAP Code 3.1'],
                })
                break  # One finding sufficient

    def _check_exit_fee_clause(self, text, findings):
        """Detect early termination / cancellation fee clauses."""
        text_lower = text.lower()
        for pat in self.EXIT_FEE_PATTERNS:
            if pat.search(text_lower):
                findings.append({
                    'type':           'Early Cancellation / Exit Fee',
                    'category':       'forced_continuity',
                    'severity':       'HIGH',
                    'confidence':     0.88,
                    'signal_strength':'moderate',
                    'description':    (
                        'Contract includes an early cancellation or termination fee, '
                        'trapping users in a subscription against their will.'
                    ),
                    'evidence':       'Early cancellation / exit fee clause detected in page text.',
                    'element':        'Page text (cancellation terms)',
                    'recommendation': (
                        'Cancellation fees must be disclosed prominently before purchase, '
                        'not buried in fine print. FTC ROSCA Act requires simple cancellation '
                        'mechanisms without penalty for standard subscriptions.'
                    ),
                    'legal_refs':     ['FTC ROSCA Act', 'EU Consumer Rights Directive Art. 9', 'UK CRA 2015'],
                })
                break  # One finding sufficient

