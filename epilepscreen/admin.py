from django.contrib import admin

from .models import (
    Analysis,
    HazardEvent,
    Purchase,
    StoreProduct,
    VideoRecord,
)


@admin.register(StoreProduct)
class StoreProductAdmin(admin.ModelAdmin):
    list_display = ('title', 'product_type', 'price_cents', 'active', 'created_at')
    list_filter = ('active', 'product_type')
    search_fields = ('title', 'description')


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ('id', 'product', 'email', 'status', 'payment_method',
                    'amount_cents', 'created_at')
    list_filter = ('status', 'payment_method')
    search_fields = ('email', 'product__title')


# --------------------------------------------------------------------------
# Read-only views of the tables the Python pipeline writes, so the database can
# be inspected during the demonstration without shell commands. Everything here
# is written by the analyser, not by hand, which is why nothing is editable.
# --------------------------------------------------------------------------

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

    def has_delete_permission(self, request, obj=None):
        return True


@admin.register(HazardEvent)
class HazardEventAdmin(admin.ModelAdmin):
    list_display = ('video_hash', 'kind', 'start_time', 'end_time', 'created_at')
    list_filter = ('kind',)
    search_fields = ('video_hash',)
    ordering = ('video_hash', 'start_time')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Analysis)
class AnalysisAdmin(admin.ModelAdmin):
    list_display = ('video_hash', 'is_safe', 'risk_flags', 'checked_at')
    list_filter = ('is_safe',)
    ordering = ('-checked_at',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False