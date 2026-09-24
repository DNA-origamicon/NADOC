# Live trajectory synchronization

Fixed two synchronization gaps: the job publisher treated any visible visualization
progress as a reason to stop streaming, even during trajectory prefetch; and the
guest discarded in-flight snapshots whenever another revision arrived, potentially
starving display updates during sustained topology changes. Available trajectory
frames now continue streaming. Completed snapshots can display before catching up
to the latest revision, while private-file replacement and returning to the already
displayed revision still invalidate pending work.

Live packets optionally carry a bounded, validated frame/total/playing descriptor.
The host retains it with the compressed geometry packet and includes it on downloads,
so clients receiving a newer packet than requested also receive its frame counter.
Pause/seek metadata changes publish even when geometry is unchanged. New snapshots
immediately attempt a frame publication. Legacy hosts continue using legacy packets.

A read-only bottom-center guest timeline mirrors the presenter for live trajectories
and reports received source frames for recorded clips. It is disposed with the scene.
Camera following remains independent. The stream coalesces frames; it does not promise
the editor's frame rate on limited connections. Representation sampling is inherited
from the presenter, including coarse atomistic playback.

Validation: targeted frontend regressions, oxDNA display controller tests, live host
and authorization tests, production build, and a Chromium visibility/placement check.

The existing browser sharing lifecycle test also passed (publish, coordinate updates,
private selection, and return to native).
