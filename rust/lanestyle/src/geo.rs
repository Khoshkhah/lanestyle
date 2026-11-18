//! The geometry of lanestyle, the same as Python's: shapely's (GEOS) line operations in the plane of the coordinates, the UTM zone of
//! geopandas' `estimate_utm_crs` both ways, and PROJ's `aeqd` (the marks, in metres around a lane's first point).

use geographiclib_rs::{DirectGeodesic, Geodesic, InverseGeodesic};

pub type P = [f64; 2];
pub type Line = Vec<P>;

fn dist(a: P, b: P) -> f64 {
    ((b[0] - a[0]).powi(2) + (b[1] - a[1]).powi(2)).sqrt()
}

/// The length of a line (GEOS: the sum of its segments).
pub fn length(l: &[P]) -> f64 {
    l.windows(2).map(|w| dist(w[0], w[1])).sum()
}

/// GEOS `pointAlongSegmentByFraction`.
fn along(p0: P, p1: P, f: f64) -> P {
    if f <= 0.0 {
        p0
    } else if f >= 1.0 {
        p1
    } else {
        [(p1[0] - p0[0]) * f + p0[0], (p1[1] - p0[1]) * f + p0[1]]
    }
}

/// shapely's `interpolate(d)` (GEOS LengthIndexedLine::extractPoint): the point `d` along the line; a negative `d` from its end.
pub fn interpolate(l: &[P], d: f64) -> P {
    let d = if d < 0.0 { length(l) + d } else { d };
    if d <= 0.0 {
        return l[0];
    }
    let mut total = 0.0;
    for w in l.windows(2) {
        let seg = dist(w[0], w[1]);
        if total + seg > d {
            return along(w[0], w[1], (d - total) / seg);
        }
        total += seg;
    }
    l[l.len() - 1]
}

/// shapely's `interpolate(d, normalized=True)`.
pub fn interpolate_n(l: &[P], d: f64) -> P {
    interpolate(l, d * length(l))
}

/// GEOS LineSegment::projectionFactor.
fn factor(a: P, b: P, p: P) -> f64 {
    if p == a {
        return 0.0;
    }
    if p == b {
        return 1.0;
    }
    let (dx, dy) = (b[0] - a[0], b[1] - a[1]);
    let len2 = dx * dx + dy * dy;
    ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2
}

/// GEOS Distance::pointToSegment.
fn seg_dist(p: P, a: P, b: P) -> f64 {
    if a == b {
        return dist(p, a);
    }
    let len2 = (b[0] - a[0]).powi(2) + (b[1] - a[1]).powi(2);
    let r = ((p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1])) / len2;
    if r <= 0.0 {
        return dist(p, a);
    }
    if r >= 1.0 {
        return dist(p, b);
    }
    let s = ((a[1] - p[1]) * (b[0] - a[0]) - (a[0] - p[0]) * (b[1] - a[1])) / len2;
    s.abs() * len2.sqrt()
}

/// shapely's `project(p)` (GEOS LengthIndexOfPoint): the distance along the line to its point closest to `p` (the first closest segment).
pub fn project(l: &[P], p: P) -> f64 {
    let (mut best, mut at, mut total) = (f64::MAX, 0.0, 0.0);
    for w in l.windows(2) {
        let seg = dist(w[0], w[1]);
        let d = seg_dist(p, w[0], w[1]);
        if d < best {
            best = d;
            let f = factor(w[0], w[1], p);
            let f = if f < 0.0 { 0.0 } else if f > 1.0 || f.is_nan() { 1.0 } else { f };
            at = total + f * seg;
        }
        total += seg;
    }
    at
}

/// shapely's `project(p, normalized=True)`.
pub fn project_n(l: &[P], p: P) -> f64 {
    project(l, p) / length(l)
}

