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
def rupees(paise):
    """49900 -> ₹499, 499450 -> ₹4,994.50. Cent-style integers in, text out."""
    from epilepscreen.money import format_paise

    return format_paise(paise)


# Kept so older templates keep working; both filters do the same thing now.
money = rupees