"""تجربة محرّك النطق الحرفي (tts_arabic: نص مشكول ← أصوات بقواعد ثابتة ← صوت).
1) يولّد كل المقاطع (التي لها تسجيل للمعلم) بالمتحدثين 0..3، وعيّنة كلمات وجمل.
2) يتحقق صوتياً من المقاطع بميزات WavLM مقابل تسجيلات المعلم (نفس طريقة فحص «حامد بنطقك»).
المخرج: audio/ar_tts/{index.json, verify.json, *.mp3}
"""
import json, os, re, subprocess, hashlib, time, sys
import numpy as np, torch, torchaudio
from tts_arabic import tts
sys.path.insert(0, 'tools'); sys.path.insert(0, 'tts')

OUT = 'audio/ar_tts'; TMP = '/tmp/at'; os.makedirs(OUT, exist_ok=True); os.makedirs(TMP, exist_ok=True)
def sh(*a): subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', *a], check=True)
man = {m['id']: m for m in json.load(open('tts/manifest.json'))}; keys = json.load(open('tts/keys.json'))
h = json.load(open('audio/human/index.json')); c = json.load(open('audio/human_clean/index.json'))
refs = {k: 'audio/human_clean/' + c[k]['f'] for k in h if k.startswith('s|') and k in c and c[k]['src'] == h[k]}
SPK = [int(x) for x in os.environ.get('SPK', '0,1,2,3').split(',')]
flags = json.load(open('tts/review_flags.json')) if os.path.exists('tts/review_flags.json') else {}

def gen(text, spk, name):
    w = f'{TMP}/{name}.wav'
    tts(text, speaker=spk, pace=float(os.environ.get('PACE', '0.9')), model_id='fastpitch', vocoder_id='hifigan', save_to=w)
    sh('-i', w, '-af', 'adelay=60:all=1,silenceremove=start_periods=1:start_threshold=-55dB,areverse,silenceremove=start_periods=1:start_threshold=-55dB,areverse,apad=pad_dur=0.12,loudnorm=I=-17:TP=-1.5:LRA=11',
       '-ar', '24000', '-c:a', 'libmp3lame', '-b:a', '64k', f'{OUT}/{name}.mp3')
    return f'{OUT}/{name}.mp3'

index = {}; t0 = time.time()
# المقاطع: نص النطق (بعد قواعد الكتاب) من manifest
syl = [(k, man[keys[k]]['text']) for k in sorted(refs) if k in keys]
for n, (k, text) in enumerate(syl):
    for s in SPK:
        name = f"s{s}_" + hashlib.sha1(k.encode()).hexdigest()[:10]
        try: index.setdefault(k, {})[str(s)] = os.path.basename(gen(text, s, name))
        except Exception as e: print('fail', k, s, e, flush=True)
    if n % 50 == 0: print('syl', n, len(syl), f'{time.time()-t0:.0f}s', flush=True)
# عينة كلمات وجمل: الكلمات المؤشَّرة سابقاً + كلمات بالتاء المربوطة والتنوين + جمل
words = [m for m in man.values() if m['role'] in ('w', 'n')]
pick = [m for m in words if re.search('هْ[.؟!،]?$', m['text'])][:12] + [m for m in words if m['role'] == 'w' and ' ' not in m['text']][:20:2] + [m for m in words if m['role'] == 'n' and len(m['text'].split()) > 4][:10]
for m in pick:
    k = next((x for x, i in keys.items() if i == m['id']), None)
    if not k: continue
    for s in SPK:
        name = f"w{s}_" + m['id']
        try: index.setdefault(k, {})[str(s)] = os.path.basename(gen(m['text'], s, name))
        except Exception as e: print('fail', k, s, e, flush=True)
    index[k]['hamed'] = m['id'] + '.mp3'
json.dump(index, open(f'{OUT}/index.json', 'w'), ensure_ascii=False, separators=(',', ':'))
print('generated', len(index), f'{time.time()-t0:.0f}s', flush=True)

# ===== التحقق الصوتي بـ WavLM =====
B = torchaudio.pipelines.WAVLM_LARGE; wl = B.get_model().eval(); torch.set_num_threads(os.cpu_count() or 2)
def feats(p):
    x, sr = torchaudio.load(p); x = x.mean(0, keepdim=True)
    if sr != 16000: x = torchaudio.functional.resample(x, sr, 16000)
    x = torch.nn.functional.pad(x, (1600, 1600))
    with torch.inference_mode(): hs, _ = wl.extract_features(x, num_layers=7)
    return torch.nn.functional.normalize(hs[6][0], dim=-1)
def dist(A, Bm):
    d = (1 - A @ Bm.T).numpy().astype(np.float64); n, m = d.shape
    acc = np.full((n + 1, m + 1), np.inf); acc[0, 0] = 0
    for i in range(1, n + 1):
        prev = acc[i - 1]; row = acc[i]; di = d[i - 1]; best = np.minimum(prev[1:], prev[:-1])
        for j in range(1, m + 1): row[j] = di[j - 1] + min(best[j - 1], row[j - 1])
    return float(acc[n, m] / (n + m))
def shape(t): return re.sub('[ء-ي]', 'C', t.replace('ـ', ''))
groups = {}
for k in refs: groups.setdefault(shape(k[2:]), []).append(k)
RF = {}
def rf(k):
    if k not in RF: RF[k] = feats(refs[k])
    return RF[k]
ver = {str(s): {} for s in SPK}; ver['hamed_tts'] = {}
for n, (k, _) in enumerate(syl):
    g = groups.get(shape(k[2:]), [])
    if len(g) < 3: continue
    cands = {str(s): f"{OUT}/{index[k][str(s)]}" for s in SPK if str(s) in index.get(k, {})}
    cands['hamed_tts'] = f"audio/{keys[k]}.mp3"
    for tag, p in cands.items():
        try:
            X = feats(p); ds = sorted((dist(X, rf(r)), r) for r in g)
            ver[tag][k] = {'rank': [r for _, r in ds].index(k) + 1, 'n': len(g), 'best': ds[0][1][2:]}
        except Exception as e: print('vfail', k, tag, e, flush=True)
    if n % 50 == 0:
        print('verify', n, flush=True); json.dump(ver, open(f'{OUT}/verify.json', 'w'), ensure_ascii=False)
json.dump(ver, open(f'{OUT}/verify.json', 'w'), ensure_ascii=False)
fl = {x for x, i in keys.items() if i in flags}
for tag, v in ver.items():
    v = {k: x for k, x in v.items() if x}
    print(tag, 'checked', len(v), 'top1', sum(1 for x in v.values() if x['rank'] == 1),
          '| flagged top1', sum(1 for k in fl if k in v and v[k]['rank'] == 1), '/', sum(1 for k in fl if k in v), flush=True)
