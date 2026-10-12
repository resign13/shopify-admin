"""Explicit capabilities; NULL uses legacy defaults without implicitly granting presale."""
MODULES = ['dashboard','products','inventory','orders','categories','presale',
           'store-accounts','admin-users','audit-logs','contracts']
CAPABILITIES = {
    'admin': MODULES,
    'sales': ['dashboard','products','inventory','orders','categories','contracts','presale'],
    'warehouse': ['inventory','orders'], 'customer': ['inventory'],
}
DEFAULTS = {**CAPABILITIES, 'sales': [k for k in CAPABILITIES['sales'] if k != 'presale']}


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
    if module in {'home-config','activity-config','banners'}:
        return user.get('role') == 'admin' and 'presale' in granted and (method == 'GET' or module != 'banners')
    if module == 'presale':
        return user.get('role') in {'admin','sales'} and 'presale' in granted
    if module == 'order-notifications':
        return user.get('role') in {'admin','sales','warehouse'} and 'orders' in granted
    if module == 'salespeople': return bool(granted & {'dashboard','orders','store-accounts'})
    if module == 'catalog-options': return bool(granted)
    if module == 'uploads': return bool(granted & {'products','orders','contracts'})
    if module == 'products' and method == 'GET':
        return bool(granted & {'products','orders','contracts','presale'})
    if module == 'store-users': module = 'store-accounts'
    return module in granted


def can_administer(user):
    return user.get('status') == 'active' and user.get('role') == 'admin' and 'admin-users' in effective(user)
