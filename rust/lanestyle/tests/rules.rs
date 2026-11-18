//! The rules, each on a small case (the Python tests of lanestyle 0.3, now on the Rust engine). The golden files check the whole
//! output on Monaco and Tartu (examples/golden.rs).
use lanestyle::geo::Line;
use lanestyle::lanes::{Crossing, Lane, Lanes, Turn};
use lanestyle::{arrows, editor, items, settings, strokes};
use serde_json::{json, Map, Value};
use std::collections::{BTreeMap, HashMap};

const NAMES: [&str; 10] = ["thru", "left", "right", "uturn", "left+thru", "thru+right", "left+right", "left+thru+right", "bus", "bike"];

fn extent(shp: &strokes::Shape) -> (f64, f64) {
    let pts: Vec<(f64, f64, f64)> = shp.iter().flat_map(|(p, w)| p.iter().map(move |q| (q[0], q[1], *w))).collect();
    let side = pts.iter().map(|(_, v, w)| v.abs() + w / 2.0).fold(0.0, f64::max);
    let (lo, hi) = pts.iter().fold((f64::MAX, f64::MIN), |(a, b), (u, _, _)| (a.min(*u), b.max(*u)));
    (side, hi - lo)
}

fn metres(l: &[[f64; 2]], lat: f64) -> Vec<(f64, f64)> {
    l.iter().map(|p| ((p[0] - 7.42) * 111320.0 * lat.to_radians().cos(), (p[1] - lat) * 110540.0)).collect()
}

#[test]
fn a_shape_is_not_empty_and_fits_its_lane() {
    for name in NAMES {
        for w in if name == "bike" { [3.25, 1.5] } else { [3.25, 2.5] } {
            let shp = strokes::shape(name, w).unwrap();
            assert!(!shp.is_empty() && shp.iter().all(|(p, w)| p.len() >= 2 && *w > 0.0), "{name}");
            assert!(extent(&shp).0 <= w / 2.0 + 1e-9, "{name} {w}");
        }
    }
    assert!((extent(&strokes::shape("thru", 3.25).unwrap()).1 - strokes::LENGTH).abs() < 0.4);
    let b = extent(&strokes::shape("bike", 1.5).unwrap()).1;
    assert!(1.4 < b && b < 1.8);
    assert!(strokes::shape("nope", 3.0).is_err());
}

#[test]
fn a_mark_is_placed_on_a_straight_and_a_curved_lane() {
    let shp = strokes::shape("thru", 3.25).unwrap();
    let east = vec![[7.42, 43.73], [7.43, 43.73]];
    let f = strokes::place(&shp, &east, 100.0, 0.0);
    let xs: Vec<f64> = f.iter().flat_map(|(l, _)| metres(l, 43.73)).map(|p| p.0).collect();
    let (lo, hi) = xs.iter().fold((f64::MAX, f64::MIN), |(a, b), x| (a.min(*x), b.max(*x)));
    assert!(f.len() == shp.len() && f.iter().all(|(_, w)| *w == strokes::SHAFT || *w == strokes::FILL) && ((lo + hi) / 2.0 - 100.0).abs() < 0.5);
    // a quarter circle of radius 50 m: every stroke point is within the lane of the curve
    let r = 50.0;
    let arc: Line = (0..=40).map(|i| {
        let t = i as f64 * std::f64::consts::PI / 2.0 / 40.0;
        [7.42 + r * t.sin() / (111320.0 * 43.73f64.to_radians().cos()), 43.73 + r * (1.0 - t.cos()) / 110540.0]
    }).collect();
    let f = strokes::place(&shp, &arc, 40.0, 0.0);
    for (l, _) in &f {
        for (x, y) in metres(l, 43.73) {
            assert!((x.hypot(y - r) - r).abs() < 1.7);
        }
    }
    assert!(f.iter().flat_map(|(l, _)| metres(l, 43.73)).any(|p| p.1 > 10.0));
}

