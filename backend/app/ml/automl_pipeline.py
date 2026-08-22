"""AutoML pipeline for payment-recovery risk scoring.

Generates a synthetic 50k-row dataset of failed payment transactions,
engineers recovery-risk features (KNN imputation, one-hot + standard
scaling, amount x tenure and decline_code x time_of_day interactions,
is_weekend / is_high_fraud_time domain flags), then trains candidate
regressors predicting ``recovery_outcome`` (expected success rate 0-100).

Backend chain: H2O AutoML -> AutoGluon -> FLAML -> built-in sklearn
harness. Available backends are trained under a common external 5-fold
CV protocol; the champion minimizes cv_MAE_mean + cv_RMSE_mean. The
winning raw-row-to-prediction sklearn Pipeline is exported as .pkl
alongside metrics.json and feature_importance.json.
"""

from __future__ import annotations

import inspect
import json
import math
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd

from sklearn.base import BaseEstimator, TransformerMixin, clone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import (
    ExtraTreesRegressor,
    HistGradientBoostingRegressor,
    RandomForestRegressor,
)
from sklearn.impute import KNNImputer, SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import KFold, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

TARGET_COLUMN = "recovery_outcome"
TIMESTAMP_COLUMN = "attempt_timestamp"
NUMERIC_COLUMNS = ["amount", "customer_tenure", "time_of_day"]
CATEGORICAL_COLUMNS = ["merchant_category", "decline_code", "device_type", "location"]

DECLINE_CODES = [
    "network_timeout",
    "otp_timeout",
    "do_not_honor",
    "invalid_cvv",
    "insufficient_funds",
    "bank_decline",
    "card_expired",
    "risk_blocked",
]
HIGH_FRAUD_HOURS = frozenset(range(0, 6))
INTERACTION_COLUMNS = [f"decline_{code}_x_tod" for code in DECLINE_CODES]
DERIVED_NUMERIC = ["amount_x_tenure"] + INTERACTION_COLUMNS
DOMAIN_BINARY = ["is_weekend", "is_high_fraud_time"]

DEFAULT_SEED = 42
DEFAULT_ROWS = 50_000
CV_FOLDS = 5
ARTIFACT_DIRNAME = "recovery_risk_automl"

_MERCHANT_CATALOG = [
    "grocery", "food_delivery", "electronics", "fashion",
    "utilities", "travel", "healthcare", "gaming",
]
_MERCHANT_WEIGHTS = [0.20, 0.16, 0.12, 0.12, 0.14, 0.10, 0.08, 0.08]
_DEVICE_CATALOG = ["android", "ios", "web", "desktop"]
_DEVICE_WEIGHTS = [0.42, 0.28, 0.22, 0.08]
_LOCATION_CATALOG = ["tier1_metro", "tier2_city", "tier3_town", "international"]
_LOCATION_WEIGHTS = [0.38, 0.30, 0.24, 0.08]

_DECLINE_WEIGHTS = {
    "network_timeout": 0.22,
    "otp_timeout": 0.16,
    "insufficient_funds": 0.18,
    "do_not_honor": 0.14,
    "invalid_cvv": 0.10,
    "bank_decline": 0.09,
    "card_expired": 0.06,
    "risk_blocked": 0.05,
}
_DECLINE_EFFECT = {
    "network_timeout": 26.0,
    "otp_timeout": 18.0,
    "do_not_honor": 8.0,
    "invalid_cvv": 2.0,
    "insufficient_funds": -6.0,
    "bank_decline": -10.0,
    "card_expired": -14.0,
    "risk_blocked": -30.0,
}
_MERCHANT_EFFECT = {
    "grocery": 4.0,
    "utilities": 3.0,
    "food_delivery": 2.0,
    "healthcare": 1.0,
    "fashion": 0.0,
    "electronics": -3.0,
    "travel": -5.0,
    "gaming": -7.0,
}
_DEVICE_EFFECT = {"ios": 4.0, "desktop": 2.0, "web": 1.5, "android": 0.5}
_LOCATION_EFFECT = {"tier1_metro": 3.0, "tier2_city": 1.0, "tier3_town": -1.0, "international": -9.0}
_NOISE_SD = 7.0


