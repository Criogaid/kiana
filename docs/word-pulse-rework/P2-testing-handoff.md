# P2 testing handoff

Stage: P2 (rework plan sections 5, 6.2, 7). New classification modules are not connected to the old entry point yet. Old bucket and charset tables remain until P3.

## Changed files and contracts

- `core/types.py`: frozen rule/message/label dataclasses; `ClassifyOutcome.__or__` concatenates labels and sums unclassified counters.
- `core/ports.py`: `Classifier.classify(msgs, themes) -> ClassifyOutcome` protocol.
- `core/text.py`: `normalize`, `is_noise`, `LiteralMatcher.match -> (relevant, cluster_ids)`. Longest writing wins at each starting position; overlapping hits at different positions remain possible. ASCII alphanumeric names require ASCII alphanumeric boundaries.
- `core/merge.py`: `AIVerdict` and `merge`; literal and semantic evidence are unioned, with no OTHER label if any cluster matches.
- `core/budget.py`: `take` clamps allowance to zero and wanted count.
- `core/timeutil.py`: Shanghai `day_of` and inclusive-now/exclusive-end `window_bounds`.
- `core/aggregate.py`: `ClusterCounts`, `ClusterStat`, `ReportData`, `build`. The builder requires keyword `now` to fill zero days even when no labels exist. Distinct SQL aggregates provide message/user counts; daily points are deduplicated by archive ID.
- `classifiers.py`: `LiteralClassifier`, `AIClassifier(batch_size, output_mode, timeout)`, `AIClassifier.literal_only`, response models, `decode_verdicts`, `matcher_for`, `ai_available`.
- `errors.py`: shared exception classes extracted from `ai.py`; old callers retain the same exception identities.
- `db.py`: additive label/unclassified/cursor/budget schema and repeatable rule-column migration. Existing rule CRUD remains unchanged until P3 switches callers to the typed transactional contract.

## Behavioral coverage for the testing model

- Normalization, bot/short/symbol/command filtering, longest match, distinct-position overlaps, theme-only relevance, ASCII boundaries, single-character names.
- Every merge branch, including AI false with literal true, multiple labels, source attribution, and OTHER suppression.
- Outcome combination preserves input counters; budget bounds; Shanghai midnight and window boundaries.
- Percentages use relevant-message totals, can sum above 100%, sort OTHER last, omit zero rows, compare the previous window, and fill zero dates.
- Both strict and JSON modes use the configured classification caller and shared AI error mapping; payloads contain only supplied names/descriptions/aliases and batch-local indices with text truncated to 300 characters. No identities or timestamps are sent.
- Unknown theme/cluster names, alias normalization, out-of-range indices, duplicate indices (all occurrences discarded), omitted messages, empty relevant hits, multiple theme hits, and semantic-only unclassified counts.
- Literal-only mode performs no AI call; all-literal themes do not consume AI calls. Classified unrelated messages are answered, not unclassified. Debug logs contain usage, not raw user messages.
- Run schema migration twice against an old schema containing rules, aliases, buckets, and charsets. Existing data survives; added rule defaults are semantic/version 1/backfill version 0.

Tests should reset `classifiers._matchers` between cases and use isolated SQLite. No files under `tests/` were read or edited. API-specific new tests remain assigned to the testing model.

## Executed validation

- Ruff over `src`: passed.
- Ruff formatting over changed Python files: passed (12 files formatted/checked).
- Full Pyright: zero errors.
- Full pytest: 562 passed, 8 failed, 7 skipped. Failures are the same eight fund matcher failures reproduced on baseline in P1; see the P1 handoff.
- `git diff --check`: passed.

P3 will remove the old entry, AI module, analysis, bucket and charset tables, and old configuration. It will supply typed transactional CRUD, label commits, aggregation readers, the pipeline, and report/command adapters.
