"""Painted lane markings as line strokes: white, flat on the lane, sized in metres.

A shape is a list of (polyline, stroke width m) in a local frame: u forward along the lane, v to the left,
(0, 0) the centre of the mark. `shape(name, lane_width)` makes one, `place(shape, line, at_m, lane_width)`
puts it on a line as GeoJSON LineString features (lon/lat, `width_m` each).
"""
import math

from pyproj import Transformer
from shapely.geometry import LineString

ARROWS = ("thru", "left", "right", "uturn", "left+thru", "thru+right", "left+right", "left+thru+right")
STROKE = 0.4          # painted line width, m (2026-10-09: 0.3 too thin)
LENGTH = 7.0          # arrow length, m (2026-10-09: 4 m too small, then 6 m: longer and thinner, 8 m; 2026-10-10: a little shorter)


SHAFT = 0.3          # an arrow's shaft and branches, m (2026-10-09: 0.45 too thick)
FILL = 0.1           # the thin strokes that fill an arrow's head solid, m


def _head(tip, ang, k, hl=1.8, hb=0.55):
    """A SOLID triangular head with its point at `tip`, pointing at angle `ang` (0 = forward, 90 = left): a fan of thin strokes from
    the base to the tip, close enough to read as one painted triangle (a single stroke width per item, so no polygon is needed)."""
    a, hl, hb = math.radians(ang), hl * k, hb * k                      # head length, half its base
    ux, uy, nx, ny = math.cos(a), math.sin(a), -math.sin(a), math.cos(a)
    bx, by = tip[0] - hl * ux, tip[1] - hl * uy
    n = max(4, int(2 * hb / (FILL * 0.6)))
    return [[(bx + nx * hb * (2 * i / n - 1), by + ny * hb * (2 * i / n - 1)), tip] for i in range(n + 1)]


def _bend(p0, ang0, ang1, r, steps=8):
    """A smooth turn: an arc of radius `r` starting at `p0` heading `ang0` and ending heading `ang1` (degrees, left positive)."""
    a0, a1 = math.radians(ang0), math.radians(ang1)
    s = 1 if a1 > a0 else -1
    cx, cy = p0[0] - s * r * math.sin(a0), p0[1] + s * r * math.cos(a0)          # the centre, on the inside of the turn
    return [(cx + s * r * math.sin(a0 + (a1 - a0) * i / steps), cy - s * r * math.cos(a0 + (a1 - a0) * i / steps)) for i in range(steps + 1)]


def _arrow(moves, W):
    """A painted lane arrow: a thick shaft, smooth bends into the turns, solid heads; (polylines, width) pairs: the shaft and branches at
    SHAFT, the heads' fill at FILL."""
    k, L = min(1.0, W / 3.25), LENGTH
    head = 1.8 * k
    thick, fill = [], []
    if moves == {"uturn"}:
        r = min(0.3 * W, W / 2 - 0.75 * k - 0.15)
        hook = [(-L / 2 + head, -r), (0.6, -r)] + _bend((0.6, -r), 0, 180, r, 12)[1:] + [(-0.6 + head, r)]
        thick.append(hook)
        fill += _head((-0.6, r), 180, k)
    else:
        if moves in ({"left"}, {"right"}):         # a single turn: the shaft runs on, then bends into the turn
            thick.append([(-L / 2, 0), (0.2, 0)])
        elif "thru" in moves:
            thick.append([(-L / 2, 0), (L / 2 - head, 0)])
            fill += _head((L / 2, 0), 0, k)
        else:                                       # left + right: the stem ends at the fork
            thick.append([(-L / 2, 0), (-0.4, 0)])
        for sgn, on in ((1, "left" in moves), (-1, "right" in moves)):
            if on:                                  # a bend to 45 degrees, a short straight run, a smaller head: all inside the lane
                u0 = 0.0 if moves in ({"left"}, {"right"}) else -1.2
                arc = _bend((u0, 0), 0, 45 * sgn, 1.0 * k)
                c45 = math.cos(math.radians(45))
                end = (arc[-1][0] + 0.5 * k * c45, arc[-1][1] + sgn * 0.5 * k * c45)
                thick.append(arc + [end])
                fill += _head((end[0] + 1.2 * k * c45, end[1] + sgn * 1.2 * k * c45), 45 * sgn, k, hl=1.2, hb=0.4)
    return [(p, SHAFT) for p in thick] + [(p, FILL) for p in fill]


# letters in a unit box, x right and y up as the driver reads them
_B = [(0, 0), (0, 1), (.7, 1), (.95, .9), (1, .75), (.95, .6), (.7, .52), (0, .52)]
_LETTERS = {
    "B": [_B, [(.7, .52), (.95, .42), (1, .25), (.95, .1), (.7, 0), (0, 0)]],
    "U": [[(0, 1), (0, .2), (.15, .04), (.5, 0), (.85, .04), (1, .2), (1, 1)]],
    "S": [[(1, .85), (.85, .97), (.5, 1), (.15, .97), (0, .82), (.05, .65), (.5, .5), (.95, .35), (1, .18), (.85, .03), (.5, 0), (.15, .03), (0, .15)]],
}


def _bus(W):
    """BUS painted as on the road: letters upright for the driver, stretched along the lane, B farthest (the word reads from far to near)."""
    wl, H, gap = 0.55 * W, 1.8, 0.4
    top = (3 * H + 2 * gap) / 2
    out = []
    for i, ch in enumerate("BUS"):
        u0 = top - H - i * (H + gap)
        out += [([(u0 + y * H, (0.5 - x) * wl) for x, y in p], 0.25) for p in _LETTERS[ch]]
    return [([(u, v) for u, v in p], w) for p, w in out]


