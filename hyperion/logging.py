from gunicorn.glogging import Logger


class RedactingLogger(Logger):
    def atoms(self, response, request, environ, request_time):
        atoms = super().atoms(response, request, environ, request_time)
        if environ.get('PATH_INFO', '').startswith('/content/'):
            atoms['U'] = '/content/[redacted]'
            atoms['r'] = f"{environ.get('REQUEST_METHOD', 'GET')} /content/[redacted]"
            atoms['q'] = ''
        return atoms
