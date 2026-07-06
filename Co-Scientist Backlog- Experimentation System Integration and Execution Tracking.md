# Co\-Scientist Backlog: Experimentation System Integration and Execution Tracking

Below is an **additive co-scientist backlog** for the PRD changes. It assumes the existing co-scientist backlog remains intact, especially the current **Experiment Card and Spec Generation**, **Human Approval and Execution Handoff**, and **Validation Result Ingestion and Score Updates** epics. The existing backlog already defines those epics and uses stable semantic epic IDs, so these additions extend that structure rather than replacing it.

The main product shift is: the co-scientist should **submit approved experiments to the Experimentation System**, track execution, and ingest ResultBundles; it should **not directly execute experiments**. This refines the original PRD flow where the co-scientist generates Experiment Cards, sends approved experiments to the experimentation environment, ingests validation results, updates scores, and synthesizes device concepts.

---

# Co-Scientist Backlog Additions

## Epic summary

| Epic ID | Epic name | Goal | Priority |
| --- | --- | --- | --- |
| **CS-EPIC-EXPERIMENT** | Experiment Card Execution Handoff Schema | Extend Experiment Cards with execution handoff fields, batch expansion, and separate lifecycle states. | P0 |
| **CS-EPIC-APPROVAL** | Human Approval and RunRequest Submission | Replace direct execution handoff with approved RunRequest submission to the Experimentation System. | P0 |
| **CS-EPIC-EXECUTION** | Execution Batch and RunRequest Tracking | Add co-scientist-side references for ExecutionBatches, RunRequests, RunAttempts, and execution status. | P0 |
| **CS-EPIC-VALIDATION** | ResultBundle Ingestion and Validation Aggregation | Ingest independent runner results and aggregate outcomes across single or multi-run experiments. | P0 |
| **CS-EPIC-SCORE** | Execution-Evidence Score Updates | Update Approach Card and Experiment Card scores using completed, failed, partial, or mixed validation evidence. | P0 |
| **CS-EPIC-APPROACH** | Approach Card Execution Evidence Links | Link Approach Cards to Experiment Cards, RunRequests, ResultBundles, and validation evidence. | P0/P1 |
| **CS-EPIC-DEVICE** | Device Concept Updates from Execution Evidence | Update Device Concept Cards from validated or failed experiments. | P1 |
| **CS-EPIC-ROADMAP** | Roadmap Updates from Execution Outcomes | Use completed, failed, or inconclusive runs to update next-best experiment planning. | P1 |
| **CS-EPIC-GOVERNANCE** | Execution Boundary and Agent Governance | Ensure the co-scientist hands off experiments but does not directly execute them. | P0 |
| **CS-EPIC-UI** | Co-Scientist Execution Status UI | Show Experiment Card approval state separately from execution state, batch status, and validation results. | P0/P1 |
| **CS-EPIC-EVALUATION** | Execution-Handoff Metrics and Quality | Measure handoff success, result ingestion quality, duplicate score updates, and traceability. | P0/P1 |

---

# CS-EPIC-EXPERIMENT — Experiment Card Execution Handoff Schema

## Epic goal

Extend the existing Experiment Card model so that approved cards can become one or more RunRequests in the Experimentation System without implying that the co-scientist itself executes the experiment.

## User stories

| Story ID | Priority | User story | Acceptance criteria |
| --- | --- | --- | --- |
| **CS-EXP-008** | P0 | As a research engineer, I want Experiment Cards to include execution handoff fields so that the co-scientist can submit approved work to the Experimentation System. | Experiment Card includes `execution_handoff`, `handoff_status`, `submission_mode`, `experiment_control_plane`, `required_capabilities`, `runner_pool_preference`, `run_request_ids`, `execution_batch_id`, `result_bundle_ids`, and `latest_execution_status`. |
| **CS-EXP-009** | P0 | As a researcher, I want an Experiment Card to support single-run or batch execution so that sweeps, ablations, and multi-seed experiments can be represented. | Experiment Card can specify `single_run`, `run_request_batch`, or `sweep_batch`. Batch mode stores expansion parameters and expected RunRequest count. |
| **CS-EXP-010** | P0 | As a researcher, I want Experiment Card lifecycle state separated from execution lifecycle state so that “approved” is not confused with “executed.” | Experiment Card lifecycle supports `generated`, `needs_review`, `approved`, `rejected`, `duplicated`, `superseded`, `archived`. Execution status separately supports `not_submitted`, `submitted`, `queued`, `running`, `partially_completed`, `completed`, `failed`, `blocked`, `mixed_outcome`. |
| **CS-EXP-011** | P0 | As a system, I want generated Experiment Cards to include required runtime and capability hints so that handoff to the Experimentation System can be validated. | Experiment Card contains runtime preference, alternatives, required capabilities, estimated runtime/cost, artifact expectations, and validation criteria. |
| **CS-EXP-012** | P1 | As a researcher, I want to preview expanded RunRequests before submission so that I understand how many runs a sweep or robustness test will create. | UI/API can show expanded runs, variables, estimated cost, estimated runtime, approval implications, and required runner capabilities before submission. |

