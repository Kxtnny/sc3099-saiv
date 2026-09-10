import base64
from typing import Tuple

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


def crop_relative(
    image: np.ndarray, bbox: Tuple[float, float, float, float]
) -> np.ndarray:
    height, width = image.shape[:2]
    x, y, w, h = bbox

    x1 = max(0, int(x * width))
    y1 = max(0, int(y * height))
    x2 = min(width, int((x + w) * width))
    y2 = min(height, int((y + h) * height))

    if x2 <= x1 or y2 <= y1:
        return image

    crop = image[y1:y2, x1:x2]
    return crop if crop.size else image


def resize_square(image: np.ndarray, size: int) -> np.ndarray:
    return cv2.resize(image, (size, size), interpolation=cv2.INTER_AREA)