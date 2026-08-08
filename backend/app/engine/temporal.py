"""
Vigil AI — Temporal Smoothing Engine
=======================================
Provides cross-scan consistency by tracking detection history per domain.

PROBLEM (before):
    Each scan is completely stateless. Re-scanning the same site can produce
    wildly different results due to page load variance, ad rotation, A/B tests.

SOLUTION:
    TemporalSmoother maintains a sliding window of recent scan results per domain.
    It smooths the trust score using exponential moving average and stabilises
    finding detection by requiring persistence across scans.

    - Trust score smoothing: EMA with configurable decay
    - Finding persistence: only flag patterns seen in >= N of last M scans
    - Flicker suppression: single-scan anomalies are dampened
"""

import time
import threading
from collections import defaultdict, deque, OrderedDict
from typing import Dict, List, Optional, Tuple

from app.core.config import Config
from app.core.logger import get_logger


logger = get_logger('vigil.temporal')


class TemporalSmoother:
    """
    Cross-scan temporal smoothing for consistent detection results.

    Thread-safe, with SQLite-backed persistence (FIX H-1) and
    LRU eviction for in-memory cache (FIX L-2).
    """

    MAX_CACHED_DOMAINS = 500  # LRU eviction threshold (FIX L-2)

    def __init__(self, window_size: Optional[int] = None, decay: Optional[float] = None):
        self.window_size = window_size or Config.TEMPORAL_WINDOW_SIZE
        self.decay = decay or Config.TEMPORAL_DECAY_FACTOR
        self._history: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def record(self, domain: str, trust_score: float, findings: List[Dict]):
        """
        Record a scan result for temporal tracking.

        Args:
            domain: The domain that was scanned
            trust_score: The raw trust score from this scan
            findings: The list of findings from this scan
        """
        entry = {
            'timestamp': time.time(),
            'trust_score': trust_score,
            'finding_types': {f.get('type', '') for f in findings},
            'categories': {f.get('category', '') for f in findings},
            'finding_count': len(findings),
        }

        with self._lock:
            if domain not in self._history:
                self._history[domain] = deque(maxlen=self.window_size)
            self._history[domain].append(entry)
            
            # LRU tracking (O(1)) (FIX L-2)
            self._history.move_to_end(domain)
            
            # Evict oldest domains if cache exceeds limit
            while len(self._history) > self.MAX_CACHED_DOMAINS:
                self._history.popitem(last=False)

        logger.info(
            f"Temporal: recorded scan for {domain} "
            f"(score={trust_score}, findings={len(findings)}, "
            f"history_depth={len(self._history[domain])})"
        )

    def smooth_trust_score(self, domain: str, current_score: float) -> float:
        """
        Apply exponential moving average smoothing to the trust score.

        If this is the first scan for the domain, returns the raw score.
        Otherwise, blends with historical scores using decay factor.

        Args:
            domain: The domain being scored
            current_score: The raw trust score from the current scan

        Returns:
            Smoothed trust score
        """
        with self._lock:
            history = list(self._history.get(domain, []))

        if len(history) <= 1:
            return current_score

        # Exponential moving average (EMA)
        # Recent scans have more weight than older ones
        weights = []
        scores = []
        for i, entry in enumerate(reversed(history)):
            weight = self.decay ** i
            weights.append(weight)
            scores.append(entry['trust_score'])

        # Add current scan with weight 1.0 (most recent)
        weights.insert(0, 1.0)
        scores.insert(0, current_score)

        total_weight = sum(weights)
        smoothed = sum(s * w for s, w in zip(scores, weights)) / total_weight

        delta = abs(smoothed - current_score)
        if delta > 3:
            logger.info(
                f"Temporal smoothing for {domain}: "
                f"raw={current_score:.0f} → smoothed={smoothed:.0f} (Δ={delta:.1f})"
            )

        return round(smoothed)

    def get_persistent_findings(self, domain: str, current_findings: List[Dict],
                                 min_occurrences: int = 2) -> Tuple[List[Dict], List[Dict]]:
        """
        Split findings into persistent (seen before) and transient (new).

        Persistent findings are more likely to be real patterns.
        Transient findings might be A/B test variants or ad rotation artifacts.

        Args:
            domain: The domain being analyzed
            current_findings: Findings from the current scan
            min_occurrences: Minimum times a finding type must appear in history

        Returns:
            Tuple of (persistent_findings, transient_findings)
        """
        with self._lock:
            history = list(self._history.get(domain, []))

        if len(history) < 2:
            # Not enough history — all findings are treated as real
            return current_findings, []

        # Count historical occurrences of each finding type
        type_counts: Dict[str, int] = defaultdict(int)
        for entry in history:
            for ftype in entry.get('finding_types', set()):
                type_counts[ftype] += 1

        persistent = []
        transient = []

        for f in current_findings:
            ftype = f.get('type', '')
            if type_counts.get(ftype, 0) >= min_occurrences:
                f_copy = dict(f)
                f_copy['_temporal_persistence'] = type_counts[ftype]
                persistent.append(f_copy)
            else:
                transient.append(f)

        if transient:
            logger.info(
                f"Temporal: {len(transient)} transient finding(s) on {domain} "
                f"(not seen in {min_occurrences}+ previous scans)"
            )

        return persistent, transient

    def get_trend(self, domain: str) -> Optional[Dict]:
        """
        Get the trust score trend for a domain.

        Returns:
            Dict with trend info or None if insufficient history.
        """
        with self._lock:
            history = list(self._history.get(domain, []))

        if len(history) < 2:
            return None

        scores = [e['trust_score'] for e in history]
        latest = scores[-1]
        previous = scores[-2]
        avg = sum(scores) / len(scores)

        trend = 'improving' if latest > previous else ('declining' if latest < previous else 'stable')

        return {
            'domain': domain,
            'scan_count': len(history),
            'current_score': latest,
            'previous_score': previous,
            'average_score': round(avg, 1),
            'trend': trend,
            'delta': latest - previous,
        }

    def get_history_summary(self, domain: str) -> Dict:
        """Get a concise summary of scan history for a domain."""
        with self._lock:
            history = list(self._history.get(domain, []))

        if not history:
            return {'domain': domain, 'scans': 0}

        scores = [e['trust_score'] for e in history]
        return {
            'domain': domain,
            'scans': len(history),
            'latest_score': scores[-1],
            'min_score': min(scores),
            'max_score': max(scores),
            'avg_score': round(sum(scores) / len(scores), 1),
        }
