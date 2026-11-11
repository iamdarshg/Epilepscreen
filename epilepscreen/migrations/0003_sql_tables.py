"""Create the three hand-written-SQL tables on whichever engine is in use.

`epilepsy` holds the uploaded media (an lzma-compressed blob), `hazard_event`
holds the timestamps the Python analyser produced, and `analysis` holds one
verdict row per screened video.

The DDL is written out per vendor because the two engines disagree on blob and
JSON types. Everything uses CREATE TABLE IF NOT EXISTS, so a database that was
already built by the old `sql.py` script simply keeps its tables.
"""
from django.db import migrations


SQLITE_DDL = [
    """
    CREATE TABLE IF NOT EXISTS epilepsy (
        hash INTEGER PRIMARY KEY,
        time_uploaded DATETIME NOT NULL,
        title TEXT NOT NULL,
        category VARCHAR(40),
        content_type VARCHAR(60),
        movie BLOB
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS hazard_event (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_hash INTEGER NOT NULL,
        kind VARCHAR(40) NOT NULL,
        start_time REAL NOT NULL,
        end_time REAL NOT NULL,
        attributes TEXT,
        created_at DATETIME NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS analysis (
        video_hash INTEGER PRIMARY KEY,
        is_safe BOOL NOT NULL,
        risk_flags TEXT,
        checked_at DATETIME NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_hazard_video ON hazard_event (video_hash)",
]

MYSQL_DDL = [
    """
    CREATE TABLE IF NOT EXISTS epilepsy (
        hash BIGINT UNSIGNED NOT NULL PRIMARY KEY,
        time_uploaded DATETIME NOT NULL,
        title TEXT NOT NULL,
        category VARCHAR(40) NULL,
        content_type VARCHAR(60) NULL,
        movie LONGBLOB
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS hazard_event (
        id INT AUTO_INCREMENT PRIMARY KEY,
        video_hash BIGINT UNSIGNED NOT NULL,
        kind VARCHAR(40) NOT NULL,
        start_time FLOAT NOT NULL,
        end_time FLOAT NOT NULL,
        attributes JSON,
        created_at DATETIME NOT NULL,
        INDEX idx_video (video_hash)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS analysis (
        video_hash BIGINT UNSIGNED NOT NULL PRIMARY KEY,
        is_safe BOOL NOT NULL,
        risk_flags JSON,
        checked_at DATETIME NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]


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

    dependencies = [
        ('epilepscreen', '0002_seed_store_products'),
    ]

    operations = [
        migrations.RunPython(create_tables, drop_tables),
    ]