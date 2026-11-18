'use strict'

const { Minimatch } = require('minimatch')

// Vite, unplugin, fdir and tinyglobby use a matcher factory; tinyglobby and
// Vite also use scan() for the literal search root and unexpanded path parts.
// Preserve slashes in grouped alternatives; splitting a brace expansion into
// independent path segments would cause tinyglobby to prune a matching tree.
function segments(pattern) {
  const parts = [], stack = []
  let start = 0
  for (let i = 0; i < pattern.length; i++) {
    const c = pattern[i], end = stack.at(-1)
    if (c === '\\') { i++; continue }
    if (end && c === end) { stack.pop(); continue }
    if (end === ']') continue
    if ((c === '+' || c === '*') && pattern[i + 1] === '(') {
      throw new SyntaxError('Repeated extglobs are not supported in admin build filters')
    }
    if (c === '[') stack.push(']')
    else if (c === '{') stack.push('}')
    else if (c === '(') stack.push(')')
    else if (c === '/' && !stack.length) { parts.push(pattern.slice(start, i)); start = i + 1 }
  }
  parts.push(pattern.slice(start))
  return parts
}

const trimPrefix = s => s.startsWith('./') ? s.slice(2) : s

function optionsFor(pattern, opts) {
  return {
    platform: 'linux', nocomment: true, magicalBraces: true,
    dot: opts.dot, nocase: opts.nocase, nobrace: opts.nobrace, noglobstar: opts.noglobstar,
    nonegate: opts.nonegate || pattern.startsWith('!('), noext: opts.noext || opts.noextglob,
    matchBase: opts.basename || opts.matchBase,
  }
}

function buildGlob(patterns, opts = {}) {
  const matchers = (Array.isArray(patterns) ? patterns : [patterns]).map(pattern => {
    segments(pattern)
    const p = trimPrefix(pattern)
    const matcher = new Minimatch(p, optionsFor(p, opts))
    // tinyglobby appends "/**" even to a filename: the suffix also means
    // zero descendants. minimatch needs a trailing separator for that case.
    const trailingTree = !opts.noglobstar && p.endsWith('/**')
    return path => matcher.match(trailingTree && !path.endsWith('/') ? path + '/' : path)
  })
  const windows = opts.windows ?? process.platform === 'win32'
  return input => {
    if (!input) return false
    const path = trimPrefix(windows ? input.replaceAll('\\', '/') : input)
    return matchers.some(matches => matches(path))
  }
}

buildGlob.scan = (pattern, opts = {}) => {
  const negated = !opts.nonegate && pattern.startsWith('!') && !pattern.startsWith('!(')
  const plain = trimPrefix(negated ? pattern.slice(1) : pattern)
  const parts = segments(plain)
  const options = { ...optionsFor(plain, opts), nonegate: true }
  const magic = parts.findIndex(part => new Minimatch(part, options).hasMagic())
  const base = magic < 0 ? plain : parts.slice(0, magic).join('/') || (plain.startsWith('/') ? '/' : '')
  return { isGlob: magic >= 0, negated, base, ...(opts.parts ? { parts } : {}) }
}

module.exports = buildGlob
