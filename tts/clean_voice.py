"""تنظيف وترتيب تسجيلات الحروف البشرية.
المدخل: audio/human/ (الخام — لا يُمسّ)   المخرج: audio/human_clean/<حرف>_<حركة>.mp3 + index.json
الخطوات: قص الصمت ← مرشح تمرير عالٍ 80Hz ← إزالة ضوضاء خفيفة ← ضبط طول الحركة (المدّ أطول بوضوح من القصيرة)
        ← توحيد مستوى الصوت ← حواف ناعمة ← MP3 أحادي 24kHz.
"""
import json, os, subprocess, sys, tempfile, numpy as np, scipy.io.wavfile as wf, scipy.signal as sg

SRC = 'audio/human'; DST = 'audio/human_clean'
import shutil; shutil.rmtree(DST, ignore_errors=True); os.makedirs(DST, exist_ok=True)
h = json.load(open(SRC + '/index.json')); st = json.load(open('tts/studio.json'))
TR = dict(zip('بمدفرسنتويقلطعحشزجصأضخثكغهذظ', 'ba mim dal fa ra sin nun ta waw ya qaf lam tta ayn hha shin zay jim sad hamza dad kha tha kaf ghayn ha dhal dha'.split()))
FORMS7 = ['a', 'u', 'i', 'aa', 'uu', 'ii', 'sk']; FORMS4 = ['a', 'u', 'i', 'sk']
SR = 24000
TMP = tempfile.mkdtemp()

def ff(args):
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y'] + args, check=True)

def rd(p):
    sr, x = wf.read(p); x = x.astype(np.float64) / 32768
    if x.ndim > 1: x = x.mean(1)
    if sr != SR: x = sg.resample_poly(x, SR, sr)
    return x

def wr(p, x): wf.write(p, SR, (np.clip(x, -1, 1) * 32767).astype(np.int16))

def env_db(x, hop=0.01, win=0.03):
    w = int(SR * win); hp = int(SR * hop)
    return np.array([10 * np.log10(np.mean(x[i:i + w] ** 2) + 1e-12) for i in range(0, max(1, len(x) - w), hp)])

def trim(x, pre=0.04, post=0.10):
    d = env_db(x); thr = d.max() - 38
    on = np.where(d > thr)[0]
    a = max(0, int((on[0] * 0.01 - pre) * SR)); z = min(len(x), int((on[-1] * 0.01 + 0.03 + post) * SR))
    return x[a:z]

# ---- كاشف الحركة ----
def _vs(x, SR=24000):
    """أطول مقطع مجهور (دوري) بطاقة منخفضة التردد عالية = الحركة. يرجع (بداية, نهاية) بالثواني."""
    hop=int(.01*SR); w=int(.03*SR)
    b,a=sg.butter(4,[150/(SR/2),1000/(SR/2)],'band'); lowb=sg.lfilter(b,a,x)
    fr=range(0,max(1,len(x)-w),hop)
    db=np.array([10*np.log10(np.mean(lowb[i:i+w]**2)+1e-12) for i in fr])
    def vc(f):
        f=f-f.mean(); ac=np.correlate(f,f,'full')[len(f)-1:]
        return ac[int(SR/400):int(SR/70)].max()/(ac[0]+1e-12)
    voi=np.array([vc(x[i:i+w]) for i in fr])
    v=(db>db.max()-15)&(voi>0.4)
    runs=[];s=None;gap=0
    for i,t in enumerate(list(v)+[False,False]):
        if t:
            if s is None: s=i
            gap=0
        elif s is not None:
            gap+=1
            if gap>1: runs.append((s,i-gap+1)); s=None; gap=0
    if not runs: return None
    s,z=max(runs,key=lambda r:r[1]-r[0])
    return s*hop/SR, (z*hop+w)/SR

def vowel_seg(x): return _vs(x, SR)

