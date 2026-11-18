The average-sequence parameter file is copied unchanged from oxDNA revision
8028cf33b3cba12992b771156085fa54879f50cd (GPL-3.0; upstream LICENSE).
Source: https://github.com/lorenzo-rovigatti/oxDNA/blob/8028cf33b3cba12992b771156085fa54879f50cd/oxDNA2_average_sequence_parameters.txt

Using this file with use_average_seq=false reproduces equal base strengths for
the average DNA2 model on CPU and CUDA. It does not introduce base-dependent
strengths. DNANM already initializes the DNA2 average tables correctly.

The sequence-dependent parameter file is also copied unchanged from that revision:
https://github.com/lorenzo-rovigatti/oxDNA/blob/8028cf33b3cba12992b771156085fa54879f50cd/oxDNA2_sequence_dependent_parameters.txt
New thermal runs select this file, with sequence_dependent=true in the persisted
stage specification. Existing specs default to false and retain average strengths.
