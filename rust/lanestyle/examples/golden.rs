//! Compare the Rust port with the golden files of the Python lanestyle (tests/golden/make_golden.py): coordinates to 1 mm, every other
//! value exactly. Prints one line for each output and exits with 1 when one differs.
//!
//!     cargo run --release -p lanestyle --features page --example golden -- DIR AREA [AREA ...]
use lanestyle::{editor, gmns, settings};
use serde_json::{json, Value};
use std::collections::BTreeMap;

/// What differs: the number of values compared, the coordinates more than 1 mm off, the 7-decimal coordinates one step off (both
/// sides rounded: the unrounded values are near the middle), the largest coordinate difference in metres, and the first other differences.
#[derive(Default)]
struct Diff {
    values: usize,
    far: usize,
    steps: usize,
    max_m: f64,
    other: Vec<String>,
}

fn coord_m(a: f64, b: f64) -> f64 {
    (a - b).abs() * 111_320.0
}

fn cmp(a: &Value, b: &Value, path: &str, coord: bool, d: &mut Diff) {
    match (a, b) {
        (Value::Number(x), Value::Number(y)) => {
            d.values += 1;
            let (x, y) = (x.as_f64().unwrap(), y.as_f64().unwrap());
            if coord {
                let m = coord_m(x, y);
                d.max_m = d.max_m.max(m);
                if m > 1e-3 {
                    let step = ((x - y).abs() - 1e-7).abs() < 1e-12 && (x * 1e7).fract().abs() < 1e-6;
                    if step { d.steps += 1 } else { d.far += 1; if d.other.len() < 8 { d.other.push(format!("{path}: {x} != {y} ({m:.4} m)")) } }
                }
            } else if x != y && d.other.len() < 8 {
                d.other.push(format!("{path}: {x} != {y}"));
            }
        }
        (Value::Array(x), Value::Array(y)) => {
            if x.len() != y.len() {
                if d.other.len() < 8 { d.other.push(format!("{path}: {} items != {}", x.len(), y.len())) }
                return;
            }
            for (i, (p, q)) in x.iter().zip(y).enumerate() {
                cmp(p, q, &format!("{path}[{i}]"), coord, d);
            }
        }
        (Value::Object(x), Value::Object(y)) => {
            let (kx, ky): (Vec<&String>, Vec<&String>) = (x.keys().collect(), y.keys().collect());
            if kx != ky && d.other.len() < 8 {
                d.other.push(format!("{path}: keys {kx:?} != {ky:?}"));
            }
            for (k, v) in x {
                if let Some(w) = y.get(k) {
                    cmp(v, w, &format!("{path}.{k}"), coord || k == "coordinates", d);
                }
            }
        }
        _ => {
            d.values += 1;
            if a != b && d.other.len() < 8 {
                d.other.push(format!("{path}: {a} != {b}"));
            }
        }
    }
}

fn report(name: &str, py: &Value, rs: &Value) -> bool {
    let mut d = Diff::default();
    cmp(py, rs, "", false, &mut d);
    let ok = d.far == 0 && d.other.is_empty();
    println!("{} {name}: {} values, largest coordinate difference {:.6} mm, {} one-step 7-decimal roundings, {} far",
             if ok { "SAME" } else { "DIFF" }, d.values, d.max_m * 1000.0, d.steps, d.far);
    for o in &d.other {
        println!("    {o}");
    }
    ok
}

fn read(path: &std::path::Path) -> Value {
    serde_json::from_slice(&std::fs::read(path).unwrap_or_else(|e| panic!("{}: {e}", path.display()))).unwrap()
}

