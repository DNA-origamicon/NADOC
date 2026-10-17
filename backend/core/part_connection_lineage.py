"""Bounded material ancestry through validated native connection stages.

No geometry construction, placement inference, snapshots in command inputs or
per-nucleotide expansion. Whole domains move only with an admitted native owner;
linker material changes only inside its declared output/removal namespace.
"""

from dataclasses import replace

from backend.core.part_group_lineage import (
    _Budget, _Group, _Interval, _Plan, _coverage, _groups, _inventory, apply_lineage,
)
from backend.core.part_command_errors import CommandContractError
from backend.core.part_structure_gate import require_valid_structure

ROLE = 'native-connection-material'


def _fail(detail):
    raise CommandContractError(detail, code='unsupported_connection_lineage')


def _domains(design, budget):
    helices, _, intervals, _ = _inventory(design, budget)
    records = {(s.id, i): (d.helix_id, d.direction, d.start_bp, d.end_bp)
               for s in design.strands for i, d in enumerate(s.domains)}
    return helices, intervals, records


class ConnectionLineage:
    def __init__(self, source):
        self.budget = _Budget()
        helices, intervals, self.current = _domains(source, self.budget)
        self.groups = _groups(source.group_organization, helices,
                              {s.id: len(s.domains) for s in source.strands}, self.budget)
        self.origins = {ref: ref for ref in self.current}
        self.original = dict(self.current)
        self.helices = helices
        self.plan = _Plan(ROLE, frozenset(helices), tuple((k, tuple(v)) for k, v in intervals.items()), self.groups)
        self.finished = False

    def advance(self, before, after, *, moved=None, added_linker=None, removed_linker=None):
        if self.finished:
            _fail('Completed connection lineage cannot be reused')
        old_helices, _, old = _domains(before, self.budget)
        helices, _, new = _domains(after, self.budget)
        if old != self.current or old_helices != self.helices:
            _fail('Native connection changed material outside its observed stage')
        moved_ref = None if moved is None else (moved['strand_id'], moved['domain_index'])
        if moved_ref is not None and (moved_ref not in old or moved_ref not in new):
            _fail('Native direct transport lost its declared domain')
        if sum(value is not None for value in (moved, added_linker, removed_linker)) != 1:
            _fail('Native connection stage requires exactly one owned material change')
        removed, added = old.keys() - new.keys(), new.keys() - old.keys()
        if removed and (removed_linker is None or any(not ref[0].startswith(f'__lnk__{removed_linker}') for ref in removed)):
            _fail('Native connection removed undeclared material')
        if added and (added_linker is None or any(not ref[0].startswith(f'__lnk__{added_linker}') for ref in added)):
            _fail('Native connection introduced undeclared material')
        for ref in old.keys() & new.keys():
            if old[ref] == new[ref]:
                continue
            if ref != moved_ref or abs(old[ref][3] - old[ref][2]) != abs(new[ref][3] - new[ref][2]):
                _fail('Native connection changed an undeclared domain or its length')
        allowed_removed = {old[moved_ref][0]} if moved_ref is not None else ({f'__lnk__{removed_linker}'} if removed_linker else set())
        allowed_added = {new[moved_ref][0]} if moved_ref is not None else ({f'__lnk__{added_linker}'} if added_linker else set())
        if not old_helices - helices <= allowed_removed or not helices - old_helices <= allowed_added:
            _fail('Native connection changed undeclared helix identities')
        self.origins = {ref: self.origins.get(ref) for ref in new}
        self.current, self.helices = new, helices

    def finish(self, result):
        if self.finished:
            _fail('Completed connection lineage cannot be reused')
        self.finished = True
        # The final native reconcile/retry may merge/rename domains, but must
        # conserve all observed directional material and helix identities.
        helices, material, _ = _domains(result, self.budget)
        if helices != self.helices:
            _fail('Native postprocessing changed observed helix identities')
        ancestry, expected = {}, {}
        for ref, (hid, direction, start, end) in self.current.items():
            key = hid, direction
            interval = _Interval(min(start, end), max(start, end), ref)
            expected.setdefault(key, []).append(interval)
            origin = self.origins[ref]
            if origin is not None:
                ancestry.setdefault(key, []).append(replace(interval, ref=origin))
        expected = {key: sorted(records, key=lambda r: r.lo) for key, records in expected.items()}
        if set(material) != set(expected) or any(_coverage(material[k]) != _coverage(v) for k, v in expected.items()):
            _fail('Native postprocessing changed observed directional material')
        original_by_host = {}
        for ref, address in self.original.items():
            original_by_host.setdefault(address[0], []).append(ref)
        groups = []
        for group in self.groups:
            if not group.domains and set(group.helices) - helices:
                # Explicit context requests following currently selected material
                # when a host disappears. Convert the ENTIRE group so domain
                # precedence cannot hide retained hosts. Never select the whole
                # destination helix merely because one domain moved onto it.
                refs = []
                for hid in group.helices:
                    self.budget.relation()
                    for ref in original_by_host.get(hid, ()):
                        self.budget.relation()
                        refs.append(ref)
                if not refs:
                    _fail('Removed group hosts have no material descendants')
                refs = tuple(refs)
                groups.append(_Group(group.style, group.helices, refs))
            else:
                groups.append(group)
        plan = replace(self.plan, helices=frozenset(helices), groups=tuple(groups),
                       intervals=tuple((key, tuple(sorted(records, key=lambda r: r.lo))) for key, records in ancestry.items()),
                       material=tuple((key, tuple(sorted(records, key=lambda r: r.lo))) for key, records in expected.items()))
        updated = apply_lineage(plan, result)
        require_valid_structure(updated)
        return updated
