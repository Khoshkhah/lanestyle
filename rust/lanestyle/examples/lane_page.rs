//! Write the lane page of a level area (lanestyle::page::lane_page), as Python's `lane_page.py`. LANE_PAGE_KW: render keywords (JSON).
//!
//!     cargo run --release -p lanestyle --features page --example lane_page -- AREA GMNS_DB SOURCE_DB OUT.html [--connectors]
fn main() {
    let a: Vec<String> = std::env::args().skip(1).collect();
    if a.len() < 4 {
        eprintln!("usage: lane_page AREA GMNS_DB SOURCE_DB OUT.html [--connectors]");
        std::process::exit(2);
    }
    let t = std::time::Instant::now();
    let (html, notes) = lanestyle::page::lane_page(std::path::Path::new(&a[0]), &a[1], &a[2], a.iter().any(|x| x == "--connectors"),
                                                   std::env::var("LANE_PAGE_KW").ok().map(|k| serde_json::from_str(&k).expect("LANE_PAGE_KW: JSON")).unwrap_or_default()).unwrap_or_else(|e| { eprintln!("{e}"); std::process::exit(1) });
    for n in notes {
        eprintln!("{n}");
    }
    std::fs::write(&a[3], html).expect("write");
    println!("wrote {} ({:.1} s)", a[3], t.elapsed().as_secs_f64());
}
