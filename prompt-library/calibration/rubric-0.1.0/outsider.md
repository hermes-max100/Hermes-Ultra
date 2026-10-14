# Migrate the billing cron to the job queue

## Goal
Move the nightly `billing-reconcile` cron job onto the shared job queue without changing its output.

## Success criteria
- Queue run and cron run on the same snapshot produce byte-identical CSVs.
- Cron entry removed only after three consecutive matching nightly runs.

## If things go wrong
Any diff between the two outputs: halt, keep cron authoritative, attach the diff. Never delete the cron entry on a mismatch.

## Proof required
The three CSV hashes per night, and the commit removing the cron line.

## What we're taking for granted
We are assuming the snapshot is immutable during a run; check the snapshot lock before the first comparison.
