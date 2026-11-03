"""Explicit, manually reviewed seed records. Run build_catalog.py after editing."""
from pathlib import Path
import json

HERE = Path(__file__).resolve().parent
ASSETS = HERE / 'assets'
if (HERE/'catalog.json').exists() and json.loads((HERE/'catalog.json').read_text()).get('schema_version',1)>=2:
    raise SystemExit('Refusing to overwrite enriched schema-v2 catalog with the initial seed recipe; edit catalog.json instead.')
SCREEN = {r['pmcid']:r for r in json.loads((ASSETS/'sources/screening.json').read_text())}
DOWNLOADS = json.loads((ASSETS/'sources/evidence-downloads.json').read_text())
URLS = {d['path']:d['source_url'] for r in DOWNLOADS for d in r['downloads']}
URLS.update({
 'sources/cargo-sorting.pdf':'https://www.dna.caltech.edu/Papers/CargoSortingSupplementary2017.pdf',
 'sources/stacking-bonds.pdf':'https://www.dna.caltech.edu/Papers/stacking-bonds2011_SI.pdf',
 'sources/tilings.pdf':'https://www.qianlab.caltech.edu/nnano.2016.256-s1.pdf',
 'sources/twist-supp.pdf':'https://www.dietzlab.org/app/download/8873041685/curvature_supporting_info.pdf?t=1474487673',
 'sources/shapes-supp.pdf':'https://www.dietzlab.org/app/download/8873059785/nature08016-s1.pdf?t=1474488006',
 'sources/rapid-figure.jpg':'https://cdn.ncbi.nlm.nih.gov/pmc/blobs/1fbe/2731887/8a7fccb631f8/gkp436f1.jpg',
 'sources/PMC4914096-supp_gkw208_20160324_Supp.pdf':'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC4914096/supplementaryFiles',
})
EXTRA = {
 'cargo':('A cargo-sorting DNA robot','10.1126/science.aan6558','2017-09-15'),
 'stacking':('Programmable molecular recognition based on the geometry of DNA nanostructures','10.1038/nchem.1070','2011-07-10'),
 'tilings':('Programmable disorder in random DNA tilings','10.1038/nnano.2016.256','2016-11-28'),
 'twist':('Folding DNA into Twisted and Curved Nanoscale Shapes','10.1126/science.1174251','2009-08-07'),
 'shapes':('Self-assembly of DNA into nanoscale three-dimensional shapes','10.1038/nature08016','2009-05-21'),
}
ROWS=[]

def add(key,design,pdf,page,lattice,location,scores,rationale,files=(),file_note='',lattice_evidence='Visible cross-section and routing grid in the cited image.'):
    if key in EXTRA: title,doi,date=EXTRA[key]
    else:
        r=SCREEN[key];title,doi,date=r['title'].rstrip('.'),r['doi'],r['firstPublicationDate']
    source='sources/'+pdf
    if pdf.endswith('.pdf'):
        image='images/'+pdf[:-4]+f'-p{page}.png'
    else: image=source
    row={'id':f'D{len(ROWS)+1:03d}','publication':title,'doi':doi,'first_publication_date':date,'design':design,'lattice':lattice,'lattice_evidence':lattice_evidence,'publication_url':'https://doi.org/'+doi,'image_source_url':URLS[source],'source_file':source,'pdf_page':page,'figure_location':location,'image_file':image,'software':'cadnano','review_status':'image_and_lattice_reviewed','quality_components':dict(zip(['routing_coverage','crossover_detail','coordinates','lattice_context','legibility','sequence_annotations'],scores)),'quality_score':round(sum(scores)/24*100),'quality_rationale':rationale,'rating_status':'provisional_manual','design_files':list(files),'file_status':'author_files_downloaded' if files else 'not_located_in_checked_sources','file_note':file_note or 'No editable original located in the checked main text, supplement links, and named repositories; this is not proof of absence.','reviewed':'2026-11-02'}
    ROWS.append(row)

add('cargo','Double-layer square tile','cargo-sorting.pdf',21,'square','SI Fig. S14; printed p.20',[4,3,3,2,3,0],'Full map and helix labels; long bridging strands overlap. No sequence-level annotations in this image.',lattice_evidence='SI section 3.1 identifies double-layer square design; conventional square-grid routing.')
for page,variant in [(80,'strong–weak'),(81,'strong–strong')]:
 add('tilings','Square tile, '+variant+' bridge staples','tilings.pdf',page,'square',f'SI part II, Fig. S{70 if page==80 else 71}',[4,4,3,2,4,0],'Complete vector routing map with colored staples and helix labels; cross-section absent.',lattice_evidence='Square tile conventional caDNAno path grid, with explicit bridge-staple variants in SI section S10.')
