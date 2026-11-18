"""Settled-invoice archiving from the hot store into the cold store.

A job walks ``invoices_hot`` by invoice_id cursor in short batch
transactions. Each batch locks the candidate rows (FOR UPDATE), copies the
still-settled ones into ``invoices_cold`` and deletes them from the hot
store; the copy, the per-invoice audit item and the cursor advance commit
together, so the data location and query visibility switch atomically.

Crash safety: a batch either fully commits or fully rolls back, leaving the
cursor at the last committed invoice. Retrying a job continues from that
cursor; rows already moved are simply no longer in the hot store, so no
invoice is moved twice or missed. A reverted (pending) invoice is skipped
and stays hot.
"""
import logging,time,os
from datetime import datetime
from sqlalchemy import select,text
from fastapi import HTTPException
from ..config.database import Session,engine
from ..models.archive import ArchiveJob,ArchiveJobItem
from ..config.settings import ARCHIVE_BATCH_SIZE
from .batch import queue
LOG=logging.getLogger('archive')
JOB_QUEUE='query-review:archive-jobs'
LOCK_KEY='archive-job'
def serialize(job):
    return {'id':job.id,'upper_invoice_id':job.upper_invoice_id,'status':job.status,
            'total_candidates':job.total_candidates,'archived_count':job.archived_count,
            'skipped_count':job.skipped_count,'last_invoice_id':job.last_invoice_id,
            'error':job.error,'created_by':job.created_by,'created_at':str(job.created_at),
            'started_at':str(job.started_at) if job.started_at else None,
            'finished_at':str(job.finished_at) if job.finished_at else None}
def create_job(db,upper_invoice_id,actor):
    job=ArchiveJob(upper_invoice_id=upper_invoice_id,created_by=actor)
    db.add(job);db.commit();db.refresh(job)
    try:queue.rpush(JOB_QUEUE,job.id)
    except Exception:LOG.exception('enqueue failed, startup recovery will pick up job %s',job.id)
    return serialize(job)
def list_jobs(db):
    return [serialize(x) for x in db.scalars(select(ArchiveJob).order_by(ArchiveJob.id.desc()))]
def get_job(db,job_id):
    job=db.get(ArchiveJob,job_id)
    if not job:raise HTTPException(404,'归档任务不存在')
    return job
def job_detail(db,job_id):return serialize(get_job(db,job_id))
def list_items(db,job_id,state=None):
    get_job(db,job_id)
    stmt=select(ArchiveJobItem).where(ArchiveJobItem.job_id==job_id)
    if state in ('archived','skipped'):stmt=stmt.where(ArchiveJobItem.state==state)
    return [{'id':x.id,'job_id':x.job_id,'invoice_id':x.invoice_id,'state':x.state,'created_at':str(x.created_at)}
            for x in db.scalars(stmt.order_by(ArchiveJobItem.id.desc()).limit(1000))]
def retry_job(db,job_id):
    job=get_job(db,job_id)
    if job.status!='failed':raise HTTPException(409,'只有失败任务可以重试，当前状态：'+job.status)
    job.status='pending';job.error=None;job.finished_at=None
    db.commit()
    try:queue.rpush(JOB_QUEUE,job.id)
    except Exception:pass
    return serialize(job)
