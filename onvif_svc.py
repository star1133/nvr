"""ONVIF helper: ค้นหากล้องในวงแลน, ดึง RTSP/snapshot/ข้อมูลเครื่อง, และสั่ง PTZ

ใช้ python-onvif-zeep (SOAP) + wsdiscovery (WS-Discovery)
ทุกฟังก์ชันเป็น blocking (ถูกเรียกผ่าน threadpool ของ FastAPI)
"""
from urllib.parse import quote, urlsplit, urlunsplit

DEFAULT_ONVIF_PORT = 80

try:
    from onvif import ONVIFCamera
    _IMPORT_ERR = None
except Exception as e:  # ไม่ได้ติดตั้ง onvif-zeep
    ONVIFCamera = None
    _IMPORT_ERR = e


class OnvifError(Exception):
    """ข้อผิดพลาดจากการคุยกับกล้องผ่าน ONVIF (มีข้อความภาษาไทยพร้อมแสดง)"""


def available() -> bool:
    return ONVIFCamera is not None


def _require():
    if ONVIFCamera is None:
        raise OnvifError(f"ยังไม่ได้ติดตั้งไลบรารี onvif-zeep ({_IMPORT_ERR})")


def _with_auth(uri: str, user: str, pwd: str) -> str:
    """ใส่ user:pass ลงใน URL ที่กล้องคืนมา (กล้องมักคืน rtsp://host/... ไม่มีรหัส)"""
    if not user:
        return uri
    parts = urlsplit(uri)
    host = parts.hostname or ""
    if not host:
        return uri
    auth = quote(user, safe="") + ":" + quote(pwd, safe="") + "@"
    netloc = auth + host + (f":{parts.port}" if parts.port else "")
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _friendly(e: Exception) -> str:
    msg = str(e) or e.__class__.__name__
    low = msg.lower()
    if "401" in msg or "unauthorized" in low or "not authorized" in low:
        return "ชื่อผู้ใช้/รหัสผ่าน ONVIF ไม่ถูกต้อง"
    if "timed out" in low or "timeout" in low or "connection refused" in low or "no route" in low:
        return "เชื่อมต่อ ONVIF ไม่ได้ — เช็ค IP/พอร์ต ONVIF (ปกติ 80) และว่ากล้องเปิด ONVIF ไว้"
    return f"ONVIF ผิดพลาด: {msg}"


# ---------- WS-Discovery ----------
def discover(timeout: int = 4) -> list[dict]:
    """ค้นหากล้อง ONVIF ในวงแลนผ่าน WS-Discovery คืน list ของ {ip, port, name, xaddr}"""
    from wsdiscovery.discovery import ThreadedWSDiscovery as WSDiscovery

    wsd = WSDiscovery()
    wsd.start()
    try:
        services = wsd.searchServices(timeout=timeout)
    finally:
        wsd.stop()

    found: dict[str, dict] = {}
    for svc in services:
        types = " ".join(str(t) for t in (svc.getTypes() or []))
        if "NetworkVideoTransmitter" not in types and "Device" not in types:
            continue
        for xaddr in svc.getXAddrs() or []:
            parts = urlsplit(xaddr)
            ip = parts.hostname
            if not ip:
                continue
            port = parts.port or DEFAULT_ONVIF_PORT
            name = ""
            for scope in svc.getScopes() or []:
                s = str(scope.getValue() if hasattr(scope, "getValue") else scope)
                if "/name/" in s:
                    name = s.rsplit("/name/", 1)[-1].replace("%20", " ")
                    break
            found[f"{ip}:{port}"] = {"ip": ip, "port": port, "name": name, "xaddr": xaddr}
    return sorted(found.values(), key=lambda d: d["ip"])


# ---------- Probe (ข้อมูลเครื่อง + โปรไฟล์ + RTSP/snapshot) ----------
def _connect(ip: str, port: int, user: str, pwd: str) -> "ONVIFCamera":
    _require()
    try:
        return ONVIFCamera(ip, int(port or DEFAULT_ONVIF_PORT), user, pwd)
    except Exception as e:
        raise OnvifError(_friendly(e)) from e


def probe(ip: str, port: int, user: str, pwd: str) -> dict:
    """เชื่อมต่อกล้อง คืนข้อมูลเครื่อง + รายการโปรไฟล์ (พร้อม rtsp/snapshot/ptz ของแต่ละโปรไฟล์)"""
    cam = _connect(ip, port, user, pwd)
    try:
        media = cam.create_media_service()
        profiles = media.GetProfiles()
    except Exception as e:
        raise OnvifError(_friendly(e)) from e

    try:
        di = cam.devicemgmt.GetDeviceInformation()
        info = {
            "manufacturer": getattr(di, "Manufacturer", "") or "",
            "model": getattr(di, "Model", "") or "",
            "firmware": getattr(di, "FirmwareVersion", "") or "",
        }
    except Exception:
        info = {"manufacturer": "", "model": "", "firmware": ""}

    out_profiles = []
    for p in profiles:
        token = p.token
        rtsp = ""
        try:
            req = media.create_type("GetStreamUri")
            req.ProfileToken = token
            req.StreamSetup = {
                "Stream": "RTP-Unicast",
                "Transport": {"Protocol": "RTSP"},
            }
            rtsp = _with_auth(media.GetStreamUri(req).Uri, user, pwd)
        except Exception:
            pass

        snapshot = ""
        try:
            snapshot = _with_auth(
                media.GetSnapshotUri({"ProfileToken": token}).Uri, user, pwd
            )
        except Exception:
            pass

        res = ""
        try:
            rc = p.VideoEncoderConfiguration.Resolution
            res = f"{rc.Width}x{rc.Height}"
        except Exception:
            pass

        has_ptz = getattr(p, "PTZConfiguration", None) is not None
        out_profiles.append({
            "token": token,
            "name": getattr(p, "Name", "") or token,
            "resolution": res,
            "rtsp": rtsp,
            "snapshot": snapshot,
            "ptz": has_ptz,
        })

    if not out_profiles:
        raise OnvifError("กล้องไม่มีโปรไฟล์วิดีโอที่ใช้งานได้")
    return {"info": info, "profiles": out_profiles}


# ---------- PTZ ----------
def ptz(ip: str, port: int, user: str, pwd: str, profile_token: str,
        pan: float = 0.0, tilt: float = 0.0, zoom: float = 0.0,
        stop: bool = False) -> None:
    """สั่ง PTZ แบบ ContinuousMove (กดค้าง) หรือ Stop เมื่อ stop=True"""
    cam = _connect(ip, port, user, pwd)
    try:
        ptz_svc = cam.create_ptz_service()
        media = cam.create_media_service()
        token = profile_token or media.GetProfiles()[0].token
        if stop:
            ptz_svc.Stop({"ProfileToken": token, "PanTilt": True, "Zoom": True})
            return
        req = ptz_svc.create_type("ContinuousMove")
        req.ProfileToken = token
        req.Velocity = {
            "PanTilt": {"x": float(pan), "y": float(tilt)},
            "Zoom": {"x": float(zoom)},
        }
        ptz_svc.ContinuousMove(req)
    except OnvifError:
        raise
    except Exception as e:
        raise OnvifError(_friendly(e)) from e