---

# CS-EPIC-APPROVAL — Human Approval and RunRequest Submission

## Epic goal

Modify approval handoff so that approved Experiment Cards create RunRequests in the Experimentation System rather than triggering direct execution inside the co-scientist.

## User stories

| Story ID | Priority | User story | Acceptance criteria |
| --- | --- | --- | --- |
| **CS-APPROVAL-007** | P0 | As a researcher, I want an approved Experiment Card to create one or more RunRequests so that execution is handled by independent experiment runners. | Approval flow calls the Experimentation System RunRequest API. Returned RunRequest IDs are stored on the Experiment Card or ExecutionBatchReference. |
| **CS-APPROVAL-008** | P0 | As an administrator, I want approval policy to be included in each RunRequest so that GPU, Treble, credentialed, costly, or shared-compute jobs remain governed. | RunRequest submission includes approval ID, approver, timestamp, cost class, credentialed flag, resource policy, and retry policy. |
| **CS-APPROVAL-009** | P0 | As a researcher, I want batch approval semantics so that I can approve a whole sweep or require review for each generated run. | Approval mode supports `approve_batch`, `approve_each_run`, and `approval_required_above_threshold`. Policy is stored with the ExecutionBatchReference. |
| **CS-APPROVAL-010** | P1 | As a researcher, I want failed handoffs to be preserved so that I can retry submission without losing approval context. | Failed handoff stores error, timestamp, payload summary, approval record, retryability, and no duplicate RunRequest is created on retry. |
| **CS-APPROVAL-011** | P1 | As a researcher, I want to request cancellation or resubmission from the co-scientist UI so that I can manage obsolete or failed experiments. | Co-scientist sends cancellation or resubmission request to the Experimentation System and records request status. Actual execution control remains owned by the Experimentation System. |

---

# CS-EPIC-EXECUTION — Execution Batch and RunRequest Tracking

## Epic goal

Add co-scientist-side tracking objects for execution batches, RunRequests, RunAttempts, and status summaries without taking ownership of execution.

## User stories

| Story ID | Priority | User story | Acceptance criteria |
| --- | --- | --- | --- |
| **CS-EXEC-001** | P0 | As a researcher, I want the co-scientist to create an ExecutionBatchReference when an Experiment Card submits multiple runs so that batch execution is traceable. | ExecutionBatchReference includes ID, Experiment Card ID, RunRequest IDs, aggregate status, submission timestamp, submitter, policy, and status counts. |
| **CS-EXEC-002** | P0 | As a system, I want to store RunRequestReferences so that the co-scientist can track jobs owned by the Experimentation System. | Each RunRequestReference stores RunRequest ID, Experiment Card ID, status, control-plane URI, submitted timestamp, latest update timestamp, and source correlation ID. |
| **CS-EXEC-003** | P0 | As a researcher, I want execution status updates so that I can see whether an experiment is queued, running, completed, failed, canceled, blocked, or timed out. | Co-scientist can receive updates through polling, webhook, or event stream. Status updates are linked to the correct Experiment Card and RunRequestReference. |
| **CS-EXEC-004** | P0 | As a researcher, I want aggregate execution status for multi-run experiments so that I can interpret partial results. | ExecutionBatchReference reports total, queued, running, completed, failed, canceled, blocked, and timed-out counts. |
| **CS-EXEC-005** | P0 | As a system, I want RunAttemptReferences when available so that failed attempts and retries are visible without owning runner internals. | RunAttemptReference stores attempt ID, RunRequest ID, runner ID if permitted, attempt status, timestamps, and failure summary. |
| **CS-EXEC-006** | P1 | As a researcher, I want partial results from long-running batches so that I can inspect early outcomes before all runs complete. | Batch status supports partial ResultBundle ingestion and marks aggregation as partial until required runs complete. |
| **CS-EXEC-007** | P1 | As a system, I want execution correlation IDs so that events from Experimentation System can be reconciled with co-scientist objects. | Each handoff includes correlation ID linking goal, Approach Card, Hypothesis Card, Experiment Card, ExecutionBatch, RunRequest, and ResultBundle. |

