from pathlib import Path
import hashlib
out=Path('r9d2-panel');out.mkdir(exist_ok=True)
s=Path('tools/engine_diagnostics_r9d/Engine-Diagnostics.ps1').read_text(encoding='utf-8-sig')
s=s.replace("'', 'A', 'B', 'C'", "'', 'A', 'B', 'C', 'D'").replace("'A','B','C'", "'A','B','C','D'")
s=s.replace('colorfulmeans-096-test8L-engine-diag-20261002-9d', 'colorfulmeans-096-test8L-engine-diag-20261002-9d2')
s=s.replace("发动机专项诊断 R9D'", "发动机专项诊断 R9D2'")
pos=s.index('function Export-DiagnosticRun {')
s=s[:pos]+'''function Get-DiagnosticHealth {
    param([string]$Path)
    $state = @{ File=[IO.Path]::GetFileName($Path); Rows=0; Samples=0; SessionStart=$false;
        SessionEnd=$false; WriterEnd=$false; ParseErrors=0; RecordErrors=0; Limit=$false;
        Dropped=0; NormalizedFields=0; LastWallTime=$null; Complete=$false; HasSamples=$false }
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read,
              ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
    $reader = New-Object IO.StreamReader($stream, (New-Object Text.UTF8Encoding($false,$true)))
    try {
        while (-not $reader.EndOfStream) {
            $line = $reader.ReadLine()
            if ([String]::IsNullOrWhiteSpace($line)) { continue }
            $state.Rows++
            try {
                $row = $line | ConvertFrom-Json
                if ($null -ne $row.wall_time) { $state.LastWallTime=$row.wall_time }
                switch ($row.kind) {
                    'sample' { $state.Samples++ }
                    'session_start' { $state.SessionStart=$true }
                    'session_end' { $state.SessionEnd=$true }
                    'record_error' { $state.RecordErrors++ }
                    'log_limit_reached' { $state.Limit=$true }
                    'writer_end' {
                        $state.WriterEnd=$true
                        $state.Dropped=[long]$row.dropped_records
                        $state.Limit=$state.Limit -or [bool]$row.limit
                        $state.NormalizedFields=[long]$row.normalized_fields
                        $state.RecordErrors=[Math]::Max([long]$state.RecordErrors,[long]$row.record_errors)
                    }
                }
            } catch { $state.ParseErrors++ }
        }
    } catch { $state.ReadError=$_.Exception.Message }
    finally { $reader.Dispose(); $stream.Dispose() }
    $state.HasSamples=$state.Samples -gt 0
    $state.Complete=$state.SessionStart -and $state.SessionEnd -and $state.WriterEnd -and
        ($state.ParseErrors -eq 0) -and ($state.RecordErrors -eq 0) -and
        ($state.Dropped -eq 0) -and (-not $state.Limit) -and (-not $state.ContainsKey('ReadError'))
    return $state
}

''' + s[pos:]
s=s.replace("    Save-DiagnosticJson (Join-Path $Run.Folder 'collection.json') @{", "    $health = @($diag | ForEach-Object { Get-DiagnosticHealth $_.FullName })\n    $incomplete = @($health | Where-Object { (-not $_.Complete) -or (-not $_.HasSamples) })\n    Save-DiagnosticJson (Join-Path $Run.Folder 'collection.json') @{")
s=s.replace("        NoAutomaticUpload=$true; NoProfilesOrSavesCollected=$true;", "        DiagnosticHealth=$health; IncompleteDiagnostic=($incomplete.Count -gt 0 -or $diag.Count -eq 0);\n        NoAutomaticUpload=$true; NoProfilesOrSavesCollected=$true;")
s=s.replace("return @{ Path=$zip; DiagnosticFiles=$diag.Count; Records=$records }", "return @{ Path=$zip; DiagnosticFiles=$diag.Count; Records=$records; Health=$health; Incomplete=($incomplete.Count -gt 0 -or $diag.Count -eq 0) }")
s=s.replace("Drawing.Size(720,410)", "Drawing.Size(720,465)")
s=s.replace("@('B','B：本车／初始友军改为原生回调直连',155)", "@('B','B：本车／友军原生直连，显形后仍保持直连',155)")
s=s.replace("@('C','C：仅取消额外 attachToModel 调用',197)))", "@('C','C：仅取消额外 attachToModel 调用',197), @('D','D：保留友军声音组件，不随画面隐藏删除（敌军不变）',239)))")
s=s.replace("' 18 242 680 22", "' 18 284 680 22").replace('Drawing.Point(18,267)', 'Drawing.Point(18,309)')
s=s.replace("Drawing.Point(18,309);$export", "Drawing.Point(18,351);$export")
s=s.replace("Drawing.Point(216,309)", "Drawing.Point(216,351)")
s=s.replace("' 18 354 684 46", "' 18 396 684 52")
s=s.replace('请选择A开始。诊断不修改车辆参数、不强制播放声音、不取消隐藏敌车静音。', '优先测试A、D。D只保留同队车辆音频；所有模式均不改变敌军隐藏静音或车辆参数。')
s=s.replace("if ($script:Buttons.Count -ne 3", "if ($script:Buttons.Count -ne 4")
s=s.replace("        [void][Windows.Forms.MessageBox]::Show($message,'日志收集')", "        if ($result.Incomplete) { $message+=' 采集不完整或没有声源样本：请把ZIP发来，不要据此判断声音链正常。详见 collection.json 的 DiagnosticHealth。' }\n        else { $message+=' 已检查存在声源样本、session_end、writer_end，且未发现丢失记录。' }\n        [void][Windows.Forms.MessageBox]::Show($message,'日志收集')")
f=out/'Engine-Diagnostics.ps1';f.write_text(s,encoding='utf-8-sig',newline='\r\n')
digest=hashlib.sha256(f.read_bytes()).hexdigest()
print(digest)
assert digest=='ed8469d715fe99f13ddb6c0f4ba7da3ce9bf704ea382f74c7fa4a616f5e22710', digest
