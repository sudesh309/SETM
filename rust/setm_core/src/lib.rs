//! Optional Rust acceleration for SETM's hot traversal paths.
//!
//! This crate is **not required**. `setm/graph/_fastpath.py` ships equivalent
//! pure-Python implementations and uses them unless this extension is importable,
//! so the MVP runs with nothing but CPython. Build it only when a programme's
//! graph grows past roughly 10^5 relations and breadth-first traversal starts to
//! show up in the `/api/kpi/app` latency figures:
//!
//! ```text
//! pip install maturin
//! cd rust/setm_core && maturin develop --release
//! ```
//!
//! The Python side then reports `"backend": "rust:setm_core"` on the System page.
//!
//! The functions take an already-built adjacency map rather than the graph
//! itself: crossing the FFI boundary once with a flat map is far cheaper than
//! calling back into Python for every neighbour lookup.

use pyo3::prelude::*;
use std::collections::{HashMap, HashSet, VecDeque};

/// Every node reachable from `start` within `max_depth` hops, including `start`.
#[pyfunction]
#[pyo3(signature = (adjacency, start, max_depth))]
fn reachable(
    adjacency: HashMap<String, Vec<String>>,
    start: String,
    max_depth: usize,
) -> PyResult<Vec<String>> {
    let mut seen: HashSet<String> = HashSet::new();
    let mut queue: VecDeque<(String, usize)> = VecDeque::new();

    seen.insert(start.clone());
    queue.push_back((start, 0));

    while let Some((current, depth)) = queue.pop_front() {
        if depth >= max_depth {
            continue;
        }
        if let Some(neighbours) = adjacency.get(&current) {
            for neighbour in neighbours {
                if seen.insert(neighbour.clone()) {
                    queue.push_back((neighbour.clone(), depth + 1));
                }
            }
        }
    }
    Ok(seen.into_iter().collect())
}

/// Hop count from `start` to every reachable node.
#[pyfunction]
#[pyo3(signature = (adjacency, start))]
fn distances(
    adjacency: HashMap<String, Vec<String>>,
    start: String,
) -> PyResult<HashMap<String, usize>> {
    let mut out: HashMap<String, usize> = HashMap::new();
    let mut queue: VecDeque<String> = VecDeque::new();

    out.insert(start.clone(), 0);
    queue.push_back(start);

    while let Some(current) = queue.pop_front() {
        let depth = out[&current];
        if let Some(neighbours) = adjacency.get(&current) {
            for neighbour in neighbours {
                if !out.contains_key(neighbour) {
                    out.insert(neighbour.clone(), depth + 1);
                    queue.push_back(neighbour.clone());
                }
            }
        }
    }
    Ok(out)
}

#[pymodule]
fn setm_core(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("__version__", env!("CARGO_PKG_VERSION"))?;
    module.add_function(wrap_pyfunction!(reachable, module)?)?;
    module.add_function(wrap_pyfunction!(distances, module)?)?;
    Ok(())
}