---

# CS-EPIC-VALIDATION — ResultBundle Ingestion and Validation Aggregation

## Epic goal

Ingest structured ResultBundle summaries from the Experimentation System, link them back to co-scientist objects, and aggregate outcomes across runs.

## User stories

| Story ID | Priority | User story | Acceptance criteria |
| --- | --- | --- | --- |
| **CS-VALIDATION-007** | P0 | As a researcher, I want the co-scientist to ingest ResultBundle summaries so that independent runner results update the research workspace. | Ingestion accepts result bundle ID, RunRequest ID, run ID, attempt ID, Experiment Card ID, Approach Card IDs, metrics, validation status, artifacts, deviations, warnings, and provenance. |
| **CS-VALIDATION-008** | P0 | As a system, I want ResultBundle ingestion to be idempotent so that duplicate completion events do not duplicate score updates. | Ingestion key includes RunRequest ID, run ID, and attempt ID. Replayed events are ignored or acknowledged without duplicating ValidationResult or score deltas. |
| **CS-VALIDATION-009** | P0 | As a researcher, I want ResultBundles linked to Experiment Cards, Hypothesis Cards, and Approach Cards so that evidence accumulates in the correct places. | ResultBundleReference links to Experiment Card, Hypothesis Card where present, Approach Cards, ExecutionBatchReference, and validation summaries. |
| **CS-VALIDATION-010** | P0 | As a researcher, I want failed experiments to return useful diagnostic context so that failures still inform research decisions. | Failed ResultBundle or failure event includes failure type, status, logs or artifact references where permitted, partial artifacts, retryability, and deviation summary. |
| **CS-VALIDATION-011** | P0 | As a researcher, I want validation results aggregated across sweeps, seeds, and ablations so that a single Experiment Card can produce one interpretable conclusion. | ValidationAggregation computes aggregate status: `passed`, `failed`, `mixed`, `inconclusive`, `partial`, or `blocked`. Aggregation records metric summaries and missing runs. |
| **CS-VALIDATION-012** | P1 | As a researcher, I want partial validation summaries so that long-running sweeps can influence review without waiting for every run. | Partial summaries are clearly marked and do not trigger final score updates unless policy allows partial updates. |
| **CS-VALIDATION-013** | P1 | As a researcher, I want artifact manifest links in validation views so that I can inspect plots, logs, metrics, and reports. | ValidationResult stores artifact manifest URI, major artifact links, visibility status, and permission-aware access labels. |

---

# CS-EPIC-SCORE — Execution-Evidence Score Updates

## Epic goal

Update co-scientist rubric scoring so that completed, failed, partial, or mixed experiment evidence affects Approach Card confidence and ranking.

## User stories

| Story ID | Priority | User story | Acceptance criteria |
| --- | --- | --- | --- |
| **CS-SCORE-008** | P0 | As a researcher, I want score evidence types to include execution evidence so that validated results are distinguished from literature and inference. | Evidence types include `approved_experiment_design`, `queued_experiment`, `completed_experiment`, `failed_experiment`, `validation_passed`, `validation_failed`, and `mixed_validation`. |
| **CS-SCORE-009** | P0 | As a researcher, I want score updates from ResultBundles to include rationale so that I understand why a score changed. | Score update records previous score, new score, score delta, confidence delta, ResultBundle references, validation status, and rationale. |
| **CS-SCORE-010** | P0 | As a system, I want duplicate ResultBundle events to avoid duplicate score updates so that recommendations remain stable. | Score update processor checks ingestion ID and update ID before applying changes. Duplicate events produce no additional score delta. |
| **CS-SCORE-011** | P1 | As a researcher, I want mixed or partial validation outcomes to update confidence differently from clean pass/fail outcomes so that uncertainty is represented. | Scoring rules support `passed`, `failed`, `mixed`, `partial`, `blocked`, and `inconclusive` outcomes with configurable confidence effects. |
| **CS-SCORE-012** | P1 | As a product lead, I want score updates to be explainable across batch experiments so that large sweeps do not become black boxes. | Batch score update includes aggregate metrics, run count, failed count, missing count, variance where available, and reviewer notes. |

