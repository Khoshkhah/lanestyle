"""The engine: a lane table drawn with roadstyle, one line per lane at its width in metres.

    import lanestyle as ls
    lanes, turns = ls.from_gmns("monaco_gmns.duckdb", source_db="monaco.duckdb")
    ls.render_lanes(lanes, turns=turns).save("lanes.html")

Design: docs/design/lanestyle_on_roadstyle.md.
"""
import json
from pathlib import Path

from lanestyle.frames import frames
from lanestyle.junctions import junction_fillets
from lanestyle.arrows import lane_arrows
from lanestyle.street_names import street_names
from lanestyle.lines import _band, _group, _level, _paired, lane_lines

_LEVEL = {"bridge": "bridge", "high": "above ground", "ground": "ground", "low": "tunnel / below ground"}
def pd_isna(v):
    import pandas as pd

    return v is None or bool(pd.isna(v))


_POPUP = ["name", "lane_type", "connects", "highway", "kind", "level", "footway", "edge_ref", "along", "footpaths", "twin", "lane_id", "lane_num", "lanes", "use", "modes", "turn", "width_m", "tunnel", "bridge",
          "layer", "turns_in", "turns_out", "from_lane", "to_lane", "link_id", "reverse_link_id", "osm_id", "from_node_id",
          "to_node_id"]                       # the ones present and not null show
_MARKED = ("auto", "bus", "bike", "walk")       # the mode groups: each has its colour and a legend row
_USE_NAME = {"auto": "car lanes", "bus": "bus lanes", "bike": "bike lanes", "walk": "footways"}      # the legend rows
# with several modes loaded (``from_gmns(modes=...)``) a lane is coloured by the set of modes that can use it
_GROUP_ORDER = ("driving", "walking", "cycling")
_GROUP_NAME = {"driving": "cars only", "driving+walking": "cars + pedestrians", "walking": "pedestrians only",
               "cycling": "bikes only", "driving+cycling": "cars + bikes", "walking+cycling": "pedestrians + bikes",
               "driving+walking+cycling": "cars + pedestrians + bikes"}


def _colour_groups(g, s):
    """What colours the lanes and what the Roads box lists: ``(column, {value: colour}, [(label, colour)])``.

    One mode: the lane's ``use`` (car, bus, bike, walk). Several (a ``modes`` column from ``from_gmns(modes=...)`` with
    more than one distinct set): the set of modes whose network has the lane's link, so a street cars and pedestrians
    share, a car-only tunnel and a pedestrian-only footway differ; a bus lane and an on-road bike lane keep their own."""
    col = s["colors"]
    if "modes" in g and g["modes"].replace("", None).dropna().nunique() > 1:
        key = g["modes"].map(lambda m: "+".join(x for x in _GROUP_ORDER if x in m.split(",")) or "driving")
        lane_beyond = (g["lane_num"] > g["lanes"].fillna(0)) if {"lane_num", "lanes"} <= set(g.columns) else False
        if "connector" in g:       # a connector has no lane number: one that joins bike lanes (it takes its lane's use) is a bike lane's too
            lane_beyond = lane_beyond | g["connector"].fillna(False).astype(bool)
        key = key.where(~(g["use"] == "bus"), "bus").where(~((g["use"] == "bike") & lane_beyond), "bike")
        g["mode_group"] = key
        colours = {k: col["groups"].get(k, col["auto"]) for k in set(key)} | {"bus": col["bus"], "bike": col["bike"]}
        names = {**_GROUP_NAME, "bus": "bus lanes", "bike": "bike lanes"}
        order = [*_GROUP_NAME, "bus", "bike"]
        rows = [(names[k], colours[k]) for k in order if k in set(key)]
        return "mode_group", colours, rows
    present = {u: col[u] for u in _MARKED if u in set(g["use"])}
    colours = {**present, **{u: col["auto"] for u in set(g["use"]) if u not in present}}
    return "use", colours, [(_USE_NAME.get(u, f"{u} lanes"), c) for u, c in present.items()]

# click a lane: it turns `clicked`, the lanes its turns lead into `turns_into`, U-turns `uturn`.
# roadstyle feature ids are indexes into its source, so lane_id -> id is built on the first click.
_CLICK_JS = """<script>
(function(){
  const T = __TURNS__, C = __COLORS__;
  let idx = null;
  const ids = ls => (ls || []).map(l => idx[l]).filter(i => i !== undefined);
  document.addEventListener("rs:select", e => {
    const d = e.detail || {};
    if (d.overlay || d.id == null) return;
    if (!idx) { idx = {}; const all = rsQuery(() => true), rows = rsGetProps(all);
                all.forEach((id, k) => { idx[rows[k].lane_id] = id; }); }
    const t = T[(d.properties || {}).lane_id] || [];
    rsColor([[[d.id], C.clicked], [ids(t[0]), C.turns_into], [ids(t[1]), C.uturn]]);
  });
  document.addEventListener("rs:deselect", () => rsColor(null));
  // a link can open the map at a spot: page.html#zoom/lat/lon (roadstyle fits the data first, so go again once the map is idle)
  const go = () => { const h = location.hash.slice(1).split("/").map(Number);
    if (h.length === 3 && !h.some(isNaN)) map.jumpTo({zoom: h[0], center: [h[2], h[1]]}); };
  go(); window.addEventListener("hashchange", go); map.once("idle", go);
})();
</script>
"""


# where a lane's layers go in the page: right after (or before) the fill layers of the lane's band. A band is a bridge (roadstyle keeps its deck layers), a
# position of roadstyle's drawing order ("-2", "0", "2": its layers roads-fill-lv-2, roads-fill, roads-fill-lv2 ... docs/design/interval_draw_order.md), or,
# in a table without a drawing order, one of roadstyle's three bands. ``lsAnchor(ids, band, before)``: the layer id, or null when the page has none.
_ANCHOR_JS = """<script>
window.lsAnchor = function(ids, b, before){       // before: false = after the band's fill, true = before it, 2 = the casing slot (before its underlay too)
  const AFTER = {low: ["roads-low-fill-pat", "roads-low-fill"], ground: ["roads-arrows", "roads-fill"], high: ["roads-high-fill"], bridge: ["roads-bridge-fill"]};
  const BEFORE = {low: ["roads-low-fill"], ground: ["roads-fill"], high: ["roads-high-fill"], bridge: ["roads-bridge-fill"]};
  let c = (before ? BEFORE : AFTER)[b];
  if (!c) { const base = b === "0" ? "roads-fill" : "roads-fill-lv" + b; c = before === 2 ? [base + "-under", base] : before ? [base] : [base + "-pat", base]; }
  return c.find(id => ids.includes(id)) || null;
};
</script>
"""


