# Review of the 0.9.4 hardware capture

Source: `home-assistant_energy_owl_2026-11-16T19-29-59.508Z.log`, captured on
16 November 2026, approximately 20:24:35–20:29:59 Europe/Rome.

## Findings

- Two batches close at 20:27:16.995 and 20:29:46.995. Both reach successful local
  prefix cleanup, at 20:27:17.181 and 20:29:47.195 respectively. The continuous
  stream no longer starves imports as in 0.9.3. Five live packets appear in the
  debug capture, with changing current readings and successful coordinator polls.
  There are no Energy OWL connection errors or recovery loops in this capture.
- These are routine recent-minute records, with duplicate transmissions, rather
  than evidence of a large recovery of missing history. Version 0.9.4 nevertheless
  reopens `syncing`, fires a completion event and creates a persistent notification
  for every internal batch. This is inappropriate user-visible behavior.
- At 20:29:47.001, the importer logs one skipped historical minute. The batch
  contains a 20:29 record received at 20:29:20.157. Its interval ends at 20:30,
  so validation rejects it at 20:29:47. Cleanup then discards the entire snapshot.
  A later device replay might recover it, but correctness should not depend on
  receiving a duplicate. The fix retains the open minute and everything after it
  until a subsequent batch, even when no new packet arrives.

The log demonstrates successful import processing and local cleanup, not a
Recorder database commit. It does not establish that every historical minute is
present in the production database or validate the absolute energy total.

## Corrected behavior

Bounded internal batches continue to save the ledger before cleanup. Routine
minute history remains silent and the diagnostic status stays `complete` after
initial processing. Only a substantial backfill (60 newly accepted distinct minutes
older than five minutes) enters `syncing`. Counts exclude already imported minutes,
duplicates and records outside the ledger's retained correction window. After two
minutes without older-history activity, with no older records pending, status
returns to `complete` and one notification and completion event are emitted.
Small separate backfills do not accumulate into a later spurious notification.

The importer snapshots only a contiguous prefix before an unfinished current
minute. Action reads/exports cannot replace that prefix length while a save is in
progress. Reopening the internal batch also works when a deferred minute is the
only remaining record and no subsequent packet arrives.

## Other integrations

The capture also contains SNMP printer blocking-filesystem warnings and duplicate
discovery errors, an LG ThinQ missing device profile, an unreachable ESPHome display
with a logging callback exception, and a Zigbee exception. These originate outside
Energy OWL.
