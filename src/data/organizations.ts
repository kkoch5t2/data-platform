import records from './procurements';
const map = new Map<string, any>();
for (const r of records as any[]) {
  if (!r.organizationId || !r.agency) continue;
  const row = map.get(r.organizationId) ?? { id:r.organizationId, name:r.agency, recordCount:0, awardTotal:0 };
  row.recordCount += 1;
  if (Number(r.awardAmount) > 0) row.awardTotal += Number(r.awardAmount);
  map.set(r.organizationId, row);
}
export default [...map.values()];
