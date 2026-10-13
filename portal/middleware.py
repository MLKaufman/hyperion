import ipaddress
from django.conf import settings
from django.http import HttpResponseNotFound
from django.shortcuts import redirect


class TrustedProxyMiddleware:
    """Accept scheme/client information only from explicitly trusted proxy hops."""
    def __init__(self, get_response):
        self.get_response = get_response
        self.networks = [ipaddress.ip_network(value) for value in settings.TRUSTED_PROXY_CIDRS]

    def trusted(self, address):
        return any(address in network for network in self.networks)

    def __call__(self, request):
        peer = request.META.get('REMOTE_ADDR', '')
        request.client_ip = peer
        try:
            if self.trusted(ipaddress.ip_address(peer)):
                scheme = request.META.get('HTTP_X_FORWARDED_PROTO', '')
                if scheme in {'http', 'https'}:
                    request.META['wsgi.url_scheme'] = scheme
                # Walk from the connection back toward the visitor, stopping at
                # the first untrusted hop. Never take a caller-supplied leftmost IP.
                for value in reversed(request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')):
                    address = ipaddress.ip_address(value.strip())
                    request.client_ip = str(address)
                    if not self.trusted(address):
                        break
        except ValueError:
            request.client_ip = peer
        return self.get_response(request)


class HostBoundaryMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().lower()
        request.is_report = request.path.startswith('/content/')
        if host != settings.PORTAL_HOST and not (host == 'app' and request.path == '/health/'):
            return HttpResponseNotFound()
        response = self.get_response(request)
        response['Referrer-Policy'] = 'no-referrer' if request.is_report else 'same-origin'
        if request.is_report:
            # Enforce the opaque origin even when a content URL is opened directly.
            # Never add allow-same-origin: reports share the portal's hostname.
            response['Content-Security-Policy'] = f"frame-ancestors {settings.PORTAL_ORIGIN}; sandbox allow-scripts allow-downloads"
        elif 'Content-Security-Policy' not in response:
            response['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        if not request.path.startswith('/static/'):
            response['Cache-Control'] = 'private, no-store'
        return response


class PasswordChangeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and request.user.must_change_password and not request.is_report and not request.path.startswith(('/password/', '/logout/', '/static/')):
            return redirect('password_change')
        return self.get_response(request)
