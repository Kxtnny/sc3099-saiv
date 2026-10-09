"""Geospatial helpers for geofence validation."""

import math
from typing import Optional, Tuple

EARTH_RADIUS_METERS = 6_371_000.0

# Singapore's territory as a (lat, lon) polygon traced along the water
# between it and its neighbours: mid Johor Strait to the north (so Johor
# Bahru, under 2 km from Woodlands, stays outside) and the Singapore Strait
# to the south (Batam outside). Covers the main island, Tuas, Jurong Island,
# Sentosa, the Southern Islands, Pulau Ubin and Pulau Tekong. Accurate to
# a few hundred metres, which is far tighter than any course geofence.
SINGAPORE_BORDER = [
    (1.2700, 103.5850),
    (1.3100, 103.5950),
    (1.3450, 103.6250),   # Second Link
    (1.3600, 103.6450),
    (1.3900, 103.6600),
    (1.4200, 103.6700),
    (1.4400, 103.6900),
    (1.4550, 103.7250),
    (1.4560, 103.7600),
    (1.4530, 103.7690),   # Causeway
    (1.4560, 103.7900),
    (1.4790, 103.8200),   # off Sembawang
    (1.4700, 103.8600),
    (1.4400, 103.9000),
    (1.4350, 103.9600),   # north of Pulau Ubin
    (1.4450, 104.0300),   # north of Pulau Tekong
    (1.4300, 104.0700),
    (1.3700, 104.0750),
    (1.3200, 104.0600),   # east of Changi
    (1.2600, 104.0500),
    (1.2000, 104.0000),
    (1.1900, 103.9000),
    (1.1500, 103.8000),
    (1.1450, 103.7300),   # south of Raffles Lighthouse
    (1.1800, 103.6500),
    (1.2300, 103.6000),
]


def haversine_distance(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """
    Great-circle distance between two GPS coordinates, in metres.

    The Haversine formula treats Earth as a sphere, which is accurate to
    roughly 0.5% - far better than the precision of a phone's GPS fix.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_METERS * math.asin(math.sqrt(a))


def coordinates_valid(lat: Optional[float], lon: Optional[float]) -> bool:
    """Latitude must be within +/-90 and longitude within +/-180."""
    if lat is None or lon is None:
        return False
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def in_singapore(lat: float, lon: float) -> bool:
    """Whether a GPS fix falls inside SINGAPORE_BORDER (ray casting)."""
    inside = False
    points = SINGAPORE_BORDER
    for (lat1, lon1), (lat2, lon2) in zip(points, points[1:] + points[:1]):
        if (lat1 > lat) != (lat2 > lat):
            crossing = lon1 + (lat - lat1) * (lon2 - lon1) / (lat2 - lat1)
            if lon < crossing:
                inside = not inside
    return inside


def round_coordinates(
    lat: Optional[float], lon: Optional[float], precision: int = 4
) -> Tuple[Optional[float], Optional[float]]:
    """
    Reduce stored coordinate precision (data minimisation).

    4 decimal places is roughly 11 metres - enough to audit a geofence
    decision, not enough to track someone around a building.
    """
    if lat is None or lon is None:
        return lat, lon
    return round(lat, precision), round(lon, precision)


def travel_speed_kmh(
    distance_meters: float, seconds_elapsed: float
) -> float:
    """Implied travel speed between two check-ins, for impossible-travel checks."""
    if seconds_elapsed <= 0:
        return float("inf")
    return (distance_meters / 1000.0) / (seconds_elapsed / 3600.0)
