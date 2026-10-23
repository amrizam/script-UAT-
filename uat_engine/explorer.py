"""UAT generik untuk aplikasi web apa pun, tanpa paket skenario.

Alur: buka URL → cari form login otomatis → login → baca menu dari halaman setelah login. Menu-menu itu menjadi
modul UAT: tiap menu dibuka, diperiksa (status HTTP, pesan error, isi halaman, tabel/isian/tombol), lalu di-screenshot.
Ditambah test case Login (akun valid & akun salah) dan Logout.
"""
import json
import os
import re
import time
from urllib.parse import urlparse

from .browser import BrowserError

ERROR_TEXT = ["Page not found", "Halaman tidak ditemukan", "404 Not Found", "404 - File or directory not found",
              "Server Error", "Internal Server Error", "An unhandled exception", "Unhandled exception", "Stack trace",
              "Whoops, looks like something went wrong", "Something went wrong", "Terjadi kesalahan", "Application error",
              "Access Denied", "Akses ditolak", "403 Forbidden", "401 Unauthorized", "SQLSTATE", "Fatal error"]
LOGIN_PATH = re.compile(r"/(log-?in|sign-?in)\b", re.I)

# Fungsi JS bersama: kunci URL halaman (hash hanya dihitung untuk routing SPA: #/... atau #!...).
JS_COMMON = r"""
const clean = s => (s || '').replace(/\s+/g, ' ').trim();
const vis = e => !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length)) && getComputedStyle(e).visibility !== 'hidden';
const keyOf = raw => {
  if (!raw || raw === '#' || /^(javascript:|mailto:|tel:)/i.test(raw)) return null;
  if (raw.startsWith('#') && !/^#[!/]/.test(raw)) return null;
  let u; try { u = new URL(raw, location.href); } catch (e) { return null; }
  if (u.origin !== location.origin) return null;
  return u.origin + u.pathname + u.search + (/^#[!/]/.test(u.hash) ? u.hash : '');
};
const hrefOf = a => a.getAttribute('href') || a.getAttribute('routerlink') || a.getAttribute('data-href') || '';
const textOf = e => clean((e.innerText || '').split('\n').find(s => s.trim()) || e.textContent || e.value
                          || e.getAttribute('aria-label') || e.getAttribute('title'));
const LOGOUT_TEXT = /^(log\s*-?\s*out|logout|sign\s*-?\s*out|log\s*-?\s*off|keluar)(\s.*)?$/i;
const LOGOUT_HREF = /log-?out|sign-?out|log-?off/i;
"""

JS_MARK_LOGIN = "(() => {" + JS_COMMON + r"""
  document.querySelectorAll('[data-uat]').forEach(e => e.removeAttribute('data-uat'));
  const HINT = /user|email|login|akun|account|nik|nip|npk|name/i;
  const hint = e => HINT.test([e.name, e.id, e.autocomplete, e.placeholder, e.type, e.getAttribute('aria-label')].join(' '));
  const pw = [...document.querySelectorAll('input[type=password]')].find(vis);
  const scope = (pw && (pw.form || pw.closest('form, [role=form], .login, .card, main'))) || document;
  const texts = [...scope.querySelectorAll('input:not([type]), input[type=text], input[type=email], input[type=tel], input[type=number]')].filter(vis);
  let user = null;
  if (pw) {
    const before = texts.filter(e => e.compareDocumentPosition(pw) & Node.DOCUMENT_POSITION_FOLLOWING);
    user = before.find(hint) || before[before.length - 1] || null;
  } else {
    user = texts.find(e => hint(e) && !/search|cari|query|^q$/i.test(e.name + ' ' + e.id)) || null;
  }
  const form = (pw || user) && (pw || user).form;
  const WORD = /\b(log\s*-?\s*in|login|sign\s*-?\s*in|masuk|next|lanjut|berikutnya|continue|submit|kirim)\b/i;
  const btns = [...(form || scope).querySelectorAll('button, input[type=submit], input[type=button], [role=button]')].filter(vis);
  const submit = btns.find(b => b.type === 'submit' && WORD.test(textOf(b))) || btns.find(b => WORD.test(textOf(b)) && textOf(b).length <= 30)
                 || btns.find(b => b.type === 'submit' && b.getAttribute('type') === 'submit') || null;
  if (pw) pw.setAttribute('data-uat', 'pass');
  if (user) user.setAttribute('data-uat', 'user');
  if (submit) submit.setAttribute('data-uat', 'submit');
  return {pass: !!pw, user: !!user, submit: !!submit, submitText: submit ? textOf(submit) : '', title: document.title};
})()"""

