# devices.py – Danh sach viewport kiem thu responsive

_UA_IPHONE  = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
_UA_ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
_UA_IPAD    = "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
_UA_ANDROID_TAB = "Mozilla/5.0 (Linux; Android 13; SM-X710) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

DEVICES = [
    # ── Mobile ────────────────────────────────────────────────
    {"id": "mobile_xs",   "name": "Mobile XS (320px)",      "group": "mobile",  "width": 320,  "height": 568,  "ua": _UA_IPHONE},
    {"id": "iphone_se",   "name": "iPhone SE (375px)",      "group": "mobile",  "width": 375,  "height": 667,  "ua": _UA_IPHONE},
    {"id": "android_360", "name": "Android S (360px)",      "group": "mobile",  "width": 360,  "height": 800,  "ua": _UA_ANDROID},
    {"id": "iphone_14",   "name": "iPhone 14 Pro (393px)",  "group": "mobile",  "width": 393,  "height": 852,  "ua": _UA_IPHONE},
    {"id": "android_412", "name": "Android L (412px)",      "group": "mobile",  "width": 412,  "height": 915,  "ua": _UA_ANDROID},
    {"id": "iphone_plus", "name": "iPhone 14 Plus (428px)", "group": "mobile",  "width": 428,  "height": 926,  "ua": _UA_IPHONE},
    {"id": "android_480", "name": "Android XL (480px)",     "group": "mobile",  "width": 480,  "height": 900,  "ua": _UA_ANDROID},

    # ── Tablet ────────────────────────────────────────────────
    {"id": "ipad_mini",   "name": "iPad Mini (744px)",      "group": "tablet",  "width": 744,  "height": 1133, "ua": _UA_IPAD},
    {"id": "tablet_768",  "name": "iPad / Tab (768px)",     "group": "tablet",  "width": 768,  "height": 1024, "ua": _UA_IPAD},
    {"id": "ipad_air",    "name": "iPad Air (820px)",       "group": "tablet",  "width": 820,  "height": 1180, "ua": _UA_IPAD},
    {"id": "android_tab", "name": "Galaxy Tab (800px)",     "group": "tablet",  "width": 800,  "height": 1280, "ua": _UA_ANDROID_TAB},
    {"id": "ipad_pro_11", "name": "iPad Pro 11 (834px)",    "group": "tablet",  "width": 834,  "height": 1194, "ua": _UA_IPAD},
    {"id": "surface_pro", "name": "Surface Pro (912px)",    "group": "tablet",  "width": 912,  "height": 1368, "ua": _UA_ANDROID_TAB},
    {"id": "ipad_pro_13", "name": "iPad Pro 13 (1024px)",   "group": "tablet",  "width": 1024, "height": 1366, "ua": _UA_IPAD},

    # ── Desktop / Laptop ──────────────────────────────────────
    {"id": "laptop_768",  "name": "Laptop S (1024px)",      "group": "desktop", "width": 1024, "height": 768,  "ua": None},
    {"id": "laptop",      "name": "Laptop (1280px)",        "group": "desktop", "width": 1280, "height": 800,  "ua": None},
    {"id": "laptop_l",    "name": "Laptop L (1440px)",      "group": "desktop", "width": 1440, "height": 900,  "ua": None},
    {"id": "desktop_hd",  "name": "Desktop HD (1920px)",    "group": "desktop", "width": 1920, "height": 1080, "ua": None},
    {"id": "desktop_2k",  "name": "Desktop 2K (2560px)",    "group": "desktop", "width": 2560, "height": 1440, "ua": None},
]

DEVICE_MAP = {d["id"]: d for d in DEVICES}

# Nhom thiet bi de hien thi UI
DEVICE_GROUPS = {
    "mobile":  [d for d in DEVICES if d["group"] == "mobile"],
    "tablet":  [d for d in DEVICES if d["group"] == "tablet"],
    "desktop": [d for d in DEVICES if d["group"] == "desktop"],
}
