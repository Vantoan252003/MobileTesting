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
        return mapping.get(group or "", ("Khác", "group-other"))

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
                                <button class="mini-btn js-open-image" type="button">Xem lớn</button>
                                <button class="mini-btn mini-btn-strong js-open-compare" type="button">So sánh</button>
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
            <span class="meta-pill">Ảnh chụp</span>
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
            <span class="meta-pill">Tương tác</span>
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
            <span class="meta-pill">Tương tác</span>
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
                    <details class="detail-block">
                        <summary>Xem bảng chi tiết tương tác</summary>
                        <table>
                            <tr><th>Loại</th><th>Tên/Label</th><th>Kích thước</th><th>Tap >=44px</th><th>Click</th></tr>
                            {rows}
                        </table>
                    </details>
        </article>"""

    device_options = ['<option value="">Tất cả thiết bị</option>']
    for device_key, label in sorted(device_keys.items(), key=lambda item: item[1].lower()):
        device_options.append(f'<option value="{esc(device_key)}">{esc(label)}</option>')

        report_html = f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Báo cáo kiểm thử viewport – {url}</title>
<style>
    *{{box-sizing:border-box;margin:0;padding:0}}
        :root{{--page:#f4f7fb;--panel:#ffffff;--panel-soft:rgba(255,255,255,.82);--ink:#142033;--muted:#66758c;--line:#dbe4f0;--line-strong:#bfd0e4;--blue:#2157d5;--teal:#0f766e;--cyan:#0ea5e9;--orange:#d97706;--green:#15803d;--rose:#be123c;--shadow:0 18px 50px rgba(15,23,42,.08);--shadow-soft:0 10px 30px rgba(20,32,51,.06)}}
        body{{font-family:'Segoe UI',system-ui,sans-serif;background:
            radial-gradient(circle at 0% 0%, rgba(14,165,233,.12), transparent 28%),
            radial-gradient(circle at 100% 0%, rgba(34,197,94,.11), transparent 24%),
            linear-gradient(180deg, #f8fbff 0%, #eef4fb 100%);color:var(--ink);line-height:1.5}}
        header{{background:linear-gradient(135deg,#0f172a 0%,#183b8c 52%,#0f766e 100%);color:#fff;padding:38px 24px 34px;text-align:center;box-shadow:var(--shadow)}}
        header h1{{font-size:1.9rem;font-weight:800;letter-spacing:-.02em}}
        header .meta{{margin-top:8px;opacity:.86;font-size:.95rem}}
        .container{{max-width:1500px;margin:0 auto;padding:26px 18px 52px}}
        .hero-grid{{display:grid;grid-template-columns:1.2fr .8fr;gap:18px;margin-bottom:18px}}
        .hero-card,.toolbar,.section-shell,.modal-card,.compare-card{{background:var(--panel-soft);backdrop-filter:blur(14px);border:1px solid rgba(219,228,240,.94);border-radius:22px;box-shadow:var(--shadow)}}
        .hero-card{{padding:24px 24px 22px;position:relative;overflow:hidden}}
        .hero-card::after{{content:'';position:absolute;inset:auto -40px -40px auto;width:180px;height:180px;background:radial-gradient(circle, rgba(14,165,233,.18), transparent 66%);pointer-events:none}}
        .hero-card h2{{font-size:1.22rem;margin-bottom:8px}}
        .hero-copy{{color:var(--muted);font-size:.96rem;max-width:64ch}}
        .hero-actions{{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px}}
        .hero-btn{{border:none;border-radius:999px;padding:10px 14px;background:#0f172a;color:#fff;font:inherit;font-weight:700;cursor:pointer}}
        .hero-btn.secondary{{background:#fff;color:#183b8c;border:1px solid var(--line)}}
        .stats-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}
        .stat-card{{padding:18px;border-radius:18px;background:linear-gradient(180deg,#fff,#f7fbff);border:1px solid var(--line);box-shadow:var(--shadow-soft)}}
        .stat-card strong{{display:block;font-size:1.7rem;line-height:1.05}}
        .stat-card span{{display:block;color:var(--muted);font-size:.86rem;margin-top:6px}}
        .toolbar{{padding:16px 16px 14px;margin-bottom:18px;position:sticky;top:14px;z-index:20}}
        .toolbar-top{{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap;margin-bottom:12px}}
        .toolbar h2{{font-size:1rem}}
        .toolbar p{{color:var(--muted);font-size:.9rem}}
        .filters-grid{{display:grid;grid-template-columns:1.2fr .9fr .9fr;gap:12px}}
        .filter-box{{padding:12px;border:1px solid var(--line);border-radius:18px;background:linear-gradient(180deg,#fcfeff,#f4f8fc)}}
        .filter-box label{{display:block;font-size:.78rem;font-weight:800;color:#42536d;margin-bottom:7px;letter-spacing:.02em;text-transform:uppercase}}
        .filter-box input,.filter-box select{{width:100%;padding:13px 14px;border:1px solid var(--line-strong);border-radius:14px;background:#fff;font:inherit;color:var(--ink);outline:none;transition:border-color .18s ease, box-shadow .18s ease;appearance:none}}
        .filter-box input:focus,.filter-box select:focus{{border-color:#7aa8f8;box-shadow:0 0 0 4px rgba(33,87,213,.12)}}
        .select-wrap{{position:relative}}
        .select-wrap::after{{content:'▾';position:absolute;right:14px;top:50%;transform:translateY(-50%);color:#59708f;font-size:.9rem;pointer-events:none}}
        .chip-row{{display:flex;gap:8px;flex-wrap:wrap}}
        .chip{{border:none;border-radius:999px;padding:9px 13px;background:#e9f0fb;color:#355170;font-weight:700;cursor:pointer;transition:.16s ease;box-shadow:inset 0 0 0 1px rgba(53,81,112,.07)}}
        .chip:hover{{transform:translateY(-1px)}}
        .chip.active{{background:#10203a;color:#fff;box-shadow:none}}
        .toolbar-foot{{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-top:12px}}
        .toolbar-note{{color:var(--muted);font-size:.88rem}}
        .toolbar-actions{{display:flex;gap:8px;flex-wrap:wrap}}
        .ghost-btn{{border:1px solid var(--line);background:#fff;border-radius:999px;padding:9px 13px;font:inherit;font-weight:700;cursor:pointer}}
        .ghost-btn:hover{{background:#f4f8ff}}
        .section-shell{{padding:18px}}
        .section-head{{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;flex-wrap:wrap;margin-bottom:14px}}
        .section-title{{font-size:1.1rem;font-weight:800;color:var(--ink)}}
        .section-subtitle{{font-size:.9rem;color:var(--muted)}}
        .report-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}}
        .report-card{{background:#fff;border:1px solid rgba(219,228,240,.96);border-radius:22px;overflow:hidden;padding:14px;display:flex;flex-direction:column;gap:12px;box-shadow:var(--shadow-soft)}}
        .report-card.hidden{{display:none}}
        .card-topline{{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;align-items:center}}
        .group-pill,.meta-pill{{display:inline-flex;align-items:center;padding:5px 10px;border-radius:999px;font-size:.72rem;font-weight:800;letter-spacing:.03em;text-transform:uppercase}}
        .group-mobile{{background:#dbeafe;color:#1d4ed8}}
        .group-tablet{{background:#ede9fe;color:#6d28d9}}
        .group-desktop{{background:#dcfce7;color:#166534}}
        .group-other{{background:#f1f5f9;color:#475569}}
        .meta-pill{{background:#fff2db;color:#b45309}}
        .vp-header{{font-weight:800;font-size:1rem;color:#1e293b}}
        .vp-header small{{display:block;font-weight:500;color:#8aa0bf;margin-top:2px}}
        .card-copy{{color:var(--muted);font-size:.9rem}}
        .image-card{{display:flex;flex-direction:column;gap:10px}}
        .image-frame{{aspect-ratio:4/3;border-radius:18px;overflow:hidden;border:1px solid var(--line);background:linear-gradient(180deg,#edf5ff,#f7fbff)}}
        .preview-image{{width:100%;height:100%;display:block;object-fit:cover;object-position:top;cursor:zoom-in;transition:transform .22s ease}}
        .image-frame:hover .preview-image{{transform:scale(1.02)}}
        .image-toolbar{{display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap}}
        .image-actions{{display:flex;gap:8px;flex-wrap:wrap}}
        .mini-btn{{border:none;border-radius:12px;padding:8px 11px;background:#edf4ff;color:#1d4ed8;font:inherit;font-weight:700;cursor:pointer;transition:.16s ease}}
        .mini-btn:hover{{background:#dbeafe}}
        .mini-btn-strong{{background:#10203a;color:#fff}}
        .mini-btn-strong:hover{{background:#183157}}
        .section-header{{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}}
        .vp-title{{font-weight:700;font-size:14px;color:#1e293b}}
        .vp-title small{{font-weight:400;color:#94a3b8}}
        .badges-row{{display:flex;gap:8px;flex-wrap:wrap}}
        .stat{{font-size:12px;color:#64748b;font-weight:700;padding:5px 9px;background:#f8fafc;border-radius:999px;border:1px solid #ebf0f6}}
        .stat-ok{{color:#15803d;background:#ecfdf3;border-color:#ccefd8}}
        .stat-warn{{color:#b45309;background:#fff7ed;border-color:#ffe1bf}}
        .stat-err{{color:#be123c;background:#fff1f2;border-color:#ffd6dc}}
        .detail-block{{border:1px solid var(--line);border-radius:16px;background:#fbfdff;overflow:hidden}}
        .detail-block summary{{list-style:none;cursor:pointer;padding:11px 13px;font-weight:700;color:#27446d;background:#f4f8fd}}
        .detail-block summary::-webkit-details-marker{{display:none}}
        .detail-block[open] summary{{border-bottom:1px solid var(--line)}}
        table{{width:100%;border-collapse:collapse;font-size:13px}}
        th{{background:#f8fafc;padding:9px 12px;text-align:left;font-weight:700;font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.03em;border-bottom:2px solid #e2e8f0}}
        td{{padding:8px 12px;border-bottom:1px solid #f1f5f9;vertical-align:middle}}
        .label-cell{{max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#334155}}
        .kind-badge{{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700}}
        .kind-badge.button{{background:#dbeafe;color:#1d4ed8}}
        .kind-badge.link{{background:#ede9fe;color:#6d28d9}}
        .kind-badge.input{{background:#fef9c3;color:#854d0e}}
        .kind-badge.select{{background:#dcfce7;color:#166534}}
        .kind-badge.textarea{{background:#ffe4e6;color:#be123c}}
        .badge{{display:inline-block;padding:3px 9px;border-radius:99px;font-size:11px;font-weight:700}}
        .badge.ok{{background:#dcfce7;color:#166534}}
        .badge.warn{{background:#fef9c3;color:#854d0e}}
        .badge.err{{background:#ffe4e6;color:#be123c;cursor:help}}
        .badge.muted{{background:#f1f5f9;color:#94a3b8}}
        .err{{color:#dc2626;padding:2px 0 0}}
        .empty-state{{display:none;padding:28px;border:1px dashed #c2d1e4;border-radius:20px;text-align:center;color:var(--muted);background:#f8fbff;margin-top:14px}}
        .empty-state.show{{display:block}}
        .image-modal,.compare-modal{{position:fixed;inset:0;background:rgba(9,18,33,.78);display:none;align-items:center;justify-content:center;padding:18px;z-index:110}}
        .image-modal.open,.compare-modal.open{{display:flex}}
        .modal-card{{width:min(1240px,96vw);max-height:92vh;padding:16px;display:flex;flex-direction:column;gap:12px;background:#081120;color:#fff}}
        .modal-top{{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}}
        .modal-top h3{{font-size:1rem}}
        .modal-top p{{color:#cbd5e1;font-size:.9rem;margin-top:4px}}
        .modal-close{{border:none;border-radius:999px;background:#16233b;color:#fff;padding:10px 13px;font:inherit;font-weight:700;cursor:pointer}}
        .modal-image{{max-width:100%;max-height:78vh;object-fit:contain;border-radius:14px;background:#020617}}
        .compare-card{{width:min(1380px,98vw);max-height:94vh;padding:18px;background:#07101d;color:#fff;border-color:rgba(191,208,228,.18)}}
        .compare-top{{display:flex;justify-content:space-between;gap:14px;align-items:flex-start;flex-wrap:wrap;margin-bottom:14px}}
        .compare-top p{{color:#b3c2d8;font-size:.92rem;margin-top:6px}}
        .compare-actions{{display:flex;gap:8px;flex-wrap:wrap}}
        .compare-chip{{border:1px solid rgba(191,208,228,.24);background:#0f1d33;color:#d7e2f1;border-radius:999px;padding:9px 13px;font:inherit;font-weight:700;cursor:pointer}}
        .compare-chip.active{{background:#eff6ff;color:#10203a;border-color:#eff6ff}}
        .compare-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;margin-bottom:14px}}
        .compare-slot{{background:#0b182c;border:1px solid rgba(191,208,228,.16);border-radius:20px;padding:14px;min-height:360px;display:flex;flex-direction:column;gap:10px}}
        .compare-slot.is-active{{outline:2px solid rgba(111,179,255,.45)}}
        .compare-slot-head{{display:flex;justify-content:space-between;align-items:center;gap:10px}}
        .compare-slot h3{{font-size:1rem}}
        .compare-slot-tag{{padding:4px 10px;border-radius:999px;background:#132742;color:#cfe0f6;font-size:.74rem;font-weight:800;text-transform:uppercase}}
        .compare-stage{{flex:1;min-height:250px;border-radius:18px;border:1px dashed rgba(191,208,228,.24);background:linear-gradient(180deg,#07101d,#0f1d33);display:flex;align-items:center;justify-content:center;overflow:hidden}}
        .compare-stage.has-image{{border-style:solid;background:#06101f}}
        .compare-placeholder{{color:#93a7c2;font-size:.92rem;text-align:center;max-width:28ch;padding:0 14px}}
        .compare-image{{width:100%;height:100%;max-height:460px;object-fit:contain;background:#030813}}
        .compare-meta{{color:#93a7c2;font-size:.88rem}}
        .compare-strip{{border-top:1px solid rgba(191,208,228,.16);padding-top:14px}}
        .compare-strip-head{{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px}}
        .compare-strip p{{color:#93a7c2;font-size:.88rem}}
        .thumb-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:10px;max-height:28vh;overflow:auto;padding-right:4px}}
        .thumb-btn{{border:1px solid rgba(191,208,228,.14);background:#0b182c;color:#d6e3f5;border-radius:16px;padding:8px;cursor:pointer;text-align:left;transition:.16s ease}}
        .thumb-btn:hover{{transform:translateY(-1px);border-color:rgba(191,208,228,.3)}}
        .thumb-btn.is-a{{box-shadow:inset 0 0 0 2px rgba(74,222,128,.6)}}
        .thumb-btn.is-b{{box-shadow:inset 0 0 0 2px rgba(56,189,248,.7)}}
        .thumb-btn img{{width:100%;aspect-ratio:4/3;object-fit:cover;object-position:top;border-radius:10px;display:block;margin-bottom:6px;background:#030813}}
        .thumb-btn strong{{display:block;font-size:.76rem;line-height:1.3}}
        .thumb-btn span{{display:block;font-size:.7rem;color:#9cb0ca;margin-top:2px}}
        footer{{text-align:center;padding:20px;color:#64748b;font-size:12px}}
        @media(max-width:1100px){{
                .hero-grid,.filters-grid,.compare-grid{{grid-template-columns:1fr}}
                .toolbar{{position:static}}
        }}
        @media(max-width:680px){{
                .stats-grid{{grid-template-columns:1fr}}
                .report-grid{{grid-template-columns:1fr}}
                .hero-actions,.toolbar-actions,.compare-actions{{width:100%}}
                .hero-btn,.ghost-btn,.compare-chip{{flex:1;justify-content:center;text-align:center}}
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
            <h2>So sánh nhanh ngay trong báo cáo</h2>
            <p class="hero-copy">Bấm nút So sánh trên bất kỳ ảnh nào để mở bảng so sánh lớn. Người dùng có thể tự chọn 2 ảnh, chuyển đổi ảnh A/B và đối chiếu chi tiết mà không cần rời khỏi báo cáo.</p>
            <div class="hero-actions">
                <button class="hero-btn" type="button" id="openCompareBoard">Mở bảng so sánh</button>
                <button class="hero-btn secondary" type="button" id="scrollToResults">Xem danh sách ảnh</button>
            </div>
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
                <div class="select-wrap"><select id="deviceFilter">{''.join(device_options)}</select></div>
            </div>
            <div class="filter-box">
                <label for="kindFilter">Mục báo cáo</label>
                <div class="select-wrap"><select id="kindFilter">
                    <option value="all">Tất cả</option>
                    <option value="screen">Ảnh chụp</option>
                    <option value="interaction">Tương tác</option>
                </select></div>
            </div>
        </div>
        <div class="toolbar-foot">
            <div class="toolbar-note" id="resultCount">Đang hiển thị {total_cards}/{total_cards} mục</div>
            <div class="toolbar-actions">
                <button class="ghost-btn" type="button" id="openCompareFromToolbar">Mở bảng so sánh</button>
                <button class="ghost-btn" type="button" id="resetFilters">Đặt lại bộ lọc</button>
            </div>
        </div>
    </section>

    <section class="section-shell">
        <div class="section-head">
            <div>
                <div class="section-title">Danh sách viewport</div>
                <div class="section-subtitle">Ảnh được hiển thị gọn để quét nhanh. Bấm vào ảnh để xem lớn hoặc mở bảng so sánh.</div>
            </div>
        </div>
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
<div class="compare-modal" id="compareModal">
    <div class="compare-card">
        <div class="compare-top">
            <div>
                <h2>So sánh hình ảnh</h2>
                <p>Chọn khung A hoặc B, sau đó bấm thumbnail phía dưới để gán ảnh vào đúng khung. Ảnh đang bấm So sánh sẽ được đưa vào đây trước.</p>
            </div>
            <div class="compare-actions">
                <button class="compare-chip active" type="button" data-slot="a">Đang chọn khung A</button>
                <button class="compare-chip" type="button" data-slot="b">Đang chọn khung B</button>
                <button class="compare-chip" type="button" id="swapCompare">Đảo A/B</button>
                <button class="compare-chip" type="button" id="clearCompare">Xóa hết</button>
                <button class="compare-chip" type="button" id="closeCompare">Đóng</button>
            </div>
        </div>
        <div class="compare-grid">
            <div class="compare-slot" id="compareSlotA"></div>
            <div class="compare-slot" id="compareSlotB"></div>
        </div>
        <div class="compare-strip">
            <div class="compare-strip-head">
                <strong>Kho ảnh để so sánh</strong>
                <p>Thumbnail phía dưới được giữ gọn để người dùng chọn nhanh ảnh cần đối chiếu.</p>
            </div>
            <div class="thumb-grid" id="compareThumbGrid"></div>
        </div>
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
    const compareModal = document.getElementById('compareModal');
    const compareThumbGrid = document.getElementById('compareThumbGrid');
    const compareSlotButtons = Array.from(document.querySelectorAll('.compare-chip[data-slot]'));
    const imageCards = Array.from(document.querySelectorAll('.image-card'));
    const compareState = {{ a: null, b: null, active: 'b' }};

    function escapeHtml(value) {{
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }}

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

    function sameImage(a, b) {{
        return Boolean(a && b && a.src === b.src && a.title === b.title);
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

    function setActiveCompareSlot(slotName) {{
        compareState.active = slotName;
        compareSlotButtons.forEach((button) => {{
            button.classList.toggle('active', button.dataset.slot === slotName);
            button.textContent = button.dataset.slot === slotName
                ? `Đang chọn khung ${{button.dataset.slot.toUpperCase()}}`
                : `Chọn khung ${{button.dataset.slot.toUpperCase()}}`;
        }});
        renderCompare();
    }}

    function renderCompareSlot(slotName) {{
        const slotEl = document.getElementById(slotName === 'a' ? 'compareSlotA' : 'compareSlotB');
        const meta = compareState[slotName];
        slotEl.classList.toggle('is-active', compareState.active === slotName);
        if (!meta) {{
            slotEl.innerHTML = `
                <div class="compare-slot-head">
                    <h3>Khung ${{slotName.toUpperCase()}}</h3>
                    <span class="compare-slot-tag">Sẵn sàng</span>
                </div>
                <div class="compare-stage">
                    <div class="compare-placeholder">Chưa có ảnh trong khung ${{slotName.toUpperCase()}}. Chọn thumbnail phía dưới để đưa ảnh vào khung này.</div>
                </div>
            `;
            return;
        }}
        slotEl.innerHTML = `
            <div class="compare-slot-head">
                <h3>${{escapeHtml(meta.title)}}</h3>
                <span class="compare-slot-tag">Khung ${{slotName.toUpperCase()}}</span>
            </div>
            <div class="compare-stage has-image">
                <img class="compare-image" src="${{meta.src}}" alt="${{escapeHtml(meta.title)}}">
            </div>
            <div class="compare-meta">${{escapeHtml(meta.kind)}} · ${{escapeHtml(meta.group || 'khác')}} · ${{escapeHtml(meta.width)}}x${{escapeHtml(meta.height)}}px</div>
        `;
    }}

    function renderCompareThumbs() {{
        compareThumbGrid.innerHTML = imageCards.map((imageCard, index) => {{
            const meta = getImageMeta(imageCard);
            const isA = sameImage(compareState.a, meta);
            const isB = sameImage(compareState.b, meta);
            return `
                <button class="thumb-btn ${{isA ? 'is-a' : ''}} ${{isB ? 'is-b' : ''}}" type="button" data-thumb-index="${{index}}">
                    <img src="${{meta.src}}" alt="${{escapeHtml(meta.title)}}">
                    <strong>${{escapeHtml(meta.title)}}</strong>
                    <span>${{escapeHtml(meta.width)}}x${{escapeHtml(meta.height)}}px · ${{escapeHtml(meta.group || 'khác')}}</span>
                </button>
            `;
        }}).join('');
    }}

    function renderCompare() {{
        renderCompareSlot('a');
        renderCompareSlot('b');
        renderCompareThumbs();
    }}

    function assignCompare(slotName, meta) {{
        if (!meta) return;
        compareState[slotName] = meta;
        renderCompare();
    }}

    function openCompare(meta) {{
        if (meta) {{
            if (!compareState.a || sameImage(compareState.a, meta)) {{
                compareState.a = meta;
                if (sameImage(compareState.b, meta)) compareState.b = null;
                compareState.active = 'b';
            }} else if (!compareState.b || sameImage(compareState.b, meta)) {{
                compareState.b = meta;
                compareState.active = 'a';
            }} else {{
                compareState[compareState.active] = meta;
                compareState.active = compareState.active === 'a' ? 'b' : 'a';
            }}
        }}
        renderCompare();
        compareModal.classList.add('open');
    }}

    function closeCompare() {{
        compareModal.classList.remove('open');
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
    document.getElementById('scrollToResults').addEventListener('click', () => {{
        reportGrid.scrollIntoView({{behavior: 'smooth', block: 'start'}});
    }});
    document.getElementById('openCompareBoard').addEventListener('click', () => openCompare());
    document.getElementById('openCompareFromToolbar').addEventListener('click', () => openCompare());
    document.getElementById('resetFilters').addEventListener('click', () => {{
        searchFilter.value = '';
        deviceFilter.value = '';
        kindFilter.value = 'all';
        groupChips.forEach((entry) => entry.classList.toggle('active', entry.dataset.group === 'all'));
        applyFilters();
    }});

    reportGrid.addEventListener('click', (event) => {{
        const openTrigger = event.target.closest('.js-open-image');
        const compareTrigger = event.target.closest('.js-open-compare');
        if (!openTrigger && !compareTrigger) return;

        const meta = getImageMeta(event.target);
        if (openTrigger) openModal(meta);
        if (compareTrigger) openCompare(meta);
    }});

    compareThumbGrid.addEventListener('click', (event) => {{
        const thumb = event.target.closest('.thumb-btn');
        if (!thumb) return;
        const meta = getImageMeta(imageCards[Number(thumb.dataset.thumbIndex)]);
        assignCompare(compareState.active, meta);
    }});

    compareSlotButtons.forEach((button) => {{
        button.addEventListener('click', () => setActiveCompareSlot(button.dataset.slot));
    }});

    document.getElementById('closeModal').addEventListener('click', closeModal);
    imageModal.addEventListener('click', (event) => {{
        if (event.target === imageModal) closeModal();
    }});
    document.getElementById('closeCompare').addEventListener('click', closeCompare);
    compareModal.addEventListener('click', (event) => {{
        if (event.target === compareModal) closeCompare();
    }});
    document.addEventListener('keydown', (event) => {{
        if (event.key === 'Escape') {{
            closeModal();
            closeCompare();
        }}
    }});
    document.getElementById('swapCompare').addEventListener('click', () => {{
        const temp = compareState.a;
        compareState.a = compareState.b;
        compareState.b = temp;
        renderCompare();
    }});
    document.getElementById('clearCompare').addEventListener('click', () => {{
        compareState.a = null;
        compareState.b = null;
        compareState.active = 'a';
        setActiveCompareSlot('a');
        renderCompare();
    }});

    setActiveCompareSlot('b');
    applyFilters();
</script>
</body>
</html>"""

    out_path = os.path.join(output_dir, "report.html")
    os.makedirs(output_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report_html)
    return out_path
