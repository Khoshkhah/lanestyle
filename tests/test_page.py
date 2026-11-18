"""The editor's hook and the lane page through the Python package (the Rust engine draws). The rules themselves are tested in Rust
(rust/lanestyle/tests/rules.rs) and against the Python goldens (rust/lanestyle/examples/golden.rs)."""
from test_lanestyle import _dbs

import lanestyle as ls


def _unpacked(html):
    """The page's text with each gzipped part (base64) unpacked."""
    import base64
    import gzip
    import re

    return html + "".join(gzip.decompress(base64.b64decode(m)).decode() for m in re.findall(r'(H4sI[A-Za-z0-9+/=]+)', html))


def test_the_level_editor_hook_puts_each_lane_on_its_edge_of_the_editor(tmp_path, monkeypatch, capsys):
    """lanestyle.editor.lane_items (roadstyle's level editor ``--items``): each road one line at its full width (single_line_classes), in the
    car lane colour; the lanes, lines and marks of the GMNS file as the road's own items (render items=, no overlay; a link is a duckOSM edge:
    ``edge`` = its ``edge_id``), each labelled with its road, the lanes picked, the bus and bike lanes drawn, the car lanes unseen, no
    connectors; a link that is no edge of the editor is left out and said (2026-10-10)."""
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import LineString

    from lanestyle import editor
    gmns, src = _dbs(tmp_path)
    monkeypatch.setenv("LANESTYLE_GMNS", str(gmns))
    monkeypatch.setenv("LANESTYLE_SOURCE_DB", str(src))
    lanes, _ = ls.from_gmns(gmns, source_db=src)
    links = sorted({str(k) for k in lanes[~lanes["connector"].fillna(False).astype(bool)]["link_id"]} if "connector" in lanes else {str(k) for k in lanes["link_id"]})
    monkeypatch.delenv("LANESTYLE_CASING_COLOR", raising=False)
    monkeypatch.delenv("LANESTYLE_CONNECTORS", raising=False)
    drawn = gpd.GeoDataFrame({"edge": links[1:], "road": ["r" + x for x in links[1:]], "highway": "residential", "modes": "driving + walking"},
                             geometry=[LineString([(0, 0), (1, 1)])] * (len(links) - 1), crs=4326)
    foot = gpd.GeoDataFrame({"edge": ["999"], "road": ["foot"], "highway": ["footway"], "modes": ["walking (private)"]}, geometry=[LineString([(0, 0), (1, 0)])], crs=4326)
    drawn = gpd.GeoDataFrame(pd.concat([drawn, foot], ignore_index=True), crs=4326)
    overlays, kw = editor.lane_items(drawn)
    # a road cars do not use in lanestyle's colour for who uses it (colors.groups), every other one in the car lane colour (2026-10-09)
    table = kw.pop("color_table")
    assert kw.pop("color_key") == "edge" and table["999"] == "#f0cb8c" and {table[e] for e in links[1:]} == {"#a3a3a3"}
    assert drawn.loc[drawn["road"] == "foot", "width_m"].tolist() == [2.0]   # a footway without lanes: lanestyle.json path_width_m, in metres
    drawn = drawn[drawn["road"] != "foot"]
    st, items, popup = kw.pop("settings"), kw.pop("items")["features"], kw.pop("items_popup")
    assert overlays == [] and kw == {"width_m_col": "width_m", "width_m_zoom": 0, "casing_m": 0.14, "casing_min_px": 1.0, "arrows": False,
                                     "palette": "lanestyle_editor"}
    assert set(drawn["highway"]) <= set(st["config"]["single_line_classes"]) and st["config"]["labels"]["halo_width"] > 0 and "lane_id" in popup
    assert {v["fill"] for v in st["palettes"]["lanestyle_editor"].values()} == {"#a3a3a3"}      # the road in the car lane colour
    assert drawn["width_m"].notna().all()
    feats = [f for f in items if f["properties"]["pick"]]                    # the lanes: picked; lines and marks: not
    assert feats and all(f["properties"]["edge"] == str(f["properties"]["edge_id"]) and f["properties"]["edge"] in links[1:] for f in feats)
    assert {f["properties"]["edge"] for f in feats} == set(links[1:]) and all("lane_num" in f["properties"] for f in feats)
    assert any(not f["properties"]["pick"] for f in items)
    special = {i for i, u in zip(lanes["lane_id"], lanes["use"].fillna("auto")) if u.startswith("bus") or u == "bike"}
    assert all(f["properties"]["road"] == "r" + f["properties"]["edge"] for f in items)
    # a bus or bike lane drawn on the road, a car lane unseen
    assert all((f["properties"]["color"] == "rgba(0,0,0,0)") == (f["properties"]["lane_id"] not in special) for f in feats)
    assert all(f["properties"]["lane_id"] in special for f in feats if f["properties"]["use"] in ("bus", "bike", "bus,bike"))
    assert any(f["properties"]["color"] == "rgba(0,0,0,0)" for f in feats)
    assert "left out" in capsys.readouterr().out
    # the casing's line is the lane page's (the middle of the carriageway), not the editor's: every edge left its dummy line
    assert all(g.coords[0] != (0.0, 0.0) for g in drawn.geometry)


def test_the_lane_page_is_the_editors_drawing_without_its_panel(tmp_path):
    """lanestyle.lane_page (2026-10-10): the roads of a level area as the editor draws them (one line at the lanes' width, its levels), the
    lanes, lines and marks as the roads' own items (render items=), a road popup and no editor panel."""
    import geopandas as gpd
    import pytest
    pytest.importorskip("scipy")
    from roadstyle.level_area import make_area
    from shapely.geometry import LineString

    import lanestyle as ls
    gmns, src = _dbs(tmp_path)
    a, b, c = (18.00, 59.30), (18.01, 59.30), (18.02, 59.30)
    edges = gpd.GeoDataFrame({"edge_id": [8121729169906061189, 2, 3], "highway": ["secondary", "tertiary", "secondary"],
                              "name": ["Main St", "Bridge Rd", "Main St"], "oneway": [True, True, True], "driving": [True] * 3,
                              "cycling": [False] * 3, "lanes": [2, 1, 1], "modes": ["driving"] * 3},
                             geometry=[LineString([a, b]), LineString([b, c]), LineString([b, a])], crs=4326)
    make_area(edges, tmp_path / "area", id_col="edge_id")
    html = ls.lane_page(tmp_path / "area", str(gmns), str(src), tiles=False).html
    data = _unpacked(html)                                                          # the page keeps its data gzipped
    assert "roads-simple" in data and '"lane_id"' in data and "1_2" in data         # the one road layer, its lane items
    assert "lv-apply" not in html and "Lanes" in html                               # no editor panel; the page's own name


