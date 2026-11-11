# Final handoff

Branch: `feat/final-sprint` (based on `main` at `6a3d279`).
Machine: Windows, Python 3.12.2, Django 5.1.7, NumPy 2.5.4, OpenCV 5.0.0.
Database used for every check below: **SQLite** (`DB_ENGINE=sqlite`, the default).

---

## 1. Verified results

Every command below was run in this session, in this order, on a database that
had just been deleted and rebuilt.

| Check | Command | Result |
| --- | --- | --- |
| Django system check | `python manage.py check` | `System check identified no issues (0 silenced).` |
| Migration drift | `python manage.py makemigrations --check --dry-run` | `No changes detected` |
| Django test suite | `python manage.py test` | **72 tests, OK** |
| Detector test suite | `python -m pytest photosensitive/tests -q` | **35 passed** |
| Overlay widget tests | `node epilepscreen/static/epilepscreen/epilepscreen.test.js` | `OK: all overlay widget tests passed` |
| Schema build from scratch | `python sql.py` | all migrations applied, including `0003_sql_tables` |
| Demo clips | `python manage.py make_samples` | 5 clips written, H.264 (ffmpeg present) |
| Browser sweep | `python scripts/qa_screens.py` | **0 problems, 0 console errors, 19 screenshots** |

The browser sweep drives the real site with Playwright and asserts, not just
screenshots:

* every page returns < 400 and contains its expected heading;
* the uploaded clip is decoded by the browser (`video.duration == 2`);
* the overlay widget is attached (`.epilepscreen-overlay` exists);
* the timeline draws **2** hazard segments from the Python events;
* clicking a timestamp moves `video.currentTime` (0.48 s);
* the checkout page contains `DEMO CHECKOUT` and no card fields;
* the confirmation page contains `Order recorded`.

Screenshots are in `qa/` (gitignored): `desktop-home`, `desktop-library`,
`desktop-library-filled`, `desktop-upload`, `desktop-store`,
`desktop-checkout-empty`, `desktop-checkout`, `desktop-confirmation`,
`desktop-player`, `desktop-player-again`, `desktop-screening`, `desktop-embed`,
`tablet-player`, and six `mobile-*` shots at 390×844.

## 2. The pipeline, end to end

Verified by the sweep and by the test suite:

```
samples/strobe.mp4
  → POST /upload/send/            hash 360446866780034648, lzma blob stored
  → run_screening()               30 frames @ 15 fps, 2.0 s
  → hazard_event                  2 rows: colour_transition, flicker
  → analysis                      1 row: is_safe = 0
  → GET /player/<hash>/           report rendered, 2 timeline segments
  → GET /events/<hash>/           {kind, start, end, attributes}
  → player.js + overlay widget    dims while currentTime is inside a window
  → POST /cart/add/1/ → /checkout/ → POST /checkout/ → /order/
                                  Purchase(payment_method='demo', status='completed')
```

Detector output for the five generated clips (`python manage.py analyze_media`):

| Clip | Verdict | Flags |
| --- | --- | --- |
| `calm.mp4` | safe | — |
| `strobe.mp4` | risky | `color_transition`, `flicker` (flash_rate 15.0/s) |
| `redflash.mp4` | risky | `red_flash` (coverage 1.0), `flicker`, `color_transition` |
| `stripes.mp4` | risky | `spatial_pattern` (coverage 0.9) |
| `colour.mp4` | risky | `color_transition`, `flicker`, `red_flash` |

## 3. What changed

**Database (commit `d9ef428`)**

* `DB_ENGINE` selects SQLite (default) or MySQL; the raw SQL in `views.py` uses
  `%s` placeholders, which Django translates for both engines.
* Migration `0003_sql_tables` creates `epilepsy`, `hazard_event` and `analysis`
  with per-vendor DDL and `IF NOT EXISTS`, so an existing MySQL database built
  by the old `sql.py` is left alone.
* Unmanaged ORM models describe those tables; `sql.py` now calls `migrate`.
* Removed the stray `connection.commit()` calls that made the code unusable
  inside a transaction (and were unnecessary in autocommit mode).

**Analysis (commit `a6a69ed`)**

* Fixed a real timestamp bug: events were stamped with the *requested* sampling
  rate instead of `source_fps / step`, which shifted every reported time.
* Frames are downscaled to a 480 px long edge and capped at 20 000 frames.
* `RiskProfile` now carries `fps`/`frame_count` and exposes `summary()` and
  `to_dict()`; flash windows report `flash_rate` and `flashes_per_second`.
* `/analyze/<hash>/` runs the screener on demand with validated sensitivity
  overrides (out-of-range values fall back to the documented defaults).
* Upload: content-hash duplicate detection, metadata probe, automatic category,
  optional inline screening, 15-minute guard for long files.
