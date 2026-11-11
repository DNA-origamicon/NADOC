"""Manually inspected FNANO2018 schedule leads, not confirmed molecular designs."""
import hashlib
import ledger as L
from review_batch_0001 import evidence

# Schedule PDF page | kind | printed abstract pointer | first author | title.
ROWS='''1|keynote|2|Lulu Qian|Scaling up the complexity, design space, and accessibility of artificial molecular machines
1|poster|71|Nicholas Stephanopoulos|Hybrid nano-cages from DNA and self-assembling proteins
1|poster|73|Xiao Wang|The Construction of a DNA Origami Based Molecular Electro-Optical Modulator
1|poster|74|Nathaniel Anderson|Synthesis and Characterization of Porphyrin-DNA Constructs for the Self-Assembly of Modular Energy Transfer Arrays
1|poster|78|Young-Joo Kim|A strain-based design approach for twisted DNA nanostructures
1|poster|80|Kyung Soo Kim|Controlling the flexibility of DNA nanostructures via gap design
1|poster|85|Pongphak Chidchob|Site-Specific Functionalization of DNA Cube with Cholesterol Units: Self-Assembly and Interactions with Lipid Bilayers
1|poster|86|Devin Daems|Combining DNA origami with aptamers for single molecule counting in microwell arrays
1|poster|89|Yulia Gerasimova|Self-assembling DNA structures as probes for nucleic acid analysis
1|invited|19|Jie Song|Reconfigurable DNA nanostructures controlled by information relay
1|invited|61|David Neff|1D Arrays of Molecular Beacons
1|invited|36|Jonathan Berengut|Tuneable repulsion domains in multi-subunit DNA origami nanostructures
1|keynote|8|Armando Hernandez-Garcia|Designing proteins for self-assembling DNA-protein nanostructures
1|invited|10|Bjorn Hogberg|Revealing the Spatial Tolerance of Human Antibodies Using Nanopatterned Antigens
1|invited|11|Jessica Lorenz|DNA-based biomimetics as tools to study reconstituted and cellular systems
2|contributed|13|Aurelie Lacroix|DNA Nanocubes Interfacing with Biological Systems
2|poster|93|Parsa Nafisi|pScaf: A novel plasmid enabling phage-based production of single-stranded DNA scaffolds of custom size and sequence
2|poster|96|Ioanna Smyrlaki|DNA Origami nanocalipers as a Precise Tool for Studying Notch Receptor Activation
2|poster|97|Suraj Makhija|Toward Immunomodulatory DNA Origami Nanodevices
2|poster|101|Samuel Núñez-Pertíñez|Development of chemical tools for DNA-templated synthesis
2|poster|107|Abhichart Krissanaprasit|Using dCas9-affinity peptides complex for organization of Inorganic Nanomaterials on DNA origami
2|poster|109|Dionis Minev|DNA-tagged methanol responsive polymer (MeRPy) for single stranded DNA purification
2|poster|112|Katarina Iric|DNA-encircled lipid bilayers
2|invited|19|Ashwin Gopinath|Democratizing single molecule nanoarrays
3|contributed|24|Sisi Jia|Measuring flow rates at the cell surface with micron-scale DNA devices
3|poster|114|Zhao Zhang|Shaping and placing liposomes with DNA origami
3|poster|116|Siddharth Agarwal|Enzyme-driven assembly and disassembly of hybrid DNA/RNA nanotubes
3|poster|118|Sisi Jia|Attachment of DNA nanotubes to specific mammalian cell receptors with control over orientation
3|poster|120|Chao-Min Huang|Uncertainty Quantification of a DNA Origami Mechanism Using a Coarse-Grained Model and Kinematic Variance Analysis
3|poster|122|Hyungmin Jun|Programming 2D DX-based DNA Nanostructures using Top-Down Geometric Specification
3|poster|124|Hyungmin Jun|Inverse Geometric Design of Honeycomb DNA Nanoparticles
3|poster|126|Byoungkwon An|An Algorithm for Design of DNA Origami Lattices with Specified 2D Pixel and 3D Voxel Patterns
3|poster|128|Byoungkwon An|Design Algorithm for DNA Oligos of Given 3D Wire-Frame Graphs
3|poster|130|Daniel Fu|Semi-Automatic Design of Arbitrarily Shaped Solid-Walled Multi-Component DNA Origami Cages
3|poster|132|Ze Shi|Modeling the Conformational Dynamics and Ion-Mediated Actuation of DNA Origami Hinges
3|keynote|26|Nick Conway|Programmable DNA origami Design with Cadnano 2.5
3|contributed|27|Ze Shi|Modeling the Cation-Triggered Actuation of DNA Origami Hinges
3|contributed|29|Christopher Maffeo|Multi-resolution modeling of DNA origami objects for fast and detailed structure prediction
3|invited|34|Chunhai Fan|Shape-dependent cell entry and intracellular transport of self-assembled DNA nanostructures
3|contributed|136|Pengfei Wang|In Vivo Delivery of siRNA by DNA Nanoparticles for Cancer Treatment
4|contributed|36|Kasturi Chakraborty|DNA-based nanodevices as reporters for lysosomal diseases
4|poster|134|Zhilei Ge|DNA Origami Nanostructures Exhibit Predominant Renal Uptake and Alleviate Acute Kidney Injury
4|poster|140|Yi Li|DNA nanostructures that self-heal in serum
4|poster|144|Chanseok Lee|Polymorphic design of DNA origami structures using mechanically tunable modules
4|poster|146|Shuo Yang|Metal-Ion Responsive Reversible Assembly of DNA Origami Dimers: G-Quadruplex Induced Intermolecular Interaction
4|poster|147|Ashley Stammers|Exploring curvature in single-sheet DNA origami nanotiles
4|poster|149|Timon Funck|Biomolecular Sensor Based on a Gold-DNA-Structure with Switchable Chirality
4|poster|150|Andrew Lee|Observing the Mode and Geometry of RecA-Mediated Homology Search within a DNA origami structure
4|poster|153|Michael Hudoba|Development of DNA Origami Education Modules for Middle School, High School, and Undergraduate Students and Educators
4|poster|155|Jinglin Fu|Undergraduate teaching and research on DNA-scaffolded proximity assembly of biochemical reaction circuit
5|invited|42|Akinori Kuzuya|Single-Molecule Observation of alpha-CyD Rotaxane Incorporated into DNA Origami with Nanocavities
5|invited|43|Andrew Lee|Direct in situ observation of RecA mediated homologous recombination
5|invited|45|Do-Nyun Kim|Mechanical design strategies for DNA origami nanostructures based on multiscale analysis framework
5|poster|161|Nayan P. Agarwal|Structural transformation of wireframe DNA Origami via DNA polymerase assisted gap-filling.
5|poster|162|Chris Wintersinger|Square-lattice wedges to assemble multi-component DNA origami rings
5|poster|163|Nikolay Frick|Progress toward reservoir computing with self-assembled neuromimetic memristor networks
5|poster|165|Tural Aksel|DNA nanotechnology platform for high-throughput cryo-EM studies of small proteins
5|poster|166|Basu Aryal|Gold Nanorod Seeding on DNA Origami Templates to Make Designed Conductive Nanostructures
5|poster|171|Johanna Zessin|DNA Origami-Templated Formation of Semiconducting Polythiophene Wires
5|invited|55|Chris Thachuk|A fast, robust and reconfigurable molecular circuit breadboard using leakless DNA strand displacement cascades
6|poster|180|Behnam Najafi|Modelling The Folding Pathway of DNA Origami
6|poster|184|Maxime Tortora|Predicting the phase chirality of cholesteric liquid crystals of DNA origamis
6|poster|186|Joshua Johnson|Directing self-assembly of multiple DNA nanostructures in a single reaction
6|poster|188|Jacob Majikes|Thermodynamics of DNA looping for origami folding
6|poster|190|Yaron Berger|Fast and Processive Computer Controlled DNA Bipedal Walker
6|poster|191|Jing Pan|DNA Walker Enabled Nanoscale Motility
6|poster|192|David Arredondo|The Effect of Leg Length and Tether Length on Superdiffusive Motion of Two Connected Bipedal Spiders on a Narrow Strip
6|keynote|58|Gourab Chatterjee|A spatially localized architecture for fast and modular DNA computing
6|contributed|59|Stephanie Lauback|Real-time Magnetic Actuation of DNA Nanodevices via Stiff Micro-levers
6|contributed|61|Sungwook Woo|Molecular Crawlers for Inspection and Reconstruction of Molecular Landscapes
7|invited|24|Thorsten L Schmidt|Self-assembled plasmonic waveguides for excitation of fluorescent nanodiamonds
7|contributed|65|Mikael Madsen|A Directional Single-Polymer Photonic Wire
7|contributed|67|Francesca Nicoli|Fluorescence Enhancement of a Single Quantum Emitter in a DNA-Mediated Self-Assembled Plasmonic Cavity
7|poster|197|Brittany Cannon|Coherent Exciton Delocalization in a Two-State DNA-Templated Dye Aggregate System
7|poster|199|Ninning Liu|Super-resolution labelling with Action-PAINT
7|poster|200|Pablo Damasceno|Toward Programmable DNA Origami Lattices
7|poster|202|Mette R. Bakke|Controlled Single-Polymer Photonics on DNA Origami'''


