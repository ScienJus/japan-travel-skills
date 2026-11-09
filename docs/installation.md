# Installation and runtime compatibility

Choose the complete plugin for combined travel planning, or copy individual skill directories for
selected capabilities. Both contain the same specialist implementations. Obtain a source checkout
or extract the shareable ZIP into a stable directory first; this project does not yet publish a
public marketplace listing.

## Runtime requirements

| Component | Requirements |
| --- | --- |
| Eight travel CLIs | Python 3.9+ standard library; outbound HTTPS for live queries |
| Three restaurant CLIs | Python 3.10+; each skill's pinned `scripts/requirements.txt`; Python 3.12 recommended |
| Nationwide JAPAN RAIL PASS source | System `curl` in addition to Python |
| City guide | An available anonymous web search/fetch tool; no Python or CLI |
| Travel planner | Relevant specialists/source-reading tools; Python 3.9+ standard library only for the optional local HTML/presentation-brief helper; actual PPTX creation needs host authoring tools |

No provider API key, login, Node.js, GUI browser or background service is required. Python packages
must be installed into the interpreter used to run restaurant commands; installing the plugin does
not install Python or pip dependencies. These are local-execution tools, not a hosted weather or
booking service.

## Complete plugin in Codex

Use a Codex version with `plugin` commands. From the checkout or extracted bundle, install runtime
dependencies into a suitable virtual environment:

```bash
python3.12 -m venv /absolute/path/to/japan-travel-venv
/absolute/path/to/japan-travel-venv/bin/python -m pip install -r /absolute/path/to/japan-travel/requirements.lock
```

Register the stable source directory and install the bundle:

```bash
codex plugin marketplace add /absolute/path/to/japan-travel
codex plugin add japan-travel@japan-travel-local
codex plugin list --marketplace japan-travel-local --json
```

These commands change Codex's marketplace/plugin configuration. Start a new session after
installation if the host has not refreshed its skills. Verify that the installed package contains
all thirteen skills; `japan-travel-planner` handles combined questions and specialists can be used
directly. The package is a managed copy: source changes do not update installed files by themselves.

Once a source repository and release tag are published, a Git-backed marketplace can use
`codex plugin marketplace add OWNER/REPO --ref RELEASE_TAG`, followed by the same plugin install
command. Replace both placeholders with the actual repository and tag. An extracted ZIP can use
the local-directory procedure above; retain its hidden `.agents/` marketplace directory. Adding a
Git source or sharing a ZIP does not create a public plugin-directory listing.

Run the selected CLI's offline `doctor` with the chosen interpreter and its actual installed path:

```bash
/absolute/path/to/japan-travel-venv/bin/python /absolute/path/to/installed/japan-weather/scripts/weather.py doctor
/absolute/path/to/japan-travel-venv/bin/python /absolute/path/to/installed/tabelog/scripts/tabelog.py doctor
```

The host's skill catalog provides installed `SKILL.md` paths. Read that skill and use the sibling
script under `scripts/`; do not derive a cache path from a hard-coded username, plugin version or
checkout location. Commands may run from any working directory. Checkout `bin/` wrappers are
optional and are not required for installed use.

To update, update the registered source directory, rerun `codex plugin add
japan-travel@japan-travel-local`, and begin a new session if needed. Updating a Git marketplace
snapshot and refreshing installed local files are different operations; see `codex plugin
marketplace --help`. Keep the registered directory available. Check for separately installed copies
before using the same skill both independently and in the bundle: duplicate names can make selection
ambiguous.

## One skill in Codex or another compatible host

Copy the complete `skills/<name>/` directory, including `SKILL.md`, `LICENSE`, `agents/`, references,
scripts and runtime data that are present. Do not copy only `SKILL.md` or only its entry script.
The root repository, wrappers and sibling skills are not required by a specialist.

For current Codex filesystem discovery, a user location is `~/.agents/skills/`; repository-scoped
skills can live in `.agents/skills/` within the intended repository. Use the destination supported
by your host. For example, when the destination does not already exist:

```bash
mkdir -p "$HOME/.agents/skills"
cp -R /absolute/path/to/japan-travel/skills/japan-weather "$HOME/.agents/skills/japan-weather"
python3 "$HOME/.agents/skills/japan-weather/scripts/weather.py" doctor
```

For a restaurant skill, install that copied skill's own requirements rather than depending on the
bundle's root lock file:

```bash
python3.12 -m venv /absolute/path/to/restaurant-venv
/absolute/path/to/restaurant-venv/bin/python -m pip install -r /absolute/path/to/installed/tabelog/scripts/requirements.txt
/absolute/path/to/restaurant-venv/bin/python /absolute/path/to/installed/tabelog/scripts/tabelog.py doctor
```

Use the same procedure with `tablecheck` or `pocket-concierge` and its own requirements and entry
script. Each restaurant skill runs independently. City guidance is usable without installing the
planner; the planner coordinates only the specialists actually available and is not a substitute
for their data sources.

To update an independent skill, replace its complete directory with the newer copy after preserving
any intentional local changes. Do not nest a new copy inside an existing directory. Recheck
dependencies and `doctor`; plugin update commands do not update separate filesystem copies.

## Compatibility and validation boundaries

The developer checks distinguish runtime execution, plugin installation and agent behavior. A
successful `doctor` or metadata check does not prove source availability or automatic skill
activation. Read each result's status and coverage even after exit 0.

Local compatibility checks cover macOS arm64 with Python 3.9/3.12, clean bundle dependencies and
each restaurant skill's independent dependency installation. Codex CLI
`0.163.0-alpha.10.2` was checked for isolated installation, managed-copy refresh, removal and the
thirteen installed skill entries in a fresh model-visible prompt from an unrelated directory.
These host checks do not establish model tool-selection quality or an online success for every
provider. The checks do not install into a user's ordinary Codex profile.

The CI matrix covers full offline tests on Python 3.10/3.12 on Ubuntu and Python 3.12 on macOS,
plus the standard-library travel tests on Python 3.9 without third-party packages. A configured
matrix is not a successful hosted run; inspect repository checks after pushing. Windows execution
is unverified. Other agents need local script execution and outbound HTTPS for CLI-backed skills;
there is no claim that every host can run this plugin unchanged.

Weathernews's sakura forecast outputs still await in-season live validation. That limitation is
separate from the supported parsing and offline tests, JMC results and foliage checks. Preserve it
when evaluating coverage; see the [seasonal skill](../skills/japan-seasons/SKILL.md).

For current host behavior, see official OpenAI documentation for [skills and filesystem
locations](https://learn.chatgpt.com/docs/build-skills), [plugin
packaging](https://developers.openai.com/plugins/build/plugins) and [local-execution
plugins](https://developers.openai.com/plugins/deploy/desktop-only).
