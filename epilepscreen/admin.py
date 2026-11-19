from django.contrib import admin
from django.db import transaction
from .analysis_store import delete_video
from .models import Analysis, CustomerSpend, HazardEvent, Purchase, StoreProduct, VideoRecord

@admin.register(StoreProduct)
class StoreProductAdmin(admin.ModelAdmin):
    list_display = ('title', 'product_type', 'price_paise', 'active', 'created_at')
    list_filter = ('active', 'product_type')
    search_fields = ('title', 'description')

@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ('id', 'product', 'email', 'status', 'payment_method', 'amount_paise', 'created_at')
    list_filter = ('status', 'payment_method')
    search_fields = ('email', 'product__title')

@admin.register(VideoRecord)
class VideoRecordAdmin(admin.ModelAdmin):
    list_display = ('hash', 'title', 'category', 'content_type', 'time_uploaded')
    list_filter = ('category', 'content_type')
    search_fields = ('title', 'category')
    ordering = ('-time_uploaded',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def delete_model(self, request, obj):
        delete_video(obj.pk)

    def delete_queryset(self, request, queryset):
        with transaction.atomic():
            for video_hash in list(queryset.values_list('pk', flat=True)):
                delete_video(video_hash)

@admin.register(HazardEvent)
class HazardEventAdmin(admin.ModelAdmin):
    list_display = ('video_hash', 'kind', 'start_time', 'end_time', 'created_at')
    list_filter = ('kind',)
    list_select_related = ('video_hash',)
    search_fields = ('video_hash__title', 'video_hash__hash', 'kind')
    ordering = ('video_hash_id', 'start_time')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

@admin.register(Analysis)
class AnalysisAdmin(admin.ModelAdmin):
    list_display = ('video_hash', 'is_safe', 'risk_flags', 'checked_at')
    list_filter = ('is_safe',)
    list_select_related = ('video_hash',)
    search_fields = ('video_hash__title', 'video_hash__hash')
    ordering = ('-checked_at',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

@admin.register(CustomerSpend)
class CustomerSpendAdmin(admin.ModelAdmin):
    """The per-email running total, written by orders.create_demo_order."""
    list_display = ('email', 'total_display', 'order_count', 'currency', 'first_order_at', 'last_order_at')
    search_fields = ('email',)
    ordering = ('-total_paise',)
    readonly_fields = ('email', 'total_paise', 'order_count', 'currency', 'first_order_at', 'last_order_at')

    def has_add_permission(self, request):
        return False
