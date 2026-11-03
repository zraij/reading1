/**
 * خادم قفل الأجهزة والجلسات — لكل الكتب (Google Apps Script)
 * تصميم وبرمجة: حسام عبدالمنعم — 07746451098 · © 2026 جميع الحقوق محفوظة
 *
 * طريقة التشغيل (مرة وحدة):
 *  1) افتح https://script.google.com ← New project، امسح الموجود والصق هذا الملف كله، واحفظ.
 *  2) Deploy ← New deployment ← النوع Web app
 *       Execute as: Me      Who has access: Anyone
 *  3) وافق على الصلاحيات، وانسخ رابط Web app (ينتهي بـ /exec) والصقه بلوحة الإدارة ← «الأجهزة والجلسات».
 *  عند أي تعديل على الملف: Deploy ← Manage deployments ← ✏️ ← Version: New version (حتى يبقى نفس الرابط).
 *
 * كيف يشتغل:
 *  - كل حساب ينربط بأول جهاز يفتح عليه (a|كتاب|حساب). جهاز ثاني ← locked.
 *  - الكتاب المفتوح يبلّغ الخادم كل كم دقيقة (الجلسة النشطة) ← تظهر بلوحة الإدارة.
 *  - «تسجيل خروج» من الإدارة: يفك ربط الحساب، والجهاز يطلع لصفحة الدخول (kicked).
 *  - «حذف وحظر»: يفك الربط + الجهاز ينحظر على هذا الكتاب لحد ما ترفع الحظر (blocked).
 *  - البيانات الدائمية بـ Script Properties، وآخر ظهور للجلسات بالذاكرة المؤقتة (حتى ما نستهلك الحصة اليومية).
 */
var P = PropertiesService.getScriptProperties();
var C = CacheService.getScriptCache();
var TTL = 21600; // 6 ساعات: أقصى مدة للذاكرة المؤقتة

function doGet(e) {
  var q = (e && e.parameter) || {}, o;
  try { o = q.op ? admin_(q) : check_(q); }
  catch (err) { o = q.op ? { ok: false, status: 'error', error: String(err) } : { ok: true, status: 'error' }; } // الفحص يفشل بأمان (يسمح)
  return out_(q, o);
}

function out_(q, o) {
  var s = JSON.stringify(o), cb = String(q.callback || '');
  if (/^[A-Za-z_$][\w$]{0,80}$/.test(cb)) return ContentService.createTextOutput(cb + '(' + s + ')').setMimeType(ContentService.MimeType.JAVASCRIPT);
  return ContentService.createTextOutput(s).setMimeType(ContentService.MimeType.JSON);
}

var id_ = function (v) { return String(v || '').replace(/[^\w.-]/g, '').slice(0, 64); };
var str_ = function (v, n) { return String(v || '').slice(0, n); };

// قراءة من الذاكرة المؤقتة أولاً، وإذا ماكو نقرأ من Properties ونحفظ النتيجة (حتى «ماكو» ننحفظ كـ '0')
function get_(keys) {
  var c = C.getAll(keys), r = {}, put = {}, miss = false;
  keys.forEach(function (k) {
    if (c[k] != null) { r[k] = c[k] === '0' ? null : JSON.parse(c[k]); return; }
    var v = P.getProperty(k); r[k] = v ? JSON.parse(v) : null; put[k] = v || '0'; miss = true;
  });
  if (miss) C.putAll(put, TTL);
  return r;
}
function set_(k, v) { var s = JSON.stringify(v); P.setProperty(k, s); C.put(k, s, TTL); }
function del_(k) { P.deleteProperty(k); C.put(k, '0', TTL); }
function withLock_(f) { var l = LockService.getScriptLock(); l.waitLock(10000); try { return f(); } finally { l.releaseLock(); } }

