---
name: Polymerization strands and extension geometry scope
description: Preserve polymerization strand identity; Full extension attachment and deferred long-tail geometry are distinct issues
type: feedback
authority: canonical
status: active
---

# November 2, 2026 user decisions

Polymerization strands require dedicated simulation treatment. Do not convert
them to ordinary `StrandExtension` objects. There is no user-facing convert
overhang-to-extension feature, and automated construction may not invent one.
The existing `assembly_flatten._materialize_periodic_strands` conversion is an
implementation defect, not an approved physical policy. Do not truncate strands,
discard their missing halves, restore synthetic duplex tails, or change molecular
placement as an inferred replacement. Track dedicated handling under ISSUE-163.
The user explicitly chose **“Track the conversion change as follow-on work”**
instead of adding an immediate unsupported-case refusal. Leave the production
simulation preparation path unchanged in this correction; ISSUE-163 remains a
deferred defect, not accepted conversion semantics.

For the retained **01 Terminal linker** review, Full representation incorrectly
connects position 1 of staple **S37** to **Extension - 0[-5›16]**. The user specifies
the connection to **Extension - 0[-5›1]**, consistent with atomistic representations.
This is display connectivity, ISSUE-162; correcting it does not validate the
conversion or approve any new atomic placement.

Extensions were intended to be short. General long-extension conformations,
internal ring piercings, clashes and attachment stereochemistry need further
development **after** the feature-log/dependency overhaul. ISSUE-164 owns that
work separately; do not expand FH-27 into a long-tail molecular-geometry project
or promote the isolated linker candidate to close the feature-history milestone.
No maximum extension length or new placement algorithm has been specified.

Describe inspection targets using the exact labels displayed in the base
Properties card, not export chain/residue numbering. The demonstrated internal
piercing is O3′ of **Extension - 0[-5›3]** to P of **Extension - 0[-5›2]**, through
the sugar ring of **Extension - 0[-5›3]**, on staple S37. This is separate from
the S37-to-›1 root connection. Saved diagnostic files remain historical evidence,
not compliant authored part examples.
