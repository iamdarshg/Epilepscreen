from django.db import models


class Video(models.Model):
    hash = models.BigIntegerField(primary_key=True)
    time_uploaded = models.DateTimeField()
    title = models.TextField()
    category = models.CharField(max_length=40, null=True, blank=True)
    content_type = models.CharField(max_length=60, null=True, blank=True)
    movie = models.BinaryField(null=True, blank=True)

    class Meta:
        db_table = 'epilepsy'

    def __str__(self):
        return self.title
