//! The lane table and the turns: what the GMNS reader gives (Python's `from_gmns`: a GeoDataFrame and a DataFrame) and what the items
//! are made from.

use crate::geo::Line;
use serde_json::{json, Value};

/// One lane, or one lane connector (`connector`), of the lane table. A field is None where Python's column is null or not there.
#[derive(Clone, Debug, Default)]
pub struct Lane {
    pub lane_id: String,
    /// the link's facility_type
    pub highway: Option<String>,
    pub width_m: Option<f64>,
    pub use_: Option<String>,
    /// lane 1 only: one label for each road
    pub name: Option<String>,
    pub link_id: Option<i64>,
    pub lane_num: Option<i64>,
    /// the link's lane count
    pub lanes: Option<i64>,
    pub turn: Option<String>,
    pub from_node_id: Option<i64>,
    pub to_node_id: Option<i64>,
    pub reverse_link_id: Option<i64>,
    pub bridge: Option<String>,
    pub tunnel: Option<String>,
    pub layer: Option<String>,
    pub osm_id: Option<i64>,
    pub footway: Option<String>,
    pub crossing: Option<String>,
    pub crossing_markings: Option<String>,
    pub along_link_id: Option<i64>,
    pub along_kind: Option<String>,
    pub edge_ref: Option<String>,
    pub roundabout: bool,
    pub along_links: Option<Vec<i64>>,
    pub connector: bool,
    pub from_lane: Option<String>,
    pub to_lane: Option<String>,
    /// the modes that have the link ("driving,walking"), with several modes read
    pub modes: Option<String>,
    /// duckOSM's line to the nodes, in the direction of travel (lon/lat)
    pub geometry: Line,
    pub full_geometry: Option<Line>,
    /// where SUMO ends the lane at its junction
    pub cut_geometry: Option<Line>,
}

/// One turn: a lane into a lane, with the movement's type and, for a fork's branch, its turn (left, thru, right).
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Turn {
    pub from_lane: String,
    pub to_lane: String,
    pub type_: Option<String>,
    pub turn: Option<String>,
    /// several modes: a later mode's walkers stepping off an earlier mode's lane (no turn of that lane)
    pub walkers: Option<bool>,
}

/// One painted crossing over one lane (duckOSM's gmns_driving.crossing and lane_crossing).
#[derive(Clone, Debug, Default)]
pub struct Crossing {
    pub crossing_id: String,
    pub lane_id: String,
    pub start_lr: Option<f64>,
    pub end_lr: Option<f64>,
    pub across_from: Option<f64>,
    pub across_to: Option<f64>,
    pub to_left: Option<bool>,
    pub painted: Option<bool>,
    pub length: Option<f64>,
    pub crossing_type: Option<String>,
    pub source: Option<String>,
    /// the crossing's rectangle, lon/lat WKT
    pub cgeom: Option<String>,
}

/// The lane table: the lanes in their order, the names of the columns Python's table has (its order), and the crossings.
#[derive(Clone, Debug, Default)]
pub struct Lanes {
    pub rows: Vec<Lane>,
    pub columns: Vec<String>,
    pub crossings: Option<Vec<Crossing>>,
}

impl Lanes {
    pub fn has(&self, c: &str) -> bool {
        self.columns.iter().any(|x| x == c)
    }
}

fn line_json(l: &Option<Line>) -> Value {
    l.as_ref().map_or(Value::Null, |l| json!({"type": "LineString", "coordinates": l}))
}

impl Lane {
    /// The value of column `c` as JSON (a line as GeoJSON): the Python binding's table.
    pub fn get(&self, c: &str) -> Value {
        match c {
            "lane_id" => json!(self.lane_id),
            "highway" => json!(self.highway),
            "width_m" => json!(self.width_m),
            "use" => json!(self.use_),
            "name" => json!(self.name),
            "link_id" => json!(self.link_id),
            "lane_num" => json!(self.lane_num),
            "lanes" => json!(self.lanes),
            "turn" => json!(self.turn),
            "from_node_id" => json!(self.from_node_id),
            "to_node_id" => json!(self.to_node_id),
            "reverse_link_id" => json!(self.reverse_link_id),
            "bridge" => json!(self.bridge),
            "tunnel" => json!(self.tunnel),
            "layer" => json!(self.layer),
            "osm_id" => json!(self.osm_id),
            "footway" => json!(self.footway),
            "crossing" => json!(self.crossing),
            "crossing_markings" => json!(self.crossing_markings),
            "along_link_id" => json!(self.along_link_id),
            "along_kind" => json!(self.along_kind),
            "edge_ref" => json!(self.edge_ref),
            "roundabout" => json!(self.roundabout),
            "along_links" => json!(self.along_links),
            "connector" => json!(self.connector),
            "from_lane" => json!(self.from_lane),
            "to_lane" => json!(self.to_lane),
            "modes" => json!(self.modes),
            "geometry" => line_json(&Some(self.geometry.clone())),
            "full_geometry" => line_json(&self.full_geometry),
            "cut_geometry" => line_json(&self.cut_geometry),
            _ => Value::Null,
        }
    }
}
