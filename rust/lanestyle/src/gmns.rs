//! The GMNS reader: a duckOSM GMNS database to the lane table and the turns (Python's `from_gmns`), the crossings and the boundary.
//! The files are attached to a DuckDB connection with the spatial extension (`connect`).

use crate::geo::{wkb_line, Line};
use crate::lanes::{Crossing, Lane, Lanes, Turn};
pub use duckdb::Connection;
use serde_json::{Map, Value};
use std::collections::{BTreeMap, HashMap, HashSet};

pub type Result<T> = std::result::Result<T, String>;

const G: &str = "lanestyle_gmns";
const S: &str = "lanestyle_src";

/// A DuckDB connection in memory with the spatial extension.
pub fn connect() -> Result<Connection> {
    let c = Connection::open_in_memory().map_err(|e| e.to_string())?;
    c.execute_batch("INSTALL spatial; LOAD spatial;").map_err(|e| format!("DuckDB's spatial extension: {e}"))?;
    Ok(c)
}

fn quote(path: &str) -> String {
    format!("'{}'", path.replace('\'', "''"))
}

/// The rows of a query as JSON objects (DuckDB's to_json).
fn rows(c: &Connection, sql: &str) -> Result<Vec<Map<String, Value>>> {
    let mut st = c.prepare(&format!("SELECT to_json(lanestyle_row)::VARCHAR FROM ({sql}) lanestyle_row")).map_err(|e| format!("{e}\n{sql}"))?;
    let texts = st.query_map([], |r| r.get::<_, String>(0)).map_err(|e| e.to_string())?;
    texts.map(|t| {
        let t = t.map_err(|e| e.to_string())?;
        match serde_json::from_str(&t).map_err(|e| e.to_string())? {
            Value::Object(m) => Ok(m),
            _ => Err("a row that is no object".into()),
        }
    }).collect()
}

/// The columns of a table of the attached database `db`.
fn cols(c: &Connection, db: &str, schema: &str, table: &str) -> Result<HashSet<String>> {
    Ok(rows(c, &format!("SELECT column_name FROM duckdb_columns() WHERE database_name = '{db}' AND schema_name = '{schema}' AND table_name = '{table}'"))?
        .into_iter().filter_map(|r| r["column_name"].as_str().map(String::from)).collect())
}

/// The files attached for one read, detached at the end.
struct Attached<'a> {
    c: &'a Connection,
    names: Vec<&'static str>,
}

impl<'a> Attached<'a> {
    fn new(c: &'a Connection, gmns: &str, source: Option<&str>) -> Result<Attached<'a>> {
        let mut a = Attached { c, names: Vec::new() };
        a.attach(G, gmns)?;
        if let Some(s) = source {
            a.attach(S, s)?;
        }
        Ok(a)
    }

    fn attach(&mut self, name: &'static str, path: &str) -> Result<()> {
        self.c.execute_batch(&format!("ATTACH {} AS {name} (READ_ONLY)", quote(path))).map_err(|e| format!("{path}: {e}"))?;
        self.names.push(name);
        Ok(())
    }
}

impl Drop for Attached<'_> {
    fn drop(&mut self) {
        for n in &self.names {
            let _ = self.c.execute_batch(&format!("DETACH {n}"));
        }
    }
}

fn hex(s: &str) -> Vec<u8> {
    (0..s.len() / 2).map(|i| u8::from_str_radix(&s[2 * i..2 * i + 2], 16).unwrap_or(0)).collect()
}

fn line_of(v: &Value) -> Option<Line> {
    v.as_str().and_then(|h| wkb_line(&hex(h)))
}

fn s(v: &Value) -> Option<String> {
    match v {
        Value::Null => None,
        Value::String(t) => Some(t.clone()),
        x => Some(x.to_string()),
    }
}

fn i(v: &Value) -> Option<i64> {
    v.as_i64().or_else(|| v.as_str().and_then(|t| t.parse().ok()))
}

/// `from_gmns(gmns_db, mode, source_db, modes)`: the lanes of `gmns_<mode>` (or of several `modes`, each later one adding only what the
/// earlier ones do not have), and the crossings when driving is read.
pub fn from_gmns(c: &Connection, gmns: &str, mode: &str, source: Option<&str>, modes: Option<&[String]>) -> Result<(Lanes, Vec<Turn>)> {
    let (mut lanes, turns) = match modes {
        Some(m) if !m.is_empty() => from_modes(c, gmns, source, m)?,
        _ => from_mode(c, gmns, mode, source)?,
    };
    let driving = modes.filter(|m| !m.is_empty()).map_or(mode == "driving", |m| m.iter().any(|x| x == "driving"));
    lanes.crossings = if driving { read_crossings(c, gmns)? } else { None };
    Ok((lanes, turns))
}