---

# CS-EPIC-APPROACH — Approach Card Execution Evidence Links

## Epic goal

Extend Approach Cards so they clearly show which claims are literature-supported, inferred, proposed for testing, or validated by independent runner results.

## User stories

| Story ID | Priority | User story | Acceptance criteria |
| --- | --- | --- | --- |
| **CS-APPROACH-008** | P0 | As a researcher, I want Approach Cards to include linked Experiment Cards, ExecutionBatches, RunRequests, and ResultBundles so that validation evidence is traceable. | Approach Card evidence block includes experiment cards, execution batches, RunRequests, ResultBundles, validation results, and reproduced experiments where applicable. |
| **CS-APPROACH-009** | P0 | As a researcher, I want Approach Cards to distinguish literature evidence from execution evidence so that I do not confuse paper claims with experimental validation. | Evidence groups include source literature, inferred synthesis, generated hypotheses, approved experiments, completed validation, failed validation, and inconclusive validation. |
| **CS-APPROACH-010** | P1 | As a researcher, I want Approach Card status to update from execution outcomes so that tested approaches move through the research lifecycle. | Approach status may transition to `experiment_proposed`, `submitted`, `tested`, `validated`, `refuted`, `inconclusive`, or `superseded` based on validation aggregation. |
| **CS-APPROACH-011** | P1 | As a researcher, I want failed or inconclusive experiments shown as useful evidence so that negative results still guide next work. | Approach Card displays failed/inconclusive ResultBundle links, failure reason, affected assumptions, and recommended follow-up actions. |

---

# CS-EPIC-DEVICE — Device Concept Updates from Execution Evidence

## Epic goal

Allow Device Concept Cards to reflect validated, failed, or inconclusive experimental evidence from independent runner results.

## User stories

| Story ID | Priority | User story | Acceptance criteria |
| --- | --- | --- | --- |
| **CS-DEVICE-007** | P1 | As a device engineer, I want Device Concept Cards to reference validation evidence so that device architecture confidence is grounded in experiments. | Device Concept Card includes supporting Experiment Cards, ExecutionBatches, ResultBundles, validation status, and score impact. |
| **CS-DEVICE-008** | P1 | As a device engineer, I want failed experiments to update unresolved risks so that device concepts remain realistic. | Failed or inconclusive validation can add or update risks such as latency risk, robustness risk, calibration burden, hardware feasibility, or low-frequency leakage. |
| **CS-DEVICE-009** | P1 | As a product lead, I want Device Concept confidence to update from validated experiments so that concepts improve as evidence accumulates. | Device Concept Card confidence changes record supporting ResultBundles, score deltas, affected approach scores, and rationale. |
| **CS-DEVICE-010** | P2 | As a device engineer, I want side-by-side device concept comparison to include execution evidence so that concepts can be ranked by tested performance. | Comparison view includes validation counts, passing metrics, failed assumptions, risks, and artifact links. |

---

# CS-EPIC-ROADMAP — Roadmap Updates from Execution Outcomes

## Epic goal

Use execution results to update roadmap items, next-best experiments, and uncertainty-reduction plans.

## User stories

| Story ID | Priority | User story | Acceptance criteria |
| --- | --- | --- | --- |
| **CS-ROADMAP-006** | P1 | As a research lead, I want completed ResultBundles to update roadmap items so that next experiments reflect what was learned. | Roadmap item status updates when linked validation passes, fails, or remains inconclusive. |
| **CS-ROADMAP-007** | P1 | As a researcher, I want failed experiments to create or update follow-up roadmap items so that failures become actionable. | Failure can generate roadmap recommendations such as rerun with changed assumptions, add baseline, inspect artifact, adjust metric, or test simpler scenario. |
| **CS-ROADMAP-008** | P1 | As a product lead, I want roadmap ranking to consider validation evidence so that experimentally supported paths move up or down appropriately. | Ranking uses validation status, information gain, cost, risk, device relevance, and unresolved gaps. |
| **CS-ROADMAP-009** | P2 | As a research lead, I want partial batch results to create provisional roadmap updates so that long experiments can inform planning early. | Partial updates are marked provisional and replaced or confirmed after final aggregation. |