def _latent_success_rate(
    amount: np.ndarray,
    tenure: np.ndarray,
    hour: np.ndarray,
    decline: List[str],
    merchant: List[str],
    device: List[str],
    location: List[str],
    weekend: np.ndarray,
) -> np.ndarray:
    decline_effect = np.array([_DECLINE_EFFECT[code] for code in decline])
    merchant_effect = np.array([_MERCHANT_EFFECT[code] for code in merchant])
    device_effect = np.array([_DEVICE_EFFECT[code] for code in device])
    location_effect = np.array([_LOCATION_EFFECT[code] for code in location])
    span = math.log1p(40_000.0) - math.log1p(800.0)
    amount_penalty = np.clip(16.0 * (np.log1p(amount) - math.log1p(800.0)) / span, -7.0, 16.0)
    tenure_bonus = 10.0 * np.sqrt(np.minimum(tenure, 120.0) / 120.0) - 2.0
    peak_bonus = np.where((hour >= 10.0) & (hour <= 20.0), 5.0, 0.0)
    fraud_penalty = np.where(np.isin(np.floor(hour), list(HIGH_FRAUD_HOURS)), -12.0, 0.0)
    weekend_penalty = np.where(weekend, -3.0, 0.0)
    return (
        38.0
        + decline_effect
        + merchant_effect
        + device_effect
        + location_effect
        - amount_penalty
        + tenure_bonus
        + peak_bonus
        + fraud_penalty
        + weekend_penalty
    )


def generate_synthetic_recovery_data(n_rows: int = DEFAULT_ROWS, seed: int = DEFAULT_SEED) -> pd.DataFrame:
    """Build the synthetic corpus with realistic signal and missingness."""
    rng = np.random.default_rng(seed)
    end = pd.Timestamp.today().normalize()
    timestamps = end - pd.to_timedelta(rng.integers(0, 120 * 24 * 60, size=n_rows), unit="m")

    decline = rng.choice(list(_DECLINE_WEIGHTS), size=n_rows, p=list(_DECLINE_WEIGHTS.values()))
    merchant = rng.choice(_MERCHANT_CATALOG, size=n_rows, p=_MERCHANT_WEIGHTS)
    device = rng.choice(_DEVICE_CATALOG, size=n_rows, p=_DEVICE_WEIGHTS)
    location = rng.choice(_LOCATION_CATALOG, size=n_rows, p=_LOCATION_WEIGHTS)

    amount = np.exp(rng.normal(math.log(1500.0), 1.05, n_rows)).clip(80.0, 60_000.0).round(2)
    tenure = np.minimum(rng.exponential(26.0, n_rows), 120.0).round(0)
    hour = timestamps.hour.to_numpy() + timestamps.minute.to_numpy() / 60.0
    weekend = timestamps.dayofweek.to_numpy() >= 5

    latent = _latent_success_rate(amount, tenure, hour, decline, merchant, device, location, weekend)
    target = (latent + rng.normal(0.0, _NOISE_SD, n_rows)).clip(0.0, 100.0).round(1)

    df = pd.DataFrame(
        {
            TIMESTAMP_COLUMN: timestamps,
            "amount": amount,
            "merchant_category": merchant.astype(object),
            "customer_tenure": tenure,
            "decline_code": decline.astype(object),
            "time_of_day": hour.round(2),
            "device_type": device.astype(object),
            "location": location.astype(object),
            TARGET_COLUMN: target,
        }
    )

    df.loc[rng.choice(n_rows, int(n_rows * 0.02), replace=False), "amount"] = np.nan
    df.loc[rng.choice(n_rows, int(n_rows * 0.04), replace=False), "customer_tenure"] = np.nan
    df.loc[rng.choice(n_rows, int(n_rows * 0.05), replace=False), "time_of_day"] = np.nan
    for column in CATEGORICAL_COLUMNS:
        df.loc[rng.choice(n_rows, int(n_rows * 0.03), replace=False), column] = None
    return df


class RecoveryFeatureBuilder(BaseEstimator, TransformerMixin):
    """Derive domain flags and interaction terms from raw transaction rows."""

    def fit(self, X: pd.DataFrame, y=None) -> "RecoveryFeatureBuilder":
        self.feature_names_in_ = list(X.columns)
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(X, pd.DataFrame):
            X = pd.DataFrame(X)
        df = X.copy()
        tod = pd.to_numeric(df["time_of_day"], errors="coerce")
        if TIMESTAMP_COLUMN in df.columns:
            ts = pd.to_datetime(df[TIMESTAMP_COLUMN], errors="coerce")
            weekend = (ts.dt.dayofweek >= 5).astype(float).fillna(0.0)
        else:
            weekend = pd.Series(np.zeros(len(df)), index=df.index)
        df["is_weekend"] = weekend
        df["is_high_fraud_time"] = np.floor(tod).isin(HIGH_FRAUD_HOURS).astype(float)
        df["amount_x_tenure"] = (
            pd.to_numeric(df["amount"], errors="coerce")
            * pd.to_numeric(df["customer_tenure"], errors="coerce")
        )
        for code in DECLINE_CODES:
            indicator = (df["decline_code"] == code).astype(float)
            df[f"decline_{code}_x_tod"] = indicator * tod
        return df


