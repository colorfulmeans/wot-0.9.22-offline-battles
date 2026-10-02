param([ValidateSet('', 'A', 'B', 'C')][string]$Mode = '', [switch]$LibraryOnly, [switch]$UiSmoke)
$ErrorActionPreference = 'Stop'

function Save-DiagnosticJson {
    param([string]$Path, $Value)
    $json = $Value | ConvertTo-Json -Depth 10
    [IO.File]::WriteAllText($Path, $json, (New-Object Text.UTF8Encoding($false)))
}

function New-DiagnosticRun {
    param([string]$Root, [string]$GameRoot, [ValidateSet('A','B','C')][string]$Mode)
    if (-not (Test-Path -LiteralPath (Join-Path $GameRoot 'WorldOfTanks.exe') -PathType Leaf)) {
        throw '请选择包含 WorldOfTanks.exe 的 #1513 游戏目录，而不是启动器目录。'
    }
    $runs = Join-Path $Root 'Engine-Diagnostics'
    [IO.Directory]::CreateDirectory($runs) | Out-Null
    $id = ('{0}-{1}-{2}' -f (Get-Date -Format 'yyyyMMdd-HHmmss'), $Mode, [Guid]::NewGuid().ToString('N').Substring(0,8))
    $folder = Join-Path $runs $id
    [IO.Directory]::CreateDirectory($folder) | Out-Null
    $offsets = @{}
    foreach ($leaf in @('offline-player-python.log','offline-worker-python.log','offline-worker-starter.log')) {
        $path = Join-Path $GameRoot $leaf
        $offsets[$leaf] = if (Test-Path -LiteralPath $path -PathType Leaf) { [long](Get-Item -LiteralPath $path).Length } else { [long]0 }
    }
    $run = @{ Id=$id; Mode=$Mode; Folder=$folder; GameRoot=[IO.Path]::GetFullPath($GameRoot); Offsets=$offsets;
        StartUtc=[DateTime]::UtcNow.ToString('o'); Build='colorfulmeans-096-test8L-engine-diag-20261002-9d'; LauncherPid=$null }
    Save-DiagnosticJson (Join-Path $folder 'run.json') $run
    return $run
}

function New-DiagnosticProcessInfo {
    param([string]$Executable, [string]$WorkingDirectory, $Run)
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $Executable
    $info.WorkingDirectory = $WorkingDirectory
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $false
    # Child-only environment; no setx, registry changes or permanent mode files.
    $info.EnvironmentVariables['WOT_OFFLINE_ENGINE_DIAG_MODE'] = $Run.Mode
    $info.EnvironmentVariables['WOT_OFFLINE_ENGINE_DIAG_DIR'] = $Run.Folder
    $info.EnvironmentVariables['WOT_OFFLINE_ENGINE_DIAG_RUN'] = $Run.Id
    $info.EnvironmentVariables.Remove('WOT_OFFLINE_REPLAY_FILE')
    return $info
}

function Copy-DiagnosticDelta {
    param([string]$Source, [string]$Destination, [long]$StartOffset, [long]$Limit = 4194304)
    if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
        return @{ Status='missing'; File=[IO.Path]::GetFileName($Source) }
    }
    $item = Get-Item -LiteralPath $Source
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        return @{ Status='skipped_reparse_point'; File=$item.Name }
    }
    $share = [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete
    $src = [IO.File]::Open($Source, [IO.FileMode]::Open, [IO.FileAccess]::Read, $share)
    try {
        [long]$end = $src.Length
        $reset = $end -lt $StartOffset
        [long]$start = if ($reset) { 0 } else { $StartOffset }
        [long]$originalStart = $start
        if ($end - $start -gt $Limit) { $start = $end - $Limit }
        [void]$src.Seek($start, [IO.SeekOrigin]::Begin)
        $dst = [IO.File]::Open($Destination, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::Read)
        [long]$copied = 0
        try {
            $buffer = New-Object byte[] 65536
            while ($copied -lt ($end - $start)) {
                [int]$want = [Math]::Min([long]$buffer.Length, [long]($end - $start - $copied))
                [int]$n = $src.Read($buffer,0,$want)
                if ($n -le 0) { break }
                $dst.Write($buffer,0,$n)
                $copied += $n
            }
        } finally { $dst.Dispose() }
        return @{ Status='copied'; File=$item.Name; Start=$start; End=$end; Bytes=$copied;
                  Truncated=($start -ne $originalStart); SourceReset=$reset; ByteExact=$true }
    } finally { $src.Dispose() }
}

