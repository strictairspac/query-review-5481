import{api,post}from'./client.js';
export const listArchiveJobs=()=>api('/archive-jobs');
export const createArchiveJob=upper_invoice_id=>post('/archive-jobs',{upper_invoice_id:Number(upper_invoice_id)});
export const getArchiveJob=id=>api('/archive-jobs/'+id);
export const listArchiveItems=(id,state)=>api(`/archive-jobs/${id}/items${state?`?state=${state}`:''}`);
export const retryArchiveJob=id=>post(`/archive-jobs/${id}/retry`);
