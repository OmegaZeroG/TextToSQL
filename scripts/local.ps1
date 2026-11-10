<#
Local dev helper. Run from the repo root:

  .\scripts\local.ps1 backend     start the API
  .\scripts\local.ps1 frontend    start the React dev server
  .\scripts\local.ps1 test        run the backend pytest suite
  .\scripts\local.ps1 eval        run the live golden-query eval (the backend must be running)

Add -Port 8010 to use a different API port.

The only configuration needed is GROQ_API_KEY in .env (see .env.example).
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("backend", "frontend", "test", "eval")]
    [string]$Task,
    [int]$Port = 8000
)

$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root ".venv\Scripts\python.exe"

switch ($Task) {
    "backend" {
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
        Set-Location (Join-Path $root "backend")
        & $python -m pytest -q -rs
        exit $LASTEXITCODE
    }
    "eval" {
        Set-Location $root
        & $python (Join-Path $root "eval\run_eval.py") --api-url "http://localhost:$Port"
        exit $LASTEXITCODE
    }
}
