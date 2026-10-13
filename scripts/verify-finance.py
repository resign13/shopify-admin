"""Read-only release check. No login, test accounts, costs or orders are created."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'admin-backend'))
import db
import module_permissions

with db._connect() as conn:
    conn.execute('SET TRANSACTION READ ONLY')
    for table in ('finance_cost_versions', 'finance_cost_history', 'finance_cost_audit',
                  'finance_cost_receipts', 'finance_settings'):
        assert conn.execute('SELECT to_regclass(%s) AS name', ('public.' + table,)).fetchone()['name'], table + ' missing'
    column = conn.execute("SELECT is_nullable FROM information_schema.columns WHERE table_schema='public' AND table_name='finance_cost_history' AND column_name='cost_cny'").fetchone()
    assert column and column['is_nullable'] == 'YES', 'Cost clearing requires nullable history'
    # Existing deployments validate role names in application code; they do not
    # require a database CHECK on this compatibility column.
    role_column = conn.execute("SELECT character_maximum_length FROM information_schema.columns WHERE table_schema='public' AND table_name='admin_users' AND column_name='role'").fetchone()
    assert role_column and role_column['character_maximum_length'] >= len('finance'), 'Finance role column missing'
    assert conn.execute('SELECT count(*) AS n FROM finance_settings').fetchone()['n'] <= 1, 'Exchange rate must be global'

for role in ('sales', 'warehouse', 'customer'):
    assert not module_permissions.allows_request({'role': role, 'permissions': None}, '/api/admin/finance/costs', 'GET')
assert module_permissions.allows_request({'role': 'finance', 'permissions': None}, '/api/admin/finance/costs', 'GET')
assert not module_permissions.allows_request({'role': 'finance', 'permissions': None}, '/api/admin/orders', 'POST')
print('Read-only finance schema, shared settings and permission checks passed.')
