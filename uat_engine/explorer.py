"""UAT generik untuk aplikasi web apa pun, tanpa paket skenario.

Alur: buka URL → cari form login otomatis → login → baca menu dari halaman setelah login. Menu-menu itu menjadi
modul UAT: tiap menu dibuka, diperiksa (status HTTP, pesan error, isi halaman, tabel/isian/tombol), lalu di-screenshot.
Ditambah test case Login (akun valid & akun salah) dan Logout.

Uji CRUD (opsional, crud=True) untuk menu yang punya tombol Tambah/Add: tambah data uji berpenanda unik "UAT…", validasi
form kosong, cari & lihat detail, ubah, lalu hapus. Ubah dan hapus hanya dilakukan pada baris yang berisi penanda data uji
itu sendiri, jadi data lain di aplikasi tidak disentuh.
"""
import base64
import datetime
import json
import os
import re
import tempfile
import time
from urllib.parse import urlparse

from .browser import BrowserError

ERROR_TEXT = ["Page not found", "Halaman tidak ditemukan", "404 Not Found", "404 - File or directory not found",
              "Server Error", "Internal Server Error", "An unhandled exception", "Unhandled exception", "Stack trace",
              "Whoops, looks like something went wrong", "Something went wrong", "Terjadi kesalahan", "Application error",
              "Access Denied", "Akses ditolak", "403 Forbidden", "401 Unauthorized", "SQLSTATE", "Fatal error"]
LOGIN_PATH = re.compile(r"/(log-?in|sign-?in)\b", re.I)
SUCCESS = re.compile(r"berhasil|sukses|success|tersimpan|disimpan|saved|created|added|ditambahkan|diperbarui|diubah|updated|"
                     r"dihapus|terhapus|deleted|removed", re.I)
FAILURE = re.compile(r"wajib|required|harus diisi|tidak boleh|invalid|tidak valid|gagal|error|failed|must|sudah ada|already|"
                     r"exists|tidak sesuai|minimal|maksimal|at least|at most|please fill|please select|isi kolom", re.I)
PLACEHOLDER = re.compile(r"^\s*(-+|pilih|select|choose|silakan|please|semua|all|none)\b", re.I)
PNG_1PX = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
PDF_MIN = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj "
           b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")

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
const inChrome = e => !!e.closest('nav, aside, header, [role=navigation], .sidebar, .navbar');
const groupOf = e => e.closest('.form-group, .mb-3, .form-item, .field, .form-floating, .el-form-item, .ant-form-item, tr');
const labelOf = e => {
  const g = groupOf(e);
  const l = (e.labels && e.labels[0]) || (g && g.querySelector('label'));
  const cell = g && g.tagName === 'TR' && g.cells[0] && !g.cells[0].contains(e) ? g.cells[0].innerText : '';
  return clean((l && l.innerText) || cell || e.getAttribute('aria-label') || e.placeholder || e.name || e.id || '').replace(/\s*[*:]+\s*$/, '').slice(0, 60);
};
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

# ── CRUD ────────────────────────────────────────────────────────────────
JS_CLEAR_MARKS = r"""(() => {
  for (const a of ['data-uat', 'data-uat-form', 'data-uat-f', 'data-uat-pre', 'data-uat-row'])
    document.querySelectorAll('[' + a + ']').forEach(e => e.removeAttribute(a));
  return true;
})()"""

JS_FIND_CREATE = "(() => {" + JS_COMMON + r"""
  const RX = /^(\+\s*)?(tambah|add|create|new|baru|buat|input|insert)\b|^\+$/i;
  const sig = e => [textOf(e), e.getAttribute('title'), e.getAttribute('aria-label'), e.getAttribute('data-original-title'),
                    e.getAttribute('data-bs-original-title')].map(clean).find(s => s && RX.test(s));
  const el = [...document.querySelectorAll('a, button, [role=button], input[type=button], input[type=submit]')]
    .filter(e => vis(e) && !inChrome(e) && !e.closest('tbody, tr, .dataTables_filter, .modal, [role=dialog]')).find(sig);
  if (!el) return null;
  el.setAttribute('data-uat', 'create');
  const f = el.form;
  const inline = !!f && el.type === 'submit' && [...f.querySelectorAll('input, select, textarea')]
    .some(x => vis(x) && !['hidden', 'submit', 'button', 'search'].includes(x.type));
  return {label: sig(el), inline};
})()"""

JS_PRE_MARK = r"""(() => {
  document.querySelectorAll('input, select, textarea, [contenteditable]').forEach(e => e.setAttribute('data-uat-pre', '1'));
  return true;
})()"""

