"""Smaller copies of published areas for disaster_check - issue #191, part 8.

A flood's affected area, as GDACS publishes it, is 200 to 350 KB of JSON.
``simplify_area`` returns a copy with far fewer positions that a client can
use in its place to decide who is affected:

- **It covers the whole published area.** Nobody inside the published area
  is outside the copy.
- **It reaches at most ``tolerance_km`` beyond the area.** Ground the copy
  adds is never farther than that from the published area.
- **It is still a valid area.** A change that would make a ring cross or
  touch any other edge, or swallow another ring, is not made, so a client
  reading it with the even-odd rule reads it the way it is meant.

Each ring keeps its direction and its place in its polygon.

How: each ring is simplified the way Douglas-Peucker simplifies a line, by
replacing a run of positions between two of them, ``a`` and ``b``, with
something shorter. The run has to fit in a band along the line from ``a`` to
``b`` no wider than ``tolerance_km``, between the ends.

- If the whole run lies on the area's side of that line, it is replaced by
  the edge from ``a`` to ``b``.
- If part of it bulges out past the line, the band's outer side is used
  instead: ``a``, a corner just past the bulge level with ``a``, another
  level with ``b``, then ``b``. Those two corners are the only positions in
  the copy that are not GDACS's own.

Either way the run lies on the area's side of what replaces it, so the
ground between the two is added to the area, never taken from it. And that
ground is within ``tolerance_km`` of the area: from any point in it, the line
straight back across the band meets the run before it has crossed the band.
"""
import math

from services.geometry import EARTH_RADIUS_KM, polygons_of

KM_PER_DEGREE = math.pi * EARTH_RADIUS_KM / 180

# How far beyond a published area the zone sent in its place may reach.
# Clients alert from impact_zone, and a false alert is worse than none, so
# the margin is kept small: 0.5 km rather than the 1 km first proposed. At
# 0.5 km the recorded India flood area, 11,568 positions and 202 KB as
# compact JSON, comes out at 3,677 positions and 66 KB (2,706 and 49 KB at
# 1 km). Across 101 live and recorded flood and burned areas, measured in
# November 2026, the copies came to 1.07 MB against 3.26 MB (0.78 MB at
# 1 km). Chosen in the review of #256 - see the README.
TOLERANCE_KM = 0.5

# New corners are written to 5 decimal places, about 1.1 m, and moved this
# much farther out first, so that rounding them cannot bring the outer side
# of a band back across the run it covers.
_ROUNDING_KM = 0.002
_DECIMALS = 5


def with_zone(area):
    """The published area, and the zone to send in its place.

    Simplifying only makes the response smaller, so if it fails, the failure
    is logged and the area is sent as published: the zone is then None.
    """
    try:
        return area, simplify_area(area, TOLERANCE_KM)
    except Exception as e:
        print(f"WARNING: area not simplified, sent as published: {type(e).__name__}: {e}")
        return area, None


def simplify_area(area, tolerance_km):
    """A MultiPolygon covering ``area`` and within ``tolerance_km`` of it.

    ``area`` is a GeoJSON Polygon or MultiPolygon. Some rings, or parts of
    them, are kept exactly as they are, and the rest keeps clear of them:

    - a ring of three corners or fewer, which has nothing to remove;
    - a ring with no area, or a hole that does not lie inside its polygon's
      outline, whose direction does not say which side the area is on;
    - where a ring crosses or touches itself, or passes the same position
      twice, it splits into two loops. Either loop that has no area, as in a
      spike out and back, or runs the opposite way to the ring is kept, and
      so are the two edges that cross. The rest of the ring is still
      simplified; a ring where such a loop has more than ``_MAX_LOOP``
      positions is kept whole.
      Live GDACS flood areas had loops like these in 36 of 332 rings in
      November 2026, none of more than 32 positions, and the main ring of
      the recorded India area has 7, of 2 to 5 positions each.

    Where a ring crosses the antimeridian, the area is returned as a
    MultiPolygon unchanged: that is left for whoever meets one, rather than
    guessed at.
    """
    polygons = polygons_of(area)
    rings = []
    for polygon in polygons:
        outline = None
        for role, ring in enumerate(polygon):
            open_ring = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else list(ring)
            if _crosses_antimeridian(open_ring):
                return {"type": "MultiPolygon", "coordinates": [list(p) for p in polygons]}
            ring = _Ring(open_ring, outline=role == 0)
            if role == 0:
                outline = ring.points
            pinned = _flaws(ring.points)
            ring.frozen = (
                len(ring.points) <= 3
                or pinned is None
                or (role > 0 and not _lies_inside(ring.points, outline))
            )
            ring.pinned = pinned or set()
            rings.append(ring)
    _Simplifier(rings, tolerance_km).run()
    out, at = [], 0
    for polygon in polygons:
        kept = []
        for _ in polygon:
            positions = rings[at].positions()
            at += 1
            kept.append([list(p) for p in positions] + [list(positions[0])])
        out.append(kept)
    return {"type": "MultiPolygon", "coordinates": out}


