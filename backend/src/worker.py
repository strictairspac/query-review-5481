import time,json,traceback,os
from pathlib import Path
from sqlalchemy import select
from .config.database import Session
from .models.batch import Batch
from .models.sample import Sample
from .models.evidence import Evidence
from .services.batch import queue
from .services.query_engine import compare
from .services.archive import run_job,recover_stuck_jobs,JOB_QUEUE
ARTIFACTS=Path(os.environ.get('ARTIFACTS_DIR','/artifacts'));ARTIFACTS.mkdir(parents=True,exist_ok=True)
heartbeat=ARTIFACTS/'worker.heartbeat'
RECOVERY_INTERVAL=30
def run_one(batch_id):
    with Session() as db:
        batch=db.get(Batch,batch_id)
        if not batch or db.scalar(select(Evidence).where(Evidence.batch_id==batch_id)):return
        sample=db.get(Sample,batch.sample_id);batch.status='running';db.commit()
        try:
            result=compare(sample.original_sql,batch.candidate_sql)
            batch.status='passed' if result['equivalent'] else 'different'
        except Exception as exc:
            result={'error':str(exc)[:500]};batch.status='failed'
        db.add(Evidence(batch_id=batch_id,result=result));db.commit()
        (ARTIFACTS/f'review-{batch_id}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
last_recovery=0.0
while True:
    try:
        heartbeat.write_text(str(time.time()))
        if time.time()-last_recovery>RECOVERY_INTERVAL:
            recover_stuck_jobs();last_recovery=time.time()
        item=queue.blpop(['query-review:jobs',JOB_QUEUE],timeout=2)
        if item:
            key,ident=item[0].decode(),int(item[1])
            if key==JOB_QUEUE:run_job(ident)
            else:run_one(ident)
        else:
            with Session() as db:pending=list(db.scalars(select(Batch.id).where(Batch.status.in_(['queued','running']))))
            for ident in pending:run_one(ident)
    except Exception:traceback.print_exc();time.sleep(2)
