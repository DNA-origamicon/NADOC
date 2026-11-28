"""Explicit empty-assembly creation inputs and whole-field proof ownership."""
from types import MappingProxyType
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AssemblyRecipeRoot(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    version: int = Field(default=1, strict=True, ge=1, le=1)
    kind: Literal['empty'] = 'empty'
    initial_name: str = 'Untitled'


AUTHORING_FIELDS = frozenset('''dimensions metadata instances joints gear_relations belt_paths belt_riders
    groups assembly_helices assembly_strands overhang_bindings overhang_connections duplexes
    protein_assets protein_attachments configurations configuration_cursor'''.split())
FIELD_ROLES = MappingProxyType({
    **dict.fromkeys(AUTHORING_FIELDS, 'authoring'),
    **dict.fromkeys('view_volumes zoom_volumes annotations annotations_enabled camera_poses animations export_representation'.split(), 'presentation'),
    **dict.fromkeys('feature_log feature_log_cursor recipe_root'.split(), 'history'),
    'id': 'document_identity',
})


def create_empty_assembly(name='Untitled'):
    """Only call at a real new-document boundary; never infer a legacy root."""
    from backend.core.models import Assembly, DesignMetadata
    return Assembly(metadata=DesignMetadata(name=name), recipe_root=AssemblyRecipeRoot(initial_name=name))


def authoring_state(assembly):
    state = assembly.model_dump(mode='json', include=AUTHORING_FIELDS)
    # These two fields are independently remembered display preferences.
    for instance in state['instances']:
        instance.pop('visible', None)
        instance.pop('representation', None)
    # Workspace identity signoff follows the same exclusion as part proof.
    for field in ('identity_last_known_path', 'identity_confirmed_at'):
        state['metadata'].pop(field, None)
    return state
