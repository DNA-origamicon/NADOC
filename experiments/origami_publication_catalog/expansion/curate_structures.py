"""Human-reviewed expansion decisions. References are publication-specific;
sequence sources and exact variant coverage retain separate verification states.
"""
import json
from pathlib import Path
H=Path(__file__).resolve().parents[1]
items=[]
def add(doi,design,lattice,location,modalities,family='',note='',status='primary_source_reviewed'):
 items.append(dict(doi=doi,design=design,lattice=lattice,sequence_location=location,characterization=modalities.split(';'),family=family or design,notes=note,review_status=status))
for design,page,fig in [('Square',25,'S18'),('Rectangle',28,'S21'),('Five-pointed star',31,'S24'),('Disk with holes / smiley',35,'S28'),('Equilateral triangle with rectangular domains',38,'S31'),('Sharp triangle with trapezoidal domains',41,'S34'),('Tall rectangle / map-pattern substrate',45,'S38')]:
 add('10.1038/nature04586',design,'square / single-layer parallel-helix domains',f'Supplementary Fig. {fig}; PDF page {page}','AFM',design,note='Original pre-caDNAno design. Staple sequences inspected in author-hosted supplement. Triangular objects join planar domains; no wireframe edges. Pattern and assembly variants are not counted as new base geometries.')
for length in [1512,2268,3024]:
 add('10.1093/synbio/ysy015',f'6HB nanotube, {length}-nt scaffold','honeycomb','Paper-linked pScaf repository: 6HB source designs and staple CSVs','negative-stain TEM','pScaf 6HB',note='Separate scaffold variant; brick-named objects in the same paper are excluded.')