# the lane lines: one MapLibre line layer per band and type, right after that band's fill, so a
# bridge covers the lines of the street under it; widths in metres (k = width_m / cos(lat)) from
# width_m_zoom, dashes in multiples of the line width (dash_m / width_m), exact at every zoom
_LINES_JS = """<script>
(function(){
  const D = __LINES__, S = __STYLES__, Z = __ZOOM__;
  // never thinner than one physical pixel of this screen (a sub-pixel line vanishes in some browsers
  // and at browser zooms under 100 %), true to scale above that; faded in over two zoom levels
  const MIN = __MIN_DEVICE_PX__ / (window.devicePixelRatio || 1);     // compact columns (_compact), rebuilt here
  const L = {type: "FeatureCollection", features: D.c.map((c, i) => ({type: "Feature",
    properties: {t: D.types[D.t[i]], b: D.bands[D.b[i]], k: D.k[i]},
    geometry: {type: Array.isArray(c[0][0]) ? "MultiLineString" : "LineString", coordinates: c}}))};
  // after the band's last fill layer (roadstyle's levels and looks: three bands, a tunnel is a road of the low band,
  // its dashes the first of these that exists; a bridge's look layer is drawn after the high band)
  const px = z => 512 * Math.pow(2, z) / 40075016.686;
  function add(){
    if (map.getSource("lane-lines")) return;
    map.addSource("lane-lines", {type: "geojson", data: L});
    const ids = map.getStyle().layers.map(l => l.id);
    for (const b of D.bands) {
      for (const t in S) {
        const s = S[t];
        if (!s || (t === "bridge_edge" && b !== "bridge")) continue;
        const casing = t === "edge" || t === "bridge_edge";                       // an outline is a casing: under the fills of its position
        const after = lsAnchor(ids, b, casing ? 2 : false);
        if (!after) continue;
        const i = ids.indexOf(after);
        const w = ["interpolate", ["exponential", 2], ["zoom"]];
        for (let z = Z; z <= 22; z++) w.push(z, ["max", ["*", ["get", "k"], px(z)], MIN]);
        const paint = {"line-color": s.color, "line-width": w,
                       "line-opacity": t === "bridge_edge" ? 1 : ["interpolate", ["linear"], ["zoom"], Z, 0.35, Z + 2, 1]};
        if (s.dash_m) paint["line-dasharray"] = s.dash_m.map(d => d / s.width_m);
        map.addLayer({id: "lane-lines-" + b + "-" + t, type: "line", source: "lane-lines", minzoom: Z,
                      filter: ["all", ["==", ["get", "t"], t], ["==", ["get", "b"], b]],
                      layout: {"line-cap": "butt", "line-join": "round"}, paint: paint}, casing ? after : ids[i + 1]);
      }
    }
  }
  if (map.isStyleLoaded()) add(); else map.once("load", add);
})();
</script>
"""


# a marked crossing: white stripes on the road. The crossing's own lane stays a footpath under the road (by road class, as
# every footway); the stripes are polygons in metres (_zebra_stripes), drawn right over the ground roads
_ZEBRA_JS = """<script>
(function(){
  const Z = __ZEBRA__, S = __STYLE__, ZOOM = __ZOOM__;
  function add(){
    if (map.getSource("zebra")) return;
    map.addSource("zebra", {type: "geojson", data: Z});
    const ids = map.getStyle().layers.map(l => l.id);
    const after = ["roads-arrows", "roads-fill"].find(id => ids.includes(id));      // above the lane arrows: none lies on the stripes
    if (!after) return;
    map.addLayer({id: "zebra", type: "fill", source: "zebra", minzoom: ZOOM,
                  paint: {"fill-color": S.color, "fill-antialias": true,
                          "fill-opacity": ["interpolate", ["linear"], ["zoom"], ZOOM, 0.5, ZOOM + 1.5, 1]}}, ids[ids.indexOf(after) + 1]);
  }
  if (map.isStyleLoaded()) add(); else map.once("load", add);
})();
</script>
"""

# the painted lane arrows (arrows.py): white polygons in metres, per band right after that band's fill
_ARROWS_JS = """<script>
(function(){
  const A = __ARROWS__, S = __STYLE__;
  function add(){
    if (map.getSource("lane-arrows")) return;
    map.addSource("lane-arrows", {type: "geojson", data: A});
    const ids = map.getStyle().layers.map(l => l.id);
    for (const b of new Set(A.features.map(f => f.properties.b))) {
      const after = lsAnchor(ids, b, false);
      if (!after) continue;
      map.addLayer({id: "lane-arrows-" + b, type: "fill", source: "lane-arrows", minzoom: S.from_zoom,
                    filter: ["==", ["get", "b"], b],
                    paint: {"fill-color": S.color, "fill-antialias": true,
                            "fill-opacity": ["interpolate", ["linear"], ["zoom"], S.from_zoom, 0.4, S.from_zoom + 1, 1]}}, ids[ids.indexOf(after) + 1]);
    }
  }
  if (map.isStyleLoaded()) add(); else map.once("load", add);
})();
</script>
"""

# street names (street_names.py): roadstyle's own name layer is hidden, ours is drawn in its font, white over a dark halo, like the paint
_NAMES_JS = """<script>
(function(){
  const N = __NAMES__, S = __STYLE__;
  function add(){
    if (map.getSource("lane-names")) return;
    const font = map.getLayer("roads-labels") ? map.getLayoutProperty("roads-labels", "text-font") : null;
    if (map.getLayer("roads-labels")) map.setLayoutProperty("roads-labels", "visibility", "none");
    map.addSource("lane-names", {type: "geojson", data: N});
    map.addLayer({id: "lane-names", type: "symbol", source: "lane-names", minzoom: S.from_zoom,
      layout: Object.assign({"symbol-placement": "line", "text-field": ["get", "name"], "text-size": S.size,
                             "symbol-spacing": 300, "text-keep-upright": true}, font ? {"text-font": font} : {}),
      paint: {"text-color": S.color, "text-halo-color": S.halo, "text-halo-width": 1.5}});
  }
  if (map.isStyleLoaded()) add(); else map.once("load", add);
})();
</script>
"""


def _compact(fc):
    """The lines as columns, not GeoJSON features: a city's ~35k lines are half wrapping otherwise."""
    fs = fc["features"]
    types = sorted({f["properties"]["t"] for f in fs})
    bands = sorted({f["properties"]["b"] for f in fs})
    return {"types": types, "bands": bands,
            "t": [types.index(f["properties"]["t"]) for f in fs],
            "b": [bands.index(f["properties"]["b"]) for f in fs],
            "k": [f["properties"]["k"] for f in fs], "c": [f["geometry"]["coordinates"] for f in fs]}


# roadstyle's tunnel look (a 45 % see-through fill over a dashed casing, light dashes on the fill) is
# made for road-width lines; at lane width the dashes become blocks, every connector dashes from its
# own start (fans where they overlap), and see-through lanes show every overlap. Lane maps draw
# tunnels at 85 %, a plain casing, no fill dashes: a tunnel still reads lighter, overlaps hardly show
_CLASSES = ("motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street",
            "service", "track", "cycleway", "footway", "path")
