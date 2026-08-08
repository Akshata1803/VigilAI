"""Vigil AI - Analytics Routes"""
from flask import Blueprint, jsonify
from app.services.database import get_history, get_stats
from collections import Counter

analytics_bp = Blueprint('analytics', __name__)

@analytics_bp.route('/analytics/summary', methods=['GET'])
def get_analytics():
    """Get overall analytics from persistent scan DB."""
    history = get_history(limit=50) # Get top 50
    db_stats = get_stats()

    if not history:
        return jsonify({
            'total_scans': 0,
            'avg_trust_score': 0,
            'most_common_risk': 'N/A',
            'scans': []
        })

    scores = [s['trust_score'] for s in history]
    # history rows are plain dicts from SQLite — 'risk_label' is a string, not a dict
    risk_levels = [s.get('risk_label', 'Low Risk') for s in history]
    risk_counter = Counter(risk_levels)

    return jsonify({
        'total_scans': db_stats['total_scans'],
        'avg_trust_score': db_stats['avg_trust_score'],
        'highest_trust': db_stats['max_trust_score'],
        'lowest_trust': db_stats['min_trust_score'],
        'most_common_risk': risk_counter.most_common(1)[0][0] if risk_counter else 'N/A',
        'risk_distribution': dict(risk_counter),
        'scans': history[:20]
    })
