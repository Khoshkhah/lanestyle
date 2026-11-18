//! lanestyle's settings and its rules for a lane's colour and width: `data/lanestyle.json` with any local `lanestyle.json` on top.

use serde_json::{Map, Value};

/// lanestyle's own settings (the "lanes" key of data/lanestyle.json).
pub const DEFAULTS: &str = include_str!("../data/lanestyle.json");

/// `a` updated by `b`, nested objects merged (state only what changes).
pub fn merge(a: &Value, b: &Value) -> Value {
    let mut out = a.as_object().cloned().unwrap_or_default();
    for (k, v) in b.as_object().into_iter().flatten() {
        let m = match (v, out.get(k)) {
            (Value::Object(_), Some(o @ Value::Object(_))) => merge(o, v),
            _ => v.clone(),
        };
        out.insert(k.clone(), m);
    }
    Value::Object(out)
}

/// lanestyle's settings: data/lanestyle.json, then a lanestyle.json in the current folder, then `settings["lanes"]`, each overriding
/// only what it states (the roadstyle.json way).
pub fn lane_settings(settings: Option<&Value>) -> Result<Value, String> {
    let d: Value = serde_json::from_str(DEFAULTS).map_err(|e| format!("data/lanestyle.json: {e}"))?;
    let mut s = d["lanes"].clone();
    if let Ok(text) = std::fs::read_to_string("lanestyle.json") {
        let local: Value = serde_json::from_str(&text).map_err(|e| format!("lanestyle.json: {e}"))?;
        s = merge(&s, &local["lanes"]);
    }
    Ok(merge(&s, settings.map_or(&Value::Null, |v| &v["lanes"])))
}

/// The mode groups: each has its colour.
const MARKED: [&str; 4] = ["auto", "bus", "bike", "walk"];

/// The colour group of a lane's use: a shared lane ("bus,bike") is the first of bus, bike, walk that it allows; a use of none of them
/// is a car lane's.
pub fn use_group(u: &str) -> &str {
    if MARKED.contains(&u) {
        return u;
    }
    ["bus", "bike", "walk"].into_iter().find(|m| u.split(',').any(|x| x == *m)).unwrap_or("auto")
}

/// A lane's colour by its use (`colors[use_group(use)]`).
// ponytail: the colour of a road cars do not use by who uses it (several modes, Python's _colour_groups) is not here: the lane page
// reads one mode
pub fn use_colour<'a>(s: &'a Value, u: &str) -> &'a str {
    s["colors"][use_group(u)].as_str().unwrap_or_default()
}

/// A lane's width in metres: its own `width_m`, else a default by use (`width_m_by_use`): a `walk` lane is a footpath, and a `bike`
/// lane beyond the link's motor lanes (`lane_num` > `lanes`; no `lanes` is 0) is an on-road bike lane; any other lane is `default_width_m`.
pub fn width(s: &Value, own: Option<f64>, use_: &str, lane_num: Option<i64>, lanes: Option<i64>, have_lanes: bool) -> f64 {
    if let Some(w) = own {
        return w;
    }
    let by = &s["width_m_by_use"];
    if use_ == "walk" {
        if let Some(w) = by["walk"].as_f64() {
            return w;
        }
    }
    if use_ == "bike" && have_lanes {
        if let (Some(w), Some(n)) = (by["bike"].as_f64(), lane_num) {
            if n > lanes.unwrap_or(0) {
                return w;
            }
        }
    }
    s["default_width_m"].as_f64().unwrap_or(3.25)
}

/// A road without lanes in metres: its OSM `width` tag in metres ("2", "2.5 m", "2,5"), else `table[class]`, else `table["default"]`.
/// The second value: the tag when it is no width in metres.
pub fn path_width(highway: Option<&str>, tag: Option<&str>, table: &Map<String, Value>) -> (f64, Option<String>) {
    if let Some(t) = tag {
        match metres(t) {
            Some(m) => return (m, None),
            None => return (class_width(highway, table), Some(t.to_string())),
        }
    }
    (class_width(highway, table), None)
}

fn class_width(highway: Option<&str>, table: &Map<String, Value>) -> f64 {
    // Python's str(hw): a missing class is "None", which is no key
    table.get(highway.unwrap_or("None")).or_else(|| table.get("default")).and_then(Value::as_f64).unwrap_or(2.0)
}

/// `\s*(\d+(?:[.,]\d+)?)\s*(?:m)?\s*` (a full match) as a number.
// ponytail: ASCII digits and white space only (Python's \d and \s are Unicode)
fn metres(t: &str) -> Option<f64> {
    let t = t.trim();
    let t = t.strip_suffix('m').map_or(t, str::trim_end);
    let (int, frac) = match t.find(['.', ',']) {
        Some(i) => (&t[..i], Some(&t[i + 1..])),
        None => (t, None),
    };
    let digits = |s: &str| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit());
    if !digits(int) || frac.is_some_and(|f| !digits(f)) {
        return None;
    }
    t.replace(',', ".").parse().ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn width_tags() {
        for (t, m) in [("2", Some(2.0)), (" 2.5 m", Some(2.5)), ("2,5m", Some(2.5)), ("2 m ", Some(2.0)), ("2.", None), ("x", None), ("2 ft", None)] {
            assert_eq!(metres(t), m, "{t}");
        }
    }
}
