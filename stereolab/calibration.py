import base64
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np

from .models import BoardConfig


def board_object(config: BoardConfig):
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    # DICT_4X4_50 contains at most 50 distinct markers.
    if config.squares_x * config.squares_y // 2 > 50:
        raise ValueError("La tavola supera i 50 marker del dizionario.")
    return cv2.aruco.CharucoBoard(
        (config.squares_x, config.squares_y), config.square_mm / 1000, config.marker_mm / 1000, dictionary
    )


def board_svg(config):
    board = board_object(config)
    image = board.generateImage((config.squares_x * 160, config.squares_y * 160), marginSize=0)
    encoded = base64.b64encode(cv2.imencode(".png", image)[1]).decode()
    w, h = config.squares_x * config.square_mm, config.squares_y * config.square_mm
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w + 20}mm" height="{h + 30}mm" '
        f'viewBox="0 0 {w + 20} {h + 30}"><rect width="100%" height="100%" fill="white"/>'
        f'<image x="10" y="10" width="{w}" height="{h}" href="data:image/png;base64,{encoded}"/>'
        f'<text x="10" y="{h + 17}" font-size="3">StereoLab | DICT_4X4_50 | '
        f"quadrato {config.square_mm} mm | stampa 100%</text>"
        f'<path d="M10 {h + 24}h50m0 -2v4m-50 -4v4" stroke="black" stroke-width="0.3"/>'
        f'<text x="65" y="{h + 25}" font-size="3">50 mm: verificare con righello</text></svg>'
    )


@dataclass
class Sample:
    object_points: np.ndarray
    left: np.ndarray
    right: np.ndarray
    ids: np.ndarray
    size: tuple[int, int]


class Calibration:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.board = BoardConfig()
        self.samples: list[Sample] = []
        self.fingerprint = None
        self.profile = None
        self.load_error = None
        path = directory / "calibration.json"
        if path.exists():
            try:
                candidate = json.loads(path.read_text())
                validate_profile(candidate)
                self.profile = candidate
            except (ValueError, KeyError, TypeError):
                self.load_error = "Profilo salvato non valido: eseguire una nuova calibrazione."

    def reset(self, config: BoardConfig):
        board_object(config)
        self.board = config
        self.samples = []
        self.fingerprint = None

    def capture(self, left, right, fingerprint):
        if left.shape != right.shape:
            raise ValueError("Le due camere devono fornire la stessa risoluzione.")
        if self.fingerprint and fingerprint != self.fingerprint:
            raise ValueError("Ottica o sorgente cambiate: azzerare i campioni.")
        board = board_object(self.board)
        detector = cv2.aruco.CharucoDetector(board)
        found = []
        for name, image in [("sinistra", left), ("destra", right)]:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            corners, ids, _, _ = detector.detectBoard(gray)
            if ids is None or len(ids) < 12:
                raise ValueError(f"Camera {name}: servono almeno 12 angoli ChArUco visibili.")
            if cv2.Laplacian(gray, cv2.CV_64F).var() < 35:
                raise ValueError(f"Camera {name}: immagine sfocata, controllare fuoco e movimento.")
            found.append({int(i): c for i, c in zip(ids.ravel(), corners.reshape(-1, 2))})
        ids = np.array(sorted(found[0].keys() & found[1].keys()), dtype=int)
        if len(ids) < 12:
            raise ValueError("Servono 12 angoli comuni alle due camere.")
        points = [np.array([f[i] for i in ids], np.float32).reshape(-1, 1, 2) for f in found]
        size = (left.shape[1], left.shape[0])
        for pts in points:
            coverage = cv2.contourArea(cv2.convexHull(pts)) / (size[0] * size[1])
            if coverage < 0.025:
                raise ValueError("Tavola troppo piccola: avvicinarla alle camere.")
        if self.samples and size != self.samples[0].size:
            raise ValueError("Risoluzione cambiata: azzerare i campioni.")
        for old in self.samples:
            common, a, b = np.intersect1d(ids, old.ids, return_indices=True)
            if len(common) >= 8:
                delta = np.linalg.norm(points[0][a, 0] - old.left[b, 0], axis=1).mean()
                if delta < size[0] * 0.018:
                    raise ValueError("Posa troppo simile: spostare o inclinare la tavola, poi fermarla.")
        if len(self.samples) >= 60:
            raise ValueError("Raggiunto il limite di 60 coppie.")
        obj = board.getChessboardCorners()[ids].astype(np.float32)
        self.samples.append(Sample(obj, points[0], points[1], ids, size))
        self.fingerprint = fingerprint
        return {"count": len(self.samples), "common_corners": len(ids)}

    def save(self, profile):
        validate_profile(profile)
        path = self.directory / "calibration.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(profile, indent=2), encoding="utf-8")
        os.replace(temporary, path)
        self.profile = profile


def validate_profile(profile):
    for key, shape in {
        "K1": (3, 3),
        "K2": (3, 3),
        "R": (3, 3),
        "R1": (3, 3),
        "R2": (3, 3),
        "P1": (3, 4),
        "P2": (3, 4),
    }.items():
        value = np.asarray(profile[key], dtype=float)
        if value.shape != shape or not np.isfinite(value).all():
            raise ValueError("Matrice di calibrazione non valida.")
    for key in ("D1", "D2", "T"):
        if not np.isfinite(np.asarray(profile[key], dtype=float)).all():
            raise ValueError("Parametri non finiti.")
    if len(profile["size"]) != 2 or profile.get("schema") != 1:
        raise ValueError("Formato di calibrazione non supportato.")
    if not isinstance(profile.get("fingerprint"), str) or not isinstance(profile.get("accepted"), bool):
        raise ValueError("Metadati mancanti.")


