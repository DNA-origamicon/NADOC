
# MD Integration Plan — topic guide

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

This is the original MD integration proposal, retained for rationale. Current job state and remaining work live in [MD jobs](project_md_job_system.md), [simulation lifecycle](project_simulation_runtime.md), and [simulation tabs](project_simulate_panel_overhaul.md). Its original “next steps” are not a current execution queue.

<a id="md-integration-plan"></a>
- [MD Integration Plan](details/md_integration_plan/01-md-integration-plan_archive.md#md-integration-plan)

<a id="current-building-blocks"></a>
- [Current Building Blocks](details/md_integration_plan/01-md-integration-plan_archive.md#current-building-blocks)

<a id="export-and-setup"></a>
- [Export and setup](details/md_integration_plan/01-md-integration-plan_archive.md#export-and-setup)

<a id="monitoring-and-analysis"></a>
- [Monitoring and analysis](details/md_integration_plan/01-md-integration-plan_archive.md#monitoring-and-analysis)

<a id="visualization-already-present"></a>
- [Visualization already present](details/md_integration_plan/01-md-integration-plan_archive.md#visualization-already-present)

<a id="key-gaps"></a>
- [Key Gaps](details/md_integration_plan/01-md-integration-plan_archive.md#key-gaps)

<a id="1-no-first-class-md-job-model"></a>
- [1. No first-class MD job model](details/md_integration_plan/01-md-integration-plan_archive.md#1-no-first-class-md-job-model)

<a id="2-namd-is-not-yet-integrated-into-the-apiruntime-loop"></a>
- [2. NAMD is not yet integrated into the API/runtime loop](details/md_integration_plan/01-md-integration-plan_archive.md#2-namd-is-not-yet-integrated-into-the-apiruntime-loop)

<a id="3-health-checks-are-experiment-scripts-not-product-services"></a>
- [3. Health checks are experiment scripts, not product services](details/md_integration_plan/01-md-integration-plan_archive.md#3-health-checks-are-experiment-scripts-not-product-services)

<a id="4-file-type-and-wrapping-details-leak-into-the-ui"></a>
- [4. File type and wrapping details leak into the UI](details/md_integration_plan/02-4-file-type-and-wrapping-details-leak-into-the-ui_archive.md#4-file-type-and-wrapping-details-leak-into-the-ui)

<a id="5-no-unified-protocol-presets"></a>
- [5. No unified protocol presets](details/md_integration_plan/02-4-file-type-and-wrapping-details-leak-into-the-ui_archive.md#5-no-unified-protocol-presets)

<a id="6-ui-needs-md-progress-as-a-first-class-panel"></a>
- [6. UI needs MD progress as a first-class panel](details/md_integration_plan/02-4-file-type-and-wrapping-details-leak-into-the-ui_archive.md#6-ui-needs-md-progress-as-a-first-class-panel)

<a id="proposed-architecture"></a>
- [Proposed Architecture](details/md_integration_plan/02-4-file-type-and-wrapping-details-leak-into-the-ui_archive.md#proposed-architecture)

<a id="backend-modules"></a>
- [Backend modules](details/md_integration_plan/02-4-file-type-and-wrapping-details-leak-into-the-ui_archive.md#backend-modules)

<a id="api"></a>
- [API](details/md_integration_plan/02-4-file-type-and-wrapping-details-leak-into-the-ui_archive.md#api)

<a id="job-directory-layout"></a>
- [Job directory layout](details/md_integration_plan/03-job-directory-layout_archive.md#job-directory-layout)

<a id="implementation-plan"></a>
- [Implementation Plan](details/md_integration_plan/03-job-directory-layout_archive.md#implementation-plan)

<a id="milestone-1-productize-current-namd-health-runner"></a>
- [Milestone 1: Productize Current NAMD Health Runner](details/md_integration_plan/03-job-directory-layout_archive.md#milestone-1-productize-current-namd-health-runner)

<a id="milestone-2-md-job-ui"></a>
- [Milestone 2: MD Job UI](details/md_integration_plan/03-job-directory-layout_archive.md#milestone-2-md-job-ui)

<a id="milestone-3-native-latest-frame-visualization"></a>
- [Milestone 3: Native Latest-Frame Visualization](details/md_integration_plan/03-job-directory-layout_archive.md#milestone-3-native-latest-frame-visualization)

<a id="milestone-4-results-and-design-feedback"></a>
- [Milestone 4: Results and Design Feedback](details/md_integration_plan/03-job-directory-layout_archive.md#milestone-4-results-and-design-feedback)

<a id="milestone-5-advanced-protocol-library"></a>
- [Milestone 5: Advanced Protocol Library](details/md_integration_plan/03-job-directory-layout_archive.md#milestone-5-advanced-protocol-library)

<a id="immediate-next-steps"></a>
- [Immediate Next Steps](details/md_integration_plan/03-job-directory-layout_archive.md#immediate-next-steps)

<a id="design-principle"></a>
- [Design Principle](details/md_integration_plan/04-design-principle_archive.md#design-principle)
