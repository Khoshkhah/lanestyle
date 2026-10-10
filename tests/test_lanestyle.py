import pytest
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


def test_render_lanes_metre_widths_uses_and_click(tmp_path):
    gmns, src = _dbs(tmp_path)
    lanes, turns = ls.from_gmns(gmns, source_db=src)
    html = ls.render_lanes(lanes, turns=turns).html
    assert '"__rs_wm"' in html                                    # widths in metres (roadstyle 0.10)
    assert {p["color"] for p in _lane_props(html).values()} == {"#a3a3a3", "#d6336c"}   # cars and a bus lane: no bike (the colour is the lane's own, "Lane use" is no roadstyle colouring any more)
    assert "#1c7ed6" not in html
    # every lane is coloured by its mode group: a row each in the Roads box (cars first), no dropdown
    assert '[["car lanes", "#a3a3a3"], ["bus lanes", "#d6336c"]]' in html and ".co-ctrl,.co-lg{display:none" in html
    t = json.loads(html.split("const T = ", 1)[1].split(", C = ", 1)[0])
    assert t["1_1"] == [["2_1"], ["3_1"]] and t["1_2"] == [["2_1"], []]


def test_settings_override_the_roadstyle_way(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "lanestyle.json").write_text('{"lanes": {"casing_m": 0.1}}')
    s = ls.lane_settings({"lanes": {"colors": {"bus": "#123456"}}})
    assert s["casing_m"] == 0.1 and s["colors"]["bus"] == "#123456" and s["colors"]["bike"] == "#1c7ed6"


def test_write_serve_index_html_does_not_loop(tmp_path):
    src = ls.write_serve(tmp_path / "index.html").read_text()
    assert 'self.path != "/index.html"' in src and '"Cache-Control", "no-store"' in src


def test_loop_halves_are_not_a_two_way_pair(tmp_path):
    """A one-way loop split in two (A->B, B->A, different geometry, Monaco way 120113154) is not a
    reverse pair: no reverse_link_id, so no centre line, and roadstyle doesn't pair them either."""
    gmns = tmp_path / "loop.duckdb"
    con = duckdb.connect(str(gmns))
    con.execute("INSTALL spatial; LOAD spatial; CREATE SCHEMA gmns_driving")
    con.execute("CREATE TABLE gmns_driving.link(link_id BIGINT, name VARCHAR, facility_type VARCHAR, "
                "from_node_id BIGINT, to_node_id BIGINT, geom GEOMETRY)")
    con.execute("CREATE TABLE gmns_driving.lane(lane_id VARCHAR, link_id BIGINT, lane_num BIGINT, "
                "allowed_uses VARCHAR, width DOUBLE, turn VARCHAR, geom GEOMETRY)")
    north = "ST_GeomFromText('LINESTRING(7.418 43.738, 7.4185 43.7384, 7.419 43.738)')"
    south = "ST_GeomFromText('LINESTRING(7.419 43.738, 7.4185 43.7376, 7.418 43.738)')"
    con.execute(f"INSERT INTO gmns_driving.link VALUES (1,NULL,'service',10,11,{north}),(2,NULL,'service',11,10,{south})")
    con.execute(f"INSERT INTO gmns_driving.lane VALUES ('1_1',1,1,'auto',NULL,NULL,{north}),('2_1',2,1,'auto',NULL,NULL,{south})")
    con.close()
    lanes, _ = ls.from_gmns(gmns)
    assert lanes["reverse_link_id"].isna().all()
    html = ls.render_lanes(lanes).html
    feats = json.loads(html.split("const style = ", 1)[1].split(", BASEMAPS", 1)[0])["sources"]["roads"]["data"]["features"]
    assert not any(f["properties"].get("__rs_twoway") for f in feats)


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


def test_lane_type_labels(tmp_path):
    """Each lane carries what it's for (the turns leaving it, 'end' where none does, the use first for a bus
    lane) in its popup data; the labels along the lanes are off unless ``type_label_zoom`` is set."""
    gmns, src = _dbs(tmp_path)
    lanes, turns = ls.from_gmns(gmns, source_db=src)
    html = ls.render_lanes(lanes, turns=turns).html
    t = {k: p["lane_type"] for k, p in _lane_props(html).items()}
    assert t == {"1_1": "U-turn + thru", "1_2": "bus · thru", "2_1": "end", "3_1": "end"}      # in the popup's data
    assert "lane-type-labels" not in html                         # but not drawn along the lanes by default
    assert '"lane-type-labels"' in ls.render_lanes(lanes, turns=turns, settings={"lanes": {"type_label_zoom": 18}}).html


