const modules = import.meta.glob('./summary.json', { eager: true, import: 'default' });
const generatedSummary = Object.values(modules)[0] as any | undefined;

// Generated procurement data is intentionally gitignored. CI must still be able to
// compile a clean checkout; production/local builds use the generated snapshot when present.
const fallbackSummary = {
  records: 0,
  awardRecords: 0,
  firstDate: '2014-03-19',
  lastDate: '—',
  generatedAt: null,
  nationalRecords: 0,
  localRecords: 0,
  jetroRecords: 0,
  gepsRecords: 0,
  yokohamaRecords: 0,
  sapporoRecords: 0,
  kobeRecords: 0,
  fukuokaRecords: 0,
  chibaRecords: 0,
  kyotoRecords: 0,
  kawasakiRecords: 0,
  sendaiRecords: 0,
};

export default generatedSummary ?? fallbackSummary;
