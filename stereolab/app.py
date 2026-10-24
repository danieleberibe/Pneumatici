import asyncio
import csv
import io
import json
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .calibration import board_svg
from .engine import Engine
from .models import BoardConfig, DetectionConfig, RigConfig
from .pairing import phone_origin, qr_png

ROOT = Path(__file__).parent


class Toggle(BaseModel):
    enabled: bool


def create_app(data_dir: Path | None = None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.engine.start()
        yield
        app.state.engine.close()

    app = FastAPI(title="StereoLab API", version="0.1.0", lifespan=lifespan)
    engine = Engine(data_dir or Path(os.getenv("STEREOLAB_DATA", "data")))
    app.state.engine = engine
    app.state.tokens = {s: secrets.token_urlsafe(24) for s in ("left", "right")}
    app.state.phone_origin = None
    app.state.setup_url = None

    @app.middleware("http")
    async def local_origin(request, call_next):
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin:
            parsed = urlsplit(origin)
            if parsed.netloc != request.headers.get("host") or parsed.scheme != request.url.scheme:
                return JSONResponse({"detail": "Origine non autorizzata."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValueError)
    async def bad_input(request, error):
        return JSONResponse({"detail": str(error)}, status_code=422)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "0.1.0", "opencv": cv2.__version__}

    @app.get("/api/state")
    def state():
        return engine.status()

    @app.get("/api/pairing")
    def pairing():
        return {s: f"/phone?side={s}#token={token}" for s, token in app.state.tokens.items()}

    @app.get("/api/connection")
    def connection():
        return {"public_origin": app.state.phone_origin, "setup_url": app.state.setup_url}

    @app.get("/api/pairing/qr/{target}.png")
    def pairing_qr(target: Literal["left", "right", "setup"], origin: str | None = None):
        if target == "setup":
            url = app.state.setup_url
            if not url:
                raise HTTPException(404, "Avviare il server telefoni per la pagina guidata.")
        else:
            base = phone_origin(origin or app.state.phone_origin or "")
            url = f"{base}/phone?side={target}#token={app.state.tokens[target]}"
        return Response(qr_png(url), media_type="image/png")

    @app.put("/api/rig")
    def rig(config: RigConfig):
        engine.configure(config)
        app.state.tokens = {s: secrets.token_urlsafe(24) for s in ("left", "right")}
        return {"ok": True}

    @app.put("/api/detection")
    def detection(config: DetectionConfig):
        with engine.lock:
            engine.detection = config
            engine.last_pair = None
            engine.previous_positions = None
            engine.result["points"] = []
            engine.event("info", "Parametri di rilevamento aggiornati.")
        return {"ok": True}

    @app.post("/api/demo")
    def demo(toggle: Toggle):
        engine.set_demo(toggle.enabled)
        return {"ok": True}

    @app.post("/api/pause")
    def pause(toggle: Toggle):
        with engine.lock:
            engine.paused = toggle.enabled
            engine.result["points"] = []
            engine.last_pair = None
            engine.previous_positions = None
        return {"ok": True}

    @app.post("/api/frames/{side}")
    async def frame(side: Literal["left", "right"], request: Request):
        supplied = request.headers.get("x-pair-token", "")
        if not secrets.compare_digest(supplied, app.state.tokens[side]):
            raise HTTPException(401, "Link di collegamento scaduto. Riaprire dal pannello Sorgenti.")
        cam = engine.cameras[side]
        generation = cam.generation
        if cam.config.kind != "phone":
            raise HTTPException(409, "Questa sorgente non è in modalità telefono.")
        if request.headers.get("content-type", "").split(";")[0] != "image/jpeg":
            raise HTTPException(415, "Inviare un frame JPEG.")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 2_000_000:
                raise HTTPException(413, "Frame troppo grande (massimo 2 MB).")
        raw_meta = request.headers.get("x-camera-optics", "{}")
        if len(raw_meta) > 2048:
            raise HTTPException(413, "Metadati troppo grandi.")
        try:
            meta = json.loads(raw_meta)
            if not isinstance(meta, dict):
                raise ValueError()
            allowed = (
                "deviceId",
                "focusMode",
                "focusDistance",
                "zoom",
                "session",
                "width",
                "height",
                "orientation",
            )
            optics = {key: value for key, value in meta.items() if key in allowed}
            if any(not isinstance(v, (str, float, int)) or len(str(v)) > 256 for v in optics.values()):
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(422, "Metadati ottici non validi.") from None
        try:
            image = await asyncio.to_thread(cv2.imdecode, np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
        except cv2.error:
            image = None
        if image is None:
            raise HTTPException(422, "Il frame JPEG ricevuto è vuoto o non decodificabile.")
        height, width = image.shape[:2]
        short_side, long_side = sorted((width, height))
        # Safari can deliver a portrait frame even for landscape getUserMedia constraints.
        # Keep native pixels untouched: both orientations have the same resolution budget.
        if not 240 <= short_side <= 1080 or not 320 <= long_side <= 1920:
            raise HTTPException(
                422,
                f"Frame ricevuto: {width}×{height} px. Sono supportati 320×240–1920×1080 "
                "e i corrispondenti formati verticali. Seleziona 1280×720 o 640×480.",
            )
        if not secrets.compare_digest(supplied, app.state.tokens[side]):
            raise HTTPException(401, "Configurazione cambiata: riaprire il link del telefono.")
        cam.push(image, optics, generation)
        return {"ok": True, "sequence": cam.sequence, "size": [width, height]}

    @app.get("/api/preview/{side}.jpg")
    def preview(side: Literal["left", "right"]):
        with engine.lock:
            image = engine.jpeg.get(side)
        if not image:
            return Response(status_code=204)
        return Response(image, media_type="image/jpeg")

    @app.put("/api/calibration/board")
    def board(config: BoardConfig):
        with engine.lock:
            if engine.solving:
                raise HTTPException(409, "Attendere il termine della calibrazione.")
            engine.calibration.reset(config)
            engine.generation += 1
            engine.event("info", "Nuova sessione di calibrazione. Campioni azzerati.")
        return {"ok": True}

    @app.get("/api/calibration/board.svg")
    def printable_board():
        with engine.lock:
            svg = board_svg(engine.calibration.board)
        return Response(
            svg,
            media_type="image/svg+xml",
            headers={"Content-Disposition": 'inline; filename="stereolab-charuco.svg"'},
        )

    @app.post("/api/calibration/capture")
    def capture():
        return engine.capture()

    @app.post("/api/calibration/solve")
    def solve():
        return engine.solve()

    @app.get("/api/calibration/export")
    def export_calibration():
        with engine.lock:
            if not engine.calibration.profile:
                raise HTTPException(404, "Nessun profilo disponibile.")
            return JSONResponse(
                engine.calibration.profile,
                headers={"Content-Disposition": 'attachment; filename="calibration.json"'},
            )

    @app.get("/api/export.csv")
    def export_csv():
        with engine.lock:
            result = dict(engine.result)
            if engine.paused or time_stale(engine.last_processed) or not result.get("points"):
                raise HTTPException(409, "Nessuna misura corrente da esportare.")
        stream = io.StringIO(newline="")
        fields = [
            "timestamp",
            "simulated",
            "coordinate_frame",
            "units",
            "synchronization",
            "id",
            "profile",
            "x_m",
            "y_m",
            "z_m",
            "sigma_z_mm",
            "epipolar_px",
            "reprojection_px",
            "disparity_px",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for point in result["points"]:
            writer.writerow({**{k: result.get(k) for k in fields}, **point})
        return Response(
            stream.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="stereolab-measurements.csv"'},
        )

    @app.get("/")
    def index():
        return FileResponse(ROOT / "static" / "index.html")

    @app.get("/phone")
    def phone():
        return FileResponse(ROOT / "static" / "phone.html")

    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    return app


def time_stale(last):
    import time

    return time.monotonic() - last > 1.0


app = create_app()
