# tester.py – Kiểm thử hiển thị + tương tác trên nhiều viewport

import os
import io
import time
import base64
import datetime
import html as html_lib
import re

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, ElementClickInterceptedException,
    ElementNotInteractableException, StaleElementReferenceException,
)


# ─────────────────────────────────────────────────────────────
# Driver
# ─────────────────────────────────────────────────────────────

def _make_driver(width: int, height: int, ua: str = None) -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--log-level=3")
    opts.add_argument("--hide-scrollbars")
    if ua:
        opts.add_argument(f"--user-agent={ua}")
    driver = webdriver.Chrome(options=opts)
    driver.set_window_size(width, height)
    return driver


def _screenshot_b64(driver) -> str:
    """Chụp màn hình, trả về base64."""
    return base64.b64encode(driver.get_screenshot_as_png()).decode()


def _load_page(driver, url: str, log_fn):
    """Tải trang và đợi body xuất hiện."""
    driver.get(url)
    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
    except TimeoutException:
        log_fn("  Cảnh báo: Trang tải quá 20 giây")
    time.sleep(1.5)  # đợi JS / animation hoàn tất


# ─────────────────────────────────────────────────────────────
# 1. CHỤP MÀN HÌNH – NHIỀU VIEWPORT (1 driver, resize liên tục)
# ─────────────────────────────────────────────────────────────

def capture_viewports(url: str, viewports: list, output_dir: str, log_fn=print) -> list:
    """
    Mở trang 1 lần duy nhất rồi resize viewport liên tục (không reload).
    Chụp ảnh full-page tại mỗi kích thước.

    viewports: list of {"name", "width", "height", "ua"(optional)}
    Trả về list dict chứa ảnh base64 mỗi viewport.
    """
    if not url.startswith("http"):
        url = "https://" + url

    os.makedirs(output_dir, exist_ok=True)
    results = []

    # Dùng UA của viewport đầu tiên (nếu có) để tải trang
    first_ua = viewports[0].get("ua") if viewports else None
    driver = _make_driver(viewports[0]["width"], viewports[0]["height"], first_ua)

    try:
        log_fn(f"  Tải trang: {url}")
        _load_page(driver, url, log_fn)

        for vp in viewports:
            w, h = vp["width"], vp["height"]
            name = vp["name"]
            device_id = vp.get("id", "")
            group = vp.get("group", "")
            log_fn(f"  Resize → {name} ({w}×{h}px)...")

            # Thay UA nếu cần (không thể đổi UA không reload, nhưng resize vẫn hiệu quả)
            driver.set_window_size(w, h)
            time.sleep(0.7)  # đợi CSS media query phản hồi

            # Expand để chụp full-page
            full_h = driver.execute_script("return document.body.scrollHeight")
            driver.set_window_size(w, max(h, full_h))
            time.sleep(0.3)

            b64 = _screenshot_b64(driver)

            # Lưu file PNG
            fname = f"screen_{device_id}_{w}px.png" if device_id else f"screen_{w}px.png"
            fpath = os.path.join(output_dir, fname)
            with open(fpath, "wb") as f:
                f.write(base64.b64decode(b64))

            results.append({
                "id":     device_id,
                "group":  group,
                "name":   name,
                "width":  w,
                "height": h,
                "b64":    b64,
                "file":   fpath,
            })
            log_fn(f"  Chụp xong {name} ({w}×{h}px) -> {fname}")
    finally:
        driver.quit()

    return results


# ─────────────────────────────────────────────────────────────
# 2. KIỂM THỬ TƯƠNG TÁC – BUTTON / LINK / FORM TRÊN TỪNG VIEWPORT
# ─────────────────────────────────────────────────────────────

def _find_interactive_elements(driver) -> list:
    """Thu thập tất cả phần tử có thể tương tác (button, link, input, select)."""
    elements = []
    selectors = {
        "button":  "button",
        "link":    "a[href]",
        "input":   "input:not([type='hidden'])",
        "select":  "select",
        "textarea":"textarea",
    }
    for kind, sel in selectors.items():
        for el in driver.find_elements(By.CSS_SELECTOR, sel):
            try:
                if not el.is_displayed():
                    continue
                label = (
                    el.text.strip()
                    or el.get_attribute("value") or ""
                    or el.get_attribute("placeholder") or ""
                    or el.get_attribute("aria-label") or ""
                    or el.get_attribute("title") or ""
                    or el.get_attribute("href") or ""
                    or f"<{el.tag_name}>"
                )[:60]
                rect = el.rect
                elements.append({
                    "kind":    kind,
                    "label":   label,
                    "x":       round(rect["x"], 1),
                    "y":       round(rect["y"], 1),
                    "w":       round(rect["width"], 1),
                    "h":       round(rect["height"], 1),
                })
            except Exception:
                pass
    return elements


