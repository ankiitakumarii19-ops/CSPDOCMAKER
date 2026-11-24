# CSP form guide video — how to re-make it

Output: `docs/CSP form guide - Hinglish.mp4` (vertical 1080x1920, Hindi voice).

1. Words spoken: `narration_hi.json` (Hindi script). Screens and on-screen text: `guide.html`.
2. Voice (Microsoft online Hindi voice, needs internet):
   `python -m pip install edge-tts` then `python tts_hindi.py` → `voice_hi/*.mp3`
3. Speed up slightly and trim pauses (ffmpeg, per clip):
   `atempo=1.18,silenceremove=start_periods=1:start_threshold=-45dB:stop_periods=-1:stop_duration=0.3:stop_threshold=-45dB:stop_silence=0.2` → `voice_hi_t/*.wav`
4. Timing + voice track: `python timeline.py voice_hi_t narration_hi.json` → `timeline.json`, `narration.wav`
5. Frames: `npm i playwright-core@1.48.2` once, then `node render.js all 24` (uses Microsoft Edge)
6. Join: `ffmpeg -framerate 24 -i frames/f%05d.jpg -i narration.wav -c:v libx264 -crf 23 -pix_fmt yuv420p -c:a aac -b:a 96k -shortest -movflags +faststart out.mp4`

`speak.ps1` + `narration.json` = the older local English-accent voice (not used).
