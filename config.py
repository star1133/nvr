"""โหลด/บันทึก/ตรวจสอบการตั้งค่ากล้อง และสร้าง RTSP URL จากฟิลด์ที่ผู้ใช้กรอก"""
import json
import re
from pathlib import Path
from urllib.parse import quote

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "cameras.json"

_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# เทมเพลตเส้นทาง RTSP ตามยี่ห้อ — {ch}=หมายเลขช่อง, {s}=ตัวเลขสตรีม(0/1)
# ใช้ตัวแปร main/sub ตามที่ยี่ห้อนั้นนิยม
BRAND_PRESETS = {
    "hikvision": {
        "label": "Hikvision / HiLook",
        "main": "/Streaming/Channels/{ch}01",
        "sub": "/Streaming/Channels/{ch}02",
        "default_port": 554,
    },
    "dahua": {
        "label": "Dahua / Imou",
        "main": "/cam/realmonitor?channel={ch}&subtype=0",
        "sub": "/cam/realmonitor?channel={ch}&subtype=1",
        "default_port": 554,
    },
    "uniview": {
        "label": "Uniview (UNV)",
        "main": "/unicast/c{ch}/s0/live",
        "sub": "/unicast/c{ch}/s1/live",
        "default_port": 554,
    },
    "tplink": {
        "label": "TP-Link / VIGI / Tapo",
        "main": "/stream1",
        "sub": "/stream2",
        "default_port": 554,
    },
    "axis": {
        "label": "Axis",
        "main": "/axis-media/media.amp",
        "sub": "/axis-media/media.amp?resolution=640x480",
        "default_port": 554,
    },
    "onvif": {
        "label": "ONVIF (ดึง URL อัตโนมัติ)",
        "main": "",
        "sub": "",
        "default_port": 554,
    },
    "custom": {
        "label": "อื่นๆ (กรอก path เอง)",
        "main": "",
        "sub": "",
        "default_port": 554,
    },
}


def build_rtsp(cam: dict) -> str:
    """สร้าง RTSP URL จากฟิลด์ที่กรอก ถ้ามี rtsp เต็มมาแล้วก็ใช้เลย"""
    raw = str(cam.get("rtsp", "")).strip()
    if raw:
        return raw

    ip = str(cam.get("ip", "")).strip()
    port = int(cam.get("port") or 554)
    user = str(cam.get("username", "")).strip()
    pwd = str(cam.get("password", ""))
    brand = str(cam.get("brand", "custom")).strip().lower()
    channel = int(cam.get("channel") or 1)
    stream = str(cam.get("stream", "main")).strip().lower()
    path_override = str(cam.get("path", "")).strip()

    preset = BRAND_PRESETS.get(brand, BRAND_PRESETS["custom"])
    if path_override:
        path = path_override
    else:
        tmpl = preset["sub"] if stream == "sub" else preset["main"]
        path = tmpl.format(ch=channel, s=1 if stream == "sub" else 0)
    if path and not path.startswith("/"):
        path = "/" + path

    # ใส่ user:pass แบบ percent-encode กันอักขระพิเศษใน password (@ : / ฯลฯ)
    auth = ""
    if user:
        auth = quote(user, safe="") + ":" + quote(pwd, safe="") + "@"
    return f"rtsp://{auth}{ip}:{port}{path}"


def normalize_transport(value) -> str:
    """คืน 'udp' หรือ 'tcp' (ดีฟอลต์ tcp) — บางกล้อง (เช่น XiongMai) ต้องใช้ udp"""
    return "udp" if str(value or "").strip().lower() == "udp" else "tcp"


def normalize_transcode(value) -> bool:
    """แปลงค่าเป็น bool — True = ให้แปลง H.265->H.264 (เปลือง CPU แต่เบราว์เซอร์เล่นได้)"""
    return str(value).strip().lower() in ("1", "true", "yes", "on", "h264")


class Camera:
    def __init__(self, raw: dict):
        self.raw = raw
        self.id = str(raw.get("id", "")).strip()
        self.name = str(raw.get("name", "") or self.id).strip()
        self.rtsp = build_rtsp(raw)
        self.transport = normalize_transport(raw.get("transport"))
        self.transcode = normalize_transcode(raw.get("transcode"))


def _validate(raw_list: list[dict]) -> list[dict]:
    """ตรวจสอบและเติม id อัตโนมัติ คืน list ที่ normalize แล้ว"""
    out: list[dict] = []
    seen: set[str] = set()
    for i, item in enumerate(raw_list):
        if not isinstance(item, dict):
            raise ValueError(f"รายการที่ {i+1} ไม่ถูกต้อง")
        cam = dict(item)
        cam_id = str(cam.get("id", "")).strip()
        if not cam_id:
            cam_id = f"cam{i+1}"
        if not _ID_RE.match(cam_id):
            raise ValueError(f"กล้องตัวที่ {i+1}: id ใช้ได้เฉพาะ A-Z a-z 0-9 _ -")
        if cam_id in seen:
            raise ValueError(f"id ซ้ำ: {cam_id!r}")
        seen.add(cam_id)
        cam["id"] = cam_id
        cam["name"] = str(cam.get("name", "") or cam_id).strip()
        cam["transport"] = normalize_transport(cam.get("transport"))
        cam["transcode"] = normalize_transcode(cam.get("transcode"))

        rtsp = build_rtsp(cam)
        if not rtsp.lower().startswith("rtsp://"):
            raise ValueError(f"กล้อง {cam_id!r}: สร้าง RTSP URL ไม่ได้ (เช็ค IP/path)")
        if not str(cam.get("rtsp", "")).strip() and not str(cam.get("ip", "")).strip():
            raise ValueError(f"กล้อง {cam_id!r}: ต้องกรอก IP")
        out.append(cam)
    return out


def load_raw() -> list[dict]:
    if not CONFIG_FILE.exists():
        return []
    data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return data.get("cameras", []) if isinstance(data, dict) else []


def load_cameras() -> list[Camera]:
    return [Camera(c) for c in load_raw()]


def save_cameras(raw_list: list[dict]) -> list[dict]:
    normalized = _validate(raw_list)
    CONFIG_FILE.write_text(
        json.dumps({"cameras": normalized}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return normalized