# Pilih wadah form (modal / form / halaman), tandai tiap field dengan data-uat-f, kembalikan keterangannya.
JS_FORM_FIELDS = "((inline) => {" + JS_COMMON + r"""
  const s2 = e => e.tagName === 'SELECT' && !!e.nextElementSibling && /select2|chosen/.test(e.nextElementSibling.className || '') && vis(e.nextElementSibling);
  const SKIP = ['hidden', 'submit', 'button', 'reset', 'image', 'search'];
  const ok = (e, pre) => !e.disabled && !(pre && e.hasAttribute('data-uat-pre')) && !inChrome(e)
    && !SKIP.includes((e.type || '').toLowerCase()) && (vis(e) || s2(e) || (e.type === 'file' && e.required));
  const fieldsIn = (root, pre) => [...root.querySelectorAll('input, select, textarea, [contenteditable="true"], [contenteditable=""]')].filter(e => ok(e, pre));
  let box = document.querySelector('[data-uat-form]');
  if (!box) {
    if (inline) { const c = document.querySelector('[data-uat=create]'); box = c && c.form; }
    box = box || [...document.querySelectorAll('.modal.show, .modal.in, .modal[style*="block"], [role=dialog], dialog[open], .offcanvas.show')]
                   .filter(vis).find(d => fieldsIn(d, true).length)
      || [...document.querySelectorAll('form')].filter(f => vis(f) && fieldsIn(f, true).length)
                   .sort((a, b) => fieldsIn(b, true).length - fieldsIn(a, true).length)[0]
      || (fieldsIn(document.body, true).length ? document.body : null);
    if (!box) return null;
    box.setAttribute('data-uat-form', '1');
  }
  const PH = /^\s*(-+|pilih|select|choose|silakan|please|semua|all|none)\b/i;
  const req = e => {
    const g = groupOf(e), l = (e.labels && e.labels[0]) || (g && g.querySelector('label'));
    return e.required || e.getAttribute('aria-required') === 'true' || !!(l && /\*/.test(l.innerText)) || !!(g && /\brequired\b/.test(g.className || ''));
  };
  return fieldsIn(box, !inline).map((e, i) => {
    e.setAttribute('data-uat-f', i);
    const t = e.isContentEditable && !('value' in e) ? 'contenteditable' : (e.type || '').toLowerCase();
    const opt = e.tagName === 'SELECT' && e.selectedIndex >= 0 ? clean(e.options[e.selectedIndex].text) : '';
    return {i, tag: e.tagName.toLowerCase(), type: t, name: e.name || '', id: e.id || '', label: labelOf(e), required: req(e),
            readonly: !!e.readOnly, maxlength: e.maxLength > 0 ? e.maxLength : 0, min: e.min || '', pattern: e.pattern || '',
            placeholder: e.placeholder || '', value: t === 'contenteditable' ? clean(e.innerText) : (e.value || ''),
            emptySelect: e.tagName === 'SELECT' && (!e.value || PH.test(opt)), checked: !!e.checked,
            groupChecked: e.type === 'radio' && !!(e.form || document).querySelector('input[type=radio][name="' + CSS.escape(e.name) + '"]:checked'),
            accept: e.accept || '', files: e.files ? e.files.length : 0};
  });
})(%s)"""

JS_SELECT_FIRST = r"""((sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const PH = /^\s*(-+|pilih|select|choose|silakan|please|semua|all|none)\b/i;
  const o = [...el.options].find(o => !o.disabled && o.value !== '' && !PH.test(o.text));
  if (!o) return null;
  el.value = o.value;
  el.dispatchEvent(new Event('input', {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
  return o.text.replace(/\s+/g, ' ').trim();
})(%s)"""

JS_SET_CE = r"""(([sel, v]) => {
  const el = document.querySelector(sel);
  el.focus();
  el.innerText = v;
  el.dispatchEvent(new InputEvent('input', {bubbles: true}));
  return true;
})(%s)"""

JS_MARK_SAVE = "((inline) => {" + JS_COMMON + r"""
  document.querySelectorAll('[data-uat=save]').forEach(e => e.removeAttribute('data-uat'));
  const box = document.querySelector('[data-uat-form]');
  if (!box) return null;
  const scope = box.closest('.modal, [role=dialog], dialog, .offcanvas') || box;
  const SAVE = /^(simpan|save|submit|kirim|tambah|add|create|buat|ok|proses|update|perbarui|ubah|apply|terapkan|selesai|done|send)\b/i;
  const NO = /batal|cancel|tutup|close|kembali|back|reset|hapus|delete|clear/i;
  const btns = [...scope.querySelectorAll('button, input[type=submit], input[type=button], a.btn, [role=button]')]
    .filter(b => vis(b) && !inChrome(b) && !NO.test(textOf(b)) && (inline || b.getAttribute('data-uat') !== 'create'));
  const el = btns.find(b => b.type === 'submit' && SAVE.test(textOf(b))) || btns.find(b => SAVE.test(textOf(b)))
             || btns.find(b => b.type === 'submit' && b.getAttribute('type') === 'submit') || null;
  if (!el) return null;
  el.setAttribute('data-uat', 'save');
  return textOf(el) || 'Simpan';
})(%s)"""

