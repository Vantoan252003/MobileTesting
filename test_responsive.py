# test_responsive.py  --  Viewport Tester entry point
# Chay: venv/bin/python test_responsive.py

import warnings; warnings.filterwarnings("ignore")
import os, json, threading, webbrowser, time, socket, re, base64

from flask import Flask, render_template, request, Response, send_file, jsonify
from devices import DEVICES, DEVICE_MAP
from tester  import capture_viewports, test_interactions, generate_report

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ket_qua")
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = Flask(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_params():
    url     = request.args.get("url", "").strip()
    dev_ids = [x.strip() for x in request.args.get("devices", "").split(",") if x.strip()]
    viewports = [DEVICE_MAP[d] for d in dev_ids if d in DEVICE_MAP] or DEVICES
    return url, viewports


def _stream(fn):
    """Run fn(log_fn) in a thread and yield SSE events back to the client."""
    buf, evt = [], threading.Event()

    def log_fn(msg):
        buf.append(msg)
        evt.set()

    result_h, err_h = [None], [None]

    def worker():
        try:
            result_h[0] = fn(log_fn)
        except Exception as exc:
            err_h[0] = str(exc)
            log_fn("ERROR: " + str(exc))
        finally:
            log_fn("__DONE__")

    threading.Thread(target=worker, daemon=True).start()

    def gen():
        step = [0]
        while True:
            evt.wait(0.3)
            evt.clear()
            while buf:
                msg = buf.pop(0)
                if msg == "__DONE__":
                    if err_h[0]:
                        yield "event: error\ndata: " + err_h[0] + "\n\n"
                        return
                    yield "event: progress\ndata: 100\n\n"
                    yield "event: done\ndata: " + json.dumps({"path": result_h[0]}) + "\n\n"
                    return
                step[0] += 1
                pct = str(min(95, step[0] * 3))
                yield "event: progress\ndata: " + pct + "\n\n"
                yield "event: log\ndata: " + msg + "\n\n"

    return gen()


def _extract_js_array(html: str, var_name: str):
    match = re.search(rf"var\s+{re.escape(var_name)}\s*=\s*(\[)", html)
    if not match:
        return []

    start = match.start(1)
    depth = 0
    for index in range(start, len(html)):
        char = html[index]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return json.loads(html[start:index + 1])
    return []


def _png_b64(path: str) -> str:
    if not path or not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def _first_existing_path(*paths: str) -> str:
    for path in paths:
        if path and os.path.exists(path):
            return path
    return ""


def _report_needs_rebuild(path: str) -> bool:
    if not os.path.exists(path):
        return True

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        head = f.read(4096)

    return "var SCREENS" in head or "var INTERACTS" in head


def _rebuild_report_from_existing_artifacts(output_dir: str):
    path = os.path.join(output_dir, "report.html")
    old_html = ""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            old_html = f.read()

    screens = []
    for device in DEVICES:
        file_path = _first_existing_path(
            os.path.join(output_dir, f"screen_{device['id']}_{device['width']}px.png"),
            os.path.join(output_dir, f"screen_{device['width']}px.png"),
        )
        if os.path.exists(file_path):
            screens.append({
                "id": device["id"],
                "name": device["name"],
                "width": device["width"],
                "height": device["height"],
                "group": device.get("group", ""),
                "b64": _png_b64(file_path),
            })

    if not screens and old_html:
        try:
            old_screens = _extract_js_array(old_html, "SCREENS")
            for item in old_screens:
                url = item.get("url", "")
                if url.startswith("data:image/png;base64,"):
                    matched_device = next(
                        (device for device in DEVICES if device["name"] == item.get("name")),
                        None,
                    )
                    screens.append({
                        "id": matched_device["id"] if matched_device else "",
                        "name": item.get("name", "Viewport"),
                        "width": item.get("width", 0),
                        "height": item.get("height", 0),
                        "group": item.get("group", matched_device.get("group", "") if matched_device else ""),
                        "b64": url.split(",", 1)[1],
                    })
        except Exception:
            pass

    interactions = []
    if old_html:
        try:
            old_interacts = _extract_js_array(old_html, "INTERACTS")
            for item in old_interacts:
                sc_url = item.get("sc_url", "")
                screenshot_b64 = ""
                if sc_url.startswith("data:image/png;base64,"):
                    screenshot_b64 = sc_url.split(",", 1)[1]
                else:
                    matched_device = next(
                        (device for device in DEVICES if device["name"] == item.get("name")),
                        None,
                    )
                    if matched_device:
                        file_path = _first_existing_path(
                            os.path.join(output_dir, f"interact_{matched_device['id']}_{item.get('width', 0)}px.png"),
                            os.path.join(output_dir, f"interact_{item.get('width', 0)}px.png"),
                        )
                        screenshot_b64 = _png_b64(file_path)
                matched_device = next(
                    (device for device in DEVICES if device["name"] == item.get("name")),
                    None,
                )

                interactions.append({
                    "id": matched_device["id"] if matched_device else "",
                    "name": item.get("name", "Viewport"),
                    "width": item.get("width", 0),
                    "height": item.get("height", 0),
                    "group": item.get("group", matched_device.get("group", "") if matched_device else ""),
                    "summary": item.get("summary", {}),
                    "elements": item.get("elements", []),
                    "error": item.get("error"),
                    "screenshot_b64": screenshot_b64,
                })
        except Exception:
            interactions = []

    title_match = re.search(r"<title>[^<]*[–-]\s*([^<]+)</title>", old_html)
    report_url = title_match.group(1).strip() if title_match else "about:blank"

    return generate_report(report_url, screens, interactions, output_dir)


SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/devices")
def api_devices():
    return jsonify([
        {"id": d["id"], "name": d["name"], "width": d["width"],
         "height": d["height"], "group": d.get("group", "")}
        for d in DEVICES
    ])


@app.route("/api/screenshot")
def api_screenshot():
    url, viewports = _get_params()

    def run(log):
        shots = capture_viewports(url, viewports, OUTPUT_DIR, log)
        return generate_report(url, shots, [], OUTPUT_DIR)

    return Response(_stream(run), mimetype="text/event-stream", headers=SSE_HEADERS)


@app.route("/api/interact")
def api_interact():
    url, viewports = _get_params()

    def run(log):
        interactions = test_interactions(url, viewports, OUTPUT_DIR, log)
        return generate_report(url, [], interactions, OUTPUT_DIR)

    return Response(_stream(run), mimetype="text/event-stream", headers=SSE_HEADERS)


@app.route("/api/full")
def api_full():
    url, viewports = _get_params()

    def run(log):
        log("Buoc 1: Chup man hinh cac viewport...")
        shots = capture_viewports(url, viewports, OUTPUT_DIR, log)
        log("Buoc 2: Kiem thu tuong tac...")
        interactions = test_interactions(url, viewports, OUTPUT_DIR, log)
        log("Tao bao cao...")
        return generate_report(url, shots, interactions, OUTPUT_DIR)

    return Response(_stream(run), mimetype="text/event-stream", headers=SSE_HEADERS)


@app.route("/report")
def report():
    path = os.path.join(OUTPUT_DIR, "report.html")
    if _report_needs_rebuild(path):
        try:
            path = _rebuild_report_from_existing_artifacts(OUTPUT_DIR)
        except Exception:
            pass
    if not os.path.exists(path):
        return "<p>Chua co bao cao. Hay chay test truoc!</p>", 404
    return send_file(path)


@app.route("/download")
def download():
    path = os.path.join(OUTPUT_DIR, "report.html")
    if _report_needs_rebuild(path):
        try:
            path = _rebuild_report_from_existing_artifacts(OUTPUT_DIR)
        except Exception:
            pass
    if not os.path.exists(path):
        return "Khong tim thay bao cao.", 404
    return send_file(path, as_attachment=True, download_name="report.html")


@app.route("/ket_qua/<path:filename>")
def serve_output(filename):
    """Serve PNG screenshots tu thu muc ket_qua."""
    safe = os.path.basename(filename)
    return send_file(os.path.join(OUTPUT_DIR, safe))


# ── Start ─────────────────────────────────────────────────────────────────────

def _free_port(start=5001, end=5020):
    for p in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("", p))
                return p
            except OSError:
                pass
    raise RuntimeError("Khong tim duoc port trong 5001-5020")


if __name__ == "__main__":
    port = _free_port()
    print("=" * 50)
    print("  Viewport Tester")
    print("  http://localhost:" + str(port))
    print("=" * 50)
    threading.Thread(
        target=lambda: (time.sleep(1.3), webbrowser.open("http://localhost:" + str(port))),
        daemon=True,
    ).start()
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)

