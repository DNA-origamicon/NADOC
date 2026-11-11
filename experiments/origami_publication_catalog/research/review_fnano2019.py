"""Program-level leads from inspection of all ten FNANO 2019 schedule pages.
Uncertain low-keyword talks are retained; none is promoted to design-bearing.
Abstract books and journal/preprint reconciliation remain pending.
"""
import hashlib
import ledger as L
from review_batch_0001 import evidence

# page, presentation type, first listed author, transcribed title.
LEADS=[
(1,'poster','Jingjing Ye','Nano-electronic components built from DNA templates'),
(1,'poster','Casey Platnich','Kinetics of Strand Displacement and Hybridization on Wireframe DNA Nanostructures: Dissecting the Roles of Size, Morphology, and Rigidity'),
(1,'poster','Xin Luo','Construct Complex Gold Nanoparticle Structures using DNA as a Chaperon'),
(1,'poster','Feng Zhou','3D self-replication of DNA nanostructures'),
(1,'invited_talk','Masayuki Endo','Investigation of physical properties of i-motif and G-quadruplex in a confined nanospace'),
(2,'poster','David Neff','Toward 1-D Arrays of Two Color Molecular Beacons'),
(2,'poster','Nathan Williams','Programmable DNA-nanostructures for rapid and facile molecular counting'),
(2,'invited_talk','Lingh Nguyen','Chiral plasmonic sensing and silicifying DNA materials'),
(2,'contributed_talk','Shalin Shah','Imaging single-molecules with temporal DNA barcodes'),
(4,'invited_talk','Kerstin Göpfrich','Synthetic cells: Bottom-up assembly with DNA nanotechnology and microfluidics'),
(4,'contributed_talk','Brian Rolczynski','Deducing the roles of individual chromophores in energy transport relays using machine-learning tools'),
(4,'contributed_talk','Rasmus Peter Thomsen','A large size-selective DNA nanopore with sensing applications'),
(4,'poster','Ming Gao','Self-Assembly of Three-Dimensional Electronic Systems with Neuromimetic Network Architectures'),
(4,'poster','Akinori Kuzuya','Real-Time Observation of The Movements of DNA Origami Pinching Devices on Mica Using High-Speed AFM'),
(4,'poster','Rajan Sharma','Self-assembled DNA Light-Pipes'),
(4,'poster','Michael Tobiason','Engineering Kinetically Reproducible DNA Devices'),
(4,'poster','Chao-Min Huang','Design automation for DNA origami mechanisms'),
(4,'contributed_talk','Daniel Fu','Automated Design of Curved DNA Origami Capsules with Multilayer-Reinforced Rigidity with Specified Shape'),
(5,'poster','William Klein','Enhanced Catalysis of a Three-Enzyme Pathway on a DNA Triangle'),
(5,'poster','Siddharth Agarwal','Engineering dynamic nucleic acid nanotubes in cell-sized compartments'),
(6,'poster','Caroline Rossi-Gendron','Isothermal formation of DNA origamis at room temperature in an unchanging buffer: robust self-assembly through multiple folding pathways'),
(6,'poster','Rokiah Alford','Concentration dependent exchange of subunits on DNA origami: a fuel-free design from nature’s molecular machines'),
(6,'poster','Jacob Majikes','Measuring Energetics and Cooperativity of Origami Folds'),
(6,'invited_talk','Bernard Yurke','Exciton quantum walks over DNA-assembled dye aggregates - a path to quantum computing?'),
(7,'invited_talk','Devin Daems','DNA origami nano-tailored surfaces enhance biomolecular interactions at the biosensor surface'),
(7,'contributed_talk','Frances Anastassacos','pH responsive DNA origami nanocapsules for endosome-specific drug delivery'),
(7,'poster','Liwei Hui','DNA-based nanofabrication for antifouling application'),
(7,'poster','Heini Ijäs','Reconfigurable and Programmable pH-Responsive DNA Origami Nanocapsule for Loading, Encapsulation and Displaying of Cargo'),
(7,'poster','Youngeun Kim','DNA dendrimer-coated DNA nanostructures'),
(7,'poster','Philip Lukeman','An Electrochemical Biosensor Exploiting Conformational Changes in Electrode-Attached DNA Origami to Detect Hundred Nanometer-Scale Targets'),
(8,'contributed_talk','Mauri Kostiainen','Virus and DNA Origami Directed Nanoparticle Superlattices'),
(8,'invited_talk','Alasdair Clark','Using the Fluorous Effect to Control the Immobilization and Orientation of DNA and DNA Nanostructures'),
(8,'invited_talk','Yuki Suzuki','Large deformation of a linear DNA origami beam via cumulative actuation of tension-adjustable modules'),
(8,'invited_talk','Andrew Tuckwell','DNA templates and building blocks for bioinspired molecular assemblies'),
(9,'poster','Qi Yan','Conformational isomerization of DNA nanostructures based on enzyme treatment'),
(9,'poster','Jonathan Berengut','Vernier Assembly of Multi-Subunit DNA Origami Nanostructures'),
(9,'poster','Anjelica Kucinic','DNA origami tubes with reconfigurable cross-section'),
(9,'poster','Yan Cui','Hybrid Wireframe DNA Nanostructures'),
(9,'poster','John Powell','DNA Origami Supports for Protein and RNA Structural Studies'),
(9,'poster','Megan Kizer','Microfluidic Delivery of DNA Nanostructures and Investigation of In Vitro and In Vivo Stability'),
(10,'keynote','Ludger Johannes','Designer DNA nanodevices to probe endocytic pathways'),
(10,'contributed_talk','Cynthia Koehler','A multiscale approach to investigating cell signaling in vivo using DNA origami and colloidal hydrogels'),
(10,'poster','Joshua Johnson','Control of DNA Origami Mechanisms and Assemblies via Gold Nanoparticles'),
(10,'poster','Andrew Tuckwell','DNA-Templated Protein Assembly: An Engineering Approach to Understanding Nature’s Molecular Machines'),
(10,'keynote','Ulrich Keyser','Active molecular sensors built with DNA nanotechnology'),
(10,'contributed_talk','Pallav Kosuri','Self-assembled DNA rotors enable high-resolution tracking of molecular motors')]