fn main() {
    let a: Vec<String> = std::env::args().skip(1).collect();
    let dir = std::path::Path::new(&a[0]);
    let mut all = true;
    let s = settings::lane_settings(None).unwrap();
    for area in &a[1..] {
        let (g, src) = (dir.join(format!("{area}_gmns.duckdb")), dir.join(format!("{area}.duckdb")));
        let (g, src) = (g.to_str().unwrap(), src.to_str().unwrap());
        let c = gmns::connect().unwrap();
        let t = std::time::Instant::now();
        let (lanes, turns) = gmns::from_gmns(&c, g, "driving", Some(src), None).unwrap();
        let read_s = t.elapsed().as_secs_f64();
        let golden = read(&dir.join(format!("{area}_lanes.json")));
        let table = json!({"columns": lanes.columns, "rows": lanes.rows.iter().map(|l| lanes.columns.iter().map(|c| l.get(c)).collect::<Vec<_>>()).collect::<Vec<_>>()});
        all &= report(&format!("{area} lane table"), &golden["lanes"], &table);
        let tt = json!({"columns": ["from_lane", "to_lane", "type", "turn"], "rows": turns.iter().map(|t| json!([t.from_lane, t.to_lane, t.type_, t.turn])).collect::<Vec<_>>()});
        all &= report(&format!("{area} turns"), &golden["turns"], &tt);
        let ids = editor::ways_needed(&lanes, &s);
        let tags = Some(gmns::way_tags(&c, src, &ids).unwrap());
        for conn in [false, true] {
            let t = std::time::Instant::now();
            let st = editor::strokes(&lanes, &turns, &s, conn, &tags).unwrap();
            let secs = t.elapsed().as_secs_f64();
            let golden = read(&dir.join(format!("{area}_strokes{}.json", if conn { "_connectors" } else { "" })));
            let lines_of: BTreeMap<&String, Value> = st.lines_of.iter().map(|(k, l)| (k, json!({"type": "LineString", "coordinates": l}))).collect();
            let width: BTreeMap<&String, f64> = st.width.iter().map(|(k, w)| (k, *w)).collect();
            for (k, v) in [("lanes", json!(st.lanes)), ("lines", json!(st.lines)), ("marks", json!(st.marks)), ("connectors", json!(st.connectors)),
                           ("zebras", json!(st.zebras)), ("sidewalks", json!(st.sidewalks)), ("special", json!(st.special))] {
                all &= report(&format!("{area} {k}{}", if conn { " (connectors on)" } else { "" }), &golden[k], &v);
            }
            let sorted = |v: &Value| -> Value { let m: BTreeMap<String, Value> = v.as_object().unwrap().iter().map(|(k, v)| (k.clone(), v.clone())).collect(); json!(m) };
            all &= report(&format!("{area} width"), &sorted(&golden["width"]), &json!(width));
            all &= report(&format!("{area} lines_of"), &sorted(&golden["lines_of"]), &json!(lines_of));
            println!("    (read {read_s:.1} s, items {secs:.1} s)");
            if !conn {
                let golden = read(&dir.join(format!("{area}_items.json")));
                let (roads, has_modes) = lanestyle::page::road_rows(std::fs::read(dir.join(format!("{area}_roads.parquet"))).unwrap()).unwrap();
                let amber = golden["kw"]["settings"]["palettes"]["lanestyle_editor"].as_object().unwrap().clone();
                // roadstyle's amber of today (page::amber) against the palette Python had (the fill is lanestyle's)
                let mine: serde_json::Map<String, Value> = lanestyle::page::amber().unwrap().into_iter().map(|(k, mut v)| { v["fill"] = amber[&k]["fill"].clone(); (k, v) }).collect();
                all &= report("roadstyle's amber palette", &json!(amber), &json!(mine));
                let wt = |ids: &[i64]| gmns::width_tags(&c, src, ids).map(|m| m.into_iter().collect());
                let it = editor::lane_items(&roads, has_modes, &st, &s, &amber, &wt).unwrap();
                for n in &it.notes {
                    println!("    {n}");
                }
                all &= report(&format!("{area} lane_items kw"), &golden["kw"], &json!(it.kw));
                all &= report(&format!("{area} lane_items width_m"), &golden["width_m"], &json!(it.width_m));
                all &= report(&format!("{area} lane_items geometry"), &golden["geometry"],
                              &json!(it.geometry.iter().map(|l| json!({"type": "LineString", "coordinates": l})).collect::<Vec<_>>()));
            }
        }
    }
    std::process::exit(if all { 0 } else { 1 });
}
