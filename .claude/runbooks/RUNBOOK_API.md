# api-and-state — diagnostics runbook
Loaded on demand from the `api-and-state` rule's Diagnostics pointer. Symptom → diagnosis content; not auto-loaded.

## Debug
- `GET /design/debug/strand-stats` — strand length/type/sequence stats

## Diagnostics

## Symptoms
- Python-level test shows correct output, but `GET /api/design` returns wrong result
- API returns 200 but design state looks wrong / stale
- Undo (Ctrl-Z) skips expected steps or reverts more than expected
- `set_design_silent` appears to have pushed to undo when it shouldn't have
- Server seems out of sync with what the test just did

## First-Check Invariants

1. **Stale server state** — uvicorn `--reload` keeps `design_state` in memory. Prior curl/test operations leave residue. If Python test is correct but API is wrong, the server state is stale.

2. **Correct mutation path** — the ONLY correct way to mutate the active design is `state.mutate_and_validate(fn)`. Direct assignment to `_active_design` outside the lock is wrong.

3. **`set_design_silent` does NOT push undo** — correct use: inside a `snapshot()` bracket for multi-step ops. Wrong use: as a replacement for `mutate_and_validate` in a single-step operation.

## Diagnosis Tree

### Python test correct but API returns wrong result
1. **STOP.** Don't add logging. Don't dig further into backend Python.
2. **Ask user to reset the server** — `just dev` or restart uvicorn.
3. After restart, re-run the same API call. If it now works, it was stale state.
4. If still wrong after restart → it's a real bug, not stale state. Now investigate.

### Undo skips a step / reverts too much
1. Check that the operation uses `mutate_and_validate()`, not `set_design_silent()`
2. If multi-step op: verify `snapshot()` is called exactly once before the first step, and `set_design_silent()` is used for intermediate steps, and `mutate_and_validate()` is used for the final step only
3. Check if `clear_history()` is being called unexpectedly (only valid after `create_bundle` or new design)

### Undo does nothing (404)
1. `_history` deque is empty
2. Either `clear_history()` was called, or no mutations have been made yet
3. Check `state.py` — `_history: deque[Design] = deque(maxlen=50)`

### Design not saving between page reloads
- NADOC uses in-memory state only (no automatic persistence)
- User must manually `File > Export Design (.nadoc)` to save
- State is lost on server restart

### 409 Conflict on DELETE
- Entity is referenced by another entity (helix referenced by strand, strand referenced by another)
- Delete the referencing entities first, or use batch delete
