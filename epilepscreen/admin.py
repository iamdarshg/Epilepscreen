from django.contrib import admin

from .models import Purchase, StoreProduct


@admin.register(StoreProduct)
class StoreProductAdmin(admin.ModelAdmin):
    list_display = ('title', 'product_type', 'price_cents', 'active', 'created_at')
    list_filter = ('active', 'product_type')
    search_fields = ('title', 'description')


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ('id', 'product', 'email', 'status', 'amount_cents', 'created_at')
    list_filter = ('status', 'payment_method')
    search_fields = ('email', 'product__title')
