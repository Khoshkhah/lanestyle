//! The roads and the items attached to them: lanes, lane lines, connectors, zebra stripes and sidewalks as LINE items of roadstyle
//! (`render_edges(items=)`): each has `edge_id` (its link) and `order` (lower first).

use crate::geo::{self, round_line, Line, Utm, P};
use crate::lanes::{Crossing, Lane};
use crate::strokes;
use serde_json::{json, Map, Value};
use std::collections::{BTreeMap, HashMap, HashSet};

// the order of the items, one scale for all (lower first)
pub const CONNECTOR: i64 = -1;
pub const LANE: i64 = 0;
pub const LINE: i64 = 1;
pub const ZEBRA: i64 = 2;
pub const ARROW: i64 = 3;

/// A GeoJSON FeatureCollection, or None without features (Python's None).
pub fn fc(fs: Vec<Value>) -> Option<Value> {
    (!fs.is_empty()).then(|| json!({"type": "FeatureCollection", "features": fs}))
}

fn line_geom(l: &[P]) -> Value {
    json!({"type": "LineString", "coordinates": round_line(l)})
}

fn pdist(a: P, b: P) -> f64 {
    ((a[0] - b[0]).powi(2) + (a[1] - b[1]).powi(2)).powf(0.5)
}

/// The roads of the carriageways (Python's `link_roads`): a road's id, its width and its line (lon/lat); every link's road, and the
/// (road, node) ends where only two roads meet (the lines run on there).
pub struct Roads {
    pub roads: Vec<(i64, f64, Line)>,
    pub road_of: BTreeMap<i64, i64>,
    pub ext: HashSet<(i64, i64)>,
}

/// The lanes of each link in lane order (the links in their order).
fn by_link<'a>(g: &[&'a Lane]) -> BTreeMap<i64, Vec<&'a Lane>> {
    let mut m: BTreeMap<i64, Vec<&Lane>> = BTreeMap::new();
    for l in g {
        if let Some(k) = l.link_id {
            m.entry(k).or_default().push(l);
        }
    }
    for v in m.values_mut() {
        v.sort_by_key(|l| l.lane_num.unwrap_or(i64::MAX));
    }
    m
}

