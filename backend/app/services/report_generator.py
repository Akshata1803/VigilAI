"""
Vigil AI - GOD MODE Report Generator
Advanced trust scoring with legal compliance flagging, weighted penalty matrix,
category correlation bonuses, and regulatory reference tagging.
"""

import time
from collections import Counter

from app.core.config import Config


class ReportGenerator:
    """GOD MODE: Generates comprehensive dark pattern reports with legal compliance tags."""

    # Calibration targets (HADE-aligned — only HIGH/CRITICAL significantly reduce score):
    #   0 findings             → 95   (clean site)
    #   1 CRITICAL finding     → ~80  (serious — e.g. cookie wall)
    #   3 HIGH findings        → ~73  (notable issues)
    #   5 HIGH + 3 MEDIUM      → ~55  (meaningful problems)
    #   10+ HIGH + CRITICAL    → ~20–40 (bad site)
    SEVERITY_WEIGHTS = {
        'CRITICAL': 12.0,  # Direct user harm — forced action, cookie wall, basket sneaking
        'HIGH':      7.0,  # Strong manipulation (pre-checked boxes, confirmshaming)
        'MEDIUM':    4.0,  # Behavioral nudging
        'LOW':       0.0,  # Not penalised — post-consensus LOW findings are informational noise
        'INFORMATIONAL': 0.0,  # Never penalised
    }

    # ── Category multipliers (some are worse than others) ───────────────────────
    CATEGORY_MULTIPLIERS = {
        'privacy':           1.50,   # GDPR/privacy violations are most serious
        'forced_continuity': 1.40,   # Auto-billing traps
        'obstruction':       1.30,   # Roach motel, sludge
        'confirmshaming':    1.20,
        'trick_question':    1.20,
        'hidden_costs':      1.20,
        'preselection':      1.15,
        'misdirection':      1.10,
        'urgency':           1.00,
        'emotional':         1.00,
        'social_proof':      0.90,
        'forced_action':     1.10,
        'disguised_ads':     0.90,
        'nagging':           0.85,
        # Compound/behavioral findings are META-summaries of existing violations.
        # They must not be double-penalised at full weight — they synthesise
        # what the base findings already captured.
        'compound_pattern':  0.25,
    }

    # ── Legal framework references per category ──────────────────────────────────
    LEGAL_REFS = {
        'privacy':           ['GDPR Art. 7', 'GDPR Art. 17', 'CCPA §1798.100', 'DPDP Act 2023'],
        'forced_continuity': ['FTC ROSCA Act', 'EU Consumer Rights Directive', 'UK CRA 2015'],
        'hidden_costs':      ['EU Price Indication Directive', 'FTC Act §5', 'ASA Guidelines'],
        'preselection':      ['GDPR Art. 7(4)', 'EU ePrivacy Directive Art. 5(3)'],
        'confirmshaming':    ['FTC Act §5', 'EU Unfair Commercial Practices Directive'],
        'trick_question':    ['FTC Act §5', 'EU UCPD Art. 7'],
        'obstruction':       ['FTC ROSCA Act', 'EU Consumer Rights Directive Art. 9'],
        'misdirection':      ['FTC Act §5', 'EU UCPD Art. 6'],
        'urgency':           ['ASA CAP Code', 'FTC Act §5', 'EU UCPD Art. 7'],
        'social_proof':      ['FTC Endorsement Guidelines', 'ASA CAP Code'],
        'nagging':           ['EU ePrivacy Directive', 'GDPR Recital 32'],
        'emotional':         ['EU UCPD Art. 8–9 (Aggressive Practices)'],
        'disguised_ads':     ['FTC Native Advertising Guidelines', 'ASA CAP Rule 2.1'],
        'forced_action':     ['GDPR Art. 7', 'EU Consumer Rights Directive'],
        'visual_misdirection':['WCAG 2.1 SC 1.4.3', 'FTC Clear and Conspicuous Standard'],
        'visual_urgency':    ['ASA CAP Rule 3.1', 'FTC .com Disclosures'],
        'visual_clutter':    ['GDPR Art. 12 (Transparent Information)', 'CCPA §999.305'],
        'visual_obstruction':['ADA Title III', 'WCAG 2.1 SC 1.4.3'],
        'compound_pattern':  ['DSA Art. 25 (Dark Patterns Prohibition)', 'EDPB Guidelines 03/2022'],
    }

    # ── Category metadata ────────────────────────────────────────────────────────
    CATEGORY_INFO = {
        'preselection': {
            'name': 'Pre-selected Options',
            'icon': '☑️',
            'description': 'Checkboxes or options pre-selected by default, silently opting users in without consent.'
        },
        'urgency': {
            'name': 'Fake Urgency / Scarcity',
            'icon': '⏰',
            'description': 'Manufactured countdown timers, fake stock counts, or urgency language that pressures quick decisions.'
        },
        'hidden_costs': {
            'name': 'Hidden Costs / Drip Pricing',
            'icon': '💰',
            'description': 'Extra fees or charges revealed late in the process, obscuring the true cost.'
        },
        'misdirection': {
            'name': 'Misdirection / Interference',
            'icon': '🎯',
            'description': 'Visual or linguistic tricks to draw attention to preferred actions while hiding alternatives.'
        },
        'obstruction': {
            'name': 'Obstruction / Roach Motel',
            'icon': '🚪',
            'description': 'Easy to enter, deliberately hard to exit — blocking cancellation, deletion or account closure.'
        },
        'forced_continuity': {
            'name': 'Forced Continuity / Auto-billing',
            'icon': '🔄',
            'description': 'Auto-renewing subscriptions or free trials that silently convert to paid without clear warning.'
        },
        'confirmshaming': {
            'name': 'Confirmshaming',
            'icon': '😢',
            'description': 'Guilt-tripping decline options designed to psychologically punish users for saying no.'
        },
        'trick_question': {
            'name': 'Trick Questions / Double Negatives',
            'icon': '❓',
            'description': 'Confusing double negatives or deliberately misleading consent wording.'
        },
        'emotional': {
            'name': 'Emotional Manipulation / FUD',
            'icon': '💔',
            'description': 'Fear, Uncertainty, Doubt, guilt or social pressure used to override rational choices.'
        },
        'social_proof': {
            'name': 'Fake Social Proof',
            'icon': '👥',
            'description': 'Fabricated or unverifiable popularity claims using inflated counts or fake real-time data.'
        },
        'forced_action': {
            'name': 'Forced Action / Registration Gate',
            'icon': '🔒',
            'description': 'Requiring unnecessary account creation or subscription before accessing standard content.'
        },
        'privacy': {
            'name': 'Privacy Zuckering / Data Exploitation',
            'icon': '🕵️',
            'description': 'Tricking users into sharing more personal data than intended, often with third parties.'
        },
        'disguised_ads': {
            'name': 'Disguised Advertisements',
            'icon': '📰',
            'description': 'Ads presented as editorial content or navigation, violating FTC disclosure rules.'
        },
        'nagging': {
            'name': 'Nagging / Exit-Intent Traps',
            'icon': '🪤',
            'description': 'Persistent pop-ups, exit-intent interstitials or timed overlays that capture departing users.'
        },
        'visual_misdirection': {
            'name': 'Visual Misdirection',
            'icon': '🎨',
            'description': 'Color, size or layout manipulation to lead attention away from unfavorable choices.'
        },
        'visual_urgency': {
            'name': 'Visual Urgency Colors',
            'icon': '🔴',
            'description': 'Overuse of red/orange urgency coloring to psychologically pressure conversion.'
        },
        'visual_clutter': {
            'name': 'Visual Overload',
            'icon': '🌀',
            'description': 'Cluttered interface creating decision fatigue and overwhelming users into default actions.'
        },
        'visual_obstruction': {
            'name': 'Visual Obstruction',
            'icon': '🌑',
            'description': 'Low contrast or hidden information making important content deliberately hard to read.'
        }
    }

    def generate_report(self, scan_data, dom_findings, text_findings, visual_findings, advanced_findings=None):
        """Generate a comprehensive dark pattern report."""
        advanced_findings = advanced_findings or []
        all_findings = dom_findings + text_findings + visual_findings + advanced_findings

        # Deduplicate
        all_findings = self._deduplicate(all_findings)

        # Sort: HIGH first, then by weighted score (severity × confidence)
        severity_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3, 'INFORMATIONAL': 4}
        all_findings.sort(
            key=lambda f: (severity_order.get(f.get('severity', 'LOW'), 5), -f.get('confidence', 0))
        )

        # --- CONTEXT-AWARE SCORING ---
        scan_state  = scan_data.get('scan_state', '') if isinstance(scan_data, dict) else ''
        trust_score = self._calculate_trust_score(all_findings)
        if scan_state == 'unauthenticated':
            trust_score = min(trust_score, 85)

        risk_level = self._get_risk_level(trust_score)

        severity_counts = Counter(f.get('severity', 'LOW') for f in all_findings)
        category_counts = Counter(f.get('category', 'unknown') for f in all_findings)

        # Attach legal refs + category info to each finding
        enriched_findings = []
        for i, finding in enumerate(all_findings):
            cat = finding.get('category', '')
            # Merge analyzer-level refs with category-level refs (deduplicated)
            merged_refs = list(set(finding.get('legal_refs', []) + self.LEGAL_REFS.get(cat, [])))
            enriched_findings.append({
                **finding,
                'id': f'dp-{i+1}',
                'category_info': self.CATEGORY_INFO.get(cat, {
                    'name': cat.replace('_', ' ').title(),
                    'icon': '⚠️',
                    'description': 'Dark pattern detected.'
                }),
                'legal_refs': merged_refs
            })

        # Compliance flags
        compliance_flags = self._get_compliance_flags(all_findings)

        # Overall grade
        grade = self._get_grade(trust_score)

        report = {
            'scan_id':       scan_data.get('scan_id', ''),
            'url':           scan_data.get('url', ''),
            'domain':        scan_data.get('domain', ''),
            'page_title':    scan_data.get('page_title', ''),
            'timestamp':     scan_data.get('timestamp', time.strftime('%Y-%m-%d %H:%M:%S')),
            'screenshot_path': scan_data.get('screenshot_path'),

            # Trust metrics
            'trust_score':     trust_score,
            'risk_level':      risk_level,
            'grade':           grade,
            'total_patterns':  len(all_findings),

            # Breakdowns
            'severity_breakdown': {
                'critical': severity_counts.get('CRITICAL', 0),
                'high':   severity_counts.get('HIGH', 0),
                'medium': severity_counts.get('MEDIUM', 0),
                'low':    severity_counts.get('LOW', 0),
                'informational': severity_counts.get('INFORMATIONAL', 0)
            },
            'category_breakdown': [
                {
                    'category': cat,
                    'count': count,
                    'info': self.CATEGORY_INFO.get(cat, {
                        'name': cat.replace('_', ' ').title(),
                        'icon': '⚠️',
                        'description': 'Dark pattern category.'
                    }),
                    'legal_refs': self.LEGAL_REFS.get(cat, [])
                }
                for cat, count in category_counts.most_common()
            ],
            'analysis_breakdown': {
                'dom_findings':      len(dom_findings),
                'text_findings':     len(text_findings),
                'visual_findings':   len(visual_findings),
                'elite_findings':    len(advanced_findings)
            },

            # Compliance
            'compliance_flags': compliance_flags,
            'regulations_violated': list({ref for cat in category_counts.keys() for ref in self.LEGAL_REFS.get(cat, [])}),

            # Findings
            'findings': enriched_findings,

            # Summary
            'summary': self._generate_summary(all_findings, trust_score, scan_data.get('domain', ''), grade, scan_data.get('scan_state', '')),
            'recommendations': self._generate_top_recommendations(all_findings),

            'status': 'completed'
        }

        return report

    def _calculate_trust_score(self, findings):
        """
        Exponential decay trust score with diminishing returns.

        Formula: score = 95 × e^(−penalty / K)

        K = 60 (decay constant) — calibration targets:
          0  findings           → 95   (clean site)
          5  HIGH findings      → ~62  (notable problems)
          10 HIGH findings      → ~38  (bad site)
          15 mixed findings     → ~40  (Booking.com tier)
          20 mixed + compound   → ~30  (BBC/Reddit tier — genuinely problematic)
          30+ HIGH severity     → ~10-18 (egregious violators)

        Compound findings get a 0.25 multiplier so they don't
        double-penalise violations already captured by base findings.
        """
        import math
        if not findings:
            return 95

        total_penalty = 0.0
        for finding in findings:
            severity = finding.get('severity', 'LOW')
            # LOW and INFORMATIONAL are not penalised — consensus engine filtered noise already
            if severity in ('INFORMATIONAL', 'LOW'):
                continue
            confidence  = finding.get('confidence', 0.5)
            category    = finding.get('category', '')
            base_weight = self.SEVERITY_WEIGHTS.get(severity, 0.0)
            if base_weight == 0.0:
                continue
            multiplier    = self.CATEGORY_MULTIPLIERS.get(category, 1.0)
            total_penalty += base_weight * confidence * multiplier

        # Exponential decay: diminishing returns prevent collapse to minimum
        raw = Config.TRUST_SCORE_BASE * math.exp(-total_penalty / Config.TRUST_SCORE_DECAY_K)
        trust_score = max(Config.TRUST_SCORE_MIN, min(int(Config.TRUST_SCORE_BASE), round(raw)))
        return trust_score

    def _get_risk_level(self, trust_score):
        """Map trust score to risk level with color and CTA."""
        if trust_score >= 80:
            return {'level': 'LOW',      'label': 'Low Risk',      'color': '#10b981', 'emoji': '✅'}
        elif trust_score >= 60:
            return {'level': 'MODERATE', 'label': 'Moderate Risk', 'color': '#f59e0b', 'emoji': '⚠️'}
        elif trust_score >= 40:
            return {'level': 'HIGH',     'label': 'High Risk',     'color': '#f97316', 'emoji': '🔶'}
        else:
            return {'level': 'CRITICAL', 'label': 'Critical Risk', 'color': '#ef4444', 'emoji': '🔴'}

    def _get_grade(self, trust_score):
        """Assign a letter grade."""
        if trust_score >= 90: return {'letter': 'A+', 'color': '#10b981'}
        if trust_score >= 80: return {'letter': 'A',  'color': '#10b981'}
        if trust_score >= 70: return {'letter': 'B',  'color': '#84cc16'}
        if trust_score >= 60: return {'letter': 'C',  'color': '#f59e0b'}
        if trust_score >= 45: return {'letter': 'D',  'color': '#f97316'}
        return                       {'letter': 'F',  'color': '#ef4444'}

    def _get_compliance_flags(self, findings):
        """Generate simplified compliance flags from findings."""
        flags = []
        cats = {f.get('category', '') for f in findings}

        if 'privacy' in cats or 'preselection' in cats:
            flags.append({'regulation': 'GDPR', 'status': 'RISK', 'icon': '🇪🇺'})
        if 'forced_continuity' in cats or 'obstruction' in cats:
            flags.append({'regulation': 'FTC ROSCA', 'status': 'RISK', 'icon': '🇺🇸'})
        if 'hidden_costs' in cats:
            flags.append({'regulation': 'Consumer Protection', 'status': 'RISK', 'icon': '⚖️'})
        if 'disguised_ads' in cats:
            flags.append({'regulation': 'FTC Disclosure', 'status': 'RISK', 'icon': '📋'})
        if any(f.get('type', '').startswith('Potential Children') for f in findings):
            flags.append({'regulation': 'COPPA', 'status': 'CRITICAL', 'icon': '👶'})

        return flags

    def _deduplicate(self, findings):
        """Deduplicate by (type, category) key."""
        seen = set()
        unique = []
        for f in findings:
            key = (f.get('type', ''), f.get('category', ''))
            if key not in seen:
                seen.add(key)
                unique.append(f)
        return unique

    def _generate_summary(self, findings, trust_score, domain, grade, scan_state=""):
        """Generate a detailed, human-readable executive summary."""
        if not findings:
            return (
                f"Vigil AI found no dark patterns on {domain}. "
                f"The website appears to follow ethical, user-respecting design practices. "
                f"Trust Score: {trust_score}/100 (Grade: {grade['letter']})."
            )

        critical = sum(1 for f in findings if f.get('severity') == 'CRITICAL')
        high     = sum(1 for f in findings if f.get('severity') == 'HIGH')
        medium   = sum(1 for f in findings if f.get('severity') == 'MEDIUM')
        low      = sum(1 for f in findings if f.get('severity') == 'LOW')
        cats     = list({f.get('category', '') for f in findings
                         if f.get('severity') not in ('INFORMATIONAL', 'LOW')})

        parts = [
            f"Vigil AI detected {len(findings)} dark pattern(s) across "
            f"{max(1, len(cats))} categor{'y' if len(cats) == 1 else 'ies'} on {domain}."
        ]

        if critical > 0:
            parts.append(
                f"{critical} CRITICAL issue(s) confirmed — direct user harm "
                f"(forced consent, hidden charges or tracking without consent). "
                f"Regulatory action risk is HIGH."
            )
        if high > 0:
            parts.append(
                f"{high} HIGH severity manipulation(s) found that seriously compromise user autonomy."
            )
        if medium > 0:
            parts.append(f"{medium} MEDIUM severity issue(s) that apply behavioral pressure.")
        if low > 0:
            parts.append(f"{low} LOW severity observation(s) worth addressing for best practices.")

        parts.append(f"Trust Score: {trust_score}/100 — Grade: {grade['letter']}.")
        
        if scan_state == 'unauthenticated':
            parts.append("Note: Limited scan due to missing user session. Some deep patterns may be hidden.")
            
        return ' '.join(parts)

    def _generate_top_recommendations(self, findings):
        """Extract and deduplicate the top 5 most important recommendations."""
        seen = set()
        recs = []
        for f in findings:
            rec = f.get('recommendation', '')
            if rec and rec not in seen:
                seen.add(rec)
                recs.append({
                    'severity': f.get('severity', 'LOW'),
                    'type': f.get('type', ''),
                    'recommendation': rec
                })
            if len(recs) >= 5:
                break
        return recs
