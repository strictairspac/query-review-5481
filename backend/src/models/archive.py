from sqlalchemy.orm import Mapped,mapped_column
from sqlalchemy import String,Integer,BigInteger,DateTime,Text,func
from datetime import datetime
from ..config.database import Base
class ArchiveJob(Base):
    __tablename__='archive_jobs'
    id:Mapped[int]=mapped_column(primary_key=True)
    upper_invoice_id:Mapped[int]=mapped_column(Integer)
    status:Mapped[str]=mapped_column(String(20),default='pending',index=True)
    total_candidates:Mapped[int]=mapped_column(Integer,default=0)
    archived_count:Mapped[int]=mapped_column(Integer,default=0)
    skipped_count:Mapped[int]=mapped_column(Integer,default=0)
    last_invoice_id:Mapped[int]=mapped_column(Integer,default=0)
    error:Mapped[str]=mapped_column(Text,nullable=True)
    created_by:Mapped[str]=mapped_column(String(120))
    created_at:Mapped[datetime]=mapped_column(DateTime,server_default=func.now())
    started_at:Mapped[datetime]=mapped_column(DateTime,nullable=True)
    finished_at:Mapped[datetime]=mapped_column(DateTime,nullable=True)
    worker_heartbeat:Mapped[datetime]=mapped_column(DateTime,nullable=True)
class ArchiveJobItem(Base):
    __tablename__='archive_job_items'
    id:Mapped[int]=mapped_column(BigInteger,primary_key=True)
    job_id:Mapped[int]=mapped_column(Integer,index=True)
    invoice_id:Mapped[int]=mapped_column(Integer,index=True)
    state:Mapped[str]=mapped_column(String(20))
    created_at:Mapped[datetime]=mapped_column(DateTime,server_default=func.now())
