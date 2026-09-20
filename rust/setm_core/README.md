# setm_core — optional Rust acceleration

SETM runs entirely on CPython. This crate exists for the one case where that is
not enough: breadth-first traversal over a very large programme graph
(roughly 10^5 relations and up), which is what `impact`, `trace` and the KPI
sweep spend their time on.

## Build

```bash
pip install maturin
cd rust/setm_core
maturin develop --release
```

`setm/graph/_fastpath.py` imports `setm_core` if it is present and silently
falls back to the Python implementation if it is not. Confirm which one is live
on the **System** page in the web interface, or:

```bash
setm info | grep engine
```

## Contract

Both functions take a pre-built adjacency map — one FFI crossing per query
rather than one per neighbour lookup — and must return results identical to the
Python versions in `_fastpath.py`. That file is the specification; if the two
ever disagree, the Python version is correct.
