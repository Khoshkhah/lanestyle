"""lanestyle: the GMNS reader (from_gmns) and the roadstyle engine (render_lanes)."""
import json
import sys

import duckdb
import pandas as pd

import lanestyle as ls


def test_no_mapstyle_dependency():
    assert "mapstyle" not in sys.modules


def _dbs(tmp_path):
    """A GMNS db: link 1 A->B (2 lanes, lane 2 bus), link 2 B->C (a bridge in the source db),
    link 3 B->A; movements 1->2 thru from every lane, 1->3 a U-turn from lane 1 only."""
    gmns, src = tmp_path / "g.duckdb", tmp_path / "s.duckdb"
    con = duckdb.connect(str(gmns))
    con.execute("INSTALL spatial; LOAD spatial; CREATE SCHEMA gmns_driving")
    ln = lambda y: f"ST_GeomFromText('LINESTRING(18.00 {y}, 18.01 {y})')"
    con.execute("CREATE TABLE gmns_driving.link(link_id BIGINT, name VARCHAR, facility_type VARCHAR, "
                "from_node_id BIGINT, to_node_id BIGINT)")
    con.execute("INSERT INTO gmns_driving.link VALUES (8121729169906061189,'Main St','secondary',10,11),"
                "(2,'Bridge Rd','tertiary',11,12),(3,'Main St','secondary',11,10)")
    con.execute("CREATE TABLE gmns_driving.lane(lane_id VARCHAR, link_id BIGINT, lane_num BIGINT, "
                "allowed_uses VARCHAR, width DOUBLE, turn VARCHAR, geom GEOMETRY)")
    con.execute(f"INSERT INTO gmns_driving.lane VALUES "
                f"('1_1',8121729169906061189,1,'auto',NULL,'left',{ln(59.30)}),"
                f"('1_2',8121729169906061189,2,'bus',3.5,NULL,{ln(59.30003)}),"
                f"('2_1',2,1,'auto',NULL,NULL,{ln(59.31)}),('3_1',3,1,'auto',NULL,NULL,{ln(59.32)})")
    con.execute("CREATE TABLE gmns_driving.movement(ib_link_id BIGINT, start_ib_lane BIGINT, "
                "end_ib_lane BIGINT, ob_link_id BIGINT, start_ob_lane INTEGER, end_ob_lane INTEGER, type VARCHAR)")
    con.execute("INSERT INTO gmns_driving.movement VALUES (8121729169906061189,NULL,NULL,2,NULL,NULL,'thru'),"
                "(8121729169906061189,1,1,3,NULL,NULL,'uturn')")
    con.close()
    con = duckdb.connect(str(src))
    con.execute("CREATE SCHEMA driving; CREATE TABLE driving.edges(edge_id BIGINT, bridge VARCHAR, "
                "tunnel VARCHAR, layer VARCHAR)")
    con.execute("INSERT INTO driving.edges VALUES (8121729169906061189,NULL,NULL,NULL),(2,'yes',NULL,'1'),"
                "(3,NULL,NULL,NULL)")
    con.close()
    return gmns, src


def test_from_gmns_lane_table_and_turns(tmp_path):
    gmns, src = _dbs(tmp_path)
    lanes, turns = ls.from_gmns(gmns, source_db=src)
    r = lanes.set_index("lane_id")
    assert r.loc["1_1", "highway"] == "secondary" and r.loc["1_2", "use"] == "bus"
    assert r.loc["1_1", "name"] == "Main St" and pd.isna(r.loc["1_2", "name"])        # lane 1 only
    assert r.loc["1_1", "link_id"] == 8121729169906061189                           # exact, not float
    assert r.loc["2_1", "bridge"] == "yes" and r.loc["2_1", "layer"] == "1"         # from source_db
    got = set(map(tuple, turns[["from_lane", "to_lane", "type"]].values))
    assert got == {("1_1", "2_1", "thru"), ("1_2", "2_1", "thru"), ("1_1", "3_1", "uturn")}
    # without source_db: every lane at ground level
    assert "bridge" not in ls.from_gmns(gmns)[0].columns


