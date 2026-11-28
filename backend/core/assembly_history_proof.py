"""Independent assembly command replay. Recovery payloads are never inspected."""
from backend.core.assembly_history_contract import AssemblyRecipeRoot, FIELD_ROLES, authoring_state, create_empty_assembly
from backend.core.part_history_proof import digest
from backend.core.assembly_dependencies import dependencies
from backend.core.part_dependencies import DependencyIndex


def _assess(assembly, *, execute, validate_definition, verify_sources, checkpoint=lambda: None, max_entries=2000, allow_prefix=False):
    result = {'scope': 'assembly', 'contract_version': 1, 'status': 'unverified',
              'verification_scope': 'authoring_reproducibility', 'checked_commands': 0,
              'native_editable': False, 'issues': [],
              'excluded_roles': ['presentation', 'document_identity'],
              'excluded_instance_fields': ['visible', 'representation']}
    issues = result['issues']
    checkpoint()
    missing = set(type(assembly).model_fields) - FIELD_ROLES.keys()
    if missing:
        issues.append({'code': 'unclassified_fields', 'fields': sorted(missing)})
    if assembly.recipe_root is None:
        issues.append({'code': 'missing_recipe_root'})
    elif assembly.recipe_root is not None:
        try:
            AssemblyRecipeRoot.model_validate(assembly.recipe_root.model_dump())
        except ValueError as error:
            issues.append({'code': 'invalid_recipe_root', 'detail': str(error)})
    cursor = assembly.feature_log_cursor
    if cursor != -1 and not allow_prefix:
        issues.append({'code': 'historical_cursor'})
    elif cursor != -1 and cursor != -2 and not 0 <= cursor < len(assembly.feature_log):
        issues.append({'code': 'invalid_history_cursor'})
    if cursor != -1 and allow_prefix:
        result.update(verification_scope='displayed_prefix_reproducibility', assessed_cursor=cursor)
    if len(assembly.feature_log) > max_entries:
        issues.append({'code': 'entry_limit'})
    if issues:
        return result
    rows = assembly.feature_log
    identities = set()
    graph = DependencyIndex()
    for entry in rows:
        checkpoint()
        if entry.id in identities:
            issues.append({'code': 'duplicate_feature_id', 'feature_id': entry.id})
            return result
        identities.add(entry.id)
        if entry.feature_type != 'snapshot':
            issues.append({'code': 'unsupported_feature_type', 'feature_id': entry.id})
            return result
        try:
            validate_definition(entry.op_kind, entry.params)
        except ValueError as error:
            issues.append({'code': 'invalid_command', 'feature_id': entry.id, 'detail': str(error)})
            return result
        contract = dependencies(entry.op_kind, entry.params, suppressed=entry.suppressed)
        graph.append(entry.id, contract)
        if not contract.known:
            issues.append({'code': 'missing_dependency_contract', 'feature_id': entry.id})
            return result
    result['dependencies'] = graph.as_dict()
    result['recipe_fingerprint'] = digest({'root': assembly.recipe_root.model_dump(mode='json'),
        'commands': [(r.id, r.op_kind, r.params, r.suppressed) for r in rows]})
    result['authoring_fingerprint'] = digest(authoring_state(assembly))
    rebuilt = create_empty_assembly(assembly.recipe_root.initial_name).model_copy(update={'id': assembly.id})
    imported = False
    prefix_length = len(rows) if cursor == -1 else 0 if cursor == -2 else cursor + 1
    for position, entry in enumerate(rows):
        checkpoint()
        try:
            # Sources in suppressed definitions still require truthful provenance.
            imported |= verify_sources(entry.op_kind, entry.params, checkpoint)
            # Validate every saved definition/source, but compare only the
            # displayed prefix. This is explicitly not proof of the full tail.
            if position >= prefix_length:
                continue
            if not entry.suppressed:
                rebuilt = execute(rebuilt, entry.op_kind, entry.params)
            from backend.core.assembly_structure import assess_references
            structure = assess_references(rebuilt, checkpoint=checkpoint)
            if structure['status'] != 'valid':
                issues.append({'code': 'invalid_intermediate_references', 'feature_id': entry.id,
                               'index': position, 'structure': structure})
                result['status'] = 'failed' if structure['status'] == 'invalid' else 'unverified'
                return result
            result['checked_commands'] += 1
        except ValueError as error:
            issues.append({'code': 'command_replay_failed', 'feature_id': entry.id,
                           'index': position, 'detail': str(error)})
            return result
    checkpoint()
    expected, actual = authoring_state(assembly), authoring_state(rebuilt)
    mismatches = sorted(field for field in expected if expected[field] != actual[field])
    if mismatches:
        result['status'] = 'mismatch'
        issues.append({'code': 'authoring_state_mismatch', 'fields': mismatches})
    else:
        result.update(status='reproduced_import' if imported else 'verified', native_editable=not imported)
    return result


def assess(assembly, **kwargs):
    from backend.core.assembly_structure import assess_references
    result = _assess(assembly, **kwargs)
    result['reproducibility_status'] = result['status']
    structure = assess_references(assembly, checkpoint=kwargs.get('checkpoint', lambda: None))
    result['structure'] = structure
    if structure['status'] != 'valid':
        result['issues'].append({'code': 'invalid_references' if structure['status'] == 'invalid' else 'reference_check_incomplete',
                                 'structure': structure})
        if result['status'] in {'verified', 'reproduced_import'}:
            result['status'] = 'failed' if structure['status'] == 'invalid' else 'unverified'
        result['native_editable'] = False
    return result
