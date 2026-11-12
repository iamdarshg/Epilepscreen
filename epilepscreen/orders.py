"""Placing a demonstration order, and keeping the per-email total in step.

Everything the store writes happens here rather than in the view, so the rules
live in one place and can be tested without a browser:

1. one `purchases` row per item (the order lines);
2. one `customer_spend` row per email (the running total).

Both happen inside a single `transaction.atomic()`, so a half-written order is
impossible. The total lives in its own table rather than being recomputed with
`SUM()` on every page view — that is the point of the exercise: an aggregate
column maintained by Python, and a MySQL table you can inspect with one SELECT.
"""

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from epilepscreen.models import CustomerSpend, Purchase


def spend_for(email):
    """The stored total for an email, or None."""
    return CustomerSpend.objects.filter(email=email).first()


def record_spend(email, amount_paise, when=None):
    """Add `amount_paise` to the running total for `email`. Returns the row.

    The increment uses an F() expression, so it is applied *in the database*
    (`UPDATE customer_spend SET total_paise = total_paise + %s`). Two orders for
    the same email arriving at once therefore add up instead of overwriting each
    other — the read-modify-write race that a plain `row.total += amount` would
    have.
    """
    now = when or timezone.now()
    amount_paise = int(amount_paise)

    try:
        # Nested atomic() gives this insert a savepoint, so a duplicate-email
        # race does not poison the caller's transaction.
        with transaction.atomic():
            spend, created = CustomerSpend.objects.get_or_create(
                email=email,
                defaults={
                    'total_paise': amount_paise,
                    'order_count': 1,
                    'currency': 'INR',
                    'first_order_at': now,
                    'last_order_at': now,
                },
            )
    except IntegrityError:
        spend, created = CustomerSpend.objects.get_or_create(
            email=email,
            defaults={
                'total_paise': amount_paise,
                'order_count': 1,
                'currency': 'INR',
                'first_order_at': now,
                'last_order_at': now,
            },
        )

    if not created:
        CustomerSpend.objects.filter(pk=spend.pk).update(
            total_paise=F('total_paise') + amount_paise,
            order_count=F('order_count') + 1,
            last_order_at=now,
        )

    spend.refresh_from_db()
    return spend


def create_demo_order(email, items, when=None):
    """Write the order lines and update the total. Returns (purchases, spend).

    `items` are StoreProduct instances (already resolved by the view). Nothing
    here contacts a payment gateway, and no card data exists anywhere in the
    call: the order is a database record with `payment_method='demo'`.
    """
    now = when or timezone.now()
    items = list(items)
    if not items:
        raise ValueError('an order needs at least one product')

    total_paise = sum(int(product.price_paise or 0) for product in items)

    with transaction.atomic():
        purchases = [
            Purchase.objects.create(
                product=product,
                email=email,
                # 'demo' is the column that records this was simulated.
                payment_method='demo',
                status='completed',
                completed_at=now,
                amount_paise=product.price_paise,
                currency='INR',
            )
            for product in items
        ]
        spend = record_spend(email, total_paise, when=now)

    return purchases, spend


def spend_summary(limit=10):
    """Top spenders, for the management command and the admin."""
    return CustomerSpend.objects.all().order_by('-total_paise')[:limit]