# Detached controls: feasibility assessment

## Implemented: 2026-11-11

View → **Un/dock sidebars** opens one dedicated browser window containing the
currently expanded left/right columns and their tab rails. Each column receives
an equal share of the available width; a 12px gap separates the sides. Tab clicks
add columns without the docked viewport-width limit. The popup has a close button
and no NADOC menu bar. Closing it, or toggling the menu again, restores docking
and applies the normal docked capacity rules.

`ui/detached_sidebars.js` owns the window lifecycle. `detached_control_view.js`
mirrors controls and forwards input to their existing owner-document nodes;
`detached_overlays.js` mirrors dialogs and context menus. Canonical controls stay
in the primary document so existing controllers, ID lookups, undo/history,
selection, jobs, and API targeting remain authoritative. Repeated views have
unique control IDs and local label/radio associations. Pointer capture and
ancestor coordinate queries use the remote controls during event dispatch.

The popup is created with a fresh `_blank` target. Authority consists only of
direct references captured from its originating editor, guarded by the exact
child Window/Document identity and active-session state. There is no cross-tab
channel, discovery, API client, or second editor in the controls window. Local
and Tailscale origins cannot attach controls to one another. Navigation or
closure of the popup releases its controls and restores docking.

Closing a part or assembly session leaves the popup blank with **the session was
closed**. Opening another session in the same editor repopulates it. Closing or
navigating away from the editor leaves the placeholder; reloading an editor does
not reconnect an old popup automatically. A blocked popup leaves docking intact
and asks the user to allow popups for that origin. Browser chrome and physical
monitor placement remain under browser/OS control.

Automated coverage lives in `ui/detached_sidebars.test.js` and
`e2e/detached_sidebars.spec.js`. Validation: the full frontend suite passed (909 files, 10,315 passed / one
skipped), followed by focused regression checks for the final input/lifecycle
refinements. Both Chromium scenarios passed, including a real trajectory-slider
widget without a simulation job, part/assembly session replacement, popup
navigation, owner isolation, and closing the popup after its owner closes.
`just smoke` passed 23 checks with two normally skipped experimental checks;
`just lint` passed. Temporary workspaces, test designs, bridge credentials and
browser artifacts were removed. `main.js` gained three lines of import/wiring.
Physical multi-monitor usability and long-running simulation/animation
interaction remain manual checks (MV-60). Presentation
viewport mirrors are outside this implementation.

## Original assessment (historical)

The following assessment preceded the implementation above.

## Conclusion

Feasible. A dedicated controls window could live on another monitor while the original window keeps the Three.js scene, rendering and playback. Opening another copy of the full NADOC app would not provide this behavior: it creates another frontend with its own transient scene, lighting, animation player and controllers.

NADOC already uses separate browser windows for document/part editing and its origami editor (`main.js`), document-scoped API headers (`shared/doc_id.js`), and BroadcastChannel-based design notifications. These are useful building blocks, but design-change notifications alone do not synchronize transient lighting, selected trajectory frames, playback or current panel selections.

## Recommended design

- Add a controls-only entry point, launched by an explicit Detach action. Keep rendering, simulation display ownership, caches and export in the original workspace window.
- Bind the controls window to both a document ID and a specific workspace-window ID. Two views of one document can have different transient scenes; the document ID alone is insufficient.
- Give the controls view a versioned state snapshot and updates from the owner, plus a small command interface (set appearance value, select job/frame, seek/play/stop, request export). The owner validates/applies each command once and returns the resulting state/error.
- Keep panel width and scroll local to each controls window. Preserve the shared selections/settings requested for duplicate sidebars.
- Handle owner close, document switch, controls-window reload and reconnection explicitly. If the owner disappears, show a disconnected view rather than silently creating a second player or starting a new simulation. Redocking should preserve the scene.
- Leave file downloads/export rendering with the workspace owner initially. Do not transfer molecular geometry or canvas frames just to synchronize controls.

A same-origin popup can access its opener, but a command/state boundary is preferable to moving the current DOM between documents. Current panels use global `document.getElementById`, window listeners, owner-document styles, singleton controllers and canvas widgets. Their same-document shared-view adapter is not a cross-window transport; adopting those nodes into another document would leave important callbacks targeting the original document/window.

## Browser constraints

`window.open()` should run directly from a user gesture. Popup blocking can return null, and browser settings may produce a tab instead of the requested window. The UI would need an ordinary controls-tab fallback. [MDN: Window.open](https://developer.mozilla.org/en-US/docs/Web/API/Window/open)

Same-origin contexts can exchange structured messages using BroadcastChannel. An explicit protocol is still needed; it does not automatically synchronize application state or replay missed messages for a newly opened window. [MDN: Broadcast Channel API](https://developer.mozilla.org/en-US/docs/Web/API/Broadcast_Channel_API)

Users can move an ordinary controls window to another screen using their OS. Automatically identifying/placing windows on a particular monitor would require the Window Management API, which has limited browser availability and asks for permission. It should be optional, not a prerequisite. [MDN: Using Window Management](https://developer.mozilla.org/en-US/docs/Web/API/Window_Management_API/Using), [MDN: window-management policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Permissions-Policy/window-management)

## Implementation scope and proof required

The popup shell is small work. The substantial work is separating reusable controls from singleton DOM lookups and defining the transient scene command/state contract. Lighting is a suitable first vertical slice, followed by animation and simulation selection. No time estimate is reliable until the panel boundaries are mapped in that work.

A future implementation should prove two-way lighting edits, simulation frame changes and animation seeking across windows; no duplicate jobs/players; correct document targeting; blocked-popup fallback; close/reopen/redock recovery; and multi-monitor usability. This assessment does not claim those behaviors have been tested.
