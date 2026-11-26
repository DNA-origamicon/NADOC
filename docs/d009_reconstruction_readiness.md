> Superseded by [partial native reconstruction](d009_partial_reconstruction.md): D009 now has a published partial native design with 194/197 staples. The findings below record the earlier blockers.

# D009 end-to-end reconstruction audit — 2026-11-25

D009 cannot yet be generated end-to-end from the article UI or published by the
native compiler. A fresh PDF-only compilation stops with
`Incomplete directed routing; native construction blocked`. No native reference
was used in this audit and no molecular file was generated.

Source: `shapes-supp.pdf`, diagram page 6 (Figure S6), sequence table page 14,
DOI 10.1038/nature08016. Current evidence is in
`.development-artifacts/d009-end-to-end/audit.json`.

## Verified recovery

- All five lattice insets agree on 46 helices.
- 187 of 197 table staple routes are recovered.
- Both scaffold insertion loops are 39 bases, at helices 30[119] and 42[119].
- All 276 routed unpaired staple bases are assigned as on-helix overhangs:
  193 at 5′ termini, 40 at 3′ termini, and 43 internal.
- Two image-A/table-T disagreements select T under the user's tie-break rule;
  both remain non-blocking source notices.
- Sequence alignment is supported, with heuristic confidence 84.92/100. This
  is not a complete-topology or physical-geometry certificate.

## Remaining blocks

1. **Missing paths:** ten table entries totaling 327 bases have sequences and
   directed endpoints but no recovered diagram route. A bounded search over
   available strand/crossover positions, constrained by those sequences and
   endpoints, must establish unique routes. Such a search is not implemented;
   uniqueness from the available evidence has not yet been demonstrated.
2. **One-base candidate representation:** the drawn scaffold plus loops contains
   7,703 bases; p7704 contains 7,704. The alignment leaves library index 7703
   (zero-based) unrepresented at the nick boundary as a hypothesis; the physical
   location/cause is unverified. The user already permits the penalized candidate,
   but native compilation still rejects any discrepancy and native comparison
   requires the full library sequence. A saved candidate must explicitly record
   its treatment of the unrepresented base, without silently truncating or adding
   sequence/topology. This is an implementation gap in carrying the approved
   uncertainty policy into native authoring.
3. **Native on-helix overhangs:** evidence classification is complete, but the
   compiler has an explicit `AGENT_PROCESS_REQUIRED` gate and its saved-design
   comparison rejects any overhang records. Existing terminal reconciliation
   merges scaffold domains into one min–max range. In D009, 138 unpaired staple
   bases are outside that range and 138 lie in holes inside it. The authoring
   path needs interval-aware coverage, recorded on-helix overhang creation,
   internal-segment support, source-selected sequences and independent replay.
   Ordinary terminal extensions must not substitute for these overhangs.
4. **Product integration:** `/article-reconstruction/check` and `/analyze` exist;
   a native generation endpoint is not wired. The Reconstruct button is explicitly
   disabled. A complete flow still needs generation/progress/error reporting,
   publication through the guard, saved-file reopen/replay and library selection.

After these are implemented, exact route/sequence comparison, saved/reopened
process replay and native bond review must pass on the actual D009 output.
No simulation-ready geometry or successful native D009 publication is claimed.

## Loop handoff fixed during this audit

Analysis already carried supported 39/39 loop counts, while the compiler kept
the two raw unresolved annotations. Both now use the shared
`apply_supported_insertions` helper, preserving original evidence and the one-base
penalty. Tests verify this handoff without clearing the missing-route blocker.

## Table-only paths still needed

Endpoints use the figure's helix labels and directed 5′/3′ base indices.

| Start | End | Bases |
| --- | --- | ---: |
| 2[292] | 19[292] | 26 |
| 4[292] | 5[306] | 37 |
| 6[300] | 13[292] | 48 |
| 8[292] | 9[292] | 26 |
| 12[286] | 13[272] | 28 |
| 15[273] | 7[292] | 34 |
| 16[292] | 17[272] | 34 |
| 18[292] | 17[292] | 26 |
| 19[273] | 3[292] | 34 |
| 20[292] | 21[272] | 34 |
