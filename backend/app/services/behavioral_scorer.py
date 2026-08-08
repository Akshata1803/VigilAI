"""
Vigil AI — Behavioral Scorer (Weighted Compound Pattern Detector)
==================================================================
FIXED: Replaced raw vector count threshold with a WEIGHTED scoring system.

Weights:
  cookie_issue              = 3  (consent violations are high-harm)
  tracking_before_consent   = 3  (GDPR/ePrivacy direct violation)
  prechecked_boxes          = 2  (dark UI pattern, well-documented)
  ml_signal                 = 1  (corroborating evidence only)
  other_verified            = 1  (all other verified findings)

Trigger: total_weight >= 5 (prevents weak combinations inflating to CRITICAL)
Requires: at least 2 DISTINCT categories of evidence

This prevents scenarios like: 3 ML-only weak signals → spurious COMPOUND finding.
"""

import math


class BehavioralScorer:

    # Weight per finding type/category
    CATEGORY_WEIGHTS = {
        # High-harm structural violations (weight 3)
        'cookie':            3,
        'cookie_wall':       3,   # cookie_analyzer CRITICAL subtype
        'tracking':          3,
        'privacy':           3,   # cookie_analyzer privacy category
        'forced_continuity': 3,

        # Confirmed UI dark patterns (weight 2)
        'preselection':      2,
        'hidden_costs':      2,
        'obstruction':       2,
        'confirmshaming':    2,
        'trick_question':    2,

        # ML corroboration only (weight 1)
        'ml_signal':         1,
        'urgency':           1,
        'social_proof':      1,
        'emotional':         1,
        'misdirection':      1,
        'forced_action':     1,
        'nagging':           1,
    }

    COMPOUND_TRIGGER_WEIGHT = 5   # Minimum total weight to trigger compound pattern
    MIN_DISTINCT_CATEGORIES = 2   # Require at least 2 different categories of evidence

    def analyze(self, findings, html_content, dom_data):
        compound_findings = []

        if not findings:
            return compound_findings

        # Gather verified (non-informational, non-low) findings
        verified = [
            f for f in findings
            if isinstance(f, dict)
            and f.get('severity', 'LOW') not in ('INFORMATIONAL', 'LOW')
            and f.get('category', '') != 'compound_pattern'
        ]

        if not verified:
            return compound_findings

        # Calculate weighted score
        total_weight   = 0
        categories_hit = set()
        type_labels    = []

        for f in verified:
            cat = f.get('category', '').lower()
            ftype = f.get('type', '')
            engine = f.get('_engine', '').lower()

            # Determine weight
            if 'ml' in engine and cat not in ('preselection', 'hidden_costs', 'forced_continuity'):
                # ML-only findings get weight 1 regardless of category
                weight = self.CATEGORY_WEIGHTS.get('ml_signal', 1)
                track_cat = 'ml_signal'
            else:
                weight = self.CATEGORY_WEIGHTS.get(cat, 1)
                track_cat = cat

            total_weight   += weight
            categories_hit.add(track_cat)
            type_labels.append(ftype)

        distinct_categories = len(categories_hit)

        # Trigger condition: weight >= threshold AND >= 2 distinct categories
        if total_weight >= self.COMPOUND_TRIGGER_WEIGHT and distinct_categories >= self.MIN_DISTINCT_CATEGORIES:
            # Determine severity: CRITICAL only if cookie/tracking involved
            high_harm_present = any(
                c in categories_hit
                for c in ('cookie', 'tracking', 'cookie_wall', 'forced_continuity', 'preselection')
            )
            severity = 'HIGH' if not high_harm_present else 'CRITICAL'

            # Build compact evidence list (unique types, max 6)
            unique_types = list(dict.fromkeys(type_labels))[:6]
            evidence_str = (
                f'Weighted score: {total_weight} across {distinct_categories} categories. '
                f'Active vectors: {", ".join(unique_types)}.'
            )

            # FIX M-9: Calculate confidence from evidence strength instead of hardcoded
            # Scale: weight 5 → 0.70, weight 10 → 0.85, weight 20+ → 0.95
            compound_confidence = min(0.95, 0.60 + 0.35 * (1 - math.exp(-total_weight / 12.0)))
            compound_confidence = round(compound_confidence, 3)

            compound_findings.append({
                'type': 'COMPOUND DARK PATTERN',
                'category': 'compound_pattern',
                'severity': severity,
                'confidence': compound_confidence,
                'signal_strength': 'strong',
                'description': (
                    f'Vigil AI detected {distinct_categories} independent dark pattern categories '
                    f'(weighted score: {total_weight}) operating together. '
                    'Multiple simultaneous manipulation techniques constitute a Compound Dark Funnel — '
                    'a coordinated system designed to override user autonomy.'
                ),
                'evidence': evidence_str,
                'element': 'Whole site',
                'recommendation': (
                    'This site uses layered manipulation. Address underlying patterns individually. '
                    'Consider a full UX ethics audit against DSA Art. 25 standards.'
                ),
                'legal_refs': ['DSA Art. 25 (Dark Patterns Prohibition)', 'EDPB Guidelines 03/2022'],
            })

        return compound_findings
