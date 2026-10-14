# Sign Windows binaries with signtool (own certificate, e.g. Azure Artifact Signing or an OV cert in a PFX).
# Does nothing unless secrets are present. SignPath Foundation signing is done by its GitHub action instead (docs/SIGNING.md).
#   WIN_CERT_PFX_BASE64 + WIN_CERT_PASSWORD     -> signtool /f pfx
#   AZURE_SIGNING_ENDPOINT + AZURE_SIGNING_ACCOUNT + AZURE_SIGNING_PROFILE (+ azure/login OIDC) -> use azure/artifact-signing-action instead
param([Parameter(Mandatory=$true)][string[]]$Files)
if (-not $env:WIN_CERT_PFX_BASE64) { Write-Host "Windows signing secret not set: leaving files unsigned."; exit 0 }
$pfx = Join-Path $env:RUNNER_TEMP "sign.pfx"
[IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:WIN_CERT_PFX_BASE64))
$st = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin\*\x64\signtool.exe" | Sort-Object FullName -Descending | Select-Object -First 1
foreach ($f in $Files) {
  & $st.FullName sign /fd SHA256 /td SHA256 /tr "http://timestamp.digicert.com" /f $pfx /p $env:WIN_CERT_PASSWORD /d "GAC Card Scanner" $f
  if ($LASTEXITCODE) { Remove-Item $pfx; throw "signtool failed on $f" }
  & $st.FullName verify /pa $f
}
Remove-Item $pfx
