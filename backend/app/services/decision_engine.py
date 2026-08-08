"""
Vigil AI — Harm-Aware Decision Engine (HADE)
============================================
A calibration layer that sits between raw engine findings and the
FindingsAggregator. Implements an 8-step decision protocol to evaluate
each finding for real-world IMPACT and manipulative INTENT before allowing
it to influence the final report or trust score.

Step 1  Impact scoring          HIGH / MEDIUM / LOW
Step 2  Intent validation       STRONG / MODERATE / WEAK
Step 3  Decision logic          filter / downgrade / upgrade
Step 4  Critical pattern boost  force CRITICAL, low confidence OK
Step 5  Weak signal filter       generic text, normal disclosures
Step 6  Multi-signal validation  MEDIUM patterns need >= 2 signals
Step 7  Severity recalibration   align to real-world harm tier
Step 8  Trust score protection   only HIGH/CRITICAL hurt the score
"""

from __future__ import annotations

from app.core.logger import get_logger
from collections import defaultdict
from typing import Dict, List, Optional

logger = get_logger('vigil.hade')


# ── Impact tier mapping ────────────────────────────────────────────────────────

_HIGH_IMPACT: frozenset = frozenset({
    'privacy',            # Tracking without consent, data exploitation
    'cookie_wall',        # Accept-only banners / cookie walls — GDPR Art. 7 violation
    'tracking',           # Tracking scripts firing before consent — GDPR/ePrivacy violation
    'forced_continuity',  # Auto-billing / subscription traps
    'obstruction',        # Roach motel — blocked cancellation / account deletion
    'hidden_costs',       # Hidden fees revealed late in checkout
    'preselection',       # Pre-checked consent boxes
    'trick_question',     # Double-negatives hiding real intent
})

_MEDIUM_IMPACT: frozenset = frozenset({
    'urgency',            # Countdown timers, fake scarcity
    'confirmshaming',     # Guilt-tripping decline options
    'misdirection',       # Anchor mismatch, UI misdirection
    'emotional',          # Fear / doubt / uncertainty pressure
    'social_proof',       # Fake "X people are viewing this"
    'forced_action',      # Registration wall
    'nagging',            # Persistent popups, exit-intent
    'disguised_ads',      # Ads styled as editorial
    'visual_misdirection',
    'visual_urgency',
})

# Everything else is LOW_IMPACT (compound_pattern, visual_clutter, informational…)


# ── Critical-override keyword triggers ────────────────────────────────────────
# Finding types containing these phrases force CRITICAL severity regardless of engine count.
# They represent direct, irrefutable user harm where a missed detection is worse than a
# false positive.

_CRITICAL_TYPE_TRIGGERS: tuple = (
    'pre-selected marketing checkbox',       # Silent opt-in — GDPR Art. 7 violation
    'pre-selected subscription enrolment',   # Subscription trial pre-checked — FTC ROSCA
    'pre-selected upsell',                   # Hidden add-on pre-ticked — EU CRD Art. 22
    'cookie_manipulation',                   # Consent denied / cookie wall
    'basket sneaking',                       # Items added without consent
    'forced arbitration',                    # Waives user legal rights
    'compound dark pattern',                 # Multi-vector manipulation funnel
    'dark download funnel',                  # Ad-network redirects before delivery
    'confirmshaming button',                 # Direct guilt-shaming
    'phone-gate cancellation',               # Cancellation requires phone call (obstruction)
    'early cancellation',                    # Exit fee traps users in subscription
    'introductory price',                    # Hidden future price hike
)


# ── Strong manipulative-intent type identifiers ────────────────────────────────

_STRONG_INTENT_TYPES: frozenset = frozenset({
    'Pre-Selected Marketing Checkbox',
    'Pre-Selected Subscription Enrolment',
    'Pre-Selected Upsell / Add-On',
    'Countdown Timer / Fake Urgency',
    'Basket Sneaking (Hidden Field)',
    'Confirmshaming Button',
    'Forced Arbitration / Class Action Waiver',
    'COOKIE_MANIPULATION',
    'COMPOUND DARK PATTERN',
    'Dark Download Funnel',
    'Button Visual Misdirection',
    'Potential Drip Pricing',
    'Fine Print Legal Link',
    'Phone-Gate Cancellation',
    'Early Cancellation / Exit Fee',
    'Introductory Price / Hidden Future Hike',
})

_STRONG_INTENT_CATEGORIES: frozenset = frozenset({
    'preselection',
    'forced_continuity',
    'obstruction',
    'hidden_costs',
    'confirmshaming',
    'trick_question',
})


# ── Weak signal fragments — NEVER appear in final report ───────────────────────
# These patterns represent normal website behaviour that could be mistaken for dark patterns.

_WEAK_SIGNAL_FRAGMENTS: tuple = (
    'above-average reading complexity',   # Grade 12–14 readability — common on legal pages
    'urgency color saturation',           # Too generic; needs corroborating signal
    'disguised advertisement',            # Only one signal — needs consensus
)


