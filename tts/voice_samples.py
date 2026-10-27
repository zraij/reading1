"""عينات أصوات edge-tts للمقارنة (بدون تحويل). المهمة: tts/voice_samples.json  ← audio/voice_samples/"""
import asyncio, hashlib, json, os, subprocess, edge_tts
job = json.load(open('tts/voice_samples.json')); OUT = 'audio/voice_samples'; os.makedirs(OUT, exist_ok=True)
res = []
async def one(v, t, path):
    for a in range(4):
        try:
            await edge_tts.Communicate(t, v['voice'], rate=v.get('rate', '-8%'), pitch=v.get('pitch', '+0Hz')).save(path); return True
        except Exception as e: print('retry', v['voice'], e); await asyncio.sleep(3)
    return False
for v in job['voices']:
    for t in job['texts']:
        tag = hashlib.sha1((v['voice'] + v.get('rate', '') + v.get('pitch', '') + t).encode()).hexdigest()[:10]
        raw = f'/tmp/{tag}.mp3'
        if not asyncio.run(one(v, t, raw)): continue
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', raw, '-af', 'silenceremove=start_periods=1:start_threshold=-50dB,areverse,silenceremove=start_periods=1:start_threshold=-50dB,areverse,apad=pad_dur=0.1', '-ar', '24000', '-b:a', '64k', f'{OUT}/{tag}.mp3'], check=True)
        res.append({'voice': v['voice'], 'name': v['name'], 'text': t, 'file': tag + '.mp3'})
        print('ok', v['voice'], t[:20], flush=True)
json.dump(res, open(f'{OUT}/index.json', 'w'), ensure_ascii=False, indent=1)
