// The vendored three.js, reproduced from the pinned npm package rather than copied by hand.
//
// `npm run vendor` copies `three/build/three.module.min.js` and `three/LICENSE` from node_modules into
// `agentdata/fleet/static/vendor/three/` and writes `VENDORED.json` beside them: the package, its version
// from package-lock.json, and the sha256 of each file. `npm run vendor:check` recomputes and compares, and
// exits 1 on any difference, so a hand edit of the served file, or a bump of `three` in package.json without
// a re-vendor, fails CI. The page still loads only the vendored copy (docs/fleet-dashboard.md: no CDN); this
// script is dev-only and never runs on the laptop at runtime. docs/npm.md says why.
import { createHash } from "node:crypto";
import { copyFileSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dest = join(root, "agentdata", "fleet", "static", "vendor", "three");
const manifest = join(dest, "VENDORED.json");
const files = { "three.module.min.js": join("build", "three.module.min.js"), "LICENSE": "LICENSE" };
const check = process.argv.includes("--check");

const sha256 = (path) => createHash("sha256").update(readFileSync(path)).digest("hex");
const lock = JSON.parse(readFileSync(join(root, "package-lock.json"), "utf8"));
const version = lock.packages?.["node_modules/three"]?.version;
if (!version) {
  console.error("vendor: package-lock.json does not list node_modules/three; run `npm ci` first");
  process.exit(1);
}
const source = join(root, "node_modules", "three");
if (!existsSync(join(source, files["three.module.min.js"]))) {
  console.error(`vendor: ${join(source, files["three.module.min.js"])} is missing; run \`npm ci\` first`);
  process.exit(1);
}

const want = { package: "three", version, files: {} };
for (const [name, rel] of Object.entries(files)) want.files[name] = sha256(join(source, rel));

if (check) {
  const problems = [];
  let have = null;
  try { have = JSON.parse(readFileSync(manifest, "utf8")); } catch { problems.push(`${manifest} is missing or not JSON`); }
  if (have && JSON.stringify(have) !== JSON.stringify(want)) {
    problems.push(`VENDORED.json says ${have.package}@${have.version}, the lockfile pins three@${version} with other hashes`);
  }
  for (const [name, hash] of Object.entries(want.files)) {
    const path = join(dest, name);
    if (!existsSync(path)) problems.push(`${path} is missing`);
    else if (sha256(path) !== hash) problems.push(`${path} differs from three@${version}'s ${files[name]} (hand-edited, or not re-vendored)`);
  }
  if (problems.length) {
    for (const p of problems) console.error(`vendor:check: ${p}`);
    console.error("vendor:check: run `npm run vendor` and commit what it writes");
    process.exit(1);
  }
  console.log(`vendor:check: three@${version} vendored as pinned`);
} else {
  for (const [name, rel] of Object.entries(files)) copyFileSync(join(source, rel), join(dest, name));
  writeFileSync(manifest, JSON.stringify(want, null, 2) + "\n");
  console.log(`vendor: three@${version} -> ${dest}`);
}
