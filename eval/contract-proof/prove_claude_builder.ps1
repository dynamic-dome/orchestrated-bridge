# Isolierter Vertragsbeweis: Claude-Code builder-Adapter gegen ECHTE claude-CLI.
#
# Ruft den Adapter direkt auf (Payload via stdin), OHNE orchestrate() — kein Fallback,
# der einen gescheiterten echten Call grün färben könnte (ADR 0001).
#
# Der Adapter nutzt KEINEN API-Key, sondern startet einen verschachtelten
# `claude -p --print --output-format json`-Lauf (echte Tokens!). Auth kommt aus
# deiner lokalen claude-CLI-Anmeldung.
#
# Modi:
#   -Fake   : nutzt eine lokale Fake-CLI (KEINE Tokens) — verifiziert nur die Mechanik.
#   (default): echter claude-Lauf.
#
# Nutzung:
#   .\eval\contract-proof\prove_claude_builder.ps1 -Fake     # mechanik-check, kostenlos
#   .\eval\contract-proof\prove_claude_builder.ps1           # echter Lauf, kostet Tokens

param(
    [switch]$Fake
)

$ErrorActionPreference = "Stop"

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$PayloadPath = Join-Path $ScriptDir "builder_payload.json"
# Getrennte Senke pro Modus: ein Fake-Lauf darf einen Real-Beweis nicht ueberschreiben (ADR 0004).
$ProofName   = if ($Fake) { "PROOF_CLAUDE_fake.json" } else { "PROOF_CLAUDE.json" }
$ProofPath   = Join-Path $ScriptDir $ProofName
$RawOutName  = if ($Fake) { "last_stdout_claude_fake.json" } else { "last_stdout_claude.json" }
$RawOutPath  = Join-Path $ScriptDir $RawOutName

if (-not (Test-Path $PayloadPath)) {
    Write-Host "STOP: Payload nicht gefunden: $PayloadPath" -ForegroundColor Red
    exit 2
}

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) { $VenvPython } else { (Get-Command python -ErrorAction Stop).Source }

# --- Fake-CLI vorbereiten, falls -Fake --------------------------------------
if ($Fake) {
    $FakeCli = Join-Path $ScriptDir "_fake_claude.py"
    # Eine Fake-CLI, die den builder-Vertrag als Claude-Code-JSON ({"result": "<rollen-json>"}) liefert.
    $fakeBody = @'
import json, sys
sys.stdin.read()
role_json = json.dumps({
    "changes": [{"file": "sample.py", "diff": "+\"\"\"Sample module.\"\"\""}],
    "logs": "fake builder run",
    "test_results": {"passed": 0, "failed": 0, "details": []},
    "artifacts": [],
    "tasks_completed": [],
    "research_used": "module docstring definition",
})
print(json.dumps({"result": role_json}), end="")
'@
    Set-Content -Path $FakeCli -Value $fakeBody -Encoding utf8
    $env:ORCHESTRATED_LOOP_CLAUDE_COMMAND = (ConvertTo-Json @($Python, $FakeCli) -Compress)
    Write-Host "MODUS: FAKE-CLI (keine Tokens)" -ForegroundColor Yellow
} else {
    # Echter Lauf: Adapter löst `claude` über PATH auf.
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

# --- builder-Vertrag validieren ---------------------------------------------
$required = @("changes", "logs", "test_results", "artifacts", "tasks_completed", "research_used")
try { $result = $stdout | ConvertFrom-Json } catch {
    Write-Host "FAIL: stdout war kein gültiges JSON." -ForegroundColor Red
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
    changes_count    = @($result.changes).Count
    raw_output       = "$RawOutPath"
}
($proof | ConvertTo-Json -Depth 5) | Out-File -FilePath $ProofPath -Encoding utf8

Write-Host ""
if ($verified) {
    Write-Host "PASS: builder-Vertrag erfüllt ($($proof.mode))." -ForegroundColor Green
    Write-Host "  provider=$providerName  changes=$($proof.changes_count)  ${durationMs}ms"
    Write-Host "  Beweis: $ProofPath"
    exit 0
} else {
    Write-Host "FAIL: builder-Vertrag NICHT bewiesen." -ForegroundColor Red
    if ($missing.Count -gt 0) { Write-Host "  fehlende Keys: $($missing -join ', ')" }
    if ($hasFallback)         { Write-Host "  -> Fallback auf lokal!" -ForegroundColor Yellow }
    exit 1
}
