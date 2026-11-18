//! Painted lane markings as line strokes: white, flat on the lane, sized in metres.
//!
//! A shape is a list of (polyline, stroke width m) in a local frame: u forward along the lane, v to the left, (0, 0) the centre of the
//! mark. `shape(name, lane_width)` makes one, `place(shape, line, at_m, offset_m)` puts it on a line as lon/lat polylines, each with its
//! `width_m`.

use crate::geo::{self, Aeqd, Line, P};
use std::f64::consts::PI;

pub const ARROWS: [&str; 8] = ["thru", "left", "right", "uturn", "left+thru", "thru+right", "left+right", "left+thru+right"];
/// arrow length, m
pub const LENGTH: f64 = 7.0;
/// an arrow's shaft and branches, m
pub const SHAFT: f64 = 0.3;
/// the thin strokes that fill an arrow's head solid, m
pub const FILL: f64 = 0.1;

pub type Shape = Vec<(Vec<P>, f64)>;

/// A solid triangular head with its point at `tip`, pointing at angle `ang` (0 = forward, 90 = left): a fan of thin strokes.
fn head(tip: P, ang: f64, k: f64, hl: f64, hb: f64) -> Vec<Vec<P>> {
    let (a, hl, hb) = (ang.to_radians(), hl * k, hb * k);
    let (ux, uy, nx, ny) = (a.cos(), a.sin(), -a.sin(), a.cos());
    let (bx, by) = (tip[0] - hl * ux, tip[1] - hl * uy);
    let n = 4.max((2.0 * hb / (FILL * 0.6)) as i64);
    (0..=n)
        .map(|i| {
            let t = 2.0 * i as f64 / n as f64 - 1.0;
            vec![[bx + nx * hb * t, by + ny * hb * t], tip]
        })
        .collect()
}

/// A smooth turn: an arc of radius `r` from `p0` heading `ang0` to heading `ang1` (degrees, left positive).
fn bend(p0: P, ang0: f64, ang1: f64, r: f64, steps: usize) -> Vec<P> {
    let (a0, a1) = (ang0.to_radians(), ang1.to_radians());
    let s = if a1 > a0 { 1.0 } else { -1.0 };
    let (cx, cy) = (p0[0] - s * r * a0.sin(), p0[1] + s * r * a0.cos());
    (0..=steps)
        .map(|i| {
            let a = a0 + (a1 - a0) * i as f64 / steps as f64;
            [cx + s * r * a.sin(), cy - s * r * a.cos()]
        })
        .collect()
}

/// A painted lane arrow of `moves` (left, thru, right, uturn): the shaft and branches at SHAFT, the heads' fill at FILL.
fn arrow(moves: &[&str], w: f64) -> Shape {
    let has = |m: &str| moves.contains(&m);
    let single = moves == ["left"] || moves == ["right"];
    let (k, l) = (1.0f64.min(w / 3.25), LENGTH);
    let hd = 1.8 * k;
    let (mut thick, mut fill): (Vec<Vec<P>>, Vec<Vec<P>>) = (Vec::new(), Vec::new());
    if moves == ["uturn"] {
        let r = (0.3 * w).min(w / 2.0 - 0.75 * k - 0.15);
        let mut hook = vec![[-l / 2.0 + hd, -r], [0.6, -r]];
        hook.extend(bend([0.6, -r], 0.0, 180.0, r, 12).into_iter().skip(1));
        hook.push([-0.6 + hd, r]);
        thick.push(hook);
        fill.extend(head([-0.6, r], 180.0, k, 1.8, 0.55));
    } else {
        if single {
            thick.push(vec![[-l / 2.0, 0.0], [0.2, 0.0]]);
        } else if has("thru") {
            thick.push(vec![[-l / 2.0, 0.0], [l / 2.0 - hd, 0.0]]);
            fill.extend(head([l / 2.0, 0.0], 0.0, k, 1.8, 0.55));
        } else {
            thick.push(vec![[-l / 2.0, 0.0], [-0.4, 0.0]]);
        }
        for (sgn, on) in [(1.0, has("left")), (-1.0, has("right"))] {
            if on {
                let u0 = if single { 0.0 } else { -1.2 };
                let mut arc = bend([u0, 0.0], 0.0, 45.0 * sgn, 1.0 * k, 8);
                let c45 = 45f64.to_radians().cos();
                let last = arc[arc.len() - 1];
                let end = [last[0] + 0.5 * k * c45, last[1] + sgn * 0.5 * k * c45];
                arc.push(end);
                thick.push(arc);
                fill.extend(head([end[0] + 1.2 * k * c45, end[1] + sgn * 1.2 * k * c45], 45.0 * sgn, k, 1.2, 0.4));
            }
        }
    }
    thick.into_iter().map(|p| (p, SHAFT)).chain(fill.into_iter().map(|p| (p, FILL))).collect()
}

