import base64

import cv2
import numpy as np


def decode_base64_image(data: str) -> np.ndarray:
    if not data:
        raise ValueError("Empty image payload")

    if "," in data:
        data = data.split(",", 1)[1]

    data = data.strip()

    try:
        raw = base64.b64decode(data)
    except ValueError as exc:
        raise ValueError("Invalid base64 encoding") from exc

    buffer = np.frombuffer(raw, dtype=np.uint8)
    bgr = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("Not a decodable image")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
