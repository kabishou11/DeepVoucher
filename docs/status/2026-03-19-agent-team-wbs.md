# 2026-03-19 Agent-Team WBS

## Objective

Coordinate subagents for the next 3–5 working days so that each parallel stream advances the voucher auto-entry prototype, keeps the 100% accuracy rule intact, and prepares for the more general rules/knowledge enhancements that follow.

## Parallel Tracks (one per subagent)

- **Track A – Rule Registry Expansion (primary track)**: Day 1 validate existing `split_rules` interfaces and add helper abstractions for multi-debit/multi-credit scenarios; Day 2 register the new helpers and add regression coverage for edge cases (e.g., multi-line payment splits); Day 3 backfill documentation/comments and ensure the pipeline still references the registry via `core/workflows/voucher_pipeline.py`. Acceptance: new helper is in `split_rules.py`, unit tests cover the helper, pipeline still passes `pytest`.
- **Track B – Knowledge/Ops Hardening**: Day 1 document the LanceDB/embedding failure modes and describe the fallback order, Day 2 add a short checklist for validating LanceDB writes on an unrestricted machine and crosscheck `knowledge/parsed/index_status.json`, Day 3 verify `docs/status/2026-03-19-progress.md` notes the outstanding steps and adjust if necessary. Acceptance: new checklist doc and updated status doc referencing outstanding verification steps; instructions to run `scripts/run_current_sample_regression.py` remain up to date.
- **Track C – Regression & Documentation Burst**: Day 1 rerun the live regression and capture outputs for the current sample, Day 2 snapshot the regression command and expected JSON in `docs/status`, Day 3 produce a short doc (or note in the WBS) summarizing what to extend next (additional ticket types). Acceptance: saved regression log plus textual summary; status/WBS references the regression command and next sample targets.

## Dependency Order

1. Rule registry helpers must land before new regression cases are added so tests record the updated behavior.
2. Knowledge checklist relies on stabilized regression output to describe “what to compare” for LanceDB.
3. Documentation updates (status + WBS) should follow the completion of the two preceding tracks to reflect their outcomes.

## Acceptance Criteria Snapshot

- Each track needs a verifiable artifact (code helpers/tests for Track A, checklist/note for Track B, regression log/summary for Track C).
- Nothing in this phase alters the main API or pipeline contracts; we keep changes confined to helpers, docs, and tests to avoid rework.
- Closing this WBS should result in updated status notes, a clear regression reference, and a path forward for the more general rule engine work.
