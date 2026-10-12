import re
from django.conf import settings
from django.http import HttpResponseNotFound
from django.shortcuts import redirect

class HostBoundaryMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        host = request.get_host().lower()
        pattern = re.escape(settings.REPORT_HOST_TEMPLATE).replace(re.escape('{pi}'), r'(?P<pi>[0-9a-f-]{36})')
        match = re.fullmatch(pattern, host)
        request.report_pi = match.group('pi') if match else None
        if host == settings.PORTAL_HOST:
            if request.path.startswith('/content/'):
                return HttpResponseNotFound()
        elif match:
            if not request.path.startswith('/content/'):
                return HttpResponseNotFound()
        elif host == 'app' and request.path == '/health/':
            pass
        else:
            return HttpResponseNotFound()
        response = self.get_response(request)
        response['Referrer-Policy'] = 'no-referrer' if request.report_pi else 'same-origin'
        if not request.report_pi and 'Content-Security-Policy' not in response:
            response['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-src " + settings.REPORT_ORIGIN_TEMPLATE.replace('{pi}', '*').replace('pi-*.', '*.') + "; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        if not request.path.startswith('/static/'):
            response['Cache-Control'] = 'private, no-store'
        return response

class PasswordChangeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        if request.user.is_authenticated and request.user.must_change_password and not request.report_pi and not request.path.startswith(('/password/', '/logout/', '/static/')):
            return redirect('password_change')
        return self.get_response(request)