# Lanes are coloured by mode group, so the highway classes in the Roads box are filters, not colours: one grey each.
# Levels and looks (roadstyle): a tunnel is a road of the low band, a bridge of the high band, each with its own look
# (a faded fill with dashes, a deck casing), drawn whole by the one rule; the class dashes (footway, path ...) stay,
# coloured by mode group.
_ROADSTYLE = {"config": {"tunnel_opacity_scale": 0.75, "tunnel_gap_shade": 0.15, "tunnel_dash_shade": 0.3,
                         "tunnel_fill_dash_color": "rgba(255,255,255,0.35)", "bridge_casing_m": 0, "bridge_casing_px": 0},
              # one grey per class, and no class dashes: a footway, path, cycleway or track lane is a solid strip like any lane
              "palettes": {name: {c: {"fill": "#a3a3a3", "dash": None} for c in _CLASSES}
                           for name in ("mono", "carto", "highsat")}}


def _demote_crossings(g, s):
    """OSM tags a whole way ``footway=crossing`` where only its end crosses the road (``1342546079``: 173 m, 2 % on a road; its last
    4 m are the crossing). A crossing link that is longer than ``crossing_max_m`` and has under ``crossing_min_on`` of its length on
    the road surface of its level is drawn as a footway (``footway`` None, ``kind`` says why). The data keeps OSM's tag."""
    import pandas as pd
    import shapely

    mx, lo = float(s.get("crossing_max_m") or 0), float(s.get("crossing_min_on") or 0)
    if not mx or "footway" not in g:
        return
    cx = (g["footway"] == "crossing") & (g["use"] == "walk")
    if "connector" in g:
        cx &= ~g["connector"].fillna(False).astype(bool)
    if not cx.any():
        return
    u = g.to_crs(g.estimate_utm_crs())
    band = [_group(r) for r in g.itertuples(index=False)]
    road = [i for i in range(len(g)) if g["use"].iloc[i] != "walk" and not (("connector" in g) and g["connector"].iloc[i])]
    surf = [u.geometry.iloc[i].buffer(float(g["width_m"].iloc[i] if g["width_m"].iloc[i] == g["width_m"].iloc[i] else 3.0) / 2) for i in road]
    tree = shapely.STRtree(surf)
    for i in g.index[cx]:
        k = g.index.get_loc(i)
        ln = u.geometry.iloc[k]
        if ln.length <= mx:                                                    # a short crossing stays a crosswalk (matched to a road or not: a crossing of a side street runs along the main road)
            continue
        if "along_link_id" in g and pd.notna(g["along_link_id"].iloc[k]):      # long, and duckOSM matched it to a road it runs along: a footpath tagged a crossing by mistake
            g.loc[i, "footway"] = None
            g.loc[i, "demoted"] = f"footway (OSM tags it a crossing; it runs along a road for most of its {ln.length:.0f} m)"
            continue
        hit = [surf[j] for j in tree.query(ln.buffer(1)) if band[road[j]] == band[k]]
        on = shapely.union_all(hit).intersection(ln).length / ln.length if hit else 0.0
        if on < lo:
            g.loc[i, "footway"] = None
            g.loc[i, "demoted"] = f"footway (OSM tags it a crossing; {on:.0%} of its {ln.length:.0f} m is on a road)"


def _classes(g):
    """Each lane's road class as roadstyle reads it (first of ``a;b``, no ``_link``)."""
    return [str(h).split(";")[0].removesuffix("_link") for h in g["highway"]] if "highway" in g else [""] * len(g)


def _modes(g):
    return list(g["modes"]) if "modes" in g else [""] * len(g)


def _connector_order(turn, highway, modes, low_turn, low_straight):
    """roadstyle's per-edge draw order of a connector. A road connector (cars can use it) is part of the road: it ranks just under
    its own road class (roadstyle's z order), so it lies under the lanes of its level but over a footway, or a footway ending
    on the road shows on top of the road's own surface. A connector only people use stays below everything (``low_*``)."""
    from roadstyle.render_web import ROAD_Z

    if modes and set(modes.split(",")) <= {"walking", ""}:
        return low_turn if turn else low_straight
    return ROAD_Z.get(highway, 4) - (0.6 if turn else 0.5)


def _footpaths_on_roads(g, share=0.6):
    """Indices (row positions) of the footpaths that lie mostly on a road of their level: mapped on the carriageway, a road is drawn above a footway by class and would hide
    them. Not a crossing (that is drawn under the road with its zebra on it) and not a connector."""
    import shapely

    walk = [i for i in range(len(g)) if g["use"].iloc[i] == "walk" and not (("footway" in g) and g["footway"].iloc[i] == "crossing")
            and not (("connector" in g) and bool(g["connector"].iloc[i]))]
    if not walk:
        return []
    u = g.to_crs(g.estimate_utm_crs())
    band = [_group(r) for r in g.itertuples(index=False)]
    road = [i for i in range(len(g)) if g["use"].iloc[i] != "walk" and not (("connector" in g) and bool(g["connector"].iloc[i]))]
    surf = [u.geometry.iloc[i].buffer(float(g["width_m"].iloc[i]) / 2, cap_style="round") for i in road]
    tree = shapely.STRtree(surf)
    out = []
    for i in walk:
        p = u.geometry.iloc[i].buffer(float(g["width_m"].iloc[i]) / 2, cap_style="round")
        hit = [surf[j] for j in tree.query(p) if band[road[j]] == band[i]]
        if hit and p.area and shapely.union_all(hit).intersection(p).area / p.area >= share:
            out.append(i)
    return out


def _break_twins(g):
    """roadstyle pairs two lines with swapped end points (to 6 decimals) as a two-way road's two
    directions and shifts them apart. Lanes are never such a pair (each has its own geometry), but the
    two halves of a one-way loop are: nudge one end of the later one by 2e-6 degrees (~0.2 m)."""
    # ponytail: geometry nudge; roadstyle's `twoway_col` (in progress on its main) replaces it
    from shapely.geometry import LineString

    key = lambda c: (round(c[0], 6), round(c[1], 6))
    seen, geoms = set(), list(g.geometry)
    walk = (g["use"] == "walk").tolist() if "use" in g else [False] * len(geoms)
    for i, ln in enumerate(geoms):
        if ln is None or ln.geom_type != "LineString" or walk[i]:      # a footway's twins are drawn as they are
            continue
        cs = list(ln.coords)
        a, z = key(cs[0]), key(cs[-1])
        if (z, a) in seen:
            cs[-1] = (cs[-1][0] + 2e-6, cs[-1][1] + 2e-6)
            geoms[i] = LineString(cs)
            z = key(cs[-1])
        seen.add((a, z))
    return g.set_geometry(geoms, crs=g.crs)


# a lane's type label: the turns that leave it, in this order, as these words
_TYPE_ORDER = ["left", "uturn", "thru", "diverge", "merge", "right"]
_TYPE_WORD = {"left": "left", "uturn": "U-turn", "thru": "thru", "diverge": "fork", "merge": "merge",
              "right": "right"}

