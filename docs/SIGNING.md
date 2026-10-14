# Code signing & notarization (prep)

Status: **not signed yet.** Windows installers trigger SmartScreen ("More info → Run anyway"); macOS DMGs are ad-hoc
signed and need right-click → Open. This page lists the options, what each costs, and ready-to-paste workflow steps.
All steps are **conditional on secrets being present**, so the current unsigned release keeps working until someone
sets them up. (The release workflow lives in the public repo `.github/workflows/release.yml`; it is owned by the
packaging worker, so the snippets below are proposals to paste there, not edits.)

Helper scripts in this branch (copy to `gac-public/packaging/` with the snippets):
- `packaging/macos/sign_notarize.sh` + `packaging/macos/entitlements.plist`: Developer ID sign (hardened runtime), notarize with `notarytool`, staple. No-op without secrets.
- `packaging/windows/sign.ps1`: `signtool` with a PFX certificate. No-op without secrets.

## Options at a glance (researched Oct 2026)

| Option | Platform | Cost | Who can get it | Notes |
|---|---|---|---|---|
| **SignPath Foundation** (signpath.org) | Windows (Authenticode) | **Free** for qualifying OSS | Any OSS project that passes review | Certificate is issued to *SignPath Foundation* (publisher shown = "SignPath Foundation"); key stays in their HSM; signing via their GitHub Action from a trusted build |
| **Azure Artifact Signing** (formerly Trusted Signing) | Windows | **$9.99/month** Basic (5,000 signatures; $0.005 each above) or $99.99/month Premium; paid Azure subscription required (free/trial/sponsored subscriptions not accepted) | Organizations in US/CA/EU/UK (+ AU, NZ, JP, KR, SG, CH, NO, IL); **individuals only in US/Canada**. Identity validation takes a few business days | Publisher = your org name; SmartScreen reputation still builds over time (no instant trust) |
| OV certificate from a CA | Windows | ~$200–400/yr + hardware token/cloud HSM | Organizations | Also no instant SmartScreen trust since 2024; not recommended vs. the two above |
| **Apple Developer Program** | macOS | **$99/yr** (fee waivers exist for some nonprofits/education/government orgs) | Individual or organization (org needs a D-U-N-S number) | Needed for a *Developer ID Application* certificate + notarization; removes the Gatekeeper warning |

**Recommendation:** Windows → apply to SignPath Foundation first (free). If refused, or the Chamber wants its own name as
publisher, use Azure Artifact Signing under the Chamber's organization ($9.99/mo). macOS → the Chamber (as an organization)
joins the Apple Developer Program ($99/yr; ask about the nonprofit fee waiver).

## SignPath Foundation: eligibility and how to apply

Conditions (signpath.org/terms.html), checked against this project:

