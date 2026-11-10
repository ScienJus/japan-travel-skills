# Documentation site

The GitHub Pages build reuses the two task guides in `docs/` and renders the public Kyoto–Nara
example with the planner's existing helper. Site build dependencies are separate from the plugin.

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

## Site photography

`assets/kyoto-evening.jpg` is a resized copy of
[Kiyomizudera-Niomon-2017-Luka-Peternel.jpg](https://commons.wikimedia.org/wiki/File:Kiyomizudera-Niomon-2017-Luka-Peternel.jpg)
by Luka Peternel, licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
The homepage crops the image to fit the display and applies a contrast overlay. The photograph
retains its own license. The privacy checker recognizes its reviewed checksum at the source and
Pages asset paths. Review the source, license and metadata again if replacing the image.
