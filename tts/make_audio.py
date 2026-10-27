"""توليد ملفات الصوت (MP3) لكل الجمل في tts/manifest.json باستعمال أصوات مايكروسوفت (edge-tts).
الاستعمال:  pip install edge-tts   ثم   python tts/make_audio.py
يولّد فقط الملفات الناقصة في مجلد audio/ ، فتكدر تشغّله أكثر من مرة."""
import asyncio, json, os, sys
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

async def one(m, sem):
    async with sem:
        dst = os.path.join(OUT, m['id'] + '.mp3')
        text = m['text'].replace('...', '، ').replace('ـ', '')
        for attempt in range(4):
            try:
                await edge_tts.Communicate(text, m['voice'], rate=m['rate'], pitch=m['pitch']).save(dst + '.tmp')
                if os.path.getsize(dst + '.tmp') > 500:
                    os.replace(dst + '.tmp', dst); return True
            except Exception as e:
                await asyncio.sleep(2 + attempt * 3)
        print('فشل:', m['text']); return False

async def main():
    sem = asyncio.Semaphore(6)
    res = await asyncio.gather(*[one(m, sem) for m in todo])
    print('تم:', sum(res), 'من', len(todo))
asyncio.run(main())
