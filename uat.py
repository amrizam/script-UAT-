#!/usr/bin/env python
"""UAT otomatis aplikasi web → dokumen UAT (.docx) mengikuti format dokumen contoh.

Berlaku untuk aplikasi web apa pun: script login sendiri, membaca menu-menu aplikasi setelah login (disimpan ke
*_menu.json), lalu menu yang dipilih menjadi modul UAT (tiap menu dibuka, diperiksa, dan di-screenshot).

Contoh:
  py uat.py            (tanpa argumen: dokumen contoh, URL, user, password, modul, dan folder simpan ditanyakan satu per satu)
  py uat.py --template "D:\\UAT\\Contoh_UAT.docx" --url https://erp.perusahaan.co.id --user qa@perusahaan.co.id ^
            --modules all --output "D:\\UAT\\Hasil"
Password tidak perlu ditulis di perintah: bila --password kosong akan ditanyakan (tidak tampil di layar).
"""
import argparse
import datetime
import getpass
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from uat_engine.browser import Browser, BrowserError  # noqa: E402
from uat_engine.docbuilder import DocBuilder  # noqa: E402
from uat_engine.explorer import Explorer, LoginError, menu_title  # noqa: E402
from uat_engine.runner import Pack, Runner  # noqa: E402

PACKS_DIR = os.path.join(HERE, "packs")
DEFAULT_TEMPLATE = os.path.join(HERE, "templates", "UAT_template_default.docx")
BULAN = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]


def tanggal_id(d):
    return f"{d.day} {BULAN[d.month - 1]} {d.year}"


def list_packs():
    return sorted(p for p in os.listdir(PACKS_DIR) if os.path.exists(os.path.join(PACKS_DIR, p, "pack.json")))


def ask(prompt, default=None, required=True):
    while True:
        suffix = f" [{default}]" if default else ""
        val = input(f"{prompt}{suffix}: ").strip().strip('"')
        if not val and default:
            return default
        if val or not required:
            return val
        print("  Wajib diisi.")


def ask_yes(prompt, default=False):
    val = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
    return default if not val else val in ("y", "ya", "yes")


def clean_path(p):
    """Path hasil drag & drop ke terminal: "C:\\a b.docx", 'C:\\a b.docx', atau & 'C:\\a b.docx' (PowerShell)."""
    p = (p or "").strip()
    if p.startswith("& "):
        p = p[2:].strip()
    return os.path.expanduser(p.strip("\"'"))


def normalize_url(url):
    url = (url or "").strip().rstrip("/")
    return url if not url or "://" in url else "https://" + url


def open_template(path):
    """DocBuilder dari dokumen contoh; .pdf/kosong → template bawaan."""
    if not path or not path.lower().endswith(".docx"):
        if path:
            print(f"Catatan: '{path}' bukan file .docx; format diambil dari template bawaan.")
        path = DEFAULT_TEMPLATE
    if not os.path.exists(path):
        raise ValueError(f"File tidak ditemukan: {path}")
    try:
        return path, DocBuilder(path)
    except Exception as e:
        raise ValueError(f"'{path}' tidak dapat dibaca sebagai dokumen Word: {e}")


def ask_template():
    while True:
        p = clean_path(ask("Dokumen contoh (.docx, Enter = template bawaan)", required=False))
        try:
            return open_template(p)
        except ValueError as e:
            print(f"  {e}")


def get_template(arg, interactive):
    if arg:
        try:
            return open_template(clean_path(arg))
        except ValueError as e:
            if not interactive:
                raise SystemExit(str(e))
            print(f"  {e}")
    return ask_template() if interactive else open_template("")


def parse_kv(items, sep="="):
    out = {}
    for it in items or []:
        if sep not in it:
            raise SystemExit(f"Format salah: {it} (harus kunci{sep}nilai)")
        k, v = it.split(sep, 1)
        out[k.strip()] = v
    return out


def parse_accounts(items):
    accs = {}
    for it in items or []:
        name, _, cred = it.partition("=")
        user, _, pw = cred.partition(":")
        if not name or not user:
            raise SystemExit(f"Format --account salah: {it} (harus nama=user:password)")
        if not pw:
            pw = getpass.getpass(f"Password akun '{name}' ({user}): ")
        accs[name.strip()] = {"user": user.strip(), "password": pw}
    return accs


