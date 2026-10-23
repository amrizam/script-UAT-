"""Menjalankan skenario UAT (JSON) di browser dan mencatat Actual Result, Status, dan screenshot.

Status per test case:
  Pass     semua pemeriksaan (expect) sesuai
  Fail     ada pemeriksaan yang tidak sesuai atau langkah gagal dijalankan
  Blocked  prasyarat tidak terpenuhi (data/akun belum ada, `require` gagal)
  Not Run  skenario menyimpan data (write) tanpa --allow-write, atau skenario manual
"""
import datetime
import json
import os
import re

from .browser import BrowserError

WEEKDAYS = {"en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
            "id": ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]}
MONTHS = {"en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
          "id": ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]}
ACTIONS = ["goto", "click", "fill", "select", "check", "uncheck", "upload", "wait", "wait_for", "eval", "login", "logout",
           "lang", "viewport", "clear_session", "dialog", "shot", "record", "actual", "note", "expect", "require", "if",
           "repeat", "save", "block"]


class Blocked(Exception):
    pass


class Aborted(Exception):
    pass


class Pack:
    """Paket skenario satu aplikasi: pack.json + modules/*.json + i18n/*.json + files/."""

    def __init__(self, folder):
        self.dir = folder
        with open(os.path.join(folder, "pack.json"), encoding="utf8") as f:
            self.cfg = json.load(f)
        self.modules = {}
        mdir = os.path.join(folder, "modules")
        for name in sorted(os.listdir(mdir)) if os.path.isdir(mdir) else []:
            if name.endswith(".json"):
                with open(os.path.join(mdir, name), encoding="utf8") as f:
                    m = json.load(f)
                self.modules[m.get("module", name[:-5])] = m
        self.order = [m for m in self.cfg.get("modules", []) if m in self.modules] + \
                     [m for m in self.modules if m not in self.cfg.get("modules", [])]

    def i18n(self, lang):
        p = os.path.join(self.dir, "i18n", f"{lang}.json")
        if not os.path.exists(p):
            return {}
        with open(p, encoding="utf8") as f:
            return json.load(f)

    def file(self, rel):
        return rel if os.path.isabs(rel) else os.path.join(self.dir, rel)