# the type label along each lane (lane_type), from zoom __ZOOM__, in roadstyle's street-name font
_LABELS_JS = """<script>
(function(){
  function add(){
    if (map.getLayer("lane-type-labels")) return;
    const font = map.getLayer("roads-labels") ? map.getLayoutProperty("roads-labels", "text-font") : null;
    map.addLayer({id: "lane-type-labels", type: "symbol", source: "roads", minzoom: __ZOOM__,
      filter: ["!", ["to-boolean", ["get", "connector"]]],     // lanes only; a connector says it in its popup
      layout: Object.assign({"symbol-placement": "line", "text-field": ["get", "lane_type"], "text-size": 11,
                             "symbol-spacing": 220, "text-keep-upright": true}, font ? {"text-font": font} : {}),
      paint: {"text-color": "#1b1b1b", "text-halo-color": "#ffffff", "text-halo-width": 1.5}});
  }
  if (map.isStyleLoaded()) add(); else map.once("load", add);
})();
</script>
"""




# bus / bike lanes are coloured with roadstyle's "colour by" (Road class + Lane use, the latter on),
# but its dropdown and legend box are hidden: the colours get rows in the Roads filter box instead,
# in place of the road classes (hidden), before Bridges / Tunnels
_USE_ROWS_JS = """<style>.co-ctrl,.co-lg{display:none!important}</style>
<script>
(function(){
  const ROWS = __ROWS__;
  function add(){
    const body = document.querySelector(".flt-ctrl .flt-body");
    if (!body) return setTimeout(add, 200);
    if (body.querySelector(".ls-use")) return;
    const before = body.querySelector(".flt-grade");
    // the road classes are no filter here (lanes are coloured by use, one grey per class): only the mode rows and Bridges / Tunnels stay
    body.querySelectorAll("label:not(.ls-use):not(.flt-grade)").forEach(l => { l.style.display = "none"; });
    ROWS.forEach(([label, color]) => {
      const lab = document.createElement("label"); lab.className = "ls-use";
      const pad = document.createElement("input"); pad.type = "checkbox"; pad.style.visibility = "hidden";
      const sw = document.createElement("span"); sw.className = "flt-sw"; sw.style.background = color;
      lab.appendChild(pad); lab.appendChild(sw); lab.appendChild(document.createTextNode(" " + label));
      body.insertBefore(lab, before);
    });
  }
  add();
})();
</script>
"""


def _lane_types(g, turns):
    """Each lane's type label: the turns that leave it (``left + thru``, ``U-turn``, ``fork``, ``merge``)
    or ``end`` where none does; a bus or bike lane says so first (``bus · thru``)."""
    out = {}
    types = turns["type"] if "type" in turns else ["turn"] * len(turns)
    for a, t in zip(turns["from_lane"].astype(str), types):
        out.setdefault(a, set()).add(t)

    def label(lane, use):
        ts = out.get(lane, set())
        words = " + ".join(_TYPE_WORD.get(t, t) for t in _TYPE_ORDER + sorted(ts - set(_TYPE_ORDER)) if t in ts)
        return (words or "end") if use == "auto" else f"{use} · {words or 'end'}"
    return [label(lane, use) for lane, use in zip(g["lane_id"], g["use"])]


# roadstyle ends its tunnel layers flat (butt caps, for the casing's dash ticks); at lane width two
# flat ends meeting at an angle leave a wedge of background, so lane maps give them round ends like
# every other road layer (Kaveh: "use curving for road end points")

# the junction fillets, a fill layer under each band's lanes, in the node's main road's colour
# (roadstyle's class colours, read from the page)
_FILLETS_JS = """<script>
(function(){
  const F = __FILLETS__;
  function add(){
    if (map.getSource("lane-fillets")) return;
    map.addSource("lane-fillets", {type: "geojson", data: F});
    const cols = window.RS_CLASS_COLORS || {};
    const color = ["match", ["get", "cls"]];
    for (const k in cols) color.push(k, cols[k]);
    color.push("#888888");
    const ids = map.getStyle().layers.map(l => l.id);
    const bands = [...new Set(F.features.map(f => f.properties.b))], gapLayers = [];
    for (const b of bands) {
      const before = lsAnchor(ids, b, true);
      if (!before) continue;
      map.addLayer({id: "lane-fillets-" + b, type: "fill", source: "lane-fillets",
                    filter: ["==", ["get", "b"], b],
                    paint: {"fill-color": ["case", ["has", "c"], ["get", "c"], Object.keys(cols).length ? color : "#888888"],
                            "fill-opacity": ["case", ["all", ["has", "tn"], ["has", "c"]], 0.72, 1]}}, before);
      gapLayers.push("lane-fillets-" + b);
    }
    // a frame gap (a sidewalk's verge) in a tunnel: the tunnel look, a light hatch over the faded fill
    const px = new Uint8Array(8 * 8 * 4);
    for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) if ((x + y) % 8 < 2) px.set([255, 255, 255, 110], (y * 8 + x) * 4);
    if (!map.hasImage("lane-hatch")) map.addImage("lane-hatch", {width: 8, height: 8, data: px});
    for (const b of bands) {
      const before = lsAnchor(ids, b, true);
      if (before) map.addLayer({id: "lane-fillets-pat-" + b, type: "fill", source: "lane-fillets",
                                filter: ["all", ["==", ["get", "b"], b], ["has", "tn"], ["has", "c"]], paint: {"fill-pattern": "lane-hatch"}}, before);
    }
    map.on("click", gapLayers, e => {
      const f = (e.features || []).find(f => f.properties && f.properties.info);
      if (!f) return;
      new maplibregl.Popup({closeButton: true, className: "lane-gap"}).setLngLat(e.lngLat).setText(f.properties.info).addTo(map);
      setTimeout(() => document.querySelectorAll(".maplibregl-popup:not(.lane-gap)").forEach(p => p.remove()), 60);   // the road beside it opens its own: this one is the gap's
    });
    map.on("mousemove", gapLayers, e => { map.getCanvas().style.cursor = (e.features || []).some(f => f.properties && f.properties.info) ? "pointer" : ""; });
    map.on("mouseleave", gapLayers, () => { map.getCanvas().style.cursor = ""; });
  }
  if (map.isStyleLoaded()) add(); else map.once("load", add);
})();
</script>
"""

# tunnel lanes are drawn faded (roadstyle: the fill at 72 %) over a dark casing, and every lane ends round: the ring of one lane's end shows through the
# next lane's faded fill at every joint. An opaque body in the land colour under the fill (above the casing) hides those rings; the casing beyond the fill's width stays.
_LOWBODY_JS = """<script>
(function(){
  const F = __BODY__;
  function add(){
    if (map.getSource("lane-low-body")) return;
    const ids = map.getStyle().layers.map(l => l.id);
    map.addSource("lane-low-body", {type: "geojson", data: F});
    for (const b of new Set(F.features.map(f => f.properties.b))) {
      const before = lsAnchor(ids, b, true);
      if (before) map.addLayer({id: "lane-low-body-" + b, type: "fill", source: "lane-low-body", filter: ["==", ["get", "b"], b],
                                paint: {"fill-color": "__LAND__", "fill-opacity": 1}}, before);
    }
  }
  if (map.isStyleLoaded()) add(); else map.once("load", add);
})();
</script>
"""