def main():
    before=L.counts(); keys=[];existing={r['registry_key'] for r in L.read('publication_reviews')}
    path=L.ROOT/'assets/research-20261105/FNANO19schedule.pdf';url='https://www2.cs.duke.edu/fnano/FNANOschedules/FNANO19schedule.pdf'
    for page,kind,author,title in LEADS:
        key='conference:fnano2019:'+hashlib.sha256(title.encode()).hexdigest()[:12];keys.append(key)
        if key in existing:continue
        ev=evidence(path,url,f'PDF p.{page}, presentation by {author}')
        date='2019-04-'+str(15 if page<=3 else 16 if page<=6 else 17 if page<=9 else 18)
        record={'registry_key':key,'registry_id':None,'doi':'','title':title,'authors':[author],
                'authors_complete':False,'author_note':'First listed author indexed; complete author list retained on cited schedule page.',
                'canonical_work_id':'work:'+key,'canonical_work_status':'provisional_unreconciled','version_links':[],
                'publication_type':['conference_'+kind],'date_evidence':{'date':date,'source':ev,'primary_verified':True,'meaning':'scheduled presentation date; first public release date unresolved'},
                'review_stage':'metadata_screened','relevance':'uncertain','design_contributions':['uncertain'],
                'catalog_eligibility':'unresolved','access':'partial','evidence':[ev],
                'rationale':'Title and first author inspected in official program. Retained as a potentially relevant lead, including low-keyword/uncertain subjects. Program is not evidence of a complete origami design.',
                'reviewer':'Codex source inspection','run_id':'fnano-2019','date':L.DATE,
                'unresolved_questions':['Inspect abstract and full author list; identify journal/preprint counterpart, original publication date and design contribution.'],
                'legacy_record':{},'revision_history':[]}
        L.upsert('publication_reviews',record,'Record inspected conference lead without inferring design completeness')
        L.upsert('discovery_edges',{'edge_id':'fnano2019:'+key.rsplit(':',1)[1],'source_key':'fnano-2019','target_key':key,
                 'relation':'conference_lead','evidence_url':url,'local_file':ev['local_file'],'sha256':ev['sha256'],
                 'locator':ev['locator'],'reconciliation_state':'journal_preprint_counterpart_pending'},'Enqueue conference reconciliation')
    run=next(r for r in L.read('discovery_runs') if r['run_id']=='fnano-2019')
    run.update(pagination={'pages':10,'pages_inspected':list(range(1,11)),'all_presentations_disposed':False},
               deduplicated_additions=50,additions_unit='conference presentation/version leads, not new eligible canonical works',
               checkpoint='All 10 schedule pages inspected; 50 potential leads recorded including four initial p.1 entries. Abstract book, full author extraction, remaining program-item dispositions and journal/preprint reconciliation pending.',closure_state='in_progress')
    L.upsert('discovery_runs',run,'Extend program inspection to all pages; preserve unclosed abstract and reconciliation work')
    if not any(b['batch_id']=='DISC0001' for b in L.read('batches')):
        L.upsert('batches',{'batch_id':'DISC0001','date':L.DATE,'status':'completed','input_keys':keys,
                 'completed_actions':['Read entire FNANO 2019 schedule and add 46 further uncertain presentation leads.','Acquire all 14 official 2006–2019 schedules; download is not review.','Inspect selected Rothemund bibliography; seven DOI links, one unmatched lead.'],
                 'before_counts':before,'after_counts':L.counts(),'exclusion_audit':{'sample':[],'reason':'No final exclusions; leads remain uncertain.'},
                 'validation':[L.validate()],'unresolved_keys':keys,'next_queue':['Find abstract books and reconcile 50 presentation leads; other 13 schedule contents unreviewed.','Continue B0003 and forward/capped-search repairs.']},'Checkpoint discovery batch and remaining coverage')
    print(L.counts())


if __name__=='__main__':main()
