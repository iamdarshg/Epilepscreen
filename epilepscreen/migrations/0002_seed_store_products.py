"""Seed a starter catalog so the storefront has something to sell.

These are sample listings with sample prices. Edit or replace them in Django
admin; the storefront reads whatever StoreProduct rows are active.
"""
from django.db import migrations


PRODUCTS = [
    {
        'title': 'Screening pack',
        'description': ('One film screened for flash, red flash, and pattern risk. '
                        'HD stream, original file, timestamped report.'),
        'product_type': 'format',
        'price_cents': 1900,
    },
    {
        'title': 'Music video pack',
        'description': ('Every film in the music video category, streamed in HD '
                        'with the library screening records.'),
        'product_type': 'category',
        'price_cents': 2900,
    },
    {
        'title': 'Premium shelf',
        'description': ('Access to the premium shelf in Browse, with the original '
                        'file behind every title.'),
        'product_type': 'premium',
        'price_cents': 7900,
    },
    {
        'title': 'Research package',
        'description': ('Event timestamps and risk flags for one study, exported '
                        'as JSON from the analyzer.'),
        'product_type': 'research',
        'price_cents': 14900,
    },
]


def seed_products(apps, schema_editor):
    StoreProduct = apps.get_model('epilepscreen', 'StoreProduct')
    if StoreProduct.objects.exists():
        return
    for product in PRODUCTS:
        StoreProduct.objects.create(active=True, **product)


def remove_products(apps, schema_editor):
    StoreProduct = apps.get_model('epilepscreen', 'StoreProduct')
    StoreProduct.objects.filter(title__in=[p['title'] for p in PRODUCTS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('epilepscreen', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_products, remove_products),
    ]
