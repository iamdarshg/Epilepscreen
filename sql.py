"""Create the database schema. Run once, before starting the server:

    python sql.py

This is a thin wrapper around `python manage.py migrate`. It exists because
earlier versions of the project used this file to run hand-written CREATE TABLE
statements against MySQL; the schema now lives in migrations, which build the
same tables on SQLite *or* MySQL (see epilepscreen/migrations/0003_sql_tables.py).

Which database gets used is decided by DB_ENGINE in .env:
    DB_ENGINE=sqlite  -> db.sqlite3 beside manage.py   (default)
    DB_ENGINE=mysql   -> the DB_NAME/DB_USER/... target
"""
import os
import sys


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings')
    try:
        import django
        django.setup()
        from django.conf import settings
        from django.core.management import call_command
    except ImportError as exc:
        print(f'Django is not installed: {exc}\nInstall it with: pip install -r requirements.txt')
        return 1

    engine = settings.DATABASES['default']['ENGINE'].rsplit('.', 1)[-1]
    print(f'Creating tables for the {engine} database...')
    call_command('migrate', interactive=False)
    print('Done. Next: python manage.py runserver')
    return 0


if __name__ == '__main__':
    sys.exit(main())