#[test]
fn dashes_are_fixed_pieces_in_metres_and_marks_have_fixed_places() {
    let east = vec![[7.42, 43.73], [7.43, 43.73]];
    let d = strokes::dashes(&east, 3.0, 9.0, 0.2, 0.0);
    assert!((d.len() as f64 - strokes::length_m(&east) / 12.0).abs() <= 1.0);
    let x: Vec<f64> = d[..3].iter().map(|l| metres(l, 43.73)[0].0).collect();
    let first = metres(&d[0], 43.73);
    assert!((x[1] - x[0] - 12.0).abs() < 0.2 && (first[first.len() - 1].0 - first[0].0 - 3.0).abs() < 0.1);
    assert_eq!(strokes::positions(100.0, 90.0, 0.0, 0.0), vec![90.0]);
    assert_eq!(strokes::positions(100.0, 10.0, 30.0, 10.0), vec![10.0, 40.0, 70.0]);
}

#[test]
fn an_offset_is_to_the_right_as_roadstyles() {
    let east = vec![[7.42, 43.73], [7.43, 43.73]];
    let f = strokes::place(&vec![(vec![[-0.5, 0.0], [0.5, 0.0]], 0.2)], &east, 100.0, 2.0);
    assert!(f[0].0.iter().all(|p| p[1] < 43.73));
}

fn lane(id: &str, link: i64, use_: &str, line: Line) -> Lane {
    Lane { lane_id: id.into(), link_id: Some(link), use_: Some(use_.into()), width_m: Some(3.25), geometry: line, ..Lane::default() }
}

fn points(fc: Option<Value>) -> usize {
    fc.map_or(0, |f| f["features"].as_array().unwrap().iter().map(|x| x["geometry"]["coordinates"].as_array().unwrap().len()).sum())
}

#[test]
fn a_shared_bus_and_bike_lane_has_both_marks() {
    let parts = |u: &str| {
        let l = lane("1_1", 1, u, vec![[7.42, 43.73], [7.4215, 43.73]]);
        points(arrows::mark_strokes(&[&l], &[], &json!({"end_m": 10, "repeat_m": 60}), &[0.0], "#ffffff").unwrap())
    };
    assert_eq!(parts("bus,bike"), parts("bus") + parts("bike"));
}

#[test]
fn a_forking_lane_gets_the_arrow_its_movement_codes_say() {
    let m = 1.0 / 111320.0;
    let l = lane("1_1", 1, "auto", vec![[18.0, 59.0], [18.0, 59.0 + 40.0 * m]]);
    let n = |a: Option<&str>, b: Option<&str>| {
        let t = [("2_1", a), ("3_1", b)].map(|(to, turn)| Turn { from_lane: "1_1".into(), to_lane: to.into(), type_: Some("diverge".into()),
                                                                  turn: turn.map(String::from), walkers: None });
        points(arrows::mark_strokes(&[&l], &t, &json!({"length_m": 8, "end_m": 10, "repeat_m": 0}), &[0.0], "#ffffff").unwrap())
    };
    let plain = n(None, None);
    assert!(plain > 0 && n(Some("thru"), Some("left")) > plain && n(Some("thru"), Some("thru")) == plain);
}