/// shapely.ops.substring, for a line and two distances that are not equal and not both at or past one end (the cases that give a
/// point: None). `normalized`: the distances are fractions of the length.
pub fn substring(l: &[P], start: f64, end: f64, normalized: bool) -> Option<Line> {
    let len = length(l);
    if start == end
        || (!normalized && start >= len && end >= len)
        || (!normalized && -start >= len && -end >= len)
        || (normalized && start >= 1.0 && end >= 1.0)
        || (normalized && -start >= 1.0 && -end >= 1.0)
    {
        return None;
    }
    let (mut s, mut e) = if normalized { (start * len, end * len) } else { (start, end) };
    if (s < 0.0 && 0.0 < e && s.abs() + e == len) || (e < 0.0 && 0.0 < s && e.abs() + s == len) {
        return None;
    }
    let (sp, ep) = (interpolate(l, s), interpolate(l, e));
    if s < 0.0 {
        s += len;
    }
    if e < 0.0 {
        e += len;
    }
    let reverse = s > e;
    if reverse {
        std::mem::swap(&mut s, &mut e);
    }
    let s = s.max(0.0);
    let mut out = vec![if reverse { ep } else { sp }];
    let mut cur = 0.0;
    for w in l.windows(2) {
        if s < cur && cur < e {
            out.push(w[0]);
        } else if cur >= e {
            break;
        }
        cur += ((w[1][0] - w[0][0]).powi(2) + (w[1][1] - w[0][1]).powi(2)).powf(0.5);
    }
    out.push(if reverse { sp } else { ep });
    if reverse {
        out.reverse();
    }
    Some(out)
}

/// shapely's `simplify(tol)` of a line (GEOS TopologyPreservingSimplifier, TaggedLineStringSimplifier): Douglas-Peucker, the first
/// farthest point splits a section, and a section is not flattened when its new segment would cross the line (its other input segments,
/// or the flattened segments made before).
pub fn simplify(l: &[P], tol: f64) -> Line {
    struct S<'a> {
        l: &'a [P],
        tol: f64,
        input: Vec<bool>,        // segment k (l[k], l[k+1]) still in the input index
        output: Vec<(P, P)>,     // the flattened segments
        result: Vec<(P, P)>,
    }
    impl S<'_> {
        fn section(&mut self, i: usize, j: usize) {
            if i + 1 == j {
                self.result.push((self.l[i], self.l[j]));
                return;
            }
            let (mut far, mut at) = (-1.0, i);
            for k in i + 1..j {
                let d = seg_dist(self.l[k], self.l[i], self.l[j]);
                if d > far {
                    far = d;
                    at = k;
                }
            }
            let cand = (self.l[i], self.l[j]);
            let ok = far <= self.tol
                && !self.output.iter().any(|s| interior_intersection(*s, cand))
                && !(0..self.l.len() - 1).any(|k| self.input[k] && !(i..j).contains(&k) && interior_intersection((self.l[k], self.l[k + 1]), cand));
            if ok {
                self.output.push(cand);
                self.input[i..j].iter_mut().for_each(|x| *x = false);
                self.result.push(cand);
                return;
            }
            self.section(i, at);
            self.section(at, j);
        }
    }
    if l.len() < 3 {
        return l.to_vec();
    }
    let mut s = S { l, tol, input: vec![true; l.len() - 1], output: Vec::new(), result: Vec::new() };
    s.section(0, l.len() - 1);
    let mut out = vec![s.result[0].0];
    out.extend(s.result.iter().map(|x| x.1));
    out
}

// ---- GEOS's robust segment intersection (RobustLineIntersector with CGAlgorithmsDD's orientation) ----

/// A double-double number (GEOS's DD).
#[derive(Clone, Copy)]
struct Dd(f64, f64);

