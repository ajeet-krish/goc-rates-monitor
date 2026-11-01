import type { DataIndex, SnapshotDoc, VerifyReport } from "./types";
import { isStrictIsoDate } from "./asof";
import { validateIndex, validateSnapshot, validateVerify, ValidationError } from "./validate";

function base(): string {
  return import.meta.env.BASE_URL || "/";
}

function join(baseUrl: string, rest: string): string {
  const left = baseUrl.endsWith("/") ? baseUrl : baseUrl + "/";
  const right = rest.startsWith("/") ? rest.slice(1) : rest;
  return left + right;
}

export function dataUrl(path: string): string {
  return join(join(base(), "data/"), path);
}

/**
 * Upper bound for any fetched JSON payload, in bytes of UTF-8 text.
 * Snapshots are small by construction, so a 5 MiB ceiling rejects
 * runaway or compromised payloads before JSON parse allocates freely.
 */
export const MAX_JSON_BYTES = 5 * 1024 * 1024;

/** Network budget per fetch, in milliseconds. Exceeded fetches abort. */
export const FETCH_TIMEOUT_MS = 15_000;

function assertAsof(asof: string, caller: string): void {
  if (!isStrictIsoDate(asof)) {
    throw new ValidationError(
      caller + ": asof must be a strict ISO YYYY-MM-DD date, got " + JSON.stringify(asof)
    );
  }
}

async function readCappedText(response: Response, url: string): Promise<string> {
  const declared = response.headers.get("content-length");
  if (declared !== null) {
    const size = Number(declared.trim());
    if (!Number.isFinite(size) || size < 0 || size > MAX_JSON_BYTES) {
      throw new Error(
        "Response for " + url + " exceeds the " + MAX_JSON_BYTES + " byte cap (declared " + declared + ")"
      );
    }
  }
  if (!response.body) {
    const text = await response.text();
    if (text.length > MAX_JSON_BYTES) {
      throw new Error("Response for " + url + " exceeds the " + MAX_JSON_BYTES + " byte cap");
    }
    return text;
  }
  const reader = response.body.getReader();
  try {
    const chunks: Uint8Array[] = [];
    let total = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (value) {
        total += value.byteLength;
        if (total > MAX_JSON_BYTES) {
          throw new Error(
            "Response for " + url + " exceeds the " + MAX_JSON_BYTES + " byte cap"
          );
        }
        chunks.push(value);
      }
    }
    const merged = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) {
      merged.set(chunk, offset);
      offset += chunk.byteLength;
    }
    return new TextDecoder("utf-8", { fatal: false }).decode(merged);
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // noop: lock release is best effort after a capped read.
    }
  }
}

async function fetchJson(url: string): Promise<unknown> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    let response: Response;
    try {
      response = await fetch(url, { cache: "no-store", signal: controller.signal });
    } catch (err) {
      if (controller.signal.aborted) {
        throw new Error(
          "Request for " + url + " timed out after " + FETCH_TIMEOUT_MS + " ms"
        );
      }
      throw err;
    }
    if (!response.ok) {
      throw new Error("Request failed with status " + response.status + " for " + url);
    }
    const text = await readCappedText(response, url);
    try {
      return JSON.parse(text) as unknown;
    } catch (err) {
      throw new Error("Response for " + url + " is not valid JSON: " + String(err));
    }
  } finally {
    clearTimeout(timer);
  }
}

/** Fetch and runtime validate the publish index. Failures throw, never fall back. */
export async function fetchIndex(): Promise<DataIndex> {
  return validateIndex(await fetchJson(dataUrl("index.json")));
}

/**
 * Fetch and runtime validate one snapshot. The stored snapshot_date must
 * match the requested asof, otherwise the payload is rejected.
 */
export async function fetchSnapshot(asof: string): Promise<SnapshotDoc> {
  assertAsof(asof, "fetchSnapshot");
  return validateSnapshot(await fetchJson(dataUrl(asof + "/snapshot.json")), asof);
}

/**
 * Fetch and runtime validate one verify report. When the published digest
 * for the date is known, the report digest must match it.
 */
export async function fetchVerify(asof: string, expectedDigest?: string): Promise<VerifyReport> {
  assertAsof(asof, "fetchVerify");
  return validateVerify(await fetchJson(dataUrl(asof + "/verify.json")), expectedDigest);
}

/**
 * Mock fixtures load only when VITE_USE_MOCK is "1" for local development.
 * Release CI must leave VITE_USE_MOCK unset (or any value other than "1")
 * so production bundles never serve fixtures, and must install with
 * `npm ci` against the committed package-lock.json.
 */
export function useMock(): boolean {
  return import.meta.env.VITE_USE_MOCK === "1";
}
