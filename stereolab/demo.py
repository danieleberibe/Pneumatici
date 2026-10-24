import cv2
import numpy as np


def demo_scene():
    width, height, focal, baseline = 960, 540, 800.0, 0.16
    k = np.array([[focal, 0, width / 2], [0, focal, height / 2], [0, 0, 1.0]])
    p1 = np.column_stack((k, np.zeros(3)))
    p2 = p1.copy()
    p2[0, 3] = -focal * baseline
    profile = {"P1": p1.tolist(), "P2": p2.tolist(), "R1": np.eye(3).tolist()}
    objects = [
        (np.array([-0.23, -0.08, 1.35]), (30, 140, 240)),
        (np.array([0.19, 0.12, 1.85]), (215, 137, 45)),
        (np.array([0.00, -0.23, 2.5]), (235, 235, 235)),
        (np.array([0.36, -0.13, 2.0]), (23, 24, 25)),
    ]
    images = []
    for projection in [p1, p2]:
        image = np.full((height, width, 3), (79, 72, 64), dtype=np.uint8)
        for x in range(0, width, 60):
            cv2.line(image, (x, 0), (x, height), (86, 79, 71), 1)
        for y in range(0, height, 60):
            cv2.line(image, (0, y), (width, y), (86, 79, 71), 1)
        for xyz, color in objects:
            uvw = projection @ np.r_[xyz, 1.0]
            u, v = np.round(uvw[:2] / uvw[2]).astype(int)
            radius = round(focal * 0.045 / xyz[2])
            cv2.circle(image, (u, v), radius, color, -1, cv2.LINE_AA)
            cv2.circle(
                image,
                (u - radius // 4, v - radius // 4),
                max(2, radius // 5),
                tuple(min(c + 22, 255) for c in color),
                -1,
                cv2.LINE_AA,
            )
        images.append(image)
    return images, profile
