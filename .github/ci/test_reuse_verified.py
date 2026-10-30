import copy
from datetime import datetime, timedelta, timezone
import io
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import reuse_verified as ci


NOW = datetime(2026, 10, 30, 10, tzinfo=timezone.utc)
REPO = 'owner/admin'


def zipped(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return output.getvalue()


def fixture():
    receipt = {'schema': 1, 'repository': REPO, 'workflow': ci.WORKFLOW,
               'run_id': 10, 'run_attempt': 2, 'pr': 39, 'head_sha': 'head',
               'base_sha': 'base', 'tested_sha': 'tested-merge', 'tree_sha': 'tree',
               'frontend_artifact_id': 20, 'checks': dict.fromkeys(ci.GROUPS, 'success')}
    pull = {'number': 39, 'merged': True, 'merged_at': NOW.isoformat(),
            'merge_commit_sha': 'squash', 'base': {'ref': 'main'},
            'head': {'sha': 'head', 'repo': {'full_name': REPO}}}
    run = {'id': 10, 'run_number': 10, 'run_attempt': 2, 'event': 'pull_request',
           'path': ci.WORKFLOW, 'status': 'completed', 'conclusion': 'success',
           'repository': {'full_name': REPO}, 'head_repository': {'full_name': REPO},
           'head_sha': 'head', 'created_at': NOW.isoformat(), 'updated_at': NOW.isoformat()}
    artifact = {'id': 20, 'name': 'verified-frontend', 'expired': False,
                'workflow_run': {'id': 10, 'head_sha': 'head'}}
    tested = {'sha': 'tested-merge', 'tree': {'sha': 'tree'},
              'parents': [{'sha': 'base'}, {'sha': 'head'}]}
    return receipt, dict(repository=REPO, target_sha='squash', target_tree='tree',
                        target_parent='base', pull=pull, run=run, artifact=artifact,
                        tested_commit=tested, now=NOW)


class ValidationTest(unittest.TestCase):
    def test_exact_tested_merge_tree_reused_even_with_squash_sha(self):
        receipt, args = fixture()
        ci.validate(receipt, **args)

    def test_changed_app_config_lockfile_or_workflow_tree_rejected(self):
        for change in ('application', 'configuration', 'lockfile', 'workflow'):
            with self.subTest(change=change):
                receipt, args = fixture()
                args['target_tree'] = change
                with self.assertRaises(ValueError):
                    ci.validate(receipt, **args)

    def test_provenance_mutations_rejected(self):
        mutations = [
            ('pull', 'merged', False), ('pull', 'merge_commit_sha', 'different-main'),
            ('pull', 'base', {'ref': 'other'}),
            ('pull', 'head', {'sha': 'head', 'repo': {'full_name': 'fork/admin'}}),
            ('run', 'event', 'pull_request_target'), ('run', 'path', 'different.yml'),
            ('run', 'repository', {'full_name': 'fork/admin'}),
            ('run', 'head_repository', {'full_name': 'fork/admin'}),
            ('run', 'status', 'in_progress'), ('run', 'conclusion', 'failure'),
            ('run', 'head_sha', 'new-head'), ('run', 'run_attempt', 3),
            ('tested_commit', 'tree', {'sha': 'different'}),
            ('tested_commit', 'parents', [{'sha': 'old-base'}, {'sha': 'head'}]),
            ('artifact', 'id', 21), ('artifact', 'name', 'unverified'),
            ('artifact', 'expired', True),
            ('artifact', 'workflow_run', {'id': 9, 'head_sha': 'head'}),
        ]
        for obj, key, value in mutations:
            with self.subTest(object=obj, key=key):
                receipt, args = fixture()
                args[obj][key] = value
                with self.assertRaises(ValueError):
                    ci.validate(receipt, **args)

    def test_receipt_cannot_substitute_a_different_identity_or_skip_tests(self):
        for key, value in {'schema': 2, 'pr': 1, 'run_id': 2, 'run_attempt': 1,
                           'repository': 'fork/admin', 'workflow': 'other',
                           'head_sha': 'new', 'base_sha': 'old', 'tested_sha': 'head',
                           'tree_sha': 'old', 'checks': {'build': 'success'}}.items():
            with self.subTest(key=key):
                receipt, args = fixture()
                receipt[key] = value
                with self.assertRaises(ValueError):
                    ci.validate(receipt, **args)

    def test_old_or_future_evidence_rejected(self):
        for delta in (timedelta(hours=24, seconds=1), timedelta(seconds=-1)):
            receipt, args = fixture()
            args['run']['created_at'] = (NOW - delta).isoformat()
            with self.assertRaises(ValueError):
                ci.validate(receipt, **args)

    def test_partial_rerun_does_not_refresh_old_verification(self):
        receipt, args = fixture()
        args['run']['created_at'] = (NOW - timedelta(days=2)).isoformat()
        args['run']['updated_at'] = NOW.isoformat()
        with self.assertRaisesRegex(ValueError, 'older than 24 hours'):
            ci.validate(receipt, **args)

    def test_all_job_result_combinations_preserve_gate(self):
        for reused, reuse_result, values in itertools.product(
                (False, True), ('success', 'failure', 'cancelled', 'skipped'),
                itertools.product(('success', 'failure', 'cancelled', 'skipped'), repeat=3)):
            expected = (reuse_result == 'success' and values == ('skipped',) * 3
                        if reused else values == ('success',) * 3)
            checks = dict(zip(ci.GROUPS, values))
            if expected:
                ci.gate(reused, reuse_result, checks)
            else:
                with self.assertRaises(ValueError):
                    ci.gate(reused, reuse_result, checks)


class FakeGitHub:
    def __init__(self):
        self.receipt, self.data = fixture()
        self.runs = [self.data['run']]
        self.receipts = [{'id': 30, 'name': 'verified-ci-2', 'expired': False}]
        self.frontend = zipped({'index.html': 'verified build', 'assets/main.js': 'candidate'})

    def get(self, path):
        if path == '/commits/squash/pulls?per_page=100':
            return [self.data['pull']]
        if path == '/pulls/39':
            return self.data['pull']
        if path.startswith('/actions/workflows/'):
            return {'workflow_runs': self.runs}
        if path == '/actions/runs/10/artifacts?per_page=100':
            return {'artifacts': self.receipts}
        if path == '/git/commits/tested-merge':
            return self.data['tested_commit']
        if path == '/actions/artifacts/20':
            return self.data['artifact']
        raise AssertionError(path)

    def archive(self, artifact_id):
        if artifact_id == 30:
            return zipped({'verified-ci.json': json.dumps(self.receipt)})
        if artifact_id == 20:
            return self.frontend
        raise AssertionError(artifact_id)


class ResolverTest(unittest.TestCase):
    def resolve(self, api, destination):
        return ci.resolve(api, repository=REPO, target_sha='squash', target_tree='tree',
                          target_parent='base', destination=destination, now=NOW)

    def test_verified_artifact_copied_without_executing_it(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'dist'
            self.assertEqual(self.resolve(FakeGitHub(), target), 10)
            self.assertEqual((target / 'index.html').read_text(), 'verified build')

    def test_latest_failed_or_pending_run_does_not_use_older_success(self):
        for status, result in [('completed', 'failure'), ('in_progress', None),
                               ('completed', 'cancelled')]:
            api = FakeGitHub()
            newer = copy.deepcopy(api.runs[0])
            newer.update(id=11, run_number=11, status=status, conclusion=result)
            api.runs.append(newer)
            with self.assertRaisesRegex(ValueError, 'Latest PR run'):
                ci.find_candidate(api, 'squash', REPO)

    def test_missing_expired_and_previous_attempt_receipts_fall_back(self):
        for receipts in ([], [{'id': 30, 'name': 'verified-ci-1', 'expired': False}],
                         [{'id': 30, 'name': 'verified-ci-2', 'expired': True}]):
            api = FakeGitHub()
            api.receipts = receipts
            with self.assertRaisesRegex(ValueError, 'No receipt'):
                ci.find_candidate(api, 'squash', REPO)

    def test_incomplete_or_traversal_artifacts_do_not_create_dist(self):
        for files in ({'assets/main.js': 'no html'}, {'../outside': 'bad'},
                      {'/absolute': 'bad'}, {'C:\\absolute': 'bad'}):
            api = FakeGitHub()
            api.frontend = zipped(files)
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / 'dist'
                with self.assertRaises(ValueError):
                    self.resolve(api, target)
                self.assertFalse(target.exists())

    def test_record_uses_tested_git_tree_not_pr_head_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'event.json').write_text(json.dumps({'pull_request': {
                'number': 39, 'head': {'sha': 'head'}, 'base': {'sha': 'base'}}}))
            env = {'GITHUB_EVENT_NAME': 'pull_request', 'GITHUB_EVENT_PATH': str(root / 'event.json'),
                   'GITHUB_REPOSITORY': REPO, 'GITHUB_RUN_ID': '10', 'GITHUB_RUN_ATTEMPT': '2'}
            with patch.object(ci, 'git', side_effect=['tested-merge', 'tree']):
                ci.record(root / 'receipt.json', 20, dict.fromkeys(ci.GROUPS, 'success'), env)
            self.assertEqual(json.loads((root / 'receipt.json').read_text()), fixture()[0])
            with self.assertRaises(ValueError):
                ci.record(root / 'receipt.json', 20, dict.fromkeys(ci.GROUPS, 'skipped'), env)

    def test_transport_failure_chooses_full_ci_without_leaking_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'output'
            env = {'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF': 'refs/heads/main',
                   'GITHUB_REPOSITORY': REPO, 'GH_TOKEN': 'do-not-log',
                   'RUNNER_TEMP': directory, 'GITHUB_OUTPUT': str(output)}
            printed = io.StringIO()
            with patch.dict(ci.os.environ, env), patch('sys.argv', ['ci', 'resolve']), \
                    patch.object(ci, 'git', return_value='test'), \
                    patch.object(ci, 'resolve', side_effect=OSError('secret-url')), \
                    patch('sys.stdout', printed):
                ci.main()
            self.assertIn('reused=false', output.read_text())
            self.assertNotIn('secret-url', printed.getvalue())
            self.assertNotIn('do-not-log', printed.getvalue())


if __name__ == '__main__':
    unittest.main()