# ── Multi-signal required categories ──────────────────────────────────────────
# MEDIUM behavioral patterns need >= 2 independent findings to be credible.
# A single "Only 3 left!" phrase alone is not sufficient.

_MULTI_SIGNAL_REQUIRED: frozenset = frozenset({'urgency', 'social_proof', 'nagging'})


# ═══════════════════════════════════════════════════════════════════════════════
# HarmAwareDecisionEngine
# ═══════════════════════════════════════════════════════════════════════════════

class HarmAwareDecisionEngine:
    """
    Calibration engine that transforms noisy raw engine output into high-quality,
    impact-graded, intent-validated findings.

    Usage:
        hade = HarmAwareDecisionEngine()
        clean_findings = hade.evaluate(all_combined_findings)
    """

    # ── Confidence thresholds ──────────────────────────────────────────────────
    CONF_DEFAULT       = 0.75   # Standard gate for all findings
    CONF_HIGH_IMPACT   = 0.65   # Reduced gate for HIGH-impact categories
    CONF_CRITICAL      = 0.60   # Minimum for critical-override patterns

    # ── Public API ─────────────────────────────────────────────────────────────

    def evaluate(self, all_findings: List[Dict]) -> List[Dict]:
        """
        Complete 8-step evaluation pipeline.

        Returns a de-noised, recalibrated finding list with metadata:
          _impact           HIGH | MEDIUM | LOW
          _intent_strength  STRONG | MODERATE | WEAK
          _hade_note        Human-readable HADE decision note
          _is_critical      bool — True if critical override was applied
        """
        if not all_findings:
            return []

        # Steps 1–2: score every finding
        evaluated = [self._score(f) for f in all_findings]

        # Steps 3–5: apply decision logic (filter / upgrade / downgrade)
        accepted = [r for f in evaluated for r in [self._decide(f)] if r is not None]

        # Step 6: multi-signal gating for MEDIUM behavioral patterns
        accepted = self._multi_signal_gate(accepted)

        # Step 7: final severity realignment
        accepted = [self._recalibrate(f) for f in accepted]

        dropped = len(all_findings) - len(accepted)
        logger.info(
            f'[HADE] {len(all_findings)} raw signals → {len(accepted)} validated '
            f'({dropped} dropped as noise/weak)'
        )
        return accepted

    def get_stats(self, raw: List[Dict], accepted: List[Dict]) -> Dict:
        """Return HADE statistics for the report breakdown."""
        return {
            'raw_count':       len(raw),
            'accepted_count':  len(accepted),
            'dropped_count':   len(raw) - len(accepted),
            'critical_count':  sum(1 for f in accepted if f.get('_is_critical')),
            'upgraded_count':  sum(1 for f in accepted if 'Upgraded' in f.get('_hade_note', '')),
            'downgraded_count':sum(1 for f in accepted if 'Downgraded' in f.get('_hade_note', '')),
        }

    # ── Step 1 + 2: scoring ────────────────────────────────────────────────────

    def _score(self, finding: Dict) -> Dict:
        """Attach _impact and _intent_strength to a copy of the finding dict."""
        f = dict(finding)
        cat  = f.get('category', '')
        ftype = f.get('type', '')
        sev  = f.get('severity', 'LOW')

        # ─ Impact ─────────────────────────────────────────────────────────────
        if cat in _HIGH_IMPACT:
            f['_impact'] = 'HIGH'
        elif cat in _MEDIUM_IMPACT:
            f['_impact'] = 'MEDIUM'
        else:
            f['_impact'] = 'LOW'

        # Override to HIGH + flag critical type
        type_lower = ftype.lower()
        if any(kw in type_lower for kw in _CRITICAL_TYPE_TRIGGERS):
            f['_impact'] = 'HIGH'
            f['_is_critical'] = True

        # ─ Intent ─────────────────────────────────────────────────────────────
        if (ftype in _STRONG_INTENT_TYPES
                or cat in _STRONG_INTENT_CATEGORIES
                or f.get('_is_critical')):
            f['_intent_strength'] = 'STRONG'
        elif sev in ('HIGH', 'CRITICAL') or f['_impact'] == 'HIGH':
            f['_intent_strength'] = 'MODERATE'
        else:
            f['_intent_strength'] = 'WEAK'

        return f

    # ── Steps 3–5: decision ────────────────────────────────────────────────────

    def _decide(self, f: Dict) -> Optional[Dict]:
        """
        Apply the decision rules to a single (already-scored) finding.
        Returns the (possibly modified) finding, or None to discard it entirely.
        """
        conf   = float(f.get('confidence', 0))
        impact = f.get('_impact', 'LOW')
        intent = f.get('_intent_strength', 'WEAK')
        sev    = f.get('severity', 'LOW')

        # ── Step 4: Critical override — never miss high-harm signals ───────────
        if f.get('_is_critical') and conf >= self.CONF_CRITICAL:
            out = dict(f)
            if sev not in ('CRITICAL', 'HIGH'):
                out['severity'] = 'CRITICAL'
            out['_hade_note'] = (
                'Critical override: direct user harm — severity forced to CRITICAL'
            )
            return out

        # ── Step 5a: INFORMATIONAL findings always pass — they are never penalised
        if sev == 'INFORMATIONAL':
            out = dict(f)
            out.setdefault('_hade_note', 'Informational: no trust score impact')
            return out

        # ── Step 5b: Weak signal filter ────────────────────────────────────────
        if self._is_weak(f):
            return None

        # ── Step 3a: Confidence gate ───────────────────────────────────────────
        min_conf = self.CONF_HIGH_IMPACT if impact == 'HIGH' else self.CONF_DEFAULT
        if conf < min_conf:
            return None

        # ── Step 3b: LOW impact → always discard ──────────────────────────────
        if impact == 'LOW':
            return None

        # ── Step 3c: MEDIUM impact + weak intent → downgrade ──────────────────
        if impact == 'MEDIUM' and intent == 'WEAK':
            out = dict(f)
            if sev in ('HIGH', 'CRITICAL'):
                out['severity']   = 'MEDIUM'
                # FIX C-2: Do NOT mutate confidence here.
                # Confidence is the engine's probabilistic signal — preserved for fusion.
                # HADE only adjusts SEVERITY.
            out['_hade_note'] = 'Downgraded: medium impact with weak manipulative intent'
            return out

        # ── Step 3d: HIGH impact + strong intent → upgrade ────────────────────
        if impact == 'HIGH' and intent == 'STRONG':
            out = dict(f)
            if sev in ('LOW', 'MEDIUM'):
                out['severity'] = 'HIGH'
            out['_hade_note'] = 'Upgraded: high user harm + strong manipulative intent'
            return out

        # Default: pass through unchanged
        out = dict(f)
        out.setdefault('_hade_note', f'Accepted: {impact} impact / {intent} intent')
        return out

    def _is_weak(self, f: Dict) -> bool:
        """
        Return True for findings that represent noise rather than genuine dark patterns.
        These are filtered before confidence or impact checks.
        """
        t      = f.get('type', '').lower()
        engine = f.get('_engine', '')
        sev    = f.get('severity', '')
        impact = f.get('_impact', 'LOW')

        # ML-only LOW-impact detections are statistical noise
        if engine == 'ml' and impact == 'LOW':
            return True

        # Known noisy type fragments
        for frag in _WEAK_SIGNAL_FRAGMENTS:
            if frag in t:
                return True

        # Readability 'jargon density' at MEDIUM — too common on legitimate sites
        if engine == 'readability' and 'jargon' in t and sev == 'MEDIUM':
            return True

        return False

    # ── Step 6: multi-signal gating ────────────────────────────────────────────

    def _multi_signal_gate(self, findings: List[Dict]) -> List[Dict]:
        """
        For categories in _MULTI_SIGNAL_REQUIRED, require >= 2 independent findings.
        A single "Only 3 left!" phrase is anecdotal — two or more signals constitute
        a genuine pattern.
        """
        cat_indices: Dict[str, List[int]] = defaultdict(list)
        for i, f in enumerate(findings):
            cat = f.get('category', '')
            if cat in _MULTI_SIGNAL_REQUIRED:
                cat_indices[cat].append(i)

        discard: frozenset = frozenset(
            idx
            for cat, indices in cat_indices.items()
            if len(indices) < 2
            for idx in indices
        )

        if discard:
            cats_dropped = {
                findings[i].get('category') for i in discard
            }
            logger.info(f'[HADE] Multi-signal gate dropped singleton signals: {cats_dropped}')

        return [f for i, f in enumerate(findings) if i not in discard]

    # ── Step 7: severity recalibration ─────────────────────────────────────────

    def _recalibrate(self, f: Dict) -> Dict:
        """
        Final severity alignment:
          CRITICAL  direct harm + forced user action
          HIGH      strong manipulation, reversible
          MEDIUM    behavioral nudging
          LOW       informational — zero trust-score impact
        """
        out = dict(f)

        # Don't re-touch critical overrides
        if 'Critical override' in out.get('_hade_note', ''):
            return out

        impact = out.get('_impact', 'LOW')
        intent = out.get('_intent_strength', 'WEAK')
        sev    = out.get('severity', 'MEDIUM')

        # Ensure HIGH-harm / STRONG-intent findings are never below HIGH
        if impact == 'HIGH' and intent in ('STRONG', 'MODERATE') and sev in ('LOW', 'MEDIUM'):
            out['severity'] = 'HIGH'
            out['_hade_note'] = out.get('_hade_note', '') + ' [recalibrated -> HIGH]'

        # Ensure MEDIUM-impact / weak-intent findings are never above MEDIUM
        if impact == 'MEDIUM' and intent == 'WEAK' and sev in ('CRITICAL', 'HIGH'):
            out['severity'] = 'MEDIUM'
            out['_hade_note'] = out.get('_hade_note', '') + ' [recalibrated -> MEDIUM]'

        return out
