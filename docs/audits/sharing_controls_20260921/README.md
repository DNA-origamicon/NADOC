# Sharing control styling — 2026-09-21

Historical styling checkpoint: the later [single-invitation workflow](../unified_sharing_20260921.md)
replaces the two create buttons shown here with one publish button and an optional
recorded-trajectory checkbox. The shared NADOC control styling is retained.

The editor Share link and Broadcast to presentation dialogs now use NADOC's
existing `.btn`, `.btn--primary`, `.btn--danger`, `.input` and `.select` primitives.
The earlier unclassed controls inherited the global transparent button reset,
which made useful actions difficult to distinguish from explanatory text.

Create/copy/play actions have primary treatment; open/pause/close actions have
secondary treatment; stop actions use the standard danger treatment. The same
styles cover the broadcast status badge. Dialog spacing, colors, typography,
borders and responsive layout use the existing theme tokens in a scoped stylesheet.
Copy invitation is primary when a password is required; guest/presenter links remain
real links with button styling. Descriptions, status, settings and active invitations
are visually separated. Both create buttons visibly disable during preparation.
No hosting or transport policy changed; main.js LOC delta: 0.

Visual review used the real app on isolated ports 8001/5174, with dummy invitation
status responses and no real host creation, design mutation or tunnel changes.
The temporary browser exercise verified button borders/classes, disabled controls,
modal opening and a 480 px viewport without horizontal overflow. Screenshots were
inspected at desktop size, including the keyboard focus outline:

- [Sharing options](share-options.png)
- [Invitation and playback controls](share-invitation.png)
- [Broadcast options](broadcast-options.png) (captured before adding final spacing
  between the options panel and Start broadcasting)

Full frontend suite: 486 files, 6,727 tests passed. Production build and Ruff lint
passed. Existing build chunk-size warning remains. The temporary visual spec was
removed in a Python finally block; its status responses contained dummy credentials.
The isolated smoke gate passed all 23 tests. Directory inventories for workspace,
.nadoc-projects, .session and playwright_tests were unchanged after teardown; see
[cleanup proof](cleanup.json). The isolated :5174 browser control credential and
disposable Playwright outputs were removed. Only these compact review images and
records are retained.
