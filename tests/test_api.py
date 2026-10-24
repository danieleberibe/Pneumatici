from urllib.parse import parse_qs, urlsplit

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from stereolab.app import create_app
from stereolab.demo import demo_scene
from stereolab.models import RigConfig, SourceConfig


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path)


def token(client, side="left"):
    link = client.get("/api/pairing").json()[side]
    return parse_qs(urlsplit(link).fragment)["token"][0]


def test_default_has_no_fabricated_measurements_and_demo_is_explicit(app):
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/phone").status_code == 200
        data = client.get("/api/state").json()
        assert data["mode"] == "live" and data["result"]["points"] == []
        assert client.get("/api/export.csv").status_code == 409
        assert client.post("/api/demo", json={"enabled": True}).status_code == 200
        app.state.engine.tick()
        data = client.get("/api/state").json()
        assert data["mode"] == "demo" and data["result"]["simulated"]
        assert len(data["result"]["points"]) == 4
        csv = client.get("/api/export.csv")
        assert csv.status_code == 200
        assert "simulated" in csv.text and "True" in csv.text
        client.post("/api/pause", json={"enabled": True})
        assert client.get("/api/export.csv").status_code == 409
        client.post("/api/demo", json={"enabled": False})
        assert client.get("/api/state").json()["result"]["points"] == []


def test_phone_upload_auth_validation_and_token_rotation(app):
    with TestClient(app) as client:
        image = np.full((480, 640, 3), 128, np.uint8)
        jpeg = cv2.imencode(".jpg", image)[1].tobytes()
        headers = {"Content-Type": "image/jpeg", "X-Pair-Token": token(client)}
        assert client.post("/api/frames/left", content=jpeg).status_code == 401
        assert client.post("/api/frames/left", headers=headers, content=jpeg).status_code == 200
        assert client.get("/api/state").json()["cameras"]["left"]["size"] == [640, 480]
        assert client.post("/api/frames/left", headers=headers, content=b"bad").status_code == 422
        assert client.post("/api/frames/left", headers=headers, content=b"x" * 2_000_001).status_code == 413
        assert client.put("/api/rig", json=RigConfig().model_dump()).status_code == 200
        assert client.post("/api/frames/left", headers=headers, content=jpeg).status_code == 401


def test_origin_rejection_and_config_validation(app):
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/demo", headers={"Origin": "https://evil.example"}, json={"enabled": True}
            ).status_code
            == 403
        )
        assert client.put("/api/detection", json={"min_radius": 50, "max_radius": 20}).status_code == 422
        assert (
            client.put("/api/rig", json={"left": {"kind": "ip", "address": "file:///etc/passwd"}}).status_code
            == 422
        )
        assert client.get("/api/calibration/export").status_code == 404
        assert client.post("/api/calibration/solve").status_code == 422