JS_FORM_SUBMIT2 = r"""(() => {
  const b = document.querySelector('[data-uat-form]');
  const f = b && (b.tagName === 'FORM' ? b : b.querySelector('form'));
  if (!f) return false;
  f.requestSubmit ? f.requestSubmit() : f.submit();
  return true;
})()"""

JS_MESSAGES = "(() => {" + JS_COMMON + r"""
  const SEL = '.alert, [role=alert], [role=status], .toast, .swal2-title, .swal2-html-container, .swal-title, .swal-text, .notification, '
    + '.notyf__message, .iziToast-message, .noty_body, .invalid-feedback, .text-danger, .text-success, .error, .errors, .field-validation-error, '
    + '.validation-summary-errors, .help-block, .el-message, .el-form-item__error, .ant-message, .ant-form-item-explain, .v-snack__content, '
    + '.Toastify__toast, .flash, .message, .msg';
  return [...new Set([...document.querySelectorAll(SEL)].filter(vis).map(e => clean(e.innerText)).filter(t => t.length >= 3 && t.length <= 300))];
})()"""

JS_INVALID = "(() => {" + JS_COMMON + r"""
  const box = document.querySelector('[data-uat-form]');
  if (!box || !vis(box)) return [];
  return [...box.querySelectorAll('input, select, textarea')].filter(e => e.willValidate && !e.checkValidity())
    .map(e => (labelOf(e) ? labelOf(e) + ': ' : '') + e.validationMessage).slice(0, 8);
})()"""

JS_CONFIRM = "(() => {" + JS_COMMON + r"""
  document.querySelectorAll('[data-uat=confirm]').forEach(e => e.removeAttribute('data-uat'));
  const YES = /^(ya|yes|ok|oke|okay|simpan|save|lanjut|lanjutkan|continue|confirm|konfirmasi|hapus|delete|yakin|setuju|proceed)\b/i;
  const box = document.querySelector('[data-uat-form]');
  const dlgs = [...document.querySelectorAll('.swal2-popup, .swal-modal, .bootbox, .jconfirm-box, .modal.show, .modal.in, .modal[style*="block"], '
                                           + '[role=alertdialog], [role=dialog], dialog[open]')]
    .filter(d => vis(d) && !(box && box !== document.body && (d.contains(box) || box.contains(d))));
  for (const d of dlgs) {
    const b = [...d.querySelectorAll('button, a.btn, [role=button], input[type=button], input[type=submit]')].filter(vis).find(x => YES.test(textOf(x)));
    if (b) { b.setAttribute('data-uat', 'confirm'); return {label: textOf(b), text: clean(d.innerText).slice(0, 200)}; }
  }
  return null;
})()"""

JS_FIND_ROW = "((mk) => {" + JS_COMMON + r"""
  document.querySelectorAll('[data-uat-row]').forEach(e => e.removeAttribute('data-uat-row'));
  const c = [...document.querySelectorAll('tr, [role=row], .card, .list-group-item, li, .item')]
    .filter(e => vis(e) && !inChrome(e) && (e.innerText || '').includes(mk) && !e.querySelector('table')
                 && !e.closest('.alert, [role=alert], [role=status], .toast, .swal2-popup, .notification'));
  if (!c.length) return null;
  c.sort((a, b) => a.innerText.length - b.innerText.length);
  const r = c.find(e => e.querySelector('a, button')) || c[0];
  r.setAttribute('data-uat-row', '1');
  return clean(r.innerText).slice(0, 200);
})(%s)"""

JS_SEARCH_MARK = "(() => {" + JS_COMMON + r"""
  const el = [...document.querySelectorAll('input[type=search], .dataTables_filter input, input[name*=search i], input[name*=cari i], '
      + 'input[name*=keyword i], input[name=q], input[placeholder*=search i], input[placeholder*=cari i], input[id*=search i]')]
    .find(e => vis(e) && !inChrome(e));
  if (!el) return false;
  el.setAttribute('data-uat', 'search');
  return true;
})()"""

