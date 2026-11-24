"""Builds timeline.json (screen timing stretched to fit each spoken line) and the
mixed narration track. Usage: python timeline.py <voice_dir> [narration.json]"""
import json, os, subprocess, sys
VOICE = sys.argv[1]
NARRATION = sys.argv[2] if len(sys.argv) > 2 else 'narration.json'
DUR = [6, 8, 8, 17, 12, 18, 16, 12, 10]   # scene lengths in guide.html
LEAD, TAIL = 0.3, 0.45
def length(f):
    return float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',f]).decode())
nar = json.load(open(NARRATION, encoding='utf-8'))
warp, clips, t = [], [], 0.0
for sc in nar:
    cues = sc['cues']; segs = []
    for i, c in enumerate(cues):
        c0 = c['t']; c1 = cues[i+1]['t'] if i+1 < len(cues) else DUR[sc['scene']]
        f = f"{VOICE}/s{sc['scene']}c{i}.wav"
        if not os.path.exists(f): f = f[:-4] + '.mp3'
        d = length(f)
        out = max(c1 - c0, LEAD + d + TAIL)
        segs.append({'c0': c0, 'c1': c1, 'out': round(out, 3)})
        clips.append((f, t + LEAD)); t += out
    warp.append({'scene': sc['scene'], 'segs': segs})
json.dump(warp, open('timeline.json', 'w'), indent=1)
print('total seconds', round(t, 2))
inp, flt = [], []
for i, (f, at) in enumerate(clips):
    inp += ['-i', f]; ms = int(at * 1000)
    flt.append(f'[{i}:a]aresample=44100,aformat=channel_layouts=stereo,adelay={ms}|{ms}[a{i}]')
flt.append(''.join(f'[a{i}]' for i in range(len(clips))) + f'amix=inputs={len(clips)}:normalize=0,apad,atrim=0:{t:.3f},loudnorm=I=-16:TP=-1.5[out]')
subprocess.check_call(['ffmpeg','-y','-loglevel','error',*inp,'-filter_complex',';'.join(flt),'-map','[out]','-ar','44100','narration.wav'])
print('narration.wav written')