def choose_modules(pack, raw):
    names = pack.order
    if not raw or raw.strip().lower() in ("all", "semua", "*"):
        return names
    picked = []
    for token in re.split(r"[,\s]+", raw.strip()):
        if not token:
            continue
        if token.isdigit() and 1 <= int(token) <= len(names):
            token = names[int(token) - 1]
        if token in pack.cfg.get("modules", []) and token not in pack.modules:
            raise ValueError(f"Modul '{token}' belum punya skenario ({os.path.join('modules', token + '.json')} belum dibuat). "
                             f"Pilihan: {', '.join(names)}")
        if token not in pack.modules:
            raise ValueError(f"Modul '{token}' tidak ada di paket {os.path.basename(pack.dir)}. Pilihan: {', '.join(names)}")
        if token not in picked:
            picked.append(token)
    return picked


def print_modules(pack):
    print(f"Modul di paket '{os.path.basename(pack.dir)}':")
    for i, name in enumerate(pack.order, 1):
        m = pack.modules[name]
        n = len(m.get("testcases", [])) if m.get("type") != "smoke" else "per halaman"
        print(f"  {i:>2}. {name:<10} {m.get('title', ''):<28} ({n} test case)")
    todo = [m for m in pack.cfg.get("modules", []) if m not in pack.modules]
    if todo:
        print(f"      belum ada skenario: {', '.join(todo)}")


def output_paths(output, title):
    stamp = datetime.date.today().isoformat()
    if output.lower().endswith(".docx"):
        out = os.path.abspath(output)
    else:
        safe = re.sub(r'[\\/:*?"<>|]+', "", title).strip() or "UAT"
        out = os.path.join(os.path.abspath(output), f"{safe} {stamp}.docx")
        k = 2
        while os.path.exists(out):  # jangan timpa hasil sebelumnya (bisa sedang dibuka di Word)
            out = os.path.join(os.path.abspath(output), f"{safe} {stamp} ({k}).docx")
            k += 1
    os.makedirs(os.path.dirname(out), exist_ok=True)
    stem = os.path.splitext(out)[0]
    return out, stem + "_screenshots", stem + "_hasil.json"


def build_content(args, pack, tpl_defaults, modules, url, user):
    d = pack.cfg.get("defaults", {})
    info_t = tpl_defaults.get("info", {})
    title = args.title or d.get("doc_title") or f"UAT {pack.cfg.get('title', '')}".strip()
    today = datetime.date.today()
    module_titles = [pack.modules[m].get("title", m) for m in modules]
    fmt = {"url": url, "user": user, "tanggal": tanggal_id(today), "modul": ", ".join(module_titles),
           "lang": "Bahasa Inggris (EN)" if args.lang == "en" else "Bahasa Indonesia (ID)"}

    def f(s):
        try:
            return s.format(**fmt)
        except (KeyError, IndexError):
            return s
    intro = [f(x) for x in (d.get("intro") or tpl_defaults.get("intro") or [
        "Dokumen User Acceptance Test (UAT) ini digunakan sebagai acuan pengujian aplikasi oleh pengguna akhir untuk memastikan "
        "bahwa fungsi aplikasi telah berjalan sesuai kebutuhan bisnis sebelum go-live."])]
    if not args.no_run_note:
        intro.append(f"Pengujian dijalankan otomatis pada {tanggal_id(today)} di {url} menggunakan akun {user}; "
                     f"screenshot diambil dengan tampilan aplikasi {fmt['lang']}.")
    info = [
        ("Nama Proyek", args.project or info_t.get("Nama Proyek") or d.get("project") or "[Nama Proyek]"),
        ("Modul", args.module_title or f"{pack.cfg.get('title', '')} ({', '.join(module_titles)})".strip()),
        ("Disusun Oleh", args.author or info_t.get("Disusun Oleh") or "[Nama Penyusun]"),
        ("Ditinjau Oleh", args.reviewer or info_t.get("Ditinjau Oleh") or "[Project Manager / QA / Business Owner]"),
        ("Tanggal", tanggal_id(today)),
        ("Versi Dokumen", args.doc_version or info_t.get("Versi Dokumen") or "1.0"),
    ]
    lingkup = [pack.modules[m]["scope"] for m in modules if pack.modules[m].get("scope")] or tpl_defaults.get("lingkup") or d.get("lingkup", [])
    signers = d.get("signers") or tpl_defaults.get("signers") or [
        {"company": "PT. Yabes Multipro Solusindo", "roles": ["Project Manager", "Consultant"]},
        {"company": "[Nama Perusahaan Klien]", "roles": ["Project Manager", "Key User", "Key User", "Key User"]}]
    if args.client:
        signers = [s if i == 0 else {**s, "company": args.client} for i, s in enumerate(signers)]
    return {
        "title": title,
        "intro": intro,
        "info": info,
        "tujuan": [f(x) for x in (d.get("tujuan") or tpl_defaults.get("tujuan") or [
            "Tujuan dari UAT adalah memastikan bahwa sistem telah memenuhi kebutuhan proses bisnis pengguna, alur kerja berjalan "
            "dengan benar, data tersimpan secara akurat, serta output sistem sesuai dengan aturan dan ekspektasi operasional perusahaan."])],
        "lingkup": lingkup,
        "kriteria": d.get("kriteria") or tpl_defaults.get("kriteria") or [
            "Seluruh skenario pengujian kritikal berhasil dijalankan",
            "Tidak terdapat defect dengan kategori blocker atau critical",
            "Data yang diinput, diproses, dan ditampilkan akurat",
            "Pengguna memberikan persetujuan bahwa sistem siap digunakan"],
        "signers": signers,
    }


