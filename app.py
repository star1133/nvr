"""เว็บดูกล้องวงจรปิด NVR ผ่าน RTSP -> HLS (FastAPI) + ตั้งค่าผ่านหน้าเว็บ"""
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import config
import onvif_svc
from config import BRAND_PRESETS, build_rtsp, load_cameras, save_cameras
from stream import StreamManager, test_rtsp

cameras = load_cameras()
manager = StreamManager(cameras)


def reload_all():
    global cameras
    cameras = load_cameras()
    manager.reload(cameras)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    manager.shutdown()


app = FastAPI(title="NVR Viewer", lifespan=lifespan)


# ---------- ดูกล้อง ----------
@app.get("/api/cameras")
def list_cameras():
    return [{"id": c.id, "name": c.name, "ptz": bool(c.raw.get("ptz"))} for c in cameras]


@app.get("/hls/{cam_id}/index.m3u8")
def hls_playlist(cam_id: str):
    stream = manager.get(cam_id)
    if stream is None:
        raise HTTPException(404, "ไม่พบกล้องนี้")
    stream.ensure_running()
    if not stream.wait_for_playlist():
        raise HTTPException(503, "เชื่อมต่อกล้องไม่ได้ — ตรวจ RTSP/เครือข่าย/รหัสผ่าน")
    return FileResponse(
        stream.playlist,
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/hls/{cam_id}/{segment}")
def hls_segment(cam_id: str, segment: str):
    stream = manager.get(cam_id)
    if stream is None or not segment.endswith(".ts"):
        raise HTTPException(404)
    stream.touch()
    path = (stream.dir / segment).resolve()
    if stream.dir.resolve() not in path.parents or not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="video/mp2t", headers={"Cache-Control": "no-store"})


@app.get("/api/health")
def health():
    return JSONResponse(
        {c.id: ("live" if manager.get(c.id)._alive() else "idle") for c in cameras}
    )


# ---------- ตั้งค่า ----------
@app.get("/api/brands")
def brands():
    return {k: {"label": v["label"], "default_port": v["default_port"]}
            for k, v in BRAND_PRESETS.items()}


@app.get("/api/config")
def get_config():
    return {"cameras": config.load_raw()}


@app.post("/api/config")
def post_config(payload: dict = Body(...)):
    cams = payload.get("cameras", [])
    try:
        save_cameras(cams)
        reload_all()
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "cameras": config.load_raw()}


@app.post("/api/test")
def test_camera(cam: dict = Body(...)):
    try:
        rtsp = build_rtsp(cam)
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(400, str(e))
    if not rtsp.lower().startswith("rtsp://"):
        raise HTTPException(400, "ข้อมูลไม่พอสำหรับสร้าง RTSP URL")
    transport = config.normalize_transport(cam.get("transport"))
    ok, msg = test_rtsp(rtsp, transport=transport)
    return {"ok": ok, "message": msg, "rtsp": rtsp}


# ---------- ONVIF ----------
@app.get("/api/onvif/available")
def onvif_available():
    return {"available": onvif_svc.available()}


@app.get("/api/onvif/discover")
def onvif_discover(timeout: int = 4):
    if not onvif_svc.available():
        raise HTTPException(400, "ยังไม่ได้ติดตั้ง onvif-zeep")
    try:
        devices = onvif_svc.discover(timeout=max(1, min(timeout, 10)))
    except Exception as e:
        raise HTTPException(502, f"ค้นหา ONVIF ไม่สำเร็จ: {e}")
    return {"devices": devices}


@app.post("/api/onvif/probe")
def onvif_probe(cam: dict = Body(...)):
    ip = str(cam.get("ip", "")).strip()
    if not ip:
        raise HTTPException(400, "ต้องกรอก IP กล้อง")
    port = int(cam.get("onvif_port") or onvif_svc.DEFAULT_ONVIF_PORT)
    user = str(cam.get("username", "")).strip()
    pwd = str(cam.get("password", ""))
    try:
        return onvif_svc.probe(ip, port, user, pwd)
    except onvif_svc.OnvifError as e:
        raise HTTPException(400, str(e))


@app.post("/api/onvif/ptz")
def onvif_ptz(cmd: dict = Body(...)):
    cam_id = str(cmd.get("id", "")).strip()
    cam = next((c for c in cameras if c.id == cam_id), None)
    if cam is None:
        raise HTTPException(404, "ไม่พบกล้องนี้")
    raw = cam.raw
    try:
        onvif_svc.ptz(
            ip=str(raw.get("ip", "")).strip(),
            port=int(raw.get("onvif_port") or onvif_svc.DEFAULT_ONVIF_PORT),
            user=str(raw.get("username", "")).strip(),
            pwd=str(raw.get("password", "")),
            profile_token=str(raw.get("profile", "")).strip(),
            pan=float(cmd.get("pan", 0) or 0),
            tilt=float(cmd.get("tilt", 0) or 0),
            zoom=float(cmd.get("zoom", 0) or 0),
            stop=bool(cmd.get("stop", False)),
        )
    except onvif_svc.OnvifError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
