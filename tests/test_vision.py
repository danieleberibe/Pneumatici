import cv2
import numpy as np
import pytest

from stereolab.demo import demo_scene
from stereolab.detection import Ball, detect_balls
from stereolab.geometry import triangulate_matches
from stereolab.models import DetectionConfig


def ball(x, y, profile="orange", radius=20):
    return Ball(profile, x, y, radius, 0.95, 0.92)


def test_demo_images_detect_achromatic_and_colored_balls_and_recover_depth():
    images, profile = demo_scene()
    config = DetectionConfig()
    detections = [detect_balls(image, config) for image in images]
    assert {b.profile for b in detections[0]} == {"white", "black", "orange", "blue"}
    points, rejected = triangulate_matches(*detections, profile, config)
    expected = {"orange": 1.35, "blue": 1.85, "white": 2.5, "black": 2.0}
    assert len(points) == 4
    for point in points:
        assert abs(point["z_m"] - expected[point["profile"]]) < 0.012
        assert point["sigma_z_mm"] > 0
    assert sum(rejected.values()) == 0


def test_false_shapes_cropped_spheres_and_rings_are_rejected():
    image = np.full((480, 640, 3), 110, np.uint8)
    cv2.rectangle(image, (50, 50), (140, 140), (255, 255, 255), -1)
    cv2.circle(image, (260, 100), 35, (255, 255, 255), 8)
    cv2.circle(image, (5, 250), 40, (0, 0, 0), -1)
    cv2.ellipse(image, (380, 250), (65, 25), 0, 0, 360, (0, 0, 0), -1)
    assert detect_balls(image, DetectionConfig()) == []


def test_identical_balls_with_ambiguous_correspondence_are_not_measured():
    _, profile = demo_scene()
    points, rejected = triangulate_matches(
        [ball(500, 250), ball(600, 250)], [ball(400, 250), ball(450, 250)], profile, DetectionConfig()
    )
    assert points == []
    assert rejected["ambiguous"] == 2


@pytest.mark.parametrize(
    "right", [ball(400, 260), ball(510, 250), ball(400, 250, "blue"), ball(400, 250, radius=60)]
)
def test_wrong_epipolar_disparity_color_and_scale_are_rejected(right):
    _, profile = demo_scene()
    points, _ = triangulate_matches([ball(500, 250)], [right], profile, DetectionConfig())
    assert not points


def test_coordinates_are_rotated_back_to_original_left_camera():
    _, profile = demo_scene()
    rotation = cv2.Rodrigues(np.array([0.0, 0.12, 0.0]))[0]
    profile["R1"] = rotation.tolist()
    point_rectified = np.array([0.2, -0.1, 2.0])
    a = np.array(profile["P1"]) @ np.r_[point_rectified, 1]
    b = np.array(profile["P2"]) @ np.r_[point_rectified, 1]
    points, _ = triangulate_matches(
        [ball(*(a[:2] / a[2]))], [ball(*(b[:2] / b[2]))], profile, DetectionConfig()
    )
    assert len(points) == 1
    np.testing.assert_allclose(
        [points[0][k] for k in ("x_m", "y_m", "z_m")], rotation.T @ point_rectified, atol=1e-5
    )


def test_uncertainty_grows_quadratically_with_distance():
    _, profile = demo_scene()
    sigmas = []
    for z in (1.0, 2.0):
        points, _ = triangulate_matches(
            [ball(480, 270)], [ball(480 - 128 / z, 270)], profile, DetectionConfig()
        )
        sigmas.append(points[0]["sigma_z_mm"])
    assert sigmas[1] / sigmas[0] == pytest.approx(4, abs=0.01)
