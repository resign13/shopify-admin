"""Department defaults are templates; explicit staff module grants are authoritative."""
MODULES = ['dashboard','products','inventory','orders','categories','presale',
           'store-accounts','admin-users','audit-logs','contracts','finance','api-integrations','size-charts']
STAFF_ROLES = {'admin', 'sales', 'warehouse', 'finance'}
# Retain existing within-module operation limits (e.g. warehouse orders and
# salesperson ownership), without making departments a module whitelist.
BASE_OPERATION_MODULES = {
    'admin': MODULES,
    'sales': ['dashboard','products','inventory','orders','categories','contracts','presale'],
    'warehouse': ['inventory','orders'], 'customer': ['inventory'], 'finance': ['finance'],
}
CAPABILITIES = {role: list(MODULES) for role in STAFF_ROLES}
CAPABILITIES['customer'] = ['inventory']
DEFAULTS = {**BASE_OPERATION_MODULES,
            'sales': [k for k in BASE_OPERATION_MODULES['sales'] if k != 'presale'] + ['size-charts'],
            'finance': ['finance', 'contracts']}


def effective(user):
    role = user.get('role', 'admin')
    selected = user.get('permissions')
    if selected is None: return list(DEFAULTS.get(role, []))
    return [key for key in CAPABILITIES.get(role, []) if key in selected]


def validate(value, role):
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise ValueError('模块权限必须是列表')
    if any(v not in CAPABILITIES.get(role, []) for v in value):
        raise ValueError('包含当前角色不支持的模块权限')
    return list(dict.fromkeys(value))


def allows_request(user, path, method):
    granted = set(effective(user))
    if not path.startswith('/api/admin/'): return True
    module = path.split('/')[3]
    if module == 'finance':
        return user.get('role') in STAFF_ROLES and 'finance' in granted
    if module in {'home-config','activity-config','banners'}:
        return user.get('role') == 'admin' and 'presale' in granted and (method == 'GET' or module != 'banners')
    if module == 'presale':
        return user.get('role') in STAFF_ROLES and 'presale' in granted
    if module == 'order-notifications':
        return user.get('role') in STAFF_ROLES and 'orders' in granted
    if module == 'salespeople': return bool(granted & {'dashboard','orders','store-accounts'})
    if module == 'catalog-options': return bool(granted)
    if module == 'uploads': return bool(granted & {'products','orders','contracts'})
    if module == 'products' and method == 'GET':
        return bool(granted & {'products','orders','contracts','presale'})
    if module == 'store-users': module = 'store-accounts'
    return module in granted


def allows_operation(user, path, method, required_roles):
    if not allows_request(user, path, method): return False
    role = user.get('role')
    if role in required_roles: return True
    if role not in STAFF_ROLES or not path.startswith('/api/admin/'): return False
    module = path.split('/')[3]
    if module == 'store-users': module = 'store-accounts'
    if module == 'order-notifications': module = 'orders'
    if module == 'uploads':
        return bool(set(effective(user)) & {'products', 'orders', 'contracts'})
    if module == 'catalog-options': return True
    if module == 'salespeople':
        return bool((set(effective(user)) - set(BASE_OPERATION_MODULES.get(role, []))) & {'dashboard','orders','store-accounts'})
    if module == 'products' and method == 'GET':
        return bool(set(effective(user)) & {'products', 'contracts', 'presale'}) or (role != 'warehouse' and 'orders' in effective(user))
    # A department's existing workflow restrictions remain unchanged. Newly
    # enabled modules use their normal management operations, not a hidden ban.
    return module not in BASE_OPERATION_MODULES.get(role, []) and module in effective(user)


def can_administer(user):
    return user.get('status') == 'active' and user.get('role') in STAFF_ROLES and 'admin-users' in effective(user)