def _circle(c, r, n=14):
    return [(c[0] + r * math.cos(2 * math.pi * i / n), c[1] + r * math.sin(2 * math.pi * i / n)) for i in range(n + 1)]


def _bike(W):
    """A bike seen from the side, pointing forward, its top to the left: 1.6 m long."""
    d = -0.1
    p = lambda u, v: (u, v + d)
    r = 0.3
    parts = [_circle(p(-0.5, 0), r), _circle(p(0.5, 0), r),
             [p(-0.5, 0), p(-0.1, 0), p(0.3, 0.4), p(-0.2, 0.4), p(-0.1, 0)],      # rear stay, down tube, top tube, seat tube
             [p(0.3, 0.4), p(0.5, 0)],                                             # fork
             [p(0.3, 0.4), p(0.25, 0.52), p(0.4, 0.52)],                           # stem and handlebar
             [p(-0.2, 0.4), p(-0.22, 0.5)], [p(-0.35, 0.5), p(-0.1, 0.5)]]         # seat post and saddle
    return [(q, 0.12) for q in parts]


def shape(name, lane_width):
    """The mark `name` ("thru", "left", ..., "bus", "bike") scaled to `lane_width` m."""
    if name == "bus":
        return _bus(lane_width)
    if name == "bike":
        return _bike(lane_width)
    moves = set(name.split("+"))
    if name not in ARROWS:
        raise ValueError(f"unknown mark {name!r}")
    return _arrow(moves, lane_width)


def place(shp, lane_line, at_m, lane_width=None, step=0.5, offset_m=0.0):
    """GeoJSON LineString features (lon/lat, `width_m` each) of `shp` centred `at_m` metres along `lane_line` (a lon/lat LineString),
    bent with the line: a point (u, v) goes to u metres on along the line and v metres to its left.
    `offset_m` moves the whole mark that far to the RIGHT of the line, the same side as roadstyle's item offsets and MapLibre's
    line-offset (positive = right of the direction of travel), so a lane and its marks take the same number (2026-10-09: left
    here and right there mirrored the marks across the road). An item's own line offset would blow a small shape up, so the strokes
    carry their place."""
    x0, y0 = lane_line.coords[0][:2]
    fwd = Transformer.from_crs(4326, f"+proj=aeqd +lat_0={y0} +lon_0={x0} +datum=WGS84", always_xy=True)
    back = Transformer.from_crs(f"+proj=aeqd +lat_0={y0} +lon_0={x0} +datum=WGS84", 4326, always_xy=True)
    line = LineString(zip(*fwd.transform(*zip(*[c[:2] for c in lane_line.coords])), strict=True))
    n = line.length

    def at(u, v):
        s = min(max(at_m + u, 0.0), n)
        a, b = line.interpolate(max(s - 0.25, 0)), line.interpolate(min(s + 0.25, n))
        tx, ty = b.x - a.x, b.y - a.y
        h = math.hypot(tx, ty) or 1.0
        c = line.interpolate(s)
        return c.x - v * ty / h, c.y + v * tx / h

    feats = []
    for pts, w in shp:
        dense = []
        for (u0, v0), (u1, v1) in zip(pts, pts[1:]):
            m = max(1, math.ceil(math.hypot(u1 - u0, v1 - v0) / step))
            dense += [(u0 + (u1 - u0) * i / m, v0 + (v1 - v0) * i / m) for i in range(m)]
        dense.append(pts[-1])
        xs, ys = zip(*[at(u, v - offset_m) for u, v in dense])
        lon, lat = back.transform(xs, ys)
        feats.append({"type": "Feature", "properties": {"width_m": w},
                      "geometry": {"type": "LineString", "coordinates": [[a, b] for a, b in zip(lon, lat, strict=True)]}})
    return feats


def length_m(lane_line):
    """The length of a lon/lat line in metres."""
    x0, y0 = lane_line.coords[0][:2]
    t = Transformer.from_crs(4326, f"+proj=aeqd +lat_0={y0} +lon_0={x0} +datum=WGS84", always_xy=True)
    return LineString(zip(*t.transform(*zip(*[c[:2] for c in lane_line.coords])), strict=True)).length


def dashes(lane_line, dash_m=3.0, gap_m=9.0, width_m=0.2, offset_m=0.0):
    """A dashed line as real pieces: `dash_m` long, `gap_m` apart, fixed in metres along the line (the same at every zoom, unlike a
    screen dash pattern). GeoJSON LineString features with `width_m`; draw them with flat ends."""
    n, out, s = length_m(lane_line), [], 0.0
    while s + dash_m <= n + 1e-9:
        out += place([([(-dash_m / 2, 0), (dash_m / 2, 0)], width_m)], lane_line, s + dash_m / 2, offset_m=offset_m)
        s += dash_m + gap_m
    return out


def positions(length, first_m, every_m=None, last_m=None):
    """Fixed places (metres along a lane) for a mark: `first_m`, then every `every_m` (None: only the first), all at least `last_m` clear of the
    lane's end (e.g. an arrow 10 m before the end: positions(L, L - 10))."""
    end = length - (last_m or 0)
    out, s = [], first_m
    while s <= end + 1e-9:
        out.append(s)
        if not every_m:
            break
        s += every_m
    return out
