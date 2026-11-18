"""Invoice reads and bounded business writes over the hot/cold view.

Amount and status edits use an optimistic version column; a version mismatch
is reported as 409 so a concurrent settlement/review or an in-flight archive
move can never silently overwrite another writer's update. Writes run on a
short-lived connection so the ORM identity map can never serve a stale
version inside one request.
"""
from sqlalchemy import text
from fastapi import HTTPException
from ..config.database import engine
from ..config.settings import INVOICE_PAGE_LIMIT
COLS='invoice_id,customer,route,amount,temperature,status,version'
def _serialize(row):
    return {**{k:str(row[k]) if k=='amount' else row[k] for k in COLS.split(',')},'location':row['location']}
def list_invoices(db,*,page=1,page_size=50,status=None,location=None,keyword=None):
    page=max(1,page);page_size=min(max(1,page_size),INVOICE_PAGE_LIMIT)
    where,params=[],{}
    if status in ('settled','pending'):where.append('status=:status');params['status']=status
    if location in ('hot','cold'):where.append('location=:location');params['location']=location
    if keyword:where.append('(customer ILIKE :kw OR invoice_id::text ILIKE :kw)');params['kw']=f'%{keyword}%'
    clause=(' WHERE '+' AND '.join(where)) if where else ''
    total=db.execute(text(f'SELECT COUNT(*) FROM invoices{clause}'),params).scalar()
    rows=db.execute(text(f'SELECT {COLS},location FROM invoices{clause} ORDER BY invoice_id LIMIT :lim OFFSET :off'),
                    {**params,'lim':page_size,'off':(page-1)*page_size}).mappings().all()
    return {'items':[_serialize(r) for r in rows],'total':total,'page':page,'page_size':page_size}
def stats(db):
    row=db.execute(text("""SELECT
      COUNT(*) AS total,
      COUNT(*) FILTER (WHERE location='hot') AS hot_total,
      COUNT(*) FILTER (WHERE location='cold') AS cold_total,
      COUNT(*) FILTER (WHERE status='settled') AS settled_total,
      COUNT(*) FILTER (WHERE status='pending') AS pending_total,
      COALESCE(SUM(amount),0) AS amount_total,
      COALESCE(SUM(amount) FILTER (WHERE location='hot'),0) AS hot_amount,
      COALESCE(SUM(amount) FILTER (WHERE location='cold'),0) AS cold_amount
      FROM invoices""")).mappings().first()
    return {k:(str(v) if k.endswith('amount') else v) for k,v in row.items()}
def create_invoice(db,data):
    params={'invoice_id':data.invoice_id,'customer':data.customer,'route':data.route,
            'amount':data.amount,'temperature':data.temperature,'status':data.status}
    with engine.begin() as conn:
        try:
            conn.execute(text(f"""INSERT INTO invoices_hot ({COLS})
                VALUES (:invoice_id,:customer,:route,:amount,:temperature,:status,1)"""),params)
        except Exception as exc:
            if 'unique' in str(exc).lower() or 'duplicate' in str(exc).lower():raise HTTPException(409,'账单号已存在')
            raise
        row=conn.execute(text('SELECT :placeholder AS location, '+COLS+' FROM invoices_hot WHERE invoice_id=:id'),
                         {'placeholder':'hot','id':data.invoice_id}).mappings().first()
    return _serialize(row)
def update_invoice(db,invoice_id,data):
    changes={k:v for k,v in data.model_dump(exclude_unset=True).items() if k!='version'}
    if not changes:raise HTTPException(422,'没有需要更新的字段')
    if 'amount' in changes and changes['amount']<=0:raise HTTPException(422,'金额必须为正数')
    if 'status' in changes and changes['status'] not in ('settled','pending'):raise HTTPException(422,'状态只能是 settled 或 pending')
    with engine.connect() as conn:
        with conn.begin():
            row=conn.execute(text('SELECT '+COLS+" FROM invoices_hot WHERE invoice_id=:id"),{'id':invoice_id}).mappings().first()
            store='hot'
            if row is None:
                row=conn.execute(text('SELECT '+COLS+" FROM invoices_cold WHERE invoice_id=:id"),{'id':invoice_id}).mappings().first()
                store='cold'
            if row is None:raise HTTPException(404,'账单不存在')
            # Optimistic lock against the version the caller read. Comparing
            # only the current DB version would make every update succeed;
            # the caller's expected version is what detects a concurrent write.
            if row['version']!=data.version:
                raise HTTPException(409,f"账单已被其他操作修改（当前版本 {row['version']}，提交基于版本 {data.version}），请刷新后重试")
            sets=', '.join(f'{k}=:{k}' for k in changes)
            params={**changes,'id':invoice_id,'ver':data.version}
            result=conn.execute(text(
                f'UPDATE invoices_{store} SET {sets}, version=version+1 WHERE invoice_id=:id AND version=:ver'),params)
            if result.rowcount!=1:
                raise HTTPException(409,'账单刚被其他操作修改，请刷新后重试（版本已变化）')
            fresh=conn.execute(text(
                "SELECT :loc AS location, "+COLS+f" FROM invoices_{store} WHERE invoice_id=:id"),
                {'loc':store,'id':invoice_id}).mappings().first()
    return _serialize(fresh)
