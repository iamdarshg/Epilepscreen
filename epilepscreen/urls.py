from epilepscreen.views import (
    index,
    stream_video,
    stream_as_file,
    upload_video,
    browse,
    store,
    add_to_cart,
    events,
    player,
    categories,
    analyze,
    upload,
)
from django.urls import path

urlpatterns = [
    path('', index, name='index'),
    path('store/', store, name='store'),
    path('browse/', browse, name='browse'),
    path('categories/', categories, name='categories'),

    path('products/<int:product_id>/', store, name='product_detail'),
    path('cart/add/<int:product_id>/', add_to_cart, name='add_to_cart'),

    path('stream/<int:video_hash>/', stream_video, name='stream_video'),
    path('player/<int:video_hash>/', player, name='player'),

    path('events/<int:video_hash>/', events, name='events'),
    path('analyze/<int:video_hash>/', analyze, name='analyze'),

    path('upload/', upload, name='upload'),
    path('health/', lambda r: HttpResponse('{"status":"ok"}', content_type='application/json'), name='health'),
]

from django.http import HttpResponse
