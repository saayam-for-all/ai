"""Distances to published areas - issue #191, part 2.

``distance_to_area_km`` decides whether someone is in a flood: 0 inside the
area GDACS publishes, otherwise the distance to its nearest edge, which is
then compared with the caller's radius. These tests pin it against simple
shapes whose answers are known, and against the recorded India flood.
"""
import json
from pathlib import Path

import pytest

from services import geometry as geo

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "fixtures" / "gdacs"

ONE_DEGREE_KM = 111.195  # of latitude, or of longitude at the equator

# One degree either side of 0, 0, with a hole of a quarter degree either side.
SQUARE = [[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]
HOLE = [[-0.25, -0.25], [-0.25, 0.25], [0.25, 0.25], [0.25, -0.25], [-0.25, -0.25]]
SQUARE_WITH_HOLE = {"type": "Polygon", "coordinates": [SQUARE, HOLE]}


def _box(west, south, east, north):
    return [[west, south], [east, south], [east, north], [west, north], [west, south]]


def test_a_point_inside_an_area_is_at_distance_zero():
    assert geo.distance_to_area_km(0.5, 0.5, SQUARE_WITH_HOLE) == 0


def test_a_point_outside_is_at_the_distance_of_the_nearest_edge():
    assert geo.distance_to_area_km(0, 2, SQUARE_WITH_HOLE) == pytest.approx(ONE_DEGREE_KM, rel=0.001)


def test_a_point_beyond_a_corner_is_measured_to_the_corner():
    expected = geo.distance_km(2, 2, 1, 1)
    assert geo.distance_to_area_km(2, 2, SQUARE_WITH_HOLE) == pytest.approx(expected, rel=0.001)


def test_a_point_in_a_hole_is_outside_and_measured_to_the_hole_edge():
    """Dry ground in the middle of a flood is not in the flood."""
    distance = geo.distance_to_area_km(0, 0, SQUARE_WITH_HOLE)
    assert distance == pytest.approx(0.25 * ONE_DEGREE_KM, rel=0.002)


def test_a_multipolygon_is_measured_to_its_nearest_part():
    area = {"type": "MultiPolygon", "coordinates": [[_box(10, 10, 11, 11)], [_box(2, 0, 3, 1)]]}
    assert geo.distance_to_area_km(0.5, 0, area) == pytest.approx(2 * ONE_DEGREE_KM, rel=0.002)
    assert geo.distance_to_area_km(0.5, 2.5, area) == 0


def test_a_ring_that_does_not_repeat_its_first_position_is_still_closed():
    open_ring = {"type": "Polygon", "coordinates": [SQUARE[:-1]]}
    assert geo.distance_to_area_km(0, 0, open_ring) == 0
    assert geo.distance_to_area_km(-1.5, 0, open_ring) == pytest.approx(0.5 * ONE_DEGREE_KM, rel=0.002)


def test_an_area_across_the_antimeridian_is_measured_the_short_way():
    """Fiji's floods sit on the line: 179.9 and -179.9 are 22 km apart."""
    area = {"type": "Polygon", "coordinates": [_box(179.5, -18.2, 180.0, -17.8)]}
    distance = geo.distance_to_area_km(-18.0, -179.9, area)
    assert distance == pytest.approx(geo.distance_km(-18.0, -179.9, -18.0, 180.0), rel=0.01)
    assert distance < 15


def test_positions_with_an_altitude_are_accepted():
    area = {"type": "Polygon", "coordinates": [[[x, y, 0.0] for x, y in SQUARE]]}
    assert geo.distance_to_area_km(0, 0, area) == 0
    assert geo.farthest_km(0, 0, area) == pytest.approx(geo.distance_km(0, 0, 1, 1))


def test_the_farthest_vertex_sets_the_covering_radius():
    assert geo.farthest_km(0, 0, SQUARE_WITH_HOLE) == pytest.approx(geo.distance_km(0, 0, 1, 1))


def test_anything_but_a_polygon_is_not_an_area():
    with pytest.raises(ValueError):
        geo.polygons_of({"type": "Point", "coordinates": [0, 0]})


def test_the_recorded_flood_agrees_with_measuring_every_vertex():
    """Against 11,568 real vertices: the edge distance can only be shorter
    than the nearest vertex, and with vertices this dense, barely."""
    document = json.loads((FIXTURES / "affected_area_FL_1104121_22.json").read_text(encoding="utf-8"))
    area = next(f for f in document["features"] if f["properties"]["Class"] == "Poly_Affected")["geometry"]
    bengaluru = (12.9716, 77.5946)

    nearest_vertex = min(
        geo.distance_km(*bengaluru, lat, lon)
        for polygon in geo.polygons_of(area) for ring in polygon for lon, lat in ring
    )
    distance = geo.distance_to_area_km(*bengaluru, area)
    assert nearest_vertex - 1.0 <= distance <= nearest_vertex
    assert distance == pytest.approx(25.8, abs=0.1)
