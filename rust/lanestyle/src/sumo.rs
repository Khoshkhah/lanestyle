//! The SUMO net reader: the lanes of a SUMO `.net.xml` (netconvert's output, for example of `duckosm sumo`) as a lane table, so that
//! roadstyle draws SUMO's own lane shapes. Each `<lane>` is one row with its `shape` (in lon/lat) and `width`. The lanes of the internal
//! edges (`:<junction>_<n>`, SUMO's paths through a junction) are connectors. duckOSM's SUMO edge id is its `edge_id`: it is the row's
//! `link_id`.

use crate::geo::{Line, Utm};
use crate::lanes::{Lane, Lanes};
use std::collections::HashMap;

/// The attributes of the tag `<name ...>` that starts at `s` (after the `<`), with the XML entities decoded.
fn attrs(s: &str) -> HashMap<&str, String> {
    let mut out = HashMap::new();
    let end = s.find('>').unwrap_or(s.len());
    let mut rest = &s[..end];
    while let Some(eq) = rest.find("=\"") {
        let key = rest[..eq].rsplit(|c: char| c.is_whitespace()).next().unwrap_or("");
        let v = &rest[eq + 2..];
        let close = v.find('"').unwrap_or(v.len());
        let val = v[..close].replace("&quot;", "\"").replace("&apos;", "'").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&");
        out.insert(key, val);
        rest = &v[(close + 1).min(v.len())..];
    }
    out
}

/// The use of a lane by its `allow` and `disallow` classes: bus, bike or walk when only that class has it, else auto.
fn use_of(allow: Option<&String>, disallow: Option<&String>) -> String {
    let Some(a) = allow else {
        let d = disallow.map(String::as_str).unwrap_or("");
        return if d.split(' ').any(|c| c == "passenger") && !d.split(' ').any(|c| c == "bus") { "bus" } else { "auto" }.into();
    };
    let has = |c: &str| a.split(' ').any(|x| x == c);
    if has("passenger") || has("private") {
        "auto"
    } else if has("bus") {
        "bus"
    } else if has("bicycle") {
        "bike"
    } else if has("pedestrian") {
        "walk"
    } else {
        "auto"
    }
    .into()
}

/// The lane table of a SUMO net (the text of a `.net.xml`): one row for each lane, in the order of the file. `lane_id`: SUMO's lane id;
/// `link_id`: the edge id (a number for duckOSM's edges); `lane_num`: SUMO's index (0: the rightmost lane); `highway`: the edge type
/// without `highway.` (an internal lane: the type of the edge it leaves); `connector`: a lane of an internal edge.
pub fn from_sumo_net(xml: &str) -> Result<Lanes, String> {
    let mut offset = [0.0, 0.0];
    let mut utm = None;
    let mut via_from: HashMap<String, String> = HashMap::new();
    let mut edges: Vec<(HashMap<&str, String>, Vec<HashMap<&str, String>>)> = Vec::new();
    for tag in xml.split('<').skip(1) {
        let name = tag.split(|c: char| c.is_whitespace() || c == '>' || c == '/').next().unwrap_or("");
        match name {
            "location" => {
                let a = attrs(tag);
                let num = |k: &str| -> Result<Vec<f64>, String> {
                    a.get(k).ok_or(format!("<location> has no {k}"))?.split(',').map(|x| x.trim().parse().map_err(|e| format!("{k}: {e}"))).collect()
                };
                let (o, b) = (num("netOffset")?, num("origBoundary")?);
                if !a.get("projParameter").is_some_and(|p| p.contains("+proj=utm")) || o.len() != 2 || b.len() != 4 {
                    return Err("the net is not in UTM (netconvert --proj.utm): only a UTM net can be read".into());
                }
                offset = [o[0], o[1]];
                utm = Some(Utm::new((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0));
            }
            "edge" => edges.push((attrs(tag), Vec::new())),
            "lane" => match edges.last_mut() {
                Some(e) => e.1.push(attrs(tag)),
                None => return Err("a <lane> outside an <edge>".into()),
            },
            "connection" => {
                let a = attrs(tag);
                if let (Some(v), Some(f)) = (a.get("via"), a.get("from")) {
                    // the internal edge of the lane `via` (its id without the lane index)
                    let e = v.rsplit_once('_').map_or(v.as_str(), |x| x.0);
                    via_from.entry(e.to_string()).or_insert_with(|| f.clone());
                }
            }
            _ => {}
        }
    }
    let utm = utm.ok_or("no <location> in the net")?;
    let class = |e: &HashMap<&str, String>| e.get("type").map(|t| t.strip_prefix("highway.").unwrap_or(t).to_string());
    let types: HashMap<&str, Option<String>> = edges.iter().filter_map(|(e, _)| Some((e.get("id")?.as_str(), class(e)))).collect();
    // the class of the normal edge that an internal edge leaves: an internal edge can leave another internal edge (a second step in the
    // junction), so follow `via_from` back to a normal edge
    let leaves = |id: &str| -> Option<String> {
        let mut e = id;
        for _ in 0..8 {
            e = via_from.get(e)?.as_str();
            if !e.starts_with(':') {
                return types.get(e).cloned().flatten();
            }
        }
        None
    };
    let mut rows = Vec::new();
    for (e, lanes) in &edges {
        let id = e.get("id").cloned().unwrap_or_default();
        let internal = e.get("function").is_some_and(|f| f == "internal");
        if e.get("function").is_some_and(|f| f != "internal" && f != "normal") {
            continue; // crossings and walking areas: no lanes of the road
        }
        let highway = if internal { leaves(&id) } else { class(e) };
        for l in lanes {
            let shape: Line = l.get("shape").ok_or_else(|| format!("lane {:?}: no shape", l.get("id")))?.split_whitespace().map(|p| {
                let (x, y) = p.split_once(',').ok_or(format!("bad point {p}"))?;
                let (x, y): (f64, f64) = (x.parse().map_err(|e| format!("{p}: {e}"))?, y.parse().map_err(|e| format!("{p}: {e}"))?);
                Ok(utm.inv([x - offset[0], y - offset[1]]))
            }).collect::<Result<_, String>>()?;
            rows.push(Lane {
                lane_id: l.get("id").cloned().unwrap_or_default(),
                highway: highway.clone(),
                width_m: Some(l.get("width").and_then(|w| w.parse().ok()).unwrap_or(3.2)), // SUMO's default lane width
                use_: Some(use_of(l.get("allow"), l.get("disallow"))),
                name: e.get("name").cloned(),
                link_id: if internal { None } else { id.parse().ok() },
                lane_num: l.get("index").and_then(|i| i.parse().ok()),
                lanes: Some(lanes.len() as i64),
                connector: internal,
                edge_ref: Some(id.clone()),
                geometry: shape,
                ..Default::default()
            });
        }
    }
    let columns = ["lane_id", "highway", "width_m", "use", "name", "link_id", "lane_num", "lanes", "connector", "edge_ref", "geometry"];
    Ok(Lanes { rows, columns: columns.map(String::from).to_vec(), crossings: None })
}
