# Race we hit + fix (don't regress) — supporting detail

[Topic head](../../project_ct_tab.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Race we hit + fix (don't regress)
**Race**: user types into a `#ct-seq-input-{a,b}` side input, doesn't Tab
out, clicks **Generate Linker**. Browser fires `blur` (which starts an
async `patchOverhang`) and then the `click` handler (which starts an
async `createOverhangConnection`). Both are in-flight simultaneously;
depending on response ordering, the new linker can be created against
NOT-YET-COMMITTED overhang sequences. Symptom: the Sequence column
complement portion renders as N's even though the side input shows the
correct value.

**Fix**: in `_onCtGenerateLinker`, before calling `createOverhangConnection`,
diff each side input's value against `_overhangs().find(o => o.id === id).sequence`
and `await patchOverhang(...)` for any that differ. Synchronous-equivalent
commit eliminates the race. See `_onCtGenerateLinker` in
[overhangs_manager_popup.js](../../../frontend/src/ui/overhangs_manager_popup.js).