/// One road per carriageway (`edge_id` = the smaller link of a link and its `reverse_link_id`): its line the middle of the carriageway
/// (between the kerb lanes of the two directions, or the first and last lane of a one-way link), at every vertex of the lanes' lines,
/// simplified by 2 cm, its ends where roads meet made one point; its width the lanes' widths, plus `centre_m` for two directions, plus the
/// casing on each side. `g`: the lanes without the connectors.
pub fn link_roads(g: &[&Lane], casing_m: f64, centre_m: f64) -> Roads {
    let utm = Utm::of(g.iter().map(|l| &l.geometry));
    let lanes_of = by_link(g);
    let mut rev: HashMap<i64, i64> = HashMap::new();
    for l in g {
        if let (Some(lk), Some(rv)) = (l.link_id, l.reverse_link_id) {
            if lanes_of.contains_key(&rv) && rv != lk {
                rev.insert(lk, rv);
            }
        }
    }
    let road_of: BTreeMap<i64, i64> = lanes_of.keys().map(|&lk| (lk, lk.min(*rev.get(&lk).unwrap_or(&lk)))).collect();
    let metres: HashMap<i64, Vec<(Line, f64)>> = lanes_of.iter().map(|(k, ls)| {
        (*k, ls.iter().map(|l| (utm.fwd_line(&l.geometry), l.width_m.unwrap_or(f64::NAN))).filter(|(m, _)| m.len() >= 2 && geo::length(m) > 0.0).collect())
    }).collect();
    let mut roads_set: Vec<i64> = road_of.values().copied().collect();
    roads_set.sort();
    roads_set.dedup();
    let (mut rows, mut geoms, mut nodes) = (Vec::new(), Vec::new(), Vec::new());
    for road in roads_set {
        let links: Vec<i64> = std::iter::once(road).chain(rev.get(&road).copied()).collect();
        let ls = &metres[&road];
        if ls.is_empty() {
            continue;
        }
        let other = links.get(1).map(|k| &metres[k]).filter(|o| !o.is_empty());
        let line = if let (2, Some(o)) = (links.len(), other) {
            let (b, wb) = &o[o.len() - 1];
            let back: Line = b.iter().rev().copied().collect();
            middle(&ls[ls.len() - 1].0, &back, ls[ls.len() - 1].1, *wb)
        } else if ls.len() > 1 {
            middle(&ls[0].0, &ls[ls.len() - 1].0, ls[0].1, ls[ls.len() - 1].1)
        } else {
            ls[0].0.clone()
        };
        let line = geo::simplify(&line, 0.02);
        let first = lanes_of[&road][0];
        let sum: f64 = links.iter().map(|k| lanes_of[k].iter().map(|l| l.width_m.unwrap_or(f64::NAN)).fold(0.0, |a, b| a + b)).fold(0.0, |a, b| a + b);
        let width = sum + 2.0 * casing_m + if links.len() == 2 { centre_m } else { 0.0 };
        rows.push((road, width));
        geoms.push(line);
        nodes.push((first.from_node_id.unwrap_or_default(), first.to_node_id.unwrap_or_default()));
    }
    let widths: Vec<f64> = rows.iter().map(|r| r.1).collect();
    let geoms = snap_ends(&geoms, &nodes, &widths);
    let ids: Vec<i64> = rows.iter().map(|r| r.0).collect();
    let ext = ends(&geoms, &nodes, &ids);
    let roads = rows.into_iter().zip(geoms).map(|((id, w), l)| (id, w, utm.inv_line(&l))).collect();
    Roads { roads, road_of, ext }
}

/// The line halfway between the outer edges of lane `a` (`wa` wide) and lane `b` (`wb`; the same direction), at every vertex of both:
/// their centres' middle moved `(wb - wa) / 4` toward `b`.
pub fn middle(a: &[P], b: &[P], wa: f64, wb: f64) -> Line {
    let mut fr: Vec<f64> = vec![0.0, 1.0];
    fr.extend(a.iter().map(|c| geo::project_n(a, *c)));
    fr.extend(b.iter().map(|c| geo::project_n(b, *c)));
    fr.sort_by(|x, y| x.total_cmp(y));
    fr.dedup();
    let k = (wb - wa) / 4.0;
    let pts: Vec<P> = fr.iter().map(|&x| {
        let (p, q) = (geo::interpolate_n(a, x), geo::interpolate_n(b, x));
        let d = (q[0] - p[0]).hypot(q[1] - p[1]);
        let (ux, uy) = if d > 1e-9 { ((q[0] - p[0]) / d, (q[1] - p[1]) / d) } else { (0.0, 0.0) };
        [(p[0] + q[0]) / 2.0 + ux * k, (p[1] + q[1]) / 2.0 + uy * k]
    }).collect();
    pts.iter().enumerate().filter(|(i, c)| *i == 0 || **c != pts[i - 1]).map(|(_, c)| *c).collect()
}

