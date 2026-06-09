"""Playwright helper — dedicated background thread, Flask HTTP API.

Maintains a persistent Chromium browser (visible window) that JARVIS can
navigate, click, type, press keys, and screenshot — preserving state across
multi-step interactions like login flows.

Launches Edge directly (no Playwright automation flags) and connects via CDP
to avoid anti-bot detection.
"""
import os, sys, json, time, base64, threading, queue, traceback, subprocess

from playwright.sync_api import sync_playwright
from flask import Flask, request, jsonify

_udir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "storage", "pw-profile"))
_EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
_port = 9223  # default Flask API port, overridden by CLI arg
_cdp_port = 9224  # Edge remote debugging port (= _port + 1)

_cmd_queue = queue.Queue()
_result_queue = queue.Queue()

# Track whether browser was initialized at least once
_browser_inited = False
_edge_proc = None


def _pw_thread():
    pw = None; browser = None; ctx = None; page = None
    global _browser_inited, _edge_proc

    def _ensure():
        """Lazy-init: launch Edge directly + CDP connection. Reuse across commands."""
        nonlocal pw, browser, ctx, page

        # If page exists and is usable, keep it
        if page is not None:
            try:
                page.title(timeout=1000)
                return
            except Exception:
                pass

        # Page is dead — close old resources, create fresh
        try:
            if page is not None:
                try: page.close()
                except: pass
                page = None
            if ctx is not None:
                try: ctx.close()
                except: pass
                ctx = None
            if browser is not None:
                try: browser.close()
                except: pass
                browser = None
            if pw is not None:
                try: pw.stop()
                except: pass
                pw = None
        except Exception:
            pass

        # Kill previous Edge process if any
        global _edge_proc
        if _edge_proc and _edge_proc.poll() is None:
            try: _edge_proc.kill()
            except: pass
            _edge_proc = None

        # Launch Edge DIRECTLY (no Playwright automation flags)
        os.makedirs(_udir, exist_ok=True)
        _edge_proc = subprocess.Popen(
            [_EDGE_PATH,
             f"--remote-debugging-port={_cdp_port}",
             f"--user-data-dir={_udir}",
             "--no-first-run",
             "--no-default-browser-check",
             "--start-maximized",
             "--disable-features=msUndersuppressedNotifications",
             "--disable-sync",
             "--noerrdialogs",
             "--disable-background-networking",
             "--disable-component-update",
             "--disable-crash-reporter",
             "--disable-breakpad",
             "--disable-backgrounding-occluded-windows",
             "--disable-renderer-backgrounding",
             "--disable-hang-monitor",
             "about:blank"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Wait for Edge CDP port to be ready
        import http.client
        cdplive = False
        for _ in range(30):
            time.sleep(0.5)
            try:
                conn = http.client.HTTPConnection("127.0.0.1", _cdp_port, timeout=2)
                conn.request("GET", "/json/version")
                resp = conn.getresponse()
                if resp.status == 200:
                    cdplive = True
                    break
                conn.close()
            except Exception:
                pass
        if not cdplive:
            raise RuntimeError("Edge CDP did not start in time")

        # Connect via CDP — no automation flags, looks like a real user browser
        pw_ctx_ = sync_playwright()
        pw = pw_ctx_.__enter__()
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{_cdp_port}")
        ctx = browser.contexts[0]
        for p in ctx.pages:
            try: p.close()
            except: pass

        page = ctx.new_page()

        # Stealth init script (extra layer — CDP alone already avoids most detection)
        ctx.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
        if (window.chrome) {
            Object.defineProperty(chrome, 'runtime', {
                get: () => ({ id: undefined, connect: () => {}, sendMessage: () => {}, getManifest: () => ({}) }),
            });
        }
        const _oq = window.navigator.permissions.query;
        window.navigator.permissions.query = (p) =>
            _oq.call(window.navigator.permissions, p).then((s) => { if (p.name === 'notifications') s.state = 'prompt'; return s; });
        Object.defineProperty(navigator, 'connection', {
            get: () => ({ effectiveType: '4g', rtt: 50, downlink: 10, saveData: false }),
        });
        Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
        Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
        Object.defineProperty(screen, 'colorDepth', { get: () => 24 });
        Object.defineProperty(screen, 'pixelDepth', { get: () => 24 });
        const _getExt = HTMLCanvasElement.prototype.getContext;
        HTMLCanvasElement.prototype.getContext = function (...a) {
            const c = _getExt.apply(this, a);
            if (c && c.getParameter) { const _op = c.getParameter; c.getParameter = function (p) { if (p === 37445) return 'Intel Inc.'; if (p === 37446) return 'Intel Iris OpenGL Engine'; return _op.call(this, p); }; }
            return c;
        };
        for (const k of ['__fxdriver_unwrapped', '__selenium_unwrapped', 'callPhantom', '_Selenium_IDE_Recorder', '_selenium']) {
            if (k in window) { window[k] = undefined; }
        }
        """)
        _browser_inited = True

    def _goto(url):
        nonlocal page
        try:
            page.goto(url, timeout=15000, wait_until="domcontentloaded")
            time.sleep(1)
            return True
        except Exception:
            pass
        try:
            page.goto(url, timeout=15000, wait_until="commit")
            time.sleep(1)
            return True
        except Exception:
            return False

    while True:
        try:
            cmd, args_dict = _cmd_queue.get()
            result = {}
            try:
                if cmd == "ensure":
                    _ensure()
                    result = {"success": True}
                elif cmd == "navigate":
                    _ensure()
                    ok = _goto(args_dict["url"])
                    result = {"success": ok}
                elif cmd == "interact":
                    _ensure()
                    ok = _goto(args_dict["url"])
                    if ok:
                        for action in args_dict.get("actions", []):
                            atype, sel, val = action.get("type"), action.get("selector"), action.get("value")
                            try:
                                if atype == "click" and sel:
                                    page.click(sel); time.sleep(1)
                                elif atype == "fill" and sel and val is not None:
                                    page.fill(sel, val); time.sleep(0.5)
                                elif atype == "type" and sel and val is not None:
                                    page.type(sel, val, delay=50); time.sleep(0.5)
                                elif atype == "wait":
                                    time.sleep(int(val or 2))
                                elif atype == "press":
                                    page.keyboard.press(val or "Enter"); time.sleep(0.5)
                            except Exception:
                                pass
                        time.sleep(1)
                    result = {"success": ok, "error": "" if ok else "Navigation failed — page did not load"}
                elif cmd == "click":
                    _ensure()
                    sel = args_dict["selector"]
                    try:
                        # Try by text first (human-friendly), then CSS
                        if not sel.startswith("#") and not sel.startswith(".") and not sel.startswith("["):
                            try:
                                page.get_by_text(sel, exact=True).click()
                                time.sleep(1)
                                result = {"success": True}
                                continue
                            except Exception:
                                try:
                                    page.get_by_role("button", name=sel).click()
                                    time.sleep(1)
                                    result = {"success": True}
                                    continue
                                except Exception:
                                    try:
                                        page.get_by_placeholder(sel).click()
                                        time.sleep(1)
                                        result = {"success": True}
                                        continue
                                    except Exception:
                                        pass
                        page.click(sel)
                    except Exception:
                        try:
                            page.locator(f"text={sel}").first.click()
                        except Exception as e2:
                            raise e2
                    time.sleep(1)
                    result = {"success": True}
                elif cmd == "type":
                    _ensure()
                    sel = args_dict.get("selector", ":focus")
                    text = args_dict["text"]
                    try:
                        if sel == ":focus":
                            page.keyboard.type(text, delay=50)
                        elif not sel.startswith("#") and not sel.startswith("."):
                            try:
                                page.get_by_placeholder(sel).fill(text)
                            except Exception:
                                try:
                                    page.get_by_label(sel).fill(text)
                                except Exception:
                                    page.fill(sel, text)
                        else:
                            page.fill(sel, text)
                    except Exception:
                        try:
                            page.locator(f"text={sel}").first.fill(text)
                        except Exception as e2:
                            page.keyboard.type(text, delay=50)
                    time.sleep(0.5)
                    result = {"success": True}
                elif cmd == "press":
                    _ensure()
                    page.keyboard.press(args_dict["key"]); time.sleep(0.5)
                    result = {"success": True}
                elif cmd == "js":
                    _ensure()
                    r = page.evaluate(args_dict["script"])
                    result = {"success": True, "result": str(r)}
                elif cmd == "text":
                    _ensure()
                    el = page.query_selector(args_dict["selector"])
                    result = {"success": bool(el), "text": el.inner_text() if el else "", "error": "" if el else "not found"}
                elif cmd == "info":
                    _ensure()
                    current_url = page.url
                    title = page.title()
                    is_login = False
                    login_hint = ""
                    try:
                        has_login_input = page.locator('input[type="email"], input[type="password"], input[name="email"], input[name="password"], input[name="login"], input[autocomplete="username"]').first.is_visible(timeout=2000)
                        if has_login_input:
                            is_login = True
                            login_hint = "login_form_detected"
                    except Exception:
                        pass
                    if not is_login:
                        try:
                            has_login_btn = page.get_by_text("Log in", exact=True).first.is_visible(timeout=1000) or page.get_by_text("Sign in", exact=True).first.is_visible(timeout=1000)
                            if has_login_btn:
                                is_login = True
                                login_hint = "login_button_visible"
                        except Exception:
                            pass
                    result = {"success": True, "url": current_url, "title": title, "is_login_page": is_login, "login_hint": login_hint}
                elif cmd == "screenshot":
                    _ensure()
                    scr = page.screenshot()
                    result = {"success": True, "screenshot_base64": base64.b64encode(scr).decode(), "title": page.title(), "url": page.url}
                elif cmd == "instagram_dm":
                    _ensure()
                    username = args_dict.get("username", "").strip()
                    message = args_dict.get("message", "").strip()
                    try:
                        # 1. Navigate to Instagram DM inbox
                        ok = _goto("https://www.instagram.com/direct/inbox/")
                        if not ok:
                            result = {"success": False, "error": "Could not navigate to Instagram inbox. Are you logged in?"}
                        else:
                            time.sleep(2)
                            # 2. Check if we're on a login page
                            try:
                                is_login = page.locator('input[name="username"], input[type="password"]').first.is_visible(timeout=2000)
                                if is_login:
                                    result = {"success": False, "error": "Instagram login required. Please log in to Instagram in the browser first, then retry."}
                                    _result_queue.put(result)
                                    continue
                            except Exception:
                                pass

                            # Dismiss any "Not Now" popup dialogs (like Notifications or Save Info)
                            for _ in range(3):
                                try:
                                    # Click "Not Now" button if it appears
                                    page.locator('button:has-text("Not Now"), button:has-text("not now")').first.click(timeout=1500)
                                    time.sleep(0.5)
                                except Exception:
                                    break

                            # 3. If username given, search for conversation in inbox
                            if username:
                                # Try to find the conversation by name in the inbox list
                                clicked = False
                                try:
                                    # Instagram shows thread names in the sidebar
                                    thread = page.get_by_text(username, exact=False).first
                                    thread.click(timeout=4000)
                                    time.sleep(1.5)
                                    clicked = True
                                except Exception:
                                    pass

                                if not clicked:
                                    # Use the search/new DM flow
                                    try:
                                        # Click "New message" pencil icon or search
                                        page.get_by_role("button", name="New message").first.click(timeout=3000)
                                        time.sleep(1)
                                    except Exception:
                                        try:
                                            # Try the pencil/compose icon
                                            page.locator('[aria-label="New message"], [aria-label="New Message"]').first.click(timeout=3000)
                                            time.sleep(1)
                                        except Exception:
                                            pass
                                    # Type the username in search box
                                    try:
                                        search_box = None
                                        for selector in ['input[placeholder="Search..."]', 'input[placeholder="Search"]', 'input[name="query"]', 'input[type="text"]']:
                                            try:
                                                el = page.locator(selector).first
                                                if el.is_visible(timeout=1000):
                                                    search_box = el
                                                    break
                                            except Exception:
                                                pass
                                        if search_box:
                                            search_box.fill(username)
                                            time.sleep(2)
                                            # Click the first result
                                            clicked_result = False
                                            for result_sel in [
                                                "div[role='dialog'] div[role='checkbox']",
                                                "div[role='dialog'] span:has-text('" + username + "')",
                                                "div[role='listbox'] div[role='checkbox']",
                                                "div[role='listbox'] span",
                                                "div[role='listbox'] div",
                                                "input[type='checkbox']"
                                            ]:
                                                try:
                                                    page.locator(result_sel).first.click(timeout=2000)
                                                    clicked_result = True
                                                    break
                                                except Exception:
                                                    pass
                                            if clicked_result:
                                                time.sleep(1)
                                                # Click "Chat" / "Next" button
                                                for btn_name in ["Chat", "Next", "Start chat", "Next button"]:
                                                    try:
                                                        page.get_by_role("button", name=btn_name).first.click(timeout=2000)
                                                        time.sleep(1.5)
                                                        break
                                                    except Exception:
                                                        pass
                                        else:
                                            raise Exception("Search box not found in compose modal")
                                    except Exception as se:
                                        result = {"success": False, "error": f"Could not find user '{username}' in DMs: {se}"}
                                        _result_queue.put(result)
                                        continue
                            else:
                                # No username — pick the FIRST conversation in inbox
                                try:
                                    first_thread = page.locator("div[role='listitem'], div[role='row'], div[style*='height:'], a[href*='/direct/t/']").first
                                    first_thread.click(timeout=3000)
                                    time.sleep(1.5)
                                except Exception as fe:
                                    result = {"success": False, "error": f"No username given and could not click first DM thread: {fe}"}
                                    _result_queue.put(result)
                                    continue

                            # 4. Type and send the message
                            if message:
                                try:
                                    # Find message input box
                                    msg_box = None
                                    for selector in [
                                        '[aria-label="Message"]',
                                        'div[role="textbox"]',
                                        '[contenteditable="true"]',
                                        '[placeholder="Message..."]',
                                        'textarea[placeholder="Message..."]',
                                        'textarea'
                                    ]:
                                        try:
                                            el = page.locator(selector).first
                                            if el.is_visible(timeout=1000):
                                                msg_box = el
                                                break
                                        except Exception:
                                            pass
                                    if msg_box:
                                        msg_box.click(timeout=3000)
                                        time.sleep(0.5)
                                        page.keyboard.type(message, delay=40)
                                        time.sleep(0.5)
                                        page.keyboard.press("Enter")
                                        time.sleep(1)
                                        result = {"success": True, "sent_to": username or "first conversation", "message": message}
                                    else:
                                        raise Exception("Message input box not found")
                                except Exception as me:
                                    result = {"success": False, "error": f"Could not type/send message: {me}"}
                            else:
                                result = {"success": True, "sent_to": username or "first conversation", "message": "(no message — conversation opened)"}
                    except Exception as ig_e:
                        result = {"success": False, "error": f"Instagram DM error: {ig_e}"}

                elif cmd == "instagram_read_inbox":
                    _ensure()
                    try:
                        ok = _goto("https://www.instagram.com/direct/inbox/")
                        if not ok:
                            result = {"success": False, "error": "Could not navigate to Instagram inbox."}
                        else:
                            time.sleep(2)
                            # Dismiss popups if any
                            for _ in range(2):
                                try:
                                    page.locator('button:has-text("Not Now"), button:has-text("not now")').first.click(timeout=1000)
                                    time.sleep(0.5)
                                except Exception:
                                    break
                            threads = []
                            for selector in ["div[role='listitem']", "div[role='row']", "div[style*='height:']", "a[href*='/direct/t/']"]:
                                try:
                                    texts = page.locator(selector).all_text_contents()
                                    cleaned = [t.strip().split("\n")[0] for t in texts if t.strip()]
                                    if cleaned:
                                        threads = cleaned
                                        break
                                except Exception:
                                    pass
                            if not threads:
                                try:
                                    threads = page.locator("div[style*='flex-direction: column'] span").all_text_contents()
                                    threads = list(set([t.strip() for t in threads if len(t.strip()) > 2 and len(t.strip()) < 30]))[:15]
                                except Exception:
                                    pass
                            result = {"success": True, "conversations": threads[:20]}
                    except Exception as ire:
                        result = {"success": False, "error": str(ire)}

                elif cmd == "close":
                    if page:
                        try: page.close()
                        except: pass
                        page = None
                    if ctx:
                        try: ctx.close()
                        except: pass
                        ctx = None
                    if browser:
                        try: browser.close()
                        except: pass
                        browser = None
                    if pw:
                        try: pw.stop()
                        except: pass
                        pw = None
                    if _edge_proc and _edge_proc.poll() is None:
                        try: _edge_proc.kill()
                        except: pass
                        _edge_proc = None
                    result = {"success": True}
                else:
                    result = {"success": False, "error": f"Unknown command: {cmd}"}
            except Exception as e:
                traceback.print_exc()
                result = {"success": False, "error": str(e)}
            _result_queue.put(result)
        except Exception as e:
            # If there's an error getting from the queue or in the outer loop,
            # we still want to put a result if possible to avoid hanging the caller
            try:
                traceback.print_exc()
                _result_queue.put({"success": False, "error": f"Thread error: {str(e)}"})
            except:
                pass  # If we can't even put to the result queue, there's nothing we can do


t = threading.Thread(target=_pw_thread, daemon=True)
t.start()


def _run(cmd, timeout=25, **kwargs):
    _cmd_queue.put((cmd, kwargs))
    try:
        return _result_queue.get(timeout=timeout)
    except queue.Empty:
        return {"success": False, "error": "browser command timed out"}


app = Flask(__name__)


@app.route("/ensure", methods=["POST"])
def route_ensure():
    return jsonify(_run("ensure", timeout=30))


@app.route("/navigate", methods=["POST"])
def route_navigate():
    data = request.get_json()
    return jsonify(_run("navigate", timeout=30, url=data["url"]))


@app.route("/interact", methods=["POST"])
def route_interact():
    data = request.get_json()
    return jsonify(_run("interact", timeout=40, url=data["url"], actions=data.get("actions", [])))


@app.route("/click", methods=["POST"])
def route_click():
    return jsonify(_run("click", timeout=15, selector=request.get_json()["selector"]))


@app.route("/type", methods=["POST"])
def route_type():
    d = request.get_json()
    return jsonify(_run("type", timeout=15, selector=d.get("selector", ":focus"), text=d["text"]))


@app.route("/press", methods=["POST"])
def route_press():
    return jsonify(_run("press", timeout=10, key=request.get_json()["key"]))


@app.route("/js", methods=["POST"])
def route_js():
    return jsonify(_run("js", timeout=15, script=request.get_json()["script"]))


@app.route("/text", methods=["POST"])
def route_text():
    return jsonify(_run("text", timeout=10, selector=request.get_json()["selector"]))


@app.route("/info", methods=["POST"])
def route_info():
    return jsonify(_run("info", timeout=10))


@app.route("/screenshot", methods=["POST"])
def route_screenshot():
    return jsonify(_run("screenshot", timeout=15))


@app.route("/close", methods=["POST"])
def route_close():
    return jsonify(_run("close", timeout=10))


@app.route("/health", methods=["GET"])
def route_health():
    return jsonify({"status": "running", "thread_alive": t.is_alive()})


@app.route("/instagram_dm", methods=["POST"])
def route_instagram_dm():
    d = request.get_json()
    return jsonify(_run(
        "instagram_dm", timeout=60,
        username=d.get("username", ""),
        message=d.get("message", ""),
    ))


@app.route("/instagram_read_inbox", methods=["POST"])
def route_instagram_read_inbox():
    return jsonify(_run("instagram_read_inbox", timeout=30))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        _port = int(sys.argv[1])
    print(f"pw_browser starting on port {_port}", flush=True)
    app.run(host="127.0.0.1", port=_port, debug=False, use_reloader=False, threaded=True)
