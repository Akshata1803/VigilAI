"""
Vigil AI — Production Entry Point
====================================
Graceful shutdown via SIGTERM/SIGINT.
Configures UTF-8 encoding on Windows.
"""

import sys
import os
import signal
import threading

# Fix Windows console encoding (must be first)
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    os.environ['PYTHONIOENCODING'] = 'utf-8'

from app import create_app
from app.core.logger import get_logger

app = create_app()
_logger = get_logger('vigil.main')

# ── Graceful shutdown ──────────────────────────────────────────────────────────
_shutdown_event = threading.Event()


def _handle_signal(signum, frame):
    _logger.info(f"Received signal {signum} -- shutting down gracefully...")
    _shutdown_event.set()


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)

if __name__ == '__main__':
    from app.core.auth import AUTH_ENABLED
    from app.core.config import Config

    threads = int(os.getenv('VIGIL_THREADS', '8'))
    port    = int(os.getenv('VIGIL_PORT', '5000'))

    _logger.info("=" * 60)
    _logger.info("  VIGIL AI -- Enterprise Dark Pattern Detection Engine")
    _logger.info(f"  Version:  {Config.VERSION}")
    _logger.info(f"  Auth:     {'ENABLED (X-API-Key required)' if AUTH_ENABLED else 'DISABLED (dev mode)'}")
    _logger.info(f"  Frontend: http://localhost:{port}")
    _logger.info(f"  API:      http://localhost:{port}/api")
    _logger.info(f"  Health:   http://localhost:{port}/api/health")
    _logger.info(f"  Async:    http://localhost:{port}/api/scan/async")
    _logger.info("=" * 60)

    from waitress import create_server

    server = create_server(app, host='0.0.0.0', port=port, threads=threads)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    _logger.info(f"Server running on port {port} with {threads} threads")

    # Block until shutdown signal
    _shutdown_event.wait()

    _logger.info("Closing server...")
    server.close()
    _logger.info("Shutdown complete.")
