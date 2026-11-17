# From cadnano to a local oxDNA production simulation

[All guides](../README.md) · [Coverage ledger](../LEDGER.md)

Import a NADOC-exported 84 bp honeycomb 6HB, assign sequences, relax it with local oxDNA, and start a production simulation from the relaxed configuration. This walkthrough uses the default GPU stage lengths and records real native simulation output.

Numbered arrows point to
mouse targets while keeping their labels visible. Dashed boxes show drag extents.
Unmarked images show settings or results. This is an editorial draft for style review.

[Download the example](example.nadoc) · [Construction verification](verification.json) ·
[Capture and source metadata](manifest.json) · [UX findings](../UX_LEDGER.md)

## Scope

- Import a cadnano part and assign scaffold and staple sequences
- Configure and complete local staged oxDNA relaxation
- Create and launch local production from the completed relaxation

## Example files

Keep this family together to preserve the complete upstream construction and conversion:

- [cadnano input](6hb84-cadnano.json)
- [Original NADOC source with its construction history](source.nadoc)
- [Imported and sequenced NADOC example](example.nadoc)
- [Exact export compatibility review](export-review.json)
- [Local simulation verification](simulation-verification.json)

## Contents

- [Import the cadnano design](#import-the-cadnano-design)
- [Assign sequences](#assign-sequences)
- [Configure a local relaxation](#configure-a-local-relaxation)
- [Start production from the relaxed structure](#start-production-from-the-relaxed-structure)

## Import the cadnano design

Start with NADOC and a working local oxDNA installation. This example uses 6hb84-cadnano.json, exported from a NADOC honeycomb 6HB routed to 84 bp from a 63 bp extrusion using Seamed Autoscaffold and Standard Full Autostaple. Keep source.nadoc with the example family to retain the upstream construction history. The captured machine has a CUDA-capable NVIDIA GPU. Local CPU MD is available through the MD backend setting when needed.

### Step 1

Open the Import menu.

![Step 1: Open the Import menu.](01.png)

### Step 2

Choose caDNAno and select the supplied 6hb84-cadnano.json file.

![Step 2: Choose caDNAno and select the supplied 6hb84-cadnano.json file.](02.png)

### Step 3

Leave Relax after import (experimental) unchecked and click Import design. The oxDNA relaxation is configured later.

![Step 3: Leave Relax after import (experimental) unchecked and click Import design. The oxDNA relaxation is configured later.](03.png)

### Step 4

Save the imported part with a descriptive name. The capture uses a temporary example name.

![Step 4: Save the imported part with a descriptive name. The capture uses a temporary example name.](04.png)

### Step 5

Press F to fit and right-drag to orbit. Inspect the imported scaffold, staples, crossovers and both ends in Full representation.

![Step 5: Press F to fit and right-drag to orbit. Inspect the imported scaffold, staples, crossovers and both ends in Full representation.](05.png)

### Step 6

Orbit to the reverse side to inspect the back helices and terminal connections. Import preserves the cadnano routing; resolve any routing problems before simulation.

![Step 6: Orbit to the reverse side to inspect the back helices and terminal connections. Import preserves the cadnano routing; resolve any routing problems before simulation.](06.png)

## Assign sequences

cadnano supplies the routing. Assign the intended scaffold sequence and complementary staples before creating the simulation. For this short demonstration, assign the beginning of M13mp18 to the short routed scaffold; the remaining reference bases are unused. For an experimental design, use its actual scaffold sequence and register.

### Step 7

Choose Tools → Sequencing → Assign Scaffold Sequence.

![Step 7: Choose Tools → Sequencing → Assign Scaffold Sequence.](07.png)

### Step 8

Review the scaffold length and M13mp18 selection, then click Apply.

![Step 8: Review the scaffold length and M13mp18 selection, then click Apply.](08.png)

### Step 9

Choose Tools → Sequencing → Assign Staple Sequences to complement the routed staples.

![Step 9: Choose Tools → Sequencing → Assign Staple Sequences to complement the routed staples.](09.png)

## Configure a local relaxation

Open Simulations and select oxDNA. A relaxation job contains CPU Monte Carlo minimization, molecular-dynamics relaxation, then equilibration. The example retains the default stage lengths and health gates.

### Step 10

Open the Simulations sidebar.

![Step 10: Open the Simulations sidebar.](10.png)

### Step 11

Select oxDNA as the simulation engine.

![Step 11: Select oxDNA as the simulation engine.](11.png)

### Step 12

Click + New job to configure the relaxation.

![Step 12: Click + New job to configure the relaxation.](12.png)

### Step 13

In Where it runs, keep Local selected. This uses the oxDNA installation on this computer.

![Step 13: In Where it runs, keep Local selected. This uses the oxDNA installation on this computer.](13.png)

### Step 14

Click Next to review Parameters & options.

![Step 14: Click Next to review Parameters & options.](14.png)

### Step 15

Review oxDNA2, Automatic engine selection, CUDA device 0 and 0.5 M salt. Defaults are 1,000 MC steps, 1,000,000 MD relaxation steps and 100,000 equilibration steps, with a 0.5 base-pair retention gate and up to three escalating MD retries. Set conditions to match your experiment.

![Step 15: Review oxDNA2, Automatic engine selection, CUDA device 0 and 0.5 M salt. Defaults are 1,000 MC steps, 1,000,000 MD relaxation steps and 100,000 equilibration steps, with a 0.5 base-pair retention gate and up to three escalating MD retries. Set conditions to match your experiment.](15.png)

### Step 16

Scroll down to review equilibration, the base-pair retention gate and retry allowance. Keep the health gates enabled.

![Step 16: Scroll down to review equilibration, the base-pair retention gate and retry allowance. Keep the health gates enabled.](16.png)

### Step 17

Click Next to inspect Full configuration, including the stage temperatures, thermostats, force caps and output intervals.

![Step 17: Click Next to inspect Full configuration, including the stage temperatures, thermostats, force caps and output intervals.](17.png)

### Step 18

Review the generated inputs before creating the job. The default temperature is 296 K. The recorded sequence parameter file uses average interaction strengths; assigning sequences alone does not select sequence-dependent thermodynamics.

![Step 18: Review the generated inputs before creating the job. The default temperature is 296 K. The recorded sequence parameter file uses average interaction strengths; assigning sequences alone does not select sequence-dependent thermodynamics.](18.png)

### Step 19

Click Create job to prepare the local relaxation inputs.

![Step 19: Click Create job to prepare the local relaxation inputs.](19.png)

### Step 20

Click Run to start the local relaxation. NADOC runs the stages in order and checks their health.

![Step 20: Click Run to start the local relaxation. NADOC runs the stages in order and checks their health.](20.png)

## Start production from the relaxed structure

Continue after the relaxation completes successfully. Review stage health and the relaxed structure before committing to longer sampling. A completed relaxation makes a production starting configuration available; sampling adequacy still depends on the scientific question.

### Step 21

Wait for production ready. If relaxation fails, inspect its reported health or engine error and resolve the cause before continuing.

![Step 21: Wait for production ready. If relaxation fails, inspect its reported health or engine error and resolve the cause before continuing.](21.png)

### Step 22

Select OxDNA display to inspect the relaxed physical configuration.

![Step 22: Select OxDNA display to inspect the relaxed physical configuration.](22.png)

### Step 23

Inspect the relaxed bundle and its terminal connections. Right-drag to orbit; physical display leaves the authored topology intact.

![Step 23: Inspect the relaxed bundle and its terminal connections. Right-drag to orbit; physical display leaves the authored topology intact.](23.png)

### Step 24

Inspect the reverse side for displaced ends, separated strands or discontinuities before starting production.

![Step 24: Inspect the reverse side for displaced ends, separated strands or discontinuities before starting production.](24.png)

### Step 25

With the completed relaxation selected, click + New job. The wizard opens in Production mode.

![Step 25: With the completed relaxation selected, click + New job. The wizard opens in Production mode.](25.png)

### Step 26

Check Continue from identifies the completed relaxation. Review the default 5,000,000 production steps and 10,000 steps per saved frame. Production inherits the local backend and salt from its parent; review the temperature, time step and thermostat for the intended sampling.

![Step 26: Check Continue from identifies the completed relaxation. Review the default 5,000,000 production steps and 10,000 steps per saved frame. Production inherits the local backend and salt from its parent; review the temperature, time step and thermostat for the intended sampling.](26.png)

### Step 27

Click Next to review the production Summary.

![Step 27: Click Next to review the production Summary.](27.png)

### Step 28

Click Create job. NADOC creates and selects a separate production job using the parent’s final configuration.

![Step 28: Click Create job. NADOC creates and selects a separate production job using the parent’s final configuration.](28.png)

### Step 29

Click Run to start production locally.

![Step 29: Click Run to start production locally.](29.png)

### Step 30

Production is running on this computer. Follow stage progress and saved trajectory frames in the oxDNA panel. Extend sampling and assess equilibration and convergence for your observable before interpreting results.

![Step 30: Production is running on this computer. Follow stage progress and saved trajectory frames in the oxDNA panel. Extend sampling and assess equilibration and convergence for your observable before interpreting results.](30.png)
