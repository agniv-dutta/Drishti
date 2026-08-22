"""Train recovery-risk / strategy models.

Engines (auto-detected or chosen via --engine):
    sklearn    HistGradientBoosting baseline - always available
    h2o        H2O AutoML                    - pip install h2o (+ Java 8+)
    autogluon  AWS AutoGluon                 - pip install autogluon

Labels are weak-supervision: synthetic outcomes sampled from the heuristic
scorer. In production, join real recovery outcomes from the ``recoveries``
table instead (see notebooks/02_automl_training.ipynb).

Outputs:
    models/risk_scorer.joblib          -> predict_proba compatible [P(fail), P(success)]
    models/recovery_classifier.joblib  -> classes_ = RecoveryStrategy values
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np


def build_dataset(n_samples: int, seed: int):
    from app.ml.data_preprocessor import FEATURE_NAMES, build_features
    from app.ml.risk_scorer import RiskScorer
    from app.models.payment import PaymentTransaction, CustomerInfo
    from app.utils.mock_data import make_failed_payment

    rng = random.Random(seed)
    scorer = RiskScorer()
    rows, labels = [], []

    for _ in range(n_samples):
        payload = make_failed_payment(seed=rng.randint(0, 10**9))
        txn = PaymentTransaction(
            payment_id="train",
            order_id=payload["order_id"],
            customer=CustomerInfo(**payload["customer"]),
            amount_paise=int(payload["amount"] * 100),
            method=payload["method"],
            status="failed",
            error_code=payload["failure_reason_code"],
        )
        features = build_features(txn)
        score, _, _ = scorer.score(features)
        rows.append([features[name] for name in FEATURE_NAMES])
        labels.append(1 if rng.random() < score else 0)  # weak supervision

    return np.array(rows), np.array(labels), FEATURE_NAMES


def train_sklearn(X, y) -> object:
    from sklearn.ensemble import HistGradientBoostingClassifier

    model = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.08, random_state=42)
    model.fit(X, y)
    return model


def train_h2o(X, y, feature_names):
    import h2o
    from h2o.automl import H2OAutoML
    import pandas as pd

    h2o.init(max_mem_size="1G", nthreads=-1)
    frame = pd.DataFrame(X, columns=feature_names)
    frame["target"] = y.astype(str)
    hf = h2o.H2OFrame(frame)
    hf["target"] = hf["target"].asfactor()

    aml = H2OAutoML(max_models=10, seed=42, balance_classes=True, max_runtime_secs=180)
    aml.train(x=feature_names, y="target", training_frame=hf)

    leader = aml.leader

    class _H2OSklearnShim:
        """predict_proba-compatible wrapper persisted via joblib."""

        def __init__(self, h2o_model, names):
            self._model_path = h2o_model.download_mojo(path=str(Path("models")))
            self.feature_names = list(names)

        def predict_proba(self, rows):
            import h2o

            h2o.no_progress()
            frame = h2o.H2OFrame(
                __import__("pandas").DataFrame(rows, columns=self.feature_names)
            )
            preds = h2o.predict(h2o.load_model(self._model_path), frame).as_data_frame()
            # class columns follow lexicographic factor order ('0','1')
            cols = sorted(c for c in preds.columns if c not in ("predict",))
            p1 = preds[cols[-1]].to_numpy()
            return np.stack([1 - p1, p1], axis=1)

        @property
        def classes_(self):
            return ["0", "1"]

    return _H2OSklearnShim(leader, feature_names)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train AutoML risk/strategy models")
    parser.add_argument("--engine", choices=["auto", "sklearn", "h2o", "autogluon"], default="auto")
    parser.add_argument("--samples", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--model-dir", default="models")
    args = parser.parse_args()

    Path(args.model_dir).mkdir(parents=True, exist_ok=True)

    print(f"Building dataset ({args.samples} samples, weak supervision)...")
    X, y, feature_names = build_dataset(args.samples, args.seed)
    print(f"Positive rate: {y.mean():.3f}")

    engine = args.engine
    if engine == "auto":
        for candidate, module_name in [("h2o", "h2o"), ("autogluon", "autogluon")]:
            try:
                __import__(module_name)
                engine = candidate
                break
            except ImportError:
                continue
        else:
            engine = "sklearn"
    print(f"Training with engine: {engine}")

    import joblib
    from sklearn.model_selection import train_test_split

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=args.seed, stratify=y)

    if engine == "h2o":
        model = train_h2o(X_train, y_train, feature_names)
    elif engine == "autogluon":
        raise SystemExit("autogluon training is wired in notebooks/02_automl_training.ipynb")
    else:
        model = train_sklearn(X_train, y_train)

    from sklearn.metrics import roc_auc_score

    proba = model.predict_proba(list(map(list, X_test)))[:, 1]
    print(f"Test ROC-AUC: {roc_auc_score(y_test, proba):.4f}")

    risk_path = Path(args.model_dir) / "risk_scorer.joblib"
    joblib.dump(model, risk_path)
    print(f"Saved risk model -> {risk_path}")

    # Strategy classifier uses the five-class feature contract and balanced weights.
    from app.ml.data_preprocessor import build_strategy_features
    from app.ml.strategy_model import train_strategy_model

    strategy_rows, strategy_labels = [], []
    reasons = ["insufficient_funds", "authentication_timeout", "bank_decline", "invalid_card_details", "card_expired", "network_error", "risk_blocked", "customer_dropoff", "unknown"]
    segments = ["new", "retained", "high-value"]
    preferences = ["sms", "call", "email", "none"]
    for index in range(max(n_samples, 100)):
        reason = reasons[index % len(reasons)]
        segment = segments[index % len(segments)]
        preference = preferences[index % len(preferences)]
        failure_count = index % 5
        days_since_attempt = float(index % 15)
        row = build_strategy_features(
            reason, segment, failure_count, days_since_attempt, preference
        )
        label = (
            "escalate" if failure_count >= 4 or reason == "risk_blocked"
            else "offer" if segment == "high-value"
            else "call" if preference == "call"
            else "sms" if preference == "sms"
            else "retry"
        )
        strategy_rows.append(row)
        strategy_labels.append(label)

    strategy_model = train_strategy_model(strategy_rows, strategy_labels, args.seed)
    strategy_path = Path(args.model_dir) / "recovery_classifier.joblib"
    joblib.dump(strategy_model, strategy_path)
    print(f"Saved strategy classifier -> {strategy_path}")


if __name__ == "__main__":
    main()
