//! Write the lane page of a SUMO net (lanestyle::page::sumo_page). LANE_PAGE_KW: render keywords (JSON).
//!
//!     cargo run --release -p lanestyle --features page --example sumo_page -- NET.net.xml OUT.html
fn main() {
    let a: Vec<String> = std::env::args().skip(1).collect();
    if a.len() < 2 {
        eprintln!("usage: sumo_page NET.net.xml OUT.html");
        std::process::exit(2);
    }
    let xml = std::fs::read_to_string(&a[0]).unwrap_or_else(|e| { eprintln!("{}: {e}", a[0]); std::process::exit(1) });
    let kw = std::env::var("LANE_PAGE_KW").ok().map(|k| serde_json::from_str(&k).expect("LANE_PAGE_KW: JSON")).unwrap_or_default();
    let (html, notes) = lanestyle::page::sumo_page(&xml, kw).unwrap_or_else(|e| { eprintln!("{e}"); std::process::exit(1) });
    for n in notes {
        eprintln!("{n}");
    }
    std::fs::write(&a[1], html).expect("write");
    println!("wrote {}", a[1]);
}
