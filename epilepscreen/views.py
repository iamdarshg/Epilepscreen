import mysql.connector
import hashlib
import datetime
import json
import os
import tempfile
from django.shortcuts import render, redirect
from django.http import HttpResponse, Http404, JsonResponse
from django.conf import settings
from django.views.decorators.clickjacking import xframe_options_exempt
import lzma

from epilepscreen.media import (
    content_type_for,
    is_audio_content,
    normalize_category,
)
from photosensitive.analyze_video import analyze_video_file
from epilepscreen.analysis_store import save_events


def get_db_connection():
    return mysql.connector.connect(**settings.DB_CONFIG)

def index(request):
    """
    Renders the list of videos. 
    Note: We do NOT fetch the 'movie' BLOB here to save bandwidth.
    """
    videos = []
    cnx = None
    try:
        cnx = get_db_connection()
        cursor = cnx.cursor(dictionary=True)
        
        # Select only metadata, not the heavy blob.
        # The EXISTS subquery tells the template whether Python-side
        # analysis has already stored hazard events for each video.
        query = (
            "SELECT hash, title, time_uploaded, category, content_type, "
            "EXISTS(SELECT 1 FROM hazard_event "
            "WHERE video_hash = epilepsy.hash) AS analyzed "
            "FROM epilepsy ORDER BY time_uploaded DESC"
        )
        cursor.execute(query)
        rows = cursor.fetchall()
        
        # Transform data for the template
        for row in rows:
            ctype = row.get("content_type") or "video/mp4"
            videos.append({
                'title': row['title'],
                'uploaded_at': row['time_uploaded'],
                'analyzed': bool(row['analyzed']),
                'category': row.get("category") or "Other",
                'kind': 'audio' if is_audio_content(ctype) else 'video',
                # We generate a virtual URL that points to our stream_video view
                'file_path': f"/stream/{row['hash']}/"
            })
            
        cursor.close()
    except mysql.connector.Error as err:
        print(f"Database Error: {err}")
    finally:
        if cnx:
            cnx.close()
        
    return render(request, 'player.html', {'videos': videos})

def stream_video(request, video_hash):
    """
    Retrieves the binary BLOB from MySQL and streams it to the client.
    """
    cnx = None
    try:
        cnx = get_db_connection()
        cursor = cnx.cursor()
        
        # Fetch the actual video binary plus its stored MIME type
        query = "SELECT movie, content_type FROM epilepsy WHERE hash = %s"
        cursor.execute(query, (video_hash,))
        row = cursor.fetchone()
        
        cursor.close()
        
        if row:
            video_data = lzma.decompress(row[0])
            mime = row[1] or "video/mp4"
            size = len(video_data)

            # Support Range requests so browsers can seek (and play on mobile).
            range_header = request.headers.get("Range")
            if range_header and range_header.startswith("bytes="):
                try:
                    start_str, _, end_str = range_header[6:].partition("-")
                    start = int(start_str) if start_str else 0
                    end = int(end_str) if end_str else size - 1
                    end = min(end, size - 1)
                    if start >= size or start > end:
                        raise ValueError
                except ValueError:
                    resp = HttpResponse(status=416)
                    resp["Content-Range"] = f"bytes */{size}"
                    return resp
                resp = HttpResponse(
                    video_data[start:end + 1],
                    status=206,
                    content_type=mime,
                )
                resp["Content-Range"] = f"bytes {start}-{end}/{size}"
                resp["Content-Length"] = str(end - start + 1)
                resp["Accept-Ranges"] = "bytes"
                return resp

            resp = HttpResponse(video_data, content_type=mime)
            resp["Accept-Ranges"] = "bytes"
            return resp
        else:
            raise Http404("Video not found")
            
    except mysql.connector.Error:
        return HttpResponse("Database Error", status=500)
    except lzma.LZMAError:
        return HttpResponse("Corrupt video data", status=500)
    finally:
        if cnx:
            cnx.close()

