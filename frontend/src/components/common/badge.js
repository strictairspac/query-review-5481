import{STATUSES,ARCHIVE_STATUSES,LOCATIONS,INVOICE_STATUSES}from'../../constants/enums.js';import{esc}from'../../utils/html.js';
const LABELS={...STATUSES,...ARCHIVE_STATUSES,...LOCATIONS,...INVOICE_STATUSES};
export const badge=s=>'<span class="badge '+esc(s)+'">'+esc(LABELS[s]||s)+'</span>';
