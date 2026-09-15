# Faster future NAMD package submissions

Identical combined positional-restraint files now share a SHA-256-named file. Composition is cached by reference and scale during preparation, avoiding repeated million-atom PDB parsing and formatting. Different coefficients retain different files. Stage-specific `consref` references remain separate, including the settling reference rewritten after minimization. Existing running packages were not modified.

Alpine uploads group eight or more small package files (at most 1 MiB each) into one temporary tar archive, unpacked before submission. Large inputs remain streamed individually. The archive preserves relative paths and executable modes, applies the existing CPU-target config transformation, and is removed after extraction. Extraction errors abort submission. Archive creation runs outside the API event loop; progress counts original files and actual transfer bytes. Runtime helper scripts staged separately after the package are not included in the transfer counts below.

An isolated rebuild using job `75af92defc27` verified all 24 original configuration files retain the same reference paths and byte-identical combined restraint contents:

| Measurement | Before | After |
| --- | ---: | ---: |
| Combined restraint PDBs | 24 | 2 |
| Package size | 4,136,295,736 bytes | 1,256,783,201 bytes |
| Package upload operations | 76 | 12 |

43 small files are carried in one 1,761,280-byte setup archive. Restraint composition in this isolated rebuild took 7.22 seconds. These measurements establish reduced package size and transfer count; they do not predict a precise Alpine submission time.

Validation: 113 tests passed across draft preparation, upload-bundle round trips (GPU and CPU), failure handling and the MD executor. The bundle tests execute real local tar extraction and compare every resulting file. Reproduction and measured results: `experiments/md_upload_dedup_20260915/verify.py` and `results.json`.
