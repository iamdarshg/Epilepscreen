"""Create the three hand-written-SQL tables on whichever engine is in use.

`epilepsy` holds the uploaded media (an lzma-compressed blob), `hazard_event`
holds the timestamps the Python analyser produced, and `analysis` holds one
verdict row per screened video.

The DDL is written out per vendor because the two engines disagree on blob and
JSON types. Everything uses CREATE TABLE IF NOT EXISTS, so a database that was
already built by the old `sql.py` script simply keeps its tables.
"""
from django.db import migrations
SQLITE_DDL = ['\n    CREATE TABLE IF NOT EXISTS epilepsy (\n        hash INTEGER PRIMARY KEY,\n        time_uploaded DATETIME NOT NULL,\n        title TEXT NOT NULL,\n        category VARCHAR(40),\n        content_type VARCHAR(60),\n        movie BLOB\n    )\n    ', '\n    CREATE TABLE IF NOT EXISTS hazard_event (\n        id INTEGER PRIMARY KEY AUTOINCREMENT,\n        video_hash INTEGER NOT NULL,\n        kind VARCHAR(40) NOT NULL,\n        start_time REAL NOT NULL,\n        end_time REAL NOT NULL,\n        attributes TEXT,\n        created_at DATETIME NOT NULL\n    )\n    ', '\n    CREATE TABLE IF NOT EXISTS analysis (\n        video_hash INTEGER PRIMARY KEY,\n        is_safe BOOL NOT NULL,\n        risk_flags TEXT,\n        checked_at DATETIME NOT NULL\n    )\n    ', 'CREATE INDEX IF NOT EXISTS idx_hazard_video ON hazard_event (video_hash)']
MYSQL_DDL = ['\n    CREATE TABLE IF NOT EXISTS epilepsy (\n        hash BIGINT UNSIGNED NOT NULL PRIMARY KEY,\n        time_uploaded DATETIME NOT NULL,\n        title TEXT NOT NULL,\n        category VARCHAR(40) NULL,\n        content_type VARCHAR(60) NULL,\n        movie LONGBLOB\n    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4\n    ', '\n    CREATE TABLE IF NOT EXISTS hazard_event (\n        id INT AUTO_INCREMENT PRIMARY KEY,\n        video_hash BIGINT UNSIGNED NOT NULL,\n        kind VARCHAR(40) NOT NULL,\n        start_time FLOAT NOT NULL,\n        end_time FLOAT NOT NULL,\n        attributes JSON,\n        created_at DATETIME NOT NULL,\n        INDEX idx_video (video_hash)\n    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4\n    ', '\n    CREATE TABLE IF NOT EXISTS analysis (\n        video_hash BIGINT UNSIGNED NOT NULL PRIMARY KEY,\n        is_safe BOOL NOT NULL,\n        risk_flags JSON,\n        checked_at DATETIME NOT NULL\n    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4\n    ']

def create_tables(apps, schema_editor):
    statements = MYSQL_DDL if schema_editor.connection.vendor == 'mysql' else SQLITE_DDL
    with schema_editor.connection.cursor() as cursor:
        for sql in statements:
            cursor.execute(sql)

def drop_tables(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for table in ('hazard_event', 'analysis', 'epilepsy'):
            cursor.execute(f'DROP TABLE IF EXISTS {table}')

class Migration(migrations.Migration):
    dependencies = [('epilepscreen', '0002_seed_store_products')]
    operations = [migrations.RunPython(create_tables, drop_tables)]
