import { createContext, useContext, type ParentProps } from "solid-js";
import type { DataIndex, HistoryDoc, SnapshotDoc, VerifyReport } from "./types";

export interface DeskState {
  index: () => DataIndex | undefined;
  indexError: () => string | null;
  asof: () => string | null;
  unknownDate: () => string | null;
  /** Compare snapshot date from ?compare=, validated against the index. Null when absent. */
  compare: () => string | null;
  unknownCompare: () => string | null;
  compareSnapshot: () => SnapshotDoc | null | undefined;
  compareLoading: () => boolean;
  compareError: () => string | null;
  snapshot: () => SnapshotDoc | null | undefined;
  snapLoading: () => boolean;
  snapError: () => string | null;
  verify: () => VerifyReport | null | undefined;
  verifyLoading: () => boolean;
  verifyError: () => string | null;
  /** Merged history loads independently and never blocks derived displays. */
  history: () => HistoryDoc | null | undefined;
  historyLoading: () => boolean;
  historyError: () => string | null;
  /** True while derived values must stay hidden (verify missing, failed, or errored). */
  blocked: () => boolean;
  blockReason: () => string | null;
}

export const DeskContext = createContext<DeskState>();

export function useDesk(): DeskState {
  const ctx = useContext(DeskContext);
  if (!ctx) throw new Error("useDesk must be used inside DeskContext.Provider");
  return ctx;
}

export function DeskProvider(props: ParentProps & { value: DeskState }) {
  return <DeskContext.Provider value={props.value}>{props.children}</DeskContext.Provider>;
}
