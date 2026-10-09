param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$text = '您有新的外贸部订单，请注意查收。'
$voiceName = 'Microsoft Huihui Desktop'
$stream = New-Object System.IO.MemoryStream
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $synth.SelectVoice($voiceName)
    $synth.Rate = 0
    $synth.SetOutputToWaveStream($stream)
    $synth.Speak($text)
    $synth.SetOutputToNull()
    $encoded = [Convert]::ToBase64String($stream.ToArray())
} finally {
    $synth.Dispose()
    $stream.Dispose()
}
$assetDir = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../frontend/src/assets'))
$code = @'
import base64,hashlib,io,json,sys,wave
from pathlib import Path
directory=Path(sys.argv[1]);directory.mkdir(parents=True,exist_ok=True)
with wave.open(io.BytesIO(base64.b64decode(sys.stdin.read())), 'rb') as source:
    channels=source.getnchannels();width=source.getsampwidth();rate=source.getframerate()
    count=source.getnframes();phrase=source.readframes(count)
    assert source.getcomptype()=='NONE' and width==2, 'Expected signed 16-bit PCM recording'
pause_count=round(rate*0.5)
pause=b'\0'*(pause_count*channels*width)
target=directory/'new-order-zh-CN.wav'
with wave.open(str(target),'wb') as output:
    output.setnchannels(channels);output.setsampwidth(width);output.setframerate(rate)
    output.writeframes(phrase+pause+phrase)
metadata={'phraseText':sys.argv[2],'voice':sys.argv[3],'repeatCount':2,'pauseMs':500,
          'channels':channels,'sampleWidth':width,'sampleRate':rate,'phraseFrameCount':count,
          'pauseFrameCount':pause_count,'phrasePcmSha256':hashlib.sha256(phrase).hexdigest(),
          'wavSha256':hashlib.sha256(target.read_bytes()).hexdigest()}
(directory/'new-order-zh-CN.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(f'Generated fixed recording: {metadata["repeatCount"]} phrases, {(count*2+pause_count)/rate:.2f}s')
'@
$encoded | & $Python -c $code $assetDir $text $voiceName
if ($LASTEXITCODE -ne 0) { throw 'Fixed voice recording generation failed' }
