"""Geometry on the globe for disaster_check and its feed adapters - issue #191.

Kept apart from services/disaster_check.py because the adapters need it too,
and disaster_check imports the adapters.

Areas are GeoJSON Polygons or MultiPolygons, positions [longitude, latitude].
"""
import math

EARTH_RADIUS_KM = 6371.0088
_CIRCLE_POINTS = 32


def distance_km(lat1, lon1, lat2, lon2):
    """Great-circle distance between two points (haversine)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    half_dphi = (phi2 - phi1) / 2
    half_dlambda = math.radians(lon2 - lon1) / 2
    a = math.sin(half_dphi) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(half_dlambda) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def circle_polygon(latitude, longitude, radius_km):
    """A circle on the globe as a GeoJSON Polygon.

    The ring is counterclockwise, as RFC 7946 asks of an exterior ring.
    Longitudes are deliberately left unwrapped: a zone that crosses the
    antimeridian has vertices past +/-180 rather than a ring that jumps to the
    far side of the map. ``impact_zone_fallback`` is the exact form.
    """
    phi1 = math.radians(latitude)
    lambda1 = math.radians(longitude)
    # The vertices sit just outside the circle so that the edges touch it. A
    # ring through points on the circle would cut inside it between them and
    # leave out people the radius includes.
    delta = radius_km / EARTH_RADIUS_KM / math.cos(math.pi / _CIRCLE_POINTS)

    ring = []
    for i in range(_CIRCLE_POINTS):
        bearing = -2 * math.pi * i / _CIRCLE_POINTS
        # Clamped because a vertex landing on a pole can come out one rounding
        # step past 1, which asin refuses.
        phi2 = math.asin(max(-1.0, min(1.0, (
            math.sin(phi1) * math.cos(delta)
            + math.cos(phi1) * math.sin(delta) * math.cos(bearing)
        ))))
        lambda2 = lambda1 + math.atan2(
            math.sin(bearing) * math.sin(delta) * math.cos(phi1),
            math.cos(delta) - math.sin(phi1) * math.sin(phi2),
        )
        ring.append([round(math.degrees(lambda2), 4), round(math.degrees(phi2), 4)])
    ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [ring]}


def polygons_of(area):
    """The polygons of an area, each a list of rings: the outline, then holes."""
    if area["type"] == "Polygon":
        return [area["coordinates"]]
    if area["type"] == "MultiPolygon":
        return area["coordinates"]
    raise ValueError(f"{area['type']!r} is not an area")


def farthest_km(latitude, longitude, area):
    """How far the farthest vertex of an area lies from a point."""
    return max(
        distance_km(latitude, longitude, vertex_latitude, vertex_longitude)
        for polygon in polygons_of(area)
        for ring in polygon
        for vertex_longitude, vertex_latitude, *_ in ring
    )


def distance_to_area_km(latitude, longitude, area):
    """Distance from a point to an area, or 0 when the point is inside it.

    Each vertex is placed at its true distance and bearing from the point (an
    azimuthal equidistant projection centred on it). Distances to vertices are
    then exact, the antimeridian needs no special case, and the only error is
    the curvature of a single edge. A point inside a hole is outside the area:
    someone on dry ground in the middle of a flood is not in the flood.

    Edges are treated as great-circle arcs. GeoJSON draws them as straight
    lines in longitude and latitude instead. For the dense rings GDACS
    publishes, with edges of a few kilometres, the difference is under a
    metre; for a ring with edges hundreds of kilometres long it would not be.
    """
    nearest = math.inf
    for polygon in polygons_of(area):
        inside = False
        for ring in polygon:
            points = [_project(latitude, longitude, lat, lon) for lon, lat, *_ in ring]
            # The closing edge is included whether or not the ring repeats its
            # first position, as GeoJSON says it should.
            for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
                # Even-odd rule: count the edges a ray east from the point crosses.
                if (y1 > 0) != (y2 > 0) and x1 - y1 * (x2 - x1) / (y2 - y1) > 0:
                    inside = not inside
                nearest = min(nearest, _distance_to_segment(x1, y1, x2, y2))
        if inside:
            return 0.0
    return nearest


def _project(lat0, lon0, lat, lon):
    """(east, north) in km of a point, from a centre, at its true distance and bearing."""
    distance = distance_km(lat0, lon0, lat, lon)
    phi0, phi = math.radians(lat0), math.radians(lat)
    dlambda = math.radians(lon - lon0)
    bearing = math.atan2(
        math.sin(dlambda) * math.cos(phi),
        math.cos(phi0) * math.sin(phi) - math.sin(phi0) * math.cos(phi) * math.cos(dlambda),
    )
    return distance * math.sin(bearing), distance * math.cos(bearing)


def _distance_to_segment(x1, y1, x2, y2):
    """Distance from the origin to the segment between two points."""
    dx, dy = x2 - x1, y2 - y1
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, -(x1 * dx + y1 * dy) / length2))
    return math.hypot(x1 + t * dx, y1 + t * dy)
