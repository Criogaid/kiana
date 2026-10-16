# Word Pulse rework acceptance

Status: P1–P5 implemented and merged. Final acceptance remains open only for the protected `.env.prod` example cleanup, explicitly deferred by the user. This document does not assert that the full repository test suite is green.

## Requirement evidence

| Plan requirement | Implementation and verification |
| --- | --- |
| §0 staged fork PRs, no legacy compatibility | PRs [1](https://github.com/Criogaid/kiana/pull/1), [2](https://github.com/Criogaid/kiana/pull/2), [3](https://github.com/Criogaid/kiana/pull/3), [4](https://github.com/Criogaid/kiana/pull/4), [5](https://github.com/Criogaid/kiana/pull/5), each merged before the next branch. P0 skipped as permitted. The user authorized test migration. |
| §1–3 semantic/literal modes, local numerical reports, query never classifies | `classifiers.py`, `pipeline.py`, `report.py`; classifier, pipeline and handler tests cover both modes, literal/AI union, OTHER exclusion, distinct messages/users, no AI query classification, missing AI and trend failure. |
| §3 atomic writes and archive consumption | `db.commit_live_batch`, `commit_backfill_chunk`; injected SQL failure proves rollback of labels/budget/cursor. Real SQLite tests prove initial backfill, live consumption, retry twice then fallback, budget head/tail split, noise cursor advancement, version guards and reconciliation after a rule edit during classification. |
| §3 tick ordering and isolation | `ensure_cursor → reconcile → live → backfill` inspected in `pipeline._tick_group`; disabled/locked ticks, group allow/deny rules and one-group failure isolation tested. Archive range tests cover group/private isolation, after/until/limit bounds and empty text. |
| §4 dependency direction and single classifier port | Core modules import standard library and sibling core modules only; inspected source/import search. Entry adapters declare cross-plugin dependencies with `require`. `core.ports.Classifier` is the only protocol. |
| §5 normalization, noise, literal matching, merge, time, aggregation | Core tests cover NFKC/case folding, ASCII boundaries, longest matching, multiple hits, command/bot/noise exclusion, union/OTHER rules, unclassified semantics, date filling, window/budget limits and percentages. Negative timestamps work on Windows. Daily totals deduplicate archive IDs across clusters. |
| §6.1 shared transaction and archive APIs | `test_storage_transaction.py` proves commit/rollback and repeated cancellation with successful/failing workers. `test_archive_cursor.py` verifies bounded cursor queries and >1100-ID batched lookup. Archive append-only contract is documented in its module. |
| §6.2–6.3 schema, migration, rules and cleanup | Legacy schema fixture verifies preserved themes/clusters/aliases and repeatable column additions/table removal. DB tests verify normalized shared namespace, no-op versions, aliases/descriptions/modes, deletes, version visibility and backfill guards. Retention test proves only derived rows expire; archive/rules/cursor remain. |
| §7 provider payload, structured responses, errors | Three protocols tested through real SDK with mocked HTTP in strict/JSON modes. Tests cover routes, aliases, no private IDs, 300-character truncation, local indices, unknown names, duplicate/missing/out-of-range indices, refused/truncated output and transport/JSON error mapping. Usage logging, temperature and timeout inspected in adapter. |
| §8.2 report snapshots, caching, trend and examples | SQL snapshot regression queues a writer during report assembly. Tests prove no classification, cache reuse across tick timestamp changes, rule-version invalidation, fallback when trend fails, empty reports and examples truncated to 40 characters without sender IDs. Trend prompt contains aggregates only. |
| §8.3 candidate discovery | `test_word_pulse_candidates.py` verifies current-version/time-window AI-only source, no literal labels, minimum 3 messages/2 users, same-message deduplication, existing-name exclusion, substring absorption, literal-mode rejection, no AI calls and repeated-cancellation lock retention. CPU mining uses a worker thread with historical PMI/entropy scoring. |
| §9 command grammar and permissions | Parser tests cover Chinese actions, aliases, missing/extra arguments, limits, windows and ordinary chat. Matcher tests cover member/admin/private access and real reply segments. Management tests verify conflict messages and immediate deletion. Candidate action uses the same administrator boundary. |
| §10 configuration | New bounds verified with Pydantic; old runtime configuration fields removed. **Pending:** `.env.prod` still contains old commented examples due to the runtime permission block. Replacement content is ready in the P3 handoff. |
| §11 jobs | Scheduler test verifies interval, single instance and coalescing; cleanup job registered. Actual retention behavior tested independently. Source confirms configured retention and Shanghai calendar cutoff. |
| §12 P5 chart | Real PNG decoded and visually inspected. Tests verify distinct total versus overlapping cluster counts, top five plus total, hollow today, zero suppression, image response and text fallback on plotting exceptions. Matplotlib uses Figure/FontProperties, runs in a thread and serializes shared renderer access. |
| §13 stage handoffs | P1 through P5 handoff documents are committed in this directory. |

## Final checks

- `uv run ruff check`: passed.
- `uv run ruff format --check src/plugins/word_pulse`: passed, 21 files.
- `uv run pyright`: passed, zero errors.
- Full `uv run pytest -q`: **536 passed, 8 failed, 6 skipped**.
- All eight failures are the independently established baseline `tests/test_fund_matcher.py` failures: regex_match, etf_code, stock_code_with_suffix, beijing_stock, handler_with_mocked_data, handler_with_unknown_code, handler_with_private_message and multiple_codes.
- Live AI network tests and deployment to a real QQ bot were not run. Mock-transport tests exercise the actual SDK protocols; matcher tests exercise local NoneBot routing.

## Remaining external action

The runtime permission system rejects `.env.prod` with `path_read`, rule `*.env.*`, even after explicit user authorization. Grant a runtime read/write exception for that file, or manually apply the exact Word Pulse example replacement in [P3-testing-handoff.md](P3-testing-handoff.md). Do not modify credentials or `.env.dev`. Then inspect the resulting diff, commit the example update and close this acceptance item. The user approved proceeding through P4/P5 without claiming this item complete.