---

# CS-EPIC-GOVERNANCE — Execution Boundary and Agent Governance

## Epic goal

Clarify that the co-scientist is a planning, approval, and interpretation layer, not the experiment execution system.

## User stories

| Story ID | Priority | User story | Acceptance criteria |
| --- | --- | --- | --- |
| **CS-GOV-007** | P0 | As an administrator, I want the Simulation Runner Agent renamed or scoped as a Simulation Handoff Agent so that responsibilities are clear. | Agent role is updated to submit RunRequests, monitor status, and ingest results. It does not start containers, run commands, allocate GPUs, or directly operate solvers. |
| **CS-GOV-008** | P0 | As an administrator, I want agents blocked from direct experiment execution so that compute and credentials remain governed by the Experimentation System. | Co-scientist agents cannot run shell commands or invoke runner adapters directly. Experiment execution occurs only through RunRequest submission. |
| **CS-GOV-009** | P0 | As an administrator, I want handoff and result ingestion audit logs so that every execution-related action is accountable. | Audit log records submitter, approval ID, Experiment Card ID, RunRequest IDs, policy, payload checksum, status updates, and ResultBundle ingestion. |
| **CS-GOV-010** | P0 | As an administrator, I want co-scientist execution references to respect experiment permissions so that private runs and artifacts are not exposed. | RunRequestReference, ResultBundleReference, artifact links, logs, and runner details are permission-checked before display. |
| **CS-GOV-011** | P1 | As an administrator, I want sensitive runner internals redacted from co-scientist views so that local paths, secrets, and infrastructure details do not leak. | UI and API redact secrets, local filesystem paths, credential names where restricted, raw runner logs where unauthorized, and operator-only diagnostics. |
| **CS-GOV-012** | P1 | As a researcher, I want all execution recommendations to retain evidence labels so that speculative plans are not mistaken for validated results. | Co-scientist labels experiment state as proposed, approved, queued, completed, failed, validation-passed, validation-failed, mixed, or inconclusive. |

---

# CS-EPIC-UI — Co-Scientist Execution Status UI

## Epic goal

Update the co-scientist UI so researchers can see approval state, execution state, batch progress, validation results, artifacts, and score changes separately.

## User stories

| Story ID | Priority | User story | Acceptance criteria |
| --- | --- | --- | --- |
| **CS-UI-008** | P0 | As a researcher, I want Experiment Cards to show approval state separately from execution state so that I know what has been approved versus what has actually run. | Experiment Card view displays lifecycle state and execution status as separate badges. |
| **CS-UI-009** | P0 | As a researcher, I want an ExecutionBatch panel so that I can track multi-run sweeps and ablations. | Panel shows RunRequest counts by queued, running, completed, failed, canceled, blocked, timed out, and mixed status. |
| **CS-UI-010** | P0 | As a researcher, I want ResultBundle summaries in the validation view so that I can inspect metrics, pass/fail status, artifacts, warnings, and deviations. | Validation view shows key metrics, checks, ResultBundleReference, artifact manifest, plots/logs if permitted, and score updates. |
| **CS-UI-011** | P1 | As a researcher, I want partial batch results clearly marked so that I do not mistake incomplete results for final conclusions. | Partial results show missing runs, completed runs, failed runs, and aggregation policy. Final score update status is explicit. |
| **CS-UI-012** | P1 | As a researcher, I want cancel or resubmit controls where allowed so that I can manage submitted experiments from the co-scientist workspace. | UI sends cancellation or resubmission requests to the Experimentation System. Co-scientist records request and displays resulting state. |
| **CS-UI-013** | P1 | As a product lead, I want to see which score changes came from validation results so that roadmap movement is explainable. | Score panel shows before/after score, ResultBundle links, rationale, confidence change, and affected roadmap items. |

---

# CS-EPIC-EVALUATION — Execution-Handoff Metrics and Quality

## Epic goal

Measure whether the co-scientist’s execution handoff, ResultBundle ingestion, validation linkage, and score updates are reliable.

## User stories