/// letters in a unit box, x right and y up as the driver reads them
fn letter(ch: char) -> Vec<Vec<P>> {
    let b = vec![[0.0, 0.0], [0.0, 1.0], [0.7, 1.0], [0.95, 0.9], [1.0, 0.75], [0.95, 0.6], [0.7, 0.52], [0.0, 0.52]];
    match ch {
        'B' => vec![b, vec![[0.7, 0.52], [0.95, 0.42], [1.0, 0.25], [0.95, 0.1], [0.7, 0.0], [0.0, 0.0]]],
        'U' => vec![vec![[0.0, 1.0], [0.0, 0.2], [0.15, 0.04], [0.5, 0.0], [0.85, 0.04], [1.0, 0.2], [1.0, 1.0]]],
        _ => vec![vec![[1.0, 0.85], [0.85, 0.97], [0.5, 1.0], [0.15, 0.97], [0.0, 0.82], [0.05, 0.65], [0.5, 0.5], [0.95, 0.35],
                       [1.0, 0.18], [0.85, 0.03], [0.5, 0.0], [0.15, 0.03], [0.0, 0.15]]],
    }
}

/// BUS painted as on the road: letters upright for the driver, stretched along the lane, B farthest.
fn bus(w: f64) -> Shape {
    let (wl, h, gap) = (0.55 * w, 1.8, 0.4);
    let top = (3.0 * h + 2.0 * gap) / 2.0;
    let mut out = Vec::new();
    for (i, ch) in "BUS".chars().enumerate() {
        let u0 = top - h - i as f64 * (h + gap);
        out.extend(letter(ch).into_iter().map(|p| (p.iter().map(|&[x, y]| [u0 + y * h, (0.5 - x) * wl]).collect(), 0.25)));
    }
    out
}

fn circle(c: P, r: f64, n: usize) -> Vec<P> {
    (0..=n).map(|i| {
        let a = 2.0 * PI * i as f64 / n as f64;
        [c[0] + r * a.cos(), c[1] + r * a.sin()]
    }).collect()
}

/// A bike seen from the side, pointing forward, its top to the left: 1.6 m long.
fn bike() -> Shape {
    let d = -0.1;
    let p = |u: f64, v: f64| [u, v + d];
    let r = 0.3;
    let parts = vec![
        circle(p(-0.5, 0.0), r, 14),
        circle(p(0.5, 0.0), r, 14),
        vec![p(-0.5, 0.0), p(-0.1, 0.0), p(0.3, 0.4), p(-0.2, 0.4), p(-0.1, 0.0)],
        vec![p(0.3, 0.4), p(0.5, 0.0)],
        vec![p(0.3, 0.4), p(0.25, 0.52), p(0.4, 0.52)],
        vec![p(-0.2, 0.4), p(-0.22, 0.5)],
        vec![p(-0.35, 0.5), p(-0.1, 0.5)],
    ];
    parts.into_iter().map(|q| (q, 0.12)).collect()
}

