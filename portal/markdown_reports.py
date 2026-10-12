import io
from pathlib import PurePosixPath
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe
from markdown_it import MarkdownIt


def render_markdown(stream, path):
    with stream:
        source = stream.read(8 * 1024 * 1024 + 1)
    if len(source) > 8 * 1024 * 1024:
        raise ValueError('Markdown report exceeds the 8 MB rendering limit')
    # Disable raw HTML and retain the parser's unsafe-link validation.
    parser = MarkdownIt('commonmark', {'html': False}).enable('table').enable('strikethrough')
    body = parser.render(source.decode('utf-8-sig'))
    page = render_to_string('portal/markdown_report.html', {
        'title': PurePosixPath(path).stem.replace('_', ' ').replace('-', ' '),
        'body': mark_safe(body),
    })
    return io.BytesIO(page.encode())