#[test]
fn a_painted_zebra_is_white_strokes_along_the_road_from_zoom_17() {
    let k = 111320.0 * 59.3f64.to_radians().cos();
    let g = Lane { lane_id: "1_1".into(), link_id: Some(7), geometry: vec![[18.0, 59.3], [18.001, 59.3]], ..Lane::default() };
    let (x0, y0) = (18.0005, 59.3 - 3.0 / 111320.0);
    let rect = format!("POLYGON(({x0} {y0}, {x0} {}, {} {}, {} {y0}, {x0} {y0}))", y0 + 6.0 / 111320.0, x0 + 4.0 / k, y0 + 6.0 / 111320.0, x0 + 4.0 / k);
    let cr = vec![Crossing { crossing_id: "1".into(), lane_id: "1_1".into(), across_from: Some(0.0), across_to: Some(6.0), painted: Some(true),
                             cgeom: Some(rect), ..Crossing::default() }];
    let st = json!({"stripe_m": 0.5, "gap_m": 0.5, "minzoom": 17});
    let fc = items::zebra_strokes(&[&g], Some(&cr), &st, &json!("#ffffff")).unwrap();
    let fs = fc["features"].as_array().unwrap();
    assert!(fs.len() == 6 && fs.iter().all(|f| f["properties"]["edge_id"] == 7 && f["properties"]["order"] == items::ZEBRA && f["properties"]["minzoom"] == 17.0));
    let c = &fs[0]["geometry"]["coordinates"];
    let (ax, ay, bx, by) = (c[0][0].as_f64().unwrap(), c[0][1].as_f64().unwrap(), c[1][0].as_f64().unwrap(), c[1][1].as_f64().unwrap());
    assert!(((bx - ax) * k - 4.0).abs() < 0.05 && (by - ay).abs() * 111320.0 < 0.05);
    let unpainted = vec![Crossing { painted: Some(false), ..cr[0].clone() }];
    assert!(items::zebra_strokes(&[&g], Some(&unpainted), &st, &json!("#ffffff")).is_none());
}

fn tags(t: Value) -> Map<String, Value> {
    t.as_object().unwrap().clone()
}

#[test]
fn sidewalks_come_from_the_ways_tags_only_on_their_side() {
    assert_eq!(items::sidewalk_sides(Some(&tags(json!({"sidewalk": "both"}))), 2.0), vec![("left", 2.0), ("right", 2.0)]);
    assert_eq!(items::sidewalk_sides(Some(&tags(json!({"sidewalk": "right", "sidewalk:right:width": "3.5"}))), 2.0), vec![("right", 3.5)]);
    assert_eq!(items::sidewalk_sides(Some(&tags(json!({"sidewalk:left": "yes", "sidewalk:right": "separate"}))), 2.0), vec![("left", 2.0)]);
    for t in [json!({"sidewalk": "separate"}), json!({"sidewalk": "no"}), json!({"sidewalk": "yes"}), json!({})] {
        assert!(items::sidewalk_sides(Some(&tags(t)), 2.0).is_empty());
    }
    let ln = vec![[18.0, 59.3], [18.001, 59.3]];
    for (r, sign) in [("9#1f", 1.0), ("9#1r", -1.0)] {
        let g = Lane { link_id: Some(5), osm_id: Some(9), edge_ref: Some(r.into()), geometry: ln.clone(), ..Lane::default() };
        let fc = items::sidewalk_strokes(&[&g], &BTreeMap::from([(5, 5)]), &HashMap::from([("5".to_string(), ln.clone())]),
                                         &HashMap::from([("5".to_string(), 8.0)]), &HashMap::from([(9, tags(json!({"sidewalk": "right"})))]),
                                         &json!({"width_m": 2.0, "minzoom": 17}), &json!("#f0cb8c")).unwrap();
        let p = &fc["features"][0]["properties"];
        assert!(fc["features"].as_array().unwrap().len() == 1 && p["offset_m"] == sign * 5.0 && p["width_m"] == 2.0 && p["minzoom"] == 17.0);
    }
}

#[test]
fn roads_that_meet_end_at_exactly_the_same_point() {
    let out = items::snap_ends(&[vec![[0.0, 0.0], [5.0, 0.0], [10.0, 0.0001]], vec![[10.0003, 0.0], [20.0, 5.0]]], &[(1, 2), (2, 3)], &[0.0, 0.0]);
    assert_eq!(out[0][2], out[1][0]);
    assert!(out[0][0] == [0.0, 0.0] && out[0][1] == [5.0, 0.0] && (out[0][2][0] - 10.00015).abs() < 1e-9);
}