add('stacking','Edge-shape origami; partial routing screenshot','stacking-bonds.pdf',15,'square','SI Fig. S6',[1,4,3,1,4,4],'Detailed GC/base annotations and editing example, but only a small portion of the design is visible.',files=[str(f.relative_to(ASSETS)) for f in sorted((ASSETS/'designs/stacking-bonds').glob('*.cdn'))],file_note='Seven original legacy caDNAno .cdn files found in Caltech Supplement 4; valid vstrands JSON. Exact screenshot-to-variant match pending.',lattice_evidence='SI p.15 explicitly identifies modified square-lattice caDNAno.')
add('twist','10 × 6 right-twisted bundle','twist-supp.pdf',19,'honeycomb','Supporting Fig. 9',[4,4,4,4,4,0],'Full colored routing, numeric coordinates and honeycomb slice; insertion/deletion marks visible.',files=['designs/twist/monolith_right_twist.json'],file_note='Original author gallery archive Science09.zip; design name matches right-twisted bundle. Topology not yet compared base-by-base to image.')
add('twist','3 × 6 straight bundle','twist-supp.pdf',20,'honeycomb','Supporting Fig. 10',[4,4,4,4,3,0],'Complete routing and slice; narrow drawing requires zooming the source PDF.',files=['designs/twist/protractor_0_v3.json'],file_note='Author gallery zero-angle design; numerical equivalence to published diagram remains to be checked.')
for page,name,file in [(4,'Monolith','monolith'),(5,'Square nut','squarenut'),(6,'Railed bridge','railedbridge'),(7,'Slotted cross','slottedcross'),(8,'Stacked cross','stackedcross'),(9,'Genie bottle / double gear','doublegear')]:
 add('shapes',name,'shapes-supp.pdf',page,'honeycomb',f'SI Fig. S{page}',[4,4,4,4,4 if page<6 else 3,0],'Complete colored caDNAno routing with helix/base indices and cross-sectional slice views.',files=[f'designs/shapes/{file}.json'],file_note='Original author gallery Nature09.zip. Exact base-by-base agreement has not been validated. The wireframe icosahedron is excluded.')
add('PMC2731887','18-helix demonstration object','rapid-figure.jpg',None,'honeycomb','Main Fig. 1',[3,3,2,4,2,1],'Published multi-panel bitmap: lattice and routes visible, but small labels and a compact path panel limit recovery.',file_note='Seven other design files from this paper were downloaded (see design_files.csv); none is asserted to be this 18-helix demonstration object.')
add('PMC6906287','Channel-and-flap nanopore','PMC6906287-41467_2019_13284_MOESM2_ESM.pdf',45,'honeycomb','Supplementary Fig. 31',[4,4,3,4,3,0],'Full split routing map and honeycomb slice; split-to-split connectivity needs careful tracing.',file_note='SI names scholer/staplestatter: repository tree checked; no .json/.sc design files located there.')
add('PMC5648847','Reconfigurable DNA nanovault','PMC5648847-41467_2017_1072_MOESM1_ESM.pdf',8,'honeycomb','Supplementary Fig. 1',[4,3,3,4,3,1],'Full path and slice, colored functional modules and anchors; long connecting strands obscure some crossings.')
add('PMC4979213','Nano-finger device','PMC4979213-41598_2016_BFsrep31379_MOESM37_ESM.pdf',8,'honeycomb','SI section 3, parameter map',[3,2,2,4,1,0],'Excellent lattice index map but tiny low-contrast path screenshot; conservative recovery priority.')
for page,label,lattice in [(60,'6-, 8-, and 10-helix bundles','honeycomb'),(61,'12-, 18-, and 24-helix bundles','honeycomb'),(66,'100-helix bundle','square')]:
 add('PMC3493638',label,'PMC3493638-41467_2012_BFncomms2095_MOESM1188_ESM.pdf',page,lattice,'Supplementary Fig. S5 design diagrams',[4,4,4,2,3,3],'Complete scaffold/staple grid with base-level annotations; narrow multi-design panels require PDF zoom.',lattice_evidence='Main text explicitly assigns 6–24 HB to honeycomb and 100 HB to square. Brick-named 42 HB variants omitted.')