def test_lane_connectors_drawn_and_coloured(tmp_path):
    """duckOSM's lane_connector rows become drawn connectors: the leaving lane's road class, no arrows,
    no type label, and coloured with the lane they lead into when a lane is clicked."""
    gmns, src = _dbs(tmp_path)
    con = duckdb.connect(str(gmns))
    con.execute("LOAD spatial; CREATE TABLE gmns_driving.lane_connector(connector_id VARCHAR, mvmt_id VARCHAR, "
                "from_lane_id VARCHAR, to_lane_id VARCHAR, width DOUBLE, geom GEOMETRY)")
    con.execute("INSERT INTO gmns_driving.lane_connector VALUES ('1_1>2_1', 'm', '1_1', '2_1', 3.25, "
                "ST_GeomFromText('LINESTRING(18.01 59.30, 18.011 59.305, 18.00 59.31)'))")
    con.close()
    lanes, turns = ls.from_gmns(gmns, source_db=src)
    c = lanes.set_index("lane_id").loc["1_1>2_1"]
    assert bool(c["connector"]) and c["highway"] == "secondary" and c["from_lane"] == "1_1"
    html = ls.render_lanes(lanes, turns=turns, settings={"lanes": {"arrows": False}}).html     # roadstyle's chevrons: on a lane, not on a connector
    assert "1_1>2_1" not in _lane_props(html) and "1_1" in _lane_props(html)        # a connector is its own overlay, under the lanes: not a lane
    assert not _page(html)[1].get("lane arrows")                                    # arrows off: none on a lane, none on a connector
    p = _lane_props(html, "connectors")
    assert p["1_1>2_1"]["order"] == -1 and p["1_1>2_1"]["road_id"] == _lane_props(html)["1_1"]["road_id"]     # drawn on the road of the lane it leaves
    assert p["1_1>2_1"]["lane_type"] == "connector · thru"
    assert p["1_1>2_1"]["connects"] == "lane 1 of Main St → lane 1 of Bridge Rd"
    assert _lane_props(html)["1_1"].get("connects") in (None, "")                   # a lane connects nothing: no literal 'nan'
    lp = _lane_props(html)["1_1"]
    assert all(isinstance(lp[k], int) for k in ("casing head start", "casing body", "casing head end", "fill"))     # the popup shows the link's four numbers, whole
    t = json.loads(html.split("const T = ", 1)[1].split(", C = ", 1)[0])
    assert "1_1>2_1" in t["1_1"][0]
    assert "line-cap" not in html.split("</body>")[0].split("const T = ")[-1]   # lane ends stay round, tunnels too


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
    lanes, turns = ls.from_gmns(gmns, source_db=src)
    st = json.loads(ls.render_lanes(lanes, turns=turns, boundary=b).html.split("const style = ", 1)[1].split(", BASEMAPS", 1)[0])
    assert "boundary" in st["sources"] and any(l["id"] == "boundary" for l in st["layers"])


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


def test_the_popup_always_says_the_level(tmp_path):
    """A ground lane would otherwise show nothing about bridges (null fields are hidden): `level` says ground / bridge."""
    gmns, src = _dbs(tmp_path)
    lanes, turns = ls.from_gmns(gmns, source_db=src)
    html = ls.render_lanes(lanes, turns=turns).html
    assert '"level"' in html and '"bridge"' in html and '"ground"' in html     # link 2 is a bridge, the others ground


def test_the_popup_names_the_twin_of_a_link(tmp_path):
    """Links 1 and 3 are one two-way road: each says the other is its twin; the one-way bridge (link 2) has none."""
    gmns, src = _dbs(tmp_path)
    lanes, turns = ls.from_gmns(gmns, source_db=src)
    html = ls.render_lanes(lanes, turns=turns).html
    assert "(reverse: the same line)" in html and '"twin"' in html


