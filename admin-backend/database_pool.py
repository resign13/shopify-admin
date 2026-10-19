"""Bounded, process-local connection reuse without transaction/auth caching.

The legacy connection contract is retained: context success commits, exceptions
roll back, and an explicit close rolls back. A lease is invalid after return.
Separate budgets isolate business queries, export coordination and machine API.
"""
import atexit
import hashlib
import json
import os
import threading

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolTimeout, PoolClosed, TooManyRequests


class DatabaseBusy(psycopg.OperationalError):
    """Capacity/connection acquisition failed; no SQL statement was replayed."""


_lock = threading.RLock()
_pools = {}


def _reset(conn):
    # Pool rolls back unfinished/aborted transactions before calling reset.
    # DISCARD ALL also removes advisory locks, SET ROLE, temp tables and GUCs.
    # Automatic prepared statements are disabled: the server cache is cleared.
    conn.autocommit = True
    conn.execute('DISCARD ALL')
    conn.isolation_level = None
    conn.read_only = None
    conn.deferrable = None
    conn.row_factory = dict_row
    conn.autocommit = False


def close_all():
    with _lock:
        current = list(_pools.values())
        _pools.clear()
    for _, pool in current:
        pool.close(timeout=5)


def _after_fork():
    global _lock, _pools
    _lock = threading.RLock()
    _pools = {}


atexit.register(close_all)
if hasattr(os, 'register_at_fork'):
    # Gunicorn preloaded master has no live request transactions at fork.
    # Drain master idle sockets before workers inherit any descriptors.
    os.register_at_fork(before=close_all, after_in_child=_after_fork)


def _number(name, default, low, high, integer=False):
    value = (int if integer else float)(os.environ.get(name, str(default)))
    if not low <= value <= high:
        raise ValueError('Invalid database pool capacity setting: '+name)
    return value


def enabled(prefix='DB'):
    value=os.environ.get(prefix+'_POOL_ENABLED','1')
    if value not in {'0','1'}: raise ValueError('Invalid database pool enable setting')
    if value=='0': return False
    # No pool is opened by production schema checks/import-time Gunicorn
    # preload. Request/worker threads open their own lazy process-local pools.
    from flask import has_request_context
    return has_request_context() or os.environ.get('APP_ENV')=='test'


class Lease:
    def __init__(self, conn, pool):
        object.__setattr__(self, '_conn', conn)
        object.__setattr__(self, '_pool', pool)
        object.__setattr__(self, '_returned', False)
        object.__setattr__(self, '_pid', os.getpid())
        object.__setattr__(self, '_return_lock', threading.RLock())

    def _check(self):
        if self._returned or self._pid != os.getpid():
            raise psycopg.OperationalError('Database connection lease is closed')

    @property
    def closed(self):
        return self._returned or self._pid!=os.getpid() or self._conn.closed

    def __getattr__(self, name):
        self._check()
        return getattr(self._conn, name)

    def __setattr__(self, name, value):
        if name.startswith('_'): object.__setattr__(self,name,value)
        else:
            self._check()
            setattr(self._conn,name,value)

    def __enter__(self):
        self._check()
        return self

    def __exit__(self, exc_type, exc, tb):
        with self._return_lock:
            if self.closed:
                self.close()
                return
            try:
                if exc_type:
                    try: self._conn.rollback()
                    except psycopg.Error: self._conn.close()
                else: self._conn.commit()
            finally: self.close()

    def close(self):
        with self._return_lock:
            if self._returned: return
            self._check()
            object.__setattr__(self,'_returned',True)
            try:
                if not self._conn.closed and self._conn.info.transaction_status in (TransactionStatus.INTRANS,TransactionStatus.INERROR):
                    self._conn.rollback()
            except psycopg.Error:
                self._conn.close()
            finally:
                self._pool.putconn(self._conn)


def borrow(kwargs, *, namespace, prefix='DB', settings=None, default_size=4):
    """One bounded pool per purpose; credentials/database changes retire it.

    Passwords participate in an internal hash, never a log/metric/pool name.
    No fallback to any other namespace, identity, or unbounded raw connection.
    """
    size=_number(prefix+'_POOL_MAX',default_size,1,16,True)
    waiting=_number(prefix+'_POOL_MAX_WAITING',32,1,128,True)
    timeout=_number(prefix+'_POOL_TIMEOUT_SECONDS',2,0.1,10)
    configuration=dict(kwargs)
    autocommit=configuration.pop('autocommit',False)
    configuration.pop('options',None)
    configuration.update(autocommit=False,prepare_threshold=None,application_name='gingtto-'+namespace,options='')
    fingerprint=hashlib.sha256(json.dumps({k:str(v) for k,v in configuration.items()},sort_keys=True).encode()).hexdigest()
    identity=(os.getpid(),fingerprint,size,waiting,timeout)
    retired=None
    with _lock:
        old=_pools.get(namespace)
        if old and old[0]!=identity:
            retired=old[1]
            old=None
        if not old:
            pool=ConnectionPool(kwargs=configuration,min_size=0,max_size=size,
                max_waiting=waiting,timeout=timeout,max_lifetime=900,max_idle=60,
                num_workers=1,reconnect_timeout=15,name='gingtto-'+namespace,
                check=ConnectionPool.check_connection,reset=_reset,open=True)
            _pools[namespace]=(identity,pool)
        else: pool=old[1]
    if retired: retired.close(timeout=5)
    try: conn=pool.getconn(timeout=timeout)
    except (PoolTimeout,PoolClosed,TooManyRequests) as error:
        raise DatabaseBusy('Database connection budget is temporarily busy') from None
    try:
        conn.autocommit=True
        if settings:
            # Operator-controlled settings only; no user values in SQL text.
            pairs=list(settings.items())
            expression=','.join(['set_config(%s,%s,false)']*len(pairs))
            conn.execute('SELECT '+expression,[str(v) for pair in pairs for v in pair])
        conn.autocommit=autocommit
        return Lease(conn,pool)
    except BaseException:
        pool.putconn(conn)
        raise


def statistics():
    with _lock:
        return {name:{'pid':identity[0],**pool.get_stats()} for name,(identity,pool) in _pools.items()}
