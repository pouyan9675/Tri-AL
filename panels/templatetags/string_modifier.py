from django import template
import re

register = template.Library()


@register.filter()
def remove_space(value):
    return value.replace(' ', '')



@register.filter()
def clean_agents(arr):
    arr = set([re.sub(r'\d+\s?mg.*', '', a.name) for a in arr if ('placebo' not in a.name.lower() and a.name.lower() != 'saline')])
    return arr


@register.filter()
def cap_string(value):
    if len(value) > 100:
        return value[:97].strip() + '...'
    return value


# register.filter('cut', cut)