//! The lane page: the level area's roads as roadstyle's level editor draws them, with lanestyle's items, in roadstyle's page.

use std::path::Path;

/// The error of the page part.
pub type Result<T> = std::result::Result<T, String>;

/// The level editor's road table of the level area `folder` (roadstyle-levels' folder: roads.parquet, pairs.csv and your edits.csv,
/// heads.csv, caps.csv), as GeoParquet: one row for each edge with `edge`, `road`, its road's columns and the drawing numbers. The numbers
/// are levels.csv's when levels_info.json says that it was solved from the same inputs, else the area is solved again (Python's
/// `roadstyle.level_editor.Area(folder).draw`).
pub fn area_draw(folder: &Path) -> Result<Vec<u8>> {
    let text = |f: &str| std::fs::read_to_string(folder.join(f)).unwrap_or_default();
    let bytes = |f: &str| std::fs::read(folder.join(f)).unwrap_or_default();
    let roads = std::fs::read(folder.join("roads.parquet")).map_err(|e| format!("{}: no level area ({e})", folder.display()))?;
    let mut ed = roadstyle::level_editor::Editor::new(roads, &text("pairs.csv")).map_err(|e| e.to_string())?;
    let key = roadstyle::levels::inputs_key(&bytes("roads.parquet"), &bytes("pairs.csv"), &bytes("edits.csv"));
    let info: serde_json::Value = serde_json::from_str(&text("levels_info.json")).unwrap_or_default();
    let stored = (info["inputs"].as_str() == Some(key.as_str())).then(|| ed.levels_of(&text("levels.csv"))).flatten();
    let levels: Vec<i64> = match stored {
        Some(l) => l.into_iter().map(i64::from).collect(),
        None => ed.solve(&text("edits.csv")).map_err(|e| e.to_string())?.levels.iter().flatten().copied().collect(),
    };
    ed.draw(&levels, &text("heads.csv"), &text("caps.csv")).map_err(|e| e.to_string())
}

/// The editor's road table (GeoParquet, `area_draw`) as the rows `editor::lane_items` reads, and whether it has the column `modes`.
pub fn road_rows(parquet: Vec<u8>) -> Result<(Vec<crate::editor::RoadRow>, bool)> {
    let rows = roadstyle::read::read_table(parquet, "geometry").map_err(|e| e.to_string())?;
    let has_modes = rows.first().is_some_and(|r| r.cols.contains_key("modes"));
    let text = |v: Option<&serde_json::Value>| match v {
        None | Some(serde_json::Value::Null) => None,
        Some(serde_json::Value::String(s)) => Some(s.clone()),
        Some(v) => Some(v.to_string()),
    };
    Ok((rows.into_iter().map(|r| crate::editor::RoadRow {
        edge: text(r.cols.get("edge")).unwrap_or_default(),
        road: text(r.cols.get("road")).unwrap_or_default(),
        edge_ref: text(r.cols.get("edge_ref")),
        highway: text(r.cols.get("highway")),
        modes: text(r.cols.get("modes")),
        geometry: r.blob.as_deref().and_then(crate::geo::wkb_line).unwrap_or_default(),
    }).collect(), has_modes))
}

/// A line as WKB (little endian, 2D).
pub fn wkb(l: &[[f64; 2]]) -> Vec<u8> {
    let mut b = vec![1u8, 2, 0, 0, 0];
    b.extend((l.len() as u32).to_le_bytes());
    for p in l {
        b.extend(p[0].to_le_bytes());
        b.extend(p[1].to_le_bytes());
    }
    b
}

