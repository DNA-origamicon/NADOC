# Operation coverage and implementation batches

As inspected October 14, 2026. A dispatcher branch is an implementation foothold, not a regeneration certificate. All entries still require the phase 1 transaction/registry contract and phase 2 verifier. P3 and P4 below refer to the family completion phases in [the plan](README.md).

Literal recording sites are direct calls identified by the AST inventory; dynamic forwarding, aliases, copied entries, and generated commands can record additional kinds. “No literal site” means inspect those paths and persisted fixtures before considering removal. Multiple sites may represent different hosts or recording behavior.

## Snapshot operations

| Kind | Command replay or special path | Literal recording sites | Completion batch |
|---|---|---|---|
| `apply-loop-skips` | No branch in the three general dispatchers | [crud.py:9936](../../../backend/api/crud.py#L9936) | P3 |
| `aptamer-import` | No branch in the three general dispatchers | [routes_design_interchange.py:516](../../../backend/api/routes_design_interchange.py#L516) | P4 |
| `assembly-add-connector` | Assembly dispatcher | [routes_assembly_connectors.py:87](../../../backend/api/routes_assembly_connectors.py#L87) | P4 |
| `assembly-add-instance` | Assembly dispatcher | [assembly.py:611](../../../backend/api/assembly.py#L611) | P4 |
| `assembly-add-joint` | Assembly dispatcher | [routes_assembly_joints.py:369](../../../backend/api/routes_assembly_joints.py#L369) | P4 |
| `assembly-create-belt` | No branch in the three general dispatchers | [routes_assembly_belts.py:149](../../../backend/api/routes_assembly_belts.py#L149) | P4 |
| `assembly-create-belt-rider` | No branch in the three general dispatchers | [routes_assembly_belts.py:264](../../../backend/api/routes_assembly_belts.py#L264) | P4 |
| `assembly-create-gear` | No branch in the three general dispatchers | [routes_assembly_gears.py:151](../../../backend/api/routes_assembly_gears.py#L151) | P4 |
| `assembly-create-group` | No branch in the three general dispatchers | [routes_assembly_groups.py:125](../../../backend/api/routes_assembly_groups.py#L125) | P4 |
| `assembly-create-mate` | No branch in the three general dispatchers | [routes_assembly_joints.py:457](../../../backend/api/routes_assembly_joints.py#L457) | P4 |
| `assembly-delete-belt` | No branch in the three general dispatchers | [routes_assembly_belts.py:194](../../../backend/api/routes_assembly_belts.py#L194) | P4 |
| `assembly-delete-belt-rider` | No branch in the three general dispatchers | [routes_assembly_belts.py:284](../../../backend/api/routes_assembly_belts.py#L284) | P4 |
| `assembly-delete-connector` | Assembly dispatcher | [routes_assembly_connectors.py:126](../../../backend/api/routes_assembly_connectors.py#L126) | P4 |
| `assembly-delete-gear` | No branch in the three general dispatchers | [routes_assembly_gears.py:193](../../../backend/api/routes_assembly_gears.py#L193) | P4 |
| `assembly-delete-group` | No branch in the three general dispatchers | [routes_assembly_groups.py:287](../../../backend/api/routes_assembly_groups.py#L287) | P4 |
| `assembly-delete-instance` | Assembly dispatcher | [assembly.py:2724](../../../backend/api/assembly.py#L2724) | P4 |
| `assembly-delete-joint` | Assembly dispatcher | [routes_assembly_joints.py:760](../../../backend/api/routes_assembly_joints.py#L760) | P4 |
| `assembly-duplex-add` | No branch in the three general dispatchers | [routes_assembly_overhangs.py:952](../../../backend/api/routes_assembly_overhangs.py#L952) | P4 |
| `assembly-duplex-connect` | No branch in the three general dispatchers | [routes_assembly_overhangs.py:1039](../../../backend/api/routes_assembly_overhangs.py#L1039) | P4 |
| `assembly-duplex-delete` | No branch in the three general dispatchers | [routes_assembly_overhangs.py:1127](../../../backend/api/routes_assembly_overhangs.py#L1127) | P4 |
| `assembly-duplex-patch` | No branch in the three general dispatchers | [routes_assembly_overhangs.py:1111](../../../backend/api/routes_assembly_overhangs.py#L1111) | P4 |
| `assembly-duplex-sync` | No branch in the three general dispatchers | [routes_assembly_overhangs.py:1062](../../../backend/api/routes_assembly_overhangs.py#L1062) | P4 |
| `assembly-duplicate-group` | No branch in the three general dispatchers | [routes_assembly_groups.py:243](../../../backend/api/routes_assembly_groups.py#L243) | P4 |
| `assembly-duplicate-instance` | Assembly dispatcher | [assembly.py:2686](../../../backend/api/assembly.py#L2686) | P4 |
| `assembly-overhang-bind` | Assembly advertised ONLY; missing branch | [routes_assembly_overhangs.py:178](../../../backend/api/routes_assembly_overhangs.py#L178) | P4 |
| `assembly-overhang-bind-patch` | Assembly advertised ONLY; missing branch | [routes_assembly_overhangs.py:211](../../../backend/api/routes_assembly_overhangs.py#L211) | P4 |
| `assembly-overhang-connection-add` | Assembly dispatcher | [routes_assembly_overhangs.py:439](../../../backend/api/routes_assembly_overhangs.py#L439) | P4 |
| `assembly-overhang-connection-delete` | Assembly advertised ONLY; missing branch | [routes_assembly_overhangs.py:601](../../../backend/api/routes_assembly_overhangs.py#L601) | P4 |
| `assembly-overhang-connection-patch` | Assembly dispatcher | [routes_assembly_overhangs.py:564](../../../backend/api/routes_assembly_overhangs.py#L564) | P4 |
| `assembly-overhang-connection-relax` | No branch in the three general dispatchers | [routes_assembly_overhangs.py:691](../../../backend/api/routes_assembly_overhangs.py#L691)<br>[routes_assembly_overhangs.py:776](../../../backend/api/routes_assembly_overhangs.py#L776) | P4 |
| `assembly-overhang-unbind` | Assembly advertised ONLY; missing branch | [routes_assembly_overhangs.py:232](../../../backend/api/routes_assembly_overhangs.py#L232) | P4 |
| `assembly-patch-group` | No branch in the three general dispatchers | [routes_assembly_groups.py:196](../../../backend/api/routes_assembly_groups.py#L196) | P4 |
| `assembly-polymerize` | Assembly dispatcher | [routes_assembly_polymerize.py:161](../../../backend/api/routes_assembly_polymerize.py#L161) | P4 |
| `assembly-polymerize-belt` | No branch in the three general dispatchers | [routes_assembly_belts.py:363](../../../backend/api/routes_assembly_belts.py#L363) | P4 |
| `assembly-polymerize-periodic` | Assembly dispatcher | [routes_assembly_polymerize.py:298](../../../backend/api/routes_assembly_polymerize.py#L298) | P4 |
| `assembly-transform-group` | No branch in the three general dispatchers | [routes_assembly_groups.py:354](../../../backend/api/routes_assembly_groups.py#L354) | P4 |
| `assembly-transform-instance` | Assembly dispatcher | [assembly.py:698](../../../backend/api/assembly.py#L698)<br>[assembly.py:1334](../../../backend/api/assembly.py#L1334) | P4 |
| `assembly-transform-instance-cluster` | No branch in the three general dispatchers | [assembly.py:1387](../../../backend/api/assembly.py#L1387) | P4 |
| `assembly-ungroup` | No branch in the three general dispatchers | [routes_assembly_groups.py:153](../../../backend/api/routes_assembly_groups.py#L153) | P4 |
| `assign-scaffold-sequence` | No branch in the three general dispatchers | [routes_assign_sequences.py:121](../../../backend/api/routes_assign_sequences.py#L121) | P3 |
| `assign-staple-sequences` | No branch in the three general dispatchers | [routes_assign_sequences.py:385](../../../backend/api/routes_assign_sequences.py#L385) | P3 |
| `auto-break` | No branch in the three general dispatchers | [crud.py:6098](../../../backend/api/crud.py#L6098) | P3 |
| `auto-crossover` | No branch in the three general dispatchers | [crud.py:3617](../../../backend/api/crud.py#L3617) | P3 |
| `auto-merge` | No branch in the three general dispatchers | [crud.py:6120](../../../backend/api/crud.py#L6120) | P3 |
| `auto-scaffold` | No branch in the three general dispatchers | No literal site; inspect dynamic paths | P3 |
| `auto-scaffold-matched` | No branch in the three general dispatchers | No literal site; inspect dynamic paths | P3 |
| `auto-scaffold-seamed` | No branch in the three general dispatchers | No literal site; inspect dynamic paths | P3 |
| `auto-scaffold-seamless` | No branch in the three general dispatchers | No literal site; inspect dynamic paths | P3 |
| `autorefine-skips` | No branch in the three general dispatchers | [routes_autorefine.py:231](../../../backend/api/routes_autorefine.py#L231) | P3 |
| `bundle-create` | Part dispatcher | [crud.py:1532](../../../backend/api/crud.py#L1532) | P3 |
| `cando-autorefine-marks` | No branch in the three general dispatchers | [routes_cando_autorefine.py:220](../../../backend/api/routes_cando_autorefine.py#L220)<br>[backend/core/cando_runner.py:739](../../../backend/core/cando_runner.py#L739) | P3 |
| `circle-segment` | No branch in the three general dispatchers | [crud.py:1256](../../../backend/api/crud.py#L1256) | P3 |
| `circular-pattern` | specialized build/edit; not general dispatcher | No literal site; inspect dynamic paths | P3 |
| `cluster-join` | No branch in the three general dispatchers | [routes_cluster_join.py:76](../../../backend/api/routes_cluster_join.py#L76) | P3 |
| `cluster-paste` | No branch in the three general dispatchers | [routes_clusters.py:402](../../../backend/api/routes_clusters.py#L402) | P3 |
| `cluster-pose` | inspect generated/legacy adapter | No literal site; inspect dynamic paths | P3 |
| `create-far-ends` | No branch in the three general dispatchers | No literal site; inspect dynamic paths | P3 |
| `create-near-ends` | No branch in the three general dispatchers | No literal site; inspect dynamic paths | P3 |
| `curve-path` | inspect generated/legacy adapter | No literal site; inspect dynamic paths | P3 |
| `element-paste` | No branch in the three general dispatchers | [routes_nanoparticles.py:1024](../../../backend/api/routes_nanoparticles.py#L1024) | P3 |
| `extrude-continuation` | Part dispatcher | [crud.py:1378](../../../backend/api/crud.py#L1378) | P3 |
| `extrude-deformed-continuation` | Part dispatcher | [crud.py:1489](../../../backend/api/crud.py#L1489) | P3 |
| `extrude-frame` | inspect generated/legacy adapter | [routes_frame_extrusion.py:93](../../../backend/api/routes_frame_extrusion.py#L93) | P3 |
| `extrude-segment` | Part dispatcher | [crud.py:1193](../../../backend/api/crud.py#L1193) | P3 |
| `flexible-relax` | No branch in the three general dispatchers | [routes_flexible_segments.py:180](../../../backend/api/routes_flexible_segments.py#L180) | P4 |
| `flexible-segment-mark` | No branch in the three general dispatchers | No literal site; inspect dynamic paths | P3 |
| `flexible-segment-unmark` | No branch in the three general dispatchers | No literal site; inspect dynamic paths | P3 |
| `full-autostaple` | No branch in the three general dispatchers | [routes_assign_sequences.py:510](../../../backend/api/routes_assign_sequences.py#L510) | P3 |
| `generate-design` | inspect generated/legacy adapter | No literal site; inspect dynamic paths | P3 |
| `linear-pattern` | specialized build/edit; not general dispatcher | No literal site; inspect dynamic paths | P3 |
| `linker-add` | No branch in the three general dispatchers | [routes_overhang_connections.py:149](../../../backend/api/routes_overhang_connections.py#L149) | P3 |
| `linker-delete` | No branch in the three general dispatchers | [routes_overhang_connections.py:343](../../../backend/api/routes_overhang_connections.py#L343) | P3 |
| `nanoparticle-attach-overhang` | No branch in the three general dispatchers | [routes_nanoparticle_attachment.py:70](../../../backend/api/routes_nanoparticle_attachment.py#L70) | P4 |
| `nanoparticle-biotin-dna` | No branch in the three general dispatchers | [routes_nanoparticles.py:977](../../../backend/api/routes_nanoparticles.py#L977)<br>[routes_nanoparticles.py:992](../../../backend/api/routes_nanoparticles.py#L992) | P4 |
| `nanoparticle-conjugate` | No branch in the three general dispatchers | [routes_nanoparticles.py:354](../../../backend/api/routes_nanoparticles.py#L354) | P4 |
| `nanoparticle-conjugation-delete` | No branch in the three general dispatchers | [routes_nanoparticles.py:382](../../../backend/api/routes_nanoparticles.py#L382) | P4 |
| `nanoparticle-connection-relax` | No branch in the three general dispatchers | [routes_nanoparticles.py:891](../../../backend/api/routes_nanoparticles.py#L891) | P4 |
| `nanoparticle-connection-version-create` | No branch in the three general dispatchers | [routes_nanoparticles.py:820](../../../backend/api/routes_nanoparticles.py#L820) | P4 |
| `nanoparticle-connection-version-delete` | No branch in the three general dispatchers | [routes_nanoparticles.py:863](../../../backend/api/routes_nanoparticles.py#L863) | P4 |
| `nanoparticle-connection-version-patch` | No branch in the three general dispatchers | [routes_nanoparticles.py:844](../../../backend/api/routes_nanoparticles.py#L844) | P4 |
| `nanoparticle-create` | No branch in the three general dispatchers | [routes_nanoparticles.py:126](../../../backend/api/routes_nanoparticles.py#L126)<br>[routes_nanoparticles.py:151](../../../backend/api/routes_nanoparticles.py#L151) | P4 |
| `nanoparticle-delete` | No branch in the three general dispatchers | [routes_nanoparticles.py:270](../../../backend/api/routes_nanoparticles.py#L270) | P4 |
| `nanoparticle-patch` | No branch in the three general dispatchers | [routes_nanoparticles.py:229](../../../backend/api/routes_nanoparticles.py#L229) | P4 |
| `nanoparticle-strand-bind` | No branch in the three general dispatchers | [routes_nanoparticles.py:947](../../../backend/api/routes_nanoparticles.py#L947) | P4 |
| `nick` | inspect generated/legacy adapter | [crud.py:4677](../../../backend/api/crud.py#L4677) | P3 |
| `nucleotide-transform` | No branch in the three general dispatchers | [routes_nucleotide_transforms.py:155](../../../backend/api/routes_nucleotide_transforms.py#L155) | P3 |
| `nucleotide-transform-batch` | No branch in the three general dispatchers | [routes_nucleotide_transforms.py:203](../../../backend/api/routes_nucleotide_transforms.py#L203) | P3 |
| `nucleotide-transform-delete` | No branch in the three general dispatchers | [routes_nucleotide_transforms.py:244](../../../backend/api/routes_nucleotide_transforms.py#L244) | P3 |
| `overhang-bulk` | No branch in the three general dispatchers | [assembly.py:1776](../../../backend/api/assembly.py#L1776)<br>[crud.py:2766](../../../backend/api/crud.py#L2766)<br>[crud.py:2800](../../../backend/api/crud.py#L2800)<br>[crud.py:2829](../../../backend/api/crud.py#L2829)<br>[crud.py:6156](../../../backend/api/crud.py#L6156)<br>[crud.py:6342](../../../backend/api/crud.py#L6342)<br>[crud.py:6722](../../../backend/api/crud.py#L6722)<br>[crud.py:6862](../../../backend/api/crud.py#L6862)<br>[crud.py:6974](../../../backend/api/crud.py#L6974)<br>[crud.py:7114](../../../backend/api/crud.py#L7114)<br>[crud.py:7174](../../../backend/api/crud.py#L7174)<br>[crud.py:7331](../../../backend/api/crud.py#L7331)<br>[crud.py:7410](../../../backend/api/crud.py#L7410)<br>[routes_connection_versions.py:483](../../../backend/api/routes_connection_versions.py#L483)<br>[routes_overhang_bindings.py:191](../../../backend/api/routes_overhang_bindings.py#L191)<br>[routes_overhang_bindings.py:441](../../../backend/api/routes_overhang_bindings.py#L441)<br>[routes_overhang_bindings.py:616](../../../backend/api/routes_overhang_bindings.py#L616)<br>[routes_overhang_sequences.py:122](../../../backend/api/routes_overhang_sequences.py#L122) | P3 |
| `overhang-extrude` | Part dispatcher | [assembly.py:1713](../../../backend/api/assembly.py#L1713)<br>[crud.py:5221](../../../backend/api/crud.py#L5221) | P3 |
| `overhang-sequence` | No branch in the three general dispatchers | [crud.py:5326](../../../backend/api/crud.py#L5326)<br>[routes_overhang_sequences.py:91](../../../backend/api/routes_overhang_sequences.py#L91) | P3 |
| `photoproduct-create` | No branch in the three general dispatchers | [routes_photoproducts.py:135](../../../backend/api/routes_photoproducts.py#L135)<br>[routes_photoproducts.py:197](../../../backend/api/routes_photoproducts.py#L197) | P3 |
| `photoproduct-delete` | No branch in the three general dispatchers | [routes_photoproducts.py:162](../../../backend/api/routes_photoproducts.py#L162) | P3 |
| `photoproduct-relax` | No branch in the three general dispatchers | [routes_photoproducts.py:222](../../../backend/api/routes_photoproducts.py#L222) | P4 |
| `protein-attach` | No branch in the three general dispatchers | [routes_protein.py:462](../../../backend/api/routes_protein.py#L462) | P4 |
| `protein-attach-delete` | No branch in the three general dispatchers | [routes_protein.py:366](../../../backend/api/routes_protein.py#L366)<br>[routes_protein.py:941](../../../backend/api/routes_protein.py#L941) | P4 |
| `protein-attach-patch` | No branch in the three general dispatchers | [routes_protein.py:851](../../../backend/api/routes_protein.py#L851) | P4 |
| `protein-conjugate` | No branch in the three general dispatchers | [routes_protein.py:668](../../../backend/api/routes_protein.py#L668) | P4 |
| `protein-import` | No branch in the three general dispatchers | [routes_design_interchange.py:384](../../../backend/api/routes_design_interchange.py#L384) | P4 |
| `route-for-polymerization` | No branch in the three general dispatchers | No literal site; inspect dynamic paths | P3 |
| `strand-sequence` | No branch in the three general dispatchers | [crud.py:5970](../../../backend/api/crud.py#L5970) | P3 |
| `sweep` | Part dispatcher; specialized downstream edit | [routes_sweep.py:53](../../../backend/api/routes_sweep.py#L53) | P3 |

## Fine Routing children

| Subtype | Command replay | Literal recording sites | Completion batch |
|---|---|---|---|
| `crossover-delete` | Minor dispatcher | [crud.py:4388](../../../backend/api/crud.py#L4388) | P3 |
| `crossover-delete-batch` | Recorded diff restoration; no minor dispatcher branch | [crud.py:4430](../../../backend/api/crud.py#L4430) | P3 |
| `crossover-extra-bases` | Recorded diff restoration; no minor dispatcher branch | [crud.py:4527](../../../backend/api/crud.py#L4527) | P3 |
| `crossover-extra-bases-batch` | Recorded diff restoration; no minor dispatcher branch | [crud.py:4480](../../../backend/api/crud.py#L4480) | P3 |
| `crossover-move` | Recorded diff restoration; no minor dispatcher branch | [crud.py:4114](../../../backend/api/crud.py#L4114) | P3 |
| `crossover-move-batch` | Recorded diff restoration; no minor dispatcher branch | [crud.py:4354](../../../backend/api/crud.py#L4354) | P3 |
| `crossover-place` | Minor dispatcher | [crud.py:3494](../../../backend/api/crud.py#L3494) | P3 |
| `crossover-place-batch` | Minor dispatcher | [crud.py:3558](../../../backend/api/crud.py#L3558) | P3 |
| `domain-add` | Recorded diff restoration; no minor dispatcher branch | [crud.py:3050](../../../backend/api/crud.py#L3050) | P3 |
| `domain-delete` | Minor dispatcher | [crud.py:3091](../../../backend/api/crud.py#L3091) | P3 |
| `domain-shift` | Minor dispatcher | [crud.py:2923](../../../backend/api/crud.py#L2923) | P3 |
| `forced-ligation-create` | Recorded diff restoration; no minor dispatcher branch | [crud.py:4921](../../../backend/api/crud.py#L4921) | P3 |
| `forced-ligation-delete` | Recorded diff restoration; no minor dispatcher branch | [crud.py:4999](../../../backend/api/crud.py#L4999) | P3 |
| `forced-ligation-delete-batch` | Recorded diff restoration; no minor dispatcher branch | [crud.py:5074](../../../backend/api/crud.py#L5074) | P3 |
| `forced-ligation-extra-bases` | Recorded diff restoration; no minor dispatcher branch | [crud.py:4569](../../../backend/api/crud.py#L4569) | P3 |
| `helix-add` | Recorded diff restoration; no minor dispatcher branch | [crud.py:2188](../../../backend/api/crud.py#L2188) | P3 |
| `helix-add-at-cell` | Recorded diff restoration; no minor dispatcher branch | [crud.py:2336](../../../backend/api/crud.py#L2336)<br>[routes_frame_cells.py:20](../../../backend/api/routes_frame_cells.py#L20) | P3 |
| `helix-delete` | Minor dispatcher | [crud.py:2536](../../../backend/api/crud.py#L2536) | P3 |
| `helix-extend` | Recorded diff restoration; no minor dispatcher branch | [crud.py:2505](../../../backend/api/crud.py#L2505) | P3 |
| `helix-reorder` | Recorded diff restoration; no minor dispatcher branch | [crud.py:2393](../../../backend/api/crud.py#L2393) | P3 |
| `helix-update` | Recorded diff restoration; no minor dispatcher branch | [crud.py:2430](../../../backend/api/crud.py#L2430) | P3 |
| `joint-delete` | Minor dispatcher | [routes_cluster_joints.py:307](../../../backend/api/routes_cluster_joints.py#L307) | P3 |
| `joint-place` | Minor dispatcher | [routes_cluster_joints.py:204](../../../backend/api/routes_cluster_joints.py#L204) | P3 |
| `joint-update` | Minor dispatcher | [routes_cluster_joints.py:288](../../../backend/api/routes_cluster_joints.py#L288) | P3 |
| `ligate` | Recorded diff restoration; no minor dispatcher branch | [crud.py:4746](../../../backend/api/crud.py#L4746)<br>[crud.py:4833](../../../backend/api/crud.py#L4833) | P3 |
| `loop-skip-bend` | Recorded diff restoration; no minor dispatcher branch | [routes_loop_skip.py:199](../../../backend/api/routes_loop_skip.py#L199) | P3 |
| `loop-skip-insert` | Recorded diff restoration; no minor dispatcher branch | [routes_loop_skip.py:92](../../../backend/api/routes_loop_skip.py#L92) | P3 |
| `loop-skip-twist` | Recorded diff restoration; no minor dispatcher branch | [routes_loop_skip.py:142](../../../backend/api/routes_loop_skip.py#L142) | P3 |
| `nick` | Minor dispatcher | [crud.py:4677](../../../backend/api/crud.py#L4677) | P3 |
| `nick-batch` | Minor dispatcher | [crud.py:5120](../../../backend/api/crud.py#L5120) | P3 |
| `scaffold-domain-paint` | Recorded diff restoration; no minor dispatcher branch | [crud.py:2644](../../../backend/api/crud.py#L2644) | P3 |
| `strand-add` | Recorded diff restoration; no minor dispatcher branch | [crud.py:2696](../../../backend/api/crud.py#L2696) | P3 |
| `strand-delete` | Minor dispatcher | [crud.py:3018](../../../backend/api/crud.py#L3018) | P3 |
| `strand-delete-batch` | Minor dispatcher | [crud.py:2978](../../../backend/api/crud.py#L2978) | P3 |
| `strand-end-resize` | Minor dispatcher | [crud.py:2861](../../../backend/api/crud.py#L2861) | P3 |
| `strand-patch` | Recorded diff restoration; no minor dispatcher branch | [crud.py:5979](../../../backend/api/crud.py#L5979) | P3 |
| `strand-update` | Recorded diff restoration; no minor dispatcher branch | [crud.py:2738](../../../backend/api/crud.py#L2738) | P3 |
| `strands-color-bulk` | Recorded diff restoration; no minor dispatcher branch | [crud.py:6033](../../../backend/api/crud.py#L6033) | P3 |
| `strands-reference` | Recorded diff restoration; no minor dispatcher branch | [crud.py:6073](../../../backend/api/crud.py#L6073) | P3 |

## Non snapshot feature families

| Type | Existing mechanism | Required completion |
|---|---|---|
| `deformation` | Saved operation plus seek overlay and specialized edit | Full parameter/reference contract, stable targets, dependent continuation/sweep rebuild |
| `cluster_op` | Absolute pose overlay and specialized edit | Cluster existence/membership/parent dependencies and typed pose effects |
| `cluster_create` | Group definition and optional snapshot | Stable identity, member/domain/parent reference validation and regroup/delete semantics |
| `overhang_rotation` | Whole-overhang and subdomain orientation batches | Complete input cardinality, stable subdomain identities and dependent pose effects |
| `routing-cluster` | Grouped child diffs and full snapshots | Group is organizational; verify every child command and propagate failures through children |
| Legacy checkpoint/top-level minor | Removed by Design loader | Raw-load diagnostics; never silently certify discarded construction |

All ordinary operation rows need independent editor capability information. Native operation names and a snapshot are not sufficient proof of editability. Pure deletion operations can expose their targets rather than numerical parameters; high-level generators may expose child commands or a supported parameterized recipe. The registry must state the actual contract.

## Mutation and route inventory

`inventory.json` contains each candidate call with path, function, line, qualified call expression and literal/dynamic kind, plus every route decorator and its direct calls. Review the complete candidate list when closing mutation bypasses. Do not count generic `snapshot()` name matches as design mutations without inspecting the receiver.