/// The link ids of a roundabout's ring (the OSM junction tag of the source's edges).
fn ring_links(c: &Connection, mode: &str) -> Result<HashSet<i64>> {
    let have = cols(c, S, mode, "edges")?;
    if !have.contains("junction") || !have.contains("edge_id") {
        return Ok(HashSet::new());
    }
    Ok(rows(c, &format!("SELECT edge_id FROM {S}.{mode}.edges WHERE junction IN ('roundabout', 'circular')"))?.iter().filter_map(|r| i(&r["edge_id"])).collect())
}

/// One mode's lanes and turns (Python's `_from_gmns_mode`).
fn from_mode(c: &Connection, gmns: &str, mode: &str, source: Option<&str>) -> Result<(Lanes, Vec<Turn>)> {
    let _a = Attached::new(c, gmns, source)?;
    let g = format!("gmns_{mode}");
    let gq = format!("{G}.{g}");
    if cols(c, G, &g, "lane")?.is_empty() {
        return Err(format!("no '{g}.lane' in {gmns}: build a GMNS db first (duckOSM `duckosm gmns`)"));
    }
    let link_cols = cols(c, G, &g, "link")?;
    let same = if link_cols.contains("geom") { " AND ST_Equals(r.geom, k.geom)" } else { "" };
    let nlanes = if link_cols.contains("lanes") { "k.lanes, " } else { "" };
    let mut lvl = String::new();
    let mut lvl_cols: Vec<&str> = Vec::new();
    if ["bridge", "tunnel", "layer"].iter().all(|x| link_cols.contains(*x)) {
        lvl = ", k.bridge, k.tunnel, k.layer".into();
        lvl_cols.extend(["bridge", "tunnel", "layer"]);
    } else if source.is_some() {
        let src_cols = cols(c, S, mode, "edges")?;
        if !["edge_id", "bridge", "tunnel", "layer"].iter().all(|x| src_cols.contains(*x)) {
            return Err(format!("no {mode}.edges with bridge / tunnel / layer in {}", source.unwrap_or_default()));
        }
        lvl = ", e.bridge, e.tunnel, e.layer".into();
        lvl_cols.extend(["bridge", "tunnel", "layer"]);
        if src_cols.contains("osm_id") {
            lvl += ", e.osm_id";
            lvl_cols.push("osm_id");
        }
    }
    if link_cols.contains("osm_id") && !lvl.contains("osm_id") {
        lvl += ", k.osm_id";
        lvl_cols.push("osm_id");
    }
    for x in ["footway", "crossing", "crossing_markings"] {
        if link_cols.contains(x) {
            lvl += &format!(", k.{x}");
            lvl_cols.push(x);
        }
    }
    if link_cols.contains("along_link_id") {
        lvl += ", k.along_link_id";
        lvl_cols.push("along_link_id");
        if link_cols.contains("along_kind") {
            lvl += ", k.along_kind";
            lvl_cols.push("along_kind");
        }
    }
    if link_cols.contains("edge_ref") {
        lvl += ", k.edge_ref";
        lvl_cols.push("edge_ref");
    }
    let join = if lvl.starts_with(", e.") { format!("LEFT JOIN {S}.{mode}.edges e ON e.edge_id = l.link_id") } else { String::new() };
    let lane_cols = cols(c, G, &g, "lane")?;
    let full = format!("{}{}", if lane_cols.contains("geom_cut") { ", ST_AsHEXWKB(l.geom_cut) AS geom_cut" } else { "" },
                       if lane_cols.contains("geom_full") { ", ST_AsHEXWKB(l.geom_full) AS geom_full" } else { "" });
    let df = rows(c, &format!(
        "SELECT l.lane_id::VARCHAR AS lane_id, k.facility_type AS highway, l.width AS width_m, \
           COALESCE(l.allowed_uses, 'auto') AS use, \
           CASE WHEN l.lane_num = 1 THEN k.name END AS name, \
           l.link_id, l.lane_num, {nlanes}l.turn, k.from_node_id, k.to_node_id, \
           (SELECT min(r.link_id) FROM {gq}.link r WHERE r.from_node_id = k.to_node_id \
              AND r.to_node_id = k.from_node_id AND r.link_id <> k.link_id{same}) AS reverse_link_id\
           {lvl}, ST_AsHEXWKB(l.geom) AS geom{full} \
         FROM {gq}.lane l JOIN {gq}.link k ON k.link_id = l.link_id {join} \
         WHERE l.geom IS NOT NULL ORDER BY l.link_id, l.lane_num"))?;
    let conn = if cols(c, G, &g, "lane_connector")?.is_empty() { None } else {
        Some(rows(c, &format!("SELECT connector_id::VARCHAR AS lane_id, from_lane_id::VARCHAR AS from_lane, to_lane_id::VARCHAR AS to_lane, \
                               width AS width_m, ST_AsHEXWKB(geom) AS geom FROM {gq}.lane_connector WHERE geom IS NOT NULL"))?)
    };
    // Python's `if route:`: an empty table adds no column
    let route: Option<HashMap<i64, Vec<i64>>> = if cols(c, G, &g, "link_along")?.is_empty() { None } else {
        Some(rows(c, &format!("SELECT link_id, list(along_link_id) AS a FROM {gq}.link_along GROUP BY 1"))?.iter()
            .filter_map(|r| Some((i(&r["link_id"])?, r["a"].as_array()?.iter().filter_map(i).collect()))).collect::<HashMap<_, _>>())
            .filter(|m| !m.is_empty())
    };
    let mut turns = Vec::new();
    let mv = cols(c, G, &g, "movement")?;
    if !mv.is_empty() {
        let letter = if mv.contains("mvmt_code") { "substr(m.mvmt_code, 3, 1)" } else { "NULL" };
        for r in rows(c, &format!(
            "SELECT DISTINCT il.lane_id::VARCHAR AS from_lane, ol.lane_id::VARCHAR AS to_lane, m.type, {letter} AS code \
             FROM {gq}.movement m \
             JOIN {gq}.lane il ON il.link_id = m.ib_link_id AND (m.start_ib_lane IS NULL OR \
               il.lane_num BETWEEN m.start_ib_lane AND COALESCE(m.end_ib_lane, m.start_ib_lane)) \
             JOIN {gq}.lane ol ON ol.link_id = m.ob_link_id AND (m.start_ob_lane IS NULL OR \
               m.start_ib_lane IS NULL OR ol.lane_num = m.start_ob_lane + il.lane_num - m.start_ib_lane) \
             ORDER BY 1, 2"))? {
            let t = s(&r["type"]);
            let turn = if t.as_deref() == Some("diverge") {
                match r["code"].as_str() { Some("L") => Some("left"), Some("T") => Some("thru"), Some("R") => Some("right"), _ => None }.map(String::from)
            } else { None };
            turns.push(Turn { from_lane: s(&r["from_lane"]).unwrap_or_default(), to_lane: s(&r["to_lane"]).unwrap_or_default(), type_: t, turn, walkers: None });
        }
    }
    let rings = if source.is_some() { ring_links(c, mode)? } else { HashSet::new() };
    let mut out: Vec<Lane> = df.iter().map(|r| Lane {
        lane_id: s(&r["lane_id"]).unwrap_or_default(),
        highway: s(&r["highway"]),
        width_m: r["width_m"].as_f64(),
        use_: s(&r["use"]),
        name: s(&r["name"]),
        link_id: i(&r["link_id"]),
        lane_num: i(&r["lane_num"]),
        lanes: r.get("lanes").and_then(i),
        turn: s(&r["turn"]),
        from_node_id: i(&r["from_node_id"]),
        to_node_id: i(&r["to_node_id"]),
        reverse_link_id: i(&r["reverse_link_id"]),
        bridge: r.get("bridge").and_then(s),
        tunnel: r.get("tunnel").and_then(s),
        layer: r.get("layer").and_then(s),
        osm_id: r.get("osm_id").and_then(i),
        footway: r.get("footway").and_then(s),
        crossing: r.get("crossing").and_then(s),
        crossing_markings: r.get("crossing_markings").and_then(s),
        along_link_id: r.get("along_link_id").and_then(i),
        along_kind: r.get("along_kind").and_then(s),
        edge_ref: r.get("edge_ref").and_then(s),
        roundabout: i(&r["link_id"]).is_some_and(|l| rings.contains(&l)),
        along_links: route.as_ref().and_then(|m| i(&r["link_id"]).and_then(|l| m.get(&l).cloned())),
        connector: false,
        geometry: line_of(&r["geom"]).unwrap_or_default(),
        cut_geometry: r.get("geom_cut").and_then(line_of),
        full_geometry: r.get("geom_full").and_then(line_of),
        ..Lane::default()
    }).collect();
    // the columns of Python's table, in its order
    let mut columns: Vec<String> = ["lane_id", "highway", "width_m", "use", "name", "link_id", "lane_num"].map(String::from).to_vec();
    if !nlanes.is_empty() {
        columns.push("lanes".into());
    }
    columns.extend(["turn", "from_node_id", "to_node_id", "reverse_link_id"].map(String::from));
    columns.extend(lvl_cols.iter().map(|x| x.to_string()));
    columns.push("roundabout".into());
    if route.is_some() {
        columns.push("along_links".into());
    }
    columns.push("connector".into());
    if let Some(conn) = conn.filter(|v| !v.is_empty()) {
        // a connector looks like the lane it leaves (not its name, number, turn and lines)
        let of: HashMap<&str, &Lane> = out.iter().map(|l| (l.lane_id.as_str(), l)).collect();
        let made: Vec<Lane> = conn.iter().map(|r| {
            let from = s(&r["from_lane"]);
            let base = from.as_deref().and_then(|f| of.get(f)).map(|l| (*l).clone()).unwrap_or_default();
            Lane {
                lane_id: s(&r["lane_id"]).unwrap_or_default(),
                width_m: r["width_m"].as_f64(),
                name: None, lane_num: None, turn: None, cut_geometry: None, full_geometry: None,
                connector: true,
                to_lane: s(&r["to_lane"]),
                geometry: line_of(&r["geom"]).unwrap_or_default(),
                from_lane: from,
                // a from_lane that is no lane: every other column null, as pandas' left merge
                roundabout: base.roundabout,
                ..if base.lane_id.is_empty() { Lane::default() } else { base }
            }
        }).collect();
        out.extend(made);
        columns.extend(["from_lane", "to_lane"].map(String::from));
    }
    if lane_cols.contains("geom_full") {
        columns.push("full_geometry".into());
    }
    if lane_cols.contains("geom_cut") {
        columns.push("cut_geometry".into());
    }
    columns.push("geometry".into());
    Ok((Lanes { rows: out, columns, crossings: None }, turns))
}