def build_preprocessor() -> Pipeline:
    numeric_branch = Pipeline(
        steps=[
            ("impute", KNNImputer(n_neighbors=5, weights="distance", n_jobs=-1)),
            ("scale", StandardScaler()),
        ]
    )
    categorical_branch = Pipeline(
        steps=[
            ("impute", SimpleImputer(strategy="constant", fill_value="__missing__")),
            ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]
    )
    encoder = ColumnTransformer(
        transformers=[
            ("num", numeric_branch, NUMERIC_COLUMNS + DERIVED_NUMERIC),
            ("cat", categorical_branch, CATEGORICAL_COLUMNS),
            ("bin", "passthrough", DOMAIN_BINARY),
        ]
    )
    return Pipeline(steps=[("features", RecoveryFeatureBuilder()), ("encode", encoder)])


def engineered_feature_names(preprocessor: Pipeline) -> List[str]:
    raw_names = preprocessor.named_steps["encode"].get_feature_names_out().tolist()
    return [name.split("__", 1)[1] if "__" in name else name for name in raw_names]


@dataclass
class TrainedCandidate:
    backend: str
    model_name: str
    model_type: str
    estimator: Any
    cv_mae_folds: List[float] = field(default_factory=list)
    cv_rmse_folds: List[float] = field(default_factory=list)
    cv_source: str = "external-cv"
    train_seconds: float = 0.0

    @property
    def cv_mae_mean(self) -> float:
        return float(np.mean(self.cv_mae_folds)) if self.cv_mae_folds else float("inf")

    @property
    def cv_rmse_mean(self) -> float:
        return float(np.mean(self.cv_rmse_folds)) if self.cv_rmse_folds else float("inf")

    @property
    def combined_score(self) -> float:
        return self.cv_mae_mean + self.cv_rmse_mean


def _manual_cv(
    estimator: Any,
    Xe: np.ndarray,
    y: np.ndarray,
    folds: int = CV_FOLDS,
    seed: int = DEFAULT_SEED,
) -> Tuple[List[float], List[float]]:
    kfold = KFold(n_splits=folds, shuffle=True, random_state=seed)
    maes: List[float] = []
    rmses: List[float] = []
    for train_idx, val_idx in kfold.split(Xe):
        model = clone(estimator)
        model.fit(Xe[train_idx], y[train_idx])
        preds = model.predict(Xe[val_idx])
        maes.append(float(mean_absolute_error(y[val_idx], preds)))
        rmses.append(float(math.sqrt(mean_squared_error(y[val_idx], preds))))
    return maes, rmses


def _sklearn_candidates(seed: int) -> List[Tuple[str, str, Any]]:
    candidates: List[Tuple[str, str, Any]] = []
    try:
        from lightgbm import LGBMRegressor

        candidates.append((
            "lgbm",
            "LightGBM (LGBMRegressor)",
            LGBMRegressor(
                n_estimators=400,
                learning_rate=0.05,
                num_leaves=63,
                min_child_samples=40,
                subsample=0.9,
                colsample_bytree=0.9,
                random_state=seed,
                n_jobs=-1,
                verbose=-1,
            ),
        ))
    except ImportError:
        pass
    try:
        from xgboost import XGBRegressor

        candidates.append((
            "xgboost",
            "XGBoost (XGBRegressor)",
            XGBRegressor(
                tree_method="hist",
                n_estimators=500,
                learning_rate=0.05,
                max_depth=7,
                min_child_weight=5.0,
                subsample=0.9,
                colsample_bytree=0.9,
                reg_lambda=1.0,
                random_state=seed,
                n_jobs=-1,
            ),
        ))
    except ImportError:
        pass
    candidates.append((
        "hist-gbm",
        "HistGradientBoosting",
        HistGradientBoostingRegressor(
            max_iter=400,
            learning_rate=0.06,
            max_leaf_nodes=31,
            l2_regularization=1.0,
            random_state=seed,
        ),
    ))
    candidates.append((
        "random-forest",
        "RandomForest",
        RandomForestRegressor(
            n_estimators=220,
            min_samples_leaf=3,
            max_features=0.6,
            n_jobs=-1,
            random_state=seed,
        ),
    ))
    candidates.append((
        "extra-trees",
        "ExtraTrees",
        ExtraTreesRegressor(
            n_estimators=260,
            min_samples_leaf=3,
            max_features=0.7,
            n_jobs=-1,
            random_state=seed,
        ),
    ))
    return candidates


