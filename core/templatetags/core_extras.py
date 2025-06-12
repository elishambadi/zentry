# core/templatetags/core_extras.py
from django import template

register = template.Library()

@register.filter
def lookup(dictionary, key):
    """Template filter to look up dictionary values by key"""
    if hasattr(dictionary, 'get'):
        return dictionary.get(key)
    return None

@register.filter
def mul(value, arg):
    """Multiply the value and argument"""
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0

@register.filter
def div(value, arg):
    """Divide the value by argument"""
    try:
        return float(value) / float(arg)
    except (ValueError, TypeError, ZeroDivisionError):
        return 0
    
@register.filter
def split(value, delimiter=','):
    """Split a string by the given delimiter"""
    if isinstance(value, str):
        return value.split(delimiter)
    return []