/// Several modes into one table (Python's `_from_gmns` with `modes`): the first as it is, each later one only the lanes of links (and OSM
/// ways) the earlier ones do not have, with its footway joins to an earlier mode's lanes; `modes` says which modes have each link.
fn from_modes(c: &Connection, gmns: &str, source: Option<&str>, modes: &[String]) -> Result<(Lanes, Vec<Turn>)> {
    let mut pushed = HashSet::new();
    if modes.iter().any(|m| m == "cycling") {
        let Some(src) = source else {
            return Err("from_gmns(modes=... 'cycling' ...): pass source_db, the duckOSM file: its cycling.edges.dismount says where bikes are pushed, not ridden".into());
        };
        let _a = Attached::new(c, gmns, Some(src))?;
        pushed = rows(c, &format!("SELECT edge_id FROM {S}.cycling.edges WHERE dismount"))?.iter().filter_map(|r| i(&r["edge_id"])).collect();
    }
    let (mut tables, mut turn_tables): (Vec<Lanes>, Vec<Vec<Turn>>) = (Vec::new(), Vec::new());
    let (mut seen, mut seen_ways, mut earlier): (HashSet<i64>, HashSet<i64>, HashSet<String>) = Default::default();
    let mut modes_of: HashMap<i64, Vec<String>> = HashMap::new();
    let mut way_of: HashMap<i64, Option<i64>> = HashMap::new();
    for (k, m) in modes.iter().enumerate() {
        let (mut lanes, mut turns) = from_mode(c, gmns, m, source)?;
        for t in &mut turns {
            t.walkers = Some(k > 0 && earlier.contains(&t.from_lane));
        }
        let mut links: Vec<i64> = lanes.rows.iter().filter_map(|l| l.link_id).collect();
        links.sort();
        links.dedup();
        for link in links {
            let mm = if m == "cycling" && pushed.contains(&link) { "walking".to_string() } else { m.clone() };
            let e = modes_of.entry(link).or_default();
            if !e.contains(&mm) {
                e.push(mm);
            }
        }
        if lanes.has("osm_id") {
            way_of.extend(lanes.rows.iter().filter_map(|l| l.link_id.map(|k| (k, l.osm_id))));
        }
        if k > 0 {
            let before: HashSet<&str> = tables.iter().flat_map(|t| t.rows.iter().map(|l| l.lane_id.as_str())).collect();
            lanes.rows = keep_joins(&lanes, &before, &seen, &seen_ways);
        }
        seen.extend(lanes.rows.iter().filter_map(|l| l.link_id));
        if lanes.has("osm_id") {
            seen_ways.extend(lanes.rows.iter().filter_map(|l| l.osm_id));
        }
        earlier.extend(lanes.rows.iter().map(|l| l.lane_id.clone()));
        tables.push(lanes);
        turn_tables.push(turns);
    }
    // pd.concat: the columns of the first table, then each new one in its order
    let mut columns: Vec<String> = Vec::new();
    for t in &tables {
        for col in &t.columns {
            if col != "geometry" && !columns.contains(col) {
                columns.push(col.clone());
            }
        }
    }
    let mut rows: Vec<Lane> = tables.into_iter().flat_map(|t| t.rows).collect();
    for l in &mut rows {
        l.modes = Some(l.link_id.and_then(|k| modes_of.get(&k)).map(|v| v.join(",")).unwrap_or_default());
    }
    if columns.iter().any(|x| x == "from_lane") && rows.iter().any(|l| l.connector) {
        // a connector joins two lanes: a street of the modes both have
        let mode_of: HashMap<String, String> = rows.iter().map(|l| (l.lane_id.clone(), l.modes.clone().unwrap_or_default())).collect();
        for l in rows.iter_mut().filter(|l| l.connector) {
            let get = |x: &Option<String>| x.as_ref().and_then(|x| mode_of.get(x)).cloned().unwrap_or_default();
            let (a, b) = (get(&l.from_lane), get(&l.to_lane));
            let both: Vec<&str> = a.split(',').filter(|m| !m.is_empty() && b.split(',').any(|x| x == *m)).collect();
            if !both.is_empty() {
                l.modes = Some(both.join(","));
            }
        }
    }
    if columns.iter().any(|x| x == "along_link_id") && columns.iter().any(|x| x == "osm_id") {
        // a sidewalk's road whose link was dropped (its other direction is kept): the same way
        let kept: HashMap<i64, i64> = rows.iter().filter_map(|l| Some((l.osm_id?, l.link_id?))).collect();
        let links: HashSet<i64> = rows.iter().filter_map(|l| l.link_id).collect();
        let map = |a: i64| if links.contains(&a) { a } else { way_of.get(&a).copied().flatten().and_then(|w| kept.get(&w).copied()).unwrap_or(a) };
        for l in &mut rows {
            l.along_link_id = l.along_link_id.map(map);
            if let Some(v) = &mut l.along_links {
                v.iter_mut().for_each(|a| *a = map(*a));
            }
        }
    }
    columns.push("modes".into());
    columns.push("geometry".into());
    let keep: HashSet<&str> = rows.iter().map(|l| l.lane_id.as_str()).collect();
    let turns = turn_tables.into_iter().flatten().filter(|t| keep.contains(t.from_lane.as_str()) && keep.contains(t.to_lane.as_str())).collect();
    Ok((Lanes { rows, columns, crossings: None }, turns))
}