def _crossing(lane_id="2_1", painted=True, to_left=True, start=200.0, end=203.0):
    """A crossing table row for road 2 (east-west at y = 59.31): the zebra's rectangle, 3 m along the road, 6.5 m across it."""
    import pandas as pd

    x = 18.0 + (start + end) / 2 / 56700
    dx, dy = 1.5 / 56700, 3.25 / 111320
    rect = f"POLYGON (({x + dx} {59.31 - dy}, {x + dx} {59.31 + dy}, {x - dx} {59.31 + dy}, {x - dx} {59.31 - dy}, {x + dx} {59.31 - dy}))"
    return pd.DataFrame({"crossing_id": ["w1"], "lane_id": [lane_id], "start_lr": [start], "end_lr": [end], "across_from": [1.6],
                         "across_to": [4.85], "to_left": [to_left], "painted": [painted], "length": [6.5],
                         "crossing_type": ["marked"], "source": ["way"], "cgeom": [rect]})


def test_a_zebra_is_one_rectangle_cut_into_stripes_parallel_to_the_lanes(tmp_path):
    """The crossing's rectangle (3 m along the road, 6.5 m across) cut into stripes, each long along the road (x) and stripe_m thin across it (y): every stripe of the rectangle, not clipped to the
    lanes (the table names a 3.25 m lane across 1.6 .. 4.85, and the zebra still has all seven stripes of its 6.5 m)."""
    from lanestyle.render import _zebra_stripes

    gmns, _ = _with_walking(tmp_path)
    lanes, _t = ls.from_gmns(gmns, modes=("driving", "walking"))
    lanes["width_m"] = lanes["width_m"].fillna(3.25)
    st = ls.lane_settings()["zebra"]
    rings, links, foot = _zebra_stripes(lanes, _crossing(), st)
    assert len(rings) == 7                                         # 6.5 m across: stripes 0.5 m every 1.0 m, the row centred
    for ring in rings:
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        assert (max(xs) - min(xs)) * 56700 == pytest.approx(3.0, abs=0.05)         # as long as the zebra is wide
        assert (max(ys) - min(ys)) * 111320 == pytest.approx(0.5, abs=0.05)        # one stripe across it
    ys = sorted(sum(p[1] for p in r) / len(r) for r in rings)
    assert all(abs((ys[i + 1] - ys[i]) * 111320 - 1.0) < 0.05 for i in range(6))     # equally spaced: cut from one rectangle
    assert foot is not None and foot.geom_type == "Polygon" and len(links) == len(rings)
    assert _zebra_stripes(lanes, _crossing(painted=False), st) == ([], [], None)       # unpainted: none


def test_a_stripe_belongs_to_the_road_of_the_lane_under_it(tmp_path):
    """Two lanes of two links named by one crossing (across 0 .. 3.25 and 3.25 .. 6.5): the stripes in the first half belong to the first link, the rest to the second."""
    import pandas as pd

    from lanestyle.render import _zebra_stripes

    gmns, _ = _with_walking(tmp_path)
    lanes, _t = ls.from_gmns(gmns, modes=("driving", "walking"))
    lanes["width_m"] = lanes["width_m"].fillna(3.25)
    road = lanes[lanes["lane_id"].isin(["1_1", "2_1"])]["lane_id"].tolist()
    two = pd.concat([_crossing(road[0]), _crossing(road[1])], ignore_index=True)
    two.loc[0, ["across_from", "across_to"]] = [0.0, 3.25]
    two.loc[1, ["across_from", "across_to"]] = [3.25, 6.5]
    rings, links, _ = _zebra_stripes(lanes, two, ls.lane_settings()["zebra"])
    ys = [sum(p[1] for p in r) / len(r) for r in rings]
    order = [lk for _, lk in sorted(zip(ys, links))]
    link_a, link_b = {str(lanes.set_index("lane_id").loc[l, "link_id"]) for l in road[:1]}.pop(), {str(lanes.set_index("lane_id").loc[l, "link_id"]) for l in road[1:]}.pop()
    assert {str(x) for x in order[:3]} == {link_a} and {str(x) for x in order[-3:]} == {link_b}, order


def test_a_painted_crossing_adds_the_zebra_layer_and_the_crossing_way_stays_under_the_road(tmp_path):
    gmns, _ = _with_walking(tmp_path)
    lanes, turns = ls.from_gmns(gmns, modes=("driving", "walking"))
    lanes["footway"] = None
    lanes.loc[lanes["lane_id"] == "5_1", "footway"] = "crossing"
    html = ls.render_lanes(lanes, turns=turns, crossings=_crossing()).html
    zebras = _page(html)[1].get("zebra crossings")
    assert zebras and all(z["order"] == 2 and "road_id" in z for z in zebras) and '"band_col"' not in html and "draw_band" not in html
    assert "zebra crossings" not in _page(ls.render_lanes(lanes, turns=turns, crossings=_crossing(painted=False)).html)[1]
    assert "zebra crossings" not in _page(ls.render_lanes(lanes, turns=turns).html)[1]


