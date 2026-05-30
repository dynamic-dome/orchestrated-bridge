# Isolierter Vertragsbeweis: Claude-Code judge-Adapter gegen ECHTE claude-CLI.
#
# Ruft den Adapter direkt auf (Payload via stdin), OHNE orchestrate() — kein Fallback,
# der einen gescheiterten echten Call gruen faerben koennte (ADR 0001).
#
# Schreibt in eine GETRENNTE Beweisdatei (PROOF_CLAUDE_JUDGE.json), damit ein
# Fake-Lauf einen vorhandenen Real-Beweis nicht ueberschreibt.
#
# Modi:
#   -Fake   : nutzt eine lokale Fake-CLI (KEINE Tokens) — verifiziert nur die Mechanik.
#   (default): echter claude-Lauf (kostet Tokens, laeuft ueber das lokale Abo).
#
# Nutzung:
#   .\eval\contract-proof\prove_claude_judge.ps1 -Fake     # mechanik-check, kostenlos
#   .\eval\contract-proof\prove_claude_judge.ps1           # echter Lauf, kostet Tokens

param(
    [switch]$Fake
)

$ErrorActionPreference = "Stop"

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$PayloadPath = Join-Path $ScriptDir "judge_payload.json"
$ProofName   = if ($Fake) { "PROOF_CLAUDE_JUDGE_fake.json" } else { "PROOF_CLAUDE_JUDGE.json" }
$ProofPath   = Join-Path $ScriptDir $ProofName
$RawOutName  = if ($Fake) { "last_stdout_claude_judge_fake.json" } else { "last_stdout_claude_judge.json" }
$RawOutPath  = Join-Path $ScriptDir $RawOutName

if (-not (Test-Path $PayloadPath)) {
    Write-Host "STOP: Payload nicht gefunden: $PayloadPath" -ForegroundColor Red
    exit 2
}

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) { $VenvPython } else { (Get-Command python -ErrorAction Stop).Source }

# --- Fake-CLI vorbereiten, falls -Fake --------------------------------------
if ($Fake) {
    $FakeCli = Join-Path $ScriptDir "_fake_claude_judge.py"
    $fakeBody = @'
import json, sys
sys.stdin.read()
role_json = json.dumps({
    "scores": {"planning": 1.0, "implementation": 0.92, "review": 0.88, "operability": 0.86},
    "overall": 0.91,
    "fail_reasons": [],
    "blocking": False,
    "next_actions": [],
})
print(json.dumps({"result": role_json}), end="")
'@
    Set-Content -Path $FakeCli -Value $fakeBody -Encoding utf8
    $env:ORCHESTRATED_LOOP_CLAUDE_COMMAND = (ConvertTo-Json @($Python, $FakeCli) -Compress)
    Write-Host "MODUS: FAKE-CLI (keine Tokens)" -ForegroundColor Yellow
} else {
    Write-Host "MODUS: ECHTER claude-Lauf (kostet Tokens)" -ForegroundColor Cyan
    $claude = Get-Command claude -ErrorAction SilentlyContinue
    if (-not $claude) {
        Write-Host "STOP: 'claude' nicht auf PATH gefunden." -ForegroundColor Red
        exit 2
    }
    Write-Host "claude: $($claude.Source)"
}

# --- Adapter isoliert aufrufen ---------------------------------------------
Push-Location $ProjectRoot
$started = Get-Date
try {
    $stdout = Get-Content -Raw $PayloadPath | & $Python -m orchestrated_loop.provider_adapters.claude_code_role 2>&1
    $exitCode = $LASTEXITCODE
} finally {
    Pop-Location
    if ($Fake) { Remove-Item Env:\ORCHESTRATED_LOOP_CLAUDE_COMMAND -ErrorAction SilentlyContinue }
}
$durationMs = [int]((Get-Date) - $started).TotalMilliseconds
$stdout | Out-File -FilePath $RawOutPath -Encoding utf8

if ($exitCode -ne 0) {
    Write-Host "FAIL: Adapter exit $exitCode." -ForegroundColor Red
    Write-Host $stdout
    @{ verified = $false; reason = "adapter exit $exitCode"; duration_ms = $durationMs } |
        ConvertTo-Json | Out-File -FilePath $ProofPath -Encoding utf8
    exit 1
}

# --- judge-Vertrag validieren -----------------------------------------------
$required = @("scores", "overall", "fail_reasons", "blocking", "next_actions")
try { $result = $stdout | ConvertFrom-Json } catch {
    Write-Host "FAIL: stdout war kein gueltiges JSON." -ForegroundColor Red
    Write-Host $stdout
    exit 1
}

$missing = @()
foreach ($key in $required) { if (-not ($result.PSObject.Properties.Name -contains $key)) { $missing += $key } }
$hasFallback = $false
if ($result.PSObject.Properties.Name -contains "adapter") {
    if ($result.adapter.PSObject.Properties.Name -contains "fallback_from") { $hasFallback = $true }
}
$providerName = if ($result.PSObject.Properties.Name -contains "provider") { $result.provider.name } else { $null }

$verified = ($missing.Count -eq 0) -and (-not $hasFallback)

$proof = [ordered]@{
    verified         = $verified
    mode             = if ($Fake) { "fake" } else { "real" }
    duration_ms      = $durationMs
    provider         = $providerName
    missing_keys     = $missing
    fallback_used    = $hasFallback
    overall          = $result.overall
    blocking         = $result.blocking
    raw_output       = "$RawOutPath"
}
($proof | ConvertTo-Json -Depth 5) | Out-File -FilePath $ProofPath -Encoding utf8

Write-Host ""
if ($verified) {
    Write-Host "PASS: judge-Vertrag erfuellt ($($proof.mode))." -ForegroundColor Green
    Write-Host "  provider=$providerName  overall=$($result.overall)  blocking=$($result.blocking)  ${durationMs}ms"
    Write-Host "  Beweis: $ProofPath"
    exit 0
} else {
    Write-Host "FAIL: judge-Vertrag NICHT bewiesen." -ForegroundColor Red
    if ($missing.Count -gt 0) { Write-Host "  fehlende Keys: $($missing -join ', ')" }
    if ($hasFallback)         { Write-Host "  -> Fallback auf lokal!" -ForegroundColor Yellow }
    exit 1
}
