"""حامد بنطق المعلم: يحوّل تسجيلات المعلم للمقاطع (نطقها صحيح) إلى نبرة صوت حامد بطريقة kNN-VC،
ثم يتحقق صوتياً: يقارن كل ناتج — بميزات WavLM (تمثّل الأصوات اللغوية لا المتكلم) — بكل تسجيلات المعلم
التي لها نفس شكل المقطع، وينجح إذا كان أقرب تسجيل له هو مقطعه نفسه. ويفحص بنفس الطريقة أصوات حامد الآلية للمقارنة.
المخرج: audio/hamed_syl/<اسم>.mp3 + index.json + verify.json
"""
import json, os, re, subprocess, sys, hashlib, time
import torch, torchaudio
torch.set_num_threads(os.cpu_count() or 2)
OUT = 'audio/hamed_syl'; TMP = '/tmp/hs'; os.makedirs(OUT, exist_ok=True); os.makedirs(TMP + '/ref', exist_ok=True); os.makedirs(TMP + '/src', exist_ok=True)
def sh(*a): subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', *a], check=True)

man = json.load(open('tts/manifest.json')); keys = json.load(open('tts/keys.json'))
h = json.load(open('audio/human/index.json')); c = json.load(open('audio/human_clean/index.json'))
src = {k: 'audio/human_clean/' + c[k]['f'] for k in h if k.startswith('s|') and k in c and c[k]['src'] == h[k]}
LIMIT = int(os.environ.get('LIMIT', '0'))
# مرجع حامد: جمل وكلمات حامد (نطق متصل غني بكل الأصوات)
ham = [m for m in man if m['voice'] == 'ar-SA-HamedNeural' and m['role'] in ('n', 'w') and os.path.exists(f"audio/{m['id']}.mp3")]
ham.sort(key=lambda m: -len(m['text'])); ham = ham[:int(os.environ.get('NREF', '450'))]
refs = []
for m in ham:
    o = f"{TMP}/ref/{m['id']}.wav"; sh('-i', f"audio/{m['id']}.mp3", '-ac', '1', '-ar', '16000', o); refs.append(o)
print('hamed ref clips', len(refs), flush=True)

knn = torch.hub.load('bshall/knn-vc', 'knn_vc', prematched=True, trust_repo=True, pretrained=True, device='cpu')
ms = knn.get_matching_set(refs, vad_trigger_level=0)
print('matching set', tuple(ms.shape), flush=True)

def wav16(p, o): sh('-i', p, '-ac', '1', '-ar', '16000', o); return o
def F(p): return knn.get_features(p, vad_trigger_level=0)   # WavLM (الطبقة السادسة) — ميزات لغوية

items = sorted(src.items())
if LIMIT: items = items[:LIMIT]
index = {}; t0 = time.time()
for n, (k, p) in enumerate(items):
    w = wav16(p, f"{TMP}/src/{hashlib.sha1(k.encode()).hexdigest()[:10]}.wav")
    out = knn.match(F(w), ms, topk=4)
    name = 'h_' + hashlib.sha1(k.encode()).hexdigest()[:10] + '.mp3'
    o16 = f'{TMP}/o.wav'; torchaudio.save(o16, out[None].cpu(), 16000)
    sh('-i', o16, '-af', 'highpass=f=70,loudnorm=I=-17:TP=-1.5:LRA=11,silenceremove=start_periods=1:start_threshold=-50dB,areverse,silenceremove=start_periods=1:start_threshold=-50dB,areverse,apad=pad_dur=0.1',
       '-ar', '24000', '-c:a', 'libmp3lame', '-b:a', '64k', f'{OUT}/{name}')
    index[k] = {'f': name, 'src': h[k]}
    if n % 50 == 0: print('conv', n, len(items), f'{time.time()-t0:.0f}s', flush=True)
json.dump(index, open(f'{OUT}/index.json', 'w'), ensure_ascii=False, separators=(',', ':'))

# ===== التحقق الصوتي =====
def shape(t):
    t = t.replace('ـ', '')
    return re.sub('[ء-ي]', 'C', t)
groups = {}
for k in src: groups.setdefault(shape(k[2:]), []).append(k)
RF = {}
def refF(k):
    if k not in RF:
        RF[k] = F(wav16(src[k], f"{TMP}/src/r_{hashlib.sha1(k.encode()).hexdigest()[:10]}.wav"))
    return RF[k]
import numpy as np
def dist(A, B):
    A = torch.nn.functional.normalize(A, dim=-1); B = torch.nn.functional.normalize(B, dim=-1)
    d = (1 - A @ B.T).numpy().astype(np.float64); n, m = d.shape
    acc = np.full((n + 1, m + 1), np.inf); acc[0, 0] = 0
    for i in range(1, n + 1):
        prev = acc[i - 1]; row = acc[i]; di = d[i - 1]
        best = np.minimum(prev[1:], prev[:-1])
        for j in range(1, m + 1):
            row[j] = di[j - 1] + min(best[j - 1], row[j - 1])
    return float(acc[n, m] / (n + m))
def check(k, path):
    g = groups.get(shape(k[2:]), [])
    if len(g) < 3: return None
    X = F(wav16(path, f'{TMP}/chk.wav'))
    ds = sorted((dist(X, refF(r)), r) for r in g)
    rank = [r for _, r in ds].index(k) + 1
    return {'rank': rank, 'n': len(g), 'best': ds[0][1][2:]}
ver = {'conv': {}, 'tts': {}}
for n, k in enumerate(index):
    ver['conv'][k] = check(k, f"{OUT}/{index[k]['f']}")
    if keys.get(k) and os.path.exists(f"audio/{keys[k]}.mp3"): ver['tts'][k] = check(k, f"audio/{keys[k]}.mp3")
    if n % 50 == 0:
        print('verify', n, flush=True); json.dump(ver, open(f'{OUT}/verify.json', 'w'), ensure_ascii=False)
json.dump(ver, open(f'{OUT}/verify.json', 'w'), ensure_ascii=False)
for t in ('conv', 'tts'):
    v = [x for x in ver[t].values() if x]; print(t, 'checked', len(v), 'top1', sum(1 for x in v if x['rank'] == 1), flush=True)
