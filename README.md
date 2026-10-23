# Script UAT

UAT otomatis aplikasi web: skenario dijalankan di browser (Edge/Chrome headless), lalu hasilnya
(Actual Result, Status, screenshot) disusun menjadi dokumen UAT `.docx` yang mengikuti format dokumen contoh.

## Persiapan (sekali saja)

1. Python 3.8+ dan Microsoft Edge atau Google Chrome (di Linux/macOS: Chrome/Chromium).
2. Pasang paket:

   ```
   py -m pip install -r requirements.txt
   ```

## Menjalankan

```
py uat.py
```

Tanpa argumen, isian ditanyakan satu per satu:

| Pertanyaan | Isi |
|---|---|
| Dokumen contoh | Path `.docx` yang formatnya diikuti (boleh drag & drop file ke terminal). Enter = template bawaan. |
| URL web | Alamat aplikasi, mis. `https://lymanportal.vcloudproperty.com` (tanpa `https://` otomatis ditambahkan). |
| User | Email / User ID login. |
| Password | Tidak tampil di layar saat diketik. |
| Modul yang di-UAT | Nomor atau nama dipisah koma (`1,3` atau `login,request`), atau `all`. |
| Simpan dokumen di | Folder hasil (bawaan `Documents\UAT`) atau path `.docx` lengkap. |
| Jalankan juga? | Hanya muncul bila modul berisi skenario yang mengirim/menyimpan data (mis. membuat request). Bawaan: tidak. |

Semua isian bisa juga lewat argumen (yang tidak diisi akan ditanyakan):

```
py uat.py --template "D:\UAT\UAT_Portal_Tenant.docx" --url https://lymanportal.vcloudproperty.com ^
          --user qa.tenant.lyman@yabes.co --modules login,home,request --output "D:\UAT\Hasil"
```

Password bisa lewat `--password` atau variabel lingkungan `UAT_PASSWORD`. Untuk jadwal/CI tanpa pertanyaan sama sekali,
tambahkan `--no-interactive`.

Perintah lain:

```
py uat.py --list-modules      daftar modul & jumlah test case
py uat.py --help              semua opsi (judul dokumen, penyusun, klien, akun tambahan, bahasa, dll.)
```

## Hasil

Di folder simpan dibuat:

- `UAT Portal Tenant 2026-10-23.docx` — dokumen UAT (bila sudah ada, diberi akhiran `(2)`, `(3)`, … agar tidak menimpa)
- `..._screenshots\` — screenshot tiap test case
- `..._hasil.json` — hasil mentah

Status test case: **Pass**, **Fail**, **Blocked** (prasyarat/akun tambahan tidak ada), **Not Run**
(skenario menyimpan data tanpa `--allow-write`, atau skenario manual).

## Opsi yang sering dipakai

| Opsi | Fungsi |
|---|---|
| `--allow-write` | Jalankan juga skenario yang mengirim/menyimpan data |
| `--account nama=user:password` | Akun tambahan untuk skenario tertentu, mis. `--account tr=qa.tr@yabes.co` (password ditanyakan) |
| `--lang id` / `--lang en` | Bahasa tampilan aplikasi saat screenshot |
| `--headed` | Tampilkan jendela browser (untuk melihat jalannya tes) |
| `--browser PATH` | Path `msedge.exe` / `chrome.exe` bila tidak terdeteksi otomatis |
| `--title`, `--project`, `--client`, `--author`, `--reviewer`, `--doc-version` | Isi bagian Informasi Umum dan tanda tangan |

## Struktur

```
uat.py                     CLI
uat_engine/browser.py      kendali browser lewat Chrome DevTools Protocol
uat_engine/runner.py       menjalankan skenario JSON → Actual Result, Status, screenshot
uat_engine/docbuilder.py   menyusun .docx mengikuti dokumen contoh
packs/<aplikasi>/          paket skenario satu aplikasi
  pack.json                URL bawaan, login/logout, parameter, isi bawaan dokumen
  modules/<modul>.json     test case per modul
  i18n/en.json, id.json    teks UI aplikasi (untuk mencocokkan pesan)
  files/                   file lampiran untuk skenario upload
templates/                 dokumen contoh bawaan
```

Modul `billing`, `overtime`, `booking`, dan `akses` sudah tercantum di `packs/portal-tenant/pack.json` tetapi
file skenarionya (`modules/<modul>.json`) belum dibuat, jadi belum bisa dipilih.