JS_CLICK_LOGIN_LINK = "(() => {" + JS_COMMON + r"""
  const RX = /^(log\s*-?\s*in|login|sign\s*-?\s*in|masuk)\b/i;
  const el = [...document.querySelectorAll('a, button, [role=button]')].filter(vis).find(e => RX.test(textOf(e)));
  if (!el) return false;
  el.removeAttribute('target');
  el.click();
  return true;
})()"""

JS_HAS_LOGIN_LINK = "(() => {" + JS_COMMON + r"""
  return [...document.querySelectorAll('a, button, [role=button]')].filter(vis).some(e => /^(log\s*-?\s*in|login|sign\s*-?\s*in|masuk)$/i.test(textOf(e)));
})()"""

JS_FORM_SUBMIT = r"""(() => {
  const f = (document.querySelector('[data-uat=pass]') || document.querySelector('[data-uat=user]') || {}).form;
  if (!f) return false;
  f.requestSubmit ? f.requestSubmit() : f.submit();
  return true;
})()"""

JS_MENUS = "(() => {" + JS_COMMON + r"""
  const NAV = 'nav, aside, header, [role=navigation], [role=menubar], [role=menu], .sidebar, .navbar, .nav, .menu, #sidebar, #menu, [class*="sidebar"], [class*="menu"], [class*="nav"]';
  const SKIP_PATH = /\.(pdf|xlsx?|docx?|csv|zip|rar|png|jpe?g|gif|svg)$|\/(delete|hapus|remove|destroy)\b/i;
  const LANG = /[?&](lang|culture|locale|language)=|\/language\//i;
  const path = el => {
    const parts = [];
    while (el && el.nodeType === 1 && el !== document.body) {
      if (el.id && /^[A-Za-z][\w-]*$/.test(el.id)) { parts.unshift('#' + el.id); break; }
      let s = el.tagName.toLowerCase();
      const p = el.parentElement;
      if (p) { const same = [...p.children].filter(c => c.tagName === el.tagName); if (same.length > 1) s += ':nth-of-type(' + (same.indexOf(el) + 1) + ')'; }
      parts.unshift(s);
      el = p;
    }
    return parts.join(' > ');
  };
  const group = a => {
    const li = a.closest('li');
    const outer = li && li.parentElement ? li.parentElement.closest('li') : null;
    if (outer) {
      const lab = [...outer.children].find(c => !c.contains(a) && clean(c.textContent));
      if (lab) return textOf(lab);
    }
    const d = a.closest('details');
    if (d) { const s = d.querySelector('summary'); if (s && !s.contains(a)) return textOf(s); }
    const col = a.closest('.collapse, .submenu, .sub-menu, .dropdown-menu, [role=menu]');
    if (col) {
      const id = col.id;
      let t = id ? document.querySelector('[href="#' + id + '"], [data-target="#' + id + '"], [data-bs-target="#' + id + '"], [aria-controls="' + id + '"]') : null;
      t = t || col.previousElementSibling;
      if (t && !t.contains(a)) return textOf(t);
    }
    return '';
  };
  const all = [...document.querySelectorAll('a[href], [routerlink], [data-href]')];
  const inNav = all.filter(a => a.closest(NAV));
  const seen = new Set();
  const out = [];
  for (const a of (inNav.length >= 2 ? inNav : all)) {
    const raw = hrefOf(a), key = keyOf(raw), text = textOf(a);
    if (!key || !text || seen.has(key) || a.hasAttribute('download')) continue;
    const u = new URL(key);
    if (LOGOUT_TEXT.test(text) || LOGOUT_HREF.test(u.pathname) || SKIP_PATH.test(u.pathname) || LANG.test(u.pathname + u.search)) continue;
    seen.add(key);
    out.push({text: text.slice(0, 80), group: group(a).slice(0, 60), url: key, selector: path(a)});
  }
  return out;
})()"""