def _train_sklearn_harness(Xe: np.ndarray, y: np.ndarray, seed: int) -> List[TrainedCandidate]:
    results: List[TrainedCandidate] = []
    for name, pretty, estimator in _sklearn_candidates(seed):
        started = time.perf_counter()
        maes, rmses = _manual_cv(estimator, Xe, y, seed=seed)
        results.append(
            TrainedCandidate(
                backend="sklearn-harness",
                model_name=f"harness-{name}",
                model_type=pretty,
                estimator=estimator,
                cv_mae_folds=maes,
                cv_rmse_folds=rmses,
                train_seconds=round(time.perf_counter() - started, 2),
            )
        )
    return results


_FLAML_ESTIMATOR_MAP = {
    "lgbm": ("lightgbm", "LGBMRegressor"),
    "xgboost": ("xgboost", "XGBRegressor"),
    "rf": ("sklearn.ensemble", "RandomForestRegressor"),
    "extra_tree": ("sklearn.ensemble", "ExtraTreesRegressor"),
}


def _rebuild_flaml_estimator(best_name: str, best_config: Dict[str, Any], seed: int) -> Optional[Tuple[str, Any]]:
    mapping = _FLAML_ESTIMATOR_MAP.get(best_name)
    if mapping is None:
        return None
    module_name, class_name = mapping
    module_ref = __import__(module_name, fromlist=[class_name])
    cls = getattr(module_ref, class_name)
    config = dict(best_config or {})
    if best_name in ("rf", "extra_tree"):
        max_leaves = config.pop("max_leaves", None)
        if max_leaves not in (None, -1):
            config["max_leaf_nodes"] = int(max_leaves)
    valid_params = set(inspect.signature(cls.__init__).parameters)
    kwargs = {key: value for key, value in config.items() if key in valid_params}
    kwargs["random_state"] = seed
    if best_name == "lgbm":
        kwargs.update(n_jobs=-1, verbose=-1)
    elif best_name in ("rf", "extra_tree"):
        kwargs["n_jobs"] = -1
    elif best_name == "xgboost":
        kwargs.setdefault("tree_method", "hist")
        kwargs.setdefault("n_jobs", -1)
    return f"{class_name} (FLAML-tuned)", cls(**kwargs)


def _train_flaml(
    Xe: np.ndarray,
    y: np.ndarray,
    budget_seconds: int,
    seed: int,
) -> Optional[TrainedCandidate]:
    try:
        from flaml import AutoML
    except ImportError:
        return None

    available: List[str] = []
    for flaml_name, (module_name, _) in _FLAML_ESTIMATOR_MAP.items():
        try:
            __import__(module_name)
            available.append(flaml_name)
        except ImportError:
            continue
    if not available:
        return None

    automl = AutoML()
    started = time.perf_counter()
    automl.fit(
        X=Xe,
        y=y,
        task="regression",
        metric="mae",
        eval_method="cv",
        n_splits=CV_FOLDS,
        time_budget=budget_seconds,
        estimator_list=available,
        verbose=0,
        seed=seed,
    )
    elapsed = round(time.perf_counter() - started, 2)

    rebuilt = _rebuild_flaml_estimator(automl.best_estimator, automl.best_config, seed)
    if rebuilt is None:
        return None
    pretty_type, plain_estimator = rebuilt
    maes, rmses = _manual_cv(plain_estimator, Xe, y, seed=seed)
    return TrainedCandidate(
        backend="flaml",
        model_name=f"flaml-{automl.best_estimator}",
        model_type=pretty_type,
        estimator=plain_estimator,
        cv_mae_folds=maes,
        cv_rmse_folds=rmses,
        train_seconds=elapsed,
    )