def test_from_gmns_levels_from_link_columns_need_no_source_db(tmp_path):
    """duckOSM writes bridge / tunnel / layer into `link`: one file is enough."""
    gmns, _ = _dbs(tmp_path)
    con = duckdb.connect(str(gmns))
    con.execute("ALTER TABLE gmns_driving.link ADD COLUMN bridge VARCHAR; "
                "ALTER TABLE gmns_driving.link ADD COLUMN tunnel VARCHAR; "
                "ALTER TABLE gmns_driving.link ADD COLUMN layer VARCHAR; "
                "UPDATE gmns_driving.link SET bridge = 'yes', layer = '1' WHERE link_id = 2")
    con.close()
    r = ls.from_gmns(gmns)[0].set_index("lane_id")
    assert r.loc["2_1", "bridge"] == "yes" and r.loc["2_1", "layer"] == "1"
    assert pd.isna(r.loc["1_1", "bridge"])


def _page(html):
    """The page's style (its sources), and the overlays by label: ``{label: [feature properties]}`` (docs/design/lanestyle_on_roadstyle_items.md:
    the roads are the source ``roads``, every lane / line / zebra / arrow is an item of an overlay, attached to its road by ``road_id``)."""
    style = json.loads(html.split("const style = ", 1)[1].split(", BASEMAPS", 1)[0])
    overlays = json.JSONDecoder().raw_decode(html.split("const OVERLAYS = ", 1)[1])[0]
    return style, {o["label"]: [f["properties"] for f in style["sources"][o["source"]]["data"]["features"]] for o in overlays}


def _lane_props(html, label="lanes"):
    return {p["lane_id"]: p for p in _page(html)[1][label]}


def test_settings_override_the_roadstyle_way(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "lanestyle.json").write_text('{"lanes": {"casing_m": 0.1}}')
    s = ls.lane_settings({"lanes": {"colors": {"bus": "#123456"}}})
    assert s["casing_m"] == 0.1 and s["colors"]["bus"] == "#123456" and s["colors"]["bike"] == "#1c7ed6"


def test_turns_pair_movement_lanes_in_order(tmp_path):
    """A movement's lane ranges pair in order (duckOSM / osm2gmns): link 1's lane 2 into link 2's
    lane 1 only, not lane 1 as well."""
    gmns, src = _dbs(tmp_path)
    con = duckdb.connect(str(gmns))
    con.execute("UPDATE gmns_driving.movement SET start_ib_lane=2, end_ib_lane=2, start_ob_lane=1, end_ob_lane=1 "
                "WHERE type='thru'")
    con.close()
    _, turns = ls.from_gmns(gmns)
    assert set(map(tuple, turns[turns["type"] == "thru"][["from_lane", "to_lane"]].values)) == {("1_2", "2_1")}


def test_read_boundary(tmp_path):
    """The area's boundary from a duckOSM db (main.boundary), None without one; drawn as an outline."""
    gmns, src = _dbs(tmp_path)
    assert ls.read_boundary(src) is None
    con = duckdb.connect(str(src))
    con.execute("INSTALL spatial; LOAD spatial; CREATE TABLE main.boundary(name VARCHAR, geom GEOMETRY)")
    con.execute("INSERT INTO main.boundary VALUES ('x', ST_GeomFromText('POLYGON((17.99 59.29, 18.02 59.29, 18.02 59.33, 17.99 59.33, 17.99 59.29))'))")
    con.close()
    b = ls.read_boundary(src)
    assert b is not None and b.geom_type == "Polygon"


def _with_walking(tmp_path):
    """_dbs plus a walking schema: footway link 5 (lane 5_1, use walk), the road link 2 walked on (lane 2_1, use walk),
    and a movement from the footway onto the road."""
    gmns, src = _dbs(tmp_path)
    con = duckdb.connect(str(gmns))
    con.execute("INSTALL spatial; LOAD spatial; CREATE SCHEMA gmns_walking")
    ln = lambda y: f"ST_GeomFromText('LINESTRING(18.00 {y}, 18.01 {y})')"
    con.execute("CREATE TABLE gmns_walking.link(link_id BIGINT, name VARCHAR, facility_type VARCHAR, "
                "from_node_id BIGINT, to_node_id BIGINT)")
    con.execute("INSERT INTO gmns_walking.link VALUES (2,'Bridge Rd','tertiary',11,12),(5,NULL,'footway',13,11)")
    con.execute("CREATE TABLE gmns_walking.lane(lane_id VARCHAR, link_id BIGINT, lane_num BIGINT, allowed_uses VARCHAR, "
                "width DOUBLE, turn VARCHAR, geom GEOMETRY)")
    con.execute(f"INSERT INTO gmns_walking.lane VALUES ('2_1',2,1,'walk',NULL,NULL,{ln(59.31)}),"
                f"('5_1',5,1,'walk',NULL,NULL,{ln(59.335)})")
    con.execute("CREATE TABLE gmns_walking.movement(ib_link_id BIGINT, start_ib_lane BIGINT, end_ib_lane BIGINT, "
                "ob_link_id BIGINT, start_ob_lane INTEGER, end_ob_lane INTEGER, type VARCHAR)")
    con.execute("INSERT INTO gmns_walking.movement VALUES (5,NULL,NULL,2,NULL,NULL,'thru')")
    con.close()
    return gmns, src


