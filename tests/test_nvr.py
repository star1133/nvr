"""Unit tests for NVR viewer (config, stream command construction, onvif helpers).
Runs purely offline with zero network, subprocess, or camera access.
"""
import unittest
from pathlib import Path
import sys

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import config
import stream
import onvif_svc


class TestNvrConfig(unittest.TestCase):
    def test_build_rtsp_presets(self):
        # Hikvision main
        cam_hik = {
            "ip": "192.168.1.100",
            "port": 554,
            "username": "admin",
            "password": "123",
            "brand": "hikvision",
            "channel": 1,
            "stream": "main",
        }
        self.assertEqual(
            config.build_rtsp(cam_hik),
            "rtsp://admin:123@192.168.1.100:554/Streaming/Channels/101",
        )

        # Dahua sub
        cam_dahua = {
            "ip": "192.168.1.101",
            "port": 554,
            "brand": "dahua",
            "channel": 2,
            "stream": "sub",
        }
        self.assertEqual(
            config.build_rtsp(cam_dahua),
            "rtsp://192.168.1.101:554/cam/realmonitor?channel=2&subtype=1",
        )

        # Uniview
        cam_unv = {
            "ip": "192.168.1.102",
            "brand": "uniview",
            "channel": 1,
            "stream": "main",
        }
        self.assertEqual(
            config.build_rtsp(cam_unv),
            "rtsp://192.168.1.102:554/unicast/c1/s0/live",
        )

        # TP-Link
        cam_tplink = {
            "ip": "192.168.1.103",
            "brand": "tplink",
            "stream": "sub",
        }
        self.assertEqual(
            config.build_rtsp(cam_tplink),
            "rtsp://192.168.1.103:554/stream2",
        )

    def test_build_rtsp_special_chars_in_password(self):
        cam = {
            "ip": "10.0.0.5",
            "port": 8554,
            "username": "user@domain",
            "password": "p:a@s/s#w?o=r&d",
            "brand": "custom",
            "path": "/live.sdp",
        }
        url = config.build_rtsp(cam)
        self.assertTrue(url.startswith("rtsp://"))
        self.assertIn("user%40domain:p%3Aa%40s%2Fs%23w%3Fo%3Dr%26d@", url)
        self.assertIn("10.0.0.5:8554/live.sdp", url)

    def test_build_rtsp_direct_url_preserved(self):
        direct = "rtsp://camera.local/stream"
        cam = {"rtsp": direct, "ip": "1.2.3.4"}
        self.assertEqual(config.build_rtsp(cam), direct)

    def test_normalize_transport(self):
        self.assertEqual(config.normalize_transport("udp"), "udp")
        self.assertEqual(config.normalize_transport("UDP"), "udp")
        self.assertEqual(config.normalize_transport("tcp"), "tcp")
        self.assertEqual(config.normalize_transport(None), "tcp")
        self.assertEqual(config.normalize_transport(""), "tcp")

    def test_normalize_transcode(self):
        for val in (True, 1, "1", "true", "True", "YES", "on", "h264"):
            self.assertTrue(config.normalize_transcode(val))
        for val in (False, 0, "0", "false", "no", "off", None):
            self.assertFalse(config.normalize_transcode(val))

    def test_validate_cameras(self):
        # Auto assigns cam1
        cams = [{"ip": "192.168.1.10", "brand": "tplink"}]
        validated = config._validate(cams)
        self.assertEqual(len(validated), 1)
        self.assertEqual(validated[0]["id"], "cam1")
        self.assertEqual(validated[0]["transport"], "tcp")
        self.assertFalse(validated[0]["transcode"])

        # Duplicate ID raises ValueError
        dups = [
            {"id": "cam1", "ip": "192.168.1.10", "brand": "tplink"},
            {"id": "cam1", "ip": "192.168.1.11", "brand": "tplink"},
        ]
        with self.assertRaises(ValueError):
            config._validate(dups)

        # Invalid ID characters raise ValueError
        invalid_id = [{"id": "cam#1", "ip": "192.168.1.10", "brand": "tplink"}]
        with self.assertRaises(ValueError):
            config._validate(invalid_id)

        # Missing IP without rtsp raises ValueError
        missing_ip = [{"id": "cam1", "brand": "tplink"}]
        with self.assertRaises(ValueError):
            config._validate(missing_ip)


class TestNvrStream(unittest.TestCase):
    def test_input_opts(self):
        tcp_opts = stream._input_opts("tcp")
        self.assertIn("-rtsp_transport", tcp_opts)
        self.assertEqual(tcp_opts[tcp_opts.index("-rtsp_transport") + 1], "tcp")
        self.assertNotIn("-reorder_queue_size", tcp_opts)

        udp_opts = stream._input_opts("udp")
        self.assertIn("-rtsp_transport", udp_opts)
        self.assertEqual(udp_opts[udp_opts.index("-rtsp_transport") + 1], "udp")
        self.assertIn("-reorder_queue_size", udp_opts)

    def test_hls_stream_cmd_construction(self):
        root = Path("/tmp/dummy_nvr")
        hls_copy = stream.HlsStream("cam1", "rtsp://10.0.0.1/1", root, transport="tcp", transcode=False)
        cmd_copy = hls_copy._build_cmd()
        self.assertIn("-c:v", cmd_copy)
        self.assertEqual(cmd_copy[cmd_copy.index("-c:v") + 1], "copy")
        self.assertIn("-f", cmd_copy)
        self.assertEqual(cmd_copy[cmd_copy.index("-f") + 1], "hls")

        hls_transcode = stream.HlsStream("cam1", "rtsp://10.0.0.1/1", root, transport="udp", transcode=True)
        cmd_trans = hls_transcode._build_cmd()
        self.assertIn("-c:v", cmd_trans)
        self.assertEqual(cmd_trans[cmd_trans.index("-c:v") + 1], "libx264")
        self.assertIn("-pix_fmt", cmd_trans)


class TestNvrOnvif(unittest.TestCase):
    def test_with_auth(self):
        uri = "rtsp://192.168.1.200:554/live"
        authed = onvif_svc._with_auth(uri, "admin", "p@ss:123")
        self.assertEqual(authed, "rtsp://admin:p%40ss%3A123@192.168.1.200:554/live")

        no_user = onvif_svc._with_auth(uri, "", "")
        self.assertEqual(no_user, uri)

    def test_friendly_errors(self):
        msg401 = onvif_svc._friendly(Exception("HTTP 401 Unauthorized"))
        self.assertIn("รหัสผ่าน", msg401)

        msg_timeout = onvif_svc._friendly(Exception("connection timed out"))
        self.assertIn("เชื่อมต่อ ONVIF ไม่ได้", msg_timeout)


if __name__ == "__main__":
    unittest.main()
