//! The SUMO net reader on one Monaco junction (tests/data/monaco_junction.net.xml: `duckosm sumo` of tests/data/monaco.osm.pbf, the
//! edges and internal edges of junction 258071979).

use lanestyle::sumo::from_sumo_net;

#[test]
fn reads_one_monaco_junction() {
    let t = from_sumo_net(include_str!("data/monaco_junction.net.xml")).unwrap();
    assert_eq!(t.rows.len(), 15);
    let conn: Vec<_> = t.rows.iter().filter(|l| l.connector).collect();
    assert_eq!(conn.len(), 7);
    // an internal lane: no link, the class of the edge it leaves
    assert!(conn.iter().all(|l| l.link_id.is_none() && l.lane_id.starts_with(":258071979_") && l.highway.is_some()));
    // the bus lane: SUMO's edge id is duckOSM's edge_id; the point in lon/lat equals pyproj's to 1e-7 degrees
    let bus = t.rows.iter().find(|l| l.lane_id == "3188778506000426711_0").unwrap();
    assert_eq!(bus.link_id, Some(3188778506000426711));
    assert_eq!(bus.use_.as_deref(), Some("bus"));
    assert_eq!(bus.highway.as_deref(), Some("secondary"));
    assert_eq!(bus.width_m, Some(3.25));
    assert_eq!(bus.name.as_deref(), Some("Boulevard Princesse Charlotte"));
    let p = bus.geometry[0];
    assert!((p[0] - 7.425061623741259).abs() < 1e-7 && (p[1] - 43.74108566199951).abs() < 1e-7, "{p:?}");
    assert!(from_sumo_net("<net></net>").is_err());
}