| Story ID | Priority | User story | Acceptance criteria |
| --- | --- | --- | --- |
| **CS-EVAL-007** | P0 | As a product owner, I want to measure RunRequest creation success so that experiment handoff reliability is visible. | Metric tracks approved Experiment Cards, attempted handoffs, successful RunRequests, failed handoffs, and retry success rate. |
| **CS-EVAL-008** | P0 | As a product owner, I want execution traceability metrics so that every result can be traced back to research intent. | Metric tracks percentage of RunRequests linked to Research Goal, Approach Card, Hypothesis Card where applicable, Experiment Card, and approval record. |
| **CS-EVAL-009** | P0 | As a product owner, I want duplicate score update rate tracked so that idempotent ingestion can be verified. | Metric tracks duplicate ResultBundle events, duplicate ingestion attempts, and duplicate score-update prevention. Target is zero duplicate score changes. |
| **CS-EVAL-010** | P1 | As a researcher, I want execution status freshness measured so that stale status displays are detectable. | Metric tracks event latency or polling lag from Experimentation System to co-scientist UI. |
| **CS-EVAL-011** | P1 | As a research lead, I want failed-run usefulness measured so that failures continue to provide research value. | Metric tracks percentage of failed runs with failure reason, diagnostic artifact, logs, retryability, and linked roadmap action. |
| **CS-EVAL-012** | P1 | As a product owner, I want batch aggregation quality metrics so that sweep handling can be improved. | Metric tracks batch completion rate, partial aggregation rate, mixed-outcome rate, and reviewer corrections to aggregation. |

---

# MVP story cut

## P0 stories to include in the co-scientist MVP update

| Epic | MVP stories |
| --- | --- |
| **CS-EPIC-EXPERIMENT** | CS-EXP-008, CS-EXP-009, CS-EXP-010, CS-EXP-011 |
| **CS-EPIC-APPROVAL** | CS-APPROVAL-007, CS-APPROVAL-008, CS-APPROVAL-009 |
| **CS-EPIC-EXECUTION** | CS-EXEC-001, CS-EXEC-002, CS-EXEC-003, CS-EXEC-004, CS-EXEC-005 |
| **CS-EPIC-VALIDATION** | CS-VALIDATION-007, CS-VALIDATION-008, CS-VALIDATION-009, CS-VALIDATION-010, CS-VALIDATION-011 |
| **CS-EPIC-SCORE** | CS-SCORE-008, CS-SCORE-009, CS-SCORE-010 |
| **CS-EPIC-APPROACH** | CS-APPROACH-008, CS-APPROACH-009 |
| **CS-EPIC-GOVERNANCE** | CS-GOV-007, CS-GOV-008, CS-GOV-009, CS-GOV-010 |
| **CS-EPIC-UI** | CS-UI-008, CS-UI-009, CS-UI-010 |
| **CS-EPIC-EVALUATION** | CS-EVAL-007, CS-EVAL-008, CS-EVAL-009 |

---

# Suggested sprint breakdown

## Sprint 1 — Schema and boundary update

Goal: make the co-scientist data model safe for independent execution handoff.

| Story ID | Priority |
| --- | --- |
| CS-EXP-008 | P0 |
| CS-EXP-010 | P0 |
| CS-GOV-007 | P0 |
| CS-GOV-008 | P0 |
| CS-GOV-009 | P0 |
| CS-GOV-010 | P0 |

**Sprint demo:** an Experiment Card shows execution handoff fields, separates approval state from execution state, and the Simulation Handoff Agent role is clearly scoped.

---

## Sprint 2 — RunRequest submission

Goal: submit approved Experiment Cards to the Experimentation System without direct execution.

| Story ID | Priority |
| --- | --- |
| CS-EXP-009 | P0 |
| CS-EXP-011 | P0 |
| CS-APPROVAL-007 | P0 |
| CS-APPROVAL-008 | P0 |
| CS-APPROVAL-009 | P0 |
| CS-EXEC-001 | P0 |
| CS-EXEC-002 | P0 |

**Sprint demo:** approve an Experiment Card, submit one or more RunRequests, and store ExecutionBatch and RunRequest references.

---

## Sprint 3 — Execution status tracking

Goal: track queued, running, completed, failed, and partial execution states.

| Story ID | Priority |
| --- | --- |
| CS-EXEC-003 | P0 |
| CS-EXEC-004 | P0 |
| CS-EXEC-005 | P0 |
| CS-UI-008 | P0 |
| CS-UI-009 | P0 |

