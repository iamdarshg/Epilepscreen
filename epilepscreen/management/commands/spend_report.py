"""python manage.py spend_report [--limit 20] [--email someone@example.com]

Print the per-email running total kept in `customer_spend`. This is the table
`epilepscreen.orders.create_demo_order` maintains on every checkout; the command
reads it with one plain SQL statement so the numbers can be checked from a
terminal (and pasted into the practical's write-up) without the admin.

Nothing here is a real financial record: every row comes from a simulated
checkout with `payment_method = 'demo'`.
"""
from django.core.management.base import BaseCommand
from django.db import connection


def _console_safe(text):
    """₹ only prints on a UTF-8 console; older Windows code pages get 'Rs.'.

    `cmd.exe` still defaults to cp1252 on some machines, and a UnicodeEncodeError
    from a reporting command is a bad way to find that out.
    """
    import sys

    from epilepscreen.money import CURRENCY_SYMBOL

    encoding = getattr(sys.stdout, 'encoding', None) or 'utf-8'
    try:
        text.encode(encoding)
        return text
    except (UnicodeEncodeError, LookupError):
        return text.replace(CURRENCY_SYMBOL, 'Rs. ')


class Command(BaseCommand):
    help = "Show how much each email address has spent in the demonstration store."

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=20,
                            help='how many rows to print (default 20)')
        parser.add_argument('--email', type=str, required=False,
                            help='show one address only')

    def handle(self, *args, **options):
        from epilepscreen.money import format_paise

        limit = max(1, int(options['limit']))
        sql = ("SELECT email, total_paise, order_count, currency, last_order_at "
               "FROM customer_spend ")
        params = []

        if options.get('email'):
            sql += "WHERE email = %s "
            params.append(options['email'])

        sql += "ORDER BY total_paise DESC LIMIT %s"
        params.append(limit)

        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()

        if not rows:
            self.stdout.write('No orders recorded yet. Run a demo checkout first.')
            return

        self.stdout.write(f'{"email":32} {"orders":>6} {"total":>14}  last order')
        self.stdout.write('-' * 76)
        for email, total_paise, order_count, currency, last_order_at in rows:
            self.stdout.write(_console_safe(
                f'{email:32} {order_count:>6} {format_paise(total_paise):>14}  '
                f'{last_order_at or "-"}'))

        grand_total = sum(int(row[1]) for row in rows)
        self.stdout.write('-' * 76)
        self.stdout.write(_console_safe(
            f'{"shown":32} {sum(int(r[2]) for r in rows):>6} '
            f'{format_paise(grand_total):>14}'))
        self.stdout.write(self.style.WARNING(
            'Demonstration data: payment_method is "demo" and no money moved.'))