def _low_body(g, s):
    """GeoJSON polygons of every lane of the low band (tunnels), as wide as the lane, round ends: the base under their faded fill (``_LOWBODY_JS``). None without any."""
    import geopandas as gpd

    low = [i for i, r in enumerate(g.itertuples(index=False)) if _level(r) == "low"]
    if not low:
        return None
    u = g.to_crs(g.estimate_utm_crs())
    polys = [u.geometry.iloc[i].buffer(float(g["width_m"].iloc[i]) / 2, cap_style="round").simplify(0.03) for i in low]
    geo = gpd.GeoSeries(polys, crs=u.crs).to_crs(4326)
    rnd = lambda ring: [[round(x, 7), round(y, 7)] for x, y in ring]  # noqa: E731
    rows = list(g.itertuples(index=False))
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"b": _band(rows[i])}, "geometry": {"type": "Polygon", "coordinates": [rnd(p_.exterior.coords)] + [rnd(h.coords) for h in p_.interiors]}}
        for i, p_ in zip(low, geo) if p_.geom_type == "Polygon" and not p_.is_empty]}


# a connector is not a road to click: roadstyle's click and hover pick from what the map renders, so connectors are left out of that answer (the lanes below them are picked instead)
_NOPICK_JS = """<script>
(function(){
  function patch(){
    if (map.__lanePatched) return;
    map.__lanePatched = true;
    const q = map.queryRenderedFeatures.bind(map);
    map.queryRenderedFeatures = (a, b) => q(a, b).filter(f => !(f.layer && /^roads-/.test(f.layer.id) && f.properties &&
                                                                (f.properties.connector === true || f.properties.connector === "true")));
  }
  if (typeof map !== "undefined") patch();
})();
</script>
"""


