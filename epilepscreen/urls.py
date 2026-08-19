from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("upload/", views.upload_video, name="uploads"),
    path("stream/", views.stream_video, name="stream_video"),
    path("analyze/<str:video_hash>/", views.analyze_video, name="analyze_video"),
    path("events/<str:video_hash>/", views.video_events, name="video_events"),
]