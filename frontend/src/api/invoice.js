import{api,post}from'./client.js';
export const listInvoices=params=>{const q=new URLSearchParams(Object.entries(params).filter(([,v])=>v!==''&&v!=null)).toString();return api('/invoices'+(q?'?'+q:''))};
export const invoiceStats=()=>api('/invoices/stats');
export const createInvoice=data=>post('/invoices',data);
export const patchInvoice=(id,data)=>api('/invoices/'+id,{method:'PATCH',body:JSON.stringify(data)});
