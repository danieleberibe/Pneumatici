import hashlib
import json
import threading
import time
from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np

from .models import SourceConfig


@dataclass
class Frame:
    image: np.ndarray
    received: float
    sequence: int
    optics: dict


class Camera:
    def __init__(self, name):
        self.name = name
        self.config = SourceConfig()
        self.frames = deque(maxlen=12)
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.error = None
        self.sequence = 0
        self.generation = 0

    def start(self, config):
        self.stop()
        self.config = config
        self.error = None
        self.generation += 1
        with self.lock:
            self.frames.clear()
        if config.kind != "phone":
            stop = threading.Event()
            self.stop_event = stop
            self.thread = threading.Thread(
                target=self._read, args=(config, stop, self.generation), daemon=True
            )
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=0.2)
            self.thread = None

    def push(self, image, optics=None, generation=None):
        if generation is not None and generation != self.generation:
            return
        with self.lock:
            self.sequence += 1
            self.frames.append(Frame(image, time.monotonic(), self.sequence, optics or {}))
            self.error = None

    def latest(self):
        with self.lock:
            return self.frames[-1] if self.frames else None

    def _read(self, config, stop, generation):
        source = config.device if config.kind == "usb" else config.address
        cap = None
        try:
            if config.kind == "ip":
                cap = cv2.VideoCapture(
                    source,
                    cv2.CAP_FFMPEG,
                    [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 4000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000],
                )
            else:
                cap = cv2.VideoCapture(source)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.height)
                cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
            if not cap.isOpened():
                raise ValueError("Sorgente non raggiungibile. Verificare indirizzo, permessi e rete.")
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            while not stop.is_set():
                ok, image = cap.read()
                if not ok:
                    raise ValueError("Stream interrotto. Riconnettere le camere.")
                optics = {
                    "focus": round(cap.get(cv2.CAP_PROP_FOCUS), 4),
                    "autofocus": cap.get(cv2.CAP_PROP_AUTOFOCUS),
                    "source": config.kind,
                }
                if not stop.is_set():
                    self.push(image, optics, generation)
        except Exception:
            if generation == self.generation:
                self.error = "Acquisizione non disponibile: verificare sorgente e riconnettere."
        finally:
            if cap:
                cap.release()

    def signature(self, frame):
        payload = {
            "config": self.config.model_dump(),
            "size": list(frame.image.shape[:2]),
            "optics": frame.optics,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def status(self):
        frame = self.latest()
        age = time.monotonic() - frame.received if frame else None
        with self.lock:
            frames = list(self.frames)
        fps = (
            (len(frames) - 1) / (frames[-1].received - frames[0].received)
            if len(frames) > 1 and frames[-1].received > frames[0].received
            else 0
        )
        return {
            "connected": age is not None and age < 1.5,
            "age_ms": round(age * 1000) if age else None,
            "fps": round(fps, 1) if age is not None and age < 1.5 else 0,
            "size": [frame.image.shape[1], frame.image.shape[0]] if frame else None,
            "kind": self.config.kind,
            "focus_locked": self.focus_ok(frame),
            "error": self.error,
            "optics": frame.optics if frame else {},
        }

    def focus_ok(self, frame):
        if frame is None:
            return False
        if frame.optics.get("focusMode") == "continuous" or frame.optics.get("autofocus", 0) > 0:
            return False
        return self.config.focus_locked or frame.optics.get("focusMode") == "manual"


def nearest_pair(left: Camera, right: Camera):
    now = time.monotonic()
    with left.lock:
        a = [f for f in left.frames if now - f.received < 0.8]
    with right.lock:
        b = [f for f in right.frames if now - f.received < 0.8]
    if not a or not b:
        return None
    # Prefer recent pairs, then closest arrival time. Arrival is NOT exposure time.
    latest = max(min(x.received, y.received) for x in a for y in b)
    pairs = [(x, y) for x in a for y in b if min(x.received, y.received) >= latest - 0.12]
    return min(pairs, key=lambda pair: abs(pair[0].received - pair[1].received))