def _crosses_antimeridian(points):
    return any(abs(b[0] - a[0]) > 180 for a, b in zip(points, points[1:] + points[:1]))


class _Ring:
    def __init__(self, points, outline):
        self.points = [(float(p[0]), float(p[1])) for p in points]
        # The area lies to the left of every edge of a counterclockwise
        # outline and of a clockwise hole. A ring drawn the other way round
        # has it on the right, and side flips every test.
        counterclockwise = _signed_area(self.points) > 0
        self.side = 1 if counterclockwise == outline else -1
        n = len(self.points)
        # After a run is replaced, the kept position i is followed by the
        # corners added[i], if any, and then by the kept position next_kept[i].
        self.next_kept = [(i + 1) % n for i in range(n)]
        self.added = {}

    def path(self, i):
        """The positions from kept position i to the next one, both ends included."""
        return [self.points[i]] + self.added.get(i, []) + [self.points[self.next_kept[i]]]

    def kept(self):
        order, i = [0], self.next_kept[0]
        while i != 0:
            order.append(i)
            i = self.next_kept[i]
        return order

    def positions(self):
        order, i = [], 0
        while True:
            order += [self.points[i]] + self.added.get(i, [])
            i = self.next_kept[i]
            if i == 0:
                return order


# The most positions a loop that has to be kept as it is may have. A ring
# with a larger one is kept whole.
_MAX_LOOP = 50

# The most published positions one band in the second pass may replace. It
# bounds the time spent trying ever longer stretches of a large ring.
_MAX_BAND = 400

# The longest edge the copy may add, in km. GeoJSON draws an edge straight
# in longitude and latitude, but a map in Web Mercator or a distance along
# the globe follows a slightly different line, and the gap grows with the
# square of the edge's length: about 14 m at 60 degrees of latitude for an
# edge of 20 km. Simplified with no limit, a live flood area had an edge of
# 280 km, whose line along the globe ran 112 m inside the area. At 20 km the
# copies of 101 areas come out about 1% larger. Edges of the published area are kept, however long.
_MAX_EDGE_KM = 20.0


def _flaws(points):
    """The positions to keep as they are so that the rest of a ring has one
    direction, or None when the whole ring has to be kept.

    Where a ring passes the same position twice, or crosses or touches
    itself, it splits there into two loops. A loop with no area, or that
    runs against the ring as a whole, is kept as it is, whichever of the two
    it is: in a ring pinched into halves that run opposite ways, it can be
    the longer one.
    """
    n = len(points)
    whole = _signed_area(points)
    if whole == 0:
        return None
    pinned = set()

    def arc(first, last):
        return [(first + k) % n for k in range((last - first) % n + 1)]

    def pin_wrong(inner, outer):
        """Keep each of the two loops that has no area or runs the wrong way.

        A loop is given by the positions to keep, and the positions whose
        direction is measured, which for a crossing leave out the ends of
        the two edges that cross.
        """
        for keep, measure in (inner, outer):
            area = _signed_area([points[k] for k in measure])
            if area == 0 or (area > 0) != (whole > 0):
                if len(keep) > _MAX_LOOP:
                    return False
                pinned.update(keep)
        return True

    seen = {}
    for i, point in enumerate(points):
        if point in seen:
            first = seen[point]
            inner, outer = arc(first, i), arc(i, first)
            if not pin_wrong((inner, inner), (outer, outer)):
                return None
        seen[point] = i
    for i, j in _meetings(points):
        # Edge i runs from position i to i + 1, and edge j from j to j + 1.
        # A loop that is kept is kept with both edges. The two edges are kept
        # even when neither loop is, so the crossing stays where it is: a
        # precaution, as no recorded or live area was found to need it.
        inner = (arc(i, (j + 1) % n), arc((i + 1) % n, j))
        outer = (arc(j, (i + 1) % n), arc((j + 1) % n, i))
        if not pin_wrong(inner, outer):
            return None
        pinned.update((i, (i + 1) % n, j, (j + 1) % n))
    return pinned