class _H2OMojoPredictor:
    """Pickle-safe wrapper holding only a MOJO path; needs Java at inference."""

    def __init__(self, mojo_path: str, feature_names: List[str]):
        self.mojo_path = mojo_path
        self.feature_names = feature_names

    def predict(self, X: Any) -> np.ndarray:
        import h2o
        from h2o.frame import H2OFrame
        from h2o.model.model_base import ModelBase

        if not h2o.connection():
            h2o.init()
        frame = H2OFrame(pd.DataFrame(np.asarray(X), columns=self.feature_names))
        model = h2o.get_model if False else None
        loaded = h2o.upload_mojo(self.mojo_path)
        preds = loaded.predict(frame).as_data_frame(use_multi_thread=True)
        return preds.iloc[:, 0].to_numpy(dtype=float)

    def fit(self, X: Any, y: Any = None) -> "_H2OMojoPredictor":
        return self


def _h2o_backend_available() -> bool:
    try:
        import h2o
    except ImportError:
        return False
    return shutil.which("java") is not None


def _train_h2o(
    preprocessor: Pipeline,
    X_train_raw: pd.DataFrame,
    y_train: np.ndarray,
    feature_names: List[str],
    max_models: int,
    seed: int,
) -> Optional[TrainedCandidate]:
    if not _h2o_backend_available():
        return None
    try:
        import h2o
        from h2o import H2OFrame
        from h2o.automl import H2OAutoML
    except ImportError:
        return None

    Xe_train = preprocessor.transform(X_train_raw)
    frame_df = pd.DataFrame(Xe_train, columns=feature_names)
    frame_df[TARGET_COLUMN] = y_train
    if not h2o.connection():
        h2o.init(max_mem_size="2G")
    hf = H2OFrame(frame_df)
    aml = H2OAutoML(
        max_models=max_models,
        nfolds=CV_FOLDS,
        sort_metric="MAE",
        seed=seed,
        keep_cross_validation_predictions=True,
    )
    started = time.perf_counter()
    aml.train(x=feature_names, y=TARGET_COLUMN, training_frame=hf)
    elapsed = round(time.perf_counter() - started, 2)
    leader = aml.leader
    summary = leader.cross_validation_metrics_summary().as_data_frame()
    maes = [float(v) for v in summary.loc["mae"].tolist()]
    rmses = [float(v) for v in summary.loc["rmse"].tolist()]

    mojo_dir = Path(tempfile.gettempdir()) / f"drishti_h2o_{seed}"
    mojo_dir.mkdir(exist_ok=True)
    mojo_path = leader.download_mojo(path=str(mojo_dir))
    estimator = _H2OMojoPredictor(mojo_path=str(mojo_path), feature_names=feature_names)
    return TrainedCandidate(
        backend="h2o",
        model_name=f"h2o-{leader.model_id[:48]}",
        model_type=str(leader.algo).upper(),
        estimator=estimator,
        cv_mae_folds=maes,
        cv_rmse_folds=rmses,
        cv_source="internal-nfolds",
        train_seconds=elapsed,
    )


def _autogluon_backend_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("autogluon.tabular") is not None


class _AutoGluonDirPredictor:
    """Pickle-safe wrapper storing the predictor directory path."""

    def __init__(self, predictor_dir: str, feature_names: List[str]):
        self.predictor_dir = predictor_dir
        self.feature_names = feature_names
        self._loaded: Any = None

    def _predictor(self) -> Any:
        if self._loaded is None:
            from autogluon.tabular import TabularPredictor

            self._loaded = TabularPredictor.load(self.predictor_dir)
        return self._loaded

    def predict(self, X: Any) -> np.ndarray:
        df = X if isinstance(X, pd.DataFrame) else pd.DataFrame(np.asarray(X), columns=self.feature_names)
        return self._predictor().predict(df).to_numpy(dtype=float)

    def fit(self, X: Any, y: Any = None) -> "_AutoGluonDirPredictor":
        return self


