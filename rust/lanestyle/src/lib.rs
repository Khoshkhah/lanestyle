//! lanestyle: lane-level maps on roadstyle. roadstyle draws every road; lanestyle gives the road's own items from duckOSM's GMNS lanes
//! (lanes, lane lines, arrows, BUS and bike marks, zebras, sidewalks). The Python package `lanestyle` is a binding of this crate.
//!
//! The rules (`lanes`, `items`, `arrows`, `strokes`, `editor`, `settings`, `geo`) are pure Rust and build for WebAssembly. The GMNS
//! reader (`gmns`, the feature `duckdb`) reads the files with DuckDB; the SUMO reader (`sumo`) reads a SUMO `.net.xml`; the lane page (`page`, the feature `page`) draws with roadstyle.

pub mod arrows;
pub mod editor;
pub mod geo;
#[cfg(feature = "duckdb")]
pub mod gmns;
pub mod items;
pub mod lanes;
#[cfg(feature = "page")]
pub mod page;
pub mod settings;
pub mod strokes;
pub mod sumo;