JS_CLICK_MENU = "(([sel, key]) => {" + JS_COMMON + r"""
  const el = document.querySelector(sel);
  if (!el || !vis(el) || keyOf(hrefOf(el)) !== key) return false;
  el.removeAttribute('target');
  el.click();
  return true;
})(%s)"""

JS_CLICK_LOGOUT = "(() => {" + JS_COMMON + r"""
  const c = [...document.querySelectorAll('a, button, input[type=submit], [role=menuitem], [role=button]')].filter(e =>
    (textOf(e).length <= 40 && LOGOUT_TEXT.test(textOf(e))) || LOGOUT_HREF.test(e.getAttribute('href') || '')
    || (e.form && e.type === 'submit' && LOGOUT_HREF.test(e.form.getAttribute('action') || '')));
  if (!c.length) return null;
  const el = c.find(vis) || c[0];
  const label = textOf(el) || 'Logout';
  el.removeAttribute('target');
  el.click();
  return label;
})()"""

JS_PAGE = "((ERR) => {" + JS_COMMON + r"""
  const inNav = e => e.closest('nav, aside, header, [role=navigation], .sidebar, .navbar');
  const h = [...document.querySelectorAll('main h1, h1, .page-title, .content-header h1, .page-header, main h2, h2, .card-title')]
            .find(e => vis(e) && !inNav(e) && clean(e.innerText));
  const body = document.body ? document.body.innerText : '';
  const tables = [...document.querySelectorAll('table')].filter(vis).slice(0, 3).map(t => ({
    cols: [...t.querySelectorAll('thead th, tr:first-child th')].map(x => clean(x.innerText)).filter(Boolean).slice(0, 10),
    rows: t.querySelectorAll('tbody tr').length}));
  const label = e => clean((e.labels && e.labels[0] && e.labels[0].innerText) || e.getAttribute('aria-label') || e.placeholder || e.name || e.id);
  const fields = [...document.querySelectorAll('input, select, textarea')]
    .filter(e => vis(e) && !inNav(e) && !['hidden', 'submit', 'button', 'reset', 'checkbox', 'radio'].includes(e.type)).map(label).filter(Boolean);
  const buttons = [...document.querySelectorAll('button, input[type=submit], input[type=button], a.btn, [role=button]')]
    .filter(e => vis(e) && !inNav(e)).map(textOf).filter(t => t && t.length <= 40 && !LOGOUT_TEXT.test(t));
  return {heading: h ? clean(h.innerText).slice(0, 120) : '', title: document.title, text: clean(body).length,
          errors: ERR.filter(t => body.includes(t) || document.title.includes(t)),
          tables, fields: [...new Set(fields)].slice(0, 12), buttons: [...new Set(buttons)].slice(0, 12)};
})(%s)"""

JS_LINES = "(document.body ? document.body.innerText : '').split('\\n').map(s => s.trim()).filter(Boolean)"


class Blocked(Exception):
    pass


class LoginError(Exception):
    pass


def app_name(title, url):
    """Nama aplikasi dari judul halaman login ("Sign in · Portal Tenant" → "Portal Tenant"), cadangan: nama host."""
    parts = [p.strip() for p in re.split(r"\s*[|·–—]\s*|\s+[-:]\s+", title or "") if p.strip()]
    parts = [p for p in parts if not re.search(r"\b(log\s*-?\s*in|login|sign\s*-?\s*in|masuk|home|beranda|dashboard|welcome|selamat datang)\b", p, re.I)]
    return max(parts, key=len) if parts else (urlparse(url).hostname or url)


def menu_title(m):
    return f"{m['group']} > {m['text']}" if m.get("group") else m["text"]


