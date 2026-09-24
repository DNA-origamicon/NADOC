# Sharing lifecycle, following, and atomistic playback

NADOC's local sharing middleware now revokes existing invitations at editor-server
startup and shutdown. This also clears invitations left in the detached host by an
unclean previous exit once NADOC starts again. Revocation ends connected guests via
the existing terminal state message. Guest status checks additionally recognize
403/404 as terminal, alongside 401/410, after a host/session has been replaced.
Transient network failures still allow reconnecting.

Follow is a guest preference across camera pauses, publisher lease handoffs, and
visualization replacements. Its button stays green and can be turned off during a
handoff. Camera application waits for a matching, active camera revision. Guest
navigation, connection loss, and performance benchmarks still release following.

## Reproduced atomistic failure

Read-only local data from the completed `3x6SQ_norm_skips` production job
`9b1151dfca21` supplied two measured DCD frames. The ball-and-stick rendering has
149,666 DNA heavy atoms and 167,851 heavy-atom bonds. Its absolute render patch is
29,558,184 bytes before compression and 8,033,470 bytes after gzip. The previous
16 MiB *raw* limit rejected the patch before publication, leaving guests frozen.
The measured regression explicitly proves the old limit rejects this case and the
updated guest receives matching atom and bond matrices.

Live frames now negotiate `live-large-frames-v1`, allowing up to 128 MiB decoded
patches and 16 million scalar channels. The compressed per-frame network limit stays
16 MiB, with bounded decompression on both host and guest; packets still coalesce to
the latest frame. Recorded clip limits retain their previous defaults. All layers
include the bounded timeline envelope in their request-size budgets. Actual playback
cadence depends on encoding, transfer, and rendering time rather than promising the
editor's frame rate for an 8 MB update.

Validation: 59 targeted frontend tests (including the measured two-frame case), host
and middleware authorization/lifecycle tests, and a production build. The optional
measured regression uses `NADOC_LIVE_ATOM_FIXTURE`; the large-packet host regression
runs without local simulation data. The fixture remains outside the repository.

The browser sharing lifecycle test passed, including the green Follow button and
its retained state through visualization/publication handoffs and native restore.
