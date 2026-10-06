import companies from '../data/companies.ts';
export const pageSize = 500;
export const rankedCompanies = [...companies].sort((a, b) => b.awardTotal - a.awardTotal || b.awardCount - a.awardCount || a.name.localeCompare(b.name, 'ja'));
export const pageCount = Math.max(1, Math.ceil(rankedCompanies.length / pageSize));
export const companyPagePath = (page: number) => page === 1 ? '/procurement/companies/' : `/procurement/companies/page/${page}/`;