class Runner:
    def __init__(self, browser, pack, base_url, accounts, params, lang, allow_write, shots_dir, log=print):
        self.b = browser
        self.pack = pack
        self.base = base_url.rstrip("/")
        self.accounts = accounts            # nama -> {"user": .., "password": ..}
        self.params = dict(pack.cfg.get("params", {}))
        self.params.update(params or {})
        self.lang = lang
        self.tr = pack.i18n(lang)
        self.allow_write = allow_write
        self.shots = shots_dir
        self.log = log
        self.vars = {}
        self.current = "?"                  # akun yang sedang login ("?" = belum diketahui)
        self.msg_sel = pack.cfg.get("messages_selector", ".alert, .error, .field-validation-error, .validation-summary-errors li")
        self.max_posts = pack.cfg.get("max_posts_per_minute")
        self._tables = {}
        self.stamp = datetime.datetime.now().strftime("%H%M%S")
        os.makedirs(shots_dir, exist_ok=True)

    def rate_guard(self):
        """Batasi jumlah POST per menit (rate limit aplikasi) dengan menunggu bila perlu."""
        if not self.max_posts:
            return
        import time
        waited = False
        while True:
            now = time.time()
            recent = [t for t in self.b.post_times if now - t < 60]
            if len(recent) < self.max_posts - 1:
                break
            if not waited:
                self.log(f"   (menunggu batas {self.max_posts} kiriman form per menit…)")
                waited = True
            self.b.pump(1.0)

    # ── variabel & teks ─────────────────────────────────────────────────
    def t(self, key, *args):
        """Teks UI dari i18n; argumen '*' membiarkan {n} (untuk dicocokkan sebagai bagian bebas)."""
        s = self.tr.get(key, key)
        for i, a in enumerate(args):
            if a != "*":
                s = s.replace("{%d}" % i, str(a))
        return s

    def _date(self, spec):
        m = re.match(r"([+-]\d+)?", spec or "")
        d = datetime.date.today() + datetime.timedelta(days=int(m.group(1) or 0))
        return d

    def _resolve(self, expr, extra):
        extra = extra or {}
        if expr in extra:
            return extra[expr]
        if expr.startswith("t:"):
            parts = expr[2:].split("|")
            return self.t(parts[0], *[self.sub(p, extra) for p in parts[1:]])
        if expr[:4] in ("ten:", "tid:"):
            lang = expr[1:3]
            table = self._tables.setdefault(lang, self.pack.i18n(lang))
            parts = expr[4:].split("|")
            s = table.get(parts[0], parts[0])
            for i, a in enumerate(parts[1:]):
                s = s.replace("{%d}" % i, self.sub(a, extra))
            return s
        if expr == "lang":
            return self.lang
        if ":" in expr:
            kind, spec = expr.split(":", 1)
            if kind in ("date", "dmy", "ym", "long", "day", "month"):
                d = self._date(spec)
                if kind == "date":
                    return d.isoformat()
                if kind == "dmy":
                    return d.strftime("%d/%m/%Y")
                if kind == "ym":
                    return d.strftime("%Y-%m")
                if kind == "day":
                    return str(d.day)
                if kind == "month":
                    return f"{MONTHS[self.lang if self.lang in MONTHS else 'en'][d.month - 1]} {d.year}"
                lang = self.lang if self.lang in WEEKDAYS else "en"
                return f"{WEEKDAYS[lang][d.weekday()]}, {d.day} {MONTHS[lang][d.month - 1]} {d.year}"
        if expr == "url":
            return self.base
        if expr == "stamp":
            return self.stamp
        if expr in ("user", "password"):
            return self.accounts.get("main", {}).get(expr, "")
        if expr.startswith("acc."):
            _, name, field = expr.split(".", 2)
            if name not in self.accounts:
                raise KeyError(expr)
            return self.accounts[name][field]
        if expr.startswith("param."):
            v = self.params[expr[6:]]
            return self.sub(v, extra)
        if expr.startswith("var."):
            return self.vars[expr[4:]]
        raise KeyError(expr)

    def sub(self, s, extra=None):
        if isinstance(s, list):
            return [self.sub(x, extra) for x in s]
        if isinstance(s, dict):
            return {k: self.sub(v, extra) for k, v in s.items()}
        if not isinstance(s, str):
            return s

        def rep(m):
            try:
                return str(self._resolve(m.group(1), extra))
            except (KeyError, ValueError, IndexError):
                return m.group(0)
        out = s
        for _ in range(6):
            new = re.sub(r"\{([^{}\s][^{}]*)\}", rep, out)
            if new == out:
                break
            out = new
        return out

    def template_regex(self, text):
        """Teks i18n dengan {0},{1} → regex dengan grup penangkap."""
        parts = re.split(r"\{\d+\}", text)
        return "(.+?)".join(re.escape(p) for p in parts)

    # ── sesi & akun ─────────────────────────────────────────────────────
    def apply_lang(self):
        for a in self.pack.cfg.get("language", {}).get(self.lang, []):
            self.act(a, None)

    def login(self, name):
        if name not in self.accounts:
            raise Blocked(f"Akun '{name}' tidak diberikan (gunakan --account {name}=user:password).")
        acc = self.accounts[name]
        cfg = self.pack.cfg.get("login")
        if not cfg:
            raise Blocked("Paket tidak memiliki konfigurasi login.")
        self.b.clear_session()
        self.apply_lang()
        self.b.goto(self.base + self.sub(cfg["path"]))
        self.b.fill(cfg["user"], acc["user"])
        self.b.fill(cfg["password"], acc["password"])
        self.rate_guard()
        self.b.click(cfg["submit"])
        if cfg.get("fail_url") and re.search(cfg["fail_url"], self.b.url()):
            msgs = "; ".join(dict.fromkeys(self.b.messages(self.msg_sel)))
            self.current = None
            raise Blocked(f"Login sebagai {acc['user']} gagal: {msgs or 'tetap di halaman login'}.")
        self.current = name

    def logout(self):
        steps = self.pack.cfg.get("logout")
        try:
            if steps and self.current not in (None, "?"):
                for a in steps:
                    self.act(a, None)
        except BrowserError:
            pass
        self.b.clear_session()
        self.current = None

    def account_user(self, name):
        return self.accounts.get(name, {}).get("user", "")

    def ensure(self, who):
        if who in (None, "none", ""):
            if self.current is not None:
                self.logout()
            self.apply_lang()
        elif self.current != who:
            self.login(who)

    # ── aksi ────────────────────────────────────────────────────────────
    def run_actions(self, actions, tc):
        for a in actions or []:
            self.act(a, tc)

    def act(self, a, tc):
        # Jenis aksi = kunci pertama objek (urutan JSON dipertahankan); kunci lain adalah opsi (actual, save, …).
        kind = next((k for k in a if k in ACTIONS), None)
        if kind is None:
            raise BrowserError(f"Aksi tidak dikenal: {list(a)}")
        b = self.b
        v = a[kind]
        if kind == "goto":
            path = self.sub(v)
            status = b.goto(path if path.startswith("http") else self.base + path)
            if tc is not None:
                tc["_http"] = status
        elif kind == "click":
            self.rate_guard()
            b.click(self.sub(v), settle=a.get("settle", True))
        elif kind == "block":
            raise Blocked(self.sub(v))
        elif kind == "fill":
            b.fill(self.sub(v), self.sub(a.get("value", "")))
        elif kind == "select":
            b.select(self.sub(v), value=self.sub(a.get("value")), label=self.sub(a.get("label")), index=a.get("index"))
        elif kind in ("check", "uncheck"):
            b.set_checked(self.sub(v), kind == "check")
        elif kind == "upload":
            b.upload(self.sub(v), [self.pack.file(self.sub(f)) for f in a.get("files", [])])
        elif kind == "wait":
            b.pump(float(v) / 1000.0)
        elif kind == "wait_for":
            self._wait_for(self.sub(v), a.get("timeout", 15))
        elif kind == "eval":
            res = b.eval(self.sub(v))
            if a.get("save"):
                self.vars[a["save"]] = res
            if a.get("settle"):
                b.settle()
        elif kind == "login":
            self.login(self.sub(v))
        elif kind == "logout":
            self.logout()
        elif kind == "lang":
            v = self.sub(v)
            self.lang = v
            self.tr = self.pack.i18n(v)
            self.apply_lang()
        elif kind == "viewport":
            b.set_viewport(v)
        elif kind == "clear_session":
            b.clear_session()
            self.current = None
        elif kind == "dialog":
            b.dialog_accept = (v != "dismiss")
        elif kind == "shot":
            self._shot(a, tc)
        elif kind == "record":
            value = self._observe(a, a["record"])
            if a.get("save"):
                self.vars[a["save"]] = value
            if a.get("actual") and tc is not None:
                tc["actual"].append(self.sub(a["actual"], {"value": value}))
        elif kind == "save":
            self.vars[v] = self._observe(a, a.get("selector"))
        elif kind == "actual":
            tc["actual"].append(self.sub(v))
        elif kind == "note":
            tc["notes"].append(self.sub(v))
        elif kind in ("expect", "require"):
            self._expect(a, tc, block=(kind == "require") or a.get("block", False))
        elif kind == "if":
            ok, _ = self._condition(v)
            self.run_actions(a.get("then" if ok else "else", []), tc)
        elif kind == "repeat":
            for i in range(int(v)):
                self.vars["i"] = i + 1
                self.run_actions(a.get("do", []), tc)

    def _wait_for(self, selector, timeout):
        import time
        end = time.time() + timeout
        while time.time() < end:
            if self.b.visible(selector):
                return
            self.b.pump(0.2)
        raise BrowserError(f"Elemen tidak muncul: {selector}")

    def _observe(self, a, selector):
        b = self.b
        if "js" in a:
            return b.eval(self.sub(a["js"]))
        sel = self.sub(selector)
        if a.get("all"):
            value = a.get("join", ", ").join(b.texts(sel))
        elif a.get("attr"):
            value = b.attr(sel, a["attr"]) if b.exists(sel) else None
        elif a.get("prop") == "value":
            value = b.value(sel) if b.exists(sel) else None
        else:
            value = b.text(sel)
        if value is not None and a.get("regex"):
            m = re.search(self.sub(a["regex"]), value)
            value = (m.group(1) if m and m.groups() else m.group(0)) if m else None
        return value

    def _shot(self, a, tc):
        if tc is None:
            return
        n = len(tc["images"]) + 1
        path = os.path.join(self.shots, f"{tc['id']}_{n}.png")
        sel = self.sub(a.get("selector"))
        try:
            if sel:
                self.b.screenshot(path, selector=sel, pad=a.get("pad", 12))
            elif a.get("clip"):
                self.b.screenshot(path, clip=a["clip"])
            else:
                self.b.screenshot(path, full=a.get("full", False))
            tc["images"].append((path, f"Gambar {tc['id']}_{n} – {self.sub(a['shot'])}"))
        except BrowserError as e:
            tc["notes"].append(f"Screenshot '{self.sub(a['shot'])}' gagal diambil: {e}")

    def _condition(self, c):
        """Evaluasi satu kondisi; kembalikan (ok, nilai teramati)."""
        b = self.b
        c = self.sub(c)
        if "account" in c:
            return c["account"] in self.accounts, None
        if "var" in c:
            return bool(self.vars.get(c["var"])), self.vars.get(c["var"])
        if "url" in c:
            u = b.url()
            return bool(re.search(c["url"], u)), u
        if "not_url" in c:
            u = b.url()
            return not re.search(c["not_url"], u), u
        if "visible" in c:
            return b.visible(c["visible"]), None
        if "hidden" in c:
            return not b.visible(c["hidden"]), None
        if "exists" in c:
            return b.exists(c["exists"]), None
        if "disabled" in c:
            return b.exists(c["disabled"]) and b.disabled(c["disabled"]), None
        if "enabled" in c:
            return b.exists(c["enabled"]) and not b.disabled(c["enabled"]), None
        if "count" in c:
            n = b.count(c["count"])
            ok = (n >= c.get("min", 0)) and (n <= c.get("max", 10 ** 9)) and (c.get("eq") is None or n == c["eq"])
            return ok, n
        if "status" in c:
            return self.b.last_doc_status == c["status"], self.b.last_doc_status
        if "js" in c:
            val = b.eval(c["js"])
            return bool(val), val
        if "selector" in c:
            val = b.text(c["selector"])
            if val is None:
                return False, None
            if "equals" in c:
                return val == c["equals"], val
            if "matches" in c:
                return bool(re.search(c["matches"], val)), val
            if "not_contains" in c:
                return c["not_contains"] not in val, val
            return c.get("contains", "") in val, val
        if "msg" in c or "text" in c:
            msgs = list(dict.fromkeys(b.messages(self.msg_sel)))
            wanted = c.get("msg") or c.get("text")
            wanted = wanted if isinstance(wanted, list) else [wanted]
            found, groups = [], []
            for w in wanted:
                pattern = self.template_regex(self.t(w) if "msg" in c else w)
                hit = next((m for m in msgs if re.search(pattern, m)), None)
                if hit is None:
                    return False, "; ".join(msgs) or "(tidak ada pesan)"
                found.append(re.search(pattern, hit).group(0))
                groups += list(re.search(pattern, hit).groups())
            return True, {"msgs": found, "groups": groups}
        if "fetch" in c:
            r = b.fetch(c["fetch"])
            ok = (r["status"] == c.get("status", 200)) and (c.get("type", "") in r["type"])
            return ok, r
        raise BrowserError(f"Kondisi tidak dikenal: {list(c)}")

    def _expect(self, a, tc, block=False):
        cond = a.get("expect") if isinstance(a.get("expect"), dict) else a.get("require")
        if not isinstance(cond, dict):
            cond = {k: v for k, v in a.items() if k not in ("expect", "require", "actual", "fail", "blocked", "save", "block", "stop")}
        try:
            ok, val = self._condition(cond)
        except BrowserError as e:
            ok, val = False, str(e)
        extra = {"value": val if not isinstance(val, (dict, list)) else ""}
        if isinstance(val, dict) and "msgs" in val:
            extra["msg"] = "' dan '".join(val["msgs"])
            for i, g in enumerate(val["groups"]):
                extra[f"g{i + 1}"] = g
            if a.get("save"):
                names = a["save"] if isinstance(a["save"], list) else [a["save"]]
                for n, g in zip(names, val["groups"]):
                    self.vars[n] = g
        elif isinstance(val, dict):
            extra.update({f"r_{k}": v for k, v in val.items()})
            extra["value"] = json.dumps(val)
        elif a.get("save") and ok:
            self.vars[a["save"]] = val
        if ok:
            if a.get("actual") and tc is not None:
                tc["actual"].append(self.sub(a["actual"], extra))
            return
        if block:
            msg = self.sub(a.get("blocked") or a.get("fail") or "Prasyarat tidak terpenuhi.", extra)
            if tc is not None and a.get("actual_blocked"):
                tc["actual"].append(self.sub(a["actual_blocked"], extra))
            raise Blocked(msg)
        line = self.sub(a.get("fail") or (self.sub(a.get("actual", "Pemeriksaan")) + " — tidak sesuai, teramati: {value}"), extra)
        if tc is not None:
            tc["actual"].append(line)
            tc["status"] = "Fail"
        if a.get("stop"):
            raise Aborted(line)

    # ── test case ───────────────────────────────────────────────────────
    def run_tc(self, tc_def, tc_id):
        tc = {"id": tc_id, "scenario": self.sub(tc_def["scenario"]), "pre": self.sub(tc_def.get("pre", "")),
              "steps": [self.sub(s["text"]) for s in tc_def.get("steps", [])], "expected": self.sub(tc_def.get("expected", "")),
              "actual": [], "status": "Pass", "notes": [], "images": []}
        note = tc_def.get("notes")
        if tc_def.get("manual"):
            tc["status"] = "Not Run"
            tc["actual"].append(self.sub(tc_def.get("manual_reason", "Skenario dijalankan manual di luar aplikasi web ini.")))
            if note:
                tc["notes"].append(self.sub(note))
            return tc
        if tc_def.get("write") and not self.allow_write:
            tc["status"] = "Not Run"
            tc["actual"].append("Tidak dijalankan: skenario ini mengirim/menyimpan data, sedangkan mode tulis tidak diaktifkan (jalankan dengan --allow-write).")
            if note:
                tc["notes"].append(self.sub(note))
            return tc
        missing = [n for n in tc_def.get("accounts", []) if n not in self.accounts]
        if missing:
            tc["status"] = "Blocked"
            tc["actual"].append("Tidak dijalankan: akun " + ", ".join(missing) + " tidak diberikan (--account nama=user:password).")
            if note:
                tc["notes"].append(self.sub(note))
            return tc
        self.b.console_errors.clear()
        current_step = None
        who = self.sub(tc_def.get("as", "main"))
        try:
            self.b.set_viewport("desktop")
            self.b.dialog_accept = True
            self.ensure(who)
            for step in tc_def.get("steps", []):
                current_step = step
                self.run_actions(step.get("do", []), tc)
            for a in tc_def.get("check", []):
                self.act(a, tc)
        except Blocked as e:
            tc["status"] = "Blocked"
            tc["notes"].insert(0, str(e))
        except Aborted:
            tc["status"] = "Fail"
        except BrowserError as e:
            tc["status"] = "Fail"
            where = self.sub(current_step["text"]) if current_step else "persiapan"
            tc["actual"].append(f"Langkah '{where}' tidak dapat dijalankan: {e}")
        finally:
            try:
                self.run_actions(tc_def.get("finally", []), tc)
            except Exception as e:  # pragma: no cover
                tc["notes"].append(f"Langkah penutup gagal: {e}")
            if who in (None, "none", "") or tc_def.get("changes_session"):
                self.current = "?"   # skenario ini login/logout sendiri: status sesi tidak diketahui
        if note:
            tc["notes"].append(self.sub(note))
        if self.b.console_errors and self.pack.cfg.get("report_console_errors", True):
            errs = list(dict.fromkeys(e for e in self.b.console_errors if e))[:3]
            if errs:
                tc["notes"].append("Error JavaScript di browser: " + " | ".join(errs))
        if not tc["actual"]:
            tc["actual"].append("Langkah dijalankan tanpa pemeriksaan otomatis.")
        return tc

    def smoke_tcs(self, module):
        """Modul generik: satu test case per halaman (buka halaman, cek status & error, screenshot)."""
        pages = module.get("pages") or [p.strip() for p in str(self.params.get("pages", "/")).split(",") if p.strip()]
        err = module.get("error_text", self.pack.cfg.get("error_text", ["Page not found", "Halaman tidak ditemukan", "Server Error", "Exception"]))
        out = []
        for p in pages:
            label, _, path = p.partition("=") if "=" in p else (p, "", p)
            out.append({
                "scenario": f"Membuka halaman {label}",
                "pre": module.get("pre", "User sudah login."),
                "as": module.get("as", "main"),
                "steps": [{"text": f"Buka halaman {path}", "do": [{"goto": path}]},
                          {"text": "Periksa judul halaman, isi, dan pesan error", "do": [
                              {"record": "h1", "actual": "Halaman terbuka dengan judul '{value}'."},
                              {"expect": {"js": "!!document.body && document.body.innerText.trim().length > 0"},
                               "actual": "Konten halaman tampil.", "fail": "Halaman kosong."},
                              {"expect": {"js": "!(" + json.dumps(err) + ").some(t => document.body.innerText.includes(t))"},
                               "actual": "Tidak ada pesan error di halaman.", "fail": "Halaman menampilkan pesan error."},
                              {"shot": f"Halaman {label}", "full": True}]}],
                "expected": f"Halaman {label} terbuka tanpa error dan menampilkan data sesuai hak akses user.",
            })
        return out