def _try_click(driver, el) -> dict:
    """
    Thử click một element:
    - Kiểm tra trước/sau URL để phát hiện navigation
    - Kiểm tra modal/overlay xuất hiện
    - Trả về kết quả chi tiết
    """
    url_before = driver.current_url
    result = {
        "clicked":   False,
        "navigated": False,
        "error":     None,
        "note":      "",
    }
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.2)
        el.click()
        result["clicked"] = True
        time.sleep(0.5)

        url_after = driver.current_url
        if url_after != url_before:
            result["navigated"] = True
            result["note"] = f"→ {url_after[:80]}"
            driver.back()
            time.sleep(0.8)
        else:
            # Kiểm tra modal/dialog xuất hiện
            for modal_sel in ["[class*='modal']", "[class*='dialog']", "[class*='popup']",
                               "[role='dialog']", "[class*='overlay']"]:
                modals = driver.find_elements(By.CSS_SELECTOR, modal_sel)
                for m in modals:
                    if m.is_displayed():
                        result["note"] = "Modal/popup xuất hiện"
                        # Đóng bằng Escape
                        try:
                            from selenium.webdriver.common.keys import Keys
                            m.send_keys(Keys.ESCAPE)
                        except Exception:
                            pass
                        break

    except ElementClickInterceptedException:
        result["error"] = "Bị che khuất (intercepted)"
    except ElementNotInteractableException:
        result["error"] = "Không thể tương tác (not interactable)"
    except StaleElementReferenceException:
        result["error"] = "Element đã thay đổi (stale)"
    except Exception as e:
        result["error"] = str(e)[:80]

    return result


def test_interactions(url: str, viewports: list, output_dir: str, log_fn=print) -> list:
    """
    Với mỗi viewport:
      - Tải trang
      - Thu thập tất cả phần tử tương tác
      - Kiểm tra kích thước (tap target >= 44px?)
      - Thử click từng button/link và ghi nhận kết quả
      - Chụp màn hình trạng thái ban đầu

    Trả về list kết quả theo viewport.
    """
    if not url.startswith("http"):
        url = "https://" + url

    os.makedirs(output_dir, exist_ok=True)
    all_results = []

    for vp in viewports:
        w, h   = vp["width"], vp["height"]
        name   = vp["name"]
        ua     = vp.get("ua")
        device_id = vp.get("id", "")
        group = vp.get("group", "")

        log_fn(f"\n  [{name} - {w}×{h}px] Đang test tương tác...")
        driver = _make_driver(w, h, ua)

        vp_result = {
            "id":       device_id,
            "group":    group,
            "name":     name,
            "width":    w,
            "height":   h,
            "elements": [],
            "summary":  {},
            "screenshot_b64": "",
        }

        try:
            _load_page(driver, url, log_fn)

            # Chụp màn hình ban đầu
            vp_result["screenshot_b64"] = _screenshot_b64(driver)
            if vp_result["screenshot_b64"]:
                fname = f"interact_{device_id}_{w}px.png" if device_id else f"interact_{w}px.png"
                fpath = os.path.join(output_dir, fname)
                with open(fpath, "wb") as f:
                    f.write(base64.b64decode(vp_result["screenshot_b64"]))
                vp_result["file"] = fpath

            # Thu thập phần tử
            elements = _find_interactive_elements(driver)
            log_fn(f"  Tìm thấy {len(elements)} phần tử tương tác")

            el_results = []
            ok_count   = 0
            warn_count = 0
            err_count  = 0

            for i, info in enumerate(elements):
                # Kích thước tap target
                tap_ok = info["w"] >= 44 and info["h"] >= 44
                if not tap_ok:
                    warn_count += 1

                # Chỉ thử click button và link (không click input/select vì phức tạp)
                click_result = None
                if info["kind"] in ("button", "link"):
                    # Lấy lại element (tránh stale)
                    try:
                        sel_map = {"button": "button", "link": "a[href]"}
                        fresh_els = driver.find_elements(By.CSS_SELECTOR, sel_map[info["kind"]])
                        # Khớp theo text/label
                        matched = None
                        for fe in fresh_els:
                            try:
                                if fe.is_displayed() and abs(fe.rect["x"] - info["x"]) < 2:
                                    matched = fe
                                    break
                            except Exception:
                                pass
                        if matched:
                            click_result = _try_click(driver, matched)
                            if click_result["clicked"] and not click_result["error"]:
                                ok_count += 1
                            elif click_result["error"]:
                                err_count += 1
                    except Exception as ex:
                        click_result = {"clicked": False, "error": str(ex)[:60], "note": "", "navigated": False}
                        err_count += 1

                el_results.append({**info, "click_result": click_result, "tap_ok": tap_ok})

            vp_result["elements"] = el_results
            vp_result["summary"] = {
                "total":      len(elements),
                "tap_issues": warn_count,
                "click_ok":   ok_count,
                "click_err":  err_count,
            }

            log_fn(f"  Tap issues: {warn_count} | Click OK: {ok_count} | Lỗi: {err_count}")

        except Exception as e:
            log_fn(f"  Lỗi: {e}")
            vp_result["error"] = str(e)
        finally:
            driver.quit()

        all_results.append(vp_result)

    return all_results