/// A later mode's lanes without the links (and OSM ways) an earlier mode has; its connectors stay when they join an earlier mode's lane
/// to a kept lane, and take that lane's columns (Python's `_keep_joins`).
fn keep_joins(lanes: &Lanes, earlier: &HashSet<&str>, seen: &HashSet<i64>, seen_ways: &HashSet<i64>) -> Vec<Lane> {
    let rest: Vec<Lane> = lanes.rows.iter().filter(|l| !l.connector)
        .filter(|l| !l.link_id.is_some_and(|k| seen.contains(&k)))
        .filter(|l| !lanes.has("osm_id") || !l.osm_id.is_some_and(|w| seen_ways.contains(&w)))
        .cloned().collect();
    let foot: HashMap<&str, &Lane> = rest.iter().map(|l| (l.lane_id.as_str(), l)).collect();
    let joins: Vec<Lane> = lanes.rows.iter().filter(|l| l.connector)
        .filter(|l| l.from_lane.as_deref().is_some_and(|f| earlier.contains(f)))
        .filter_map(|j| {
            let f = foot.get(j.to_lane.as_deref()?)?;
            Some(Lane { lane_id: j.lane_id.clone(), width_m: j.width_m, geometry: j.geometry.clone(), connector: true,
                        from_lane: j.from_lane.clone(), to_lane: j.to_lane.clone(), ..(*f).clone() })
        }).collect();
    rest.into_iter().chain(joins).collect()
}

