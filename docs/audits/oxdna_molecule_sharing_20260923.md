# oxDNA molecular presentation sharing

PEG surfaces already participate in prepared snapshots: `surface_strands_overlay`
adds instanced beads, bond lines, and a translucent coverage patch to the exported
scene. New PEG simulation frames replace geometry, which causes job sharing to
publish a new scene on the same invitation. Protein trace/ovoid/box meshes and
nanoparticle physical meshes also use supported objects, including oxDNA poses.

The missing case was optimized sphere materials, used by atomic streptavidin
coatings and optionally other atomic proteins. Prepared scene version 4 carries
only a validated radius and instance-alpha flag. Guests reconstruct the known
local sphere shader, preserving depth, colors, clipping and sphere picking.
Arbitrary custom shader code remains unsupported. Older packages still load.
Hosting advertises `sphere-impostors-v1`; publishing to an older host prompts a
restart after the meeting.

Validation: 111 frontend tests (viewer suite plus impostor and streptavidin
renderer tests), 8 host/broadcast/live-frame tests, and the production build pass.
`shared_molecules.test.js` exercises real PEG and protein/coating renderers through
serialization, guest reconstruction, and live frame application/republication.
This validation did not include a manual internet meeting or GPU screenshot comparison.
