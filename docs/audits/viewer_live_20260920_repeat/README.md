# Real-browser automation evidence

VoltronCoreArmV2 was opened through the authenticated local controller using the
normal NADOC File → Open lifecycle. No manual file picker or copied log was needed.
The connected browser was Windows Chrome 153 using the NVIDIA RTX 2080 SUPER
through ANGLE/D3D11. Full representation, atomistic/surface off, strand colors,
927 × 833 canvas, device pixel ratio 1. This viewport differs from the user's
earlier pasted runs, so those runs are not a controlled comparison with this batch.

`captures.json` retains one warmup plus five valid 20-second repeatable orbits.
The median of the five per-run mean frame rates is **39.876 FPS** (range
39.274–40.362). Median per-run p95 frame time is **28.700 ms** (range 28.200–29.700).
These are render-loop intervals, not GPU durations. All five last render passes
reported 2,677 draws, 6,069,870 triangles, 30,503 lines, 1,711 geometries, and 195
textures. Camera pose and enabled controls were restored exactly.

`before.png` and `after.png` were captured outside timing and inspected as overview
images. The design and its attached structures are present. Both PNG files have
SHA-256 `bdf6ad1fa896d913c60543305c263496ed71592ae6d45fa5056f647b9b0d71e3`.
This supports restoration of the overview; it does not establish atomic geometry,
trajectory content, close-up visual parity, or a browser/OS matrix.

The build hash is `0fc46aeb32d951710d024635b4a80befe3e7297c04d6014bf4ebe257ad8c2ee2`;
fixture document hash is `7afd7103269830f4bf25a5ccd93551b664c6e4e123b3f250e215ce30d7f46561`.
This is **current-build repeatability evidence**, not frozen-baseline A/B acceptance.
The controller's compare command rejects comparing this batch with itself because
both sides identify the same frontend build.

The preceding `../viewer_live_20260920` attempt is deliberately retained as failure
evidence: a document refresh invalidated its second measured run, the controller
stopped, and partial records were preserved. No invalid sample was included above.

Reproduction after opening the desired browser tab:

```bash
node scripts/viewer_test.mjs capture --file VoltronCoreArmV2.nadoc --runs 5 --warmups 1 --seconds 20 --output /absolute/path/to/new-evidence
```

Complete edits before measuring; changing Python files can restart a development
backend and refresh the document even if frontend sources remain unchanged.