/// The lines with the ends at one node made the same point; the widest roads decide (within half a metre of the widest): the mean of
/// their ends, which replaces them; a narrower road keeps its end and gets the point as one more vertex (a hook inside the wider road).
/// A node where a narrower end is farther than half the widest road from the point: the mean of all the ends.
pub fn snap_ends(lines: &[Line], nodes: &[(i64, i64)], widths: &[f64]) -> Vec<Line> {
    // node -> [(line, end 0/1, point, width)], in the order the ends are met
    let mut order: Vec<i64> = Vec::new();
    let mut at: HashMap<i64, Vec<(usize, usize, P, f64)>> = HashMap::new();
    for (k, (ln, (a, b))) in lines.iter().zip(nodes).enumerate() {
        for (node, end, p) in [(*a, 0, ln[0]), (*b, 1, ln[ln.len() - 1])] {
            at.entry(node).or_insert_with(|| { order.push(node); Vec::new() }).push((k, end, p, widths[k]));
        }
    }
    let mean = |es: &[&(usize, usize, P, f64)]| -> P {
        let n = es.len() as f64;
        [es.iter().fold(0.0, |s, e| s + e.2[0]) / n, es.iter().fold(0.0, |s, e| s + e.2[1]) / n]
    };
    let (mut point, mut hook): (HashMap<i64, P>, HashSet<(usize, usize)>) = (HashMap::new(), HashSet::new());
    for node in order {
        let ends = &at[&node];
        let wmax = ends.iter().map(|e| e.3).fold(f64::MIN, f64::max);
        let mut main: Vec<&(usize, usize, P, f64)> = ends.iter().filter(|e| e.3 >= wmax - 0.5).collect();
        let mut pt = mean(&main);
        let far = ends.iter().any(|e| e.3 < wmax - 0.5 && pdist(e.2, pt) > wmax / 2.0);
        if far {
            main = ends.iter().collect();
            pt = mean(&main);
        }
        point.insert(node, pt);
        for e in ends {
            if !main.iter().any(|m| std::ptr::eq(*m, e)) && pdist(e.2, pt) > 1e-6 {
                hook.insert((e.0, e.1));
            }
        }
    }
    lines.iter().zip(nodes).enumerate().map(|(k, (ln, (a, b)))| {
        let mut out = vec![point[a]];
        if hook.contains(&(k, 0)) {
            out.push(ln[0]);
        }
        out.extend_from_slice(&ln[1..ln.len() - 1]);
        if hook.contains(&(k, 1)) {
            out.push(ln[ln.len() - 1]);
        }
        out.push(point[b]);
        out
    }).collect()
}

/// The (road, node) ends where only two roads meet (a road that goes on: the lane lines run on through the node).
pub fn ends(lines: &[Line], nodes: &[(i64, i64)], ids: &[i64]) -> HashSet<(i64, i64)> {
    let mut count: HashMap<i64, Vec<usize>> = HashMap::new();
    for (k, (a, b)) in nodes.iter().enumerate() {
        let _ = &lines[k];
        count.entry(*a).or_default().push(k);
        count.entry(*b).or_default().push(k);
    }
    count.into_iter().filter(|(_, ks)| ks.len() == 2).flat_map(|(n, ks)| ks.into_iter().map(move |k| (ids[k], n))).collect()
}

/// The links that are one direction of a road of two.
pub fn two_way_links(road_of: &BTreeMap<i64, i64>) -> HashSet<i64> {
    let mut n: HashMap<i64, usize> = HashMap::new();
    for rd in road_of.values() {
        *n.entry(*rd).or_default() += 1;
    }
    road_of.iter().filter(|(_, rd)| n[rd] == 2).map(|(lk, _)| *lk).collect()
}

/// Each lane's sideways shift (metres, + = right of its travel): `centre_m / 2` on a road of two directions, else 0.
// ponytail: right-hand traffic only (the centre is on the left of travel)
pub fn lane_shifts(g: &[&Lane], road_of: &BTreeMap<i64, i64>, centre_m: f64) -> Vec<f64> {
    let two = two_way_links(road_of);
    g.iter().map(|l| if l.link_id.is_some_and(|k| two.contains(&k)) { centre_m / 2.0 } else { 0.0 }).collect()
}

/// A lane's number as Python's table has it: a float when the table has connectors (pandas' concat with their empty numbers).
fn num_json(v: Option<i64>, float: bool) -> Value {
    match v {
        None => Value::Null,
        Some(n) if float => json!(n as f64),
        Some(n) => json!(n),
    }
}