#[test]
fn the_widest_road_decides_where_roads_meet_and_a_narrower_one_gets_a_hook() {
    let (a, b) = (vec![[0.0, 0.0], [10.0, 0.0]], vec![[10.2, 0.1], [20.0, 0.0]]);
    let w = [6.78, 6.78, 3.53];
    let mid = [10.1, 0.05];
    let out = items::snap_ends(&[a.clone(), b.clone(), vec![[10.0, 5.0], [10.0, 1.6]]], &[(1, 2), (2, 3), (4, 2)], &w);
    assert!(out[0][1] == mid && out[1][0] == mid && out[0][0] == [0.0, 0.0]);
    assert!(out[2].len() == 3 && out[2][2] == mid && out[2][1] == [10.0, 1.6]);
    let out = items::snap_ends(&[a.clone(), b.clone(), vec![[10.0, 1.6], [10.0, 5.0]]], &[(1, 2), (2, 3), (2, 4)], &w);
    assert!(out[2][0] == mid && out[2][1] == [10.0, 1.6] && out[2][2] == [10.0, 5.0]);
    let out = items::snap_ends(&[a, b, vec![[10.0, 30.0], [10.0, 8.0]]], &[(1, 2), (2, 3), (4, 2)], &w);
    assert!(out[2].len() == 2 && out[2][1] == out[0][1]);          // too far from the wide road: the mean of all the ends
}

#[test]
fn lane_lines_run_on_only_where_a_road_goes_on() {
    let l: Vec<Line> = vec![vec![[0.0, 0.0], [100.0, 0.0]], vec![[100.0, 0.0], [100.0, 100.0]], vec![[100.0, 100.0], [200.0, 100.0]], vec![[100.0, 100.0], [0.0, 100.0]]];
    let ext = items::ends(&l, &[(10, 20), (20, 30), (30, 40), (30, 50)], &[1, 2, 3, 4]);
    assert!(ext.contains(&(1, 20)) && ext.contains(&(2, 20)) && !ext.contains(&(2, 30)) && !ext.contains(&(1, 10)));
}

#[test]
fn a_road_is_a_carriageway_whose_line_is_the_middle_of_its_outer_lane_edges() {
    let m = 1.0 / 111320.0;
    let y0 = 43.73;
    let ln = |dy: f64| vec![[7.42, y0 + dy * m], [7.4205, y0 + dy * m]];
    let mk = |n, w, dy| Lane { link_id: Some(1), lane_num: Some(n), width_m: Some(w), from_node_id: Some(10), to_node_id: Some(20), geometry: ln(dy), ..Lane::default() };
    let (a, b) = (mk(-1, 1.5, 0.75), mk(1, 3.25, -1.625));
    let r = items::link_roads(&[&a, &b], 0.14, 0.15);
    let ys: Vec<f64> = r.roads[0].2.iter().map(|c| (c[1] - y0) / m).collect();
    assert!((ys.iter().sum::<f64>() / ys.len() as f64 + 0.875).abs() < 0.05);
    assert!((r.roads[0].1 - (1.5 + 3.25 + 0.28)).abs() < 1e-9);        // the lanes and the casing on each side; one direction: no centre line
}

#[test]
fn default_widths_by_use() {
    let s = settings::lane_settings(None).unwrap();
    let w = |own, u, n, lanes| settings::width(&s, own, u, n, lanes, true);
    assert_eq!([w(None, "auto", Some(1), Some(2)), w(None, "walk", Some(1), None), w(None, "bike", Some(2), Some(1)), w(None, "bike", Some(1), Some(2)),
                w(None, "bike", Some(1), None), w(Some(2.5), "walk", Some(1), Some(1))], [3.25, 2.0, 1.5, 3.25, 1.5, 2.5]);
    let s2 = settings::lane_settings(Some(&json!({"lanes": {"width_m_by_use": {"walk": 1.2}}}))).unwrap();
    assert_eq!(settings::width(&s2, None, "walk", Some(1), None, true), 1.2);
    assert_eq!(settings::width(&s, None, "bike", Some(2), Some(1), false), 3.25);     // without lane_num / lanes: the default
}

