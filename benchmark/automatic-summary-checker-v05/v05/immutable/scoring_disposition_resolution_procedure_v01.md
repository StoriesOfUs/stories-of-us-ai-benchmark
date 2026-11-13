# Protected scoring-disposition resolution procedure V01

Status: **FROZEN PROPOSED EXPERIMENTAL PROCEDURE**

This procedure applies after the candidate checker's response has been captured and
frozen. It does not permit another model request, clarification, retry, correction
or altered candidate decision.

## Common record

For every disposition review preserve unchanged:

- the complete candidate response and its original diagnostic decision;
- the candidate summary and its exact anchors;
- the complete retained source evidence and evidence IDs;
- the protected reference inventory and expected verdicts used at scoring time;
- the first adjudication, scorer output and package freeze; and
- reviewer identity as `CODEX_ASSISTED` unless an actual human review is recorded.

## Inventory gap

Confirm from the unchanged summary that the proposition is genuinely asserted or
necessarily implied and that no protected reference unit represents its material
meaning. Record `INVENTORY_GAP`; do not count it as checker invention or factual
error. The affected experimental gate stops.

Any correction to the protected inventory or expected verdicts requires explicit
owner approval, a separately versioned package, review of the changed key, affected
offline regression tests and a new freeze. Preserve the original unresolved score.
Only the saved response may be rescored under the approved successor; the earlier
package may not be retrospectively relabelled PASS.

## Uncertain mapping

Record `UNCERTAIN_MAPPING` when the unchanged wording, summary anchors and evidence
do not support a confident mapped/invented/inventory-gap decision. The affected gate
stops. A subsequent authorised semantic review may resolve the saved portion as
`MAPPED`, `INVENTED` or `INVENTORY_GAP`, using only the unchanged record. If doubt
remains, the status remains unresolved and no PASS is available.

## Invention and mapped claims

Use `INVENTED` only when the checker attributed a proposition that the summary
neither asserts nor necessarily implies. A false proposition genuinely present in
the summary is `MAPPED` when represented by the inventory; its factual verdict is
then scored separately. A compound returned claim receives multiple portion rows
where necessary so a mapped portion cannot conceal an invented or unresolved part.

