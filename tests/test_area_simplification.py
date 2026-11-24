"""Smaller copies of published areas - issue #191, part 8.

A flood's affected area is sent to the caller as ``impact_zone``, and a
client decides who is affected from it. The copy ``simplify_area`` makes in
its place has to keep three promises, and these tests hold it to them on the
recorded GDACS areas and on shapes built to break it:

- everyone in the published area is in the copy;
- the copy reaches no more than the tolerance beyond the area;
- the copy is still a valid area: nothing in it crosses or touches anything
  it did not already, and no ring is swallowed by another.

Coverage is judged the way GeoJSON draws an area, with straight edges in
longitude and latitude, rather than with ``geometry.distance_to_area_km``,
which treats edges as great-circle arcs and so disagrees by up to a few
metres along the long edges of a copy.
"""
import functools
import json
import math
from pathlib import Path

import pytest

from services import area_simplification as simplification
from services.area_simplification import TOLERANCE_KM, simplify_area, with_zone
from services.geometry import distance_to_area_km, polygons_of

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "fixtures" / "gdacs"
INDIA = "affected_area_FL_1104121_22.json"
AREAS = [
    "affected_area_FL_1104081_20.json",
    INDIA,
    "burned_area_WF_1023255_13.json",
    "burned_area_WF_1023277_5.json",
    "burned_area_WF_1029628_32.json",
]
KM_PER_DEGREE = simplification.KM_PER_DEGREE


def _recorded(name):
    """The area as the adapters read it: polygons of the published class,
    positions cut to longitude and latitude, and only the outline of a fire."""
    features = json.loads((FIXTURES / name).read_text(encoding="utf-8-sig"))["features"]
    polygons = []
    for feature in features:
        if feature["properties"].get("Class") not in ("Poly_Affected", "Poly_area"):
            continue
        geometry = feature["geometry"]
        for polygon in [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]:
            rings = [[[p[0], p[1]] for p in ring] for ring in polygon]
            polygons.append(rings[:1] if name.startswith("burned") else rings)
    return {"type": "MultiPolygon", "coordinates": polygons}


@functools.cache
def _recorded_and_zone(name):
    """A recorded area and its copy, made once for every test that only reads
    them. Simplifying the India area takes about half a second, and several
    times that under coverage."""
    area = _recorded(name)
    return area, simplify_area(area, TOLERANCE_KM)


def _square(west, south, east, north, clockwise=False):
    ring = [[west, south], [east, south], [east, north], [west, north], [west, south]]
    return ring[::-1] if clockwise else ring


def _positions(area):
    return sum(len(ring) for polygon in polygons_of(area) for ring in polygon)


class _Covering:
    """Whether points are in an area, edges straight in degrees, holes outside.

    A point within 1 cm of an edge counts as in: a position of the published
    area that is also on the copy's edge is covered, whichever way rounding
    tips it.
    """

    CELL = 0.01

    def __init__(self, area):
        self.polygons = []
        for polygon in polygons_of(area):
            rings = []
            for ring in polygon:
                edges = list(zip(ring, ring[1:]))
                rows, cells = {}, {}
                for e, (a, b) in enumerate(edges):
                    for row in range(self._at(min(a[1], b[1])), self._at(max(a[1], b[1])) + 1):
                        rows.setdefault(row, []).append(e)
                        for column in range(self._at(min(a[0], b[0])), self._at(max(a[0], b[0])) + 1):
                            cells.setdefault((column, row), []).append(e)
                rings.append((edges, rows, cells))
            self.polygons.append(rings)

    def _at(self, degrees):
        return math.floor(degrees / self.CELL)

    def covers(self, point):
        x, y = point
        column, row = self._at(x), self._at(y)
        scale = math.cos(math.radians(y)) * KM_PER_DEGREE
        for rings in self.polygons:
            for edges, _, cells in rings:
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        for e in cells.get((column + dx, row + dy), ()):
                            (x1, y1), (x2, y2) = edges[e]
                            if _segment_km(x, y, x1, y1, x2, y2, scale) < 1e-5:
                                return True
            inside = []
            for edges, rows, _ in rings:
                crossings = False
                for e in rows.get(row, ()):
                    (x1, y1), (x2, y2) = edges[e]
                    if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                        crossings = not crossings
                inside.append(crossings)
            if inside[0] and not any(inside[1:]):
                return True
        return False


