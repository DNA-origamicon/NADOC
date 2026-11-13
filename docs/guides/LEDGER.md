# Feature guide ledger

[Guide library](README.md) · [Maintenance](MAINTENANCE.md) · [UX findings](UX_LEDGER.md)

Generated from `catalog.json` and capture manifests. Dates are ISO 8601 with timezone.
Coverage describes the listed workflows, not every subfeature or editor context.
Run `python3 -m scripts.check_feature_guides` for current source freshness;
this table deliberately does not freeze a potentially stale “current” badge.

| Feature | Coverage | First created | Last captured | Guide / scope |
|---|---|---|---|---|
| **Design and Editing** | | | | |
| Design Readiness | planned | — | — | Not created |
| Lattice Design | planned | — | — | Not created |
| Extrude | partial | 2026-11-11T21:07:37-07:00 | 2026-11-12T22:27:20-07:00 | [extrude](extrude/README.md): Desktop: select a 3×6 cross-section normal to XY/XZ/YZ source planes, then Next for a fitted 3D length preview; Length in bp/nm, forward/reverse direction, scaffold-size recommendations, strand classes and ligation; Apply a 64 bp extrusion, continue a 2×3 end cross-section by 8 bp, then create a separated 3×6 cluster |
| Sweep | planned | — | — | Not created |
| Primitive Library | planned | — | — | Not created |
| Scaffold Routing | planned | — | — | Not created |
| Staple Design | planned | — | — | Not created |
| Strand Editing | planned | — | — | Not created |
| 2D Origami Editor | planned | — | — | Not created |
| Move/Rotate | planned | — | — | Not created |
| Bend and Twist | partial | 2026-11-12T12:43:47-07:00 | 2026-11-12T22:24:33-07:00 | [bend](bend/README.md): Open Tools → Bend on a two-cluster 256 bp design; select one 3×6 cluster and apply two 60° bends in directions 0° and 90° with live plane guides; Generate staple routing and loops/skips with built-in tools; inspect the same marks in Full 3D and the cadnano-style editor |
| Bend and Twist | partial | 2026-11-12T21:24:18-07:00 | 2026-11-12T22:17:07-07:00 | [twist](twist/README.md): Two separated 3×6 square-lattice clusters, each 256 bp long; Tools → Twist and selection of one cluster; Adjacent intervals with 180° right-handed and left-handed total twist; Full Autostaple and Add Loops/Skips; Full 3D loop/skip overlay and cadnano-style editor views |
| Clusters and Joints | planned | — | — | Not created |
| Dimensions | planned | — | — | Not created |
| **Sequences and Ordering** | | | | |
| Sequence Assignment | planned | — | — | Not created |
| Sequence Spreadsheet | planned | — | — | Not created |
| Overhang Sequence Generation | planned | — | — | Not created |
| Ordering and Plates | planned | — | — | Not created |
| **Overhangs and Attachments** | | | | |
| Overhang Design | planned | — | — | Not created |
| Overhang Connections | planned | — | — | Not created |
| Proteins | planned | — | — | Not created |
| Aptamers | planned | — | — | Not created |
| Gold Nanospheres | planned | — | — | Not created |
| Quantum Dots | planned | — | — | Not created |
| Fluorescence | planned | — | — | Not created |
| **Assemblies and Mechanisms** | | | | |
| Assembly Workspace | planned | — | — | Not created |
| Connectors and Mates | planned | — | — | Not created |
| Assembly Strand Connections | planned | — | — | Not created |
| Polymerization | planned | — | — | Not created |
| Gears | planned | — | — | Not created |
| Belts and Pulleys | planned | — | — | Not created |
| **Visualization and Navigation** | | | | |
| Representations | planned | — | — | Not created |
| Coloring | planned | — | — | Not created |
| Comparison Views | planned | — | — | Not created |
| Spatial Views | planned | — | — | Not created |
| Display Overlays | planned | — | — | Not created |
| Selection and Navigation | planned | — | — | Not created |
| **Simulation and Analysis** | | | | |
| Simulation Workspace | planned | — | — | Not created |
| oxDNA | planned | — | — | Not created |
| mrDNA | planned | — | — | Not created |
| CanDo FEM | planned | — | — | Not created |
| SNUPI FEM | planned | — | — | Not created |
| NAMD | planned | — | — | Not created |
| Nanopore Transport | planned | — | — | Not created |
| Trajectory Analysis | planned | — | — | Not created |
| Simulation Health | planned | — | — | Not created |
| Photocrosslink Analysis | blocked | — | — | Experimental CPD workflow; guide execution requires a specifically authorized CPD session. |
| Preliminary CPD Construction | blocked | — | — | Experimental CPD workflow; guide execution requires a specifically authorized CPD session. |
| **Rendering, Animation, and VR** | | | | |
| Photo Mode | planned | — | — | Not created |
| Animation | planned | — | — | Not created |
| Strand Animation | planned | — | — | Not created |
| Native VR | planned | — | — | Not created |
| **Files, History, and Collaboration** | | | | |
| File Management | planned | — | — | Not created |
| Browser Presentation (Experimental) | planned | — | — | Not created |
| Import and Export | planned | — | — | Not created |
| 3D Printing | planned | — | — | Not created |
| Feature History | planned | — | — | Not created |
| Loadouts and Versions | planned | — | — | Not created |
| Workspace Collaboration | planned | — | — | Not created |
| **Automation and Diagnostics** | | | | |
| Automation | planned | — | — | Not created |
| Diagnostics | planned | — | — | Not created |
