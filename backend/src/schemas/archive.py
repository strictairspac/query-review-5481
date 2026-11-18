from pydantic import BaseModel,Field
class ArchiveJobInput(BaseModel):
    upper_invoice_id:int=Field(gt=0,le=10**9)
class ArchiveJobOutput(BaseModel):
    id:int
    upper_invoice_id:int
    status:str
    total_candidates:int
    archived_count:int
    skipped_count:int
    last_invoice_id:int
    error:str|None=None
    created_by:str
    created_at:str
    started_at:str|None=None
    finished_at:str|None=None
class ArchiveItemOutput(BaseModel):
    id:int
    job_id:int
    invoice_id:int
    state:str
    created_at:str
