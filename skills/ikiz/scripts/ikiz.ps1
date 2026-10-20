<#
.SYNOPSIS
  Ikiz protokolu icin cocuk Claude Code ajani calistirici (Windows / PowerShell 5.1+).

.DESCRIPTION
  Gorev dosyasini stdin ile "claude -p" surecine verir, JSON sonucu dosyaya yazar.
  Derinlik kilidi, zaman asimi, git worktree izolasyonu ve paralel calistirma icerir.

.EXAMPLE
  # Tek cocuk, salt-okunur plan
  .\ikiz.ps1 -Gorev .ikiz\kazan\gorev.md -Cikti .ikiz\kazan\plan-B.json

.EXAMPLE
  # Yazan cocuk, izole worktree'de
  .\ikiz.ps1 -Gorev .ikiz\kazan\uygula.md -Cikti .ikiz\kazan\uygula-B.json -Yaz -Worktree

.EXAMPLE
  # Fan-out: klasordeki her *.md bir cocuk
  .\ikiz.ps1 -GorevKlasoru .ikiz\kesif -CiktiKlasoru .ikiz\kesif\sonuc -Paralel 3
#>
[CmdletBinding(DefaultParameterSetName = 'Tek')]
param(
    [Parameter(Mandatory, ParameterSetName = 'Tek')]
    [string]$Gorev,

    [Parameter(ParameterSetName = 'Tek')]
    [string]$Cikti,

    [Parameter(Mandatory, ParameterSetName = 'Toplu')]
    [string]$GorevKlasoru,

    [Parameter(Mandatory, ParameterSetName = 'Toplu')]
    [string]$CiktiKlasoru,

    [Parameter(ParameterSetName = 'Toplu')]
    [ValidateRange(1, 6)]
    [int]$Paralel = 2,

    # Cocuk ajan varsayilani OPUS: ikiz protokolu hatasi pahali isler icindir,
    # ikinci gorusun ucuz modelden gelmesi protokolun amacini bozar.
    # Tam model kimligi kullan. Kisa alias ("opus"/"sonnet") sessizce yok sayilabilir
    # - bkz. references/komut-sozlugu.md Tuzak 1.
    [string]$Model = 'claude-opus-5',

    [string]$Araclar = 'Read,Grep,Glob',

    [string]$Repo = (Get-Location).Path,

    # Yazma araclarini acar (Edit/Write/Bash + acceptEdits).
    [switch]$Yaz,

    # Cocugu izole bir git worktree'de calistirir ve diff uretir. -Yaz ile kullanilir.
    [switch]$Worktree,

    [string]$Dal,

    [ValidateRange(30, 7200)]
    [int]$Zaman = 900,

    # --json-schema icin JSON semasi (string).
    [string]$Sema,

    [string]$SistemEki = 'Sadece istenen ciktiyi ver, fazladan aciklama yazma. Commit/push/merge yapma. Delege etme, alt ajan baslatma.'
)

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------- yardimcilar

function Get-ClaudeExe {
    $cmd = Get-Command claude -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($aday in @(
            (Join-Path $env:USERPROFILE '.local\bin\claude.exe'),
            (Join-Path $env:LOCALAPPDATA 'Programs\claude\claude.exe'),
            (Join-Path $env:APPDATA 'npm\claude.cmd'))) {
        if (Test-Path $aday) { return $aday }
    }
    throw "claude CLI bulunamadi. PATH'e ekle veya tam yolu bu fonksiyona yaz."
}

function Assert-Derinlik {
    $d = $env:CLAUDE_IKIZ_DERINLIK
    if ($d -and ([int]$d) -ge 1) {
        throw "DERINLIK KILIDI: CLAUDE_IKIZ_DERINLIK=$d. Sen zaten bir cocuk ajansin; delege etme, isi kendin yap."
    }
}

function New-IkizWorktree {
    param([string]$RepoYolu, [string]$DalAdi)

    $kok = (& git -C $RepoYolu rev-parse --show-toplevel 2>$null)
    if ($LASTEXITCODE -ne 0) { throw "git deposu degil: $RepoYolu (worktree kullanilamaz)" }
    $kok = $kok.Trim()

    $hedef = Join-Path (Split-Path $kok -Parent) ((Split-Path $kok -Leaf) + '-ikiz-B')
    if (Test-Path $hedef) {
        Write-Host "[ikiz] mevcut worktree kullaniliyor: $hedef" -ForegroundColor DarkYellow
        return $hedef
    }

    & git -C $kok worktree add -b $DalAdi $hedef | Out-Null
    if ($LASTEXITCODE -ne 0) {
        # dal zaten varsa dalsiz dene
        & git -C $kok worktree add $hedef | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "worktree olusturulamadi: $hedef" }
    }
    Write-Host "[ikiz] worktree hazir: $hedef (dal: $DalAdi)" -ForegroundColor Green
    return $hedef
}

