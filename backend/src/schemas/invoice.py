from pydantic import BaseModel,Field
class InvoiceInput(BaseModel):
    invoice_id:int=Field(gt=0,le=10**9)
    customer:str=Field(min_length=1,max_length=120)
    route:str=Field(min_length=1,max_length=120)
    amount:float=Field(gt=0)
    temperature:float
    status:str
class InvoicePatch(BaseModel):
    amount:float|None=Field(default=None,gt=0)
    status:str|None=None
    version:int=Field(ge=1)
