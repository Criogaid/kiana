# P4: local candidate discovery

`词频候选 <主题>` is restricted by the existing administrator boundary. It selects current-version labels from the last seven Shanghai calendar days with AI evidence and no literal evidence for that theme/message. Literal themes return an explicit unsupported-mode message. No AI call is made.

`db.candidate_archive_ids(theme_id, rules_version, start, end)` implements source selection. `candidates.scan_candidates(theme, now)` reads archive text and runs `core.candidates.discover_candidates(theme, messages)` in a worker thread. The pure miner adapts the historical branch's residual segmentation, layered support pruning, PMI, left/right entropy and substring absorption. It requires three distinct messages and two users, excludes existing names/aliases, and returns at most twenty phrases. Same-theme concurrent scans are rejected; cancellation retains the lock until the worker finishes.

Validation: Ruff, formatting and Pyright pass. Four focused tests pass. Full pytest: **525 passed, 8 failed, 6 skipped**; the eight failures remain the documented baseline fund matcher failures. Tests cover support thresholds, same-message repetition, known names, substring absorption, AI-only source selection, version/window filters, literal mode, no AI calls, and repeated cancellation. Candidate locks are reset in `tests/conftest.py`.

The `.env.prod` example cleanup remains deferred by explicit user decision due to the runtime permission block, as recorded in the P3 handoff. P5 charts remain pending.
