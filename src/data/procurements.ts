const modules = import.meta.glob('./procurements-*.json', { eager: true, import: 'default' });
const records = Object.values(modules).flatMap((value) => value as any[]);
export default records;