def _train_autogluon(
    preprocessor: Pipeline,
    X_train_raw: pd.DataFrame,
    y_train: np.ndarray,
    X_val_raw: pd.DataFrame,
    y_val: np.ndarray,
    feature_names: List[str],
    budget_seconds: int,
    out_dir: Path,
    seed: int,
) -> Optional[TrainedCandidate]:
    if not _autogluon_backend_available():
        return None
    try:
        from autogluon.tabular import TabularPredictor
    except ImportError:
        return None

    Xe_train = pd.DataFrame(preprocessor.transform(X_train_raw), columns=feature_names)
    train_df = Xe_train.assign(**{TARGET_COLUMN: y_train})
    ag_dir = out_dir / f"ag_predictor_seed{seed}"
    predictor = TabularPredictor(
        label=TARGET_COLUMN,
        path=str(ag_dir),
        eval_metric="mean_absolute_error",
        problem_type="regression",
    )
    started = time.perf_counter()
    predictor.fit(train_df, num_bag_folds=CV_FOLDS, time_limit=budget_seconds, verbosity=0)
    elapsed = round(time.perf_counter() - started, 2)

    scores = predictor.evaluate_scores(train_df) if hasattr(predictor, "evaluate_scores") else None
    mae_value = None
    rmse_value = None
    if scores:
        mae_value = abs(float(scores.get("mean_absolute_error", scores.get("mae"))))
        rmse_value = float(scores.get("root_mean_squared_error", scores.get("rmse")))
    if mae_value is None:
        perf = predictor.evaluate(train_df, silent=True)
        metrics_row = perf if isinstance(perf, dict) else {}
        mae_value = abs(float(metrics_row.get("mean_absolute_error", 0.0))) or None
    if not mae_value:
        return None
    maes = [mae_value] * CV_FOLDS
    rmses = ([rmse_value] if rmse_value else []) * CV_FOLDS
    estimator = _AutoGluonDirPredictor(str(ag_dir), feature_names)
    return TrainedCandidate(
        backend="autogluon",
        model_name="autogluon-tabular",
        model_type=f"AutoGluon ensemble ({predictor.model_best})",
        estimator=estimator,
        cv_mae_folds=maes,
        cv_rmse_folds=rmses,
        cv_source="internal-bagged",
        train_seconds=elapsed,
    )


def _compute_feature_importance(
    candidate: TrainedCandidate,
    final_pipeline: Pipeline,
    feature_names: List[str],
    Xe_train: np.ndarray,
    y_train: np.ndarray,
    X_val_raw: pd.DataFrame,
    y_val: np.ndarray,
    seed: int,
) -> Tuple[str, Dict[str, float]]:
    base_estimator = getattr(candidate.estimator, "__class__", None)
    if hasattr(base_estimator, "fit") and hasattr(base_estimator, "feature_importances_") if False else False:
        pass
    fitted = None
    est_cls = candidate.estimator.__class__
    if hasattr(est_cls, "feature_importances_"):
        fitted = clone(candidate.estimator)
        fitted.fit(Xe_train, y_train)
        ranked = dict(zip(feature_names, [float(v) for v in fitted.feature_importances_]))
        method = "native-feature_importances_(engineered)"
    else:
        perm = permutation_importance(
            final_pipeline,
            X_val_raw,
            y_val,
            n_repeats=5,
            random_state=seed,
            scoring="neg_mean_absolute_error",
            n_jobs=-1,
        )
        raw_cols = list(X_val_raw.columns)
        ranked = {col: float(score) for col, score in zip(raw_cols, perm.importances_mean)}
        method = "permutation(raw-columns)"
    return method, dict(sorted(ranked.items(), key=lambda kv: kv[1], reverse=True))


def _benchmark_latency(pipeline: Pipeline, X_raw: pd.DataFrame, single_rows: int = 100) -> Dict[str, float]:
    warm = X_raw.iloc[[0]]
    for _ in range(10):
        pipeline.predict(warm)
    timings_ms: List[float] = []
    for i in range(single_rows):
        row = X_raw.iloc[[i % len(X_raw)]]
        started = time.perf_counter()
        pipeline.predict(row)
        timings_ms.append((time.perf_counter() - started) * 1000.0)
    batch_started = time.perf_counter()
    pipeline.predict(X_raw.head(min(10_000, len(X_raw))))
    batch_total_ms = (time.perf_counter() - batch_started) * 1000.0
    batch_rows = min(10_000, len(X_raw))
    return {
        "single_row_ms_mean": round(float(np.mean(timings_ms)), 3),
        "single_row_ms_p95": round(float(np.percentile(timings_ms, 95)), 3),
        "batch_ms_per_row_amortized": round(batch_total_ms / batch_rows, 4),
    }


