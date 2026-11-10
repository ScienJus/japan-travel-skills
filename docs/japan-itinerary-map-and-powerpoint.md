# Turn a Japan itinerary into an interactive map and PowerPoint

Japan Travel Skills can turn a shared itinerary into a local HTML travel guide and a presentation
brief. The guide switches dates to show the corresponding stops and transport. It filters hotels,
attractions and restaurants, and keeps places without sourced coordinates in the list. An actual
PowerPoint file requires presentation tools available in the agent's host.

## Ask your agent to visualize a trip

[Set up the Japan Travel Skills](installation.md) and give the planner a trip brief or an existing
itinerary. Say whether to research the trip or only reformat your supplied content.

> Use the japan-travel-planner skill to turn my Japan itinerary into a mobile-friendly local HTML guide with
> a map, and an illustrated PPTX if presentation tools are available. Include overnight bases,
> intercity travel, sights, local dishes and restaurant candidates from my plan. Preserve fixed
> choices, source links and unresolved checks. Do not publish the files.

For a draft that may contain scheduling conflicts, [check the itinerary](check-japan-itinerary.md)
before producing several views of it.

## Generate the Kyoto–Nara example locally

Run from the repository root with Python 3.9 or later. The two files use the same public example
records and need no network access to generate. Use an output directory outside the checkout.

```bash
demo_dir="$(mktemp -d)"
python3 skills/japan-travel-planner/scripts/render_plan.py \
  --input skills/japan-travel-planner/examples/kyoto-nara-demo.json \
  --output "$demo_dir/guide.html"
python3 skills/japan-travel-planner/scripts/render_plan.py --format brief \
  --input skills/japan-travel-planner/examples/kyoto-nara-demo.json \
  --output "$demo_dir/presentation.md"
printf 'Example files: %s\n' "$demo_dir"
```

Open `guide.html` locally. Switch between the Kyoto stay and the Nara day trip, then use the place
filters or download the shared JSON. This curated demo has sample dates and candidate choices;
it is not a verified future itinerary. The Markdown brief contains editable plan records and
page patterns for a presentation tool. The commands use the repository's Chinese sample. The
product site also offers English and Japanese versions of the same example.

## Keep the map and presentation in agreement

Both views should carry the same dates, overnight bases, transport notes and venue conditions.
For a deck, use illustrations with suitable reuse rights, retain their credits and keep the checked
scope beside the relevant choice. After a change to the itinerary, regenerate or revise the affected
views.

The local guide makes no external requests by default. The optional GSI basemap loads only when
requested in the page; mapped points do not establish routes or walking times. The HTML embeds
the full plan, so review all records before sharing. See the [data contract](../skills/japan-travel-planner/references/plan-data.md)
and [delivery workflow](../skills/japan-travel-planner/references/deliverables.md) for details.
