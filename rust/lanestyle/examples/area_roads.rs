//! Write the level editor's road table of a level area (lanestyle::page::area_draw) to a GeoParquet file: the input of the golden files.
//!
//!     cargo run --release -p lanestyle --features page --example area_roads -- AREA.levels OUT.parquet
fn main() {
    let a: Vec<String> = std::env::args().skip(1).collect();
    let bytes = lanestyle::page::area_draw(std::path::Path::new(&a[0])).expect("area_draw");
    std::fs::write(&a[1], bytes).expect("write");
}
