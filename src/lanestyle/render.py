"""The engine: a lane table drawn with roadstyle, one line per lane at its width in metres.

    import lanestyle as ls
    lanes, turns = ls.from_gmns("monaco_gmns.duckdb", source_db="monaco.duckdb")
    ls.render_lanes(lanes, turns=turns).save("lanes.html")

Design: docs/design/lanestyle_on_roadstyle.md.
"""
import json
from pathlib import Path

from lanestyle import items
from lanestyle.arrows import lane_arrows
from lanestyle.frames import frames
from lanestyle.junctions import junction_fillets
from lanestyle.levels import COLUMNS, by_link, link_levels, own_levels, stored_head_m
from lanestyle.lines import _group, _level, _paired

_LEVEL = {"bridge": "bridge", "high": "above ground", "ground": "ground", "low": "tunnel / below ground"}
def pd_isna(v):
    import pandas as pd

    return v is None or bool(pd.isna(v))


_POPUP = ["name", "lane_type", "connects", "highway", "kind", "level", "footway", "edge_ref", "along", "footpaths", "twin", "lane_id", "lane_num", "lanes", "use", "modes", "turn", "width_m", "tunnel", "bridge",
          "casing head start", "casing body", "casing head end", "fill", "layer", "turns_in", "turns_out", "from_lane", "to_lane", "link_id", "reverse_link_id", "osm_id", "from_node_id",
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
    def key(u):          # a shared lane ("bus,bike": a bus lane bikes may use) is the first of bus, bike, walk it allows; a use of none of them is a car lane's
        return u if u in _MARKED else next((m for m in ("bus", "bike", "walk") if m in u.split(",")), "auto")
    keys = {u: key(u) for u in set(g["use"])}
    present = [k for k in _MARKED if k in set(keys.values())]
    return "use", {u: col[k] for u, k in keys.items()}, [(_USE_NAME[k], col[k]) for k in present]

# click a lane: it turns `clicked`, the lanes its turns lead into `turns_into`, U-turns `uturn`. The lanes (and their connectors) are the features of the overlays "lanes" and "connectors":
# roadstyle's `rsColor` paints one set one colour on an overlay, so the three sets are painted here, on the overlays' layers (docs/design/lanestyle_on_roadstyle_items.md).
# roadstyle feature ids are indexes into an overlay's source: lane_id -> id is built on the first click.
_CLICK_JS = """<script>
(function(){
  const T = __TURNS__, C = __COLORS__, fillOf = {};
  let idx = null;
  const ov = label => (window.RS_OVERLAYS || []).find(o => o.label === label);
  const layers = label => { const o = ov(label); return o ? o.layers.filter(id => map.getLayer(id) && map.getLayer(id).type === "fill") : []; };
  function paint(sets) {                  // sets: {label: [[ids, colour], ...]}
    for (const label in sets) layers(label).forEach(id => {
      if (!(id in fillOf)) fillOf[id] = map.getPaintProperty(id, "fill-color");
      let e = fillOf[id];
      const groups = sets[label].filter(([ids]) => ids.length);
      if (groups.length) { const c = ["case"]; groups.forEach(([ids, col]) => c.push(["in", ["id"], ["literal", ids]], col)); c.push(fillOf[id]); e = c; }
      map.setPaintProperty(id, "fill-color", e);
    });
  }
  function index() {
    idx = {};
    for (const label of ["lanes", "connectors"]) if (ov(label)) { const all = rsQuery(() => true, label), rows = rsGetProps(all, label);
      all.forEach((id, k) => { idx[rows[k].lane_id] = [label, id]; }); }
  }
  const pick = ls => { const out = {lanes: [], connectors: []}; (ls || []).forEach(l => { const x = idx[l]; if (x) out[x[0]].push(x[1]); }); return out; };
  document.addEventListener("rs:select", e => {
    const d = e.detail || {};
    if (d.overlay !== "lanes" || d.id == null) return;
    if (!idx) index();
    const t = T[(d.properties || {}).lane_id] || [], into = pick(t[0]), uturn = pick(t[1]);
    paint({lanes: [[[d.id], C.clicked], [into.lanes, C.turns_into], [uturn.lanes, C.uturn]],
           connectors: [[into.connectors, C.turns_into], [uturn.connectors, C.uturn]]});
  });
  document.addEventListener("rs:deselect", () => paint({lanes: [], connectors: []}));
  // a link can open the map at a spot: page.html#zoom/lat/lon (roadstyle fits the data first, so go again once the map is idle)
  const go = () => { const h = location.hash.slice(1).split("/").map(Number);
    if (h.length === 3 && !h.some(isNaN)) map.jumpTo({zoom: h[0], center: [h[2], h[1]]}); };
  go(); window.addEventListener("hashchange", go); map.once("idle", go);
})();
</script>
"""


# roadstyle's Street View panel and window answer road clicks only (an overlay click carries no ``streetView``), and a click on a lane is an overlay click: this passes it on as a click on the lane's road,
# at the clicked point, so the panel and its map marker follow it.
_STREET_VIEW_JS = """<script>
(function(){
  let at = null;
  map.on("click", e => { at = e.lngLat; });                       // after roadstyle's own handler, which has just dispatched rs:select
  document.addEventListener("rs:select", e => {
    const d = e.detail || {};
    if (d.overlay !== "lanes" || (d.properties || {}).road_id == null) return;
    setTimeout(() => {
      const rid = Number(d.properties.road_id), id = rsQuery(p => Number(p.edge_id) === rid)[0];     // the lane's road_id is a rounded number, the road's edge_id an exact string
      if (id == null || !at) return;
      const f = _feats()[id];
      document.dispatchEvent(new CustomEvent("rs:select", {detail: {id: id, layer: null, properties: (f || {}).properties || {}, streetView: _svPick(at, f, id)}}));
    }, 0);
  });
})();
</script>
"""


# roadstyle draws a road's casing at a width in pixels; at lane scale (from ``width_m_zoom``) the lanes are as wide as they are and the casing is their outline. Below that zoom the casing is
# off (Kaveh: "just set it to not show the casing at zoom less than 16")
_CASING_ZOOM_JS = """<script>
(function(){
  const z = __ZOOM__;
  const hide = () => { try { map.getStyle().layers.forEach(l => { if (/^roads-casing/.test(l.id) && map.getLayer(l.id).minzoom !== z) map.setLayerZoomRange(l.id, z, 24); }); } catch (e) {} };
  hide(); map.on("styledata", hide); map.once("idle", hide);       // the style may not be ready when this runs; the full map's was not
})();
</script>
"""


# roadstyle's tunnel pattern (light dashes) is a translucent stroke as wide as the road: on a roundabout ring, tight against the lane width, its dashes pile up into shards. The pattern stays on every
# tunnel road but a roundabout's (Kaveh: "remove it only from the tunnel roundabout")
_NO_PATTERN_ON_RINGS_JS = """<script>
(function(){
  const fix = () => { try { map.getStyle().layers.forEach(l => { if (/^roads-fill.*-pat$/.test(l.id)) { const f = map.getFilter(l.id);
      if (f && !JSON.stringify(f).includes('"roundabout"')) map.setFilter(l.id, ["all", f, ["!", ["to-boolean", ["get", "roundabout"]]]]); } }); } catch (e) {} };
  fix(); map.on("styledata", fix); map.once("idle", fix);
})();
</script>
"""


# where a lane's layers go in the page: right after (or before) the fill layers of the lane's position in roadstyle's drawing order ("-8", "0", "4": its layers roads-fill-lv-8,
# roads-fill, roads-fill-lv4 ..., docs/design/lanestyle_on_roadstyle_levels.md). ``lsAnchor(ids, position, before)``: the layer id, or null when the page has none.
_ANCHOR_JS = """<script>
window.lsAnchor = function(ids, b, before){       // before: false = after the position's fill, true = before it, 2 = the casing slot (before its underlay too)
  const base = b === "0" ? "roads-fill" : "roads-fill-lv" + b;
  const c = before === 2 ? [base + "-under", base] : before ? [base] : [base + "-pat", base];
  return c.find(id => ids.includes(id)) || null;
};
</script>
"""


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
                         "tunnel_fill_dash_color": "rgba(255,255,255,0.35)"},      # the light dashes along a tunnel (its pattern) are on; the road lines are simplified (items.link_roads) so they do not fan
              # one grey per class, and no class dashes: a footway, path, cycleway or track lane is a solid strip like any lane
              "palettes": {name: {c: {"fill": "#a3a3a3", "casing": "#5a5a5a", "dash": None} for c in _CLASSES}
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


# a lane's type label: the turns that leave it, in this order, as these words
_TYPE_ORDER = ["left", "uturn", "thru", "diverge", "merge", "right"]
_TYPE_WORD = {"left": "left", "uturn": "U-turn", "thru": "thru", "diverge": "fork", "merge": "merge",
              "right": "right"}

# the type label along each lane (lane_type), from zoom __ZOOM__, in roadstyle's street-name font
_LABELS_JS = """<script>
(function(){
  function add(){
    if (map.getLayer("lane-type-labels")) return;
    const own = map.getStyle().layers.map(l => l.id).find(id => id.startsWith("roads-labels"));      // roadstyle's name layer of any position: its font
    const font = own ? map.getLayoutProperty(own, "text-font") : null;
    const lanes = (window.RS_OVERLAYS || []).find(o => o.label === "lanes");      // lanes only; a connector says it in its popup
    if (!lanes) return;
    map.addLayer({id: "lane-type-labels", type: "symbol", source: lanes.source, minzoom: __ZOOM__,
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
    """Each lane's type label: the turns that leave it (``left + thru``, ``U-turn``, ``fork`` (a fork whose branches have no letter), ``merge``)
    or ``end`` where none does; a bus or bike lane says so first (``bus · thru``)."""
    out = {}
    types = turns["type"] if "type" in turns else ["turn"] * len(turns)
    if "turn" in turns:                          # a fork's branch says which way it goes (duckOSM's movement code): the lane is "left" or "thru", not "fork"
        types = types.where(turns["turn"].isna(), turns["turn"])
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


def lane_theme():
    """The lanestyle theme as roadstyle settings: ``styles/themes/lanestyle.yaml``, whose ``config.overlays.styles`` are the looks of the items (docs/design/lanestyle_on_roadstyle_items.md)."""
    import yaml

    return yaml.safe_load((Path(__file__).parent / "styles" / "themes" / "lanestyle.yaml").read_text(encoding="utf-8"))


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
    """The zebra stripes from duckOSM's crossing table, ``(rings, links, footprint)``: the stripes as lon/lat polygon rings, the link of each, and the zebras' rectangles as one lon/lat geometry (the lane
    lines and arrows keep clear of it). ``cr``: :func:`lanestyle.read_crossings`.

    One rectangle per crossing, the table's ``crossing.geom``: ``width`` along the road, ``length`` across the whole road it crosses. It is cut into stripes across its length, ``stripe_m``
    thick, ``stripe_m + gap_m`` apart (the row centred), each as long as the rectangle is wide: parallel to the lanes. That is all: the stripes are not clipped to the lanes, the data's rectangle is
    the zebra. A stripe belongs to the road of the lane that lies under it, told by the table's ``across_from`` .. ``across_to`` of each lane (metres from the rectangle's first edge); where no lane
    lies under it (an island), to the nearest."""
    import math

    from shapely import wkt as _w
    from shapely.geometry import Polygon

    if cr is None or not len(cr) or "painted" not in cr or "cgeom" not in cr:
        return [], [], None
    cr = cr[cr["painted"].fillna(False).astype(bool)]
    if not len(cr):
        return [], [], None
    import geopandas as gpd
    import shapely

    u = g.estimate_utm_crs()
    pitch, thick = st["stripe_m"] + st["gap_m"], st["stripe_m"]
    stripes, foot, links = [], [], []
    link_of = dict(zip(g["lane_id"], g["link_id"]))
    for _cid, grp in cr.groupby("crossing_id"):
        rect = gpd.GeoSeries([_w.loads(grp["cgeom"].iloc[0])], crs=4326).to_crs(u).iloc[0]
        if rect.geom_type != "Polygon":
            continue
        (x0, y0), (x1, y1), _, (x3, y3) = list(rect.exterior.coords)[:4]
        length = math.hypot(x1 - x0, y1 - y0)                       # across the road: the rectangle's first side
        wx, wy = x3 - x0, y3 - y0                                   # along the road: the second side, as long as the zebra is wide
        if length < thick or math.hypot(wx, wy) < 0.5:
            continue
        under = [(r.across_from, r.across_to, int(link_of[r.lane_id])) for r in grp.itertuples() if r.lane_id in link_of]
        if not under:
            continue
        dx, dy = (x1 - x0) / length, (y1 - y0) / length
        n = int((length - thick) // pitch) + 1
        first = (length - ((n - 1) * pitch + thick)) / 2
        for i in range(n):
            t0 = first + i * pitch
            a, b = (x0 + dx * t0, y0 + dy * t0), (x0 + dx * (t0 + thick), y0 + dy * (t0 + thick))
            stripes.append(Polygon([a, b, (b[0] + wx, b[1] + wy), (a[0] + wx, a[1] + wy)]))
            mid = t0 + thick / 2
            links.append(min(under, key=lambda x: 0.0 if x[0] <= mid <= x[1] else min(abs(mid - x[0]), abs(mid - x[1])))[2])
        foot.append(rect)
    if not stripes:
        return [], [], None
    back = gpd.GeoSeries(stripes, crs=u).to_crs(4326)
    footprint = gpd.GeoSeries([shapely.union_all(foot)], crs=u).to_crs(4326).iloc[0] if foot else None
    return [[[round(x, 7), round(y, 7)] for x, y in p.exterior.coords] for p in back], links, footprint


def _roads_only(g):
    """The lanes of links that have a road class: a link with none is no road (a ferry in the walking network, a way with no ``highway`` tag)."""
    return g[g["highway"].notna()] if "highway" in g and g["highway"].isna().any() else g


def render_lanes(lanes, turns=None, palette="mono", settings=None, crossings=None, street_view=False, street_view_key=None, source_db=None, **kwargs):
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
    import numpy as np
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
    turns_all = turns                                    # the connectors are labelled and ordered by every movement, a lane's arrows and counts leave the walkers' out
    if turns is not None and "walkers" in turns:
        turns = turns[~turns["walkers"].astype(bool)].reset_index(drop=True)
    on_road = _footpaths_on_roads(g)
    # the roads: one per link, with the line of its carriageway (roadstyle draws their casing, not their fill); their casing and fill numbers, read from the duckOSM file when
    # `duckosm levels` stored them, else computed by roadstyle (docs/design/lanestyle_on_roadstyle_items.md); every lane and connector takes the numbers of its link
    conn = g["connector"].fillna(False).astype(bool) if "connector" in g else None
    isconn = conn.to_numpy() if conn is not None else np.zeros(len(g), dtype=bool)
    head_m = float(s["head_m"]) if s.get("head_m") else (stored_head_m(source_db or lanes.attrs.get("source_db")) or 5.0)      # settings["lanes"]["head_m"] if given, else the stored numbers' own head length
    roads = items.link_roads(g[~isconn], float(s["casing_m"]), float(s["centre_line_m"]))
    roads[list(COLUMNS)] = link_levels(roads, source_db or lanes.attrs.get("source_db"), head_m).to_numpy()
    road_of = roads.attrs["road_of"]
    g[list(COLUMNS)] = by_link(roads, [road_of.get(int(k), k) for k in g["link_id"]])
    own = own_levels(g["link_id"].to_numpy(), source_db or lanes.attrs.get("source_db"))      # the popup shows the numbers of the lane's own link (its heads in its own direction), whole;
    for k, (col, shown) in enumerate(zip(COLUMNS, ("casing head start", "casing body", "casing head end", "fill"))):          # drawing uses its road's (the two directions of a street are one road)
        v = np.where(np.isnan(own[:, k]), g[col].to_numpy(dtype=float), own[:, k])
        g[shown] = [None if np.isnan(x) else int(x) for x in v]
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
    if turns is not None and len(turns):                 # what each lane is for (label + popup)
        g["lane_type"] = _lane_types(g, turns)
        if conn is not None and conn.any():              # a connector says what it is, in words
            kind = dict(zip(zip(turns_all["from_lane"].astype(str), turns_all["to_lane"].astype(str)),
                            turns_all["type"] if "type" in turns_all else ["turn"] * len(turns_all)))
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
            g["connects"] = pd.Series([None] * len(g), index=g.index, dtype=object)   # not str: pandas 3 turns the gaps into 'nan'
            g.loc[conn, "connects"] = [says(a, b) for a, b in zip(g.loc[conn, "from_lane"], g.loc[conn, "to_lane"])]
    if turns is not None and len(turns):                 # how many lanes lead in / out, for the popup
        g["turns_in"] = g["lane_id"].map(turns.groupby(turns["to_lane"].astype(str)).size()).fillna(0).astype(int)
        g["turns_out"] = g["lane_id"].map(turns.groupby(turns["from_lane"].astype(str)).size()).fillna(0).astype(int)
    cr = crossings if crossings is not None else lanes.attrs.get("crossings")
    zebra, zlinks, zfoot = _zebra_stripes(g, cr, s["zebra"]) if s.get("zebra") else ([], [], None)
    gaps, frame, _ = frames(g, s)                # a road and its sidewalk within frame_gap_m: one frame
    arrows = lane_arrows(g, turns, s.get("arrows"), avoid=zfoot)
    fillets = junction_fillets(g, s)             # connectors included: their corners are the usual gaps
    if gaps:
        fillets = gaps if not fillets else {"type": "FeatureCollection", "features": fillets["features"] + gaps["features"]}
    draw = rs.render_edges
    if street_view_key and not street_view:      # the map's own Street View window: with a key it offers the real panorama (Linked)
        kwargs = {"street_view_key": street_view_key, **kwargs}
    if street_view:       # roadstyle's map + Google Street View page: click a lane, see the street; a Maps JavaScript API key makes it a real panorama
        draw = lambda *a, **k: rs.render_street_view(*a, street_view_key=street_view_key, **k)          # noqa: E731
    # the items: each is attached to its road (road_id) and has its order; roadstyle draws them at the fill number of their road (the order scale: lanestyle.items)
    colours = g[colour_col].map(palette_colors)
    popup = [c for c in _POPUP if c in g.columns]
    on_mask = np.zeros(len(g), dtype=bool)
    on_mask[on_road] = True
    land = s["tunnel_body"]
    lane_fc, line_fc = items.lane_strokes(g[~isconn], colours[~isconn], land, popup, road_of, float(s["centre_line_m"]), s["lines"] or {"divider": False, "centre": False},
                                          float(s["junction_trim_m"]), on_road=np.nonzero(on_mask[~isconn])[0], level_of=_level,
                                          ext=roads.attrs["ext"])
    conn_fc = (items.connector_strokes(g[isconn], colours[isconn], land, popup, dict(zip(g["lane_id"], g["width_m"])), level_of=_level)
               if s.get("connectors", True) else None)      # lanestyle.json "connectors": false leaves them off (2026-10-10: roads first, then junctions)
    overlays = [rs.Overlay(items.on_roads(fc, road_of), edge_col="road_id", order_col="order", style=style, label=label, popup=pop, **extra)
                for fc, style, label, pop, extra in (
                    (conn_fc, None, "connectors", popup if s.get("connectors_clickable") else [], {"color_col": "color", "width_m_col": "width_m", "offset_m_col": "offset_m"}),
                    (lane_fc, None, "lanes", popup, {"color_col": "color", "width_m_col": "width_m", "offset_m_col": "offset_m", "select": "item"}),
                    (line_fc, None, "lane lines", [], {"color_col": "color", "width_m_col": "width_m", "offset_m_col": "offset_m"}),
                    (items.stripes(zebra, zlinks), "zebra", "zebra crossings", [], {}),
                    (items.tag(arrows, items.ARROW), "lane_arrow", "lane arrows", [], {})) if fc]
    rs_settings = _merge(_merge(lane_theme(), _ROADSTYLE), {k: v for k, v in (settings or {}).items() if k != "lanes"})
    m = draw(
        roads, palette=palette, road_fill=False, edge_id_col="edge_id", directed_col="directed", overlays=overlays,
        width_m_col="width_m", width_m_zoom=s["width_m_zoom"], casing_m=float(s["casing_m"]), cap_start_col="cap0", cap_end_col="cap1",
        casing_level_col="casing_level", fill_level_col="fill_level", casing_start_col="casing_start", casing_end_col="casing_end", head_m=head_m,
        arrows=False, labels=True,                 # the lane arrows are lanestyle's own items; the street names are roadstyle's, one per road (its ``name``)
        road_popup=[c for c in ("name", "highway", "edge_ref", "osm_id") if c in roads.columns],
        **{"select_color": s["colors"]["clicked"], **kwargs},   # roadstyle's own selection glow
        settings=rs_settings)
    js = ""
    if fillets:
        js += _FILLETS_JS.replace("__FILLETS__", json.dumps(fillets, separators=(",", ":")))
    if rows:                                             # the mode groups' colours as rows in the Roads box
        js += _USE_ROWS_JS.replace("__ROWS__", json.dumps([[label, c] for label, c in rows]))
    if turns is not None and len(turns):
        via = {}                                         # (from lane, to lane) -> its connector
        if conn is not None and conn.any():
            via = dict(zip(zip(g.loc[conn, "from_lane"], g.loc[conn, "to_lane"]), g.loc[conn, "lane_id"]))
        js += _click_js(turns, s, via)
        if s.get("type_label_zoom") is not None:
            js += _LABELS_JS.replace("__ZOOM__", json.dumps(s["type_label_zoom"]))
    js += _CASING_ZOOM_JS.replace("__ZOOM__", json.dumps(float(s["width_m_zoom"]))) + _NO_PATTERN_ON_RINGS_JS
    js += _STREET_VIEW_JS                                # the map's own Street View window needs it as much as the Street View page
    js = _ANCHOR_JS + js                                 # the helper first: the fillets are placed with it
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


socketserver.ThreadingTCPServer.allow_reuse_address = True
port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
here = str(Path(__file__).resolve().parent)
for p in range(port, port + 20):                       # 8080 busy? hop to the next free port
    try:
        httpd = socketserver.ThreadingTCPServer(("", p), partial(Handler, directory=here))
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