def test_modes_add_only_the_footpaths_not_the_roads_walked_on(tmp_path):
    gmns, src = _with_walking(tmp_path)
    lanes, turns = ls.from_gmns(gmns, modes=("driving", "walking"))
    assert set(lanes.lane_id) == {"1_1", "1_2", "2_1", "3_1", "5_1"}        # the road's own walk lane is not added
    r = lanes.set_index("lane_id")
    assert r.loc["5_1", "use"] == "walk" and r.loc["1_2", "use"] == "bus" and r.loc["2_1", "use"] == "auto"
    assert lanes["link_id"].dtype == "Int64"
    assert ("5_1", "2_1") in set(zip(turns["from_lane"], turns["to_lane"]))   # the footway leads onto the road
    assert set(turns["from_lane"]) | set(turns["to_lane"]) <= set(lanes.lane_id)
    only, _ = ls.from_gmns(gmns, mode="walking")                             # one mode: unchanged
    assert set(only.lane_id) == {"2_1", "5_1"}
    assert set(ls.from_gmns(gmns)[0].lane_id) == {"1_1", "1_2", "2_1", "3_1"}


def test_modes_skip_the_other_direction_of_a_road_walked_on(tmp_path):
    """The walking network has a link for the way a one-way road is not driven (here 6, the reverse of road 2): the same
    OSM way as the driving link, so not a footpath of its own."""
    gmns, _ = _with_walking(tmp_path)
    con = duckdb.connect(str(gmns))
    con.execute("LOAD spatial")
    for sch in ("driving", "walking"):
        con.execute(f"ALTER TABLE gmns_{sch}.link ADD COLUMN osm_id BIGINT")
    con.execute("UPDATE gmns_driving.link SET osm_id = link_id + 900; UPDATE gmns_walking.link SET osm_id = link_id + 900")
    con.execute("INSERT INTO gmns_walking.link VALUES (6,'Bridge Rd','tertiary',12,11,902)")
    con.execute("INSERT INTO gmns_walking.lane VALUES ('6_1',6,1,'walk',NULL,NULL,ST_GeomFromText('LINESTRING(18.01 59.311, 18.00 59.311)'))")
    con.close()
    lanes, _ = ls.from_gmns(gmns, modes=("driving", "walking"))
    assert "6_1" not in set(lanes.lane_id) and "5_1" in set(lanes.lane_id)


def _crossing(lane_id="2_1", painted=True, to_left=True, start=200.0, end=203.0):
    """A crossing table row for road 2 (east-west at y = 59.31): the zebra's rectangle, 3 m along the road, 6.5 m across it."""
    import pandas as pd

    x = 18.0 + (start + end) / 2 / 56700
    dx, dy = 1.5 / 56700, 3.25 / 111320
    rect = f"POLYGON (({x + dx} {59.31 - dy}, {x + dx} {59.31 + dy}, {x - dx} {59.31 + dy}, {x - dx} {59.31 - dy}, {x + dx} {59.31 - dy}))"
    return pd.DataFrame({"crossing_id": ["w1"], "lane_id": [lane_id], "start_lr": [start], "end_lr": [end], "across_from": [1.6],
                         "across_to": [4.85], "to_left": [to_left], "painted": [painted], "length": [6.5],
                         "crossing_type": ["marked"], "source": ["way"], "cgeom": [rect]})


def test_a_link_with_no_road_class_is_not_drawn(tmp_path):
    """A ferry in the walking network has no road class (highway null): it is no lane."""
    from lanestyle.settings import _roads_only

    gmns, _ = _with_walking(tmp_path)
    lanes, turns = ls.from_gmns(gmns, modes=("driving", "walking"))
    lanes.loc[lanes["lane_id"] == "5_1", "highway"] = None
    kept = set(_roads_only(lanes)["lane_id"])
    assert "5_1" not in kept and "1_1" in kept and len(kept) == len(lanes) - 1