function Export-DiagnosticRun {
    param($Run, [string]$Note = '')
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $capture = Join-Path $Run.Folder 'captured'
    [IO.Directory]::CreateDirectory($capture) | Out-Null
    $records = @()
    foreach ($leaf in @('offline-player-python.log','offline-worker-python.log','offline-worker-starter.log')) {
        try {
            $records += Copy-DiagnosticDelta (Join-Path $Run.GameRoot $leaf) (Join-Path $capture $leaf) ([long]$Run.Offsets[$leaf])
        } catch {
            $records += @{ File=$leaf; Status='read_failed'; Error=$_.Exception.Message }
        }
    }
    $diag = @(Get-ChildItem -LiteralPath $Run.Folder -Filter 'engine-*.jsonl' -File)
    Save-DiagnosticJson (Join-Path $Run.Folder 'collection.json') @{
        Mode=$Run.Mode; Id=$Run.Id; EndUtc=[DateTime]::UtcNow.ToString('o'); Sources=$records;
        DiagnosticFiles=$diag.Count; MissingDiagnostic=($diag.Count -eq 0); UserNote=$Note;
        NoAutomaticUpload=$true; NoProfilesOrSavesCollected=$true;
        Note='Native engine sound output is not measurable from API return alone. See user audio/notes.'
    }
    $zip = Join-Path ([IO.Path]::GetDirectoryName($Run.Folder)) ('Engine-Diagnostic-{0}-{1}.zip' -f $Run.Id, [Guid]::NewGuid().ToString('N').Substring(0,6))
    $stream = [IO.File]::Open($zip, [IO.FileMode]::CreateNew)
    $archive = New-Object IO.Compression.ZipArchive($stream, [IO.Compression.ZipArchiveMode]::Create, $false)
    try {
        # Only our own run metadata, diagnostic records, and these three deltas.
        $sources = @((Get-ChildItem -LiteralPath $Run.Folder -File | Where-Object { $_.Extension -in @('.json','.jsonl','.txt') }))
        $sources += @(Get-ChildItem -LiteralPath $capture -File -Filter '*.log')
        foreach ($file in $sources) {
            if (($file.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { continue }
            $relative = $file.FullName.Substring($Run.Folder.Length).TrimStart('\','/').Replace('\','/')
            $entry = $archive.CreateEntry($relative, [IO.Compression.CompressionLevel]::Fastest)
            $input = [IO.File]::Open($file.FullName, [IO.FileMode]::Open, [IO.FileAccess]::Read, ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
            $output = $entry.Open()
            try { $input.CopyTo($output) } finally { $output.Dispose(); $input.Dispose() }
        }
    } finally { $archive.Dispose(); $stream.Dispose() }
    return @{ Path=$zip; DiagnosticFiles=$diag.Count; Records=$records }
}

if ($LibraryOnly) { return }
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$script:Root = $PSScriptRoot
$script:Launcher = Join-Path $script:Root 'wot-0.9.22-offline-battles.exe'
if (-not (Test-Path -LiteralPath $script:Launcher -PathType Leaf)) {
    [void][Windows.Forms.MessageBox]::Show('请先完整解压诊断包，脚本必须与 EXE 和 _internal 放在一起。','发动机诊断'); exit 1
}
$script:Run = $null
$script:Child = $null
$script:Notified = $false
$form = New-Object Windows.Forms.Form
$form.Text = '坦克世界 · 发动机专项诊断 R9D'
$form.ClientSize = New-Object Drawing.Size(720,410)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.Font = New-Object Drawing.Font('Microsoft YaHei UI',9)
function Label-At([string]$Text,[int]$X,[int]$Y,[int]$Width,[int]$Height) {
    $item=New-Object Windows.Forms.Label; $item.Text=$Text; $item.Location=New-Object Drawing.Point($X,$Y); $item.Size=New-Object Drawing.Size($Width,$Height); $form.Controls.Add($item); return $item
}
[void](Label-At '先关闭其他游戏和启动器。每种模式会打开同一个完整启动器，再从中开始单人战斗。' 18 12 685 26)
[void](Label-At '游戏目录（用于截取本轮日志；启动器里也请选择这个目录）：' 18 45 680 24)
$pathBox=New-Object Windows.Forms.TextBox; $pathBox.Location=New-Object Drawing.Point(18,73); $pathBox.Size=New-Object Drawing.Size(592,26); $form.Controls.Add($pathBox)
$settings=Join-Path $script:Root 'Engine-Diagnostics\panel-settings.json'
if (Test-Path -LiteralPath $settings) { try { $pathBox.Text=(Get-Content -Raw -LiteralPath $settings | ConvertFrom-Json).GameRoot } catch {} }
$browse=New-Object Windows.Forms.Button; $browse.Text='选择…';$browse.Location=New-Object Drawing.Point(620,71);$browse.Size=New-Object Drawing.Size(82,28);$form.Controls.Add($browse)
$browse.Add_Click({ $dialog=New-Object Windows.Forms.FolderBrowserDialog; $dialog.Description='选择包含 WorldOfTanks.exe 的 #1513 游戏目录'; try { if ($dialog.ShowDialog() -eq 'OK') { $pathBox.Text=$dialog.SelectedPath } } finally { $dialog.Dispose() } })
$script:Buttons=@()
foreach ($row in @(@('A','A：当前R8路径＋采集',113), @('B','B：本车／初始友军改为原生回调直连',155), @('C','C：仅取消额外 attachToModel 调用',197))) {
    $button=New-Object Windows.Forms.Button; $button.Tag=$row[0]; $button.Text=$row[1]; $button.Location=New-Object Drawing.Point(18,[int]$row[2]);$button.Size=New-Object Drawing.Size(684,34);$form.Controls.Add($button);$script:Buttons += $button
    $button.Add_Click({
        try {
            if ($script:Child -and -not $script:Child.HasExited) { throw '请先退出上一轮游戏和启动器，再切换诊断模式。' }
            if (@(Get-Process -Name WorldOfTanks -ErrorAction SilentlyContinue).Count -gt 0) { throw '仍检测到游戏客户端。请先手动退出，诊断工具不会强制结束进程。' }
            $script:Run=New-DiagnosticRun $script:Root $pathBox.Text ([string]$this.Tag)
            Save-DiagnosticJson $settings @{ GameRoot=$script:Run.GameRoot }
            $info=New-DiagnosticProcessInfo $script:Launcher $script:Root $script:Run
            $script:Child=New-Object Diagnostics.Process; $script:Child.StartInfo=$info
            if (-not $script:Child.Start()) { throw '启动器未能启动。' }
            $script:Run.LauncherPid=$script:Child.Id
            Save-DiagnosticJson (Join-Path $script:Run.Folder 'run.json') $script:Run
            $script:Notified=$false
            foreach ($b in $script:Buttons) { $b.Enabled=$false }
            $status.Text='模式 '+$script:Run.Mode+' 已启动。请测约一分钟，退出游戏和本轮启动器后打包。'
            $note.Text='本车：；友军：；敌军：；炮声：；大致测试时间：'
        } catch { [void][Windows.Forms.MessageBox]::Show($_.Exception.Message,'启动失败') }
    })
}
[void](Label-At '听感记录（填写有声／无声；不自动录音）：' 18 242 680 22)
$note=New-Object Windows.Forms.TextBox;$note.Location=New-Object Drawing.Point(18,267);$note.Size=New-Object Drawing.Size(684,26);$form.Controls.Add($note)
$export=New-Object Windows.Forms.Button;$export.Text='打包本轮日志';$export.Location=New-Object Drawing.Point(18,309);$export.Size=New-Object Drawing.Size(180,34);$form.Controls.Add($export)
$export.Add_Click({
    try {
        if ($null -eq $script:Run) { throw '请先通过A、B或C启动一轮诊断。' }
        $result=Export-DiagnosticRun $script:Run $note.Text
        $status.Text='已保存：'+[IO.Path]::GetFileName($result.Path)
        $message='日志已保存到 Engine-Diagnostics 文件夹。没有自动上传。'
        if ($result.DiagnosticFiles -eq 0) { $message+=' 未发现发动机专项记录：可能尚未进入游戏，或环境参数未到达客户端。请仍保留这个ZIP。' }
        [void][Windows.Forms.MessageBox]::Show($message,'日志收集')
        Start-Process explorer.exe -ArgumentList ('/select,"'+$result.Path+'"') | Out-Null
    } catch { [void][Windows.Forms.MessageBox]::Show($_.Exception.Message,'收集失败') }
})
$open=New-Object Windows.Forms.Button;$open.Text='打开结果文件夹';$open.Location=New-Object Drawing.Point(216,309);$open.Size=New-Object Drawing.Size(180,34);$form.Controls.Add($open)
$open.Add_Click({ $folder=Join-Path $script:Root 'Engine-Diagnostics';[IO.Directory]::CreateDirectory($folder)|Out-Null;Start-Process explorer.exe -ArgumentList ('"'+$folder+'"')|Out-Null })
$status=Label-At '请选择A开始。诊断不修改车辆参数、不强制播放声音、不取消隐藏敌车静音。' 18 354 684 46
$timer=New-Object Windows.Forms.Timer;$timer.Interval=1000
$timer.Add_Tick({
    if ($script:Child -and $script:Child.HasExited -and -not $script:Notified) {
        $script:Notified=$true
        foreach ($b in $script:Buttons) { $b.Enabled=$true }
        $status.Text='本轮启动器已关闭。请填写听感并点“打包本轮日志”，然后再开下一模式。'
    }
})
$timer.Start()
$form.Add_FormClosing({
    if ($script:Child -and -not $script:Child.HasExited) {
        $answer=[Windows.Forms.MessageBox]::Show('本轮启动器仍在运行。关闭诊断面板不会关闭游戏，原始专项日志仍保留。确定关闭？','关闭面板','YesNo')
        if ($answer -ne 'Yes') { $_.Cancel=$true }
    }
})
$form.Add_FormClosed({ $timer.Stop();$timer.Dispose() })
if ($Mode) { $form.Add_Shown({ $selected=$script:Buttons | Where-Object { $_.Tag -eq $Mode }; if ($pathBox.Text -and $selected) { $selected.PerformClick() } }) }
if ($UiSmoke) {
    $form.CreateControl()
    if ($script:Buttons.Count -ne 3 -or $form.Controls.Count -lt 10) { throw 'Diagnostic panel did not construct correctly' }
    $timer.Stop(); $timer.Dispose(); $form.Dispose()
    Write-Output 'UI construction smoke passed; no game was started.'
    return
}
[void]$form.ShowDialog()
$form.Dispose()
