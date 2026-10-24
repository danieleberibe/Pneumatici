import cv2
import numpy as np

from .models import DetectionConfig


def triangulate_matches(left, right, calibration: dict, config: DetectionConfig):
    """Mutual unique matching; matrices refer to rectified views, output to original left camera."""
    p1, p2 = np.asarray(calibration["P1"]), np.asarray(calibration["P2"])
    r1 = np.asarray(calibration["R1"])
    tx = float(p2[0, 3] / p2[0, 0])
    if abs(tx) < 1e-9:
        return [], {"geometry": 1}
    costs = np.full((len(left), len(right)), np.inf)
    for i, a in enumerate(left):
        for j, b in enumerate(right):
            disparity = a.x - b.x
            radius_ratio = a.radius / b.radius
            if (
                a.profile == b.profile
                and abs(a.y - b.y) <= config.epipolar_px
                and disparity * -tx > 0
                and abs(disparity) >= 1.5
                and 0.65 < radius_ratio < 1.54
            ):
                costs[i, j] = abs(a.y - b.y) + 3 * abs(np.log(radius_ratio))
    points, rejected = [], {"unmatched": 0, "ambiguous": 0, "geometry": 0}
    for i, a in enumerate(left):
        js = np.flatnonzero(np.isfinite(costs[i]))
        if len(js) == 0:
            rejected["unmatched"] += 1
            continue
        j = int(js[np.argmin(costs[i, js])])
        column = costs[:, j]
        row_sorted, col_sorted = np.sort(costs[i]), np.sort(column)
        ambiguous = (len(row_sorted) > 1 and row_sorted[1] - row_sorted[0] < 0.8) or (
            len(col_sorted) > 1 and col_sorted[1] - col_sorted[0] < 0.8
        )
        if int(np.argmin(column)) != i or ambiguous:
            rejected["ambiguous"] += 1
            continue
        b = right[j]
        homogeneous = cv2.triangulatePoints(p1, p2, a.point.reshape(2, 1), b.point.reshape(2, 1))[:, 0]
        if abs(homogeneous[3]) < 1e-10:
            rejected["geometry"] += 1
            continue
        rectified = homogeneous[:3] / homogeneous[3]
        point = r1.T @ rectified
        reprojection = []
        valid = np.all(np.isfinite(point)) and 0.05 < point[2] < config.max_depth_m
        for projection, observed in [(p1, a.point), (p2, b.point)]:
            uvw = projection @ np.r_[rectified, 1.0]
            if uvw[2] <= 0:
                valid = False
            reprojection.append(float(np.linalg.norm(uvw[:2] / max(uvw[2], 1e-10) - observed)))
        error = max(reprojection)
        if not valid or error > config.max_reprojection_px:
            rejected["geometry"] += 1
            continue
        disparity = abs(a.x - b.x)
        sigma_z = abs(rectified[2]) / disparity * np.sqrt(2) * config.pixel_sigma
        points.append(
            {
                "id": f"P{len(points) + 1:02d}",
                "profile": a.profile,
                "x_m": round(float(point[0]), 5),
                "y_m": round(float(point[1]), 5),
                "z_m": round(float(point[2]), 5),
                "sigma_z_mm": round(float(sigma_z * 1000), 2),
                "epipolar_px": round(abs(a.y - b.y), 3),
                "reprojection_px": round(error, 3),
                "disparity_px": round(disparity, 2),
                "shape_score": round(min(a.shape_score, b.shape_score), 3),
                "left_px": a.point.tolist(),
                "right_px": b.point.tolist(),
            }
        )
    return points, rejected