def test_default_widths_by_use():
    import pandas as pd

    from lanestyle.settings import _widths, lane_settings
    g = pd.DataFrame({"use": ["auto", "walk", "bike", "bike", "bike", "walk"],
                      "lane_num": [1, 1, 2, 1, 1, 1], "lanes": [2, None, 1, 2, None, 1],
                      "width_m": [None, None, None, None, None, 2.5]})
    # auto 3.25; walk 2.0; a bike lane beyond the 1 motor lane 1.5; a bike lane that is one of 2 motor lanes 3.25;
    # a bike lane on a cycleway (no motor lanes) 1.5; a tagged width is kept
    assert _widths(g, lane_settings()).tolist() == [3.25, 2.0, 1.5, 3.25, 1.5, 2.5]
    assert _widths(g, lane_settings({"lanes": {"width_m_by_use": {"walk": 1.2}}})).tolist()[1] == 1.2
    # without lane_num / lanes the bike rule cannot tell, so a bike lane keeps the default
    assert _widths(g.drop(columns=["lane_num", "lanes"]), lane_settings()).tolist()[2] == 3.25


def test_several_modes_colour_a_road_cars_do_not_use_by_who_uses_it(tmp_path):
    """2026-10-09, one rule with the level editor: a lane of a road cars use keeps its use's colour (a street cars and pedestrians
    share is a car road, a bus lane keeps its own); a lane of a road cars do not use takes the colour of who uses it (a footway: walk).
    One mode: the lane's use."""
    from lanestyle.settings import _colour_groups, lane_settings
    gmns, src = _with_walking(tmp_path)
    lanes, turns = ls.from_gmns(gmns, modes=("driving", "walking"))
    r = lanes.set_index("lane_id")
    assert r.loc["2_1", "modes"] == "driving,walking" and r.loc["5_1", "modes"] == "walking" and r.loc["1_1", "modes"] == "driving"
    g = lanes.assign(use=lanes["use"].fillna("auto"))
    col, palette, rows = _colour_groups(g, lane_settings())
    c = dict(zip(g["lane_id"], g[col].map(palette), strict=True))
    assert (c["1_1"], c["1_2"], c["2_1"], c["5_1"]) == ("#a3a3a3", "#d6336c", "#a3a3a3", "#f0cb8c") and c["3_1"] == c["1_1"]
    assert "pedestrians only" in [label for label, _ in rows] and "car lanes" in [label for label, _ in rows]
    one = ls.from_gmns(gmns)[0]
    col1, _, rows1 = _colour_groups(one.assign(use=one["use"].fillna("auto")), lane_settings())
    assert col1 == "use" and "pedestrians only" not in [label for label, _ in rows1]

def test_a_footway_join_is_read_from_duckosms_walking_connectors_not_made_here(tmp_path):
    """The join of a footway to a road lane is data (duckOSM `gmns_walking.lane_connector`, docs/design/gmns_walk_joins.md): lanestyle keeps it when both its lanes are kept,
    as a footway's lane (its class, use and link), and invents none."""
    gmns, _ = _with_walking(tmp_path)
    assert not ls.from_gmns(gmns, modes=("driving", "walking"))[0]["connector"].any()      # no table: no connector
    con = duckdb.connect(str(gmns))
    con.execute("LOAD spatial; CREATE TABLE gmns_walking.lane_connector(connector_id VARCHAR, mvmt_id VARCHAR, from_lane_id VARCHAR, "
                "to_lane_id VARCHAR, width DOUBLE, geom GEOMETRY)")
    con.execute("INSERT INTO gmns_walking.lane_connector VALUES ('2_1>5_1', NULL, '2_1', '5_1', 2.0, ST_GeomFromText('LINESTRING(18.01 59.31, 18.011 59.335)')), "
                "('2_1>9_1', NULL, '2_1', '9_1', 2.0, ST_GeomFromText('LINESTRING(18.01 59.31, 18.012 59.335)'))")      # 9_1 is no lane
    con.close()
    lanes, _ = ls.from_gmns(gmns, modes=("driving", "walking"))
    c = lanes[lanes["connector"]].set_index("lane_id")
    assert list(c.index) == ["2_1>5_1"]
    f = lanes.set_index("lane_id").loc["5_1"]
    assert c.loc["2_1>5_1", "use"] == "walk" and c.loc["2_1>5_1", "highway"] == f["highway"] and c.loc["2_1>5_1", "link_id"] == f["link_id"]
    assert c.loc["2_1>5_1", "from_lane"] == "2_1" and c.loc["2_1>5_1", "width_m"] == 2.0


