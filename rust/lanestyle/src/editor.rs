//! The lanes on the level area's roads: each road one line at its lanes' full width, and the road's own items (render `items=`): the
//! bus and bike lanes, the car lanes unseen (picked and highlighted only), the lane lines, zebras, sidewalks and marks, and the
//! connectors unseen and unpicked. The lane page and roadstyle's level editor use the same items (Python's `lanestyle.editor`).

use crate::arrows::mark_strokes;
use crate::geo::{self, Line};
use crate::items::{connector_strokes, lane_shifts, lane_strokes, link_roads, sidewalk_strokes, zebra_strokes};
use crate::lanes::{Lane, Lanes, Turn};
use crate::settings::{self, use_colour};
use serde_json::{json, Map, Value};
use std::collections::{BTreeSet, HashMap};

/// What `strokes` reads from the duckOSM source file: the OSM tags of the streets' ways (the sidewalks). None: no source file.
pub type WayTags = Option<HashMap<i64, Map<String, Value>>>;

/// Each lane's line cut where its junction begins (plain junctions): duckOSM's line to the nodes, cut at the points along it where SUMO's
/// line (`cut_geometry`) starts and ends. A lane without a cut line, or whose cut is under 1 m long, as it is.
pub fn to_junctions(l: &Lane) -> Line {
    let Some(cut) = l.cut_geometry.as_ref().filter(|c| !c.is_empty()) else { return l.geometry.clone() };
    let ln = &l.geometry;
    let (a, b) = (geo::project(ln, cut[0]), geo::project(ln, cut[cut.len() - 1]));
    if b > a {
        if let Some(p) = geo::substring(ln, a, b, false) {
            if p.len() >= 2 && geo::length(&p) * 111320.0 >= 1.0 {
                return p;
            }
        }
    }
    ln.clone()
}

/// Everything `lane_items` draws (Python's `editor._strokes`).
pub struct Strokes {
    pub lanes: Option<Value>,
    pub lines: Option<Value>,
    pub marks: Option<Value>,
    /// link -> its road's full width (metres)
    pub width: HashMap<String, f64>,
    /// link -> its road's line in the link's direction
    pub lines_of: HashMap<String, Line>,
    pub connectors: Option<Value>,
    pub zebras: Option<Value>,
    pub sidewalks: Option<Value>,
    /// the lanes drawn on the road: every bus, bike and bus + bike lane
    pub special: BTreeSet<String>,
}

/// The ids of the ways whose tags `strokes` needs (the sidewalks), from the lane table; empty when it needs none.
pub fn ways_needed(lanes: &Lanes, s: &Value) -> Vec<i64> {
    if s.get("sidewalk").is_none_or(|v| v.is_null() || v == &json!(false)) || !lanes.has("osm_id") {
        return Vec::new();
    }
    let ids: BTreeSet<i64> = roads_only(lanes).iter().filter(|l| !l.connector).filter_map(|l| l.osm_id).collect();
    ids.into_iter().collect()
}

/// The lanes of links that have a road class (a link with none is no road).
fn roads_only(lanes: &Lanes) -> Vec<&Lane> {
    lanes.rows.iter().filter(|l| !lanes.has("highway") || l.highway.is_some()).collect()
}

