"""
Vigil AI — Text Autoencoder (Linear) Training
===========================================
Implements an "autoencoder-style" anomaly detector using TruncatedSVD
(a linear autoencoder) trained on SAFE text only.

At inference time, we compute reconstruction error on feature vectors and
flag unusually high-error chunks as "anomalous" (potentially novel dark patterns).
"""

import os
import sys
from typing import List, Tuple

import joblib
import numpy as np

# Reuse the exact same custom feature extractor as the classifier
PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.abspath(PROJECT_ROOT))
from app.services.ml_analyzer import extract_custom_features  # noqa: E402

from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: E402
from sklearn.pipeline import FeatureUnion  # noqa: E402
from sklearn.preprocessing import FunctionTransformer, MaxAbsScaler  # noqa: E402
from sklearn.decomposition import TruncatedSVD  # noqa: E402
from sklearn.model_selection import train_test_split  # noqa: E402


def _load_dataset() -> List[Tuple[str, str]]:
    """
    Load the dataset used by the supervised model so we don't need a new file format.
    Importing this module is safe: it only defines DATASET at module scope.
    """
    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
    from train_ml_model import DATASET  # type: ignore  # noqa: E402

    return list(DATASET)


def _build_feature_union():
    # Keep these aligned with train_ml_model.py
    word_tfidf = TfidfVectorizer(
        analyzer="word",
        ngram_range=(1, 3),
        max_features=10000,
        sublinear_tf=True,
        min_df=1,
        lowercase=True,
    )
    char_tfidf = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(3, 6),
        max_features=8000,
        sublinear_tf=True,
        min_df=1,
        lowercase=True,
    )
    custom_feats = FunctionTransformer(extract_custom_features)

    return FeatureUnion(
        [
            ("word", word_tfidf),
            ("char", char_tfidf),
            ("custom", custom_feats),
        ]
    )


def _reconstruction_mse(x_scaled, xhat_scaled) -> np.ndarray:
    """
    Compute per-row mean squared reconstruction error.
    x_scaled can be sparse; xhat_scaled is dense.
    """
    if hasattr(x_scaled, "toarray"):
        x_dense = x_scaled.toarray()
    else:
        x_dense = np.asarray(x_scaled)
    diff = x_dense - xhat_scaled
    return np.mean(diff * diff, axis=1)


def train(
    n_components: int = 256,
    threshold_percentile: float = 99.0,
    random_state: int = 42,
):
    dataset = _load_dataset()
    safe_texts = [t for (t, y) in dataset if y == "safe"]

    if len(safe_texts) < 50:
        raise RuntimeError("Not enough SAFE examples to train autoencoder.")

    X_train, X_val = train_test_split(
        safe_texts, test_size=0.2, random_state=random_state
    )

    feature_union = _build_feature_union()
    scaler = MaxAbsScaler()
    svd = TruncatedSVD(n_components=n_components, random_state=random_state)

    print("=" * 72)
    print("  Vigil AI — Text Autoencoder (Linear/SVD) Training")
    print("=" * 72)
    print(f"  SAFE samples: {len(safe_texts)} (train={len(X_train)}, val={len(X_val)})")
    print(f"  SVD components: {n_components}")
    print(f"  Threshold percentile (val): {threshold_percentile}")

    # Fit transforms on SAFE train
    X_train_feats = feature_union.fit_transform(X_train)
    X_train_scaled = scaler.fit_transform(X_train_feats)
    svd.fit(X_train_scaled)

    # Compute validation reconstruction errors
    X_val_feats = feature_union.transform(X_val)
    X_val_scaled = scaler.transform(X_val_feats)
    Z = svd.transform(X_val_scaled)
    Xhat_val_scaled = svd.inverse_transform(Z)
    val_err = _reconstruction_mse(X_val_scaled, Xhat_val_scaled)

    threshold = float(np.percentile(val_err, threshold_percentile))
    print(f"  Val reconstruction error: mean={val_err.mean():.6f}, p99={np.percentile(val_err, 99):.6f}")
    print(f"  Chosen threshold: {threshold:.6f}")

    artifact = {
        "kind": "vigil_text_ae_svd",
        "version": 1,
        "feature_union": feature_union,
        "scaler": scaler,
        "svd": svd,
        "threshold": threshold,
        "threshold_percentile": threshold_percentile,
        "n_components": n_components,
        "random_state": random_state,
    }

    models_dir = os.path.join(os.path.dirname(__file__), "..", "app", "models")
    os.makedirs(models_dir, exist_ok=True)
    model_path = os.path.join(models_dir, "dp_text_ae.pkl")
    joblib.dump(artifact, model_path)

    print(f"\n  ✓ Autoencoder artifact saved → {os.path.abspath(model_path)}")
    print("=" * 72)


if __name__ == "__main__":
    train()

