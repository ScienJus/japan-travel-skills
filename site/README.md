# Product site

The GitHub Pages build combines a product homepage, the two task guides in `docs/`, the Hokuriku case study, and
the public Kyoto–Nara example rendered with the planner's existing helper. The homepage walks through
planning, review and delivery using a curated excerpt from the sample. The map and downloadable
Markdown presentation brief are generated from the same demo plan. Site build dependencies are
separate from the plugin.

## Build and review

From the source checkout, use a Python 3.10+ development environment:

```bash
python -m pip install -r site/requirements.txt
python scripts/build_docs_site.py --output /absolute/new/path/outside-the-checkout/site
```

Open `index.html` from the output directory or serve the directory with a local HTTP server.
Check each language's navigation, both guides, the Hokuriku case study, the three demo stages, the presentation brief
download, the embedded and standalone maps, and the mobile layout.
The build scans the output for private data. Keep previews and generated artifacts outside the
repository. The plugin ZIP does not include the site build or its dependencies.

## Translations

Site labels and homepage strings live in `locales/<language>/`. The English guides use the original
Markdown in `docs/`. The English case study comes from the planner's worked example. Chinese
and Japanese articles live beside their locale catalogs. Links between articles stay in the same
language. Links to installation and other repository material
lead to the original documents.

The public demo uses the planner's Kyoto–Nara sample as the source of truth. Each locale catalog
translates display text. IDs, dates, links, coordinates and evidence fields stay in the original
record. Review the locale text alongside any edits to the sample, especially changed source scope.
A map and a presentation brief are built from the same localized records in each language.

## Publish

After reviewing the source and preview, select **GitHub Actions** as the repository's Pages
source and manually run **Publish documentation to GitHub Pages** on `main` with the full
reviewed commit SHA. The workflow checks this SHA before building; a normal push does not deploy.
The workflow uses the Pages base URL for canonical links and the sitemap.

Check that the twelve canonical URLs and `sitemap.xml` return successful public responses.
The English pages retain their original URLs. Simplified Chinese uses `zh/`, and Japanese uses
`ja/`. Each page links to its equivalents with `hreflang`, with English as the default.
Interactive maps are supplemental assets with `noindex`. Verify crawler access using the host's effective `robots.txt` at the origin root.
For a project site under a URL path, a file named `robots.txt` within that path is not the host's
crawler policy. Submit the sitemap after verifying the site's URL prefix in Search Console.

## Check search discovery after indexing

After the task pages appear in the index, repeat the original queries without a project or owner name:

- `Japan itinerary checker Codex`
- `Japan itinerary map PowerPoint agent skill`
- `日本自由行 行程校验 AI skill`

Record whether public web results and fresh agents without the installed plugin return or cite
the project or its task pages. Keep the dated queries, results and raw traces outside the checkout.
Deployment and a submitted sitemap do not establish indexing or ranking.

## Site typography

The site uses a locally served [Manrope](https://github.com/googlefonts/manrope) variable Latin
webfont under the [SIL Open Font License](assets/manrope-OFL.txt). The original Google Fonts
[v23 WOFF2 subset](https://fonts.gstatic.com/s/manrope/v23/xn7gYHE41ni1AdIRggexSvfedN4.woff2)
is distributed with its license. The privacy checker accepts only the reviewed bytes at the
source and Pages asset paths. The font and website are separate from the skill bundle.

## Destination photographs

- `assets/kyoto-kiyomizu.jpg` comes from [Kyoto from Kiyomizu-Dera](https://commons.wikimedia.org/wiki/File:Kyoto_from_Kiyomizu-Dera.jpg)
  by Ray in Manila, licensed under [CC BY 2.0](https://creativecommons.org/licenses/by/2.0/).
- `assets/nara-park.jpg` comes from [DeerNaraJapan](https://commons.wikimedia.org/wiki/File:DeerNaraJapan.jpg)
  by Taiko, released into the public domain by its author.

The homepage uses resized copies with metadata removed and crops them to fit the layout.
The privacy checker accepts the reviewed bytes at the source and Pages asset paths.
