"""Independent security cutovers. Deferred features never enable implicitly."""
import os


def attachment_mode():
    value = os.environ.get('SECURITY_ATTACHMENT_MODE', 'legacy')
    if value not in {'legacy', 'private'}:
        raise RuntimeError('Invalid SECURITY_ATTACHMENT_MODE')
    return value


def login_protection_enabled():
    value = os.environ.get('SECURITY_LOGIN_PROTECTION_ENABLED', '0')
    if value not in {'0', '1'}:
        raise RuntimeError('Invalid SECURITY_LOGIN_PROTECTION_ENABLED')
    return value == '1'
