from flask import Flask, send_from_directory
from flask_cors import CORS
import os

def create_app():
    static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static')
    app = Flask(__name__, static_folder=static_dir)

    # S-1 FIX: Restrict CORS — only allow localhost dev + Chrome extension
    allowed_origins = os.getenv('VIGIL_CORS_ORIGINS', 'http://localhost:5000,http://127.0.0.1:5000').split(',')
    CORS(app, origins=[o.strip() for o in allowed_origins])
    
    from app.extensions import limiter, logger

    app.config['SCREENSHOT_DIR'] = os.path.join(static_dir, 'screenshots')
    os.makedirs(app.config['SCREENSHOT_DIR'], exist_ok=True)
    
    # Init Rate Limiter (Flask-Limiter)
    limiter.init_app(app)
    logger.info("Enterprise components initialized: Rate-Limiting & Structured Logging online")

    # SEC-4 FIX: Request body size limit (1MB max, prevents DoS)
    app.config['MAX_CONTENT_LENGTH'] = 1 * 1024 * 1024

    # Start Background Screenshot Cleanup Thread
    import threading
    import time
    from app.core.config import Config

    def cleanup_old_screenshots(directory, age_hours, interval_s):
        logger.info(f"Started background TTL cleaner for {directory}")
        while True:
            try:
                now = time.time()
                count = 0
                for filename in os.listdir(directory):
                    filepath = os.path.join(directory, filename)
                    if os.path.isfile(filepath):
                        if os.stat(filepath).st_mtime < now - age_hours * 3600:
                            os.remove(filepath)
                            count += 1
                if count > 0:
                    logger.info(f"LRU Cleaner: Purged {count} old screenshots.")
            except Exception as e:
                logger.error(f"LRU Cleaner error: {e}")
            time.sleep(interval_s)

    cleaner_thread = threading.Thread(
        target=cleanup_old_screenshots, 
        args=(
            app.config['SCREENSHOT_DIR'],
            Config.SCREENSHOT_TTL_HOURS,
            Config.SCREENSHOT_CLEANUP_INTERVAL_S,
        ),
        daemon=True
    )
    cleaner_thread.start()

    # Register blueprints
    from app.routes.scan import scan_bp
    from app.routes.report import report_bp
    from app.routes.analytics import analytics_bp
    
    app.register_blueprint(scan_bp, url_prefix='/api')
    app.register_blueprint(report_bp, url_prefix='/api')
    app.register_blueprint(analytics_bp, url_prefix='/api')
    
    # Serve frontend
    @app.route('/')
    def serve_frontend():
        return send_from_directory(static_dir, 'index.html')
    
    # SEC-1 FIX: Add CSP + Security headers
    @app.after_request
    def set_security_headers(response):
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self';"
        )
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response

    return app
