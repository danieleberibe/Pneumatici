from urllib.parse import parse_qs, urlsplit

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from stereolab.app import create_app
from stereolab.models import RigConfig


def decode(response):
    assert response.status_code == 200
    image = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_GRAYSCALE)
    url, _, _ = cv2.QRCodeDetector().detectAndDecode(image)
    assert url, "QR must be readable by a real decoder"
    return urlsplit(url)


def test_qr_codes_encode_correct_camera_current_token_and_lan_origin(tmp_path):
    app = create_app(tmp_path)
    app.state.phone_origin = "https://192.168.1.37:8767"
    app.state.setup_url = "http://192.168.1.37:8765/connect"
    with TestClient(app) as client:
        before = {}
        for side in ("left", "right"):
            response = client.get(f"/api/pairing/qr/{side}.png")
            assert response.headers["cache-control"] == "no-store"
            decoded = decode(response)
            assert decoded.scheme == "https" and decoded.netloc == "192.168.1.37:8767"
            assert parse_qs(decoded.query)["side"] == [side]
            before[side] = parse_qs(decoded.fragment)["token"][0]
            assert before[side] == app.state.tokens[side]
        assert before["left"] != before["right"]
        setup = decode(client.get("/api/pairing/qr/setup.png"))
        assert setup.geturl() == app.state.setup_url
        client.put("/api/rig", json=RigConfig().model_dump())
        after = decode(client.get("/api/pairing/qr/left.png"))
        assert parse_qs(after.fragment)["token"][0] != before["left"]
        assert client.get("/api/connection").json()["public_origin"] == app.state.phone_origin


@pytest.mark.parametrize(
    "origin",
    [
        "http://192.168.1.37:8767",
        "https://127.0.0.1:8767",
        "https://localhost:8767",
        "https://[::1]:8767",
        "https://0.0.0.0:8767",
        "https://example.com/path",
        "https://user:pass@example.com",
        "https://example.com:bad",
    ],
)
def test_unusable_phone_origins_are_rejected(tmp_path, origin):
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/pairing/qr/left.png", params={"origin": origin}).status_code == 422