def test_no_lane_line_under_a_zebra_crossing():
    """The zebra's stripes are the road's marking there: the lane lines (dashes, centre, edges) stop at its stretch."""
    import geopandas as gpd
    from shapely.geometry import LineString, box

    from lanestyle.lines import lane_lines

    rows = [("a1", 1, 1, [(18.000, 59.3), (18.001, 59.3)]), ("a2", 1, 2, [(18.000, 59.29997), (18.001, 59.29997)])]
    lanes = gpd.GeoDataFrame({"lane_id": [r[0] for r in rows], "link_id": [r[1] for r in rows], "lane_num": [r[2] for r in rows],
                              "use": "auto", "width_m": 3.25}, geometry=[LineString(r[3]) for r in rows], crs=4326)
    avoid = box(18.0004, 59.2998, 18.0006, 59.3002)                      # a 2e-4 deg zebra square over both lanes
    xs = [x for f in lane_lines(lanes, ls.lane_settings(), avoid=avoid)["features"]
          for line in ([f["geometry"]["coordinates"]] if f["geometry"]["type"] == "LineString" else f["geometry"]["coordinates"]) for x, _ in line]
    assert xs and not any(18.0004 < x < 18.0006 for x in xs)


def test_a_link_with_no_road_class_is_not_drawn(tmp_path):
    """A ferry in the walking network has no road class (highway null): it is no lane."""
    from lanestyle.render import _roads_only

    gmns, _ = _with_walking(tmp_path)
    lanes, turns = ls.from_gmns(gmns, modes=("driving", "walking"))
    lanes.loc[lanes["lane_id"] == "5_1", "highway"] = None
    kept = set(_roads_only(lanes)["lane_id"])
    assert "5_1" not in kept and "1_1" in kept and len(kept) == len(lanes) - 1
    ls.render_lanes(lanes, turns=turns)                                       # and the map still renders


def test_the_popup_says_what_a_footway_is(tmp_path):
    """highway=footway + footway=crossing is a crosswalk, not "a footway": a `kind` row says so (and sidewalk for a sidewalk)."""
    gmns, _ = _with_walking(tmp_path)
    lanes, turns = ls.from_gmns(gmns, modes=("driving", "walking"))
    lanes["footway"] = None
    lanes["crossing"] = None
    lanes.loc[lanes["lane_id"] == "5_1", ["footway", "crossing"]] = ["crossing", "marked"]
    html = ls.render_lanes(lanes, turns=turns, settings={"lanes": {"crossing_max_m": 0}}).html     # (a crossing off every road is demoted: next test)
    assert '"kind"' in html and "crosswalk (marked)" in html


def test_a_crossing_that_is_mostly_off_the_road_is_drawn_as_a_footway(tmp_path):
    """OSM tags a whole 173 m way footway=crossing where only its end crosses (1342546079): a long link with almost nothing on a road is a footway."""
    gmns, _ = _with_walking(tmp_path)
    lanes, turns = ls.from_gmns(gmns, modes=("driving", "walking"))
    lanes["footway"] = None
    lanes["crossing"] = None
    lanes.loc[lanes["lane_id"] == "5_1", ["footway", "crossing"]] = ["crossing", "marked"]
    from lanestyle.render import _demote_crossings
    g = lanes.copy()
    g["demoted"] = None
    _demote_crossings(g, {"crossing_max_m": 0.1, "crossing_min_on": 0.2})                # any length counts as long here
    assert g.loc[g["lane_id"] == "5_1", "footway"].isna().all() and "OSM tags it a crossing" in g.loc[g["lane_id"] == "5_1", "demoted"].iloc[0]
    g = lanes.copy()
    g["demoted"] = None
    _demote_crossings(g, {"crossing_max_m": 1e6, "crossing_min_on": 0.2})                # a short one stays a crosswalk
    assert (g.loc[g["lane_id"] == "5_1", "footway"] == "crossing").all()


