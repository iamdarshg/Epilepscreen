# Epilepscreen — project explanation

Written for the practical exam: what the project does, which Python does the
work, and how to explain each part out loud.

---

## 1. Objective

Photosensitive epilepsy is triggered by flashing lights, red flashes, and
high-contrast moving patterns. Video is the usual delivery method, and there is
no easy way to know whether a file is safe before pressing play.

Epilepscreen takes a video file, measures it frame by frame in Python, and
produces a report of **where** in the timeline the risky moments are. The player
uses that report to dim the picture during those moments.

The project is not a medical device. It is a screening filter that makes the
risk visible and gives the viewer a way to watch more safely.

---

## 2. Why Python

* **OpenCV** (`cv2`) decodes almost any container and gives frame-by-frame access.
* **NumPy** turns a frame into an array, so a whole-image measurement is one
  vectorised expression instead of a loop over pixels.
* **Django** gives routing, templates, an ORM and a database layer without
  writing a web server.
* The same language runs the analysis, the management commands and the web app,
  so there is one place to look when something is wrong.

---

## 3. Libraries

| Library | Used for |
| --- | --- |
| `opencv-python-headless` | Decoding video, resizing frames, reading duration and dimensions |
| `numpy` | Luminance maps, colour deltas, edge detection, statistics |
| `Django` | URLs, views, templates, ORM, migrations, admin |
| `python-dotenv` | Reading `.env` (secret key, database settings) |
| `requests` + `beautifulsoup4` | The store's in-page source browser (server-side fetch and clean-up) |
| `pytest` | Detector unit tests |
| `playwright` (optional) | Browser QA sweep in `scripts/qa_screens.py` |

---

## 4. Modules and responsibilities

```
photosensitive/
  config.py        every threshold in one dict, overridable per request
  temporal.py      luminance, red coverage, colour delta  (pure NumPy)
  spatial.py       luminance map, stripe/pattern score, pattern movement
  analyzer.py      runs all detectors, groups frames into HazardEvents
  analyze_video.py OpenCV decoding + frame subsampling (the only cv2 import)

epilepscreen/
  views.py         SQL layer, screening endpoint, player, demo store
  analysis_store.py writes hazard_event + analysis rows
  media.py         content types, categories, metadata probe
  models.py        ORM models (store) + unmanaged models for the SQL tables
  migrations/      0003 creates the three hand-written-SQL tables
  management/      ingest_media, analyze_media, make_samples
  static/          store.css (design system), pages.css, player.js, overlay widget
```

---

## 5. Core algorithms

### 5.1 Frame extraction (`analyze_video.py`)

```python
cap = cv2.VideoCapture(path)
src_fps = cap.get(cv2.CAP_PROP_FPS)      # e.g. 30
step = max(1, round(src_fps / 15))       # read every 2nd frame
```

Frames are converted BGR → RGB and shrunk so the long edge is 480 px. Shrinking
costs nothing in accuracy for these measurements and makes analysis roughly 20×
cheaper than 1080p.

**Timestamps use the effective rate**, `src_fps / step`, not the rate we asked
for. Getting this wrong shifts every reported time — it was a real bug in an
earlier version of this project.

### 5.2 Luminance (`temporal.py`)

sRGB is not linear, so the WCAG formula is applied per channel:

```
c  = channel / 255
c' = c / 12.92                    if c <= 0.04045
c' = ((c + 0.055) / 1.055) ** 2.4 otherwise
Y  = 0.2126 R' + 0.7152 G' + 0.0722 B'
```

`Y` is 0–1; multiplying by 255 gives the 0–255 scale the thresholds use.

### 5.3 Flash / flicker

For each pair of neighbouring frames, `|mean_luminance[i] - mean_luminance[i-1]|`.
A jump of **≥ 40** units is a flash. Consecutive flagged frames are grouped into
one window, and the window records:

* `brightness_diff` — the biggest jump inside it,
* `flash_rate` — brightness transitions per second,
* `flashes_per_second` — half of that, the figure you compare with the
  "3 flashes per second" guidance.

### 5.4 Red flash

A pixel counts as red when red dominates the sum of channels (`r/(r+g+b) ≥ 0.8`),
red is bright (`r > 60`) and green/blue are low. The fraction of such pixels is
the frame's red coverage; **≥ 25 %** is a red frame. A red run that has a
non-red frame before and after it is a red flash.

