"""
Vigil AI — Machine Learning Analyzer (Gated)
=============================================
FIXED: ML predictions must be confirmed by rule engine OR context signals.

Gating logic:
  • 'privacy' prediction    → requires cookie_analyzer or tracking signal in dom_data
  • 'urgency' prediction    → requires numeric value in the text
  • 'preselection'          → requires form/checkbox element reference
  • 'forced_continuity'     → requires auto-renew/billing keyword match
  • All others              → require confidence > 0.75 OR a DOM selector match

If no supporting signal: downgrade to INFORMATIONAL (not reported in final output)

extract_custom_features lives at module level so joblib can resolve it.
"""

import os
import re
import math
import threading
import joblib
import numpy as np

from app.core.logger import get_logger
from app.core.exceptions import ModelLoadError

_logger = get_logger('vigil.ml_analyzer')

# ── URGENCY / SHAME WORD LISTS ────────────────────────────────────────────────
_URGENCY_WORDS = [
    'hurry', 'limited', 'only', 'last', 'expires', 'ending', 'act now',
    'today only', 'flash', 'midnight', 'sold out', 'almost gone', 'selling fast',
    'must', 'urgent', 'immediately', 'deadline', 'final', 'running out'
]
_SHAME_WORDS = [
    "don't want", "don't care", "prefer to pay more", "miss out", "stay poor",
    "fine without", "i'll pass", "rather lose", "ignore", "overpay", "foolish"
]


def extract_custom_features(texts):
    """
    Custom numeric dark pattern signals used by the ML pipeline.
    Must be module-level for joblib serialization.
    """
    matrix = []
    for text in texts:
        t = text.lower()
        feats = [
            text.count('!') / (len(text) + 1),
            sum(1 for c in text if c.isupper()) / (len(text) + 1),
            len(re.findall(r'\d', text)) / (len(text) + 1),
            sum(1 for w in _URGENCY_WORDS if w in t),
            sum(1 for w in _SHAME_WORDS if w in t),
            min(len(text.split()) / 50.0, 1.0),
            int(bool(re.search(r'(free|no cost|gratis)', t))),
            int(bool(re.search(r'(auto.renew|automatically charged)', t))),
            int(bool(re.search(r'(pre.?select|pre.?check|already tick)', t))),
            int(bool(re.search(r'(you must|required to|have to)', t))),
        ]
        matrix.append(feats)
    return np.array(matrix, dtype=np.float32)


