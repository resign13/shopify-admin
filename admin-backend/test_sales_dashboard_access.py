"""Explicit permission upgrade on guarded synthetic fixtures, not production."""
import unittest
from test_workbench import seed, db
from sales_dashboard_access import MARKER, apply_once, candidates


class SalesDashboardAccessTest(unittest.TestCase):
    def setUp(self):
        seed()
        db._fetch_all('DELETE FROM sales_ownership_migrations WHERE name=%s RETURNING name', (MARKER,))

    def test_upgrade_preserves_modules_roles_and_audits_once(self):
        db._fetch_one("UPDATE admin_users SET permissions='[\"orders\",\"inventory\"]'::jsonb WHERE id=2 RETURNING id")
        disabled = db.create_admin_user({'name': 'Disabled', 'email': 'disabled@fixture.test', 'passwordHash': 'fixture',
                                        'role': 'sales', 'status': 'disabled', 'permissions': ['orders']})
        before = db._fetch_all('SELECT id,role,status,permissions FROM admin_users ORDER BY id')
        with db.get_connection() as conn:
            self.assertEqual([row['id'] for row in candidates(conn)], [2])
            self.assertEqual(apply_once(conn), {'alreadyApplied': False, 'changedIds': [2]})
        after = db._fetch_all('SELECT id,role,status,permissions FROM admin_users ORDER BY id')
        self.assertEqual(after[1]['permissions'], ['orders', 'inventory', 'dashboard'])
        self.assertEqual([row for row in before if row['id'] != 2], [row for row in after if row['id'] != 2])
        logs = db._fetch_all("SELECT * FROM admin_audit_logs WHERE entity_table='admin_users' AND action='UPDATE' AND actor->>'role'='system'")
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]['module'], 'admin-users')
        db._fetch_one("UPDATE admin_users SET permissions='[\"orders\"]'::jsonb WHERE id=2 RETURNING id")
        with db.get_connection() as conn:
            self.assertEqual(apply_once(conn), {'alreadyApplied': True, 'changedIds': []})
        self.assertEqual(db.get_admin_user_by_id(2)['permissions'], ['orders'])

    def test_explicit_empty_and_default_grants(self):
        db._fetch_one("UPDATE admin_users SET permissions='[]'::jsonb WHERE id=2 RETURNING id")
        with db.get_connection() as conn:
            self.assertEqual(apply_once(conn)['changedIds'], [2])
        self.assertEqual(db.get_admin_user_by_id(2)['permissions'], ['dashboard'])
