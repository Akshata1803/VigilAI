"""
Vigil AI — Async Scan Task Interface
=========================================
Public API for submitting and querying async scan tasks.

This module wraps the AsyncTaskWorker singleton and provides
a clean interface used by the scan routes.

Architecture:
  Flask (API) → ThreadPoolExecutor (background) → In-Memory Store
  Client polls /api/scan/status/<task_id> for completion.
"""

from app.worker import task_worker, TaskState
from app.core.logger import get_logger

_logger = get_logger('vigil.tasks')


def scan_website_task(url: str, cookies: list = None, scan_options: dict = None) -> str:
    """
    Submit an async scan task — runs the full pipeline in a background thread.

    Args:
        url: Target URL to scan
        cookies: Optional list of cookie dicts
        scan_options: Optional dict with scan configuration

    Returns:
        task_id (str): UUID for polling via get_task_status()
    """
    return task_worker.submit(url, cookies=cookies, scan_options=scan_options)


def get_task_status(task_id: str) -> dict:
    """
    Get the current status of an async scan task.

    Returns a dict matching the API response contract:
        {
            'task_id': str,
            'state': 'PENDING' | 'SCANNING' | 'ANALYZING' | 'CALIBRATING' | 'SUCCESS' | 'FAILURE',
            'progress': int (0-100),
            'stage': str,
            'url': str,
            'result': dict | None,   # Only when state == SUCCESS
            'error': str | None,     # Only when state == FAILURE
        }
    """
    task = task_worker.get_status(task_id)

    if task is None:
        return None

    response = {
        'task_id': task.task_id,
        'state': task.state,
        'progress': task.progress,
        'stage': task.stage,
        'url': task.url,
    }

    if task.state == 'SUCCESS' and task.result:
        response['result'] = task.result

    if task.state == 'FAILURE' and task.error:
        response['error'] = task.error

    return response
