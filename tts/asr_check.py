"""فحص تلقائي للنطق: يستمع لكل ملف صوتي (كلمات وجمل) بنموذج Whisper ويقارن ما سمعه بالنص.
لا يحكم على الحركات (Whisper يكتب بلا تشكيل)، لكنه يكشف الكلمات الناقصة أو المقروءة خطأ.
الاستعمال (على GitHub Actions):  python asr_check.py <shard> <shards>   ← out/asr/part_<shard>.json
"""
import json, os, re, sys, difflib
from faster_whisper import WhisperModel

SH, N = int(sys.argv[1]), int(sys.argv[2])
man = json.load(open('tts/manifest.json'))
items = [m for m in man if m['role'] != 's'][SH::N]
model = WhisperModel(os.environ.get('WHISPER', 'medium'), device='cpu', compute_type='int8', cpu_threads=os.cpu_count() or 2)

def skel(t):
    t = re.sub('[ً-ْٰـ]', '', t)
    t = re.sub('[إأآٱ]', 'ا', t).replace('ى', 'ي').replace('ة', 'ه').replace('ؤ', 'و').replace('ئ', 'ي')
    t = re.sub(r'[^ء-ي\s]', ' ', t)
    return ' '.join(t.split())

res = {}
os.makedirs('out/asr', exist_ok=True)
for n, m in enumerate(items):
    f = f"audio/{m['id']}.mp3"
    if not os.path.exists(f): continue
    segs, _ = model.transcribe(f, language='ar', beam_size=2, vad_filter=False, condition_on_previous_text=False)
    heard = ' '.join(s.text for s in segs).strip()
    a, b = skel(m['text']), skel(heard)
    score = difflib.SequenceMatcher(None, a.replace(' ', ''), b.replace(' ', '')).ratio()
    res[m['id']] = {'heard': heard, 'score': round(score, 3)}
    if n % 50 == 0:
        print(n, len(items), flush=True); json.dump(res, open(f'out/asr/part_{SH}.json', 'w'), ensure_ascii=False)
json.dump(res, open(f'out/asr/part_{SH}.json', 'w'), ensure_ascii=False)
print('done', len(res))
