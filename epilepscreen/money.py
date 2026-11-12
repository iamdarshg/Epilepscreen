"""Money formatting and parsing for the storefront.

Prices are stored as whole paise in integer columns — `price_paise = 49900` is
₹499 — because binary floating point cannot represent 0.1 exactly and a store
should never round a total by accident. This module is the only place that turns
that integer into something a person reads.

The grouping is the Indian one: the last three digits, then pairs. So
`12345678900` renders as ₹1,23,45,678.90, not ₹12,345,678.90.
"""

CURRENCY_SYMBOL = '₹'
CURRENCY_CODE = 'INR'


def group_indian(digits: str) -> str:
    """'1234567' -> '12,34,567'. Pure string work, no floats involved."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ','.join(parts + [tail])


def format_paise(paise) -> str:
    """49900 -> '₹499'; 49950 -> '₹499.50'; None -> '₹0'."""
    try:
        value = int(paise)
    except (TypeError, ValueError):
        return f'{CURRENCY_SYMBOL}0'

    sign = '-' if value < 0 else ''
    value = abs(value)
    rupees, fraction = divmod(value, 100)

    whole = group_indian(str(rupees))
    if fraction:
        return f'{sign}{CURRENCY_SYMBOL}{whole}.{fraction:02d}'
    return f'{sign}{CURRENCY_SYMBOL}{whole}'


def rupees_to_paise(text) -> int:
    """'499' or '499.50' or '₹1,999' -> paise. Raises ValueError on nonsense.

    Used by the management command that seeds or re-prices the catalogue, so a
    price typed by a human can never be stored as a float.
    """
    cleaned = str(text).strip().replace(CURRENCY_SYMBOL, '').replace(',', '')
    if not cleaned:
        raise ValueError('empty amount')
    if cleaned.count('.') > 1:
        raise ValueError(f'not an amount: {text!r}')
    if '.' in cleaned:
        whole, fraction = cleaned.split('.')
        if len(fraction) > 2 or not fraction.isdigit():
            raise ValueError(f'paise must be 0-2 digits: {text!r}')
        fraction = (fraction + '00')[:2]
    else:
        whole, fraction = cleaned, '00'
    if not whole.lstrip('-').isdigit() or not fraction.isdigit():
        raise ValueError(f'not an amount: {text!r}')
    return int(whole) * 100 + int(fraction)