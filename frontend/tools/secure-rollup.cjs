'use strict'

// Rollup 4.60.2 also ships six already-bundled glob compilers. npm overrides
// don't reach those. Disallow quantified extglobs at the parser entry, before
// any enclosing repeated regexp can be emitted. Normal globs are untouched.
const fs = require('node:fs')
const path = require('node:path')
const checkOnly = process.argv.includes('--check')
const files = {
  'dist/shared/rollup.js': 1, 'dist/es/shared/node-entry.js': 1,
  'dist/shared/index.js': 2, 'dist/es/shared/watch.js': 2,
}
const entry = 'const extglobOpen = (type, value) => {'
const patched = entry + "\n\t    if (type === 'plus' || type === 'star') throw new SyntaxError('Repeated extglobs are not supported in admin build filters');"

function secureRollup() {
  let manifest
  try { manifest = require.resolve('rollup/package.json') } catch (error) {
    if (!checkOnly && error.code === 'MODULE_NOT_FOUND' && process.env.NODE_ENV === 'production') return
    throw error
  }
  if (require(manifest).version !== '4.60.2') throw new Error('Review bundled glob compilers before updating Rollup')
  for (const [filename, count] of Object.entries(files)) {
    const file = path.join(path.dirname(manifest), filename)
    const src = fs.readFileSync(file, 'utf8')
    const entries = src.split(entry).length - 1, guards = src.split(patched).length - 1
    if (entries === count && guards === count) continue
    if (checkOnly || entries !== count || guards !== 0) throw new Error('Unexpected or unprotected Rollup compiler: ' + filename)
    fs.writeFileSync(file, src.replaceAll(entry, patched))
  }
}
secureRollup()
