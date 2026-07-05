"""
lanestyle — a **lane-level** base map, built by reusing [`mapstyle`](../mapstyle)'s renderer.

The workspace lineage is `roadstyle` (styles road *lines*) → `mapstyle` (a whole base map) →
**`lanestyle`** (the *lanes* themselves). It reads a duckOSM **GMNS** db's per-lane geometry
(``gmns_<mode>.lane`` — drive-side offset centerline + width), buffers each lane to a **surface
polygon**, and hands the layers to ``mapstyle.render_basemap`` — so the lane map looks like a natural
lane-resolution companion to mapstyle's road map. An optional **lane route** (from duckOSM's
``route-lanes``) is drawn on top.

    from lanestyle import render_lane_map
    render_lane_map("../duckOSM/data/db/sodermalm_pbf_gmns.duckdb", "lanes.html")
    render_lane_map(gmns_db, "lanes.html", route_geojson="route.geojson")   # + a routed lane path
"""
_LANE_W = 3.25
_USE_COLOR = {"auto": "#8fa2b4", "bus": "#e8944a", "bike": "#5ab0e6"}     # lane fill by allowed use
_ROUTE_COLOR = "#ffd400"


def lane_gdf(gmns_db, mode="driving"):
    """All lanes of ``gmns_<mode>.lane`` as one GeoDataFrame of **surface polygons** (offset centerline
    buffered by ½·width, metric → WGS84) with ``use`` / ``lane`` / ``edge_id`` / ``width`` columns."""
    import duckdb
    import geopandas as gpd
    import shapely.wkt as wkt

    g = f"gmns_{mode}"
    con = duckdb.connect(str(gmns_db), read_only=True)
    con.execute("INSTALL spatial; LOAD spatial;")
    if con.execute("SELECT count(*) FROM duckdb_tables() WHERE schema_name=? AND table_name='lane'",
                   [g]).fetchone()[0] == 0:
        con.close()
        raise ValueError(f"no '{g}.lane' in {gmns_db} — build a GMNS db first (duckOSM `duckosm gmns`)")
    rows = con.execute(
        f"SELECT allowed_uses, lane_num, link_id, COALESCE(width, {_LANE_W}) AS w, "
        f"ST_AsText(ST_Transform(ST_Buffer("
        f"  ST_Transform(geom, 'EPSG:4326', 'EPSG:3006', always_xy := true), COALESCE(width, {_LANE_W})/2.0), "
        f"  'EPSG:3006', 'EPSG:4326', always_xy := true)) "
        f"FROM {g}.lane WHERE geom IS NOT NULL").fetchall()
    con.close()
    rows = [r for r in rows if r[4] and r[4].startswith(("POLYGON", "MULTIPOLYGON"))]
    gdf = gpd.GeoDataFrame(
        {"use": [r[0] for r in rows], "lane": [r[1] for r in rows], "edge_id": [str(r[2]) for r in rows],
         "width": [round(float(r[3]), 2) for r in rows]},
        geometry=[wkt.loads(r[4]) for r in rows], crs="EPSG:4326")
    return gdf


def lane_layers(gmns_db, mode="driving"):
    """Read ``gmns_<mode>.lane`` → one ``mapstyle.Layer`` (polygon) per allowed use, each lane a
    surface polygon, coloured by use."""
    from mapstyle import Layer

    gdf = lane_gdf(gmns_db, mode=mode)
    layers = []
    for use, color in _USE_COLOR.items():
        sub = gdf[gdf["use"] == use]
        if len(sub):
            layers.append(Layer(f"lanes_{use}", sub.reset_index(drop=True), kind="polygon", color=color))
    return layers


def route_layer(route_geojson, color=_ROUTE_COLOR):
    """A line ``Layer`` from a lane-route GeoJSON (duckOSM ``duckosm route-lanes -o route.geojson``)."""
    import geopandas as gpd
    from mapstyle import Layer

    gdf = gpd.read_file(str(route_geojson))[["geometry"]].copy()   # drop list props (maneuvers) — not JSON-safe
    gdf["highway"] = "route"                               # mapstyle line layers key off `highway`
    return Layer("route", gdf, kind="line", color=color)


def render_lane_map(gmns_db, out, mode="driving", route_geojson=None, theme="dark",
                    backend="folium"):
    """Render a lane-level base map to ``out`` (HTML) via mapstyle. Lanes are coloured by use; pass a
    ``route_geojson`` (from duckOSM's ``route-lanes``) to overlay a routed lane path. Returns ``out``."""
    from mapstyle import render_basemap

    layers = lane_layers(gmns_db, mode=mode)
    if route_geojson:
        layers.append(route_layer(route_geojson))
    render_basemap(layers, backend=backend, theme=theme, out=str(out))
    return out


def render_lane_debug(gmns_db, out, mode="driving", route_geojson=None, zoom_start=15):
    """A **debug** lane map (QA): every lane is inspectable — hover a lane to see its ``use`` / lane # /
    ``edge_id`` / width, with a hover highlight and per-use toggles; the route (if given) shows its
    lane count + cost. Built directly on folium so each feature carries a tooltip. Returns ``out``."""
    import folium
    import geopandas as gpd

    gdf = lane_gdf(gmns_db, mode=mode)
    minx, miny, maxx, maxy = gdf.total_bounds
    m = folium.Map(location=[(miny + maxy) / 2, (minx + maxx) / 2], zoom_start=zoom_start,
                   tiles="CartoDB dark_matter")
    for use, color in _USE_COLOR.items():
        sub = gdf[gdf["use"] == use]
        if not len(sub):
            continue
        folium.GeoJson(
            sub, name=f"lanes_{use} ({len(sub)})",
            style_function=lambda f, c=color: {"fillColor": c, "color": c, "weight": 0.4, "fillOpacity": 0.65},
            highlight_function=lambda f: {"weight": 2.5, "color": "#ffffff", "fillOpacity": 0.9},
            tooltip=folium.GeoJsonTooltip(fields=["use", "lane", "edge_id", "width"],
                                          aliases=["use", "lane #", "edge_id", "width (m)"], sticky=True),
        ).add_to(m)
    if route_geojson:
        rgdf = gpd.read_file(str(route_geojson))
        props = rgdf.drop(columns="geometry").iloc[0].to_dict() if len(rgdf) else {}
        tip = f"route · {props.get('lanes', '?')} lanes · cost {round(float(props.get('cost', 0) or 0))}"
        folium.GeoJson(rgdf[["geometry"]], name="route",
                       style_function=lambda f: {"color": "#ffd400", "weight": 4, "opacity": 0.95},
                       tooltip=tip).add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    m.fit_bounds([[miny, minx], [maxy, maxx]])
    m.save(str(out))
    return out
