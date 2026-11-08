# Preparing a release

These steps prepare a reviewed source repository and an installable ZIP. They do not publish a
repository, create a Git tag, install into a user's profile or submit a marketplace listing.

## Validate the source checkout

Use the environment from the [README setup](../README.md#use-from-this-checkout):

```bash
.venv/bin/python scripts/check_repo.py
.venv/bin/python scripts/check_privacy.py
.venv/bin/python -m unittest discover -s tests -v
```

The suite includes extracted-bundle and independent-skill checks from an unrelated directory.
Review changed instructions for clear routing, source/date identity, unknown states and request
boundaries. Prompt-only edits do not require repeated itinerary comparisons. For CLI changes,
use focused regression tests and source evidence; when an integration changes, follow its bounded
live-check policy. Keep captures, review records and artifacts outside the repository.

Confirm that every shipped skill retains its license, runtime data and declared dependencies.
Keep the documented qualifications: fourteen curated destinations, source-specific coverage,
unverified Windows execution and Weathernews sakura forecasts awaiting in-season live validation.
Do not describe an offline check as provider availability or model-quality validation.

## Build and inspect the bundle

```bash
.venv/bin/python scripts/build_plugin.py
```

The builder rejects common privacy/credential patterns in the exact release contents before
writing a ZIP. Recheck the finished artifact with `python3 scripts/check_privacy.py --archive
/absolute/path/to/bundle.zip`. Findings never print matching values. The check is a safeguard,
not proof that all personal information has been found; review the diff and archive manually.
Follow [SECURITY.md](../SECURITY.md) and remove personal/employer configuration before the first
public commit. Enable GitHub private vulnerability reporting before making the repository public.

For local static and dependency checks, use a development environment with
`python3 -m pip install -r requirements-security.txt`, then run
`python3 -m bandit -r skills scripts -ll` and
`python3 -m pip_audit --no-deps --disable-pip -r requirements.lock`.
Bandit reports medium/high-severity findings; low-severity diagnostics can be reviewed separately.
Dependency advisories require network access and send package names/versions, not travel queries.
An unavailable audit is incomplete, never a clean bill. Dependabot proposes updates; keep shared
runtime pins aligned across the root lock and independent restaurant requirements.

The filename uses `plugin.json`'s version and defaults to
`~/.local/share/japan-travel-skills/artifacts/japan-travel-<version>.zip`. Keep version metadata stable
during preparation. Select and confirm the release version once before tagging; do not change it
for each local build. Inspect the ZIP's manifests, thirteen complete skill folders, eleven wrappers,
licenses and dependency files. Tests, captures, local environments and personal paths do not belong
in the package. The explicit lists in `scripts/build_plugin.py` define its contents.

Generate and share a SHA-256 checksum beside the ZIP. For example, from its output directory:

```bash
shasum -a 256 japan-travel-<version>.zip > SHA256SUMS
shasum -a 256 -c SHA256SUMS
```

Replace `<version>` with the manifest version. The CI workflow also uploads
`japan-travel-bundle`, containing `japan-travel.zip` and `SHA256SUMS`, after its Ubuntu/Python 3.12
checks pass. Download it from the workflow run's artifacts. Other matrix jobs must also pass
before release; the presence of this artifact alone is not a release approval. CI does not create
a public release or query upstream travel providers.

## Publish when authorized

1. Review the source changes and intended repository visibility. Commit only source, tests and
   maintained documentation; check the Git identity for the intended remote before committing.
2. Push to the chosen repository and inspect the actual hosted CI results. A configured matrix or
   a local test result does not establish that the hosted run passed.
3. Create a tag matching the confirmed manifest version. Attach the reviewed ZIP and checksum to
   that release, with a short capability summary, runtime requirements and material source limits.
   Confirm that the ZIP was built from the tagged source.
4. Follow [installation instructions](installation.md) from a clean directory. A public Git
   marketplace, local ZIP installation and public plugin-directory submission are separate paths.
   Use the current [desktop-only plugin guidance](https://developers.openai.com/plugins/deploy/desktop-only)
   if submitting a local-execution plugin to the public directory.

Do not advertise a repository URL, tag, hosted check or marketplace listing before it exists.
