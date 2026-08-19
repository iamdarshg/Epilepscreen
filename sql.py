import mysql.connector

mydb = mysql.connector.connect(
  host="localhost",
  user="root",
  password="sql123",
  database="darsh"
)

mycursor = mydb.cursor()
query = """CREATE TABLE epilepsy (
  hash_id BIGINT UNSIGNED PRIMARY KEY, 
  time_uploaded DATETIME NOT NULL, 
  filename TEXT NOT NULL DEFAULT 'README.md', 
  repo_id INT NOT NULL, 
  repo_name TEXT NOT NULL, 
  time_modified DATETIME NOT NULL, 
  modified_by BIGINT NOT NULL
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
mydb.commit()
'''
TYPING-
UNSIGNED BIGINT hash // unique ID, hash of title and time uploaded
DATETIME time_uploaded 
TEXT title
LONGBLOB movie // movie being accessed
'''
