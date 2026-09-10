from django.db import models

# NOTE: this app does not use the Django ORM. All data lives in MySQL
# (the `darsh` database) and is accessed with raw SQL through
# mysql.connector - see epilepscreen/views.py and analysis_store.py.
# The table layout is created by sql.py.
