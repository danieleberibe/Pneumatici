"""Evaluate independently measured positions in the LEFT optical coordinate frame, in metres.

CSV columns: point_id,x_true_m,y_true_m,z_true_m,x_m,y_m,z_m
Repeat each point_id over independent captures. Do not duplicate a frame to simulate repeatability.
"""

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np


def evaluate(path):
    groups = defaultdict(list)
    errors = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("simulated", "false").lower() not in ("false", "0", ""):
                raise ValueError("Non usare misure sintetiche per validare l'accuratezza reale.")
            actual = np.array([float(row[f"{axis}_m"]) for axis in "xyz"])
            reference = np.array([float(row[f"{axis}_true_m"]) for axis in "xyz"])
            if not np.isfinite(np.r_[actual, reference]).all():
                raise ValueError("Coordinate non finite.")
            errors.append(actual - reference)
            groups[row["point_id"]].append(actual)
    if not errors:
        raise ValueError("Nessuna misura nel CSV.")
    error_mm = np.array(errors) * 1000
    norm = np.linalg.norm(error_mm, axis=1)
    return {
        "readings": len(errors),
        "physical_positions": len(groups),
        "mean_error_mm": float(norm.mean()),
        "rmse_3d_mm": float(np.sqrt(np.mean(norm**2))),
        "p95_error_mm": float(np.percentile(norm, 95)),
        "max_error_mm": float(norm.max()),
        "bias_xyz_mm": error_mm.mean(axis=0).tolist(),
        "repeatability_std_xyz_mm": {
            key: (np.std(np.array(points) * 1000, axis=0, ddof=1).tolist() if len(points) > 1 else None)
            for key, points in groups.items()
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.csv), indent=2, allow_nan=False))