def run_pipeline(
    n_rows: int = DEFAULT_ROWS,
    seed: int = DEFAULT_SEED,
    flaml_time_budget: int = 180,
    backends: str = "auto",
    out_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    t0 = time.perf_counter()
    resolved_out = Path(out_dir) if out_dir else Path(__file__).resolve().parents[1] / "models" / ARTIFACT_DIRNAME
    resolved_out.mkdir(parents=True, exist_ok=True)

    df = generate_synthetic_recovery_data(n_rows=n_rows, seed=seed)
    y_all = df[TARGET_COLUMN].to_numpy(dtype=float)
    X_all = df.drop(columns=[TARGET_COLUMN])

    missing_summary = {col: int(X_all[col].isna().sum()) for col in NUMERIC_COLUMNS + CATEGORICAL_COLUMNS}

    X_train_raw, X_val_raw, y_train, y_val = train_test_split(
        X_all, y_all, test_size=0.2, random_state=seed
    )

    preprocessor = build_preprocessor()
    Xe_train = preprocessor.fit_transform(X_train_raw)
    Xe_val = preprocessor.transform(X_val_raw)
    names = engineered_feature_names(preprocessor)

    selected: List[str]
    ordered = ["h2o", "autogluon", "flaml", "sklearn"]
    if backends.strip().lower() == "auto":
        selected = ordered
    else:
        requested = [part.strip().lower() for part in backends.split(",") if part.strip()]
        selected = [b for b in ordered if b in requested]

    candidates: List[TrainedCandidate] = []
    skipped: Dict[str, str] = {}
    for backend in selected:
        try:
            if backend == "flaml":
                result = _train_flaml(Xe_train, y_train, flaml_time_budget, seed)
                if result is None:
                    skipped[backend] = "flaml not installed"
                else:
                    candidates.append(result)
            elif backend == "sklearn":
                candidates.extend(_train_sklearn_harness(Xe_train, y_train, seed))
            elif backend == "h2o":
                result = _train_h2o(preprocessor, X_train_raw, y_train, names, max_models=12, seed=seed)
                if result is None:
                    skipped[backend] = "h2o not installed or Java runtime missing"
                else:
                    candidates.append(result)
                    h2o_candidate = result
            elif backend == "autogluon":
                result = _train_autogluon(
                    preprocessor, X_train_raw, y_train, X_val_raw, y_val, names,
                    budget_seconds=flaml_time_budget, out_dir=resolved_out, seed=seed,
                )
                if result is None:
                    skipped[backend] = "autogluon not installed"
                else:
                    candidates.append(result)
        except Exception as exc:
            skipped[backend] = f"{type(exc).__name__}: {exc}"

    if not candidates:
        raise RuntimeError(f"No AutoML backend could train: {skipped}")

    champion = min(candidates, key=lambda c: c.combined_score)
    final_pipeline = Pipeline(
        steps=[("preprocess", build_preprocessor()), ("regressor", clone(champion.estimator))]
    )
    final_pipeline.fit(X_train_raw, y_train)

    val_preds = final_pipeline.predict(X_val_raw)
    holdout = {
        "rows": int(len(y_val)),
        "mae": round(float(mean_absolute_error(y_val, val_preds)), 3),
        "rmse": round(float(math.sqrt(mean_squared_error(y_val, val_preds))), 3),
        "r2": round(float(r2_score(y_val, val_preds)), 4),
    }

    importance_method, importance_ranked = _compute_feature_importance(
        champion, final_pipeline, names, Xe_train, y_train, X_val_raw, y_val, seed
    )

    latency = _benchmark_latency(final_pipeline, X_val_raw)

    pkl_path = resolved_out / "recovery_risk_pipeline.pkl"
    joblib.dump(final_pipeline, pkl_path)

    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": {
            "rows_requested": n_rows,
            "rows_generated": int(len(df)),
            "train_rows": int(len(X_train_raw)),
            "holdout_rows": int(len(X_val_raw)),
            "raw_features": NUMERIC_COLUMNS + CATEGORICAL_COLUMNS,
            "engineered_features": len(names),
            "missing_values_injected": missing_summary,
            "target": TARGET_COLUMN,
            "target_range": [float(df[TARGET_COLUMN].min()), float(df[TARGET_COLUMN].max())],
        },
        "cv_protocol": {"folds": CV_FOLDS, "selection_rule": "cv_mae_mean + cv_rmse_mean (lower is better)"},
        "candidates": [
            {
                "backend": c.backend,
                "model_name": c.model_name,
                "model_type": c.model_type,
                "cv_source": c.cv_source,
                "train_seconds": c.train_seconds,
                "cv_mae_folds": [round(v, 3) for v in c.cv_mae_folds],
                "cv_rmse_folds": [round(v, 3) for v in c.cv_rmse_folds],
                "cv_mae_mean": round(c.cv_mae_mean, 3),
                "cv_rmse_mean": round(c.cv_rmse_mean, 3),
                "combined_score": round(c.combined_score, 3),
            }
            for c in sorted(candidates, key=lambda c: c.combined_score)
        ],
        "champion": {
            "backend": champion.backend,
            "model_name": champion.model_name,
            "model_type": champion.model_type,
        },
        "holdout_metrics": holdout,
        "feature_importance": {
            "method": importance_method,
            "top10": [{"feature": k, "importance": round(v, 5)} for k, v in list(importance_ranked.items())[:10]],
            "full_ranking_count": len(importance_ranked),
        },
        "latency_benchmark": latency,
        "backends_skipped": skipped,
        "wall_clock_seconds": round(time.perf_counter() - t0, 1),
        "artifacts": {
            "pipeline_pkl": str(pkl_path),
            "metrics_json": str(resolved_out / "metrics.json"),
            "feature_importance_json": str(resolved_out / "feature_importance.json"),
        },
        "inference_example": (
            "import joblib, pandas as pd\n"
            f"pipe = joblib.load(r'{pkl_path}')\n"
            "row = pd.DataFrame([{"
            "'attempt_timestamp': '2026-08-22T14:30:00', 'amount': 2499.0, "
            "'merchant_category': 'electronics', 'customer_tenure': 26, "
            "'decline_code': 'network_timeout', 'time_of_day': 14.5, "
            "'device_type': 'android', 'location': 'tier1_metro'}])\n"
            "expected_recovery_pct = pipe.predict(row)[0]"
        ),
    }

    (resolved_out / "metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    importance_payload = {
        "method": importance_method,
        "model": champion.model_type,
        "top10": report["feature_importance"]["top10"],
        "ranking": {k: round(v, 6) for k, v in importance_ranked.items()},
    }
    (resolved_out / "feature_importance.json").write_text(json.dumps(importance_payload, indent=2), encoding="utf-8")
    return report