def _meetings(points):
    """Pairs of edges of a ring, not one after the other, that meet other than
    end to end at a position the ring passes twice."""
    n = len(points)
    edges = list(zip(points, points[1:] + points[:1]))
    # Cells a few edges across, so each holds a handful of edges.
    cell = 4 * sum(abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in edges) / n or 1.0
    grid = {}
    for i, (a, b) in enumerate(edges):
        for cx in range(math.floor(min(a[0], b[0]) / cell), math.floor(max(a[0], b[0]) / cell) + 1):
            for cy in range(math.floor(min(a[1], b[1]) / cell), math.floor(max(a[1], b[1]) / cell) + 1):
                grid.setdefault((cx, cy), []).append(i)
    found = set()
    for members in grid.values():
        for x, i in enumerate(members):
            for j in members[x + 1:]:
                if (j - i) % n in (1, n - 1) or (min(i, j), max(i, j)) in found:
                    continue
                (a, b), (p, q) = edges[i], edges[j]
                if not _segments_meet(a, b, p, q):
                    continue
                shared = {a, b} & {p, q}
                if len(shared) == 1:
                    corner = shared.pop()
                    mine, theirs = (b if a == corner else a), (q if p == corner else p)
                    if not (_overlap_beyond(corner, mine, theirs) or _overlap_beyond(corner, theirs, mine)):
                        continue
                found.add((min(i, j), max(i, j)))
    return sorted(found)


def _lies_inside(hole, outline):
    """Whether a hole lies inside its outline, judged by its first position not on it."""
    on_outline = set(outline)
    for point in hole:
        if point not in on_outline:
            return _point_in_ring(point, outline)
    return False


def _signed_area(points):
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1])) / 2


def _cross(o, a, b):
    """Positive when b lies to the left of the line from o through a."""
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