* `make_samples` generates the five demo clips and re-encodes them to H.264 when
  `ffmpeg` is on PATH, because browsers cannot decode OpenCV's default `mp4v`.

**Interface (commit `88773cd`)**

* One `base.html`, two stylesheets: `store.css` (the existing design system) and
  `pages.css` (new components only). No second palette, no per-page design.
* Home, library, upload, player, report, checkout and receipt all use the
  darkroom/editorial system.
* Player: real `<video>` with range streaming, hazard timeline, click-to-seek,
  dim-strength and padding sliders, next-hazard jump, keyboard shortcuts.
* Checkout is explicitly simulated: `DEMO CHECKOUT — NO REAL PAYMENT`, no card
  fields anywhere, receipt states that nothing was charged.

## 4. Commands for the demonstration

```powershell
cd D:\CodeProjects\Epilepscreen
.venv\Scripts\activate
python manage.py migrate            # first time only
python manage.py make_samples       # writes samples/*.mp4
python manage.py runserver
```

Then: <http://127.0.0.1:8000/> → **Upload** → `samples/strobe.mp4` → the player
opens with a red *2 windows* chip → press play and watch the picture dim inside
the red band → **Read the full report** → **Store** → *Add to the demo cart* →
**Checkout** → *Confirm demo order*.

## 5. Outstanding limitations (stated, not hidden)

1. **Sampling aliasing.** Analysis reads ~15 frames/s. A flash that repeats at
   exactly the sampling rate can cancel out (a 15 fps strobe sampled at 15 fps
   is fine; a 30 fps strobe sampled at 15 fps is not). This is why the default
   is 15 fps and why the report page says so.
2. **Heuristics, not a clinical standard.** Thresholds follow WCAG 2.3 guidance
   (40/255 luminance jump, 25 % red coverage, 0.4 colour delta, 15 % pattern
   coverage). They are not validated against patient data, and the site never
   claims protection from seizures.
3. **MySQL path not exercised here.** No MySQL server was reachable from this
   machine, so the MySQL branch of `0003_sql_tables` and the `mysqlclient`
   backend are written but unverified. SQLite is verified end to end.
4. **Inline screening cap.** Files longer than 15 minutes are stored but not
   screened during the upload request; the player's *Screen this video* button
   runs it on demand. There is no background queue.
5. **Blobs in the database.** Uploads are lzma-compressed rows in `epilepsy`.
   Fine for a school project and for the 100 MB cap; not how a production
   service would store media.
6. **Source browser needs the internet.** The store's in-page reader proxies six
   named sources; without network access it shows its error panel.
7. **Store is fictional.** Prices are seeded sample values, orders are local
   rows, and no email or invoice is ever sent.
8. **`samples/*.mp4` is gitignored.** Regenerate with `make_samples`; without
   `ffmpeg` the clips are `mp4v` and will screen correctly but will not play in
   a browser.

## 6. Test changes — what was replaced and why

The old `epilepscreen/tests.py` (38 tests) was written against a database layer
that no longer exists: it patched `epilepscreen.views.get_db_connection` with
`mysql.connector` mocks, asserted on raw SQL strings, and expected `/embed/` to
return 500 when the database was down. Those tests could not pass against the
current code without re-introducing the MySQL-only layer, so they were replaced
rather than deleted:

| Old test | Replaced by |
| --- | --- |
| `IndexTests` (mocked cursor rows) | `HomeTests` / `BrowseTests` against a real test database |
| `BrowseTests` (asserted `%gig%` reached a mock) | search and category filters asserted on real rows |
| `UploadTests` (oversized file only) | 6 upload tests: extension, empty, oversized, success, duplicate, inline screening |
| `StreamTests` / `EmbedTests` (expected 500) | range/206/416/404 streaming tests and an embed render test |
| `AnalysisStoreTests` (asserted `REPLACE INTO` text) | `save_events` replace semantics and one-row-per-video verdict, checked in SQL |
| `AnalyzeSensitivityTests` (3-key cfg echo) | full 9-key effective config, overrides echoed separately, out-of-range fallback |

Nothing was removed to make the suite green: the count went from 38 mocked tests
to 72 tests that exercise the real pipeline, plus 6 new detector tests in
`photosensitive/tests/test_sampling.py` (35 total there).

## 7. Files worth opening first

| File | Why |
| --- | --- |
| `photosensitive/analyzer.py` | the five detectors and the event grouping |
| `photosensitive/analyze_video.py` | OpenCV decoding, subsampling, effective fps |
| `epilepscreen/views.py` | SQL layer, `run_screening()`, player, demo checkout |
| `epilepscreen/migrations/0003_sql_tables.py` | the schema, per engine |
| `templates/player.html` + `static/epilepscreen/player.js` | how timestamps reach the overlay |
| `PROJECT_EXPLANATION.md` | the viva script |

