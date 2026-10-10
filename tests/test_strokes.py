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


def test_a_shared_bus_and_bike_lane_has_both_marks():
    """A ``bus,bike`` lane (2026-10-10, Boulevard des Moulins' contraflow lane) gets the bike 12 m after each BUS; a bus-only lane gets BUS alone."""
    import geopandas as gpd
    from shapely.geometry import LineString

    from lanestyle.arrows import mark_strokes

    def parts(use):
        g = gpd.GeoDataFrame({"link_id": [1], "lane_id": ["1_1"], "use": [use], "width_m": [3.25]},
                             geometry=[LineString([(7.42, 43.73), (7.4215, 43.73)])], crs=4326)        # about 120 m
        fc = mark_strokes(g, None, {"end_m": 10, "repeat_m": 60}, [0.0])
        return sum(len(f["geometry"]["coordinates"]) for f in fc["features"])
    bike_only = parts("bike")
    assert parts("bus,bike") == parts("bus") + bike_only


def test_a_painted_zebra_is_white_strokes_along_the_road_from_zoom_17():
    """2026-10-10: a painted crossing's stripes are items of the link under them, strokes along the road as long as the crossing is wide,
    stripe_m wide and stripe_m + gap_m apart across it, shown from minzoom; an unpainted crossing has none."""
    import math

    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import LineString

    from lanestyle.items import ZEBRA, zebra_strokes
    k = 111320 * math.cos(math.radians(59.3))
    g = gpd.GeoDataFrame({"lane_id": ["1_1"], "link_id": [7]}, geometry=[LineString([(18.0, 59.3), (18.001, 59.3)])], crs=4326)
    # 4 m along the road (x), 6 m across it (y): first side across, second along
    x0, y0 = 18.0005, 59.3 - 3 / 111320
    rect = f"POLYGON(({x0} {y0}, {x0} {y0 + 6 / 111320}, {x0 + 4 / k} {y0 + 6 / 111320}, {x0 + 4 / k} {y0}, {x0} {y0}))"
    cr = pd.DataFrame([{"crossing_id": 1, "lane_id": "1_1", "across_from": 0.0, "across_to": 6.0, "painted": True, "cgeom": rect}])
    fc = zebra_strokes(g, cr, {"stripe_m": 0.5, "gap_m": 0.5, "minzoom": 17}, "#ffffff")
    fs = fc["features"]
    assert len(fs) == 6 and all(f["properties"]["edge_id"] == 7 and f["properties"]["order"] == ZEBRA and f["properties"]["minzoom"] == 17 for f in fs)
    (ax, ay), (bx, by) = fs[0]["geometry"]["coordinates"]
    assert abs((bx - ax) * k - 4) < 0.05 and abs(by - ay) * 111320 < 0.05            # along the road, as long as the crossing is wide
    assert zebra_strokes(g, cr.assign(painted=False), {"stripe_m": 0.5, "gap_m": 0.5}, "#ffffff") is None


def test_sidewalks_come_from_the_ways_tags_only_on_their_side():
    """2026-10-10: a sidewalk OSM tags on a street (right / left / both, sidewalk[:side]:width) is a strip just outside the street's width on
    that side of the way, so on the other side of a link that runs against the way; separate, no and a bare yes give none."""
    import geopandas as gpd
    from shapely.geometry import LineString

    from lanestyle.items import _sidewalk_sides, sidewalk_strokes
    assert _sidewalk_sides({"sidewalk": "both"}, 2.0) == {"left": 2.0, "right": 2.0}
    assert _sidewalk_sides({"sidewalk": "right", "sidewalk:right:width": "3.5"}, 2.0) == {"right": 3.5}
    assert _sidewalk_sides({"sidewalk:left": "yes", "sidewalk:right": "separate"}, 2.0) == {"left": 2.0}
    for t in ({"sidewalk": "separate"}, {"sidewalk": "no"}, {"sidewalk": "yes"}, {}):
        assert _sidewalk_sides(t, 2.0) == {}
    ln = LineString([(18.0, 59.3), (18.001, 59.3)])
    st = {"width_m": 2.0, "minzoom": 17}
    for ref, sign in (("9#1f", 1), ("9#1r", -1)):
        g = gpd.GeoDataFrame({"link_id": [5], "osm_id": [9], "edge_ref": [ref], "reverse_link_id": [None]}, geometry=[ln], crs=4326)
        fc = sidewalk_strokes(g, {5: 5}, {"5": ln}, {"5": 8.0}, {9: {"sidewalk": "right"}}, st, "#f0cb8c")
        (f,) = fc["features"]
        assert f["properties"]["offset_m"] == sign * 5.0 and f["properties"]["width_m"] == 2.0 and f["properties"]["minzoom"] == 17
