"""The AADTBench reference calibrator and the raw-track scale factor.

Calibrated track model, fitted by ordinary least squares on training sites:

    log(1 + count) = a + b * log(1 + flow) + road class effects + error

Predictions are back-transformed with Duan's smearing factor:

    count_hat = smear * exp(fitted) - 1, floored at 0

``smear`` is the mean of the exponentiated training residuals.

Notes on choices that the spec leaves open:

* The response is ``log(1 + count)`` rather than ``log(count)`` so that a count
  of zero is allowed. The metrics use ``log1p`` too.
* Road classes with fewer than ``MIN_CLASS_SITES`` training sites are merged
  into ``other``. If ``other`` still has fewer than ``MIN_CLASS_SITES``
  sites, it joins the reference class (the most common class). A class not
  seen in training gets the ``other`` effect, or the reference effect (zero)
  if there is no ``other`` group.
* With ``covariate=False`` the flow term is dropped (``class_only``).

Raw track: one scale factor, the geometric mean of observed over predicted
flow on the training sites. Zero rules:

* Training sites with predicted flow 0 or observed value 0 are left out of the
  geometric mean (a ratio is undefined or zero).
* Sites with predicted flow 0 are predicted as 0 after scaling. The tool
  said "no flow" and the raw track takes it at its word.
* If no training site has both values positive, the factor is 1.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

MIN_CLASS_SITES = 5
OTHER = "other"


def _design(logflow: np.ndarray | None, classes: np.ndarray, levels: list[str]) -> np.ndarray:
    cols = [np.ones(len(classes))]
    if logflow is not None:
        cols.append(logflow)
    for lev in levels:
        cols.append((classes == lev).astype(float))
    return np.column_stack(cols)


@dataclass
class Calibrator:
    """A fitted reference calibrator."""

    intercept: float
    slope: float | None
    class_effects: dict[str, float]
    smearing: float
    covariate: bool
    merged_classes: list[str] = field(default_factory=list)
    n_train: int = 0

    def _map_classes(self, road_class) -> np.ndarray:
        rc = np.asarray(road_class, dtype=object).astype(str)
        known = set(self.class_effects) | {self.reference}
        return np.array([c if c in known else OTHER for c in rc], dtype=object)

    @property
    def reference(self) -> str:
        return self._reference

    _reference: str = ""

    def predict(self, flow, road_class) -> np.ndarray:
        """Predicted count on the natural scale."""
        classes = self._map_classes(road_class)
        eta = np.full(len(classes), self.intercept, dtype=float)
        if self.covariate:
            eta = eta + self.slope * np.log1p(np.maximum(np.asarray(flow, dtype=float), 0.0))
        eff = np.array([self.class_effects.get(c, 0.0) for c in classes])
        return np.maximum(self.smearing * np.exp(eta + eff) - 1.0, 0.0)

    def coefficients(self) -> dict:
        """Coefficients for the run record."""
        return {
            "intercept": self.intercept,
            "slope": self.slope,
            "class_effects": dict(self.class_effects),
            "reference_class": self._reference,
            "smearing": self.smearing,
            "covariate": self.covariate,
            "merged_classes": list(self.merged_classes),
            "n_train": self.n_train,
        }


def fit_calibrator(flow, road_class, count, covariate: bool = True,
                   min_class_sites: int = MIN_CLASS_SITES) -> Calibrator:
    """Fit the reference calibrator by OLS with numpy ``lstsq``."""
    flow = np.asarray(flow, dtype=float)
    count = np.asarray(count, dtype=float)
    rc = np.asarray(road_class, dtype=object).astype(str)
    ok = np.isfinite(flow) & np.isfinite(count) & (count >= 0)
    flow, count, rc = flow[ok], count[ok], rc[ok]
    if len(count) == 0:
        raise ValueError("no training sites")
    levels, n = np.unique(rc, return_counts=True)
    small = [str(lv) for lv, k in zip(levels, n) if k < min_class_sites]
    rc = np.array([OTHER if c in small else c for c in rc], dtype=object)
    # The reference class is the most common one. Its effect is zero.
    levels, n = np.unique(rc, return_counts=True)
    ref = str(levels[np.argmax(n)])
    # If the merged ``other`` group is still small, it joins the reference
    # class, so a handful of sites never get a free effect of their own.
    if OTHER in levels and n[list(levels).index(OTHER)] < min_class_sites and ref != OTHER:
        rc = np.array([ref if c == OTHER else c for c in rc], dtype=object)
        levels, n = np.unique(rc, return_counts=True)
    others = [str(lv) for lv in levels if lv != ref]
    y = np.log1p(count)
    lf = np.log1p(np.maximum(flow, 0.0)) if covariate else None
    X = _design(lf, rc, others)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    smear = float(np.mean(np.exp(resid)))
    k = 1
    slope = None
    if covariate:
        slope = float(beta[1])
        k = 2
    effects = {lev: float(b) for lev, b in zip(others, beta[k:])}
    effects[ref] = 0.0
    cal = Calibrator(intercept=float(beta[0]), slope=slope, class_effects=effects,
                     smearing=smear, covariate=covariate, merged_classes=sorted(small),
                     n_train=int(len(count)))
    cal._reference = ref
    return cal


@dataclass
class ScaleFactor:
    """The raw-track scale factor."""

    factor: float
    n_used: int = 0

    def predict(self, flow) -> np.ndarray:
        return self.factor * np.maximum(np.asarray(flow, dtype=float), 0.0)

    def coefficients(self) -> dict:
        return {"scale_factor": self.factor, "n_used": self.n_used}


def fit_scale_factor(flow, count) -> ScaleFactor:
    """Geometric mean ratio of observed to predicted flow on training sites."""
    flow = np.asarray(flow, dtype=float)
    count = np.asarray(count, dtype=float)
    ok = np.isfinite(flow) & np.isfinite(count) & (flow > 0) & (count > 0)
    if not ok.any():
        return ScaleFactor(1.0, 0)
    return ScaleFactor(float(np.exp(np.mean(np.log(count[ok] / flow[ok])))), int(ok.sum()))
