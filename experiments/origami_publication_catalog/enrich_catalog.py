"""Recorded manual evidence update, 2026-11-02. Idempotent migration to schema 2."""
import json
from pathlib import Path
import re
import html
from scoring import reconstruction_score
H=Path(__file__).resolve().parent
A=H/'assets'
f=H/'catalog.json';data=json.loads(f.read_text());rows=data['rows']
old_order=sorted(rows,key=lambda r:(-r['quality_score'],r['doi'],r['id']))
rank={r['id']:i for i,r in enumerate(old_order,1)}
source_urls={d['path']:d['source_url'] for x in json.loads((A/'sources/evidence-downloads.json').read_text()) for d in x['downloads']}
source_urls.update({x['path']:x['source_url'] for x in json.loads((A/'sources/enrichment-downloads.json').read_text())})
for r in rows: source_urls.setdefault(r['source_file'],r['image_source_url'])

def source(path,label,page=None):
    return {'label':label,'url':source_urls[path]+(f'#page={page}' if page and path.endswith('.pdf') else ''),'local_file':path,'pdf_page':page}

def staples(r,status,label,page=None,path=None,note='Published sequence list located; sequence-to-topology equivalence has not been validated.'):
    path=path or r['source_file']
    r['staple_list']={'status':status,'location':label,'notes':note,'sources':[source(path,label,page)]}

