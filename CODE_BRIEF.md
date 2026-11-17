# Epilepscreen code brief

Epilepscreen is a Django video library with a Python screener, a guarded player, and a demo shop. The main flow is **upload → decode → detect → store results → display report and dim playback**.

| Code | What the functions do |
| --- | --- |
| `manage.py`, `mysite/` | Start Django, read environment settings, set up the database connection, and route requests to the app. |
| `epilepscreen/urls.py`, `views.py` | Route library, upload, playback, screening, store, checkout, and health requests. `VideoStore` queries and updates the video table. `decorate_videos` joins screening status and event counts into library cards. |
| `epilepscreen/media.py` | Identify media types, probe file properties, and normalize or suggest categories. `upload_video` validates the upload, hashes its contents to detect duplicates, and compresses its bytes before storage. |
| `epilepscreen/views.py` screening functions | `materialise_video` writes a temporary input file. `sensitivity_from_request` validates overrides. `run_screening` calls the analyzer, saves the verdict and events, and returns a report. `screening_report` reconstructs the saved report for the player, report page, and events API. |
| `photosensitive/analyze_video.py` | Probe the source rate and dimensions, build a reduced-resolution FFmpeg proxy when needed, stream RGB frames through OpenCV, and clean up the proxy. Screening reads every decoded frame by default. |
| `photosensitive/{temporal,spatial,config}.py` | Measure luminance, red coverage, color changes, stripe coverage, and pattern movement. Find repeated alternating brightness changes and provide the default thresholds. |
| `photosensitive/analyzer.py` | `analyze_frames` turns measurements into timestamped windows and returns a `RiskProfile`. `HazardEvent` holds a detector kind, times, and measurements. The profile exposes counts, duration, and a JSON-ready summary. The flicker rate counts peak brightness transitions in a rolling second. |
| `epilepscreen/{models,analysis_store}.py` | Define database records for media, screening results, and shop data. `save_events` replaces the previous event list, `save_analysis` upserts the verdict, and `clear_analysis` deletes both. Migrations create and seed the schema. |
| `templates/`, `epilepscreen/static/epilepscreen/` | Templates render the pages. `player.js` connects timeline and protection controls. `epilepscreen.js` draws the dimming overlay during saved hazard windows. `store.js` handles the source browser and upload UI. |
| `epilepscreen/{orders,money,store_browser}.py` | Record demo orders and cumulative customer spending, convert and format rupee amounts using integer paise, and fetch and rewrite pages from the store's allowed external sources. |
| `epilepscreen/management/commands/`, `sql.py` | `ingest_media` imports files. `analyze_media` emits a JSON report. `make_samples` creates demo clips. `spend_report` lists demo spending. `sql.py` runs migrations. |

The detector tests live in `photosensitive/tests/`, Django tests in `epilepscreen/`, and the guard widget test alongside its JavaScript. For setup and daily use, see the [user guide](USER_GUIDE.md).
