#!/usr/bin/env python
"""UAT otomatis aplikasi web → dokumen UAT (.docx) mengikuti format dokumen contoh.

Contoh:
  py uat.py --template "D:\\UAT\\UAT_Portal_Tenant.docx" --url https://lymanportal.vcloudproperty.com ^
            --user qa.tenant.lyman@yabes.co --modules login,request,billing --output "D:\\UAT\\Hasil"
  py uat.py            (tanpa argumen: semua isian ditanyakan satu per satu)
  py uat.py --list-modules
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
        if token not in pack.modules:
            raise SystemExit(f"Modul '{token}' tidak ada di paket {os.path.basename(pack.dir)}. Pilihan: {', '.join(names)}")
        if token not in picked:
            picked.append(token)
    return picked


def print_modules(pack):
    print(f"Modul di paket '{os.path.basename(pack.dir)}':")
    for i, name in enumerate(pack.order, 1):
        m = pack.modules[name]
        n = len(m.get("testcases", [])) if m.get("type") != "smoke" else "per halaman"
        print(f"  {i:>2}. {name:<10} {m.get('title', ''):<28} ({n} test case)")


def output_paths(output, title):
    stamp = datetime.date.today().isoformat()
    if output.lower().endswith(".docx"):
        out = os.path.abspath(output)
    else:
        safe = re.sub(r'[\\/:*?"<>|]+', "", title).strip() or "UAT"
        out = os.path.join(os.path.abspath(output), f"{safe} {stamp}.docx")
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


def main():
    ap = argparse.ArgumentParser(description="UAT otomatis aplikasi web → dokumen UAT (.docx)",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("-t", "--template", help="Dokumen contoh (.docx) yang formatnya diikuti. PDF/kosong = template bawaan.")
    ap.add_argument("-u", "--url", help="URL aplikasi web, contoh https://lymanportal.vcloudproperty.com")
    ap.add_argument("--user", help="User/email login utama")
    ap.add_argument("--password", help="Password login utama (kosongkan agar ditanyakan)")
    ap.add_argument("-m", "--modules", help="Modul yang di-UAT, pisahkan koma (nama atau nomor), atau 'all'")
    ap.add_argument("-o", "--output", help="Folder atau path .docx hasil")
    ap.add_argument("-p", "--pack", help="Paket skenario (folder di packs\\)")
    ap.add_argument("--lang", choices=["en", "id"], help="Bahasa tampilan aplikasi saat screenshot (bawaan paket)")
    ap.add_argument("--allow-write", action="store_true", help="Jalankan juga skenario yang mengirim/menyimpan data")
    ap.add_argument("--account", action="append", metavar="NAMA=USER:PASSWORD", help="Akun tambahan, mis. tenantB=amri@yabes.co:xxx atau tr=qa.tr@yabes.co")
    ap.add_argument("--param", action="append", metavar="KUNCI=NILAI", help="Parameter skenario (lihat pack.json → params)")
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
    ap.add_argument("--list-modules", action="store_true", help="Tampilkan daftar modul paket lalu keluar")
    ap.add_argument("--list-packs", action="store_true", help="Tampilkan daftar paket lalu keluar")
    ap.add_argument("--no-interactive", action="store_true", help="Jangan bertanya; isian wajib harus lewat argumen")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    packs = list_packs()
    if args.list_packs:
        for p in packs:
            with open(os.path.join(PACKS_DIR, p, "pack.json"), encoding="utf8") as f:
                print(f"  {p:<16} {json.load(f).get('title', '')}")
        return 0
    interactive = not args.no_interactive and sys.stdin.isatty()

    if not args.pack:
        if interactive and len(packs) > 1:
            print("Paket skenario: " + ", ".join(f"{i}. {p}" for i, p in enumerate(packs, 1)))
            choice = ask("Pilih paket", packs[0])
            args.pack = packs[int(choice) - 1] if choice.isdigit() else choice
        else:
            args.pack = packs[0]
    pack = Pack(os.path.join(PACKS_DIR, args.pack))
    if args.list_modules:
        print_modules(pack)
        return 0

    if interactive:
        args.template = args.template or ask("Dokumen contoh (.docx/.pdf, Enter = template bawaan)", required=False)
        args.url = args.url or ask("URL web", pack.cfg.get("default_url"))
        args.user = args.user or ask("User")
        if not args.modules:
            print_modules(pack)
            args.modules = ask("Modul yang di-UAT (nomor/nama dipisah koma, atau all)", "all")
        args.output = args.output or ask("Simpan dokumen di (folder atau .docx)", os.path.join(os.path.expanduser("~"), "Documents", "UAT"))
    for name in ("url", "user", "output"):
        if not getattr(args, name):
            raise SystemExit(f"--{name} wajib diisi.")
    password = args.password or os.environ.get("UAT_PASSWORD") or getpass.getpass(f"Password {args.user}: ")
    lang = args.lang or pack.cfg.get("default_lang", "en")
    args.lang = lang
    modules = choose_modules(pack, args.modules)

    template = args.template.strip('"') if args.template else ""
    if not template or not template.lower().endswith(".docx") or not os.path.exists(template):
        if template:
            print(f"Catatan: '{template}' bukan file .docx yang ada; format diambil dari template bawaan.")
        template = DEFAULT_TEMPLATE
    builder = DocBuilder(template)

    accounts = {"main": {"user": args.user, "password": password}}
    accounts.update(parse_accounts(args.account))
    content = build_content(args, pack, builder.tpl.defaults, modules, args.url.rstrip("/"), args.user)
    out_docx, shots_dir, out_json = output_paths(args.output, content["title"])

    print(f"\nUAT {pack.cfg.get('title', '')} · {args.url} · modul: {', '.join(modules)} · bahasa {lang.upper()}"
          f" · {'mode tulis AKTIF' if args.allow_write else 'mode baca (tanpa kirim data)'}")
    print(f"Format dokumen: {template}\n")
    started = time.time()
    browser = Browser(headless=not args.headed, browser_path=args.browser)
    results = []
    try:
        browser.start()
        runner = Runner(browser, pack, args.url, accounts, parse_kv(args.param), lang, args.allow_write, shots_dir)
        prefix = pack.cfg.get("id_prefix", "UAT")
        n = 0
        for m in modules:
            mod = pack.modules[m]
            print(f"[{mod.get('title', m)}]")
            tcs = runner.smoke_tcs(mod) if mod.get("type") == "smoke" else mod.get("testcases", [])
            for tc_def in tcs:
                n += 1
                tc_id = f"{prefix}-{n:03d}"
                tc = runner.run_tc(tc_def, tc_id)
                tc["module"] = m
                results.append(tc)
                print(f"  {tc_id} {tc['status']:<8} {tc['scenario']}")
    except BrowserError as e:
        print(f"\nBrowser error: {e}")
    except KeyboardInterrupt:
        print("\nDihentikan oleh user; dokumen dibuat dari test case yang sudah selesai.")
    finally:
        browser.close()

    with open(out_json, "w", encoding="utf8") as f:
        json.dump({"url": args.url, "user": args.user, "modules": modules, "lang": lang, "allow_write": args.allow_write,
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