def _process_batch(db,job):
    """Move one batch. Returns (moved, skipped, last_id, done)."""
    rows=db.execute(text("""SELECT invoice_id,customer,route,amount,temperature,status,version
        FROM invoices_hot WHERE invoice_id>:cursor AND invoice_id<=:upper
        ORDER BY invoice_id LIMIT :n FOR UPDATE"""),
        {'cursor':job.last_invoice_id,'upper':job.upper_invoice_id,'n':ARCHIVE_BATCH_SIZE}).mappings().all()
    if not rows:return 0,0,job.last_invoice_id,True
    moved=skipped=0;last_id=job.last_invoice_id
    for row in rows:
        last_id=row['invoice_id']
        if row['status']!='settled':
            db.add(ArchiveJobItem(job_id=job.id,invoice_id=row['invoice_id'],state='skipped'))
            skipped+=1;continue
        inserted=db.execute(text("""INSERT INTO invoices_cold
            (invoice_id,customer,route,amount,temperature,status,version)
            VALUES (:invoice_id,:customer,:route,:amount,:temperature,:status,:version)
            ON CONFLICT (invoice_id) DO NOTHING"""),dict(row)).rowcount
        db.execute(text('DELETE FROM invoices_hot WHERE invoice_id=:id'),{'id':row['invoice_id']})
        db.add(ArchiveJobItem(job_id=job.id,invoice_id=row['invoice_id'],state='archived'))
        moved+=1
        if inserted==0:LOG.warning('invoice %s already existed in cold store for job %s',row['invoice_id'],job.id)
    job.last_invoice_id=last_id
    job.archived_count+=moved;job.skipped_count+=skipped
    db.commit()
    return moved,skipped,last_id,False
def run_job(job_id):
    lock_conn=engine.connect();acquired=False
    try:
        acquired=lock_conn.execute(text('SELECT pg_try_advisory_lock(hashtext(:k))'),{'k':f'{LOCK_KEY}-{job_id}'}).scalar()
        if not acquired:
            LOG.info('job %s already running elsewhere, skip',job_id);return
        with Session() as db:
            job=db.get(ArchiveJob,job_id)
            if not job or job.status in ('completed','failed'):return
            if job.status=='pending':
                job.total_candidates=db.execute(text(
                    "SELECT COUNT(*) FROM invoices_hot WHERE status='settled' AND invoice_id<=:u"),
                    {'u':job.upper_invoice_id}).scalar()
                job.status='moving';job.started_at=datetime.now();db.commit()
            LOG.info('archive job %s starts at cursor %s',job_id,job.last_invoice_id)
            while True:
                moved,skipped,last_id,done=_process_batch(db,job)
                if done:break
                # heartbeat proves the move is alive; recovery only reclaims jobs whose heartbeat is stale
                db.refresh(job);job.worker_heartbeat=datetime.now();db.commit()
                time.sleep(float(os.environ.get('ARCHIVE_BATCH_DELAY','0.02')))
            job.status='completed';job.finished_at=datetime.now();db.commit()
            LOG.info('archive job %s completed: moved=%s skipped=%s',job_id,job.archived_count,job.skipped_count)
    except Exception as exc:
        LOG.exception('archive job %s failed',job_id)
        with Session() as db:
            job=db.get(ArchiveJob,job_id)
            if job and job.status not in ('completed','failed'):
                job.status='failed';job.error=str(exc)[:500];job.finished_at=datetime.now();db.commit()
    finally:
        if acquired:lock_conn.execute(text('SELECT pg_advisory_unlock(hashtext(:k))'),{'k':f'{LOCK_KEY}-{job_id}'})
        lock_conn.close()
HEARTBEAT_STALE_SECONDS=60
def recover_stuck_jobs():
    """Re-enqueue jobs needing (re)processing, without queue duplication.

    - pending jobs never started: always enqueue.
    - moving jobs: only when their worker heartbeat is stale (dead worker), so
      a healthy long-running job is never duplicated.
    Each id is enqueued at most once per scan, skipping ids already queued.
    """
    already={int(x) for x in queue.lrange(JOB_QUEUE,0,-1)}
    cutoff=datetime.now().timestamp()-HEARTBEAT_STALE_SECONDS
    with Session() as db:
        candidates=list(db.scalars(select(ArchiveJob).where(ArchiveJob.status.in_(['pending','moving']))))
        ids=[]
        for job in candidates:
            if job.id in already:continue
            if job.status=='pending':ids.append(job.id)
            elif job.worker_heartbeat is None or job.worker_heartbeat.timestamp()<cutoff:ids.append(job.id)
    for ident in ids:
        try:queue.rpush(JOB_QUEUE,ident)
        except Exception:LOG.exception('recovery enqueue failed for job %s',ident)
    if ids:LOG.info('re-enqueued archive jobs: %s',ids)
    return ids