function Get-WorktreeDiff {
    param([string]$Yol, [string]$CiktiDosyasi)
    # -N: izlenmeyen dosyalar da diff'e girsin
    & git -C $Yol add -A -N 2>$null | Out-Null
    $d = & git -C $Yol diff
    if ($null -eq $d) { $d = '' }
    Set-Content -Path $CiktiDosyasi -Value $d -Encoding UTF8
    return $CiktiDosyasi
}

function Build-Arguments {
    param([string]$CalismaDizini)

    $a = @('-p', '--output-format', 'json', '--model', $Model)

    if ($Yaz) {
        $araclar = if ($Araclar -eq 'Read,Grep,Glob') { 'Read,Grep,Glob,Edit,Write,Bash' } else { $Araclar }
        $a += @('--tools', $araclar, '--permission-mode', 'acceptEdits')
    }
    else {
        $a += @('--tools', $Araclar)
    }

    # git yazma yollari her zaman kapali
    $a += @('--disallowedTools', '"Bash(git commit:*),Bash(git push:*),Bash(git merge:*),Bash(git rebase:*)"')

    $a += @('--add-dir', ('"' + $CalismaDizini + '"'))
    $a += @('--append-system-prompt', ('"' + ($SistemEki -replace '"', "'") + '"'))

    if ($Sema) { $a += @('--json-schema', ('"' + ($Sema -replace '"', '\"') + '"')) }

    return $a
}

function Invoke-Cocuk {
    param(
        [string]$GorevDosyasi,
        [string]$CiktiDosyasi,
        [string]$CalismaDizini,
        [switch]$Bekle
    )

    $hataDosyasi = [IO.Path]::ChangeExtension($CiktiDosyasi, '.err.txt')
    $argv = Build-Arguments -CalismaDizini $CalismaDizini

    $p = Start-Process -FilePath (Get-ClaudeExe) `
        -ArgumentList $argv `
        -WorkingDirectory $CalismaDizini `
        -RedirectStandardInput $GorevDosyasi `
        -RedirectStandardOutput $CiktiDosyasi `
        -RedirectStandardError $hataDosyasi `
        -NoNewWindow -PassThru

    if ($Bekle) { return (Wait-Cocuk -Surec $p -CiktiDosyasi $CiktiDosyasi) }
    return $p
}

function Wait-Cocuk {
    param([System.Diagnostics.Process]$Surec, [string]$CiktiDosyasi)

    if (-not $Surec.WaitForExit($Zaman * 1000)) {
        try { $Surec.Kill() } catch {}
        Write-Warning "[ikiz] ZAMAN ASIMI ($Zaman sn) -> $CiktiDosyasi"
        return [pscustomobject]@{ Dosya = $CiktiDosyasi; Basarili = $false; Sebep = 'zaman-asimi'; Maliyet = 0 }
    }
    return (Test-Sonuc -CiktiDosyasi $CiktiDosyasi -CikisKodu $Surec.ExitCode)
}

