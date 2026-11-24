"""Speaks narration_hi.json with Microsoft's online Hindi voice (edge-tts).

Run from this folder:
    python -m pip install edge-tts
    python tts_hindi.py
Writes voice_hi/s<scene>c<cue>.mp3 — one clip per caption change.
Only the narration text below is sent to Microsoft's speech service.
"""
import asyncio
import json
import os

import edge_tts

VOICE = os.environ.get("VOICE", "hi-IN-SwaraNeural")   # or hi-IN-MadhurNeural (male)
RATE = os.environ.get("RATE", "+0%")
HERE = os.path.dirname(os.path.abspath(__file__))


async def main():
    lines = json.load(open(os.path.join(HERE, "narration_hi.json"), encoding="utf-8"))
    out = os.path.join(HERE, "voice_hi")
    os.makedirs(out, exist_ok=True)
    n = 0
    for scene in lines:
        for i, cue in enumerate(scene["cues"]):
            path = os.path.join(out, f"s{scene['scene']}c{i}.mp3")
            await edge_tts.Communicate(cue["text"], VOICE, rate=RATE).save(path)
            n += 1
            print("spoke", os.path.basename(path))
    print(f"done: {n} clips with {VOICE}")


asyncio.run(main())
