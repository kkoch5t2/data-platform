import records from './procurements';

const dates = records.map((r:any) => r.noticeDate || r.awardDate).filter(Boolean).sort();
const awards = records.filter((r:any) => Number(r.awardAmount) > 0);
const companies = new Set(records.map((r:any) => r.companyId).filter(Boolean));
const organizations = new Set(records.map((r:any) => r.organizationId).filter(Boolean));
const localRecords = records.filter((r:any) => String(r.id || '').startsWith('jetro-local:')).length;

export default {
  records: records.length,
  nationalRecords: records.length - localRecords,
  localRecords,
  firstDate: dates[0] ?? null,
  lastDate: dates.at(-1) ?? null,
  awardRecords: awards.length,
  awardTotal: awards.reduce((sum:number, r:any) => sum + Number(r.awardAmount || 0), 0),
  companies: companies.size,
  organizations: organizations.size,
};
