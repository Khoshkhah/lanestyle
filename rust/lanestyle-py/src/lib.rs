//! The Python binding of lanestyle (the module `lanestyle._rust`): the Python package only calls these functions. Tables go to Python as
//! JSON text, lines as WKB.

use lanestyle::{editor, gmns, page, settings};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use serde_json::{json, Map, Value};
use std::sync::Mutex;

fn err(e: String) -> PyErr {
    PyValueError::new_err(e)
}

fn conn() -> PyResult<gmns::Connection> {
    gmns::connect().map_err(err)
}

fn table(lanes: &lanestyle::lanes::Lanes) -> Value {
    json!({"columns": lanes.columns, "rows": lanes.rows.iter().map(|l| lanes.columns.iter().map(|c| l.get(c)).collect::<Vec<_>>()).collect::<Vec<_>>()})
}

fn crossings_json(c: &Option<Vec<lanestyle::lanes::Crossing>>) -> Value {
    c.as_ref().map_or(Value::Null, |c| json!(c.iter().map(|x| json!({
        "crossing_id": x.crossing_id, "lane_id": x.lane_id, "start_lr": x.start_lr, "end_lr": x.end_lr, "across_from": x.across_from,
        "across_to": x.across_to, "to_left": x.to_left, "painted": x.painted, "length": x.length, "crossing_type": x.crossing_type,
        "source": x.source, "cgeom": x.cgeom})).collect::<Vec<_>>()))
}

/// from_gmns(gmns_db, mode, source_db, modes) -> str: {"lanes": {columns, rows}, "turns": {columns, rows}, "crossings": [rows] | null}
/// (lines as GeoJSON).
#[pyfunction]
#[pyo3(signature = (gmns_db, mode="driving", source_db=None, modes=None))]
fn from_gmns(py: Python<'_>, gmns_db: &str, mode: &str, source_db: Option<&str>, modes: Option<Vec<String>>) -> PyResult<String> {
    py.detach(|| {
        let c = conn()?;
        let (lanes, turns) = gmns::from_gmns(&c, gmns_db, mode, source_db, modes.as_deref()).map_err(err)?;
        let walkers = turns.iter().any(|t| t.walkers.is_some());
        let mut tc = vec!["from_lane", "to_lane", "type", "turn"];
        if walkers {
            tc.push("walkers");
        }
        let rows: Vec<Value> = turns.iter().map(|t| {
            let mut r = vec![json!(t.from_lane), json!(t.to_lane), json!(t.type_), json!(t.turn)];
            if walkers {
                r.push(json!(t.walkers.unwrap_or(false)));
            }
            Value::Array(r)
        }).collect();
        Ok(json!({"lanes": table(&lanes), "turns": {"columns": tc, "rows": rows}, "crossings": crossings_json(&lanes.crossings)}).to_string())
    })
}

/// read_crossings(gmns_db) -> str: the crossings' rows as JSON (null where the file has none).
#[pyfunction]
fn read_crossings(py: Python<'_>, gmns_db: &str) -> PyResult<String> {
    py.detach(|| Ok(crossings_json(&gmns::read_crossings(&conn()?, gmns_db).map_err(err)?).to_string()))
}

/// read_boundary(db) -> bytes | None: the area's boundary as WKB.
#[pyfunction]
fn read_boundary<'py>(py: Python<'py>, db: &str) -> PyResult<Option<Bound<'py, PyBytes>>> {
    let b = py.detach(|| gmns::read_boundary(&conn()?, db).map_err(err))?;
    Ok(b.map(|b| PyBytes::new(py, &b)))
}

/// lane_settings(settings) -> str: lanestyle's settings (JSON text in and out).
#[pyfunction]
#[pyo3(signature = (settings=None))]
fn lane_settings(settings: Option<&str>) -> PyResult<String> {
    let v: Option<Value> = settings.map(serde_json::from_str).transpose().map_err(|e| err(e.to_string()))?;
    Ok(settings::lane_settings(v.as_ref()).map_err(err)?.to_string())
}

/// The last strokes (the editor asks for the items of the same files again and again: Python's lru_cache of one).
static LAST: Mutex<Option<((String, Option<String>, bool), editor::Strokes)>> = Mutex::new(None);