/// roadstyle's palette "amber" as `{class: {fill, width, casing_width, casing, dash, opacity}}`: the palette file's classes (their colours) at
/// the default profile's widths, as roadstyle's look makes every palette's table (roadstyle-look `class_entries`; Python's
/// `roadstyle.palette_to_dict("amber")` before roadstyle 0.26).
pub fn amber() -> Result<serde_json::Map<String, serde_json::Value>> {
    use serde_json::{json, Value};
    use yaml_rust2::{Yaml, YamlLoader};
    fn to_json(y: &Yaml) -> Value {
        match y {
            Yaml::Real(r) => r.parse::<f64>().map_or(Value::Null, |f| json!(f)),
            Yaml::Integer(i) => json!(i),
            Yaml::String(s) => json!(s),
            Yaml::Boolean(b) => json!(b),
            Yaml::Array(a) => Value::Array(a.iter().map(to_json).collect()),
            Yaml::Hash(h) => Value::Object(h.iter().filter_map(|(k, v)| Some((k.as_str()?.to_string(), to_json(v)))).collect()),
            _ => Value::Null,
        }
    }
    let pal = YamlLoader::load_from_str(roadstyle::assets::text!("data/palettes/amber.yaml")).map_err(|e| format!("amber.yaml: {e}"))?;
    let colours = to_json(&pal[0]["classes"]);
    let o = roadstyle::look::Options::from_value(&json!({"palette": "amber"})).map_err(|e| e.to_string())?;
    let look = roadstyle::Look::resolve(&o).map_err(|e| e.to_string())?;
    let sections = serde_json::to_value(&look.sections).map_err(|e| e.to_string())?;
    let classes = &sections["roads"]["classes"];
    let mut out = serde_json::Map::new();
    for (c, col) in colours.as_object().into_iter().flatten() {
        let Some(cl) = classes.get(c).filter(|e| e.get("width").is_some()) else { continue };
        out.insert(c.clone(), json!({"fill": col["fill"], "width": cl["width"], "casing_width": cl["casing_width"],
                                     "casing": col.get("casing").cloned().unwrap_or(Value::Null), "dash": cl.get("dash").cloned().unwrap_or(Value::Null),
                                     "opacity": col.get("opacity").cloned().unwrap_or(json!(1.0))}));
    }
    Ok(out)
}

/// The road table of the page: the editor's rows (`draw`, GeoParquet) with lanestyle's `width_m` and lines.
fn page_roads(draw: Vec<u8>, width_m: &[f64], lines: &[crate::geo::Line]) -> Result<roadstyle::RoadTable> {
    use serde_json::{json, Value};
    let rows = roadstyle::read::read_table(draw, "geometry").map_err(|e| e.to_string())?;
    let rows: Vec<(Vec<(String, Value)>, Value)> = rows.into_iter().zip(width_m).zip(lines).map(|((r, w), l)| {
        let mut props: Vec<(String, Value)> = r.cols.into_iter().filter(|(k, _)| k != "width_m").collect();
        props.push(("width_m".into(), json!(w)));
        (props, json!({"type": "LineString", "coordinates": l}))
    }).collect();
    let bytes = roadstyle_io::write::parquet(|| rows.iter().map(|(p, g)| roadstyle_io::write::Row {
        id: None,
        props: p.iter().map(|(k, v)| (k.as_str().into(), v.clone().into())).collect(),
        geometry: Some(g.clone().into()),
    }), true).map_err(|e| e.to_string())?;
    roadstyle::read::read_roads(bytes, "geometry").map_err(|e| e.to_string())
}

