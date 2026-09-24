# Native presentation cleanup

Stopping a shared oxDNA or NAMD job previously restored native coordinates but
resumed the simulation setup previews. In particular, clearing PEG results via
`setResults(null)` redraws the configured seed PEG surface. That preview was then
exported to guests and remained after the presenter deselected the job.

The stop-sharing native transition now stops live-follow, awaits the full native
representation, then clears occupancy and the existing simulation scene visuals
(surface grid, graphene nanopore, surface strands/PEG, anchor glow, and field gizmo)
before publishing. Native proteins and nanoparticles remain part of the model.

Ping is mounted before End inside the top-center Presenting controls. The period
shortcut and selection-based enabled state are retained.

Validation: 125 viewer/selection unit tests passed; production build passed.
The Chromium host/guest selection and Ping regression also passed.
The cleanup regression uses a real PEG overlay and loads the actual uploaded guest
snapshot for both oxDNA and NAMD. It verifies that Off resumes the seed preview,
publication waits for native restoration, the final snapshot contains no PEG, native
coordinates are restored, and deselection cannot republish the old simulation.
