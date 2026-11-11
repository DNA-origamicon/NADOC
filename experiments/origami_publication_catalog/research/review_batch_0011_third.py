"""Named-source review; lattice evidence is distinct from full source eligibility."""
import json
import ledger as L
from review_batch_0001 import evidence

NOTES=[
('10.1021/acsnano.7b05631','9661441-nn7b05631_si_001.pdf','9661441',
 'SI pp2,22–25; SI14 structure design, FigS12 caption, SI15 modified strands and references',
 'SI14 explicitly describes a three-layer square-lattice block folded from M13mp18 p8064. Dyes are placed on the block surface; G2 is shifted half a helical turn because the ideal aligned position would lie on scaffold rather than a staple. R/G1/G3/B have 5-prime terminal fluorophores plus an extra thymine; G2 has internal Cy3 attached to thymine. TableS11 lists these five modified strands. Dye-arrangement variants are not automatically new cores. FigS12 is captioned as caDNAno design and sequences, but its graphical routing/sequence content has not been visually audited and is absent from plain text extraction. Explicit square-lattice evidence does not certify a complete recoverable source set.',
 ['Inspect high-resolution FigS12 and acquire native design/full sequences if available; compare all dye placements and replacement strands.', 'Acquire main Methods and establish exact core parent and all arrangement mappings; complete source eligibility remains unresolved.']),
('10.1021/acsnano.7b06470','9678106-nn7b06470_si_001.pdf','9678106',
 'SI pp1–5 sections SI/SII and FigsS1–S7; p8 FigS10; p10 FigS12; references pp4–5',
 'Simulation study reuses jointed origami mechanisms: hinges, sliders, crank-slider and Bennett linkage. Ref5 identifies Marras/Zhou/Su/Castro Programmable Motion of DNA Origami Mechanisms, PNAS2015,112,713–718 as an experimental parent lead. Hinge2 is studied with and without staples bound to single-stranded connectors; this is a composition variant, not merely a different sampled conformation. Slider results likewise depend on connector-covering staples. Extreme configurations/probability distributions do not define separate cores. Angle analysis uses middle60percent of hinge arms to avoid end splay. CanDo overlap examples are model diagnostics and not physical constructs. Exact source routing, staple-removal identities, lattice and parent-to-model transformations remain unchecked; movie attachments are deferred in acquisition records.',
 ['Read main Methods and retrieve original experimental/CAD sources; map exact retained/removed connector staples for every modeled variant.', 'Reconcile parent publication identity and source transformations; inspect deferred movies only as supporting evidence, not source certification.']),
('10.1021/jacs.7b10862','9711697-ja7b10862_si_001.pdf','9711697',
 'SI pp1–5 scaffold preparation, sequence tables and FigS2 caption; p9 references',
 'SIp1 explicitly specifies honeycomb lattice for a nominal100nm six-helix bundle. BsrDI restriction of M13mp18 yields a1715nt scaffold without the ligation used in the cited Said2013 approach. SIp2 provides scaffold with cut/recognition annotations and two restriction-complement oligos; these are preparation reagents, not core staples. SIp3 lists42bare_6HB staples. SIp4 lists seven periphery strands replacing six bare staples(4,8,25,29,40,41), so this is not a one-for-one substitution table. FigS2 distinguishes thiol-anchor complementary overhang, three fluorescent labels with two-adenine spacers, and antigen-DNA-binding overhangs. The struck-out scaffold prefix, exact split-staple mapping, native routing and complete modified composition need verification before source certification.',
 ['Visually inspect struck-out scaffold prefix and underlined restriction/overhang annotations; verify1715nt endpoints and all42core rows.', 'Reconcile seven-periphery/six-core substitution including split strands with routing, electrode anchor and main Methods; confirm source/lattice eligibility independently.'])]

def main():
    pubs={p['registry_key']:p for p in L.read('publication_reviews')}
    for key,name,fid,locator,note,questions in NOTES:
        p=pubs[key];ev=evidence(L.ROOT/'assets/sources/acs-expansion-20261104'/name,'https://ndownloader.figshare.com/files/'+fid,locator)
        p.update(review_stage='design_sources_reviewed',relevance='design_bearing',publication_type=['journal_article'],design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',evidence=[ev],rationale=note,unresolved_questions=questions,reviewer='Codex named supplement sections and sequence-table inspection',run_id='B0011',date=L.DATE)
        L.upsert('publication_reviews',p,'Record explicit lattice and variant evidence while retaining source-completeness checks')
    b=next(b for b in L.read('batches') if b['batch_id']=='B0011')
    action='Reviewed photonic wire, joint-motion simulation and electrical nanolever SI:10/25first passes saved; no source certifications.'
    if action not in b['completed_actions']:b['completed_actions'].append(action)
    b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Review6remaining ACS and9rotating B0011records','Follow source parents and unresolved complete-source checks','Continue FNANO2012, abstracts, forward citations and author histories'])
    L.upsert('batches',b,'Checkpoint10/25 first passes; keep batch active')
    L.atomic(L.HERE/'batch_0011_third_audit.json',json.dumps(dict(batch_id='B0011',first_pass_count=10,input_count=25,complete_source_certifications=0,counts=L.counts(),validation=L.validate()),indent=2)+'\n')
    print(L.validate())
if __name__=='__main__':main()
