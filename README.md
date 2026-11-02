# GoC Rates Monitor

Live site: https://ajeet-krish.github.io/goc-rates-monitor/

## What this is

This is a daily Government of Canada rates desk for reading levels, shape, funding cost, and inflation pressure in one place. It is an end of day desk, not a real time terminal, and it updates on a next day rhythm as official sources publish. Think of it as a morning briefing page that shows what yesterday closed at and why you can trust it.

## Start here in 2 minutes

Open the live site and start on Desk, which gives you the one paragraph thesis for today. Note the 2 year yield, the 10 year yield, the slope between them, the Canada minus United States gap, and the carry for holding the position. Then open Curve to see whether the move came from the front end or the long end. Then open Verification to confirm the day is marked verified before you quote it.

## Page by page

Desk is today in one view, with the headline yields, the curve chart, and the short table that explains the thesis. Curve answers whether quoted yields and solved zeros agree, since quotes go in and mathematically solved zeros come out. Funding answers what it costs to hold the trade, using overnight funding, cross border spreads, carry for price drift as time passes, and sensitivity to a small rate move. Inflation separates final headline inflation from experimental core replicas for trim and median, plus a clear validation flag that tells you whether the replica is tracking its publisher. Breaks tells you when a benchmark bond was switched, so you do not mistake a substitution for a market move, and it also flags calendar gaps. Verification is the trust page, where every check passes or the desk visibly blocks derived values. Methods is the plain language rulebook, with assumptions, limits, and what each number assumes.

## How to interrogate a day

Pick any published date from the date menu to travel back in time, and add a second date to overlay it for direct comparison. The comparison shows the current value, the earlier value, and the difference in simple basis points. Use the history charts to separate solid verified spans from dashed backfilled spans. Sort any table by tapping a column header, and export any table to a spreadsheet file for your own notes. Use the left and right arrow keys to step one published day at a time. Share a view by copying the page address after you pick a date, since the date travels with the link.

## What dashed, NA, and suppressed mean

A solid line means a verified snapshot stands behind that point. A dashed muted line means backfilled history that is useful for shape but not yet sealed by verification. The letters NA mean the desk chose to show nothing rather than show a guess, and a short reason is always printed nearby. A suppressed day over day move means a benchmark switch happened inside the window, so the change is hidden on purpose because it would compare two different bonds. Calendar gap means trading days were skipped for a holiday or weekend, so the number is kept but flagged. Carry tells you the expected price drift from the passage of time if the curve froze, excluding coupons and funding. Sensitivity tells you the approximate dollar change per million for a tiny parallel move in rates.

## Trust and limits

The desk fails closed, which means any failed check turns affected values to NA and blocks the page with an explanation. Empty and degraded notices are honesty, not software bugs. Spreads can be missing when the United States leg is unavailable in the automated build, and inflation can read as degraded when basket weights drift from vintage. Official inflation prints are final, while trim and median replicas stay experimental and revisable. Long end shape past the last anchor is a flat proxy, not a forecast. This desk explains yesterday with named sources and named checks, and it will not invent a number to fill a gap.