def main():
 before=L.counts();known={r['registry_key'] for r in L.read('publication_reviews')};keys=[]
 path=L.ROOT/'assets/research-20261105/FNANO18schedule.pdf';url='https://www2.cs.duke.edu/fnano/FNANOschedules/FNANO18schedule.pdf'
 for line in ROWS.split('\n'):
  page,kind,pointer,author,title=line.split('|');page=int(page)
  key='conference:fnano2018:'+hashlib.sha256(line.encode()).hexdigest()[:12];keys.append(key)
  if key in known:continue
  ev=evidence(path,url,f'PDF p.{page}; {kind} by {author}; printed abstract pointer p{pointer} (not yet checked against abstract book)')
  date='2018-04-'+str(16 if page<=2 else 17 if page<=4 else 18 if page<=6 else 19)
  L.upsert('publication_reviews',{'registry_key':key,'registry_id':None,'doi':'','title':title,'authors':[author],'authors_complete':False,'author_note':'First listed author transcribed; full list retained in cited schedule.','canonical_work_id':'work:'+key,'canonical_work_status':'provisional_unreconciled','version_links':[],'publication_type':['conference_'+kind],'date_evidence':{'date':date,'source':ev,'primary_verified':True,'meaning':'Scheduled presentation date, not verified first public release.'},'review_stage':'metadata_screened','relevance':'uncertain','design_contributions':['uncertain'],'catalog_eligibility':'unresolved','access':'partial','evidence':[ev],'rationale':'Official program title/author inspected. Potential origami, methodological or uncertain low-keyword lead; no design or source-completeness inference from the program.','reviewer':'Codex program inspection','run_id':'fnano-2018','date':L.DATE,'unresolved_questions':['Inspect abstract and complete authors; reconcile journal/preprint versions and original date.','Determine whether experimental origami designs are presented, modified or reused.'],'legacy_record':{},'revision_history':[]},'Record inspected 2018 conference lead without title-based inclusion')
  L.upsert('discovery_edges',{'edge_id':'fnano2018:'+key.rsplit(':',1)[1],'source_key':'fnano-2018','target_key':key,'relation':'conference_lead','evidence_url':url,'local_file':ev['local_file'],'sha256':ev['sha256'],'locator':ev['locator'],'reconciliation_state':'journal_preprint_counterpart_pending'},'Preserve program lead for abstract and publication reconciliation')
 run=next(r for r in L.read('discovery_runs') if r['run_id']=='fnano-2018')
 run.update(pagination={'pages':7,'pages_inspected':list(range(1,8)),'all_presentations_disposed':False},deduplicated_additions=len(keys),additions_unit='presentation/version leads, not eligible canonical works',closure_state='in_progress',checkpoint=f'All seven schedule pages inspected; {len(keys)} potential leads retained without arbitrary relevance cap. Full author transcription, remaining program-item dispositions, abstracts and journal/preprint matching pending. Archived 2018 program page links to a 2015 program PDF; that does not supply a 2018 abstract book.')
 for filename,source in [('fnano18-home.html','http://www.cs.duke.edu/FNANO18/'),('fnano18-program.html','http://www.cs.duke.edu/FNANO18/program.html')]:
  ev=evidence(L.ROOT/'assets/research-20261105'/filename,source,'Archived official page; program links inspected')
  if not any(x.get('local_file')==ev['local_file'] for x in run['evidence']):run['evidence'].append(ev)
 L.upsert('discovery_runs',run,'Save 2018 program coverage and mismatched 2015 link')
 if not any(b['batch_id']=='DISC0003' for b in L.read('batches')):
  L.upsert('batches',{'batch_id':'DISC0003','date':L.DATE,'status':'completed','input_keys':keys,'before_counts':before,'after_counts':L.counts(),'completed_actions':['Inspect seven-page FNANO2018 schedule; retain potential/uncertain leads.','Follow archived homepage and program links; 2018 abstracts remain unlocated in checked pages.'],'exclusion_audit':{'sample':[],'reason':'No final exclusions; unrecorded program items not yet disposed.'},'validation':[L.validate()],'unresolved_keys':keys,'next_queue':['Inspect acquired 2015 program if available; find 2018 abstract book.','Reconcile conference leads and complete authors; continue other conference years.','Continue persisted B0005 and older source gaps.']},'Checkpoint conference discovery without closure claim')
 print(L.validate());print('2018 leads',len(keys))

if __name__=='__main__':main()
