Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$requirementsFile = Join-Path $projectRoot 'requirements.txt'
$importScript = Join-Path $projectRoot 'import_products.py'
$crawlerScript = Join-Path $projectRoot 'safe_crawler.py'
$trainScript = Join-Path $projectRoot 'train_model.py'
$startServerScript = Join-Path $projectRoot 'start_server.ps1'

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Title,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Action
    )

    Write-Host "`n=== $Title ===" -ForegroundColor Cyan
    & $Action
}

Invoke-Step -Title 'Prepare virtual environment' -Action {
    if (-not (Test-Path $venvPython)) {
        Write-Host 'No .venv found. Creating virtual environment...'

        if (Get-Command py -ErrorAction SilentlyContinue) {
            & py -3 -m venv .venv
        }
        elseif (Get-Command python -ErrorAction SilentlyContinue) {
            & python -m venv .venv
        }
        else {
            throw 'Cannot find py or python. Failed to create virtual environment.'
        }

        if (-not (Test-Path $venvPython)) {
            throw 'Virtual environment creation failed: .venv\Scripts\python.exe not found.'
        }
    }
    else {
        Write-Host 'Existing .venv detected.'
    }
}

Invoke-Step -Title 'Install or update dependencies' -Action {
    if (Test-Path $requirementsFile) {
        & $venvPython -m pip install --upgrade pip
        & $venvPython -m pip install -r $requirementsFile
    }
    else {
        Write-Host 'requirements.txt not found. Skipping dependency install.' -ForegroundColor Yellow
    }
}

Invoke-Step -Title 'Import product data' -Action {
    if (-not (Test-Path $importScript)) {
        throw 'import_products.py not found.'
    }
    & $venvPython $importScript
}

Invoke-Step -Title 'Run seasonal crawler' -Action {
    if (-not (Test-Path $crawlerScript)) {
        throw 'safe_crawler.py not found.'
    }
    & $venvPython $crawlerScript
}

Invoke-Step -Title 'Train Random Forest model' -Action {
    if (-not (Test-Path $trainScript)) {
        throw 'train_model.py not found.'
    }
    & $venvPython $trainScript
}

Invoke-Step -Title 'Start web server' -Action {
    if (-not (Test-Path $startServerScript)) {
        throw 'start_server.ps1 not found.'
    }

    Write-Host 'Server will now start and keep running. Press Ctrl+C to stop.' -ForegroundColor Green
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $startServerScript
}