def solve_calibration(samples, board_config, fingerprint):
    if len(samples) < 15:
        raise ValueError("Acquisire almeno 15 coppie diverse; consigliate 25–35.")
    # Every fifth view is held out from BOTH intrinsic and stereo fitting.
    train = [s for i, s in enumerate(samples) if i % 5 != 4]
    held = [s for i, s in enumerate(samples) if i % 5 == 4]
    size = train[0].size
    obj = [s.object_points for s in train]
    a, b = [s.left for s in train], [s.right for s in train]
    rms1, k1, d1, rotations, _ = cv2.calibrateCamera(obj, a, size, None, None)
    rms2, k2, d2, _, _ = cv2.calibrateCamera(obj, b, size, None, None)
    rms, k1, d1, k2, d2, r, t, _, _ = cv2.stereoCalibrate(
        obj,
        a,
        b,
        k1,
        d1,
        k2,
        d2,
        size,
        flags=cv2.CALIB_FIX_INTRINSIC,
        criteria=(cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-7),
    )
    r1, r2, p1, p2, q, roi1, roi2 = cv2.stereoRectify(k1, d1, k2, d2, size, r, t, alpha=0)
    vertical_errors, validation_errors = [], []
    for sample in held:
        u1 = cv2.undistortPoints(sample.left, k1, d1, R=r1, P=p1).reshape(-1, 2)
        u2 = cv2.undistortPoints(sample.right, k2, d2, R=r2, P=p2).reshape(-1, 2)
        vertical_errors.extend((u1[:, 1] - u2[:, 1]).tolist())
        for observed, k, d in [(sample.left, k1, d1), (sample.right, k2, d2)]:
            ok, rv, tv = cv2.solvePnP(sample.object_points, observed, k, d)
            if not ok:
                raise ValueError("Validazione pose non riuscita.")
            projected = cv2.projectPoints(sample.object_points, rv, tv, k, d)[0]
            validation_errors.extend(np.linalg.norm(projected - observed, axis=2).ravel().tolist())
    epi = float(np.sqrt(np.mean(np.square(vertical_errors))))
    hold_rms = float(np.sqrt(np.mean(np.square(validation_errors))))
    baseline = float(np.linalg.norm(t))
    # Require views spanning at least three regions and a meaningful perspective change.
    centers = np.array([s.left[:, 0].mean(axis=0) for s in train]) / np.array(size)
    bins = {(min(2, int(c[0] * 3)), min(2, int(c[1] * 3))) for c in centers}
    warnings = []
    normals = np.array([cv2.Rodrigues(rv)[0][:, 2] for rv in rotations])
    tilt_span = float(np.degrees(np.arccos(np.clip(normals @ normals.T, -1, 1))).max())
    if tilt_span < 15:
        warnings.append("Inclinazioni insufficienti: variare la prospettiva della tavola di almeno 15 gradi.")
    for intrinsic in (k1, k2):
        if (
            not 0.25 * size[0] < intrinsic[0, 0] < 5 * size[0]
            or not 0.25 * size[0] < intrinsic[1, 1] < 5 * size[0]
            or not 0 < intrinsic[0, 2] < size[0]
            or not 0 < intrinsic[1, 2] < size[1]
        ):
            warnings.append("Intrinseci non plausibili per questo rig: aumentare la varietà delle pose.")
            break
    if len(bins) < 3:
        warnings.append("Copertura insufficiente: spostare la tavola in almeno 3 zone dell'immagine.")
    if max(rms1, rms2, rms) > 1.0:
        warnings.append("RMS di calibrazione sopra 1 px.")
    if epi > 1.0 or hold_rms > 1.2:
        warnings.append("Errore sui campioni di verifica troppo alto.")
    if not 0.02 <= baseline <= 2.0:
        warnings.append("Baseline fuori intervallo 20–2000 mm: verificare scala e montaggio.")
    if abs(float(p2[1, 3])) > abs(float(p2[0, 3])):
        warnings.append("Rig verticale non supportato: montare le camere affiancate orizzontalmente.")
    if any(not np.isfinite(x) for x in [rms1, rms2, rms, epi, hold_rms, baseline]):
        raise ValueError("Calibrazione numericamente instabile.")
    profile = {
        "schema": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "fingerprint": fingerprint,
        "board": board_config.model_dump(),
        "size": list(size),
        "accepted": not warnings,
        "warnings": warnings,
        "samples": len(samples),
        "training_samples": len(train),
        "validation_samples": len(held),
        "coverage_regions": len(bins),
        "tilt_span_deg": tilt_span,
        "rms_left": rms1,
        "rms_right": rms2,
        "rms_stereo": rms,
        "validation_rms": hold_rms,
        "epipolar_rms": epi,
        "baseline_mm": baseline * 1000,
        "roi1": list(roi1),
        "roi2": list(roi2),
    }
    for name, value in [
        ("K1", k1),
        ("D1", d1),
        ("K2", k2),
        ("D2", d2),
        ("R", r),
        ("T", t),
        ("R1", r1),
        ("R2", r2),
        ("P1", p1),
        ("P2", p2),
        ("Q", q),
    ]:
        profile[name] = value.tolist()
    validate_profile(profile)
    return profile