def print_items(items, rel):
    print("\nModul = menu yang terbaca setelah login:")
    w = min(45, max(len(it["title"]) for it in items))
    for k, it in enumerate(items, 1):
        print(f"  {k:>3}. {it['title']:<{w}}  {it.get('note') or rel(it['url'])}")


def choose_items(items, raw):
    """Pilih modul: nomor (3), rentang (2-10), nama menu, nama grup menu, atau all."""
    if not raw or raw.strip().lower() in ("all", "semua", "*"):
        return items
    tokens = []
    for part in raw.split(","):
        part = part.strip()
        tokens += part.split() if re.fullmatch(r"\d+(\s+\d+)+", part) else [part] if part else []
    picked = []
    for token in tokens:
        rng = re.fullmatch(r"(\d+)\s*-\s*(\d+)", token)
        if rng or token.isdigit():
            a, b = (int(rng.group(1)), int(rng.group(2))) if rng else (int(token), int(token))
            if not 1 <= a <= b <= len(items):
                raise ValueError(f"Nomor {token} di luar 1-{len(items)}.")
            found = items[a - 1:b]
        else:
            low = token.lower()
            found = ([i for i in items if i["title"].lower() == low] or [i for i in items if i.get("text", "").lower() == low]
                     or [i for i in items if (i.get("group") or "").lower() == low] or [i for i in items if low in i["title"].lower()])
            if not found:
                raise ValueError(f"Menu '{token}' tidak ditemukan.")
        picked += [i for i in found if i not in picked]
    return [i for i in items if i in picked]


