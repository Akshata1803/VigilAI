"""
Vigil AI — Findings Aggregator (Consensus-Driven Validation Engine)
=====================================================================
REDESIGNED: This module is now a VALIDATION ENGINE, not just a merger.

Core Principle: NO SINGLE ANALYZER CAN PRODUCE A FINAL FINDING.

Every detection must be validated by:
  • at least 2 independent engines
  OR
  • 1 strong rule + 1 contextual validation
  OR
  • 1 engine with CRITICAL severity + confidence >= 0.6 (failsafe)

Pipeline:
  1. Signal strength classification  — tag each finding: weak / moderate / strong
  2. DOM-selector grouping           — cluster findings that target the same UI element
  3. Consensus gate                  — enforce multi-engine or strong-signal requirement
  4. Weak signal filter              — drop stray ML-only / no-selector / info-only noise
  5. Confidence boost                — reward validated multi-engine findings
  6. Semantic deduplication + cap    — remove near-dupes, cap per-category totals

Context-sensitivity:
  • Booking / hotel pages: sensitivity boost — 2 signals sufficient for detection
  • E-commerce / cart pages: same boost
"""

from collections import defaultdict


# ── Constants ──────────────────────────────────────────────────────────────────
MIN_CONFIDENCE          = 0.60
MAX_PER_CATEGORY        = 4
MAX_COMPOUND            = 2
FAILSAFE_CONFIDENCE     = 0.60

# Patterns always detected if CRITICAL + confidence >= 0.6
# Matches against both finding type (lowercased) and category (lowercased).
# Include all real category/type values actually emitted by the analyzers.
CRITICAL_FAILSAFE_TYPES = {
    # cookie_analyzer emits type='COOKIE_MANIPULATION', category='privacy'
    'cookie_manipulation', 'cookie wall', 'cookie_wall',
    # scanner / cookie_analyzer tracking findings
    'tracking before consent', 'tracking_before_consent', 'tracking',
    # forced continuity / subscription traps
    'forced subscription', 'forced_continuity', 'forced continuity',
    # hidden harm patterns
    'hidden cancellation', 'hidden charges', 'hidden costs',
    # pre-checked consent (dom_analyzer emits category='preselection')
    'pre-checked subscription', 'prechecked_subscription',
    # privacy category itself — cookie_analyzer uses this
    'privacy',
}

BOOKING_CONTEXT_KEYWORDS = [
    'hotel', 'room', 'night', 'check-in', 'check-out', 'availability',
    'book now', 'reserve', 'per night', 'booking',
]
ECOMMERCE_CONTEXT_KEYWORDS = [
    'add to cart', 'cart', 'checkout', 'buy now', 'order', 'shipping',
    'payment', 'purchase', 'basket',
]

# Specialist engines that are the ONLY source for certain categories (FIX C-5)
_SPECIALIST_ENGINES = frozenset({'cookie', 'readability', 'link'})
_SPECIALIST_CATEGORIES = frozenset({
    'privacy', 'cookie_wall', 'forced_continuity',
    'obstruction', 'hidden_costs',
})


