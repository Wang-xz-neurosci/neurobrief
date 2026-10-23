param([string]$Repository = 'Wang-xz-neurosci/neurobrief')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$site = Get-Content -LiteralPath 'config/site.json' -Raw | ConvertFrom-Json
if ($Repository -ne $site.repository) { throw 'Repository must match config/site.json.' }
$expectedOwner = $Repository.Split('/')[0]
$ghCommand = Get-Command gh -ErrorAction SilentlyContinue
$gh = if ($ghCommand) { $ghCommand.Source } else { Join-Path $projectRoot '.tools/gh/gh.exe' }
if (-not (Test-Path -LiteralPath $gh)) { throw 'Install GitHub CLI and run gh auth login first.' }

function Invoke-Gh {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
    $result = & $gh @Arguments
    if ($LASTEXITCODE -ne 0) { throw "GitHub command failed: $($Arguments[0])" }
    return $result
}
function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
    & git @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Git command failed: $($Arguments[0])" }
}

$account = (Invoke-Gh api user) | ConvertFrom-Json
if ($account.login -ine $expectedOwner) { throw "Logged in as $($account.login); expected $expectedOwner." }

$remoteInfo = & $gh api "repos/$Repository" 2>$null
$exists = $LASTEXITCODE -eq 0
if ($exists) {
    $repo = $remoteInfo | ConvertFrom-Json
    if ($repo.private) { throw 'Existing repository is private; refusing to change its visibility.' }
    if (-not (Test-Path -LiteralPath '.git')) {
        throw 'Repository already exists. Inspect or clone it before publishing; no remote history was overwritten.'
    }
} else {
    # Distinguish a genuine 404 from network/permission errors before mutation.
    $response = & $gh api --include "repos/$Repository" 2>&1 | Out-String
    if ($response -notmatch '404') { throw "Cannot verify repository availability: $response" }
}

if (-not (Test-Path -LiteralPath '.git')) { Invoke-Git init --initial-branch=main }
$actualRoot = (& git rev-parse --show-toplevel).Trim()
if ([IO.Path]::GetFullPath($actualRoot) -ne [IO.Path]::GetFullPath($projectRoot)) { throw 'Unexpected Git root.' }
$branch = (& git branch --show-current).Trim()
if ($branch -ne 'main') { throw 'Expected the main branch; refusing to switch existing work.' }
Invoke-Git config user.name $account.login
Invoke-Git config user.email "$($account.id)+$($account.login)@users.noreply.github.com"

if (-not $exists) {
    Invoke-Gh repo create $Repository --public --description '认知神经科学文献观察：语言与大脑、结构与功能、脑疾病机理、静息态与自然刺激'
}
$remote = & git remote get-url origin 2>$null
if ($LASTEXITCODE -eq 0) {
    if ($remote.Trim() -notin @("https://github.com/$Repository.git", "https://github.com/$Repository")) { throw 'Unexpected origin; refusing to replace it.' }
} else {
    Invoke-Git remote add origin "https://github.com/$Repository.git"
}
Invoke-Git add dist config scripts tests .github .gitignore README.md
& git diff --cached --quiet
$hasChanges = $LASTEXITCODE -ne 0
if ($hasChanges) { Invoke-Git commit -m 'Publish NeuroBrief with four neuroscience research topics' }

# Scope git authentication to this invocation; do not edit global Git settings.
$helper = '!' + ($gh -replace '\\','/') + ' auth git-credential'
Invoke-Git -c http.version=HTTP/1.1 -c 'credential.helper=' -c "credential.https://github.com.helper=$helper" push --set-upstream origin main

$pages = & $gh api "repos/$Repository/pages" 2>$null
if ($LASTEXITCODE -ne 0) {
    Invoke-Gh api --method POST "repos/$Repository/pages" -f build_type=workflow
} else {
    Invoke-Gh api --method PUT "repos/$Repository/pages" -f build_type=workflow
}
if (-not $hasChanges) { Invoke-Gh workflow run daily-update.yml --repo $Repository --ref main }
Write-Host "Requested deployment. Verify the update and deploy jobs: https://github.com/$Repository/actions"
Write-Host "Expected website after successful deployment: $($site.url)"