def generic_content(args, tpl_defaults, app, items, url, user, crud_titles=()):
    """Isi dokumen untuk mode generik. Isi bawaan (tujuan, kriteria, tanda tangan, proyek) hanya diambil dari dokumen contoh
    yang diberikan user, bukan dari template bawaan. crud_titles: menu yang ikut diuji CRUD (ditandai di ruang lingkup)."""
    info_t = tpl_defaults.get("info", {})
    today = datetime.date.today()
    menus = [i for i in items if i["kind"] == "menu"]
    groups = {}
    for m in menus:
        name = m["text"] + (" (CRUD)" if m["title"] in crud_titles else "")
        groups.setdefault(m.get("group") or name, []).append(name if m.get("group") else None)
    tops = list(groups)
    intro = [f"Dokumen User Acceptance Test (UAT) ini digunakan sebagai acuan pengujian aplikasi {app} oleh pengguna akhir untuk "
             "memastikan bahwa fungsi aplikasi telah berjalan sesuai kebutuhan bisnis sebelum go-live."]
    if not args.no_run_note:
        intro.append(f"Pengujian dijalankan otomatis pada {tanggal_id(today)} di {url} menggunakan akun {user}; daftar menu yang "
                     "diuji dibaca langsung dari aplikasi setelah login.")
    lingkup = []
    if any(i["kind"] == "login" for i in items):
        lingkup.append("Login dengan akun valid dan akun yang salah")
    for g, subs in groups.items():
        subs = [x for x in subs if x]
        lingkup.append(f"Menu {g}: {', '.join(subs)}" if subs else f"Menu {g}")
    if any(i["kind"] == "logout" for i in items):
        lingkup.append("Logout dan akses halaman setelah logout")
    signers = tpl_defaults.get("signers") or [
        {"company": "PT. Yabes Multipro Solusindo", "roles": ["Project Manager", "Consultant"]},
        {"company": "[Nama Perusahaan Klien]", "roles": ["Project Manager", "Key User", "Key User", "Key User"]}]
    if args.client:
        signers = [s if i == 0 else {**s, "company": args.client} for i, s in enumerate(signers)]
    return {
        "title": args.title or f"UAT {app}",
        "intro": intro,
        "info": [
            ("Nama Proyek", args.project or info_t.get("Nama Proyek") or "[Nama Proyek]"),
            ("Modul", args.module_title or (f"{app} ({', '.join(tops[:10])}{', dll.' if len(tops) > 10 else ''})" if tops else app)),
            ("Disusun Oleh", args.author or info_t.get("Disusun Oleh") or "[Nama Penyusun]"),
            ("Ditinjau Oleh", args.reviewer or info_t.get("Ditinjau Oleh") or "[Project Manager / QA / Business Owner]"),
            ("Tanggal", tanggal_id(today)),
            ("Versi Dokumen", args.doc_version or info_t.get("Versi Dokumen") or "1.0"),
        ],
        "tujuan": tpl_defaults.get("tujuan") or [
            "Tujuan dari UAT adalah memastikan bahwa sistem telah memenuhi kebutuhan proses bisnis pengguna, alur kerja berjalan "
            "dengan benar, data tersimpan secara akurat, serta output sistem sesuai dengan aturan dan ekspektasi operasional perusahaan."],
        "lingkup": lingkup,
        "kriteria": tpl_defaults.get("kriteria") or [
            "Seluruh skenario pengujian kritikal berhasil dijalankan",
            "Tidak terdapat defect dengan kategori blocker atau critical",
            "Data yang diinput, diproses, dan ditampilkan akurat",
            "Pengguna memberikan persetujuan bahwa sistem siap digunakan"],
        "signers": signers,
    }


def ask_output(args, interactive):
    if interactive:
        args.output = args.output or ask("Simpan dokumen di (folder atau path .docx)", os.path.join(os.path.expanduser("~"), "Documents", "UAT"))
    if not args.output:
        raise SystemExit("--output wajib diisi.")
    args.output = clean_path(args.output)


def run_all(groups, prefix):
    """groups: [(judul modul, [(skenario, fungsi(tc_id) → hasil test case)])]."""
    results, n = [], 0
    try:
        for title, tcs in groups:
            print(f"[{title}]")
            for _, fn in tcs:
                n += 1
                tc = fn(f"{prefix}-{n:03d}")
                results.append(tc)
                print(f"  {tc['id']} {tc['status']:<8} {tc['scenario']}")
    except BrowserError as e:
        print(f"\nBrowser error: {e}")
    except KeyboardInterrupt:
        print("\nDihentikan oleh user; dokumen dibuat dari test case yang sudah selesai.")
    return results


