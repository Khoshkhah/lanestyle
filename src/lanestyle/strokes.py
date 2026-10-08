"""Painted lane markings as line strokes: white, flat on the lane, sized in metres.

A shape is a list of (polyline, stroke width m) in a local frame: u forward along the lane, v to the left,
(0, 0) the centre of the mark. `shape(name, lane_width)` makes one, `place(shape, line, at_m, lane_width)`
puts it on a line as GeoJSON LineString features (lon/lat, `width_m` each).
"""
import math

from pyproj import Transformer
from shapely.geometry import LineString

ARROWS = ("thru", "left", "right", "uturn", "left+thru", "thru+right", "left+right", "left+thru+right")
STROKE = 0.3          # painted line width, m
LENGTH = 4.0          # arrow length, m


def _head(tip, ang, k):
    """A chevron of two short strokes whose point is `tip`, pointing at angle `ang` (0 = forward, 90 = left)."""
    a, size, spread = math.radians(ang), 0.55 * k, math.radians(40)
    arm = lambda s: (tip[0] - size * math.cos(a + s), tip[1] - size * math.sin(a + s))
    return [arm(spread), tip, arm(-spread)]


def _arrow(moves, W):
    k, L = min(1.0, W / 3.25), LENGTH
    vt = W / 2 - 0.3 * k - 0.05                     # the side tip, inside the lane edge
    lines = []
    if moves == {"uturn"}:
        r = 0.3 * W
        arc = [(0.8 + r * math.sin(t), r * -math.cos(t)) for t in [math.pi * i / 12 for i in range(13)]]
        lines = [[(-L / 2, -r)] + arc + [(-0.3, r)], _head((-0.3, r), 180, k)]
        return [(p, STROKE) for p in lines]
    if moves in ({"left"}, {"right"}):
        s = 1 if moves == {"left"} else -1
        return [(p, STROKE) for p in ([(-L / 2, 0), (0.3, 0), (0.3, s * vt)], _head((0.3, s * vt), 90 * s, k))]
    if "thru" in moves:
        lines += [[(-L / 2, 0), (L / 2, 0)], _head((L / 2, 0), 0, k)]
    else:                                           # left + right: the stem ends at the fork
        lines += [[(-L / 2, 0), (-0.4, 0)]]
    for s, on in ((1, "left" in moves), (-1, "right" in moves)):
        if on:
            u0 = -0.9 if "thru" in moves else -0.4
            d = vt - 0.3 * k                         # a 45 degree branch from the shaft
            tip = (u0 + d, s * d)
            lines += [[(u0, 0), tip], _head(tip, 45 * s, k)]
    return [(p, STROKE) for p in lines]


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
    `offset_m` moves the whole mark that far to the left of the line (to put it on a lane beside the road's centre line; an item's own
    line offset would blow a small shape up, so the strokes carry their place)."""
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
        xs, ys = zip(*[at(u, v + offset_m) for u, v in dense])
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
