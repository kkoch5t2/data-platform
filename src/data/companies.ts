export type ProcurementCompany = {
  id: string;
  name: string;
  awardCount: number;
  awardTotal: number;
};

const modules = import.meta.glob('./companies.json', { eager: true, import: 'default' });
const generatedCompanies = Object.values(modules)[0] as ProcurementCompany[] | undefined;

// Procurement snapshots are generated locally and intentionally gitignored.
// Keep clean CI checkouts buildable while using the real snapshot whenever it exists.
export default generatedCompanies ?? [];