/// The mark `name` ("thru", "left", ..., "bus", "bike") scaled to a lane `lane_width` m wide; an error for an unknown name.
pub fn shape(name: &str, lane_width: f64) -> Result<Shape, String> {
    match name {
        "bus" => Ok(bus(lane_width)),
        "bike" => Ok(bike()),
        _ if ARROWS.contains(&name) => {
            let mut moves: Vec<&str> = name.split('+').collect();
            moves.sort();
            moves.dedup();
            // the set of moves, in a fixed order (Python's set); arrow only asks what is in it
            Ok(arrow(&moves, lane_width))
        }
        _ => Err(format!("unknown mark {name:?}")),
    }
}

/// `shp` centred `at_m` metres along `lane_line` (lon/lat), bent with the line: a point (u, v) goes u metres on along the line and v
/// metres to its left; `offset_m` moves the mark that far to the RIGHT of the line (roadstyle's item offsets). Each stroke as a lon/lat
/// polyline with its width.
pub fn place(shp: &Shape, lane_line: &[P], at_m: f64, offset_m: f64) -> Vec<(Line, f64)> {
    let pr = Aeqd::new(lane_line[0]);
    let line = pr.fwd_line(lane_line);
    let n = geo::length(&line);
    let at = |u: f64, v: f64| -> P {
        let s = (at_m + u).max(0.0).min(n);
        let (a, b) = (geo::interpolate(&line, (s - 0.25).max(0.0)), geo::interpolate(&line, (s + 0.25).min(n)));
        let (tx, ty) = (b[0] - a[0], b[1] - a[1]);
        let h = tx.hypot(ty);
        let h = if h == 0.0 { 1.0 } else { h };
        let c = geo::interpolate(&line, s);
        [c[0] - v * ty / h, c[1] + v * tx / h]
    };
    shp.iter()
        .map(|(pts, w)| {
            let mut dense = Vec::new();
            for q in pts.windows(2) {
                let ([u0, v0], [u1, v1]) = (q[0], q[1]);
                let m = 1.max(((u1 - u0).hypot(v1 - v0) / 0.5).ceil() as i64);
                dense.extend((0..m).map(|i| [u0 + (u1 - u0) * i as f64 / m as f64, v0 + (v1 - v0) * i as f64 / m as f64]));
            }
            dense.push(pts[pts.len() - 1]);
            (dense.iter().map(|&[u, v]| pr.inv(at(u, v - offset_m))).collect(), *w)
        })
        .collect()
}

/// The length of a lon/lat line in metres.
pub fn length_m(lane_line: &[P]) -> f64 {
    geo::length(&Aeqd::new(lane_line[0]).fwd_line(lane_line))
}

/// A dashed line as real pieces: `dash_m` long, `gap_m` apart, fixed in metres along the line; each piece a lon/lat polyline.
pub fn dashes(lane_line: &[P], dash_m: f64, gap_m: f64, width_m: f64, offset_m: f64) -> Vec<Line> {
    let (n, mut out, mut s) = (length_m(lane_line), Vec::new(), 0.0);
    while s + dash_m <= n + 1e-9 {
        out.extend(place(&vec![(vec![[-dash_m / 2.0, 0.0], [dash_m / 2.0, 0.0]], width_m)], lane_line, s + dash_m / 2.0, offset_m)
            .into_iter().map(|(l, _)| l));
        s += dash_m + gap_m;
    }
    out
}

/// Fixed places (metres along a lane) for a mark: `first_m`, then every `every_m` (0: only the first), all at least `last_m` clear of
/// the lane's end.
pub fn positions(length: f64, first_m: f64, every_m: f64, last_m: f64) -> Vec<f64> {
    let end = length - last_m;
    let (mut out, mut s) = (Vec::new(), first_m);
    while s <= end + 1e-9 {
        out.push(s);
        if every_m == 0.0 {
            break;
        }
        s += every_m;
    }
    out
}