### 5.5 Colour transition

Mean per-pixel Euclidean distance between two normalised RGB frames:

```
delta = mean( || rgb[i] - rgb[i-1] || )      # 0 … ~1.73
```

**≥ 0.4** is a colour transition — a hard cut from one saturated colour to
another, which is the pattern that matters for red/blue alternation.

### 5.6 High-contrast pattern

Along sampled scanlines, take the derivative of luminance. Edges with
`|ΔL| > 0.3` are strong. Where two consecutive strong edges have **opposite
signs**, the pixels between them are part of an alternating run — the signature
of stripes or a checkerboard. Coverage is the fraction of sampled pixels inside
such runs; **≥ 15 %** flags a pattern.

### 5.7 Pattern movement

`mean(|lum[i] - lum[i-1]|)` over the whole frame. A large change **while** the
pattern score is already high means the stripes are moving, which is flagged
separately from a stationary pattern.

### 5.8 Grouping into events

`_group_runs()` turns a boolean list into inclusive `(start, end)` index runs.
Each run becomes one `HazardEvent(kind, start/fps, end/fps, attributes)`. That is
the whole reason the player can dim at the right moment: the event carries
seconds, not frame numbers.

---

## 6. Database structure

Three tables are written with hand-written SQL (so the SQL is visible and
explainable); the store uses the Django ORM.

```
epilepsy                      hazard_event                  analysis
--------                      ------------                  --------
hash        BIGINT PK         id          PK                video_hash  PK
time_uploaded DATETIME        video_hash  FK -> epilepsy     is_safe     BOOL
title       TEXT              kind        VARCHAR(40)       risk_flags  JSON
category    VARCHAR(40)       start_time  FLOAT             checked_at  DATETIME
content_type VARCHAR(60)      end_time    FLOAT
movie       BLOB (lzma)       attributes  JSON
                              created_at  DATETIME
```

Store tables (ORM): `store_products`, `purchases`, `customer_spend`,
`store_subscriptions`, `video_categories`, `video_formats`, `videos`,
`video_purchases`.

The two that matter for money:

```
store_products                     purchases                    customer_spend
--------------                     ---------                    --------------
id            PK                   id           PK              email          PK
title         TEXT                 product_id   FK              total_paise    INT
product_type  VARCHAR(50)          email        VARCHAR(254)     order_count    INT
price_paise   INT  (₹499 = 49900)  amount_paise INT             currency       'INR'
active        BOOL                 currency     'INR'           first_order_at DATETIME
                                   payment_method 'demo'        last_order_at  DATETIME
                                   status       'completed'
```

Money is always integer **paise** — ₹499 is `49900` — so no total is ever affected
by floating-point error, and `money.format_paise` renders it as `₹499` with Indian
digit grouping.

`purchases.payment_method` is `'demo'` for every order the site creates — that
column is the record that no real payment happened.

`customer_spend` holds one row per email: the running total, how many orders made
it, and when they were placed. `epilepscreen/orders.py` writes it in the same
transaction as the order lines, using `F('total_paise') + amount` so the addition
happens inside MySQL rather than in Python.

---

## 7. Architecture

```
        browser
           │  upload (multipart)
           ▼
   Django view  ──────────────►  epilepsy table (lzma blob)
           │                            │
           │  run_screening()           │ decompress to temp file
           ▼                            ▼
   photosensitive.analyze_video_file  ── cv2.VideoCapture ──► frames
           │                            │
           │  analyze_frames()          ▼
           │                     NumPy measurements
           ▼
   HazardEvent list ──► hazard_event + analysis tables
           │
           ▼
   player.html  ──►  /events/<hash>/  ──►  player.js  ──►  overlay dims
```

The JavaScript never decides whether a frame is dangerous. It receives
`{kind, start, end}` and compares `video.currentTime` with those numbers.

---

## 8. Sample input and output

Input: `samples/strobe.mp4` — 30 frames, 15 fps, black/white alternating.

`python manage.py analyze_media samples/strobe.mp4`:

```json
{
  "is_safe": false,
  "risk_flags": ["color_transition", "flicker"],
  "summary": {"frames": 30, "fps": 15.0, "duration_s": 2.0, "event_count": 2,
              "counts": {"color_transition": 1, "flicker": 1},
              "max_flash_rate": 15.0, "peak_luminance": 249.0,
              "min_luminance": 0.0, "risky_frame_share": 0.967},
  "events": [
    {"kind": "color_transition", "start": 0.067, "end": 1.933,
     "attributes": {"max_delta": 1.71, "duration_s": 1.93}},
    {"kind": "flicker", "start": 0.067, "end": 1.933,
     "attributes": {"brightness_diff": 249.0, "flash_rate": 15.0,
                    "flashes_per_second": 7.5}}
  ]
}
```

