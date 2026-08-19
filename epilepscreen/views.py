import mysql.connector
import hashlib
import datetime
import json
from django.shortcuts import render, redirect
from django.http import HttpResponse, Http404, JsonResponse
import lzma


# Configuration for MySQL connection
DB_CONFIG = {
    'user': 'root',
    'password': 'sql123',
    'host': 'localhost',
    'database': 'darsh',
    'raise_on_warnings': True,
    # buffer_result is often needed when fetching large BLOBs
    # ensuring the connector doesn't timeout or run OOM easily
}

def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)

def index(request):
    """
    Renders the list of videos. 
    Note: We do NOT fetch the 'movie' BLOB here to save bandwidth.
    """
    videos = []
    try:
        cnx = get_db_connection()
        cursor = cnx.cursor(dictionary=True)
        
        # Select only metadata, not the heavy blob
        query = "SELECT hash, title, time_uploaded FROM epilepsy ORDER BY time_uploaded DESC"
        cursor.execute(query)
        rows = cursor.fetchall()
        
        # Transform data for the template
        for row in rows:
            videos.append({
                'title': row['title'],
                'uploaded_at': row['time_uploaded'],
                # We generate a virtual URL that points to our stream_video view
                'file_path': f"/stream/{row['hash']}/"
            })
            
        cursor.close()
        cnx.close()
    except mysql.connector.Error as err:
        print(f"Database Error: {err}")
        
    return render(request, 'player.html', {'videos': videos})

def stream_video(request, video_hash):
    """
    Retrieves the binary BLOB from MySQL and streams it to the client.
    """
    try:
        cnx = get_db_connection()
        cursor = cnx.cursor()
        
        # Fetch the actual video binary
        query = "SELECT movie FROM epilepsy WHERE hash = %s"
        cursor.execute(query, (video_hash,))
        row = cursor.fetchone()
        
        cursor.close()
        cnx.close()
        
        if row:
            video_data = lzma.decompress(row[0])
            # Return the binary data with video MIME type
            return HttpResponse(video_data, content_type='video/mp4')
        else:
            raise Http404("Video not found")
            
    except mysql.connector.Error:
        return HttpResponse("Database Error", status=500)

def upload_video(request):
    """
    Handles file upload and insertion into the new schema format.
    """
    if request.method == 'POST' and request.FILES.get('video_file'):
        video_file = request.FILES['video_file']
        title = request.POST.get('title', 'Untitled')
        
        # 1. Read file into memory (binary)
        # Note: Large files might require chunking or stream reading in production
        movie_blob = video_file.read()


        # 2. Generate Metadata
        now = datetime.datetime.now()

        # Generate UNSIGNED BIGINT hash from title + time
        # We use SHA256 and convert the first 15 chars to an int to fit in BIGINT
        hash_input = f"{title}{now}".encode('utf-8')
        hash_val = int(hashlib.sha256(hash_input).hexdigest()[:15], 16)


        movie_blob = lzma.compress(movie_blob)
        # 3. Insert into MySQL
        try:
            cnx = get_db_connection()
            cursor = cnx.cursor()

            query = """
                INSERT INTO epilepsy (hash, time_uploaded, title, movie)
                VALUES (%s, %s, %s, %s)
            """
            vals = (hash_val, now, title, movie_blob)
            
            cursor.execute(query, vals)
            cnx.commit()
            
            cursor.close()
            cnx.close()
        except mysql.connector.Error as err:
            return HttpResponse(f"Database Insert Error: {err}", status=500)

        return redirect('index')
    
    return redirect('index')

# ---------------------------------------------------------
# DATABASE SETUP INSTRUCTIONS
# ---------------------------------------------------------
# Run this SQL in your MySQL client to match the requested schema:
#
# CREATE TABLE videos (
#     hash BIGINT UNSIGNED PRIMARY KEY,
#     time_uploaded DATETIME NOT NULL,
#     title TEXT NOT NULL,
#     lenjson LONGTEXT,
#     movie LONGBLOB
# );
#
# IMPORTANT:
# Storing videos requires a large `max_allowed_packet` in MySQL.
# You may need to run: SET GLOBAL max_allowed_packet = 1073741824; -- (1GB)


def analyze_video(request, video_hash):
    """Analyze a stored video, persist hazard events, and return JSON."""
    try:
        cnx = get_db_connection()
        cursor = cnx.cursor()
        cursor.execute("SELECT movie FROM epilepsy WHERE hash = %s", (video_hash,))
        row = cursor.fetchone()
        cursor.close()
        cnx.close()
        if not row:
            return JsonResponse({"error": "Video not found"}, status=404)
        video_data = lzma.decompress(row[0])
    except Exception as exc:  # pragma: no cover - DB path
        return JsonResponse({"error": str(exc)}, status=500)

    import tempfile, os
    from photosensitive.analyze_video import analyze_video_file

    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
        tmp.write(video_data)
        tmp_path = tmp.name
    try:
        profile = analyze_video_file(tmp_path)
    finally:
        os.unlink(tmp_path)

    from epilepscreen.analysis_store import save_events
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
        cnx.close()
    except Exception:  # pragma: no cover - DB path
        return JsonResponse({"events": []})
    events = [
        {"kind": r["kind"], "start": float(r["start_time"]),
         "end": float(r["end_time"]),
         "attributes": r["attributes"]}
        for r in rows
    ]
    return JsonResponse({"events": events})