def _segment_km(x, y, x1, y1, x2, y2, scale):
    ax, ay = (x1 - x) * scale, (y1 - y) * KM_PER_DEGREE
    bx, by = (x2 - x) * scale, (y2 - y) * KM_PER_DEGREE
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / length2))
    return math.hypot(ax + t * dx, ay + t * dy)


def _uncovered(area, zone):
    """Positions and edge midpoints of the area that the zone leaves out."""
    covering = _Covering(zone)
    points = []
    for polygon in polygons_of(area):
        for ring in polygon:
            points += [tuple(p) for p in ring]
            points += [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in zip(ring, ring[1:])]
    return [p for p in points if not covering.covers(p)]


def _edges(area):
    for polygon in polygons_of(area):
        for ring in polygon:
            for a, b in zip(ring, ring[1:]):
                yield tuple(a), tuple(b)


def _new_meetings(area, zone):
    """Pairs of the zone's edges that meet other than end to end, and did not
    already meet in the area itself."""
    published = set(_edges(area))
    edges = list(_edges(zone))
    ends = {}
    for a, b in edges:
        ends.setdefault(a, set()).add((a, b))
        ends.setdefault(b, set()).add((a, b))
    grid = {}
    for e, (a, b) in enumerate(edges):
        for column in range(math.floor(min(a[0], b[0]) / 0.05), math.floor(max(a[0], b[0]) / 0.05) + 1):
            for row in range(math.floor(min(a[1], b[1]) / 0.05), math.floor(max(a[1], b[1]) / 0.05) + 1):
                grid.setdefault((column, row), []).append(e)
    found = set()
    for members in grid.values():
        for x, i in enumerate(members):
            for j in members[x + 1:]:
                first, second = edges[i], edges[j]
                if first in published and second in published:
                    continue
                if set(first) & set(second):
                    # End to end: a problem only if one folds back along the other.
                    corner = (set(first) & set(second)).pop()
                    mine = first[1] if first[0] == corner else first[0]
                    theirs = second[1] if second[0] == corner else second[0]
                    if simplification._overlap_beyond(corner, mine, theirs):
                        found.add((i, j))
                    continue
                if simplification._segments_meet(*first, *second):
                    found.add((i, j))
    return found


# -------------------------------------------------------------------------
# The three promises, on every recorded area
# -------------------------------------------------------------------------

@pytest.mark.parametrize("name", AREAS)
def test_everyone_in_a_recorded_area_is_in_its_zone(name):
    area, zone = _recorded_and_zone(name)
    assert _uncovered(area, zone) == []


@pytest.mark.parametrize("name", AREAS)
def test_a_zone_reaches_no_more_than_the_tolerance_beyond_its_area(name):
    """Its own positions, and points along its edges.

    Every position the copy adds is checked, and the middle of every edge,
    on a small area. The India area is checked at one in 40 of each, still
    about 150 points, to keep the test fast. The 1 m allowance is the
    curvature distance_to_area_km gives each edge.
    """
    area, zone = _recorded_and_zone(name)
    published = {tuple(p) for polygon in polygons_of(area) for ring in polygon for p in ring}
    added = [p for polygon in polygons_of(zone) for ring in polygon for p in ring if tuple(p) not in published]
    edges = list(_edges(zone))
    sampled = edges[::40] if name == INDIA else edges
    added = added[::40] if name == INDIA else added
    points = added + [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in sampled]
    farthest = max(distance_to_area_km(lat, lon, area) for lon, lat in points)
    assert farthest <= TOLERANCE_KM + 0.001


@pytest.mark.parametrize("name", AREAS)
def test_a_zone_meets_itself_nowhere_its_area_did_not(name):
    area, zone = _recorded_and_zone(name)
    assert _new_meetings(area, zone) == set()