class _Simplifier:
    def __init__(self, rings, tolerance_km):
        self.rings = rings
        self.tolerance_km = tolerance_km
        # A grid in degrees, to find the edges and positions near a change.
        # Cells are about twice the tolerance across, the width of the band
        # a change can reach into.
        self.cell = max(2 * tolerance_km / KM_PER_DEGREE, 1e-6)
        self.paths = {}
        self.path_cells = {}
        self.path_grid = {}
        self.vertex_grid = {}
        for r, ring in enumerate(rings):
            for i, point in enumerate(ring.points):
                self._add_path((r, i), ring.path(i))
                self.vertex_grid.setdefault(self._cell_of(point), []).append((r, point, i in ring.pinned))

    def run(self):
        for r, ring in enumerate(self.rings):
            n = len(ring.points)
            if ring.frozen:
                continue
            # First, every run that can go without adding a corner, top down.
            # Three anchors, so that a ring never comes out with fewer than
            # three corners.
            anchors = [0, n // 3, 2 * n // 3]
            stack = [(a, b) for a, b in zip(anchors, anchors[1:] + anchors[:1])]
            while stack:
                i, j = stack.pop()
                plan = self._plan(r, i, j, corners=False)
                if plan[0] == "split":
                    stack += [(plan[1], j), (i, plan[1])]
                elif plan[0] == "replace":
                    self._commit(r, i, j, plan[1])
            # Then the stretches that bulge outward, which only the outer
            # side of a band can cover, where that saves positions.
            self._widen(r)

    def _widen(self, r):
        """Walk the ring once, replacing as long a stretch as will go each time."""
        ring = self.rings[r]
        kept = ring.kept()
        start = 0
        while start < len(kept) - 1:
            best, misses = None, 0
            # Replacing fewer than three positions with two corners saves nothing.
            end = start + 4
            # The ring keeps at least two of its own positions besides the
            # corners, and its first position, where the walk ends.
            while end - start <= len(kept) - 2 and end <= len(kept) and misses < 3:
                i, j = kept[start], kept[end % len(kept)]
                if (j - i) % len(ring.points) > _MAX_BAND:
                    break
                plan = self._plan(r, i, j, corners=True)
                if plan[0] == "replace":
                    best, misses = (end, plan[1]), 0
                else:
                    misses += 1
                end += 1
            if best is None:
                start += 1
                continue
            end, replacement = best
            self._commit(r, kept[start], kept[end % len(kept)], replacement)
            start = end

    def _plan(self, r, i, j, corners):
        """What would replace the run between i and j: ("replace", positions),
        ("split", where to split it), or ("keep",) when there is nothing to do."""
        ring = self.rings[r]
        n = len(ring.points)
        run = [(i + k) % n for k in range(1, (j - i) % n)]
        if not run:
            return ("keep",)
        held = [k for k in run if k in ring.pinned]
        if held:
            return ("split", held[0])
        a, b = ring.points[i], ring.points[j]
        frame = _Frame(a, b, ring.side)
        if frame.length == 0 or frame.length > _MAX_EDGE_KM:
            return ("split", run[len(run) // 2])
        # Where each run position lies along the line (along) and how far out
        # from it, away from the area (out, negative on the area's side).
        along_out = [frame.place(ring.points[k]) for k in run]
        if any(t < 0 or t > frame.length for t, _ in along_out):
            # Split in the middle: splitting where it fails can take one
            # position off at a time, and a long ring would take minutes.
            return ("split", run[len(run) // 2])
        outs = [s for _, s in along_out]
        bulge, depth = max(0.0, max(outs)), max(0.0, -min(outs))
        # Exactly, in degrees: is every position on the area's side of the edge?
        if bulge == 0 and any(ring.side * _cross(a, b, ring.points[k]) < 0 for k in run):
            bulge = 1e-9
        if bulge > 0 and not corners:
            return ("split", max(zip(run, outs), key=lambda found: found[1])[0])
        width = depth + (bulge + _ROUNDING_KM if bulge > 0 else 0)
        if width > self.tolerance_km:
            return ("split", max(zip(run, outs), key=lambda found: abs(found[1]))[0])
        added = []
        if bulge > 0:
            added = [frame.corner(0, bulge + _ROUNDING_KM), frame.corner(frame.length, bulge + _ROUNDING_KM)]
            if not self._covers(ring, a, added, b, run):
                return ("split", run[len(run) // 2])
        replacement = [a] + added + [b]
        if not self._clear(r, i, j, run, replacement):
            return ("split", run[len(run) // 2])
        return ("replace", replacement)

    def _commit(self, r, i, j, replacement):
        ring = self.rings[r]
        k = i
        while k != j:
            following = ring.next_kept[k]
            self._remove_path((r, k))
            ring.added.pop(k, None)
            k = following
        ring.next_kept[i] = j
        corners = replacement[1:-1]
        if corners:
            ring.added[i] = corners
            for corner in corners:
                self.vertex_grid.setdefault(self._cell_of(corner), []).append((r, corner, False))
        self._add_path((r, i), replacement)

    @staticmethod
    def _covers(ring, a, corners, b, run):
        """Whether every run position is on the area's side of all three new edges.

        Checked in degrees with the rounded corners, rather than trusted to
        the band they were placed by.
        """
        path = [a] + corners + [b]
        return all(
            ring.side * _cross(p, q, ring.points[k]) >= 0
            for p, q in zip(path, path[1:])
            for k in run
        )

    def _clear(self, r, i, j, run, replacement):
        """Whether the replacement meets nothing but its own neighbours, at its
        ends, and the ground it adds holds no other ring."""
        ring = self.rings[r]
        own = {(r, k) for k in [i] + run if (r, k) in self.paths}
        before = (r, self._before(r, i))
        after = (r, j)
        new_edges = list(zip(replacement, replacement[1:]))
        xs = [p[0] for p in replacement]
        ys = [p[1] for p in replacement]
        for key in self._paths_in(min(xs), min(ys), max(xs), max(ys)):
            if key in own:
                continue
            old_edges = list(zip(self.paths[key], self.paths[key][1:]))
            for e, (p, q) in enumerate(new_edges):
                for o, (u, v) in enumerate(old_edges):
                    # The one meeting allowed: where the replacement joins
                    # the paths either side of it, end to end, and nowhere else.
                    if key == before and e == 0 and o == len(old_edges) - 1:
                        meets = _overlap_beyond(p, q, u)
                    elif key == after and e == len(new_edges) - 1 and o == 0:
                        meets = _overlap_beyond(q, p, v)
                    else:
                        meets = _segments_meet(p, q, u, v)
                    if meets:
                        return False
        region = [ring.points[i]] + [ring.points[k] for k in run] + replacement[::-1][:-1]
        xs = [p[0] for p in region]
        ys = [p[1] for p in region]
        corners = set(region)
        for other, point, pinned in self._vertices_in(min(xs), min(ys), max(xs), max(ys)):
            # The ring's own positions can only be inside by crossing the
            # replacement, which is checked above, unless they are in a loop
            # where the ring crosses itself.
            if (other != r or pinned) and point not in corners and _point_in_ring(point, region):
                return False
        return True

    def _before(self, r, i):
        """The kept position whose path ends at i."""
        ring = self.rings[r]
        k = (i - 1) % len(ring.points)
        while ring.next_kept[k] != i:
            k = (k - 1) % len(ring.points)
        return k

    def _cell_of(self, p):
        return (math.floor(p[0] / self.cell), math.floor(p[1] / self.cell))

    def _cells(self, x0, y0, x1, y1):
        (cx0, cy0), (cx1, cy1) = self._cell_of((x0, y0)), self._cell_of((x1, y1))
        return ((cx, cy) for cx in range(cx0, cx1 + 1) for cy in range(cy0, cy1 + 1))

    def _add_path(self, key, path):
        self.paths[key] = path
        xs = [p[0] for p in path]
        ys = [p[1] for p in path]
        cells = list(self._cells(min(xs), min(ys), max(xs), max(ys)))
        self.path_cells[key] = cells
        for cell in cells:
            self.path_grid.setdefault(cell, set()).add(key)

    def _remove_path(self, key):
        for cell in self.path_cells.pop(key):
            self.path_grid[cell].discard(key)
        del self.paths[key]

    def _paths_in(self, x0, y0, x1, y1):
        found = set()
        for cell in self._cells(x0, y0, x1, y1):
            found |= self.path_grid.get(cell, set())
        return found

    def _vertices_in(self, x0, y0, x1, y1):
        for cell in self._cells(x0, y0, x1, y1):
            yield from self.vertex_grid.get(cell, ())


class _Frame:
    """Km along and out from the line from a to b, at the scale where they are.

    Longitude is scaled by the cosine of the latitude halfway between a and b.
    That is an affine map of longitude and latitude, so straight edges stay
    straight and every side test agrees with one made in degrees; only
    distances are approximate, and over the few km of a band that is far
    below a metre.
    """

    def __init__(self, a, b, side):
        self.a = a
        self.scale = math.cos(math.radians((a[1] + b[1]) / 2)) * KM_PER_DEGREE
        bx, by = self._km(b)
        self.length = math.hypot(bx, by)
        if self.length:
            ux, uy = bx / self.length, by / self.length
            self.along = (ux, uy)
            # Away from the area: the right of the line when the area is on
            # its left.
            self.out = (uy, -ux) if side > 0 else (-uy, ux)

    def _km(self, p):
        return (p[0] - self.a[0]) * self.scale, (p[1] - self.a[1]) * KM_PER_DEGREE

    def place(self, p):
        x, y = self._km(p)
        return x * self.along[0] + y * self.along[1], x * self.out[0] + y * self.out[1]

    def corner(self, along_km, out_km):
        x = along_km * self.along[0] + out_km * self.out[0]
        y = along_km * self.along[1] + out_km * self.out[1]
        return (
            round(self.a[0] + x / self.scale, _DECIMALS),
            round(self.a[1] + y / KM_PER_DEGREE, _DECIMALS),
        )


def _overlap_beyond(shared, other_end, far):
    """Whether an edge from shared to far folds back along one from shared to other_end."""
    return _cross(shared, other_end, far) == 0 and _within_box(shared, other_end, far) and far != shared


def _segments_meet(a, b, p, q):
    """Whether two segments cross or touch, ends included."""
    d1, d2 = _cross(p, q, a), _cross(p, q, b)
    d3, d4 = _cross(a, b, p), _cross(a, b, q)
    if d1 * d2 < 0 and d3 * d4 < 0:
        return True
    return (
        (d1 == 0 and _within_box(p, q, a)) or (d2 == 0 and _within_box(p, q, b))
        or (d3 == 0 and _within_box(a, b, p)) or (d4 == 0 and _within_box(a, b, q))
    )


def _within_box(a, b, p):
    return min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])


def _point_in_ring(point, ring):
    """Even-odd rule, the ring closed back to its start."""
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside
