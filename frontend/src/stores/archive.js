import{listArchiveJobs}from'../api/archive.js';
export const archiveJobs={items:[],async load(){this.items=await listArchiveJobs();return this.items}};
