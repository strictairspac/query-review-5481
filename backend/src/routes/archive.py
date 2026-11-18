from fastapi import APIRouter,Depends
from ..config.database import get_db
from ..schemas.archive import ArchiveJobInput
from ..services.auth import admin
from ..services import archive
router=APIRouter(prefix='/archive-jobs')
@router.get('')
def listing(db=Depends(get_db),user=Depends(admin)):return archive.list_jobs(db)
@router.post('',status_code=202)
def create(data:ArchiveJobInput,db=Depends(get_db),user=Depends(admin)):
    return archive.create_job(db,data.upper_invoice_id,user.email)
@router.get('/{job_id}')
def detail(job_id:int,db=Depends(get_db),user=Depends(admin)):return archive.job_detail(db,job_id)
@router.get('/{job_id}/items')
def items(job_id:int,state:str|None=None,db=Depends(get_db),user=Depends(admin)):
    return archive.list_items(db,job_id,state)
@router.post('/{job_id}/retry',status_code=202)
def retry(job_id:int,db=Depends(get_db),user=Depends(admin)):return archive.retry_job(db,job_id)