/// lane_items(roads, gmns_db, source_db, connectors) -> (kw, width_m, geometry, notes): the editor's hook. `roads`: JSON text
/// {"edge", "road", "edge_ref", "highway", "modes": [values] (a missing column: null)}; `wkb`: each row's line. Gives the render keywords
/// (JSON text), each row's width and line (WKB) and what to print.
#[pyfunction]
#[allow(clippy::type_complexity)]
fn lane_items<'py>(py: Python<'py>, roads: &str, wkb: Vec<Vec<u8>>, gmns_db: &str, source_db: Option<&str>, connectors: bool)
                   -> PyResult<(String, Vec<f64>, Vec<Bound<'py, PyBytes>>, Vec<String>)> {
    let (kw, widths, lines, notes) = py.detach(|| -> PyResult<_> {
        let cols: Map<String, Value> = serde_json::from_str(roads).map_err(|e| err(e.to_string()))?;
        let col = |k: &str, i: usize| -> Option<String> {
            match cols.get(k).and_then(|v| v.get(i)) { None | Some(Value::Null) => None, Some(Value::String(s)) => Some(s.clone()), Some(v) => Some(v.to_string()) }
        };
        let rows: Vec<editor::RoadRow> = wkb.iter().enumerate().map(|(i, b)| editor::RoadRow {
            edge: col("edge", i).unwrap_or_default(), road: col("road", i).unwrap_or_default(), edge_ref: col("edge_ref", i),
            highway: col("highway", i), modes: col("modes", i), geometry: lanestyle::geo::wkb_line(b).unwrap_or_default(),
        }).collect();
        let s = settings::lane_settings(None).map_err(err)?;
        let c = conn()?;
        let key = (gmns_db.to_string(), source_db.map(String::from), connectors);
        let mut last = LAST.lock().map_err(|e| err(e.to_string()))?;
        if last.as_ref().is_none_or(|(k, _)| *k != key) {
            let (lanes, turns) = gmns::from_gmns(&c, gmns_db, "driving", source_db, None).map_err(err)?;
            let tags = source_db.map(|src| gmns::way_tags(&c, src, &editor::ways_needed(&lanes, &s))).transpose().map_err(err)?;
            *last = Some((key, editor::strokes(&lanes, &turns, &s, connectors, &tags).map_err(err)?));
        }
        let st = &last.as_ref().expect("strokes").1;
        let amber = page::amber().map_err(err)?;
        let wt = |ids: &[i64]| match source_db {
            Some(src) => gmns::width_tags(&c, src, ids).map(|m| m.into_iter().collect()),
            None => Ok(Default::default()),
        };
        let it = editor::lane_items(&rows, cols.contains_key("modes"), st, &s, &amber, &wt).map_err(err)?;
        Ok((Value::Object(it.kw).to_string(), it.width_m, it.geometry.iter().map(|l| page::wkb(l)).collect::<Vec<_>>(), it.notes))
    })?;
    Ok((kw, widths, lines.iter().map(|b| PyBytes::new(py, b)).collect(), notes))
}

/// lane_page(area, gmns_db, source_db, connectors, kw) -> (html, notes): the lane page (MapLibre in it). `kw`: render_edges' keywords
/// (JSON text) over the page's.
#[pyfunction]
fn lane_page(py: Python<'_>, area: &str, gmns_db: &str, source_db: &str, connectors: bool, kw: &str) -> PyResult<(String, Vec<String>)> {
    let kw: Map<String, Value> = serde_json::from_str(kw).map_err(|e| err(e.to_string()))?;
    py.detach(|| page::lane_page(std::path::Path::new(area), gmns_db, source_db, connectors, kw).map_err(err))
}

#[pymodule]
fn _rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(from_gmns, m)?)?;
    m.add_function(wrap_pyfunction!(read_crossings, m)?)?;
    m.add_function(wrap_pyfunction!(read_boundary, m)?)?;
    m.add_function(wrap_pyfunction!(lane_settings, m)?)?;
    m.add_function(wrap_pyfunction!(lane_items, m)?)?;
    m.add_function(wrap_pyfunction!(lane_page, m)?)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
