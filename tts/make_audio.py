"""توليد ملفات الصوت (MP3) لكل الجمل في tts/manifest.json باستعمال أصوات مايكروسوفت (edge-tts).
الاستعمال:  pip install edge-tts   ثم   python tts/make_audio.py
يولّد فقط الملفات الناقصة في مجلد audio/ ، فتكدر تشغّله أكثر من مرة."""
import asyncio, json, os, sys, shutil, subprocess
try:
    import edge_tts
except ImportError:
    sys.exit('ثبّت المكتبة أولاً:  pip install edge-tts')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MAN = os.path.join(HERE, 'manifest.json')
OUT = os.path.join(ROOT, 'audio')
os.makedirs(OUT, exist_ok=True)
items = json.load(open(MAN, encoding='utf-8'))
todo = [m for m in items if not os.path.exists(os.path.join(OUT, m['id'] + '.mp3'))]
print(f'المجموع {len(items)} — الناقص {len(todo)}')
# حذف الملفات القديمة التي لم تعد مستعملة
keep = {m['id'] + '.mp3' for m in items}
old = [f for f in os.listdir(OUT) if f.endswith('.mp3') and f not in keep]
for f in old: os.remove(os.path.join(OUT, f))
print('حُذف', len(old), 'ملف قديم')

FF = shutil.which('ffmpeg')
def trim(f):
    # حذف الصمت من بداية الملف ونهايته حتى يكون النطق سريع الاستجابة
    if not FF: return
    t = f + '.trim.mp3'
    af = 'silenceremove=start_periods=1:start_threshold=-60dB:start_silence=0.06,areverse,silenceremove=start_periods=1:start_threshold=-60dB:start_silence=0.25,areverse,apad=pad_dur=0.08'  # قص لطيف: لا يقطع أواخر الكلمات (مثل الهاء الساكنة)
    r = subprocess.run([FF, '-v', 'error', '-y', '-i', f, '-af', af, '-ac', '1', '-ar', '24000', '-b:a', '64k', t])
    if r.returncode == 0 and os.path.exists(t) and os.path.getsize(t) > 300: os.replace(t, f)

async def one(m, sem):
    async with sem:
        dst = os.path.join(OUT, m['id'] + '.mp3')
        text = m['text'].replace('...', '، ').replace('ـ', '')
        for attempt in range(4):
            try:
                await edge_tts.Communicate(text, m['voice'], rate=m['rate'], pitch=m['pitch']).save(dst + '.tmp')
                if os.path.getsize(dst + '.tmp') > 500:
                    trim(dst + '.tmp'); os.replace(dst + '.tmp', dst); return True
            except Exception as e:
                await asyncio.sleep(2 + attempt * 3)
        print('فشل:', m['text']); return False

# ===== محرّك النطق الحرفي (tts_arabic) للأصوات 'ar:<متحدث>' =====
FALLBACK = {'0': 'ar-SA-HamedNeural', '1': 'ar-SA-HamedNeural', '2': 'ar-SA-ZariyahNeural', '3': 'ar-SA-ZariyahNeural'}
import re
_PATCHED = False
def patch_engine():
    """إصلاح خطأين في محوّل النطق داخل المحرك:
    ١) جدول الكلمات الثابتة كان يطابق هيكلاً ناقصاً (يحذف حروفاً مثل ق ب ص)، فصارت «قِطَّهْ» و«بَطَّهْ» تُقرأ «طه»،
       و«بِنْتْ» و«صَنَعَتْ» تُقرأ «نِتْ». الآن لا يُطبَّق الجدول إلا إذا تطابقت حروف الكلمة كلها.
    ٢) الألف بعد واو أو كاف في أول الكلمة كانت تُقصَّر (وَاضِحْ ← وَضِح، وَالِد ← وَلِد، كَا ← كَ)، فنفصلها بفاصل خفي
       حين تكون مدّاً حقيقياً (الحرف بعدها متحرك)، ونتركها حين تكون همزة وصل (وَالقَمَرُ، وَالَّتِي)."""
    global _PATCHED
    if _PATCHED: return
    import tts_arabic.text.phonetise_buckwalter as pb
    orig = pb.isFixedWord
    def fixed(word, results, orth, prons):
        if re.sub(u'[aiuoFNK~`]', '', word) != re.sub(u'[^h*Ahn\'>wl}kmyTtfd]', '', word): return results
        return orig(word, results, orth, prons)
    pb.isFixedWord = fixed
    _PATCHED = True
ZW = re.compile('(^|[\\s،,.؟?!:؛«(])([وك]َ)(ا)(?!ل[َُِ]?ّ)(?=$|[\\s،,.؟?!:؛»)]|[ء-ي]ّ?[َُِ ًٌٍ])')
def engine_text(t): return ZW.sub(lambda m: m.group(1) + m.group(2) + '\u200d' + m.group(3), t)

def engine(m):
    from tts_arabic import tts
    patch_engine()
    dst = os.path.join(OUT, m['id'] + '.mp3'); w = dst + '.wav'
    text = engine_text(m['text'].replace('...', '، ').replace('ـ', ''))
    tts(text, speaker=int(m['voice'].split(':')[1]), pace=float(m['rate']), pitch_mul=float(m['pitch']),
        model_id='fastpitch', vocoder_id='hifigan', save_to=w)
    r = subprocess.run([FF, '-v', 'error', '-y', '-i', w, '-af', 'adelay=60:all=1,silenceremove=start_periods=1:start_threshold=-55dB:start_silence=0.05,areverse,silenceremove=start_periods=1:start_threshold=-55dB:start_silence=0.2,areverse,apad=pad_dur=0.1,loudnorm=I=-17:TP=-1.5:LRA=11',
                        '-ac', '1', '-ar', '24000', '-b:a', '64k', dst])
    os.remove(w)
    if r.returncode != 0 or not os.path.exists(dst): raise RuntimeError('ffmpeg')

async def main():
    ar = [m for m in todo if m['voice'].startswith('ar:')]; ed = [m for m in todo if not m['voice'].startswith('ar:')]
    fails = []
    for i, m in enumerate(ar):
        try: engine(m)
        except Exception as e:
            print('المحرك فشل، صوت احتياطي:', m['text'][:40], e)
            fails.append(dict(m, voice=FALLBACK[m['voice'].split(':')[1]], rate='-8%', pitch='+0Hz'))
        if i % 200 == 0: print('محرك', i, len(ar), flush=True)
    sem = asyncio.Semaphore(6)
    res = await asyncio.gather(*[one(m, sem) for m in ed + fails])
    print('تم: المحرك', len(ar) - len(fails), '— احتياطي/آخر', sum(res), 'من', len(ed) + len(fails))
asyncio.run(main())
