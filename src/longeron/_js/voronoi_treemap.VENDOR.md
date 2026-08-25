# Vendored: `voronoi_treemap.bundled.js`

The Voronoi tessellation of the requirements scoreboard widget
(`longeron.analysis.scoreboard`) uses Kcnarf's d3-voronoi-treemap plugin.
It and its dependency closure are bundled here as ONE minified IIFE
exposing the global `lgnVoronoi` (`voronoiTreemap`, `hierarchy`), so the
widget's ESM stays a single self-contained module with no CDN imports.

Rebuild (any machine with node + npm):

```sh
npm install d3-voronoi-treemap@1.1.2 d3-hierarchy@3.1.2 esbuild
cat > entry.js <<'EOF'
export { voronoiTreemap } from "d3-voronoi-treemap";
export { hierarchy } from "d3-hierarchy";
EOF
npx esbuild entry.js --bundle --format=iife --global-name=lgnVoronoi \
    --minify --outfile=voronoi_treemap.bundled.js
```

## Bundled packages and licenses (all permissive: BSD-3-Clause / ISC)

| package | version | license | copyright |
|---|---|---|---|
| [d3-voronoi-treemap](https://github.com/Kcnarf/d3-voronoi-treemap) | 1.1.2 | BSD-3-Clause | Kcnarf |
| [d3-voronoi-map](https://github.com/Kcnarf/d3-voronoi-map) | 2.1.1 | BSD-3-Clause | Kcnarf |
| [d3-weighted-voronoi](https://github.com/Kcnarf/d3-weighted-voronoi) | 1.1.3 | BSD-3-Clause | Kcnarf |
| [d3-hierarchy](https://github.com/d3/d3-hierarchy) | 3.1.2 | ISC | Mike Bostock |
| [d3-array](https://github.com/d3/d3-array) | 2.12.1 | BSD-3-Clause | Mike Bostock |
| [d3-polygon](https://github.com/d3/d3-polygon) | 2.0.0 | BSD-3-Clause | Mike Bostock |
| [d3-timer](https://github.com/d3/d3-timer) | 2.0.0 | BSD-3-Clause | Mike Bostock |
| [d3-dispatch](https://github.com/d3/d3-dispatch) | 2.0.0 | BSD-3-Clause | Mike Bostock |
| [internmap](https://github.com/mbostock/internmap) | 1.0.1 | ISC | Mike Bostock |

License texts ship with the upstream packages; the bundle header records
the same table. All licenses permit redistribution in binary/bundled form
with attribution, which this note and the bundle header provide.
