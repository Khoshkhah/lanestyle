"""Tests for lanestyle — standalone lane-level maps (no mapstyle dependency)."""
import sys

import duckdb
import pytest

from lanestyle.core import lane_gdf, render_lane_debug, render_lane_map, road_gdf, write_serve


def test_no_mapstyle_dependency():
    # lanestyle must be fully standalone — importing it must not pull mapstyle in
    import lanestyle  # noqa: F401
    assert "mapstyle" not in sys.modules


def _gmns_db(path):
    """A minimal GMNS db: gmns_driving.lane (auto + bus) + link (a named two-way road + a one-way)."""
    con = duckdb.connect(str(path))
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute("CREATE SCHEMA gmns_driving")
    p = "ST_GeomFromText('LINESTRING(18.06 59.32, 18.07 59.32)')"
    con.execute("CREATE TABLE gmns_driving.lane(lane_id VARCHAR, link_id BIGINT, lane_num INTEGER, "
                "allowed_uses VARCHAR, width DOUBLE, geom GEOMETRY)")
    con.execute(f"INSERT INTO gmns_driving.lane VALUES ('1_1',1,1,'auto',3.25,{p}),('1_2',1,2,'bus',3.25,{p})")
    con.execute("CREATE TABLE gmns_driving.link(link_id BIGINT, name VARCHAR, from_node_id BIGINT, "
                "to_node_id BIGINT, geom GEOMETRY)")
    con.execute(f"INSERT INTO gmns_driving.link VALUES (1,'Main St',10,11,{p}),(2,'Main St',11,10,{p}),"
                f"(3,'One Way',11,12,{p})")   # 1<->2 two-way (Main St), 3 one-way
    con.close()
    return path


def test_lane_gdf(tmp_path):
    gdf = lane_gdf(str(_gmns_db(tmp_path / "g.duckdb")))
    assert {"use", "lane", "edge_id", "width"}.issubset(gdf.columns)
    assert (gdf.geometry.geom_type == "Polygon").all() and gdf.crs.to_epsg() == 4326
    assert set(gdf["use"]) == {"auto", "bus"}


def test_road_gdf_oneway(tmp_path):
    roads = road_gdf(str(_gmns_db(tmp_path / "g.duckdb")))
    assert set(roads["name"]) == {"Main St", "One Way"}
    ow = dict(zip(roads["name"], roads["oneway"]))
    assert ow["One Way"] is True and ow["Main St"] is False        # 1<->2 pair → two-way; 3 → one-way


def test_render_lane_map_webgl(tmp_path):
    out = tmp_path / "lanes.html"
    render_lane_map(str(_gmns_db(tmp_path / "g.duckdb")), out)      # webgl by default
    html = out.read_text().lower()
    assert out.exists() and "lanes_auto" in html and "deck.gl" in html and "maplibre" in html


def test_render_lane_map_folium(tmp_path):
    out = tmp_path / "lanes_f.html"
    render_lane_map(str(_gmns_db(tmp_path / "g.duckdb")), out, backend="folium")
    assert "leaflet" in out.read_text().lower()                     # folium backend still available


def test_render_lane_debug_webgl(tmp_path):
    out = tmp_path / "debug.html"
    render_lane_debug(str(_gmns_db(tmp_path / "g.duckdb")), out)
    html = out.read_text()
    assert "edge_id" in html                                       # click-inspect fields
    assert "osm-carto" in html and "satellite" in html             # base-layer selector
    assert "Main St" in html or "One Way" in html                  # street names in the data
    assert "one-way arrows" in html                                # arrows toggle
    assert (tmp_path / "serve.py").exists()


def test_serve_py(tmp_path):
    out = tmp_path / "lanes.html"
    render_lane_map(str(_gmns_db(tmp_path / "g.duckdb")), out)
    src = (tmp_path / "serve.py").read_text()
    assert "lanes.html" in src and "http.server" in src
    compile(src, "serve.py", "exec")


def test_bad_db_raises(tmp_path):
    bare = tmp_path / "bare.duckdb"
    duckdb.connect(str(bare)).close()
    with pytest.raises(ValueError, match="lane"):
        lane_gdf(str(bare))
