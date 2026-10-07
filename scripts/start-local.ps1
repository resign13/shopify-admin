param(
    [string]$Python = 'python',
    [ValidateRange(1024, 65535)][int]$Port = 5004
)

$ErrorActionPreference = 'Stop'
$backend = Join-Path (Split-Path -Parent $PSScriptRoot) 'admin-backend'
# Manual validation always uses the locally synchronized production snapshot.
# Regression tests override their own isolated *_test database separately.
$env:PGHOST = '127.0.0.1'
$env:PGPORT = '55439'
$env:PGDATABASE = 'lumiere_admin'
Push-Location $backend
try {
    & $Python -c "import db; c=db._connect(); assert db.DB_HOST=='127.0.0.1' and db.DB_PORT==55439 and db.DB_NAME=='lumiere_admin'; assert c.execute('SELECT COUNT(*) AS n FROM admin_users').fetchone()['n']>0, 'Sync the local production snapshot first'; c.close()"
    if ($LASTEXITCODE -ne 0) { throw 'Local mirror validation failed; no server started.' }
    # Daily sync also migrates the active feature before replacing the mirror.
    # Keep the existing sync script/automation in its original checkout.
    $registryDirectory = Join-Path $env:USERPROFILE '.codex/private/gingtto-db-sync'
    New-Item -ItemType Directory -Path $registryDirectory -Force | Out-Null
    $backends = @($backend)
    $storeBackend = Join-Path (Split-Path -Parent (Split-Path -Parent $backend)) 'shopify/storefront-backend'
    if (Test-Path -LiteralPath (Join-Path $storeBackend 'app.py')) { $backends += $storeBackend }
    ConvertTo-Json -InputObject $backends | Set-Content -LiteralPath (Join-Path $registryDirectory 'local-manual-backends.json') -Encoding UTF8
    Write-Host "Local manual validation: http://127.0.0.1:$Port (lumiere_admin mirror)"
    & $Python -c "from app import app; app.run(debug=False,use_reloader=False,host='127.0.0.1',port=$Port)"
    if ($LASTEXITCODE -ne 0) { throw 'Local server exited with an error.' }
} finally {
    Pop-Location
}
