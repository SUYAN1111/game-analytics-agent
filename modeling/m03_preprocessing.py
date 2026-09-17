"""Explicit train-only median/scaler/one-hot layout; four fixed indicators."""

import numpy as np
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from modeling.m03_data import x_rows
from modeling.m03_io import NUMERIC, CATEGORIES, MISSING, require


class Preprocessor:
    def __init__(self, scaled):
        self.scaled = scaled
        self.fitted = False

    def fit(self, *args, **kwargs):
        raise ValueError("product frozen preprocessor: fitting disabled")

    @staticmethod
    def numeric(x):
        return np.array([[np.nan if r[k] is None else r[k] for k in NUMERIC] for r in x], dtype=np.float64)

    def transform(self, x):
        require(self.fitted, "not_fitted", "预处理")
        x = x_rows(x)
        if not x:
            return np.empty((0, len(self.columns)), dtype=np.float64)
        numeric = self.numeric(x)
        filled = np.where(np.isnan(numeric), self.medians, numeric)
        values = self.scaler.transform(filled) if self.scaled else filled
        indicators = np.array([[int(r[k] is None) for k in MISSING] for r in x], dtype=np.float64)
        encoded = self.encoder.transform([[r[k] for k in CATEGORIES] for r in x])
        output = np.column_stack((values, indicators, encoded))
        require(np.isfinite(output).all(), "transform_nonfinite", "变换结果")
        return output

    def parameters(self):
        require(self.fitted, "not_fitted", "预处理")
        return {"numeric": list(NUMERIC), "scaled": self.scaled, "medians": self.medians.tolist(),
                "mean": self.scaler.mean_.tolist(), "variance_ddof0": self.scaler.var_.tolist(),
                "scale": self.scaler.scale_.tolist(), "all_missing_in_train": [
                    k for k, v in zip(NUMERIC, self.all_missing) if v],
                "missing_indicators": list(MISSING), "categories": {
                    k: v.tolist() for k, v in zip(CATEGORIES, self.encoder.categories_)},
                "columns": self.columns, "n_features": len(self.columns),
                "fit_rows": int(self.scaler.n_samples_seen_),
                "scaler_options": {"with_mean": self.scaler.with_mean, "with_std": self.scaler.with_std},
                "encoder_options": {"handle_unknown": self.encoder.handle_unknown, "drop": self.encoder.drop,
                                    "sparse_output": self.encoder.sparse_output, "dtype": str(self.encoder.dtype)},
                "constant_45": "当前没有区分能力"}
