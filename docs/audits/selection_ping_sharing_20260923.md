# Presenter selections and pings

Native presentations now mirror selection changes and deselection independently of
camera sharing. Live jobs and editor broadcasts carry the same display metadata.
Guests receive the existing rendered selection highlights plus an amber target
cloud and a read-only selection label. Selection does not depend on annotation
visibility. The target cloud follows current coordinates through live render frames.

The target resolver supports canonical base/end/bond, domain, strand, cluster,
crossover/forced-ligation, overhang, extension, protein and nanoparticle refs.
Loop/skip marker selections use a read-only selection-manager adapter. Assembly
part, group, cluster and overhang selections resolve through instance world
transforms. Large target clouds are sampled to at most 20,000 points; original
selection highlighting remains in the exported display. Backbone membership is
cached between selection/topology changes while positions remain live.

The Ping button in the View tools row and the period key emit a unique event for
the current selection. For 2.4 seconds, local and guest views flash selected
positions and draw expanding rings; the existing quiet chime plays when browser
sound is unlocked. Reduced-motion users receive a steady outline. Text inputs,
editable content, open dialogs, modified keys and key repeats do not trigger the
shortcut. Empty selections disable the button. Pings preserve camera and selection.

Guests animate locally, remember recently seen event IDs across scene replacements,
and reject events older than eight seconds. Deselecting/changing selection cancels
the current effect. Existing document/job privacy guards still apply. Older hosts
must restart to advertise `selection-ping-v1`. Frozen exported clips remain snapshots.

Validation: 123 frontend tests; 8 hosting/live-frame/broadcast tests; a Chromium
exercise with real editor base/domain/strand selection, a separate guest viewer,
period/button pings, expiry, no replay and deselection; production build.