/// The lane table's lanes, lines and marks as items, each on its link, and each link's width and line. `connectors`: also duckOSM's lane
/// connectors as items of the link they leave. `tags`: the ways' tags (`ways_needed`) when there is a source file.
pub fn strokes(lanes: &Lanes, turns: &[Turn], s: &Value, connectors: bool, tags: &WayTags) -> Result<Strokes, String> {
    let f = |k: &str| s[k].as_f64().unwrap_or_default();
    let has_lanes = lanes.has("lanes") && lanes.has("lane_num");
    // every lane on its line to its nodes, its use and width filled
    let base: Vec<Lane> = roads_only(lanes).into_iter().map(|l| {
        let mut l = l.clone();
        let u = l.use_.clone().unwrap_or_else(|| "auto".into());
        l.width_m = Some(settings::width(s, l.width_m, &u, l.lane_num, l.lanes, has_lanes));
        l.use_ = Some(u);
        l
    }).collect();
    let has = |c: &str| lanes.has(c) || c == "use" || c == "width_m";
    let mut conn_fc = None;
    if connectors && base.iter().any(|l| l.connector) {
        let c: Vec<&Lane> = base.iter().filter(|l| l.connector).collect();
        let colours: Vec<String> = c.iter().map(|l| use_colour(s, l.use_.as_deref().unwrap_or("auto")).to_string()).collect();
        let w: HashMap<String, f64> = base.iter().map(|l| (l.lane_id.clone(), l.width_m.unwrap_or_default())).collect();
        conn_fc = connector_strokes(&c, &colours, &w)?;
    }
    let base: Vec<&Lane> = base.iter().filter(|l| !l.connector).collect();
    // the lanes, their lines and marks stop where a junction begins (base: the road to the nodes)
    let cut: Vec<Lane> = base.iter().map(|l| Lane { geometry: to_junctions(l), ..(*l).clone() }).collect();
    let g: Vec<&Lane> = cut.iter().collect();
    let colours: Vec<String> = g.iter().map(|l| use_colour(s, l.use_.as_deref().unwrap_or("auto")).to_string()).collect();
    let roads = link_roads(&base, f("casing_m"), f("centre_line_m"));
    let lines_set = if s["lines"].as_object().is_some_and(|o| !o.is_empty()) { s["lines"].clone() } else { json!({"divider": false, "centre": false}) };
    let num_float = lanes.has("from_lane");
    let (lane_fc, line_fc) = lane_strokes(&g, &colours, &roads.road_of, f("centre_line_m"), &lines_set, f("junction_trim_m"), &roads.ext, num_float, &has)?;
    let road_w: HashMap<i64, f64> = roads.roads.iter().map(|r| (r.0, r.1)).collect();
    let width: HashMap<String, f64> = roads.road_of.iter().filter_map(|(lk, rd)| Some((lk.to_string(), *road_w.get(rd)?))).collect();
    let line: HashMap<i64, &Line> = roads.roads.iter().map(|r| (r.0, &r.2)).collect();
    let lines_of: HashMap<String, Line> = roads.road_of.iter().filter_map(|(lk, rd)| {
        let l = line.get(rd)?;
        Some((lk.to_string(), if lk == rd { (*l).clone() } else { l.iter().rev().copied().collect() }))
    }).collect();
    let zebra_fc = if s.get("zebra").is_some_and(|z| z.as_object().is_some_and(|o| !o.is_empty())) {
        let colour = s["lines"].get("color").cloned().unwrap_or(json!("#f2f2f2"));
        zebra_strokes(&g, lanes.crossings.as_deref(), &s["zebra"], &colour)
    } else { None };
    let side_fc = match tags {
        Some(t) if s.get("sidewalk").is_some_and(|v| v.as_object().is_some_and(|o| !o.is_empty())) && lanes.has("osm_id") =>
            sidewalk_strokes(&base, &roads.road_of, &lines_of, &width, t, &s["sidewalk"], &s["colors"]["walk"]),
        _ => None,
    };
    let shifts = lane_shifts(&g, &roads.road_of, f("centre_line_m"));
    let marks_fc = if lanes.has("link_id") { mark_strokes(&g, turns, &s["arrows"], &shifts, "#ffffff")? } else { None };
    let special = g.iter().filter(|l| { let u = l.use_.as_deref().unwrap_or(""); u.starts_with("bus") || u == "bike" }).map(|l| l.lane_id.clone()).collect();
    Ok(Strokes { lanes: lane_fc, lines: line_fc, marks: marks_fc, width, lines_of, connectors: conn_fc, zebras: zebra_fc, sidewalks: side_fc, special })
}

/// The OSM `width` tag of each of these ways (a way without one is not in the map).
pub type WidthTags<'a> = dyn Fn(&[i64]) -> Result<HashMap<i64, String>, String> + 'a;

/// One row of the editor's road table (one edge): what `lane_items` reads of it.
#[derive(Clone, Debug, Default)]
pub struct RoadRow {
    pub edge: String,
    pub road: String,
    pub edge_ref: Option<String>,
    pub highway: Option<String>,
    pub modes: Option<String>,
    pub geometry: Line,
}

/// What `lane_items` gives: the render keywords (with `items`) and each road row's new width and line.
pub struct Items {
    pub kw: Map<String, Value>,
    pub width_m: Vec<f64>,
    pub geometry: Vec<Line>,
    /// what Python printed
    pub notes: Vec<String>,
}