def char(modalities,location,note):return {'modalities':modalities,'location':location,'simulation_comparison_notes':note}
chars={
'10.1126/science.aan6558':char(['AFM'],'SI Figs. S7, S10–S11; AFM methods in SI section 2.9','Surface images show tile/cargo placement; compare projected tile dimensions and cargo-position distributions. Bulk fluorescence kinetics are functional evidence, not 3D structural data.'),
'10.1038/nnano.2016.256':char(['AFM'],'Main figures and SI; SI section S1.2','AFM measures surface-bound tile arrays and pattern statistics; compare 2D tiling arrangements, not solution-state 3D density.'),
'10.1038/nchem.1070':char(['AFM'],'Main figures and SI wide-field AFM panels, including Fig. S15','Paper-level evidence for assembled tiles/chains. The catalog crop is conceptual and has not been matched to a specific measured tile variant.'),
'10.1126/science.1174251':char(['negative-stain TEM'],'Main Figs. 1–3 and supporting micrographs','Projected twist, bundle shape and bend-angle distributions; select the same scaffold and insertion/deletion variant and account for staining/drying.'),
'10.1038/nature08016':char(['negative-stain TEM'],'Main Fig. 2 and SI microscopy','Compare projected dimensions and folding morphology for the named object. Genie-bottle pEGFP and p7308 scaffolds have distinct sequence lists.'),
'10.1093/nar/gkp436':char(['negative-stain TEM (other designs in paper)'],'Main Fig. 2, rectangular-block series','No experimental image match established for the 18-helix tutorial object shown in the catalog. Do not transfer block-series TEM evidence to that illustration.'),
'10.1038/s41467-019-13284-1':char(['negative-stain TEM','2D class averages','cryo-EM micrographs'],'Main Fig. 2; SI Figs. 6–10 and 12','Compare pore dimensions, lumen and flap states. Cryo-EM is limited micrograph characterization here, not a verified deposited 3D reconstruction. Confocal/TIRF leak assays measure function.'),
'10.1038/s41467-017-01072-8':char(['uranyl-acetate-stained TEM','FRET'],'Main Fig. 2; SI Figs. 6–7','TEM resolves open/closed vault morphology; FRET provides an ensemble distance proxy. Methods call the TEM preparation positive staining; not relabeled as cryo-EM or negative staining.'),
'10.1038/srep31379':char(['AFM','TEM (tweezers component)','confocal FRET'],'Main Figs. 2 and 4','AFM characterizes the whole device; TEM initially tests its tweezers component. FRET constrains conformational switching, not atomic coordinates.'),
'10.1038/ncomms2095':char(['negative-stain TEM','particle class averages'],'Main Figs. 1–2; SI particle images','Variant-specific micrographs under sodium/magnesium folding conditions. Match helix count and annealing condition before comparing shapes.'),
'10.1038/ncomms4691':char(['negative-stain TEM','averaged particle projections'],'Main Fig. 1; SI Figs. 4–9','Zero-pseudo-defect and omitted-staple variants have separate image sets. TEM cannot resolve all internal defects; the fluorescent defect assay is complementary, not imaging density.'),
'10.1038/ncomms12787':char(['stained TEM','2D class averages'],'Main Figs. 1, 3–4; SI pore microscopy','Match pin versus T pore and lipidation state. Confocal vesicle-flux videos support transport/dynamics, not direct nanoscale 3D shape.'),
'10.1038/s41467-018-03313-w':char(['negative-stain TEM','negative-stain tomography','cryo-EM 2D averages','TIRF photobleaching'],'Main Figs. 2–3; SI Figs. 7–10','Empty ring / 32-NSP1 / 32-NSP1-S cryo averages use 1663 / 637 / 1051 particles. Compare projected protein densities and radial profiles; the paper already compares these with coarse-grained MD. No public raw stack or 3D map accession verified.'),
'10.1038/srep15634':char(['TEM','wide-field fluorescence of deposited patterns'],'SI Fig. S1b and Note 2; main Fig. 4','TEM confirms the 60HB structure. AFM in this paper concerns the separate planar ST/DT designs; fluorescence coating images are not single-particle structure.'),
'10.1038/nnano.2014.58':char(['AFM'],'Main Fig. 1B; SI characterization','AFM supports barrel/robot architectures. Flow cytometry measures logic/function, not a spatial density map; catalog CAD panel is cropped.'),
'10.1038/s41467-018-03601-5':char(['AFM','TEM','optical actuation tracking'],'Main Figs. 1 and 3–4; SI Figs. 1 and 5; Supplementary Movies','Separate platform and hinge images from the excluded nano-brick. Videos constrain driven assembly trajectories, not equilibrium structural ensembles.'),
'10.1093/nar/gkw208':char(['negative-stain TEM'],'Main Fig. 2C; SI antenna characterization','The shown antennas are components of a larger testing device. Match each LLL/SLL/etc. antenna variant; the 24HB class averages in Fig. 3 are a different design family.'),
'10.1038/ncomms13966':char(['3D DNA-PAINT super-resolution microscopy'],'Main Figs. 2–3; SI Figs. 1–5','12HB localization marks and rectangle height measurements. Gold-induced localization bias is the measured effect; simulate fluorophore/optical displacement rather than treating localization positions as unbiased DNA coordinates.')}
requested={'10.1038/ncomms12787','10.1038/ncomms13966','10.1038/s41467-018-03601-5','10.1038/s41467-017-01072-8','10.1038/s41467-019-13284-1','10.1038/s41467-018-03313-w'}
# Scores: coverage, scaffold, staple routing/ends, base register/indels, helix mapping, legibility.
score_values={
'D001':[4,3,3,3,2,3], 'D002':[4,4,3,3,2,4], 'D003':[4,4,3,3,2,4],
'D004':[1,1,1,2,1,3], 'D005':[4,4,4,4,4,4], 'D006':[4,4,4,4,4,3],
'D007':[4,4,4,4,4,4], 'D008':[4,4,4,4,4,4], 'D009':[4,3,3,4,4,3],
'D010':[4,3,3,4,4,3], 'D011':[4,3,3,4,4,3], 'D012':[4,3,3,4,4,3],
'D013':[1,2,1,1,4,2], 'D014':[4,3,3,3,4,3], 'D015':[4,3,3,3,4,3],
'D016':[3,2,1,1,4,1], 'D017':[4,4,3,4,2,3], 'D018':[4,4,3,4,2,3],
'D019':[4,4,3,4,2,3], 'D020':[4,4,4,4,2,3], 'D021':[4,4,3,3,4,4],
'D022':[4,3,3,3,4,4], 'D023':[4,3,2,2,2,2], 'D024':[4,3,3,3,2,3],
'D025':[1,1,0,0,4,2], 'D026':[4,4,3,1,2,4], 'D027':[4,3,3,1,2,4],
'D028':[2,3,3,3,2,3], 'D029':[4,3,3,3,4,3], 'D030':[4,3,3,3,2,3],
'D031':[4,3,3,3,2,3], 'D032':[4,3,3,3,2,3]}
for r in rows:
    rid=r['id'];doi=r['doi']
    if 'previous_quality_score' not in r:
        r['previous_quality_score']=r['quality_score'];r['previous_rank']=rank[rid]
        r['previous_quality_components']=r['quality_components'];r['previous_quality_rationale']=r['quality_rationale']
    kind='conceptual_illustration' if rid in ['D004','D013','D025'] else 'component_only' if rid=='D028' else 'partial_design' if rid=='D016' else 'complete_design_map'
    r['image_kind']=kind
    r['quality_components']=dict(zip(['whole_design_coverage','scaffold_routing','staple_routes_and_ends','base_register_and_indels','helix_layout','legibility'],score_values[rid]))
    r['quality_score']=reconstruction_score(r['quality_components'],kind)
    r['score_version']='image_reconstruction_v2'
    r['quality_rationale']=r['previous_quality_rationale']+' Image-only score now requires full target coverage and resolvable scaffold, staple ends, base register/indels and helix mapping; sequence letters and extra views earn no independent bonus.'
    if rid in ['D004','D013','D025']:
        r['quality_rationale']='Conceptual/partial illustration, not a complete reconstruction specification. Missing full-object routing cannot be recovered by counting additional panels or slice/3D views. Capped at 15/100.'
    if rid=='D028':r['quality_rationale']='Maps show antenna components/variants, not the complete origami testing device. Component-only coverage; capped at 35/100.'
    r['rating_status']='provisional_image_only_manual'
    if rid=='D001':staples(r,'available','SI Table S1, PDF pp.22–25',22)
    elif rid in ['D002','D003']:staples(r,'available','SI Table S1 (strong–weak), pp.82–85; Table S2 (strong–strong), pp.86–89; edge variants Tables S3 onward',82 if rid=='D002' else 86)
    elif rid=='D004':staples(r,'paper_lists_available_variant_unmatched','SI sequence lists and corner variants, pp.43–61',43,note='Staple lists exist in the paper, but the conceptual crop is not assigned to a unique full design. No complete image-to-list match claimed.')
    elif rid in ['D005','D006']:staples(r,'available','Supporting sequence list: right-twisted 10×6 p.37' if rid=='D005' else 'Supporting sequence list: 3×6 0-degree bend p.39',37 if rid=='D005' else 39)
    elif rid in ['D007','D008','D009','D010','D011','D012']:
        pg={'D007':12,'D008':13,'D009':14,'D010':15,'D011':16,'D012':17}[rid]
        staples(r,'available',f'SI named-object staple list, PDF p.{pg}'+('–18 (pEGFP / p7308 scaffold variants)' if rid=='D012' else ''),pg)
    elif rid=='D013':staples(r,'not_verified_for_this_illustration','Main Fig. 1 teaching example; exact 18HB staple list not located',note='Paper-wide sequence/design availability for other block motifs does not establish a staple list for this illustrated target.')
    elif rid=='D014':staples(r,'available','Supplementary Table 6, PDF pp.46–49',46)
    elif rid=='D015':staples(r,'available','Supplementary Table 2, PDF pp.23–30',23)
    elif rid=='D016':staples(r,'available','SI sections 1.1–1.4: tweezers, linkage and platform sequences, PDF pp.1–7',1)
    elif rid in ['D017','D018','D019']:staples(r,'available','Supplementary Data 1: DNA sequences for all objects',path='sources/41467_2012_BFncomms2095_MOESM1190_ESM.xls',note='Publisher labels workbook as sequences for all objects. Select the matching helix-count sheet; individual sequences have not been reconciled to the image.')
    elif rid=='D020':staples(r,'available','Supplementary Table 1, PDF pp.38–42: 42HB sequences',38)
    elif rid in ['D021','D022']:staples(r,'available','Supplementary Dataset 1: '+r['design']+' sequence table',path='sources/41467_2016_BFncomms12787_MOESM1905_ESM.docx')
    elif rid=='D023':staples(r,'available','Supplementary Tables 1–3, PDF pp.16–18 (8-/32-anchor variants)',16)
    elif rid=='D024':staples(r,'available','Supplementary Table S4, PDF pp.10–12; linker sequences Table S2',10)
    elif rid=='D025':staples(r,'available','Supplementary Fig. 3: robot staple sequences, PDF p.8 onward',8)
    elif rid in ['D026','D027']:staples(r,'available','Supplementary Table 1: platform, PDF p.17 onward' if rid=='D026' else 'Supplementary Table 3: hinge, PDF p.25 onward',17 if rid=='D026' else 25)
    elif rid=='D028':staples(r,'available','SI Tables S5–S16: antenna/control variants, pp.25–32; core/asymmetric part Tables S3–S4',25)
    else:staples(r,'available','SI Tables 2–3: 12HB + modifications, pp.7–12' if rid=='D029' else 'SI Tables 4–5: rectangle + variant modifications, pp.13–18',7 if rid=='D029' else 13,path='sources/PMC5512867-41467_2017_BFncomms13966_MOESM666_ESM.pdf')
    r['structural_characterization']=dict(chars[doi])
    r['structural_characterization']['source_url']=r['publication_url']
    r['structural_characterization']['scope']='paper_level_not_matched_to_illustration' if rid in ['D004','D013'] else 'design_or_named_variant_family'
    r['imaging_datasets']={'public_raw_dataset_status':'not_located_in_checked_sources','accession':None,'raw_dataset_links':[],'availability':'additional_data_on_author_request' if doi in requested else 'no_public_raw_deposit_located','availability_source':r['publication_url'],'notes':'Published figures/supplementary image collections are linked separately below; they are not deposited raw micrographs, particle stacks, localization tables, or reconstructed 3D maps. No claim that data do not exist.','resources':[],'checked':'2026-11-02'}
    # Preserve named links to actual imaging evidence, including source-only resources.
    paths={
    'D029':'sources/PMC5512867-41467_2017_BFncomms13966_MOESM666_ESM.pdf',
    'D030':'sources/PMC5512867-41467_2017_BFncomms13966_MOESM666_ESM.pdf',
    'D031':'sources/PMC5512867-41467_2017_BFncomms13966_MOESM666_ESM.pdf',
    'D032':'sources/PMC5512867-41467_2017_BFncomms13966_MOESM666_ESM.pdf'}
    p=paths.get(rid,r['source_file'])
    if p.endswith('.pdf'):
        rr=source(p,chars[doi]['location']);rr['kind']='published_figure_collection';r['imaging_datasets']['resources'].append(rr)
    else:r['imaging_datasets']['resources'].append({'label':chars[doi]['location'],'url':r['publication_url'],'kind':'published_figures'})
    r['enrichment_reviewed']='2026-11-02'

