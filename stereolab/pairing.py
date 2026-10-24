"""Local QR generation. Pairing tokens never leave the StereoLab server."""

import ipaddress
from urllib.parse import urlsplit

import cv2


def phone_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or len(value) > 250
    ):
        raise ValueError("Inserire solo l'origine HTTPS del computer, es. https://192.168.1.37:8767.")
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("Localhost non è raggiungibile dai telefoni: usare l'IP LAN del computer.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address and (address.is_loopback or address.is_unspecified or address.is_link_local):
        raise ValueError("Usare un indirizzo LAN raggiungibile dai telefoni.")
    _ = parsed.port  # Validate malformed port numbers too.
    return f"https://{parsed.netloc}"


def qr_png(url: str) -> bytes:
    parameters = cv2.QRCodeEncoder_Params()
    parameters.correction_level = cv2.QRCodeEncoder_CORRECT_LEVEL_M
    matrix = cv2.QRCodeEncoder_create(parameters).encode(url)
    matrix = cv2.copyMakeBorder(matrix, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=255)
    image = cv2.resize(matrix, None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST)
    return cv2.imencode(".png", image)[1].tobytes()