def test_the_india_flood_zone_is_a_third_of_the_size():
    area, zone = _recorded_and_zone(INDIA)
    assert _positions(area) == 11568
    assert _positions(zone) == 3677
    assert len(json.dumps(zone)) < len(json.dumps(area)) / 3


@pytest.mark.parametrize("name", AREAS)
def test_a_zone_keeps_every_polygon_ring_and_direction(name):
    area, zone = _recorded_and_zone(name)
    assert [len(p) for p in polygons_of(zone)] == [len(p) for p in polygons_of(area)]
    for original, copy in zip(polygons_of(area), polygons_of(zone)):
        for ring, simplified in zip(original, copy):
            assert simplified[0] == simplified[-1]
            assert len(simplified) >= 4
            assert (_signed(ring) > 0) == (_signed(simplified) > 0)


def _signed(ring):
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:]))


# -------------------------------------------------------------------------
# Shapes built to break it
# -------------------------------------------------------------------------

def _circle(longitude, latitude, radius_km, points=96, clockwise=False):
    ring = []
    for k in range(points):
        angle = 2 * math.pi * k / points * (-1 if clockwise else 1)
        ring.append([
            round(longitude + radius_km * math.cos(angle) / (KM_PER_DEGREE * math.cos(math.radians(latitude))), 6),
            round(latitude + radius_km * math.sin(angle) / KM_PER_DEGREE, 6),
        ])
    return ring + [ring[0]]


@pytest.mark.parametrize("clockwise", [False, True])
def test_a_round_outline_is_covered_from_outside_whichever_way_it_is_drawn(clockwise):
    """A convex outline can only be shortened by corners outside it."""
    area = {"type": "Polygon", "coordinates": [_circle(10, 45, 20, clockwise=clockwise)]}
    zone = simplify_area(area, 1.0)
    assert _positions(zone) < _positions(area) / 2
    assert _uncovered(area, zone) == []
    assert max(distance_to_area_km(lat, lon, area) for lon, lat in zone["coordinates"][0][0]) <= 1.0


@pytest.mark.parametrize("clockwise", [False, True])
def test_a_hole_only_ever_shrinks(clockwise):
    """Dry ground in a flood is outside it. The copy may take some of it in,
    never put flooded ground into the hole."""
    hole = _circle(10, 45, 5, clockwise=not clockwise)
    outline = _square(9.5, 44.7, 10.5, 45.3, clockwise=clockwise)
    area = {"type": "Polygon", "coordinates": [outline, hole]}
    zone = simplify_area(area, 1.0)
    (simplified_outline, simplified_hole), = zone["coordinates"]
    assert len(simplified_hole) < len(hole)
    assert _uncovered(area, zone) == []
    # The copy of the hole lies inside the hole.
    assert all(distance_to_area_km(lat, lon, {"type": "Polygon", "coordinates": [hole]}) == 0
               for lon, lat in simplified_hole)


# A square about 11 km a side, so that closing the bay needs no edge longer
# than the zone may add, with a bay 450 m wide and 1.3 km deep in its north side.
BAY = [[0, 0], [0.1, 0], [0.1, 0.1], [0.052, 0.1], [0.052, 0.088], [0.048, 0.088], [0.048, 0.1], [0, 0.1], [0, 0]]


def test_a_bay_with_an_island_in_it_is_not_closed_over_the_island():
    """The bay is 450 m wide and 1.3 km deep, shallow enough at a 2 km
    tolerance for its mouth to be closed, if not for the island. Closing it
    would put the island inside the outline, and the even-odd rule would then
    read the island as a hole."""
    bay = BAY
    island = _square(0.0498, 0.0935, 0.0502, 0.0939)
    area = {"type": "MultiPolygon", "coordinates": [[bay], [island]]}
    zone = simplify_area(area, 2.0)
    assert _uncovered(area, zone) == []
    ((outline,), _) = zone["coordinates"]
    assert not simplification._point_in_ring(tuple(island[0]), [tuple(p) for p in outline[:-1]])


