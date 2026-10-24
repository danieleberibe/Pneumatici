from xml.etree import ElementTree

import cv2
import numpy as np
import pytest

from stereolab.calibration import Calibration, Sample, board_object, board_svg, solve_calibration
from stereolab.models import BoardConfig


def synthetic_samples(noise=0.05, corrupt_holdout=False):
    rng = np.random.default_rng(4)
    board = board_object(BoardConfig())
    obj = board.getChessboardCorners()
    k = np.array([[900.0, 0, 640], [0, 900.0, 360], [0, 0, 1.0]])
    r = cv2.Rodrigues(np.array([0.004, 0.015, -0.003]))[0]
    t = np.array([-0.16, 0.002, 0.001])
    samples = []
    for i in range(30):
        rv = rng.uniform(-0.5, 0.5, 3)
        tv = np.array([[-0.25, 0.0, 0.17][i % 3], [-0.13, 0.02, 0.12][(i // 3) % 3], rng.uniform(0.65, 1.2)])
        a = cv2.projectPoints(obj, rv, tv, k, None)[0]
        right_rv = cv2.Rodrigues(r @ cv2.Rodrigues(rv)[0])[0]
        b = cv2.projectPoints(obj, right_rv, r @ tv + t, k, None)[0]
        a += rng.normal(0, noise, a.shape).astype(np.float32)
        b += rng.normal(0, noise, b.shape).astype(np.float32)
        if corrupt_holdout and i % 5 == 4:
            b[:, :, 1] += 8
        samples.append(Sample(obj.copy(), a, b, np.arange(len(obj)), (1280, 720)))
    return samples


def test_calibration_recovers_known_rig_and_holds_out_images():
    profile = solve_calibration(synthetic_samples(), BoardConfig(), "test-rig")
    assert profile["accepted"], profile["warnings"]
    assert profile["baseline_mm"] == pytest.approx(160, abs=2)
    assert profile["epipolar_rms"] < 0.3
    assert profile["training_samples"] == 24
    assert profile["validation_samples"] == 6
    assert np.array(profile["K1"])[0, 0] == pytest.approx(900, abs=20)


def test_holdout_detects_bad_geometry_even_when_training_fit_is_good():
    profile = solve_calibration(synthetic_samples(corrupt_holdout=True), BoardConfig(), "rig")
    assert profile["rms_stereo"] < 0.2
    assert not profile["accepted"]
    assert profile["epipolar_rms"] > 5


def test_metric_scale_is_derived_from_board_in_metres():
    samples = synthetic_samples(noise=0)
    for sample in samples:
        sample.object_points *= 2
    profile = solve_calibration(samples, BoardConfig(square_mm=50, marker_mm=36), "rig")
    assert profile["baseline_mm"] == pytest.approx(320, abs=1)


def test_real_charuco_detection_and_duplicate_rejection(tmp_path):
    calibration = Calibration(tmp_path)
    config = BoardConfig()
    board = board_object(config).generateImage((700, 500), marginSize=0)
    gray = np.full((720, 1280), 180, np.uint8)
    gray[100:600, 220:920] = board
    left = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    right = cv2.warpAffine(
        left, np.float32([[1, 0, -80], [0, 1, 0]]), (1280, 720), borderValue=(180, 180, 180)
    )
    result = calibration.capture(left, right, "rig")
    assert result["common_corners"] >= 12
    with pytest.raises(ValueError, match="simile"):
        calibration.capture(left, right, "rig")
    with pytest.raises(ValueError, match="cambiate"):
        calibration.capture(left, right, "other-rig")


def test_calibration_minimum_and_invalid_profile(tmp_path):
    with pytest.raises(ValueError, match="15"):
        solve_calibration([], BoardConfig(), "rig")
    (tmp_path / "calibration.json").write_text('{"schema": 99}')
    calibration = Calibration(tmp_path)
    assert calibration.profile is None
    assert calibration.load_error


def test_printable_board_has_metric_dimensions():
    svg = board_svg(BoardConfig())
    element = ElementTree.fromstring(svg)
    assert float(element.attrib["width"].removesuffix("mm")) == 195
    assert float(element.attrib["height"].removesuffix("mm")) == 155
    assert "50 mm" in svg