def prepare_pack(args, pack, browser, password, builder, interactive):
    """Mode paket skenario (--pack): modul dari packs/<paket>/modules."""
    if interactive and not args.modules:
        print_modules(pack)
        while True:
            try:
                modules = choose_modules(pack, ask("Modul yang di-UAT (nomor/nama dipisah koma, atau all)", "all"))
                break
            except ValueError as e:
                print(f"  {e}")
    else:
        try:
            modules = choose_modules(pack, args.modules)
        except ValueError as e:
            raise SystemExit(str(e))
    ask_output(args, interactive)
    n_write = sum(1 for m in modules for tc in pack.modules[m].get("testcases", []) if tc.get("write"))
    if interactive and n_write and not args.allow_write:
        args.allow_write = ask_yes(f"{n_write} skenario akan mengirim/menyimpan data ke aplikasi (mis. membuat request, ganti password). "
                                   "Jalankan juga?")
    args.lang = args.lang or pack.cfg.get("default_lang", "en")
    accounts = {"main": {"user": args.user, "password": password}}
    accounts.update(parse_accounts(args.account))
    content = build_content(args, pack, builder.tpl.defaults, modules, args.url, args.user)
    out_docx, shots_dir, out_json = output_paths(args.output, content["title"])
    print(f"\nUAT {pack.cfg.get('title', '')} · {args.url} · modul: {', '.join(modules)} · bahasa {args.lang.upper()}"
          f" · {'mode tulis AKTIF' if args.allow_write else 'mode baca (tanpa kirim data)'}")
    runner = Runner(browser, pack, args.url, accounts, parse_kv(args.param), args.lang, args.allow_write, shots_dir)

    def tc_fn(d, m):
        return lambda tc_id: {**runner.run_tc(d, tc_id), "module": m}
    groups = []
    for m in modules:
        mod = pack.modules[m]
        tcs = runner.smoke_tcs(mod) if mod.get("type") == "smoke" else mod.get("testcases", [])
        groups.append((mod.get("title", m), [(d["scenario"], tc_fn(d, m)) for d in tcs]))
    extra = {"modules": modules, "lang": args.lang, "allow_write": args.allow_write}
    return lambda results: (content, extra), groups, (out_docx, shots_dir, out_json), pack.cfg.get("id_prefix")


def prepare_generic(args, browser, password, template, builder, interactive):
    """Mode generik: login, baca menu aplikasi, menu menjadi modul UAT."""
    ex = Explorer(browser, args.url, args.user, password)
    while True:
        print(f"\nLogin ke {args.url} sebagai {args.user} …")
        try:
            ex.login()
            break
        except LoginError as e:
            print(f"  {e}")
            if not interactive:
                raise SystemExit(1)
            args.user = ask("User", args.user)
            ex.user, ex.password = args.user, ""
            while not ex.password:
                ex.password = getpass.getpass(f"Password {args.user} (tidak tampil di layar): ")
    print(f"Login berhasil → {ex.rel(ex.home)}")
    if args.menu_file:
        with open(clean_path(args.menu_file), encoding="utf8") as f:
            menus = [{"text": m.get("title") or m.get("url", ""), "group": "", "selector": "", **m} for m in json.load(f)["menus"] if m.get("url")]
        for m in menus:
            m.setdefault("title", menu_title(m))
        print(f"Menu diambil dari {args.menu_file}: {len(menus)} menu.")
    else:
        menus = ex.discover()
        print(f"Menu terbaca: {len(menus)} menu.")
    items = ([{"kind": "login", "title": "Login", "note": "(login akun valid & akun salah)"}]
             + [{"kind": "menu", **m} for m in menus]
             + [{"kind": "logout", "title": "Logout", "note": "(logout & buka halaman setelah logout)"}])
    if interactive and not args.modules:
        print_items(items, ex.rel)
        while True:
            try:
                chosen = choose_items(items, ask("Modul yang di-UAT (nomor, rentang 2-10, nama menu, dipisah koma, atau all)", "all"))
                break
            except ValueError as e:
                print(f"  {e}")
    else:
        try:
            chosen = choose_items(items, args.modules)
        except ValueError as e:
            raise SystemExit(str(e))
    if interactive and not args.crud and any(i["kind"] == "menu" for i in chosen):
        args.crud = ask_yes("Uji CRUD juga? Di menu yang punya tombol Tambah/Add, script akan MENAMBAH data uji berpenanda 'UAT…', "
                            "melihat, MENGUBAH, lalu MENGHAPUS data uji itu lagi (data lain tidak disentuh)", default=True)
    ex.crud = args.crud
    ask_output(args, interactive)
    tpl_defaults = builder.tpl.defaults if os.path.abspath(template) != os.path.abspath(DEFAULT_TEMPLATE) else {}
    title = args.title or f"UAT {ex.app}"
    out_docx, shots_dir, out_json = output_paths(args.output, title)
    os.makedirs(shots_dir, exist_ok=True)
    ex.shots = shots_dir
    menu_json = os.path.splitext(out_docx)[0] + "_menu.json"
    with open(menu_json, "w", encoding="utf8") as f:
        json.dump({"url": args.url, "app": ex.app, "home": ex.home, "dibaca": datetime.datetime.now().isoformat(timespec="seconds"),
                   "menus": [{k: m.get(k, "") for k in ("title", "text", "group", "url", "selector")} for m in menus]},
                  f, ensure_ascii=False, indent=1)
    print(f"Daftar menu disimpan: {menu_json}")

    def tcs(it):  # dibaca bertahap: test case CRUD baru diketahui setelah halaman menu dibuka
        for s, fn in ex.plan(it):
            yield s, lambda tc_id, s=s, fn=fn: {**ex.run(tc_id, s, fn), "module": it["title"]}
    groups = [(it["title"], tcs(it)) for it in chosen]
    print(f"\nUAT {ex.app} · {args.url} · {len(chosen)} modul · CRUD {'aktif' if ex.crud else 'tidak'}")

    def finish(results):
        crud = {r["module"] for r in results if r.get("crud")}
        content = generic_content(args, tpl_defaults, ex.app, chosen, args.url, args.user, crud)
        left = [{"menu": next((m["title"] for m in menus if m["url"] == u), u), "data": mk} for u, mk in ex.leftovers()]
        return content, {"app": ex.app, "home": ex.home, "modules": [it["title"] for it in chosen], "crud": ex.crud,
                         "data_uji_tersisa": left}
    return finish, groups, (out_docx, shots_dir, out_json), None


