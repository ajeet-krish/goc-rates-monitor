import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

/**
 * Resolve extensionless relative imports inside the TypeScript sources
 * under ../src, so plain node --test can import the .ts validators
 * without a framework. Only .ts and .tsx candidates are probed.
 */
export async function resolve(specifier, context, nextResolve) {
  try {
    return await nextResolve(specifier, context);
  } catch (err) {
    if (err?.code !== "ERR_MODULE_NOT_FOUND") throw err;
    if (!context.parentURL?.startsWith("file:")) throw err;
    if (
      !specifier.startsWith("./") &&
      !specifier.startsWith("../") &&
      !specifier.startsWith("/")
    ) {
      throw err;
    }
    const parentPath = fileURLToPath(context.parentURL);
    const base = specifier.startsWith("/")
      ? specifier
      : path.resolve(path.dirname(parentPath), specifier);
    const candidates = [
      base + ".ts",
      base + ".tsx",
      path.join(base, "index.ts"),
    ];
    for (const candidate of candidates) {
      if (existsSync(candidate)) {
        return { url: pathToFileURL(candidate).href, shortCircuit: true };
      }
    }
    throw err;
  }
}

/**
 * Shim Vite-only import.meta.env inside snapshot.ts so the fetch layer can
 * run under plain node. The build is unaffected: this hook lives in
 * tests only and the replacement pins the same defaults Vite provides
 * locally (root base, no mock flag).
 */
export async function load(url, context, nextLoad) {
  const result = await nextLoad(url, context);
  if (url.endsWith("/src/lib/snapshot.ts")) {
    const source = String(result.source).replaceAll(
      "import.meta.env",
      '({"BASE_URL": "/", "VITE_USE_MOCK": undefined})'
    );
    return { format: result.format, source, shortCircuit: true };
  }
  return result;
}
