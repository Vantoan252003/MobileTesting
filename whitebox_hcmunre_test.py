#!/usr/bin/env python3
"""
Standalone white-box responsive + interaction test for https://hcmunre.edu.vn.

Run:
  venv/bin/python whitebox_hcmunre_test.py
  venv/bin/python whitebox_hcmunre_test.py --groups mobile,tablet
  venv/bin/python whitebox_hcmunre_test.py --max-viewports 8

Output:
  - ket_qua_whitebox/<timestamp>/report.json
  - ket_qua_whitebox/<timestamp>/screenshots/*.png

Exit code:
  - 0: all checks passed
  - 1: at least one viewport has failures
"""

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from devices import DEVICES

DEFAULT_URL = "https://hcmunre.edu.vn"
MOBILE_BREAKPOINT = 992
OVERFLOW_FAIL_PX = 8
LOGO_RATIO_FAIL = 0.035
SMALL_TAP_WARN_RATIO = 0.35

LOGO_SELECTORS = [
    "header img",
    "img[alt*='logo' i]",
    "img[src*='logo' i]",
    "img[class*='logo' i]",
    "[id*='logo' i] img",
    ".logo img",
]

MENU_TOGGLE_SELECTORS = [
    "button.navbar-toggler",
    "button[class*='menu' i]",
    "button[aria-label*='menu' i]",
    "[class*='toggle' i][class*='menu' i]",
    "[id*='menu' i][class*='toggle' i]",
]

NAV_CONTAINER_SELECTORS = [
    "nav",
    "header nav",
    ".navbar-collapse",
    "#navbarNav",
    "[id*='menu' i]",
]


@dataclass
class ViewportResult:
    device_id: str
    name: str
    group: str
    width: int
    height: int
    screenshot: str
    checks: Dict[str, object] = field(default_factory=dict)
    failures: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)



def make_driver(width: int, height: int, ua: Optional[str], headless: bool) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--hide-scrollbars")
    opts.add_argument("--log-level=3")
    if ua:
        opts.add_argument(f"--user-agent={ua}")
    driver = webdriver.Chrome(options=opts)
    driver.set_window_size(width, height)
    return driver



def wait_page_ready(driver, timeout: int = 25) -> None:
    WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    time.sleep(1.2)



def screenshot_path(base_dir: str, vp: Dict[str, object]) -> str:
    fname = f"{vp['id']}_{vp['width']}x{vp['height']}.png"
    return os.path.join(base_dir, "screenshots", fname)



def get_responsive_metrics(driver) -> Dict[str, object]:
    script = """
    const isVisible = (el) => {
      const style = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' && r.width > 0 && r.height > 0;
    };

    const viewportW = window.innerWidth;
    const viewportH = window.innerHeight;
    const docW = Math.max(
      document.documentElement.scrollWidth,
      document.body ? document.body.scrollWidth : 0
    );
    const overflowPx = Math.max(0, docW - viewportW);

    const interactive = Array.from(document.querySelectorAll("a[href], button, input:not([type='hidden']), select, textarea"))
      .filter(isVisible)
      .map((el) => {
        const r = el.getBoundingClientRect();
        return { w: r.width, h: r.height };
      });

    const smallTap = interactive.filter((x) => x.w < 44 || x.h < 44).length;

    return {
      viewportW,
      viewportH,
      docW,
      overflowPx,
      interactiveCount: interactive.length,
      smallTapCount: smallTap,
    };
    """
    return driver.execute_script(script)



def pick_logo(driver) -> Optional[Dict[str, object]]:
    selector = ", ".join(LOGO_SELECTORS)
    script = """
    const selector = arguments[0];
    const nodes = Array.from(document.querySelectorAll(selector));
    const out = [];

    for (const el of nodes) {
      const style = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      const visible = style.display !== 'none' && style.visibility !== 'hidden' && r.width > 8 && r.height > 8;
      if (!visible) continue;

      const tag = (el.tagName || '').toLowerCase();
      let iw = 0;
      let ih = 0;
      if (tag === 'img') {
        iw = Number(el.naturalWidth || 0);
        ih = Number(el.naturalHeight || 0);
      } else if (tag === 'svg') {
        const vb = (el.getAttribute('viewBox') || '').trim().split(/\s+/);
        if (vb.length === 4) {
          iw = Number(vb[2] || 0);
          ih = Number(vb[3] || 0);
        }
      }

      let score = 0;
      const hint = `${(el.id || '').toLowerCase()} ${(el.className || '').toString().toLowerCase()} ${(el.alt || '').toLowerCase()} ${(el.src || '').toLowerCase()}`;
      if (hint.includes('logo')) score += 7;
      if (r.top < 220) score += 4;
      score += Math.min(6, (r.width * r.height) / 3500);

      out.push({
        score,
        tag,
        hint: (el.alt || el.id || el.className || el.src || 'logo').toString().slice(0, 140),
        renderedW: r.width,
        renderedH: r.height,
        intrinsicW: iw,
        intrinsicH: ih,
        objectFit: style.objectFit || '',
      });
    }

    out.sort((a, b) => (b.score - a.score));
    return out[0] || null;
    """
    return driver.execute_script(script, selector)



