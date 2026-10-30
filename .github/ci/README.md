# CI / release verification

PRs still run every existing frontend, backend and browser check. A newer
commit cancels only older runs for that PR. Main runs remain serial and are
never automatically cancelled.

## Exact-result reuse on main

The optional `reuse` job accepts only a successful, same-repository PR run:

- It is the latest run/attempt for the merged PR head in `deploy.yml`.
- The tested Git merge tree equals main's tree, including application code,
  configuration, dependency locks, tests and workflow files.
- The tested PR base equals main's first parent. A changed base uses full CI.
- The receipt identifies that run/attempt and all three successful test groups.
- The frontend artifact ID is the immutable candidate built in that same run.
- Verification is at most 24 hours old, and both artifacts are still available.

The receipt is uploaded by `verify` only after full PR verification succeeds.
It records the checked-out synthetic merge commit, not just the PR head.
The build is downloaded as data into a temporary directory, then shared with
the existing deploy job. Downloaded scripts are never executed.

Any missing evidence, mismatch, expired artifact or API/download failure selects
the complete build/test path. Manual workflow runs always run full CI. The
stable required `verify` check accepts **either** successful exact reuse with
all full jobs skipped, **or** all full jobs successful; mixed results fail.

This does not authorize a release: `[no deploy]`, SSH host verification,
short-lived production approval, backups, health checks and rollback are
unchanged. No production change is needed for these CI improvements.

## Browser jobs

- The three isolated runner groups remain independent. Product weight/order
  lifecycle tests run in `operations` to balance the previously longer `orders`
  group. The mobile fixture's dependent stages remain in their original order.
- `.github/ci/playwright/package-lock.json` pins the already-tested CLI 0.1.22
  and its existing transitive versions. Install once per runner with `npm ci`,
  then use the same `playwright-cli` binary in all stages. The lock is included
  in the npm cache key; no dependency version upgrade is part of this change.
- The repeated layout/search checks wait for their actual API responses,
  rendered loading state and fonts instead of a global `networkidle` period.
  All screen sizes/assertions remain; voice timing and reconnect tests are
  unchanged.

Local policy tests (no database or network writes):

```sh
python -m unittest discover -s .github/ci -p 'test_*.py' -v
```

Browser regression still uses the guarded local `*_test` fixture, never the
manual mirror or production database. PR CI is the end-to-end Linux validation;
merging and publishing remain separate user decisions.