/// duckOSM's gmns_driving.crossing and lane_crossing as one table, a row per crossing per lane it covers; None where the file has none.
pub fn read_crossings(c: &Connection, gmns: &str) -> Result<Option<Vec<Crossing>>> {
    let _a = Attached::new(c, gmns, None)?;
    if cols(c, G, "gmns_driving", "crossing")?.is_empty() || cols(c, G, "gmns_driving", "lane_crossing")?.is_empty() {
        return Ok(None);
    }
    let f = |v: &Value| v.as_f64();
    Ok(Some(rows(c, &format!(
        "SELECT lc.crossing_id, lc.lane_id, lc.start_lr, lc.end_lr, lc.across_from, lc.across_to, lc.to_left, \
                c.painted, c.length, c.crossing_type, c.source, ST_AsText(c.geom) AS cgeom \
         FROM {G}.gmns_driving.lane_crossing lc JOIN {G}.gmns_driving.crossing c USING (crossing_id)"))?
        .iter().map(|r| Crossing {
            crossing_id: s(&r["crossing_id"]).unwrap_or_default(), lane_id: s(&r["lane_id"]).unwrap_or_default(),
            start_lr: f(&r["start_lr"]), end_lr: f(&r["end_lr"]), across_from: f(&r["across_from"]), across_to: f(&r["across_to"]),
            to_left: r["to_left"].as_bool(), painted: r["painted"].as_bool(), length: f(&r["length"]),
            crossing_type: s(&r["crossing_type"]), source: s(&r["source"]), cgeom: s(&r["cgeom"]),
        }).collect()))
}