impl Dd {
    fn add(self, y: Dd) -> Dd {
        let (hi, lo) = (self.0, self.1);
        let s = hi + y.0;
        let t = lo + y.1;
        let mut e = s - hi;
        let f = t - lo;
        let mut s2 = s - e;
        let mut t2 = t - f;
        s2 = (y.0 - e) + (hi - s2);
        t2 = (y.1 - f) + (lo - t2);
        e = s2 + t;
        let h1 = s + e;
        let h = e + (s - h1);
        e = t2 + h;
        let zhi = h1 + e;
        Dd(zhi, e + (h1 - zhi))
    }
    fn neg(self) -> Dd {
        Dd(-self.0, -self.1)
    }
    fn mul(self, y: Dd) -> Dd {
        const SPLIT: f64 = 134_217_729.0;
        let (hi, lo) = (self.0, self.1);
        let mut c1 = SPLIT * hi;
        let mut hx = c1 - hi;
        let mut c = SPLIT * y.0;
        hx = c1 - hx;
        let tx = hi - hx;
        let mut hy = c - y.0;
        c1 = hi * y.0;
        hy = c - hy;
        let ty = y.0 - hy;
        c = ((((hx * hy - c1) + hx * ty) + tx * hy) + tx * ty) + (hi * y.1 + lo * y.0);
        let zhi = c1 + c;
        hx = c1 - zhi;
        Dd(zhi, c + hx)
    }
}

/// GEOS Orientation::index(p1, p2, q): 1 left, -1 right, 0 on the line.
fn orientation(p1: P, p2: P, q: P) -> i32 {
    let sign = |d: f64| if d > 0.0 { 1 } else if d < 0.0 { -1 } else { 0 };
    let detleft = (p1[0] - q[0]) * (p2[1] - q[1]);
    let detright = (p1[1] - q[1]) * (p2[0] - q[0]);
    let det = detleft - detright;
    let detsum = if detleft > 0.0 {
        if detright <= 0.0 { return sign(det) }
        detleft + detright
    } else if detleft < 0.0 {
        if detright >= 0.0 { return sign(det) }
        -detleft - detright
    } else {
        return sign(det);
    };
    if det >= 1e-15 * detsum || -det >= 1e-15 * detsum {
        return sign(det);
    }
    let dx1 = Dd(p2[0], 0.0).add(Dd(-p1[0], 0.0));
    let dy1 = Dd(p2[1], 0.0).add(Dd(-p1[1], 0.0));
    let dx2 = Dd(q[0], 0.0).add(Dd(-p2[0], 0.0));
    let dy2 = Dd(q[1], 0.0).add(Dd(-p2[1], 0.0));
    let d = dx1.mul(dy2).add(dy1.mul(dx2).neg());
    if d.0 > 0.0 || (d.0 == 0.0 && d.1 > 0.0) { 1 } else if d.0 < 0.0 || (d.0 == 0.0 && d.1 < 0.0) { -1 } else { 0 }
}

/// `q` in the box of `a` and `b` (GEOS Envelope::intersects(p1, p2, q)).
fn in_box(a: P, b: P, q: P) -> bool {
    q[0] >= a[0].min(b[0]) && q[0] <= a[0].max(b[0]) && q[1] >= a[1].min(b[1]) && q[1] <= a[1].max(b[1])
}

