import logging


class RedactContent(logging.Filter):
    def filter(self, record):
        request = getattr(record, 'request', None)
        if request and request.path.startswith('/content/'):
            record.msg = 'Report request failed (%s): /content/[redacted]'
            record.args = (getattr(record, 'status_code', 'error'),)
        return True
