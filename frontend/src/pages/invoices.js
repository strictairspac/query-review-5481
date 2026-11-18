import{listInvoices,invoiceStats,createInvoice,patchInvoice}from'../api/invoice.js';
import{header}from'../components/common/header.js';
import{badge}from'../components/common/badge.js';
import{esc}from'../utils/html.js';
import{submit,notify}from'../hooks/feedback.js';
import{session}from'../stores/session.js';
import{LOCATIONS,INVOICE_STATUSES}from'../constants/enums.js';
const state={page:1,page_size:20,status:'',location:'',keyword:''};
const write=()=>session.get().role!=='viewer';
function editForm(x){
  return `<tr class="edit-row" data-edit="${x.invoice_id}" hidden><td colspan="8">
    <form class="inline-form" data-form="${x.invoice_id}">
      <label>金额<input name="amount" type="number" step="0.01" min="0.01" value="${esc(x.amount)}" required></label>
      <label>状态<select name="status">
        <option value="settled" ${x.status==='settled'?'selected':''}>已结算 settled</option>
        <option value="pending" ${x.status==='pending'?'selected':''}>待结算 pending</option>
      </select></label>
      <input type="hidden" name="version" value="${x.version}">
      <button type="submit" class="primary">保存</button>
      <button type="button" data-cancel="${x.invoice_id}">取消</button>
      <span class="helper">基于版本 ${x.version}，并发冲突会被拒绝</span>
    </form></td></tr>`;
}
export async function invoicesPage(el){
  const [data,stat]=await Promise.all([listInvoices(state),invoiceStats()]);
  const totalPages=Math.max(1,Math.ceil(data.total/data.page_size));
  el.innerHTML=header('06','冷热全量账单查询与改账','invoices 视图 UNION ALL 热库与冷库，原 SQL 口径不变。只读查询受限（每页最多 200 行）；改账带版本乐观锁，并发修改不丢更新。')
  +`<div class="stat-grid">
      <div class="stat"><b>${stat.total}</b><span>账单总量</span></div>
      <div class="stat"><b class="hot-text">${stat.hot_total}</b><span>热库</span></div>
      <div class="stat"><b class="cold-text">${stat.cold_total}</b><span>冷库</span></div>
      <div class="stat"><b>${stat.settled_total}</b><span>已结算</span></div>
      <div class="stat"><b>${stat.pending_total}</b><span>待结算</span></div>
      <div class="stat"><b>¥${esc(stat.amount_total)}</b><span>总金额（冷热合计）</span></div>
    </div>
    <div class="panel">
      <form id="filter-form" class="filter-bar">
        <input name="keyword" placeholder="客户名 / 账单号" value="${esc(state.keyword)}">
        <select name="status"><option value="">全部状态</option>${Object.entries(INVOICE_STATUSES).map(([v,l])=>`<option value="${v}" ${state.status===v?'selected':''}>${l}</option>`).join('')}</select>
        <select name="location"><option value="">全部位置</option>${Object.entries(LOCATIONS).map(([v,l])=>`<option value="${v}" ${state.location===v?'selected':''}>${l}</option>`).join('')}</select>
        <button type="submit" class="primary">查询</button>
        ${write()?'<button type="button" id="new-btn">新增账单</button>':''}
      </form>
      <div id="new-form" hidden class="panel inner">
        <form id="create-form" class="filter-bar">
          <input name="invoice_id" type="number" min="1" placeholder="账单号" required>
          <input name="customer" placeholder="客户" required maxlength="120">
          <input name="route" placeholder="路线" required maxlength="120">
          <input name="amount" type="number" step="0.01" min="0.01" placeholder="金额" required>
          <input name="temperature" type="number" step="0.1" placeholder="温度" required>
          <select name="status"><option value="settled">已结算</option><option value="pending">待结算</option></select>
          <button type="submit" class="primary">保存</button>
        </form>
      </div>
      <div class="tablewrap"><table><thead><tr>
        <th>账单号</th><th>客户</th><th>路线</th><th>金额</th><th>温度</th><th>状态</th><th>位置 / 版本</th>${write()?'<th>操作</th>':''}
      </tr></thead><tbody>
      ${data.items.map(x=>`<tr data-row="${x.invoice_id}">
        <td class="mono">#${x.invoice_id}</td><td>${esc(x.customer)}</td><td>${esc(x.route)}</td>
        <td>¥${esc(x.amount)}</td><td>${x.temperature}</td>
        <td>${badge(x.status)}</td>
        <td><span class="badge loc-${x.location}">${LOCATIONS[x.location]||x.location}</span> <span class="muted mono">v${x.version}</span></td>
        ${write()?`<td><button class="link-btn" data-edit-btn="${x.invoice_id}">改账</button></td>`:''}
      </tr>${write()?editForm(x):''}`).join('')}
      </tbody></table></div>
      <div class="pager">
        <button id="prev" ${state.page<=1?'disabled':''}>← 上一页</button>
        <span class="muted">第 ${state.page} / ${totalPages} 页 · 共 ${data.total} 条 · 每页 ${data.page_size} 条（上限 200）</span>
        <button id="next" ${state.page>=totalPages?'disabled':''}>下一页 →</button>
      </div>
    </div>`;
  el.querySelector('#filter-form').onsubmit=e=>{e.preventDefault();
    const f=Object.fromEntries(new FormData(e.target));
    Object.assign(state,{...f,page:1});invoicesPage(el)};
  el.querySelector('#prev')?.addEventListener('click',()=>{state.page--;invoicesPage(el)});
  el.querySelector('#next')?.addEventListener('click',()=>{state.page++;invoicesPage(el)});
  const nb=el.querySelector('#new-btn');
  if(nb)nb.onclick=()=>{el.querySelector('#new-form').hidden=false};
  const cf=el.querySelector('#create-form');
  if(cf)cf.onsubmit=e=>{e.preventDefault();submit(cf,async()=>{
    const d=Object.fromEntries(new FormData(cf));
    d.invoice_id=Number(d.invoice_id);d.amount=Number(d.amount);d.temperature=Number(d.temperature);
    await createInvoice(d);notify('账单已新增到热库');invoicesPage(el)})};
  el.querySelectorAll('[data-edit-btn]').forEach(btn=>btn.onclick=()=>{
    const row=el.querySelector(`.edit-row[data-edit="${btn.dataset.editBtn}"]`);
    row.hidden=!row.hidden;
  });
  el.querySelectorAll('[data-cancel]').forEach(btn=>btn.onclick=()=>{
    el.querySelector(`.edit-row[data-edit="${btn.dataset.cancel}"]`).hidden=true;
  });
  el.querySelectorAll('[data-form]').forEach(form=>form.onsubmit=e=>{
    e.preventDefault();const id=form.dataset.form;
    submit(form,async()=>{
      const d=Object.fromEntries(new FormData(form));
      d.amount=Number(d.amount);d.version=Number(d.version);
      const updated=await patchInvoice(id,d);
      notify(`账单 #${id} 已更新，新版本 v${updated.version}`);invoicesPage(el);
    });
  });
}
