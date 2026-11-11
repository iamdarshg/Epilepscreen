"""Small template filters used by the player and report pages.

Keeping the formatting here means the views hand templates plain numbers and
the HTML never has to do arithmetic.
"""
from django import template

register = template.Library()


@register.filter
def clock(seconds):
    """0:07.4 — minutes, seconds, tenths. Used for hazard timestamps."""
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return '--'
    if value < 0:
        value = 0.0
    minutes = int(value // 60)
    rest = value - minutes * 60
    return f'{minutes}:{rest:04.1f}'


@register.filter
def kind_label(value):
    labels = {
        'flicker': 'Flash / flicker',
        'red_flash': 'Red flash',
        'color_transition': 'Colour transition',
        'spatial_pattern': 'High-contrast pattern',
        'pattern_movement': 'Moving pattern',
    }
    return labels.get(value, value)


@register.filter
def attrs(value):
    """Flatten an event's attribute dict into 'key value' pairs."""
    if not isinstance(value, dict):
        return ''
    return ', '.join(f'{key} {val}' for key, val in value.items())


@register.filter
def money(cents):
    """1900 -> $19, 1999 -> $19.99. Cent amounts live in the database."""
    try:
        amount = int(cents) / 100
    except (TypeError, ValueError):
        return '$0'
    text = f'{amount:,.2f}'.rstrip('0').rstrip('.')
    return f'${text}'