/// GEOS LineIntersector: do the segments meet at a point that is no end point of one of them (`isInteriorIntersection`)?
fn interior_intersection(p: (P, P), q: (P, P)) -> bool {
    let ((p1, p2), (q1, q2)) = (p, q);
    let boxes = p1[0].min(p2[0]) <= q1[0].max(q2[0]) && q1[0].min(q2[0]) <= p1[0].max(p2[0])
        && p1[1].min(p2[1]) <= q1[1].max(q2[1]) && q1[1].min(q2[1]) <= p1[1].max(p2[1]);
    if !boxes {
        return false;
    }
    let (pq1, pq2) = (orientation(p1, p2, q1), orientation(p1, p2, q2));
    if (pq1 > 0 && pq2 > 0) || (pq1 < 0 && pq2 < 0) {
        return false;
    }
    let (qp1, qp2) = (orientation(q1, q2, p1), orientation(q1, q2, p2));
    if (qp1 > 0 && qp2 > 0) || (qp1 < 0 && qp2 < 0) {
        return false;
    }
    let interior = |pts: &[P]| pts.iter().any(|x| !(*x == p1 || *x == p2) || !(*x == q1 || *x == q2));
    if pq1 == 0 && pq2 == 0 && qp1 == 0 && qp2 == 0 {
        // collinear: the ends of the overlap
        let (q1p, q2p, p1q, p2q) = (in_box(p1, p2, q1), in_box(p1, p2, q2), in_box(q1, q2, p1), in_box(q1, q2, p2));
        let pts: Vec<P> = if q1p && q2p { vec![q1, q2] } else if p1q && p2q { vec![p1, p2] }
            else if q1p && p1q { if q1 == p1 && !q2p && !p2q { vec![q1] } else { vec![q1, p1] } }
            else if q1p && p2q { if q1 == p2 && !q2p && !p1q { vec![q1] } else { vec![q1, p2] } }
            else if q2p && p1q { if q2 == p1 && !q1p && !p2q { vec![q2] } else { vec![q2, p1] } }
            else if q2p && p2q { if q2 == p2 && !q1p && !p1q { vec![q2] } else { vec![q2, p2] } }
            else { return false };
        return interior(&pts);
    }
    if pq1 == 0 || pq2 == 0 || qp1 == 0 || qp2 == 0 {
        let x = if p1 == q1 || p1 == q2 { p1 } else if p2 == q1 || p2 == q2 { p2 }
            else if pq1 == 0 { q1 } else if pq2 == 0 { q2 } else if qp1 == 0 { p1 } else { p2 };
        return interior(&[x]);
    }
    true        // a proper intersection
}

/// Python's `round(x, 7)`: the decimal number of 7 places nearest to `x` (correctly rounded, as Python's).
pub fn round7(x: f64) -> f64 {
    format!("{x:.7}").parse().unwrap_or(x)
}

pub fn round_line(l: &[P]) -> Vec<P> {
    l.iter().map(|p| [round7(p[0]), round7(p[1])]).collect()
}

/// A WKB LineString (2D or with Z, Z dropped).
pub fn wkb_line(b: &[u8]) -> Option<Line> {
    if b.len() < 9 {
        return None;
    }
    let le = b[0] == 1;
    let u32_at = |i: usize| -> u32 { let a = [b[i], b[i + 1], b[i + 2], b[i + 3]]; if le { u32::from_le_bytes(a) } else { u32::from_be_bytes(a) } };
    let f64_at = |i: usize| -> f64 { let mut a = [0u8; 8]; a.copy_from_slice(&b[i..i + 8]); if le { f64::from_le_bytes(a) } else { f64::from_be_bytes(a) } };
    let t = u32_at(1);
    let (kind, z) = (t & 0xffff, t & 0x8000_0000 != 0 || (1000..2000).contains(&(t & 0xffff)) || (3000..4000).contains(&(t & 0xffff)));
    if kind % 1000 != 2 {
        return None;
    }
    let n = u32_at(5) as usize;
    let step = if z { 24 } else { 16 };
    if b.len() < 9 + n * step {
        return None;
    }
    Some((0..n).map(|i| [f64_at(9 + i * step), f64_at(17 + i * step)]).collect())
}

/// A WKT POLYGON's outer ring (DuckDB's ST_AsText), as shapely reads it.
pub fn wkt_ring(t: &str) -> Option<Vec<P>> {
    let body = t.trim().strip_prefix("POLYGON")?.trim().strip_prefix("((")?;
    let ring = body.split(')').next()?;
    ring.split(',').map(|p| {
        let mut xy = p.split_whitespace().map(|x| x.parse::<f64>());
        Some([xy.next()?.ok()?, xy.next()?.ok()?])
    }).collect()
}

// ---- UTM (WGS 84): PROJ's transverse Mercator (tmerc.cpp, the Poder/Engsager series of 6th order with Clenshaw sums), step for step,
// so that the numbers are PROJ's to the last bit: the simplify of a line chooses between points that are nanometres apart ----

const ORDER: usize = 6;

