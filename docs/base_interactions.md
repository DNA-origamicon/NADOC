# Atomistic base interactions

Representation Options → **Hydrogen bonds & base stacking** displays contacts
between standard nucleobases in the atomistic renderer. Cyan dashed segments join
hydrogen-bond donor/acceptor heavy atoms; amber dashed segments join stacked base
centroids. The checkbox is a session display preference. In Ball & Stick or Stick,
a single selected base automatically shows its contacts even with the checkbox off.
Clearing or broadening that selection removes the automatic overlay. With the
checkbox on, contacts throughout the rendered atom set remain visible.

These are geometric annotations, not energetic measurements or authored bonds.
No molecular coordinates, topology, or feature history change. Display conventions
are inspired by the [Mol* interaction display](https://molstar.org/viewer-docs/faqs-scenarios/);
the following deliberately bounded nucleobase detector is not Mol*'s full chemical
perception implementation.

* Standard neutral A/G/C/T/U chemistry is recognized from named ring and exocyclic
  atoms. Explicitly modified residues, incomplete or unnamed rings are skipped.
* Hydrogen bonds require a 0.24–0.35 nm heavy-atom separation, the contact direction
  within 30° of each base plane, and at least 90° between the contact and every
  bonded heavy neighbor of both donor and acceptor. Hydrogens need not be present.
* Stacking requires centroid distance ≤0.55 nm, plane normals within 30° (parallel
  or antiparallel), separation along each normal of 0.25–0.45 nm, and lateral offset
  ≤0.25 nm in both planes. This detects face stacking, not edge-to-face contacts.
* The base plane comes from N1/C2/C6, with all ring atoms within 0.04 nm of that
  plane; the centroid includes both fused rings for purines.

The overlay reads live atom-instance positions and excludes hidden atoms. Contacts
are recomputed on coordinate and visibility updates. A spatial grid bounds the
pair search; unchanged renderer state reuses the overlay. Atom payloads without
names cannot support chemical contact detection. Protein/solvent interactions and
contacts across separate renderer instances are outside this detector. The assembly
shared GPU batch uses a separate rendering path and is not covered by this overlay.

Tests: `frontend/src/scene/atomistic_renderer/base_interactions.test.js`,
`frontend/src/ui/repr_option_sliders.test.js`, and the read-only app regression
`frontend/e2e/base_interactions.spec.js`.