def stretch(x, seg, factor):
    """يمطّ (factor>1) أو يقصّر (<1) الحركة فقط، مع الحفاظ على طبقة الصوت."""
    a = int(seg[0] * SR); a = max(0, a)
    head, tail = x[:a], x[a:]
    p1 = os.path.join(TMP, 't.wav'); p2 = os.path.join(TMP, 't2.wav'); wr(p1, tail)
    ff(['-i', p1, '-af', f'rubberband=tempo={1 / factor:.4f}:pitch=1:transients=smooth:formant=preserved:pitchq=quality', p2])
    tail2 = rd(p2)
    xf = int(0.008 * SR)  # وصلة ناعمة
    if len(head) > xf and len(tail2) > xf:
        r = np.linspace(0, 1, xf)
        return np.concatenate([head[:-xf], head[-xf:] * (1 - r) + tail2[:xf] * r, tail2[xf:]])
    return np.concatenate([head, tail2])

def level(x, target=-17.0, peak=0.89):
    d = env_db(x); act = d[d > d.max() - 20]
    rms = 10 * np.log10(np.mean(10 ** (act / 10)))
    g = 10 ** ((target - rms) / 20)
    pk = np.max(np.abs(x)) * g
    if pk > peak: g *= peak / pk
    return x * g

def fade(x, a=0.012, b=0.05):
    na, nb = int(a * SR), int(b * SR)
    x = x.copy(); x[:na] *= np.linspace(0, 1, na); x[-nb:] *= np.linspace(1, 0, nb) ** 1.5
    return np.concatenate([np.zeros(int(0.03 * SR)), x, np.zeros(int(0.06 * SR))])

def clean(k):
    p = os.path.join(TMP, 'in.wav'); q = os.path.join(TMP, 'dn.wav')
    ff(['-i', os.path.join(SRC, h[k]), '-ac', '1', '-ar', str(SR), '-af', 'highpass=f=80:poles=2,afftdn=nr=14:nf=-44:tn=1,lowpass=f=9500', q])
    return trim(rd(q))

index = {}; report = []
for b in st['base']:
    L = b['L']; it = b['items']; forms = FORMS7 if len(it) == 7 else FORMS4
    X = {f: clean(k) for f, k in zip(forms, it)}
    seg = {f: vowel_seg(X[f]) for f in forms}
    vl = {f: (seg[f][1] - seg[f][0]) if seg[f] else 0 for f in forms}
    adj = {}
    # الحركات القصيرة: لا تطول أكثر من اللازم
    for f in ['a', 'u', 'i']:
        if seg[f] and vl[f] > 0.36:
            fac = max(0.55, 0.30 / vl[f]); X[f] = stretch(X[f], seg[f], fac); adj[f] = fac; vl[f] *= fac
    # المدود: ضعف الحركة القصيرة تقريباً (حركتان) وبحد أدنى 0.42 ث
    for f, s in [('aa', 'a'), ('uu', 'u'), ('ii', 'i')]:
        if f not in X or not seg[f]: continue
        tgt = min(0.75, max(0.45, 2.0 * vl[s]))
        fac = tgt / max(vl[f], 0.05)
        if fac > 1.08:
            fac = min(fac, 2.3); X[f] = stretch(X[f], seg[f], fac); adj[f] = fac
    for f, k in zip(forms, it):
        y = fade(level(X[f]))
        name = f'{TR[L]}_{f}'
        w = os.path.join(TMP, name + '.wav'); wr(w, y)
        ff(['-i', w, '-ac', '1', '-ar', str(SR), '-c:a', 'libmp3lame', '-b:a', '64k', os.path.join(DST, name + '.mp3')])
        index[k] = {'f': name + '.mp3', 'src': h[k]}
        report.append(dict(k=k, file=name + '.mp3', adj=round(adj.get(f, 1), 2), dur=round(len(y) / SR, 2)))

# أي تسجيلات أخرى (غير الحروف الأساسية) تُنظَّف بلا تعديل للطول
for k, fn in h.items():
    if k in index: continue
    y = fade(level(clean(k)))
    name = 'x_' + fn.split('_')[0]
    w = os.path.join(TMP, name + '.wav'); wr(w, y)
    ff(['-i', w, '-c:a', 'libmp3lame', '-b:a', '64k', os.path.join(DST, name + '.mp3')])
    index[k] = {'f': name + '.mp3', 'src': fn}

json.dump(index, open(DST + '/index.json', 'w'), ensure_ascii=False, separators=(',', ':'))
if os.environ.get('REPORT'): json.dump(report, open(os.environ['REPORT'], 'w'), ensure_ascii=False, indent=1)
print('done', len(index), 'files;', sum(1 for r in report if r['adj'] != 1), 'length-adjusted')