def test_the_same_bay_with_no_island_is_closed():
    """So the test above is about the island, not about a bay too deep to close."""
    bay = BAY
    zone = simplify_area({"type": "Polygon", "coordinates": [bay]}, 2.0)
    assert [0.052, 0.088] not in zone["coordinates"][0][0]


def test_two_rings_side_by_side_are_not_drawn_across_each_other():
    """Two jagged strips 200 m apart, each with bulges that a 1 km tolerance
    would otherwise push into the other."""
    def strip(south, north):
        top = [[x / 100, north + (0.001 if x % 2 else 0)] for x in range(0, 101)]
        return [[0, south], [1, south]] + top[::-1] + [[0, south]]
    area = {"type": "MultiPolygon", "coordinates": [[strip(0, 0.1)], [strip(0.1018, 0.2)]]}
    zone = simplify_area(area, 1.0)
    assert _uncovered(area, zone) == []
    assert _new_meetings(area, zone) == set()


def test_a_ring_of_three_corners_is_kept_as_it_is():
    triangle = [[0, 0], [0.01, 0], [0, 0.01], [0, 0]]
    assert simplify_area({"type": "Polygon", "coordinates": [triangle]}, 1.0)["coordinates"] == [[triangle]]


@pytest.mark.parametrize("ring", [
    # No area: out along a line and back again.
    [[0, 0], [0.001, 0], [0.002, 0], [0.003, 0], [0.002, 0], [0.001, 0], [0, 0]],
    # A figure of eight, its two loops drawn in opposite directions.
    [[0, 0], [0.01, 0.01], [0.02, 0], [0.02, 0.01], [0.01, 0], [0, 0.01], [0, 0]],
    # Pinched at a repeated position into two loops of the same size, drawn
    # in opposite directions.
    [[0, 0], [0.01, 0], [0.01, 0.01], [0.01, 0.02], [0.02, 0.02], [0.02, 0.01], [0.01, 0.01],
     [0, 0.01], [0, 0]],
], ids=["no area", "crosses itself", "pinched both ways"])
def test_a_ring_whose_direction_cannot_say_where_the_area_is_is_kept_as_it_is(ring):
    """Too small to have anything worth removing once its loops are kept."""
    area = {"type": "Polygon", "coordinates": [ring]}
    assert simplify_area(area, 5.0)["coordinates"] == [[ring]]


def test_a_ring_pinched_into_loops_that_agree_is_still_simplified():
    lobe = _circle(10, 45, 5, points=48)[:-1]
    other = _circle(10 + 10 / (KM_PER_DEGREE * math.cos(math.radians(45))), 45, 5, points=48)[:-1]
    # Both loops counterclockwise, joined at the east point of the first and
    # the west point of the second, moved onto it.
    other[24] = lobe[0]
    ring = lobe + other[24:] + other[:24] + [lobe[0], lobe[0]]
    ring = ring[:-1]
    area = {"type": "Polygon", "coordinates": [ring]}
    zone = simplify_area(area, 1.0)
    assert _positions(zone) < _positions(area)
    assert _uncovered(area, zone) == []


def _wavy_square(west, south, east, north, waves=40):
    """A square whose sides zigzag 50 m in and out, so there is plenty to remove."""
    ring = []
    corners = [(west, south), (east, south), (east, north), (west, north)]
    for (x1, y1), (x2, y2) in zip(corners, corners[1:] + corners[:1]):
        for k in range(waves):
            t = k / waves
            nudge = 0.0005 if k % 2 else 0.0
            ring.append([round(x1 + t * (x2 - x1) + nudge, 6), round(y1 + t * (y2 - y1) + nudge, 6)])
    return ring + [ring[0]]


# Two holes from a live GDACS flood in Mozambique, November 2026: slivers
# that run out and back over the same positions. The first version of this
# module read them the wrong way round and made them larger, leaving flooded
# ground outside the zone. They are now kept as they are.
SLIVERS = [
    [[31.2439, -22.364], [31.2446, -22.3639], [31.2473, -22.3633], [31.2477, -22.3631], [31.2484, -22.3629],
     [31.2473, -22.3633], [31.2439, -22.364]],
    [[31.2002, -22.3597], [31.1991, -22.3579], [31.1983, -22.3573], [31.1988, -22.3577], [31.1991, -22.3579],
     [31.2, -22.3593], [31.2002, -22.3597]],
]


