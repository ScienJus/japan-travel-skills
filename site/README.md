# Product site

The GitHub Pages build combines a product homepage, the two task guides in `docs/`, and the
public Kyoto–Nara example rendered with the planner's existing helper. Site build dependencies are separate from the plugin.

## Build and review

From the source checkout, use a Python 3.10+ development environment:

```bash
python -m pip install -r site/requirements.txt
python scripts/build_docs_site.py --output /absolute/new/path/outside-the-checkout/site
```

Open `index.html` from the output directory or serve the directory with a local HTTP server.
Check the navigation, both articles, the embedded and standalone demo, and the mobile layout.
The build scans the output for private data. Keep previews and generated artifacts outside the
repository. The plugin ZIP does not include the site build or its dependencies.

## Publish

After reviewing the source and preview, select **GitHub Actions** as the repository's Pages
source and manually run **Publish documentation to GitHub Pages** on `main` with the full
reviewed commit SHA. The workflow checks this SHA before building; a normal push does not deploy.
The workflow uses the Pages base URL for canonical links and the sitemap.

Check that the three canonical URLs and `sitemap.xml` return successful public responses.
The three documentation pages are indexable HTML; the interactive demo is a supplemental asset with
`noindex`. Verify crawler access using the host's effective `robots.txt` at the origin root.
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

The display typeface is [Fraunces](https://github.com/undercasetype/Fraunces), served as two
Google Fonts v38 Latin WOFF2 subsets under the [SIL Open Font License](assets/fraunces-OFL.txt).

## Homepage artwork

`assets/railway-poster.jpg` is a generated screenprint-style illustration of an imagined rail
journey in Japan. Only the reviewed,
metadata-stripped web asset is published. The illustration is separate from the skill bundle.
