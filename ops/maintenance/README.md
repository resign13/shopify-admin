# Maintenance document/API negotiation

- Global maintenance still uses the existing `/etc/gingtto/maintenance` flag. This configuration does not turn it on.
- Browser GET/HEAD document requests accepting HTML receive the existing Chinese admin page or an English store page, with HTTP 503, no-store and Retry-After.
- API, static-file and non-document requests retain JSON `code=maintenance` and the explicit `X-Gingtto-Maintenance: 1` header.
- The existing admin backend-health fallback remains in place.
- Already-loaded apps keep their route and form mounted under an inert maintenance notice. Only GET health checks are made; recovery requires Continue and does not reload or replay the failed operation.

## Operations

`patch.py` replaces only the old named JSON maintenance handler in the two existing HTTPS security snippets. `install.py` installs the maps in `conf.d`, the response snippet and the two static documents, runs `nginx -t`, then reloads nginx. It keeps original files in a root-only operator record and checks that both application masters and release pointers are unchanged.

Run `verify_nginx.py` against a standalone nginx process on a private loopback port before installation. Its marker is under a temporary directory, never the live maintenance flag. It covers document/API/asset/POST/HEAD negotiation, flag removal and the previous admin health fallback.

These operator assets live outside the application release inventory, so installing nginx configuration does not change the backend fingerprint or require a backend restart. Application releases contain only the frontend changes and are eligible for the existing static-only switch after runtime preflight confirms it.

Do not activate the live maintenance flag merely to test this installation; request a separate maintenance window for that check.
