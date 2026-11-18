# Epilepscreen user guide

## Start the app

1. Install Python 3.10 or newer.
2. From the repository directory, create a virtual environment with `python -m venv .venv`. Activate it with `source .venv/bin/activate` on macOS or Linux, or `.venv\Scripts\Activate.ps1` in Windows PowerShell.
3. Run `python -m pip install -r requirements.txt`. Copy `.env.example` to `.env` if one does not already exist. Generate a key with `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` and paste it into `DJANGO_SECRET_KEY`.
4. Run `python manage.py migrate`, then `python manage.py runserver`. Open [Epilepscreen on localhost](http://127.0.0.1:8000/).

The example uses SQLite and creates `db.sqlite3` locally. To use MySQL, create a database and user, install `mysqlclient`, set `DB_ENGINE=mysql`, and fill in the MySQL section of `.env` before running migrations. Keep `ANALYSIS_FPS=0` to screen every decoded frame.

## Upload and screen a video

1. Open **Upload** and choose a video. MP4 and WebM are convenient for testing playback. The default upload limit is 100 MiB.
2. Leave **Screen it now** selected to screen during upload. For longer videos or uploads with screening turned off, open the video from **Library** and select **Screen this video** in the player.
3. Select **Read the full report** and review the verdict and timestamped windows before playback. **Unscreened** means there is no saved result. **Clear** means the app found no matching triggers. **Risky** means one or more detectors flagged a window.
4. Use **Re-screen this video** to update results saved by an earlier version. The new result replaces the existing report.

The screener uses approximate thresholds and may miss triggers. The guard dims the image during detected windows and can leave other parts of the video unchanged. If you are sensitive to flashes, read the report before deciding whether to play the video.

## Delete an upload

Open the video from **Library**, select **Delete video** in the player, then confirm. This removes the video and its screening results. The option appears in the browser session that uploaded the file. An administrator with video-delete permission can remove earlier uploads or files whose original session is unavailable.

## Use the player and demo store

- **Guard while in a hazard** toggles dimming. **Dim strength** controls how dark the overlay gets. **Warning padding** extends dimming before and after each window.
- The timeline and **Jump to next hazard** seek to flagged sections. Press Space to play or pause, N for the next hazard, and G to toggle the guard.
- Select any pack in **Store** to play its two stock previews. Use **Source and license** under a clip to open its credits.
- To try the demo checkout, add a sample pack to the cart, open **Checkout**, and confirm the demo order with an email address. The receipt shows the order and the running demo total for that email. The app takes no payment.

## Troubleshooting

- If the database fails to connect, check `DB_ENGINE` and run migrations. For MySQL, confirm the server is running and the configured user can access the database.
- If screening cannot decode the file, check that it contains video and try an H.264 MP4. For large files, check that both `ffmpeg` and `ffprobe` are available on your PATH.
- To inspect a file without uploading, run `python manage.py analyze_media path/to/video.mp4` for a JSON report. For a calm test clip, run `python manage.py make_samples` and upload `samples/calm.mp4`.
