'use strict'
const test = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')
const { execFileSync } = require('node:child_process')
const match = require('picomatch')
const { globSync } = require('tinyglobby')
const root = path.resolve(__dirname, '..')

test('all installed build consumers resolve the minimatch adapter', () => {
  assert.equal(require('picomatch/package.json').name, '@gingtto/build-glob')
  assert.equal(require('minimatch/package.json').version, '11.0.9')
  for (const name of ['vite', 'tinyglobby', 'fdir', 'unplugin', 'unplugin-utils', 'unplugin-vue-components']) {
    const parent = path.dirname(require.resolve(name))
    assert.equal(require(require.resolve('picomatch', { paths: [parent] })), match, name)
  }
})

test('file matching retains braces, globstars, negation, dot-file protection and Windows paths', () => {
  const vue = match(['**/*.{vue,ts}', 'index.html'], { windows: true })
  assert.equal(vue('src\\views\\DashboardView.vue'), true)
  assert.equal(vue('src/.hidden/view.ts'), false)
  assert.equal(vue('index.html'), true)
  assert.equal(match('!**/*.map')('assets/a.js.map'), false)
  assert.equal(match('src/@(views|components)/*.vue')('src/views/DashboardView.vue'), true)
  assert.equal(match([])('index.html'), false)
  const denied = match(['**/.env', '**/.env.*', '**/.git/**', '**/*.{crt,pem}'], { dot: true, nocase: true })
  for (const f of ['.env', 'src/.env.local', '.git/config', 'keys/CERT.PEM']) assert.equal(denied(f), true, f)
  assert.equal(denied('src/views/DashboardView.vue'), false)
})

test('Vite scan roots and tinyglobby directory pruning work with the real Vue source tree', () => {
  assert.deepEqual(match.scan('!./src/{views/panel,components/row}/**/*.vue', { parts:true }),
    { isGlob:true, negated:true, base:'src', parts:['src','{views/panel,components/row}','**','*.vue'] })
  assert.equal(match.scan('/src/views/DashboardView.vue').base, '/src/views/DashboardView.vue')
  assert.deepEqual(globSync('./src/{views,components}/**/DashboardView.vue', { cwd:root }), ['src/views/DashboardView.vue'])
  assert.ok(!globSync('src/views/*View.vue', {cwd:root, ignore:['**/Dashboard*']}).includes('src/views/DashboardView.vue'))
})

test('unsupported quantified groups are rejected before compilation, including in the installed Rollup parsers', () => {
  // A harmless literal group checks the policy; no timing or adversarial input.
  assert.throws(() => match('+(unit).js'), /Repeated extglobs/)
  assert.throws(() => match.scan('*(unit).js'), /Repeated extglobs/)
  execFileSync(process.execPath, ['tools/secure-rollup.cjs', '--check'], { cwd:root })
})
