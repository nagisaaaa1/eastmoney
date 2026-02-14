param(
    [string]$ApiKey
)

if (-not $ApiKey) {
    Write-Host "Usage: .\\scripts\\run_backend_qwen.ps1 -ApiKey <DASHSCOPE_API_KEY>"
    exit 1
}

$env:LLM_PROVIDER = "qwen"
$env:OPENAI_API_KEY = $ApiKey
$env:OPENAI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
$env:OPENAI_MODEL = "qwen-plus"

py -3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
