# Epilepscreen

Screen a video for photosensitive triggers **before** anyone watches it.

Upload a file, and Python reads it frame by frame with OpenCV, measures it with
NumPy, and writes a timestamped hazard report into the database. The player then
dims the picture exactly where the report says it should.

This is a Class 12 Computer Science project. Python does all the real work; the
browser only draws the overlay and drives the player.

---

## What it does

| Step | Where | What happens |
| --- | --- | --- |
| Upload | `epilepscreen/views.py` | Extension, size and empty-file checks; `hashlib.sha256` content hash; `lzma` compression; row in the `epilepsy` table |
| Screen | `photosensitive/` | `cv2.VideoCapture` decodes ~15 frames/s, NumPy computes luminance, red coverage, colour deltas and stripe structure, thresholds turn them into events |
| Store | `epilepscreen/analysis_store.py` | One row per event in `hazard_event`, one verdict in `analysis` |
| Play | `templates/player.html` + `player.js` | The player fetches the event times and dims the video while playback is inside a hazard window |
| Sell | `templates/checkout.html` | A **simulated** checkout that records a demo order. No card details, no gateway, no money |

---

## Install

Windows, Python 3.10+ (tested on 3.12).

```powershell
git clone https://github.com/iamdarshg/Epilepscreen
cd Epilepscreen
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Database

Two engines, one codebase. `DB_ENGINE` in `.env` picks one.

**SQLite (default, nothing to install):**

```powershell
copy .env.example .env      # then set DJANGO_SECRET_KEY
python manage.py migrate
```

**MySQL (optional):**

```powershell
pip install mysqlclient
# .env
#   DB_ENGINE=mysql
#   DB_NAME=darsh
#   DB_USER=root
#   DB_PASSWORD=...
#   DB_HOST=127.0.0.1
#   DB_PORT=3306
python manage.py migrate
```

`python sql.py` is a shortcut for `python manage.py migrate`; it exists because
older versions of the project created the tables with hand-written SQL.

## Run

```powershell
python manage.py runserver
```

Open <http://127.0.0.1:8000/>.

## Demo in five minutes

```powershell
python manage.py make_samples          # writes samples/*.mp4 (needs ffmpeg for browser playback)
python manage.py runserver
```

1. **Upload** → choose `samples/strobe.mp4`, leave *Screen it now* ticked.
2. The player opens with a red **2 windows** chip, a hazard table, and a red band
   on the timeline. Press play: the picture dims inside the band.
3. **Re-screen this video** re-runs the Python analyser and reloads the report.
4. **Read the full report** shows the measurements and the method.
5. **Store** → *Add to the demo cart* → **Checkout** → *Confirm demo order* →
   receipt. The page says **DEMO CHECKOUT — NO REAL PAYMENT** throughout.

## Tests

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test                 # 71 Django tests
python -m pytest photosensitive/tests -q   # 35 detector tests
node epilepscreen/static/epilepscreen/epilepscreen.test.js   # overlay widget
```

Optional browser sweep (needs `pip install playwright` and
`python -m playwright install chromium`, plus a running server):

```powershell
python scripts/qa_screens.py          # writes qa/*.png, exits 1 on any error
```

## Layout

```
mysite/            settings, root URLs
epilepscreen/      Django app: views, models, SQL, templates glue
  management/      ingest_media, analyze_media, make_samples
  static/          store.css (design system), pages.css, player.js, overlay widget
photosensitive/    the detector: pure NumPy core + OpenCV decoder
templates/         base.html + one template per page
samples/           generated demo clips
scripts/           qa_screens.py (Playwright sweep)
```

## Limits

The detectors are heuristics modelled on WCAG 2.3 guidance, not a clinical
standard. Sampling at ~15 frames/s can miss a flash that repeats at exactly the
sampling rate. A clear report is evidence, not a guarantee. See
`PROJECT_EXPLANATION.md` for the full list.