def _corner_gap_m(d=3.0, cw=1.5):
    """A lane going east, a lane going north and a narrow connector turning from one to the other (a left turn at a corner): the longest stretch of
    the drawn surface's boundary near the connector that has no outline line within 15 cm, in metres."""
    import math

    import geopandas as gpd
    import shapely
    from lanestyle.lines import lane_lines
    from shapely.geometry import LineString, Point

    kx = math.cos(math.radians(59.3))
    ll = lambda pts: LineString([(18.0 + x / (111320 * kx), 59.3 + y / 111320) for x, y in pts])      # noqa: E731  metres from (18.0, 59.3)
    t = [i / 8 for i in range(9)]
    turn = [(2 * (1 - u) * u * d + u ** 2 * d, u ** 2 * d) for u in t]   # (0,0) -> (d,d)
    rows = [dict(lane_id="a", link_id=1, lane_num=1, width_m=3.0, connector=False, from_node_id=1, to_node_id=2, highway="service", geometry=ll([(-20, 0), (0, 0)])),
            dict(lane_id="b", link_id=2, lane_num=1, width_m=3.0, connector=False, from_node_id=2, to_node_id=3, highway="service", geometry=ll([(d, d), (d, d + 20)])),
            dict(lane_id="c", link_id=3, lane_num=1, width_m=3.0, connector=False, from_node_id=2, to_node_id=4, highway="service", geometry=ll([(30, -30), (50, -30)])),   # a third link at node 2 (a junction: lane lines stop short of it), far from the corner
            dict(lane_id="a>b", link_id=1, lane_num=1, width_m=cw, connector=True, from_lane="a", to_lane="b", from_node_id=1, to_node_id=2, highway="service", geometry=ll(turn))]
    lanes = gpd.GeoDataFrame(rows, crs=4326)
    fc = lane_lines(lanes, ls.lane_settings())
    from shapely.geometry import shape
    to_m = lambda g: LineString([((x - 18.0) * 111320 * kx, (y - 59.3) * 111320) for x, y in g.coords])      # noqa: E731
    lines = shapely.union_all([to_m(q) for f in fc["features"] if f["properties"]["t"] == "edge" for q in getattr(shape(f["geometry"]), "geoms", [shape(f["geometry"])])])
    surface = shapely.union_all([Point(0, 0).buffer(1.5), Point(d, d).buffer(1.5), LineString([(-20, 0), (0, 0)]).buffer(1.5, cap_style="flat"),
                                 LineString([(d, d), (d, d + 20)]).buffer(1.5, cap_style="flat"), LineString(turn).buffer(cw / 2)])
    near = surface.boundary.intersection(Point(d / 2, d / 2).buffer(2.5))
    pts = [near.interpolate(i / 10) for i in range(int(near.length * 10))]
    bare = [p for p in pts if lines.distance(p) > 0.15]
    return len(bare) / 10                                   # metres of boundary with no line


def test_a_roundabouts_ring_is_read_from_the_source_junction_tag(tmp_path):
    import duckdb

    from lanestyle.gmns import _ring_links

    db = tmp_path / "src.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE SCHEMA driving; CREATE TABLE driving.edges (edge_id BIGINT, junction VARCHAR)")
    con.execute("INSERT INTO driving.edges VALUES (1, 'roundabout'), (2, NULL), (3, 'circular')")
    con.close()
    assert sorted(_ring_links(db, "driving")) == [1, 3] and _ring_links(None, "driving") == []


def test_walkers_stepping_off_a_road_are_no_turn_of_the_car_lane(tmp_path):
    """Kaveh (2026-10-03, lane 8804188488117379077_1): the walking mode's movement from a road onto a footway gave the car lane a left / right turn (1,443 of 8,502 car-lane turns in Monaco).
    A later mode's movement that starts on an earlier mode's lane is dropped; the footway's own movements stay."""
    gmns, _ = _with_walking(tmp_path)
    con = duckdb.connect(str(gmns))
    con.execute("INSERT INTO gmns_walking.movement VALUES (2,NULL,NULL,5,NULL,NULL,'left')")      # the road onto the footway
    con.close()
    lanes, turns = ls.from_gmns(gmns, modes=("driving", "walking"))
    own = turns[~turns["walkers"].astype(bool)]                    # the row stays (flagged `walkers`: it orders the footway's join), but is no turn of the car lane
    pairs = set(zip(own["from_lane"], own["to_lane"]))
    assert ("2_1", "5_1") not in pairs and ("5_1", "2_1") in pairs
    assert set(zip(turns[turns["walkers"].astype(bool)]["from_lane"], turns[turns["walkers"].astype(bool)]["to_lane"])) == {("2_1", "5_1")}

