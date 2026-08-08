# 🧠 Vigil AI — Training Pipeline (Planned)

This directory is reserved for the **supervised ML training pipeline** for Vigil AI v2.

## Current Architecture

Vigil AI v1 uses a **rule-based + heuristic** approach across 9 analysis engines:
- 300+ hand-crafted regex patterns for NLP
- Structural heuristics for DOM analysis
- Cialdini-mapped behavioural scoring
- Flesch-Kincaid readability scoring

This is intentional — rule-based systems are **transparent, auditable, and legally defensible**, which matters for a tool used in regulatory compliance contexts.

## Planned: v2 ML Enhancements

| Model | Purpose | Dataset |
|---|---|---|
| `fine_grained_nlp.pkl` | Multi-class dark pattern NLP classifier | ORCA dataset (Princeton) + custom labels |
| `visual_cnn.h5` | Screenshot-based dark pattern CNN | Synthetic + scraped UI screenshots |
| `trust_score_regressor.pkl` | Calibrated trust score regression | Scan history + manual ground truth |

## Datasets Referenced

- **Princeton ORCA corpus** — 11,000+ pages labelled for dark patterns
- **GrayScale** — GDPR dark pattern dataset from CNIL/DPA reports
- **UIGuard benchmark** — Visual dark pattern image dataset

## Timeline

Training pipeline will be implemented in **Vigil AI v2.0**.
Current v1 ships without trained models to maintain zero external ML dependencies at runtime.
