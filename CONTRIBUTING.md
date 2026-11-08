# Contributing

Contributions are welcome: report problems, improve existing tools and instructions, add reliable
travel-research tools, or expand the official city guides. You do not need to write code to help.
An unclear result, a broken source link or a useful official tourism portal is a good starting point.

## Report a problem or suggest an improvement

For security or privacy vulnerabilities, follow [SECURITY.md](SECURITY.md) instead of posting
sensitive details in a public issue. The [source policy](docs/sources.md) distinguishes official,
commercial and community data and defines the selection defaults.

Open an [issue](https://github.com/ScienJus/japan-travel-skills/issues) in this repository. Describe what you were trying to find, what happened and what
you expected. Include only the details relevant to reproducing the problem:

- The skill, CLI command or agent request, and the relevant part of the output.
- The location, travel date and time zone when they affect the result.
- The plugin version or source revision, Python version and operating system, if known.
- The original source URL and when you checked it, especially for incorrect or missing information.

For agent behavior problems, a short example is more useful than a complete conversation.
Remove personal travel details, local usernames/paths, credentials, cookies and session data from
anything you share. An incomplete report is still welcome; say which details are unknown.

## Improve or add a tool

Small fixes to parsing, missing information, errors, request costs and documentation are welcome.
For a new integration, start by explaining the travel-planning need, the proposed source and a
small example of information it can reliably provide. Validate source quality before building
around it; an issue or draft pull request can establish this first.

- Prefer official operators, public institutions and established Japanese services. Identify the
  publisher, geographic coverage, update information and material limitations. Official status
  alone does not establish that a particular field is current or suitable for the question.
- A documented API is not required. Public JSON or HTML can be suitable when anonymous access,
  source terms and reliability support the use. Do not bypass access restrictions or use accounts,
  login cookies or authenticated sessions.
- Keep queries bounded and follow the [HTTP client contract](docs/http-client.md). Attribute
  results and preserve unknown, stale and unavailable states rather than filling gaps by inference.
- Keep each skill self-contained under `skills/<name>/`, with its instructions, source references,
  implementation, declared dependencies and license. Read [AGENTS.md](AGENTS.md) for project rules.
- Cover changed behavior with focused offline tests, including relevant failure cases. If a network
  integration changes, follow its source policy for one small live check; avoid repeated provider
  queries. Keep captures and investigation records outside the checkout.

This project supports anonymous, read-only travel planning. Reservation creation, changes,
cancellations, holds, waitlist submissions, purchases and payments are outside its scope.

## Add or improve a city guide

City guides are maintained Markdown source navigation, not a database of copied attraction content.
See the [city-guide skill](skills/japan-city-guide/SKILL.md) and the
[Toyama reference](skills/japan-city-guide/references/toyama.md) for the existing structure.

1. Extend the relevant prefectural file in `skills/japan-city-guide/references/`, or create one if
   missing. Put municipal entries inside that file; distinguish city and prefectural coverage.
2. Identify the official tourism body and show how its relationship to the portal is established,
   such as an organization page or a municipal-government link. Record the entry-check date and
   what was actually readable; this is separate from the publisher's update time.
3. Add a small set of useful entries for attractions, events, food, routes and practical access,
   where available. Preserve Japanese source names and link to original pages. Explain material
   language, geographic or access limits, and use facility/operator sites for visit conditions.
4. Keep hours, prices, event dates and seasonal conditions for live verification. Do not copy whole
   articles, mirror third-party content or treat a tourism listing as proof a venue is open.
5. Update the skill's destination index and, when coverage changes, the root capability summary.
   Add any new distributed file to the explicit lists in `scripts/build_plugin.py`.

If you only have a promising official link or a correction, an issue is enough; a complete guide
is not required.

## Prepare a pull request

Keep changes focused. Explain the user-visible benefit, source evidence where relevant, checks
performed and any remaining uncertainty. Follow the [README development setup](README.md#development)
and run the repository metadata/link check plus the tests appropriate to your change. Documentation
changes need link/content review; runtime changes need relevant offline regression checks. Use the
[release guide](docs/releasing.md) for changes affecting distribution.

Maintain documentation in English and retain Japanese source labels. Keep prompt edits concise;
explain the intended behavior without treating one model's response as a universal failure or
requiring repeated itinerary comparisons. Do not bump the version for routine contributions.
Submit code, automated tests and maintained documentation; keep raw captures, personal trip records,
benchmark run records and review logs outside the repository. Retain existing licenses and attribution.
