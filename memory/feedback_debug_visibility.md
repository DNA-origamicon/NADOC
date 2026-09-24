---
name: feedback_debug_visibility
description: Proactively improve observation conditions during visual debugging; preserve the behavior under test and verify what the user actually sees.
type: feedback
status: active
authority: canonical
---

# Make debugging observable

On 2026-09-22 the user explicitly praised autonomously tilting the Extrude panel for
better viewing and asked to reinforce this approach through durable guidance and skills.

**Preference:** when debugging an interactive feature, independently identify and fix
reversible obstacles to observation within the task. Choose useful orientation, framing,
contrast, trace persistence, review pacing, and viewer visibility rather than waiting
for the user to specify each adjustment. The user's inability to see an expected result
is a debugging failure even if input delivery and state assertions pass.

**Boundary:** preserve the behavior under test. If a viewing parameter is itself being
tested, retain that condition and label any normalized view as a diagnostic alternate.
Do not change physical head tracking, production defaults, hit geometry, human-motion
presets, or acceptance thresholds merely to make the demonstration pass.

The successful Extrude adjustment used observed panel orientation and the tracked eye
to choose a simulated wrist pose through normal panel placement. It improved the view
without hardcoding compensation for the production tilt. Related checks followed input
and state through native eye pixels, mirror downsampling, and actual desktop visibility.
Review holds were outside measured motion; ray-contact traces exposed the interaction
on the panel rather than only showing controller-body movement in front of it.

Reusable Codex skill: [improve-debug-visibility](/home/jojo/.codex/skills/improve-debug-visibility/SKILL.md).
Installed in the personal skills directory for discovery in future sessions; explicit
invocation is `$improve-debug-visibility`. This captures an operational workflow, not a
change to model training. This feedback file retains the core preference in the repository
even if the personal skill is unavailable on another machine.

Read [the inspector runbook](../docs/scrywrite_inspector.md) for current tools and
[human-motion policy](project_vr_human_motion.md) for steady_fast initial testing and
all four presets in final validation. Keep failures and retries visible in reports;
rendered-eye evidence does not establish physical headset comfort or through-lens legibility.
