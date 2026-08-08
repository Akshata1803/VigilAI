"""
Vigil AI — Exception Hierarchy
================================
Structured exceptions with retry hints and error categorization.
Every exception carries enough context for the error handler to make
intelligent recovery decisions.
"""


class VigilError(Exception):
    """Base exception for all Vigil AI errors."""

    def __init__(self, message, *, retryable=False, error_code=None, details=None):
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        self.error_code = error_code or 'VIGIL_ERROR'
        self.details = details or {}

    def to_dict(self):
        return {
            'error': self.message,
            'error_code': self.error_code,
            'retryable': self.retryable,
            'details': self.details,
        }


class ScanError(VigilError):
    """Error during website scanning (Playwright/network failure)."""

    def __init__(self, message, url='', **kwargs):
        super().__init__(message, error_code='SCAN_ERROR', **kwargs)
        self.url = url
        self.details['url'] = url


class AnalyzerError(VigilError):
    """Error within an individual analyzer."""

    def __init__(self, message, analyzer_name='', **kwargs):
        super().__init__(message, error_code='ANALYZER_ERROR', **kwargs)
        self.analyzer_name = analyzer_name
        self.details['analyzer'] = analyzer_name


class PipelineError(VigilError):
    """Error in the detection pipeline orchestration."""

    def __init__(self, message, failed_analyzers=None, **kwargs):
        super().__init__(message, error_code='PIPELINE_ERROR', **kwargs)
        self.failed_analyzers = failed_analyzers or []
        self.details['failed_analyzers'] = self.failed_analyzers


class FusionError(VigilError):
    """Error during finding fusion/aggregation."""

    def __init__(self, message, **kwargs):
        super().__init__(message, error_code='FUSION_ERROR', **kwargs)


class DatabaseError(VigilError):
    """Error in database operations."""

    def __init__(self, message, **kwargs):
        super().__init__(message, error_code='DB_ERROR', retryable=True, **kwargs)


class ModelLoadError(VigilError):
    """Error loading ML model weights."""

    def __init__(self, message, model_path='', **kwargs):
        super().__init__(message, error_code='MODEL_LOAD_ERROR', **kwargs)
        self.details['model_path'] = model_path
