# NADOC illustrated user guides

Step-by-step guides captured from NADOC's real interface. Read them directly in
your Git host's Markdown viewer: screenshots and examples are stored beside each
guide, with no website build, external image host or experiment folder required.

| Start here | What it covers |
|---|---|
| [Feature Log](feature-log/README.md) · [Browser version](feature-log.html) | 3×6 body plus 2×6 continuation, Bend and routing; history controls, recipe verification and loadouts; individual end resizes within a Fine Routing group in Origami Editor |
| [Extrude](extrude/README.md) · [Browser version](extrude.html) | 3×6 square-lattice walkthrough: length, 2×3 end continuation and a separate cluster |
| [Bend](bend/README.md) · [Browser version](bend.html) | Two 256 bp clusters, Tools → Bend on one cluster, and loops/skips in 3D and the cadnano-style editor |
| [Twist](twist/README.md) · [Browser version](twist.html) | Two 256 bp clusters, RH/LH twists on one cluster, and loops/skips in 3D and the cadnano-style editor |
| [Feature guide ledger](LEDGER.md) | All 60 main features from [the feature inventory](../../FEATURES.md), guide coverage and capture dates |
| [UX findings](UX_LEDGER.md) | Friction discovered while producing guides, including workarounds that still need fixes |
| [Guide maintenance](MAINTENANCE.md) | Storage rules, source checks, regeneration and adding guides |

Extrude is the first illustrated guide and the specimen for visual-style review.
The standard guide model is a **3-row × 6-column square lattice (18 helices)**
unless a lesson explicitly specifies otherwise. Length is lesson-specific;
Extrude uses 64 bp; Bend and Twist use 256 bp. **All 3D guide images use Full representation**, except
lessons specifically demonstrating representation changes. Numbered arrows point
to controls and canvas targets.

The catalog records the demonstrated scope; desktop and headset interactions
are distinct. Existing technical references elsewhere in `docs/` remain useful.
Batch generation and scheduling are deferred until the guide style is approved.
Coverage remains **partial**: square-lattice deformed continuation has an
implementation gap ([GUIDE-UX-004](UX_LEDGER.md)). Deformed continuation is outside the Extrude lesson. Bend has its own guide;
Twist has a separate guide; advanced deformation options remain future coverage.

From the repository root, check whether guides need attention:

```sh
python3 -m scripts.check_feature_guides
```

The check compares captured source hashes to the current checkout, including
local edits. **Current** means that the declared dependencies match; it is not
a claim of complete feature coverage or usability approval.

Open `extrude.html` directly in a browser for the illustrated HTML version. For
offline use, download the whole `docs/guides/` directory so images and links remain
together. Git hosts may display HTML source; use their download/raw-file option
and open the downloaded copy locally.

## Organization

```text
docs/guides/
  README.md              Reader entry point
  LEDGER.md              Generated feature coverage and dates
  catalog.json           Feature inventory, scopes and dependency rules
  UX_LEDGER.md           Human-maintained usability findings
  MAINTENANCE.md          Contributor workflow
  extrude/
    README.md            Illustrated instructions
    01.png … NN.png       Annotated screenshots
    example.nadoc        Guard-published, replay-verified example
    steps.json           Captions and mouse targets
    verification.json    Construction verification
    manifest.json        Capture dates, source and asset hashes
```

Keep only the latest published capture per guide in this tree; Git preserves
previous revisions. Temporary captures, browser traces and failed runs belong
in isolated scratch. Do not add timestamped experiment directories here.