def _merge(a, b):
    """``a`` updated by ``b``, nested dicts merged (state only what changes)."""
    out = dict(a)
    for k, v in (b or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def lane_settings(settings=None):
    """lanestyle's settings: ``data/lanestyle.json``, then a ``lanestyle.json`` in the current folder,
    then ``settings["lanes"]``, each overriding only what it states (the roadstyle.json way)."""
    s = json.loads((Path(__file__).parent / "data" / "lanestyle.json").read_text())["lanes"]
    local = Path("lanestyle.json")
    if local.is_file():
        s = _merge(s, json.loads(local.read_text()).get("lanes"))
    return _merge(s, (settings or {}).get("lanes"))


def _widths(g, s):
    """Each lane's width in metres: its own ``width_m``, else a default by use (``width_m_by_use``): a ``walk`` lane is
    a footpath, and a ``bike`` lane *beyond the link's motor lanes* (``lane_num`` > ``lanes``; empty ``lanes`` is 0,
    as on a cycleway) is an on-road bike lane, both narrow; any other lane is ``default_width_m``."""
    import pandas as pd

    w = g["width_m"] if "width_m" in g else pd.Series(float("nan"), index=g.index)
    by = s.get("width_m_by_use") or {}
    default = pd.Series(float(s["default_width_m"]), index=g.index)
    if "walk" in by:
        default[g["use"] == "walk"] = by["walk"]
    if "bike" in by and {"lane_num", "lanes"} <= set(g.columns):
        beyond = pd.to_numeric(g["lane_num"], errors="coerce") > pd.to_numeric(g["lanes"], errors="coerce").fillna(0)
        default[(g["use"] == "bike") & beyond] = by["bike"]
    return w.fillna(default)


def _zebra_stripes(g, cr, st):
    """The zebra stripes from duckOSM's crossing table, ``(rings, footprint)``: the stripes as lon/lat polygon rings and the zebras'
    rectangles as one lon/lat geometry (the lane lines stop there). ``cr``: :func:`lanestyle.read_crossings`.

    One rectangle per crossing, the table's ``crossing.geom``: ``width`` along the road, ``length`` across the whole road it crosses.
    It is cut into stripes across its length, ``stripe_m`` thick, ``stripe_m + gap_m`` apart (the row centred), each as long as the
    rectangle is wide: parallel to the lanes, one straight band. Then a real clip: each stripe is intersected with the true shape of
    the lanes the crossing names in ``lane_crossing`` (each lane's line, from one rectangle-width before its ``start_lr`` to one
    after its ``end_lr``, ``width_m`` wide): the paint is only on those lanes, and a lane's edge is the stripe's edge. The extra
    rectangle-width on each side of a lane's stretch means the clip only ever cuts across the road, never along it, so a stripe
    that stays is as long as the zebra is wide. Nothing else is done to the stripes: no projection, no merging, no shrinking."""
    import math

    import shapely
    from shapely import wkt as _w
    from shapely.geometry import Polygon

    if cr is None or not len(cr) or "painted" not in cr or "cgeom" not in cr:
        return [], None
    cr = cr[cr["painted"].fillna(False).astype(bool)]
    if not len(cr):
        return [], None
    import geopandas as gpd

    from shapely.ops import substring

    u = g.estimate_utm_crs()
    geom = dict(zip(g["lane_id"], g.to_crs(u).geometry))
    wid = dict(zip(g["lane_id"], g["width_m"]))
    pitch, thick = st["stripe_m"] + st["gap_m"], st["stripe_m"]
    stripes, foot = [], []
    # every road lane, to find the ones that cross the zebra's road: a zebra across a side road does not run onto the carriageway it joins
    others = [(lid, ln) for lid, ln, use in zip(g["lane_id"], g.to_crs(u).geometry, g["use"]) if use != "walk" and ln is not None and ln.geom_type == "LineString"]
    other_tree = shapely.STRtree([ln for _, ln in others])
    for _cid, grp in cr.groupby("crossing_id"):
        rect = gpd.GeoSeries([_w.loads(grp["cgeom"].iloc[0])], crs=4326).to_crs(u).iloc[0]
        if rect.geom_type != "Polygon":
            continue
        (x0, y0), (x1, y1), _, (x3, y3) = list(rect.exterior.coords)[:4]
        length = math.hypot(x1 - x0, y1 - y0)                       # across the road: the rectangle's first side
        wx, wy = x3 - x0, y3 - y0                                   # along the road: the second side, as long as the zebra is wide
        along = math.hypot(wx, wy)
        if length < thick or along < 0.5:
            continue
        dx, dy = (x1 - x0) / length, (y1 - y0) / length
        lanes = []                                                  # the true shape of each named lane, a rectangle-width beyond its stretch
        for r in grp.itertuples():
            ln = geom.get(r.lane_id)
            if ln is None or ln.geom_type != "LineString":
                continue
            sub = substring(ln, max(r.start_lr - along, 0.0), min(r.end_lr + along, ln.length))
            if sub.geom_type == "LineString" and sub.length > 0.3:
                lanes.append(sub.buffer(float(wid[r.lane_id]) / 2, cap_style="flat", join_style="mitre", mitre_limit=2.0))
        if not lanes:
            continue
        # the lanes of a road meet at joints that are not exact (a flat end against the next lane's flat start): close seams under 0.6 m, which
        # leaves the outer border where it is, so consecutive lanes clip as the one road they are
        road = shapely.union_all(lanes).buffer(0.3, join_style="mitre", mitre_limit=2.0).buffer(-0.3, join_style="mitre", mitre_limit=2.0)
        ax, ay = wx / along, wy / along                           # the zebra's road direction
        crossing_roads = []
        for k in other_tree.query(rect):
            lid, ln = others[k]
            if lid in set(grp["lane_id"]):
                continue
            p = ln.interpolate(ln.project(rect.centroid))
            q0, q1 = ln.interpolate(max(ln.project(p) - 0.5, 0)), ln.interpolate(min(ln.project(p) + 0.5, ln.length))
            nn = math.hypot(q1.x - q0.x, q1.y - q0.y)
            if nn and abs(((q1.x - q0.x) * ax + (q1.y - q0.y) * ay) / nn) < 0.5:              # runs across the zebra's road, not along it
                crossing_roads.append(ln.buffer(float(wid[lid]) / 2, cap_style="flat"))
        if crossing_roads:
            road = road.difference(shapely.union_all(crossing_roads))
        n = int((length - thick) // pitch) + 1
        first = (length - ((n - 1) * pitch + thick)) / 2
        for i in range(n):
            t0 = first + i * pitch
            a, b = (x0 + dx * t0, y0 + dy * t0), (x0 + dx * (t0 + thick), y0 + dy * (t0 + thick))
            on = Polygon([a, b, (b[0] + wx, b[1] + wy), (a[0] + wx, a[1] + wy)]).intersection(road)
            stripes += [q for q in getattr(on, "geoms", [on]) if q.geom_type == "Polygon" and q.area > 0.02]
        on = rect.intersection(road)
        if not on.is_empty:
            foot.append(on)
    if not stripes:
        return [], None
    back = gpd.GeoSeries(stripes, crs=u).to_crs(4326)
    footprint = gpd.GeoSeries([shapely.union_all(foot)], crs=u).to_crs(4326).iloc[0] if foot else None
    return [[[round(x, 7), round(y, 7)] for x, y in p.exterior.coords] for p in back], footprint


def _roads_only(g):
    """The lanes of links that have a road class: a link with none is no road (a ferry in the walking network, a way with no ``highway`` tag)."""
    return g[g["highway"].notna()] if "highway" in g and g["highway"].isna().any() else g


def render_lanes(lanes, turns=None, palette="mono", settings=None, crossings=None, street_view=False, street_view_key=None, **kwargs):
    """Draw a lane table (see :func:`lanestyle.from_gmns` for the columns) as one roadstyle map and
    return roadstyle's ``WebMap`` (``.save(path)``, ``.html``).

    Each lane is one line on its own geometry, exactly ``width_m`` metres wide from
    ``width_m_zoom`` on (where null: ``width_m_by_use`` for a footpath or an on-road bike lane, else
    ``default_width_m``). Bus, bike and walk lanes are painted over the
    palette (a "Lane use" colouring; the legend lists only uses present). ``turns`` (``from_lane``,
    ``to_lane``, optional ``type``) makes a lane clickable: it turns red and the lanes it leads into
    green, U-turns purple. Lane lines (dividers, centre and edge lines, styled per type under
    ``lines``) come from ``link_id`` / ``lane_num`` (+ ``reverse_link_id``, node ids; see
    :func:`lanestyle.lines.lane_lines`). ``crossings``: duckOSM's crossing tables (:func:`lanestyle.read_crossings`, default
    ``lanes.attrs["crossings"]``), painted as zebra stripes along the lanes they name. ``settings``: roadstyle settings, plus a ``"lanes"`` key
    for lanestyle's own (``data/lanestyle.json``). ``street_view=True``: roadstyle's map + Google Street View page (a click on a lane shows the street
    at that point; ``street_view_key``: a Google Maps JavaScript API key for a real panorama, none for the keyless embed; ``panel_width`` 20-80 %).
    Other keywords go to ``roadstyle.render_edges``."""
    import roadstyle as rs

    s = lane_settings(settings)
    g = lanes.copy()
    g = _roads_only(g)
    g["use"] = g["use"].fillna("auto") if "use" in g else "auto"
    g["width_m"] = _widths(g, s)
    # every lane is coloured by its mode group (car, bus, bike, walk), not by its road's class; a use that has no
    # group of its own is a car lane's colour
    g["zebra"] = (g["footway"] == "crossing") if "footway" in g else False      # a crossing lane lies under the road, no lines of its own
    g["demoted"] = None
    _demote_crossings(g, s)                      # a "crossing" that is mostly no crossing is a footway
    colour_col, palette_colors, rows = _colour_groups(g, s)
    if "footway" in g and (g["footway"] == "crossing").any():      # a crosswalk is not a footway: its own, lighter colour and legend row
        if colour_col == "use":
            g["mode_group"], colour_col = g["use"], "mode_group"
        g.loc[g["footway"] == "crossing", colour_col] = "crossing"
        palette_colors = {**palette_colors, "crossing": s["colors"]["crossing"]}
        rows = [*rows, ("crosswalks", s["colors"]["crossing"])]
    if "footway" in g and (g["footway"] == "sidewalk").any():      # a mapped sidewalk: its own colour and legend row
        if colour_col == "use":
            g["mode_group"], colour_col = g["use"], "mode_group"
        g.loc[g["footway"] == "sidewalk", colour_col] = "sidewalk"
        palette_colors = {**palette_colors, "sidewalk": s["colors"]["sidewalk"]}
        rows = [*rows, ("sidewalks", s["colors"]["sidewalk"])]
    if "use" in g:      # a footway's two links are one strip people walk both ways: roadstyle must not pair them as a two-way road's lanes
        g["directed"] = g["use"] != "walk"
    on_road = _footpaths_on_roads(g)
    if "connector" in g and g["connector"].fillna(False).astype(bool).any():
        # a connector fills the gap between two lanes: drawn below the lanes of its level (roadstyle's per-edge order), so it never sits on a lane of another colour
        # and a connector that goes straight on (thru, merge, fork, a continued lane) above the ones that turn (left, right, U-turn): -250 over -300
        kind = dict(zip(zip(turns["from_lane"].astype(str), turns["to_lane"].astype(str)), turns["type"])) if turns is not None and len(turns) and "type" in turns else {}
        frm = g["from_lane"] if "from_lane" in g else [None] * len(g)
        to = g["to_lane"] if "to_lane" in g else [None] * len(g)
        g["draw_order"] = [(_connector_order(kind.get((str(a), str(b))) in ("left", "right", "uturn"), hw, m, -300.0, -250.0)) if c else float("nan")
                           for c, a, b, hw, m in zip(g["connector"].fillna(False).astype(bool), frm, to, _classes(g), _modes(g))]
    lowgrp = [_group(r) for r in g.itertuples(index=False)]
    if any(x.startswith("low@") for x in lowgrp):
        # layers below ground are one roadstyle band, drawn by road class: layer -1 must lie over layer -2 over -3 (colour and casing). Order = layer * 90 + a rank inside the
        # layer (its connectors under its lanes, straight ones above turns, a road class by roadstyle's z order, a footpath on a road above it): the ranks span under 90
        from roadstyle.render_web import ROAD_Z

        if "draw_order" not in g:
            g["draw_order"] = float("nan")
        kind_t = dict(zip(zip(turns["from_lane"].astype(str), turns["to_lane"].astype(str)), turns["type"])) if turns is not None and len(turns) and "type" in turns else {}
        onr = set(on_road)
        for i, gp in enumerate(lowgrp):
            if not gp.startswith("low@"):
                continue
            if "connector" in g and bool(g["connector"].iloc[i]):
                turn = kind_t.get((str(g["from_lane"].iloc[i]), str(g["to_lane"].iloc[i]))) in ("left", "right", "uturn")
                sub = _connector_order(turn, _classes(g)[i], _modes(g)[i], -30.0, -20.0)
            else:
                hw = str(g["highway"].iloc[i]).split(";")[0].removesuffix("_link") if "highway" in g else ""
                sub = float(ROAD_Z.get(hw, 4)) + (15.0 if i in onr else 0.0)
            g.iloc[i, g.columns.get_loc("draw_order")] = int(gp[4:]) * 90 + sub
    if "roundabout" in g and g["roundabout"].any():
        # a roundabout's ring lies over the arms that join it, whatever their colour: an arm of the ring's own class would end in a round cap on the ring
        import pandas as pd
        from roadstyle.render_web import ROAD_Z

        if "draw_order" not in g:
            g["draw_order"] = float("nan")
        ring = (g["roundabout"].fillna(False).astype(bool) & ~g["connector"].fillna(False).astype(bool) & g["draw_order"].isna()
                & ~pd.Series(lowgrp, index=g.index).str.startswith("low@")).to_numpy().nonzero()[0]
        hw = _classes(g)
        g.iloc[ring, g.columns.get_loc("draw_order")] = [float(ROAD_Z.get(hw[i], 4)) + 0.5 for i in ring]
    if on_road:           # a footpath mapped on a carriageway is drawn above it (roadstyle's per-edge order), else the road hides it
        if "draw_order" not in g:
            g["draw_order"] = float("nan")
        keep = [i for i in on_road if not lowgrp[i].startswith("low@")]
        g.iloc[keep, g.columns.get_loc("draw_order")] = 100.0
    opts = dict(directed_col="directed" if "use" in g else None, order_col="draw_order" if "draw_order" in g else None, color_options={"Road class": {}, "Lane use": {"color_by": colour_col, "colors": palette_colors}},
                color_active="Lane use")
    if "pos_fill" in g:       # the drawing order of each road: an interval [casing, fill] (docs/design/interval_draw_order.md); the layers go by position, not by band
        opts.update(casing_level_col="pos_casing", fill_level_col="pos_fill")
    conn = g["connector"].fillna(False).astype(bool) if "connector" in g else None
    if "footway" in g:             # what a footway is, in words: a crosswalk is no "footway" (OSM tags both: highway=footway + footway=crossing)
        cx = g["crossing"] if "crossing" in g else None
        g["kind"] = [("crosswalk" + (f" ({c})" if isinstance(c, str) and c else "")) if f == "crossing" else ("sidewalk" if f == "sidewalk" else d)
                     for f, c, d in zip(g["footway"], cx if cx is not None else [None] * len(g), g["demoted"])]
    if "along_link_id" in g and "edge_ref" in g and g["along_link_id"].notna().any():
        # the match, as the popup shows it: a footpath names the road it runs along (its route), a road the footpaths that run along it
        first = {}
        for lk, er in zip(g["link_id"], g["edge_ref"]):
            first.setdefault(lk, er)
        routes = g["along_links"] if "along_links" in g else [None] * len(g)
        g["along"] = [None if pd_isna(a) else f"{first.get(a, a)} ({k}" + (f", route of {len(rt)} roads" if isinstance(rt, list) and len(rt) > 1 else "") + ")"
                      for a, k, rt in zip(g["along_link_id"], g["along_kind"] if "along_kind" in g else [""] * len(g), routes)]
        onroad = {}
        for lk, rt, a in zip(g["link_id"], routes, g["along_link_id"]):
            for r_ in (rt if isinstance(rt, list) else ([] if pd_isna(a) else [a])):
                onroad.setdefault(r_, set()).add(first.get(lk, lk))
        g["footpaths"] = [", ".join(sorted(onroad[lk])[:5]) + (f" … ({len(onroad[lk])})" if len(onroad.get(lk, ())) > 5 else "") if lk in onroad else None
                          for lk in g["link_id"]]
    g["level"] = [_LEVEL[_level(r)] for r in g.itertuples()]    # always in the popup: "ground" says it is no bridge
    import pandas as pd

    if {"link_id", "lane_num"} <= set(g.columns):        # the link's twin: its other direction (the same line) or, for a road mapped as two one-way
        nc = g[~conn] if conn is not None else g         # ways, the one placed together with it; None for a one-way road with no twin
        part = _paired(nc.to_crs(nc.estimate_utm_crs())) if len(nc) else {}
        rev = g["reverse_link_id"] if "reverse_link_id" in g else None
        ref = dict(zip(g["link_id"], g["edge_ref"])) if "edge_ref" in g else {}        # name a twin by its edge_ref where there is one
        name = lambda k: ref.get(k) if isinstance(ref.get(k), str) else k                # noqa: E731
        g["twin"] = [f"{name(rv)} (reverse: the same line)" if rv is not None and not pd.isna(rv)
                     else (f"{name(part[lk])} (paired: two one-way ways placed together)" if lk in part else None)
                     for lk, rv in zip(g["link_id"], rev if rev is not None else [None] * len(g))]
    walk = g["use"] == "walk"                            # a footpath is walked both ways: no arrow
    if conn is not None:                                 # arrows on lanes, not on connectors
        g["oneway"] = ~conn & ~walk
    elif walk.any():
        g["oneway"] = ~walk
    if turns is not None and len(turns):                 # what each lane is for (label + popup)
        g["lane_type"] = _lane_types(g, turns)
        if conn is not None and conn.any():              # a connector says what it is, in words
            kind = dict(zip(zip(turns["from_lane"].astype(str), turns["to_lane"].astype(str)),
                            turns["type"] if "type" in turns else ["turn"] * len(turns)))
            road = dict(zip(g["lane_id"], g.get("name", [None] * len(g))))
            num = dict(zip(g["lane_id"], g.get("lane_num", [None] * len(g))))
            first = {}                                   # a road's name sits on its lane 1 only
            for lid, nm in road.items():
                if isinstance(nm, str):
                    first[str(lid).rsplit("_", 1)[0]] = nm

            def says(a, b):
                def lane(x):
                    n = num.get(x)
                    nm = first.get(str(x).rsplit("_", 1)[0]) or "(unnamed road)"
                    return f"lane {int(n)} of {nm}" if n == n and n is not None else str(x)
                return f"{lane(a)} → {lane(b)}"
            g.loc[conn, "lane_type"] = ["connector · " + _TYPE_WORD.get(kind.get((a, b)), kind.get((a, b)) or "turn")
                                         for a, b in zip(g.loc[conn, "from_lane"], g.loc[conn, "to_lane"])]
            g.loc[conn, "connects"] = [says(a, b) for a, b in zip(g.loc[conn, "from_lane"], g.loc[conn, "to_lane"])]
    if turns is not None and len(turns):                 # how many lanes lead in / out, for the popup
        g["turns_in"] = g["lane_id"].map(turns.groupby(turns["to_lane"].astype(str)).size()).fillna(0).astype(int)
        g["turns_out"] = g["lane_id"].map(turns.groupby(turns["from_lane"].astype(str)).size()).fillna(0).astype(int)
    cr = crossings if crossings is not None else lanes.attrs.get("crossings")
    zebra, zfoot = _zebra_stripes(g, cr, s["zebra"]) if s.get("zebra") else ([], None)
    gaps, frame, rims = frames(g, s)             # a road and its sidewalk within frame_gap_m: one frame
    lines = lane_lines(g, s, avoid=zfoot, frame=frame, frame_edges=rims)
    arrows = lane_arrows(g, turns, s.get("arrows"), avoid=zfoot)
    if arrows:                                   # the painted arrows are the one direction marking: roadstyle's chevrons go
        g["oneway"] = False
    fillets = junction_fillets(g, s)             # connectors included: their corners are the usual gaps
    if gaps:
        fillets = gaps if not fillets else {"type": "FeatureCollection", "features": fillets["features"] + gaps["features"]}
    draw = rs.render_edges
    if street_view_key and not street_view:      # the map's own Street View window: with a key it offers the real panorama (Linked)
        kwargs = {"street_view_key": street_view_key, **kwargs}
    if street_view:       # roadstyle's map + Google Street View page: click a lane, see the street; a Maps JavaScript API key makes it a real panorama
        draw = lambda *a, **k: rs.render_street_view(*a, street_view_key=street_view_key, **k)          # noqa: E731
    m = draw(
        _break_twins(g), palette=palette,
        width_m_col="width_m", width_m_zoom=s["width_m_zoom"], casing_m=s["casing_m"],
        road_popup=[c for c in _POPUP if c in g.columns],
        **{"select_color": s["colors"]["clicked"], **kwargs},   # roadstyle's own selection glow
        settings=_merge(_ROADSTYLE, {k: v for k, v in (settings or {}).items() if k != "lanes"}),
        **opts)
    js = ""
    if conn is not None and conn.any() and not s.get("connectors_clickable"):
        js += _NOPICK_JS
    body = _low_body(g, s) if s.get("tunnel_body") else None
    if body:
        js += _LOWBODY_JS.replace("__BODY__", json.dumps(body, separators=(",", ":"))).replace("__LAND__", s["tunnel_body"])
    if fillets:
        js += _FILLETS_JS.replace("__FILLETS__", json.dumps(fillets, separators=(",", ":")))
    if rows:                                             # the mode groups' colours as rows in the Roads box
        js += _USE_ROWS_JS.replace("__ROWS__", json.dumps([[label, c] for label, c in rows]))
    if lines:
        js += (_LINES_JS.replace("__LINES__", json.dumps(_compact(lines), separators=(",", ":")))
               .replace("__STYLES__", json.dumps(s["lines"])).replace("__ZOOM__", json.dumps(s["width_m_zoom"]))
               .replace("__MIN_DEVICE_PX__", json.dumps(s.get("line_min_device_px", 1))))
    if arrows:
        js += _ARROWS_JS.replace("__ARROWS__", json.dumps(arrows, separators=(",", ":"))).replace("__STYLE__", json.dumps(s["arrows"]))
    names = street_names(g, arrows, s.get("names"), avoid=zfoot)
    if names:
        js += _NAMES_JS.replace("__NAMES__", json.dumps(names, separators=(",", ":"))).replace("__STYLE__", json.dumps(s["names"]))
    # the zebra goes above the lane arrows (none on the stripes); the lane lines stop at its footprint
    if zebra:
        fc = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [ring]}} for ring in zebra]}
        js += (_ZEBRA_JS.replace("__ZEBRA__", json.dumps(fc, separators=(",", ":"))).replace("__STYLE__", json.dumps(s["zebra"]))
               .replace("__ZOOM__", json.dumps(s["width_m_zoom"])))
    if turns is not None and len(turns):
        via = {}                                         # (from lane, to lane) -> its connector
        if conn is not None and conn.any():
            via = dict(zip(zip(g.loc[conn, "from_lane"], g.loc[conn, "to_lane"]), g.loc[conn, "lane_id"]))
        js += _click_js(turns, s, via)
        if s.get("type_label_zoom") is not None:
            js += _LABELS_JS.replace("__ZOOM__", json.dumps(s["type_label_zoom"]))
    if not js:
        return m
    js = _ANCHOR_JS + js                                 # the helper first: every script below places its layers with it
    html = m.html
    i = html.rfind("</body>")
    return type(m)(html[:i] + js + html[i:])