// ---------- فحص الجهاز (من صفحة الكتاب) ----------
// book, id (الحساب), device, label, ip, ua, x=1 (مدير معفى من القفل), beat=1 (نبضة من كتاب مفتوح)
function check_(q) {
  var book = id_(q.book) || 'old', id = id_(q.id), dev = id_(q.device);
  if (!id || !dev) return { ok: true, status: 'noid' };
  var ak = 'a|' + book + '|' + id, bk = 'b|' + book + '|' + dev, kk = 'k|' + book + '|' + dev;
  var g = get_([ak, bk, kk]), now = Date.now();
  var info = { t: now, ip: str_(q.ip, 64), ua: str_(q.ua, 300), l: str_(q.label, 80) };

  if (g[bk]) return { ok: false, status: 'blocked' };
  if (g[kk]) { del_(kk); return { ok: false, status: 'kicked' }; }

  var st = 'ok';
  if (q.x == '1') {
    // حساب المدير: ما ينقفل، بس ينحفظ جهازه حتى يظهر بالجلسات
    var xk = 'x|' + book + '|' + id + '|' + dev, xr = get_([xk])[xk];
    if (!xr || now - (xr.t || 0) > 3600000) set_(xk, { d: dev, f: (xr && xr.f) || now, t: now, ip: info.ip, ua: info.ua, l: info.l || (xr && xr.l) || '' });
  } else {
    var a = g[ak];
    if (!a) {
      a = withLock_(function () {
        var v = P.getProperty(ak); if (v) return JSON.parse(v);
        var n = { d: dev, f: now, t: now, ip: info.ip, ua: info.ua, l: info.l }; set_(ak, n); st = 'new'; return n;
      });
    }
    if (a.d !== dev) {
      // محاولة من جهاز ثاني: تنحفظ مؤقتاً حتى تشوفها الإدارة
      C.put('r|' + book + '|' + id, JSON.stringify({ d: dev, t: now, ip: info.ip, ua: info.ua, l: info.l }), TTL);
      return { ok: false, status: 'locked' };
    }
    if (st !== 'new' && (now - (a.t || 0) > 3600000 || (info.l && info.l !== a.l))) {
      a.t = now; if (info.ip) a.ip = info.ip; if (info.ua) a.ua = info.ua; if (info.l) a.l = info.l; set_(ak, a);
    }
    if (!info.l) info.l = a.l || '';
  }
  C.put('s|' + book + '|' + id + '|' + dev, JSON.stringify(info), TTL);
  return { ok: true, status: st };
}

// ---------- الإدارة ----------
function admin_(q) {
  var key = String(q.key || ''), saved = P.getProperty('ADMIN_KEY');
  if (q.op === 'setup') {
    if (key.length < 24) return { ok: false, status: 'shortkey' };
    if (!saved) { P.setProperty('ADMIN_KEY', key); return { ok: true, status: 'claimed' }; }
    return saved === key ? { ok: true, status: 'ok' } : { ok: false, status: 'badkey' };
  }
  if (!saved || key !== saved) return { ok: false, status: 'badkey' };
  var book = id_(q.book), id = id_(q.id), dev = id_(q.device), now = Date.now();
  if (q.op === 'list') return list_(book);
  if (!book || !dev) return { ok: false, status: 'args' };
  return withLock_(function () {
    if (q.op === 'kick' || q.op === 'block') {
      var info = null;
      if (id) {
        var ak = 'a|' + book + '|' + id, a = P.getProperty(ak);
        if (a) { a = JSON.parse(a); if (a.d === dev) { info = a; del_(ak); } }
        var xk = 'x|' + book + '|' + id + '|' + dev, x = P.getProperty(xk);
        if (x) { info = info || JSON.parse(x); del_(xk); }
        C.remove('s|' + book + '|' + id + '|' + dev);
      }
      if (q.op === 'block') {
        info = info || {};
        set_('b|' + book + '|' + dev, { i: id, l: str_(q.label, 80) || info.l || '', ip: info.ip || '', ua: info.ua || '', t: now });
      } else set_('k|' + book + '|' + dev, { i: id, t: now });
      return { ok: true };
    }
    if (q.op === 'unblock') { del_('b|' + book + '|' + dev); return { ok: true }; }
    return { ok: false, status: 'op' };
  });
}

function list_(book) {
  var all = P.getProperties(), ses = [], blocked = [], skeys = [], rkeys = [];
  Object.keys(all).forEach(function (k) {
    var p = k.split('|'); if (book && p[1] !== book) return;
    var v; try { v = JSON.parse(all[k]); } catch (_) { return; }
    if (p[0] === 'a') { ses.push({ book: p[1], id: p[2], d: v.d, f: v.f, t: v.t, ip: v.ip, ua: v.ua, l: v.l }); skeys.push('s|' + p[1] + '|' + p[2] + '|' + v.d); rkeys.push('r|' + p[1] + '|' + p[2]); }
    else if (p[0] === 'x') { ses.push({ book: p[1], id: p[2], d: p[3], f: v.f, t: v.t, ip: v.ip, ua: v.ua, l: v.l, x: 1 }); skeys.push('s|' + p[1] + '|' + p[2] + '|' + p[3]); rkeys.push(''); }
    else if (p[0] === 'b') blocked.push({ book: p[1], d: p[2], id: v.i, l: v.l, ip: v.ip, ua: v.ua, t: v.t });
  });
  var s = skeys.length ? C.getAll(skeys) : {}, r = rkeys.length ? C.getAll(rkeys.filter(String)) : {};
  ses.forEach(function (x, i) {
    var c = s[skeys[i]]; if (c) { c = JSON.parse(c); x.t = Math.max(x.t || 0, c.t); if (c.ip) x.ip = c.ip; if (c.ua) x.ua = c.ua; if (c.l) x.l = c.l; }
    var a = rkeys[i] && r[rkeys[i]]; if (a) x.try = JSON.parse(a);
  });
  return { ok: true, now: Date.now(), sessions: ses, blocked: blocked };
}
