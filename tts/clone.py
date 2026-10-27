"""استنساخ صوت المعلم: صوت عصبي عربي (نطق صحيح بالتشكيل) ← تحويل نبرته إلى صوت المعلم
بطريقة kNN-VC (مرخّصة MIT) باستعمال كل تسجيلاته المنظفة (audio/human_clean) كمرجع.
يعمل على GitHub Actions (يحتاج إنترنت لتنزيل النماذج). المهمة في tts/clone_job.json
"""
import asyncio, hashlib, json, os, subprocess, sys
import torch, torchaudio, edge_tts

job = json.load(open('tts/clone_job.json'))
REF = 'audio/human_clean'; OUT = job.get('out', 'audio/clone_samples'); TMP = '/tmp/clone'
os.makedirs(TMP + '/ref', exist_ok=True); os.makedirs(OUT, exist_ok=True)
torch.set_num_threads(os.cpu_count() or 2)

def sh(*a): subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', *a], check=True)

refs = []
for f in sorted(os.listdir(REF)):
    if f.endswith('.mp3'):
        o = f'{TMP}/ref/{f[:-4]}.wav'; sh('-i', f'{REF}/{f}', '-ac', '1', '-ar', '16000', o); refs.append(o)
print('reference clips:', len(refs), flush=True)

knn = torch.hub.load('bshall/knn-vc', 'knn_vc', prematched=True, trust_repo=True, pretrained=True, device='cpu')
ms = knn.get_matching_set(refs)
print('matching set', tuple(ms.shape), flush=True)

async def tts(text, v, path):
    await edge_tts.Communicate(text, v['voice'], rate=v.get('rate', '+0%'), pitch=v.get('pitch', '+0Hz')).save(path)

res = []
for it in job['items']:
    text = it['text']
    for v in job['voices']:
        tag = hashlib.sha1((text + v['voice'] + v.get('rate', '') + v.get('pitch', '')).encode()).hexdigest()[:10]
        src = f'{TMP}/{tag}.mp3'; s16 = f'{TMP}/{tag}.wav'; o16 = f'{TMP}/{tag}_o.wav'
        asyncio.run(tts(text, v, src))
        sh('-i', src, '-ac', '1', '-ar', '16000', '-af', 'silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse', s16)
        q = knn.get_features(s16)
        for topk in job.get('topk', [4]):
            out = knn.match(q, ms, topk=topk)
            torchaudio.save(o16, out[None].cpu(), 16000)
            name = f'{tag}_k{topk}.mp3'
            sh('-i', o16, '-af', 'highpass=f=70,loudnorm=I=-18:TP=-1.5:LRA=11', '-ar', '24000', '-c:a', 'libmp3lame', '-b:a', '64k', f'{OUT}/{name}')
            res.append({'text': text, 'voice': v['voice'], 'topk': topk, 'file': name, 'src': tag + '_src.mp3'})
        sh('-i', src, '-c:a', 'libmp3lame', '-b:a', '64k', '-ar', '24000', f'{OUT}/{tag}_src.mp3')
        print('ok', v['voice'], text[:30], flush=True)

json.dump(res, open(f'{OUT}/index.json', 'w'), ensure_ascii=False, indent=1)
