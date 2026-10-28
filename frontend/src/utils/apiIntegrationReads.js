// API integration GETs have independent latest-request lifetimes.
// Sequence checks are required even when a transport ignores AbortSignal.
export function createApiReadTask(request, { active, loading, receive, fail }) {
  let sequence = 0, controller;
  function cancel() {
    ++sequence;
    controller?.abort();
    controller = undefined;
    if (active()) loading(false);
  }
  async function run(path) {
    if (!active()) return;
    const current = ++sequence;
    controller?.abort();
    const ownController = new AbortController();
    controller = ownController;
    const isCurrent = () => current === sequence && !ownController.signal.aborted && active();
    loading(true);
    try {
      const data = await request(path, { signal: ownController.signal });
      if (isCurrent()) { receive(data); return data; }
    } catch (error) {
      if (isCurrent() && error.name !== 'AbortError') fail(error);
    } finally {
      if (isCurrent()) { controller = undefined; loading(false); }
    }
  }
  return { run, cancel };
}

// Input edits stay drafts. Pagination and metadata reloads use the last submit.
export function createApiAccountQuery() {
  return {
    keyword: '', appliedKeyword: '', page: 1,
    submit() { this.appliedKeyword = this.keyword; this.page = 1; },
    params() { return new URLSearchParams({ keyword: this.appliedKeyword, page: this.page }).toString(); },
  };
}