function Test-Sonuc {
    param([string]$CiktiDosyasi, [int]$CikisKodu)

    $sonuc = [pscustomobject]@{ Dosya = $CiktiDosyasi; Basarili = $false; Sebep = ''; Maliyet = 0; Sure = 0 }

    if ($CikisKodu -ne 0) { $sonuc.Sebep = "cikis-kodu=$CikisKodu"; return $sonuc }
    if (-not (Test-Path $CiktiDosyasi)) { $sonuc.Sebep = 'cikti-yok'; return $sonuc }

    try { $j = Get-Content $CiktiDosyasi -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { $sonuc.Sebep = 'json-ayristirilamadi'; return $sonuc }

    $sonuc.Maliyet = $j.total_cost_usd
    $sonuc.Sure = $j.duration_ms

    if ($j.is_error) { $sonuc.Sebep = 'is_error=true'; return $sonuc }
    if (-not $j.result) { $sonuc.Sebep = 'bos-sonuc'; return $sonuc }
    if ($j.permission_denials -and $j.permission_denials.Count -gt 0) {
        # is yarim kalmis olabilir - basarili sayma, uyar
        $sonuc.Sebep = "izin-reddi=$($j.permission_denials.Count)"
        return $sonuc
    }

    $sonuc.Basarili = $true
    return $sonuc
}

# ---------------------------------------------------------------------- akis

Assert-Derinlik
$env:CLAUDE_IKIZ_DERINLIK = '1'   # cocuk miras alir

$calisma = (Resolve-Path $Repo).Path

if ($Worktree) {
    if (-not $Yaz) { Write-Warning "[ikiz] -Worktree genelde -Yaz ile anlamlidir." }
    if (-not $Dal) { $Dal = 'ikiz/' + (Get-Date -Format 'yyyyMMdd-HHmm') }
    $calisma = New-IkizWorktree -RepoYolu $calisma -DalAdi $Dal
}

if ($PSCmdlet.ParameterSetName -eq 'Tek') {

    if (-not (Test-Path $Gorev)) { throw "gorev dosyasi yok: $Gorev" }
    if (-not $Cikti) { $Cikti = [IO.Path]::ChangeExtension((Resolve-Path $Gorev).Path, '.sonuc.json') }
    $ciktiDizin = Split-Path $Cikti -Parent
    if ($ciktiDizin -and -not (Test-Path $ciktiDizin)) { New-Item -ItemType Directory -Path $ciktiDizin -Force | Out-Null }

    Write-Host "[ikiz] cocuk basliyor: $Gorev (model=$Model, calisma=$calisma)" -ForegroundColor Cyan
    $r = Invoke-Cocuk -GorevDosyasi (Resolve-Path $Gorev).Path -CiktiDosyasi $Cikti -CalismaDizini $calisma -Bekle

    if ($Worktree) {
        $diff = Get-WorktreeDiff -Yol $calisma -CiktiDosyasi ([IO.Path]::ChangeExtension($Cikti, '.patch'))
        Write-Host "[ikiz] diff: $diff" -ForegroundColor Green
        Write-Host "[ikiz] worktree SILINMEDI: $calisma  (temizlik: git worktree remove '$calisma')" -ForegroundColor DarkYellow
    }

    if ($r.Basarili) {
        Write-Host ("[ikiz] TAMAM  sure={0}ms  maliyet=`${1}" -f $r.Sure, $r.Maliyet) -ForegroundColor Green
    }
    else {
        Write-Warning ("[ikiz] BASARISIZ ({0}) -> {1}" -f $r.Sebep, $Cikti)
        exit 1
    }
}
else {

    if (-not (Test-Path $GorevKlasoru)) { throw "gorev klasoru yok: $GorevKlasoru" }
    if (-not (Test-Path $CiktiKlasoru)) { New-Item -ItemType Directory -Path $CiktiKlasoru -Force | Out-Null }

    $gorevler = @(Get-ChildItem -Path $GorevKlasoru -Filter '*.md' -File | Sort-Object Name)
    if ($gorevler.Count -eq 0) { throw "gorev klasorunde *.md yok: $GorevKlasoru" }

    Write-Host "[ikiz] $($gorevler.Count) gorev, en fazla $Paralel es zamanli" -ForegroundColor Cyan

    $calisanlar = @()
    $sonuclar = @()

    foreach ($g in $gorevler) {
        while (@($calisanlar | Where-Object { -not $_.Surec.HasExited }).Count -ge $Paralel) {
            Start-Sleep -Milliseconds 400
        }
        $out = Join-Path $CiktiKlasoru ($g.BaseName + '.json')
        Write-Host "  -> $($g.Name)" -ForegroundColor DarkCyan
        $p = Invoke-Cocuk -GorevDosyasi $g.FullName -CiktiDosyasi $out -CalismaDizini $calisma
        $calisanlar += [pscustomobject]@{ Ad = $g.BaseName; Surec = $p; Cikti = $out }
    }

    foreach ($c in $calisanlar) {
        $r = Wait-Cocuk -Surec $c.Surec -CiktiDosyasi $c.Cikti
        $sonuclar += [pscustomobject]@{
            gorev = $c.Ad; cikti = $c.Cikti; basarili = $r.Basarili
            sebep = $r.Sebep; maliyet_usd = $r.Maliyet; sure_ms = $r.Sure
        }
    }

    $ozet = Join-Path $CiktiKlasoru '_ozet.json'
    $sonuclar | ConvertTo-Json -Depth 5 | Set-Content -Path $ozet -Encoding UTF8

    $ok = @($sonuclar | Where-Object { $_.basarili }).Count
    $toplam = ($sonuclar | Measure-Object -Property maliyet_usd -Sum).Sum
    Write-Host ("[ikiz] {0}/{1} basarili  toplam maliyet=`${2}  ozet={3}" -f $ok, $sonuclar.Count, $toplam, $ozet) -ForegroundColor Green
    $sonuclar | Where-Object { -not $_.basarili } | ForEach-Object { Write-Warning ("  BASARISIZ {0}: {1}" -f $_.gorev, $_.sebep) }
    if ($ok -lt $sonuclar.Count) { exit 1 }
}