/// The lane page (Python's `lanestyle.lane_page`): the roads of the level area `area` as roadstyle's level editor draws them, each one
/// line at its lanes' full width, with lanestyle's items, in roadstyle's page (MapLibre in it). `gmns`: duckOSM's GMNS file of `source`,
/// the duckOSM file. `connectors`: also the lane connectors through the junctions, unseen. `kw`: render_edges' keywords over the page's
/// (`basemap`, `filter_control`, `name`, ...). Gives the page and what lanestyle and roadstyle say about it.
pub fn lane_page(area: &Path, gmns: &str, source: &str, connectors: bool, kw: serde_json::Map<String, serde_json::Value>) -> Result<(String, Vec<String>)> {
    use crate::{editor, gmns as g, settings};
    use serde_json::json;
    let draw = area_draw(area)?;
    let (rows, has_modes) = road_rows(draw.clone())?;
    let cols: Vec<String> = roadstyle::read::read_table(draw.clone(), "geometry").map_err(|e| e.to_string())?
        .first().map(|r| r.cols.keys().cloned().collect()).unwrap_or_default();
    let c = g::connect()?;
    let s = settings::lane_settings(None)?;
    let (lanes, turns) = g::from_gmns(&c, gmns, "driving", Some(source), None)?;
    let tags = Some(g::way_tags(&c, source, &editor::ways_needed(&lanes, &s))?);
    let st = editor::strokes(&lanes, &turns, &s, connectors, &tags)?;
    let it = editor::lane_items(&rows, has_modes, &st, &s, &amber()?, &|ids| g::width_tags(&c, source, ids).map(|m| m.into_iter().collect()))?;
    let roads = page_roads(draw, &it.width_m, &it.geometry)?;
    // render_edges' keywords: the level columns of the editor's table, the page's (blank: just the lanes), lanestyle's, then the caller's
    let mut args = serde_json::Map::new();
    for (k, v) in [("edge_id_col", "edge"), ("directed_col", "directed"), ("driving_col", "driving"), ("casing_start_col", "casing_start"),
                   ("casing_level_col", "casing_level"), ("casing_end_col", "casing_end"), ("fill_level_col", "fill_level"),
                   ("cap_start_col", "cap_start"), ("cap_end_col", "cap_end"), ("head_start_m_col", "head_start_m"), ("head_end_m_col", "head_end_m")] {
        args.insert(k.into(), json!(v));
    }
    let popup: Vec<&str> = ["name", "highway", "edge_ref", "lanes", "modes", "bus_lines"].into_iter().filter(|c| cols.iter().any(|x| x == c)).collect();
    args.insert("road_popup".into(), json!(popup));
    args.insert("name".into(), json!("Lanes · map"));
    args.insert("basemap".into(), json!("blank"));
    args.insert("filter_control".into(), json!(false));
    args.extend(it.kw);
    args.extend(kw);
    render(roads, args, it.notes)
}

/// The lane page of a SUMO net (the text of a `.net.xml`, `sumo::from_sumo_net`): every SUMO lane one line on its own shape at its own
/// width, in lanestyle's colour for its use, with roadstyle's outline; the lanes of the internal edges (SUMO's paths through a junction)
/// too, under the roads. The same look as `lane_page`: lanestyle's settings and roadstyle's palette "amber" in the car lane colour. `kw`:
/// render_edges' keywords over the page's. Gives the page and what lanestyle and roadstyle say about it.
pub fn sumo_page(net_xml: &str, kw: serde_json::Map<String, serde_json::Value>) -> Result<(String, Vec<String>)> {
    use crate::settings::{lane_settings, use_colour};
    use serde_json::{json, Map, Value};
    let lanes = crate::sumo::from_sumo_net(net_xml)?;
    let s = lane_settings(None)?;
    let mut notes = Vec::new();
    let rows: Vec<&crate::lanes::Lane> = lanes.rows.iter().collect();
    let no_class = rows.iter().filter(|l| l.highway.is_none()).count();
    if no_class > 0 {
        notes.push(format!("lanestyle.sumo_page: {no_class} lanes have no road class: drawn as unclassified"));
    }
    let class = |l: &crate::lanes::Lane| l.highway.clone().unwrap_or_else(|| "unclassified".into());
    let table: Vec<(Vec<(String, Value)>, Value)> = rows.iter().map(|l| (vec![
        ("edge".into(), json!(l.lane_id)),
        ("highway".into(), json!(class(l))),
        // one label for each road: on its lane 0
        ("name".into(), json!(if l.connector || l.lane_num != Some(0) { None } else { l.name.clone() })),
        ("sumo_edge".into(), json!(l.edge_ref)),
        ("lane_id".into(), json!(l.lane_id)),
        ("use".into(), json!(l.use_)),
        ("width_m".into(), json!(l.width_m)),
        ("internal".into(), json!(l.connector)),
        // the drawing order: the internal lanes (0) under the lanes of the roads (1), each with its outline
        ("level".into(), json!(if l.connector { 0 } else { 1 })),
        // flat ends: a SUMO lane ends where its junction begins
        ("cap".into(), json!(true)),
    ], json!({"type": "LineString", "coordinates": l.geometry}))).collect();
    let bytes = roadstyle_io::write::parquet(|| table.iter().map(|(p, g)| roadstyle_io::write::Row {
        id: None,
        props: p.iter().map(|(k, v)| (k.as_str().into(), v.clone().into())).collect(),
        geometry: Some(g.clone().into()),
    }), true).map_err(|e| e.to_string())?;
    let roads = roadstyle::read::read_roads(bytes, "geometry").map_err(|e| e.to_string())?;
    // lane_items' look: every class of amber in the car lane colour; each lane in the colour of its use
    let auto = s["colors"]["auto"].clone();
    let pal: Map<String, Value> = amber()?.into_iter().map(|(c, v)| {
        let mut v = v.as_object().cloned().unwrap_or_default();
        v.insert("fill".into(), auto.clone());
        (c, Value::Object(v))
    }).collect();
    let classes: std::collections::BTreeSet<String> = rows.iter().map(|l| class(l)).collect();
    let colours: Map<String, Value> = rows.iter().map(|l| (l.lane_id.clone(), json!(use_colour(&s, l.use_.as_deref().unwrap_or("auto"))))).collect();
    let mut args = Map::new();
    for (k, v) in [("edge_id_col", json!("edge")), ("name", json!("SUMO lanes · map")), ("basemap", json!("blank")), ("filter_control", json!(false)),
                   ("road_popup", json!(["name", "highway", "sumo_edge", "lane_id", "use", "width_m", "internal"])),
                   ("width_m_col", json!("width_m")), ("width_m_zoom", json!(0)), ("casing_m", s["casing_m"].clone()),
                   ("casing_min_px", s["casing_min_px"].clone()), ("arrows", json!(false)), ("palette", json!("lanestyle_editor")),
                   ("settings", json!({"palettes": {"lanestyle_editor": pal}, "config": {"single_line_classes": classes,
                       "labels": {"color": "#333333", "halo_color": "#ffffff", "halo_width": 1.5, "size": [[15, 10], [17, 12], [19, 15], [21, 20], [22, 24]]}}})),
                   ("color_table", Value::Object(colours)), ("color_key", json!("edge")), ("casing_level_col", json!("level")), ("cap_col", json!("cap")),
                   ("fill_level_col", json!("level"))] {
        args.insert(k.into(), v);
    }
    args.extend(kw);
    render(roads, args, notes)
}

