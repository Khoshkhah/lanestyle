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


def lane_layers(gmns_db, mode="driving"):
    """Read ``gmns_<mode>.lane`` → one ``mapstyle.Layer`` (polygon) per allowed use, each lane a
    surface polygon (its offset centerline buffered by ½·width, in metric then back to WGS84)."""
    import duckdb
    import geopandas as gpd
    import shapely.wkt as wkt
    from mapstyle import Layer

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

    layers = []
    for use, color in _USE_COLOR.items():
        sub = [(ln, lk, w, geo) for u, ln, lk, w, geo in rows if u == use and geo]
        if not sub:
            continue
        gdf = gpd.GeoDataFrame(
            {"lane": [s[0] for s in sub], "edge_id": [str(s[1]) for s in sub], "width": [s[2] for s in sub]},
            geometry=[wkt.loads(s[3]) for s in sub], crs="EPSG:4326")
        layers.append(Layer(f"lanes_{use}", gdf, kind="polygon", color=color))
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
