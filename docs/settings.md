# Application settings

Open **File → Settings…**. The popup has ten tabs: Appearance & accessibility,
Files & storage, Saving & recovery, Layout & startup, Viewport, Navigation & input,
Editor defaults, Notifications, Data & diagnostics, and Settings management.
Simulation workflow is deliberately excluded.

Implemented controls:

| Tab | Controls |
| --- | --- |
| Appearance & accessibility | Text multiplier, dark/light/system theme, high contrast, reduced interface motion, compact/comfortable spacing |
| Files & storage | MD/NAMD and oxDNA folders, server folder browser, path validation and free-space display |
| Saving & recovery | Workspace autosave, save delay, unsaved-change exit warning, recent-file limit and clearing |
| Layout & startup | Remember sidebar layouts and collapsed sections, default left/right tabs, reset saved layout |
| Viewport | Background color, antialiasing, pixel-density cap, frame-rate cap, hidden-tab drawing, default helix labels and molecular coloring |
| Navigation & input | Multiscale/turntable/trackball mode, orbit/pan/zoom sensitivity, orbit zoom-to-cursor, shortcut viewer and remapping with conflict checks |
| Editor defaults | Extrusion preview; scaffold, staple, strand, domain and end selection defaults |
| Notifications | Toast duration, persistent errors, optional background desktop alerts and sounds, bounded session message history |
| Data & diagnostics | Browser storage estimate, cached-library clearing, diagnostic report, sync console logging and history-row limit |
| Settings management | Versioned import/export, category reset and full browser-preference reset |

Preferences belong to this browser origin and are stored under
`nadoc:preferences:v1`. Apply validates the complete draft before saving. Closing,
Escape, or Cancel discards unapplied changes and restores the saved appearance.
Text size previews immediately and scales both typography tokens and legacy
pixel-sized labels, without scaling the WebGL canvas or molecular coordinates.

The MD/NAMD and oxDNA folder controls use the existing engine-specific run-location
preferences and server folder browser. An empty value selects the workspace
folder. Explicit paths must exist and be writable; validation reports the resolved
path and available disk space. Changing a default neither moves existing data nor
redirects running jobs. Folder preferences are excluded from export/import and
preference reset.

Autosave controls govern workspace-file write-back for parts and assemblies.
Recovery/session persistence is independent and remains active. Annotation-only
saves retain their existing minimum coalescing delay. Changes to a save delay
apply to subsequent edits; disabling autosave also suppresses pending writes
that have not started. Explicit File → Save remains available.

Sidebar defaults apply when there is no saved layout, or when remembering layout
is disabled. Sidebar persistence, default tabs and antialiasing take effect on
reload. Background color uses the same controller as View → Background Settings.
Rendering limits skip drawing only; animation callbacks and job monitoring keep
running. WebXR drawing is not capped by the desktop preference.

Keyboard shortcut overrides retain the original command's input/context guards.
Blank shortcut fields use the registered binding; Apply rejects ambiguous
conflicts. Preference imports reject unknown keys, unsupported versions and
invalid values. Browser/operating-system shortcuts may take precedence.

Application message history retains the last 200 notifications in memory.
Desktop alerts require explicit browser permission and apply to success/error
messages while the tab is hidden. Sounds are subject to browser autoplay policy.
Diagnostics omit document contents, recovery contents and machine paths. Clearing
the library cache removes only the cached listing; reset does not clear designs,
recovery state, jobs or feature logs.

The dialog exposes implemented application controls. The broader proposal's
server workspace relocation, archive/export/scratch roots, backup versioning,
recovery retention, startup document restoration, viewport projection/palettes,
label sizing, geometric snapping/measurement formatting, and tooltip controls
are not implemented by this change. They need their own persistence and runtime
integration; no inactive controls or pretend settings are presented.
