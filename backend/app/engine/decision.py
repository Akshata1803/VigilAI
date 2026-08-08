"""
Vigil AI — Risk Decision Engine
==================================
Final-stage decision logic that takes fused findings and produces
a calibrated risk assessment.

Replaces the scattered decision logic in the old pipeline:
  - HADE does impact/intent calibration (kept as-is)
  - FusionEngine does weighted ensemble scoring (new)
  - RiskDecisionEngine does FINAL risk classification (this module)

Decision Flow:
  fused_findings → severity_scoring → category_correlation → risk_classification
"""

import math
from typing import Dict, List
from app.core.logger import get_logger


logger = get_logger('vigil.decision')


class RiskDecisionEngine:
    """
    Final risk classification engine.

    Takes post-HADE, post-fusion findings and produces:
      - Per-finding risk labels
      - Overall scan risk score
      - Risk distribution breakdown
    """

    # Severity to numeric score mapping
    SEVERITY_SCORES = {
        'CRITICAL': 1.0,
        'HIGH': 0.75,
        'MEDIUM': 0.40,
        'LOW': 0.15,
        'INFORMATIONAL': 0.0,
    }

    # Category correlation: certain combinations are worse than the sum of parts
    COMPOUND_CATEGORIES = {
        frozenset({'privacy', 'forced_continuity'}): 1.3,         # Hidden data use + billing trap
        frozenset({'preselection', 'hidden_costs'}): 1.25,        # Silent opt-in + drip pricing
        frozenset({'obstruction', 'forced_continuity'}): 1.2,     # Roach motel + can't cancel
        frozenset({'confirmshaming', 'preselection'}): 1.15,      # Shame + pre-checked
        frozenset({'urgency', 'hidden_costs'}): 1.1,              # Pressure + surprise fees
    }

    def assess(self, findings: List[Dict]) -> 'RiskAssessment':
        """
        Produce a comprehensive risk assessment from post-fusion findings.

        Returns:
            RiskAssessment with overall score, risk level, and breakdown.
        """
        if not findings:
            return RiskAssessment(
                risk_score=0.0,
                risk_level='LOW',
                risk_label='Low Risk',
                finding_count=0,
                severity_distribution={},
                category_distribution={},
                compound_bonus=1.0,
            )

        # Step 1: Calculate base risk score from individual findings
        total_risk = 0.0
        severity_dist: Dict[str, int] = {}
        category_dist: Dict[str, int] = {}
        categories_present = set()

        for f in findings:
            sev = f.get('severity', 'LOW')
            cat = f.get('category', 'unknown')
            conf = float(f.get('confidence', 0.5))
            fusion = float(f.get('_fusion_score', 0.5))

            # Risk contribution = severity × confidence × fusion quality
            sev_score = self.SEVERITY_SCORES.get(sev, 0.1)
            finding_risk = sev_score * conf * (0.7 + 0.3 * fusion)
            total_risk += finding_risk

            severity_dist[sev] = severity_dist.get(sev, 0) + 1
            category_dist[cat] = category_dist.get(cat, 0) + 1
            categories_present.add(cat)

        # Step 2: Apply compound category correlation bonuses
        compound_bonus = 1.0
        for cat_combo, multiplier in self.COMPOUND_CATEGORIES.items():
            if cat_combo.issubset(categories_present):
                compound_bonus = max(compound_bonus, multiplier)
                logger.info(
                    f"Compound correlation detected: {set(cat_combo)} → {multiplier}× bonus"
                )

        total_risk *= compound_bonus

        # Step 3: Normalize to 0-1 range (diminishing returns curve)
        normalized = 1.0 - math.exp(-total_risk / 3.0)
        normalized = min(1.0, max(0.0, normalized))

        # Step 4: Classify
        risk_level, risk_label = self._classify(normalized)

        assessment = RiskAssessment(
            risk_score=round(normalized, 3),
            risk_level=risk_level,
            risk_label=risk_label,
            finding_count=len(findings),
            severity_distribution=severity_dist,
            category_distribution=category_dist,
            compound_bonus=compound_bonus,
        )

        logger.info(
            f"Risk assessment: score={assessment.risk_score}, "
            f"level={assessment.risk_level}, "
            f"findings={assessment.finding_count}, "
            f"compound_bonus={compound_bonus}"
        )

        return assessment

    def _classify(self, score: float):
        """Map normalized risk score to risk level and label."""
        if score >= 0.75:
            return 'CRITICAL', 'Critical Risk'
        elif score >= 0.50:
            return 'HIGH', 'High Risk'
        elif score >= 0.25:
            return 'MODERATE', 'Moderate Risk'
        else:
            return 'LOW', 'Low Risk'


class RiskAssessment:
    """Result of a risk assessment."""

    __slots__ = (
        'risk_score', 'risk_level', 'risk_label', 'finding_count',
        'severity_distribution', 'category_distribution', 'compound_bonus',
    )

    def __init__(self, risk_score, risk_level, risk_label, finding_count,
                 severity_distribution, category_distribution, compound_bonus):
        self.risk_score = risk_score
        self.risk_level = risk_level
        self.risk_label = risk_label
        self.finding_count = finding_count
        self.severity_distribution = severity_distribution
        self.category_distribution = category_distribution
        self.compound_bonus = compound_bonus

    def to_dict(self) -> Dict:
        return {
            'risk_score': self.risk_score,
            'risk_level': self.risk_level,
            'risk_label': self.risk_label,
            'finding_count': self.finding_count,
            'severity_distribution': self.severity_distribution,
            'category_distribution': self.category_distribution,
            'compound_bonus': self.compound_bonus,
        }

    def __repr__(self):
        return f'<RiskAssessment: {self.risk_label} (score={self.risk_score}, findings={self.finding_count})>'
