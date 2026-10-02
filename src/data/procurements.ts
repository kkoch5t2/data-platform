import { readdirSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

// Read the annual snapshots during static generation. Bundling all JSON as
// JavaScript modules exceeds the native bundler's string conversion capacity.
const directory = resolve(process.cwd(), 'src/data');
const records = readdirSync(directory)
  .filter((name) => /^procurements-\d{4}\.json$/.test(name))
  .sort()
  .flatMap((name) => JSON.parse(readFileSync(join(directory, name), 'utf8')) as any[]);
export default records;
