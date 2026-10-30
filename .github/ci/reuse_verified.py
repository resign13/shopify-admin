"""Reuse a successful PR build only for the exact tested merge tree.

This is an optional fast path, not a release authorization. Missing/expired
evidence or GitHub transport errors fall back to all existing CI jobs.
"""
import argparse
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile


WORKFLOW = '.github/workflows/deploy.yml'
MAX_AGE_SECONDS = 24 * 60 * 60
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
GROUPS = ('build', 'backend', 'browsers')


def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHub:
    def __init__(self, repository, token):
        self.base = f'https://api.github.com/repos/{repository}'
        self.headers = {'Authorization': f'Bearer {token}',
                        'Accept': 'application/vnd.github+json',
                        'X-GitHub-Api-Version': '2022-11-28'}

    def get(self, path):
        request = urllib.request.Request(self.base + path, headers=self.headers)
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)

    def archive(self, artifact_id):
        request = urllib.request.Request(
            self.base + f'/actions/artifacts/{int(artifact_id)}/zip', headers=self.headers)
        # GitHub redirects to signed blob storage. Never forward the API token.
        try:
            response = urllib.request.build_opener(NoRedirect).open(request, timeout=20)
        except urllib.error.HTTPError as error:
            if error.code != 302:
                raise
            location = error.headers['Location']
            require(urllib.parse.urlsplit(location).scheme == 'https', 'Non-HTTPS artifact')
            response = urllib.request.urlopen(location, timeout=30)
        with response:
            payload = response.read(MAX_ARCHIVE_BYTES + 1)
        require(len(payload) <= MAX_ARCHIVE_BYTES, 'Artifact exceeds limit')
        return payload


