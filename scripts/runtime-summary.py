"""Read structured application logs from stdin; print aggregate operational metrics."""
from collections import defaultdict
import json
import math
import re
import sys


def summarize(lines):
    routes, stages, pools = defaultdict(list), defaultdict(list), {}
    statuses = defaultdict(int)
    peak_rss = 0
    for line in lines:
        event = None
        start = line.find('{')
        if start >= 0:
            try: event = json.loads(line[start:])
            except ValueError: pass
        if isinstance(event, dict) and event.get('event') == 'request_timing':
            route = event.get('route', '<unknown>')
            value = event.get('durationMs')
            if isinstance(value, (float, int)) and math.isfinite(value):
                routes[route].append(value)
                statuses[str(event.get('status'))] += 1
        elif isinstance(event, dict) and event.get('event') == 'worker_resources':
            peak_rss = max(peak_rss, event.get('rssKiB', 0))
            for name, stats in event.get('pools', {}).items():
                pools[f"{event.get('pid')}:{name}"] = {k: v for k,v in stats.items()
                    if k in {'pool_size','pool_available','requests_waiting','requests_errors','requests_wait_ms','requests_queued'}}
        else:
            match = re.search(r'export_stage request_id=[a-f0-9]* phase=(\w+) duration_ms=([0-9.]+)', line)
            if match: stages[match[1]].append(float(match[2]))
    def metrics(values):
        values = sorted(values)
        return {'count':len(values), 'p50Ms':values[math.ceil(len(values)*.5)-1],
                'p95Ms':values[math.ceil(len(values)*.95)-1], 'maxMs':values[-1]}
    return {'routes':{k:metrics(v) for k,v in routes.items()},
        'exportStages':{k:metrics(v) for k,v in stages.items()},
        'statusCounts':dict(statuses),'maxObservedWorkerRssKiB':peak_rss,'latestPools':pools}


if __name__ == '__main__':
    print(json.dumps(summarize(sys.stdin),ensure_ascii=False,indent=2))
