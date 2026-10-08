# Scaffold routing across continued helices

Sweep from a selected blunt end extends the existing scaffold and staple chains
in each occupied footprint cell. The new segment has its own helix record and
lattice frame, but the bond joining consecutive bases is an ordinary backbone
connection. The renderer shows the same direction cone as within either segment.
Saving and loading the design must preserve this connection without introducing
a forced-ligation record. Newly added footprint cells have free strand ends at
the attachment plane.

Seamed and seamless autoscaffold operate on connected strand topology. A boundary
between helix records is not a free end when a strand continues across it. Both
routers must preserve those existing connections, including connections recorded
as forced ligations. Forced ligations keep their explicit junction records and
arc presentation; that presentation does not make their endpoints available for
new end turns.

For the `Sweep_test` 6→10 example, the six original duplexes cover bp 0–62 and
continue into six of the ten swept duplexes at bp 63. All twelve existing
scaffold/staple backbone bonds across 62/63 remain intact. Only the four new
duplexes have free ends there. Each routing mode should produce one scaffold
through the entire structure while leaving the staple strands unchanged.

Seamed routing uses interior double crossovers and local end turns. Seamless
routing uses only end turns and closes the path with one buried nick; it must not
introduce an interior double crossover to work around unequal track lengths.
Neither mode may extend or cap a segment's internal attachment boundary. A failed
attempt must retain the original design rather than apply a fragmented or damaged
route. Inserted-base or nonconsecutive forced junctions cannot be collapsed into
ordinary adjacent-base connections.

Continuity is established from authored strand-domain order and attachment or
junction records. Spatial proximity, a shared lattice coordinate, and visible
overlap alone do not create a connection. Routing and rendering must retain this
distinction when geometry is deformed or the design is reloaded.

Regression coverage includes backend continuation, loader, and routing checks;
frontend cone-versus-arc checks; and `frontend/e2e/sweep_scaffold.spec.js`, which
recreates the 6→10 example through the public API, runs both routing modes from
the menu, and checks the topology and rendered bonds before and after reload.
