"""
host/memdiag.py

Per-frame memory diagnostics: RSS, Python heap (tracemalloc), GC generation
counts, and the top allocation sites that grew since the last snapshot.

Call start() once at startup, then update(now) each frame. Reports are
throttled to _interval seconds so they don't flood stdout.

Metrics:
    RSS        — physical RAM pages currently mapped into the process (OS view).
                 Includes Python heap + loaded libraries + malloc arenas held
                 after Python frees objects (macOS malloc fragmentation shows here).
    heap_cur   — live Python-managed allocations tracked by tracemalloc.
                 If this is stable but RSS grows, the cause is outside Python's heap.
    heap_peak  — high-water mark of heap_cur since tracemalloc.start().
    gc         — (gen0, gen1, gen2) object counts awaiting collection.
"""

import gc
import os
import tracemalloc

import psutil

_proc     = psutil.Process(os.getpid())
_last     = 0.0
_interval = 5.0   # seconds between reports
_snap     = None


def start() -> None:
    """Begin tracemalloc tracing. Call once before the frame loop."""
    tracemalloc.start()


def update(now: float) -> None:
    """Emit a memory report if the interval has elapsed. Call once per frame."""
    global _last, _snap
    if now - _last < _interval:
        return
    _last = now

    rss        = _proc.memory_info().rss / 1024 ** 3
    cur, peak  = tracemalloc.get_traced_memory()
    g0, g1, g2 = gc.get_count()

    print(
        f"[mem]  RSS={rss:.3f} GB"
        f"  heap_cur={cur/1024**2:.1f} MB"
        f"  heap_peak={peak/1024**2:.1f} MB"
        f"  gc=({g0},{g1},{g2})"
    )

    # Top 5 allocation sites that grew since last snapshot
    snap = tracemalloc.take_snapshot()
    if _snap is not None:
        stats = snap.compare_to(_snap, 'lineno')
        for s in stats[:5]:
            print(f"  {s}")
    _snap = snap