/// The C library's asinh, as PROJ calls it (Rust's f64::asinh is a formula of its own, a bit away in the last place).
#[cfg(not(target_family = "wasm"))]
fn asinh(x: f64) -> f64 {
    extern "C" {
        fn asinh(x: f64) -> f64;
    }
    // SAFETY: asinh of the C library takes and gives a double, with no other effect
    unsafe { asinh(x) }
}

#[cfg(target_family = "wasm")]
fn asinh(x: f64) -> f64 {
    x.asinh()
}

/// PROJ's pj_clenshaw: sum(F[k] sin((2k+2) zeta)), zeta given by its sine and cosine.
fn clenshaw(s: f64, c: f64, f: &[f64; ORDER]) -> f64 {
    let (mut u0, mut u1) = (0.0, 0.0);
    let x = 2.0 * (c - s) * (c + s);
    for k in (0..ORDER).rev() {
        let t = x * u0 - u1 + f[k];
        u1 = u0;
        u0 = t;
    }
    2.0 * s * c * u0
}

/// PROJ's pj_auxlat_convert.
fn auxlat(zeta: f64, s: f64, c: f64, f: &[f64; ORDER]) -> f64 {
    zeta + clenshaw(s, c, f)
}

/// PROJ's clenS: the complex Clenshaw sum; (real, imaginary).
fn clen_s(a: &[f64; ORDER], sin_r: f64, cos_r: f64, sinh_i: f64, cosh_i: f64) -> (f64, f64) {
    let r = 2.0 * cos_r * cosh_i;
    let i = -2.0 * sin_r * sinh_i;
    let (mut hi1, mut hr1, mut hi) = (0.0, 0.0, 0.0);
    let mut hr = a[ORDER - 1];
    for k in (0..ORDER - 1).rev() {
        let (hr2, hi2) = (hr1, hi1);
        hr1 = hr;
        hi1 = hi;
        hr = -hr2 + r * hr1 - i * hi1 + a[k];
        hi = -hi2 + i * hr1 + r * hi1;
    }
    let (r, i) = (sin_r * cosh_i, cos_r * sinh_i);
    (r * hr - i * hi, r * hi + i * hr)
}

/// A UTM zone of WGS 84, both ways (PROJ's `+proj=utm +zone=.. +datum=WGS84`).
pub struct Utm {
    lam0: f64,
    y0: f64,
    a: f64,
    qn: f64,
    zb: f64,
    cbg: [f64; ORDER],
    cgb: [f64; ORDER],
    utg: [f64; ORDER],
    gtu: [f64; ORDER],
}

const DEG: f64 = 0.017453292519943296;

