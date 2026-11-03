from django import template

register = template.Library()


@register.filter
def nickname_lines(value):
    """Interpret literal backslash-n for display, leaving stored names intact."""
    return str(value).replace('\\n', '\n')
