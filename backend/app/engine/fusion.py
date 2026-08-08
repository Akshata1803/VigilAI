"""
Vigil AI — Weighted Ensemble Fusion Engine
============================================
Fuses findings from multiple analyzers using configurable weights.

BEFORE: FindingsAggregator used a flat consensus gate (count engines).
AFTER:  FusionEngine applies weighted scoring per-engine so that
        structural analyzers (cookie, DOM) contribute more to the
        final confidence than statistical ones (ML).

The fusion score is used to:
  1. Boost or suppress individual finding confidence
  2. Provide a per-finding 'fusion_score' for downstream decision logic
  3. Calculate an overall scan fusion score for risk assessment
"""

from collections import defaultdict
from typing import Dict, List, Optional

from app.core.config import Config
from app.core.logger import get_logger
from app.core.exceptions import FusionError


logger = get_logger('vigil.fusion')


class FusionEngine:
    """
    Weighted ensemble fusion for multi-engine detection results.

    Each engine has a configurable weight. When multiple engines detect
    the same category or element, the fusion engine:
      1. Calculates a weighted consensus score
      2. Boosts confidence of corroborated findings
      3. Suppresses confidence of uncorroborated ones
    """

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.weights = weights or Config.FUSION_WEIGHTS

    def fuse(self, all_findings: List[Dict]) -> List[Dict]:
        """
        Apply weighted fusion to a list of findings.

        Process:
          1. Group findings by category
          2. For each category, calculate weighted engine agreement
          3. Adjust confidence based on fusion score
          4. Tag each finding with _fusion_score and _fusion_engines

        Returns:
            The same findings list with confidence adjusted and fusion metadata added.
        """
        if not all_findings:
            return []

        if not isinstance(all_findings, list):
            raise FusionError(
                "Fusion input must be a list of finding dicts",
                retryable=False,
            )

        # Step 1: Build category → engine map with weighted scores
        category_engine_scores: Dict[str, Dict[str, float]] = defaultdict(dict)
        for f in all_findings:
            cat = f.get('category', 'unknown')
            engine = f.get('_engine', 'unknown')
            conf = float(f.get('confidence', 0.5))
            weight = self.weights.get(engine, 0.05)
            # Track best confidence per engine per category
            if engine not in category_engine_scores[cat]:
                category_engine_scores[cat][engine] = 0.0
            category_engine_scores[cat][engine] = max(
                category_engine_scores[cat][engine],
                conf * weight,
            )

        # Step 2: Calculate fusion score per category (FIX H-5: proper normalization)
        category_fusion: Dict[str, float] = {}
        total_possible_weight = sum(self.weights.values()) or 1.0
        for cat, engine_scores in category_engine_scores.items():
            total_weighted = sum(engine_scores.values())
            # Normalize against the TOTAL possible weight (all engines), not just
            # engines that found this category. This ensures cross-category comparability.
            fusion_score = total_weighted / total_possible_weight
            category_fusion[cat] = min(1.0, fusion_score)

        # Step 3: Adjust confidence of each finding based on fusion
        fused = []
        for f in all_findings:
            f_copy = dict(f)
            cat = f_copy.get('category', 'unknown')
            engine = f_copy.get('_engine', 'unknown')
            engines_for_cat = list(category_engine_scores.get(cat, {}).keys())
            engine_count = len(engines_for_cat)
            fusion_score = category_fusion.get(cat, 0.0)

            # Multi-engine corroboration boost
            if engine_count >= 3:
                conf_boost = 0.10
            elif engine_count >= 2:
                conf_boost = 0.05
            else:
                conf_boost = 0.0

            # FIX C-2: Store fusion-adjusted confidence as METADATA, not overwrite.
            # The original 'confidence' field is the engine's raw probabilistic signal
            # and must be preserved for audit trail.
            raw_conf = float(f_copy.get('confidence', 0.5))
            f_copy['_fusion_confidence'] = round(min(0.98, raw_conf + conf_boost), 3)
            f_copy['_fusion_conf_boost'] = conf_boost
            # DO NOT: f_copy['confidence'] = new_conf  ← this was the bug

            # Tag with fusion metadata
            f_copy['_fusion_score'] = round(fusion_score, 3)
            f_copy['_fusion_engines'] = engines_for_cat
            f_copy['_fusion_engine_count'] = engine_count

            fused.append(f_copy)

        # Log fusion summary
        multi_cat = [c for c, es in category_engine_scores.items() if len(es) >= 2]
        if multi_cat:
            logger.info(
                f"Fusion: {len(multi_cat)} categories confirmed by multiple engines: "
                f"{', '.join(multi_cat[:5])}"
            )

        return fused

    def calculate_scan_fusion_score(self, all_findings: List[Dict]) -> float:
        """
        Calculate an overall scan-level fusion score.

        Higher = more engines agree on issues = higher confidence in results.
        Range: 0.0 (no agreement) to 1.0 (full consensus).
        """
        if not all_findings:
            return 0.0

        # Gather per-finding fusion scores
        scores = [float(f.get('_fusion_score', 0.5)) for f in all_findings]
        engine_counts = [int(f.get('_fusion_engine_count', 1)) for f in all_findings]

        avg_fusion = sum(scores) / len(scores)
        avg_engines = sum(engine_counts) / len(engine_counts)

        # Weighted combination: fusion quality × engine diversity
        scan_score = (avg_fusion * 0.6) + (min(avg_engines / 4.0, 1.0) * 0.4)
        return round(min(1.0, scan_score), 3)
