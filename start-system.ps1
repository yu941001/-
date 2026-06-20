$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = 'C:/Users/lsp10/AppData/Roaming/uv/python/cpython-3.14.6-windows-x86_64-none/python.exe'

Set-Location $projectRoot
Start-Process 'http://127.0.0.1:5000/'
& $python (Join-Path $projectRoot 'app.py')