impl Utm {
    /// The zone of a point (lon, lat): its 6-degree zone, north or south.
    pub fn new(lon: f64, lat: f64) -> Utm {
        let zone = (((lon + 180.0) / 6.0).floor() as i32).clamp(0, 59) + 1;
        // PROJ's ellipsoid: rf, then es, e, the angular eccentricity and the third flattening from it
        let f: f64 = 1.0 / 298.257223563;
        let es = 2.0 * f - f * f;
        let alpha = es.sqrt().asin();
        let n = (alpha / 2.0).tan().powf(2.0);
        let mut np = n;
        let mut cgb = [0.0; ORDER];
        let mut cbg = [0.0; ORDER];
        cgb[0] = n * (2.0 + n * (-2.0 / 3.0 + n * (-2.0 + n * (116.0 / 45.0 + n * (26.0 / 45.0 + n * (-2854.0 / 675.0))))));
        cbg[0] = n * (-2.0 + n * (2.0 / 3.0 + n * (4.0 / 3.0 + n * (-82.0 / 45.0 + n * (32.0 / 45.0 + n * (4642.0 / 4725.0))))));
        np *= n;
        cgb[1] = np * (7.0 / 3.0 + n * (-8.0 / 5.0 + n * (-227.0 / 45.0 + n * (2704.0 / 315.0 + n * (2323.0 / 945.0)))));
        cbg[1] = np * (5.0 / 3.0 + n * (-16.0 / 15.0 + n * (-13.0 / 9.0 + n * (904.0 / 315.0 + n * (-1522.0 / 945.0)))));
        np *= n;
        cgb[2] = np * (56.0 / 15.0 + n * (-136.0 / 35.0 + n * (-1262.0 / 105.0 + n * (73814.0 / 2835.0))));
        cbg[2] = np * (-26.0 / 15.0 + n * (34.0 / 21.0 + n * (8.0 / 5.0 + n * (-12686.0 / 2835.0))));
        np *= n;
        cgb[3] = np * (4279.0 / 630.0 + n * (-332.0 / 35.0 + n * (-399572.0 / 14175.0)));
        cbg[3] = np * (1237.0 / 630.0 + n * (-12.0 / 5.0 + n * (-24832.0 / 14175.0)));
        np *= n;
        cgb[4] = np * (4174.0 / 315.0 + n * (-144838.0 / 6237.0));
        cbg[4] = np * (-734.0 / 315.0 + n * (109598.0 / 31185.0));
        np *= n;
        cgb[5] = np * (601676.0 / 22275.0);
        cbg[5] = np * (444337.0 / 155925.0);
        np = n * n;
        // the rectifying radius in this order of operations: 46,643 lane points of Monaco and Tartu equal to pyproj (PROJ 9.8.1) to the bit
        let qn = 0.9996 / (1.0 + n) * (1.0 + np * (1.0 / 4.0 + np * (1.0 / 64.0 + np / 256.0)));
        let mut utg = [0.0; ORDER];
        let mut gtu = [0.0; ORDER];
        utg[0] = n * (-0.5 + n * (2.0 / 3.0 + n * (-37.0 / 96.0 + n * (1.0 / 360.0 + n * (81.0 / 512.0 + n * (-96199.0 / 604800.0))))));
        gtu[0] = n * (0.5 + n * (-2.0 / 3.0 + n * (5.0 / 16.0 + n * (41.0 / 180.0 + n * (-127.0 / 288.0 + n * (7891.0 / 37800.0))))));
        utg[1] = np * (-1.0 / 48.0 + n * (-1.0 / 15.0 + n * (437.0 / 1440.0 + n * (-46.0 / 105.0 + n * (1118711.0 / 3870720.0)))));
        gtu[1] = np * (13.0 / 48.0 + n * (-3.0 / 5.0 + n * (557.0 / 1440.0 + n * (281.0 / 630.0 + n * (-1983433.0 / 1935360.0)))));
        np *= n;
        utg[2] = np * (-17.0 / 480.0 + n * (37.0 / 840.0 + n * (209.0 / 4480.0 + n * (-5569.0 / 90720.0))));
        gtu[2] = np * (61.0 / 240.0 + n * (-103.0 / 140.0 + n * (15061.0 / 26880.0 + n * (167603.0 / 181440.0))));
        np *= n;
        utg[3] = np * (-4397.0 / 161280.0 + n * (11.0 / 504.0 + n * (830251.0 / 7257600.0)));
        gtu[3] = np * (49561.0 / 161280.0 + n * (-179.0 / 168.0 + n * (6601661.0 / 7257600.0)));
        np *= n;
        utg[4] = np * (-4583.0 / 161280.0 + n * (108847.0 / 3991680.0));
        gtu[4] = np * (34729.0 / 80640.0 + n * (-3418889.0 / 1995840.0));
        np *= n;
        utg[5] = np * (-20648693.0 / 638668800.0);
        gtu[5] = np * (212378941.0 / 319334400.0);
        let z = auxlat(0.0, 0.0, 1.0, &cbg);
        let zb = -qn * auxlat(z, z.sin(), z.cos(), &gtu);
        Utm {
            lam0: ((zone as f64 - 1.0) + 0.5) * std::f64::consts::PI / 30.0 - std::f64::consts::PI,
            y0: if lat >= 0.0 { 0.0 } else { 10_000_000.0 },
            a: 6_378_137.0,
            qn, zb, cbg, cgb, utg, gtu,
        }
    }

