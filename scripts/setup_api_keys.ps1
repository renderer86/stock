param(
    [switch]$IncludeFutureKrx
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Read-SecretText {
    param([Parameter(Mandatory = $true)][string]$Prompt)

    $secure = Read-Host -Prompt $Prompt -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $projectRoot ".env"

if (Test-Path -LiteralPath $envPath) {
    $answer = Read-Host ".env 파일이 이미 있습니다. 덮어쓸까요? [y/N]"
    if ($answer -notmatch "^(?i:y|yes)$") {
        Write-Host "취소했습니다."
        exit 0
    }
}

$ecosKey = Read-SecretText "한국은행 ECOS API 키"
$dartKey = Read-SecretText "OpenDART API 키"
if ([string]::IsNullOrWhiteSpace($ecosKey) -or [string]::IsNullOrWhiteSpace($dartKey)) {
    throw "ECOS_API_KEY와 DART_API_KEY는 비워둘 수 없습니다."
}

$lines = @(
    "# 이 파일은 Git에서 제외됩니다. 외부에 공유하지 마세요."
    "ECOS_API_KEY=$ecosKey"
    "DART_API_KEY=$dartKey"
)

if ($IncludeFutureKrx) {
    $krxId = Read-Host "KRX 계정 ID (향후 공매도 수집용)"
    $krxPassword = Read-SecretText "KRX 계정 비밀번호 (향후 공매도 수집용)"
    $lines += "KRX_ID=$krxId"
    $lines += "KRX_PW=$krxPassword"
}

[IO.File]::WriteAllLines(
    $envPath,
    $lines,
    [Text.UTF8Encoding]::new($false)
)

Write-Host ".env 파일을 만들었습니다: $envPath"
Write-Host "키 값은 화면에 출력하지 않았고 Git 커밋 대상에서도 제외됩니다."
