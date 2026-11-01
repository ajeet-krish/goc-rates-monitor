export default function MethodsPage() {
  return (
    <section aria-label="Methods">
      <p class="hero-kicker">Methods: what v1 claims and what it does not</p>
      <h2 class="hero-headline">Par approx, stated plainly.</h2>
      <div class="ledger-card">
        <h2>Curve v1</h2>
        <p>
          Method <span class="num">par_approx_semiannual_log_discount_v1</span>.
          Benchmark YTM inputs are treated as par approximations. Knot discounts use
          D equals 1 over (1 plus y over 2) to the 2T. Log discounts interpolate
          linearly. Ends hold the nearest yield flat. Long is a 30Y proxy.
        </p>
        <p>
          No Nelson Siegel Svensson in v1. The 10s30s slope carries the largest
          approximation error. Benchmark switches are flagged, never spliced.
        </p>
      </div>
      <div class="grid-two" style={{ margin: "16px 0" }}>
        <div class="ledger-card">
          <h2>Carry and risk</h2>
          <p>
            Carry roll uses horizon 0.25 years, ex coupon and ex funding, on an
            unchanged curve. Risk uses semiannual closed forms for price, modified
            duration, and DV01 per million.
          </p>
        </div>
        <div class="ledger-card">
          <h2>Verification</h2>
          <p>
            Eighteen checks V01 to V18 at 1.0 basis point tolerance. Any failure
            blocks the build. Derived quantities carry units and a derived source.
          </p>
        </div>
      </div>
    </section>
  );
}