def main():
    ap = argparse.ArgumentParser(description="UAT otomatis aplikasi web → dokumen UAT (.docx)",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("-t", "--template", help="Dokumen contoh (.docx) yang formatnya diikuti. PDF/kosong = template bawaan.")
    ap.add_argument("-u", "--url", help="URL aplikasi web, contoh https://erp.perusahaan.co.id")
    ap.add_argument("--user", help="User/email login")
    ap.add_argument("--password", help="Password login (kosongkan agar ditanyakan)")
    ap.add_argument("-m", "--modules", help="Menu yang di-UAT: nomor, rentang (2-10), nama menu/grup dipisah koma, atau 'all'")
    ap.add_argument("-o", "--output", help="Folder atau path .docx hasil")
    ap.add_argument("--crud", action="store_true", help="Uji juga tambah/lihat/ubah/hapus data (CRUD) di menu yang punya tombol Tambah; "
                    "data uji berpenanda UAT… dihapus lagi di akhir")
    ap.add_argument("--menu-file", help="Pakai daftar menu dari file *_menu.json hasil sebelumnya (bisa diedit) daripada membaca ulang")
    ap.add_argument("--id-prefix", help="Awalan Test Case ID (bawaan UAT → UAT-001)")
    ap.add_argument("-p", "--pack", help="Opsional: jalankan skenario dari paket di packs\\ (mis. portal-tenant) alih-alih menu otomatis")
    ap.add_argument("--lang", choices=["en", "id"], help="[--pack] Bahasa tampilan aplikasi saat screenshot")
    ap.add_argument("--allow-write", action="store_true", help="[--pack] Jalankan juga skenario yang mengirim/menyimpan data")
    ap.add_argument("--account", action="append", metavar="NAMA=USER:PASSWORD", help="[--pack] Akun tambahan, mis. tr=qa.tr@yabes.co")
    ap.add_argument("--param", action="append", metavar="KUNCI=NILAI", help="[--pack] Parameter skenario (lihat pack.json → params)")
    ap.add_argument("--title", help="Judul dokumen (footer & properti dokumen)")
    ap.add_argument("--project", help="Isi 'Nama Proyek'")
    ap.add_argument("--client", help="Nama perusahaan klien pada tabel tanda tangan")
    ap.add_argument("--module-title", help="Isi 'Modul' pada Informasi Umum")
    ap.add_argument("--author", help="Isi 'Disusun Oleh'")
    ap.add_argument("--reviewer", help="Isi 'Ditinjau Oleh'")
    ap.add_argument("--doc-version", help="Isi 'Versi Dokumen'")
    ap.add_argument("--no-run-note", action="store_true", help="Jangan tambahkan kalimat waktu/URL eksekusi di paragraf pembuka")
    ap.add_argument("--headed", action="store_true", help="Tampilkan jendela browser (bukan headless)")
    ap.add_argument("--browser", help="Path msedge.exe / chrome.exe")
    ap.add_argument("--list-modules", action="store_true", help="[--pack] Tampilkan daftar modul paket lalu keluar")
    ap.add_argument("--list-packs", action="store_true", help="Tampilkan daftar paket lalu keluar")
    ap.add_argument("--no-interactive", action="store_true", help="Jangan bertanya; isian wajib harus lewat argumen")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    if args.list_packs:
        for p in list_packs():
            with open(os.path.join(PACKS_DIR, p, "pack.json"), encoding="utf8") as f:
                print(f"  {p:<16} {json.load(f).get('title', '')}")
        return 0
    interactive = not args.no_interactive and sys.stdin.isatty()
    pack = Pack(os.path.join(PACKS_DIR, args.pack)) if args.pack else None
    if args.list_modules:
        if not pack:
            raise SystemExit("Tanpa --pack, modul = menu aplikasi yang dibaca otomatis setelah login (jalankan py uat.py).")
        print_modules(pack)
        return 0

    try:
        browser = Browser(headless=not args.headed, browser_path=args.browser)  # cek browser sebelum mulai bertanya
    except BrowserError as e:
        raise SystemExit(str(e))

    # Urutan isian: dokumen contoh → URL → user → password → (login & baca menu) → modul → folder simpan
    if interactive:
        print("Isi data UAT (Enter = pakai nilai di dalam [ ]).")
    template, builder = get_template(args.template, interactive)
    if interactive:
        args.url = args.url or ask("URL web", pack.cfg.get("default_url") if pack else None)
        args.user = args.user or ask("User")
    args.url = normalize_url(args.url)
    for name in ("url", "user"):
        if not getattr(args, name):
            raise SystemExit(f"--{name} wajib diisi.")
    password = args.password or os.environ.get("UAT_PASSWORD")
    while not password and sys.stdin.isatty():
        password = getpass.getpass(f"Password {args.user} (tidak tampil di layar): ")
    if not password:
        raise SystemExit("--password wajib diisi (atau isi variabel lingkungan UAT_PASSWORD).")

    try:
        browser.start()
    except BrowserError as e:
        browser.close()
        raise SystemExit(f"Browser error: {e}")
    try:
        try:
            if pack:
                finish, groups, paths, prefix = prepare_pack(args, pack, browser, password, builder, interactive)
            else:
                finish, groups, paths, prefix = prepare_generic(args, browser, password, template, builder, interactive)
        except BrowserError as e:
            raise SystemExit(f"Browser error: {e}")
        out_docx, shots_dir, out_json = paths
        print(f"Format dokumen: {template}\n")
        started = time.time()
        results = run_all(groups, args.id_prefix or prefix or "UAT")
    finally:
        browser.close()

    content, extra = finish(results)
    with open(out_json, "w", encoding="utf8") as f:
        json.dump({"url": args.url, "user": args.user, **extra,
                   "results": [{**r, "images": [list(i) for i in r["images"]]} for r in results]}, f, ensure_ascii=False, indent=1)
    builder.build(content, results, out_docx)
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"\nSelesai dalam {int(time.time() - started)} detik: {len(results)} test case · "
          + ", ".join(f"{k} {v}" for k, v in counts.items()))
    print(f"Dokumen   : {out_docx}\nScreenshot: {shots_dir}\nHasil JSON: {out_json}")
    if builder.missing:
        print("Screenshot tidak ditemukan: " + ", ".join(builder.missing))
    if extra.get("data_uji_tersisa"):
        print("\nPERHATIAN: data uji berikut mungkin masih ada di aplikasi, periksa dan hapus manual:")
        for d in extra["data_uji_tersisa"]:
            print(f"  - menu {d['menu']}: {d['data']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nDibatalkan.")
        sys.exit(1)
