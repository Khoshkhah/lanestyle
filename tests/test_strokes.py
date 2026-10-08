import math

import pytest
from shapely.geometry import LineString

from lanestyle import strokes

NAMES = (*strokes.ARROWS, "bus", "bike")


def _extent(shp):
    pts = [(u, v, w) for p, w in shp for u, v in p]
    return (max(abs(v) + w / 2 for u, v, w in pts), max(u for u, v, w in pts) - min(u for u, v, w in pts))


@pytest.mark.parametrize("name", NAMES)
def test_shape_is_not_empty_and_fits_its_lane(name):
    for W in (3.25, 1.5) if name == "bike" else (3.25, 2.5):
        shp = strokes.shape(name, W)
        assert shp and all(len(p) >= 2 and w > 0 for p, w in shp)
        assert _extent(shp)[0] <= W / 2 + 1e-9


def test_sizes():
    assert abs(_extent(strokes.shape("thru", 3.25))[1] - strokes.LENGTH) < strokes.STROKE
    assert 1.4 < _extent(strokes.shape("bike", 1.5))[1] < 1.8


def test_unknown_mark():
    with pytest.raises(ValueError):
        strokes.shape("nope", 3)


def _metres(f, lat=43.73):
    return [((x - 7.42) * 111320 * math.cos(math.radians(lat)), (y - lat) * 110540) for x, y in f["geometry"]["coordinates"]]


def test_place_straight_and_curved():
    shp = strokes.shape("thru", 3.25)
    east = LineString([(7.42, 43.73), (7.43, 43.73)])
    f = strokes.place(shp, east, 100, 3.25)
    xs = [x for g in f for x, _ in _metres(g)]
    assert len(f) == len(shp) and all(g["properties"]["width_m"] in (strokes.SHAFT, strokes.FILL) for g in f) and abs((min(xs) + max(xs)) / 2 - 100) < 0.5
    # a quarter circle of radius 50 m: every stroke point is within the lane of the curve
    r = 50
    arc = LineString([(7.42 + (r * math.sin(t)) / (111320 * math.cos(math.radians(43.73))), 43.73 + r * (1 - math.cos(t)) / 110540) for t in [i * math.pi / 2 / 40 for i in range(41)]])
    f = strokes.place(shp, arc, 40, 3.25)
    for g in f:
        for x, y in _metres(g):
            assert abs(math.hypot(x, y - r) - r) < 1.7        # distance from the circle's centre = r +- half lane
    assert max(y for g in f for _, y in _metres(g)) > 10        # it did turn with the lane


def test_dashes_are_fixed_pieces_in_metres():
    east = LineString([(7.42, 43.73), (7.43, 43.73)])      # about 805 m
    d = strokes.dashes(east, 3.0, 9.0)
    assert abs(len(d) - strokes.length_m(east) / 12) <= 1
    xs = [_metres(f)[0][0] for f in d[:3]]
    assert abs(xs[1] - xs[0] - 12) < 0.2 and abs(_metres(d[0])[-1][0] - _metres(d[0])[0][0] - 3) < 0.1
    assert strokes.positions(100, 90) == [90] and strokes.positions(100, 10, 30, 10) == [10, 40, 70]


def test_offset_is_to_the_right_like_roadstyle():
    """A positive offset puts the mark on the right of the direction of travel, as roadstyle's item offsets and MapLibre's line-offset
    (2026-10-09: the marks were mirrored across the road)."""
    east = LineString([(7.42, 43.73), (7.43, 43.73)])
    f = strokes.place([([(-0.5, 0), (0.5, 0)], 0.2)], east, 100, offset_m=2.0)
    assert all(lat < 43.73 for _, lat in f[0]["geometry"]["coordinates"])          # south of an eastward line = its right