def test_default_widths_by_use():
    import pandas as pd
    from lanestyle.render import _widths, lane_settings
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
    One mode: the lane's use, as before."""
    gmns, src = _with_walking(tmp_path)
    lanes, turns = ls.from_gmns(gmns, modes=("driving", "walking"))
    r = lanes.set_index("lane_id")
    assert r.loc["2_1", "modes"] == "driving,walking" and r.loc["5_1", "modes"] == "walking"   # link 2 is in both networks
    assert r.loc["1_1", "modes"] == "driving"
    html = ls.render_lanes(lanes, turns=turns).html
    for row in ("car lanes", "bus lanes", "pedestrians only"):
        assert row in html, row
    assert "cars + pedestrians" not in html
    c = {k: p["color"] for k, p in _lane_props(html).items()}
    cars, bus, both, walk = c["1_1"], c["1_2"], c["2_1"], c["5_1"]
    assert (cars, bus, both, walk) == ("#a3a3a3", "#d6336c", "#a3a3a3", "#f0cb8c") and c["3_1"] == cars
    single = ls.render_lanes(*ls.from_gmns(gmns)).html                      # one mode: by use
    assert "pedestrians only" not in single and "car lanes" in single


def test_a_tunnel_is_one_whole_lane_in_its_band_and_a_bridge_keeps_its_look(tmp_path):
    """roadstyle's levels and looks: the level alone decides the band, so a tunnel lane is drawn whole, under the
    ground lanes, with its own look (no stretches to hide its arrows and lane lines); a bridge keeps its deck look."""
    gmns, src = _dbs(tmp_path)
    html = ls.render_lanes(*ls.from_gmns(gmns, source_db=src)).html
    style = json.loads(html.split("const style = ", 1)[1].split(", BASEMAPS", 1)[0])
    p = {f["properties"]["edge_id"]: f["properties"] for f in style["sources"]["roads"]["data"]["features"]}      # the roads: one per link, lane 2_1 is on road 2
    assert p[2]["lvl"] == 1 and p[2]["__rs_bridge"] and not p[2]["__rs_tunnel"]    # the bridge: its look
    assert "tpieces" not in style["sources"]                       # nothing cut into stretches
    assert "moveLayer" not in html.split("const T = ")[-1]         # and no arrow workaround


def test_every_lane_is_coloured_by_its_mode_group(tmp_path):
    gmns, src = _dbs(tmp_path)
    html = ls.render_lanes(*ls.from_gmns(gmns, source_db=src)).html
    lanes = _page(html)[1]["lanes"]
    assert {p["color"] for p in lanes} == {"#a3a3a3", "#d6336c"}   # cars have their own colour, not the class's (the lane's colour is its item's `color`)
    assert all(p["color"] for p in lanes)                          # and every lane has one from the start: no "colour by" choice to open with


def test_a_footpath_has_no_arrow_and_a_tunnel_is_as_opaque_as_a_road(tmp_path):
    gmns, src = _with_walking(tmp_path)
    html = ls.render_lanes(*ls.from_gmns(gmns, modes=("driving", "walking"))).html
    lanes = _lane_props(html)
    arrowed = {p["edge_id"] for p in _page(html)[1]["lane marks"]}                       # the painted arrows are items of their lane's link
    assert arrowed and lanes["5_1"]["edge_id"] not in arrowed       # walk: none; roads: yes, where their link ends at a junction (at_junctions, 2026-10-10)


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


def test_a_tunnel_differs_from_ground_in_look_only(tmp_path):
    """Kaveh (2026-10-02, said several times): the only difference of a tunnel is its colour and pattern. The same lane table at ground level and as a tunnel
    (every lane layer -1, tunnel yes) gives the same outlines, lane lines and gap fills, the same footpaths drawn above roads and the same draw order: only the level label differs."""
    from lanestyle.frames import frames
    from lanestyle.lines import lane_lines
    from lanestyle.render import _footpaths_on_roads, _widths

    gmns, _ = _with_walking(tmp_path)
    s = ls.lane_settings()
    ground, _ = ls.from_gmns(gmns, modes=("driving", "walking"))
    ground["use"] = ground["use"].fillna("auto")
    ground["width_m"] = _widths(ground, s)
    tunnel = ground.copy()
    tunnel["layer"], tunnel["tunnel"] = "-1", "yes"

    def shape(fc):                                                   # the lines without their level label
        return sorted((f["properties"]["t"], str(f["geometry"])) for f in (fc or {"features": []})["features"])
    assert {f["properties"]["b"] for f in lane_lines(ground, s)["features"]} <= {"ground"}
    assert {f["properties"]["b"] for f in lane_lines(tunnel, s)["features"]} == {"low"}
    assert shape(lane_lines(ground, s)) == shape(lane_lines(tunnel, s))
    gg, _, _ = frames(ground, s)
    gt, _, _ = frames(tunnel, s)
    assert [f["geometry"] for f in (gg or {"features": []})["features"]] == [f["geometry"] for f in (gt or {"features": []})["features"]]
    assert _footpaths_on_roads(ground) == _footpaths_on_roads(tunnel)


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