/// The way of an edge_ref (`<way>#<piece><f|r>`, a negative way: its OSM way with a minus).
pub fn way_of_ref(r: &str) -> Option<i64> {
    let end = r.char_indices().find(|(i, c)| !(c.is_ascii_digit() || (*i == 0 && *c == '-'))).map_or(r.len(), |(i, _)| i);
    r[..end].parse::<i64>().ok().map(i64::abs)
}

/// The editor's hook (Python's `lane_items`): each road one line at its full width (`width_m`; a road without lanes: its OSM width tag
/// in metres, else `path_width_m` by its class) on the lanes' line, in the car lane colour; the road's own items; the render keywords.
/// `roads`: the editor's table (`has_modes`: it has the column `modes`); `st`: `strokes`; `amber`: roadstyle's palette "amber" (`{class: style}`); `width_tag`: the OSM width tag
/// of a way (the roads without lanes).
pub fn lane_items(roads: &[RoadRow], has_modes: bool, st: &Strokes, s: &Value, amber: &Map<String, Value>, width_tag: &WidthTags)
                  -> Result<Items, String> {
    let road_of: HashMap<&str, &str> = roads.iter().map(|r| (r.edge.as_str(), r.road.as_str())).collect();
    let mut notes = Vec::new();
    let mut on_edges = |fc: &Option<Value>, pick: bool, seen: &dyn Fn(&Value) -> bool| -> Vec<Value> {
        let fs = fc.as_ref().and_then(|f| f["features"].as_array()).cloned().unwrap_or_default();
        let total = fs.len();
        let out: Vec<Value> = fs.into_iter().filter_map(|mut f| {
            let e = match &f["properties"]["edge_id"] { Value::String(t) => t.clone(), v => v.to_string() };
            let road = road_of.get(e.as_str())?.to_string();
            let visible = seen(&f);
            let p = f["properties"].as_object_mut()?;
            p.insert("edge".into(), json!(e));
            p.insert("road".into(), json!(road));
            if let Some(v) = p.get("link_id").filter(|v| !v.is_null()).cloned() {
                p.insert("link_id".into(), json!(match v { Value::String(t) => t, v => v.to_string() }));
            }
            p.insert("pick".into(), json!(pick));
            if !visible {
                p.insert("color".into(), json!("rgba(0,0,0,0)"));
            }
            Some(f)
        }).collect();
        if out.len() < total {
            notes.push(format!("lanestyle.editor: {} of {total} items are on links that are no edge of the area: left out", total - out.len()));
        }
        out
    };
    let special = &st.special;
    let mut items = on_edges(&st.lanes, true, &|f| f["properties"]["lane_id"].as_str().is_some_and(|i| special.contains(i)));
    for fc in [&st.lines, &st.zebras, &st.sidewalks, &st.marks] {
        items.extend(on_edges(fc, false, &|_| true));
    }
    items.extend(on_edges(&st.connectors, false, &|_| false));
    // the road's width and line from its edge with lanes, whichever edge draws it; the other direction runs the line backwards
    let mut own: HashMap<&str, &str> = HashMap::new();
    for r in roads {
        if st.width.contains_key(&r.edge) {
            own.insert(r.road.as_str(), r.edge.as_str());
        }
    }
    let mut width_m: Vec<f64> = roads.iter().map(|r| own.get(r.road.as_str()).and_then(|e| st.width.get(*e)).copied().unwrap_or(f64::NAN)).collect();
    // a road without lanes in metres too: its OSM width tag, else path_width_m by its class
    let need: Vec<usize> = (0..roads.len()).filter(|&i| width_m[i].is_nan()).collect();
    if !need.is_empty() {
        let ways: Vec<Option<i64>> = need.iter().map(|&i| roads[i].edge_ref.as_deref().and_then(way_of_ref)).collect();
        let mut ids: Vec<i64> = ways.iter().flatten().copied().collect();
        ids.sort();
        ids.dedup();
        let tags = width_tag(&ids)?;
        let table = s["path_width_m"].as_object().cloned().unwrap_or_default();
        let mut unread = Vec::new();
        for (k, &i) in need.iter().enumerate() {
            let tag = ways[k].and_then(|w| tags.get(&w));
            let (w, bad) = settings::path_width(roads[i].highway.as_deref(), tag.map(String::as_str), &table);
            width_m[i] = w;
            unread.extend(bad);
        }
        if !unread.is_empty() {
            let set: BTreeSet<String> = unread.iter().cloned().collect();
            notes.push(format!("lanestyle.editor: {} width tags are no width in metres, the class width instead: {:?}", unread.len(),
                               set.into_iter().take(5).collect::<Vec<_>>()));
        }
    }
    let geometry: Vec<Line> = roads.iter().map(|r| {
        if let Some(l) = st.lines_of.get(&r.edge) {
            l.clone()
        } else if let Some(l) = own.get(r.road.as_str()).and_then(|e| st.lines_of.get(*e)) {
            l.iter().rev().copied().collect()
        } else {
            r.geometry.clone()
        }
    }).collect();
    let mut kw = Map::new();
    kw.insert("width_m_col".into(), json!("width_m"));
    kw.insert("width_m_zoom".into(), json!(0));
    kw.insert("casing_m".into(), json!(s["casing_m"].as_f64()));
    kw.insert("casing_min_px".into(), json!(s["casing_min_px"].as_f64()));
    kw.insert("arrows".into(), json!(false));
    kw.insert("items".into(), json!({"type": "FeatureCollection", "features": items}));
    kw.insert("items_popup".into(), json!(["road", "name", "lane_id", "lane_num", "use", "width_m", "link_id"]));
    let test = std::env::var("LANESTYLE_CASING_COLOR").ok().filter(|t| !t.is_empty());
    let auto = s["colors"]["auto"].clone();
    let pal: Map<String, Value> = amber.iter().map(|(c, v)| {
        let mut v = v.as_object().cloned().unwrap_or_default();
        v.insert("fill".into(), auto.clone());
        if let Some(t) = &test {
            v.insert("casing".into(), json!(t));
        }
        (c.clone(), Value::Object(v))
    }).collect();
    let classes: BTreeSet<&str> = roads.iter().filter_map(|r| r.highway.as_deref()).collect();
    let mut cfg = json!({"single_line_classes": classes, "labels": {"color": "#333333", "halo_color": "#ffffff", "halo_width": 1.5,
                         "size": [[15, 10], [17, 12], [19, 15], [21, 20], [22, 24]]}});
    kw.insert("palette".into(), json!("lanestyle_editor"));
    if let Some(t) = &test {
        cfg["bridge_casing_color"] = json!(t);
        if let Ok(tun) = std::env::var("LANESTYLE_TUNNEL_CASING") {
            if !tun.is_empty() {
                cfg["tunnel_palettes"] = json!({"lanestyle_test": tun.split(',').collect::<Vec<_>>()});
                cfg["tunnel_palette"] = json!("lanestyle_test");
            }
        }
    }
    kw.insert("settings".into(), json!({"palettes": {"lanestyle_editor": pal}, "config": cfg}));
    // a road cars do not use in lanestyle's colour for who uses it (colors.groups); every other road in the car lane colour
    if !has_modes {
        return Err("lanestyle.editor.lane_items: the area's roads have no per-edge modes (who uses each road): make the area again".into());
    }
    let mut who: HashMap<&str, BTreeSet<String>> = HashMap::new();
    for r in roads {
        let e = who.entry(r.road.as_str()).or_default();
        e.extend(r.modes.as_deref().unwrap_or_default().split('+').map(|x| { let x = x.trim(); x.strip_suffix(" (private)").unwrap_or(x).to_string() }));
    }
    let groups = &s["colors"]["groups"];
    let colour: HashMap<&str, Value> = who.iter().map(|(r, w)| {
        let users: Vec<&str> = ["walking", "cycling"].into_iter().filter(|x| w.contains(*x)).collect();
        (*r, if w.contains("driving") || users.is_empty() { auto.clone() } else { groups[users.join("+")].clone() })
    }).collect();
    let table: Map<String, Value> = roads.iter().map(|r| (r.edge.clone(), colour[r.road.as_str()].clone())).collect();
    kw.insert("color_table".into(), Value::Object(table));
    kw.insert("color_key".into(), json!("edge"));
    Ok(Items { kw, width_m, geometry, notes })
}
