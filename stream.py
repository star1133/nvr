"""จัดการ ffmpeg ที่แปลง RTSP -> HLS แบบเปิดเมื่อมีคนดู และปิดเองเมื่อไม่มีคนดู"""
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

# ปิดสตรีมอัตโนมัติเมื่อไม่มีการเรียกไฟล์ playlist เกินกี่วินาที
IDLE_TIMEOUT = 30
# จำนวน segment ที่เก็บใน playlist (สั้น = หน่วงต่ำ, ใช้ดิสก์น้อย)
HLS_LIST_SIZE = 6
HLS_SEGMENT_TIME = 1


def _input_opts(transport: str) -> list[str]:
    """ออปชันฝั่ง input ให้ทนทาน: วิเคราะห์สตรีมนานพอจะได้พารามฯ codec (เช่น H.265 GOP ยาว)
    และเพิ่ม buffer สำหรับ UDP กัน packet เรียงผิด/หาย"""
    opts = [
        "-rtsp_transport", transport,
        "-analyzeduration", "8000000",   # วิเคราะห์ได้ถึง ~8 วิ (ffmpeg หยุดเองเมื่อพอ)
        "-probesize", "8000000",
        "-max_delay", "5000000",
    ]
    if transport == "udp":
        opts += ["-buffer_size", "2000000", "-reorder_queue_size", "2000"]
    return opts


def test_rtsp(rtsp: str, timeout: float = 12.0, transport: str = "tcp") -> tuple[bool, str]:
    """ลองเชื่อมต่อ RTSP และอ่าน 1 เฟรม คืน (สำเร็จไหม, ข้อความ)"""
    cmd = [
        "ffmpeg", "-nostdin", "-loglevel", "error",
        *_input_opts(transport),
        "-i", rtsp,
        "-frames:v", "1", "-f", "null", "-",
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "หมดเวลาเชื่อมต่อ — เช็ค IP/พอร์ต/เครือข่าย ว่าเข้าถึงกล้องได้ไหม"
    except FileNotFoundError:
        return False, "ไม่พบ ffmpeg ในระบบ"
    if p.returncode == 0:
        return True, "เชื่อมต่อกล้องได้ ✓"
    err = (p.stderr or b"").decode(errors="ignore").strip().splitlines()
    msg = err[-1] if err else "เชื่อมต่อไม่สำเร็จ"
    low = msg.lower()
    if "401" in msg or "unauthorized" in low:
        msg = "รหัสผ่าน/ชื่อผู้ใช้ไม่ถูกต้อง (401)"
    elif "404" in msg or "not found" in low:
        msg = "ไม่พบ stream path นี้ (404) — ลองเปลี่ยนยี่ห้อ/ช่อง/path"
    elif "timed out" in low or "timeout" in low:
        msg = "เชื่อมต่อไม่ได้ — เช็ค IP/พอร์ต/เครือข่าย"
    elif "connection refused" in low:
        msg = "ถูกปฏิเสธการเชื่อมต่อ — เช็คพอร์ต RTSP (ปกติ 554)"
    return False, msg


class HlsStream:
    def __init__(self, cam_id: str, rtsp: str, root: Path,
                 transport: str = "tcp", transcode: bool = False):
        self.cam_id = cam_id
        self.rtsp = rtsp
        self.transport = transport
        self.transcode = transcode
        self.dir = root / cam_id
        self.playlist = self.dir / "index.m3u8"
        self.proc: subprocess.Popen | None = None
        self.last_access = 0.0
        self.lock = threading.Lock()

    def _video_args(self) -> list[str]:
        if self.transcode:
            # แปลงเป็น H.264 ให้เบราว์เซอร์ทั่วไปเล่นได้ (เช่นกล้องที่ส่ง H.265)
            # -g = keyframe ทุก ~1 วิ ให้ตรงกับ hls_time เพื่อตัด segment สะอาด
            return [
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-tune", "zerolatency",
                "-profile:v", "main",
                "-pix_fmt", "yuv420p",
                "-g", "30", "-keyint_min", "30", "-sc_threshold", "0",
            ]
        # คัดลอก codec ตรงๆ -> CPU ต่ำมาก รองรับทั้ง H.264/H.265
        return ["-c:v", "copy"]

    def _build_cmd(self) -> list[str]:
        return [
            "ffmpeg",
            "-nostdin",
            "-loglevel", "error",
            *_input_opts(self.transport),      # tcp เสถียรกว่าในวงแลน แต่บางกล้องต้อง udp
            "-i", self.rtsp,
            "-an",                             # ไม่เอาเสียง
            *self._video_args(),
            "-f", "hls",
            "-hls_time", str(HLS_SEGMENT_TIME),
            "-hls_list_size", str(HLS_LIST_SIZE),
            "-hls_flags", "delete_segments+append_list+omit_endlist",
            "-hls_segment_type", "mpegts",
            "-hls_segment_filename", str(self.dir / "seg_%05d.ts"),
            str(self.playlist),
        ]

    def _alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def ensure_running(self) -> None:
        with self.lock:
            self.last_access = time.time()
            if self._alive():
                return
            self.dir.mkdir(parents=True, exist_ok=True)
            for f in self.dir.glob("*"):
                f.unlink(missing_ok=True)
            self.proc = subprocess.Popen(
                self._build_cmd(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def touch(self) -> None:
        self.last_access = time.time()

    def stop(self) -> None:
        with self.lock:
            if self._alive():
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            self.proc = None

    def wait_for_playlist(self, timeout: float = 12.0) -> bool:
        """รอจน ffmpeg เขียน playlist ที่มี segment อย่างน้อย 1 อัน"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self._alive():
                return False
            if self.playlist.exists() and ".ts" in self.playlist.read_text(errors="ignore"):
                return True
            time.sleep(0.2)
        return False


class StreamManager:
    def __init__(self, cameras):
        self.root = Path(tempfile.mkdtemp(prefix="nvr_hls_"))
        self.streams: dict[str, HlsStream] = {
            c.id: HlsStream(c.id, c.rtsp, self.root, c.transport, c.transcode)
            for c in cameras
        }
        self._stop_evt = threading.Event()
        self._reaper = threading.Thread(target=self._reap_loop, daemon=True)
        self._reaper.start()

    def get(self, cam_id: str) -> HlsStream | None:
        return self.streams.get(cam_id)

    def reload(self, cameras) -> None:
        """อัปเดตรายชื่อกล้องขณะรัน: หยุดตัวที่ถูกลบ/เปลี่ยน URL แล้วสร้างใหม่"""
        new_ids = {c.id for c in cameras}
        for cam_id in list(self.streams):
            if cam_id not in new_ids:
                self.streams.pop(cam_id).stop()
        for c in cameras:
            existing = self.streams.get(c.id)
            if existing is None:
                self.streams[c.id] = HlsStream(c.id, c.rtsp, self.root, c.transport, c.transcode)
            elif (existing.rtsp != c.rtsp or existing.transport != c.transport
                  or existing.transcode != c.transcode):
                existing.stop()
                self.streams[c.id] = HlsStream(c.id, c.rtsp, self.root, c.transport, c.transcode)

    def _reap_loop(self) -> None:
        while not self._stop_evt.wait(5):
            now = time.time()
            for s in self.streams.values():
                if s._alive() and now - s.last_access > IDLE_TIMEOUT:
                    s.stop()

    def shutdown(self) -> None:
        self._stop_evt.set()
        for s in self.streams.values():
            s.stop()
        shutil.rmtree(self.root, ignore_errors=True)
