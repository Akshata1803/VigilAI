"""Quick eval script — run from backend/train/"""
import os, sys, joblib
sys.path.insert(0, os.path.dirname(__file__))

from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report

from train_ml_model import DATASET

texts  = [d[0] for d in DATASET]
labels = [d[1] for d in DATASET]

model_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'models', 'dp_classifier.pkl')
model = joblib.load(model_path)

X_train, X_test, y_train, y_test = train_test_split(
    texts, labels, test_size=0.18, random_state=42, stratify=labels
)

y_pred = model.predict(X_test)
acc = accuracy_score(y_test, y_pred)

print(f"Dataset     : {len(DATASET)} examples, {len(set(labels))} classes")
print(f"Test set    : {len(X_test)} samples")
print(f"Test Accuracy: {acc*100:.1f}%\n")
print(classification_report(y_test, y_pred))