/// The area's boundary of a duckOSM file (main.boundary, all its rows as one), as WKB; None where there is none.
pub fn read_boundary(c: &Connection, db: &str) -> Result<Option<Vec<u8>>> {
    let _a = Attached::new(c, db, None)?;
    if !cols(c, G, "main", "boundary")?.contains("geom") {
        return Ok(None);
    }
    let r = rows(c, &format!("SELECT ST_AsHEXWKB(ST_Union_Agg(geom)) AS g FROM {G}.main.boundary"))?;
    Ok(r.first().and_then(|r| r["g"].as_str()).map(hex))
}

/// The OSM tags of these ways (raw.ways of the duckOSM file `source`); empty when it has no raw.ways.
pub fn way_tags(c: &Connection, source: &str, ids: &[i64]) -> Result<HashMap<i64, Map<String, Value>>> {
    let _a = Attached::new(c, source, None)?;
    if ids.is_empty() || cols(c, G, "raw", "ways")?.is_empty() {
        return Ok(HashMap::new());
    }
    let list = ids.iter().map(|x| x.to_string()).collect::<Vec<_>>().join(",");
    Ok(rows(c, &format!("SELECT osm_id, tags FROM {G}.raw.ways WHERE osm_id IN ({list})"))?.into_iter()
        .filter_map(|r| Some((i(&r["osm_id"])?, r["tags"].as_object().cloned().unwrap_or_default()))).collect())
}

/// The OSM `width` tag of these ways (raw.ways); a way without one is not in the map.
pub fn width_tags(c: &Connection, source: &str, ids: &[i64]) -> Result<BTreeMap<i64, String>> {
    let _a = Attached::new(c, source, None)?;
    if ids.is_empty() {
        return Ok(BTreeMap::new());
    }
    let list = ids.iter().map(|x| x.to_string()).collect::<Vec<_>>().join(",");
    Ok(rows(c, &format!("SELECT osm_id, tags['width'] AS w FROM {G}.raw.ways WHERE osm_id IN ({list})"))?.into_iter()
        .filter_map(|r| Some((i(&r["osm_id"])?, s(&r["w"])?))).collect())
}

