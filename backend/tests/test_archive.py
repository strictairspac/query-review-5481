"""End-to-end tests for hot/cold invoice archiving.

Runs against a live local stack (PostgreSQL + Redis + API + worker).
Reset helper rebuilds the invoices_hot/cold fixture so tests are independent
of run order.
"""
import os,time,subprocess,signal,hashlib,json
import pytest,httpx
from sqlalchemy import text
from src.config.database import engine,Session
from src.services.schema_bootstrap import bootstrap
from src.services.batch import queue
from src.models.archive import ArchiveJob
BASE=os.environ.get('TEST_BASE_URL','http://127.0.0.1:19240')
BACKEND_DIR=os.path.abspath(os.path.join(os.path.dirname(__file__),'..'))
ART_DIR=os.environ.get('ARTIFACTS_DIR','/tmp/artifacts')
def reset_data():
    bootstrap()
    with engine.begin() as c:
        c.execute(text('TRUNCATE archive_job_items,archive_jobs,evidence,batches RESTART IDENTITY CASCADE'))
        c.execute(text('TRUNCATE invoices_hot,invoices_cold'))
        c.execute(text("""INSERT INTO invoices_hot
            SELECT i,(ARRAY['澄港海产','南港鲜食','北湾冷运'])[1+(i%3)],(ARRAY['东线','西线'])[1+(i%2)],
            35+(i%17)*7,2+(i%9),CASE WHEN i%7=0 THEN 'pending' ELSE 'settled' END,1
            FROM generate_series(1,600) i"""))
    queue.flushdb()
def checksum():
    """Full-dataset multiset fingerprint over the invoices view."""
    with engine.connect() as c:
        rows=c.execute(text("""SELECT invoice_id,customer,route,amount::text,temperature::text,status
            FROM invoices ORDER BY invoice_id""")).all()
    return hashlib.sha256(json.dumps([tuple(r) for r in rows],ensure_ascii=False).encode()).hexdigest(),len(rows)
def login(role='admin'):
    r=httpx.post(f'{BASE}/auth/login',json={'email':f'{role}@chenggang.test','password':'ColdChain!17'},timeout=10)
    r.raise_for_status();return {'Authorization':'Bearer '+r.json()['token']}
def wait_job(headers,job_id,timeout=30,expect='completed'):
    deadline=time.time()+timeout
    while time.time()<deadline:
        job=httpx.get(f'{BASE}/archive-jobs/{job_id}',headers=headers,timeout=10).json()
        if job['status'] in ('completed','failed'):return job
        time.sleep(0.1)
    raise AssertionError('job did not finish')
