"""Vigil AI - Report Routes"""
from flask import Blueprint, jsonify
from app.services.database import get_scan

report_bp = Blueprint('report', __name__)


@report_bp.route('/report/<scan_id>', methods=['GET'])
def get_report(scan_id):
    """Get a previously generated report by scan ID from the persistent DB."""
    # FIX D-2: Validate scan_id format before hitting DB
    if not scan_id or len(scan_id) > 64 or not scan_id.replace('-', '').isalnum():
        return jsonify({
            'error': 'Invalid scan ID format.',
            'status': 'error'
        }), 400
    report = get_scan(scan_id)
    if not report:
        return jsonify({
            'error': f'Report not found. Verify the scan_id or run a new scan.',
            'status': 'error'
        }), 404
    return jsonify(report)

