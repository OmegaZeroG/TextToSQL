<#
Local dev helper. Run from the repo root:

  .\scripts\local.ps1 backend     start the API (seeds the database first if it is empty)
  .\scripts\local.ps1 frontend    start the React dev server
  .\scripts\local.ps1 test        run the pytest suite
  .\scripts\local.ps1 eval        run the live golden-query eval (the backend must be running)

Add -Port 8010 to use a different API port.

DATABASE_URL comes from .env. If this PC's DNS cannot resolve the database host
(some routers refuse *.neon.tech names), the host is looked up through Cloudflare
(1.1.1.1) and the connection goes by IP address. This applies to this process only;
no system or network setting is changed.
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("backend", "frontend", "test", "eval")]
    [string]$Task,
    [int]$Port = 8000
)

$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root ".venv\Scripts\python.exe"

function Set-DatabaseUrl {
    $line = Get-Content (Join-Path $root ".env") | Where-Object { $_ -like "DATABASE_URL=*" } | Select-Object -First 1
    if (-not $line) { throw "DATABASE_URL is not set in .env" }
    $url = $line -replace "^DATABASE_URL=", ""

    if ($url -match "@([^/:?]+)") { $dbHost = $Matches[1] } else { throw "Could not read the host from DATABASE_URL" }

    $resolvable = $true
    try { [void][System.Net.Dns]::GetHostAddresses($dbHost) } catch { $resolvable = $false }

    if ($resolvable) {
        Write-Host "Database host $dbHost resolves normally."
    }
    elseif ($url -match "hostaddr=") {
        Write-Host "Database host $dbHost does not resolve; using the hostaddr already in DATABASE_URL."
    }
    else {
        $record = Resolve-DnsName $dbHost -Type A -Server 1.1.1.1 -DnsOnly -ErrorAction SilentlyContinue |
            Where-Object { $_.IPAddress } | Select-Object -First 1
        if (-not $record) { throw "Could not resolve $dbHost through this PC's DNS or through 1.1.1.1" }
        $separator = if ($url -match "\?") { "&" } else { "?" }
        $url = "$url${separator}hostaddr=$($record.IPAddress)"
        Write-Host "Your DNS cannot resolve $dbHost; connecting by IP $($record.IPAddress) for this session only."
    }
    $env:DATABASE_URL = $url
}

switch ($Task) {
    "backend" {
        Set-DatabaseUrl
        & $python (Join-Path $root "data\seed.py") --if-empty
        Set-Location (Join-Path $root "backend")
        Write-Host "API starting on http://localhost:$Port  (interactive docs: http://localhost:$Port/docs)"
        & $python -m uvicorn app.main:app --port $Port
    }
    "frontend" {
        $env:VITE_API_URL = "http://localhost:$Port"
        Set-Location (Join-Path $root "frontend")
        Write-Host "Frontend will call the API at $env:VITE_API_URL"
        npm run dev
    }
    "test" {
        Set-DatabaseUrl
        Set-Location (Join-Path $root "backend")
        & $python -m pytest -q -rs
        exit $LASTEXITCODE
    }
    "eval" {
        Set-DatabaseUrl
        Set-Location $root
        & $python (Join-Path $root "eval\run_eval.py") --api-url "http://localhost:$Port"
        exit $LASTEXITCODE
    }
}
