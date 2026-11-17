// Writes the small file installed copies of Culler read to learn about a new version.
//   node scripts/make_latest_json.mjs <version> <signature file> <download url> <notes file>
import { readFileSync } from "node:fs";

const [version, signatureFile, url, notesFile] = process.argv.slice(2);
if (!version || !signatureFile || !url) {
  console.error("usage: make_latest_json.mjs <version> <signature file> <download url> [notes file]");
  process.exit(1);
}
const signature = readFileSync(signatureFile, "utf8").trim();
if (!signature) {
  console.error("The signature file is empty.");
  process.exit(1);
}
const notes = notesFile ? readFileSync(notesFile, "utf8").trim() : "";
console.log(JSON.stringify({
  version,
  notes,
  pub_date: new Date().toISOString(),
  platforms: { "darwin-aarch64": { signature, url } },
}, null, 2));
