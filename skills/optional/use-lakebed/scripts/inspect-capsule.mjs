import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const capsuleRoot = resolve(process.argv[2] ?? ".");
const binding = await readSafeJson(resolve(capsuleRoot, "lakebed.json"), ["deployId"], ["deployId"]);
const legacyDeploy = await readSafeJson(resolve(capsuleRoot, ".lakebed/deploy.json"), ["api", "deployId", "url"]);
const serverEnvironment = await readServerEnvironment(resolve(capsuleRoot, ".env.lakebed.server"));

console.log(JSON.stringify({ binding, legacyDeploy, serverEnvironment }, null, 2));

async function readSafeJson(filePath, allowedKeys, requiredKeys = []) {
  let value;

  try {
    value = JSON.parse(await readFile(filePath, "utf8"));
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw new Error(`Unable to read safe Lakebed metadata from ${filePath}.`);
  }

  for (const key of requiredKeys) {
    if (typeof value?.[key] !== "string" || !value[key].trim()) {
      throw new Error(`${filePath} must contain ${key}.`);
    }
  }

  return Object.fromEntries(allowedKeys.flatMap((key) => typeof value?.[key] === "string" ? [[key, value[key]]] : []));
}

async function readServerEnvironment(filePath) {
  let source;

  try {
    source = await readFile(filePath, "utf8");
  } catch (error) {
    if (error?.code === "ENOENT") return { keys: [], present: false };
    throw new Error(`Unable to read server environment key names from ${filePath}.`);
  }

  const keys = source
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"))
    .flatMap((line) => {
      const match = line.match(/^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=/);
      return match ? [match[1]] : [];
    });

  return { keys: [...new Set(keys)].sort(), present: true };
}
