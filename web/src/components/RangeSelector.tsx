import { For } from "solid-js";
import { RANGE_KEYS, rangeKey, setRangeKey } from "../lib/history-range";
import type { RangeKey } from "../lib/types";

/**
 * Shared range switch for the history charts on one page. One instance per
 * page reads and writes the module signal, so every chart on the page follows
 * the same choice without per chart state. ARIA radiogroup pattern: arrow
 * keys move and select, Home and End jump to the ends, and roving tabindex
 * keeps the group to a single tab stop with the checked segment focused.
 */
export default function RangeSelector() {
  let options: HTMLButtonElement[] = [];

  const selectAt = (index: number) => {
    const key: RangeKey | undefined = RANGE_KEYS[index];
    if (key === undefined) return;
    setRangeKey(key);
    const target = options[index];
    if (target) target.focus();
  };

  const handleKeyDown = (event: KeyboardEvent, index: number) => {
    const count = RANGE_KEYS.length;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      event.preventDefault();
      selectAt((index + 1) % count);
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      event.preventDefault();
      selectAt((index - 1 + count) % count);
    } else if (event.key === "Home") {
      event.preventDefault();
      selectAt(0);
    } else if (event.key === "End") {
      event.preventDefault();
      selectAt(count - 1);
    }
  };

  return (
    <div class="range-selector">
      <span class="range-selector-label" aria-hidden="true">
        Range
      </span>
      <div class="range-selector-track" role="radiogroup" aria-label="Range">
        <For each={RANGE_KEYS}>
          {(key, index) => (
            <button
              type="button"
              role="radio"
              class="range-selector-option"
              aria-checked={rangeKey() === key}
              tabIndex={rangeKey() === key ? 0 : -1}
              onClick={() => setRangeKey(key)}
              onKeyDown={(event) => handleKeyDown(event, index())}
              ref={(element) => {
                options[index()] = element;
              }}
            >
              {key}
            </button>
          )}
        </For>
      </div>
    </div>
  );
}