add('10.1093/synbio/ysy015','Three-scaffold 6HB nanotube trimer','honeycomb','pScaf repository; Fig. 4B–C and connector-staple definitions','negative-stain TEM','pScaf 6HB',note='Assembly of the 1512/2268/3024-nt variants. Connector completeness needs per-file matching; not counted as a wholly new helix cross-section.')
add('10.1038/s41467-019-12639-y','Protein-conductive nanopore NP / NPΔC','square','Supplementary Table 1 / Supplementary Data spreadsheet MOESM3','AFM;confocal fluorescence;ionic-current recordings','Protein-conductive nanopore',note='NP and NPΔC differ in cholesterol anchors. Confocal/current assays are functional, not 3D structural imaging. Methods explicitly specify square lattice.')
add('10.1038/ncomms9102','42-helix two-layer walking track','honeycomb','Supplementary Fig. 9 and Table 1','TEM','Plasmonic walker track',note='Methods explicitly specify honeycomb packing. The separate 3D origami in Table 2 is not assumed identical.')
add('10.1038/s41467-017-02127-6','Modular honeycomb bundle: straight and hinge variants','honeycomb','Supplementary Data spreadsheet MOESM4; reference pool and replacement staples','TEM','Modular hinge bundle',note='Grouped variant family; paper reports dozens of hinge configurations. Do not count every configuration as a separately verified complete sequence list. Closed wireframe/frame assemblies are not included.')
add('10.1038/s41467-019-13507-5','Rectangular metallization canvas','square / single-layer parallel helices','SI sequence tables, PDF pages 35–41; design maps in Supplementary Figs. 22–33','AFM;TEM;SEM','Tall rectangle',note='Digit/letter, seven-dot and tetramer patterns are functionalization/assembly variants of the base canvas. Sequence supplement downloaded; exact variant composition remains group-level.')
add('10.1038/s41467-019-13507-5','Triangular metallization substrate','square / planar domains','SI sequence tables, PDF pages 35–41; Supplementary Fig. 28','TEM;STEM;EDX;SEM','Planar triangle',note='Filled planar triangular origami, not a wireframe; metallized edge patterns are modifications. Verify core-plus-modification combination before synthesis.')
add('10.1038/s41467-018-07805-7','Square tiles for displacement and reconfiguration','square / planar domains','Supplementary Tables 1–4: interior, bridge, edge and label staples','AFM','Hierarchical square tile',note='Invader/cover and X/O label variants share the four-triangle tile architecture; record variants without counting each label as a new geometry.')
add('10.1038/s41467-019-12933-9','Nanohole-forming rectangular tile family N/M/Nf/Mf/O/Of','square / single-layer parallel helices','Supplementary Tables 17–24; common rectangle staples in Table 24','AFM','Rectangle with removable domains',note='Tables 17–23 contain variant/functional sequences and Table 24 the shared core. Completeness requires both, not a single short table.')
add('10.1038/s41467-019-09064-6','DNA-PAINT rectangle with 10/20-nm docking grids','square / single-layer parallel helices','Supplementary Tables 1–3, PDF pages 10–15','DNA-PAINT super-resolution','Rothemund-derived rectangle',note='Docking-site variants and imaging calibration substrates; not separate base geometries.')
add('10.1038/s41467-018-04031-z','Addressability rectangle and 18 docking-pattern variants','square / single-layer parallel helices','Supplementary staple tables; PDF pages 19–23','DNA-PAINT super-resolution','Rothemund-derived rectangle',note='18 unique docking patterns probe 168 staples. Common core plus variant docking extensions must be combined. No raw localization deposit verified.')
add('10.1038/s41598-017-12257-y','48-docking-site Exchange-PAINT rectangle, five barcode variants','square / single-layer parallel helices','Supplemental Table S1; scaffold in Table S2, PDF pages 10–14','Exchange-PAINT super-resolution','Rothemund-derived rectangle',note='Five docking sequences share the substrate geometry; imaging labels are variant metadata.')
add('10.1038/s41467-017-00542-3','Twist-corrected rectangular proximity-recording scaffold','square / single-layer parallel helices','Supplementary Table 1 (core); Table 2 (probe variants); Supplementary Fig. 5','AFM;proximity sequencing','Twist-corrected rectangle',note='Probe arrangements are functionalization variants; sequencing proximity records are not raw microscopy.')
add('10.1038/s41467-017-02028-8','Rectangle with 3×4 grid / four-corner DNA-PAINT motifs','square / single-layer parallel helices','Supplementary Data spreadsheets MOESM7–8','3D DNA-PAINT;spinning-disk confocal','Rothemund-derived rectangle',note='Downloaded sequence spreadsheets. Rectangles used as calibration structures; cellular imaging data must not be assigned to the origami itself.')
add('10.1038/nmeth.3804','qPAINT rectangle: 12/48/150 docking sites and calibration grids','square / single-layer parallel helices','Supplementary Tables 1–6','DNA-PAINT super-resolution','Rothemund-derived rectangle',note='Primary methods enumerate separate staple tables for each docking variant. Whole-cell experiments are separate from the origami standards.')
add('10.1038/srep21266','Aptamer-bearing rectangular origami targeting PfLDH','square / single-layer parallel helices','Supplementary Table S1','AFM','Rothemund-derived rectangle',note='226-staple rectangular substrate with site-specific aptamer modifications; distinguish modified and unmodified variants.')
add('10.7554/elife.05472','Flat rectangular motor-bearing origami','square / single-layer parallel helices','Supplementary file 1: computer-aided staple sequences','fluorescence microscopy;motor trajectories','Rectangular myosin scaffold',note='Motor number and attachment-site variants share the scaffold. DirectionalAnalysis repository is analysis software, not native design files.')
add('10.1016/j.jmau.2015.08.001','Honeycomb DNA nanotube','honeycomb','Main-text Table 1','TEM;AFM;STM','Honeycomb nanotube',note='Authors explicitly specify caDNAno honeycomb design. Table 1 is available in full-text XML; presence does not independently establish completeness of the physical design.')
add('10.1038/ncomms14698','BEARS twist-corrected 2D origami rectangle','square / single-layer parallel helices','Supplementary Data 1 (non-extended and pre-extended oligos)','AFM;barcode sequencing','Twist-corrected rectangle',note='Only scaffolded origami subset; excludes 2D/3D DNA-brick structures. Different scaffold sequence from original rectangle.')
add('10.1038/ncomms14698','BEARS scaffolded 3D origami cuboid','square','Supplementary Data 1; Fig. 5','TEM;barcode sequencing','BEARS origami cuboid',note='Separate from scaffold-free brick cuboid. Square-lattice model is described in methods; sequence spreadsheet contains mixed-design data, so sheet-level matching is necessary.')
# These structure families have explicit lists, but lattice assignment requires
# inspection beyond the primary prose. Keep them visible without admitting them.
for args in [
 ('10.1038/s42003-019-0683-0','10HB thick filament with six 2HB linkers','Supplementary Data MOESM6, core staple spreadsheet','high-speed AFM;darkfield microscopy'),
 ('10.1038/s41467-019-13517-3','DNA origami cryptography structure variants','SI DNA sequences, PDF pages 41–47','AFM'),
 ('10.1038/s41467-019-09002-6','Frustration-study origami variants','Supplementary Data MOESM4','AFM;single-molecule fluorescence'),
 ('10.1093/nar/gky1189','Sequence-dependent nick / twisted 6HB variants','Supplementary Table S18','TEM'),
 ('10.1093/nar/gkx1262','Square-lattice single-layer model test structure','Supplementary Table S3','AFM;FRET'),
 ('10.1038/ncomms1452','DNA origami pliers and forceps','Supplementary Tables S1–S3; Figs. S5–S10','AFM'),
 ('10.1038/s41467-018-03198-9','Curved 20HB membrane-sculpting H/Q designs','Supplementary Tables 3 onward','TEM;fluorescence microscopy'),
 ('10.1021/acsnano.6b03759','19-cholesterol funnel-shaped porin','Supporting Tables S1–S6','TEM;confocal fluorescence'),
 ('10.1126/sciadv.1602803','Reconfigurable chiral plasmonic origami','Supplementary Table S1','TEM;CD spectroscopy'),
 ('10.1126/sciadv.1602128','Metafluorophore origami variants','Supplementary Table S1','fluorescence microscopy'),
 ('10.1002/anie.201302727','Rigid multihelix DNA beam variants','Supporting Table S1','TEM;single-molecule mechanics'),
 ('10.1021/nn5011914','Membrane-encapsulated DNA nano-octahedron','Supporting Information sequence list','TEM;fluorescence'),
 ('10.1021/ja906381y','2×21, 3×14, 6×12 and 8×8 square-lattice blocks','Supporting Information; sequence list retrieval unresolved','negative-stain TEM;cryo-EM'),
 ('10.1073/pnas.1215713109','Square-lattice cryo-EM pointer object','Supporting sequence information; PDB 4V5X polymer sequences','cryo-EM'),
 ('10.1038/nature07971','DNA box with a controllable lid','Supplementary Data sequence list','cryo-EM;SAXS;AFM;FRET'),
 ('10.1038/nature14860','Small origami folding-pathway variants','Supplementary nucleotide sequences','AFM'),
 ('10.1039/b907800b','Box-shaped 3D origami with joint strands','Publisher-listed supplement: staple and joint sequences','AFM;DLS'),
]:
 doi,design,loc,mods=args
 lattice='square' if doi in ['10.1021/ja906381y','10.1073/pnas.1215713109','10.1093/nar/gkx1262'] else 'requires_design_specific_review'
 add(doi,design,lattice,loc,mods,note='Named structure and sequence source identified; not yet counted as a verified in-scope sequence-complete design. Preserve this gap rather than infer topology from a paper title.',status='candidate_scope_or_list_verification_needed')
(H/'expansion/curation.json').write_text(json.dumps(items,indent=2)+'\n');print('curated design groups',len(items))
