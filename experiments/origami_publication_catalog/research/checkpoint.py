"""Recompute research handoff from saved ledgers and actual local files."""
import json
from collections import Counter
import ledger as L


def main():
    c=L.counts(); validation=L.validate(); batches=L.read('batches');edges=L.read('discovery_edges')
    acs=json.loads((L.ROOT/'acs_acquisition.json').read_text())['records']
    files=[f for r in acs for f in r['files'] if f['status']=='downloaded']
    present=sum((L.ROOT/'assets'/f['local_file']).is_file() for f in files)
    articles={a['id'] for r in acs for a in r['articles']}
    metadata=sum((L.ROOT/f'assets/sources/acs-expansion-20261104/article-{i}.json').is_file() for i in articles)
    active=[b for b in batches if b['status']=='in_progress'];completed=[b['batch_id'] for b in batches if b['status']=='completed']
    conference_count=sum(any(t.startswith('conference_') for t in r.get('publication_type',[])) and r.get('run_id','').startswith('fnano-') for r in L.read('publication_reviews'))
    screened=sum(bool(r.get('legacy_record',{}).get('key')) and r['review_stage']!='unreviewed' for r in L.read('publication_reviews'))
    out=f'''# DNA origami literature census checkpoint

Updated {L.DATE}. Persistent research goal active following resumed continuation; closure criteria are not met.
Local sidecars, not session goal state, are the portable authority. No commits,
pushes, molecular authoring, simulation, or production changes performed.

## Saved counts and denominators

- Legacy publication registry: 2,210 records; legacy map: 100 groups (75 reviewed,
  25 candidates). All stable IDs and legacy evidence preserved unchanged.
- Research publication/version records: {c['publication_versions']}; includes {conference_count}
  FNANO 2010–2019 program leads (including a withdrawn2014 poster). {screened} legacy registry records have been screened
  in screening and conference-follow-up batches (source checks remain open); program-only leads have their own publication types. Most work keys remain provisional. One pScaf preprint/journal pair has an explicit
  Crossref version relation; the two publication records retain separate dates.
  Canonical work keys: {c["canonical_work_keys"]}; provisional unreconciled keys: {c["provisional_work_keys_not_reconciled"]}.
  These are not a fully identity-reconciled work count.
- Review stages among those {c['publication_versions']} records: {json.dumps(c['review_stages'])}.
  Stages indicate depth of inspected evidence, not completion of every source check.
- Relevance: {json.dumps(c['relevance'])}.
- Catalog eligibility: {json.dumps(c['catalog_eligibility'])}. Wireframe DNO is
  literature-relevant but catalog-excluded. Legacy map remains unchanged; newer
  sidecar decisions and pending catalog synchronization are explicit.
- Design groups: {c['design_groups']} total, preserving all 100 legacy IDs; two
  research-only nonstandard-lattice groups are excluded; two further thesis groups
  await scope/source verification, one new nano-brick group has explicit
  honeycomb evidence, and two CanDo experiment groups retain source checks. A further2007 nanotube family separates front/rear components from their heterodimer assembly. Groups with new
  extraction notes: {c['design_source_reviews']}. No newly certified complete synthesis sets; no new map promotions. The sole
  newly recorded eligible decision reaffirms an existing square-lattice paper.
- Discovery edges: {len(edges)}. Relation counts: {json.dumps(dict(Counter(e['relation'] for e in edges)))}.
  Edge reconciliation: {json.dumps(dict(Counter(e['reconciliation_state'] for e in edges)))}.
  Reference targets are leads, not automatically eligible publications.
- ACS documents present now: {present}/269; metadata files present: {metadata}/360.
  The completed read-only restoration audit verified all 269 document sizes and
  SHA-256 values and found no missing metadata (exit 0); see
  `research/local_asset_audit.json`. Metadata presence is not a document checksum.
  At session start 0/269 ACS files existed. All 672 older recorded XML files existed.

## Batch history and reproducibility

Completed batches: {', '.join(completed) or 'none'}. Active batches: {', '.join(b['batch_id'] for b in active) or 'none'}.

Five durable JSONL ledgers live in `research/`: `publication_reviews`,
`design_evidence`, `discovery_runs`, `discovery_edges`, `batches`.
`ledger.py init` imports missing legacy keys without promoting review stages;
`select` persists/resumes queues; mutations retain superseded rows. Acquisition
sources and extraction previews are under `assets/research-20261105/`, with a
hashed acquisition manifest. Original XML and ACS paths/hashes accompany decisions.
`review_batch_0001.py`, `review_batch_0002.py`, and `review_batch_0003.py` / `review_batch_0003_rotation.py`, and `review_batch_0004.py` / `review_batch_0004_rotation.py` / `review_batch_0004_primary.py` contain explicit source-reviewed
decisions, not keyword rules. `review_batch_0005.py` / `review_batch_0005_rotation.py` record the fifth balanced batch. `review_fnano2019.py` records only program leads.
`index_sources.py` retains extraction diagnostics; the AuNP-alignment SI
(`4310950-nl200306w_si_002.pdf`) produced Poppler warnings. That PDF still requires
source-image checks; text extraction has not certified image integrity. The B0003
metallized-wire SI (`4132963-jp302316p_si_001.pdf`) also produces Poppler warnings.
`discover_batch_0001.py` parses both JATS pub-id and ext-link DOI forms and retains
all references irrespective of title. Initial incomplete extraction remains in revision
history. The 523 distinct target keys still include unresolved no-DOI references;
they are not a deduplicated work count.

Latest saved validation: `{json.dumps(validation)}`.
Eighteen focused tests passed: one bibliography duplicate-anchor/resume fixture, nine ledger/acquisition persistence fixtures, four
Crossref discovery fixtures, and four ACS restoration fixtures. Unicode separators
and reordered query parameters exposed resume failures on live data; both were
fixed and regression-tested, and the saved first page replayed without duplicate
records. Failure history is retained in the discovery run. Run `python3 research/test_ledger.py` from the catalog,
or the corresponding repository-relative path. B0001 audited its sole catalog exclusion on SI Fig.1; B0002 audited its sole
background-only exclusion against saved publisher HTML. B0003 audited its sole final exclusion against the entire subscription-notice XML,
retaining the cover-credit lead. These were same-agent second passes, not independent review.

## Access, next queue and coverage gaps

Enzyme-cages2016 (10.1038/ncomms10619) targeted review added RDE0086/87/88 for
SH single-layer honeycomb, SS single-layer square and DS double-layer square cage
architectures. Six half-cage staple pools each pass the100-entry gate; half-cages
are components and cargo variants are not additional cores. SI linkers/probes
indexed separately: SH210/210, SS219/221, DS220/228 half-cage rows;
linker pools24/18/24 respectively. These are indexed rows, not certified complete
recipes. Capture-probe conflict retained: Results says two, Methods
four per half-cage, listed probe sequences three per half. No complete synthesis
recipe certification or silent corrections. Open-/closed-wall variants need mapping.
Figure60 PDF60 visually inspected; Fig1/61 captions state lattice; narrow geometry
eligibility remains open. Evidence: assets/sources/PMC4749968.xml and
assets/sources/pre2020-expansion/supplements/PMC4749968-41467_2016_BFncomms10619_MOESM965_ESM.pdf,
Note4 PDF69-103. Script/index: research/review_cages2016.py and
research/cages2016_source_index.json. All three SEQ0003 passing papers now have
targeted followups. Next: balanced first-screen batch, preserving priority-author
coverage and low-signal rotation. Failed/unknown gates inactive; FNANO deferred.
Current validation/counts above; source completeness and discovery closure open.

Photoswitch2016 (10.1038/ncomms10591) targeted source review added RDE0085 as a
modified source family, not a proven novel core. Methods explicitly adopt the
2014 template (10.1038/nmat4031); parent relationship retained. Two14HB bundles
carry handedness-specific disulfide/azobenzene branches. Table1 has138shared core
rows plus two mutually exclusive RH/LH rows,24nanorod handles and separate modified
branch recipes. Figure3 PDF3 visually inspected; routing and complete chemistry
verification remain open. Published scaffold designation p7650 is retained
literally rather than silently changed. Narrow lattice eligibility unresolved.
Evidence: assets/sources/pre2020-expansion/PMC4740900.xml and supplements/
PMC4740900-41467_2016_BFncomms10591_MOESM891_ESM.pdf, PDF18-24.
Reproduce: research/review_photoswitch2016.py; index:
research/photoswitch2016_source_index.json. Next: qualifying enzyme-cage paper
10.1038/ncomms10619, then balanced source-screen rotation. No-table records
inactive; FNANO deferred. Current counts and validation above.

Deposition2015 (10.1038/srep15634) source followup retained D024 and added RDE0084
for the planar double-triangle. Methods explicitly state square packing with
scaffold deletions to reduce twist; FigureS4 PDF5 visually inspected at overview
scale. TableS3 has163unique position-pair rows. D024 TableS4 has141rows plus six
separate Cy5 linkers (TableS2); the141rows alone are not the complete labelled
recipe. Seeman tile/hexagonal tube reuse references7/52 retained, including
side-strand omissions and five hexagonal-tube linkers. No new groups inferred
for those reused templates. Exact prior-core reconciliation, sequence-image
verification and complete synthesis sets remain open.
Evidence: assets/sources/PMC4616047.xml and
assets/sources/pre2020-expansion/supplements/PMC4616047-41598_2015_BFsrep15634_MOESM1_ESM.pdf.
Reproduce with research/review_deposition2015.py; index:
research/deposition2015_source_index.json. Next qualifying sources:
10.1038/ncomms10591 and10.1038/ncomms10619, then balanced first-screen rotation.
Failed/unknown gates inactive; FNANO deferred. Current validation/counts above.

SEQ0003 balanced first-screen batch completed: 10 previously unreviewed records,
five with saved supplements plus five low-signal records from distinct years.
Three pass: srep15634 (163 double-triangle staple rows), ncomms10591 (140 core
staple rows), ncomms10619 (210 rows in the first SH cage section). Seven have no
qualifying table found in checked sources: two saved supplements and five records
with empty source inventories. Those five remain availability-unknown, not proven
source-absent. No new scientific exclusions or design groups in this batch.
Saved keys/index/report: research/sequence_chunk_0003_*.json; reproducible selection
and decisions: research/select_sequence_chunk_0003.py and
research/apply_sequence_chunk_0003.py. The macro-brick DOCX was inspected separately
because the existing candidate-string index handles PDFs only. The amplification
paper's primer table received a same-agent second pass; no100-entry staple list
was found in that saved SI. No end-to-end speedup or corpus recall estimate claimed.
Next source reviews: 10.1038/srep15634, 10.1038/ncomms10591,
10.1038/ncomms10619; continue rotating low-signal records in subsequent batches.
Failed/unknown gates inactive; FNANO deferred. Validation and current counts above.

Walker2015 (10.1038/ncomms9102) qualifying-source followup retained S013 for
the explicitly honeycomb 42-helix two-layer plate and added RDE0083 for the separate
triangular-prism track. Walking stations are states, not additional cores.
Table1 PDF12-16 has 210 unique position pairs; Table2 PDF17-20 has 147 entries
but 141 unique position pairs. Six repeated pairs are retained; the E/F duplicates
were confirmed in the PDF20 image. No sequence repairs or completeness claim.
Figure7 PDF7 shows a filled prism cross-section; exact lattice eligibility remains
unresolved. Source: assets/sources/PMC4560816.xml and
assets/sources/pre2020-expansion/supplements/PMC4560816-41467_2015_BFncomms9102_MOESM1085_ESM.pdf.
Script/index: research/review_walker2015.py, research/walker2015_source_index.json.
All seven SEQ0001 passing papers now have targeted followups; complete recipes and
reuse reconciliation remain open. Next: balanced first-screen chunk across saved
sources and low-signal records. No-table records inactive; FNANO deferred.

SLB2015 (10.1038/ncomms9052) targeted source review added RDE0082, one
provisional cross-shaped origami family. SI Table1 has 215 unique labels, including
linking/4HB/loop entries; this is not a verified complete sequence count. Table2
contains 24 edge replacements with two T4 tails each; Tables3/4 specify four-biotin
and eight-biotin variants (Table4 includes eight additional partner strands).
Figure18 routing image inspected; exact folded packing, prior-template identity,
base-level verification and complete recipes remain unresolved. Triangle and
hexagon reuse references retained separately; no new groups inferred for them.
Evidence: assets/sources/PMC4560778.xml and
assets/sources/PMC4560778-41467_2015_BFncomms9052_MOESM1003_ESM.pdf,
PDF25-32. Reproduce with research/review_slb2015.py; label/variant index:
research/slb2015_source_index.json. Ledger/hash validation passed; regenerated
counts above are authoritative. Next: qualifying ncomms9102, then a balanced
first-screen chunk. Failed/unknown source gates remain inactive; FNANO deferred.

Amyloid2014(10.1038/nnano.2014.102) qualifying-source followup:RDE0080tube and
RDE0081four-tileplatform recorded. Tube20gon uses15/26/25bp crossoverdomains,
nonstandardcurvedcrosssection explicitlynarrow-catalogexcluded; stillliterature
relevant. Platformfour32-entryconnector sets andLegvariants separatefromshared
staples;threeone-fibril/onetwo-fibril arrangements notnewcores automatically.
171tube entries extracted; source labels123 asStaple123. Firstregexfailed by
consumingnextTubeinitialT; replacedwithline-based parser andboundedsection.
Sourcebase/variantimageaudit pending; no completenesscertification. Script
research/review_amyloid2014.py,indexresearch/amyloid2014_source_index.json.
Evidence assets/sources/pre2020-expansion/PMC4082467.xml andsupplements/
PMC4082467-41565_2014_BFnnano2014102_MOESM286_ESM.pdf. Nextqualifiers
ncomms9102/ncomms9052,thenbalancedfirstscreenchunk. No-tableinactive,FNANOdeferred.

Quality2014(10.1038/ncomms4691) source-gate followup: D02042HB enriched;
RDE0076-0079record experimentallyreported6/8/10/12HBarchitectures withqualifying
sequencepools. p7560,omittedstaple pseudo-defects,Cy5objectlabel/Cy3probe roles
retained. Omission/thermalconditions notcounted asnewcores. SIoddTables1-11
sequence-length pairs indexed inresearch/quality2014_sequence_index.json; not
complete sourcecertification. Table11caption42HBinternaldefects conflictswith
substantialextractedoverlap againstTable9(12HB); source-imageauditneeded,no repair.
Targetedmain Methods/architecture/qualityparagraphs andSIcaptions/tables inspected;
crosssection/native/source-completeness remainopen. Scriptresearch/review_quality2014.py.
Evidence assets/sources/PMC3997801.xml andpre2020-expansion/supplements/
PMC3997801-41467_2014_BFncomms4691_MOESM86_ESM.pdf. Nextqualifiers
nnano.2014.102,ncomms9102,ncomms9052; maintainbalancedfirstscreens.
No-tableinactive,FNANOdeferred; no certifiedcomplete synthesis sets added.

Amir2014robot(10.1038/nnano.2014.58) qualifying-source followup: existingD025
enriched,no newcoregroup. Mainexplicitly reusesDouglas/Bachelet/Church2012
10.1126/science.1214081. SI278numberedentries indexed:153core,82edge,1Keyhandle,
11handles,7guides,7guideremoval,17gates. Entirepool isnot anindividualrobotrecipe.
PDF15E/P1/P2/N/F/P3 gate/payload compositions distinguished fromlogic mixtures;
Eopen lacks sensingstrands. NativecaDNAnoJSON explicitlymentionedPDF5,notyetin
savedset. SIcorrected2014-04-17addingNote6;XMLepub2014-04-06retained. Targeted
main/SIPDF1,4,5,8-16review;fullbase/image/variantcompleteness stillpending.
Script research/review_amir2014.py,indexresearch/amir2014_strand_index.json;
evidence assets/sources/PMC4012984.xml and
PMC4012984-41565_2014_BFnnano201458_MOESM9_ESM.pdf. Popplerfontweightwarnings
retained inrunoutput; extractiondoesnotcertifyimageintegrity. Nextqualifier
ncomms4691,then nnano.2014.102; maintainbalanced firstscreening,no-tableinactive.

DNA-PAINT2014(10.1038/nmeth.2835) qualifying-source followup: targeted origami
Results/Methods andSI table contexts reviewed;FigureS1PDF2 visuallyinspected.
RDE0074 records p8064microtubule-like16x16x75nm monomer andseparateconnector
polymerization;RDE0075provisionally groups single-layer driftmarker andrectangle
digit variants without asserting identicalcores. Tables3/4odd/even patterns,
Table5ONLYmodifiedstrands; nottenindependentcores orcomplete standaloneTable5.
Position-based index candidate rowsTables1-5:234/184/184/184/85;differentfrom
rawACGT-run counts,notcertifiedstrandcounts. Sourcecolors/variantassemblypending.
ZIPmemberhashes saved:imagingexe/dll/config,notnativeDNA designs; nothingexecuted.
Spreadsheetsunparsed. XMLepub2014-02-02;34references retained. Script
research/review_paint2014.py,indexresearch/paint2014_source_index.json.
Evidence assets/sources/pre2020-expansion/PMC4153392.xml andsupplements/
PMC4153392-41592_2014_BFnmeth2835_MOESM233_ESM.pdf /234_ESM.zip.
Nextqualifier nnano.2014.58(robotstaples),then ncomms4691; keepbalancedfirstscreens.
No complete synthesis sets certified; no-table recordsinactive,FNANOdeferred.

Gu2009(10.1038/nnano.2009.5) qualifying source reviewed: entiremain body and
SIexperimentalmethods/helperlist;FigureS1PDF12routing visuallyinspected.208unique
namedhelpers indexed in research/gu2009_helper_index.json. NewRDE0073records
120x50nm notched two-slot substrate; PX/JX2device states andfourcapturetiles are
functional variants,not fourneworigami cores. M13clone,basecoverage andancillary
cassette/set/fuel recipes remain unverified; no complete-source certification.
ExplicitXMLepub2009-02-15;14main+2SIreferences retained. Scriptresearch/review_gu2009.py.
Evidence assets/sources/pre2020-expansion/PMC2836238.xml andsupplements/
PMC2836238-41565_2009_BFnnano20095_MOESM188_ESM.pdf. Nextpassing source
10.1038/nmeth.2835,thenotherSEQ0001qualifiers; maintainbalanced firstscreening.
No-table records remain inactive; FNANOdeferred.

SEQ0002 completed first source gate over all25 B0017inputs:2prioritize(Rothemund2006
andnnano.2009.5),2patents excluded,21no qualifying table found inchecked saved
sources. This is NOT21confirmed source absences or25fulltext reviews. Most lack
recorded supplement links/downloads; availability stays unknown,inactive underuser
instruction. UNIQUIMER3D XMLTables1-3 have4/6/32strands; belowthreshold. Cover,
abstract andhighlights XML inventories have no qualifying tables. Evidence and
scope in research/sequence_batch_0017_report.json; reproducible script
research/screen_batch_0017_sources.py. No rescue retrieval requested. Prior deep
review counts preserved. Next process qualifyingnnano.2009.5 andSEQ0001's7passing
sources,then select anotherbalanced first-screen chunk. FNANOdeferred.

Latest user instruction: qualifying staple table/list(at least100DNA entries) is
the mandatory FIRST screening gate. If not found in readily available sources,
record sources checked andmove on; no deep review,extended retrieval,or human
request torescue that record. Unknown access/extraction remains explicit butinactive.
Earlier missing-source followup queues below are superseded for gate-failing records.
Reopen only on new source evidence or user request. Patent exclusions remain inforce.
Next work: gate remaining B0017 records first; process SEQ0001's7passing sources;
leave its3deferred records outof active recovery. Received Estrich dissertation may
be used for the alreadypassing diblock staple-list paper. No design completeness
is implied by passing this screen. See RESEARCH_PROTOCOL.md andREADME.md.

User workflow update: patents excluded regardless of source availability; all3
patent-type records retain IDs/evidence but now have explicit census-scope and
catalog exclusions. Earlier patent followup queues below are superseded.
SEQ0001 rapid-source pilot screened10 previouslyunreviewed records with available
PDF supplements:7 prioritized for large staple lists,3 deferred. This is not10
fulltext/design reviews. Named table/strand context checked; RNAcube image table
visually inspected andbelow100, FRET221whole-document strings split among small
tables anddo not pass, DARTfunctionaloligos belowthreshold. Scaffold sequences and
linewrap fragments excluded from qualifying-list judgments. No design certification.
Evidence/counts/decisions: research/sequence_pilot_0001_index.json and
sequence_pilot_0001_report.json. Frozen10keys in sequence_pilot_0001_keys.json;
reproduce with screen_sequence_sources.py --keys KEYFILE --output INDEXFILE,
then apply_sequence_pilot_0001.py for preserved human decisions. Do not substitute
a different index into the fixed pilot decision script. Availability-biased sample;
timing measures extraction only,not human review or proven end-to-end acceleration.
Next: process7priority sources andexpand rapid screening across balanced backlog;
missing/unreadable sources remain unknown,not no-source exclusions. Publication
relevance stays separate from source gate; FNANOdeferred. B0017historic4reviewed
inputs unchanged; additional metadata/source triage andpatent exclusions recorded.

Human-access update: ACCESS-a556b23d8f received from user-provided Downloads/etd.pdf.
Verified title,author,institution,2016 copyright/title pages andcontents as requested
Nicole Ashley Estrich dissertation; this is a related source,not ACS SI. Stored
assets/human-assisted/ACCESS-a556b23d8f-438497c62f1b.pdf,8445785bytes,
SHA256438497c62f1b38634ed79d16f8b8444d1d13ed8ff03197d21b22c7d724ec61c4.
Original download untouched. Access queue has no pending human requests. Attached
to10.1021/acsnano.6b07291 and existingRDE0055/RDE0056 without review-stage or
source-completeness promotion. Next source review: Chapter2 printed31-49,Chapter4
85-118,AppendixA169-193(PDF186-210),compareDesign1/2A/2B with journalSI.
Script research/receive_estrich_dissertation.py; scientific contents still pending.
This receipt does not change B0017's4of25processed count.

B0017 now4of25processed:3substantive reviews plus1metadata-only;21untouched.
Sepel2007 DOI10.55838/1980-3540.ge.2007.32 excluded from both molecular-origami
relevance and narrow catalog after all3pages: printed-paper classroom folding,
not DNA self-assembly. Three references retained; teaching templates unacquired.
Primary PDF/HTML saved as assets/research-20261105/sepel2007-paper.pdf and
sepel2007-publisher.html. Script research/review_batch_0017_third.py.
epmc:1842 resolved to CN101050228A; original cover visually verifies publication
2007-10-10 versus legacy filing2007-03-22. Original16-pagePDF and machine-translated
HTML saved as cn101050228a.pdf/.html in the same asset directory. Targeted Example1
supports China-map229oligos/BsrBI and candidate existingRDE0044 relationship;
no canonical merge or new design group. Example2 inductor/silver embodiment needs
original-text, source and experimental-evidence audit. Translation contains
concatenated numeric routing lengths, unsuitable for reconstruction. Remaining
patent pages,embodiments,citations and complete recipes unreviewed. Script
research/review_batch_0017_fourth.py. Next balanced input epmc:1391,then remaining
21inputs; source/citation and priorityauthor routes continue,FNANOdeferred.

B0017 now2of25processed:1source-reviewed Rothemund and1metadata-only EBSA
abstract collection PMC7080001;23untouched. The latter XML has no body, so old
fulltext-triaged label is not content evidence. Primary DOI10.1007/s00249-007-0178-7
and epub2007-06-14 recorded;2020PMC release is not first publication. Actual PDF
249_2007_Article_178.pdf still needed; no design decision or canonical merge.
Script research/review_batch_0017_metadata.py. Next balanced input
10.55838/1980-3540.ge.2007.32; Rothemund SI and citation followups stay open.

B0017 main-paper followup: all Rothemund2006 main text and Figure1-3 captions
read, with figure-image audit still pending. Existing S001-S007 now retain explicit
linear/circular scaffold, seam, vertex-bridge, pattern and assembly distinctions.
All24 printed main references retained without relevance filtering; identity/scope
reconciliation pending. No new publication or design count, no complete-source
certification. Script research/review_rothemund_main.py; validation passed with
6158 publication keys,100 stable legacy IDs and15881 hashed evidence references.
Next balanced input PMC7080001, followed by remaining B0017 queue; remaining
Rothemund SI recipes and citation leads stay open. Priority authors/citations
continue; FNANO deferred. Access-system checks5/5 and payload checks3/3 passed;
NCState dissertation request ACCESS-a556b23d8f remains pending, independent work open.

Earlier B0017 firstreview:1of25inputs targetedsource-reviewed,24remain. Rothemund2006
mainPDF acquired assets/research-20261105/rothemund2006-main.pdf; header/abstract
onlyread. ExistingSI1/2 inspected selectively, no newdesignIDs. S007tallrectangle
32helices/224ntnominalwidth;SI1S38PDF45 has225uniquenamed rows forBRIDGEDseam,
whileexperimentalmapS37PDF44 usesUNBRIDGEDseam,T4edgeloops/twoT4cornertails.
FigureS37visuallyinspected; research/rothemund2006_tall_rectangle_index.json is
literalbridgedtable extraction, notexperimentalrecipe. S004smiley Note12explicitly
warns incorrectnoncentralscaffoldcrossovers/spuriousdashes; retaincoloredcontinuity
andfoldingpath requirement. SI1S39NEBclone sequence reflects2002resequencing.
Readscope evidenceandhashes saved; no sourcecertification orcatalogpromotion.
Script research/review_batch_0017_first.py. NextreadRothemundmain/remainingSI and
rotatePMC7080001; priorityauthor/citationcoverage stillopen,FNANOdeferred.

B0016 firstpassclosed25of25inputs:22substantive reviews+3metadata/abstract-only
(Talks,solarnews,BCRposter), notcomplete sourcevalidation. B0017 selected/persisted
25balancedinputs startingRothemund2006(10.1038/nature04586); preserveexistingSIDs.
LatestAmoako2019paper acquiredfrompublisher,all7pages textread: crossreuse linked
existingRDE0042,four-end eightmodifiedstrand variant distinct2015two-endvariant;
provisionaltubeRDE0072 with10AuNPsites, reported7occupied,networkdistortion/aggregation.
18Table1literalrows matchprintedlengths;K5prose/K2table discrepancy unresolved.
41references retained; exact2013/2018parent sourcevariants pending. Evidence
assets/research-20261105/amoako2019-publisher.pdf and
research/amoako2019_connection_index.json. Figuresnotvisuallyaudited.
BCR10.4049/jimmunol.202.supp.130.13 correctedconferenceabstract; primarywebabstract
andAAIprogram identifyP1230,Chaudhary/Schoettle/Dubois/Jones/Ulrich/Yan/Blattman.
Researcherwebsummary research/bcr2019_web_evidence.json isNOTdownloadedprimary;
local403/404/nonPDFattempts retained. Design-bearing leadonly,noRDE fromabstract.
Script research/review_batch_0016_twentyfirst.py; validationpassed. Next workB0017
andpriorityauthor histories,includingHaoYanBCRpublicationmatch,Ahmadi2018sources,
Amoako2013/2018parents. FNANOremainsdeferred. Goalclosure criteriaNOTmet.

B0016 twentieth pass:23of25inputs processed=21substantive+2metadata-only;2firstpass
inputsremain. JoVE10.3791/58771 publisherHTML acquired locally despite webtool
JavaScriptchallenge: assets/research-20261105/jove58771.html(522785bytes). Intro,
protocol1-2/11-12,Results,Figures1-4captions,Discussion inspected;steps3-10 andvideo
notfullyreviewed. Explicitadaptation ofAhmadi2018ref16(10.1039/c7nr09461b), not
Ponnuswamy2017whichiscontextref12. RDE0070NRsquare-latticerod/NBhoneycombbottle
andfunctionalNRvariants;RDE0071DAEDALUSwireframeWN,narrowcatalogexcluded.
NR3biotin-HRP andup-to24PS2.Maptamerhandles; exactstapleIDs/fullsourcepending.
All28referencesretained. RSCc7andc8supplementpath attempts404; noentitlementclaim.
Script research/review_batch_0016_twentieth.py. Nextremaining2inputs:
10.4049/jimmunol.202.supp.130.13 conferenceabstract and10.5539/jmsr.v8n4p14.
ParentAhmadi2018main/SI/nativefiles remainunreviewed; no sourcecompletion certified.
Talks/news metadata-onlygaps andpriorityauthor discovery remainopen; FNANO deferred.

B0016 nineteenth pass:22of25inputs processed=20substantive reviews+2metadata-only
(Talks and2006solarnews);3firstpassinputs remain.10.3762/bjnano.10.153 review is
background/narrowcatalogexcluded after targetedinterface/origami/attribution/conclusion
inspection. Yonamine2016ref219(10.1039/c6cp01586g) describes lipid-complexed90x65nm
origami rectangle polymerization by repeatedcompression; Figure8AFMreproduction is
credited separately to2019ref144(10.1021/acs.langmuir.8b01434). Retainbothpaths,
not a newdesign inreview.294references appended atomically preservingexisting rows;
remainingmaterialsections and citedsources notfullyreviewed. Evidence
assets/sources/pre2020-expansion/PMC6693411.xml. No designgroup added.
News publisherAPI returned valid1915byteXML coredata only (openaccess=true), notbody:
assets/research-20261105/solarnews2006.xml; dateDecember2006cover, exactonlineunknown.
Sourceaccess gap explicit, no title-only relevance exclusion. Script
research/review_batch_0016_nineteenth.py. Next10.3791/58771 JoVEcoatingprotocol,
then10.4049/jimmunol.202.supp.130.13 and10.5539/jmsr.v8n4p14. Priorityauthor
and citationroutes remain open; FNANO deferred. No newhumanrequest required.

B0016 eighteenth pass:20of25inputs processed=19substantive reviews+1metadata-only
collection;5firstpassinputs remain.10.1038/nrg1892 classifiedbackground_or_review,
narrowcatalogexcluded after targetedstructuraldiscussion/Figure5-6/conclusions audit.
Figure5c reproducedRothemund2006ref42; Shih2004octahedron isref43. No new design
group or experimentalreuse inferred. All82bibliographyentries retained, reconciliation
pending. Evidence assets/sources/pre2020-expansion/PMC7097529.xml; publisherXML
epub2006-06-13. Remaining sequence/folding/computation sections not fullyread.
Script research/review_batch_0016_eighteenth.py. 2006solarnews ScienceDirect web
attempt403; no articleclassification inferred from title. Next localreview
10.3762/bjnano.10.153; remainingalso news10.1016/s1369-7021(06)71752-7,
10.3791/58771,10.4049/jimmunol.202.supp.130.13,10.5539/jmsr.v8n4p14.
Talks access and priorityauthor/citation discovery remain open; FNANO deferred.

B0016 seventeenth pass:19of25inputs processed =18source/text reviews plus1
metadata-only collection,6firstpassinputs remaining. PMC6610276 identified as
FEBS2019 Talks aggregate, DOI10.1002/2211-5463.12674; stablePMCkey preserved.
Corrected type toconference_abstract_collection. FullTalks pages2-64 NOT reviewed.
Acquired assets/research-20261105/febs2019-abstracts.pdf is only4pages: cover,
issueinformation, posterpages265-266; it verifies collection identity, not coverage.
Issueinformation distinguishes Talks andPosters DOIs and says abstracts notpeerreviewed.
EuropePMCXML500, NCBlOAendpoint404, EuropePMCPDF403 and WileyPDF403 saved in
acquisitionmanifest. These do not establish absent CUentitlement. No design or
negative relevance decision inferred. Script research/review_batch_0016_seventeenth.py.
Next10.1016/s1369-7021(06)71752-7 news(primarytext stillneeded), then10.1038/nrg1892
review(existingXML); returnTalksfulltext independently. FNANO remains deferred;
this is an existing balancedbacklog input, not new conference-route expansion.

B0016 sixteenth review:18of25inputs reviewed,7remaining, plus existing preprint
followup.10.1021/acsabm.9b01171/RDE0069 computational honeycomb tetrapods:
6/10HBdirect units,32HBangled wings and proposed84HB-arm hierarchical assembly.
All10SIpages text inspected,FigureS4PDF6 visually checked. Local honeycomb does not
establish whole-object catalog eligibility; no experimental fabrication or complete
source set certified. PreprintPDF acquired as assets/research-20261105/diamond-main.pdf
(filename notwithstanding, this is NOT journalmain): header verifies2019-12-19 for
10.1101/2019.12.17.880302. ACSjournalhistory gives2020-01-07online; legacy2019-12-24
matchesacceptance/banner. Keep separate versions and candidate relationship, no
canonical merge (Crossrefrelation empty). TargetedpreprintPDF4-5/8/15-16read;
remainingmain unreviewed.57Crossref bibliography metadata leads and5SIreferences
retained. p8634/p8623 wording discrepancy explicit. Script
research/review_batch_0016_sixteenth.py. Next rotate to PMC6610276 Talks abstract
collection and remaining balanced backlog; priorityauthor histories remain open,
FNANO expansion deferred. Evidence SI20707317-mt9b01171_si_001.pdf plus acquired
preprint and diamond-preprint-crossref.json. No human intervention required.

B0016 fifteenth review:17of25 inputs reviewed,8remaining.10.1021/acscentsci.9b00964
pH peptide-DNA locks excluded as not_origami after main Introduction/Results/Discussion
and SI methods/captions/sequence-table audit. Short duplex/triplex peptide conjugates,
including short scaffold-named linker, are not origami. Douglas2012 and Amir2014
nanorobots are cited prior work. All46main references retained without relevance cap.
Evidence assets/sources/pre2020-expansion/PMC6978833.xml and
assets/sources/acs-expansion-20261104/20394732-oc9b00964_si_001.pdf.
XMLepub2019-12-23, issue2020-01-22. Script research/review_batch_0016_fifteenth.py;
no design group added. Next10.1021/acsabm.9b01171 Diamond Photonic Crystals,
then remaining balanced queue and priority author/citation discovery; FNANO deferred.

B0016 fourteenth review:16of25inputs reviewed,9remaining. Aptamer rectangle
10.1021/acsami.9b20707/RDE0068: full32page SI text read; routingPDF6 and anchor
TableS2PDF25 visually inspected.202regular rows plus56anchors indexed in
research/aptamer_rectangle_source_index.json.28Bcl2/28P-gp sites,12MUC1 aptamers;
biotin/FAM/disulfide and Dox variants kept distinct. Anchor63 duplicates64 in printed
TableS2 but differs from regular63; preserve discrepancy. Missing side-staple
composition and parent identity remain unresolved;3SIreferences matched registry
(Lund2010,Ke2016,Li2018). No source certification or catalog promotion. Main unread.
Evidence assets/sources/acs-expansion-20261104/20277726-am9b20707_si_001.pdf;
script research/review_batch_0016_fourteenth.py. ACS history and PubMed viaweb give
online2019-12-18, issue2020-01-08; localPubMed cookie challenge rejected and removed.
Downloader now recognizes that challenge. Next10.1021/acscentsci.9b00964 plus
remaining balanced queue and priority-author/citation routes; FNANO deferred.

Latest targeted followup (research/review_fret_main_context.py): B0016 remains
15/25 reviewed inputs,10 remaining. Original FRET paper assembly methods explicitly
identify square-lattice two-layer p7560; reference25 Endo2010 nanochip is inspiration,
not demonstrated identical reuse. Three parent/context citation leads saved. Main
Associated Content lists PDF plus two MOV files; no native caDNAno listed there.
Source completeness and whole-frame catalog eligibility remain unresolved. Evidence:
assets/research-20261105/bartnik-thesis.pdf, original reprint PDF88-98, targeted methods,
Figure1 and refs25-27. Remaining results/full bibliography are not claimed reviewed.
Validation passed after ledger save. Next balanced input10.1021/acsami.9b20707;
continue priority-author histories and backward/forward citations. FNANO deferred.
Human access queue remains available; public downloads remain paced and resumable.

B0016 thirteenth review:15of25inputs reviewed,10remaining. LiedlFRETrepair frame
10.1021/jacs.9b09093 sourcegroupRDE0067: two-layerp7560frame with two inward
substrates,185Oligo+40Endcap labels indexed; endcaps10/32biotin. TableS1assayvariants
0/4/6/8ntoverhangs,alteredlength/hairpin/restriction constructs kept separate fromframe
geometry. research/fret_frame_source_index.json is name/page index only; sequence
wrapping/fullsource verification and native/movieinventory open. Public Bartnik2020
thesis acquired assets/research-20261105/bartnik-thesis.pdf(50356836bytes). Original
paperreprintPDF88/printed815 explicitlyPublishedDecember4,2019; PDF90/817design
paragraph read. CurrentACShistory/PubMedJanuary2,2020 conflicts; retainboth rather
thanexclude by2020issue. Datedinstituteannouncement corroborates2019viaweb,local403.
Evidence SI assets/sources/acs-expansion-20261104/20550705-ja9b09093_si_001.pdf;
2SIreferences retained. Script research/review_batch_0016_thirteenth.py; validation
passed. Next read remainingmainreprintPDF88-98 andparentrefs25-27,then
10.1021/acsami.9b20707 and balancedbatch remainder. No sourcecompletion or catalog
promotion. Priorityauthor/citation routes continue,FNANO deferred.


B0016 twelfth review:14of25inputs reviewed,11remaining. Enzyme-cascade triangle
10.1021/acsnano.9b05746 targetedSI review records sevenenzyme configurations and
four208row staple tables(832occurrences,226distinctliteral sequences). RDE0066
retains sourcegroup; exactparent notmerged. research/cascade_triangle_sequence_index.json
stores all rows and21sequence-length mismatches;PDF22rows2/3visuallyconfirm32nt
sequences with47printedlength. No implied15nt extensions filled in. Protein coding
sequences and enzymeconjugation oligos are not counted as scaffold/staples. TwoSI
references retained. Mainarticle,scaffoldidentity,parentcomparison,native routing and
fullvariant recipes remain unresolved; no complete synthesis set certified.
Evidence assets/sources/acs-expansion-20261104/19205261-nn9b05746_si_001.pdf.
Script research/review_batch_0016_twelfth.py; validation passed. Next
10.1021/jacs.9b09093 and remaining balanced inputs; priorityauthor/citation routes
continue,FNANO deferred. Independent work continues while dissertation request awaits
browser assistance.


B0016 parent-source followup (still13of25firstpass,12remaining): targeted Johnson2020
thesis sections establish prior hinge attribution toMarras2015
10.1073/pnas.1408869112 and citeLe2016 10.1021/acsnano.6b03218 alongside it.
RDE0065 now retains this relationship without merging identities. Printed124/148
(PDF145/169) specify top20A,sites1-3bottom9A,site4bottom5-9A and23TNP coating;
printed158(PDF179) confirms54unique polymerizationoverhangs. Exactextra bottomset
roles remain unresolved. ThesisMethods genericm13mp18 versusSI8064gel label retained
as scaffold identity gap. Chapters3/4 are reproduced only in part: sidewaysarrays
and controlledlength additions are not backdated to2019. No furtherdesign count or
sourcecompletion claim. Script research/review_reciprocal_thesis_context.py; validation
passed. Evidence assets/research-20261105/johnson-control-thesis.pdf; targetedsections
and bibliography inspected,not complete chapters. Next10.1021/acsnano.9b05746;
parent sequence comparison and maintext reconciliation remain queued.


B0016 eleventh review:13of25inputs reviewed,12remaining. Castro reciprocalNP-hinge
paper10.1021/acs.nanolett.9b02786 SI source-composition reviewed; RDE0065 retains two
explicit routing pools and separate array assemblies. TableS1 has171Core labels,
TableS2 has139; labels restart,not sharedidentity. S2 includes54polymerizationoverhang
and54replacement names plus48separateZag connectors(4/8/12/24pools). Fullsequence
and sixsets-of-four versus extra bottomsets7/8 recipe mapping remains unresolved.
research/reciprocal_hinge_source_index.json is name/page index,not verified synthesisset.
Evidence: assets/sources/acs-expansion-20261104/18533306-nl9b02786_si_001.pdf;
selected routingPDF35 visually inspected. Public Johnson2020dissertation acquired
successfully as assets/research-20261105/johnson-control-thesis.pdf; title/contents
inspected,chapters awaitingreview. This later source is not counted as a pre2020
publication. Next read relevant thesis chapters for parenthinge/main context,then
10.1021/acsnano.9b05746 and balanced batch remainder. Native routing,arm lattice,
source mixtures and catalog eligibility remain unresolved. Script
research/review_batch_0016_eleventh.py; validation passed. Priorityauthor/citation
routes continue,FNANO deferred; existing dissertation browser request independent.


B0016 tenth review:12of25inputs reviewed,13remaining. Nanocluster patterning
10.1021/jacs.9b09308 SI methods/figures/variant instructions reviewed, with triangle
SchemeS1(PDF26) and rectangleSchemeS4(PDF29) visually inspected. RDE0063/0064
separate triangle and rectangle sourcegroups; parent legacy identities unresolved.
research/nanocluster_sequence_index.json retains208triangle and226rectangle original
sequence rows plus modificationIDsets. Triangle methods205helper strands conflicts
with195arm+12Link+1Loop=208listed; rectangle214A/no215 and omittedside-staple IDs
remain open. Three triangle arm-pattern variants and four rectangle patterns retained;
rectangle extension sets have24/27/45/63IDs. No complete mixture or base-level source
certification. SixSIreferences retained including HaoYan2008lead. Main article,
primarydate verification,native sources and catalog scope decisions pending.
Evidence: assets/sources/acs-expansion-20261104/18255026-ja9b09308_si_001.pdf.
Script research/review_batch_0016_tenth.py; ledger validation passed. Next
10.1021/acs.nanolett.9b02786 and remaining balanced inputs; priorityauthor/citation
routes continue. FNANO remains deferred, human dissertation request independent.


B0016 ninth review:11of25inputs reviewed,14remaining. Evolutionary refinement
10.1021/acsnano.9b03473 main author manuscript acquired publicly fromPMC7613751
(after EuropePMCXML500; HTML succeeded). Complete main text and7pageSItext read;
SIFig6 experimental square-rod comparison visually inspected. RDE0062 retains five
wireframe source families with iterative variants, not a unique-design count.
Broad census design-bearing; narrow catalog excluded explicitly for wireframe/truss.
research/evolution_archive_inventory.json records3577ZIPmembers,117618335expanded
bytes, hashes and five geometry/topology candidates. README states software for
moving internal supports; prova.top header15908nucleotides205strands has not been
mapped to a publication figure. No software executed, structures authored or complete
synthesis sets certified.36main references retained, including Benson2015parent-method
lead. Source evidence: assets/research-20261105/evolution-main.html;
assets/sources/acs-expansion-20261104/18005924-nn9b03473_si_002.pdf and
18005921-nn9b03473_si_001.zip in the same directory.
Script research/review_batch_0016_ninth.py and ledger validation passed. Next
10.1021/jacs.9b09308 and remaining balanced batch inputs; source-to-figure mapping,
priorityauthor/citation reconciliation continue. FNANO deferred; dissertation human
request is independent of these available sources.


B0016 eighth review:10of25inputs reviewed,15remaining. Reconfigurable plasmonic
diastereomers10.1021/acsnano.9b06734 now has source groupRDE0061. All16SIpages of
text read; routingPDF2,sequencePDF12 and capture/switchingPDF15 visually inspected.
research/diastereomer_sequence_index.json retains173coordinate-keyed TableS2-S5rows
(126plate,23arm,12armcapture,12platecapture). One32-character sequence contains two
literal question marks in the actual PDF:33[147]to35[150]. No bases inferred and no
complete source set certified. p8064 and honeycomb component layout documented;
exact assembly variants, capture extensions, native routing and whole-object catalog
eligibility remain unresolved. Three chiral switching centers and reconfigured states
are not automatically counted as separate core designs. Main PDF directACS attempt
returned403; public alternatives remain open, no entitlement conclusion or new human
request.44Crossref reference leads retained. September24Crossref and September26ACS
history/PubMed date conflict retained,bothpre2020.
Evidence: assets/sources/acs-expansion-20261104/17811194-nn9b06734_si_001.pdf and
assets/research-20261105/diastereomer-crossref.json; acquisition manifest records
failed main route. Script research/review_batch_0016_eighth.py; validation passed.
Next10.1021/acsnano.9b03473 and remaining balanced inputs; priority-author/citation
routes continue, FNANO deferred. Existing dissertation handoff remains independent.


B0016 seventh review:9of25inputs reviewed,16remaining. Counterion paper
10.1021/acsnano.9b05650 presents a512bp computational rectangle derived from
Rothemund2006; RDE0060 records eight parallel helices visible in SI FigureS2.
Six solvent conditions are not counted as six designs. Fullsequence is advertised
in FigureS2 but embedded as an image; native source, strand transcription and
independent verification remain open. Main Methods and Conclusions plus opening
Results read; detailed remaining Results not fully inspected. XMLepubSeptember10
versus legacySeptember16 remains unresolved (both2019). The stated8192bp parent
must be reconciled rather than copied into the2006 design record.
Evidence: assets/sources/pre2020-expansion/PMC6764110.xml and
assets/sources/acs-expansion-20261104/17624588-nn9b05650_si_001.pdf(PDF3visual).
Script research/review_batch_0016_seventh.py retains76references plus parent edge;
validation passed. Next10.1021/acsnano.9b06734 and remaining balanced batch inputs,
priority-author histories/citations. No source-completeness certification or catalog
promotion. Human dissertation request remains independent; FNANO deferred.


B0016 sixth review:8of25inputs reviewed,17remaining. Peptide-fluorophore hydrogel
10.1021/acsomega.9b01586 is excluded after main Results/Discussion/Conclusions and
all28SIpages of extracted text: PEG-linked capture and peptide-linked detection
probes support a hydrogel assay, not an origami experiment. Source evidence:
assets/sources/pre2020-expansion/PMC6714519.xml and
assets/sources/acs-expansion-20261104/17290484-ao9b01586_si_001.pdf.
All51numbered main references and6SIfootnotes retained; bundledref3 is not collapsed
onto one DOI. Ref9(10.1021/acs.analchem.7b04082) is a separate Tinnefeld antenna lead.
Script research/review_batch_0016_sixth.py records exclusion audit and validation.
Next:10.1021/acsnano.9b05650 and remaining B0016 downloaded supplements, priority
author/citation routes. One NCState dissertation browser request remains pending;
independent source review proceeds. FNANO remains deferred. No new design group
or source-completeness certification from this exclusion pass.


B0016 fifth review:7of25inputs reviewed. Turberfield clathrin-mimic main/SI supports
RDE0059,p7249 triskelia,three28HBhoneycomb arms and3HBbridges. Flat92bp versus curved84bp
bridges use18common+6variant-specific strands.6dimerization staples(arm1/1) distinct
from12polymerization staples(arm2/3);9cholesterol/6dyehandles bind separate conjugates.
Convex/concave observations not counted as separate sequence designs. Whole-object narrow
eligibility and exact core/interface replacement recipe remain unresolved.40main+3SIrefs
saved. Evidence assets/sources/pre2020-expansion/PMC6764109.xml and
assets/sources/acs-expansion-20261104/17371898-nn8b07734_si_001.pdf; FigS1PDF3 visual.
research/clathrin_source_composition.json; reproduce research/review_batch_0016_fifth.py.
Next18remainingbatch inputs plus native routing/movie inventory/full sequence audit.
XMLAug16 versus current publisherAug20online dates unresolved,both2019.


B0016 fourth review:6of25inputs reviewed. Antibody conjugation10.1021/acs.bioconjchem.9b00490
excluded as not_origami after entire main/SI text review: cellular docking/imager oligos,
not origami staples. Prior nanostructure application belongs to ref32Rosier2017
10.1039/c7cc04178k;37references retained for followup. XMLepub2019-08-22 differs from
PubMed2019-09-03; exact date pending, pre2020scope unaffected. Evidence
assets/sources/pre2020-expansion/PMC6753658.xml and assets/sources/acs-expansion-20261104/
17489498-bc9b00490_si_001.pdf. Reproduce research/review_batch_0016_fourth.py.
Next19remainingB0016inputs, clathrin-mimic SI and peptide-hydrogel main/SI, plusRosierparent.


B0016 third review:5of25inputs source-reviewed. Engineered defects10.1021/acsnano.9b03770
RDE0058 groups experimental4HBsquare,6HB/10HBhoneycomb and12HBhinges (not four
certified distinct source sets). Computational cross-section sweep kept separate.
research/engineered_defects_sequence_index.json:1373unique source names across pools,
3814HB+6806HB+31210HB; exact per-variant shared/replacement mix and base certification
pending. PDF82visually confirms4HB-Ref total698/wellfolded760 inconsistency and
6HB-1nt-200% label differing from Table1's6HB-2nt-100%; no silent corrections.
18SIreferences saved. Evidence assets/sources/acs-expansion-20261104/
16217996-nn9b03770_si_001.pdf; reproduce research/review_batch_0016_third.py.
Next main acquisition, remainingSIimage/variant/source audit and remaining20batch inputs.
No molecular authoring/simulation performed; inspection only.


B0016 second review:4of25 inputs reviewed. Tinnefeld/Liedl optical antenna SI establishes
RDE0057 square-lattice2LS sheet,42helices, p7249,1BS/2BS variants. Routing image and
modification recipes do not provide complete staple inventory/native source. ThiolDNA
row19T conflicts with caption/methods15T; retained unresolved. Gold metamaterials
10.34133/2019/7403580 main uses five-strand tiles(two48nt strands) in ribbons/lattices:
narrow catalog excluded, broad origami terminology classification uncertain pending SI.
All references retained. Evidence paths assets/sources/acs-expansion-20261104/
17430617-nl9b02886_si_001.pdf and assets/sources/pre2020-expansion/PMC6750079.xml.
Reproduce research/review_batch_0016_second.py. Next remaining21B0016inputs,
starting engineered-defectsSI, plus antenna main/native source and gold actualSI.


B0016 first rotation:2of25 inputs full-text reviewed. Pickett2006Olympic gels models
DNA-end-tagged flexible polymers, not scaffolded origami (excluded/not_origami);
first-online corrected to2006-10-25 from PDF1. Lindsay chromatin commentary retained
as background with no design-bearing claim; its final origami analogy cites Rothemund.
Both exclusions audited against complete text. All14+8references saved, including
Pickett submitted2006lead whose eventual publication remains unresolved.
Evidence assets/research-20261105/olympic-gels2006.pdf and chromatin2006.html;
reproduce research/review_batch_0016_rotation_first.py. EuropePMC XML retrieval500
recorded; publicPMC HTML succeeded. Next23B0016 inputs, including downloadedACS SI,
review/proceedings leads and low-keyword records. B0016 remains in progress.


AUTHOR0032: Precise Coating main read; explicit Rothemund tall rectangle reuse mapped to
existing S007 (no new geometry ID). Main PDF5/7/8 names parent, refers staples/layout
to ref31 and specifies7249ntM13mp18. Fig6/7 PDF6 visually reviewed. All35deposited
references preserved. Protein concentrations/coatings are conditions, not routing variants.
Main PDF1 says published2016-12-01 whereas deposited/current publisher online date is
2016-12-12; exact date conflict retained, pre2020scope unaffected. Movies identified
by main as T4-DNA fluorescence, not new origami; direct movie review remains pending.
Evidence: assets/research-20261105/precise-coating-main.pdf and precise-coating-crossref.json.
Reproduce research/review_precise_coating_main.py. Exact S007 experimental staple variant
and source completeness remain unresolved. Next rotate full backlog, then parent source
reconciliation; dissertation ACCESS-a556b23d8f remains awaiting user without blocking work.


AUTHOR0031: Precise Coating10.1021/acsnano.6b05938 now design-bearing from SI FigureS5
origami digestion assay. Four protein adapter oligos in TableS1 are NOT origami staples.
All four publisher SI files acquired and MD5/size verified (PDF+3AVI); movies not reviewed.
Author-hosted main subsequently acquired: assets/research-20261105/precise-coating-main.pdf,
5458745bytes SHA2560083f849517260fad5c33d514e956178668665b7af54e24c730c6f58842334e5.
Next read main for template/parent/date and references; no exact design group asserted yet.
One human request ACCESS-a556b23d8f: Estrich2016dissertation blocked by NCState bot check
on direct/API and web routes. Download exact ID PDF to Downloads; agent continues other work.
No evidence of missing CU entitlement. See research/ACCESS_REQUESTS.html.
Reproduce SI review with research/review_precise_coating_si.py; acquisition manifest retains
all routes. Source validation passed; counts generated below from actual ledgers.


AUTHOR0030: Diblock SI reviewed (18pages text; S2/S9 visual). Paper now design-bearing,
with RDE0055 tetrahedral source group and RDE0056 tall rectangle experimental group.
144tetrahedral staple names:72structural+48arm+24crown; two separate thiolated
nanoparticle coating oligos. research/diblock_sequence_index.json indexes72structural
sequences and72arm/crown names; colored capture boundaries and complete synthesis set
NOT certified. Main, two tetrahedral variants, parent routing and lattice eligibility
remain unresolved. All deposited journal references retained. Estrich dissertation
bitstream returned non-PDF, rejected; alternate repository acquisition is next.
Source/evidence paths: assets/research-20261105/diblock-si.pdf and diblock-crossref.json;
reproduce with research/review_diblock_si.py. No human intervention required yet.


AUTHOR0029: LaBean diblock paper10.1021/acsnano.6b07291 SI acquired publicly
from publisher Figshare4524902/file7321154. assets/research-20261105/diblock-si.pdf
(1202413bytes; SHA256fe9300d017b372fa03d18b280d4fc99d4cb94eb6546cded26c0d596db5d91740).
Parent DOI, cover title/authors, size and provider MD5 checked by research/acquire_diblock.py.
Scientific classification remains unreviewed: next inspect all SI routing/table pages,
resolve tetrahedral variants and geometry eligibility, acquire main and reconcile citations.
No human access request needed; public acquisition succeeded. Validation14669hashed refs,
6158publication/version records and100stable legacy design IDs passed.


AUTHOR0028: LaBean official old Duke CV59entries inventoried (29journal-section,
21proceedings/meeting,8chapters,1bookreview), plus10current NCSU-profile entries;
61pre2020/undated leads retained, with submitted/in-preparation status explicit.
Counts overlap and are not unique published works. Inventory and script:
research/labean_bibliography_inventory.json, research/discover_labean_bibliography.py.
Linked lab404; linked NCSU full bibliography returned HTTP200botchallenge. Its
challenge payload was replaced with a non-sensitive diagnostic, manifest marked
failed, and downloader now rejects this challenge before saving. Two focused
source-payload tests pass. No private login needed; alternate public histories
remain available. CV stops around2007;2008–2016coverage gap and later incomplete
coverage explicit. Next: later-career independent histories,2017diblock-polypeptide
paper source review, then existing cutoff/source queues. FNANO remains deferred;
no molecular work or map promotion. Validation14667hashedrefs/100legacy IDs.

AUTHOR0027: Ultrafast fluorescence10.1021/acs.nanolett.9b04354 ACS SI acquired
via Figshare11541942/file20731413; providerMD5 verified. SI confirms p8064
nanoantenna/Cy7/100nmAuNP dimer; RDE0054 retains design evidence with unresolved
lattice, parent mapping and cutoff. TableS2 indexed188unmodified staples;
S3 has22modified row names (12biotin/8npbind/2dye), but wrapped polyA text crosses
row boundaries in PDF22, visually verified; modified sequences not certified.
Main not acquired: ACS403 and Regensburg landing supplies metadata only.
Publisher web banner2019-12-23 conflicts with history2020-01-08; Figshare SI
published2020-01-07. Retained observer date note; first public full-design date
remains unresolved, not silently pre2020. Twelve SI references retained.
Scripts:research/review_ultrafast_si.py; index:research/ultrafast_sequence_index.json.
Next: main via author copies, date/source version check, native/routing and parent
comparison; continue LaBean and independent history rotation. Human queue empty,
public routes remain; FNANO deferred. No reconstruction or catalog promotion.

AUTHOR0026: Tinnefeld official bibliography traversed5pages through explicit next
links to terminal absence:211occurrences,210provider IDs,156pre2020/boundary/
unknown leads,46existing DOI matches. RepeatedID15 across pages1/2 retained;
emptyID206 has no title/year and remains unidentified, not a publication.
Inventory:research/tinnefeld_bibliography_inventory.json; parser/downloader:
research/discover_tinnefeld_bibliography.py. Added metadata-only candidate
10.1021/acs.nanolett.9b04354: deposited online2019-12-23 versus issue2020-02-12.
Primary date/main/SI and origami relevance pending. No design-source promotion.
Next: this low-keyword main/SI, independent LMU history comparison, LaBean history;
Doye undated submissions and crystal source/version gaps remain queued. No
saturation or completeness claim. FNANO deferred; no human access request.

AUTHOR0025: Low-keyword Doye hierarchical-bounding-structures paper screened.
Registered journal10.1063/1.5002666 and arxiv:1708.09382v3 as separate versions
with explicit author/arXiv DOI identity, common work key. Preprint targeted
full-text review remains relevance-uncertain: main results use generic twisted
cuboids, but PDF11 explicitly reports nucleotide-level tests on origamis from
10.1038/nmat4909. No unsupported background exclusion or new design group.
ArXivv3 dated2017-12-13 versus internalPDF July4,2018; discrepancy retained;
v1firstposted2017-08-30. Journal deposited online2017-12-12, primary page pending.
All96journal reference entries retained;98preprint numbered references need
column-safe extraction/reconciliation. Script:research/review_bounding2017.py.
Counts now distinguish explicit arXiv version relations alongside Crossref/edition
relations. Validation passed14422hashedrefs,6157versions,100legacy IDs.
Next: inspect Tinnefeld official bibliography (acquired HTML in research-20261105),
then LaBean; retain Doye submitted-date and origami-test/source queues. FNANO
remains deferred; human-access queue empty.

AUTHOR0024: Doye official history180list-item occurrences enumerated across
2024–1992 and Other;164pre2020/boundary/undated leads retained, including7
submitted entries under2024 that require independent preprint-date checks.
All raw list starts reconciled, including three missing closing tags in2003.
Inventory:research/doye_bibliography_inventory.json; reproducible parser:
research/discover_doye_bibliography.py. One explicit author DOI resolves2017
jointed-DNA entry to already-reviewed P1387, avoiding duplicate scientific review.
Next: remaining linked abstracts and submitted dates, rotate low-keyword2017
hierarchical-bounding-structures paper, then Tinnefeld/LaBean histories. Crystal
journal/preprint comparison remains queued. No history/citation saturation claim;
FNANO deferred, access queue empty. Publication/design counts unchanged.

AUTHOR0023: Registered arxiv:1706.06965v1 separately (primary date2017-06-21)
and reviewed its21-page main+SI PDF. RDE0053 records honeycomb14HB-strut
p8634 tensegrity frame, seam connection versus polymerization strands, and
six3prime19A nanoparticle handles. Whole frame/crystal excluded by existing
truss rule, retained as design-bearing literature. S1/S2 PDF12/13 visually
inspected; approximately235oligos is not a certified sequence count. arXiv src
endpoint returns byte-identical PDF, no extra native files. Preprint38main+8SI
references retained separately from45journal deposited entries. Journal identity
link is provisional: title/authors match but content comparison remains pending;
no canonical merge or journal review-stage promotion. Script:
research/review_crystals_preprint.py. Next: journal main/SI comparison, native
source search, then Tinnefeld/Doye/LaBean histories and low-keyword rotation.
No human access request; no molecular authoring. FNANO remains deferred.

AUTHOR0022: Completed visual review of silica article10.1002/anie.201811323
original main PDF37–41 and accepted-article SI PDF78–93 in Nguyen thesis.
Paper now design_sources_reviewed/design_bearing; narrow eligibility unresolved.
RDE0052 records14-HB p8634 rod/ring and reused triangular-monomer crystal.
Routing images are not certified sequence sets. Mainp916 proves accepted-online
2018-11-06 and VOR2018-12-11, distinct from issue2019-01-14. Retained all42
Crossref entries representing36printed reference numbers (six edition pairs),
plus4SI references. Crystal parent resolves to10.1002/adma.201800273; exact
variant/source review pending. Script:research/review_silica2018.py.
Validation passed14052hashed references,100legacy IDs retained. Next: crystal
parent main/preprint/source review, then rotate Tinnefeld/Doye/LaBean histories
and low-keyword records. Parent DESY download rejected as non-PDF; arXiv PDF
1706.06965 acquired at assets/research-20261105/crystals2017-arxiv.pdf (manifest
SHA retained); first-page identity inspected only, version/design review pending.
FNANO remains deferred; human-access queue empty.

AUTHOR0021: Recovered Nguyen author thesis (2022) at assets/research-20261105/nguyen-thesis.pdf
containing original silica article10.1002/anie.201811323 and accepted-article SI
reprints, after direct Wiley403. SHA retained in publication evidence/acquisition
manifest. Only PDF37,38,78,79 visually inspected so far; no review-stage,
relevance, design-group or eligibility promotion. Next: inspect main PDF39–41
and SI PDF80–93, verify source boundaries, dates and design parents, then retain
all citations. The later thesis is source hosting, not a pre2020 publication.
Human-access queue empty; access_queue focused tests5/5 passed. Public-source
acquisition remains autonomous; no credentials requested or stored.

AUTHOR0020: Tim Liedl lab history119 citation paragraphs (2024–2004 plus Reviews)
and LMU repository64 unique IDs enumerated, with88/42 selected pre2020/boundary
occurrences respectively. Counts overlap and are not unique works. All88 selected
lab entries have plain-text getarticle/downloadpdf labels without actual links;
repository landing links retained as alternative route. Repository covers2013–2025,
not older career coverage. Inventories:research/liedl_bibliography_inventory.json
and research/liedl_repository_inventory.json. Silica-growth lab2018:2 and LMU83240
reconciled via explicit repository DOI to P1773/10.1002/anie.201811323. Source review
still pending: lab2018,repository2019,legacyfirstdate2018-12-11 require primary
online-date verification. No literature/design classification changed. Validation
passed including all64 provider IDs and lab paragraph counts. Next: acquire
silica paper main/SI, reconcile author-history overlaps and low-keyword records;
rotate Tinnefeld/Doye/LaBean and remaining named authors. FNANO deferred, no human
access request or discovery saturation claim.

AUTHOR0019: Simmel public TUM faculty frontend recovered institutional history
without authentication despite portal403. All23 endpoint pages saved:223 unique
provider UUIDs match provider total;154 selected pre2020/boundary leads, including
44 before2008.27 explicit DOI registry matches; ten provider publication types
retained, including conference records, chapters, reviews and comments. They are
leads, not proof of complete designs. research/simmel_faculty_inventory.json
and retained frontend HTML/JS reproduce endpoint traversal; terminal pagination
verified. Lab/faculty explicit DOI overlap audit:33/142 identifiers,32 shared,
1 lab-only and110 faculty-only. Not new-work counts: lab scope differs, including
Kuzyk sole-author10.1002/elps.201100038. Both histories preserved. Pre2008 page gap
now has an independent source, but identity/version/source and saturation work
remain open. Validation passed. Next: reconcile histories and pre2008/type leads;
rotate Liedl/Tinnefeld/Doye/LaBean and remaining requested authors, keeping source
and low-keyword queues active. FNANO deferred; no user access request needed.

AUTHOR0018: Simmel official lab page enumerated across19 year sections2026–2008.
142 citation occurrences;87 selected2008–2020 leads;8 explicit DOI registry matches.
Raw HTML audit143 paragraphs =142 nonempty citations+1 empty2021 paragraph.
research/simmel_bibliography_inventory.json preserves raw citations and links;
heading years are discovery labels, not verified first-online dates. No new
publication classification. Pre2008 absent from this page: explicit coverage gap.
TUM institutional-history local downloader returned403; no entitlement conclusion
or user authentication request, since independent public routes remain untried.
Validation passed. Next: recover pre2008 via TUM/faculty/archive alternatives,
reconcile87 leads and primary dates/versions, rotate remaining named authors and
low-keyword/source queues. FNANO deferred; census closure not established.

AUTHOR0017: P0023 DOI10.1021/ja8030196 deeper source review via Wilksref50 and
Shih author-linked ZIP75. Main identity/webdate2008-07-10 verified despite2010
filenames. ZIP SI matches existing ACS SHA exactly; successful downloads reused.
RDE0051 separates revised410nm p7560 6HB from explicitly reused Rothemund rectangle.
SI FigS1 S4 visually inspected: hexameric six-cylinder ring and repeat/end routing.
Full AppendixA extraction7560bases and AppendixB186staple entries indexed with page
locators in research/jungmann2008_sequence_index.json. Lengths174x42nt,4x27,4x31,
2x24,2x34. splitlines handles form-feed page-start rows. Source appendix-label
errors retained: S1 namesA for staples/C forinsert, actualA scaffold/B staples.
Rectangle226short-strand source set requires parent verification; no source-set
certification or catalog promotion. All16 main references and explicit rectangle
reuse retained. Validation passed. Next: parent6HB/source reconciliation and
independent Simmel bibliography enumeration, other named authors and low-keyword
rotation; FNANO deferred. Human access queue remains empty.

AUTHOR0016: Low-keyword Oxford lead10.1021/nn402642a added and audited as
not_origami from main construction and SI controls: four oligonucleotides s1–s4
form a tetrahedron; s2 carries polymer, with no long scaffold/staple architecture.
Main/SI acquired publicly from Groningen repository. Three repeated bibliography
occurrences reconcile to one publication record; all62 deposited references
retained (count agrees with main finalref62), including origami-methodref50.
Exact first-online date remains explicit conflict: PDF printed2013-09-16 versus
publisher-deposited2013-10-01; both establish pre2020 scope. No design group added.
New exclusion audited against mainpp8564–8565/8568 and SI FigsS11/S12/S14.
Validation passed;6154 publication/version records, not fully reconciled works.
Next: cited isothermal-origami method and parent-tetrahedron leads; continue
remaining named-author histories, forward/backward routes and low-keyword records.
Outstanding source queues remain; FNANO deferred; no human access request.

AUTHOR0015: P2048 DOI10.1021/acsnano.9b04251 reviewed from primary XML and
retained ACS SI. RDE0050 records two sleeve-decorated6HB cores A/B and eight
handle-valency variants. FigsS9/S10 PDF/printedpp21–23 visually inspected;
TableS6-1/S6-2 pp41–44 indexed in research/peptide2019_sequence_index.json.
Base counts69/67 reconcile with main; three replacement controls and two tags
per object are additional components, not extra base staples. FigS10 specifies
active handle helices3-valent0/2/4,2-valent0/2,1-valent2,0-valentnone; remaining
positions use controls. A MID37 Cy3/B MID41 Cy5 and A righthelix2T6 exception
recorded separately. Native routing/cross-section and complete source matching
remain unverified; catalog eligibility unresolved, no promotion or reconstruction.
Online2019-08-05 corroborated by primary XML and publisher Crossref, correcting
legacy2019-08-08 while preserving history; issue2019-09-24 distinct. Local ACS
page403 did not block source review. All50 main and5 SI references retained.
Validation passed. Next: low-keyword Oxford records and remaining named-author
histories; source routing followups, Bathe DAEDALUS/TALOS and Shih/Qian pending.
FNANO deferred; user access queue empty; no discovery closure claim.

AUTHOR0014: Andrew Turberfield Oxford author-history pages0–37 fully enumerated
via provider next links;187 bibliography occurrences,176 exact title strings,
169 pre2020/boundary/date-uncertain selected leads,14 explicit DOI registry matches.
These are not unique-work counts. Four unknown-date entries retained, including
three undated tail records; DOI-embedded years are not substituted for publication
dates. Raw publication-block counts agree on all38 pages (37x5 +2);169 saved edges.
A missing citation field on page36 initially stopped parsing; corrected to retain
missing-metadata records, then resumed from cached acquisitions without downloads.
No publication relevance or eligibility decisions from this enumeration. Source
inventory:research/turberfield_bibliography_inventory.json; script reproduces traversal.
Next concrete source review:P2048 DOI10.1021/acsnano.9b04251 peptide assembly,
existing assets/sources/PMC6764022.xml and ACS17012882-nn9b04251_si_001.pdf,
SI FigsS9/S10/TableS6; primary XML2019-08-05 versus legacy2019-08-08 date pending.
Continue author overlap/type/date reconciliation and independent coverage. Other
named authors, Bathe/Shih/Qian sources and low-keyword rotation remain queued;
FNANO deferred. Validation passed; human access queue empty; closure remains open.

AUTHOR0013: TALOS main manuscript recovered from MIT public repository despite
local ACS403. Shepherdref23 resolved to10.1021/acsnano.8b08671 using manuscript
identity and retained ACS supplement metadata; original malformed DOI preserved.
RDE0049 records10 reported experimental variants (5 FV,4 regular MV,1 asymmetric MV)
separately from240 computed library entries; overlap not yet mapped. SI FigS76
PDF/printedp96 visually inspected: asymmetric tetrahedron edges42,69,69,103,103,130bp.
Twisted prism is a designed example, not automatically an experimental object.
All68 main references retained; first-online date remains to be verified against
saved primary metadata, distinguishing it from issue and repository upload dates.
No new catalog promotion or complete-source certification; validation passed.
Next: map experimental/library source identities; acquire DAEDALUS2016 primary
main/SI, rotate remaining named-author histories and low-keyword backlog. FNANO
remains deferred. No human access request required.

AUTHOR0012: P1939 DOI10.1038/s41598-019-42665-1 reviewed from retained
PMC6467869 XML, publisher page and both newly acquired public Springer supplements.
Two DAEDALUS wireframe pentagonal bipyramid variants (52/84-bp edges) retained in
RDE0048 as literature-relevant, narrow-catalog-excluded. Four workbook sheets indexed
in research/shepherd2019_sequence_index.json: scaffold sequences1676/2520nt,
44/74 author-labeled staple entries. These are table-entry counts, not certified
complete synthesis sets. SI FigS8 PDF/printedp9 visually inspected. Main1580nt
52-bp design length versus1676nt phPB52 scaffold remains an explicit source question;
native routing and exact prior-template relationship remain unverified. All56 main
references retained, including malformed ref23 DOI without silent correction.
Validation passed; no molecular authoring, catalog promotion or user access request.
Next: verify ref23 against TALOS primary source; follow DAEDALUS template citation,
continue remaining named-author histories and low-keyword backlog, and resolve
pending Shih/Qian sources. FNANO deferred; no discovery saturation established.

AUTHOR0011: Mark Bathe public lab bibliography116 entries and MIT2025 CV109
publication entries enumerated without title filtering. Current pre2020/boundary
selection:68 lab +70 CV =138 overlapping citation occurrences, not unique works.
Seven occurrences have explicit DOI matches to registry records. Two earlier
selection mistakes (lab94 page1960; lab70 article suffix2020) remain as corrected
historical edges outside current selection:140 retained edges total. All raw
citations and date-token candidates retained in research/bathe_bibliography_inventory.json.
CV56 has a volume/page discrepancy against lab56; primary verification pending.
HTTPS lab certificate hostname mismatch avoided using its public HTTP URL;
MIT CV downloaded over HTTPS. No TLS verification bypass or user login required.
Parser tests passed2/2; ledger validation passed including saved evidence hashes.
No publication classification or catalog promotion in this discovery batch.
Next: review existing P1939 DOI10.1038/s41598-019-42665-1 from saved
assets/sources/pre2020-expansion/PMC6467869.xml and retrieve its PDF/XLSX
supplements; reconcile Bathe overlaps/primary dates; continue other named authors,
Shih/Qian pending sources and low-keyword rotation. FNANO remains deferred.
Access queue remains empty; no user action required. Full census closure remains open.

AUTHOR0010: Hahn2019 DOI10.1093/nar/gkz844 main/SI experiments verified as
free-strand thermal-displacement circuits, not origami; explicit scope exclusion
retains cited origami-chip P0103 DOI10.1002/smll.201000908 as a next review lead.
Krieg SNAPCAR DOI10.1002/anie.201710469 advances to design-source review with
three experimental objects(RDE0047): ss3315 barrel, ss7301 rectangle and6HB.
SI folding protocols, TableS2 primers and FigsS18–20(PDF23–24, printedS22–23)
inspected. No complete staple set/native routing certification. Mainp718 gives
accepted manuscript online2017-12-05 andVOR2017-12-18 despite2018 issue; separate
German-edition DOI10.1002/ange.201710469 retained as pending edition lead.
All54 deposited main references(24Hahn+30Krieg) plus10 Krieg SI references saved.
Next compare barrel variants across Ponnuswamy/SNAPCAR/MeRPy, verify exact native
sources and parent identities, inspect P0103, recover Tellechea, and rotate other
requested authors. Reproduce with research/review_shih_hahn_krieg.py.

AUTHOR0009 completes visual inspection of all eight Ponnuswamy caDNAno panels,
with per-object notes in research/ponnuswamy_diagram_review.json. DN5 remains
poorly legible even in a600dpi crop; prior description as planar was unsupported
and is corrected in current publication/design records, with history preserved.
Other panels show numbered staggered/bundle layouts and flattened paths, but
final topology, sequence mapping and catalog eligibility are not certified.
Next seek native routing/source correspondence, resolve DN9 parent and MeRPy
variant questions, and rotate to already acquired Hahn/Krieg sources.

AUTHOR0008: Ponnuswamy2017 DOI10.1038/ncomms15654 advanced to bounded
design-source review. MainFig2, SI DN1/DN2 routing panels(PDF/printed40–41),
DN9 descriptions and all10 workbook cells inspected/indexed. Data1–9 have
324,162,408,342,175,154,120,156,187 sequence-like cells; these are not verified
staple counts. Data9 also contains two source-footer cells(A93–A94); Data10 has
36 labelled sequences(18Cy3,18Cy5). Publisher captions supply object mappings.
RDE0045 groups DN1–DN8 pending exact variant/lattice verification; RDE0046
retains literature-relevant DN9 but excludes its explicit polyhedral mesh from
the narrow catalog. DN9 main text cites Veneziano2016 while workbook footer
names Benson2015 DOI10.1038/nature14586: provenance conflict remains explicit.
MeRPy RDE0043 now points to recovered parent sources, but2019 p3315/miniscaffold
versus2017 p7308 equivalence is unverified. All32 backward references retained.
Next inspect remaining six diagrams, reconcile sequence/variant and DN9 provenance,
then review acquired Hahn/Krieg sources and rotate author histories. No complete
source certification or catalog promotion. Reproduce cell index with
research/index_ponnuswamy_sequences.py and decisions with
research/review_ponnuswamy_sources.py.

AUTHOR0007: Shih official publication page enumerated83 citation paragraphs;
65 pre2020/boundary entries retained(59 under earlier headings,6 under2020),
40 exact DOI registry matches and25 identities pending. Dates in citations remain
separate from heading years:2004 heading includes five older1994–2001 papers.
All65 selected entries have source links. Four author ZIPs downloaded: ordinals
26(Hahn2019) and32(Krieg2018) each contain main+SI;34(Ponnuswamy2017) contains
main+SI+tenXLSX;44(Tellechea2015) contains only directory/Mac metadata and is
explicitly empty scientific content. Alternative eScholarship PDF returned403.
Inventory/extraction script: research/inventory_shih_sources.py; member hashes and
text paths: research/shih_source_archive_inventory.json. New low-keyword primary
reviews exclude Qian BDNF genetics10.1016/j.bbrc.2006.12.121 and linear-duplex
DNA addition10.1007/s11434-007-0230-0 from origami scope, with both decisions
audited against main methods/results. No title-only exclusions. Next inspect
Ponnuswamy DN1–DN9, sequence workbooks and MeRPy variant relation; review
Hahn/Krieg sources; recover Tellechea content; compare Shih HMS/DASH histories
and reconcile25 pending identities. Qian supplements remain unresolved.

AUTHOR0006: Retrieved2006 China-map main PDF directly from Springer on local
CU-connected path and2010 asymmetric-chip main PDF from historical Caltech page.
Added2006 DOI10.1007/s11434-006-2223-9; advanced existing2010 DOI10.1002/adma.201000151
to fulltext review. One family RDE0044 records original map plus probe-functionalized
reuse;2006 uses digested7176nt scaffold and229 oligos, while2010 explicitly uses
undigested M13mp18. Exact variant correspondence and complete sources remain open.
2010 first-online date verified as2010-05-03 from article. Both supplements remain
unacquired: Wiley SI hosts403, guessed legacy VCH route404;2006 per-base routing
PDF is cited in main article but its location remains unresolved. Historical
Caltech bibliography adds9 overlapping source occurrences (42 across three
bibliographies, not unique papers); all7 references of2006 retained for identity
reconciliation. Next: locate both supplements, reconcile references and remaining
Qian bibliography versions, rotate next named author and low-keyword backlog.
No human request yet: further independent source-location work remains available.

AUTHOR0005: Qian current official bibliography (23 numbered paragraphs) and
September2019 CV (18 refereed entries) saved and enumerated. Retained33 source
occurrences:15 current-page pre2020/boundary paragraphs plus18 CV citations;
these overlap and are not33 unique publications. CV14–18 add older citations
absent from the current page, including asymmetric origami2010 and China-map2006.
Next: reconcile identities/dates/versions for these older leads, then inspect
article and supplement evidence; split embedded conference/journal/commentary
citations. Historical personal bibliography and independent author searches remain
open. Parser fixture validates section identity, embedded version years and
exclusion of tokenized links from extracted link lists. Access queue remains empty;
human handoff is available through research/ACCESS_HELP.md when actually necessary.

AUTHOR0004 resolves MeRPy first publication as2019-11-12 from Oxford article
history (issue2019-12-16; legacy2019-12-01 superseded in sidecar history).
All13 authors transcribed. FigS7 PDF/printedp20 visually inspected: upper barrel
and lower rectangle path diagrams, without cross-sectional lattice/helix labels.
Diagram availability confirmed; lattice, strand-role/sequence matching and complete
staple pools remain unresolved. Evidence:yin_merpy_primary_date.json and retained
SI; reproduce review_yin_merpy_followup.py. No new design groups/promotions.

AUTHOR0003: Yin/Shih MeRPy paper10.1093/nar/gkz998 reviewed at main
Fig2B/results, SI ProtocolS4 pp13–14 and sequence Sheet1(rows1–23).
RDE0043 retains two demonstrated objects as one provisional paper-level source
group:3315nt barrel and7308nt rectangle; not two newly proven architectures.
Barrel cites Ponnuswamy2017 parent; staple+miniscaffold versus rectangle
core/helper/handle pools remain distinct. Workbook supplies scaffold/template
entries, not complete staple sets. FigS7 diagram/lattice/sequence matching and
first-online date remain open. Source/archive hashes and parsed rows saved in
yin_merpy_source_inventory.json; reproduce review_yin_merpy.py.

Human access handoff implemented at research/ACCESS_REQUESTS.html and
research/access_queue.py, documented in research/ACCESS_HELP.md. Queue currently
empty: no human action requested. Stable public links, exact blocked-resource
reasons and automatic attempts accompany any future request. User downloads can
be imported by request-ID filenames or explicit paths, preserving originals and
SHA256 provenance; received files still await identity/design review. Five focused
tests passed (request resume, challenge rejection, file conflict/integrity, URL
credential/query rejection, answer preservation). Public paced/resumable
acquisition continues independently; CU egress remains verified as below.

Current access check: local Python egress verified as AS104 University of
Colorado at Boulder. RSC and ACS requests return403 Cloudflare “Just a moment”
browser/bot challenges, not demonstrated subscription denial. See
research/network_access_check.json (no IP, credentials, cookies or tokens saved).
Web-reader egress is separate and unverified. Browser challenge handling remains
open; do not request VPN/login merely from these403 responses.

Peng Yin enumeration saved:68 pre2020 numbered entries(68–1) plus8 boundary
2020-anchor rows;20/76 explicit DOI matches and56 pending identities. Duplicate
2020.cnt anchors retained separately; media links excluded from core source links.
Parser fixture passed. See yin_bibliography_inventory.json and
discover_yin_bibliography.py. Author-hosted2019.ssDNA.pdf acquired and hashed;
content review pending. Next: inspect this article/SI, resolve Yin identities,
and continue other requested authors.

AUTHOR0002: Castro review Crossref deposit enumerated178/178 reported references,
172 with DOI and6 without.79 targets match registry DOIs;99 unmatched targets
remain leads, not new eligible publications. Audit:castro_review_reference_audit.json;
reproduce:discover_castro_review_references.py. RSC fulltext acquisition and web
open both returned403. Crossref year-only2020 conflicts with publisher explicit
2019-10-15; publisher date retained. Article remains metadata_screened.
Peng Yin official publication page acquired with SHA256 in acquisition manifest;
2019 header/first entries inspected for parser structure, full enumeration pending.
Next enumerate Yin bibliography/PDF/SI links, resolve99 reference targets, and
continue42 Castro identities while rotating the15 requested authors.

Castro boundary batch AUTHOR0001:3/45 bibliography identities now matched;42
remain. The dynamic-device review10.1039/c9nh00529c was first published
2019-10-15 despite its2020 issue. Electrochemical-origami journal version
10.1039/d0nr00952k first published2020-06-18, with earlier-version question open.
GelMA10.1088/1758-5090/ab97a1 has2020 primary metadata but earliest online date
needs verification. Primary abstracts inspected, not full designs; no final
exclusions or complete-source certifications. Evidence: castro_boundary_*.json;
reproduce with reconcile_castro_boundary.py. Next: review/citation acquisition
and remaining Castro identities, rotating other priority authors.

User priority correction: defer FNANO until other search methods demonstrate
recorded diminishing returns. Existing FNANO progress is preserved, not exhausted.
Prioritize Carlos Castro, Hendrik Dietz, Shawn Douglas, William Shih, Hao Yan,
Peng Yin, Andrew Turberfield, Mark Bathe, Tim Liedl, Lulu Qian, Friedrich Simmel,
Philip Tinnefeld, Jonathan Doye, Thomas LaBean and Paul Rothemund publication
histories, then primary-source review and recursive citation discovery. This
instruction supersedes all historical FNANO-first next queues below. No saturation
has been demonstrated. See research/author_priority_queue.json.
Castro’s official OSU bibliography now has45 saved leads:42 entries listed under
2007–2019 plus3 under2020 retained for first-online boundary checks. These are
unreconciled citations, not45 new publications. Evidence is
research/castro_publications_web_capture.json; inventory is
research/castro_bibliography_inventory.json. The paced downloader returned403;
the web reader supplied the retained page. Next: resolve these identities/dates,
compare the official CV/full bibliography, and review their main/SI designs while
rotating through the15 requested author histories. Existing Dietz, Douglas, Yan
and Rothemund runs are reused rather than duplicated. Validation passed after
saving the45 edges; no publication dispositions or catalog eligibility changed.


Resumed continuation: FNANO2010 pages1–15 now saved:143 program appearances,
105 distinct leads and38 repeated poster appearances. Pages14–15 were visually
inspected:15 new leads and3 repeated appearances. Andersen’s repeated title
phrase is retained as printed pending abstract/title reconciliation. The Friday track label on page12 groups
posters presented in the April29 session; the session date is preserved.
Printed name ZHAO ZHAO is retained pending author identity reconciliation. Repeated
appearances retain separate page evidence; no program entry certifies a design.
See research/fnano2010_transcription.json, research/fnano2010_schedule_audit.json
and research/review_fnano2010.py. Resume at page16 (4/19 pages remain), then
2006–2009 enumeration, abstract/counterpart reconciliation,234 remaining CV
identity leads and balanced screening/source follow-ups. B0015 first-pass review
is25/25 with all25 retaining follow-ups. Main-text access, exact variant/source
composition, publication dates and canonical identity remain unresolved where
documented. No access problem blocks these independent queues. Earlier queue
paragraphs below are historical; this note supersedes their FNANO2010 position.
Two targeted searches support candidate journal links for Liu metallization
(10.1021/nn1035075) and Bui quantum-dot nanotubes(10.1021/nl101079u).
No identity merges: exact conference scope and full author lists remain pending.
Search evidence and pending BYU dissertation/CUA/QDNA bibliography routes are
saved in fnano2010_pages78_counterpart_search.json and discovery run fnano-2010;
reconcile_fnano2010_first.py reproduces the links.
Reproduce current projections with export_reviews.py and checkpoint.py;
review_fnano2010.py resumes from its saved transcription.

FNANO2012 all9 official program pages now retain139 named entries without
keyword filtering:12,16,16,16,13,20,20,10,16 by title-start page. DISC0008 remains
active for full authors/speakers, abstracts and journal/preprint counterparts.
The p3 poster author list continues onto p4; the p6 final title has authors on
p7 and is retained once with a two-page locator. Page7 rendered inspection
confirms the printed missing numerals in “Encapsulation of D DNA” and “D and D
DNA Lattices”; preserve source typography pending abstract reconciliation.
Page2 rendered inspection confirms vHelix mojibake and F -ATPase typography.
The p3 SiO / D Real-Time and p4 D DNA titles retain extracted typography pending
image/abstract verification. These are uncertain conference leads, not complete
design evidence. See fnano2012_transcription.json, review_fnano2012.py and
fnano2012_schedule_audit.json. Next: abstract books, named counterparts (Schüller
CpG carrier, Bell nanopores, Han gridiron, Perrault lipid encapsulation, Woo
ParMRC), then FNANO2011 schedule, alongside B0011 sources and balanced screening.

FNANO2012 counterpart search supports Schüller CpG-carrier poster → existing
10.1021/nn203161y: all eight program authors match the journal group. Primary
abstract reports30helix tubes/up to62CpG sequences; exact poster scope remains
unverified. Publisher November17 versus PubMed Epub November23,2011 date conflict
retained; issue December27. No merge or new design certification. Exact ParMRC
title query yielded no supporting counterpart in returned results, not evidence
of absence. Saved fnano2012_counterpart_search.json and reconcile_fnano2012.py.

FNANO2012 source follow-up adds two previously absent publications:
10.1126/science.1232252 (Han gridiron,2013) and10.1039/bk9781849734165-00001
(Bell conference-proceedings book chapter,2012). Gridiron acquired lab PDF contains
ONLY printed p1412: preceding Li article and subsequent Li SI are not Han sources.
Page1412 reports11by11 perpendicular-layer gridiron,21bp spacing,5301of7249nt
body plus1948nt loop,12042nt staples,63bp cavity variants and scaffold-free/mixed
variants. Intro7429 versus design7249 source discrepancy awaits visual/sequence
check. Standard square-lattice eligibility is not established by a square frame.
Bell program five-author group matches proceedings chapter; same-title NanoLetters
paper has a different seven-author group. Candidate edges preserved without merge.
Extended existing nl204098n SI review records2344bp duplex extension separately
from body,13–18nm solid-state SiN device separately from DNA, and resistance-cone
approximation separately from routing. All4works in3numbered SI references retained
without filtering. No complete source certifications or new design groups.
See review_fnano2012_sources.py, fnano2012_source_followup_audit.json and retained
primary metadata JSONs. Next: full Han main/SI, Bell chapter/native sources,
Perrault encapsulation counterpart, balanced screening and FNANO2011.

Perrault2014 source follow-up preserves stable S041 and wireframe catalog
exclusion while extending literature evidence. Results/Methods plus SI captions
and Table1 identify144staples,12inner fluor handles and0/12/24/48outer lipid-handle
variants. Full extracted table has144unique endpoint pairs;132lengths agree.
Twelve p13rows list42but contain63bases. Rendered p13 confirms blue21base fluor
handles, explaining the omitted handle in printed length; no sequence corrected.
Remaining checks: complete routing/complementarity, scaffold sequence, exact handle
subsets/replacements, separate conjugate strands, and curvature Note1. Encapsulation
and lipid formulations are material conditions, not automatically new DNA cores.
The FNANO2012two-author poster is linked as possible2014journal counterpart, exact
scope unverified. Scripts review_perrault2014_followup.py and
perrault2014_sequence_inventory.json retain raw table and arithmetic evidence.
All38article references are extracted without filtering by
 discover_perrault2014_references.py; recursive identity/scope review remains open.

Balanced screening B0012 selected25records (15downloadedACS plus10rotating
low/broad records); first1of25 reviewed. acssensors7b00825 is a physical-paper
origami diagnostic, excluded after main Methods, Results, Conclusion and allSI
text inspection. Filter-paper wax channels/plastic chambers/glass-fibre capture
are distinct from analyte DNA and LAMP primers. Same-agent second-pass exclusion
audit recorded; no independent-reviewer claim. Online2018-02-05 agrees between
explicit publisher history and PubMed; January11header/repository labels conflict
with acceptance, retained in evidence. Main accepted manuscript acquired publicly.
See review_batch_0012_first.py and batch_0012_paper_primary.json. Next:
acssynbio7b00278 Inside-Out Viruses, remainingACS and all10rotating records,
then conference/source/citation follow-ups. No source-completeness claim.

B0012 second pass now4of25inputs screened (21unreviewed);3new design-source
first passes, no new source certification or catalog promotion. Inside-Out Viruses
sb7b00278: six-face M13box; face-joining/scaffold modification/i-motif strands
separate from dye replacements, GFP cargo and HIV-Tat coating. Exact native routing
and replacement sets remain open. Uptake ja7b09024: ST/SR use425nt cut fragment,
LT/LR usep7560; body paired-bp counts and scaffold lengths are distinct. Handle
placement and LR-Au labeling documented; whole sequence/packing checks remain.
Electro-optical modulator nl8b00332: frame plus HPV/OANI device compositions.
Renderedp13 shows graphical cavity-frame sequence map; bases not audited. P15six
modified staples/templates and p17assembly inspected; printed increasing65to25
thermal wording retained as source inconsistency. See review_batch_0012_second.py
and batch_0012_second_audit.json. Next: remaining11ACS and all10rotating records,
then detailed source/native/parent checks and conference/citation discovery.

B0012 third source pass now7of25screened,18unreviewed. Voltage nl7b05354:
p8064plate/pore plus separate duplex leash and A1/A2dye-location/split-strand
variants; exact replacement mapping remains open. Gap-filling nn7b08345:
small/large flat/tube wireframes with single-duplex edges; staple controls,
enzymatic products, curved and partial-fill variants distinguished. Four native
JSONs plus sequences.yaml inventoried with hashes; only metadata parsed, no
molecular authoring. SI p31swaps small/large tube descriptions and givesUFFS in
flat-large partial-fill recipe versus usualUFFL; these are unresolved, not repaired.
SAXS nl8b00412reusesp8064block/p7560bundle parents Stein2011/Kuzyk2012 with
CCCCedge oligos and particle-handle variants. Printed3primeT19label versus5primeHS
sequence needs reconciliation. No complete-source certification or new exclusions.
See review_batch_0012_third.py, batch_0012_third_audit.json,
inventory_gap2018_sources.py and gap2018_archive_inventory.json. Next:
nl8b00793, remaining8ACS/all10rotating records, with parent/source/citation
follow-ups retained. Native archive availability alone is not design completeness.

B0012 fourth source pass now10of25screened,15unreviewed. Dimer nl8b00793:
M13rectangular tiles A/B/C/D with edge/hairpin modifications; AB/CD↔AD/CB
pairings distinguished from monomer core identity. Base/modified tables identified,
full mapping pending. Switch nl8b00592: switchD16 plus separate brickA1/A2
monomers;10Tcontact deactivation and stacking16contacts documented. Parent refs3/4
Gerling2015/Bruetzel2016require exact lineage checks. All21SI references retained
without filtering; main bibliography/recursive discovery remain open. Nanohole
la8b00793SI supports triangle reuse in adsorption experiments but supplies no
construction recipe; substrate sizes and processing conditions are not DNA variants.
See review_batch_0012_fourth.py, batch_0012_fourth_audit.json and
 discover_switch2018_references.py / switch2018_reference_audit.json.
Next: remaining5ACS and all10rotating records, preserving native/parent/source
follow-ups. No new catalog eligibility or complete-source certifications.

B0012 fifth source pass now13of25screened,12unreviewed. Mass/shape nl8b00660:
nine named large/small rods, block, rings, octahedron and barrel; p3024/p7308
sequences and long tables located. Intro says eleven whereas contents/TableS1/
FigS3say nine; full inventory remains open. Beacon nn8b01510: SH/SV/DH sensors,
foot/hinge differences,56/60/30FRET-pair arrays and an additional labeled
nonaggregating tall-rectangle control. SV7ntscaffold hinge follows staple removal;
exact replacement/omission sets pending. Twist nn8b01669: explicit square-lattice
10.44/10.55/10.66bp-per-turn tiles, braced/rolled modifications and separate10helix
nanotube.29finite-element basis models are not29experimental core designs.
Sources inspected at stated section/caption depth; full sequence/routing and
per-design eligibility remain open. See review_batch_0012_fifth.py and
batch_0012_fifth_audit.json. Next: acsnano8b01844/jacs8b03914 then all10rotating
records; preserve citation/conference/native-source follow-ups. No new complete
source certifications or catalog promotions.

B0012 now16of25screened: all15ACS and1of10rotating records,9unreviewed.
FinalACS nn8b01844force-unravelling SI separates experimental handles from
simulated10ntpolyA replacements, modifiedRothemund rectangle,10HB and7tile
biosensor; exact experimental/model sources remain open. jacs8b03914SI has24HB/
tripodp7560 andRothemund triangle withRNA-capture replacements;720/1230/1910ntRNA
classes are not origami scaffold variants. Full capture/core tables still pending.
Rotating biophysics10.69full-text context describes60nmduplex myosin handle and
prospective origami muscle, retained as background, not a complete design. Follow
refs35/36/author history. See review_batch_0012_sixth.py and
review_batch_0012_rotation_first.py. Next: SNPchipDOI138527281815140916092815,
PDB4V5Xdeposition, and remaining7rotating records. No complete-source certification
or new catalog promotion; all previously recorded source gaps remain active.

B0012 now20of25screened,5unreviewed after four rotating records. SNPchip
138527281815140916092815publisher abstract supportsorigami/AuNPstrand-displacement
assay, but main/core/source completeness remains inaccessible/unverified.4V5X
correctly typed dataset: primary2012BaiPNAScitation,2014-07-09initial release,
2012deposition, five superseded split entries andEMD-2210association recorded.
CurrentRCSBmetadata includes2024update; historical pre2020model not certified.
No coordinates authored or downloaded. Synthetic-biology tools paper is explicitly
a review; section survey only, not full absence audit. Aptamer-smart-materials
review attributes origami nanorobot toDouglas/Bachelet/Church2012ref35; explicit
citation edge retained without treating review as new design. See
review_batch_0012_rotation_second.py, batch_0012_rotation_metadata.json and
pdb4v5x-entry-metadata.json acquisition record. Next five: protein-bionanostructures
review, supercritical-angle microscopy,polyploidyDNAstorage,HS-AFMreview and
cancer nanomedicine review. Broad/source/citation follow-ups remain unresolved.

B0012 first-pass queue is now complete25/25 (15ACS +10rotating), with25/25
retaining source/citation follow-ups and zero new whole-source certifications.
Final rotated inspection distinguishes protein-origami review from DNA designs,
actual tetrahedron reuse in supercritical-angle microscopy (abstract only),
genomic-DNA phosphate-storage experiments from incidental origami citation,
and two review records. Henderson HS-AFM first online2014-12-31 is primary
verified despite2015issue. Cancer review PMC4183929 retrieval hit a browser
challenge; institutional abstract/type supports metadata classification only.
Evidence: research/batch_0012_final_primary.json, batch_0012_cancer_access.json,
review_batch_0012_final.py and batch_0012_complete_audit.json; existing XML
PMC3938474/PMC3986227. Saved validation passes5873publication keys,
100stable legacy design IDs,11269hashed evidence references. Actual current
stages:1000metadata,58fulltext,191design-source reviewed,4624unreviewed.
Next: FNANO2011 official schedule enumeration/abstract acquisition; microscopy
tetrahedron main/SI and parents; balancedB0013; all prior source and discovery
follow-ups. No discovery closure or catalog-scope expansion is claimed.

FNANO2011 discovery DISC0009 now covers first4of12official schedule pages:
59named leads (13/18/16/12 per page), no title-keyword exclusions; named TBA
talks retained, administrative introductory remarks omitted. Text layer has
font substitutions (ti as R, tt as g); p1 visually checked, remaining visual
normalization pending. Raw extracted names/titles retained, no silent repair.
Evidence/transcription/replay: fnano2011_transcription.json, review_fnano2011.py,
fnano2011_schedule_audit.json. FNANO2012–2019 remain929program leads; total
with partial2011 is988. Remaining2011pages5–12 and2006–2010 unenumerated.
Following Wickham conference motor lead found Oxford2011thesis and candidate
journal counterparts nnano.2010.284/nnano.2011.253. New thesis identity retained,
no merges. Primary snippets in fnano2011_wickham_primary.json; replay via
reconcile_fnano2011_wickham.py. Thesis PDF acquired through paced resumable
fetcher: assets/research-20261105/wickham-2011-thesis.pdf (20,872,342bytes,
SHA256 ed5f48d83f9e32b2cf0e73823d574af9d20d9a621eab3848e71cebac6d46f0cd).
Only abstract screened; chapters/appendices and exact counterpart overlap pending.
Current validation passes5933publication/version keys,100legacy design IDs,
11397hashed evidence references. Next queue: FNANO2011pages5–12, thesis source
inspection, remaining B0012 follow-ups and balanced B0013. No coverage closure.

FNANO2011 schedule enumeration now complete12/12pages:169appearances,
167distinct kind/author/title leads; Bui/Cigler posters repeat on p6/p10 and both
page/date evidence references preserved. Combined2011–2019 program leads1096;
2006–2010 schedules remain unenumerated. Abstracts/counterparts are not exhausted.
Saved fnano2011_schedule_audit.json and fnano2011_visual_audit.json. Page7render
confirms Han title ends at functionalized in source; author-column clipping and
font substitutions remain explicit. No title-based relevance exclusions.
Wickham2011 thesis now source-reviewed at named sections, provisional family
RDE0039: TypeA original seam rectangle and TypeB reduced-twist tile. AppendixA
assignments have exceptions in Section2.6 and C.3.1 (initial Ch3fluorescence uses
TypeA). TableC.1 PDF226–232 yields216position-named rows:144x31,48x32,20x36,
2x28,2x48nt;15Mem rows:12x27+3x28nt. This differs from simplified Chapter2
counts; roles/end modifications and full synthesis composition NOT certified.
Saved review_wickham2011_thesis.py and wickham2011_sequence_inventory.json;
no molecular authoring. Source diagram/scaffold/variant/parent audits pending.
Current6041publication/version records,139design groups; validation passed
100stable legacy IDs and11634hashed evidence references after visual audit.
Next: FNANO2010 enumeration,2011abstract/counterpart follow-ups, thesis exact
compositions/native sources, balancedB0013 and earlier unresolved reviews.

Wickham thesis follow-up resolved edge context, not complete composition:
Section2.2 adds4T edge loops; visually inspected FigC.1 places all24unusual-length
position-named strands at +/-9outer edges/corners. FifteenMem rows still unassigned.
Saved review_wickham2011_edges.py with primary PDF locators; no molecular edits.
B0013 balanced25-input batch now2/25first-pass reviewed,23unreviewed inputs.
FRETam8b03585SI(12264080) lists12triangle sites and separate dye-complement
oligos, parentRothemund; smaller-array subsets/base sequences require main/parent.
Channelingja8b05429SI(12273029) specifies G6pDH152/153 and four LDHpaired-site
spacings, HJ139/163components, azobenzene and NAD+arm variants. Unmodified
TableS4 numbering is noncontinuous; complete scaffold/replacement/map audit open.
Evidence: review_batch_0013_first.py and batch_0013_first_audit.json; saved
validation6041publication/version records,100stable legacy IDs,11638hashed refs.
No new complete-source certifications. Next B0013nl8b01374tension probes,
remaining12ACS then10rotating2015records; retain FNANO2010 and all discovery queues.

B0013 now5/25first-pass reviewed,20unreviewed inputs. Tension-probe
nl8b01374SI gives425ntscaffold,16numbered staples andfunctional strands;
1H1P/1H2P/2H2P/3H2P plus helix4/6peptide and22/77%GC variants require exact
replacement audit. DE/LSam8b04757SI has separate staple tables/caDNAno figures;
four-oligo tetrahedron comparator retained as non-origami, not another core.
Custom scaffoldam8b09222SI explicitly square-lattice rectangles andTiamat
triangles, five named custom-scaffold objects plusM13rectangle comparator.
Methods/captions21261nt conflict with TableS4label and extracted20307bases.
Other scaffold tables yield10563/10782/31274bases, with lowercase t accepted
in10782table. Counts do not certify sequence correctness or full source set.
Saved review_batch_0013_second.py, batch_0013_second_audit.json and
chen2018_scaffold_inventory.json. First-pass audit preserved separately.
Validation6041publication/version keys,100legacy design IDs,11641hashed refs.
Next remaining10ACS startingbioconjchem8b00418, ten rotating2015records,
FNANO2010 and all earlier discovery/source-completeness follow-ups.

B0013 now8/25first-pass reviewed,17unreviewed. Three additional SI reviews:
bc8b00418rectangle has six LE/BEreplacement staples; base set explicitly depends
on Wang2012Angew10.1002/anie.201206389, parent edge saved. AuNPratio/length
and unintended shared-particle dimers kept separate from core designs.
nn8b02720has cross/shortrectangle/longrectangle plus linker-mediated1Dassemblies;
22-pageSI and13-page sequence supplement inspected at named sections.10.4vs10.67
bp/turn, biotin/streptavidin and two cornerGquadruplex staples recorded; full
per-shape composition/native maps still pending. la8b01933SI lists117base staples,
separateAuNP/AuNRcapture patterns,16troughstrands andA–Etails; particle multimers
are assemblies. FigS3/S14duplicate captions handled by PDFpage locators.
Saved review_batch_0013_third.py and batch_0013_third_audit.json. Current validation
6041publication/version keys,100legacy IDs,11646hashed refs including parent edge.
Next remaining7ACS startingjacs8b06146, tenrotating2015records; FNANO2010 and
all earlier discovery/source queues remain open. No new completeness certificates.

B0013 now11/25first-pass reviewed,14unreviewed. jacs8b06146BTAcomputing
excludednot_origami after primary XMLPMC6077772Introduction/Conclusion,
Results andExperimental subsection context plusSIoligo table. Origami references
are priorwork and microscopy-method attribution; citation discovery retained.
Same-agent exclusion audit explicitly identified, not independent reviewer.
am8b11167AuNRchirality hasM13rectangle with3x7capture sites; method omits
100–111/205–216but capturetable includes102/215. Exact replacement exception
unresolved. ao8b00934drugloading SI names6HB/60HB/Z/triangle/bowtie and reports
paired/unpaired counts; no complete base sequences supplied in SI, parent/main
sources pending. No molecular construction or complete-source certification.
Saved review_batch_0013_fourth.py and batch_0013_fourth_audit.json. Validation
6041publication/version keys,100stablelegacy IDs,11650hashed evidence refs.
Next4ACS startingacsnano8b04148, tenrotating2015records; all discovery queues open.

B0013 all15ACS inputs nowfirst-pass reviewed;10rotating2015records remain.
nn8b04148SI names wireframe rods by cross-section/edge size plusligated and
reinforced variants; complete architecture/native sources pending, polygonal
outline not lattice proof. la8b02225SI supplies plus/cross/Cmetal-pattern
staple lists andpolyA10capture annotations; underlying shared-core and full
color/replacement audit pending. oc8b00383excludednot_origami afterSIpreparation
and mainXMLPMC6202645object audit:four-oligo tetrahedra/dimer and20-oligotube,
origami is comparison/future work. Same-agent exclusion audit preserved.
la8b01850SI distinguishes direct/proximal/9ss/9ds/18ss/18dsTEG-chol strategies;
neighbor-staple versus extended-complement hybridization and3prime/5prime
cholesterol ends recorded. Statistical supplement is not extra design evidence.
Saved review_batch_0013_fifth.py and batch_0013_fifth_audit.json; validation
6041publication/version keys,100stablelegacy IDs,11656hashed evidence references.
No new complete-source certifications. Next tenrotatingrecords starting
jbc.r115.638452, thenFNANO2010 and all citation/author/source followups.

B0013 now20/25first-pass reviewed,5unreviewed. Rotating records: JBCmicrotubule
andDNA-biomedical-machines reviews classified from primary abstracts/type; full
attribution still pending. Publisherfirst-online dates2015-05-08 and2014-12-29
respectively distinguished from issue/otherdate fields. Abstract74combinatorial
arrays is journal-supplement conference abstract, not complete article; publisher
TOCdate2015-06-23. Caltech history provides2016BiophysJ/2017nnano.2016.256
candidate counterparts, no merges. Neighboring abstract DOI1032690PDF shares
page48but is not replacement identity for1032691. Primary snippets/access
failures saved in batch_0013_rotation_primary.json andabstract74files.
gkv994Ghairpin simulation andsrep08721protected displacement excludednot_origami
after primaryXMLmethod/object audits, preserving citedorigami leads. Same-agent
exclusion audit explicit. Saved review_batch_0013_rotation_first.py and audit.
Next5: nanopore044001,enzymemodelct5007482,goldseedingc4ra15451g,
oxDNA1.4921957,motionpnas1408869112. All prior completeness/discovery queues open.

B0013 first-pass screening is complete25/25; all25 retain source or citation
follow-ups. Final five: nanopore044001 and oxDNA2 remain uncertain at metadata
depth; GeomBD enzyme modeling and gold seeding establish broad origami reuse;
Marras motion main sections establish sliders/hinges and linked mechanisms.
No full source certification or narrow-catalog expansion follows. Motion SI PDF
and sequence XLS browser links returned challenges; public acquisition retry
remains tracked separately. Enzyme publisher dates conflict, so exact day is open.
Saved recipe research/review_batch_0013_final.py and batch_0013_complete_audit.json
record6041 publication/version rows,4599 unreviewed,1174 metadata-screened,
63 full-text-reviewed and205 design-source-reviewed; these are depth categories,
not complete-design counts. Validation passed11679 hashed evidence references
and preservation of100 legacy design IDs.139 design groups,62 source-review
groups and1 existing eligible-complete legacy record remain unchanged.
Next: motion supplements, nanopore/oxDNA main scopes, FNANO2010 enumeration,
balancedB0014, and unresolved author/citation/counterpart routes. Closure not met.

B0014 balanced25-input queue selected;3/25 first-pass screened,22 unreviewed
inputs remain. AFM manipulation DOCX and environmental-stability SI establish
reuse but not exact core identity; conditions are not new designs. Persistence-
length SI gives linearized M13mp18 and four seven-duplex rod component blocks.
Block labels imply pairs1+3/1+2/3+4/2+4 for500/1019/1481/2000nt variants;
this is not a full routing/sequence audit. Native file and lattice eligibility open.
Recipe research/review_batch_0014_first.py; audit batch_0014_first_audit.json.
Validation passed11682 hashed evidence references;4596 unreviewed records,
208 design-source-reviewed. Motion PDF direct download failed non-PDF validation
and is recorded in assets/research-20261105/acquisition.json; no false acquisition.
Next B0014acsami8b12374 and remaining12ACS,10rotating2015records; retain
motion/main-source, FNANO2010 and all discovery follow-ups. Goal remains active.

B0014 now6/25 first-pass screened,19 inputs remain. Source reviews add RDE0040
enzyme-capture rectangle (GOx fixed; HRP10/20/45/65nm) and RDE0041 HRP/Atto488
triangle with biotin anchors. Exact full composition/native sources remain open.
Paper-origami transport nl8b04051 is excluded after SI methods/TableS1 and primary
abstract scope audit: folded chromatography paper and four-oligo tetrahedral probe,
not DNA origami. This is a same-agent audit, not independent review. Saved recipe
review_batch_0014_second.py and audit batch_0014_second_audit.json; two explicit
method citations linked by discover_batch_0014_parents.py to existing Ke2008 and
Fu2012 records, with exact design lineage unresolved.
Actual totals6041 publications,4593 unreviewed,211 design-source-reviewed,
141 design groups,64 source-review groups. No new complete source certifications.
Institutional Hao Yan CV acquired as47-page PDF (initial html extension corrected
without changing bytes); SHA c7943d2851572d286437e52a2451b4e2e560c02f287c8f4b4ffde7772f046ccc.
Discovery run author-hao-yan-asu-cv is active; only selected page contexts inspected,
no full enumeration or author-history closure claimed. Next extract entire Journal
Publications section, reconcile pre2020 records, and continue B0014jacs8b10609,
remaining9ACS and10rotating records plus FNANO2010 and prior source follow-ups.

Hao Yan CV journal-section enumeration now retains239 numbered source entries,
not243 works: PDFp5 visually confirms numbering jumps232 to227. No entries
228–231 were invented. Entries224 and220 repeat the DNA Origami Tessellations
citation and require reconciliation; numbering is not work identity. The heading
also contains proceedings and submitted manuscripts. All raw entry text/page
locators are in research/hao_yan_cv_journal_inventory.json; extraction recipe
extract_hao_yan_cv.py asserts the observed sequence including the source gap.
239 pending discovery edges were added, no publication records or relevance
decisions.56 entries have normalized-title substring candidates and183 do not;
these are matching aids, not verified identities.165 entries have pre2020/mixed
year text,27 earlier-methodological,46 later/boundary and1 undated. Year text is
not primary first-online verification. Author route remains active; book chapters,
full date/identity reconciliation and other lab histories remain unexhausted.

B0014 now7/25 first-pass screened,18 input records remain. Triangular tilings
jacs8b10609 SI supports a three-domain equilateral tile, each domain32 helices,
M13mp18 origin5087, interior/bridge versus edge staple sets,48 negation strands,
and finite/unbounded/3D assembly variants. Exact table-to-variant composition,
native source and narrow lattice eligibility remain unresolved. No molecular
authoring or complete-source certification. Recipe review_batch_0014_third.py,
audit batch_0014_third_audit.json. Validation passed11934 hashed references;
6041 publication/version rows,4592 unreviewed,212 design-source-reviewed.
Next: reconcile CV pre2020 entries and source duplicates; B0014acsami8b15629,
remaining8ACS and10rotating inputs; FNANO2010 and all prior coverage/source gaps.

B0014 now10/25 first-pass screened,15 inputs remain. Three source reviews saved
in review_batch_0014_fourth.py and batch_0014_fourth_audit.json:
am8b15629 protein-crystallization rectangle/tubes: methods8/11/22nm diameters
and100nm length conflict with12nm side-chain table labels and110nm TableS1
length. PDFp18 visually confirms12nm; exact variants remain unresolved.
am8b19153 chiral plasmonic sensor: materials p7650 versus synthesis p7560
(PDFp6 visually checked); core/bridge/linker and right/left ds/split-aptamer
components distinguished. Native caDNAno is stated available on request, not
acquired; no contact made. acsnano8b08010 cell-spreading triangle: six peptide
sites,three biotin-EGF sites and15 amino anchors. TableS1 A33-Amino sequence
matches base C33 rather than A33; C33-Amino also conflicts with its base label.
Modified table PDFp4 visually inspected; preserve discrepancies, do not repair
sequences or certify complete sources. Substrate array pitch is not a new core.
Validation passed11937 hashed references;6041 publication/version rows,
4589 unreviewed and215 design-source-reviewed. No new complete-source claims.
Next B0014acsami8b18611 and remaining5ACS,10rotating records; reconcile CV
entries and continue FNANO2010, author/citation routes and all source gaps.

B0014 now15/25 first-pass screened: all15ACS inputs,10rotating records remain.
review_batch_0014_fifth.py and batch_0014_fifth_audit.json record five reviews.
Electrical-actuation rods:594/1715nt sequence headings include restriction sites;
exact cut fragments require graphical verification.50nm4HB methods versus6HB
TableS4 caption and duplicated4HB_3/_4 sequences remain unresolved. Short duplex
controls are not origami. Membrane diffusion distinguishes monomer/triskelion/
lattice and separate one-layer sheet; trimerization and multimerization strands
are separate sets. Nanobead microscopy SI reports measured brightness populations,
not exact dye recipes or independent cores. SERS probe reuses6HB,p8064,168staples,
four active sites with threeA15 handles each; original parent/mapping open.
TALOS is broadly design-bearing but excluded from narrow catalog as wireframe,
despite honeycomb6HB edges. This is a same-agent architectural scope audit.
Read-only inventory_talos_archives.py hashes481 library and113 source-code ZIP
members;240 geometry/sequence directory pairs confirmed, not source-completeness
or experimental validation. No code executed or structures extracted/authored.
Saved research/talos_archive_inventory.json with exact member names and hashes.
Validation passed11946 hashed evidence references;6041 publication/version rows,
4584 unreviewed and220 design-source-reviewed. No new complete-source claims.
Next ten rotating2015 records beginning10.1155/2015/245154; full CV identity/date
reconciliation, FNANO2010 enumeration and all earlier source/discovery gaps remain.

B0014 now20/25 first-pass screened,5 input records remain. Low-keyword pass:
muscle-contraction article is a review proposing future origami motor scaffolds;
cancer-nanoparticle anniversary item is commentary at metadata depth, with main
PMC access challenge. CCMV epitope study and abasic-site pairing study excluded
after named primary Methods/Results/Conclusions scope checks: protein VLPs and
short oligo melting respectively, not implemented origami. Explicit CCMVrefs32/34
linked to nl500677j andnn203161y. Audits are same-agent, not independent review.
Portuguese Nanocell item remains uncertain with publication type unassigned;
secondary metadata alone and failed primary DOI access do not justify an original-
design or news classification. Saved review_batch_0014_rotation_first.py and
batch_0014_rotation_first_audit.json; primary/access evidence files retained.
Validation passed11955 hashed evidence references.6041publication/version rows,
4579 unreviewed,1176 metadata-screened,66 fulltext-reviewed,220source-reviewed.
Next five rotating records:nanopore074004,cooperativitygkv602,ping-pong2014.0215,
CLEOPR7375859 andDETC46833. Full CV reconciliation,FNANO2010,all prior source
and discovery routes remain open; no closure or source-completeness claim.

B0014 first-pass queue complete25/25; all25 retain follow-up questions, no new
source-completeness certifications. Final five: nanopore074004 review at metadata
depth; cooperativitygkv602 supports origami measurements/model comparisons but
exact shape/native sources pending; ping-pong2014.0215 is a theoretical platform
proposal, not a demonstrated complete computing assembly. CLEOPR7375859 retains
conference identity and uncertain design scope; primary Optica page25E3_4 gives
2015event/proceedings while importedORCID says2016, so exact date unresolved.
DETC46833 primary access failed; possible2017journal1.4036216 identified from OSU
history, linked without merging. Recipe review_batch_0014_final.py and audit
batch_0014_complete_audit.json retain evidence depth and unresolved questions.
Next FNANO2010 enumeration, CV identity/date reconciliation, cooperativity main/SI,
conference/journal scope comparisons and balancedB0015. All earlier source and
coverage gaps remain; no closure claim. Saved primary searches omit signed
download URL query tokens; no private access or credentials used.

Hao Yan CV reconciliation:3/239 entries resolved bibliographically,236 pending.
Entry167 matches nchem.2852 by primary title/four authors, despite CVnchem.20405;
review classified at metadata depth, primary Epub2017-09-25 recorded. Entry88
matches ja106292x; primary JACS volume132 corrects CV138, existing design review
preserved. Entry159 cuboid vesicles matches anie.201610133; published header
explicitly pairs German ange.201610133. Both publication rows retained with one
canonical work identity; no source equivalence or design-completeness claim.
Primary title/header searches retained in hao_yan_cv_reconciliation_primary1/2.json;
reconcile_hao_yan_cv_first.py and hao_yan_cv_reconciliation_first_audit.json record
decisions. Author-hosted PDF fetch timed out and is logged failed; no local PDF
acquisition claimed. Other edition-pair candidates remain pending explicit evidence.
Count logic now includes publisher-header-verified editions as well as Crossref
preprint relations:6041 publication versions,6039 canonical keys,6037 provisional
unreconciled work keys,4 records with verified version/edition relationships.
4573 records unreviewed;1181 metadata,67fulltext,220design-source reviewed.
Validation passed11979 hashed references;11 ledger unit tests passed. No new
publication rows, no field-wide closure. Next remaining CV identities/date conflicts,
FNANO2010 enumeration, balancedB0015 and all unresolved design/source work.

CV identity reconciliation now5/239 resolved,234 pending. Entries130 and91
match International Edition title/authors/volume/pages;91 omits Jacovetty in CV,
recorded against primary author list. No additional edition merges: explicit
pairing evidence not obtained. Entry157 remains mixed-edition ambiguous (CV
International label with German128:13024–13027; primary International55:12832–12835).
Three primary metadata screens added: unidirectional scaffold construction and
layered-crossovers broad design-bearing; cage content remains uncertain beyond
identity because primary fulltext returned challenge. Main/SI/native sources not
certified. Primary Wiley lists25.1MB unidirectional SI, not acquired this pass.
reconcile_hao_yan_cv_second.py and hao_yan_cv_reconciliation_second_audit.json
retain decisions; primary3 search/scope evidence saved. Validation passed11987
hashed references;6041 versions,6039 canonical keys;4570 unreviewed,1184 metadata,
67fulltext,220design-source reviewed. No complete-source or coverage closure.
Next remaining CV matches/edition evidence, FNANO2010, balancedB0015 and prior
source/citation/abstract followups.

FNANO2010 discovery now underway (DISC0010): pages1–2 of19 visually inspected,
15named contributions transcribed (4 onp1,11 onp2) with separate conference types.
Font encoding corrupts extracted text, so rendering is required; no title-keyword
exclusions or completeness claims. Administrative welcome/chair/blitz headings
are not separate scientific records. See `fnano2010_transcription.json`,
`review_fnano2010.py`, and `fnano2010_schedule_audit.json`. Resume at page3;
17pages remain, then abstract/full-author and journal/preprint reconciliation.
All prior screening/source and234CV identity followups remain open.

B0015 first-pass queue completed25/25; all25 retain followup questions and zero
complete source sets were certified. JoVE identity verified from author bibliography,
classification remains uncertain due to full-text access failures. G-quadruplex
chapter reproduction inspected in limited sections; frame reuse supported, publisher
copy/source integrity and original counterparts pending. See
`review_batch_0015_final.py` and `batch_0015_complete_audit.json`; validation
passes12,029 hashed references. Next priority FNANO2010 complete program enumeration,
then continuing CV/citation/source routes and balanced screening. This is batch
completion only; research goal remains active and closure criteria are unmet.

Latest B0015 progress is23/25 first passes,2 pending. AJB cross article acquired
and main sections inspected: explicit square lattice, six layers72helices,178staples,
four3-prime biotin extensions. Provisional literature group RDE0042 added; source
completeness unresolved, no authored structure. Thesis and drug-review records
metadata-screened from primary repository/publisher evidence. Oxford2016 citation/
deposit conflicts with legacy2015; full thesis remains pending. See
`review_batch_0015_rotation_third.py` and audit. Validation passes12,027 hashed
references and100legacy IDs. JoVE52486 and G-quadruplex chapter remain unreviewed.
FNANO2010,234CV identities and all prior source/citation followups remain open.

Latest B0015 progress is20/25 first passes,5 pending. Four local XML section
reviews saved: silver-cluster and leishmaniasis background reviews; knotting-model
and sphere-lithography studies excluded after same-agent method audits. Nine
inspected bibliography leads retained without target eligibility inference.
See `review_batch_0015_rotation_second.py` and corresponding audit; validation
passes12,022 hashed references. Remaining: JoVE52486, G-quadruplex chapter,
AJB biotin-streptavidin,epmc1835 thesis,drug-delivery review. FNANO2010 and234CV
identities plus all earlier source/citation checks remain open.

Latest B0015 progress is16/25 first passes,9 pending. Wang2015 nanopore review
PDF acquired; header/abstract/section1.2/ref31 inspected, with Bell2012 citation
edge saved. PDF November16 date conflicts with publisher December16; unresolved.
JoVE52486 remains unreviewed: browser checks and guessed author URL404; unrelated
narrow search results are explicitly not classification evidence. See
`review_batch_0015_rotation_first.py` and its audit; validation passes12,009 hashed
references. Resume verified JoVE access plus other rotating inputs; no credential
request needed. Discovery/source queues remain open.

Latest B0015 progress is15/25 first passes: all15ACS inputs source-reviewed,
10rotating2015 records remain. Cross-shaped miRNA platform records ten modified
probes and parent Liu/Zhong/Wang/Seeman2011. Graphene nanopositioners separate
NR/ND/pillar cores, dye-position variants and pyrene controls; ATTO647N source
mapping remains open. No complete-source certification. See
`review_batch_0015_eighth.py` and `batch_0015_eighth_audit.json`; validation
passes12,006 hashed references. Next review rotating2015 inputs starting
10.3791/52486 and10.3934/matersci.2015.4.448. FNANO2010 and234CV identity
leads remain open, alongside all previous citation and source checks.

Latest B0015 progress is13/25 first passes,12 pending. Twist-control SI has
explicit FB/VB variant tables; contents mislabels S18–S20 as10insertions while
actual headings say12/14/16. Binding-site SI separates triangle/rectangle label
sets;16digoxin labels on15staples includes doubly labeled133. Neither source is
certified complete. See `review_batch_0015_seventh.py` and
`batch_0015_seventh_audit.json`; validation passes12,004 hashed references.
Next acsomega.9b01166 and nanolett.9b00172, then10rotating2015 inputs.
FNANO2010 and234CV identity leads plus earlier source/citation checks remain open.

Latest B0015 progress is11/25 first passes,14 pending. Fluorescent uptake study
oc9b00174 is excluded from origami after component-list and assembly-method audit,
while retaining methodological relevance. nl9b01201 documents an original6HB
pattern referencing Douglas/Chou/Shih2007; microtubule blocks/asters are separate
assembly levels. Exact acceptor-site composition and complete sources remain open.
See `review_batch_0015_sixth.py` and `batch_0015_sixth_audit.json`; validation
passes12,002 hashed references. Next acsnano.9b01561;4ACS and10rotating2015
records remain. FNANO2010 and234CV identity leads remain open discovery work.

Latest B0015 progress is9/25 first passes,16 pending. Custom-scaffold paper
nn9b01025 now has inspected design/variant captions and read-only XLSX/ZIP
inventory. Spreadsheet has Scaffolds/Helper plasmids sheets, not a certified
per-object staple set; ZIP contains software packages, not executed. Distinct
bundle cores, scaffold variants, oligomer assemblies, and switch/pointer diagrams
are retained for further reconciliation. Both final diagrams carry label S17.
See `review_batch_0015_fifth.py`, `nn9b01025_source_inventory.json`, and
`batch_0015_fifth_audit.json`. Validation passes12,000 hashed references.
Next acscentsci.9b00174;6ACS plus10rotating2015 records remain. FNANO2010,
author identities and all earlier source/citation followups remain open.

Latest B0015 progress is8/25 first passes,17 pending. RNase carrier SI records
56 stated capture sites versus54 named sequence rows, duplicate11/12muc1 sequences
(visually confirmed S21), and thiol-end wording discrepancy. pH capsule SI gives
explicit S1+S2+one-of-S3/S4/S5 composition, eight latch pairs and four10nt scaffold
links, with repeated coordinates retained as unresolved. No synthesis sets certified.
See `review_batch_0015_fourth.py` and `batch_0015_fourth_audit.json` for evidence,
reproducible extraction and validation of11,996 hashed references. Next input
acsnano.9b01025;7ACS and10rotating2015 inputs remain. Discovery queues unchanged.

Latest B0015 progress:6/25 inputs first-pass reviewed,19 pending. PX-DNA
bi9b00057 is excluded after SI sequence/assembly audit. la8b03804 records reused
rectangle partial-folding and seeding variants, with an inspectable read-only
sequence-table audit (225 base rows;56/20 pore omissions;14+14 add-back rows;
96 half-rectangle omissions and33 additional no-seam rows). These counts do not
certify synthesis completeness or routing. Evidence and exclusions are saved in
`review_batch_0015_third.py`, `batch_0015_third_audit.json`, and
`la8b03804_table_audit.json`; reproduce extraction using
`audit_la8b03804_tables.py`. Validation passes11,994 hashed references.
Next input: acsami.8b21724, then remaining9ACS and10rotating2015 records.
FNANO2010 enumeration and234CV identity leads remain open discovery work.

Resumed continuation: B0015 now4/25 first-pass reviewed,21 pending. The fourth
paper (ac8b05407) was excluded based on SI methods and visual inspection of the
image-only TableS1 on printed S3–S4: TDN13/17/26/30 use four oligos each;
TDN37 uses eight. These are tetrahedral oligo assemblies, not established origami
objects. Main article and citation checks remain pending. Reproduce with
`review_batch_0015_second.py`; audit in `batch_0015_second_audit.json`.
Next: acs.biochem.9b00057, remaining11ACS and10rotating2015 inputs;
FNANO2010 and234CV identities remain discovery priorities. Validation now checks
11,991 hashed references. The pause below records the earlier session boundary.

User-requested stopping point, November5: B0015 has3/25 first-pass inputs saved
in `review_batch_0015_first.py` and `batch_0015_first_audit.json`;22 remain
unreviewed within this batch. Brightness-density SI records7249nt rectangular
origami and an unresolved dye-end discrepancy; the2bp TableS2 row is present.
Protein-scaffolded hydrogel is excluded after same-agent SI methods/table audit
(main article not read). Liposome work distinguishes47-helix STDO and triangle
TrDO from encapsulation/drug conditions. No new complete-source certifications.
Validation passes with11,990 hashed evidence references and all100 legacy design
IDs preserved. Resume B0015 at10.1021/acs.analchem.8b05407, finish remaining12ACS
and10rotating2015 inputs, then continue source followups. Discovery queue retains
FNANO2010 enumeration,234 pending Hao Yan CV identities, and unfinished citation,
author/laboratory and conference counterpart routes. Existing downloads are
resumable; no private-access dependency is required for this queue. Goal paused
by explicit user request, not completed or blocked.

FNANO2013 all7official program pages now transcribed:132named entries,
including one cancelled Niemeyer keynote visually confirmed onp4. Source-label
counts21+17+20+21+16+21+16match saved transcription. Poster-session/reception
headers are excluded from scientific-entry counts. Overlapping p4author text
near Ko/Kellis remains explicit; rendered row startsDonaldKellis but extracted
text includesBrittanyCannon/WilliamKnowlton. RobertPenner p2 remains Monday15.
Unnamed ISNSCE award addressp3, contradictory reception wording, full authors,
abstracts and counterpart reconciliation remain open. DISC0007 stays active;
next conference schedule2012. No title-based relevance exclusions or complete
conference coverage claim. See fnano2013_transcription.json and
fnano2013_schedule_audit.json; rendered source inspection recorded in review notes.
Conference route found absent journal10.1126/science.1229919 (Sobczak2012),
exact title/four-author match, primary abstract screened; main/SI pending. This
illustrates ongoing discovery incompleteness despite large registry counts.
Casting2013poster has probable2014counterpart10.1126/science.1258361; all3
program authors appear in7-author article. Actual10-page main and121-page SI
acquired from author lab and named sections reviewed. RDE0036 provisional
family separates barrel/lid components, assembled molds, metal casts, and failed
prototypes. SI PDFp58 explicitly says main-text molds are square-lattice,
multilayer; honeycomb hexagonal test distorted. MutatedP8064 and SupplementII
sequence/map sections located but not certified. Main/SI extraction reports
Illegal URI-type link warning; actual CAD/images still need inspection. Sources
sun-2014-casting-main.pdf and sun-2014-casting-si.pdf; recipe
reconcile_fnano2013.py and fnano2013_counterpart_audit.json. No canonical merges,
complete-source claims or catalog promotions. Continue FNANO2013abstracts/counterparts and FNANO2012schedule,
rapid-folding sources, full mold map/sequence review, and balanced B0011.

B0011 completed25/25first passes; the initial three were: modular BLCS, polythiophene pad and localized HCR.
Actual39-sheet XLS inventoried with xlrd2.0.2 installed in temporary tooling;
recipe inventory_batch_0011_sources.py requires xlrd (PYTHONPATH can point to
/tmp/origami-research-readers). Source JSON audit includes reader version.
BLCS has source contradictions: introductory FigS6/S7 descriptions reversed
relative to captions; FigS15three offset groups versus sheet header two. Exact
packing and complete variant composition remain unresolved. RDE0037provisional
family separates base shapes, ties/conformations and multimer assemblies.
RDE0038pad source specifies16helices,6792/7249scaffold bases,210body rows with
replacement-by-type column and three handle patterns. Full mapping pending.
HCR ZIP central directory has twoAVI movies, native Tall_rectangle.json andSVG;
JSON/SVG hashed, JSON parses32virtual helix records, routing not certified.
Hairpins/anchors/initiators/readout/biotin roles remain distinct from core.
FNANO2013HieuBui poster linked as possible counterpart, exact overlap pending.
See review_batch_0011_first.py, batch_0011_first_audit.json and
batch_0011_source_inventory.json. No complete synthesis source sets certified.
Second pass saved3further ACS supplement reviews: seeded breadboard geometry
is distinguished from its origami core, peptide/TL nanosheets from short-strand
ribbons, and two-triangle chiral assemblies from responsive controller variants.
No complete sequence set certified; exact parents/lattices remain open.
Rotating gku233 is excluded after Methods/Discussion and a same-agent Results
second pass: implemented genelet circuit, origami only prospective background.
All52references enumerated without keyword filtering; target reconciliation open.
Recipes: review_batch_0011_second.py and discover_batch_0011_local.py;
audit batch_0011_second_audit.json. Saved validation passes after both writes.
Third pass: photonic-wire SI explicitly specifies three-layer square-lattice
p8064 block, with five modified fluorophore strands; graphical full routing/
sequences remain unchecked. Joint-motion SI distinguishes reused mechanisms
and connector-staple removal variants from sampled conformations; parent
Marras2015 and native-source transformations remain to trace. Electrical nanolever
SI explicitly specifies honeycomb1715nt restricted-M13 6HB with42bare staples;
seven periphery strands replace six core rows. Cut-prefix formatting and exact
split-staple mapping remain open. See review_batch_0011_third.py and audit.
Fourth pass saves enzyme-raft, nanostar-dimer and nanocavity-plate reviews.
Raft evidence separates bilayer-tethered catalase from GOx carried by triangle;
full staple/replacement audit remains open. Nanostar SI distinguishes two
monomers and edge versus branching sets for7/13nm gaps. Nanocavity plate has
two24-helix layers, p7560, four film anchors and six particle overhangs;
repeated staple IDs are alternative dye/overhang modifications. Internal iCy5
rows differ from the general3-prime caption; p29 visual inspection confirms anomalous staple22 thiol syntax is printed
in the source, not an extraction error. Intended correction remains unresolved. No source set certified or catalog scope broadened.
Recipes review_batch_0011_fourth.py and discover_batch_0011_si.py retain
three reviews and all26references across raft/nanocavity supplements; exact
identity/relevance reconciliation remains pending. Main bibliographies not covered.
Fifth pass completes all15selected ACS first passes. Short-scaffold sensing
remains uncertain: authors call it origami-based but SI describes ten short
oligos forming165bp duplex and protrusions; no scope shortcut or exclusion.
NuPOD8064nt rings distinguish0–32inner-handle versus48inner/outer routing maps;
protein sequences and cylinder simulation are not full DNA design sources.
PCP antenna SI distinguishes six particle handles, protein-biotin binding and
surface immobilization strands; pillar parent/lattice/source composition open.
Recipes review_batch_0011_fifth.py and discover_batch_0011_si_final.py save
three decisions and19supplement references (8short-scaffold,11NuPOD).
Reference parser initially mistook wrapped page-range19 for reference19;
contiguous-label assertion stopped before writes. Require same-line author text
for numbered NuPOD references; rerun matches all11. No complete-source claims.
First rotating pass reviewed mechanical conference and thermal journal Methods:
6nm×400nm nanotube preparation cites Kiss2012NEMS;197-staple rectangle cites
Woo/Rothemund2011nchem.1070. Explicit edges saved, exact variants pending.
DACCAD indexed Methods concern reaction networks; full-scope audit remains
uncertain because EuropePMCXML returned500 and directPMC browser challenges.
Saved author-uploaded article excerpts and indexed primary sections accompany
review_batch_0011_rotation_first.py and batch_0011_rotation_first_audit.json.
Second rotating pass acquires iinuma-2014-cage-main.pdf and cage-si.pdf
from Yin laboratory; both hashed in resumable acquisition manifest. Main Design/
ConnectorDesigns/PolyhedraAssembly and SI S2/table headings inspected: honeycomb
16-helix tripod arms, p8064, strut/vertex variants and short/long connectors;
actual pentagonal/hexagonal assembly uses120/140degree tripod designs. No
full sequence certification or automatic wireframe exclusion.
Gquad-frame primary abstract supports design use; publisher first publication
2013-12-20 corrects legacy issue-year2014. Actual supplement links remain open:
two guessed RSC SI filenames returned404; these failures do not prove absence.
Strand-break article retains uncertain scope after plasmid-film abstract review;
full Methods/context audit pending, PMC access challenged. See
review_batch_0011_rotation_second.py and corresponding audit/retained search.
Latest extraction index:208sources with12retained warning entries; neither
new cage PDF produced a Poppler warning. Extraction success does not validate
sequence completeness. Final3reviews saved: weighing-author PDF includes SI,
M13mp18 core with nine named core-to-hook substitutions and1/2/3particle-site
variants (full geometry/table audit open). Lithography paper is primary-abstract
confirmed review; tensegrity section5.4 attributes origami example to Liedl2010.
No new exclusion or source certification. All25input keys are saved and no longer
unreviewed; all25retain follow-up questions. review_batch_0011_final.py verifies
those invariants; batch_0011_complete_audit.json records actual counts.
B0011 completion means first-pass screening only, not complete design review.
Next: FNANO2012 abstracts/counterparts and FNANO2011 schedule, B0011 source and bibliography
follow-ups, next balanced screening batch, and uncapped citation/lab discovery.

Queue-selection bug fixed: ledger.select now resumes screening B-series batches
rather than being blocked by active DISC batches. Two regression cases pass;
11ledger/acquisition tests passed this turn. B0011 keys persisted using the
existing balanced15priority+5low+5broad selection. No production code changes.
Rapid-folding source attempts remain blocked: candidate ScienceSI filename
sobczak.sm.pdf returned403 (filename not verified), digital issue pg74returned
reader/login shell. Acquisition manifest corrected to failed with prior transfer
retained. No article text or full source claim. Public/authorized institutional
routes remain available for later follow-up; independent research continues.

B0010 completion: Chinese progress review and Japanese single-molecule review
were checked against explicit review labels, abstracts and conclusions. Science
Rewiring DNA Origami is a separate short highlight of Han et al p1412, not a new
design experiment. Primary Moller2013 Methods describes220nm12HB pillar with
three6HB base bundles and explicitly reuses ref14; parents10.1126/science.1228638
and10.1021/nl304492y retained. Main was readable in web renderer but direct
HTML acquisition returned empty. Ding2013hairpin abstract describes prospective
origami application; full text subscription preview, uncertain scope retained.
Amoako2013cached author-uploaded article excerpt supports5nm AuNP C-shape on
inner/outer origami double tube, explicitly reusing unresolved ref25. Actual
institutional PDF download404; alternate failed and subsequent web pages404;
locally retained excerpt is not a complete downloaded PDF. No final exclusions
or complete-source promotions added. See review_batch_0010_rotation.py and
batch_0010_completion_audit.json; acquired reviews and Science highlight under
assets/research-20261105, cached primary evidence in research/batch_0010_rotation*json.
Uncapped reference enumeration saved177edges from Shi90, Moller22, Ding49
and Endo16;
contiguous source numbering and saved counts audited. These are177provisional
target keys, not177new publications. See discover_batch_0010_rotation.py and
batch_0010_rotation_reference_audit.json. Resolve identities and scope; other source bibliographies remain to enumerate. Follow FNANO2013program and2014
counterparts, then balanced B0011. No citation/conference/lab closure claimed.

Latest continuation reviewed10 additional ACS sources. UV source explicitly
specifies square-lattice shaft with8-helix center/two10-helix flags; rectangle
ribbons use26linkers and26quenchers, separate from core identity. Aptamer A–F
functionalization variants retain shared-core checks. Nanolens source explicitly
reuses Rothemund sharp triangle; three particle arrangements are not established
as three cores. Graphite deposition retains triangle versus tile/lambda controls.
Simulated hinge variants0/11/32/53/74b require parent/experimental provenance.
Synthetic2.4knt DNA square and1.1knt RNA–DNA hybrid are separated; lattice and
hybrid scope remain open. LC study distinguishes nanoswitch,6HB nanotube and
reused sphere. NanoDyn source separates shared staples1–153, constraint154–170,
closing171–173 and10bp-linker174/175; virtual helices are not physical helices.
Cavity Raman templates retain missing cavity/staple mapping; I-motif miniM13
SI supports seam/control conditions but complete main/source checks remain.
Garbled formula text in nanolens/LC/cavity sources is explicitly flagged despite
successful extraction. See review_batch_0010_acs_third.py and
review_batch_0010_acs_remaining.py with corresponding saved audits. No new
complete-source certifications, design-group splits or catalog promotions.

Earlier ACS continuation adds imprinting10.1021/acsnano.6b04777, metallized
wire10.1021/acs.langmuir.6b04097 and hierarchical seed10.1021/acsnano.6b08008
source reviews. Triangular origami is separate from brick crystals/nanotubes
and polymer replicas; mixed paper remains unresolved for narrow eligibility.
Wire plating conditions are material outcomes, not separate core designs.
RDE0035 records provisional long/short/model/L/T/Y seed family. DAE-E tile
nanotubes are separate from M13-origami seeds. Successful junction lattice not
inferred from failed honeycomb attempt. Weak L-strut staples have10bp scaffold
complementarity and18Tspacer; authors explicitly doubt occupancy in some folded
structures. Complete tables/CAD/core matching pending. Explicit parent
10.1021/nl400881w verified from primary title/authors/pages; existing source
review preserved. See review_batch_0010_acs_second.py, batch_0010_seed_parent_web.json
and batch_0010_acs_second_audit.json. No complete-source certifications.

B0010 completed25/25first-pass reviews:4local XML records,15ACS source sets
and6balanced rotation records.
10.12703/p5-14 and10.1186/1556-276x-8-119 are reviews; the latter XML generic
research-article label is contradicted by its Review body and Conclusion.
Ribbon-crystals10.1371/journal.pone.0074932 uses18mm transparency ribbons;
origami is a background citation, not implemented DNA design. CpG-AuNP
10.1371/journal.pone.0063550 directly conjugates modified oligos to particles,
with origami only attributed to Schuller2011ref37. Both exclusions audited
against Methods/Conclusion/Discussion by the same agent, not independently.
All4bibliographies enumerated:210edges,205distinct provisional targets; no
recursive or target relevance closure. See review_batch_0010_local.py and
discover_batch_0010_local.py.
ACS10.1021/acsami.6b11001 SI describes computational single/double-layer
nanopores and temporary scaffold breaks reconnected before simulation; no
experimental synthesis claimed. FigS3/S4 actual maps/lattice/source completeness
remain unverified. ACS10.1021/acsnano.6b06861 SI separates tripod core,
30/60/90degree angle locks/releases, asymmetric conformations and AuNR loads.
Core-1 through core-119labels located but full sequence completeness not checked.
See review_batch_0010_acs_first.py and batch_0010_acs_first_audit.json.
Next: B0011 balanced selection; B0010 core/source follow-ups and
conference/backward/forward/author discovery remain active.

FNANO2014 all10 program pages now transcribed:140named entries, including one
withdrawn Kuzyk poster verified visually on PDFp1. First-listed author is not
necessarily the speaker. The Jeppesen p3 talk remains Monday14April. All page
entry-type counts match the source:13+17+16+14+14+15+16+15+17+3=140.
No title-based relevance exclusions, abstract reviews or complete-design claims.
Durable input: research/fnano2014_transcription.json; importer review_fnano2014.py;
source/count/hash audit fnano2014_schedule_audit.json. DISC0006 remains active
for counterpart/source follow-ups. Next:2013schedule, unnamed2014 award address
p8, full authors/speaker roles, abstract book and journal/preprint counterparts;
maintain balanced B0010 source reviews.
FNANO2014 counterpart follow-up added previously absent10.1038/nmat4031 after
primary title/author/date verification. Actual22-page SI acquired and named
sections reviewed:two14HBs, two scaffold crossings with8ntspacers,12AuNR handles
per bundle; left/right/relaxed conformations and removal/return strands distinct
from core identity. Source says p7650 onpp1/11 but p7560 inFigS6p12; unresolved.
No complete sequence/routing/lattice certification; Poppler font warnings retained.
Schaffert candidate10.1002/smll.201503934 has overlapping authors but addsMortensen;
2016journal date remains separate from2014conference. No canonical merges.
Official META2014 same-author invited-talk lead retained; fullprogram pending.
Hariadi candidate remains unconfirmed after PubMed challenge. See
reconcile_fnano2014.py and fnano2014_counterpart_web_evidence.json.

RecA DOI10.1103/physreve.87.032702 was excluded after inspecting Results II.A
and the entire Conclusion: origami is a thermodynamic comparison, not design reuse.
Retained source: assets/research-20261105/vlassakis-2013-main.html.
Korevaar PMC3808594 returned a browser challenge (manifest corrected to failed);
institutional PDF route returned404. Alternate primary routes remain open.
See research/batch_0009_rotation_audit.json and review_batch_0009_reca.py.

B0009 completed25/25first-pass reviews:15selected ACS source sets, five local
XML records, RecA primary HTML, Doll primary review sections, and three
metadata/abstract screens. Completion is batch screening, not complete design review.
Doll10.1098/rsif.2012.0740 section3.2 and Conclusions attribute origami designs
to prior papers; retained as background review. Korevaar10.1073/pnas.1310092110
remains uncertain: primary abstract studies OPV enantiomer coassembly; indexed
discussion compares origami refs25–28, but full source not acquired.
EuropePMC XML routes for both articles returned500; Doll PMC HTML succeeded.
Albany abstract14410.1080/07391102.2013.786386 is explicitly a conference
abstract, published2013-05-29; all three cited references retained, exact
Kuzyk2012 and later orientation/hotspot counterpart mapping pending.
Tubule10.1088/0957-4484/24/43/435601 author abstract establishes design relevance
but core/lattice/source completeness remains open. IOP PDF was non-PDF.
Official ASME2014-36708 same-title technical presentation retained as separate
conference lead; no automatic journal merge. See review_batch_0009_remaining.py,
batch_0009_remaining_web_evidence.json and batch_0009_completion_audit.json.

Choi lab primary bibliography now fully enumerated for this page:90publication
and8patent paragraphs;60publication and1patent entries state pre2020 years.
Only5entries match explicit existing DOI strings; other identities, PMID links,
publication types and dates remain pending. All98edges preserved without keyword
filtering. See choi_bibliography_inventory.json and discover_choi_bibliography.py.
Google Scholar navigation and further lab/author/citation routes remain open.

`review_batch_0009_acs_remaining.py` records ten
additional named-section reviews. Electrotransfection distinguishes tCRROsquare
rectangle, hollow honeycomb tube and compact honeycomb42HB, plus21fluorescent
adapters; complete core/scaffold mappings remain open. pH-responsive tile cores
are separate from dimer/trimer connections. Cuboid body/passivation/caps differ
from assembled fibrils. Aptamer frames differ from separately folded DXtiles.
Frame-group inconsistency (three groups versus G1–G4; frame1/3same listed recipe)
was confirmed visually on SI p2, not corrected. Molecular-logic capture labels,
pH-table recovery row and cuboid connector-stock units are explicit questions.
SERS dye-load variants and force-spectrometer nucleosome adapters are separate
from their cores. Protein-mask and Au-nanowire supplements establish experimental
origami use but do not supply complete core designs. No new certifications.

`review_batch_0009_acs_first.py` records named
sections and seven provisional groups RDE0028–34. Nanotube6HB142core+24binding
staples has four/eight-site variants;841ntunused p8064scaffold loop is separate.
SAXS sheet/brick/24HB use p7308/p8064/p7560respectively; SI explicitly states
square packing for sheet/brick and hexagonal packing for24HB. Native topology,
parentage and complete staple checks remain open. Hexagon-tile family includes
failed designs and separates eight connector alternatives from core routing;
higher-order honeycomb geometry is not proof of intrabundle honeycomb packing.
Cuboid-mask FigS11 was rendered and visually inspected; complete routing not
traced. Nanoflower table distinguishes AuNPattachment, internal anti-stacking
inserts and interflower A/Blinkers. No certified source sets or catalog promotions.
SAXS extraction has corrupt math/ellipsis glyphs despite no stderr. Hexagon CAD
pages produce enormous whitespace-heavy text; inspect figures visually for topology.

Perspective10.1091/mbc.e13-03-0155, review10.1101/gad.226837.113 and interview
10.1083/jcb.2002pi are background/discovery sources; generic XML article types
were checked against actual content. G-quadruplex paper10.1093/nar/gkt592
explicitly reuses Endo2010frame10.1021/ja907649w; assay duplex variants are
separate from the frame core. Computational10.1093/nar/gkt1269 reuses Stein2011
origami FRET switch10.1021/ja1105464; separate19oligo seven-helix antenna is not
automatically origami. Parent links saved, exact variants/lattice/SI remain open.
See `review_batch_0009_local.py`. Complete reference lists from these five sources
are retained by `discover_batch_0009_local.py`:249citation edges,245distinct
provisional targets (63+64+22+95+5references). Enumeration is source-local,
not closure of identity, relevance, recursive or forward discovery. Continue
B0010 balanced queue, B0009 source follow-ups, supplementary DOC/ZIP acquisition
and FNANO2014.
Both direct PMC bin routes for the XML-named DOC/ZIP returned404; failures saved
in acquisition manifest. Try actual current publisher/PMC supplement links or OA
packages next; no source contents inferred from filenames. No authentication used.

Latest B0008 source batch:15/15 selected ACS supplements have named section-level
reviews; all25/25 first passes are now saved, including the remaining eight
low/broad records. Ten provisional design families RDE0018–27 were
recorded without certifying complete source sets or distinct-core identity. Examples:
28 capture replacements versus170 parent nanotube staples; computational small
origamiA versus calibrationB; four monomer/interface variants versus tetramer
assembly; separate ring protein/lipid handles; rectangleA/B versus8-mer assembly;
two curved24HB versions versus LH/RH cargo and ring connectors. Exact role as new
or reused design remains uncertain where parent evidence has not been inspected.

Truss paper10.1021/acs.nanolett.6b00381 includes a conventional6HB control in
SI p7 across three scaffold clones. Truss objects remain outside narrow catalog
scope, but paper-wide exclusion is unwarranted; control source/lattice review is
pending. ZIP lists four truss CAD files and no6HB control. Folding-pathway ZIP is
image-analysis code, not a CAD archive. Dimerization workbook actual sheet names
(staples,hairpin,blockers,Linkers,CaDNAno Origami Snapshot) differ from descriptive
SI labels; exact sheet composition remains pending. Inventory and member hashes
are saved in `batch_0008_archive_inventory.json`. See `review_batch_0008_acs.py`.
Light-release PDF extraction emits syntax/image errors; polarizability equations
have corrupt extracted glyphs. These are recorded limitations, not repaired data.
No final exclusions or newly certified synthesis sets in this batch.

DISC0005 bounded batch is complete with open route/source follow-ups. Chiral
filament primary author-hosted PDF inspected at pp1–3,9–10:7560nt scaffold,
177 staples for straight6HB, four6HB twist variants, separate8HB and10HB rods.
RDE0015–17 preserve those families; bulk ribbons/membranes and virus controls
are not additional origami cores. Entire2-page SI contains movie descriptions only,
not staple tables. Full sequence/native-file and lattice checks remain open.
See `review_chiral_filaments.py`; no complete source sets claimed.

B0008 saved25-record rotation (15 candidate/ACS, five low-keyword, five broad).
The bounded first-pass batch is complete; source checks remain open. RSV paper
10.1073/pnas.1309070110 explicitly reuses silver-enhanced left-handed origami
AuNP helices as tomography handedness controls, citing10.1038/nature10889;
this is a supported reuse, not a title-based exclusion. AFM paper
10.1049/mnl.2013.0483 Methods/Fig2 uses M13mp18 nanotubes with28 repeating
staple units; its proposed AuNP/MEMS scheme is conceptual. Kiss ref17 parent
identity and source figures remain open. Evidence retained in primary HTML and
`batch_0008_web_evidence.json`; direct Wiley HTML403, but web-tool Methods text
was inspectable. Hinckley primary PMC HTML was acquired despite publisher PDF403;
Results/Discussion/Conclusion support background-method classification (duplex/
hairpin benchmarks; origami a prospective application). RNA-hybrid RSC landing
and author PDF returned403; direct indexed SI URL returned404. Hybrid chemistry
is explicit and narrow catalog eligibility remains unresolved. Two conference
abstracts are retained independently: Liu141 in Albany2013 Book of Abstracts,
and Kauert in Biophysical Journal supplement with matching society program.
Crossref journal-article types do not override primary conference evidence;
Kauert primary abstract still inaccessible. Liu Crossref PDF link has a different
DOI and is not trusted. Liu/Fan chapter is a review; full chapter access unresolved.
Jin graphene paper reuses a p7308 origami ring, citing Dietz2009; L/X/Y/Z letters
and ribbons are SST. All3pages SI inspected (morphology/Raman, not sequences).
No new ring core counted before exact-parent mapping. RSC loop-crystallization
paper first-online2012-11-23 differs from2013issue; ACS rotary-frame header2012-12-19
differs from explicit online2013-01-11. Dates preserved without silent resolution.
See `review_batch_0008_remaining.py` and retained web evidence files. No new
catalog exclusions or source-completeness certifications. Next: journal counterparts
for abstract141, inaccessible SI/frames and exact ring parent; continue FNANO2014
and balanced B0009. Bibliographies of Liu/Fan (73references) and Jin (60) are
enumerated without filtering; source-local closure only. Saved inventories and
`batch_0008_reference_audit.json` retain matched/unresolved denominators:
70/133 citation targets matched existing explicit DOIs;63 need identity/scope
resolution. These counts concern citation edges, not distinct new publications.
Abstract141's two references are identified: Pal10.1021/jp312422n (existing,
B0004SI review) and Deng10.1021/ja3081023 (new publication lead). Deng remains
uncertain pending primary main/SI inspection; conference attribution of origami
patterning is retained. No conference/journal canonical merge. See
`reconcile_albany2013_abstract141.py`; broader Albany abstract-book coverage open.

Dietz entry47 DOI typo resolved: lab text10.1138/nmat4909 is preserved while
primary metadata verifies10.1038/nmat4909, matching title/full authors and online
2017-05-22 (issue2017-08). Abstract screened as design-bearing; no source-set or
lattice completeness claim. Old lab URL returned a generic Browse Articles page,
explicitly marked failed acquisition with the original transfer retained. Canonical
publisher HTML acquired successfully. See `reconcile_dietz_chiral.py`. Next source
queue includes chiral-filament Methods/Results/SI and rotary SI alternatives.

Latest source/citation continuation: all33 positioner references and all30 rotary
apparatus references enumerated without relevance filtering. Three focused parser
fixtures passed (duplicate numbered bibliography labels, book ISBN year boundary,
and inline reference text with explicit DOI). Source-local bibliography exhaustion
does not close the citation route.

Rotary apparatus10.1126/sciadv.1501209 primary XML reviewed (Introduction, Results,
Discussion, Methods and Fig1–4 captions); RDE0014 retains rotor/clamp/module and
socket variants separately from assembly and Mg conditions. Rotor54×94bp and
clamp62×115bp domains have explicit honeycomb evidence. The430nm6HB crank module
is separate. SI diagrams remain uninspected: original DC1 URL returned403 and PMC
web viewing returned a browser challenge. No complete source-set claim. Apparent
rotation-tolerance wording and annealing-ramp/total-time inconsistency remain
questions, not silently corrected. Dietz bibliography entry35 now matches primary
XML identifiers and author/title/journal evidence. See `review_rotary_apparatus.py`
and `discover_positioner_references.py`.

Latest DISC0005 extension: all14 FNANO2015 schedule pages were inspected and130
named scientific presentations retained, without relevance filtering. This brings
named schedule leads for2015–2019 to518. Full author groups are still partial except
explicitly completed follow-ups; the unnamed2015 ISNSCE award address on p12,
abstracts and journal/preprint identity reconciliation remain open. Both2015 PDFs
were compared to prevent duplicate presentation rows. See `fnano2015_entries.tsv`,
`fnano2015_source_comparison.json`, `fnano2015_schedule_audit.json` and
`review_fnano2015.py`.

Positioner10.1038/nnano.2015.240: publisher metadata verifies online2015-10-19
versus issue2016-01. Public32-page SI Methods and selected design/characterization
sections inspected; Fig3 independently rendered. p7704 core with four2nt hinge
connectors, four30nt loose loops and adjustable duplexes is recorded as RDE0013;
configuration measurements are not counted as independent core designs. Sequence
completeness, lattice eligibility and full variant mapping remain unverified. The
main article is a subscription preview; no full-text access claimed. SI extraction
has invalid-font-weight warnings. All33 main references are now retained as citation edges; relevance/recursive
review remains pending. The Dietz laboratory bibliography
now has107 numbered entries retained from both linked pages (65 have stated
pre2020 bibliography years); these are discovery edges, not107 new publications.
The six patent entries and three book/thesis entries remain retained as unnumbered
source paragraphs pending record reconciliation. Repeated number100 and DOI typos
remain explicit; see `dietz_bibliography_inventory.json` and
`discover_dietz_bibliography.py`. See
`review_fnano2015_followup.py`. Next: reconcile unmatched lab entries, patents/books/theses, then FNANO2014
and rotated broad/low-keyword screening.

DISC0005 primary follow-up reviewed light-harvesting paper10.1021/acs.nanolett.5b05139
and SI pp1–4. It experimentally varies more than30 dye configurations on a
170bp-by24-helix two-layer platform; RDE0012 retains the family without claiming
an exhaustive variant/source map. Eight modified strand sites and dye termini
are tabulated. The finite platform parent is10.1021/nn505825z; its previously
reviewed periodic simulation models remain distinct. Complete conference authors
were transcribed, with the journal counterpart still tentative.

The chain-armor lead yielded Cassinelli thesis10.5282/edoc.21476, stable key
`thesis:lmu:21476`. Inspected chapters3/4 use24-oligonucleotide SST nanotubes;
whole-thesis relevance and conference counterpart remain unresolved. Title-page
2016, oral examination2017-05-02 and repository deposit2017-12-08 are separately
recorded. PDF p63 visibly prints22mer end strands whereas p70 Methods says28mer.
The optional-content-group parser warning persists; only p63 has a source-image
check. See `cassinelli_source_check.json` and `review_fnano2016_followup.py`.
The alternate FNANO15Program.pdf is14 pages; its first page is a2015 timetable,
not evidence of a2016 abstract book. All14 pages of2015 have now been enumerated, alongside
thesis scope, exact light-harvesting variants and unresolved conference abstracts.

FNANO2016 follow-up inspected all8 official schedule pages and retained145 named
scientific presentation rows, including low-keyword and non-DNA subjects as uncertain
leads. Per-page/type counts match source labels (21,20,21,18,20,21,17,7).
`fnano2016_entries.tsv`, `review_fnano2016.py` and `fnano2016_schedule_audit.json`
make the transcription and bounded count audit reproducible. First authors only
are transcribed; abstract content and complete design/source availability are not
inferred. A combined-topic Lukeman poster row and two unnamed award sessions
remain explicit gaps. Rendered p5 confirms sponsor text overlaps Patrick D. Ellis
in the source itself. The archived2016 program links a2016 schedule but its booklet
link points to FNANO15Program.pdf; it did not supply a2016 abstract book. The
archived award page names past winners only, leaving2016 addresses unresolved.
Scoped web searches did not locate a full2016 abstract book; no exhaustive-absence
claim is made. DISC0005 retains counterpart and abstract follow-up, then schedules
2006–2015 and the wider author/backward/forward routes remain open.

B0007 completed all25 first-pass screens:17 have section-level source reviews
(all15 ACS supplements and two rotating records); eight have metadata/abstract
triage only and remain uncertain.
Fifteen reviewed inputs are design-bearing; X-DNA lipid-network and nanotube
simulation cases retain unresolved topology questions. EGNAS computationally
redesigns attachment sequences for a triangle and6HB; two design families and
explicit parent links preserve the difference from experimental parent sources.
The phage-production paper tests an adaptable-loop rectangle, pointer,42HB and
gear; it is design-bearing despite its production focus. Motor-ensemble primary
text reports a12HB chassis with configurable handles. Direct PMC acquisition
returned a challenge; saved web-provider primary text supplies the review evidence.
No final exclusions or catalog promotions were made. Reproduce with
`review_batch_0007.py` and `review_batch_0007_followup.py`; source locations and
limitations are in each record. `batch_0007_triangle_archive_inventory.json`
hashes all members of the existing sharp-triangle ZIP without molecular authoring.
Next: primary full text for eight metadata-only records, EGNAS Additional files7/8, triangle
XLS/JSON mapping, and the unresolved X-DNA/nanopore topology checks. Broader
FNANO/author/citation discovery remains open and must rotate back after screening.

Additional source follow-up acquired arXiv1111.7130v2, posted2012-10-02 with
initial submission2011-11-30. This differently titled preprint is retained as a
separate record without journal work-key merging. Its inspected sections describe
O1–O4 experimental rectangle variants, O4 computational scaffold permutations,
and O5/O6 crossover redesigns. RDE0011 preserves these variants with routing and
complete-source checks pending. All27 numbered bibliography entries were retained
without filtering; PDF pp19–20 and the start of figures p21 were checked to audit
the extraction boundary. See `review_arbona_preprint.py`. The EPL offprint route
returned empty content/403; HSQ publisher PDF returned403; ECS PDF route returned
non-PDF content. These are route-specific failures, not universal access claims.
MEMS2012 program p29 supports a50nm-square imaging lead; full proceedings/source
verification remains open. Next discovery route: full FNANO2016 schedule, then
remaining years and abstract books; continue27 Arbona citation targets in parallel
with future source-review batches. No author contact or private credentials used.

Latest Douglas follow-up reviewed the2007 primary nanotube text and added
RDE0008 (front/rear monomers and heterodimer, source completeness unresolved).
PMC metadata independently verifies DOI/PMID and2007-04-02 date. Six supplement
links returned HTML rather than PDF; all responses remain retained but are marked
failed in the acquisition manifest. The downloader now checks PDF content.
See `research/douglas_supplement_access_audit.json`. The downloaded later protocol
is a2013 paper10.1038/nprot.2013.037 despite the filename containing2011; its
substantive design review is pending. Local primary XML resolved two further
Douglas bibliography PMID identities. The2017 Perspective10.1126/science.aam9541
was reviewed as background; all11 Crossref references were retained without filtering.
Its absent author-text reference list and publisher layout still require inspection;
no final catalog exclusion was made. A seven-PMID EuropePMC request failed503.

The pScaf2268 original2018-05-16 CSV is byte-identical to the pinned copy.
The native design path has49 positions, agreeing with the stated Length49 but
not resolving the51-character ambiguous sequence. See
`research/pscaf_2268_history_audit.json`; no molecular source was changed.

pScaf follow-up inspected primary Methods2.4, Results3.2–3.3 and Availability.
Four existing6HB/trimer groups S008–S011 gained evidence. Six pinned author files
were inventoried; CSVs contain48/72/96 staple rows. The2268 CSV row69 contains
???? and51 characters versus stated Length49. Source is unchanged; this ambiguity
and all scaffold/routing/connector completeness checks remain unresolved. Six brick-like
objects remain separate morphology questions. Crossref explicitly links preprint
10.1101/309682 (deposited2018-04-27 date) to journal10.1093/synbio/ysy015
(XML2018-08-09 date); one work key now covers both separate versions.
Both2017/2018 conference relations remain tentative. The current Douglas lab
bibliography yielded17 entries (11 stated pre2020), all retained without keyword
filtering; duplicate HTML anchors were disambiguated. Its older-publications link
now provides only a Google Scholar citation-profile link. Historical author coverage
and unresolved bibliography identities remain open.

B0006 completed25 first-pass screens:15 ACS supplements plus ten rotating records.
Sixteen records are design-bearing and nine remain uncertain; eight of those nine
are metadata-only cases. The crystal-replication paper uses a32-helix origami seed,
verified in author-hosted main/SI sources; daughter tile crystals are distinguished.
Five original design-group IDs now have additional source notes: S061/S062 workbook
sheet identities and D017/D018/D019 primary lattice evidence. No sequence-to-routing
completeness was certified. RSC c2cc32204h SI direct acquisition failed and remains
queued. Three parent-design citation links and three rendered-page checks were saved;
see `research/batch_0006_image_checks.json`. am501599f and nn502058j SI extraction
warnings remain explicit. Next: FNANO2017 schedule and author/citation routes, then
Schulman adapter Methods12.9, eight metadata cases and six notched-rectangle variants.

B0005 completed25 first-pass screens:15 ACS sources and10 rotating records.
The paper-folding assay10.1021/ac402118a was excluded after inspecting main
materials/fabrication/conclusions and SI, then a same-agent second pass.
CanDo validation10.1093/nar/gkr1173 reports experimentally built A/S objects and
four honeycomb32HB crossover-density variants; two research groups were added
without catalog promotion. The primer SI was acquired and experimental stability
methods inspected. RSC direct fetches returned403, while saved web-provider
abstracts supplied limited evidence. An IEEE response returned zero bytes; it
is now marked failed and the downloader rejects empty responses with a regression
test. Next source queue: CanDo SI and alignment SI, then broader FNANO/author routes.

B0004 completed first-pass screening of 25 records. `research/review_lally_voigt_sources.py`
then inspected the 250-page Lally thesis at selected Chapter 3/Appendix B sections and
the 41-page Voigt supplement at assembly/design/sequence sections. Neither source
has complete sequence-to-routing verification. Two named thesis design groups were
added only to the research ledger. The thesis stable key `epmc:1320` now carries its
repository DOI and full author name; 2010 thesis date and 2012 repository deposit
remain separate. Poppler font warnings for the Voigt SI and near-empty extraction
for the carbon-nanotube SI require source-image checks. Fifteen B0004 ACS records
and eight metadata-only records retain explicit source questions.

Public ACS restoration is paced and resumable using
`python3 experiments/origami_publication_catalog/expansion/restore_acs_assets.py --restore`.
Do not restart successful files or treat historical download status as local presence.
The asset link resolves onto the mounted Archive filesystem (3.2 TiB free at start).
No private authentication was needed or tested; current VPN access is unverified.

'''
    out+='B0003 public Europe PMC DOI lookups returned HTTP 503 for three records; Crossref metadata was acquired as fallback. Six other lookups succeeded (two returned zero hits, not evidence of absence). The author-hosted Science probe-tile paper was acquired and inspected. See the hashed acquisition manifest.\n\n'
    for b in active:
        out+='### '+b['batch_id']+' persisted input queue\n\n'+'\n'.join('- `'+k+'`' for k in b['input_keys'])+'\n\n'
    out+='''Continue article/SI inspection for that queue, with all design and identity gaps
retained per record. Revisit B0001 fulltext/metadata-only source gaps, especially
box, pointer, folding-pathway papers, all lattice questions, and exact variant sets.

FNANO2017 all ten pages have been inspected and116 named scientific presentations
retained, including low-keyword entries. Full authors are transcribed for the caliper
lead only; others remain explicitly partial. Two unnamed award sessions on pp6/9
remain unresolved. A scoped Duke-domain search returned schedules, not an abstract
book; other routes remain open. The caliper journal SI was inspected and a tentative
counterpart edge recorded. Native caDNAno is described as available on request; no
author contact was made. DISC0004 continues abstracts and version reconciliation.

FNANO: all 14 official 2006–2019 schedules are retained with hashes, using actual
overview hyperlinks. All ten 2019 schedule pages and seven 2018 pages were inspected: 50 and 77
potential presentation leads, respectively, are retained. DISC0003 inspected two
likely journal counterparts using existing primary XML; relationships remain
tentative until abstracts confirm scope. A publisher correction to the antibody
paper restores omitted SI references48–62; it is a separate linked publication.
The magnetic-actuation SI was inspected at selected diagram/table sections and
separates folding from polymerization strand sets. No full abstract book has been inspected; journal/
preprint matching and remaining program-item dispositions remain open. Other
8 years (2006–2013) have not yet had their programs enumerated;2014 has140named program leads retained, but abstract/source review remains open. A second14-page2015 schedule was
acquired from an actual archived2018 program link; its full text was compared with
the official schedule (room-label/format differences, no presentation-content differences). That
link does not provide a 2018 abstract book. Exact-title and abstract-book web
searches also failed to locate that book in the checked results; archival routes
remain open. Web-tool homepage/overview access
returned HTTP 403, but public direct acquisition succeeded.

Backward references: B0005 extracted all89 references from the CanDo validation
and seesaw-gate primary XML articles (87 distinct target keys, still provisional).
See `research/discover_batch_0005.py`; no automatic eligibility decisions were made.
Resolve unmatched DOI/no-DOI targets, then recurse. Forward
citation enumeration for Science 10.1126/science.1150082 retrieved all 311
Europe PMC targets over four 100-row pages: 252 pre-2020 year leads and 59 later
leads. Twenty targets are matched to existing registry records using explicit PMID/DOI
pairs from retained primary XML; 291 remain unreconciled. This identity pass adds
no relevance decisions. See `research/reconcile_forward_local.py`. The 1,000-row request failed
HTTP 500; the paced 100-row retry succeeded. `research/discover_forward.py`
resumes retained pages. Other forward seeds remain pending. The selected Rothemund lab
bibliography was inspected; seven DOI links include one unmatched lead, and its
linked full bibliography remains pending. Other author queues are not exhausted.
Crossref single-term `origami` and `scaffolded` queries for 2006–2019 were fully
cursor-paginated: 3,262 and 415 hits; 2,725 new normalized DOI records retained
without automatic relevance decisions. These two query routes reached short final
pages. Historical multiword queries returned over 200,000 results in live probes;
their generic tails remain unexhausted. Other terminology and provider coverage
remain open. See DISC0002 and the capability-check run. No field-wide closure or
saturation round has been claimed. From B0003 onward, five low-signal and five broad records rotate across year and
publisher buckets alongside 15 prioritized ACS records. This is queue balancing,
not exhaustive review of any year or publisher.

Closure remains distant: not every collected record has a disposition, source
checks remain open, conference/author/forward routes are unfinished, and two complete
zero-yield passes have not occurred. Continue meaningful unblocked work.
'''
    L.atomic(L.ROOT/'RESEARCH_CHECKPOINT.md',out)
    L.atomic(L.HERE/'validation.json',json.dumps({'date':L.DATE,'validation':validation,'counts':c,'local_acs_documents_present':present,'local_acs_metadata_present':metadata},indent=2)+'\n')
    print(json.dumps(validation))


if __name__=='__main__':main()
