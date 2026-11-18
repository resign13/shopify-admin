# Admin build path matching

The registry version of picomatch is not installed. The lockfile redirects Vite,
tinyglobby, fdir and unplugin to this private build-only package, which uses
minimatch 11.0.9 for file matching. The adapter implements the matcher and scan
fields used by those consumers; it is not a general-purpose picomatch replacement.
Repeated extglobs are not used by the admin build and are explicitly rejected.
Ordinary wildcards, globstars and brace alternatives remain available.

Rollup 4.60.2 embeds another six parser copies in its CommonJS/ESM build and
watch distributions. The install hook guards those parser entries before they
compile a repeated extglob. The build checks that the guard is installed.
Review the guard when changing the locked Rollup version. Remove the temporary
adapter and guard once both the registry package and Rollup's embedded copies
have a verified upstream fix for GHSA-fc5q-39xc-vjpf.

The existing npm audit threshold is unchanged; no advisory or dependency is
excluded. Neither the matcher nor the install script is shipped with the
production dashboard assets.
