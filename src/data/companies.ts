import records from './procurements';
const map = new Map<string, any>();
for (const r of records as any[]) {
  if (!r.companyId || !r.winnerName) continue;
  const row = map.get(r.companyId) ?? { id:r.companyId, name:r.winnerName, awardCount:0, awardTotal:0 };
  if (Number(r.awardAmount) > 0) { row.awardCount += 1; row.awardTotal += Number(r.awardAmount); }
  map.set(r.companyId, row);
}
export default [...map.values()];
