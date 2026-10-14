"""Fixture transport adapter. Business tests exercise real cookie/CSRF middleware."""
import os
from flask.testing import FlaskClient
import security_core


def install(application):
    if not security_core.test_database() or os.environ.get('APP_ENV') != 'test':
        raise RuntimeError('Cookie fixture client requires an isolated test database')

    class CookieFixtureClient(FlaskClient):
        def open(self, *args, **kwargs):
            headers = dict(kwargs.get('headers') or {})
            bearer = headers.pop('Authorization', '')
            security = application.extensions['security']
            row = None
            if bearer.startswith('Bearer '):
                token = bearer[7:]
                self.set_cookie(security.cookie, token)
                row = security_core.session(security.db, security.channel, token)
            method = kwargs.get('method', 'GET').upper()
            if method not in security_core.SAFE:
                if row:
                    headers.setdefault('X-CSRF-Token', security.csrf(row))
                else:
                    # A real pre-login CSRF request; no test-only auth bypass.
                    response = super().open('/api/auth/csrf', method='GET')
                    if response.is_json:
                        headers.setdefault('X-CSRF-Token', response.json.get('csrfToken', ''))
                headers.setdefault('Origin', 'http://localhost')
            kwargs['headers'] = headers
            return super().open(*args, **kwargs)

    application.test_client_class = CookieFixtureClient