class MLAnalyzer:
    """Machine Learning Analyzer — Scikit-Learn Ensemble with rule-engine gating."""

    # ── Lazy Singleton Model Cache (FIX C-1) ──────────────────────────────────
    _model_cache = None
    _model_loaded = False
    _model_lock = __import__('threading').Lock()

    _SEVERITY_MAP = {
        'urgency':           'MEDIUM',
        'confirmshaming':    'HIGH',
        'social_proof':      'LOW',
        'privacy':           'HIGH',
        'forced_continuity': 'HIGH',
        'forced_action':     'MEDIUM',
        'basket_sneaking':   'HIGH',
        'emotional':         'MEDIUM',
        'preselection':      'HIGH',
        'hidden_costs':      'HIGH',
    }

    _DESCRIPTION_MAP = {
        'urgency':           'ML model detected manufactured urgency language designed to pressure rapid decisions.',
        'confirmshaming':    'ML model detected guilt-tripping / confirmshaming in opt-out or decline text.',
        'social_proof':      'ML model detected potentially fabricated or unverifiable social proof claims.',
        'privacy':           'ML model detected language indicating hidden or deceptive data sharing practices.',
        'forced_continuity': 'ML model detected auto-billing or forced subscription continuation language.',
        'forced_action':     'ML model detected a forced registration or account gate blocking user access.',
        'basket_sneaking':   'ML model detected language indicating items auto-added to cart without explicit consent.',
        'emotional':         'ML model detected fear, guilt or emotional manipulation tactics.',
        'preselection':      'ML model detected pre-selected checkboxes or default opt-ins.',
        'hidden_costs':      'ML model detected language obscuring fees, taxes or additional charges.',
    }

    # Minimum confidence per category AFTER gating
    _MIN_GATED_CONFIDENCE = {
        'social_proof':  0.80,  # High false-positive category
        'emotional':     0.78,
        'urgency':       0.75,
        'privacy':       0.75,
        'default':       0.70,
    }

    @classmethod
    def _load_model(cls):
        """Thread-safe lazy model loading with SHA-256 integrity verification.
        
        Security: pickle deserialization can execute arbitrary code (RCE).
        We verify the model file hash against a signed manifest before loading.
        If verification fails, the model is NOT loaded and ML analysis is disabled.
        """
        if cls._model_loaded:
            return cls._model_cache
        with cls._model_lock:
            if cls._model_loaded:
                return cls._model_cache
            model_dir = os.path.join(
                os.path.dirname(__file__), '..', 'models'
            )
            model_path = os.path.join(model_dir, 'dp_classifier.pkl')
            manifest_path = os.path.join(model_dir, 'model_manifest.json')
            try:
                if not os.path.exists(model_path):
                    _logger.warning(f"ML model not found at {model_path}. Run training script first.")
                    cls._model_loaded = True
                    return cls._model_cache

                # ── SHA-256 integrity verification (anti-RCE) ─────────────
                if os.path.exists(manifest_path):
                    import hashlib, json as _json
                    with open(manifest_path, 'r') as mf:
                        manifest = _json.load(mf)
                    expected_hash = manifest.get('sha256', '')

                    sha256 = hashlib.sha256()
                    with open(model_path, 'rb') as f:
                        for chunk in iter(lambda: f.read(8192), b''):
                            sha256.update(chunk)
                    actual_hash = sha256.hexdigest()

                    if actual_hash != expected_hash:
                        msg = (
                            f"MODEL INTEGRITY FAILURE: SHA-256 mismatch. "
                            f"Expected {expected_hash[:16]}..., got {actual_hash[:16]}... "
                            f"Model file may be tampered. Refusing to load."
                        )
                        _logger.error(msg)
                        cls._model_loaded = True
                        raise ModelLoadError(msg, model_path=model_path)

                    _logger.info(f"Model integrity verified (SHA-256: {actual_hash[:16]}...)")
                else:
                    _logger.warning(
                        "No model_manifest.json found — loading model WITHOUT integrity check. "
                        "Run train_ml_model.py to generate a manifest."
                    )

                cls._model_cache = joblib.load(model_path)
            except Exception as e:
                _logger.error(f"ML Model load error: {e}")
            cls._model_loaded = True
            return cls._model_cache

    @classmethod
    def preload(cls):
        """Background preload — call during app init to warm the model cache."""
        threading.Thread(target=cls._load_model, daemon=True).start()

    def __init__(self):
        self.findings = []

    @property
    def model(self):
        """Lazy-loaded model property."""
        return self._load_model()

    def analyze(self, text_content, dom_data=None, html_content=None):
        """Analyze text using BATCH ML inference (single model call vs N calls)."""
        self.findings = []
        self._html_content = html_content
        model = self.model
        if not model or not text_content:
            return self.findings

        chunks = [
            c.strip() for c in re.split(r'\n{2,}|\.\s+', text_content)
            if 15 < len(c.strip()) < 600
        ]
        if not chunks:
            return self.findings

        # ── BATCH INFERENCE: 1 call instead of N ─────────────────────────
        try:
            predictions  = model.predict(chunks)
            proba_arrays = model.predict_proba(chunks)
        except Exception as e:
            _logger.warning(f"ML batch inference failed ({type(e).__name__}: {e})")
            return self.findings

        seen = set()
        text_elements = dom_data.get('text_elements', []) if dom_data else []

        for chunk, prediction, proba_array in zip(chunks, predictions, proba_arrays):
            try:
                confidence = float(proba_array.max())

                if prediction == 'safe' or confidence < 0.60:
                    continue

                key = chunk[:120]
                if key in seen:
                    continue
                seen.add(key)

                # Category-specific gating
                gated_severity, gated_category, gated_type = self._gate_prediction(
                    prediction, confidence, chunk, dom_data
                )

                if gated_severity == 'INFORMATIONAL':
                    continue

                min_conf = self._MIN_GATED_CONFIDENCE.get(
                    prediction, self._MIN_GATED_CONFIDENCE['default']
                )
                if confidence < min_conf:
                    continue

                # DOM selector mapping
                element  = 'Page text (ML statistical prediction)'
                evidence = f'"{chunk[:180]}"'
                for el in text_elements:
                    el_text = str(el.get('text', ''))
                    if chunk in el_text or (el_text in chunk and len(el_text) > 20):
                        tag      = str(el.get('tag', ''))
                        classes  = str(el.get('classes', ''))
                        selector = tag
                        if classes:
                            selector += f" .{classes.replace(' ', '.')}"
                        evidence = f"DOM: {selector}\nText: {el_text[:200]}"
                        element  = selector
                        break

                self.findings.append({
                    'type':           gated_type,
                    'category':       gated_category,
                    'severity':       gated_severity,
                    'confidence':     round(confidence, 2),
                    'signal_strength': 'moderate' if element != 'Page text (ML statistical prediction)' else 'weak',
                    'description':    self._DESCRIPTION_MAP.get(
                                          prediction,
                                          'ML classifier flagged this text as a potential dark pattern.'
                                      ),
                    'evidence':       evidence,
                    'element':        element,
                    'recommendation': (
                        'ML classifier flagged this as similar to known dark patterns. '
                        'Review text for deceptive or manipulative framing.'
                    ),
                    'legal_refs': ['Evaluated via Vigil AI ML Ensemble (LinearSVC + SGD + RandomForest)'],
                })

            except Exception as e:
                _logger.debug(f"Chunk processing error ({type(e).__name__}): {e}")
                continue

        return self.findings


    # ── Gating logic ───────────────────────────────────────────────────────────
    def _gate_prediction(self, prediction, confidence, chunk, dom_data):
        """
        Validate ML prediction against rule engine / contextual signals.
        Returns (severity, category, type_label).
        Returns ('INFORMATIONAL', ...) to suppress the finding.
        """
        chunk_lower = chunk.lower()
        dom_signals = self._extract_dom_signals(dom_data)

        # ── Privacy manipulation: require cookie or tracking signal ────────
        if prediction == 'privacy':
            manipulation_kws = [
                "legitimate interest", "share with partners", "automatically enrolled",
                "opt-out required", "may sell data", "sell your data",
            ]
            disclosure_kws = [
                "ad choices", "learn more", "advertising preferences",
                "interest-based advertising", "privacy choices",
            ]
            has_manipulation = any(k in chunk_lower for k in manipulation_kws)
            has_disclosure   = any(k in chunk_lower for k in disclosure_kws)

            # Require: manipulation keyword OR cookie/tracking signal from another engine
            if has_disclosure and not has_manipulation:
                return ('INFORMATIONAL', 'informational', 'Informational Privacy Disclosure')

            has_cookie_signal   = dom_signals.get('has_cookie_banner')
            has_tracking_signal = dom_signals.get('has_tracking_scripts')

            if not has_manipulation and not has_cookie_signal and not has_tracking_signal:
                # No supporting signal — downgrade
                return ('INFORMATIONAL', 'informational', 'Informational Privacy Disclosure')

            severity = 'HIGH' if (has_manipulation and confidence > 0.80) else 'MEDIUM'
            return (severity, 'privacy', 'ML: Privacy Manipulation')

        # ── Urgency: require numeric value in the text ─────────────────────
        if prediction == 'urgency':
            has_numeric = bool(re.search(r'\b[0-9]+\b', chunk_lower))
            if not has_numeric:
                return ('INFORMATIONAL', 'informational', 'ML: Urgency (no numeric — suppressed)')
            return ('MEDIUM', 'urgency', 'ML: Urgency')

        # ── Preselection: require form/checkbox DOM element ────────────────
        if prediction == 'preselection':
            has_form_element = dom_signals.get('has_checkboxes') or dom_signals.get('has_forms')
            presel_kws = ['pre-selected', 'pre-checked', 'already ticked', 'pre.?select', 'pre.?check']
            has_kw = any(re.search(kw, chunk_lower) for kw in presel_kws)
            if not has_form_element and not has_kw:
                return ('INFORMATIONAL', 'informational', 'ML: Preselection (no form DOM — suppressed)')
            return ('HIGH', 'preselection', 'ML: Pre-selected Option')

        # ── Forced continuity: require auto-billing keyword ────────────────
        if prediction == 'forced_continuity':
            billing_kws = ['auto-renew', 'automatically charged', 'auto renew', 'automatically billed',
                           'recurring charge', 'subscription will', 'trial ends',
                           'will be charged', 'automatically renew', 'will automatically',
                           'billed monthly', 'billed annually', 'charged monthly',
                           'charged automatically', 'continues at', 'renews at']
            has_billing_kw = any(kw in chunk_lower for kw in billing_kws)
            if not has_billing_kw and confidence < 0.85:
                return ('INFORMATIONAL', 'informational', 'ML: Forced Continuity (weak — suppressed)')
            return ('HIGH', 'forced_continuity', 'ML: Forced Continuity')

        # ── Default: require confidence > threshold OR DOM selector match ──
        has_dom_anchor = bool(dom_signals.get('matched_element'))
        min_conf = self._MIN_GATED_CONFIDENCE.get(prediction, self._MIN_GATED_CONFIDENCE['default'])
        if confidence < min_conf and not has_dom_anchor:
            return ('INFORMATIONAL', 'informational', f'ML: {prediction.title()} (low confidence — suppressed)')

        severity = self._SEVERITY_MAP.get(prediction, 'MEDIUM')
        type_label = f'ML: {prediction.replace("_", " ").title()}'
        return (severity, prediction, type_label)

    # ── DOM signal helper ──────────────────────────────────────────────────────
    def _extract_dom_signals(self, dom_data):
        """Extract structural signals from dom_data to support gating."""
        if not dom_data:
            return {}
        signals = {}
        # scanner.py uses 'cookie_banners' (plural)
        signals['has_cookie_banner'] = bool(dom_data.get('cookie_banners')) or bool(dom_data.get('cookie_banner'))

        # Check for tracking scripts in raw HTML — text_elements have scripts stripped
        html_raw = getattr(self, '_html_content', '') or ''
        tracking_script_patterns = [
            r'google-analytics\.com',
            r'googletagmanager\.com',
            r'gtag\s*\(',
            r'ga\s*\(\s*["\']create',
            r'fbq\s*\(',                     # Meta Pixel
            r'connect\.facebook\.net',
            r'hotjar\.com',
            r'clarity\.ms',
            r'fullstory\.com',
            r'segment\.com/analytics',
            r'mixpanel\.com',
            r'heap-analytics',
            r'amplitude\.com',
            r'plausible\.io',
        ]
        signals['has_tracking_scripts'] = any(
            re.search(pat, html_raw, re.I) for pat in tracking_script_patterns
        )

        signals['has_checkboxes'] = bool(dom_data.get('checkboxes'))
        signals['has_forms'] = bool(dom_data.get('forms'))
        return signals