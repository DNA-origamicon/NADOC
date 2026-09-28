# VR view-volume controls — 2026-09-27

Visualization's View Volumes title opens a dedicated paginated list. Square and
hex creation, independent outline and enabled switches, deletion and menu return
are implemented. Native outlines use transformed document coordinates and follow
the model transform. Moving/resizing volumes in VR and native per-volume
representation rendering are outside this menu/backend change.

Both interfaces share the part's saved records. An atomic acknowledged native
journal binds writes to the launching document. The backend publishes desktop
edits to the viewer; desktop polling imports native edits and invokes normal
workspace autosave. Unsaved parts need their normal first Save. Desktop changes
patch individual fields so unrelated concurrent native edits survive. Assembly
volume management is disabled.

Validation: native build and 42 CTests pass; 66 focused backend tests and 44
frontend unit tests pass. Three Chromium scenarios pass: add/edit/delete and
transforms, recovery after stale full-design responses, and externally created
records appearing live with independent switches and deletion. The backend test
writes a `.nadoc` file, reloads it, and verifies saved state, rotated hex outline
coordinates, native creation coordinates, replay and document binding.

The initial native link used an incompatible Conda linker; rebuilding with
`PATH=/usr/bin:/bin` passed. The sidebar collapse regression test now excludes
both list-opening title cards. Earlier browser attempts hit nested heading/row
controls and a sidebar covering hard-coded canvas coordinates. Tests now click
the actual title/row padding and derive unobscured canvas coordinates using
`elementFromPoint`; production hit geometry and acceptance thresholds were not
changed. The final desktop screenshot scrolls the volume card into view and was
visually inspected: the externally created VR hex record and controls are visible.

Evidence, including failed browser attempts:
[artifact directory](../../.development-artifacts/vr-view-volumes/).
[Desktop capture](../../.development-artifacts/vr-view-volumes/nadoc-view-volume-controls.png).
No headset run was performed; physical legibility, controller interaction and
stereo outline appearance remain unverified.
