"""Seven actual fits. No validation/test data accepted by fit_candidates."""

import time
import warnings
import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from threadpoolctl import threadpool_limits, threadpool_info

from modeling.m03_data import x_rows
from modeling.m03_io import IDS, ModelError, digest, probabilities, require
from modeling.m03_preprocessing import Preprocessor


def positive_probability(estimator, matrix):
    classes = list(estimator.classes_)
    require(classes.count(1) == 1 and set(classes) == {0, 1}, "positive_class", str(classes))
    return probabilities(estimator.predict_proba(matrix)[:, classes.index(1)])


class FrozenCandidate:
    def __init__(self, candidate_id, preprocessor, estimator, n, n1):
        self.candidate_id, self.preprocessor, self.estimator = candidate_id, preprocessor, estimator
        self.n, self.n1 = n, n1
        self.classes_ = np.array([0, 1]) if estimator is None else estimator.classes_.copy()
        self.state_sha256 = digest(self.parameters())

    def fit(self, *args, **kwargs):
        raise ModelError("refit_forbidden: 冻结对象只支持预测")

    def parameters(self):
        value = {"candidate_id": self.candidate_id, "n": self.n, "n1": self.n1,
                 "classes": self.classes_.tolist(), "prior": self.n1/self.n,
                 "preprocessing": None if self.preprocessor is None else self.preprocessor.parameters()}
        if self.estimator is not None:
            value["algorithm"] = self.estimator.get_params(deep=False)
            value["estimator_classes"] = self.estimator.classes_.tolist()
            if hasattr(self.estimator, "coef_"):
                value.update(coef=self.estimator.coef_.tolist(), intercept=self.estimator.intercept_.tolist(),
                             n_iter=self.estimator.n_iter_.tolist())
            else:
                t = self.estimator.tree_
                value["tree"] = {k: getattr(t, k).tolist() for k in (
                    "children_left", "children_right", "feature", "threshold", "value", "n_node_samples")}
                value["depth"] = int(self.estimator.get_depth())
                value["leaves"] = int(self.estimator.get_n_leaves())
                value["leaf_training_counts"] = t.n_node_samples[t.children_left == -1].tolist()
        return value

    def check(self):
        require(digest(self.parameters()) == self.state_sha256, "model_state_changed", self.candidate_id)

    def predict_proba(self, x):
        self.check()
        x = x_rows(x)
        if self.estimator is None:
            p = probabilities([self.n1/self.n] * len(x))
        elif not x:
            p = []
        else:
            with threadpool_limits(limits=1):
                p = positive_probability(self.estimator, self.preprocessor.transform(x))
        self.check()
        return np.array([[1-v, v] for v in p], dtype=np.float64).reshape((-1, 2))