def test_a_hole_that_runs_out_and_back_is_not_made_larger():
    area = {"type": "Polygon", "coordinates": [_wavy_square(31.15, -22.4, 31.3, -22.32)] + SLIVERS}
    zone = simplify_area(area, TOLERANCE_KM)
    assert _positions(zone) < _positions(area)
    assert _uncovered(area, zone) == []
    assert zone["coordinates"][0][1:] == SLIVERS


def test_a_ring_with_a_small_loop_in_it_is_simplified_around_the_loop():
    """A twist of a few tens of metres, as in the recorded India area: the
    twist is kept, and the rest of the ring is simplified."""
    ring = _wavy_square(0, 0, 0.1, 0.1)[:-1]
    assert ring[8] == [0.02, 0.0]
    # After the position at 0.02, 0 on the south side: up to the right, down,
    # then up to the left, so the first and third edges cross.
    twist = [[0.0205, 0.0003], [0.0205, 0.0], [0.0201, 0.0003]]
    ring = ring[:9] + twist + ring[9:] + [ring[0]]
    area = {"type": "Polygon", "coordinates": [ring]}
    zone = simplify_area(area, TOLERANCE_KM)
    assert _positions(zone) < _positions(area) / 2
    assert _uncovered(area, zone) == []
    kept = [list(p) for p in zone["coordinates"][0][0]]
    assert all(position in kept for position in twist)


def _side(start, end, steps):
    return [[round(start[0] + (end[0] - start[0]) * k / steps, 6), round(start[1] + (end[1] - start[1]) * k / steps, 6)]
            for k in range(steps)]


def test_a_ring_pinched_into_two_large_loops_running_opposite_ways_is_kept_whole():
    """Too large a loop to keep apart from the rest, so the whole ring is kept."""
    east = _circle(10.1, 45, 5, points=60)[:-1]
    west = _circle(10, 45, 5, points=60, clockwise=True)[:-1]
    # Both loops pass through the same position, where they meet.
    west = west[30:] + west[:30]
    west[0] = east[0] = [10.05, 45.0]
    ring = east + west + [east[0]]
    area = {"type": "Polygon", "coordinates": [ring]}
    assert simplify_area(area, 1.0)["coordinates"] == [[ring]]


def test_a_ring_that_crosses_itself_between_large_loops_is_kept_whole():
    """A bow tie with 30 positions to a side: its two halves run opposite ways."""
    ring = (
        _side([0, 0], [0.1, 0.1], 30) + _side([0.1, 0.1], [0.1, 0], 30)
        + _side([0.1, 0], [0, 0.1], 30) + _side([0, 0.1], [0, 0], 30) + [[0, 0]]
    )
    area = {"type": "Polygon", "coordinates": [ring]}
    assert simplify_area(area, 5.0)["coordinates"] == [[ring]]


def test_a_figure_eight_with_no_area_is_kept_whole_however_small_its_loops():
    """Its two loops are mirror images running opposite ways, so it has no
    area and no direction to say which side is inside, even though each
    loop is small enough to keep on its own and has positions in line.
    Positions are in 64ths of a degree, so its area adds up to exactly 0."""
    right = [[x / 64, y / 64] for x, y in [[1, -1], [1.5, -1], [2, -1], [3, -1], [3, 1], [2, 1], [1.5, 1], [1, 1]]]
    left = [[-x, y] for x, y in right]
    ring = [[0, 0]] + right + [[0, 0]] + left + [[0, 0]]
    area = {"type": "Polygon", "coordinates": [ring]}
    assert simplify_area(area, 50.0)["coordinates"] == [[ring]]


