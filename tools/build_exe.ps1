# 打包「智慧赛场」为单文件 exe（输出到 release\SmartArena.exe）
# 用法： powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1
$ErrorActionPreference = "Continue"
Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "[1/2] 安装依赖 ..." -ForegroundColor Cyan
py -m pip install --disable-pip-version-check -r requirements.txt -r requirements-build.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "依赖安装失败，请检查网络或 Python 环境。" -ForegroundColor Red
    exit 1
}

Write-Host "[2/2] 开始打包 ..." -ForegroundColor Cyan
py -m PyInstaller --noconfirm --clean --distpath release --workpath build SmartArena.spec
if ($LASTEXITCODE -ne 0) {
    Write-Host "打包失败。" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "打包完成！exe 位于： release\SmartArena.exe" -ForegroundColor Green