# Klik tombol aksi (edit / delete / view) di dalam baris data uji yang sudah ditandai data-uat-row.
JS_ROW_ACTION = "((kind) => {" + JS_COMMON + r"""
  const RX = {edit: /\b(edit|ubah|update|perbarui|pencil|pen)\b/i, delete: /\b(hapus|delete|remove|trash|destroy)\b|trash/i,
              view: /\b(detail|details|lihat|view|show|preview|eye)\b/i};
  const row = document.querySelector('[data-uat-row]');
  if (!row) return null;
  const sig = e => [textOf(e), e.getAttribute('title'), e.getAttribute('aria-label'), e.getAttribute('data-original-title'),
    e.getAttribute('data-bs-original-title'), e.getAttribute('href'), String(e.getAttribute('class') || ''),
    ...[...e.querySelectorAll('i, svg, span, img')].map(x => [x.getAttribute('class'), x.getAttribute('data-icon'), x.getAttribute('alt')].join(' '))].join(' ');
  const others = Object.keys(RX).filter(k => k !== kind && k !== 'view');
  const els = [...row.querySelectorAll('a, button, [role=button], [role=menuitem], input[type=submit], input[type=button]')]
    .filter(e => RX[kind].test(sig(e)) && others.every(k => !RX[k].test(sig(e))));
  const el = els.find(vis) || els[0];
  if (!el) return null;
  const label = textOf(el) || clean(el.getAttribute('title') || el.getAttribute('aria-label') || el.getAttribute('data-original-title') || '')
                || {edit: 'Ubah', delete: 'Hapus', view: 'Lihat'}[kind];
  el.removeAttribute('target');
  el.click();
  return label;
})(%s)"""

JS_DIALOG_TITLE = "(() => {" + JS_COMMON + r"""
  const d = [...document.querySelectorAll('.modal.show, .modal.in, .modal[style*="block"], [role=dialog], dialog[open], .offcanvas.show')].find(vis);
  const h = d && d.querySelector('h1, h2, h3, h4, h5, .modal-title');
  return h ? clean(h.innerText) : null;
})()"""

