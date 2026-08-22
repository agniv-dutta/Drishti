"""Concept-drift monitoring via Population Stability Index (PSI).

Feed rolling batches of feature vectors from live scoring traffic; when PSI
for a feature crosses the threshold the supervisor raises a DRIFT_ALERT audit
event so models can be retrained.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Dict, List, Optional

EPS = 1e-6


def population_stability_index(expected: List[float], actual: List[float], bins: int = 10) -> float:
    """PSI between two numeric samples; <0.1 stable, 0.1-0.25 watch, >0.25 drift."""
    if not expected or not actual:
        return 0.0
    edges = _quantile_edges(expected, bins)
    if len(edges) < 2:
        return 0.0

    expected_counts = _bin_counts(expected, edges)
    actual_counts = _bin_counts(actual, edges)

    psi = 0.0
    n_expected, n_actual = len(expected), len(actual)
    for exp_count, act_count in zip(expected_counts, actual_counts):
        e_ratio = max(exp_count / n_expected, EPS)
        a_ratio = max(act_count / n_actual, EPS)
        psi += (a_ratio - e_ratio) * math.log(a_ratio / e_ratio)
    return round(psi, 4)


def _quantile_edges(values: List[float], bins: int) -> List[float]:
    ordered = sorted(values)
    edges: List[float] = []
    for i in range(1, bins):
        position = int(len(ordered) * i / bins)
        position = min(max(position, 0), len(ordered) - 1)
        edge = ordered[position]
        if not edges or edge > edges[-1]:
            edges.append(edge)
    return [ordered[0]] + edges + [ordered[-1] + EPS]


def _bin_counts(values: List[float], edges: List[float]) -> List[int]:
    counts = [0] * (len(edges) - 1)
    for value in values:
        for i in range(len(edges) - 1):
            if edges[i] <= value <= edges[i + 1]:
                counts[i] += 1
                break
        else:
            counts[-1] += 1
    return counts


class DriftDetector:
    """Holds reference distributions per feature and scores new batches."""

    def __init__(self, threshold: float = 0.2, min_samples: int = 30):
        self.threshold = threshold
        self.min_samples = min_samples
        self._reference: Dict[str, List[float]] = {}
        self.last_checked_at: Optional[datetime] = None

    def update_reference(self, feature_values: Dict[str, List[float]]) -> None:
        for name, values in feature_values.items():
            bucket = self._reference.setdefault(name, [])
            bucket.extend(values)
            # keep reference bounded
            self._reference[name] = bucket[-5000:]

    def has_reference(self) -> bool:
        return bool(self._reference) and all(
            len(v) >= self.min_samples for v in self._reference.values()
        )

    def check(self, batch: Dict[str, List[float]]) -> Dict[str, object]:
        """Return {feature: psi} plus an aggregate drifted verdict."""
        report: Dict[str, float] = {
            name: population_stability_index(ref, batch.get(name, []))
            for name, ref in self._reference.items()
            if name in batch
        }
        drifted = any(psi >= self.threshold for psi in report.values())
        self.last_checked_at = datetime.utcnow()
        return {
            "checked_at": self.last_checked_at.isoformat(),
            "threshold": self.threshold,
            "per_feature_psi": report,
            "drifted": drifted,
            "drifted_features": [f for f, psi in report.items() if psi >= self.threshold],
        }
