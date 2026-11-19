"""Make the analysis tables' video hashes real foreign keys.

`hazard_event.video_hash` and `analysis.video_hash` were plain integers that
happened to point at `epilepsy.hash`; nothing stopped an orphan row from being
written. This migration adds the constraints with ON DELETE CASCADE, so deleting
a video also removes its events and verdict.

Both models are unmanaged (migration 0003 creates the tables with raw DDL), so
the AlterField operations only update Django's state. `RunPython` performs the
actual schema change for each engine: ALTER TABLE on MySQL, a table rebuild on
SQLite (which cannot add a constraint to an existing table).
"""
import django.db.models.deletion
from django.db import migrations, models
CHILD_TABLES = ('hazard_event', 'analysis')
CONSTRAINT_NAMES = {'hazard_event': 'fk_hazard_event_video', 'analysis': 'fk_analysis_video'}

def _check_orphans(cursor):
    for table in CHILD_TABLES:
        cursor.execute(f'SELECT COUNT(*) FROM {table} child LEFT JOIN epilepsy parent ON parent.hash = child.video_hash WHERE parent.hash IS NULL')
        count = cursor.fetchone()[0]
        if count:
            raise RuntimeError(f'{table} has {count} row(s) whose video_hash is not present in epilepsy.hash. Repair or remove those rows, then run the migration again.')

def _mysql_has_constraint(cursor, table):
    cursor.execute("\n        SELECT COUNT(*) FROM information_schema.KEY_COLUMN_USAGE\n        WHERE TABLE_SCHEMA = DATABASE()\n          AND TABLE_NAME = %s\n          AND COLUMN_NAME = 'video_hash'\n          AND REFERENCED_TABLE_NAME = 'epilepsy'\n          AND REFERENCED_COLUMN_NAME = 'hash'\n        ", (table,))
    return cursor.fetchone()[0] > 0

def _mysql_add(cursor):
    _check_orphans(cursor)
    for table in CHILD_TABLES:
        if _mysql_has_constraint(cursor, table):
            continue
        cursor.execute(f'ALTER TABLE {table} ADD CONSTRAINT {CONSTRAINT_NAMES[table]} FOREIGN KEY (video_hash) REFERENCES epilepsy (hash) ON DELETE CASCADE')

def _mysql_drop(cursor):
    for table in CHILD_TABLES:
        cursor.execute("\n            SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE\n            WHERE TABLE_SCHEMA = DATABASE()\n              AND TABLE_NAME = %s\n              AND COLUMN_NAME = 'video_hash'\n              AND REFERENCED_TABLE_NAME = 'epilepsy'\n              AND REFERENCED_COLUMN_NAME = 'hash'\n            LIMIT 1\n            ", (table,))
        row = cursor.fetchone()
        if row:
            cursor.execute(f'ALTER TABLE {table} DROP FOREIGN KEY `{row[0]}`')

def _sqlite_rebuild(cursor, with_fk):
    fk_clause = ',\n            FOREIGN KEY (video_hash) REFERENCES epilepsy (hash) ON DELETE CASCADE' if with_fk else ''
    cursor.execute(f'\n        CREATE TABLE hazard_event_new (\n            id INTEGER PRIMARY KEY AUTOINCREMENT,\n            video_hash INTEGER NOT NULL,\n            kind VARCHAR(40) NOT NULL,\n            start_time REAL NOT NULL,\n            end_time REAL NOT NULL,\n            attributes TEXT,\n            created_at DATETIME NOT NULL{fk_clause}\n        )\n    ')
    cursor.execute('INSERT INTO hazard_event_new (id, video_hash, kind, start_time, end_time, attributes, created_at) SELECT id, video_hash, kind, start_time, end_time, attributes, created_at FROM hazard_event')
    cursor.execute('DROP TABLE hazard_event')
    cursor.execute('ALTER TABLE hazard_event_new RENAME TO hazard_event')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_hazard_video ON hazard_event (video_hash)')
    cursor.execute(f'\n        CREATE TABLE analysis_new (\n            video_hash INTEGER PRIMARY KEY,\n            is_safe BOOL NOT NULL,\n            risk_flags TEXT,\n            checked_at DATETIME NOT NULL{fk_clause}\n        )\n    ')
    cursor.execute('INSERT INTO analysis_new (video_hash, is_safe, risk_flags, checked_at) SELECT video_hash, is_safe, risk_flags, checked_at FROM analysis')
    cursor.execute('DROP TABLE analysis')
    cursor.execute('ALTER TABLE analysis_new RENAME TO analysis')

def add_foreign_keys(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        if connection.vendor == 'mysql':
            _mysql_add(cursor)
        elif connection.vendor == 'sqlite':
            _check_orphans(cursor)
            _sqlite_rebuild(cursor, with_fk=True)

def remove_foreign_keys(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        if connection.vendor == 'mysql':
            _mysql_drop(cursor)
        elif connection.vendor == 'sqlite':
            _sqlite_rebuild(cursor, with_fk=False)

class Migration(migrations.Migration):
    dependencies = [('epilepscreen', '0006_video_upload_owner')]
    operations = [migrations.AlterField(model_name='hazardevent', name='video_hash', field=models.ForeignKey(db_column='video_hash', on_delete=django.db.models.deletion.CASCADE, related_name='hazard_events', to='epilepscreen.videorecord')), migrations.AlterField(model_name='analysis', name='video_hash', field=models.OneToOneField(db_column='video_hash', on_delete=django.db.models.deletion.CASCADE, primary_key=True, related_name='analysis', serialize=False, to='epilepscreen.videorecord')), migrations.RunPython(add_foreign_keys, remove_foreign_keys)]
