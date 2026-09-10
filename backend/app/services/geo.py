"""Geospatial helpers for geofence validation."""

import math
from typing import Optional, Tuple

EARTH_RADIUS_METERS = 6_371_000.0


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
