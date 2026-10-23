"""Browser headless (Microsoft Edge / Google Chrome) lewat Chrome DevTools Protocol.

Tanpa Playwright/Selenium: cukup paket `websocket-client`. Satu instance = satu profil browser sementara,
jadi cookie/sesi tidak bercampur dengan browser milik user.
"""
import base64
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request

try:
    import websocket  # websocket-client
except ImportError:  # pragma: no cover - dicek di uat.py
    websocket = None

BROWSER_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]
# Linux / PATH
BROWSER_NAMES = ["microsoft-edge", "microsoft-edge-stable", "google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser", "msedge", "chrome"]

DESKTOP = dict(width=1366, height=800, deviceScaleFactor=1, mobile=False)
MOBILE = dict(width=390, height=844, deviceScaleFactor=2, mobile=True)


class BrowserError(Exception):
    pass


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def find_browser(explicit=None):
    explicit = explicit or os.environ.get("UAT_BROWSER")
    if explicit:
        if os.path.exists(explicit):
            return explicit
        raise BrowserError(f"Browser tidak ditemukan: {explicit}")
    for p in BROWSER_PATHS + [shutil.which(n) for n in BROWSER_NAMES]:
        if p and os.path.exists(p):
            return p
    raise BrowserError("Microsoft Edge / Google Chrome / Chromium tidak ditemukan. "
                       "Isi --browser dengan path msedge.exe, chrome.exe, atau chromium.")


