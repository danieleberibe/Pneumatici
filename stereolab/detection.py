from dataclasses import dataclass

import cv2
import numpy as np

from .models import DetectionConfig

COLORS = {
    "orange": (40, 154, 255),
    "green": (120, 220, 90),
    "blue": (255, 160, 65),
    "red": (80, 70, 245),
    "white": (240, 240, 240),
    "black": (160, 160, 160),
}


@dataclass
class Ball:
    profile: str
    x: float
    y: float
    radius: float
    circularity: float
    shape_score: float

    @property
    def point(self):
        return np.array([self.x, self.y], dtype=np.float64)


def detect_balls(image: np.ndarray, config: DetectionConfig) -> list[Ball]:
    """HSV masks + closed, convex, near-circular silhouettes. No semantic guarantee."""
    hsv = cv2.cvtColor(cv2.GaussianBlur(image, (5, 5), 0), cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    masks = {
        "orange": ((h >= 5) & (h <= 25) & (s >= 100) & (v >= 70)),
        "green": ((h >= 35) & (h <= 88) & (s >= 65) & (v >= 55)),
        "blue": ((h >= 90) & (h <= 130) & (s >= 80) & (v >= 55)),
        "red": (((h <= 4) | (h >= 170)) & (s >= 100) & (v >= 70)),
        "white": ((s <= 55) & (v >= config.white_min)),
        "black": (v <= config.black_max),
    }
    kernel = np.ones((3, 3), np.uint8)
    balls = []
    height, width = image.shape[:2]
    for profile in config.profiles:
        mask = masks[profile].astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        for contour in contours:
            if len(contour) < 12:
                continue
            area = cv2.contourArea(contour)
            perimeter = cv2.arcLength(contour, True)
            if perimeter == 0 or area < np.pi * config.min_radius**2:
                continue
            circularity = 4 * np.pi * area / perimeter**2
            (x, y), (a, b), angle = cv2.fitEllipse(contour)
            radius = (a + b) / 4
            if not config.min_radius <= radius <= config.max_radius:
                continue
            if circularity < config.circularity or min(a, b) / max(a, b) < 0.78:
                continue
            if x - radius < 3 or y - radius < 3 or x + radius >= width - 3 or y + radius >= height - 3:
                continue  # A cropped silhouette has a biased center.
            solidity = area / max(cv2.contourArea(cv2.convexHull(contour)), 1)
            radial = np.linalg.norm(contour[:, 0, :] - [x, y], axis=1)
            residual = float(np.std(radial) / max(radius, 1))
            if solidity < 0.93 or residual > 0.12:
                continue
            # A square can exceed 0.78 circularity: test the fitted ellipse boundary too.
            theta = np.deg2rad(angle)
            rotation = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
            local = (contour[:, 0, :] - [x, y]) @ rotation
            ellipse_radii = np.linalg.norm(local / [a / 2, b / 2], axis=1)
            if np.sqrt(np.mean((ellipse_radii - 1) ** 2)) > 0.06:
                continue
            # Suppress hollow rings and colored highlights inside another ball.
            if mask[int(y), int(x)] == 0:
                continue
            score = min(1.0, circularity * solidity * (1 - residual))
            balls.append(Ball(profile, float(x), float(y), float(radius), float(circularity), score))
    balls.sort(key=lambda ball: ball.radius, reverse=True)
    distinct = []
    for ball in balls:
        if all(
            np.linalg.norm(ball.point - other.point) > max(ball.radius, other.radius) for other in distinct
        ):
            distinct.append(ball)
    return distinct[:40]


def annotate(image, balls):
    result = image.copy()
    for ball in balls:
        center = (round(ball.x), round(ball.y))
        color = COLORS[ball.profile]
        cv2.circle(result, center, round(ball.radius), color, 2, cv2.LINE_AA)
        cv2.drawMarker(result, center, color, cv2.MARKER_CROSS, 12, 1)
        cv2.putText(
            result,
            ball.profile.upper(),
            (center[0] + 8, center[1] - round(ball.radius) - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            color,
            1,
            cv2.LINE_AA,
        )
    return result
