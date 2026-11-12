# Epilepscreen — code guide

A complete reference to the repository as it stands on `main` after the final
merge (`51e71fa`). Every file, every function, every SQL statement, how the
database works, and how the MySQL connection works.

Read it front to back once; after that it is a lookup table for the viva.

---

## Contents

1. [The website as a whole](#1-the-website-as-a-whole)
2. [Request lifecycle, end to end](#2-request-lifecycle-end-to-end)
3. [File-by-file reference](#3-file-by-file-reference)
4. [Every SQL statement and what it is for](#4-every-sql-statement-and-what-it-is-for)
5. [How the database works](#5-how-the-database-works)
6. [The demonstration order ("cost") path](#6-the-demonstration-order-cost-path)
7. [How the MySQL connection works](#7-how-the-mysql-connection-works)
8. [Configuration and environment](#8-configuration-and-environment)
9. [Known weak points](#9-known-weak-points)

---

## 1. The website as a whole

Epilepscreen is a Django project with two halves that share one database:

* a **screening tool** — upload a video, run a Python analyser over it, read a
  timestamped hazard report, watch it in a player that dims itself;
* a **demonstration storefront** — a sample catalogue, a cart, and a checkout
  that records a fake order. No gateway, no card, no money.

### 1.1 Routes

Every URL is declared in `epilepscreen/urls.py` and maps to a function in
`epilepscreen/views.py`.

| URL | View | Method | Template / response | Purpose |
| --- | --- | --- | --- | --- |
| `/` | `index` | GET | `home.html` | Landing page: hero, three-step explanation, newest six videos, pack list |
| `/browse/` | `browse` | GET | `browse.html` | Library grid with `?q=` title search and `?category=` filter |
| `/categories/` | `categories` | GET | JSON | `{categories: [{name, count}]}` for the filter chips / API use |
| `/upload/` | `upload` | GET | `upload.html` | Upload form |
| `/upload/send/` | `upload_video` | POST | 302 | Validate → hash → compress → store → optional inline screening |
| `/player/<hash>/` | `player` | GET | `player.html` | Video, hazard timeline, protection controls |
| `/embed/<hash>/` | `embed` | GET | `player.html` (`embedded=True`) | Same page with the site chrome hidden |
| `/screening/<hash>/` | `screening` | GET | `screening.html` | Written report: counts, every window, the method, the limits |
| `/stream/<hash>/` | `stream_video` | GET/HEAD | bytes | Range-capable video streaming out of the blob |
| `/stream/<hash>/file/` | `stream_as_file` | GET | bytes | Same, `X-Frame-Options` exempt |
| `/events/<hash>/` | `events` | GET | JSON | `{events:[{kind,start,end,start_time,end_time,attributes}]}` for the overlay |
| `/analyze/<hash>/` | `analyze` | GET or POST | JSON | Run the Python screener now, persist results, return the report |
| `/store/` | `store` | GET | `store.html` | Catalogue, source browser, upload, report sample, recent items |
| `/store/browser/` | `browser_page` | GET | `store_browser.html` | Server-side reader for six allowed sources |
| `/store/browser/asset/` | `browser_asset` | GET | bytes | Proxied image / font / stylesheet for that reader |
| `/products/<id>/` | `product_detail` | GET | 302 | Redirects to `/store/?product=<id>#order` |
| `/cart/add/<id>/` | `add_to_cart` | POST | 302 or JSON | Append the pack to the session cart |
| `/cart/remove/<id>/` | `remove_from_cart` | POST | 302 | Drop the pack from the cart |
| `/checkout/` | `checkout` | GET / POST | `checkout.html` → 302 | Order summary; POST creates the demo purchases |
| `/order/` | `order_confirmation` | GET | `order_confirmation.html` | Receipt for the order just placed |
| `/health/` | `health` | GET | JSON | `{status, database, engine}`; 503 when the DB is unreachable |
| `/admin/` | Django admin | — | — | Store products, purchases, and read-only screening tables |

### 1.2 Templates

`base.html` is the shell (banner, sticky bar with Library/Upload/Store/Cart,
message stack, footer, script blocks). Every page extends it except
`store_browser.html`, which is a standalone reader rendered inside an iframe.

`partials/_status_chip.html` is the one shared fragment: it turns
`video.rating` (`safe` / `caution` / `risk` / `unknown`) plus `event_count` into
the coloured chip used on the home page and in the library grid.

### 1.3 Stylesheets

Four files, two of which are infrastructure and two of which are layout:

| File | Owns |
| --- | --- |
| `tokens.css` | Space, type, colour, easing, z-index variables. One palette (`oklch` paper/ink/accent). |
| `base.css` | Reset, typography defaults, `.container`, `[data-slot]` image plates, reduced-motion rule. |
| `store.css` | The storefront design system: banner/bar, hero, `.btn`, `.field`, `.range__row`, `.report-table`, footer, the source-browser dialog. This is the reference the whole site follows. It also `@import`s tokens and base. |
| `pages.css` | Only the components the new pages need: chips, stat strips, library grid, upload split, player stage/timeline/controls, `.table-scroll`, checkout line items, `.demo-band`, receipt, print rules. It re-imports `tokens.css` and `base.css` so it also works standalone. |

`base.html` loads `store.css` then `pages.css`; the duplicate `@import` of the
tokens and base files is served from cache and only re-applies the same rules.

No page defines its own palette. `pages.css` has no new colour values except
`color-mix()` of existing tokens.

### 1.4 JavaScript

| File | Role |
| --- | --- |
| `epilepscreen.js` | The reusable overlay widget. `window.Epilepscreen.attach(video, options)` dims a transparent div over the video while `currentTime` is inside an event window. Also supports `liveDetect` (canvas sampling) and a `data-auto` mode that guards every `<video>` on a page. |
| `player.js` | Page glue: reads the embedded event JSON, builds the timeline, wires the sliders, the guard toggle, seek buttons, next-hazard jump, and the re-screen form. |
| `store.js` | Source-browser dialog, capture-status messages, file-name echo. |
| `epilepscreen.test.js` | Dependency-free Node harness for the widget (no browser, fake video object). |
| `player.js` / `store.js` are not unit-tested; the Playwright sweep covers them in a real browser. |

---

## 2. Request lifecycle, end to end

### 2.1 Upload → screening → report

```
POST /upload/send/
  views.upload_video
    request.FILES['video_file']
    ├── size == 0                     → message, redirect /upload/
    ├── size > settings.MAX_UPLOAD_BYTES → message, redirect /upload/
    ├── extension not in VIDEO_EXTENSIONS → message, redirect /upload/
    ├── content_type_for(...) not video/*  → message, redirect /upload/
    ├── raw = upload_file.read()
    ├── video_hash = int(sha256(raw)[:15], 16)
    ├── VideoStore.hash_exists(hash)
    │     └── exists → message "already in the library", redirect /player/<hash>/
    ├── _probe_bytes(raw, name) → cv2 duration/width/height (best effort)
    ├── suggest_category(...) when no category was given
    ├── VideoStore.insert_video(hash, title, category, mime, lzma.compress(raw))
    └── if POST['screen'] and duration <= 15 min:
            run_screening(hash)
              ├── materialise_video → temp file
              ├── photosensitive.analyze_video_file(path, target_fps=15)
              │      └── analyze_frames(...) → RiskProfile
              ├── analysis_store.save_events(hash, events)   [DELETE + executemany INSERT]
              ├── analysis_store.save_analysis(hash, profile) [REPLACE INTO]
              └── report dict (counts, fps, duration, events)
        → redirect /player/<hash>/
```

### 2.2 Playback

```
GET /player/<hash>/
  _video_or_404       → SELECT ... FROM epilepsy WHERE hash = %s   (no blob)
  screening_report    → analysis row, event counts, full event list
  render player.html  → events embedded as <script type="application/json" id="hazard-data">

browser:
  <video src="/stream/<hash>/" preload=auto>
  player.js  → window.Epilepscreen.attach(video, {fetchEvents: () => events, paddingSeconds})
  timeupdate → overlay.style.display = inHazard(currentTime) ? 'block' : 'none'
```

The server never sends "this frame is dangerous" — it sends seconds. The overlay
only compares numbers.

### 2.3 Store → demo order

```
POST /cart/add/<id>/      → session['cart'] = [ids...] → redirect /checkout/
GET  /checkout/           → cart items + totals + DEMO band
POST /checkout/           → validate email
                            transaction.atomic():
                              for product in items: Purchase.objects.create(
                                  payment_method='demo', status='completed', ...)
                            session['last_order'] = [pks]
                            session['cart'] = []
                          → redirect /order/
GET  /order/              → receipt from session (fallback: ?order=<pk>)
```

---

## 3. File-by-file reference

### 3.1 `manage.py` (22 lines)

Standard Django entry point. `main()` sets `DJANGO_SETTINGS_MODULE=mysite.settings`,
imports `execute_from_command_line`, and prints Django's own helpful message if
Django is missing. Nothing project-specific.

### 3.2 `sql.py` (37 lines)

`main()` — sets the settings module, calls `django.setup()`, prints which engine
`settings.DATABASES['default']['ENGINE']` resolved to, then
`call_command('migrate', interactive=False)`.

Kept because older versions of the project created tables by running this file.
It now delegates so there is exactly one schema definition (the migrations).

### 3.3 `mysite/settings.py` (180 lines)

| Block | Detail |
| --- | --- |
| `BASE_DIR` | Repo root; used for `db.sqlite3`, `templates/`, `.env`. |
| `load_dotenv(BASE_DIR/'.env')` | Secrets stay out of git. |
| `SECRET_KEY` | `DJANGO_SECRET_KEY` or an insecure development fallback. |
| `DEBUG` | `DJANGO_DEBUG == '1'`, default on. |
| `ALLOWED_HOSTS` | `localhost`, `127.0.0.1`. |
| `INSTALLED_APPS` | Django contrib + `epilepscreen`. |
| `MIDDLEWARE` | Standard seven, including CSRF, sessions, messages, clickjacking. |
| `TEMPLATES.DIRS` | `BASE_DIR/templates`. |
| `DATABASES` | Built from `DB_ENGINE` — see §7. |
| `STATIC_URL` | `'static/'` (Django's staticfiles app serves it in DEBUG). |
| `MAX_UPLOAD_BYTES` | Default 100 MB, `MAX_UPLOAD_BYTES` env override. |
| `ANALYSIS_FPS` | Default 15, `ANALYSIS_FPS` env override. |
| `DEMO_STORE` | `True`; the templates label the store from this. |

Note there is no `DB_CONFIG` dict any more: the old `mysql.connector.connect(**DB_CONFIG)`
path is gone, and everything goes through Django's connection.

### 3.4 `mysite/urls.py` (23 lines)

`""` → `include('epilepscreen.urls')`, `admin/` → `admin.site.urls`.
Nothing else.

### 3.5 `mysite/wsgi.py`, `mysite/asgi.py` (16 lines each)

Generated. `get_wsgi_application()` / `get_asgi_application()` with the settings
module preset. Used by a real deployment server, not by `runserver`.

### 3.6 `epilepscreen/apps.py` (6 lines)

`EpilepscreenConfig` — app name and `BigAutoField` default. Django boilerplate.

### 3.7 `epilepscreen/urls.py` (34 lines)

The route table from §1.1. `path('', views.index, name='index')` etc. Note
`upload/send/` is named `upload_send` (templates post to it) while the form page
is `upload`.

### 3.8 `epilepscreen/views.py` (1073 lines)

The largest file: SQL layer, screening orchestration, every page view.

#### Constants

| Name | Meaning |
| --- | --- |
| `MAX_UPLOAD_BYTES`, `ANALYSIS_FPS` | Import-time copies of the settings values (used as defaults). |
| `INLINE_SCREENING_LIMIT_S` | 900 s — longer footage is not screened inside the upload request. |
| `VIDEO_EXTENSIONS` | `mp4, webm, mov, avi, mkv, flv, m4v, 3gp, ogv`. |
| `SENSITIVITY_SPEC` | `key → (cast, min, max)` for the nine detector thresholds. |
| `KIND_LABELS` | Event kind → human label ("Flash / flicker", "Red flash", …). |
| `EXTERNAL_STORES` | The six catalogue sources the reader may proxy. |
| `PRODUCT_TYPE_LABELS` | `StoreProduct.PRODUCT_TYPES` as a dict. |
| `CART_SESSION_KEY`, `ORDER_SESSION_KEY` | `'cart'`, `'last_order'`. |

#### Small functions

* `max_upload_bytes()` — reads `settings.MAX_UPLOAD_BYTES` **at call time**, so
  tests and deployments can override it. (Reading it at import time was a bug
  that made `override_settings` silently ineffective.)
* `analysis_fps()` — same for `settings.ANALYSIS_FPS`.

#### `class VideoStore`

All access to the `epilepsy` table. One instance is created per call by
`get_video_store()`; there is no connection pooling of its own because it borrows
Django's connection.

| Method | SQL | Notes |
| --- | --- | --- |
| `cursor()` | — | `connection.cursor()` |
| `_rows(sql, params)` | any SELECT | Runs the query and maps rows to dicts using `cursor.description`. |
| `get_videos(search_query, category, limit, offset)` | SELECT … WHERE movie IS NOT NULL [AND LOWER(category)=LOWER(%s)] [AND LOWER(title) LIKE LOWER(%s)] ORDER BY time_uploaded DESC, hash DESC LIMIT/OFFSET | Builds the WHERE clause incrementally; values always go through params. Returns rows already decorated. |
| `get_video_by_hash(hash)` | SELECT … , movie WHERE hash=%s | Includes the blob — only used by streaming and screening. |
| `get_video_meta(hash)` | SELECT … WHERE hash=%s | No blob; used by the player so a page load never pulls megabytes. |
| `count_videos()` | SELECT COUNT(*) … | Home page stat and store footer. |
| `categories()` | SELECT category, COUNT(*) … GROUP BY category | Filter chips with counts. |
| `insert_video(hash, title, category, content_type, blob, when=None)` | INSERT INTO epilepsy … | `when` defaults to `timezone.now()`. |
| `hash_exists(hash)` | SELECT title WHERE hash=%s | Duplicate detection; returns the existing title so the message can name it. |
| `set_category(hash, category)` | UPDATE epilepsy SET category=%s WHERE hash=%s | Correcting a category after upload. Defined and tested, but no view calls it today — the fix-up path is the admin or `ingest_media`. |
| `delete_video(hash)` | DELETE hazard_event / analysis / epilepsy | Inside `transaction.atomic()`, children first. Same status: available, not wired to a route. |

#### Module-level helpers

* `get_video_store()` — returns a `VideoStore()`. (Historically a singleton; no
  state is kept now, so it is a plain constructor.)
* `get_db_connection()` — returns Django's `connection` object. Kept as a named
  seam so tests can patch it and so nothing else has to know about Django's
  internals.
* `_analysis_rows(hashes)` — one SELECT with an `IN (...)` list; returns
  `{hash: {is_safe, risk_flags, checked_at}}`. JSON text is decoded with
  `_loads`. Batching avoids one query per card on the library page.
* `_event_stats(hashes)` — one `GROUP BY video_hash, kind` SELECT; returns
  `{hash: {count, counts: {kind: n}}}`. Portable: `GROUP_CONCAT` behaves
  differently on the two engines, so the grouping happens in Python.
* `_loads(value, fallback)` — JSON column → Python value, tolerating `NULL`,
  already-decoded values (MySQL JSON columns come back as objects), and malformed
  text.
* `decorate_videos(videos)` — adds `analyzed`, `is_safe`, `risk_flags`,
  `checked_at`, `event_count`, `kinds`, `kind_labels`, `rating` to each row.
  `rating` is `unknown` (never screened), `safe` (screened, no events),
  `caution` (screened, safe verdict but events exist) or `risk`.
* `sensitivity_from_request(request)` — reads `flash_delta`, `flash_window`,
  `flash_limit`, `red_floor`, `red_window`, `color_threshold`,
  `spatial_contrast`, `spatial_threshold`, `pattern_move_threshold` from
  `POST` or `GET`; casts, range-checks against `SENSITIVITY_SPEC`, drops
  anything invalid. Returns `(overrides, effective)` where `effective` is the
  full nine-key config actually used.
* `_suffix_for(content_type)` — MIME → file extension for the temp file, because
  some demuxers sniff the extension.
* `materialise_video(hash)` — fetches the row, `lzma.decompress()` (falling back
  to the raw bytes if the blob was not compressed), writes a `NamedTemporaryFile`,
  returns `(path, row)`. Raises `Http404` for a missing row or missing blob.
* `run_screening(hash, cfg=None)` — the orchestrator: materialise → refuse audio
  → `analyze_video_file` → delete the temp file in `finally` → `save_events` →
  `save_analysis` → build the report dict (`is_safe`, `risk_flags`, `flags`,
  `counts`, `event_count`, `stored_events`, `frames`, `duration_s`, `fps`,
  `max_flash_rate`, `events`, `checked_at`). Raises `ValueError` when the file
  cannot be decoded — the caller turns that into a 422.
* `_max_flash_rate(profile)` — biggest `flash_rate` among flicker events.
* `event_for_json(event)` — one event shaped with **both** `start`/`end` (what
  the overlay reads) and `start_time`/`end_time` (what the older API shape used).
* `screening_report(hash)` — everything the player and report pages need:
  analysis row, per-kind counts, full event list. Returns `analyzed: False` when
  no verdict exists.

#### Page views

* `index(request)` — newest six videos + total + products → `home.html`.
* `browse(request)` — `q`, `category` from the query string → `browse.html` with
  `videos`, `categories` (with counts), `library_count`, `result_count`.
* `categories(request)` — `@require_GET`, JSON list for the chips.
* `upload(request)` — GET renders the form; POST delegates to `upload_video`.
* `_upload_error(request, message, status_redirect='upload')` — queues a message
  and redirects to the form.
* `upload_video(request)` — the validation/storage/screening pipeline described in
  §2.1. Returns 302 in every success and failure case (messages carry the reason),
  which keeps the browser on a refreshable page.
* `_probe_bytes(raw, name)` — writes bytes to a temp file, calls
  `media.probe_media`, deletes the file, returns metadata or `None`. Never raises.
* `_video_or_404(hash)` — `get_video_meta` or `Http404`.
* `player(request, video_hash)` — `@ensure_csrf_cookie` (so `player.js` can read
  the CSRF cookie for its POST), renders `_player_context`.
* `_player_context(video_hash)` — the context shared by `player` and `embed`:
  video row, report, `stream_url`, `events_url`, `analyze_url`, `screening_url`,
  `events_json` (marked safe — it is `json.dumps` of server-built dicts),
  thresholds, fps.
* `embed(request, video_hash)` — same context plus `embedded=True`; `player.html`
  adds the `is-embedded` body class, and `pages.css` hides the header, footer,
  breadcrumbs and page head.
* `screening(request, video_hash)` — the written report page.
* `stream_video(request, video_hash)` — decompress, then serve:
  * no `Range` → 200 with the whole body, `Accept-Ranges: bytes`;
  * `bytes=a-b` → 206 with `Content-Range: bytes a-b/size` and the slice;
  * malformed or out-of-bounds → 416 with `Content-Range: bytes */size`;
  * database unreadable → 503; unknown hash → 404.
  Range support is what makes the scrubber and `currentTime` seeking work.
* `stream_as_file(request, video_hash)` — same response with
  `@xframe_options_exempt`, for embedding in a frame on another origin.
* `events(request, video_hash)` — `screening_report` reduced to the JSON the
  overlay consumes (`analyzed`, `is_safe`, `events`, `counts`).
* `analyze(request, video_hash)` — validates overrides, calls `run_screening`,
  and maps failures to 422 (undecodable / audio-only) or 500 (database, decoder
  crash). On success returns the report plus `sensitivity` and `overrides`.
* `health(request)` — `SELECT 1`; returns `{status, database, engine}`, HTTP 200
  when the query works and 503 when it does not.

#### Store views

* `_money(paise)` — thin wrapper over `money.format_paise`, so `49900 → "₹499"`
  with Indian digit grouping. Called for cart totals, product cards and JSON.
* `_decorate_product(product)` — adds `price_amount` (formatted `"₹499"`),
  `price_display` (same string, kept as the template-facing name) and
  `kind_label`.
* `_products()` — active products ordered by `price_paise`; swallows
  `DatabaseError` so the page still renders before `migrate`.
* `_cart_ids(request)` — the session cart as a list of ints, defensively filtered.
* `_cart_context(request)` — resolves the cart against the catalogue (removing
  ids that are gone), returns `cart_items`, `cart_count`, `cart_total_paise`
  (integer) and `cart_total` (formatted).
* `_recent_videos(limit=4)` / `_library_count()` — small read helpers.
* `_store_context(request, selected_product_id=None)` — everything `store.html`
  needs: products, hero product, selection, external stores, categories, recent
  videos, library count, last order.
* `store(request)`, `product_detail(request, product_id)`,
  `add_to_cart(request, product_id)`, `remove_from_cart(request, product_id)` —
  the cart. `add_to_cart` answers JSON for `X-Requested-With: XMLHttpRequest`
  and redirects otherwise.
* `_source_for(url)` — maps a URL to one of the six named sources (or the host).
* `browser_page(request)` — `@xframe_options_sameorigin`; validates the URL,
  fetches and rewrites the page via `store_browser`, renders the reader shell.
  A capture returns a dict instead of `(title, html, url)` and switches the page
  into its "captured" state.
* `browser_asset(request)` — `@xframe_options_sameorigin`; proxies one asset,
  502 on `BrowserError`, 404 for a disallowed URL.
* `_checkout_email_error(email)` — the only field validation in the checkout.
* `checkout(request)` — GET builds the summary (session cart, or a single
  `?product=` for a direct link); POST validates the email and then hands the
  items to `orders.create_demo_order`, which writes the purchase rows **and** the
  per-email total in one transaction. Clears the cart, remembers the purchase ids
  in the session, redirects to the receipt.
  * `order_confirmation(request)` — reads those ids (or `?order=<pk>`), renders the
  lines, the simulated total, the per-email total from `customer_spend`
  (`spend_total`, `spend_orders`) and the "no payment taken" note.

### 3.9 `epilepscreen/models.py` (307 lines)

Ten models. Two groups.

**ORM-owned tables (Django creates and migrates them):**

| Model | Table | Key fields |
| --- | --- | --- |
| `Video` | `videos` | Legacy extended-metadata model (`url`, `bitrate`, `hdr_enabled`, `safety_rating`, `price_paise`). Present and migrated, but the live pipeline uses `VideoRecord` instead; it is the richer schema the project started from. |
| `StoreProduct` | `store_products` | `active`, `title`, `description`, `product_type`, `price_paise`, `duration_seconds`, `thumbnail`. The catalogue, priced in paise (₹499 = `49900`). |
| `Purchase` | `purchases` | FK `product`, `email`, `payment_method`, `card_last4` (always blank — no card is ever collected), `status`, `completed_at`, `amount_paise`, `currency` (default `INR`). The demo order lines. |
| `CustomerSpend` | `customer_spend` | `email` (PK), `total_paise`, `order_count`, `currency`, `first_order_at`, `last_order_at`. The running total per address; `total_display` renders it as ₹. |
| `VideoFormat` | `video_formats` | Reference specs (resolution, fps range, bitrate range). Unused by the current UI. |
| `VideoPurchase` | `video_purchases` | Per-video purchase history (`price_paise`, `currency`). Unused by the current UI. |
| `StoreSubscription` | `store_subscriptions` | Premium plan rows. Unused by the current UI. |
| `VideoCategory` | `video_categories` | Hierarchical categories with slug/icon/ordering. Unused by the current UI; categories currently live as a text column on `epilepsy`. |

**SQL-owned tables (`managed = False`, created by migration 0003):**

| Model | Table | Fields |
| --- | --- | --- |
| `VideoRecord` | `epilepsy` | `hash` (PK), `time_uploaded`, `title`, `category`, `content_type`, `movie` (blob) |
| `HazardEvent` | `hazard_event` | `video_hash`, `kind`, `start_time`, `end_time`, `attributes` (JSON), `created_at` |
| `Analysis` | `analysis` | `video_hash` (PK), `is_safe`, `risk_flags` (JSON), `checked_at` |

`managed = False` means migrations never issue DDL for them; they exist so the
admin can list them, so `makemigrations --check` stays clean, and so the schema
is documented in Python as well as in SQL.

### 3.10 `epilepscreen/migrations/`

| File | What it does |
| --- | --- |
| `0001_initial.py` | Creates `videos`, `store_products`, `purchases`, `store_subscriptions`, `video_categories`, `video_formats`, `video_purchases` with their indexes. |
| `0002_seed_store_products.py` | `seed_products()` inserts four sample packs if the table is empty; `remove_products()` reverses it. |
| `0003_sql_tables.py` | `create_tables()` runs per-vendor `CREATE TABLE IF NOT EXISTS` DDL for `epilepsy`, `hazard_event`, `analysis` (and an index on `hazard_event.video_hash` for SQLite). `drop_tables()` reverses. |
| `0004_analysis_hazardevent_videorecord.py` | `CreateModel` entries with `managed=False` — state only, no DDL. Keeps Django's model state in sync with `models.py`. |
| `0005_inr_prices_and_customer_spend.py` | Renames `*_cents` to `*_paise` on `purchases`, `store_products`, `videos`, `video_purchases`; sets `currency` default to `INR`; re-prices the four packs (₹499 / ₹799 / ₹1,999 / ₹3,999); creates `customer_spend`; re-prices any old order line from its product and back-fills the totals from existing `purchases` with `GROUP BY email` + `SUM(amount_paise)`. Reversible: restores the old prices and empties the spend table. |

### 3.11 `epilepscreen/admin.py` (95 lines)

* `StoreProductAdmin` — list/filter/search the catalogue (price shown in paise).
* `PurchaseAdmin` — list/filter/search orders (including `payment_method`, so
  every `demo` row is obvious).
* `VideoRecordAdmin` — `has_add_permission`/`has_change_permission` return
  `False` (the analyser owns those rows); delete is allowed.
* `HazardEventAdmin`, `AnalysisAdmin` — same read-only treatment.
* `CustomerSpendAdmin` — every field read-only, ordered by `-total_paise`, with
  `total_display` so the admin shows ₹ rather than raw paise. The table is
  written only by `orders.create_demo_order`.

### 3.12 `epilepscreen/analysis_store.py` (59 lines)

* `save_events(video_hash, events) -> int` — inside `transaction.atomic()`:
  `DELETE` the video's rows, then one `executemany` `INSERT` for the new events
  (or return 0 immediately if there are none). Re-screening therefore replaces
  rather than duplicates.
* `save_analysis(video_hash, profile)` — `REPLACE INTO analysis` so exactly one
  verdict row exists per video; wraps `DatabaseError` with context.
* `clear_analysis(video_hash)` — deletes events and verdict together, for a
  re-upload under a new hash or a manual reset. Exposed for maintenance; no view
  calls it today.

### 3.13 `epilepscreen/money.py` (60 lines)

The only place that turns stored integers into readable money. Prices are whole
paise in the database (`49900` is ₹499) because binary floating point cannot
represent 0.1 exactly and a store must never round a total by accident.

* `CURRENCY_SYMBOL = '₹'`, `CURRENCY_CODE = 'INR'` — one definition, imported by
  the view helper, the template filter and the management command.
* `group_indian(digits)` — `'1234567' → '12,34,567'`: last three digits, then
  pairs, which is the Indian convention (not `1,234,567`). Pure string work.
* `format_paise(paise)` — `49900 → '₹499'`, `49950 → '₹499.50'`, `None → '₹0'`,
  negatives keep their sign. Drops the fraction when it is zero.
* `rupees_to_paise(text)` — `'₹1,999'`/`'19.5'`/`'499'` → paise; raises
  `ValueError` on anything else (`''`, `'abc'`, `'1.2.3'`, `'12.345'`). Used when
  a human types a price, so a hand-entered amount can never be stored as a float.

### 3.14 `epilepscreen/orders.py` (127 lines)

Placing a demonstration order, and keeping the per-email total in step. The view
calls one function; the rules live here so they can be tested without a browser.

* `spend_for(email)` — the stored `CustomerSpend` row for an address, or `None`.
* `record_spend(email, amount_paise, when=None)` — adds to the running total.
  `get_or_create` for the first order (inside a nested `atomic()`, so a duplicate
  email race cannot poison the caller's transaction), then
  `CustomerSpend.objects.filter(pk=...).update(total_paise=F('total_paise') + amount, ...)`
  for later ones. The `F()` expression makes the addition happen **in the
  database** (`UPDATE customer_spend SET total_paise = total_paise + 49900`), so
  two orders arriving at once add up instead of overwriting each other. Returns
  the refreshed row.
* `create_demo_order(email, items, when=None)` — inside one
  `transaction.atomic()`: one `Purchase` per product
  (`payment_method='demo'`, `status='completed'`, `currency='INR'`,
  `amount_paise=product.price_paise`), then `record_spend(email, total)`. Returns
  `(purchases, spend)`. Raises `ValueError` for an empty item list. No gateway is
  contacted and no card data exists in the call.
* `spend_summary(limit=10)` — top spenders by total, for tooling and tests.

### 3.15 `epilepscreen/media.py` (106 lines)

Pure helpers, no database.

* `content_type_for(filename, uploaded_type=None)` — extension map first
  (`EXT_CONTENT_TYPES`), then the browser's type if it starts with video/ or
  audio/, then `application/octet-stream`.
* `is_audio_content(content_type)` — `startswith("audio/")`; used to skip
  screening and to categorise as Music.
* `normalize_category(raw)` — trims, caps at 40 chars, blank → `None`.
* `suggest_category(duration_s, width, height, title, audio_only)` — audio →
  Music; music keywords in the title → Music Video; ≥ 20 min → Movie; portrait →
  Short; otherwise Other.
* `probe_media(path)` — `cv2.VideoCapture` for width, height, fps and frame
  count; returns `{"duration_s", "width", "height"}` or `None` when the file has
  no readable video track. `None` is a normal answer, not an error.

### 3.16 `epilepscreen/store_browser.py` (410 lines)

The server-side reader behind the store's sources panel.

* `BrowserError` — one exception type for "cannot show this".
* `is_allowed_url(url)` — http/https only, no credentials, no odd ports, host must
  equal or be a subdomain of one of six suffixes in `ALLOWED_SUFFIXES`. This is
  the whole SSRF defence.
* `_session()` — `requests.Session` with the project UA.
* `_open(url, accept)` — GET with `allow_redirects=False`, follows up to six
  redirects manually, re-checking `is_allowed_url` on each hop, rejects ≥ 400.
* `_read_limited(response, limit, too_big)` — streams with a hard byte cap.
* `content_type_of(response)` — header, lowercased, parameters stripped.
* `_filename_for(response, url)` — Content-Disposition (including `filename*`),
  else the URL path; sanitised and given a guessed extension.
* `_is_video(response, url, filename)` — video MIME, or a video extension with a
  generic MIME.
* `page_url(target, back)` / `asset_url(target)` — build the proxied URLs.
* `_local_back(value)` — accepts a local path or an allowed source URL as a back
  target.
* `_first_srcset(value)` — first candidate from a srcset.
* `_rewrite_css(text, base_url)` — rewrites `url()`/`@import` to proxied asset
  URLs, blanking disallowed ones.
* `rewrite_page(data, base_url, charset)` — the sanitiser: parse; drop scripts,
  styles, iframes, forms' actions (later re-pointed), event handlers, inline
  styles; rewrite links to `page_url`, images to `asset_url`, `<video>` to a
  "Save this video" link; strip `<audio>`. Returns `(title, body_html)`.
* `fetch_page(url)` — opens, decides page vs video, returns either
  `(title, body_html, final_url)` or the dict from `capture_video`.
* `capture_video(response, url, filename, data)` — hashes the bytes and inserts
  into `epilepsy` with `lzma.compress(data)`; an `IntegrityError` means "already
  in the library" and is reported as `saved: False` rather than an error.
* `fetch_asset(url)` — images/fonts pass through, CSS is rewritten; anything
  else raises.
* `browser_context(source, target_url, back)` — the shell's context
  (`source_name`, `source_url`, `display_url`, `back_href`).

### 3.17 `epilepscreen/templatetags/epilepscreen_fmt.py` (61 lines)

* `clock(seconds)` — `7.4 → "0:07.4"`, for hazard timestamps.
* `kind_label(kind)` — event kind → label.
* `attrs(dict)` — `{"flash_rate": 15.0}` → `"flash_rate 15.0"` for the
  measurement column.
* `rupees(paise)` — the receipt filter: `49900 → "₹499"`, `499450 →
  "₹4,994.50"`. Delegates to `money.format_paise` so grouping is defined once.
  `money = rupees` is kept as an alias so older templates keep rendering.
  (Before the rupee change this filter was `money(cents)` and printed `$`.)

### 3.18 `epilepscreen/management/commands/`

**`analyze_media.py`** — `python manage.py analyze_media <path> [--hash N] [--fps 15]`.
`add_arguments` defines them; `handle` runs `analyze_video_file`, optionally
`save_events`/`save_analysis`, and prints the profile as JSON (`is_safe`,
`risk_flags`, `stored_events`, `summary`, `events`). The CLI way to demonstrate
the detector without the web UI.

**`ingest_media.py`** — bulk import with a thread pool.

* `iter_media_files(directory, recursive=False, extensions=None)` — yields known
  media paths; pure, no database.
* `ingest_file(path, category=None, auto_category=False, do_analyze=False)` —
  reads the file, refuses > 100 MB, `sha256` → 15-hex hash, optional category
  probe, `lzma.compress`, one INSERT, then optional screening. Returns
  `(hash, title, status)` where status is a short human string ("stored",
  "duplicate: already stored", "skipped: over 100MB", …). Opens its own
  connection per call so threads are safe.
* `Command` — parses `--recursive --workers --category --auto-category --analyze
  --extensions` and runs a `ThreadPoolExecutor`, printing a per-file line and a
  summary.

**`make_samples.py`** — writes the five demo clips.

* `Clip` — name + frames + fps holder.
* `_solid(height, width, rgb)` / `_stripes(height, width, bar, a, b)` — frame
  builders with NumPy.
* `build_clips(width, height, fps)` — calm ramp, strobe, red flash, stripes,
  colour sweep.
* `Command.handle` — writes each clip with `cv2.VideoWriter` (`mp4v`), then calls
  `_to_h264` when `ffmpeg` is on PATH (browsers cannot decode `mp4v`).
* `_to_h264(ffmpeg, path)` — `ffmpeg -c:v libx264 -pix_fmt yuv420p -movflags
  +faststart`, replacing the file in place; on failure it deletes the temp file
  and warns.

**`spend_report.py`** — `python manage.py spend_report [--limit 20] [--email x]`.

* `_console_safe(text)` — returns the string with `₹` swapped for `Rs. ` when the
  console's encoding cannot carry it. A `cmd.exe` window defaults to cp1252, and
  a `UnicodeEncodeError` from a report is a bad way to discover that.
* `Command.handle` — one plain SQL read of `customer_spend` (see §4.7), printed as
  a table with the total per email and a grand total. `--email` narrows it to one
  address. This is the command to run during the demonstration: it prints exactly
  what the checkout stored.

### 3.19 `photosensitive/` — the detector

**`config.py` (27 lines)** — `DEFAULTS` dict: `flash_delta 40.0`, `flash_window
10`, `flash_limit 3`, `red_floor 0.25`, `red_window 15`, `color_threshold 0.4`,
`spatial_contrast 0.3`, `spatial_threshold 0.15`, `pattern_move_threshold 0.1`.
`get(cfg, key)` — override or default. Every consumer reads through it, which is
why one request can re-tune the detector.

**`temporal.py` (91 lines)**

* `relative_luminance(rgb)` — WCAG linearisation then
  `0.2126R + 0.7152G + 0.0722B`; returns an `(H, W)` float array in 0–1.
* `mean_luminance(rgb)` — that array's mean × 255, so thresholds are in 0–255.
* `classify_flicker(luminances, flash_delta, window, limit)` — the sliding-window
  rule ("limit flashes inside window frames"). Used by the unit tests and
  available as an aggregate check; `analyze_frames` flags per frame instead, so
  it can report *where* the flashes were.
* `red_coverage(rgb)` — fraction of pixels that are saturated red with real
  luminance (`r/(r+g+b) ≥ 0.8`, `r > 60`, `g < 120`, `b < 120`).
* `classify_red_flash(coverages, floor, window)` — a red frame preceded *and*
  followed by a non-red frame within the window. Same status as
  `classify_flicker`: a whole-sequence boolean, used by tests.
* `mean_color_delta(prev, curr)` — mean per-pixel Euclidean RGB distance on
  0–1 normalised frames (range 0…~1.73).
* `classify_color_transition(deltas, threshold)` — any delta ≥ threshold; again a
  whole-sequence boolean used by tests.

**`spatial.py` (64 lines)**

* `luminance_map(rgb)` — alias of `relative_luminance`.
* `spatial_pattern_score(lum, contrast=None)` — on up to 24 sampled rows, finds
  edges with `|ΔL| > contrast`, and counts pixels between consecutive edges whose
  signs alternate. Returns covered/total in 0–1: stripes and checkerboards score
  high, flat frames and noise score low.
* `pattern_change(prev_lum, curr_lum)` — mean absolute difference of two
  luminance maps.

**`analyzer.py` (230 lines)**

* `HazardEvent` dataclass — `kind`, `start_time`, `end_time`, `attributes`;
  `duration` property.
* `RiskProfile` dataclass — verdict, flags, the three curves, `fps`,
  `frame_count`; properties `duration`, `counts`, `max_flash_rate`; methods
  `summary()` (JSON-ready statistics) and `to_dict()` (summary + events).
* `_group_runs(flags)` — boolean list → inclusive `(start, end)` index runs.
* `analyze_frames(frames, fps=30.0, cfg=None)` — the whole algorithm in one
  function: measure every frame (luminance map, mean luminance, red coverage,
  colour delta, spatial score, pattern change), apply thresholds, flag frames,
  group runs into events per detector, sort, and build the `RiskProfile`. Refuses
  fewer than two frames — with one frame there is nothing to compare.
  * `_add(kind, flags, attrs_fn)` — turns a flag list into events.
  * `_flash_attrs(a, b)` — `brightness_diff`, `flash_rate` (transitions per
    second), `flashes_per_second` (half of that).
  * `_red_attrs(a, b)` — `coverage`, `duration_s`.
  * `_color_attrs(a, b)` — `max_delta`, `duration_s`.
  * `_spatial_attrs(a, b)` — `coverage`, `spatial_frequency`, `contrast`,
    `duration_s`.
  * `_move_attrs(a, b)` — `speed`, `duration_s`.

**`analyze_video.py` (106 lines)** — the only file that imports OpenCV, and it
imports it inside functions so the rest of the package tests without a build.

* `_source_fps(cap, fallback)` — container fps with guards (0, NaN, > 480).
* `source_frame_rate(path, fallback)` — opens, reads, closes.
* `_read_frames(path, target_fps, max_dimension=480)` — subsamples by
  `step = round(src_fps / target_fps)`, BGR→RGB, downscales so the long edge is
  ≤ 480 px, caps at 20 000 frames, always releases the capture.
* `effective_fps(path, target_fps)` — `src_fps / step`. This is the number the
  timestamps must use.
* `analyze_video_file(path, target_fps=15, cfg=None)` — frames + effective fps →
  `analyze_frames`. Raises `ValueError` when fewer than two frames decode
  (unsupported codec, audio-only, corrupt file).

### 3.20 Tests

| File | Covers |
| --- | --- |
| `epilepscreen/tests.py` (515 lines) | The real pipeline against a temporary database: home, browse search/category, six upload cases, screening + storage + timestamps, sensitivity parsing, detector integration, streaming (200/206/416/404), the rupee catalogue, the demo cart and checkout, the per-email total, health, admin. Helpers `_write_clip`, `_solid`, `clip_bytes(kind)`, `store_video(raw)`, `upload_file(raw)`. |
| `epilepscreen/test_media.py` | Content types, category suggestion, `probe_media` on a generated clip. |
| `epilepscreen/test_ingest.py` | File discovery, insert parameters, deterministic content hash, duplicate handling, size skip, auto category, missing file. |
| `photosensitive/tests/test_luminance.py` | Black = 0, white = 1, green brighter than blue, map matches the function. |
| `photosensitive/tests/test_flicker.py` | Steady video is not flicker, alternating frames are, one flash is not, thresholds are configurable. |
| `photosensitive/tests/test_color.py` | Red coverage, red flash needs a transition in *and* out, sustained red is not a flash, colour deltas. |
| `photosensitive/tests/test_spatial.py` | Flat frame = 0, stripes high, noise low. |
| `photosensitive/tests/test_movement.py` | Identical maps = 0, moving stripes > 0, bounded. |
| `photosensitive/tests/test_analyzer.py` | Steady = safe, strobe → flicker with exact timestamps, red flash, stripes, fps scaling, too-few-frames error. |
| `photosensitive/tests/test_analyze_video.py` | Decoder path with a monkeypatched reader. |
| `photosensitive/tests/test_sampling.py` | Real encoded clips: container fps, effective fps per step, alternating frames not lost to aliasing, events inside the analysed span, calm clip safe, unreadable file raises. |
| `scripts/qa_screens.py` | Not a test suite but the browser gate: drives the site with Playwright, asserts status codes, expected text, overlay attachment, decoded duration, timeline segments, seeking, the demo label, the receipt; writes 19 screenshots to `qa/`. |

### 3.21 Templates in detail

| Template | Blocks / structure |
| --- | --- |
| `base.html` | `title`, `description`, `head`, `banner`, `body_class`, `content`, `dialogs`, `scripts`; skip link; nav with cart count; message stack; footer. |
| `home.html` | Hero (eyebrow, headline, sentence, two buttons, 4:3 photo plate), stat strip, three numbered steps, "Recently added" grid or empty state, store teaser + pack list. |
| `browse.html` | Page head with counts, search form + category chips, `.library-grid` of cards (index, status chip, title, kind labels, date) or an empty state that distinguishes "nothing matches" from "library is empty". |
| `upload.html` | Form (title, category with "detect automatically", file, "screen it now" checkbox) and a side column with the photo plus "what the upload does". |
| `player.html` | Breadcrumbs, head with chips and screened-at, `.stage` video, timeline, hazard table, `aside.controls` (guard toggle, dim slider, padding slider, next hazard, verdict, per-kind counts, re-screen form, report link), embedded event JSON. |
| `screening.html` | Stat strip (windows, kinds, fps, verdict), "detectors that fired", "every window", method list, limitations block. |
| `store.html` | Banner override, hero with price counter, range list + order form (posts to `add_to_cart`), sources grid, upload section, sample report table, recently captured list, buy bar, source-browser `<dialog>`. |
| `checkout.html` | `DEMO CHECKOUT — NO REAL PAYMENT` band, line items with ₹ prices and remove forms, order summary with email field and confirm button, fine print about `payment_method = 'demo'`. |
| `order_confirmation.html` | Receipt: stamp, order number, date, email, rupee line items, simulated total, the stored per-email total from `customer_spend`, "not a financial document" note, three exit buttons. |
| `store_browser.html` | Standalone reader shell: source name, URL, back/store buttons, sanitised body, captured/error states, `postMessage` back to the parent. |
| `partials/_status_chip.html` | One chip from `video.rating` + `video.event_count`. |

---

## 4. Every SQL statement and what it is for

All application SQL lives in four files: `views.py`, `analysis_store.py`,
`store_browser.py` and the `spend_report` management command. Migrations contain
the DDL. Values are **always** passed as `%s` parameters — Django rewrites them to
`?` for SQLite and to `%s` for MySQL.

### 4.1 Schema (DDL) — `migrations/0003_sql_tables.py`

SQLite:

```sql
CREATE TABLE IF NOT EXISTS epilepsy (
    hash INTEGER PRIMARY KEY,
    time_uploaded DATETIME NOT NULL,
    title TEXT NOT NULL,
    category VARCHAR(40),
    content_type VARCHAR(60),
    movie BLOB
);
CREATE TABLE IF NOT EXISTS hazard_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_hash INTEGER NOT NULL,
    kind VARCHAR(40) NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    attributes TEXT,
    created_at DATETIME NOT NULL
);
CREATE TABLE IF NOT EXISTS analysis (
    video_hash INTEGER PRIMARY KEY,
    is_safe BOOL NOT NULL,
    risk_flags TEXT,
    checked_at DATETIME NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hazard_video ON hazard_event (video_hash);
```

MySQL (same shape, MySQL types):

```sql
CREATE TABLE IF NOT EXISTS epilepsy (
    hash BIGINT UNSIGNED NOT NULL PRIMARY KEY,
    time_uploaded DATETIME NOT NULL,
    title TEXT NOT NULL,
    category VARCHAR(40) NULL,
    content_type VARCHAR(60) NULL,
    movie LONGBLOB
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS hazard_event (
    id INT AUTO_INCREMENT PRIMARY KEY,
    video_hash BIGINT UNSIGNED NOT NULL,
    kind VARCHAR(40) NOT NULL,
    start_time FLOAT NOT NULL,
    end_time FLOAT NOT NULL,
    attributes JSON,
    created_at DATETIME NOT NULL,
    INDEX idx_video (video_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS analysis (
    video_hash BIGINT UNSIGNED NOT NULL PRIMARY KEY,
    is_safe BOOL NOT NULL,
    risk_flags JSON,
    checked_at DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

Why the two dialects: `BLOB` vs `LONGBLOB` (a ≥ 4 GB vs 64 KB blob), `REAL` vs
`FLOAT`, `TEXT` vs `JSON`, and `AUTOINCREMENT` vs `AUTO_INCREMENT`. Everything
uses `IF NOT EXISTS` so a database already built by the old `sql.py` is left
untouched. `drop_tables()` reverses in child-first order.

The store tables are created by Django from the models, not by hand. The one that
matters for the money path is `customer_spend` (migration `0005`); the SQL MySQL
receives is:

```sql
CREATE TABLE `customer_spend` (
    `email` varchar(254) NOT NULL PRIMARY KEY,
    `total_paise` int NOT NULL,
    `order_count` int NOT NULL,
    `currency` varchar(3) NOT NULL,
    `first_order_at` datetime(6) NULL,
    `last_order_at` datetime(6) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX `spend_total_idx` ON `customer_spend` (`total_paise` DESC);
CREATE INDEX `spend_last_idx`  ON `customer_spend` (`last_order_at`);
```

SQLite gets the same columns with `INTEGER`/`TEXT`-style types and the email as
the primary key. Integer paise, no floats, and the address itself as the key.

### 4.2 `epilepsy` — the video library

**1. List / search / filter**

```sql
SELECT hash, time_uploaded, title, category, content_type
FROM epilepsy
WHERE movie IS NOT NULL
  [AND LOWER(category) = LOWER(%s)]
  [AND LOWER(title) LIKE LOWER(%s)]
ORDER BY time_uploaded DESC, hash DESC
LIMIT %s OFFSET %s;
```

Used by `VideoStore.get_videos` → home page (limit 6) and `browse`
(limit 60). `movie IS NOT NULL` hides half-written rows. `LOWER()` on both sides
makes the search case-insensitive on MySQL's binary-ish collations and on
SQLite. The blob is deliberately not selected — the library page would otherwise
transfer every video.

**2. Fetch with blob**

```sql
SELECT hash, time_uploaded, title, category, content_type, movie
FROM epilepsy WHERE hash = %s;
```

`get_video_by_hash` — streaming (`stream_video`) and screening
(`materialise_video`) are the only callers.

**3. Fetch metadata only**

```sql
SELECT hash, time_uploaded, title, category, content_type
FROM epilepsy WHERE hash = %s;
```

`get_video_meta` — the player, report page and `/analyze` lookup, none of which
need the bytes.

**4. Count**

```sql
SELECT COUNT(*) FROM epilepsy WHERE movie IS NOT NULL;
```

Home stat, store footer, tests.

**5. Categories with counts**

```sql
SELECT category, COUNT(*)
FROM epilepsy
WHERE movie IS NOT NULL AND category IS NOT NULL
GROUP BY category
ORDER BY category;
```

The filter chips; the count is shown next to each name.

**6. Insert**

```sql
INSERT INTO epilepsy (hash, time_uploaded, title, category, content_type, movie)
VALUES (%s, %s, %s, %s, %s, %s);
```

Three callers, one statement shape:

* `upload_video` — `lzma.compress(raw)`;
* `store_browser.capture_video` — raw downloaded bytes, `IntegrityError` means
  "already in the library";
* `ingest_media.ingest_file` — `lzma.compress(raw)` from disk.

**7. Duplicate check**

```sql
SELECT title FROM epilepsy WHERE hash = %s;
```

`hash_exists` — returns the existing title so the message can say *which* file
was already there. The `INSERT` would also fail on the primary key; this query
exists to give a friendly answer instead of an error.

**8. Update category**

```sql
UPDATE epilepsy SET category = %s WHERE hash = %s;
```

`set_category` — correct a category after upload. Not called by a view today; the
admin and `ingest_media --category` are how categories are actually changed.

**9. Delete a video and its results**

```sql
DELETE FROM hazard_event WHERE video_hash = %s;
DELETE FROM analysis     WHERE video_hash = %s;
DELETE FROM epilepsy     WHERE hash       = %s;
```

`delete_video`, inside one `transaction.atomic()` so a partial delete cannot
leave orphan events. Child rows go first because there is no `ON DELETE CASCADE`
on the hand-written tables.

### 4.3 `analysis` — one verdict per video

**10. Batch read**

```sql
SELECT video_hash, is_safe, risk_flags, checked_at
FROM analysis
WHERE video_hash IN (%s, %s, ...);
```

`_analysis_rows(hashes)` — one query for a whole page of cards, not one per row.
The placeholder list is built from the number of hashes; the values are still
parameters.

**11. Write / replace**

```sql
REPLACE INTO analysis (video_hash, is_safe, risk_flags, checked_at)
VALUES (%s, %s, %s, %s);
```

`save_analysis`. `REPLACE` = delete-then-insert on the primary key, so re-screening
updates the verdict instead of stacking rows. (SQLite accepts `REPLACE INTO` as an
alias for `INSERT OR REPLACE`.) `risk_flags` is `json.dumps(...)`; MySQL's JSON
column validates it, SQLite stores it as text, and `_loads()` handles both.

**12. Delete**

```sql
DELETE FROM analysis WHERE video_hash = %s;
```

`clear_analysis` and `delete_video`.

### 4.4 `hazard_event` — the timestamps

**13. Batch statistics**

```sql
SELECT video_hash, kind, COUNT(*)
FROM hazard_event
WHERE video_hash IN (%s, ...)
GROUP BY video_hash, kind;
```

`_event_stats`. Grouped by kind rather than string-concatenated, because
`GROUP_CONCAT(DISTINCT ...)` is not portable across the two engines; the
aggregation happens in Python.

**14. Ordered event list**

```sql
SELECT kind, start_time, end_time, attributes
FROM hazard_event
WHERE video_hash = %s
ORDER BY start_time ASC;
```

`screening_report` — feeds both the player page (server-rendered table and the
embedded JSON) and the report page. `ORDER BY start_time` is what makes the
"next hazard" button and the timeline left-to-right.

**15. Replace all events for a video**

```sql
DELETE FROM hazard_event WHERE video_hash = %s;
INSERT INTO hazard_event
    (video_hash, kind, start_time, end_time, attributes, created_at)
VALUES (%s, %s, %s, %s, %s, %s);   -- executemany, one row per event
```

`save_events`, inside `transaction.atomic()`. Delete-then-insert is the simplest
correct way to re-screen: no stale rows survive, no duplicates accumulate, and
the whole swap is atomic. `executemany` sends one statement with N parameter
tuples instead of N round trips.

**16. Delete**

```sql
DELETE FROM hazard_event WHERE video_hash = %s;
```

`clear_analysis`, `delete_video`.

### 4.5 `customer_spend` — the running total per email

**17. Read the total (management command)**

```sql
SELECT email, total_paise, order_count, currency, last_order_at
FROM customer_spend
[WHERE email = %s]
ORDER BY total_paise DESC
LIMIT %s;
```

`spend_report` — the one hand-written query against this table. `--email` adds the
`WHERE`; the limit is always bound as a parameter.

**18. Create the first row for an address (ORM)**

```sql
INSERT INTO customer_spend
    (email, total_paise, order_count, currency, first_order_at, last_order_at)
VALUES (%s, %s, 1, 'INR', %s, %s);
```

`orders.record_spend` via `get_or_create`. The email is the primary key, so the
database itself refuses a second row for the same address.

**19. Add to an existing total (ORM, with `F()`)**

```sql
UPDATE customer_spend
SET total_paise = total_paise + %s,
    order_count = order_count + 1,
    last_order_at = %s
WHERE email = %s;
```

This is what `F('total_paise') + amount` compiles to. The arithmetic runs **in
the database**, so two checkouts for the same email arriving at the same time add
up instead of overwriting each other. A plain `row.total_paise += amount` in
Python would be a read-modify-write race.

`select_for_update()` is deliberately *not* used: SQLite does not support it
(`NotSupportedError`), and the `F()` update plus the primary key already give the
right result on both engines.

### 4.6 Health

**20.**

```sql
SELECT 1;
```

`health` — the cheapest possible round trip that proves the connection, the
credentials and the schema's database all work. Returns 200/503.

### 4.7 ORM queries (Django generates the SQL)

| Where | Equivalent SQL |
| --- | --- |
| `_products()` | `SELECT * FROM store_products WHERE active = 1 ORDER BY price_paise ASC` |
| `_cart_context` | `SELECT * FROM store_products WHERE id IN (...) AND active = 1 ORDER BY price_paise` |
| `add_to_cart` / `product_detail` | `SELECT * FROM store_products WHERE id = %s AND active = 1 LIMIT 1` |
| `orders.create_demo_order` | `INSERT INTO purchases (product_id, email, payment_method, card_last4, status, created_at, completed_at, amount_paise, currency) VALUES (..., 'demo', '', 'completed', ..., 'INR')` per item |
| `orders.record_spend` | the INSERT/UPDATE pair in §4.5 |
| `order_confirmation` | `SELECT * FROM purchases JOIN store_products ... WHERE id IN (...)` (`select_related`) |
| `order_confirmation` spend | `SELECT * FROM customer_spend WHERE email = %s LIMIT 1` |
| `_store_context` recent order | `SELECT * FROM purchases JOIN store_products WHERE id = %s LIMIT 1` |

The ORM is used for the store because those models are ordinary Django models;
the screening tables are queried with hand-written SQL because that SQL is part
of what the project demonstrates.

### 4.8 Statements that look like they should exist but do not

* No `UPDATE hazard_event` — events are replaced wholesale, never edited.
* No `SELECT *` on `epilepsy` — the blob is always named explicitly or excluded.
* No `DROP`/`TRUNCATE` in application code; only the migration's reverse.
* No `LIKE` with user input concatenated into the string — always a parameter.
* No `SUM()` on the request path — the total is read from `customer_spend`, not
  recomputed from `purchases`. `SUM(amount_paise)` appears only in the migration
  that back-filled the table and in `orders.spend_summary()`.
* No `SELECT ... FOR UPDATE` — see the note in §4.5; `F()` plus the primary key
  does the job on both engines.

---

## 5. How the database works

### 5.1 Two engines, one schema

`settings.DATABASES['default']` is chosen at import time from `DB_ENGINE`:

```python
DB_ENGINE = os.environ.get('DB_ENGINE', 'sqlite').strip().lower()
if DB_ENGINE == 'mysql':   # django.db.backends.mysql, utf8mb4, STRICT_TRANS_TABLES
else:                      # django.db.backends.sqlite3, BASE_DIR / 'db.sqlite3'
```

Everything above that line is engine-agnostic:

* raw SQL uses `%s` placeholders (Django's cursor wrapper converts them);
* `REPLACE INTO`, `LOWER()`, `IN (...)`, `GROUP BY`, `LIMIT/OFFSET` all exist in
  both dialects;
* no MySQL-only function is used in application code;
* JSON columns are written as `json.dumps` text and read through `_loads()`, so
  SQLite's `TEXT` and MySQL's `JSON` behave the same from Python's side.

### 5.2 Who owns which table

| Owner | Tables | Created by | Written by |
| --- | --- | --- | --- |
| Django ORM | `videos`, `store_products`, `purchases`, `customer_spend`, `store_subscriptions`, `video_categories`, `video_formats`, `video_purchases` | `0001_initial` (`customer_spend`: `0005`) | ORM |
| Hand-written SQL | `epilepsy`, `hazard_event`, `analysis` | `0003_sql_tables` (per-vendor DDL) | `views.VideoStore`, `analysis_store`, `store_browser`, `ingest_media` |

The three SQL tables also have `managed = False` models, which is a
documentation device: the admin can list them, `makemigrations --check` stays
silent, and `models.py` describes the schema the SQL actually creates.

`customer_spend` is the one table whose contents are derived from another table.
It is not a cache that can be rebuilt lazily: it is written in the same
transaction as the order lines, so reading it always matches the orders that
exist.

### 5.3 The upload blob

Raw upload → `sha256(raw).hexdigest()[:15]` → `int(..., 16)` → `hash`, the
primary key. Then `lzma.compress(raw)` → `movie`.

Consequences, all intentional:

* **Dedupe for free.** Identical bytes produce the identical hash, so the
  primary key rejects a second copy. `hash_exists` turns that into a friendly
  message before the insert is even attempted.
* **Compression is real.** Video does not compress much, but screenshots, short
  clips and screen recordings often do, and the cap is on the *upload*, not the
  stored size.
* **Streaming decompresses per request.** `stream_video` decompresses the whole
  blob into memory to serve a range. That is why the cap is 100 MB — a
  production system would store files on disk or object storage and seek.
* **No filename on disk.** Nothing but a temporary file exists during analysis,
  and `materialise_video`'s `finally` deletes it even when decoding throws.

### 5.4 Verdicts vs events

`analysis` answers "was this screened, and what did it conclude?"
`hazard_event` answers "where?". A video that was screened and came back clean
has an `analysis` row and zero `hazard_event` rows — which is exactly how
"never screened" (`no analysis row`) is distinguished from "screened, safe". That
distinction drives the `unknown` / `safe` / `caution` / `risk` chips.

### 5.5 Transactions

* Django runs in **autocommit** mode, so a single statement is committed
  immediately and no explicit `connection.commit()` is needed (or allowed inside
  an atomic block — the code used to call it and raised
  `TransactionManagementError` under test).
* `save_events` — `transaction.atomic()` around the delete + `executemany`.
* `delete_video`, `clear_analysis` — `transaction.atomic()` around the child
  deletes.
* `orders.create_demo_order` — `transaction.atomic()` around the purchase rows
  **and** the `customer_spend` update, so a failure part-way leaves neither a
  half order nor an inflated total.
* `orders.record_spend` — a nested `atomic()` around its `get_or_create`, which
  gives that insert a savepoint: if two checkouts race for the same new address,
  the loser retries without poisoning the order transaction.
* Tests wrap each case in its own transaction and roll it back, which is why the
  test suite never touches `db.sqlite3`.

### 5.6 Indexes

| Index | On | Why |
| --- | --- | --- |
| primary key | `epilepsy.hash` | every lookup, and the dedupe guarantee |
| `idx_hazard_video` / `idx_video` | `hazard_event.video_hash` | every event query filters by it |
| `store_active_price_idx` | `store_products(active, price_paise)` | catalogue order |
| `purchase_*` | `purchases(email / status / product / completed_at)` | admin filtering, and the migration's `GROUP BY email` back-fill |
| `spend_total_idx` | `customer_spend(total_paise DESC)` | the report's `ORDER BY total_paise DESC` |
| `spend_last_idx` | `customer_spend(last_order_at)` | "who ordered recently" |
| `video_*` | `videos(...)` | the legacy model's own indexes |

The library's `ORDER BY time_uploaded DESC` has no index; at a few hundred rows
that is fine, and it is listed as a known weak point.

### 5.7 Migrations

```
0001_initial              ORM tables
0002_seed_store_products  four sample packs (dollar cent prices)
0003_sql_tables           epilepsy / hazard_event / analysis (per vendor)
0004_…                    unmanaged model state only, no DDL
0005_inr_prices_and_…     *_cents → *_paise, INR defaults, rupee prices,
                          customer_spend + back-fill from purchases
```

`python manage.py migrate` builds a working database on either engine;
`python sql.py` is the same call under an older name. `makemigrations --check`
is part of the test routine to prove no model change is missing a migration.

---

## 6. The demonstration order ("cost") path

The arithmetic is `price_paise × count`, summed per email. What exists is a
working order record plus a running total, and the whole path is deliberately
honest about being fake.

### 6.1 The catalogue, in rupees

`store_products` is seeded by migration `0002` (in dollars) and re-priced by
`0005` to rupee values:

| Pack | Price | Stored as |
| --- | --- | --- |
| Screening pack | ₹499 | `49900` |
| Music video pack | ₹799 | `79900` |
| Premium shelf | ₹1,999 | `199900` |
| Research package | ₹3,999 | `399900` |

Prices are **integer paise** — never floats — so a total is exact. `_money()` and
the `rupees` filter only format for display, using Indian digit grouping
(`₹1,00,000`, not `₹100,000`). `money.format_paise` is the single implementation;
`money.rupees_to_paise` goes the other way for anything typed by a human.

### 6.2 The cart

Held in the Django session (`'cart'` = list of product ids), not in the database.
`add_to_cart` appends, `remove_from_cart` filters, `_cart_context` resolves ids
against the live catalogue (so a deleted product silently drops out) and sums
`price_paise`.

Why the session: a cart is per-visitor ephemeral state, and Django's session
store already gives that with a signed cookie. No `cart_items` table, no user
accounts.

### 6.3 The checkout

`POST /checkout/` takes exactly one field, `email`:

1. cart must be non-empty, else redirect back to the store with a message;
2. `django.core.validators.validate_email` — the only validation;
3. `orders.create_demo_order(email, items)` runs one transaction that does two
   things:
   * one `Purchase` per item — `payment_method='demo'`, `status='completed'`,
     `amount_paise=product.price_paise`, `currency='INR'`, `card_last4=''`;
   * `orders.record_spend(email, total)` — the `customer_spend` row: first order
     inserts it, later orders `UPDATE ... SET total_paise = total_paise + %s`
     with `F()`, plus `order_count + 1` and a new `last_order_at`;
4. clear the session cart, remember the purchase ids, redirect to `/order/`.

`completed_at` uses `timezone.now()` — a naive `datetime.now()` triggers a Django
warning because `USE_TZ = True`.

The total is stored, not derived. `customer_spend` answers "how much has this
address spent" with a primary-key lookup instead of a `GROUP BY` over every order
it ever placed, and it can never disagree with `purchases` because both writes
share a transaction.

### 6.4 What is deliberately absent

* No card number, expiry, CVC, or holder-name field exists anywhere in the HTML;
  a test asserts the checkout page contains none of those strings.
* No Stripe/Razorpay/PayPal client, no API key, no outbound payment request.
* No invoice email, no PDF, no order fulfilment.
* The page carries a `DEMO CHECKOUT — NO REAL PAYMENT` band, the button says
  *Confirm demo order*, and the receipt says in plain text that it is not a
  financial document.
* No GST, tax, discount or refund logic: a demo total is `sum(price_paise)`,
  full stop.

### 6.5 Reading the money back

Three ways, all reading the same rows:

1. **The receipt** — `order_confirmation` sums `amount_paise` over the session's
   purchases (or `?order=<pk>`), renders each line through `rupees`, and shows the
   stored per-email total from `customer_spend`:
   *Total spend stored for someone@example.com — ₹1,497 across 3 demonstration
   orders · one row in `customer_spend`.*
2. **The command** — `python manage.py spend_report` prints every address, its
   order count, its total and its last order, plus a grand total, from one SQL
   `SELECT` on `customer_spend`. `--email` narrows it to one row.
3. **The admin** — *Customer spend*, ordered by `-total_paise`, all fields
   read-only, totals rendered as ₹ by the model's `total_display` property.

That is the entire "accounts" side of the project: integer paise in, formatted
string out, one row per item and one row per address.

---

## 7. How the MySQL connection works

### 7.1 What Django actually uses

With `DB_ENGINE=mysql`, `settings.DATABASES['default']` is:

```python
'ENGINE': 'django.db.backends.mysql',
'NAME': os.environ.get('DB_NAME', 'darsh'),
'USER': os.environ.get('DB_USER', 'root'),
'PASSWORD': os.environ.get('DB_PASSWORD', ''),
'HOST': os.environ.get('DB_HOST', '127.0.0.1'),
'PORT': os.environ.get('DB_PORT', '3306'),
'OPTIONS': {'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'"},
'TEST': {'CHARSET': 'utf8mb4', 'COLLATION': 'utf8mb4_unicode_ci'},
```

Django's MySQL backend imports **`MySQLdb`**, i.e. the `mysqlclient` package:

```
django.db.backends.mysql.base → import MySQLdb as Database
```

If `mysqlclient` is not installed you get, at the first query:

```
django.core.exceptions.ImproperlyConfigured: Error loading MySQLdb module.
Did you install mysqlclient?
```

which is exactly what happened on this machine before the SQLite path existed.
`mysqlclient` needs a C compiler on Windows; `pip install mysqlclient` usually
finds a wheel for CPython 3.12. `mysql-connector-python` is **not** used by the
Django backend (it has its own experimental backend and is not configured here).

### 7.2 Connection lifecycle

1. The first query in a request calls `django.db.connection`, which lazily opens
   a `MySQLdb` connection with the parameters above.
2. Django keeps that connection for the life of the request/thread
   (`CONN_MAX_AGE` is unset here, so it is closed at the end of each request).
3. Autocommit is on. `transaction.atomic()` temporarily turns it off, issuing
   `START TRANSACTION` … `COMMIT`/`ROLLBACK`.
4. `init_command` runs `SET sql_mode='STRICT_TRANS_TABLES'` on connect, so MySQL
   rejects truncated or invalid values instead of silently coercing them — the
   safer behaviour for a database holding a primary key derived from a hash.
5. `charset=utf8mb4` matters for titles with emoji or non-Latin text.

### 7.3 Why the same SQL runs on both engines

Django's cursor is a thin wrapper. For MySQL it passes `%s` through (`format`
style is MySQLdb's paramstyle). For SQLite, `SQLiteCursorWrapper.execute`
rewrites `%s` → `?` (and `%%` → `%`) before handing the string to `sqlite3`.
Application code therefore writes one dialect of placeholders, and both engines
receive correctly-escaped parameters — never string interpolation.

### 7.4 What "raw SQL" means here, and what changed

Earlier versions opened a **second, independent** connection:

```python
mydb = mysql.connector.connect(**DB_CONFIG)   # old sql.py / views
```

That had three problems: two connections with two transaction states, no SQLite
support at all, and tests could only fake it with `MagicMock`. Now every query
goes through `django.db.connection` (`get_db_connection()` is just a named
accessor), so:

* one connection pool, one transaction;
* `TestCase` gives a real temporary database and rolls it back;
* the same code path is exercised in tests and in production;
* `DB_ENGINE=sqlite` needs no server at all, which is why the project runs on a
  school machine.

### 7.5 Switching to MySQL

```powershell
pip install mysqlclient
# .env
DB_ENGINE=mysql
DB_NAME=darsh
DB_USER=root
DB_PASSWORD=...
DB_HOST=127.0.0.1
DB_PORT=3306
python manage.py migrate
```

`migrate` creates the ORM tables and runs `0003_sql_tables`, which takes the
MySQL branch of the DDL (`LONGBLOB`, `JSON`, `AUTO_INCREMENT`, `ENGINE=InnoDB`,
`utf8mb4`). If the schema already exists from the old `sql.py`, every statement
is `IF NOT EXISTS`, so nothing is dropped or recreated. `0005` then renames the
money columns, sets the rupee prices, creates `customer_spend` and back-fills it
with a single `GROUP BY email` aggregate over `purchases`.

Checking the total against the server, without Django:

```sql
SELECT email, total_paise, order_count, last_order_at
FROM customer_spend
ORDER BY total_paise DESC;

-- does the stored total agree with the order lines?
SELECT p.email, s.total_paise AS stored, SUM(p.amount_paise) AS recomputed
FROM purchases p
JOIN customer_spend s ON s.email = p.email
GROUP BY p.email, s.total_paise
HAVING stored <> recomputed;      -- must return no rows
```

That second query is the reconciliation check; run it after a demonstration and
an empty result means the aggregate table and the order lines agree.

### 7.6 Failure modes and what the site does

| Failure | Where it surfaces |
| --- | --- |
| `mysqlclient` missing | `ImproperlyConfigured` on first query — the server will not serve pages |
| Server down / bad password | `django.db.utils.OperationalError`; `/health/` returns 503 with the message; pages that swallow `DatabaseError` still render (empty library, no products) |
| Table missing (`migrate` not run) | `DatabaseError`; `/browse/` shows its empty state, `/analyze/` returns 500 JSON, `/health/` 503 |
| Duplicate hash | `IntegrityError`, caught: upload says "already in the library" |
| Long-running screening | Not a connection issue (each request holds one connection), but a 15-minute guard keeps an upload request from running for hours |

`/health/` is the one endpoint whose job is to answer "is the database
reachable", so it deliberately does **not** swallow the error: it reports it.

---

## 8. Configuration and environment

`.env` (gitignored; `.env.example` is the template):

| Variable | Default | Used by |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | insecure dev fallback | sessions, CSRF |
| `DJANGO_DEBUG` | `1` | settings |
| `DB_ENGINE` | `sqlite` | settings |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` | `darsh` / `root` / — / `127.0.0.1` / `3306` | MySQL only |
| `MAX_UPLOAD_BYTES` | `104857600` | upload validation |
| `ANALYSIS_FPS` | `15` | `analyze_video_file` |

Detector thresholds are **not** environment variables: they live in
`photosensitive/config.py` and are overridden per request through the query
string, which is what makes the sensitivity sliders possible.

---

## 9. Known weak points

1. **Aliasing.** ~15 fps sampling can miss a flash that repeats at exactly that
   rate. Documented on the report page.
2. **Heuristic thresholds.** WCAG-inspired, not clinically validated. Never
   described as protection from seizures.
3. **Blob in the database.** `stream_video` decompresses the whole file per
   range request; fine for 100 MB demo clips, wrong for a real service.
4. **No index on `time_uploaded`.** The library's sort is a scan.
5. **Synchronous screening.** A long file blocks its upload request; there is no
   job queue. The 15-minute cap is the mitigation.
6. **Session cart.** Cleared when the session cookie is lost; no cart table.
7. **`Videos`/`VideoFormat`/`VideoPurchase`/`StoreSubscription`/`VideoCategory`
   are migrated but unused** — the richer schema the project started with.
   Categories live as a text column on `epilepsy` instead.
8. **`customer_spend` is maintained in application code, not by a trigger or a
   generated column.** It is correct because `create_demo_order` writes both
   tables in one transaction; a script that inserted `purchases` rows directly
   would leave the total stale. The reconciliation query in §7.5 is the check.
9. **The stored total is per exact address.** `Student@Example.com` and
   `student@example.com` are two rows; nothing normalises case. Admins see what
   the buyer typed.
10. **Rupee formatting is display-only.** No currency conversion, no rounding
    rules beyond `divmod`, and no locale-aware formatter: `money.group_indian`
    implements the one convention the store needs.
11. **`manage.py spend_report` falls back to `Rs. 499`** on a console whose
    code page cannot encode `₹` (Windows `cmd.exe` default). The web pages are
    unaffected — they are served as UTF-8.
12. **MySQL branch unverified.** Written and reasoned through, but no MySQL server
    was reachable from this machine; only SQLite was exercised end to end. That
    includes `customer_spend`: the table, the `F()` update and the report query
    are portable SQL, but they have only run on SQLite here.
13. **The source browser is a reader, not a browser.** Scripts are stripped, so
    some sources will show a mostly empty page; that is a deliberate safety
    trade-off, not a bug.


