# Shared presenter annotations

Visible part annotations are included in prepared presentations. Their text, icon,
color, opacity, size, callout style and normalized manual placement accompany the
existing highlight geometry. Hidden annotations and disabled annotation text are
excluded, as are editor selection references. Guest callouts are read-only and
use the existing layout renderer with the guest camera.

Callout anchors reference exported highlight/halo UUIDs rather than backend model
IDs. Guests read those render buffers each frame, so simulation frame updates and
independent camera movement keep leaders attached to the displayed targets.
Native presentations watch annotation changes as well as view-tool changes; live
job and editor broadcasts include annotations in their existing scene fingerprints.
The document/job privacy guards and same-invitation updates remain in effect.

Guests clean up callouts and frame callbacks when a scene is replaced, cleared,
or disposed. Annotation metadata is bounded and validated before guest rendering.
Older hosts need a restart to advertise `annotations-v1`.

Validation: 131 unit/integration tests across viewer and annotation overlay/subsystem
suites; a Chromium test of actual editor annotations, guest loading/rendering,
on/off toggles, text changes, manual placement, independent camera movement and
cleanup; production build. No public internet meeting was created for validation.
