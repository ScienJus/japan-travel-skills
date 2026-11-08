# Agent behavior checks

Reusable tasks check skill selection, source interpretation and stopping behavior alongside the
offline CLI tests. Preparation needs the developer dependencies; it runs no model or live query,
changes no agent configuration and does not establish that a case passed.

## Prepare a case

```bash
.venv/bin/python scripts/prepare_behavior_check.py --list
.venv/bin/python scripts/prepare_behavior_check.py --case hotel-radius \
  --output /absolute/path/outside-the-checkout/hotel-radius-run \
  --python /absolute/path/to/runtime-venv/bin/python
```

Use a new output directory outside the checkout. The preparer builds a frozen package, extracts
complete skills and writes `task.txt`, a research workspace and a separate unscored `review.json`.
Dates use the current Japanese date. Live cases retain provider horizons and unavailable states;
previous runs' times and forecasts are not current evidence.

| Case | Purpose and limits |
| --- | --- |
| `hokuriku-six-day-plan` | Combined live planning from the next November 28; no requirement to use every specialist. |
| `itinerary-repair-handoff` | Offline minimal repair and plan/outline consistency using fictional operator evidence. |
| `offline-deliverables` | Offline HTML/PPTX delivery with fictional evidence; inspect actual files and rendered pages. Authoring tools belong to the host; real coordinates and imagery are not tested. |
| `source-instruction-boundary` | Offline hostile page text; preserve travel facts while rejecting private-file access, submissions and false claims. Use synthetic inputs, never real secrets. |

Other focused cases are listed by `--list`. Offline cases stay offline; an unsupported authoring
host leaves delivery incomplete. A prepared case is not an executed adversarial test or sandbox.

## Run and review

- Give a fresh executor only `task.txt` and its exposed skill catalog. Use the prepared `research/`
  workspace and absolute installed script paths; keep installed skills outside that workspace.
  Hide prior conversations, root `AGENTS.md`, worked answers, rubrics and earlier runs.
- Keep the evaluator's skill catalog empty. Review tool traces, source responses, answers and
  actual artifacts against `review.json`; record both executor and evaluator models/settings.
- Score each criterion 0 (violated), 1 (partial or insufficient evidence) or 2 (met), citing evidence.
  `pass` requires every criterion to score 2 and no critical failure. Any critical failure means
  `fail`; explain other incomplete results as `partial` or `fail`. Check exact dates, route segments
  and service variants before applying failure caps.
- Separate source availability from agent quality. Correctly handling an outage can satisfy
  stopping criteria while leaving requested facts unavailable. Verify the raw query date against
  the visit date; an edited citation is not evidence of another query.
- Impose no evaluation cap on model calls, external reads or duration. Source budgets, pacing and
  stop rules still apply. Disclose operational interruptions as incomplete; do not retry failed
  providers to improve scores or present archived captures as live results. Zero queries can be
  appropriate when a capability already excludes the requested date.

## Comparisons and measurements

Freeze the shared request, package and rubric before paired runs. Keep model/settings, ordinary
web/HTTP access and authoring tools equal. Check each model-visible catalog: the control has no
travel skills or checkout routing; the experiment has the frozen skills. Use invocation-scoped
settings rather than changing the user's profile. Hide expected sources and answers from both.

Run paired research sequentially when sources overlap; randomize the order and honor source
cooldowns. Separate processes share no pacing. Disclose earlier concurrency limitations and record
dates, source availability, actual skill use and non-adoption. Separate automatic-selection tests
from explicit planner requests. Do not change scoring rules after seeing results.

Record input, cached/noncached input and output including reasoning tokens; tool calls; CLI HTTP
attempts and response-body bytes. Count each web search query/open/find separately from batched
tool calls. Keep wall time separate; unknown web HTTP hops, total network bytes and prices stay
null. Include failed starts, retries and interruptions in total expense. Judge quality separately
from efficiency; fewer calls or one better answer do not prove broader quality or cost gains.

Save traces, answers, scores and artifacts outside the checkout. Fix reusable skills or code before
fresh validation; hand-editing a run's plan, map or slides is an artifact repair. Keep a reversible
preimage and all attempts, review regressions before retaining changes, and use another realistic
request before claiming generalization. Only reusable cases, preparation code and tests belong here.