@pytest.mark.parametrize(
    "width,height", [(1280, 720), (720, 1280), (1920, 1080), (1080, 1920), (640, 480), (480, 640)]
)
def test_phone_accepts_native_portrait_and_landscape_without_transforming_pixels(app, width, height):
    with TestClient(app) as client:
        image = np.full((height, width, 3), 128, np.uint8)
        image[15:45, 15:45] = (0, 0, 255)
        jpeg = cv2.imencode(".jpg", image)[1].tobytes()
        headers = {
            "Content-Type": "image/jpeg",
            "X-Pair-Token": token(client),
            "X-Camera-Optics": '{"orientation":90,"focusMode":"manual"}',
        }
        response = client.post("/api/frames/left", content=jpeg, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["size"] == [width, height]
        frame = app.state.engine.cameras["left"].latest()
        assert frame.image.shape == image.shape
        assert frame.image[30, 30, 2] > 230  # The red reference remains at its original pixel position.
        assert frame.optics["orientation"] == 90
        assert not client.get("/api/state").json()["result"]["points"]


@pytest.mark.parametrize("width,height", [(1920, 1920), (2048, 1080), (1080, 2048), (320, 200)])
def test_phone_still_rejects_out_of_budget_frames_with_actual_dimensions(app, width, height):
    with TestClient(app) as client:
        jpeg = cv2.imencode(".jpg", np.full((height, width, 3), 128, np.uint8))[1].tobytes()
        response = client.post(
            "/api/frames/left",
            content=jpeg,
            headers={"Content-Type": "image/jpeg", "X-Pair-Token": token(client)},
        )
        assert response.status_code == 422
        assert f"{width}×{height}" in response.json()["detail"]


def test_empty_jpeg_has_a_clear_client_error(app):
    with TestClient(app) as client:
        response = client.post(
            "/api/frames/left",
            content=b"",
            headers={"Content-Type": "image/jpeg", "X-Pair-Token": token(client)},
        )
        assert response.status_code == 422
        assert "JPEG" in response.json()["detail"]


def test_mixed_orientation_blocks_stereo_calibration_and_changes_optics_signature(app):
    engine = app.state.engine
    image = np.full((1280, 720, 3), 128, np.uint8)
    engine.cameras["left"].push(image, {"orientation": 0, "focusMode": "manual"})
    signature = engine.cameras["left"].signature(engine.cameras["left"].latest())
    engine.cameras["left"].push(image, {"orientation": 180, "focusMode": "manual"})
    assert signature != engine.cameras["left"].signature(engine.cameras["left"].latest())
    engine.cameras["right"].push(np.zeros((720, 1280, 3), np.uint8), {"focusMode": "manual"})
    _, _, blockers = engine.pair_context()
    assert any("Risoluzioni diverse" in message for message in blockers)


def test_missing_focus_stale_frames_and_changed_optics_never_produce_3d(app):
    engine = app.state.engine
    image = np.full((480, 640, 3), 128, np.uint8)
    engine.configure(RigConfig(stationary_scene=True))
    for cam in engine.cameras.values():
        cam.push(image, {"focusMode": "continuous"})
    engine.tick()
    assert not engine.result["points"]
    assert any("fuoco" in b for b in engine.result["blockers"])
    for cam in engine.cameras.values():
        cam.latest().received -= 5
    engine.tick()
    assert not engine.result["points"]
    assert engine.jpeg == {}


def test_operator_cannot_override_known_continuous_autofocus(app):
    cam = app.state.engine.cameras["left"]
    cam.config = SourceConfig(focus_locked=True)
    cam.push(np.zeros((480, 640, 3), np.uint8), {"focusMode": "continuous"})
    assert not cam.focus_ok(cam.latest())


def test_arrival_pairing_does_not_claim_exposure_synchronization(app):
    engine = app.state.engine
    engine.configure(RigConfig(stationary_scene=True))
    image = np.full((480, 640, 3), 128, np.uint8)
    for cam in engine.cameras.values():
        cam.push(image, {"focusMode": "manual"})
    engine.cameras["right"].latest().received -= 0.3
    _, _, blockers = engine.pair_context()
    assert any("150 ms" in b for b in blockers)


def test_old_capture_thread_cannot_publish_after_reconfiguration(app):
    cam = app.state.engine.cameras["left"]
    generation = cam.generation
    cam.start(SourceConfig())
    cam.push(np.zeros((480, 640, 3), np.uint8), {}, generation)
    assert cam.latest() is None


def test_live_pipeline_requires_stability_and_invalidates_optical_change(app):
    engine = app.state.engine
    images, geometry = demo_scene()
    for cam, image in zip(engine.cameras.values(), images):
        cam.push(image, {"focusMode": "manual", "zoom": 1})
    engine.rig.stationary_scene = True
    _, fingerprint, blockers = engine.pair_context()
    assert not blockers
    intrinsic = np.asarray(geometry["P1"])[:, :3].tolist()
    engine.calibration.profile = {
        **geometry,
        "schema": 1,
        "accepted": True,
        "fingerprint": fingerprint,
        "created_at": "test",
        "size": [960, 540],
        "K1": intrinsic,
        "K2": intrinsic,
        "D1": [0, 0, 0, 0, 0],
        "D2": [0, 0, 0, 0, 0],
        "R2": np.eye(3).tolist(),
    }
    engine.tick()
    assert not engine.result["points"]
    assert any("ferme" in message for message in engine.result["blockers"])
    engine.stable_since -= 1
    for cam, image in zip(engine.cameras.values(), images):
        with cam.lock:
            cam.frames.clear()
        cam.push(image, {"focusMode": "manual", "zoom": 1})
    engine.tick()
    assert len(engine.result["points"]) == 4
    assert engine.result["simulated"] is False
    assert engine.result["synchronization"] == "arrival_only_static_scene"
    for cam, image in zip(engine.cameras.values(), images):
        with cam.lock:
            cam.frames.clear()
        cam.push(image, {"focusMode": "manual", "zoom": 2})
    engine.tick()
    assert not engine.result["points"]
    assert any("ricalibrare" in message for message in engine.result["blockers"])
