# Pinned Puter.js browser SDK

`puter-2.6.5.js` is the unmodified browser bundle (`dist/puter.cjs`) from
`@heyputer/puter.js@2.6.5`, fetched from the npm registry. No package install scripts
were executed. It is embedded with the app but only initialized after AI consent.

- Upstream: https://github.com/HeyPuter/puter/tree/main/src/puter-js
- Package: https://registry.npmjs.org/@heyputer/puter.js/-/puter.js-2.6.5.tgz
- Bundle SHA-256: `0e5665b9fd76839e14a56a65dd10c78f43a8d556f51b48a66f67781419d04c2d`
- Tarball SHA-256: `94aaa1efbfae0863873fd945449d8e5b5a10aa96fb5c78a06b497c5e5addebd2`
- Package integrity was verified against the registry's SHA-512 metadata.
- Copyright 2024-present Puter Technologies Inc.; Apache-2.0.
  See `licenses/PUTER.txt`.

The SDK manages the user's Puter authentication in their browser. Solvera never asks
for a pasted API key or forwards that credential to its Python server. AI requests
still require internet access to Puter and the user's own account allowance.
