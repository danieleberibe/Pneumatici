from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator


class SourceConfig(BaseModel):
    kind: Literal["phone", "usb", "ip"] = "phone"
    address: str = ""
    device: int = Field(default=0, ge=0, le=20)
    width: int = Field(default=1280, ge=320, le=1920)
    height: int = Field(default=720, ge=240, le=1080)
    focus_locked: bool = False

    @model_validator(mode="after")
    def validate_url(self):
        if self.kind == "ip":
            parsed = urlparse(self.address)
            if parsed.scheme not in ("http", "https", "rtsp") or not parsed.hostname:
                raise ValueError("Usare un URL HTTP(S)/RTSP della camera.")
        return self


class RigConfig(BaseModel):
    left: SourceConfig = Field(default_factory=SourceConfig)
    right: SourceConfig = Field(default_factory=lambda: SourceConfig(device=1))
    stationary_scene: bool = False


class DetectionConfig(BaseModel):
    profiles: list[Literal["orange", "green", "blue", "red", "white", "black"]] = Field(
        default_factory=lambda: ["orange", "green", "blue", "white", "black"], min_length=1, max_length=6
    )
    min_radius: float = Field(default=7, ge=3, le=100)
    max_radius: float = Field(default=160, ge=10, le=500)
    circularity: float = Field(default=0.75, ge=0.45, le=0.98)
    white_min: int = Field(default=195, ge=100, le=250)
    black_max: int = Field(default=55, ge=5, le=140)
    epipolar_px: float = Field(default=2.0, ge=0.2, le=5)
    max_reprojection_px: float = Field(default=1.5, ge=0.2, le=4)
    max_depth_m: float = Field(default=5.0, ge=0.2, le=20)
    pixel_sigma: float = Field(default=0.5, ge=0.1, le=3)

    @model_validator(mode="after")
    def radius_order(self):
        if self.max_radius <= self.min_radius:
            raise ValueError("Raggio massimo deve superare il minimo.")
        self.profiles = list(dict.fromkeys(self.profiles))
        return self


class BoardConfig(BaseModel):
    squares_x: int = Field(default=7, ge=4, le=12)
    squares_y: int = Field(default=5, ge=4, le=10)
    square_mm: float = Field(default=25, ge=5, le=80)
    marker_mm: float = Field(default=18, ge=3, le=60)

    @model_validator(mode="after")
    def marker_size(self):
        if self.marker_mm >= self.square_mm * 0.85:
            raise ValueError("Il marker deve essere più piccolo dell'85% del quadrato.")
        return self