class Browser:
    def __init__(self, headless=True, browser_path=None, log=print):
        if websocket is None:
            raise BrowserError("Paket 'websocket-client' belum terpasang: py -m pip install -r requirements.txt")
        self.headless = headless
        self.exe = find_browser(browser_path)
        self.log = log
        self.proc = None
        self.ws = None
        self.profile = None
        self._id = 0
        self.inflight = {}
        self.loading = False
        self.main_frame = None
        self.last_doc_status = None
        self.last_doc_url = None
        self.console_errors = []
        self.last_dialog = None
        self.dialog_accept = True
        self.viewport = "desktop"
        self.post_times = []

    # ── siklus hidup ────────────────────────────────────────────────────
    def start(self):
        port = _free_port()
        self.profile = tempfile.mkdtemp(prefix="uat_profile_")
        args = [self.exe, f"--remote-debugging-port={port}", f"--user-data-dir={self.profile}",
                "--no-first-run", "--no-default-browser-check", "--disable-extensions", "--disable-sync",
                "--disable-features=Translate,msEdgeSidebarV2,msHubApps", "--remote-allow-origins=*",
                "--window-size=1366,800", "about:blank"]
        if self.headless:
            args.insert(1, "--headless=new")
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            args.insert(1, "--no-sandbox")  # Chromium menolak jalan sebagai root (Linux/Docker) tanpa ini
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # DevTools ada di localhost: jangan lewat proxy dari HTTP(S)_PROXY
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.time() + 30
        target = None
        while time.time() < deadline and target is None:
            if self.proc.poll() is not None:
                raise BrowserError(f"Browser langsung tertutup (kode {self.proc.returncode}): {self.exe}")
            try:
                with opener.open(f"http://127.0.0.1:{port}/json/list", timeout=2) as r:
                    pages = [t for t in json.load(r) if t.get("type") == "page"]
                target = pages[0] if pages else None
            except Exception:
                time.sleep(0.25)
        if target is None:
            raise BrowserError("Browser tidak dapat dijalankan (DevTools tidak merespons).")
        self.ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=60, suppress_origin=True,
                                              enable_multithread=False)
        for domain in ("Page", "Runtime", "Network"):
            self.send(f"{domain}.enable")
        self.main_frame = self.send("Page.getFrameTree")["frameTree"]["frame"]["id"]
        self.set_viewport("desktop")
        return self

    def close(self):
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except Exception:
                self.proc.kill()
        if self.profile:
            shutil.rmtree(self.profile, ignore_errors=True)

    # ── protokol ────────────────────────────────────────────────────────
    def send(self, method, params=None, timeout=90):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while True:
            if time.time() > deadline:
                raise BrowserError(f"Timeout menunggu {method}")
            msg = self._recv(deadline)
            if msg is not None and msg.get("id") == mid:
                if "error" in msg:
                    raise BrowserError(f"{method}: {msg['error'].get('message')}")
                return msg.get("result", {})

    def _recv(self, deadline):
        self.ws.settimeout(max(0.05, deadline - time.time()))
        try:
            raw = self.ws.recv()
        except websocket.WebSocketTimeoutException:
            return None
        msg = json.loads(raw)
        if "method" in msg:
            self._on_event(msg["method"], msg.get("params", {}))
        return msg

    def _post(self, method, params=None):
        """Perintah tanpa menunggu jawaban (dipakai di dalam penanganan event)."""
        self._id += 1
        self.ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))

    def _on_event(self, method, p):
        if method == "Network.requestWillBeSent":
            if p.get("type") not in ("WebSocket", "EventSource"):
                self.inflight[p["requestId"]] = time.time()
            if p.get("request", {}).get("method") == "POST" and p.get("type") == "Document":
                self.post_times.append(time.time())
        elif method in ("Network.loadingFinished", "Network.loadingFailed"):
            self.inflight.pop(p.get("requestId"), None)
        elif method == "Network.responseReceived" and p.get("type") == "Document":
            self.last_doc_status = p["response"].get("status")
            self.last_doc_url = p["response"].get("url")
        elif method == "Page.frameStartedLoading" and p.get("frameId") == self.main_frame:
            self.loading = True
        elif method in ("Page.loadEventFired",):
            self.loading = False
        elif method == "Page.frameStoppedLoading" and p.get("frameId") == self.main_frame:
            self.loading = False
        elif method == "Page.javascriptDialogOpening":
            self.last_dialog = p.get("message")
            self._post("Page.handleJavaScriptDialog", {"accept": self.dialog_accept})
        elif method == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails", {})
            self.console_errors.append((d.get("exception") or {}).get("description") or d.get("text"))
        elif method == "Runtime.consoleAPICalled" and p.get("type") == "error":
            self.console_errors.append(" ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", [])))

    def pump(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            self._recv(end)

    def settle(self, timeout=60, idle=0.5, first=0.3):
        """Tunggu navigasi selesai dan jaringan diam selama `idle` detik."""
        self.pump(first)
        end = time.time() + timeout
        quiet = None
        while time.time() < end:
            stale = [k for k, t in self.inflight.items() if time.time() - t > 30]
            for k in stale:  # permintaan menggantung (long-poll) tidak ditunggu
                self.inflight.pop(k, None)
            busy = self.loading or bool(self.inflight)
            if busy:
                quiet = None
            else:
                quiet = quiet or time.time()
                if time.time() - quiet >= idle:
                    break
            self.pump(0.1)
        try:
            self.eval("document.readyState")
        except BrowserError:
            pass

    # ── navigasi & JavaScript ───────────────────────────────────────────
    def goto(self, url, timeout=90):
        self.last_doc_status = None
        res = self.send("Page.navigate", {"url": url}, timeout=timeout)
        if res.get("errorText"):
            raise BrowserError(f"Gagal membuka {url}: {res['errorText']}")
        self.settle(timeout=timeout)
        return self.last_doc_status

    def eval(self, expression, timeout=60):
        res = self.send("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True,
                                             "userGesture": True}, timeout=timeout)
        if res.get("exceptionDetails"):
            d = res["exceptionDetails"]
            msg = (d.get("exception") or {}).get("description") or d.get("text") or "error"
            raise BrowserError(msg.split("\n")[0].replace("Error: ", ""))
        return res.get("result", {}).get("value")

    def _el(self, selector, body):
        """Jalankan `body` (JS) dengan variabel `el` = elemen pertama yang cocok dengan selector."""
        sel = json.dumps(selector)
        return self.eval(f"(() => {{ const el = document.querySelector({sel}); "
                         f"if (!el) throw new Error('Elemen tidak ditemukan: ' + {sel}); {body} }})()")

    def url(self):
        return self.eval("location.href")

    def exists(self, selector):
        return bool(self.eval(f"!!document.querySelector({json.dumps(selector)})"))

    def visible(self, selector):
        return bool(self.eval(f"(() => {{ const e = document.querySelector({json.dumps(selector)}); "
                              "return !!e && !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length); })()"))

    def count(self, selector):
        return self.eval(f"document.querySelectorAll({json.dumps(selector)}).length")

    def text(self, selector):
        if not self.exists(selector):
            return None
        return self._el(selector, "return (el.innerText || el.value || el.textContent || '').trim().replace(/\\s+/g, ' ');")

    def texts(self, selector):
        return self.eval(f"[...document.querySelectorAll({json.dumps(selector)})]"
                         ".map(e => (e.innerText || e.textContent || '').trim().replace(/\\s+/g, ' ')).filter(Boolean)")

    def attr(self, selector, name):
        return self._el(selector, f"return el.getAttribute({json.dumps(name)});")

    def value(self, selector):
        return self._el(selector, "return el.value;")

    def disabled(self, selector):
        return bool(self._el(selector, "return !!el.disabled;"))

    def messages(self, selector):
        return self.eval(f"[...document.querySelectorAll({json.dumps(selector)})]"
                         ".filter(e => e.offsetParent !== null || e.getClientRects().length)"
                         ".map(e => (e.innerText || '').trim().replace(/\\s+/g, ' ')).filter(Boolean)")

    # ── aksi ────────────────────────────────────────────────────────────
    def click(self, selector, settle=True):
        self._el(selector, "el.scrollIntoView({block: 'center'}); el.click(); return true;")
        if settle:
            self.settle()

    def fill(self, selector, value):
        self._el(selector, f"""
            const v = {json.dumps(str(value))};
            const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(proto, 'value');
            if (setter && setter.set) setter.set.call(el, v); else el.value = v;
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
            return true;""")
        self.pump(0.1)

    def select(self, selector, value=None, label=None, index=None):
        how = json.dumps({"value": value, "label": label, "index": index})
        self._el(selector, f"""
            const h = {how}; const opts = [...el.options];
            let o = null;
            if (h.value !== null) o = opts.find(x => x.value === String(h.value));
            if (!o && h.label !== null) o = opts.find(x => x.textContent.trim() === String(h.label));
            if (!o && h.index !== null) o = opts[h.index];
            if (!o) throw new Error('Pilihan tidak ditemukan di ' + {json.dumps(selector)});
            el.value = o.value;
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
            return true;""")
        self.settle(first=0.3)

    def set_checked(self, selector, on=True):
        self._el(selector, f"if (el.checked !== {json.dumps(bool(on))}) el.click(); return true;")
        self.pump(0.15)

    def upload(self, selector, files):
        root = self.send("DOM.getDocument", {"depth": 0})["root"]["nodeId"]
        node = self.send("DOM.querySelector", {"nodeId": root, "selector": selector}).get("nodeId")
        if not node:
            raise BrowserError(f"Elemen tidak ditemukan: {selector}")
        self.send("DOM.setFileInputFiles", {"nodeId": node, "files": [os.path.abspath(f) for f in files]})
        self.pump(0.4)

    def fetch(self, url):
        """GET dengan cookie sesi halaman; kembalikan status, content-type, ukuran."""
        return self.eval(f"""fetch({json.dumps(url)}, {{credentials: 'include'}}).then(async r => {{
            const b = await r.arrayBuffer();
            return {{status: r.status, type: r.headers.get('content-type') || '', size: b.byteLength, url: r.url}}; }})""")

    def clear_session(self):
        self.send("Network.clearBrowserCookies")
        try:
            self.eval("try { localStorage.clear(); sessionStorage.clear(); } catch (e) {} true")
        except BrowserError:
            pass

    def set_viewport(self, kind):
        m = MOBILE if kind == "mobile" else DESKTOP
        self.send("Emulation.setDeviceMetricsOverride", dict(m))
        self.send("Emulation.setTouchEmulationEnabled", {"enabled": bool(m["mobile"])})
        self.viewport = kind

    # ── screenshot ──────────────────────────────────────────────────────
    def screenshot(self, path, full=False, selector=None, pad=0, clip=None):
        params = {"format": "png"}
        if selector:
            r = self._el(selector, "el.scrollIntoView({block: 'center'}); const b = el.getBoundingClientRect(); "
                                   "return [b.left + scrollX, b.top + scrollY, b.width, b.height, "
                                   "document.documentElement.scrollWidth];")
            x, y, w, h, docw = r
            x0, y0 = max(0, x - pad), max(0, y - pad)
            params.update(clip={"x": x0, "y": y0, "width": min(docw - x0, w + 2 * pad), "height": h + 2 * pad, "scale": 1},
                          captureBeyondViewport=True)
        elif clip:
            params.update(clip={"x": clip[0], "y": clip[1], "width": clip[2], "height": clip[3], "scale": 1})
        elif full:
            m = self.send("Page.getLayoutMetrics")
            size = m.get("cssContentSize") or m.get("contentSize")
            vw = (m.get("cssLayoutViewport") or m.get("layoutViewport"))["clientWidth"]
            params.update(clip={"x": 0, "y": 0, "width": max(vw, size["width"]), "height": size["height"], "scale": 1},
                          captureBeyondViewport=True)
        data = self.send("Page.captureScreenshot", params)["data"]
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))
        return path
