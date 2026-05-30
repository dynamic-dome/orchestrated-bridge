# Isolierter Vertragsbeweis: OpenAI researcher-Adapter gegen ECHTEN Provider.
#
# Ruft den Adapter direkt auf (Payload via stdin), OHNE orchestrate() — damit es
# KEINEN Fallback-Pfad gibt, der einen gescheiterten echten Call grün färben könnte.
# Siehe docs/adr/0001-isolierter-adapter-call-als-vertragsbeweis.md
#
# Key-Quelle (in dieser Reihenfolge):
#   1. $env:OPENAI_API_KEY, falls in der Session gesetzt.
#   2. -KeyFile <pfad>, eine Textdatei mit NUR dem Key (z.B. Desktop\openai_key.txt).
# Der Key wird nur in die Prozess-Env dieses Laufs geladen, nie ausgegeben.
#
# Nutzung:
#   .\eval\contract-proof\prove_openai_researcher.ps1 -KeyFile "$env:USERPROFILE\Desktop\openai_key.txt"
#   # oder, wenn der Key schon in der Session steht:
#   .\eval\contract-proof\prove_openai_researcher.ps1

param(
    [string]$KeyFile = ""
)

$ErrorActionPreference = "Stop"

# --- Key aus Datei laden, falls Env leer und -KeyFile gegeben ---------------
if (-not $env:OPENAI_API_KEY -and $KeyFile) {
    if (-not (Test-Path $KeyFile)) {
        Write-Host "STOP: KeyFile nicht gefunden: $KeyFile" -ForegroundColor Red
        exit 2
    }
    $env:OPENAI_API_KEY = (Get-Content -Raw $KeyFile).Trim()
}

# --- Pfade relativ zum Skript auflösen -------------------------------------
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$PayloadPath = Join-Path $ScriptDir "researcher_payload.json"
$ProofPath   = Join-Path $ScriptDir "PROOF.json"
$RawOutPath  = Join-Path $ScriptDir "last_stdout.json"

# --- Preflight --------------------------------------------------------------
if (-not $env:OPENAI_API_KEY) {
    Write-Host "STOP: `$env:OPENAI_API_KEY ist nicht gesetzt." -ForegroundColor Red
    Write-Host 'Setze ihn nur in dieser Session:  $env:OPENAI_API_KEY = "sk-..."'
    exit 2
}
if (-not (Test-Path $PayloadPath)) {
    Write-Host "STOP: Payload nicht gefunden: $PayloadPath" -ForegroundColor Red
    exit 2
}

# Python aus dem venv bevorzugen, sonst PATH (Windows-Subprocess-Regel §10.1)
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $Python = $VenvPython
} else {
    $Python = (Get-Command python -ErrorAction Stop).Source
}

$ModelLabel = if ($env:ORCHESTRATED_LOOP_OPENAI_MODEL) { $env:ORCHESTRATED_LOOP_OPENAI_MODEL } else { "gpt-5 (default)" }
Write-Host "=== OpenAI researcher Vertragsbeweis (isoliert) ===" -ForegroundColor Cyan
Write-Host "Python : $Python"
Write-Host "Modell : $ModelLabel"
Write-Host "Payload: $PayloadPath"
Write-Host ""

# --- Adapter isoliert aufrufen (stdin -> stdout) ----------------------------
Push-Location $ProjectRoot
$started = Get-Date
try {
    $stdout = Get-Content -Raw $PayloadPath | & $Python -m orchestrated_loop.provider_adapters.openai_researcher 2>&1
    $exitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
$durationMs = [int]((Get-Date) - $started).TotalMilliseconds

# stdout kann bei Fehler Fehlertext (stderr gemergt) enthalten
$stdout | Out-File -FilePath $RawOutPath -Encoding utf8

if ($exitCode -ne 0) {
    Write-Host "FAIL: Adapter exit $exitCode (kein echter Vertragsbeweis)." -ForegroundColor Red
    Write-Host "Ausgabe:" -ForegroundColor Yellow
    Write-Host $stdout
    $proof = [ordered]@{
        verified     = $false
        reason       = "adapter exited with $exitCode"
        duration_ms  = $durationMs
        raw_output   = "$RawOutPath"
    }
    ($proof | ConvertTo-Json -Depth 5) | Out-File -FilePath $ProofPath -Encoding utf8
    exit 1
}

# --- Output gegen ROLE_REQUIRED_KEYS validieren -----------------------------
# researcher-Vertrag: answer, findings, citations, open_questions
$required = @("answer", "findings", "citations", "open_questions")
try {
    $result = $stdout | ConvertFrom-Json
} catch {
    Write-Host "FAIL: stdout war kein gültiges JSON." -ForegroundColor Red
    Write-Host $stdout
    exit 1
}

$missing = @()
foreach ($key in $required) {
    if (-not ($result.PSObject.Properties.Name -contains $key)) { $missing += $key }
}

$hasFallback = $false
if ($result.PSObject.Properties.Name -contains "adapter") {
    if ($result.adapter.PSObject.Properties.Name -contains "fallback_from") { $hasFallback = $true }
}
$answerEmpty = [string]::IsNullOrWhiteSpace([string]$result.answer)
$providerName = if ($result.PSObject.Properties.Name -contains "provider") { $result.provider.name } else { $null }

# --- Verdikt ----------------------------------------------------------------
$verified = ($missing.Count -eq 0) -and (-not $hasFallback) -and (-not $answerEmpty) -and ($providerName -eq "openai")

$proof = [ordered]@{
    verified        = $verified
    duration_ms     = $durationMs
    provider        = $providerName
    response_id     = if ($result.PSObject.Properties.Name -contains "provider") { $result.provider.response_id } else { $null }
    model           = if ($result.PSObject.Properties.Name -contains "provider") { $result.provider.model } else { $null }
    missing_keys    = $missing
    fallback_used   = $hasFallback
    answer_present  = (-not $answerEmpty)
    answer_preview  = if (-not $answerEmpty) { ([string]$result.answer).Substring(0, [Math]::Min(160, ([string]$result.answer).Length)) } else { "" }
    findings_count  = @($result.findings).Count
    citations_count = @($result.citations).Count
    raw_output      = "$RawOutPath"
}
($proof | ConvertTo-Json -Depth 5) | Out-File -FilePath $ProofPath -Encoding utf8

Write-Host ""
if ($verified) {
    Write-Host "PASS: Vertrag erfüllt durch ECHTEN OpenAI-Call." -ForegroundColor Green
    Write-Host "  provider=$providerName  model=$($proof.model)  response_id=$($proof.response_id)"
    Write-Host "  findings=$($proof.findings_count)  citations=$($proof.citations_count)  ${durationMs}ms"
    Write-Host "  Beweis: $ProofPath"
    exit 0
} else {
    Write-Host "FAIL: Vertrag NICHT bewiesen." -ForegroundColor Red
    if ($missing.Count -gt 0) { Write-Host "  fehlende Keys: $($missing -join ', ')" }
    if ($hasFallback)         { Write-Host "  -> Fallback auf lokal: echter Provider wurde NICHT verifiziert!" -ForegroundColor Yellow }
    if ($answerEmpty)         { Write-Host "  -> answer leer" }
    if ($providerName -ne "openai") { Write-Host "  -> provider != openai (war: $providerName)" }
    Write-Host "  Beweis: $ProofPath"
    exit 1
}