def _click_js(turns, s, via=None):
    nxt, via = {}, via or {}
    types = turns["type"] if "type" in turns else [None] * len(turns)
    for a, b, t in zip(turns["from_lane"].astype(str), turns["to_lane"].astype(str), types):
        nxt.setdefault(a, [[], []])[t == "uturn"].append(b)
        if (a, b) in via:                                # and the connector into it
            nxt[a][t == "uturn"].append(via[a, b])
    return (_CLICK_JS.replace("__TURNS__", json.dumps(nxt, separators=(",", ":")))
            .replace("__COLORS__", json.dumps({k: s["colors"][k] for k in ("clicked", "turns_into", "uturn")})))


_SERVE_PY = '''#!/usr/bin/env python3
"""Static server for this lanestyle render.
   python serve.py [port]   ->  http://localhost:8080/__INDEX__"""
import sys, http.server, socketserver
from functools import partial
from pathlib import Path


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html") and self.path != "/__INDEX__":   # the root URL opens the map
            self.send_response(302)
            self.send_header("Location", "/__INDEX__")
            self.end_headers()
            return
        super().do_GET()

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")   # a rebuilt map shows on a plain reload
        super().end_headers()


socketserver.TCPServer.allow_reuse_address = True
port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
here = str(Path(__file__).resolve().parent)
for p in range(port, port + 20):                       # 8080 busy? hop to the next free port
    try:
        httpd = socketserver.TCPServer(("", p), partial(Handler, directory=here))
    except OSError:
        continue
    if p != port:
        print(f"port {port} busy -> using {p}")
    print(f"serving {here}")
    print(f"  open:    http://localhost:{p}/   (-> __INDEX__)")
    print(f"  REMOTE:  forward port {p}  (VS Code auto-forwards it in the Ports panel; "
          f"or `ssh -L {p}:localhost:{p} <host>`), then open the URL above")
    httpd.serve_forever()
    break
else:
    sys.exit(f"no free port in {port}..{port + 19}")
'''


def write_serve(out_html):
    """Drop a ``serve.py`` next to ``out_html`` — ``python serve.py [port]`` serves that folder (auto-hops
    off a busy port) and prints the map URL. Returns the serve.py path."""
    from pathlib import Path

    out_html = Path(out_html)
    serve = out_html.parent / "serve.py"
    serve.write_text(_SERVE_PY.replace("__INDEX__", out_html.name))
    return serve