/// The lanes (no connectors) and the lines between them as LINE items: `(lanes, lines)`. A lane is its own line, `width_m` wide, in its
/// colour, shifted as `lane_shifts`; the lines lie on the borders of neighbouring lanes of a link (dashed in metres between two car
/// lanes, solid next to any other lane), and a road of two directions gets one solid centre line, `centre_m` wide, on lane 1's left edge
/// of its first link. A line stops `trim_m` short of a junction end of its lane and runs on where its road goes on (`ext`).
#[allow(clippy::too_many_arguments)]
pub fn lane_strokes(g: &[&Lane], colours: &[String], road_of: &BTreeMap<i64, i64>, centre_m: f64, lines: &Value, trim_m: f64,
                    ext: &HashSet<(i64, i64)>, num_float: bool, has: &dyn Fn(&str) -> bool) -> Result<(Option<Value>, Option<Value>), String> {
    if g.is_empty() {
        return Ok((None, None));
    }
    let bad: Vec<&str> = g.iter().filter(|l| l.geometry.len() < 2).map(|l| l.lane_id.as_str()).collect();
    if !bad.is_empty() {
        return Err(format!("{} lane(s) have no line (first: {:?})", bad.len(), &bad[..bad.len().min(5)]));
    }
    let two = two_way_links(road_of);
    let shift = lane_shifts(g, road_of, centre_m);
    let mut lane_fs = Vec::new();
    for (i, l) in g.iter().enumerate() {
        let mut p = Map::new();
        for c in ["name", "lane_id", "lane_num", "use", "width_m", "link_id"] {
            if has(c) {
                p.insert(c.into(), match c {
                    "lane_num" => num_json(l.lane_num, num_float),
                    _ => l.get(c),
                });
            }
        }
        p.insert("edge_id".into(), json!(l.link_id));
        p.insert("order".into(), json!(LANE));
        p.insert("color".into(), json!(colours[i]));
        p.insert("width_m".into(), json!(l.width_m));
        p.insert("offset_m".into(), json!(shift[i]));
        lane_fs.push(json!({"type": "Feature", "properties": p, "geometry": line_geom(&l.geometry)}));
    }
    let mut line_fs = Vec::new();
    let f = |k: &str| lines[k].as_f64().unwrap_or_default();
    let minzoom = lines.get("minzoom").filter(|v| !v.is_null()).map(|v| json!(v.as_f64()));
    let mut add = |i: usize, x: f64, dashed: bool, width: f64, kind: &str| {
        let l = g[i];
        let link = l.link_id.unwrap_or_default();
        let rd = road_of.get(&link).copied().unwrap_or(i64::MIN);
        let t0 = if ext.contains(&(rd, l.from_node_id.unwrap_or_default())) { 0.0 } else { trim_m };
        let t1 = if ext.contains(&(rd, l.to_node_id.unwrap_or_default())) { 0.0 } else { trim_m };
        let n = strokes::length_m(&l.geometry);
        if n <= t0 + t1 + 0.2 {
            return;
        }
        let ln = if t0 != 0.0 || t1 != 0.0 { geo::substring(&l.geometry, t0 / n, 1.0 - t1 / n, true).unwrap_or_else(|| l.geometry.clone()) } else { l.geometry.clone() };
        let (geom, x) = if dashed {
            let parts = strokes::dashes(&ln, f("dash_m"), f("gap_m"), width, x);
            if parts.is_empty() {
                return;
            }
            (json!({"type": "MultiLineString", "coordinates": parts.iter().map(|p| round_line(p)).collect::<Vec<_>>()}), 0.0)
        } else {
            (line_geom(&ln), x)
        };
        let mut p = json!({"edge_id": link, "order": LINE, "color": lines["color"], "width_m": width, "offset_m": x, "t": kind});
        if let Some(m) = &minzoom {
            p["minzoom"] = m.clone();
        }
        line_fs.push(json!({"type": "Feature", "geometry": geom, "properties": p}));
    };
    let mut rows_of: BTreeMap<i64, Vec<usize>> = BTreeMap::new();
    for (i, l) in g.iter().enumerate() {
        if let Some(k) = l.link_id {
            rows_of.entry(k).or_default().push(i);
        }
    }
    for (lk, rows) in &mut rows_of {
        rows.sort_by_key(|&i| g[i].lane_num.unwrap_or(i64::MAX));
        if lines.get("divider").and_then(Value::as_bool).unwrap_or(true) {
            for w in rows.windows(2) {
                let (a, b) = (w[0], w[1]);
                let dashed = has("use") && g[a].use_.as_deref() == Some("auto") && g[b].use_.as_deref() == Some("auto");
                add(a, shift[a] + g[a].width_m.unwrap_or_default() / 2.0, dashed, f("width_m"), "divider");
            }
        }
        if lines.get("centre").and_then(Value::as_bool).unwrap_or(true) && two.contains(lk) && road_of.get(lk) == Some(lk) {
            add(rows[0], -g[rows[0]].width_m.unwrap_or_default() / 2.0, false, centre_m, "centre");
        }
    }
    Ok((fc(lane_fs), fc(line_fs)))
}

