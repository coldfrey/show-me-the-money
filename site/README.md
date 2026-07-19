# Site — Show Me The Money frontend

Static, dependency-free frontend (plain HTML/CSS/JS, no build step) for the
constraint-cost tracker. Designed for Cloudflare Pages with data served from
R2 under `data/` (contract: SPEC.md §8 — `data/summary.json`,
`data/daily/YYYY-MM-DD.json`).

## Local preview

```sh
uv run python site/dev/build_site_data.py   # runs the engine's real exports -> site/data/
python3 -m http.server 8787 -d site         # then open http://localhost:8787
```

`build_site_data.py` runs `tracker export` + `tracker export-summary` (the real
§8 contract JSON, with genuine per-station/per-company attribution from Phase B)
and stages `out/` into `site/data/`, plus a `dates.json` local-nav manifest.

`site/data/` is generated and gitignored. Production serves the engine's `out/`
directory (synced to R2) at `/data/`; the app works without `dates.json` (it
probes daily files by date).

`dev/make_dev_data.py` is the retired preview generator (pre-M5 scaling
aggregate), kept only for reference.
