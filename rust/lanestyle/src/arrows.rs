//! Painted lane arrows (docs/design/lane_arrows.md): the direction marking of a lane map, from the movements that leave each lane, and
//! the BUS and bike marks.

use crate::items::{fc, ARROW};
use crate::lanes::{Lane, Turn};
use crate::strokes;
use serde_json::{json, Value};
use std::collections::{BTreeSet, HashMap, HashSet};

const TURNS: [&str; 3] = ["left", "right", "uturn"];

/// The move arrow of a lane: its left / right / thru / uturn, or None. A thru-only lane has one only beside a lane that turns.
fn kinds(lane_id: &str, siblings: &[String], turns_of: &HashMap<String, BTreeSet<String>>) -> Option<BTreeSet<String>> {
    let own: BTreeSet<String> = turns_of.get(lane_id).into_iter().flatten().filter(|t| TURNS.contains(&t.as_str()) || *t == "thru").cloned().collect();
    if own.is_empty() {
        return None;
    }
    let only = |s: &BTreeSet<String>, x: &str| s.len() == 1 && s.contains(x);
    if only(&own, "thru") {
        let turning = siblings.iter().any(|o| turns_of.get(o).is_some_and(|t| t.iter().any(|x| TURNS.contains(&x.as_str()))));
        return turning.then_some(own);
    }
    // ponytail: a uturn beside other moves is not drawn
    if !only(&own, "uturn") && own.iter().any(|x| x == "left" || x == "right" || x == "thru") {
        return Some(own.into_iter().filter(|x| x != "uturn").collect());
    }
    Some(own)
}

/// strokes::shape's name for a set of moves: "uturn", or the moves in left / thru / right order joined by "+".
fn mark_name(k: &BTreeSet<String>) -> String {
    if k.len() == 1 && k.contains("uturn") {
        return "uturn".into();
    }
    let s: Vec<&str> = ["left", "thru", "right"].into_iter().filter(|x| k.contains(*x)).collect();
    if s.is_empty() { "thru".into() } else { s.join("+") }
}

/// The painted marks of each lane as LINE items: a car lane's arrow (its moves, from `turns`) `end_m` before its end, then a plain
/// arrow back along it every `repeat_m`; a bus lane's BUS and a bike lane's bike from 15 m, then every `repeat_m` (60 m when 0; a shared
/// `bus,bike` lane: BUS, its bike 12 m after). Each mark on its lane's line, shifted as the lane (`shifts`); one item per lane and stroke
/// width (a MultiLineString). With `at_junctions` a car lane gets its arrow only where its link ends at a junction: three or more roads
/// with car lanes at its end node. None when nothing is marked.
pub fn mark_strokes(lanes: &[&Lane], turns: &[Turn], s: &Value, shifts: &[f64], colour: &str) -> Result<Option<Value>, String> {
    if s.is_null() || s.as_object().is_some_and(|o| o.is_empty()) || s == &json!(false) {
        return Ok(None);
    }
    let mut turns_of: HashMap<String, BTreeSet<String>> = HashMap::new();
    for t in turns {
        if let Some(k) = t.turn.clone().or_else(|| t.type_.clone()) {
            turns_of.entry(t.from_lane.clone()).or_default().insert(k);
        }
    }
    let mut siblings: HashMap<i64, Vec<String>> = HashMap::new();
    for l in lanes {
        if let Some(k) = l.link_id {
            siblings.entry(k).or_default().push(l.lane_id.clone());
        }
    }
    let back = s["end_m"].as_f64().unwrap_or(10.0);
    let every = s.get("repeat_m").and_then(Value::as_f64).unwrap_or(0.0);
    let junction: Option<HashSet<i64>> = if s.get("at_junctions").and_then(Value::as_bool).unwrap_or(false) {
        let mut pairs: HashSet<(Option<i64>, Option<i64>)> = HashSet::new();
        for l in lanes.iter().filter(|l| !matches!(l.use_.as_deref().unwrap_or("auto"), "walk" | "bike")) {
            pairs.insert((l.from_node_id, l.to_node_id));
        }
        let mut roads_at: HashMap<Option<i64>, HashSet<(Option<i64>, Option<i64>)>> = HashMap::new();
        for (a, b) in pairs {
            let road = if a <= b { (a, b) } else { (b, a) };       // the two directions of a road: one road
            for n in [a, b] {
                roads_at.entry(n).or_default().insert(road);
            }
        }
        Some(roads_at.into_iter().filter(|(_, r)| r.len() >= 3).filter_map(|(n, _)| n).collect())
    } else { None };
    let minzoom = s.get("minzoom").and_then(Value::as_f64);
    let mut out = Vec::new();
    for (i, l) in lanes.iter().enumerate() {
        let use_ = l.use_.clone().unwrap_or_else(|| "auto".into());
        let use_ = if use_.is_empty() { "auto".to_string() } else { use_ };
        if l.geometry.len() < 2 || use_ == "walk" {
            continue;
        }
        let ln = &l.geometry;
        let n = strokes::length_m(ln);
        let mut at: Vec<(f64, String)> = Vec::new();
        if use_.starts_with("bus") || use_ == "bike" {
            let name = if use_.starts_with("bus") { "bus" } else { "bike" };
            at = strokes::positions(n, 15.0, if every == 0.0 { 60.0 } else { every }, back).into_iter().map(|d| (d, name.to_string())).collect();
            if name == "bus" && use_.split(',').any(|x| x == "bike") {
                let more: Vec<(f64, String)> = at.iter().filter(|(d, _)| d + 12.0 + strokes::LENGTH / 2.0 <= n).map(|(d, _)| (d + 12.0, "bike".to_string())).collect();
                at.extend(more);
            }
        } else {
            if n < strokes::LENGTH + 2.0 || junction.as_ref().is_some_and(|j| !l.to_node_id.is_some_and(|t| j.contains(&t))) {
                continue;
            }
            let end = if n >= 2.0 * back { n - back } else { n / 2.0 };
            let sib = l.link_id.and_then(|k| siblings.get(&k)).cloned().unwrap_or_default();
            let k = kinds(&l.lane_id, &sib, &turns_of).unwrap_or_else(|| BTreeSet::from(["thru".to_string()]));
            at.push((end, mark_name(&k)));
            while every != 0.0 && at[at.len() - 1].0 - every > 2.0 * strokes::LENGTH {
                at.push((at[at.len() - 1].0 - every, "thru".into()));
            }
        }
        let w = l.width_m.unwrap_or(f64::NAN);
        let mut by_w: Vec<(f64, Vec<Vec<[f64; 2]>>)> = Vec::new();
        for (d, name) in &at {
            for (line, wm) in strokes::place(&strokes::shape(name, w)?, ln, *d, shifts[i]) {
                match by_w.iter_mut().find(|(x, _)| *x == wm) {
                    Some((_, v)) => v.push(line),
                    None => by_w.push((wm, vec![line])),
                }
            }
        }
        for (wm, parts) in by_w {
            let mut p = json!({"edge_id": l.link_id, "order": ARROW, "color": colour, "width_m": wm, "offset_m": 0.0, "lane_id": l.lane_id});
            if let Some(m) = minzoom {
                p["minzoom"] = json!(m);
            }
            out.push(json!({"type": "Feature", "geometry": {"type": "MultiLineString", "coordinates": parts}, "properties": p}));
        }
    }
    Ok(fc(out))
}
