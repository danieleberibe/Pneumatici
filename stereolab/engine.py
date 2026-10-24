import hashlib
import logging
import threading
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np

from .acquisition import Camera, nearest_pair
from .calibration import Calibration, solve_calibration
from .demo import demo_scene
from .detection import annotate, detect_balls
from .geometry import triangulate_matches
from .models import DetectionConfig, RigConfig

log = logging.getLogger(__name__)


class Engine:
    def __init__(self, directory: Path):
        self.lock = threading.RLock()
        self.cameras = {side: Camera(side) for side in ("left", "right")}
        self.rig = RigConfig()
        self.detection = DetectionConfig()
        self.calibration = Calibration(directory)
        self.demo = False
        self.paused = False
        self.solving = False
        self.generation = 0
        self.events = deque(maxlen=60)
        self.jpeg = {}
        self.result = {"points": [], "blockers": ["Collegare le due camere."], "pair_skew_ms": None}
        self.stop_event = threading.Event()
        self.thread = None
        self.maps_key = None
        self.maps = None
        self.previous_positions = None
        self.stable_since = time.monotonic()
        self.last_pair = None
        self.last_processed = 0.0
        self.event("info", "Laboratorio pronto. Collegare le camere o avviare la demo.")

    def start(self):
        self.thread = threading.Thread(target=self._loop, daemon=True, name="stereo-pipeline")
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
        for cam in self.cameras.values():
            cam.stop()

    def event(self, level, message):
        self.events.appendleft({"time": datetime.now(UTC).isoformat(), "level": level, "message": message})

    def configure(self, rig):
        with self.lock:
            self.demo = False
            self.paused = False
            self.rig = rig
            self.generation += 1
            self.calibration.reset(self.calibration.board)
            self.maps_key = None
            self.jpeg.clear()
            self.result = {"points": [], "blockers": ["Attesa nuove immagini."], "pair_skew_ms": None}
            self.last_pair = None
            self.previous_positions = None
            for side, cam in self.cameras.items():
                cam.start(getattr(rig, side))
            self.event("info", "Sorgenti aggiornate. Verificare montaggio rigido, fuoco e scala.")

    def set_demo(self, enabled):
        with self.lock:
            self.demo = enabled
            self.paused = False
            self.generation += 1
            self.result = {"points": [], "blockers": [], "pair_skew_ms": None}
            self.jpeg.clear()
            self.last_pair = None
            self.previous_positions = None
            self.event(
                "info", "Demo sintetica attiva: coordinate simulate." if enabled else "Modalità camere reali."
            )

    def pair_context(self):
        pair = nearest_pair(self.cameras["left"], self.cameras["right"])
        if not pair:
            errors = [
                f"Camera {side}: {camera.error}" for side, camera in self.cameras.items() if camera.error
            ]
            return None, None, ["Manca una coppia recente: collegare entrambe le camere.", *errors]
        fingerprint = hashlib.sha256(
            "|".join(self.cameras[s].signature(f) for s, f in zip(("left", "right"), pair)).encode()
        ).hexdigest()
        blockers = []
        if pair[0].image.shape != pair[1].image.shape:
            blockers.append("Risoluzioni diverse: selezionare la stessa dimensione sui due telefoni.")
        if abs(pair[0].received - pair[1].received) > 0.15:
            blockers.append("Arrivo dei frame troppo distante (>150 ms).")
        if not self.rig.stationary_scene:
            blockers.append("Confermare scena ferma: questi ingressi non hanno sincronizzazione hardware.")
        if not all(self.cameras[s].focus_ok(f) for s, f in zip(("left", "right"), pair)):
            blockers.append("Bloccare e verificare il fuoco su entrambe le camere.")
        return pair, fingerprint, blockers

    def capture(self):
        with self.lock:
            if self.demo or self.solving or self.paused:
                raise ValueError("Acquisizione disponibile su camere reali, a calibrazione inattiva.")
            pair, fingerprint, blockers = self.pair_context()
            if blockers:
                raise ValueError(" ".join(blockers))
            result = self.calibration.capture(pair[0].image, pair[1].image, fingerprint)
            self.event(
                "success",
                f"Coppia {result['count']:02d} acquisita: {result['common_corners']} angoli comuni.",
            )
            return result

    def solve(self):
        with self.lock:
            if self.solving or self.demo:
                raise ValueError("Calibrazione già attiva o modalità demo.")
            self.solving = True
            samples = list(self.calibration.samples)
            board = self.calibration.board.model_copy()
            fingerprint = self.calibration.fingerprint
            generation = self.generation
        try:
            profile = solve_calibration(samples, board, fingerprint)
            with self.lock:
                if self.generation != generation:
                    raise ValueError("Configurazione cambiata durante il calcolo. Ripetere la calibrazione.")
                self.calibration.save(profile)
                self.maps_key = None
                self.event(
                    "success" if profile["accepted"] else "warning",
                    f"Calibrazione {'accettata' if profile['accepted'] else 'da migliorare'} · RMS {profile['rms_stereo']:.3f} px.",
                )
            return profile
        except cv2.error as error:
            raise ValueError(
                "OpenCV non riesce a stimare il rig: acquisire pose più varie e nitide."
            ) from error
        finally:
            with self.lock:
                self.solving = False

    def _loop(self):
        while not self.stop_event.is_set():
            start = time.monotonic()
            try:
                with self.lock:
                    self.tick()
            except Exception:
                log.exception("Pipeline failure")
                with self.lock:
                    self.result = {
                        "points": [],
                        "blockers": ["Errore nella pipeline. Controllare i log del server."],
                        "pair_skew_ms": None,
                    }
            self.stop_event.wait(max(0.01, 0.10 - (time.monotonic() - start)))

    def tick(self):
        start = time.monotonic()
        blockers, skew, profile, rectified = [], None, None, False
        if self.paused:
            self.result["points"] = []
            self.result["blockers"] = ["Acquisizione in pausa: nessuna misura corrente."]
            return
        if self.demo:
            images, profile = demo_scene()
            skew = 0
            rectified = True
        else:
            pair, fingerprint, blockers = self.pair_context()
            if not pair:
                self.previous_positions = None
                # Still show the connected camera while waiting for its partner.
                for side, cam in self.cameras.items():
                    frame = cam.latest()
                    if frame and start - frame.received < 1.5:
                        self.jpeg[side] = cv2.imencode(".jpg", frame.image, [cv2.IMWRITE_JPEG_QUALITY, 80])[
                            1
                        ].tobytes()
                    else:
                        self.jpeg.pop(side, None)
                self.result = {"points": [], "blockers": blockers, "pair_skew_ms": None}
                return
            images = [f.image for f in pair]
            skew = abs(pair[0].received - pair[1].received) * 1000
            profile = self.calibration.profile
            if not profile or not profile["accepted"]:
                blockers.append("Calibrazione stereo valida necessaria per le coordinate 3D.")
            elif profile["fingerprint"] != fingerprint:
                blockers.append("Ottica, sorgente o risoluzione diverse dal profilo: ricalibrare.")
            else:
                if self.maps_key != profile["created_at"]:
                    self.maps = [
                        cv2.initUndistortRectifyMap(
                            np.array(profile[f"K{i}"]),
                            np.array(profile[f"D{i}"]),
                            np.array(profile[f"R{i}"]),
                            np.array(profile[f"P{i}"]),
                            tuple(profile["size"]),
                            cv2.CV_32FC1,
                        )
                        for i in (1, 2)
                    ]
                    self.maps_key = profile["created_at"]
                images = [cv2.remap(image, *maps, cv2.INTER_LINEAR) for image, maps in zip(images, self.maps)]
                rectified = True
            key = tuple(f.sequence for f in pair)
            if key == self.last_pair and start - self.last_processed < 0.5:
                return
            self.last_pair = key
        balls = [detect_balls(image, self.detection) for image in images]
        if not self.demo:
            positions = np.array(
                [[b.x, b.y] for group in balls for b in sorted(group, key=lambda x: (x.profile, x.x))]
            )
            if (
                self.previous_positions is None
                or positions.shape != self.previous_positions.shape
                or (positions.size and np.max(np.abs(positions - self.previous_positions)) > 2.5)
            ):
                self.stable_since = start
                # Compare against the stability window's anchor, not only the last frame:
                # slow cumulative movement must not pass as stationary.
                self.previous_positions = positions
            if start - self.stable_since < 0.8:
                blockers.append("Attendere palline ferme per almeno 0,8 s.")
        points, rejected = [], {}
        if not blockers and rectified:
            points, rejected = triangulate_matches(*balls, profile, self.detection)
        for side, image, detected in zip(("left", "right"), images, balls):
            overlay = annotate(image, detected)
            if rectified:
                for y in range(60, overlay.shape[0], 80):
                    cv2.line(overlay, (0, y), (overlay.shape[1], y), (100, 95, 70), 1)
            self.jpeg[side] = cv2.imencode(".jpg", overlay, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()
        self.last_processed = start
        self.result = {
            "points": points,
            "blockers": blockers,
            "pair_skew_ms": round(skew, 1),
            "detections": {"left": len(balls[0]), "right": len(balls[1])},
            "rejected": rejected,
            "processing_ms": round((time.monotonic() - start) * 1000, 1),
            "rectified": rectified,
            "timestamp": datetime.now(UTC).isoformat(),
            "simulated": self.demo,
            "coordinate_frame": "left_camera_optical",
            "units": "metres",
            "synchronization": "synthetic" if self.demo else "arrival_only_static_scene",
        }

    def status(self):
        with self.lock:
            profile = self.calibration.profile
            summary = (
                {
                    k: v
                    for k, v in profile.items()
                    if k
                    in (
                        "created_at",
                        "accepted",
                        "warnings",
                        "rms_left",
                        "rms_right",
                        "rms_stereo",
                        "validation_rms",
                        "epipolar_rms",
                        "baseline_mm",
                        "samples",
                        "validation_samples",
                        "coverage_regions",
                        "size",
                    )
                }
                if profile
                else None
            )
            return {
                "mode": "demo" if self.demo else "live",
                "paused": self.paused,
                "solving": self.solving,
                "cameras": {s: c.status() for s, c in self.cameras.items()},
                "result": self.result,
                "calibration": summary,
                "samples": len(self.calibration.samples),
                "board": self.calibration.board.model_dump(),
                "detection": self.detection.model_dump(),
                "rig": self.rig.model_dump(),
                "events": list(self.events),
                "load_error": self.calibration.load_error,
            }
