---
name: Advanced staple router temporarily disabled
description: Advanced thermodynamic staple optimizer in auto_staple_route (crud.py) is disabled due to perf issues — falls back to basic algorithm
type: project
originSessionId: 042f70e4-daa1-46d9-809d-6c6c51de14ce
---
Advanced staple routing algorithm (`algo == 'advanced'` in `auto_staple_route`, crud.py ~line 4732) temporarily disabled — now falls back to the basic `make_nicks_for_autostaple` algorithm.

**Why:** The thermodynamic global optimizer (`staple_routing.optimize_staples_for_scaffold`) was too slow and caused system timeouts/hangs.

**How to apply:** When re-enabling, restore the original advanced branch in `auto_staple_route` (crud.py). The `backend.core.staple_routing` module and `build_scaffold_index_map` logic are still intact — only the call site was bypassed. Performance of `optimize_staples_for_scaffold` needs to be fixed first.