/// The lane connectors as LINE items: each its own line through the junction, as wide as the lane it leaves (`lane_width`), in its
/// colour, on the link it leaves, with the order CONNECTOR. None without any.
pub fn connector_strokes(c: &[&Lane], colours: &[String], lane_width: &HashMap<String, f64>) -> Result<Option<Value>, String> {
    let mut fs = Vec::new();
    for (i, l) in c.iter().enumerate() {
        let from = l.from_lane.clone().unwrap_or_default();
        let w = lane_width.get(&from).ok_or_else(|| format!("connector {}: its lane {from:?} is not in the table", l.lane_id))?;
        fs.push(json!({"type": "Feature", "properties": {"lane_id": l.lane_id, "from_lane": l.from_lane, "to_lane": l.to_lane,
                       "edge_id": l.link_id, "order": CONNECTOR, "color": colours[i], "width_m": w, "offset_m": 0.0},
                       "geometry": line_geom(&l.geometry)}));
    }
    Ok(fc(fs))
}

/// Python's float `//`.
fn floordiv(a: f64, b: f64) -> f64 {
    let mut m = a % b;
    let mut div = (a - m) / b;
    if m != 0.0 && ((b < 0.0) != (m < 0.0)) {
        m += b;
        div -= 1.0;
    }
    let _ = m;
    if div != 0.0 {
        let f = div.floor();
        if div - f > 0.5 { f + 1.0 } else { f }
    } else {
        0.0f64.copysign(a / b)
    }
}