Input: `samples/calm.mp4` — a slow grey ramp → `is_safe: true`, no events.
Input: `samples/stripes.mp4` — stationary bars → `spatial_pattern`, coverage 0.9.
Input: `samples/redflash.mp4` — red frames in black → `red_flash`, coverage 1.0.

---

## 9. Viva questions

**What does the project do?**
It screens a video for photosensitive triggers and reports the timestamps, then
dims the video during those moments in the player.

**Why Python?**
OpenCV and NumPy make frame-level image maths short and fast, and Django gives
the web layer in the same language.

**How does OpenCV extract frames?**
`cv2.VideoCapture(path)` opens the file; `cap.read()` returns `(ok, frame)` for
each frame; we keep every *n*-th frame and convert BGR to RGB.

**Why not analyse every frame?**
Cost. At 15 frames/s a two-minute clip is 1800 frames instead of 3600, and the
detectors work on averages that survive subsampling. The trade-off is aliasing,
which is documented.

**How does NumPy help?**
A frame is an `(H, W, 3)` array. Luminance is one matrix expression, the
difference between frames is one subtraction, and the mean is one call — no
Python loop over pixels.

**How is a flash detected?**
Absolute difference of mean luminance between neighbouring frames ≥ 40.

**How is a red flash different from a red frame?**
A red frame is ≥ 25 % red pixels. A red *flash* also needs a non-red frame
before and after it, because the transition is what triggers the response.

**How does the database store results?**
`hazard_event` gets one row per window (kind, start, end, attributes);
`analysis` gets one row per video (safe/unsafe, flags, timestamp).

**How do timestamps reach the overlay?**
The player page embeds the events as JSON; `player.js` passes them to the
overlay widget, which compares `video.currentTime` with each `start`/`end`.

**What are the limitations?**
Sampling can miss very short flashes; thresholds are heuristics, not clinical
limits; compression alters colours; and a clean report is not a guarantee.

**Why is the checkout simulated?**
The store exists to demonstrate the Python order path. Taking real payments
would need a gateway, PCI obligations and a legal entity — none of which belong
in a school project, so the site records a demo order and says so on every page.

**Why are prices stored in paise and not as decimals?**
A `FLOAT` cannot represent 0.1 exactly, so sums drift by a paisa and comparisons
fail. Integers in the smallest unit are exact: ₹499 is `49900`, and the display
layer adds the symbol and the commas. This is how real systems store money.

**How is the total spend per email kept?**
In `customer_spend`, one row per address. The checkout writes the order lines and
updates that row inside a single transaction:

```sql
UPDATE customer_spend
SET total_paise = total_paise + 49900,
    order_count = order_count + 1,
    last_order_at = NOW()
WHERE email = 'someone@example.com';
```

The addition happens in SQL (`F('total_paise') + amount`), so two checkouts at
the same moment add up instead of overwriting each other.

**Why store the total instead of summing `purchases` every time?**
Two reasons: one primary-key lookup instead of a `GROUP BY` over every order, and
it makes the idea of an aggregate table explicit. The cost is that it must be
maintained — it is correct only because the order lines and the total are written
in the same transaction, which is exactly what `transactions.atomic()` is for.

**How would you check the total is not wrong?**
Recompute it and compare:

```sql
SELECT p.email, s.total_paise AS stored, SUM(p.amount_paise) AS recomputed
FROM purchases p JOIN customer_spend s ON s.email = p.email
GROUP BY p.email, s.total_paise
HAVING stored <> recomputed;
```

An empty result means every stored total matches its orders.

**What is Indian digit grouping?**
`₹1,00,000`, not `₹100,000`: the last three digits, then pairs.
`money.group_indian` implements it as pure string work.

---

## 10. What I would do next

* Analyse every frame for short clips and subsample only for long ones.
* Store the luminance curve so the report can draw a graph.
* Add a per-second "risk density" bar instead of one band per event.
* Compare against a published test set (e.g. the WCAG flash examples) and report
  precision/recall instead of only thresholds.
