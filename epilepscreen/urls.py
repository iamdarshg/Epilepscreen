from django.urls import path

from epilepscreen import views

urlpatterns = [
    # Library
    path('', views.index, name='index'),
    path('browse/', views.browse, name='browse'),
    path('categories/', views.categories, name='categories'),
    path('upload/', views.upload, name='upload'),
    path('upload/send/', views.upload_video, name='upload_send'),

    # Playback and screening
    path('player/<int:video_hash>/', views.player, name='player'),
    path('embed/<int:video_hash>/', views.embed, name='embed'),
    path('screening/<int:video_hash>/', views.screening, name='screening'),
    path('stream/<int:video_hash>/', views.stream_video, name='stream_video'),
    path('stream/<int:video_hash>/file/', views.stream_as_file, name='stream_file'),
    path('events/<int:video_hash>/', views.events, name='events'),
    path('analyze/<int:video_hash>/', views.analyze, name='analyze'),

    # Demonstration store
    path('store/', views.store, name='store'),
    path('store/browser/', views.browser_page, name='browser_page'),
    path('store/browser/asset/', views.browser_asset, name='browser_asset'),
    path('products/<int:product_id>/', views.product_detail, name='product_detail'),
    path('cart/add/<int:product_id>/', views.add_to_cart, name='add_to_cart'),
    path('cart/remove/<int:product_id>/', views.remove_from_cart, name='remove_from_cart'),
    path('checkout/', views.checkout, name='checkout'),
    path('order/', views.order_confirmation, name='order_confirmation'),

    # Ops
    path('health/', views.health, name='health'),
]