/// render_edges(backend="web") of a road table with the keywords `args`: the palette, profile and settings out of the keywords, the class
/// column, the live page. `notes`: what the caller says, before roadstyle's warnings.
fn render(roads: roadstyle::RoadTable, mut args: serde_json::Map<String, serde_json::Value>, mut notes: Vec<String>) -> Result<(String, Vec<String>)> {
    use serde_json::{json, Value};
    let palette = args.remove("palette").unwrap_or(json!("amber"));
    let profile = args.remove("profile").unwrap_or(Value::Null);
    let settings = args.remove("settings").unwrap_or(Value::Null);
    args.entry("highway_col").or_insert(json!("highway"));
    args.insert("state".into(), json!("live"));
    let o = roadstyle::look::Options::from_value(&json!({"palette": palette, "profile": profile, "settings": settings, "args": args}))
        .map_err(|e| e.to_string())?;
    let look = roadstyle::Look::resolve(&o).map_err(|e| e.to_string())?;
    let mut given = roadstyle::page_options::given_of(&look, &o.args);
    for (k, env) in [("street_view_key", "GOOGLE_MAPS_KEY"), ("mapillary_token", "MAPILLARY_TOKEN")] {
        if !given.get(k).is_some_and(|v| !v.is_null()) {
            given.insert(k.into(), std::env::var(env).ok().filter(|v| !v.is_empty()).map_or(Value::Null, Value::from));
        }
    }
    let page = roadstyle::page_options::page_from(roads, None, &look, &o, &given).map_err(|e| e.to_string())?;
    notes.extend(page.warnings);
    let html = page.html.replacen("__MAPLIBRE_CSS__", roadstyle::assets::text!("vendor/maplibre-gl.css"), 1)
        .replacen("__MAPLIBRE_JS__", &roadstyle::assets::text!("vendor/maplibre-gl.js").replace("</script>", "<\\/script>"), 1);
    Ok((html, notes))
}