def check_logo_distortion(logo: Optional[Dict[str, object]], baseline_ratio: Optional[float]) -> Dict[str, object]:
    if not logo:
        return {
            "found": False,
            "distorted": False,
            "reason": "Logo not found",
            "rendered_ratio": None,
            "intrinsic_ratio": None,
            "baseline_ratio": baseline_ratio,
            "delta_intrinsic": None,
            "delta_baseline": None,
        }

    rw = float(logo.get("renderedW") or 0)
    rh = float(logo.get("renderedH") or 0)
    iw = float(logo.get("intrinsicW") or 0)
    ih = float(logo.get("intrinsicH") or 0)

    rendered_ratio = rw / max(rh, 1e-6)
    intrinsic_ratio = (iw / ih) if iw > 0 and ih > 0 else None

    delta_intrinsic = None
    delta_baseline = None
    distorted = False
    reasons: List[str] = []

    if intrinsic_ratio:
        delta_intrinsic = abs(rendered_ratio - intrinsic_ratio) / intrinsic_ratio
        if delta_intrinsic > LOGO_RATIO_FAIL:
            distorted = True
            reasons.append(f"ratio vs intrinsic lệch {delta_intrinsic * 100:.2f}%")

    if baseline_ratio and baseline_ratio > 0:
        delta_baseline = abs(rendered_ratio - baseline_ratio) / baseline_ratio
        if delta_baseline > LOGO_RATIO_FAIL:
            distorted = True
            reasons.append(f"ratio vs baseline lệch {delta_baseline * 100:.2f}%")

    if str(logo.get("objectFit") or "").strip().lower() == "fill":
        distorted = True
        reasons.append("object-fit: fill")

    return {
        "found": True,
        "distorted": distorted,
        "reason": "; ".join(reasons) if reasons else "ok",
        "hint": logo.get("hint"),
        "rendered": f"{rw:.1f}x{rh:.1f}",
        "intrinsic": f"{int(iw)}x{int(ih)}" if intrinsic_ratio else "unknown",
        "rendered_ratio": rendered_ratio,
        "intrinsic_ratio": intrinsic_ratio,
        "baseline_ratio": baseline_ratio,
        "delta_intrinsic": delta_intrinsic,
        "delta_baseline": delta_baseline,
    }



def check_mobile_menu_interaction(driver, is_mobile: bool) -> Dict[str, object]:
    if not is_mobile:
        return {"checked": False, "ok": True, "reason": "skip on non-mobile"}

    toggle_candidates = []
    for sel in MENU_TOGGLE_SELECTORS:
        toggle_candidates.extend(driver.find_elements(By.CSS_SELECTOR, sel))

    toggle = None
    for candidate in toggle_candidates:
        try:
            if candidate.is_displayed() and candidate.is_enabled():
                toggle = candidate
                break
        except Exception:
            continue

    nav_before = _count_visible_nav_links(driver)

    if toggle is None:
        if nav_before > 0:
            return {
                "checked": True,
                "ok": True,
                "reason": "no toggler but nav links are visible",
                "nav_visible_before": nav_before,
                "nav_visible_after": nav_before,
            }
        return {
            "checked": True,
            "ok": False,
            "reason": "mobile menu toggler not found",
            "nav_visible_before": nav_before,
            "nav_visible_after": nav_before,
        }

    expanded_before = (toggle.get_attribute("aria-expanded") or "").strip().lower()
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", toggle)
    driver.execute_script("arguments[0].click();", toggle)
    time.sleep(0.5)
    expanded_after = (toggle.get_attribute("aria-expanded") or "").strip().lower()
    nav_after = _count_visible_nav_links(driver)

    state_changed = expanded_before != expanded_after and (expanded_before or expanded_after)
    nav_changed = nav_after != nav_before
    ok = state_changed or nav_changed or nav_after > 0

    return {
        "checked": True,
        "ok": bool(ok),
        "reason": "ok" if ok else "toggler click did not change nav state",
        "expanded_before": expanded_before,
        "expanded_after": expanded_after,
        "nav_visible_before": nav_before,
        "nav_visible_after": nav_after,
    }



