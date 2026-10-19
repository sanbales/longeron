# Vendored: `elk.bundled.js`

`longeron.render` lays diagrams out headlessly with elkjs in a node
subprocess. This file is `lib/elk.bundled.js` of the npm package, unchanged.
Keep its version equal to the elkjs that ipyelk bundles for the browser, so
both pipelines run the same layout engine.

| package | version | license | file sha256 |
|---|---|---|---|
| [elkjs](https://github.com/kieler/elkjs) | 0.12.0 | EPL-2.0 OR GPL-3.0-or-later | `1222e44f953ce7746af23801e723708f8e6f436b8b377a6a5fc7552f34a307b3` |

npm tarball integrity: `sha512-YZcKynxVxYoKIOEpywEPwCFdg+BTbxQRNf3pbwdDCvc8O3kQD8bmIwSxKU1eOTVc4Xo+VG9Te+575mlfvOrhEQ==`.

Update (any machine with npm):

```sh
npm pack elkjs@0.12.0
tar xzf elkjs-0.12.0.tgz package/lib/elk.bundled.js
cp package/lib/elk.bundled.js src/longeron/_js/elk.bundled.js
shasum -a 256 src/longeron/_js/elk.bundled.js  # record it in the table above
```
