# Occupancy clouds — archived

Archived on November 22, 2026 at the user’s request, for both NAMD and oxDNA.

Removed from the visualization cards, scope pickers, scene startup, job-switch
refresh, setup capture/restore, shared-view feature names, public API registration,
README, FEATURES and the guide feature catalog. Old saved occupancy scope selections
are ignored. Trajectory files and existing analysis caches are preserved.

The renderer, controller and engine-specific analysis remain at their original
source paths, explicitly marked archived, for historical research and unit coverage.
Shared clustering utilities remain active for extra-base position analysis.
The old route implementation functions remain unregistered. Historical browser
workflows have `.spec.js.archived` suffixes and are not active Playwright tests.
The last published version with occupancy clouds was `1e31e4f5`.

Historical design notes: [occupancy clouds](../../memory/project_oxdna_occupancy_clouds.md).
This retirement concerns the conformational-cloud visualization, not pore-ion
occupancy measurements, molecular site occupancy, or other uses of that term.