class Explorer:
    def __init__(self, browser, url, user, password, log=print):
        self.b = browser
        self.url = url
        self.user = user
        self.password = password
        self.log = log
        self.shots = None
        self.home = None            # URL halaman pertama setelah login
        self.login_url = None
        self.logged_in = False
        self.app = None
        self.stamp = time.strftime("%H%M%S")

    # ── utilitas ────────────────────────────────────────────────────────
    def rel(self, url):
        u = urlparse(url or "")
        return (u.path or "/") + (f"?{u.query}" if u.query else "") + (f"#{u.fragment}" if u.fragment else "")

    def _wait(self, cond, timeout):
        end = time.time() + timeout
        while True:
            try:
                if cond():
                    return True
            except BrowserError:
                pass
            if time.time() >= end:
                return False
            self.b.pump(0.25)

    def logged_out_page(self):
        """Halaman saat ini adalah halaman login / halaman publik dengan tombol Login."""
        return self.b.visible("input[type=password]") or bool(LOGIN_PATH.search(urlparse(self.b.url()).path)) \
            or bool(self.b.eval(JS_HAS_LOGIN_LINK))

    def shot(self, tc, caption):
        n = len(tc["images"]) + 1
        path = os.path.join(self.shots, f"{tc['id']}_{n}.png")
        try:
            self.b.eval("window.scrollTo(0, 0); true")
            self.b.screenshot(path)
            tc["images"].append((path, f"Gambar {tc['id']}_{n} – {caption}"))
        except BrowserError as e:
            tc["notes"].append(f"Screenshot '{caption}' gagal diambil: {e}")

    @staticmethod
    def fail(tc, line):
        tc["actual"].append(line)
        tc["status"] = "Fail"

    # ── login ───────────────────────────────────────────────────────────
    def reset(self):
        self.b.clear_session()
        self.logged_in = False

    def open_login(self):
        """Buka URL; bila belum ada form login, klik tautan/tombol Login. Kembalikan hasil deteksi form."""
        self.b.goto(self.url)
        st = {}
        if not self._wait(lambda: st.update(self.b.eval(JS_MARK_LOGIN)) or st.get("pass"), 5) and \
                self.b.eval(JS_CLICK_LOGIN_LINK):
            self.b.settle()
            self._wait(lambda: st.update(self.b.eval(JS_MARK_LOGIN)) or st.get("pass"), 5)
        if not st.get("pass") and not st.get("user"):
            raise LoginError(f"Form login tidak ditemukan di {self.b.url()}.")
        self.login_url = self.b.url()
        self.app = self.app or app_name(st.get("title"), self.url)
        return st

    def _submit(self, st):
        if st.get("submit"):
            self.b.click("[data-uat=submit]")
        elif self.b.eval(JS_FORM_SUBMIT):
            self.b.settle()
        else:
            self.b.press_enter("[data-uat=pass]" if st.get("pass") else "[data-uat=user]")

    def submit(self, st, user, password, shot=None):
        """Isi dan kirim form login. Kembalikan (berhasil, [teks baru di halaman, mis. pesan error])."""
        if not st.get("pass"):  # login dua langkah: user dulu, password di halaman berikutnya
            self.b.fill("[data-uat=user]", user)
            self._submit(st)
            if not self._wait(lambda: st.update(self.b.eval(JS_MARK_LOGIN)) or st.get("pass"), 15):
                return False, self.b.messages("[role=alert], .alert, .error, .invalid-feedback, .text-danger")
        elif st.get("user"):
            self.b.fill("[data-uat=user]", user)
        self.b.fill("[data-uat=pass]", password)
        if shot:
            shot("Form login terisi")
        before = set(self.b.eval(JS_LINES) or [])
        self.b.last_dialog = None
        self._submit(st)
        ok = self._wait(lambda: not self.b.visible("input[type=password]"), 15)
        new = [s for s in (self.b.eval(JS_LINES) or []) if s not in before and len(s) <= 200]
        if self.b.last_dialog:
            new.insert(0, self.b.last_dialog)
        return ok, new

    def login(self):
        self.reset()
        ok, msgs = self.submit(self.open_login(), self.user, self.password)
        if not ok:
            raise LoginError(f"Login sebagai {self.user} gagal: " + ("; ".join(msgs[:3]) if msgs else "tetap di halaman login") + ".")
        self.logged_in = True
        self.home = self.b.url()

    def ensure_login(self):
        if not self.logged_in:
            try:
                self.login()
            except LoginError as e:
                raise Blocked(str(e))

    # ── menu ────────────────────────────────────────────────────────────
    def discover(self):
        """Baca menu dari halaman setelah login."""
        self.ensure_login()
        if self.b.url() != self.home:
            self.b.goto(self.home)
        self._wait(lambda: self.b.count("a[href]") > 0, 5)
        menus = []
        for m in self.b.eval(JS_MENUS) or []:
            if self.login_url and m["url"].rstrip("/") == self.login_url.rstrip("/"):
                continue
            m["title"] = menu_title(m)
            menus.append(m)
        return menus

    def open_menu(self, m):
        self.b.last_doc_status = None
        if m.get("selector") and self.b.eval(JS_CLICK_MENU % json.dumps([m["selector"], m["url"]])):
            self.b.settle()
            return True
        self.b.goto(m["url"])
        return False

    # ── test case ───────────────────────────────────────────────────────
    def plan(self, item):
        """Test case (judul, fungsi) untuk satu modul."""
        if item["kind"] == "login":
            return [("Login dengan akun valid", self.tc_login),
                    ("Login gagal dengan user/password yang salah", self.tc_login_invalid)]
        if item["kind"] == "logout":
            return [("Logout dan akses halaman setelah logout", self.tc_logout)]
        return [(f"Membuka menu {item['title']}", lambda tc: self.tc_menu(tc, item))]

    def run(self, tc_id, scenario, fn):
        tc = {"id": tc_id, "scenario": scenario, "pre": "", "steps": [], "expected": "", "actual": [], "status": "Pass",
              "notes": [], "images": []}
        self.b.console_errors.clear()
        self.b.set_viewport("desktop")
        try:
            fn(tc)
        except Blocked as e:
            tc["status"] = "Blocked"
            tc["notes"].insert(0, str(e))
        except (BrowserError, LoginError) as e:
            self.fail(tc, f"Langkah tidak dapat dijalankan: {e}")
        errs = list(dict.fromkeys(e for e in self.b.console_errors if e))[:3]
        if errs:
            tc["notes"].append("Error JavaScript di browser: " + " | ".join(errs))
        if not tc["actual"]:
            tc["actual"].append("Langkah dijalankan tanpa pemeriksaan otomatis.")
        return tc

    def tc_login(self, tc):
        self.reset()
        st = self.open_login()
        tc.update(pre=f"Akun {self.user} sudah terdaftar dan aktif.",
                  steps=[f"Buka {self.url}", f"Isi user dengan {self.user} dan isi password",
                         f"Klik tombol '{st.get('submitText') or 'Login'}'"],
                  expected="User berhasil login dan diarahkan ke halaman utama aplikasi.")
        tc["actual"].append(f"Halaman login tampil ({self.rel(self.login_url)}).")
        ok, msgs = self.submit(st, self.user, self.password, shot=lambda c: self.shot(tc, c))
        if not ok:
            self.fail(tc, "Login gagal, user tetap di halaman login" + (": " + "; ".join(msgs[:3]) if msgs else "") + ".")
            self.shot(tc, "Login gagal")
            return
        self.logged_in = True
        self.home = self.b.url()
        info = self.b.eval(JS_PAGE % json.dumps(ERROR_TEXT))
        tc["actual"].append(f"Login berhasil, user diarahkan ke halaman '{info['heading'] or info['title']}' ({self.rel(self.home)}).")
        self.shot(tc, "Halaman setelah login")

    def tc_login_invalid(self, tc):
        self.reset()
        st = self.open_login()
        wrong = f"uat.salah.{self.stamp}@example.com"
        tc.update(pre="User belum login.",
                  steps=[f"Buka {self.url}", f"Isi user dengan akun yang tidak terdaftar ({wrong}) dan password sembarang",
                         f"Klik tombol '{st.get('submitText') or 'Login'}'"],
                  expected="Login ditolak: user tetap di halaman login dan sistem menampilkan pesan kesalahan.")
        ok, msgs = self.submit(st, wrong, f"Salah#{self.stamp}")
        self.shot(tc, "Login dengan akun yang salah")
        if ok:
            self.fail(tc, "Login dengan akun yang tidak terdaftar justru berhasil masuk.")
            self.reset()
            return
        tc["actual"].append("Login ditolak, user tetap di halaman login.")
        if msgs:
            tc["actual"].append("Pesan yang tampil: '" + "'; '".join(msgs[:3]) + "'.")
        else:
            tc["notes"].append("Tidak terdeteksi pesan kesalahan baru di halaman; periksa screenshot.")

    def tc_menu(self, tc, m):
        label = m["title"]
        tc.update(pre=f"User sudah login sebagai {self.user}.",
                  steps=[f"Klik menu '{label}'", "Periksa judul, isi halaman, dan pesan error"],
                  expected=f"Halaman {label} terbuka tanpa error dan menampilkan data/fitur sesuai hak akses user.")
        self.ensure_login()
        clicked = self.open_menu(m)
        if self.b.visible("input[type=password]"):  # sesi berakhir: login ulang sekali
            self.logged_in = False
            self.ensure_login()
            clicked = self.open_menu(m)
            if self.b.visible("input[type=password]"):
                self.fail(tc, "Membuka menu justru diarahkan ke halaman login (akses ditolak atau sesi berakhir).")
                self.shot(tc, f"Halaman {label}")
                return
        if not clicked:
            tc["notes"].append(f"Menu tidak terlihat di halaman aktif; dibuka langsung melalui URL {self.rel(m['url'])}.")
        status = self.b.last_doc_status
        info = self.b.eval(JS_PAGE % json.dumps(ERROR_TEXT))
        tc["actual"].append(f"Halaman '{info['heading'] or info['title'] or '-'}' tampil ({self.rel(self.b.url())}).")
        if status and status >= 400:
            self.fail(tc, f"Server mengembalikan HTTP {status}.")
        if not info["text"]:
            self.fail(tc, "Halaman kosong.")
        if info["errors"]:
            self.fail(tc, "Halaman menampilkan pesan error: '" + "', '".join(info["errors"]) + "'.")
        elif status is None or status < 400:
            tc["actual"].append("Tidak ada pesan error di halaman.")
        for t in info["tables"]:
            tc["actual"].append(f"Tabel menampilkan {t['rows']} baris data" + (f" dengan kolom {', '.join(t['cols'])}." if t["cols"] else "."))
        if info["fields"]:
            tc["actual"].append("Isian/filter yang tersedia: " + ", ".join(info["fields"]) + ".")
        if info["buttons"]:
            tc["actual"].append("Tombol yang tersedia: " + ", ".join(info["buttons"]) + ".")
        self.shot(tc, f"Halaman {label}")

    def tc_logout(self, tc):
        tc.update(pre=f"User sudah login sebagai {self.user}.",
                  steps=["Klik menu/tombol logout", "Buka kembali halaman utama aplikasi tanpa login"],
                  expected="User keluar dan diarahkan ke halaman login; halaman aplikasi tidak dapat dibuka lagi sebelum login ulang.")
        self.ensure_login()
        if self.b.url() != self.home:
            self.b.goto(self.home)
        label = self.b.eval(JS_CLICK_LOGOUT)
        if not label:
            raise Blocked("Menu/tombol logout tidak ditemukan di halaman.")
        tc["steps"][0] = f"Klik '{label}'"
        self.b.settle()
        self._wait(self.logged_out_page, 10)
        self.logged_in = False
        tc["actual"].append(f"Setelah '{label}' diklik, user diarahkan ke {self.rel(self.b.url())}"
                            + (" (halaman login)." if self.b.visible("input[type=password]") else "."))
        self.shot(tc, "Setelah logout")
        self.b.goto(self.home)
        if self.logged_out_page():
            tc["actual"].append(f"Membuka kembali {self.rel(self.home)} tanpa login mengarahkan user ke halaman login.")
        else:
            self.fail(tc, f"Halaman {self.rel(self.home)} masih dapat dibuka setelah logout.")
        self.shot(tc, "Membuka halaman setelah logout")
