import records from './procurements';

const recordsByCompany = new Map<string, any[]>();
for (const r of records as any[]) {
  if (!r.companyId || !r.awardAmount) continue;
  const rows = recordsByCompany.get(r.companyId) ?? [];
  rows.push(r);
  recordsByCompany.set(r.companyId, rows);
}
for (const rows of recordsByCompany.values()) {
  rows.sort((a,b)=>(b.awardDate||'').localeCompare(a.awardDate||''));
}

export default recordsByCompany;