def _count_visible_nav_links(driver) -> int:
    script = """
    const isVisible = (el) => {
      const style = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' && r.width > 0 && r.height > 0;
    };

    const containerSelectors = arguments[0];
    const containers = [];
    for (const sel of containerSelectors) {
      try {
        containers.push(...Array.from(document.querySelectorAll(sel)));
      } catch (e) {}
    }

    let links = [];
    if (containers.length) {
      for (const c of containers) {
        links.push(...Array.from(c.querySelectorAll("a[href]")));
      }
    } else {
      links = Array.from(document.querySelectorAll("header a[href], nav a[href]"));
    }

    return links.filter(isVisible).length;
    """
    return int(driver.execute_script(script, NAV_CONTAINER_SELECTORS) or 0)



def check_header_link_click(driver, base_url: str) -> Dict[str, object]:
    script = """
    const links = Array.from(document.querySelectorAll("header a[href], nav a[href]"));
    const isVisible = (el) => {
      const style = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' && r.width > 8 && r.height > 8;
    };

    for (const a of links) {
      const href = a.getAttribute('href') || '';
      if (!href || href.startsWith('#') || href.startsWith('javascript:') || href.startsWith('tel:') || href.startsWith('mailto:')) {
        continue;
      }
      if (!isVisible(a)) continue;
      return {
        found: true,
        href,
        text: (a.textContent || '').trim().slice(0, 80),
      };
    }
    return { found: false };
    """
    candidate = driver.execute_script(script)
    if not candidate.get("found"):
        return {"checked": True, "ok": False, "reason": "no visible nav/header link found"}

    href = candidate.get("href", "")
    if href.startswith("/"):
        target = base_url.rstrip("/") + href
    else:
        target = href

    try:
        before = driver.current_url
        driver.get(target)
        wait_page_ready(driver, timeout=20)
        after = driver.current_url
        ok = bool(after)
        return {
            "checked": True,
            "ok": ok,
            "reason": "ok" if ok else "navigation failed",
            "target": target,
            "before": before,
            "after": after,
        }
    except TimeoutException:
        return {"checked": True, "ok": False, "reason": "navigation timeout", "target": target}
    except Exception as exc:
        return {"checked": True, "ok": False, "reason": str(exc)[:120], "target": target}



def select_viewports(groups: List[str], max_viewports: int) -> List[Dict[str, object]]:
    chosen = [d for d in DEVICES if d.get("group") in groups]
    chosen.sort(key=lambda x: (x["group"], x["width"]))
    if max_viewports > 0:
        chosen = chosen[:max_viewports]
    return chosen