/// The painted zebra crossings as LINE items: each stripe a stroke along the road, `stripe_m` wide, as long as the crossing is wide, an
/// item (ZEBRA) of the link of the lane under it, from `st["minzoom"]`. The stripes lie across duckOSM's crossing rectangle, `stripe_m +
/// gap_m` apart, the row centred; only crossings duckOSM calls painted. `g`: the lanes. None without any.
pub fn zebra_strokes(g: &[&Lane], cr: Option<&[Crossing]>, st: &Value, colour: &Value) -> Option<Value> {
    let cr: Vec<&Crossing> = cr?.iter().filter(|c| c.painted == Some(true)).collect();
    if cr.is_empty() {
        return None;
    }
    let u = Utm::of(g.iter().map(|l| &l.geometry));
    let (stripe, gap) = (st["stripe_m"].as_f64().unwrap_or_default(), st["gap_m"].as_f64().unwrap_or_default());
    let (pitch, thick) = (stripe + gap, stripe);
    let link_of: HashMap<&str, i64> = g.iter().filter_map(|l| Some((l.lane_id.as_str(), l.link_id?))).collect();
    let mut groups: BTreeMap<&str, Vec<&Crossing>> = BTreeMap::new();
    for c in cr {
        groups.entry(c.crossing_id.as_str()).or_default().push(c);
    }
    let (mut lines, mut links): (Vec<Line>, Vec<i64>) = (Vec::new(), Vec::new());
    for grp in groups.values() {
        let Some(ring) = grp[0].cgeom.as_deref().and_then(geo::wkt_ring) else { continue };
        if ring.len() < 4 {
            continue;
        }
        let r: Vec<P> = ring.iter().take(4).map(|p| u.fwd(*p)).collect();
        let ([x0, y0], [x1, y1], [x3, y3]) = (r[0], r[1], r[3]);
        let length = (x1 - x0).hypot(y1 - y0);
        let (wx, wy) = (x3 - x0, y3 - y0);
        if length < thick || wx.hypot(wy) < 0.5 {
            continue;
        }
        let under: Vec<(f64, f64, i64)> = grp.iter().filter_map(|c| Some((c.across_from.unwrap_or(f64::NAN), c.across_to.unwrap_or(f64::NAN),
                                                                           *link_of.get(c.lane_id.as_str())?))).collect();
        if under.is_empty() {
            continue;
        }
        let (dx, dy) = ((x1 - x0) / length, (y1 - y0) / length);
        let n = floordiv(length - thick, pitch) as i64 + 1;
        let first = (length - ((n - 1) as f64 * pitch + thick)) / 2.0;
        for i in 0..n {
            let mid = first + i as f64 * pitch + thick / 2.0;
            let a = [x0 + dx * mid, y0 + dy * mid];
            lines.push(vec![a, [a[0] + wx, a[1] + wy]]);
            let key = |x: &(f64, f64, i64)| if x.0 <= mid && mid <= x.1 { 0.0 } else { (mid - x.0).abs().min((mid - x.1).abs()) };
            let best = under.iter().fold(None::<&(f64, f64, i64)>, |b, x| match b { Some(b) if !(key(x) < key(b)) => Some(b), _ => Some(x) });
            links.push(best.map_or(0, |b| b.2));
        }
    }
    let mz = st.get("minzoom").and_then(Value::as_f64).unwrap_or(17.0);
    fc(lines.iter().zip(links).map(|(l, link)| json!({"type": "Feature", "geometry": line_geom(&u.inv_line(l)),
        "properties": {"edge_id": link, "order": ZEBRA, "color": colour, "width_m": thick, "offset_m": 0.0, "minzoom": mz}})).collect())
}

/// Python's `float(str(v).split()[0].replace(",", "."))`, None where it fails.
fn num(v: Option<&Value>) -> Option<f64> {
    let t = match v? { Value::String(s) => s.clone(), x => x.to_string() };
    t.split_whitespace().next()?.replace(',', ".").parse().ok()
}

/// The sides of an OSM way with a sidewalk in its tags (`sidewalk` / `sidewalk:both|left|right`), each with its width in metres (the
/// width tags, else `default_m`), sides of the way's own direction; `separate`, `no` and a bare `yes` give none.
pub fn sidewalk_sides(tags: Option<&Map<String, Value>>, default_m: f64) -> Vec<(&'static str, f64)> {
    let empty = Map::new();
    let tags = tags.unwrap_or(&empty);
    let t = |k: &str| tags.get(k).and_then(Value::as_str);
    let mut have = [("left", false), ("right", false)];
    if let Some(m @ ("both" | "left" | "right")) = t("sidewalk") {
        for h in &mut have {
            h.1 = m == "both" || m == h.0;
        }
    }
    if t("sidewalk:both") == Some("yes") {
        have = [("left", true), ("right", true)];
    }
    for h in &mut have {
        match t(&format!("sidewalk:{}", h.0)) {
            Some("yes") => h.1 = true,
            Some("no" | "separate") => h.1 = false,
            _ => {}
        }
    }
    // Python's `a or b or c`: a width of 0 is no width
    let pick = |side: &str| [format!("sidewalk:{side}:width"), "sidewalk:both:width".into(), "sidewalk:width".into()].iter()
        .filter_map(|k| num(tags.get(k))).find(|w| *w != 0.0).unwrap_or(default_m);
    have.iter().filter(|h| h.1).map(|h| (h.0, pick(h.0))).collect()
}