# Publisher-linked movies are previews of experiments, not large raw datasets. Link, do not bulk-download.
for pmc,doi in [('PMC5899095','10.1038/s41467-018-03601-5'),('PMC5036142','10.1038/ncomms12787'),('PMC6906287','10.1038/s41467-019-13284-1')]:
    text=(A/'sources'/(pmc+'-publisher.html')).read_text()
    urls=list(dict.fromkeys(html.unescape(u) for u in re.findall(r'href="([^"]+)"',text) if '/esm/' in u and u.endswith(('.mp4','.avi','.mov'))))
    for r in rows:
        if r['doi']==doi and r['id'] in ['D022','D014']:
            r['imaging_datasets']['resources'] += [{'label':(f'Supplementary movie {i}: T-pore confocal transport assay' if r['id']=='D022' else 'Supplementary video 1: liposome TIRF / stage-drift correction'), 'url':u, 'kind':'supplementary_movie', 'scope':'paper_level_variant_match_required'} for i,u in enumerate(urls,1)]
data['schema_version']=2;data['score_version']='image_reconstruction_v2'
data['score_definition']={'coverage_multiplier':'whole_design_coverage/4','detail_weights':{'scaffold_routing':25,'staple_routes_and_ends':30,'base_register_and_indels':20,'helix_layout':15,'legibility':10},'kind_caps':{'complete_design_map':100,'partial_design':35,'component_only':35,'conceptual_illustration':15},'essential_dimension_caps':{'0':15,'1':35,'2':60,'3':85,'4':100},'external_evidence_excluded':['staple_lists','author_design_files','microscopy','number_of_panels','sequence_letters_alone'],'interpretation':'Provisional completeness of reconstructing caDNAno topology from the cited image alone; not a success probability or exact-sequence recovery guarantee.'}
f.write_text(json.dumps(data,indent=2)+'\n')
print('Updated',len(rows),'rows')