def test_no_edge_the_zone_adds_is_longer_than_the_limit():
    """A square on the equator about 111 km a side, with a position every
    1.1 km exactly on its straight sides. With no limit each side would be
    drawn as one edge of 111 km; with one, it is drawn in edges of 20 km or
    less, and still covers the square."""
    steps = 100
    side = [k / steps for k in range(steps)]
    ring = (
        [[x, 0] for x in side] + [[1, y] for y in side]
        + [[1 - x, 1] for x in side] + [[0, 1 - y] for y in side] + [[0, 0]]
    )
    area = {"type": "Polygon", "coordinates": [ring]}
    zone = simplify_area(area, TOLERANCE_KM)
    copy = zone["coordinates"][0][0]
    lengths = [math.hypot(b[0] - a[0], b[1] - a[1]) * KM_PER_DEGREE for a, b in zip(copy, copy[1:])]
    assert max(lengths) <= simplification._MAX_EDGE_KM
    assert max(lengths) > simplification._MAX_EDGE_KM / 2
    assert _positions(zone) < _positions(area) / 5
    assert _uncovered(area, zone) == []


def test_a_spike_across_the_first_position_is_kept():
    """The ring runs out to a point and back just before it closes, so the
    loop to keep wraps round past its first position."""
    square = _wavy_square(0, 0, 0.1, 0.1)[:-1]
    spike = [0.0, -0.0003]
    ring = square + [square[0], spike] + [square[0]]
    area = {"type": "Polygon", "coordinates": [ring]}
    zone = simplify_area(area, TOLERANCE_KM)
    assert _positions(zone) < _positions(area) / 2
    assert _uncovered(area, zone) == []
    assert spike in zone["coordinates"][0][0]


def test_a_hole_drawn_along_its_outline_is_kept_as_it_is():
    """With every position on the outline, it cannot be told to be inside."""
    outline = _square(0, 0, 1, 1)
    hole = outline[::-1]
    zone = simplify_area({"type": "Polygon", "coordinates": [outline, hole]}, 1.0)
    assert zone["coordinates"][0][1] == hole


def test_a_hole_outside_its_outline_is_kept_as_it_is():
    outline = _square(0, 0, 1, 1)
    stray = _circle(5, 0.5, 5, clockwise=True)
    zone = simplify_area({"type": "Polygon", "coordinates": [outline, stray]}, 1.0)
    assert zone["coordinates"][0][1] == stray


def test_an_area_across_the_antimeridian_is_left_as_published():
    ring = [[179.9, 0], [-179.9, 0], [-179.9, 0.1], [179.9, 0.1], [179.9, 0]]
    zone = simplify_area({"type": "Polygon", "coordinates": [ring]}, 1.0)
    assert zone == {"type": "MultiPolygon", "coordinates": [[ring]]}


def test_a_corner_that_rounding_would_pull_inside_is_never_used(monkeypatch):
    """Corners are written to 5 decimal places, after being moved 2 m farther
    out to allow for it. With no allowance, rounding pulls some of them back
    across the stretch they replace; those are checked again, in degrees, and
    left out, so the zone still covers the whole area."""
    monkeypatch.setattr(simplification, "_ROUNDING_KM", 0.0)
    area = _recorded(INDIA)
    assert _uncovered(area, simplify_area(area, TOLERANCE_KM)) == []


def test_a_zone_is_valid_json_with_finite_numbers():
    zone = simplify_area(_recorded(INDIA), TOLERANCE_KM)
    json.dumps(zone, allow_nan=False)


# -------------------------------------------------------------------------
# with_zone, which the adapters call
# -------------------------------------------------------------------------

def test_with_zone_returns_the_area_and_its_copy():
    area = _recorded("burned_area_WF_1023255_13.json")
    published, zone = with_zone(area)
    assert published is area
    assert zone == simplify_area(area, TOLERANCE_KM)


def test_a_failure_to_simplify_sends_the_area_as_published(monkeypatch, capsys):
    """Simplifying only makes the answer smaller. A bug in it must not cost a
    detection, so the adapter gets no zone and the area is sent instead."""
    def broken(area, tolerance_km):
        raise IndexError("a bug")

    monkeypatch.setattr(simplification, "simplify_area", broken)
    area = _recorded("burned_area_WF_1023255_13.json")
    assert with_zone(area) == (area, None)
    assert "area not simplified" in capsys.readouterr().out
