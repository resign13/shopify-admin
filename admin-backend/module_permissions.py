"""Module access is an explicit subset of the existing role's capabilities.

NULL preserves legacy role defaults; [] deliberately grants no modules.
"""
MODULES = ['dashboard', 'products', 'inventory', 'orders', 'categories',
           'home-config', 'activity-zone/apply', 'activity-zone/manage',
           'store-accounts', 'admin-users', 'audit-logs', 'contracts']
DEFAULTS = {
    'admin': MODULES,
    'sales': MODULES[:8] + ['contracts'],
    'warehouse': ['inventory', 'orders'],
    'customer': ['inventory'],
}


def effective(user):
    available = DEFAULTS.get(user.get('role', 'admin'), [])
    selected = user.get('permissions')
    return [key for key in available if selected is None or key in selected]


def validate(value, role):
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise ValueError('模块权限必须是列表')
    if any(v not in DEFAULTS.get(role, []) for v in value):
        raise ValueError('包含当前角色不支持的模块权限')
    return list(dict.fromkeys(value))


def allows_request(user, path, method):
    granted = set(effective(user))
    if not path.startswith('/api/admin/'):
        return True
    module = path.split('/')[3]
    operations = {'home-config', 'activity-zone/apply', 'activity-zone/manage'}
    if module == 'catalog-options':
        return bool(granted)
    if module == 'uploads':
        return bool(granted & {'products', 'home-config', 'orders', 'contracts'})
    if module == 'products' and method == 'GET':
        # Order and operation editors need the same read-only product picker.
        return bool(granted & ({'products', 'orders', 'contracts'} | operations))
    if module == 'activity-config':
        return bool(granted & {'activity-zone/apply', 'activity-zone/manage'})
    if module == 'banners':
        module = 'home-config'
    if module == 'store-users':
        module = 'store-accounts'
    return module in granted


def can_administer(user):
    return user.get('status') == 'active' and user.get('role') == 'admin' and 'admin-users' in effective(user)