def test_the_roads_box_has_no_road_class_rows(tmp_path):
    """The Roads filter box lists the lane uses and Bridges / Tunnels, not roadstyle's highway classes (Kaveh, 2026-10-02)."""
    gmns, src = _dbs(tmp_path)
    html = ls.render_lanes(*ls.from_gmns(gmns, source_db=src)).html
    assert 'label:not(.ls-use):not(.flt-grade)' in html and 'l.style.display = "none"' in html


def test_a_hole_the_road_encloses_is_paved():
    """Four lanes in a square loop leave a 0.3 m square hole between their surfaces: it is under the 0.3 m2 / 24 cm rule of the closing, and was left white
    (a slit between a connector and a lane end at Monaco's dead-end spurs). An enclosed hole is never a real feature: it gets a fillet."""
    import math

    import geopandas as gpd
    from lanestyle.junctions import junction_fillets
    from shapely.geometry import LineString, Point

    kx = math.cos(math.radians(59.3))
    ll = lambda pts: LineString([(18.0 + x / (111320 * kx), 59.3 + y / 111320) for x, y in pts])      # noqa: E731
    side = 3.3                                            # lane width 3.0: the hole between the four surfaces is 0.3 m square
    rows = [dict(lane_id=str(i), width_m=3.0, highway="service", geometry=ll(seg))
            for i, seg in enumerate([[(0, 0), (side, 0)], [(side, 0), (side, side)], [(side, side), (0, side)], [(0, side), (0, 0)]])]
    f = junction_fillets(gpd.GeoDataFrame(rows, crs=4326), ls.lane_settings())
    assert f is not None
    centre = Point(18.0 + (side / 2) / (111320 * kx), 59.3 + (side / 2) / 111320)
    from shapely.geometry import shape
    assert any(shape(x["geometry"]).contains(centre) for x in f["features"])


def test_every_lane_gets_one_arrow_and_a_long_one_repeats():
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import LineString

    from lanestyle.arrows import lane_arrows

    # three lanes going north, 40 m: left + thru, thru, fork (a fork is shape: the plain direction arrow, no move arrow)
    lane = lambda i, n=40: dict(lane_id=str(i), link_id=1, lane_num=i, use="auto", width_m=3.25, connector=False,   # noqa: E731
                                geometry=LineString([(7.4 + i * 4e-5, 43.7), (7.4 + i * 4e-5, 43.7 + n / 111000)]))
    g = gpd.GeoDataFrame([lane(1), lane(2), lane(3)], crs=4326)
    t = pd.DataFrame({"from_lane": ["1", "1", "2", "3"], "to_lane": list("abcd"), "type": ["left", "thru", "thru", "diverge"]})
    s = {"length_m": 4, "end_m": 10, "repeat_m": 60}
    area = lambda f: __import__("shapely.geometry", fromlist=["shape"]).shape(f["geometry"]).area   # noqa: E731
    fc = lane_arrows(g, t, s)
    assert len(fc["features"]) == 3                                  # one each
    assert area(fc["features"][0]) > 1.2 * area(fc["features"][2])   # left + thru is bigger than the plain arrow of the fork
    assert len(lane_arrows(g, None, s)["features"]) == 3             # no turns table: still every lane's direction
    long = gpd.GeoDataFrame([lane(1, 200)], crs=4326)
    assert len(lane_arrows(long, None, s)["features"]) == 4          # the end arrow (190 m) and repeats 60 m apart (130, 70, 10)


