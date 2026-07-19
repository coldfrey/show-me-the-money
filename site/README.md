# Site — Show Me The Money frontend

Static, dependency-free frontend (plain HTML/CSS/JS, no build step) for the
constraint-cost tracker. Designed for Cloudflare Pages with data served from
R2 under `data/` (contract: SPEC.md §8 — `data/summary.json`,
`data/daily/YYYY-MM-DD.json`).

## Local preview

```sh
uv run python site/dev/make_dev_data.py   # regenerate site/data/ from data/tracker.duckdb
python3 -m http.server 8787 -d site       # then open http://localhost:8787
```

`site/data/` is generated and gitignored. `data/dates.json` is a dev-only
manifest of available days; production works without it (the app probes daily
files by date).

Note: until the engine's Phase B (M5) per-BMU attribution ships, the
"paid to stop / paid to start" tables come from a best-effort preview
aggregate in `dev/make_dev_data.py` and are badged "preview" in the UI.
Daily and monthly headline figures are the engine's real computed numbers.