def upload_video(request):
    """
    Handles file upload and insertion into the new schema format.
    """
    if request.method == 'POST' and request.FILES.get('video_file'):
        video_file = request.FILES['video_file']
        title = request.POST.get('title', 'Untitled')
        # Free-text category (blank = unknown, may be auto-filled later).
        category = normalize_category(request.POST.get('category', ''))
        # Bytes are stored exactly as uploaded (lossless); remember the type
        # so audio (mp3/flac/wav) streams back with the right MIME type.
        content_type = content_type_for(
            video_file.name, getattr(video_file, "content_type", None))

        # Reject files over 100MB to prevent memory exhaustion
        if video_file.size > 100 * 1024 * 1024:
            return HttpResponse("File too large (max 100MB)", status=413)

        # 1. Read file into memory (binary)
        movie_blob = video_file.read()

        # 2. Generate Metadata
        now = datetime.datetime.now()

        # Generate UNSIGNED BIGINT hash from title + time + random bytes
        hash_input = f"{title}{now}{os.urandom(8)}".encode('utf-8')
        hash_val = int(hashlib.sha256(hash_input).hexdigest()[:15], 16)

        movie_blob = lzma.compress(movie_blob)
        # 3. Insert into MySQL
        cnx = None
        try:
            cnx = get_db_connection()
            cursor = cnx.cursor()

            query = """
                INSERT INTO epilepsy (hash, time_uploaded, title, category,
                                      content_type, movie)
                VALUES (%s, %s, %s, %s, %s, %s)
            """
            vals = (hash_val, now, title, category, content_type, movie_blob)
            
            cursor.execute(query, vals)
            cnx.commit()
            
            cursor.close()
        except mysql.connector.Error as err:
            return HttpResponse(f"Database Insert Error: {err}", status=500)
        finally:
            if cnx:
                cnx.close()

        return redirect('index')
    
    return redirect('index')


def analyze_video(request, video_hash):
    """Analyze a stored video, persist hazard events, and return JSON."""
    cnx = None
    try:
        cnx = get_db_connection()
        cursor = cnx.cursor()
        cursor.execute("SELECT movie FROM epilepsy WHERE hash = %s", (video_hash,))
        row = cursor.fetchone()
        cursor.close()
        if not row:
            return JsonResponse({"error": "Video not found"}, status=404)
        video_data = lzma.decompress(row[0])
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=500)
    finally:
        if cnx:
            cnx.close()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
        tmp.write(video_data)
        tmp_path = tmp.name
    try:
        profile = analyze_video_file(tmp_path)
    finally:
        os.unlink(tmp_path)

    save_events(int(video_hash), profile.events)

    return JsonResponse({
        "hash": video_hash,
        "is_safe": profile.is_safe,
        "risk_flags": profile.risk_flags,
        "events": [
            {"kind": e.kind, "start": e.start_time, "end": e.end_time,
             "attributes": e.attributes}
            for e in profile.events
        ],
    })


def video_events(request, video_hash):
    """Return stored hazard events for a video, for the overlay widget."""
    cnx = None
    rows = []
    try:
        cnx = get_db_connection()
        cursor = cnx.cursor(dictionary=True)
        cursor.execute(
            "SELECT kind, start_time, end_time, attributes FROM hazard_event "
            "WHERE video_hash = %s ORDER BY start_time",
            (int(video_hash),),
        )
        rows = cursor.fetchall()
        cursor.close()
    except Exception:
        return JsonResponse({"events": []})
    finally:
        if cnx:
            cnx.close()
    events = [
        {"kind": r["kind"], "start": float(r["start_time"]),
         "end": float(r["end_time"]),
         "attributes": r["attributes"]}
        for r in rows
    ]
    return JsonResponse({"events": events})


@xframe_options_exempt
def embed(request, video_hash):
    """Minimal embeddable player widget for any webpage.

    Usage: <iframe src="/embed/<hash>/" width="560" height="315"
                   frameborder="0" allowfullscreen></iframe>
    """
    cnx = None
    try:
        cnx = get_db_connection()
        cursor = cnx.cursor(dictionary=True)
        cursor.execute(
            "SELECT title FROM epilepsy WHERE hash = %s",
            (video_hash,),
        )
        row = cursor.fetchone()
        cursor.close()
        if not row:
            raise Http404("Video not found")
        title = row["title"]
    except Http404:
        raise
    except Exception:
        return HttpResponse("Video unavailable", status=500)
    finally:
        if cnx:
            cnx.close()
    return render(request, "embed.html", {
        "title": title,
        "stream_url": f"/stream/{video_hash}/",
        "events_url": f"/events/{video_hash}/",
    })