    /// geopandas' `estimate_utm_crs` of some lines: the zone of the center of their box.
    pub fn of<'a>(lines: impl IntoIterator<Item = &'a Line>) -> Utm {
        let (mut x0, mut y0, mut x1, mut y1) = (f64::MAX, f64::MAX, f64::MIN, f64::MIN);
        for p in lines.into_iter().flatten() {
            (x0, y0, x1, y1) = (x0.min(p[0]), y0.min(p[1]), x1.max(p[0]), y1.max(p[1]));
        }
        Utm::new((x0 + x1) / 2.0, (y0 + y1) / 2.0)
    }

    /// (lon, lat) to (easting, northing): PROJ's exact_e_fwd.
    pub fn fwd(&self, p: [f64; 2]) -> [f64; 2] {
        let (lam, phi) = (p[0] * DEG - self.lam0, p[1] * DEG);
        let mut cn = auxlat(phi, phi.sin(), phi.cos(), &self.cbg);
        let (sin_cn, cos_cn, sin_ce, cos_ce) = (cn.sin(), cn.cos(), lam.sin(), lam.cos());
        let cos_cn_cos_ce = cos_cn * cos_ce;
        cn = sin_cn.atan2(cos_cn_cos_ce);
        let inv_denom = 1.0 / sin_cn.hypot(cos_cn_cos_ce);
        let tan_ce = sin_ce * cos_cn * inv_denom;
        let mut ce = asinh(tan_ce);
        let two_inv = 2.0 * inv_denom;
        let two_inv_sq = two_inv * inv_denom;
        let tmp_r = cos_cn_cos_ce * two_inv_sq;
        let sin_r = sin_cn * tmp_r;
        let cos_r = cos_cn_cos_ce * tmp_r - 1.0;
        let sinh_i = tan_ce * two_inv;
        let cosh_i = two_inv_sq - 1.0;
        let (dcn, dce) = clen_s(&self.gtu, sin_r, cos_r, sinh_i, cosh_i);
        cn += dcn;
        ce += dce;
        let (x, y) = (self.qn * ce, self.qn * cn + self.zb);
        [self.a * x + 500_000.0, self.a * y + self.y0]
    }

    /// (easting, northing) to (lon, lat): PROJ's exact_e_inv.
    pub fn inv(&self, p: [f64; 2]) -> [f64; 2] {
        let ra = 1.0 / self.a;
        let (x, y) = ((p[0] - 500_000.0) * ra, (p[1] - self.y0) * ra);
        let mut cn = (y - self.zb) / self.qn;
        let mut ce = x / self.qn;
        let (sin_r, cos_r) = ((2.0 * cn).sin(), (2.0 * cn).cos());
        let e2 = (2.0 * ce).exp();
        let half_inv = 0.5 / e2;
        let (sinh_i, cosh_i) = (0.5 * e2 - half_inv, 0.5 * e2 + half_inv);
        let (dcn, dce) = clen_s(&self.utg, sin_r, cos_r, sinh_i, cosh_i);
        cn += dcn;
        ce += dce;
        let (sin_cn, cos_cn) = (cn.sin(), cn.cos());
        let sinh_ce = ce.sinh();
        ce = sinh_ce.atan2(cos_cn);
        let modulus = sinh_ce.hypot(cos_cn);
        let rr = sin_cn.hypot(modulus);
        cn = sin_cn.atan2(modulus);
        let _ = dcn;
        let phi = auxlat(cn, sin_cn / rr, modulus / rr, &self.cgb);
        [(ce + self.lam0) / DEG, phi / DEG]
    }

    pub fn fwd_line(&self, l: &[P]) -> Line {
        l.iter().map(|p| self.fwd(*p)).collect()
    }

    pub fn inv_line(&self, l: &[P]) -> Line {
        l.iter().map(|p| self.inv(*p)).collect()
    }
}

// ---- PROJ's aeqd on WGS 84 (`+proj=aeqd +lat_0=.. +lon_0=.. +datum=WGS84`): the geodesic from the center ----

/// The azimuthal equidistant projection around a point (lon, lat), as PROJ's ellipsoidal one.
pub struct Aeqd {
    lon0: f64,
    lat0: f64,
    g: Geodesic,
}

