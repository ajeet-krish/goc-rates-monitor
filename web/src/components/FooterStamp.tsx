import { Show } from "solid-js";
import { A } from "@solidjs/router";
import type { VerifyReport } from "../lib/types";
import { fmtShortSha } from "../lib/format";

interface Props {
  asof: string | null;
  sha: string | undefined;
  verify: VerifyReport | null;
  curveMethod: string | null;
  inflationMethod: string | null;
  breaksMethod: string | null;
  feedVintage: string | null;
  checkedUtc: string | undefined;
  unknownDate?: string | null;
}

export default function FooterStamp(props: Props) {
  const total = () => props.verify?.checks.length ?? 0;
  const state = () => {
    if (!props.verify) return "warn";
    return props.verify.passed ? "pass" : "fail";
  };
  const label = () => {
    if (!props.verify) return "verify missing";
    if (props.verify.passed) {
      return "verify pass " + props.verify.passed_count + " of " + total();
    }
    const failed = total() - props.verify.passed_count;
    return "verify fail " + failed + " of " + total();
  };
  const tolerance = () =>
    props.verify
      ? props.verify.tolerance_bp + " " + props.verify.tolerance_unit
      : "tolerance unknown";
  return (
    <footer class="footer-stamp" aria-label="Provenance stamp">
      <p class="stamp-title">Provenance stamp: snapshot, methods, verification</p>
      <div class="stamp-row">
        <span>
          snapshot date <span class="num">{props.asof ?? "date missing"}</span>
        </span>
        <span title={props.sha ?? "no digest published"}>
          snapshot sha <span class="num">{fmtShortSha(props.sha)}</span>
        </span>
        <span>
          tolerance <span class="num">{tolerance()}</span>
        </span>
        <span>
          curve method <span class="num">{props.curveMethod ?? "method unknown"}</span>
        </span>
        <span class="badge" data-state={state()}>
          {label()}
        </span>
      </div>
      <div class="stamp-row">
        <span>
          checked <span class="num">{props.checkedUtc ?? "checked time unknown"}</span> UTC
        </span>
        <span>
          inflation method <span class="num">{props.inflationMethod ?? "method unknown"}</span>
        </span>
        <span>
          breaks method <span class="num">{props.breaksMethod ?? "method unknown"}</span>
        </span>
        <span>
          feed vintage <span class="num">{props.feedVintage ?? "vintage unknown"}</span>
        </span>
      </div>
      <Show when={props.unknownDate}>
        <div class="stamp-row">
          <span>
            Unknown date requested: <span class="num">{props.unknownDate}</span>. Showing
            latest good snapshot instead.
          </span>
        </div>
      </Show>
      <div class="stamp-row">
        <A href="/verification">Read verification checks</A>
        <A href="/methods">Read curve method and limits</A>
        <A href="/breaks">Read breaks register</A>
        <A href="/inflation">Read inflation vintage</A>
      </div>
    </footer>
  );
}