# ─────────────────────────────────────────────────────────────
# 3. TẠO BÁO CÁO HTML
# ─────────────────────────────────────────────────────────────

def generate_report(url: str, screenshots: list, interactions: list, output_dir: str) -> str:
    """Gộp kết quả chụp màn hình + tương tác thành 1 báo cáo HTML."""

    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def esc(value) -> str:
        return html_lib.escape(str(value or ""), quote=True)

    def slugify(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower())
        return slug.strip("-") or "unknown"

    def group_badge(group: str) -> tuple:
        mapping = {
            "mobile": ("Mobile", "group-mobile"),
            "tablet": ("Tablet", "group-tablet"),
            "desktop": ("Desktop", "group-desktop"),
        }
        return mapping.get(group or "", ("Khac", "group-other"))

    def build_image_panel(src_b64: str, title: str, kind: str, group: str, device_key: str, width: int, height: int):
        if not src_b64:
            return ""

        badge_label, badge_class = group_badge(group)
        src = f"data:image/png;base64,{src_b64}"
        safe_title = esc(title)
        return f"""
          <div class="image-card" data-title="{safe_title}" data-src="{src}" data-kind="{esc(kind)}"
               data-group="{esc(group)}" data-device="{esc(device_key)}" data-width="{width}" data-height="{height}">
            <div class="image-frame">
              <img class="preview-image js-open-image" src="{src}" alt="{safe_title}" loading="lazy">
            </div>
            <div class="image-toolbar">
              <span class="group-pill {badge_class}">{badge_label}</span>
              <div class="image-actions">
                <button class="mini-btn js-open-image" type="button">Mở lớn</button>
                <button class="mini-btn js-compare-a" type="button">So sánh A</button>
                <button class="mini-btn js-compare-b" type="button">So sánh B</button>
              </div>
            </div>
          </div>"""

    total_cards = len(screenshots) + len(interactions)
    screen_cards = ""
    interaction_cards = ""
    device_keys = {}
    screen_count = 0
    interaction_count = 0

    for s in screenshots:
        device_key = s.get("id") or slugify(s.get("name"))
        device_keys[device_key] = s.get("name", "Viewport")
        group = s.get("group", "")
        screen_count += 1
        group_label, group_class = group_badge(group)
        title = f"{s['name']} - Screenshot"
        screen_cards += f"""
        <article class="report-card report-screen" data-kind="screen" data-group="{esc(group)}"
                 data-device="{esc(device_key)}" data-search="{esc((s['name'] + ' ' + group_label + ' ' + str(s['width']))).lower()}">
          <div class="card-topline">
            <span class="group-pill {group_class}">{group_label}</span>
            <span class="meta-pill">Screenshot</span>
          </div>
          <div class="vp-header">{esc(s['name'])} <small>{s['width']}×{s['height']}px</small></div>
          <div class="card-copy">Ảnh chụp full-page để so sánh bố cục và mật độ nội dung theo từng viewport.</div>
          {build_image_panel(s.get('b64', ''), title, 'screen', group, device_key, s['width'], s['height'])}
        </article>"""

    for vp in interactions:
        device_key = vp.get("id") or slugify(vp.get("name"))
        device_keys[device_key] = vp.get("name", "Viewport")
        group = vp.get("group", "")
        group_label, group_class = group_badge(group)
        interaction_count += 1

        if vp.get("error"):
            interaction_cards += f"""
        <article class="report-card report-interaction" data-kind="interaction" data-group="{esc(group)}"
                 data-device="{esc(device_key)}" data-search="{esc((vp['name'] + ' ' + group_label)).lower()}">
          <div class="card-topline">
            <span class="group-pill {group_class}">{group_label}</span>
            <span class="meta-pill">Interaction</span>
          </div>
          <div class="vp-header">{esc(vp['name'])} <small>{vp['width']}×{vp['height']}px</small></div>
          <p class="err">Lỗi: {esc(vp['error'])}</p>
        </article>"""
            continue

        sm = vp.get("summary", {})
        tap_issues = sm.get("tap_issues", 0)
        click_ok = sm.get("click_ok", 0)
        click_err = sm.get("click_err", 0)
        total = sm.get("total", 0)

        rows = ""
        for el in vp.get("elements", []):
            tap_badge = (
                '<span class="badge ok">OK</span>'
                if el["tap_ok"]
                else f'<span class="badge warn">{esc(el["w"])}×{esc(el["h"])}px</span>'
            )
            click_res = el.get("click_result")
            if click_res is None:
                click_badge = '<span class="badge muted">-</span>'
            elif click_res.get("error"):
                click_badge = f'<span class="badge err" title="{esc(click_res["error"])}">Lỗi</span>'
            elif click_res.get("clicked"):
                note = esc(click_res.get("note", ""))
                click_badge = f'<span class="badge ok">OK</span> <small>{note}</small>' if note else '<span class="badge ok">OK</span>'
            else:
                click_badge = '<span class="badge muted">Chưa test</span>'

            rows += f"""
            <tr>
              <td><span class="kind-badge {esc(el['kind'])}">{esc(el['kind'])}</span></td>
              <td class="label-cell">{esc(el['label'])}</td>
              <td>{esc(el['w'])}×{esc(el['h'])}px</td>
              <td>{tap_badge}</td>
              <td>{click_badge}</td>
            </tr>"""

        title = f"{vp['name']} - Interaction"
        interaction_cards += f"""
        <article class="report-card report-interaction" data-kind="interaction" data-group="{esc(group)}"
                 data-device="{esc(device_key)}"
                 data-search="{esc((vp['name'] + ' ' + group_label + ' ' + str(vp['width']))).lower()}">
          <div class="card-topline">
            <span class="group-pill {group_class}">{group_label}</span>
            <span class="meta-pill">Interaction</span>
          </div>
          <div class="section-header">
            <span class="vp-title">{esc(vp['name'])} <small>{vp['width']}×{vp['height']}px</small></span>
            <div class="badges-row">
              <span class="stat">{total} phan tu</span>
              <span class="stat {'stat-warn' if tap_issues else ''}">Tap issues: {tap_issues}</span>
              <span class="stat {'stat-ok' if click_ok else ''}">Click OK: {click_ok}</span>
              <span class="stat {'stat-err' if click_err else ''}">Lỗi: {click_err}</span>
            </div>
          </div>
          <div class="card-copy">Ảnh chụp ban đầu và bảng kết quả click/tap để người dùng lọc theo từng nhóm thiết bị.</div>
          {build_image_panel(vp.get('screenshot_b64', ''), title, 'interaction', group, device_key, vp['width'], vp['height'])}
          <table>
            <tr><th>Loai</th><th>Ten/Label</th><th>Kich thuoc</th><th>Tap >=44px</th><th>Click</th></tr>
            {rows}
          </table>
        </article>"""

    device_options = ['<option value="">Tat ca thiet bi</option>']
    for device_key, label in sorted(device_keys.items(), key=lambda item: item[1].lower()):
        device_options.append(f'<option value="{esc(device_key)}">{esc(label)}</option>')

    report_html = f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Viewport Test Report – {url}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
    :root{{--bg:#eef2ff;--panel:#ffffff;--ink:#132238;--muted:#64748b;--line:#d9e1f2;--blue:#1d4ed8;--cyan:#0f766e;--orange:#c2410c;--green:#15803d;--rose:#be123c;--shadow:0 18px 45px rgba(15,23,42,.08)}}
    body{{font-family:'Segoe UI',system-ui,sans-serif;background:radial-gradient(circle at top left,#e0f2fe,transparent 28%),radial-gradient(circle at top right,#fee2e2,transparent 22%),linear-gradient(180deg,#f8fbff 0%,#edf4ff 100%);color:var(--ink);line-height:1.5}}
    header{{background:linear-gradient(135deg,#0f172a,#1d4ed8 55%,#0f766e);color:#fff;padding:34px 24px 30px;text-align:center;box-shadow:var(--shadow)}}
  header h1{{font-size:1.7rem;font-weight:800}}
    header .meta{{margin-top:8px;opacity:.86;font-size:.92rem}}
    .container{{max-width:1480px;margin:0 auto;padding:24px 18px 48px}}
    .hero-grid{{display:grid;grid-template-columns:1.15fr .85fr;gap:18px;margin-bottom:18px}}
    .hero-card,.toolbar,.section-shell,.compare-panel,.modal-card{{background:rgba(255,255,255,.88);backdrop-filter:blur(10px);border:1px solid rgba(217,225,242,.9);border-radius:18px;box-shadow:var(--shadow)}}
    .hero-card{{padding:20px 22px}}
    .hero-card h2{{font-size:1.15rem;margin-bottom:8px}}
    .hero-copy{{color:var(--muted);font-size:.95rem;max-width:60ch}}
    .stats-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}
    .stat-card{{padding:16px;border-radius:14px;background:linear-gradient(180deg,#fff,#f8fbff);border:1px solid var(--line)}}
    .stat-card strong{{display:block;font-size:1.6rem;line-height:1.1}}
    .stat-card span{{display:block;color:var(--muted);font-size:.84rem;margin-top:4px}}
    .toolbar{{padding:16px 18px;margin-bottom:18px;position:sticky;top:16px;z-index:20}}
    .toolbar-top{{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap;margin-bottom:14px}}
    .toolbar h2{{font-size:1rem}}
    .toolbar p{{color:var(--muted);font-size:.9rem}}
    .filters-grid{{display:grid;grid-template-columns:1.1fr .9fr .9fr;gap:12px}}
    .filter-box label{{display:block;font-size:.8rem;font-weight:700;color:#334155;margin-bottom:6px}}
    .filter-box input,.filter-box select{{width:100%;padding:11px 12px;border:1px solid var(--line);border-radius:12px;background:#fff;font:inherit;color:var(--ink)}}
    .chip-row{{display:flex;gap:8px;flex-wrap:wrap}}
    .chip{{border:none;border-radius:999px;padding:8px 12px;background:#e7eefc;color:#36517a;font-weight:700;cursor:pointer;transition:.15s}}
    .chip.active{{background:var(--ink);color:#fff}}
    .toolbar-foot{{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-top:14px}}
    .toolbar-note{{color:var(--muted);font-size:.86rem}}
    .toolbar-actions{{display:flex;gap:8px;flex-wrap:wrap}}
    .ghost-btn{{border:1px solid var(--line);background:#fff;border-radius:999px;padding:9px 12px;font:inherit;font-weight:700;cursor:pointer}}
    .compare-panel{{padding:16px 18px;margin-bottom:18px}}
    .compare-head{{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:14px}}
    .compare-head p{{color:var(--muted);font-size:.9rem}}
    .compare-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}}
    .compare-slot{{border:1px dashed #9db1d7;border-radius:16px;padding:14px;min-height:260px;background:linear-gradient(180deg,#fbfdff,#f2f7ff)}}
    .compare-slot.ready{{border-style:solid;background:#fff}}
    .compare-slot h3{{font-size:.95rem;margin-bottom:8px}}
    .compare-empty{{color:var(--muted);font-size:.9rem}}
    .compare-preview{{width:100%;max-height:420px;object-fit:contain;border-radius:12px;background:#f8fafc;border:1px solid var(--line)}}
    .compare-meta{{font-size:.84rem;color:var(--muted);margin-top:8px}}
    .section-shell{{padding:18px}}
    .section-title{{font-size:1.1rem;font-weight:800;color:var(--ink);margin-bottom:14px}}
    .report-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:16px}}
    .report-card{{background:#fff;border:1px solid rgba(217,225,242,.9);border-radius:18px;overflow:hidden;padding:14px;display:flex;flex-direction:column;gap:12px;box-shadow:0 10px 25px rgba(15,23,42,.05)}}
    .report-card.hidden{{display:none}}
    .card-topline{{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;align-items:center}}
    .group-pill,.meta-pill{{display:inline-flex;align-items:center;padding:4px 10px;border-radius:999px;font-size:.74rem;font-weight:800;letter-spacing:.03em;text-transform:uppercase}}
    .group-mobile{{background:#dbeafe;color:#1d4ed8}}
    .group-tablet{{background:#ede9fe;color:#6d28d9}}
    .group-desktop{{background:#dcfce7;color:#166534}}
    .group-other{{background:#f1f5f9;color:#475569}}
    .meta-pill{{background:#fff7ed;color:#c2410c}}
    .vp-header{{font-weight:800;font-size:1rem;color:#1e293b}}
    .vp-header small{{display:block;font-weight:500;color:#8aa0bf;margin-top:2px}}
    .card-copy{{color:var(--muted);font-size:.9rem}}
    .image-card{{display:flex;flex-direction:column;gap:10px}}
    .image-frame{{border-radius:14px;overflow:hidden;border:1px solid var(--line);background:#eef5ff;min-height:180px}}
    .preview-image{{width:100%;display:block;cursor:zoom-in}}
    .image-toolbar{{display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap}}
    .image-actions{{display:flex;gap:8px;flex-wrap:wrap}}
    .mini-btn{{border:none;border-radius:10px;padding:8px 10px;background:#eff6ff;color:#1d4ed8;font:inherit;font-weight:700;cursor:pointer}}
    .mini-btn:hover{{background:#dbeafe}}
    .section-header{{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}}
  .vp-title{{font-weight:700;font-size:14px;color:#1e293b}}
  .vp-title small{{font-weight:400;color:#94a3b8}}
  .badges-row{{display:flex;gap:10px;flex-wrap:wrap}}
  .stat{{font-size:12px;color:#64748b;font-weight:600}}
  .stat-ok{{color:#16a34a}}
  .stat-warn{{color:#d97706}}
  .stat-err{{color:#dc2626}}
  table{{width:100%;border-collapse:collapse;font-size:13px}}
  th{{background:#f8fafc;padding:9px 14px;text-align:left;font-weight:700;
      font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.03em;
      border-bottom:2px solid #e2e8f0}}
  td{{padding:8px 14px;border-bottom:1px solid #f1f5f9;vertical-align:middle}}
  .label-cell{{max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#334155}}
  .kind-badge{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700}}
  .kind-badge.button{{background:#dbeafe;color:#1d4ed8}}
  .kind-badge.link{{background:#ede9fe;color:#6d28d9}}
  .kind-badge.input{{background:#fef9c3;color:#854d0e}}
  .kind-badge.select{{background:#dcfce7;color:#166534}}
  .kind-badge.textarea{{background:#ffe4e6;color:#be123c}}
  .badge{{display:inline-block;padding:2px 9px;border-radius:99px;font-size:11px;font-weight:700}}
  .badge.ok{{background:#dcfce7;color:#166534}}
  .badge.warn{{background:#fef9c3;color:#854d0e}}
  .badge.err{{background:#ffe4e6;color:#be123c;cursor:help}}
  .badge.muted{{background:#f1f5f9;color:#94a3b8}}
    .err{{color:#dc2626;padding:2px 0 0}}
    .empty-state{{display:none;padding:24px;border:1px dashed #b6c5df;border-radius:16px;text-align:center;color:var(--muted);background:#f8fbff;margin-top:14px}}
    .empty-state.show{{display:block}}
    .image-modal{{position:fixed;inset:0;background:rgba(15,23,42,.74);display:none;align-items:center;justify-content:center;padding:20px;z-index:100}}
    .image-modal.open{{display:flex}}
    .modal-card{{max-width:min(1200px,96vw);max-height:92vh;padding:14px;display:flex;flex-direction:column;gap:12px;background:#0f172a;color:#fff}}
    .modal-top{{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}}
    .modal-top h3{{font-size:1rem}}
    .modal-top p{{color:#cbd5e1;font-size:.9rem;margin-top:4px}}
    .modal-close{{border:none;border-radius:999px;background:#1e293b;color:#fff;padding:10px 12px;font:inherit;font-weight:700;cursor:pointer}}
    .modal-image{{max-width:100%;max-height:78vh;object-fit:contain;border-radius:12px;background:#020617}}
    footer{{text-align:center;padding:20px;color:#64748b;font-size:12px}}
    @media(max-width:980px){{
        .hero-grid,.filters-grid,.compare-grid{{grid-template-columns:1fr}}
        .toolbar{{position:static}}
    }}
</style>
</head>
<body>
<header>
    <h1>Báo cáo kiểm thử viewport</h1>
    <div class="meta">URL: <strong>{esc(url)}</strong> · {ts}</div>
</header>
<div class="container">

    <section class="hero-grid">
        <div class="hero-card">
            <h2>Bộ lọc và so sánh ngay trong báo cáo</h2>
            <p class="hero-copy">Người dùng có thể lọc theo nhóm thiết bị, tìm theo tên viewport, mở ảnh lớn và đưa 2 ảnh vào khung so sánh để đối chiếu bố cục.</p>
        </div>
        <div class="stats-grid">
            <div class="stat-card"><strong>{total_cards}</strong><span>Tổng số mục trong báo cáo</span></div>
            <div class="stat-card"><strong>{screen_count}</strong><span>Ảnh chụp để so sánh giao diện</span></div>
            <div class="stat-card"><strong>{interaction_count}</strong><span>Mục kiểm thử tương tác</span></div>
        </div>
    </section>

    <section class="toolbar">
        <div class="toolbar-top">
            <div>
                <h2>Lọc báo cáo</h2>
                <p>Chọn nhóm, thiết bị cụ thể hoặc tìm nhanh theo tên viewport / kích thước.</p>
            </div>
            <div class="chip-row" id="groupChips">
                <button class="chip active" type="button" data-group="all">Tất cả</button>
                <button class="chip" type="button" data-group="mobile">Mobile</button>
                <button class="chip" type="button" data-group="tablet">Tablet</button>
                <button class="chip" type="button" data-group="desktop">Desktop</button>
            </div>
        </div>
        <div class="filters-grid">
            <div class="filter-box">
                <label for="searchFilter">Tìm kiếm</label>
                <input id="searchFilter" type="text" placeholder="Ví dụ: iPhone, 768, desktop...">
            </div>
            <div class="filter-box">
                <label for="deviceFilter">Thiết bị</label>
                <select id="deviceFilter">{''.join(device_options)}</select>
            </div>
            <div class="filter-box">
                <label for="kindFilter">Mục báo cáo</label>
                <select id="kindFilter">
                    <option value="all">Tất cả</option>
                    <option value="screen">Ảnh chụp</option>
                    <option value="interaction">Tương tác</option>
                </select>
            </div>
        </div>
        <div class="toolbar-foot">
            <div class="toolbar-note" id="resultCount">Đang hiển thị {total_cards}/{total_cards} mục</div>
            <div class="toolbar-actions">
                <button class="ghost-btn" type="button" id="resetFilters">Đặt lại bộ lọc</button>
            </div>
        </div>
    </section>

    <section class="compare-panel">
        <div class="compare-head">
            <div>
                <h2>So sánh 2 hình ảnh</h2>
                <p>Bấm So sánh A/B trên bất kỳ ảnh nào trong báo cáo, sau đó đối chiếu 2 viewport cạnh nhau.</p>
            </div>
            <div class="toolbar-actions">
                <button class="ghost-btn" type="button" id="swapCompare">Đảo A/B</button>
                <button class="ghost-btn" type="button" id="clearCompare">Xóa so sánh</button>
            </div>
        </div>
        <div class="compare-grid">
            <div class="compare-slot" id="compareA">
                <h3>Khung A</h3>
                <div class="compare-empty">Chưa có ảnh. Chọn "So sánh A" trên một ảnh chụp hoặc ảnh tương tác.</div>
            </div>
            <div class="compare-slot" id="compareB">
                <h3>Khung B</h3>
                <div class="compare-empty">Chưa có ảnh. Chọn "So sánh B" trên một ảnh chụp hoặc ảnh tương tác.</div>
            </div>
        </div>
    </section>

    <section class="section-shell">
        <div class="section-title">Danh sách viewport</div>
        <div class="report-grid" id="reportGrid">
            {screen_cards}
            {interaction_cards}
        </div>
        <div class="empty-state" id="emptyState">Không có mục nào phù hợp với bộ lọc hiện tại.</div>
    </section>

</div>
<div class="image-modal" id="imageModal">
    <div class="modal-card">
        <div class="modal-top">
            <div>
                <h3 id="modalTitle">Xem hình ảnh</h3>
                <p id="modalMeta"></p>
            </div>
            <button class="modal-close" id="closeModal" type="button">Đóng</button>
        </div>
        <img class="modal-image" id="modalImage" src="" alt="Preview">
    </div>
</div>
<footer>Tạo bởi Viewport Tester &nbsp;·&nbsp; {ts}</footer>
<script>
    const reportCards = Array.from(document.querySelectorAll('.report-card'));
    const reportGrid = document.getElementById('reportGrid');
    const resultCount = document.getElementById('resultCount');
    const emptyState = document.getElementById('emptyState');
    const searchFilter = document.getElementById('searchFilter');
    const deviceFilter = document.getElementById('deviceFilter');
    const kindFilter = document.getElementById('kindFilter');
    const groupChips = Array.from(document.querySelectorAll('#groupChips .chip'));
    const imageModal = document.getElementById('imageModal');
    const modalImage = document.getElementById('modalImage');
    const modalTitle = document.getElementById('modalTitle');
    const modalMeta = document.getElementById('modalMeta');
    const compareSlots = {{ a: null, b: null }};

    function getActiveGroup() {{
        const active = groupChips.find((chip) => chip.classList.contains('active'));
        return active ? active.dataset.group : 'all';
    }}

    function applyFilters() {{
        const search = (searchFilter.value || '').trim().toLowerCase();
        const group = getActiveGroup();
        const device = deviceFilter.value || '';
        const kind = kindFilter.value || 'all';
        let visible = 0;

        reportCards.forEach((card) => {{
            const matchesGroup = group === 'all' || card.dataset.group === group;
            const matchesDevice = !device || card.dataset.device === device;
            const matchesKind = kind === 'all' || card.dataset.kind === kind;
            const haystack = card.dataset.search || '';
            const matchesSearch = !search || haystack.includes(search);
            const show = matchesGroup && matchesDevice && matchesKind && matchesSearch;
            card.classList.toggle('hidden', !show);
            if (show) visible += 1;
        }});

        resultCount.textContent = `Đang hiển thị ${{visible}}/${{reportCards.length}} mục`;
        emptyState.classList.toggle('show', visible === 0);
    }}

    function getImageMeta(source) {{
        const imageCard = source.closest('.image-card');
        if (!imageCard) return null;
        return {{
            src: imageCard.dataset.src,
            title: imageCard.dataset.title,
            kind: imageCard.dataset.kind,
            group: imageCard.dataset.group,
            device: imageCard.dataset.device,
            width: imageCard.dataset.width,
            height: imageCard.dataset.height,
        }};
    }}

    function openModal(meta) {{
        if (!meta) return;
        modalImage.src = meta.src;
        modalTitle.textContent = meta.title;
        modalMeta.textContent = `${{meta.kind}} · ${{meta.group || 'khác'}} · ${{meta.width}}x${{meta.height}}px`;
        imageModal.classList.add('open');
    }}

    function closeModal() {{
        imageModal.classList.remove('open');
        modalImage.src = '';
    }}

    function renderCompare(slotName) {{
        const slotEl = document.getElementById(slotName === 'a' ? 'compareA' : 'compareB');
        const meta = compareSlots[slotName];
        if (!meta) {{
            slotEl.classList.remove('ready');
            slotEl.innerHTML = `<h3>Khung ${{slotName.toUpperCase()}}</h3><div class="compare-empty">Chưa có ảnh. Chọn \"So sánh ${{slotName.toUpperCase()}}\" trên một ảnh chụp hoặc ảnh tương tác.</div>`;
            return;
        }}
        slotEl.classList.add('ready');
        slotEl.innerHTML = `
            <h3>${{meta.title}}</h3>
            <img class="compare-preview" src="${{meta.src}}" alt="${{meta.title}}">
            <div class="compare-meta">${{meta.kind}} · ${{meta.group || 'khác'}} · ${{meta.width}}x${{meta.height}}px</div>
        `;
    }}

    function setCompare(slotName, meta) {{
        if (!meta) return;
        compareSlots[slotName] = meta;
        renderCompare(slotName);
    }}

    groupChips.forEach((chip) => {{
        chip.addEventListener('click', () => {{
            groupChips.forEach((entry) => entry.classList.remove('active'));
            chip.classList.add('active');
            applyFilters();
        }});
    }});

    searchFilter.addEventListener('input', applyFilters);
    deviceFilter.addEventListener('change', applyFilters);
    kindFilter.addEventListener('change', applyFilters);
    document.getElementById('resetFilters').addEventListener('click', () => {{
        searchFilter.value = '';
        deviceFilter.value = '';
        kindFilter.value = 'all';
        groupChips.forEach((entry) => entry.classList.toggle('active', entry.dataset.group === 'all'));
        applyFilters();
    }});

    reportGrid.addEventListener('click', (event) => {{
        const openTrigger = event.target.closest('.js-open-image');
        const compareA = event.target.closest('.js-compare-a');
        const compareB = event.target.closest('.js-compare-b');
        if (!openTrigger && !compareA && !compareB) return;

        const meta = getImageMeta(event.target);
        if (openTrigger) openModal(meta);
        if (compareA) setCompare('a', meta);
        if (compareB) setCompare('b', meta);
    }});

    document.getElementById('closeModal').addEventListener('click', closeModal);
    imageModal.addEventListener('click', (event) => {{
        if (event.target === imageModal) closeModal();
    }});
    document.addEventListener('keydown', (event) => {{
        if (event.key === 'Escape') closeModal();
    }});
    document.getElementById('swapCompare').addEventListener('click', () => {{
        const temp = compareSlots.a;
        compareSlots.a = compareSlots.b;
        compareSlots.b = temp;
        renderCompare('a');
        renderCompare('b');
    }});
    document.getElementById('clearCompare').addEventListener('click', () => {{
        compareSlots.a = null;
        compareSlots.b = null;
        renderCompare('a');
        renderCompare('b');
    }});

    renderCompare('a');
    renderCompare('b');
    applyFilters();
</script>
</body>
</html>"""

    out_path = os.path.join(output_dir, "report.html")
    os.makedirs(output_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report_html)
    return out_path