/// The sidewalks OSM tags on a street as LINE items: a strip in `colour` along the street's drawn line (`lines`: link -> the road's line
/// in that link's direction), just outside its full width (`width`), `st["width_m"]` wide unless tagged, from `st["minzoom"]`; it stops
/// where the street's lanes stop at a junction (their `cut_geometry`). One strip per side per road, on the road's own link. `g`: the
/// lanes; `tags`: OSM way id -> its tags. None without any.
pub fn sidewalk_strokes(g: &[&Lane], road_of: &BTreeMap<i64, i64>, lines: &HashMap<String, Line>, width: &HashMap<String, f64>,
                        tags: &HashMap<i64, Map<String, Value>>, st: &Value, colour: &Value) -> Option<Value> {
    let mut info: HashMap<i64, &Lane> = HashMap::new();
    for l in g {
        if let Some(k) = l.link_id {
            info.entry(k).or_insert(l);
        }
    }
    let mut cut: HashMap<i64, (f64, f64)> = HashMap::new();
    for l in g {
        let (Some(lk), Some(c)) = (l.link_id, &l.cut_geometry) else { continue };
        if c.is_empty() || geo::length(&l.geometry) == 0.0 {
            continue;
        }
        let (a, b) = (geo::project_n(&l.geometry, c[0]), 1.0 - geo::project_n(&l.geometry, c[c.len() - 1]));
        let (s0, s1) = cut.get(&lk).copied().unwrap_or((0.0, 0.0));
        cut.insert(lk, (s0.max(a), s1.max(b)));
    }
    let (wm, mz) = (st["width_m"].as_f64().unwrap_or(2.0), st.get("minzoom").and_then(Value::as_f64).unwrap_or(17.0));
    let mut fs = Vec::new();
    for (&lk, &rd) in road_of {
        let key = lk.to_string();
        let (Some(row), Some(line), Some(w)) = (info.get(&lk), lines.get(&key), width.get(&key)) else { continue };
        if lk != rd {
            continue;
        }
        let back = row.edge_ref.as_deref().unwrap_or_default().ends_with('r');
        let (mut a, mut b) = cut.get(&lk).copied().unwrap_or((0.0, 0.0));
        if let Some((ra, rb)) = row.reverse_link_id.and_then(|r| cut.get(&r)) {
            (a, b) = (a.max(*rb), b.max(*ra));
        }
        if a + b >= 0.95 {
            continue;
        }
        let Some(part) = geo::substring(line, a, 1.0 - b, true) else { continue };
        if part.len() < 2 || geo::length(&part) == 0.0 {
            continue;
        }
        for (side, m) in sidewalk_sides(row.osm_id.and_then(|o| tags.get(&o)), wm) {
            let sign = (if side == "right" { 1.0 } else { -1.0 }) * if back { -1.0 } else { 1.0 };
            fs.push(json!({"type": "Feature", "geometry": line_geom(&part),
                           "properties": {"edge_id": lk, "order": LANE, "color": colour, "width_m": m, "minzoom": mz,
                                          "offset_m": sign * (w / 2.0 + m / 2.0), "kind": "sidewalk"}}));
        }
    }
    fc(fs)
}

#[cfg(test)]
mod tests {
    use super::floordiv;

    #[test]
    fn floordiv_as_python() {
        assert_eq!(floordiv(7.0, 1.0), 7.0);
        assert_eq!(floordiv(6.5, 1.0), 6.0);
        assert_eq!(floordiv(-0.5, 1.0), -1.0);
        assert_eq!(floordiv(0.3, 0.1), 2.0);    // Python: 0.3 // 0.1 == 2.0
    }
}
