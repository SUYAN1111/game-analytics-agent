"""Fresh-process, prediction-only worker. Requests contain no label path/value."""

import argparse
import os
from pathlib import Path
import joblib
from threadpoolctl import threadpool_limits

from modeling.m03_data import align
from modeling.m03_io import (IDS, ModelError, digest, probabilities, read, rows, require, sha,
                            write_json, write_rows, now)


class Predictor:
    def __init__(self, directory, asset_hashes):
        self.directory = Path(directory)
        require(set(asset_hashes) == set(IDS), "asset_candidates", "必须七项资产")
        self.hashes, self.models = dict(asset_hashes), {}
        for candidate in IDS:
            path = self.directory / (candidate+".joblib")
            require(sha(path) == self.hashes[candidate], "asset_hash", candidate)
            model = joblib.load(path)  # Only this project's explicitly hashed local assets.
            require(model.candidate_id == candidate, "asset_candidate_id", candidate)
            model.check()
            self.models[candidate] = model

    def predict(self, x, candidate_id):
        require(candidate_id in self.models, "candidate_id", candidate_id)
        require(sha(self.directory/(candidate_id+".joblib")) == self.hashes[candidate_id], "asset_hash", candidate_id)
        model = self.models[candidate_id]
        # FrozenCandidate has a deliberately rejecting fit method; estimator positive column is mapped internally.
        with threadpool_limits(limits=1):
            return probabilities(model.predict_proba(x)[:, 1])










if __name__ == "__main__":
    main()
