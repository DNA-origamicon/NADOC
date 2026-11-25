"""Small replay-verified specimen for the extension-slab app regression."""
import sys
from pathlib import Path
from backend.core.models import Design
from backend.api import crud, routes_extensions, routes_animations, state
from backend.api.doc_context import set_current_doc, reset_current_doc
from scripts.agent_structure_guard import publish, audit


def create(path):
    token = set_current_doc('__e2e__extension-slab-fixture')
    try:
        crud.create_bundle(crud.BundleRequest(cells=[[0, 0]], length_bp=8,
            ligate_adjacent=False, name='__e2e__extension-slabs'))
        design = state.get_or_404()
        for strand in design.strands:
            for end in ('five_prime', 'three_prime'):
                routes_extensions.add_strand_extension(routes_extensions.StrandExtensionRequest(
                    strand_id=strand.id, end=end, sequence='ACGT', modification='cy3'))
        routes_animations.create_animation(routes_animations.CreateAnimationBody(ensure_default=True))
        result = publish(state.get_or_404(), path)
        audit(Design.model_validate_json(Path(path).read_text()))
        return {key: result[key] for key in ('status', 'commands', 'physical_reference_checked', 'sha256')}
    finally:
        state.drop_doc('__e2e__extension-slab-fixture')
        reset_current_doc(token)


if __name__ == '__main__':
    print(create(sys.argv[1]))
