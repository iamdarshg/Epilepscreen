"""Create the legacy raw-SQL tables used for video/blobs and analysis.

Run once against the database configured in .env:

    python sql.py

Django's own tables (store products, purchases, auth, sessions) are created
separately by `python manage.py migrate`.
"""
import os
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().with_name('.env'))

mydb = mysql.connector.connect(
  host=os.environ.get('DB_HOST', '127.0.0.1'),
  user=os.environ.get('DB_USER', 'root'),
  password=os.environ.get('DB_PASSWORD', ''),
  database=os.environ.get('DB_NAME', 'darsh'),
  charset='utf8mb4',
)

mycursor = mydb.cursor()
query = """CREATE TABLE IF NOT EXISTS epilepsy (
  hash BIGINT UNSIGNED PRIMARY KEY,
  time_uploaded DATETIME NOT NULL,
  title TEXT NOT NULL,
  category VARCHAR(40) NULL,
  content_type VARCHAR(60) NULL,
  movie LONGBLOB
  )
"""
mycursor.execute(query)

hazard_query = """CREATE TABLE IF NOT EXISTS hazard_event (
  id INT AUTO_INCREMENT PRIMARY KEY,
  video_hash BIGINT UNSIGNED NOT NULL,
  kind VARCHAR(40) NOT NULL,
  start_time FLOAT NOT NULL,
  end_time FLOAT NOT NULL,
  attributes JSON,
  created_at DATETIME NOT NULL,
  INDEX idx_video (video_hash)
)
"""
mycursor.execute(hazard_query)

analysis_query = """CREATE TABLE IF NOT EXISTS analysis (
  video_hash BIGINT UNSIGNED PRIMARY KEY,
  is_safe BOOL NOT NULL,
  risk_flags JSON,
  checked_at DATETIME NOT NULL
)
"""
mycursor.execute(analysis_query)
mydb.commit()

mycursor.close()
mydb.close()