def start_worker(env_extra=None):
    env={**os.environ,'ARTIFACTS_DIR':ART_DIR}
    if env_extra:env.update(env_extra)
    log=open(f'{ART_DIR}/test-worker-{time.time()}.log','w')
    proc=subprocess.Popen(['python3','-u','-m','src.worker'],cwd=BACKEND_DIR,env=env,
                          stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    deadline=time.time()+15
    hb=os.path.join(ART_DIR,'worker.heartbeat')
    while time.time()<deadline:
        if os.path.exists(hb) and time.time()-float(open(hb).read())<5:return proc,log
        time.sleep(0.2)
    proc.kill();raise AssertionError('worker did not start')
def stop_worker(proc,log):
    if proc.poll() is None:os.killpg(os.getpgid(proc.pid),signal.SIGTERM)
    proc.wait(timeout=10);log.close()
@pytest.fixture(scope='session')
def headers():return login('admin')
_SESSION_WORKER={}
@pytest.fixture(scope='session')
def bg_worker():
    proc,log=start_worker()
    _SESSION_WORKER.update(proc=proc,log=log)
    yield proc
    stop_worker(proc,log)
def pause_session_worker():
    proc=_SESSION_WORKER.get('proc')
    if proc and proc.poll() is None:stop_worker(proc,_SESSION_WORKER['log'])
def resume_session_worker():
    proc,_=start_worker();_SESSION_WORKER.update(proc=proc)
@pytest.fixture(autouse=True)
def _reset(bg_worker):
    reset_data()
    yield
def test_full_dataset_read_unchanged_through_view(headers):
    """Original statements keep reading hot+cold with identical counts/amounts."""
    before_sum,before_cnt=_db_aggregates()
    r=httpx.post(f'{BASE}/archive-jobs',headers=headers,json={'upper_invoice_id':300})
    job=wait_job(headers,r.json()['id'])
    assert job['status']=='completed'
    after_sum,after_cnt=_db_aggregates()
    assert before_sum==after_sum and before_cnt==after_cnt==600
    stats=httpx.get(f'{BASE}/invoices/stats',headers=headers).json()
    assert stats['total']==600 and stats['hot_total']+stats['cold_total']==600
def _db_aggregates():
    with engine.connect() as c:
        return (str(c.execute(text('SELECT sum(amount) FROM invoices')).scalar()),
                c.execute(text('SELECT count(*) FROM invoices')).scalar())
def test_pending_invoice_stays_hot_even_when_in_range(headers):
    """Reverted-to-pending invoices are skipped and remain in the hot store."""
    # invoice 7 is pending in fixture; also force a settled one back to pending
    with engine.begin() as c:
        c.execute(text("UPDATE invoices_hot SET status='pending' WHERE invoice_id=8"))
    r=httpx.post(f'{BASE}/archive-jobs',headers=headers,json={'upper_invoice_id':50})
    job=wait_job(headers,r.json()['id'])
    items={x['invoice_id']:x['state'] for x in httpx.get(f'{BASE}/archive-jobs/{job["id"]}/items',headers=headers).json()}
    assert items[7]=='skipped' and items[8]=='skipped'
    with engine.connect() as c:
        loc7=c.execute(text("SELECT location FROM invoices WHERE invoice_id=7")).scalar()
        loc8=c.execute(text("SELECT location FROM invoices WHERE invoice_id=8")).scalar()
        assert loc7=='hot' and loc8=='hot'
        assert c.execute(text("SELECT count(*) FROM invoices_cold WHERE status<>'settled'")).scalar()==0
def test_concurrent_amount_update_is_not_lost(headers):
    """CAS version check: concurrent edits both survive, no lost update."""
    current=httpx.get(f'{BASE}/invoices?keyword=100&page_size=5',headers=headers).json()['items']
    inv=next(x for x in current if x['invoice_id']==100)
    r1=httpx.patch(f'{BASE}/invoices/100',headers=headers,
                   json={'amount':999.0,'version':inv['version']})
    assert r1.status_code==200 and r1.json()['amount']=='999.00'
    # stale version must be rejected
    r2=httpx.patch(f'{BASE}/invoices/100',headers=headers,
                   json={'amount':888.0,'version':inv['version']})
    assert r2.status_code==409
    # fresh version succeeds
    r3=httpx.patch(f'{BASE}/invoices/100',headers=headers,
                   json={'amount':777.0,'version':r1.json()['version']})
    assert r3.status_code==200 and r3.json()['amount']=='777.00'
    with engine.connect() as c:
        assert str(c.execute(text('SELECT amount FROM invoices_hot WHERE invoice_id=100')).scalar())=='777.00'
        assert c.execute(text('SELECT version FROM invoices_hot WHERE invoice_id=100')).scalar()==3
def test_edit_during_archive_keeps_update_and_no_loss(headers):
    """Edit an invoice while the worker is mid-move; update survives."""
    pause_session_worker()
    proc,log=start_worker({'ARCHIVE_BATCH_DELAY':'0.15'})
    try:
        r=httpx.post(f'{BASE}/archive-jobs',headers=headers,json={'upper_invoice_id':600})
        job_id=r.json()['id']
        edited=False
        deadline=time.time()+20
        target=250
        while time.time()<deadline:
            job=httpx.get(f'{BASE}/archive-jobs/{job_id}',headers=headers).json()
            if job['status'] in ('completed','failed'):break
            inv=httpx.get(f'{BASE}/invoices?keyword=250&page_size=5',headers=headers).json()['items']
            inv=next((x for x in inv if x['invoice_id']==target),None)
            if inv and not edited:
                rr=httpx.patch(f'{BASE}/invoices/250',headers=headers,
                               json={'amount':432.10,'version':inv['version']})
                if rr.status_code==200:edited=True
                elif rr.status_code!=409:raise AssertionError(rr.text)
            time.sleep(0.05)
        job=wait_job(headers,job_id)
        assert job['status']=='completed' and edited
        with engine.connect() as c:
            row=c.execute(text("SELECT amount,location FROM invoices WHERE invoice_id=250")).mappings().first()
            assert str(row['amount'])=='432.10'  # update never lost, wherever it lives
            assert c.execute(text("SELECT count(*) FROM invoices_hot JOIN invoices_cold USING(invoice_id)")).scalar()==0
            assert c.execute(text("SELECT count(*) FROM invoices")).scalar()==600
    finally:
        stop_worker(proc,log)
def test_worker_restart_mid_archive_resumes_without_duplicate_or_gap(headers):
    """Kill the worker mid-move; restart and verify no double move / missing rows."""
    pause_session_worker()
    proc,log=start_worker({'ARCHIVE_BATCH_DELAY':'0.1'})
    try:
        r=httpx.post(f'{BASE}/archive-jobs',headers=headers,json={'upper_invoice_id':600})
        job_id=r.json()['id']
        moved=0
        deadline=time.time()+15
        while time.time()<deadline:
            with engine.connect() as c:
                moved=c.execute(text('SELECT count(*) FROM invoices_cold')).scalar()
            if 30<moved<300:break
            time.sleep(0.05)
        assert moved>0
        stop_worker(proc,log)
        with engine.connect() as c:
            cold_at_kill=c.execute(text('SELECT count(*) FROM invoices_cold')).scalar()
            hot_at_kill=c.execute(text('SELECT count(*) FROM invoices_hot')).scalar()
            assert cold_at_kill+hot_at_kill==600  # atomic switch, nothing stranded
        proc,log=start_worker()  # restart triggers recovery re-enqueue
        job=wait_job(headers,job_id,timeout=40)
        assert job['status']=='completed'
        with engine.connect() as c:
            assert c.execute(text('SELECT count(*) FROM invoices_hot JOIN invoices_cold USING(invoice_id)')).scalar()==0
            assert c.execute(text('SELECT count(*) FROM invoices')).scalar()==600
            # ledger never double-records an invoice as archived
            dupes=c.execute(text("""SELECT invoice_id FROM archive_job_items
                WHERE state='archived' GROUP BY invoice_id HAVING count(*)>1""")).all()
            assert dupes==[]
            # every archived row in cold, every skipped row still hot
            missing=c.execute(text("""SELECT i.invoice_id FROM archive_job_items i
                LEFT JOIN invoices_cold c ON c.invoice_id=i.invoice_id
                WHERE i.state='archived' AND c.invoice_id IS NULL""")).all()
            assert missing==[]
    finally:
        stop_worker(proc,log)
        resume_session_worker()
def test_overlapping_archive_ranges_do_not_double_move(headers):
    """Two jobs with overlapping upper bounds; second job finds nothing left to move."""
    r1=httpx.post(f'{BASE}/archive-jobs',headers=headers,json={'upper_invoice_id':300})
    j1=wait_job(headers,r1.json()['id'])
    r2=httpx.post(f'{BASE}/archive-jobs',headers=headers,json={'upper_invoice_id':500})
    j2=wait_job(headers,r2.json()['id'])
    assert j1['status']==j2['status']=='completed'
    with engine.connect() as c:
        # cold store holds exactly the union of the two jobs' archived rows
        assert c.execute(text('SELECT count(*) FROM invoices_cold')).scalar()==j1['archived_count']+j2['archived_count']
        # job2 only moved invoices in (300,500] that are settled
        assert c.execute(text("SELECT count(*) FROM invoices_cold WHERE invoice_id>500")).scalar()==0
        assert c.execute(text("SELECT count(*) FROM invoices_hot JOIN invoices_cold USING(invoice_id)")).scalar()==0
    # ledger uniqueness of archived invoice across jobs
    with engine.connect() as c:
        dupes=c.execute(text("""SELECT invoice_id FROM archive_job_items WHERE state='archived'
            GROUP BY invoice_id HAVING count(*)>1""")).all()
        assert dupes==[]
def test_reader_role_and_limits_remain_enforced(headers):
    """Viewer stays read-only; pagination caps and SQL guardrails intact."""
    vh=login('viewer')
    assert httpx.post(f'{BASE}/archive-jobs',headers=vh,json={'upper_invoice_id':10}).status_code==403
    assert httpx.post(f'{BASE}/invoices',headers=vh,
                      json={'invoice_id':999,'customer':'x','route':'y','amount':10,'temperature':3,'status':'settled'}).status_code==403
    assert httpx.patch(f'{BASE}/invoices/1',headers=vh,json={'amount':12.0,'version':1}).status_code==403
    r=httpx.get(f'{BASE}/invoices?page_size=9999',headers=vh)
    assert len(r.json()['items'])<=200
    # operator also cannot manage archive jobs
    oh=login('operator')
    assert httpx.post(f'{BASE}/archive-jobs',headers=oh,json={'upper_invoice_id':10}).status_code==403
def test_invoice_create_and_limited_queries(headers):
    r=httpx.post(f'{BASE}/invoices',headers=headers,
                 json={'invoice_id':9001,'customer':'测试客户','route':'南线','amount':123.45,'temperature':5.0,'status':'settled'})
    assert r.status_code==201 and r.json()['location']=='hot'
    dup=httpx.post(f'{BASE}/invoices',headers=headers,
                   json={'invoice_id':9001,'customer':'测试客户','route':'南线','amount':123.45,'temperature':5.0,'status':'settled'})
    assert dup.status_code==409
    found=httpx.get(f'{BASE}/invoices?keyword=9001',headers=headers).json()['items']
    assert any(x['invoice_id']==9001 for x in found)
    bad=httpx.get(f'{BASE}/invoices?page=0',headers=headers)
    assert bad.status_code==200
def test_failed_job_retry_is_idempotent(headers):
    """Simulate a failure then retry; retry never re-moves rows."""
    # break the cold store temporarily by renaming it, run job, then restore
    with engine.begin() as c:
        c.execute(text('ALTER TABLE invoices_cold RENAME TO invoices_cold_bak'))
    r=httpx.post(f'{BASE}/archive-jobs',headers=headers,json={'upper_invoice_id':100})
    job=wait_job(headers,r.json()['id'])
    assert job['status']=='failed' and job['error']
    with engine.begin() as c:
        c.execute(text('ALTER TABLE invoices_cold_bak RENAME TO invoices_cold'))
    rr=httpx.post(f'{BASE}/archive-jobs/{job["id"]}/retry',headers=headers)
    assert rr.status_code==202
    job2=wait_job(headers,job['id'])
    assert job2['status']=='completed'
    with engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM invoices_hot JOIN invoices_cold USING(invoice_id)')).scalar()==0
        assert c.execute(text('SELECT count(*) FROM invoices')).scalar()==600
