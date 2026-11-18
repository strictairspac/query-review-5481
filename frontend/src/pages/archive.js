import{archiveJobs}from'../stores/archive.js';
import{createArchiveJob,retryArchiveJob,listArchiveItems}from'../api/archive.js';
import{header}from'../components/common/header.js';
import{badge}from'../components/common/badge.js';
import{esc}from'../utils/html.js';
import{submit,notify}from'../hooks/feedback.js';
import{session}from'../stores/session.js';
import{ARCHIVE_STATUSES}from'../constants/enums.js';
const progress=job=>{const base=job.total_candidates||0;const done=job.archived_count+job.skipped_count;
  if(!base)return job.status==='completed'?100:0;
  return Math.min(100,Math.round(done/base*100))};
function jobCard(j){
  const pct=progress(j);
  return `<article class="record archive-card status-${esc(j.status)}">
    <div class="archive-head">
      <h3>归档任务 #${j.id} <span class="mono muted">账单号 ≤ ${j.upper_invoice_id}</span></h3>
      ${badge(j.status)}
    </div>
    <div class="progress" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100">
      <div class="progress-bar" style="width:${pct}%"></div><span class="progress-label">${pct}%</span>
    </div>
    <div class="archive-metrics">
      <span>候选已结算 <b>${j.total_candidates}</b></span>
      <span>已入冷库 <b class="cold-text">${j.archived_count}</b></span>
      <span>跳过留热库 <b class="hot-text">${j.skipped_count}</b></span>
      <span>游标 <b class="mono">#${j.last_invoice_id}</b></span>
    </div>
    <p class="helper">创建：${esc(j.created_by)} · ${esc(j.created_at)}${j.started_at?` · 开始 ${esc(j.started_at)}`:''}${j.finished_at?` · 结束 ${esc(j.finished_at)}`:''}</p>
    ${j.error?`<div class="error-box"><b>失败原因：</b>${esc(j.error)}</div>`:''}
    <div class="actions">
      <button class="link-btn" data-items="${j.id}">查看逐账留痕 →</button>
      ${j.status==='failed'?`<button class="primary" data-retry="${j.id}">重试本任务</button>`:''}
    </div>
    <div class="items-drawer" id="drawer-${j.id}" hidden></div>
  </article>`;
}
export async function archivePage(el){
  const jobs=await archiveJobs.load();
  const isAdmin=session.get().role==='admin';
  el.innerHTML=header('05','已结算账单分批归档（热库 → 冷库）','按账单号上界分批搬运。搬运按批短事务提交，数据位置与查询可见性原子切换；迁走前恢复待结算的账单自动跳过并留在热库。中断恢复后重试不重复、不漏账。')
    +`<div class="split"><section class="panel">
        <div class="actions" style="margin-top:0">
          <button id="refresh">刷新进度</button>
          <span class="muted">${jobs.length} 个归档任务</span>
        </div>
        ${jobs.length?jobs.map(jobCard).join(''):'<div class="empty">还没有归档任务。管理员可在右侧按账单号上界创建。</div>'}
      </section>
      <aside class="panel">
        <h2>新建归档批次</h2>
        ${isAdmin?`<form id="archive-form">
          <label>账单号上界（含）</label>
          <input name="upper_invoice_id" type="number" min="1" required placeholder="例如 300，仅处理 invoice_id ≤ 300">
          <div class="actions"><button type="submit" class="primary">提交归档 →</button></div>
          <p class="helper">仅搬运当前为 <b>settled</b> 的账单；任务执行期间新增、改账、复核照常进行。范围可与历史任务重叠，已在冷库的账单不会重复搬运。</p>
        </form>`:'<div class="empty">仅管理员可创建与重试归档任务。</div>'}
        <div class="helper">
          状态流转：${Object.values(ARCHIVE_STATUSES).join(' / ')}<br>
          失败任务保留游标与失败原因，可从断点重试。
        </div>
      </aside></div>`;
  el.querySelector('#refresh').onclick=()=>archivePage(el);
  const form=el.querySelector('#archive-form');
  if(form)form.onsubmit=e=>{e.preventDefault();submit(form,async()=>{
    const data=Object.fromEntries(new FormData(form));
    const j=await createArchiveJob(data.upper_invoice_id);
    notify('归档任务 #'+j.id+' 已进入队列');archivePage(el);
  })};
  el.querySelectorAll('[data-retry]').forEach(btn=>btn.onclick=()=>submit(btn,async()=>{
    await retryArchiveJob(btn.dataset.retry);notify('已重新入队，从断点继续');archivePage(el);
  }));
  el.querySelectorAll('[data-items]').forEach(btn=>btn.onclick=async()=>{
    const id=btn.dataset.items;const drawer=el.querySelector('#drawer-'+id);
    if(!drawer.hidden){drawer.hidden=true;return}
    drawer.hidden=false;
    const items=await listArchiveItems(id);
    const archived=items.filter(x=>x.state==='archived').length;
    const skipped=items.filter(x=>x.state==='skipped').length;
    drawer.innerHTML=`<div class="eyebrow">LEDGER / 最近 ${items.length} 条 · 入库 ${archived} · 跳过 ${skipped}</div>
      <div class="tablewrap"><table><thead><tr><th>账单号</th><th>处理结果</th><th>记录时间</th></tr></thead><tbody>
      ${items.slice(0,200).map(x=>`<tr><td class="mono">#${x.invoice_id}</td><td><span class="badge ${x.state}">${x.state==='archived'?'已入冷库':'跳过留热库'}</span></td><td>${esc(x.created_at)}</td></tr>`).join('')}
      </tbody></table></div>`;
  });
}
