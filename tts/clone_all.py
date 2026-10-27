"""تحويل كل أصوات الكتاب (الراوي، الكلمات، المقاطع غير المسجلة) إلى صوت المعلم المستنسخ.
الإعدادات في tts/clone_all.json. يعمل على أجزاء متوازية:  python clone_all.py <shard> <shards>
المخرج: out/clone/<id>.mp3 و out/clone/part_<shard>.json  (يدمجها سير العمل في audio/clone)
"""
import asyncio, hashlib, json, os, re, subprocess, sys, time
import torch, torchaudio, edge_tts

SHARD, SHARDS = int(sys.argv[1]), int(sys.argv[2])
cfg = json.load(open('tts/clone_all.json'))
keys = json.load(open('tts/keys.json'))                       # key -> id
man = {m['id']: m for m in json.load(open('tts/manifest.json'))}  # id -> {text(بعد تحويل النطق), role}
human = json.load(open('audio/human/index.json'))
old = {}
try: old = json.load(open('audio/clone/index.json'))
except Exception: pass
OUT = 'out/clone'; TMP = '/tmp/cl'; os.makedirs(OUT, exist_ok=True); os.makedirs(TMP + '/ref', exist_ok=True)
torch.set_num_threads(os.cpu_count() or 2)

def canon(t):  # نفس canonSyl في الكتاب
    t = t.replace('ـ', '').strip()
    t = re.sub('^[ءئ]ِ', 'إِ', t); t = re.sub('^ء', 'أ', t); t = re.sub('^أِ', 'إِ', t); t = re.sub('^ة', 'ت', t)
    t = re.sub('^([\u0621-\u064A])\u064Eى$', '\\1\u064Eا', t)
    t = re.sub('^([\u0621-\u064A])\u0650\u064A\u0652$', '\\1\u0650\u064A', t); t = re.sub('^([\u0621-\u064A])\u064F\u0648\u0652$', '\\1\u064F\u0648', t)
    return t

def has_human(k):
    if k in human: return True
    r, t = k.split('|', 1)
    return (' ' not in t and len(t) <= 8) and ('s|' + canon(t)) in human

V = cfg['voice']; RATES = cfg['rates']; PITCH = cfg.get('pitch', '+0Hz'); TOPK = cfg.get('topk', 4)
todo = []
for k, i in sorted(keys.items()):
    role = k.split('|', 1)[0]
    if role not in RATES or has_human(k): continue
    text = man[i]['text']
    sig = hashlib.sha1('|'.join([text, V, RATES[role], PITCH, str(TOPK), str(cfg.get('v', 1))]).encode()).hexdigest()[:10]
    if old.get(k, {}).get('sig') == sig and os.path.exists('audio/clone/' + old[k]['f']): continue
    todo.append((k, role, text, sig))
todo = todo[SHARD::SHARDS]
print(f'shard {SHARD}/{SHARDS}: {len(todo)} clips', flush=True)
if not todo:
    json.dump({}, open(f'{OUT}/part_{SHARD}.json', 'w')); sys.exit(0)

def sh(*a): subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', *a], check=True)
refs = []
for f in sorted(os.listdir('audio/human_clean')):
    if f.endswith('.mp3'):
        o = f'{TMP}/ref/{f[:-4]}.wav'; sh('-i', f'audio/human_clean/{f}', '-ac', '1', '-ar', '16000', o); refs.append(o)
knn = torch.hub.load('bshall/knn-vc', 'knn_vc', prematched=True, trust_repo=True, pretrained=True, device='cpu')
ms = knn.get_matching_set(refs, vad_trigger_level=0)
print('matching set', tuple(ms.shape), flush=True)

async def say(text, rate, path):
    for a in range(5):
        try:
            await edge_tts.Communicate(text, V, rate=rate, pitch=PITCH).save(path)
            if os.path.getsize(path) > 500: return
        except Exception as e:
            print('retry', a, e, flush=True)
        await asyncio.sleep(2 + a * 3)
    raise RuntimeError('tts failed: ' + text)

part = {}; t0 = time.time()
TRIM = 'silenceremove=start_periods=1:start_threshold=-50dB,areverse,silenceremove=start_periods=1:start_threshold=-50dB,areverse'
for n, (k, role, text, sig) in enumerate(todo):
    try:
        src, s16, o16 = f'{TMP}/s.mp3', f'{TMP}/s.wav', f'{TMP}/o.wav'
        asyncio.run(say(text, RATES[role], src))
        sh('-i', src, '-ac', '1', '-ar', '16000', '-af', 'adelay=60:all=1,' + TRIM + ',apad=pad_dur=0.12', s16)
        out = knn.match(knn.get_features(s16, vad_trigger_level=0), ms, topk=TOPK)
        torchaudio.save(o16, out[None].cpu(), 16000)
        fn = keys[k] + '.mp3'
        sh('-i', o16, '-af', 'highpass=f=70,afftdn=nr=10:nf=-45,' + TRIM + ',loudnorm=I=-18:TP=-1.5:LRA=11,afade=t=in:d=0.01,apad=pad_dur=0.08',
           '-ar', '24000', '-c:a', 'libmp3lame', '-b:a', '56k', f'{OUT}/{fn}')
        part[k] = {'f': fn, 'sig': sig}
    except Exception as e:
        print('FAIL', k, e, flush=True)
    if n % 25 == 0:
        print(f'{n + 1}/{len(todo)}  {time.time() - t0:.0f}s', flush=True)
        json.dump(part, open(f'{OUT}/part_{SHARD}.json', 'w'), ensure_ascii=False)
json.dump(part, open(f'{OUT}/part_{SHARD}.json', 'w'), ensure_ascii=False)
print('done', len(part), f'{time.time() - t0:.0f}s', flush=True)
