$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$version = '0.41.0'
$expectedSha256 = '99811FA17D8D14C64C5F35A230D8F77FAAB63AAA85097F67D272F781E677C252'
$cache = Join-Path $env:LOCALAPPDATA 'Temp\opencode\RadioPlusPlus-mpv-0.41.0'
$package = Join-Path $cache 'libmpv.zip'
$dll = Join-Path $cache 'build\x64\libmpv-2.dll'

if (-not (Test-Path $dll)) {
    New-Item -ItemType Directory -Force -Path $cache | Out-Null
    Invoke-WebRequest -Uri "https://api.nuget.org/v3-flatcontainer/endpne.libmpv.windows/$version/endpne.libmpv.windows.$version.nupkg" -OutFile $package
    if ((Get-FileHash $package -Algorithm SHA256).Hash -ne $expectedSha256) {
        throw 'El paquete mpv descargado no coincide con la versión verificada.'
    }
    Expand-Archive -Path $package -DestinationPath $cache -Force
}
if (-not (Test-Path $dll)) { throw 'No se encontró libmpv-2.dll en el paquete descargado.' }

python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name RadioPlusPlus-Qt-v10 --icon (Join-Path $root 'resources\icons\default\radio-original.ico') `
    --add-data "$(Join-Path $root 'resources');resources" `
    --collect-submodules yt_dlp --copy-metadata yt-dlp --hidden-import unicodedata `
    --exclude-module requests --exclude-module urllib3 --exclude-module curl_cffi `
    --add-binary "$dll;." (Join-Path $root 'app.py')
if ($LASTEXITCODE -ne 0) { throw 'No se pudo generar el ejecutable.' }
Write-Host "Listo: $(Join-Path $root 'dist\RadioPlusPlus-Qt-v10.exe')"