impl Aeqd {
    pub fn new(center: P) -> Aeqd {
        Aeqd { lon0: center[0], lat0: center[1], g: Geodesic::wgs84() }
    }

    pub fn fwd(&self, p: P) -> P {
        let lam = (p[0] - self.lon0).to_radians();
        if lam.abs() < 1e-10 && (p[1] - self.lat0).to_radians().abs() < 1e-10 {
            return [0.0, 0.0];
        }
        let (s12, azi1, _, _): (f64, f64, f64, f64) = self.g.inverse(self.lat0, self.lon0, p[1], p[0]);
        let a = azi1.to_radians();
        [s12 * a.sin(), s12 * a.cos()]
    }

    pub fn inv(&self, p: P) -> P {
        let s12 = p[0].hypot(p[1]);
        if s12 < 1e-10 {
            return [self.lon0, self.lat0];
        }
        let (lat, lon): (f64, f64) = self.g.direct(self.lat0, self.lon0, p[0].atan2(p[1]).to_degrees(), s12);
        [lon, lat]
    }

    pub fn fwd_line(&self, l: &[P]) -> Line {
        l.iter().map(|p| self.fwd(*p)).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn utm_round_trip_is_under_a_micrometre() {
        let u = Utm::new(7.42, 43.73);
        for p in [[7.41, 43.72], [7.44, 43.75], [6.1, 43.1]] {
            let b = u.inv(u.fwd(p));
            assert!((b[0] - p[0]).abs() < 1e-11 && (b[1] - p[1]).abs() < 1e-11, "{p:?} {b:?}");
        }
    }

    #[test]
    fn aeqd_round_trip() {
        let a = Aeqd::new([7.42, 43.73]);
        let p = [7.4213, 43.7311];
        let b = a.inv(a.fwd(p));
        assert!((b[0] - p[0]).abs() < 1e-12 && (b[1] - p[1]).abs() < 1e-12);
    }

    #[test]
    fn substring_as_shapely() {
        let l: Line = (0..6).map(|i| [i as f64, 0.0]).collect();
        assert_eq!(substring(&l, 1.0, 3.0, false).unwrap(), vec![[1.0, 0.0], [2.0, 0.0], [3.0, 0.0]]);
        assert_eq!(substring(&l, 3.0, 1.0, false).unwrap(), vec![[3.0, 0.0], [2.0, 0.0], [1.0, 0.0]]);
        assert_eq!(substring(&l, 1.0, -3.0, false).unwrap(), vec![[1.0, 0.0], [2.0, 0.0]]);
        assert_eq!(substring(&l, 0.2, -0.6, true).unwrap(), vec![[1.0, 0.0], [2.0, 0.0]]);
    }
}

#[cfg(test)]
mod simplify_tests {
    use super::*;

    #[test]
    fn a_zigzag_keeps_the_point_that_geos_keeps() {
        let c = [[373657.40005974483, 4844802.902638862], [373658.5518851269, 4844803.895576644], [373659.7037101673, 4844804.888514617],
                 [373660.85417800734, 4844805.88028058], [373660.8555348666, 4844805.881452786], [373660.85553486465, 4844805.881452784],
                 [373660.855534866, 4844805.881452785], [373660.8562066604, 4844805.882680171], [373661.79769148974, 4844807.606205531],
                 [373662.7398476475, 4844809.330958405], [373663.6820033396, 4844811.055711405], [373664.62415856577, 4844812.780464535],
                 [373665.56631332624, 4844814.50521779], [373666.5084676207, 4844816.229971175], [373667.45062144945, 4844817.954724686],
                 [373668.39277481235, 4844819.679478323], [373669.3349277095, 4844821.40423209], [373670.27708014066, 4844823.128985984]];
        // shapely 2.1 (GEOS 3.14): LineString(c).simplify(0.02)
        assert_eq!(simplify(&c, 0.02), vec![c[0], c[3], c[4], c[17]]);
    }
}
