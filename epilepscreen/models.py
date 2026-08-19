from django.db import models

from django.db import models

class GitHub(models.Model):
    hash_id = models.BigIntegerField(primary_key=True)
    time_uploaded = models.DateTimeField(null=False)
    filename = models.TextField(default='README.md', null=False)
    repo_id = models.IntegerField(null=False)
    repo_name = models.TextField(null=False)
    time_modified = models.DateTimeField(null=False)
    modified_by = models.BigIntegerField(null=False)

    class Meta:
        db_table = 'github'