#[test]
fn a_road_without_lanes_is_its_width_tag_else_its_class_width() {
    let t = tags(json!({"footway": 2.0, "steps": 2.0, "default": 1.0}));
    let got: Vec<(f64, Option<String>)> = [("footway", None), ("steps", Some("2.5 m")), ("corridor", None), ("footway", Some("3,5")), ("footway", Some("8'"))]
        .iter().map(|(h, w)| settings::path_width(Some(h), *w, &t)).collect();
    assert_eq!(got.iter().map(|x| x.0).collect::<Vec<_>>(), vec![2.0, 2.5, 1.0, 3.5, 2.0]);
    assert_eq!(got.iter().filter_map(|x| x.1.clone()).collect::<Vec<_>>(), vec!["8'".to_string()]);
}

#[test]
fn a_link_with_no_road_class_is_not_drawn() {
    let s = settings::lane_settings(None).unwrap();
    let mut a = lane("1_1", 1, "auto", vec![[18.0, 59.3], [18.001, 59.3]]);
    a.highway = Some("residential".into());
    let ferry = Lane { highway: None, ..lane("5_1", 5, "walk", vec![[18.0, 59.31], [18.001, 59.31]]) };
    let t = Lanes { rows: vec![a, ferry], columns: ["lane_id", "highway", "link_id", "use", "width_m"].map(String::from).to_vec(), crossings: None };
    let st = editor::strokes(&t, &[], &s, false, &None).unwrap();
    let ids: Vec<&str> = st.lanes.as_ref().unwrap()["features"].as_array().unwrap().iter().map(|f| f["properties"]["lane_id"].as_str().unwrap()).collect();
    assert_eq!(ids, vec!["1_1"]);
}

#[test]
fn lanes_and_lines_are_line_items_with_the_centre_line_between_the_directions() {
    // 2 car lanes one way, a bus/bike lane the other (Boulevard Charles III)
    let (m, kx) = (1.0 / 111320.0, 1.0 / (111320.0 * 0.7225));
    let line = |x0: f64, x1: f64, y: f64| vec![[7.4 + x0 * kx, 43.73 + y * m], [7.4 + x1 * kx, 43.73 + y * m]];
    let mk = |id: &str, link, rev, n, from, to, u: &str, l| Lane { lane_id: id.into(), link_id: Some(link), reverse_link_id: Some(rev), lane_num: Some(n),
        width_m: Some(3.25), from_node_id: Some(from), to_node_id: Some(to), highway: Some("primary".into()), use_: Some(u.into()), geometry: l, ..Lane::default() };
    let g = [mk("1_1", 1, 2, 1, 10, 20, "auto", line(0.0, 100.0, -1.625)), mk("1_2", 1, 2, 2, 10, 20, "auto", line(0.0, 100.0, -4.875)),
             mk("2_1", 2, 1, 1, 20, 10, "bus,bike", line(100.0, 0.0, 1.625))];
    let g: Vec<&Lane> = g.iter().collect();
    let roads = items::link_roads(&g, 0.14, 0.15);
    assert!((roads.roads[0].1 - (3.0 * 3.25 + 0.15 + 0.28)).abs() < 1e-9);
    let set = json!({"divider": true, "centre": true, "width_m": 0.15, "dash_m": 3, "gap_m": 9, "color": "#f2f2f2"});
    let (lanes, lines) = items::lane_strokes(&g, &vec!["#aaa".to_string(); 3], &roads.road_of, 0.15, &set, 1.0, &roads.ext, false, &|_| true).unwrap();
    for f in lanes.unwrap()["features"].as_array().unwrap() {
        assert!(f["geometry"]["type"] == "LineString" && f["properties"]["width_m"] == 3.25 && f["properties"]["offset_m"] == 0.075);
    }
    let lines = lines.unwrap();
    let by: HashMap<&str, &Value> = lines["features"].as_array().unwrap().iter().map(|f| (f["properties"]["t"].as_str().unwrap(), f)).collect();
    assert_eq!(by.len(), 2);
    assert!(by["divider"]["geometry"]["type"] == "MultiLineString" && by["divider"]["geometry"]["coordinates"].as_array().unwrap().len() == 8);
    let c = &by["centre"]["properties"];
    assert!(c["width_m"] == 0.15 && c["offset_m"] == -1.625 && c["edge_id"] == 1 && c["order"] == items::LINE);
}
