// Checks a running review-artifact capsule: node scripts/verify-routes.mjs <origin>
import { readFileSync } from "node:fs";

const origin = process.argv[2];
if (!origin) throw new Error("usage: node scripts/verify-routes.mjs <origin>");
const { title, verdict } = JSON.parse(readFileSync(new URL("markers.json", import.meta.url), "utf8"));
for (const [path, type, marker] of [
  ["/", "text/html", '<div id="app">'],
  ["/llms.md", "text/markdown", verdict],
  ["/index.md", "text/markdown", title],
  ["/llms.txt", "text/plain", "/llms.md"],
]) {
  const response = await fetch(new URL(path, origin));
  const body = await response.text();
  if (response.status !== 200) throw new Error(`${path}: ${response.status}`);
  if (!(response.headers.get("content-type") ?? "").includes(type)) throw new Error(`${path}: content-type ${response.headers.get("content-type")}`);
  if (!body.includes(marker)) throw new Error(`${path}: missing ${marker}`);
  console.log(`ok ${path} ${response.status} ${body.length} bytes`);
}
