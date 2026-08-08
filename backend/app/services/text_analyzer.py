"""
Vigil AI — Text Analyzer (Calibrated)
=======================================
FIXED: Only detect urgency/scarcity when BOTH conditions are present:
  1. A numeric value OR specific qualifying phrase
  2. An action context: price / booking / CTA nearby in the same element OR adjacent elements

Examples:
  VALID:   "Only 2 rooms left" + price visible + "Book now" nearby
  INVALID: "Limited time offer" alone → ignored
  VALID:   "Only 3 left in stock" on a product page with price
  INVALID: "Last chance" in a marketing headline with no numeric/price context
"""

import re


class TextAnalyzer:
    # Phrases that require BOTH a numeric value AND an action context to be flagged
    CONDITIONAL_PHRASES = [
        "in high demand",
        "limited time deal",
        "last chance",
        "deal expires soon",
        "selling fast",
        "almost gone",
        "limited availability",
        "don't miss out",
        "hurry",
    ]

    # Standalone urgency patterns — strong enough to flag without numeric context
    STANDALONE_URGENCY_PATTERNS = [
        r'flash\s+sale',
        r'offer\s+ends\s+tonight',
        r'deal\s+ends\s+(at\s+)?midnight',
        r'sale\s+ends\s+today',
        r'today\s+only',
        r'ends\s+in\s+\d+\s*(hours?|minutes?|mins?|hrs?)',
        r'limited\s+time\s+only',
        r'while\s+supplies\s+last',
        r'act\s+now',
        r'last\s+day',
        r'final\s+hours?',
        r'expiring\s+soon',
        r'closing\s+soon',
    ]

    # Numeric scarcity patterns — strong by themselves only when price/CTA context also present
    NUMERIC_PATTERNS = [
        r'only\s+[0-9]+\s+rooms?\s+left',
        r'[0-9]+\s+people\s+viewing',
        r'booked\s+[0-9]+\s+times\s+today',
        r'only\s+[0-9]+\s+left',
        r'[0-9]+\s+remaining',
        r'[0-9]+\s+in\s+stock',
        r'expires?\s+in\s+[0-9]+',
    ]

    # Price context signals
    PRICE_PATTERNS = [
        r'[\$\€\£\₹]\s*[0-9]',
        r'[0-9]+\s*(usd|eur|gbp|inr|per night|/night|/mo)',
        r'\bprice\b',
        r'\bcost\b',
        r'\bfee\b',
    ]

    # Action CTA signals
    CTA_KEYWORDS = [
        'book now', 'book today', 'reserve', 'buy now', 'add to cart',
        'order now', 'get it now', 'checkout', 'subscribe', 'sign up now',
        'claim', 'grab', 'don\'t wait',
    ]

    def analyze(self, dom_data, text_content):
        findings = []
        text_elements = dom_data.get('text_elements', []) if dom_data else []
        seen_evidence = set()

        # Build a window of text from nearby elements for context checking
        all_texts = [el.get('text', '') for el in text_elements if el.get('text')]
        page_context = ' '.join(all_texts).lower()

        def has_price_context(local_text, page_ctx):
            combined = (local_text + ' ' + page_ctx).lower()
            return any(re.search(p, combined) for p in self.PRICE_PATTERNS)

        def has_cta_context(local_text, page_ctx):
            combined = (local_text + ' ' + page_ctx).lower()
            return any(kw in combined for kw in self.CTA_KEYWORDS)

        def check_text(text, element_desc):
            text_lower = text.lower()
            text_key = text_lower.strip()

            if text_key in seen_evidence:
                return

            # ── Path A: Numeric pattern detection ──────────────────────────
            # Numeric scarcity is strong, but we still require price OR CTA context
            for pattern in self.NUMERIC_PATTERNS:
                if re.search(pattern, text_lower):
                    # Need at least one of: price context OR CTA context
                    price_ok = has_price_context(text, page_context)
                    cta_ok   = has_cta_context(text, page_context)
                    if price_ok or cta_ok:
                        seen_evidence.add(text_key)
                        findings.append({
                            'type': 'Numeric Scarcity Claim',
                            'category': 'urgency',
                            'severity': 'MEDIUM',
                            'confidence': 0.88,
                            'signal_strength': 'moderate',
                            'description': (
                                'Numeric scarcity or social proof claim combined with '
                                'price/booking context — designed to manufacture urgency.'
                            ),
                            'evidence': f'"{text.strip()}"',
                            'element': element_desc,
                            'recommendation': (
                                'Ensure numeric scarcity claims reflect real-time inventory data. '
                                'Fabricated counts may violate FTC Act §5 and EU UCPD Art. 7.'
                            ),
                        })
                    # If no action context, silently discard — it's noise
                    return

            # ── Path A2: Standalone urgency patterns — no numeric context required ──
            for pattern in self.STANDALONE_URGENCY_PATTERNS:
                if re.search(pattern, text_lower):
                    seen_evidence.add(text_key)
                    findings.append({
                        'type': 'Standalone Urgency Claim',
                        'category': 'urgency',
                        'severity': 'MEDIUM',
                        'confidence': 0.82,
                        'signal_strength': 'moderate',
                        'description': (
                            'Strong standalone urgency language detected — '
                            'designed to manufacture time pressure on user decisions.'
                        ),
                        'evidence': f'"{text.strip()}"',
                        'element': element_desc,
                        'recommendation': (
                            'Urgency claims must be genuine and verifiable. '
                            'Evergreen "today only" or "flash sale" messaging violates FTC Act §5.'
                        ),
                    })
                    return

            # ── Path B: Conditional phrase detection ────────────────────────
            # Generic phrases are only flagged when BOTH numeric value AND action context are present
            for phrase in self.CONDITIONAL_PHRASES:
                if phrase in text_lower:
                    has_numeric = bool(re.search(r'[0-9]+', text_lower))
                    price_ok    = has_price_context(text, page_context)
                    cta_ok      = has_cta_context(text, page_context)

                    # Require: numeric value AND (price OR CTA)
                    if has_numeric and (price_ok or cta_ok):
                        seen_evidence.add(text_key)
                        findings.append({
                            'type': 'Urgency/Scarcity Messaging',
                            'category': 'urgency',
                            'severity': 'MEDIUM',
                            'confidence': 0.78,
                            'signal_strength': 'moderate',
                            'description': (
                                'Urgency language combined with a numeric claim and '
                                'price/booking context — a dark pattern pressure tactic.'
                            ),
                            'evidence': f'"{text.strip()}"',
                            'element': element_desc,
                            'recommendation': (
                                'Urgency claims must be based on genuine, verifiable constraints. '
                                'Manufactured pressure may breach ASA CAP Code and EU UCPD Art. 7.'
                            ),
                        })
                    # Generic phrase alone ("Limited time offer") → DISCARDED
                    return

        # Analyze short UI fragments only (badges, labels, banners, price tags)
        for el in text_elements:
            text = el.get('text', '')
            if text and len(text) < 250:
                tag     = str(el.get('tag', ''))
                classes = str(el.get('classes', ''))
                selector = tag
                if classes:
                    selector += f" .{classes.replace(' ', '.')}"
                check_text(text, selector)

        return findings
