param([string]$LinesJson, [string]$OutDir, [string]$VoiceMatch = "Heera", [double]$Rate = 0.92)
# Speaks each line of a JSON list ({id,text}) to OutDir\<id>.wav with a local Windows (OneCore) voice.
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.DataReader, Windows.Storage.Streams, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$t) {
  $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait() | Out-Null; $task.Result
}
$synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$voice = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices | Where-Object { $_.DisplayName -match $VoiceMatch } | Select-Object -First 1
if (-not $voice) { throw "voice $VoiceMatch not found: " + (([Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices | ForEach-Object DisplayName) -join ', ') }
$synth.Voice = $voice
$synth.Options.SpeakingRate = $Rate
Write-Output ("voice: " + $voice.DisplayName + " " + $voice.Language)
$lines = Get-Content -Raw -Encoding UTF8 $LinesJson | ConvertFrom-Json
New-Item -ItemType Directory -Force $OutDir | Out-Null
foreach ($l in $lines) {
  $stream = Await ($synth.SynthesizeTextToStreamAsync($l.text)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
  $size = [uint32]$stream.Size
  $reader = New-Object Windows.Storage.Streams.DataReader($stream.GetInputStreamAt(0))
  $null = Await ($reader.LoadAsync($size)) ([uint32])
  $bytes = New-Object byte[] $size
  $reader.ReadBytes($bytes)
  [System.IO.File]::WriteAllBytes((Join-Path $OutDir ($l.id + ".wav")), $bytes)
}
Write-Output ("wrote " + $lines.Count)