def print_report(report: Dict[str, Any]) -> None:
    ds = report["dataset"]
    print("=" * 72)
    print("DRISHTI RECOVERY-RISK AUTOML - TRAINING REPORT")
    print("=" * 72)
    print(f"dataset          : {ds['rows_generated']:,} rows ({ds['train_rows']:,} train / {ds['holdout_rows']:,} holdout)")
    print(f"features         : {ds['engineered_features']} engineered from {len(ds['raw_features'])} raw columns")
    print(f"missing injected : " + ", ".join(f"{k}={v}" for k, v in ds["missing_values_injected"].items()))
    print("-" * 72)
    print(f"{'candidate':34s} {'cv MAE':>8s} {'cv RMSE':>9s} {'MAE+RMSE':>10s} {'secs':>7s}")
    for cand in report["candidates"]:
        print(
            f"{cand['model_name'][:34]:34s} {cand['cv_mae_mean']:8.3f} "
            f"{cand['cv_rmse_mean']:9.3f} {cand['combined_score']:10.3f} {cand['train_seconds']:7.1f}"
        )
    champ = report["champion"]
    holdout = report["holdout_metrics"]
    imp = report["feature_importance"]
    lat = report["latency_benchmark"]
    print("-" * 72)
    print(f"CHAMPION         : {champ['model_name']} [{champ['model_type']}] via {champ['backend']}")
    print(f"HOLDOUT MAE      : {holdout['mae']} pts   RMSE: {holdout['rmse']} pts   R2: {holdout['r2']}")
    print(f"LATENCY          : single-row mean {lat['single_row_ms_mean']} ms "
          f"(p95 {lat['single_row_ms_p95']} ms) | batch {lat['batch_ms_per_row_amortized']} ms/row")
    print("TOP-10 FEATURES  :")
    for item in imp["top10"]:
        print(f"   {item['feature']:44s} {item['importance']:.5f}")
    if report["backends_skipped"]:
        print(f"SKIPPED BACKENDS : {report['backends_skipped']}")
    print(f"WALL CLOCK       : {report['wall_clock_seconds']}s")
    print(f"ARTIFACTS        : {report['artifacts']['pipeline_pkl']}")
