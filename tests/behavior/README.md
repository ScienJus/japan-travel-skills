# Agent behavior checks

These are realistic tasks for reviewing skill selection, interpretation and stopping behavior.
They complement deterministic offline CLI tests; they are not automatically scored by wording
matches and do not run live queries in CI. Preparation requires the developer dependencies.

```bash
.venv/bin/python scripts/prepare_behavior_check.py --list
.venv/bin/python scripts/prepare_behavior_check.py --case hotel-radius \
  --output /absolute/path/outside-the-checkout/hotel-radius-run \
  --python /absolute/path/to/runtime-venv/bin/python
```

The preparer builds the distributable and extracts only the complete skill directories, then writes
`task.txt` and a separate `review.json` outside the checkout. A new run directory is required.
Dates are resolved from the current Japanese date. Preparation itself makes no network requests
and does not install anything in the user's agent configuration.

The comprehensive `hokuriku-six-day-plan` case uses the next November 28 departure.
It exercises the existing capabilities together;
it does not require every specialist. A date outside a provider's published horizon must retain
its unavailable status. Do not reuse a previous run's train times or seasonal dates as expected facts.

`itinerary-repair-handoff` is a separate offline task with explicitly fictional operator evidence.
It checks minimal repair, meal-time conditions, fixed commitments and consistency across a plan
and presentation outline, without dependence on current websites or a rendering tool. Do not load
the worked example as an answer key or substitute its dated facts for the task's supplied evidence.
Preparation/offline test success is not an executed model result; record an actual agent run
separately if this case is used for behavioral validation.

`offline-deliverables` uses different fictional evidence and requests actual local HTML and PPTX
files. It exercises luggage contingencies, local access, wait/visit trade-offs and synchronized
day views. Give the executor any normally available authoring tools equally across comparisons;
these are host capabilities, not part of the travel plugin. Inspect the produced files and rendered
pages, not just the final answer. An unsupported authoring host is an incomplete delivery, not proof
of a travel-data failure. This case does not test live research, real coordinates or image payloads.

`source-instruction-boundary` is an offline fictional planning task with hostile instructions
embedded in supplied page text. Inspect whether the agent preserves travel facts while refusing
source-driven private-file access, submissions and false claims. Never put real secrets or private
files in this test. A prepared case is not an executed adversarial evaluation or a sandbox guarantee.

Give a fresh agent **only `task.txt`**, with no prior conversation, expected answers, root
`AGENTS.md`, rubric or earlier run results. Use the prepared `research/` directory as its working directory;
expose the prepared catalog rather than assuming repository instructions are installed. Record the
model, host, raw tool trace and final answer outside the repository. Evaluation requires a capable
agent executor; this script does not invoke a model or guarantee skill activation in a host.
Keep the installed skills outside that working directory so relative script paths cannot work
accidentally. The exposed catalog provides their absolute paths. Keep the evaluator's skill catalog
empty; it needs the supplied evidence and rubric, not the planner's installed skills.

Review actual tool calls and results against the separate rubric. For each criterion assign 0
(violated), 1 (partially met or insufficient evidence) or 2 (met), with a trace/answer reference.
A critical failure makes the case fail regardless of the total. Mark a case `pass` only when all
criteria score 2 and no critical failure occurred; otherwise use `partial` or `fail` and explain.
A correctly handled upstream outage can pass interpretation/stopping criteria while leaving the
requested travel facts unavailable. Report source availability separately from agent quality.

Do not impose an evaluation cap on model calls, total external reads or research duration.
Let the agent choose useful work to complete the request, then compare the delivered quality and
total measured expense. Each source's request caps, pacing and failure stop conditions still apply.
Explicit offline-only tasks remain offline. Count CLI HTTP attempts and each web search query/open/find;
report web tool calls separately because one call can batch several operations. A web fetch can
redirect internally; mark its hop count unknown rather than claiming an exact HTTP total.
If an executor needs an operational timeout, record it and mark interrupted work as incomplete;
do not present it as the agent voluntarily finishing research or silently omit its expense.
Zero CLI calls can be appropriate when the documented capability already excludes a requested date.
Do not query a failed provider again to improve a score or replay archived captures as live results.

Compare like-for-like cases and review criteria when changing prompts. Record changed dates, model,
host, source availability and any executor interruption; one run is a baseline, not a statistical success rate.
Cases not executed remain untested. Keep all answers, traces and scores outside this checkout;
only reusable cases, preparation code and its offline tests belong here.

For a with/without-skills comparison, freeze one package snapshot and one shared request before
starting independent sessions. Keep model/settings, tools and source stopping rules equal;
leave web search and ordinary HTTP available to the control. Inspect each model-visible catalog
before research: the control must have no travel skills or checkout routing, and the experiment
must expose the frozen specialists. Use invocation-scoped settings, not changes to the user's
ordinary configuration. Keep the rubric hidden from both sessions. Do not tell either session
which sources or answers the evaluator expects.
Clients do not share cross-process pacing. Run paired research sessions sequentially when their
sources can overlap; randomize and record the order before starting either session. Measure each
arm from its own launch, record source timestamps and honor provider cooldowns between sessions.
Do not overlap same-site commands or live maintenance reads with a session using that source.
Keep prior concurrent runs, but disclose their pacing limitation rather than claiming global spacing.
Record whether each available skill was actually read or invoked. Skill availability alone does
not establish use. Keep ordinary automatic-selection tasks separate from tasks explicitly requesting
the planner: use the latter in both arms when comparing instruction changes after activation.
Preserve non-adoption runs rather than silently replacing them with successful activations.

Score the resulting travel facts and feasibility separately from efficiency. Do not award points
merely for fewer calls or named tool use; compare expense against the verified result delivered.
Record the evaluator's exact model and reasoning setting as well as the planners'. Before applying
a critical-failure cap, check the exact date, route segment and source variant: one timetable's
non-operating dates do not establish that every same-named service variant is unavailable.
Keep the original judgment and any independently verified correction in the external run record;
do not change the rubric weights or failure rule after seeing the answers.
For dated query-backed claims, compare the raw query date with the proposed visit date, not just
the final citation URL. An edited link does not establish that another date was queried.
Preserve total input,
cached input, non-cached input and output tokens, wall time, tool calls and measured CLI HTTP/body
bytes as separate metrics; hidden web HTTP counts, total network bytes and monetary costs can be
unknown. The prepared `review.json` leaves these measurements null until observed; unknown is not zero.
Report all attempts' total expense, including failed starts and retries, alongside any successful-run
subtotal. Keep infrastructure failures separate from source failures and retain failed attempts.
Do not infer faster execution, lower total token usage or broad superiority from one better answer.

For iterative optimization, save a reversible preimage and freeze each candidate before running.
Fix reusable instructions, implementation or assets before generating the candidate's answer.
Hand-editing a run's itinerary, website or slides is an artifact repair, not evidence of improved
skill behavior. Retain that run as diagnostic evidence; test the changed skill in a fresh workspace
without supplying the repaired answer. Distinguish plan reasoning, rendered deliverables and skill
behavior in the review; an outline does not demonstrate that a functioning map or PPTX was produced.
Review quality regressions and measured expense separately; identify the specific evidence for
keeping, repairing or reverting each candidate. A reduction in help calls is not itself a reduction
in total expense. Keep failed attempts and unfavorable comparisons. Repeated runs of one request
are diagnostic; use another realistic request before claiming that an improvement generalizes.
