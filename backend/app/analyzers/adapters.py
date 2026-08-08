"""
Vigil AI — Analyzer Adapters
===============================
Adapts existing analyzer classes to the new BaseAnalyzer interface.

Each adapter wraps an existing service-layer analyzer and provides:
  - Unified .run() API via BaseAnalyzer contract
  - Automatic timing, error handling, engine tagging
  - Consistent AnalysisContext extraction

This allows the pipeline to treat all analyzers uniformly without
rewriting the proven detection logic inside each one.
"""

from typing import Dict, List

from app.analyzers.base import BaseAnalyzer, AnalysisContext

# Import existing analyzers (preserving all detection logic)
from app.services.dom_analyzer import DOMAnalyzer
from app.services.text_analyzer import TextAnalyzer
from app.services.visual_analyzer import VisualAnalyzer
from app.services.advanced_analyzer import AdvancedAnalyzer
from app.services.cookie_analyzer import CookieConsentAnalyzer
from app.services.link_analyzer import LinkPathAnalyzer
from app.services.readability_analyzer import ReadabilityAnalyzer
from app.services.ml_analyzer import MLAnalyzer


class DOMAnalyzerAdapter(BaseAnalyzer):
    """Adapter for DOM structural analyzer."""
    name = 'dom'
    weight = 0.20

    def __init__(self):
        super().__init__()
        self._analyzer = DOMAnalyzer()

    def execute(self, context: AnalysisContext) -> List[Dict]:
        return self._analyzer.analyze(context.dom_data, context.html_content)


class TextAnalyzerAdapter(BaseAnalyzer):
    """Adapter for NLP text analyzer."""
    name = 'text'
    weight = 0.15

    def __init__(self):
        super().__init__()
        self._analyzer = TextAnalyzer()

    def execute(self, context: AnalysisContext) -> List[Dict]:
        return self._analyzer.analyze(context.dom_data, context.text_content)


class VisualAnalyzerAdapter(BaseAnalyzer):
    """Adapter for visual/CSS analyzer."""
    name = 'visual'
    weight = 0.10

    def __init__(self):
        super().__init__()
        self._analyzer = VisualAnalyzer()

    def execute(self, context: AnalysisContext) -> List[Dict]:
        return self._analyzer.analyze(context.screenshot_path, context.dom_data)


class AdvancedAnalyzerAdapter(BaseAnalyzer):
    """Adapter for advanced structural analyzer."""
    name = 'advanced'
    weight = 0.15

    def __init__(self):
        super().__init__()
        self._analyzer = AdvancedAnalyzer()

    def execute(self, context: AnalysisContext) -> List[Dict]:
        scan_data = {'url': context.url}
        return self._analyzer.analyze(
            context.dom_data,
            context.html_content,
            context.text_content,
            scan_data,
        )


class CookieAnalyzerAdapter(BaseAnalyzer):
    """Adapter for cookie/consent analyzer."""
    name = 'cookie'
    weight = 0.15

    def __init__(self):
        super().__init__()
        self._analyzer = CookieConsentAnalyzer()

    def execute(self, context: AnalysisContext) -> List[Dict]:
        return self._analyzer.analyze(context.dom_data, context.html_content)


class LinkAnalyzerAdapter(BaseAnalyzer):
    """Adapter for link/journey path analyzer."""
    name = 'link'
    weight = 0.05

    def __init__(self):
        super().__init__()
        self._analyzer = LinkPathAnalyzer()

    def execute(self, context: AnalysisContext) -> List[Dict]:
        return self._analyzer.analyze(
            context.dom_data,
            context.html_content,
            context.url,
        )


class ReadabilityAnalyzerAdapter(BaseAnalyzer):
    """Adapter for readability/typography analyzer."""
    name = 'readability'
    weight = 0.05

    def __init__(self):
        super().__init__()
        self._analyzer = ReadabilityAnalyzer()

    def execute(self, context: AnalysisContext) -> List[Dict]:
        return self._analyzer.analyze(
            context.dom_data,
            context.html_content,
            context.text_content,
        )


class MLAnalyzerAdapter(BaseAnalyzer):
    """Adapter for ML ensemble analyzer with lazy model loading."""
    name = 'ml'
    weight = 0.10
    max_retries = 0  # ML model failures are not transient

    # Lazy singleton — model loaded once, reused across all scans
    _shared_analyzer = None

    def __init__(self):
        super().__init__()
        if MLAnalyzerAdapter._shared_analyzer is None:
            MLAnalyzerAdapter._shared_analyzer = MLAnalyzer()
        self._analyzer = MLAnalyzerAdapter._shared_analyzer

    def execute(self, context: AnalysisContext) -> List[Dict]:
        return self._analyzer.analyze(
            context.text_content,
            dom_data=context.dom_data,
            html_content=context.html_content,
        )


class BehavioralScorerAdapter(BaseAnalyzer):
    """
    Adapter for behavioral/compound pattern scorer.

    NOTE: This runs AFTER the main pipeline because it needs
    HADE-verified findings as input. It's registered separately
    in the scan route, not in the main parallel pool.
    """
    name = 'behavioral'
    weight = 0.05

    def __init__(self):
        super().__init__()
        from app.services.behavioral_scorer import BehavioralScorer
        self._scorer = BehavioralScorer()

    def execute(self, context: AnalysisContext) -> List[Dict]:
        # BehavioralScorer uses pre-verified findings from context
        # These are injected via a special '_verified_findings' field
        verified = getattr(context, '_verified_findings', [])
        return self._scorer.analyze(
            verified,
            context.html_content,
            context.dom_data,
        )


# ── Factory ────────────────────────────────────────────────────────────────────

def create_default_analyzers() -> list:
    """Create the default set of analyzers for the pipeline."""
    return [
        DOMAnalyzerAdapter(),
        TextAnalyzerAdapter(),
        VisualAnalyzerAdapter(),
        AdvancedAnalyzerAdapter(),
        CookieAnalyzerAdapter(),
        LinkAnalyzerAdapter(),
        ReadabilityAnalyzerAdapter(),
        MLAnalyzerAdapter(),
    ]
