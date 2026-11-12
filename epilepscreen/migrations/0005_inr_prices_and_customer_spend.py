"""Prices in rupees, and a per-email running total in `customer_spend`.

Three things happen here:

1. the money columns are renamed from `*_cents` to `*_paise` — same integer
   minor-unit idea, Indian currency;
2. the four seeded packs are re-priced in rupees (₹499 / ₹799 / ₹1,999 / ₹3,999);
3. `customer_spend` is created and back-filled from any `purchases` rows that
   already exist, so the total is correct for a database that was used before
   this migration.

`epilepscreen/orders.py` keeps the table up to date from here on.
"""
from django.db import migrations, models
from django.db.models import Count, Max, Min, Sum

# title -> price in paise (₹1 = 100 paise)
RUPEE_PRICES = {
    'Screening pack': 49900,        # ₹499
    'Music video pack': 79900,      # ₹799
    'Premium shelf': 199900,        # ₹1,999
    'Research package': 399900,     # ₹3,999
}

# What 0002 seeded, so the migration can be reversed.
OLD_PRICES = {
    'Screening pack': 1900,
    'Music video pack': 2900,
    'Premium shelf': 7900,
    'Research package': 14900,
}


def set_prices(prices):
    def _apply(apps, schema_editor):
        StoreProduct = apps.get_model('epilepscreen', 'StoreProduct')
        for title, price in prices.items():
            StoreProduct.objects.filter(title=title).update(price_paise=price)
        # Anything that was not one of the seeded packs was stored as a dollar
        # cent amount; interpret it as whole rupees so the numbers stay sane.
        StoreProduct.objects.exclude(title__in=list(prices)).update(
            price_paise=models.F('price_paise') * 100)
    return _apply


def normalise_purchases_and_backfill_spend(apps, schema_editor):
    """Re-price old demo orders in rupees, then rebuild the running totals.

    The rows written before this migration were priced in dollars, so each line
    is re-priced from its product's current rupee price and stamped INR. They are
    demonstration orders; nothing was ever charged.
    """
    Purchase = apps.get_model('epilepscreen', 'Purchase')
    CustomerSpend = apps.get_model('epilepscreen', 'CustomerSpend')

    for purchase in Purchase.objects.select_related('product'):
        product = purchase.product
        purchase.currency = 'INR'
        if product is not None:
            purchase.amount_paise = product.price_paise
        purchase.save(update_fields=['currency', 'amount_paise'])

    rows = (Purchase.objects.values('email')
            .annotate(total=Sum('amount_paise'),
                      orders=Count('id'),
                      first=Min('completed_at'),
                      last=Max('completed_at')))
    for row in rows:
        CustomerSpend.objects.update_or_create(
            email=row['email'],
            defaults={
                'total_paise': int(row['total'] or 0),
                'order_count': int(row['orders'] or 0),
                'currency': 'INR',
                'first_order_at': row['first'],
                'last_order_at': row['last'],
            },
        )


def clear_spend(apps, schema_editor):
    CustomerSpend = apps.get_model('epilepscreen', 'CustomerSpend')
    CustomerSpend.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("epilepscreen", "0004_analysis_hazardevent_videorecord"),
    ]

    operations = [
        migrations.CreateModel(
            name="CustomerSpend",
            fields=[
                (
                    "email",
                    models.EmailField(
                        max_length=254, primary_key=True, serialize=False
                    ),
                ),
                ("total_paise", models.IntegerField(default=0)),
                ("order_count", models.IntegerField(default=0)),
                ("currency", models.CharField(default="INR", max_length=3)),
                ("first_order_at", models.DateTimeField(blank=True, null=True)),
                ("last_order_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "verbose_name": "Customer spend",
                "verbose_name_plural": "Customer spend",
                "db_table": "customer_spend",
                "ordering": ["-total_paise"],
            },
        ),
        migrations.AlterModelOptions(
            name="storeproduct",
            options={"ordering": ["price_paise"]},
        ),
        migrations.RemoveIndex(
            model_name="storeproduct",
            name="store_active_price_idx",
        ),
        migrations.RenameField(
            model_name="purchase",
            old_name="amount_cents",
            new_name="amount_paise",
        ),
        migrations.RenameField(
            model_name="storeproduct",
            old_name="price_cents",
            new_name="price_paise",
        ),
        migrations.RenameField(
            model_name="video",
            old_name="price_cents",
            new_name="price_paise",
        ),
        migrations.RenameField(
            model_name="videopurchase",
            old_name="price_cents",
            new_name="price_paise",
        ),
        migrations.AlterField(
            model_name="purchase",
            name="currency",
            field=models.CharField(default="INR", max_length=3),
        ),
        migrations.AlterField(
            model_name="videopurchase",
            name="currency",
            field=models.CharField(default="INR", max_length=3),
        ),
        migrations.AddIndex(
            model_name="storeproduct",
            index=models.Index(
                fields=["active", "price_paise"], name="store_active_price_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="customerspend",
            index=models.Index(fields=["-total_paise"], name="spend_total_idx"),
        ),
        migrations.AddIndex(
            model_name="customerspend",
            index=models.Index(fields=["last_order_at"], name="spend_last_idx"),
        ),
        # Data: rupees, then the running totals that already exist.
        migrations.RunPython(set_prices(RUPEE_PRICES), set_prices(OLD_PRICES)),
        migrations.RunPython(normalise_purchases_and_backfill_spend, clear_spend),
    ]