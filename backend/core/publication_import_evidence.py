"""Portable source evidence for reconstruction attempts, including failed ones."""
import pymupdf
from backend.core.publication_reconstruction_report import ReconstructionBlocked
from backend.core.publication_table_import import import_pdf_tables
from backend.core.publication_raster_tracing import register_and_trace


def extraction_evidence(data, choice):
    with pymupdf.open(stream=data, filetype='pdf') as doc:
        if not 1 <= choice['diagram_page'] <= len(doc):raise ReconstructionBlocked('diagram_page_out_of_range', 'Diagram page is outside this PDF.')
        tables = import_pdf_tables(doc)
        table = next((t for t in tables if choice['table_page'] in t['pages']), None)
        modules = choice.get('table_modules')
        if modules is not None:
            if not table or not isinstance(modules,list) or not all(isinstance(m,str) and m in table['module_counts'] for m in modules):
                raise ReconstructionBlocked('table_selection_invalid', 'Selected table modules are not present in the source.')
        selected = [r for r in table['rows'] if modules is None or (r['module'] or 'unlabelled') in modules] if table else []
        raster = register_and_trace(doc[choice['diagram_page']-1])
        fallback = None
        if table and raster:
            if modules and len(selected)>500:
                fallback = {'status':'row_budget_exceeded','selected_rows':len(selected),'native_routing_resolved':False}
            elif modules and selected:
                from backend.core.publication_sequence_domains import sequence_fallback
                from backend.core.sequences import M13MP18_SEQUENCE
                fallback = sequence_fallback(selected, M13MP18_SEQUENCE, scaffold_name='M13mp18 hypothesis')
            else:
                fallback = {'status':'select_modules_first', 'reason':'Variants/accessory rows must not be combined into one occupancy search.', 'native_routing_resolved':False}
        if fallback and fallback.get('anchors'):
            from backend.core.publication_anchor_image_mapping import image_span_candidates
            final_anchors=fallback['anchor_refinement'].get('anchor_recheck') or fallback['anchors']
            fallback['image_anchor_candidates']=image_span_candidates(raster,final_anchors)
            from backend.core.publication_sequence_continuity import continuity_candidates
            fallback['image_continuity']=continuity_candidates(
                raster['classified_tracing'], final_anchors, selected, M13MP18_SEQUENCE)
        return {'sequence_fallback':fallback,'table_import':table, 'selected_modules':modules, 'selected_row_ids':[r['id'] for r in selected],
                'selection_status':'module_selection' if modules else 'unresolved_design_membership',
                'annotations':[{'row_id':r['id'],'modifications':r['modifications'],
                    'overhangs':r['overhang_annotations']} for r in selected if r['modifications'] or r['overhang_annotations']],
                'raster_evidence':raster,
                'native_annotation_status':'Pending verified strand and overhang mapping; no chemistry or topology inferred from labels.'}