| Condition | This project |
|---|---|
| OSI-approved license, no commercial dual-licensing, for all components | ✅ GPL-3.0 (`LICENSE`). Bundled: Tesseract (Apache-2.0), onnxruntime (MIT), RapidOCR/PP-OCR models (Apache-2.0), Python deps (see THIRD-PARTY-NOTICES.md) |
| No proprietary code (system libraries allowed) | ⚠️ Check: the WebView2 *bootstrapper* (Microsoft, proprietary) is downloaded into the installer; the GAC logo is a trademark (not code). Ask SignPath whether the bootstrapper counts as a system component, or download it at install time instead of bundling. The optional Qwen2.5-VL fallback (research license) is **not** bundled – keep it that way |
| No malware / PUP | ✅ |
| Actively maintained | ✅ |
| Already released in the form to be signed | ✅ v0.1.0 installers on GitHub Releases |
| Functionality described on the download page | ✅ README + release notes; make sure the README says what the app does and links Releases |
| Signing only binaries built from the repo in CI; public code-signing policy; MFA for all members; roles (authors/reviewers/approvers) | To do: add a "Code signing policy" section to the README (template in SignPath's docs), enable MFA on GitHub for everyone with write access |

Steps:
1. Prepare the repo: README "Code signing policy" section (who approves releases, "Free code signing provided by SignPath.io, certificate by SignPath Foundation"), privacy statement link (PRIVACY-NOTE.md), MFA on.
2. Apply at **https://signpath.org/apply.html** (form: repo URL, license, download URL = GitHub Releases, short description, maintainers).
3. After approval SignPath creates an organization + project; you get `organization-id`, `project-slug`, a signing policy (`test-signing` first, `release-signing` later), and create a CI user → API token.
4. Add GitHub secrets: `SIGNPATH_API_TOKEN`, `SIGNPATH_ORGANIZATION_ID`; variables `SIGNPATH_PROJECT_SLUG`, `SIGNPATH_POLICY_SLUG`.
5. Configure the artifact configuration in SignPath to sign the `.exe` files inside the PyInstaller folder **and** the Inno Setup installer (two passes, or sign the onedir before Inno and the setup after).
6. Release-signing requests need manual approval by an approver in SignPath's web UI (by design).

## Azure Artifact Signing: setup outline
1. Paid Azure subscription → register `Microsoft.CodeSigning` → create an Artifact Signing account (Basic, $9.99/mo).
2. Identity validation (Organization, Public) – legal name/address must match; a few business days.
3. Create a *Public Trust* certificate profile. Create an app registration with federated credentials for GitHub OIDC; give it the "Artifact Signing Certificate Profile Signer" role.
4. Secrets: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`; variables `AZURE_SIGNING_ENDPOINT` (e.g. `https://eus.codesigning.azure.net/`), `AZURE_SIGNING_ACCOUNT`, `AZURE_SIGNING_PROFILE`.

## Apple Developer ID + notarization: setup outline
1. Join the Apple Developer Program as the organization ($99/yr; D-U-N-S number needed).
2. Create a **Developer ID Application** certificate (Xcode → Settings → Accounts, or developer.apple.com) → export as `.p12` with a password.
3. App Store Connect → Users and Access → Integrations → **App Store Connect API key** (role Developer) → download `AuthKey_XXXX.p8`, note Key ID + Issuer ID.
4. Secrets: `MACOS_CERT_P12_BASE64` (`base64 -i cert.p12`), `MACOS_CERT_PASSWORD`, `MACOS_SIGN_IDENTITY` (e.g. `Developer ID Application: Greater Akron Chamber (TEAMID)`), `APPLE_API_KEY_BASE64`, `APPLE_API_KEY_ID`, `APPLE_API_ISSUER`.

## Proposed workflow snippets (for gac-public `.github/workflows/release.yml`)

Secrets can't be read in `if:` directly, so each job first exports a flag.

### Windows job – option A: SignPath Foundation
Insert after "PyInstaller" (signs the app exe/dlls) and again after "Inno Setup installer" (signs the setup exe):
```yaml
      - name: Signing flags
        shell: bash
        run: |
          echo "HAS_SIGNPATH=${{ secrets.SIGNPATH_API_TOKEN != '' }}" >> $GITHUB_ENV
          echo "HAS_PFX=${{ secrets.WIN_CERT_PFX_BASE64 != '' }}" >> $GITHUB_ENV
      # ... after "Inno Setup installer":
      - name: Upload unsigned installer for SignPath
        if: env.HAS_SIGNPATH == 'true'
        id: unsigned
        uses: actions/upload-artifact@v4
        with: { name: windows-unsigned, path: dist/GAC-Card-Scanner-Setup-*.exe }
      - name: Sign with SignPath Foundation
        if: env.HAS_SIGNPATH == 'true'
        uses: signpath/github-action-submit-signing-request@v1
        with:
          api-token: ${{ secrets.SIGNPATH_API_TOKEN }}
          organization-id: ${{ secrets.SIGNPATH_ORGANIZATION_ID }}
          project-slug: ${{ vars.SIGNPATH_PROJECT_SLUG }}
          signing-policy-slug: ${{ vars.SIGNPATH_POLICY_SLUG }}      # test-signing until approved, then release-signing
          artifact-configuration-slug: installer
          github-artifact-id: ${{ steps.unsigned.outputs.artifact-id }}
          wait-for-completion: true
          output-artifact-directory: dist/signed
      - name: Use signed installer
        if: env.HAS_SIGNPATH == 'true'
        shell: pwsh
        run: Copy-Item dist\signed\*.exe dist\ -Force
```
(For signing the inner `GAC Card Scanner.exe` too, do the same upload/sign round-trip on `dist/GAC Card Scanner/` right after
PyInstaller, before Inno Setup packs it.)

### Windows job – option B: Azure Artifact Signing (or a PFX)
```yaml
      - name: Azure login (OIDC)
        if: vars.AZURE_SIGNING_ACCOUNT != ''
        uses: azure/login@v2
        with: { client-id: "${{ secrets.AZURE_CLIENT_ID }}", tenant-id: "${{ secrets.AZURE_TENANT_ID }}", subscription-id: "${{ secrets.AZURE_SUBSCRIPTION_ID }}" }
      - name: Sign app with Azure Artifact Signing
        if: vars.AZURE_SIGNING_ACCOUNT != ''
        uses: azure/artifact-signing-action@v1     # formerly azure/trusted-signing-action
        with:
          endpoint: ${{ vars.AZURE_SIGNING_ENDPOINT }}
          signing-account-name: ${{ vars.AZURE_SIGNING_ACCOUNT }}
          certificate-profile-name: ${{ vars.AZURE_SIGNING_PROFILE }}
          files-folder: dist/GAC Card Scanner
          files-folder-filter: exe,dll
          file-digest: SHA256
          timestamp-rfc3161: http://timestamp.acs.microsoft.com
          timestamp-digest: SHA256
      # repeat with files-folder: dist, files-folder-filter: exe after Inno Setup
      - name: Sign with PFX (fallback)
        if: env.HAS_PFX == 'true'
        shell: pwsh
        env: { WIN_CERT_PFX_BASE64: "${{ secrets.WIN_CERT_PFX_BASE64 }}", WIN_CERT_PASSWORD: "${{ secrets.WIN_CERT_PASSWORD }}" }
        run: ./packaging/windows/sign.ps1 -Files (Get-ChildItem dist\GAC-Card-Scanner-Setup-*.exe).FullName
```
Add `permissions: id-token: write` to the workflow for OIDC.

### macOS job
Replace "Ad-hoc sign" with (ad-hoc stays as fallback):
```yaml
      - name: Ad-hoc sign (fallback)
        run: codesign --force --deep --sign - "dist/GAC Card Scanner.app"
      - name: Developer ID sign + notarize app
        env:
          MACOS_CERT_P12_BASE64: ${{ secrets.MACOS_CERT_P12_BASE64 }}
          MACOS_CERT_PASSWORD: ${{ secrets.MACOS_CERT_PASSWORD }}
          MACOS_SIGN_IDENTITY: ${{ secrets.MACOS_SIGN_IDENTITY }}
        run: bash packaging/macos/sign_notarize.sh "dist/GAC Card Scanner.app"     # no-op without secrets
```
and after "DMG":
```yaml
      - name: Sign + notarize + staple DMG
        env:
          MACOS_CERT_P12_BASE64: ${{ secrets.MACOS_CERT_P12_BASE64 }}
          MACOS_CERT_PASSWORD: ${{ secrets.MACOS_CERT_PASSWORD }}
          MACOS_SIGN_IDENTITY: ${{ secrets.MACOS_SIGN_IDENTITY }}
          APPLE_API_KEY_BASE64: ${{ secrets.APPLE_API_KEY_BASE64 }}
          APPLE_API_KEY_ID: ${{ secrets.APPLE_API_KEY_ID }}
          APPLE_API_ISSUER: ${{ secrets.APPLE_API_ISSUER }}
        run: bash packaging/macos/sign_notarize.sh "dist/GAC Card Scanner.app" "$(ls dist/*.dmg)"
```

### Version file for the update check
The in-app update check (`app/updates.py`) compares GitHub's latest release tag with the running version. In the
release workflow, before PyInstaller: `echo "$GAC_VERSION" > VERSION`, and add `("VERSION", ".")` to `datas` in
`packaging/gac.spec` (or set `GAC_VERSION` in the launcher). Done in the release workflow and spec since v0.2.0. Without it the app reports the version in the repo's VERSION file.

### Release notes text once signed
Drop "SmartScreen: More info > Run anyway" / "right-click > Open" from the `gh release create --notes` text for the signed platform.