add('PMC3997801','42-helix bundle, zero pseudo-defects','PMC3997801-41467_2014_BFncomms4691_MOESM86_ESM.pdf',1,'honeycomb','Supplementary Fig. 1',[4,4,4,2,3,4],'Full route, base labels and nucleotide sequences retained in vector source.',lattice_evidence='CaDNAno routing uses standard honeycomb 7-base crossover grid; 42-HB multilayer layout.')
for page,label,lattice in [(19,'Pin pore','honeycomb'),(21,'T pore','square')]:
 add('PMC5036142',label,'PMC5036142-41467_2016_BFncomms12787_MOESM1904_ESM.pdf',page,lattice,f'Supplementary Fig. 24{"a" if page==19 else "c"}',[4,4,3,4,4,0],'Full colored routing with cross-sectional lattice view; strong candidate for tracing.')
add('PMC5834454','DNA ring scaffold','PMC5834454-41467_2018_3313_MOESM1_ESM.pdf',3,'honeycomb','Supplementary Fig. 2',[4,3,3,2,2,0],'Complete long route and attachment sites; compressed drawing limits legibility.',lattice_evidence='Regular 7-base honeycomb route grid in caDNAno; ring built from parallel bundle helices, not a wireframe polyhedron.')
add('PMC4616047','60-helix bundle','PMC4616047-41598_2015_BFsrep15634_MOESM1_ESM.pdf',9,'honeycomb','Supplementary Fig. S5',[4,3,3,2,3,0],'Whole path grid and helix labels; staples largely monochrome, cross-section not shown.',lattice_evidence='Standard 7-base honeycomb routing repeat in bundle diagram.')
add('PMC4012984','Barrel robot screenshot','PMC4012984-41565_2014_BFnnano201458_MOESM9_ESM.pdf',5,'honeycomb','Supplementary Fig. 1; printed p.4',[1,1,1,4,2,0],'Lattice and 3D shape clear; only a cropped path-panel strip is visible.',file_note='SI explicitly says a JSON supplement exists, but the retrieved publisher links expose only the PDF. Marked referenced-but-not-retrieved, not absent.')
ROWS[-1]['file_status']='referenced_not_retrieved'
for page,label in [(3,'Nano-platform'),(9,'Nano-hinge')]:
 add('PMC5899095',label,'PMC5899095-41467_2018_3601_MOESM1_ESM.pdf',page,'square' if page==3 else 'honeycomb','Supplementary Fig. '+('2' if page==3 else '6'),[4,4,1,2,4,1],'Clear full colored path, but no numbered base/helix grid. The separate nano-brick design is excluded.',lattice_evidence='Platform: two-layer 32-helix rectangle in methods, square-grid routing inferred from map. Hinge: methods explicitly state two 36HB honeycomb bundles.')
add('PMC4914096','Six-helix antenna variants','PMC4914096-supp_gkw208_20160324_Supp.pdf',6,'honeycomb','Supplementary Fig. S4',[4,3,3,2,3,0],'Twelve complete antenna maps with indices; each is small on the page.',files=['designs/ReuseDNA/6helix.json'],file_note='Paper-linked author repository contains 6helix template; variant-specific sequence and routing equivalence not established. 24helix template separately indexed.',lattice_evidence='Six-helix bundle template in paper-linked repository and conventional honeycomb crossover spacing.')
for n in range(1,5):
 path=f'images/mirage-Supplementary-Data-File-{n}.png'
 arch=f'41467_2017_BFncomms13966_MOESM{666+n}_ESM.zip'
 url='https://static-content.springer.com/esm/art%3A10.1038%2Fncomms13966/MediaObjects/'+arch
 URLS['sources/'+Path(path).name]=url
 add('PMC5512867','12-helix bundle' if n==1 else f'Rectangle variant (data file {n})',Path(path).name,None,'honeycomb' if n==1 else 'square',f'Supplementary Data File {n}',[4,4,3,4 if n==1 else 2,3,1],'Original high-resolution PNG design map; transparent background must be displayed on white.',file_note='Publisher ZIP inspected: contains a PNG only, not editable caDNAno JSON.',lattice_evidence='Honeycomb slice explicitly visible for 12HB; rectangles use conventional planar square-grid crossover routing.')
 ROWS[-1]['source_file']='sources/'+arch
 ROWS[-1]['image_file']=path
 ROWS[-1]['image_source_url']=url

(HERE/'catalog.json').write_text(json.dumps({'status':'research_side_project','production_feature':False,'cutoff_exclusive':'2020-01-01','coverage':'initial_verified_subset_not_exhaustive','reviewed':'2026-11-02','rows':ROWS},indent=2)+'\n')