JS_HAS_TEXT = r"""((mk) => (document.body.innerText || '').includes(mk)
  || [...document.querySelectorAll('input, textarea')].some(e => (e.value || '').includes(mk)))(%s)"""


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
    def __init__(self, browser, url, user, password, log=print, crud=False):
        self.b = browser
        self.crud = crud
        self.caps = {}              # url menu -> {"create": label tombol tambah, "required": form punya field wajib}
        self.created = {}           # url menu -> penanda data uji yang ada di aplikasi (belum dihapus)
        self.unverified = {}        # url menu -> penanda data uji yang mungkin tersimpan tapi tidak ditemukan di daftar
        self.seq = 0
        self.run_id = datetime.datetime.now().strftime("%m%d%H%M")
        self._samples = None
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
        return self._menu_plan(item)

    def _menu_plan(self, m):
        """Generator: test case CRUD baru diketahui setelah halaman menu dibuka (ada tombol Tambah atau tidak)."""
        t = m["title"]
        yield f"Membuka menu {t}", lambda tc: self.tc_menu(tc, m)
        if not (self.crud and self.caps.get(m["url"], {}).get("create")):
            return
        yield f"Menambah data baru di menu {t}", lambda tc: self.tc_create(tc, m)
        if self.caps[m["url"]].get("required"):
            yield f"Validasi field wajib saat menambah data di menu {t}", lambda tc: self.tc_validate(tc, m)
        yield f"Mencari dan melihat detail data di menu {t}", lambda tc: self.tc_read(tc, m)
        yield f"Mengubah data di menu {t}", lambda tc: self.tc_update(tc, m)
        yield f"Menghapus data di menu {t}", lambda tc: self.tc_delete(tc, m)

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
        create = self.b.eval(JS_FIND_CREATE)
        self.caps[m["url"]] = {"create": create["label"] if create else None}
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

    # ── CRUD: bantuan ───────────────────────────────────────────────────
    def leftovers(self):
        """Data uji yang (mungkin) masih ada di aplikasi: [(url menu, penanda)]."""
        return list(self.created.items()) + list(self.unverified.items())

    def samples(self):
        if not self._samples:
            d = os.path.join(tempfile.gettempdir(), "uat_samples")
            os.makedirs(d, exist_ok=True)
            self._samples = {"png": os.path.join(d, "uat_lampiran.png"), "pdf": os.path.join(d, "uat_lampiran.pdf")}
            for k, data in (("png", PNG_1PX), ("pdf", PDF_MIN)):
                with open(self._samples[k], "wb") as f:
                    f.write(data)
        return self._samples

    def open_list(self, m):
        if self.b.url() == m["url"]:
            self.b.reload()
        else:
            self.b.goto(m["url"])
        if self.b.visible("input[type=password]"):  # sesi berakhir
            self.logged_in = False
            self.ensure_login()
            self.b.goto(m["url"])
        self.b.eval(JS_CLEAR_MARKS)

    def open_form(self, m):
        """Dari halaman daftar klik tombol Tambah; kembalikan (info tombol, field form)."""
        self.open_list(m)
        c = self.b.eval(JS_FIND_CREATE)
        if not c:
            raise Blocked(f"Tombol tambah data tidak ditemukan di menu {m['title']}.")
        self.b.eval(JS_PRE_MARK)
        if not c["inline"]:
            self.b.click("[data-uat=create]")
            self._wait(lambda: self.b.eval(JS_FORM_FIELDS % "false"), 8)
        fields = self.b.eval(JS_FORM_FIELDS % json.dumps(c["inline"]))
        if not fields:
            raise Blocked(f"Form tambah data tidak terdeteksi setelah klik '{c['label']}'.")
        return c, fields

    def field_value(self, f, marker):
        t = f["type"]
        hint = " ".join((f["name"], f["id"], f["label"], f["placeholder"])).lower()
        today = datetime.date.today()
        if t == "email" or "email" in hint or "e-mail" in hint:
            v = f"{marker.lower()}@example.com"
        elif t == "date":
            v = today.isoformat()
        elif t == "datetime-local":
            v = today.isoformat() + "T09:00"
        elif t == "time":
            v = "09:00"
        elif t == "month":
            v = today.strftime("%Y-%m")
        elif t == "url" or re.search(r"website|\burl\b|link", hint):
            v = "https://example.com"
        elif t == "password":
            v = f"Uat#{self.run_id}a"
        elif t == "tel" or re.search(r"phone|telp|telepon|\bhp\b|handphone|mobile|whatsapp|\bwa\b", hint):
            v = "081234567890"
        elif t == "number" or re.search(r"harga|price|amount|jumlah|qty|stok|stock|nominal|total|biaya|tarif", hint):
            lo = float(f["min"]) if re.fullmatch(r"-?\d+(\.\d+)?", f["min"]) else 0
            v = str(int(max(lo, 10)))
        elif re.search(r"tanggal|\btgl\b|date", hint):
            fmt = re.search(r"(dd|mm)([/.-])(dd|mm)[/.-]yyyy", f["placeholder"].lower())
            v = today.strftime(f"%{fmt.group(1)[0]}{fmt.group(2)}%{fmt.group(3)[0]}{fmt.group(2)}%Y") if fmt else today.isoformat()
        elif re.search(r"\bnik\b|ktp", hint):
            v = "3201010101900001"
        elif "npwp" in hint:
            v = "012345678901000"
        elif re.search(r"kode ?pos|postal|\bzip\b", hint):
            v = "40111"
        elif re.search(r"rekening|account.?(no|number)", hint):
            v = "1234567890"
        elif f["tag"] == "textarea" or t == "contenteditable":
            v = f"Data uji otomatis {marker}"
        elif re.search(r"alamat|address", hint):
            v = f"Jl. Uji {marker} No. 1"
        else:
            v = marker
        if f["pattern"]:
            try:
                if not re.fullmatch(f["pattern"], v):
                    v = next((d for d in ("1234567890123456"[:k] for k in range(1, 17)) if re.fullmatch(f["pattern"], d)), v)
            except re.error:
                pass
        if f["maxlength"] and len(v) > f["maxlength"]:
            v = marker[-f["maxlength"]:] if v == marker else v[:f["maxlength"]]
        return v

    def fill_field(self, f, marker, radios):
        """Isi satu field bila masih kosong; kembalikan nilai yang diisi (None = tidak diubah)."""
        sel = f'[data-uat-f="{f["i"]}"]'
        t = f["type"]
        if f["tag"] == "select":
            if not f["emptySelect"]:
                return None
            v = self.b.eval(JS_SELECT_FIRST % json.dumps(sel))
            if v:
                self.b.settle(first=0.2)  # dropdown bertingkat memuat pilihan berikutnya
            return v
        if t == "checkbox":
            if f["required"] and not f["checked"]:
                self.b.set_checked(sel, True)
                return "dicentang"
            return None
        if t == "radio":
            if f["groupChecked"] or f["name"] in radios:
                return None
            radios.add(f["name"])
            self.b.set_checked(sel, True)
            return f["label"] or "dipilih"
        if t == "file":
            if f["files"] or not f["required"]:
                return None
            path = self.samples()["pdf" if "pdf" in f["accept"] and "image" not in f["accept"] else "png"]
            self.b.upload(sel, [path])
            return os.path.basename(path)
        if f["value"] or (f["readonly"] and not f["required"]) or t in ("color", "range", "week"):
            return None
        v = self.field_value(f, marker)
        if t == "contenteditable":
            self.b.eval(JS_SET_CE % json.dumps([sel, v]))
        else:
            self.b.fill(sel, v)
        return v

    def fill_form(self, marker, inline):
        filled = []
        for _ in range(2):  # putaran kedua: field yang baru muncul setelah dropdown dipilih
            radios = set()
            n = 0
            for f in self.b.eval(JS_FORM_FIELDS % json.dumps(inline)) or []:
                v = self.fill_field(f, marker, radios)
                if v is not None:
                    name = f["name"] if f["type"] == "radio" else f["label"] or f["name"] or f["type"]
                    filled.append(f"{name} = {v}")
                    n += 1
            if not n:
                break
        return filled

    def _messages(self, before, lines0):
        out = [x for x in (self.b.eval(JS_MESSAGES) or []) if x not in before]
        out += [x for x in (self.b.eval(JS_LINES) or []) if x not in lines0 and x not in out and len(x) <= 200
                and (SUCCESS.search(x) or FAILURE.search(x))]
        return out

    def confirm_and_collect(self, before, lines0, tc=None):
        """Setujui dialog konfirmasi (ya/ok/hapus) bila muncul; kumpulkan pesan baru di halaman."""
        msgs, confirmed = [], []
        for _ in range(3):
            msgs += [x for x in self._messages(before, lines0) if x not in msgs]
            c = self.b.eval(JS_CONFIRM)
            if not c:
                break
            if tc is not None and not confirmed:
                self.shot(tc, f"Konfirmasi '{c['label']}'")
            confirmed.append(c["label"])
            self.b.click("[data-uat=confirm]")
        if self.b.last_dialog:
            confirmed.insert(0, "OK")
            msgs.insert(0, self.b.last_dialog)
        return msgs, confirmed

    def save(self, inline):
        """Klik tombol simpan; kembalikan (label tombol, pesan baru, field tidak valid)."""
        before = set(self.b.eval(JS_MESSAGES) or [])
        lines0 = set(self.b.eval(JS_LINES) or [])
        label = self.b.eval(JS_MARK_SAVE % json.dumps(inline))
        self.b.dialog_accept = True
        self.b.last_dialog = None
        if label:
            self.b.click("[data-uat=save]")
        elif self.b.eval(JS_FORM_SUBMIT2):
            self.b.settle()
        else:
            raise Blocked("Tombol simpan tidak ditemukan di form.")
        invalid = self.b.eval(JS_INVALID) or []
        msgs, _ = self.confirm_and_collect(before, lines0)
        return label or "submit", msgs, invalid

    @staticmethod
    def verdict(msgs, invalid):
        return invalid + [x for x in msgs if FAILURE.search(x) and not SUCCESS.search(x)], [x for x in msgs if SUCCESS.search(x)]

    def find_row(self, m, marker):
        """Cari baris berisi penanda di halaman daftar (pakai kotak pencarian bila perlu). Kembalikan (teks baris, lewat pencarian)."""
        self.open_list(m)
        row = self.b.eval(JS_FIND_ROW % json.dumps(marker))
        if row:
            return row, False
        if self.b.eval(JS_SEARCH_MARK):
            self.b.fill("[data-uat=search]", marker)
            self.b.settle(first=0.8)
            row = self.b.eval(JS_FIND_ROW % json.dumps(marker))
            if not row and self.b.exists("[data-uat=search]"):
                self.b.press_enter("[data-uat=search]")
                row = self.b.eval(JS_FIND_ROW % json.dumps(marker))
            if row:
                return row, True
        return None, False

    def _marker(self, m):
        marker = self.created.get(m["url"])
        if not marker:
            raise Blocked("Data uji dari test case tambah data tidak tersedia.")
        return marker

    # ── CRUD: test case ─────────────────────────────────────────────────
    def tc_create(self, tc, m):
        tc["crud"] = True
        label = m["title"]
        self.seq += 1
        marker = f"UAT{self.run_id}{self.seq:02d}"
        tc.update(pre=f"User sudah login sebagai {self.user} dan membuka menu {label}.",
                  steps=[f"Klik '{self.caps[m['url']]['create']}'", f"Isi field form dengan data uji (penanda {marker})",
                         "Klik tombol simpan", f"Periksa data {marker} di daftar {label}"],
                  expected=f"Data tersimpan tanpa error dan data {marker} tampil di daftar {label}.")
        self.ensure_login()
        c, fields = self.open_form(m)
        self.caps[m["url"]]["required"] = any(f["required"] and f["tag"] != "select" and f["type"] not in ("checkbox", "radio")
                                              and not f["value"] for f in fields)
        tc["steps"][0] = f"Klik '{c['label']}'"
        filled = self.fill_form(marker, c["inline"])
        tc["actual"].append(f"Form tambah tampil dengan {len(fields)} field. Diisi: " + "; ".join(filled[:15]) + ".")
        self.shot(tc, "Form tambah data terisi")
        btn, msgs, invalid = self.save(c["inline"])
        tc["steps"][2] = f"Klik '{btn}'"
        errs, oks = self.verdict(msgs, invalid)
        if errs:
            self.fail(tc, "Data tidak tersimpan: " + "; ".join(errs[:5]) + ".")
            self.shot(tc, "Hasil simpan")
        elif oks:
            tc["actual"].append("Pesan tampil: '" + "'; '".join(oks[:3]) + "'.")
        row, searched = self.find_row(m, marker)
        if row:
            self.created[m["url"]] = marker
            tc["actual"].append(f"Data {marker} tampil di daftar" + (" (melalui pencarian)" if searched else "") + f": {row}")
            self.shot(tc, "Data baru di daftar")
        elif not errs:
            self.unverified[m["url"]] = marker
            if oks:
                tc["notes"].append(f"Data {marker} tidak ditemukan di halaman daftar (mungkin di halaman lain); periksa dan hapus manual.")
            else:
                self.fail(tc, f"Data {marker} tidak ditemukan di daftar setelah disimpan.")
            self.shot(tc, "Daftar setelah simpan")

    def tc_validate(self, tc, m):
        tc["crud"] = True
        tc.update(pre=f"User sudah login sebagai {self.user} dan membuka menu {m['title']}.",
                  steps=[f"Klik '{self.caps[m['url']]['create']}'", "Biarkan field wajib kosong", "Klik tombol simpan"],
                  expected="Data tidak tersimpan dan sistem menampilkan pesan bahwa field wajib harus diisi.")
        self.ensure_login()
        c, fields = self.open_form(m)
        req = [f["label"] or f["name"] for f in fields if f["required"]]
        btn, msgs, invalid = self.save(c["inline"])
        tc["steps"][2] = f"Klik '{btn}'"
        errs, oks = self.verdict(msgs, invalid)
        if req:
            tc["actual"].append("Field wajib di form: " + ", ".join(req[:10]) + ".")
        if errs:
            tc["actual"].append("Data tidak tersimpan; pesan validasi: " + "; ".join(errs[:6]) + ".")
        elif oks:
            self.fail(tc, "Form kosong berhasil disimpan tanpa validasi: '" + "'; '".join(oks[:2]) + "'.")
            tc["notes"].append("Kemungkinan ada data kosong yang tersimpan; periksa dan hapus manual.")
        else:
            tc["actual"].append("Data tidak tersimpan (form tetap terbuka).")
            tc["notes"].append("Tidak terdeteksi pesan validasi di halaman; periksa screenshot.")
        self.shot(tc, "Simpan form kosong")

    def tc_read(self, tc, m):
        tc["crud"] = True
        marker = self._marker(m)
        tc.update(pre=f"Data uji {marker} sudah ditambahkan.",
                  steps=[f"Buka menu '{m['title']}'", f"Cari data {marker}", "Buka detail data"],
                  expected=f"Data {marker} dapat ditemukan di daftar dan detailnya tampil sesuai data yang diinput.")
        self.ensure_login()
        row, searched = self.find_row(m, marker)
        if not row:
            self.fail(tc, f"Data {marker} tidak ditemukan di daftar.")
            self.shot(tc, "Pencarian data")
            return
        tc["actual"].append("Data ditemukan di daftar" + (f" melalui pencarian '{marker}'" if searched else "") + f": {row}")
        self.shot(tc, "Data di daftar")
        label = self.b.eval(JS_ROW_ACTION % '"view"')
        if not label:
            tc["steps"] = tc["steps"][:2]
            tc["notes"].append("Baris data tidak memiliki tombol detail/lihat.")
            return
        tc["steps"][2] = f"Klik '{label}' pada baris data"
        self.b.settle()
        info = self.b.eval(JS_PAGE % json.dumps(ERROR_TEXT))
        title = self.b.eval(JS_DIALOG_TITLE) or info["heading"] or info["title"]
        if self.b.eval(JS_HAS_TEXT % json.dumps(marker)):
            tc["actual"].append(f"Detail '{title}' tampil dan memuat data {marker}.")
        else:
            self.fail(tc, f"Detail yang tampil ('{title}') tidak memuat data {marker}.")
        self.shot(tc, "Detail data")

    def tc_update(self, tc, m):
        tc["crud"] = True
        marker = self._marker(m)
        new = marker + "U"
        tc.update(pre=f"Data uji {marker} sudah ditambahkan.",
                  steps=[f"Cari data {marker} di menu '{m['title']}'", "Klik tombol ubah pada baris data", f"Ubah {marker} menjadi {new}",
                         "Klik tombol simpan", f"Periksa data {new} di daftar"],
                  expected=f"Perubahan tersimpan dan data tampil sebagai {new} di daftar.")
        self.ensure_login()
        row, _ = self.find_row(m, marker)
        if not row:
            self.fail(tc, f"Data {marker} tidak ditemukan di daftar.")
            return
        self.b.eval(JS_PRE_MARK)
        label = self.b.eval(JS_ROW_ACTION % '"edit"')
        if not label:
            raise Blocked("Tombol ubah tidak ditemukan pada baris data uji.")
        tc["steps"][1] = f"Klik '{label}' pada baris data"
        self.b.settle()
        self._wait(lambda: self.b.eval(JS_FORM_FIELDS % "false"), 8)
        fields = self.b.eval(JS_FORM_FIELDS % "false") or []
        target = [f for f in fields if marker in f["value"] and f["type"] not in ("email", "file", "password")]
        if not target:  # pengaman: hanya mengubah form yang memang berisi data uji
            raise Blocked(f"Form ubah tidak tampil atau tidak berisi data uji {marker}; tidak ada perubahan yang dikirim.")
        changed = []
        for f in target:
            v = f["value"].replace(marker, new)
            if f["maxlength"] and len(v) > f["maxlength"]:
                continue
            sel = f'[data-uat-f="{f["i"]}"]'
            if f["type"] == "contenteditable":
                self.b.eval(JS_SET_CE % json.dumps([sel, v]))
            else:
                self.b.fill(sel, v)
            changed.append(f"{f['label'] or f['name']} = {v}")
        if not changed:
            raise Blocked("Field data uji tidak dapat diubah (batas panjang isian).")
        tc["actual"].append("Form ubah tampil berisi data uji. Diubah: " + "; ".join(changed) + ".")
        self.shot(tc, "Form ubah data")
        btn, msgs, invalid = self.save(False)
        tc["steps"][3] = f"Klik '{btn}'"
        errs, oks = self.verdict(msgs, invalid)
        if errs:
            self.fail(tc, "Perubahan tidak tersimpan: " + "; ".join(errs[:5]) + ".")
        elif oks:
            tc["actual"].append("Pesan tampil: '" + "'; '".join(oks[:3]) + "'.")
        row, searched = self.find_row(m, new)
        if row:
            self.created[m["url"]] = new
            tc["actual"].append(f"Data tampil sebagai {new} di daftar" + (" (melalui pencarian)" if searched else "") + f": {row}")
        elif not errs:
            self.fail(tc, f"Data {new} tidak ditemukan di daftar setelah disimpan.")
        self.shot(tc, "Daftar setelah ubah")

    def tc_delete(self, tc, m):
        tc["crud"] = True
        marker = self._marker(m)
        tc.update(pre=f"Data uji {marker} sudah ada di daftar.",
                  steps=[f"Cari data {marker} di menu '{m['title']}'", "Klik tombol hapus pada baris data", "Setujui konfirmasi hapus",
                         f"Periksa data {marker} di daftar"],
                  expected=f"Muncul konfirmasi sebelum menghapus, data terhapus, dan {marker} tidak tampil lagi di daftar.")
        self.ensure_login()
        row, _ = self.find_row(m, marker)
        if not row:
            self.fail(tc, f"Data {marker} tidak ditemukan di daftar.")
            return
        before = set(self.b.eval(JS_MESSAGES) or [])
        lines0 = set(self.b.eval(JS_LINES) or [])
        self.b.dialog_accept = True
        self.b.last_dialog = None
        label = self.b.eval(JS_ROW_ACTION % '"delete"')  # hanya di baris data uji (data-uat-row)
        if not label:
            raise Blocked("Tombol hapus tidak ditemukan pada baris data uji.")
        tc["steps"][1] = f"Klik '{label}' pada baris data {marker}"
        self.b.settle()
        msgs, confirmed = self.confirm_and_collect(before, lines0, tc)
        if confirmed:
            tc["actual"].append("Muncul konfirmasi hapus" + (f" '{msgs[0]}'" if self.b.last_dialog else "")
                                + f"; dipilih '{confirmed[-1]}'.")
        else:
            tc["notes"].append("Tidak terdeteksi dialog konfirmasi sebelum data dihapus.")
        oks = [x for x in msgs if SUCCESS.search(x)]
        if oks:
            tc["actual"].append("Pesan tampil: '" + "'; '".join(oks[:3]) + "'.")
        row, _ = self.find_row(m, marker)
        if row:
            self.fail(tc, f"Data {marker} masih tampil di daftar setelah dihapus: {row}")
        else:
            self.created.pop(m["url"], None)
            tc["actual"].append(f"Data {marker} tidak lagi tampil di daftar.")
        self.shot(tc, "Daftar setelah hapus")