class FindingsAggregator:
    """
    Consensus-driven validation engine.
    Call: aggregate(all_findings, engine_tag_map=None, page_text='')
    """

    SEVERITY_RANK = {'CRITICAL': 5, 'HIGH': 4, 'MEDIUM': 3, 'LOW': 2, 'INFORMATIONAL': 1}

    def aggregate(self, all_findings, engine_tag_map=None, page_text=''):
        if not all_findings:
            return []

        context = self._detect_context(page_text)
        candidates = [f for f in all_findings if float(f.get('confidence', 0.0)) >= MIN_CONFIDENCE]
        candidates = [self._tag_signal_strength(f) for f in candidates]
        grouped = self._group_by_element(candidates)
        validated = self._consensus_gate(grouped, context)
        validated = self._weak_signal_filter(validated)
        validated = self._apply_confidence_boost(validated)
        result = self._deduplicate_and_cap(validated)
        return result

    # ── Context detection ──────────────────────────────────────────────────────
    def _detect_context(self, page_text):
        if not page_text:
            return 'generic'
        lower = page_text.lower()
        booking_hits   = sum(1 for kw in BOOKING_CONTEXT_KEYWORDS   if kw in lower)
        ecommerce_hits = sum(1 for kw in ECOMMERCE_CONTEXT_KEYWORDS if kw in lower)
        if booking_hits >= 2:
            return 'booking'
        if ecommerce_hits >= 2:
            return 'ecommerce'
        return 'generic'

    # ── Signal strength tagging ────────────────────────────────────────────────
    def _tag_signal_strength(self, finding):
        """Classify each finding as weak / moderate / strong."""
        f = dict(finding)
        if f.get('_signal_strength') in ('strong', 'moderate', 'weak'):
            return f

        engine = f.get('_engine', '').lower()
        element = f.get('element', '').strip().lower()
        has_selector = bool(element) and element not in (
            'page text (ml statistical prediction)', 'document body', 'whole site', '',
        )

        is_ml_only = ('ml' in engine or engine == 'ml_analyzer')
        is_structural = (
            has_selector
            and any(kw in element for kw in ('#', '.', 'button', 'input', 'form', 'checkbox', 'banner'))
        )
        is_multi_step = 'multi' in str(f.get('type', '')).lower()
        is_visual_dominant = 'visual' in engine and has_selector

        if is_structural or is_multi_step or is_visual_dominant:
            f['_signal_strength'] = 'strong'
        elif is_ml_only and not has_selector:
            f['_signal_strength'] = 'weak'
        elif has_selector or f.get('category') in ('preselection', 'cookie', 'tracking'):
            f['_signal_strength'] = 'moderate'
        else:
            f['_signal_strength'] = 'weak'

        return f

    # ── Group by element ───────────────────────────────────────────────────────
    def _group_by_element(self, findings):
        by_element = defaultdict(lambda: {'sources': set(), 'findings': []})
        for f in findings:
            element = f.get('element', '').strip() or '__no_selector__'
            key = element.lower()
            by_element[key]['selector'] = element
            by_element[key]['sources'].add(f.get('_engine', 'unknown'))
            by_element[key]['findings'].append(f)
        groups = list(by_element.values())
        for g in groups:
            g['findings'].sort(key=lambda x: float(x.get('confidence', 0)), reverse=True)
            g['best'] = g['findings'][0] if g['findings'] else None
        return groups

    # ── Consensus gate ─────────────────────────────────────────────────────────
    def _consensus_gate(self, groups, context):
        """
        Rule priority:
          1. Failsafe: CRITICAL + known harm type + confidence >= threshold → always pass
          2. Multi-engine (>= 2 sources for this element OR same category) → pass
          3. Single strong signal in booking/ecommerce context → pass
          4. Single moderate/strong signal at CRITICAL severity → pass
          5. Compound/behavioral HIGH or CRITICAL → pass
          6. Everything else → discard
        """
        cat_engines = defaultdict(set)
        for g in groups:
            for f in g['findings']:
                cat_engines[f.get('category', 'unknown')].add(f.get('_engine', 'unknown'))

        validated = []
        for g in groups:
            for f in g['findings']:
                category   = f.get('category', 'unknown')
                severity   = f.get('severity', 'LOW')
                confidence = float(f.get('confidence', 0.0))
                signal     = f.get('_signal_strength', 'weak')
                sources    = g['sources']
                cat_src_count = len(cat_engines[category])

                # Rule 1: Critical failsafe
                ftype_lower = f.get('type', '').lower()
                fcat_lower  = category.lower()
                is_critical_type = any(
                    ct in ftype_lower or ct in fcat_lower
                    for ct in CRITICAL_FAILSAFE_TYPES
                )
                if severity == 'CRITICAL' and confidence >= FAILSAFE_CONFIDENCE and is_critical_type:
                    f['_gate_reason'] = 'Failsafe: critical harm type'
                    validated.append(f)
                    continue

                # Rule 1b: HADE-flagged _is_critical at HIGH severity + strong/moderate signal
                # Pre-checked checkboxes, basket sneaking, confirmshaming = structural DOM proof,
                # self-sufficient — no second engine needed to confirm a visible form element.
                if (f.get('_is_critical') and severity in ('HIGH', 'CRITICAL')
                        and confidence >= FAILSAFE_CONFIDENCE and signal in ('strong', 'moderate')):
                    f['_gate_reason'] = 'Failsafe: HADE _is_critical + strong structural signal'
                    validated.append(f)
                    continue

                # Rule 2: Multi-engine consensus
                effective_sources = max(len(sources), cat_src_count)
                if effective_sources >= 2:
                    f['_gate_reason'] = f'Consensus: {effective_sources} engines'
                    validated.append(f)
                    continue

                # Rule 3: Strong or moderate signal in high-risk page context
                if signal in ('strong', 'moderate') and context in ('booking', 'ecommerce'):
                    f['_gate_reason'] = f'{signal.title()} signal in {context} context'
                    validated.append(f)
                    continue

                # Rule 3b: Single verified urgency/social_proof signal in booking/ecommerce context
                if context in ('booking', 'ecommerce') and category in ('urgency', 'social_proof') and confidence >= 0.70:
                    f['_gate_reason'] = f'Context-aware single signal ({category} in {context})'
                    validated.append(f)
                    continue

                # Rule 4: Moderate/strong signal at CRITICAL severity (single engine)
                if signal in ('moderate', 'strong') and severity == 'CRITICAL':
                    f['_gate_reason'] = 'Single-engine CRITICAL with moderate+ signal'
                    validated.append(f)
                    continue

                # Rule 5: Compound/behavioral findings at HIGH+
                if category == 'compound_pattern' and severity in ('HIGH', 'CRITICAL'):
                    f['_gate_reason'] = 'Compound pattern'
                    validated.append(f)
                    continue

                # Rule 5b: Specialized single-engine findings (FIX H-4)
                # Some findings can ONLY come from one specialized engine —
                # cookie walls, arbitration, exit fees, roach motels.
                # These should not be dropped for lack of consensus.
                engine = f.get('_engine', '').lower()
                if (engine in _SPECIALIST_ENGINES
                        and category in _SPECIALIST_CATEGORIES
                        and severity in ('HIGH', 'CRITICAL')
                        and signal in ('moderate', 'strong')
                        and confidence >= 0.70):
                    f['_gate_reason'] = f'Specialist engine ({engine}) with strong evidence'
                    validated.append(f)
                    continue

                # Rule 6: Discard — insufficient evidence

        return validated

    # ── Weak signal global filter ──────────────────────────────────────────────
    def _weak_signal_filter(self, findings):
        """Remove residual noise after consensus gate."""
        kept = []
        for f in findings:
            engine   = f.get('_engine', '').lower()
            signal   = f.get('_signal_strength', 'weak')
            severity = f.get('severity', 'LOW')
            element  = f.get('element', '').strip().lower()
            has_selector = bool(element) and element not in (
                'page text (ml statistical prediction)', 'document body', 'whole site', '',
            )

            is_ml_only = 'ml' in engine

            # Drop ML-only weak signals
            if is_ml_only and signal == 'weak':
                continue

            # Drop INFORMATIONAL findings with no DOM anchor
            if severity == 'INFORMATIONAL' and not has_selector:
                continue

            kept.append(f)
        return kept

    # ── Confidence boost ───────────────────────────────────────────────────────
    def _apply_confidence_boost(self, findings):
        """Tag findings with consensus metadata. Cap severity for single-engine.

        FIX C-2: Confidence values are NO LONGER mutated here.
        Confidence is the engine's probabilistic signal and must be preserved
        for audit trail. Instead, we add '_consensus' metadata and only
        adjust severity for single-engine high-severity findings.
        """
        cat_engines = defaultdict(set)
        for f in findings:
            cat_engines[f.get('category', 'unknown')].add(f.get('_engine', 'unknown'))

        result = []
        for f in findings:
            f_copy = dict(f)
            cat = f.get('category', 'unknown')
            engine_count = len(cat_engines[cat])

            if engine_count >= 2:
                f_copy['_consensus'] = f'Confirmed by {engine_count} engines'
                f_copy['_consensus_engine_count'] = engine_count
            elif engine_count == 1:
                sev = f_copy.get('severity', 'LOW')
                hade_critical = (
                    f_copy.get('_is_critical')
                    or f_copy.get('_gate_reason', '').startswith('Failsafe')
                )
                if sev in ('HIGH', 'CRITICAL') and not hade_critical:
                    f_copy['severity'] = 'MEDIUM'
                    f_copy['_consensus'] = 'Single-engine signal - severity capped at MEDIUM'

            result.append(f_copy)
        return result

    # ── Deduplication + per-category cap ──────────────────────────────────────
    def _deduplicate_and_cap(self, findings):
        by_cat = defaultdict(list)
        for f in findings:
            by_cat[f.get('category', 'unknown')].append(f)

        result = []
        for cat, cat_findings in by_cat.items():
            # a) Dedup by type
            type_best = {}
            for f in cat_findings:
                t = f.get('type', '').strip().lower()
                if t not in type_best or float(f.get('confidence', 0)) > float(type_best[t].get('confidence', 0)):
                    type_best[t] = f
            unique = list(type_best.values())

            # b) Dedup by element
            element_best = {}
            for f in unique:
                elem = f.get('element', '').strip().lower()
                generic = elem in ('page text (ml statistical prediction)', 'document body', 'whole site', '')
                if generic:
                    element_best[str(id(f))] = f
                else:
                    if elem not in element_best or float(f.get('confidence', 0)) > float(element_best[elem].get('confidence', 0)):
                        element_best[elem] = f
            unique = list(element_best.values())

            # c) Dedup by evidence prefix
            seen_ev = {}
            for f in unique:
                ev_key = str(f.get('evidence', ''))[:60].lower().strip()
                if ev_key not in seen_ev:
                    seen_ev[ev_key] = f
                elif float(f.get('confidence', 0)) > float(seen_ev[ev_key].get('confidence', 0)):
                    seen_ev[ev_key] = f
            deduped = list(seen_ev.values())

            # d) Sort: severity desc, confidence desc
            sev_rank = self.SEVERITY_RANK
            deduped.sort(
                key=lambda x: (sev_rank.get(x.get('severity', 'LOW'), 1), float(x.get('confidence', 0))),
                reverse=True,
            )

            # e) Cap
            cap = MAX_COMPOUND if cat == 'compound_pattern' else MAX_PER_CATEGORY
            result.extend(deduped[:cap])

        return result