def test_painted_arrows_are_the_one_direction_marking():
    gmns, src = _dbs(__import__("pathlib").Path(__import__("tempfile").mkdtemp()))
    html = ls.render_lanes(*ls.from_gmns(gmns, source_db=src)).html
    style, ov = _page(html)
    assert not any(f["properties"].get("oneway") for f in style["sources"]["roads"]["data"]["features"]) and ov["lane marks"]     # roadstyle's chevrons off, ours on (strokes)
    assert not any("arrow" in lyr["id"] and lyr["id"].startswith("roads") for lyr in style["layers"])


def test_street_names_go_clear_of_the_arrows():
    import geopandas as gpd
    from shapely.geometry import LineString, box

    from lanestyle.street_names import street_names

    # one 100 m one-way link going north with a name; an arrow at its middle: the name's line is cut there
    n = 100 / 111000
    g = gpd.GeoDataFrame([dict(lane_id="1", link_id=1, lane_num=1, use="auto", width_m=3.25, connector=False, name="Rue X",
                               geometry=LineString([(7.4, 43.7), (7.4, 43.7 + n)]))], crs=4326)
    s = {"clear_m": 3}
    whole = street_names(g, None, s)
    assert len(whole["features"]) == 1
    mid = 43.7 + n / 2
    arrow = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": {
        "type": "Polygon", "coordinates": [[[7.39999, mid - 2e-5], [7.40001, mid - 2e-5], [7.40001, mid + 2e-5], [7.39999, mid + 2e-5], [7.39999, mid - 2e-5]]]}}]}
    cut = street_names(g, arrow, s)
    assert len(cut["features"]) == 2 and cut["features"][0]["properties"]["name"] == "Rue X"


def test_an_arrow_slides_clear_of_a_zebra():
    import geopandas as gpd
    from shapely.geometry import LineString, box

    from lanestyle.arrows import lane_arrows

    n = 100 / 111000                                                  # one 100 m lane north, its arrow at 90 m
    g = gpd.GeoDataFrame([dict(lane_id="1", link_id=1, lane_num=1, use="auto", width_m=3.25, connector=False,
                               geometry=LineString([(7.4, 43.7), (7.4, 43.7 + n)]))], crs=4326)
    s = {"length_m": 4, "end_m": 10, "repeat_m": 0}
    top = lambda fc: max(y for f in fc["features"] for _, y in f["geometry"]["coordinates"][0])   # noqa: E731
    z = box(7.3999, 43.7 + 80 / 111000, 7.4001, 43.7 + 92 / 111000)    # a zebra over metres 80 to 92
    assert top(lane_arrows(g, None, s, avoid=z)) < 43.7 + 80 / 111000   # slid back below it
    assert top(lane_arrows(g, None, s)) > 43.7 + 80 / 111000


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


def test_a_forking_lane_gets_the_arrow_its_movement_codes_say():
    """docs/design/lane_arrows.md: a lane whose moves are all ``diverge`` has the arrow of the turn letters of their codes (``turn``, from duckOSM's ``mvmt_code``): left + thru is the combined arrow; thru alone stays the plain one."""
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import LineString

    from lanestyle.arrows import lane_arrows

    m = 1 / 111320
    lanes = gpd.GeoDataFrame({"lane_id": ["1_1", "1_2"], "link_id": [1, 1], "use": ["auto"] * 2, "width_m": [3.25] * 2, "layer": [None] * 2, "bridge": [None] * 2, "tunnel": [None] * 2},
                             geometry=[LineString([(18.0, 59.0), (18.0, 59.0 + 40 * m)]), LineString([(18.00005, 59.0), (18.00005, 59.0 + 40 * m)])], crs=4326)
    s = {"length_m": 4, "end_m": 10, "repeat_m": 60}
    plain = pd.DataFrame({"from_lane": ["1_1", "1_1"], "to_lane": ["2_1", "3_1"], "type": ["diverge", "diverge"], "turn": [None, None]})
    fork = pd.DataFrame({"from_lane": ["1_1", "1_1"], "to_lane": ["2_1", "3_1"], "type": ["diverge", "diverge"], "turn": ["thru", "left"]})
    area = lambda t: max(shape(f["geometry"]).area for f in lane_arrows(lanes, t, s)["features"])      # noqa: E731
    from shapely.geometry import shape
    assert area(fork) > 1.3 * area(plain)                                  # the combined arrow has a branch
    assert area(pd.DataFrame({**plain.to_dict("list"), "turn": ["thru", "thru"]})) == area(plain)      # every branch straight: the plain arrow
