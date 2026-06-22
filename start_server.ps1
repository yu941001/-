Set-Location $PSScriptRoot
$env:OPENAI_API_KEY = [Environment]::GetEnvironmentVariable('OPENAI_API_KEY', 'User')
$env:LLM_MODEL = 'gpt-4.1-mini'
& "$PSScriptRoot\.venv\Scripts\python.exe" "$PSScriptRoot\app.py"