def unpack(payload, target):
    """Extract data, never execute downloaded scripts or accept traversal paths."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        require(sum(item.file_size for item in archive.infolist()) <= MAX_ARCHIVE_BYTES,
                'Expanded artifact exceeds limit')
        for item in archive.infolist():
            path = PurePosixPath(item.filename)
            require(not path.is_absolute() and '..' not in path.parts
                    and '\\' not in item.filename and ':' not in item.filename
                    and not stat.S_ISLNK(item.external_attr >> 16), 'Invalid artifact path')
        archive.extractall(target)


def validate(receipt, *, repository, target_sha, target_tree, target_parent,
             pull, run, tested_commit, artifact, now):
    """Every input except receipt is read from Git/GitHub, not the artifact."""
    require(pull['merged'] and pull['merge_commit_sha'] == target_sha
            and pull['base']['ref'] == 'main', 'Not this merged PR')
    require(pull['head']['repo']['full_name'] == repository, 'Fork results not reused')
    require(run['event'] == 'pull_request' and run['path'] == WORKFLOW
            and run['repository']['full_name'] == repository
            and run['head_repository']['full_name'] == repository,
            'Different workflow/repository')
    require(run['status'] == 'completed' and run['conclusion'] == 'success',
            'Latest PR run did not succeed')
    require(run['head_sha'] == pull['head']['sha'], 'Different PR head')
    # A partial rerun updates updated_at without rerunning previously successful
    # audits. Use the original run creation time, not its latest metadata edit.
    age = (now - datetime.fromisoformat(run['created_at'].replace('Z', '+00:00'))).total_seconds()
    require(0 <= age <= MAX_AGE_SECONDS, 'PR verification older than 24 hours')
    require(receipt['schema'] == 1 and receipt['repository'] == repository
            and receipt['workflow'] == WORKFLOW
            and receipt['run_id'] == run['id']
            and receipt['run_attempt'] == run['run_attempt']
            and receipt['pr'] == pull['number']
            and receipt['head_sha'] == run['head_sha'], 'Receipt identity mismatch')
    require(receipt['checks'] == {group: 'success' for group in GROUPS},
            'Incomplete verification groups')
    # Tree identity includes application, tests, dependency locks, configuration
    # and this workflow. Also require the tested base to be main's actual parent.
    require(receipt['tested_sha'] == tested_commit['sha']
            and receipt['tree_sha'] == tested_commit['tree']['sha'] == target_tree,
            'Merged source/configuration differs from tested tree')
    require(receipt['base_sha'] == target_parent
            and [p['sha'] for p in tested_commit['parents']]
            == [target_parent, receipt['head_sha']], 'Tested merge base differs')
    require(artifact['id'] == receipt['frontend_artifact_id']
            and artifact['name'] == 'verified-frontend' and not artifact['expired']
            and artifact['workflow_run']['id'] == run['id']
            and artifact['workflow_run']['head_sha'] == run['head_sha'],
            'Build artifact is not the verified candidate')


def find_candidate(api, target_sha, repository):
    pulls = api.get(f'/commits/{target_sha}/pulls?per_page=100')
    merged = [p for p in pulls if p.get('merged_at') and p['merge_commit_sha'] == target_sha
              and p['base']['ref'] == 'main' and p['head'].get('repo')
              and p['head']['repo']['full_name'] == repository]
    require(len(merged) == 1, 'No unique same-repository merged PR')
    pull = api.get(f"/pulls/{merged[0]['number']}")
    workflow = urllib.parse.quote(WORKFLOW.rsplit('/', 1)[1])
    runs = api.get(f"/actions/workflows/{workflow}/runs?event=pull_request"
                   f"&head_sha={pull['head']['sha']}&per_page=100")['workflow_runs']
    # Do not select an older green run when a newer run failed or is pending.
    runs = [r for r in runs if r['head_sha'] == pull['head']['sha']]
    require(bool(runs), 'No PR workflow run')
    run = max(runs, key=lambda r: (r['run_number'], r['run_attempt']))
    require(run['status'] == 'completed' and run['conclusion'] == 'success',
            'Latest PR run did not succeed')
    artifacts = api.get(f"/actions/runs/{run['id']}/artifacts?per_page=100")['artifacts']
    receipts = [a for a in artifacts if a['name'] == f"verified-ci-{run['run_attempt']}"
                and not a['expired']]
    require(len(receipts) == 1, 'No receipt from the latest run attempt')
    with tempfile.TemporaryDirectory() as directory:
        unpack(api.archive(receipts[0]['id']), directory)
        path = Path(directory) / 'verified-ci.json'
        require(path.stat().st_size < 64 * 1024, 'Invalid receipt size')
        receipt = json.loads(path.read_text(encoding='utf-8'))
    return pull, run, receipt


def resolve(api, *, repository, target_sha, target_tree, target_parent, destination, now):
    pull, run, receipt = find_candidate(api, target_sha, repository)
    tested = api.get(f"/git/commits/{receipt['tested_sha']}")
    artifact = api.get(f"/actions/artifacts/{int(receipt['frontend_artifact_id'])}")
    validate(receipt, repository=repository, target_sha=target_sha,
             target_tree=target_tree, target_parent=target_parent, pull=pull,
             run=run, tested_commit=tested, artifact=artifact, now=now)
    with tempfile.TemporaryDirectory() as directory:
        unpack(api.archive(artifact['id']), directory)
        require((Path(directory) / 'index.html').is_file(), 'Build is incomplete')
        # Keep a partially downloaded build out of the application's dist path.
        require(not destination.exists(), 'Build destination already exists')
        shutil.copytree(directory, destination)
    return run['id']


def record(destination, artifact_id, checks, environ=os.environ):
    require(checks == {group: 'success' for group in GROUPS}, 'Full CI must succeed')
    require(environ['GITHUB_EVENT_NAME'] == 'pull_request', 'Only full PR runs produce receipts')
    event = json.loads(Path(environ['GITHUB_EVENT_PATH']).read_text(encoding='utf-8'))
    pull = event['pull_request']
    receipt = {
        'schema': 1, 'repository': environ['GITHUB_REPOSITORY'], 'workflow': WORKFLOW,
        'run_id': int(environ['GITHUB_RUN_ID']), 'run_attempt': int(environ['GITHUB_RUN_ATTEMPT']),
        'pr': pull['number'], 'head_sha': pull['head']['sha'], 'base_sha': pull['base']['sha'],
        'tested_sha': git('rev-parse', 'HEAD'), 'tree_sha': git('rev-parse', 'HEAD^{tree}'),
        'frontend_artifact_id': int(artifact_id), 'checks': checks,
    }
    destination.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')


def gate(reused, reuse_result, checks):
    if reused:
        require(reuse_result == 'success' and all(checks[g] == 'skipped' for g in GROUPS),
                'Reuse did not complete cleanly')
    else:
        require(all(checks[g] == 'success' for g in GROUPS), 'Full CI did not succeed')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['resolve', 'record', 'gate'])
    args = parser.parse_args()
    env = os.environ
    checks = {group: env.get(group.upper() + '_RESULT', '') for group in GROUPS}
    if args.action == 'gate':
        gate(env.get('REUSED') == 'true', env.get('REUSE_RESULT', ''), checks)
    elif args.action == 'record':
        record(Path('verified-ci.json'), env['FRONTEND_ARTIFACT_ID'], checks)
    else:
        reused, source_run = False, ''
        try:
            require(env['GITHUB_EVENT_NAME'] == 'push' and env['GITHUB_REF'] == 'refs/heads/main',
                    'Full CI for PR/manual runs')
            source_run = resolve(GitHub(env['GITHUB_REPOSITORY'], env['GH_TOKEN']),
                                 repository=env['GITHUB_REPOSITORY'], target_sha=git('rev-parse', 'HEAD'),
                                 target_tree=git('rev-parse', 'HEAD^{tree}'),
                                 target_parent=git('rev-parse', 'HEAD^'),
                                 destination=Path(env['RUNNER_TEMP']) / 'reused-frontend',
                                 now=datetime.now(timezone.utc))
            reused = True
            print(f'Reusing verified PR run {source_run}; identical merge tree and base.')
        except Exception as error:
            # Never log credential-bearing URLs/headers from transport exceptions.
            reason = str(error) if type(error) is ValueError else type(error).__name__
            print(f'Full verification selected: {reason}')
        with open(env['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
            output.write(f'reused={str(reused).lower()}\nsource_run={source_run}\n')


if __name__ == '__main__':
    main()
