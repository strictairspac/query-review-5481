from fastapi import APIRouter,Depends
from ..config.database import get_db
from ..schemas.invoice import InvoiceInput,InvoicePatch
from ..services.auth import current_user,writer
from ..services import invoice
router=APIRouter(prefix='/invoices')
@router.get('')
def listing(page:int=1,page_size:int=50,status:str|None=None,location:str|None=None,
            keyword:str|None=None,db=Depends(get_db),user=Depends(current_user)):
    return invoice.list_invoices(db,page=page,page_size=page_size,status=status,location=location,keyword=keyword)
@router.get('/stats')
def stats(db=Depends(get_db),user=Depends(current_user)):return invoice.stats(db)
@router.post('',status_code=201)
def create(data:InvoiceInput,db=Depends(get_db),user=Depends(writer)):return invoice.create_invoice(db,data)
@router.patch('/{invoice_id}')
def update(invoice_id:int,data:InvoicePatch,db=Depends(get_db),user=Depends(writer)):
    return invoice.update_invoice(db,invoice_id,data)
