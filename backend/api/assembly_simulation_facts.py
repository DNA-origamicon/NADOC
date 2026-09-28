"""Cheap recommendation facts; never construct or load a flattened Design."""

from backend.core.models import Design
from backend.physics.oxdna_interface import _strand_nucleotide_order
from backend.physics.oxdna_protein import has_proteins


def simulation_facts(design):
    return has_proteins(design), len(_strand_nucleotide_order(design))


def assembly_simulation_facts(assembly, load_source):
    # A polymer may have thousands of copies but only one source. Count each
    # source once, preserving the same visible-instance scope as flatten_assembly.
    sources = {}
    proteins, count = has_proteins(assembly), 0
    for instance in assembly.instances:
        if not instance.visible:
            continue
        source = instance.source
        key = source.path if source.type == "file" else id(source.design)
        if key not in sources:
            sources[key] = simulation_facts(load_source(source))
        source_proteins, source_count = sources[key]
        proteins |= source_proteins
        count += source_count
    if assembly.assembly_strands:
        linkers = Design(helices=assembly.assembly_helices, strands=assembly.assembly_strands)
        count += simulation_facts(linkers)[1]
    return proteins, count
