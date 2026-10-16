# P5: daily trend charts

`ReportData.daily_totals` now carries distinct archive-message counts for each date, computed from the same label sets as `daily`. Totals are never the sum of overlapping cluster counts. `render.render_trend_chart(data)` returns a PNG or `None` for all-zero data, using `Figure` and the bundled CJK font without pyplot. It draws the top five named clusters plus total discussion; today's markers are hollow. Matplotlib access is serialized across worker threads.

`ReportResult.chart` is cached alongside text. The QQ query response sends text and an image segment together. Rendering runs outside the event loop; exceptions are logged and preserve the text response.

Validation: Ruff, formatting, Pyright and diff checks pass. Chart tests cover deduplicated totals, top-five selection, hollow markers, actual 1350×720 PNG decoding, all-zero suppression and application-level text fallback on an injected rendering failure. A generated PNG was inspected visually for Chinese glyphs, labels, legend and today's hollow point. Full pytest: **528 passed, 8 failed, 6 skipped**; all failures are the previously documented fund matcher baseline failures. Live AI and deployment to a real QQ bot were not run.

The runtime permission block on `.env.prod` remains the deferred final acceptance item; see the P3 handoff for the approved replacement block.