**Sprint demo:** the co-scientist UI shows execution status for a single RunRequest and a multi-run ExecutionBatch.

---

## Sprint 4 — ResultBundle ingestion

Goal: ingest independent runner results and link them to co-scientist objects.

| Story ID | Priority |
| --- | --- |
| CS-VALIDATION-007 | P0 |
| CS-VALIDATION-008 | P0 |
| CS-VALIDATION-009 | P0 |
| CS-VALIDATION-010 | P0 |
| CS-VALIDATION-011 | P0 |
| CS-UI-010 | P0 |

**Sprint demo:** ingest a ResultBundle summary, link it to Experiment Card and Approach Cards, and show metrics, validation status, artifacts, warnings, and deviations.

---

## Sprint 5 — Score and evidence updates

Goal: update scores and evidence views from validation outcomes.

| Story ID | Priority |
| --- | --- |
| CS-SCORE-008 | P0 |
| CS-SCORE-009 | P0 |
| CS-SCORE-010 | P0 |
| CS-APPROACH-008 | P0 |
| CS-APPROACH-009 | P0 |

**Sprint demo:** a completed ResultBundle updates an Approach Card score with rationale, evidence type, confidence change, and no duplicate update on replayed events.

---

## Sprint 6 — Evaluation and operations readiness

Goal: measure whether the handoff loop is reliable.

| Story ID | Priority |
| --- | --- |
| CS-EVAL-007 | P0 |
| CS-EVAL-008 | P0 |
| CS-EVAL-009 | P0 |
| CS-VALIDATION-010 | P0 |
| CS-GOV-009 | P0 |

**Sprint demo:** show metrics for RunRequest creation success, traceability coverage, duplicate score-update prevention, and failed-run diagnostics.

---

# Updated dependency map

```
CS-EPIC-EXPERIMENT
  -> CS-EPIC-APPROVAL
      -> CS-EPIC-EXECUTION
          -> CS-EPIC-VALIDATION
              -> CS-EPIC-SCORE
                  -> CS-EPIC-APPROACH
                      -> CS-EPIC-DEVICE
                      -> CS-EPIC-ROADMAP

CS-EPIC-GOVERNANCE
  -> CS-EPIC-APPROVAL
  -> CS-EPIC-EXECUTION
  -> CS-EPIC-VALIDATION

CS-EPIC-UI
  -> CS-EPIC-EXECUTION
  -> CS-EPIC-VALIDATION
  -> CS-EPIC-SCORE

CS-EPIC-EVALUATION
  -> CS-EPIC-APPROVAL
  -> CS-EPIC-EXECUTION
  -> CS-EPIC-VALIDATION
  -> CS-EPIC-SCORE
```

---

# Definition of Done additions

A story in this backlog is done only when:

1. The co-scientist does not execute jobs directly.
2. Approved experiments are handed off as RunRequests or ExecutionBatches.
3. Execution state is separate from Experiment Card approval state.
4. ResultBundle ingestion is idempotent.
5. RunRequest, RunAttempt, ResultBundle, and artifact references are traceable to Experiment Card and Approach Cards.
6. Failed runs preserve useful diagnostic references where available.
7. Score updates include rationale, confidence change, and ResultBundle references.
8. Permissions are respected for run status, logs, artifacts, and runner details.
9. Duplicate events do not create duplicate score updates.
10. The UI labels execution as running in the Experimentation System, not inside the co-scientist.

---

# Updated MVP acceptance criteria

The co-scientist execution-handoff update is MVP-complete when:

1. An approved Experiment Card can create one or more RunRequests in the Experimentation System.
2. The co-scientist stores returned RunRequest IDs and ExecutionBatch IDs.
3. The co-scientist can display separate approval and execution states.
4. The co-scientist can show queued, running, completed, failed, canceled, blocked, and partial batch statuses.
5. A completed ResultBundle summary can be ingested and linked to the original Experiment Card, Hypothesis Card where present, and Approach Cards.
6. Failed runs preserve failure status, diagnostic references, logs or artifact links where available, and retryability.
7. Approach Card scores update from validation results with rationale and no duplicate score updates.
8. Multi-run Experiment Cards can aggregate ResultBundles into a batch validation summary.
9. Roadmap items can be updated from validation outcomes.
10. The co-scientist never directly executes experiments, manages runners, or runs shell commands.