def run_suite(url: str, viewports: List[Dict[str, object]], output_dir: str, headless: bool) -> Dict[str, object]:
    os.makedirs(os.path.join(output_dir, "screenshots"), exist_ok=True)

    suite_results: List[ViewportResult] = []
    logo_baseline_ratio: Optional[float] = None

    for vp in viewports:
        print(f"[RUN] {vp['name']} ({vp['width']}x{vp['height']})")
        driver = make_driver(vp["width"], vp["height"], vp.get("ua"), headless=headless)
        shot_path = screenshot_path(output_dir, vp)

        result = ViewportResult(
            device_id=vp.get("id", ""),
            name=vp["name"],
            group=vp.get("group", ""),
            width=int(vp["width"]),
            height=int(vp["height"]),
            screenshot=shot_path,
        )

        try:
            driver.get(url)
            wait_page_ready(driver)

            driver.save_screenshot(shot_path)

            metrics = get_responsive_metrics(driver)
            result.checks["layout"] = metrics
            overflow_px = float(metrics.get("overflowPx") or 0)
            interactive_count = int(metrics.get("interactiveCount") or 0)
            small_tap_count = int(metrics.get("smallTapCount") or 0)

            if overflow_px > OVERFLOW_FAIL_PX:
                result.failures.append(f"horizontal overflow {overflow_px:.1f}px > {OVERFLOW_FAIL_PX}px")

            if interactive_count > 0:
                small_tap_ratio = small_tap_count / interactive_count
                result.checks["layout"]["smallTapRatio"] = round(small_tap_ratio, 4)
                if small_tap_ratio > SMALL_TAP_WARN_RATIO:
                    result.warnings.append(
                        f"small tap targets ratio {small_tap_ratio * 100:.1f}% > {SMALL_TAP_WARN_RATIO * 100:.1f}%"
                    )

            logo = pick_logo(driver)
            logo_check = check_logo_distortion(logo, baseline_ratio=logo_baseline_ratio)
            result.checks["logo"] = logo_check

            candidate_ratio = logo_check.get("intrinsic_ratio") or logo_check.get("rendered_ratio")
            if candidate_ratio and (logo_baseline_ratio is None or (vp.get("group") == "desktop" and not logo_check.get("distorted"))):
                logo_baseline_ratio = float(candidate_ratio)

            if not logo_check.get("found"):
                result.warnings.append("logo not found by selectors")
            elif logo_check.get("distorted"):
                result.failures.append(f"logo distortion: {logo_check.get('reason')}")

            menu_check = check_mobile_menu_interaction(driver, is_mobile=vp["width"] < MOBILE_BREAKPOINT)
            result.checks["mobile_menu"] = menu_check
            if menu_check.get("checked") and not menu_check.get("ok"):
                result.failures.append(f"mobile menu interaction failed: {menu_check.get('reason')}")

            link_check = check_header_link_click(driver, base_url=url)
            result.checks["nav_link"] = link_check
            if not link_check.get("ok"):
                result.failures.append(f"header/nav link interaction failed: {link_check.get('reason')}")

        except Exception as exc:
            result.failures.append(f"test crashed: {str(exc)[:180]}")
        finally:
            driver.quit()

        suite_results.append(result)

    failed = [r for r in suite_results if r.failures]
    warned = [r for r in suite_results if (not r.failures and r.warnings)]

    return {
        "url": url,
        "run_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "thresholds": {
            "overflow_fail_px": OVERFLOW_FAIL_PX,
            "logo_ratio_fail": LOGO_RATIO_FAIL,
            "small_tap_warn_ratio": SMALL_TAP_WARN_RATIO,
            "mobile_breakpoint": MOBILE_BREAKPOINT,
        },
        "summary": {
            "total": len(suite_results),
            "failed": len(failed),
            "warning_only": len(warned),
            "passed": len(suite_results) - len(failed) - len(warned),
        },
        "results": [asdict(r) for r in suite_results],
    }



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="White-box responsive + interaction test for hcmunre.edu.vn")
    parser.add_argument("--url", default=DEFAULT_URL, help="Target URL")
    parser.add_argument(
        "--groups",
        default="mobile,tablet,desktop",
        help="Comma-separated groups from: mobile,tablet,desktop",
    )
    parser.add_argument("--max-viewports", type=int, default=0, help="Limit number of viewports (0 = all)")
    parser.add_argument("--headed", action="store_true", help="Run with browser UI")
    parser.add_argument(
        "--out-dir",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "ket_qua_whitebox"),
        help="Base output directory",
    )
    return parser.parse_args()



def main() -> int:
    args = parse_args()

    groups = [x.strip() for x in args.groups.split(",") if x.strip()]
    valid_groups = {"mobile", "tablet", "desktop"}
    groups = [g for g in groups if g in valid_groups]
    if not groups:
        print("[ERROR] No valid groups selected. Use mobile,tablet,desktop")
        return 2

    run_dir = os.path.join(args.out_dir, datetime.now().strftime("%Y%m%d_%H%M%S"))
    viewports = select_viewports(groups, args.max_viewports)

    if not viewports:
        print("[ERROR] No viewports selected")
        return 2

    print(f"[INFO] URL: {args.url}")
    print(f"[INFO] Viewports: {len(viewports)}")
    print(f"[INFO] Output: {run_dir}")

    report = run_suite(args.url, viewports, run_dir, headless=not args.headed)

    os.makedirs(run_dir, exist_ok=True)
    report_path = os.path.join(run_dir, "report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    total = report["summary"]["total"]
    failed = report["summary"]["failed"]
    warning_only = report["summary"]["warning_only"]
    passed = report["summary"]["passed"]

    print("\n[SUMMARY]")
    print(f"  Total      : {total}")
    print(f"  Passed     : {passed}")
    print(f"  Warning    : {warning_only}")
    print(f"  Failed     : {failed}")
    print(f"  Report JSON: {report_path}")

    if failed > 0:
        print("\n[FAILED VIEWPORTS]")
        for item in report["results"]:
            if item["failures"]:
                print(f"  - {item['name']} ({item['width']}x{item['height']})")
                for reason in item["failures"]:
                    print(f"      * {reason}")

    return 1 if failed > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
