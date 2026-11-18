"""SSD1306 OLED 驱动 / 胜率渲染 / 显示设备 / 刷新泵 测试。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arena.hardware import (ConsoleDisplay, DisplayPump, MemoryDisplay,  # noqa: E402
                            Ssd1306Display, make_display)
from arena.hardware_log import HardwareLog  # noqa: E402
from arena.oled import (Framebuffer, RecordingTransport, SSD1306,  # noqa: E402
                        SerialOledTransport, demo_view, render_winrate_frame)
from arena.tournament import EventBus  # noqa: E402


class FramebufferTest(unittest.TestCase):
    def test_pixel_layout_is_page_major(self):
        fb = Framebuffer(128, 32)
        fb.pixel(0, 0)
        self.assertEqual(fb.buf[0], 0x01)
        fb.pixel(0, 7)
        self.assertEqual(fb.buf[0], 0x81)
        fb.pixel(127, 8)                       # 第二页的 (127, 0)
        self.assertEqual(fb.buf[255], 0x01)
        self.assertEqual(len(fb.to_bytes()), 128 * 4)

    def test_rejects_bad_geometry(self):
        with self.assertRaises(ValueError):
            Framebuffer(128, 30)
        with self.assertRaises(ValueError):
            Framebuffer(0, 32)

    def test_out_of_bounds_is_ignored(self):
        fb = Framebuffer(8, 8)
        for x, y in ((-1, 0), (0, -1), (8, 0), (0, 8)):
            fb.pixel(x, y)
        self.assertEqual(fb.to_bytes(), b"\x00" * 8)

    def test_rect_border_and_fill(self):
        fb = Framebuffer(8, 8)
        fb.rect(0, 0, 8, 8, fill=False)
        self.assertEqual(fb.buf[0] & 0x81, 0x81)
        fb.clear()
        fb.rect(0, 0, 8, 8, fill=True)
        self.assertEqual(fb.to_bytes(), b"\xff" * 8)

    def test_text_advances_and_draws(self):
        fb = Framebuffer(32, 8)
        end = fb.text(0, 0, "8")
        self.assertEqual(end, 6)
        self.assertEqual(Framebuffer.text_width("8"), 5)
        self.assertGreater(sum(fb.to_bytes()), 0)
        self.assertEqual(str(fb).count("\n"), 7)


class SSD1306Test(unittest.TestCase):
    def test_init_sequence_128x32(self):
        tr = RecordingTransport()
        SSD1306(tr, 128, 32).init()
        cmds = tr.commands
        self.assertEqual(cmds[:3], [0xAE, 0xD5, 0x80])
        self.assertEqual(cmds[cmds.index(0xA8) + 1], 0x1F)      # mux = 32
        self.assertEqual(cmds[cmds.index(0xDA) + 1], 0x02)
        self.assertIn(0xAF, cmds)

    def test_init_uses_64_layout(self):
        tr = RecordingTransport()
        SSD1306(tr, 128, 64).init()
        cmds = tr.commands
        self.assertEqual(cmds[cmds.index(0xA8) + 1], 0x3F)
        self.assertEqual(cmds[cmds.index(0xDA) + 1], 0x12)

    def test_display_writes_whole_frame(self):
        tr = RecordingTransport()
        dev = SSD1306(tr, 128, 32)
        fb = Framebuffer(128, 32)
        fb.clear(True)
        dev.display(fb, init_if_needed=False)
        self.assertEqual(tr.data_bytes, b"\xff" * (128 * 4))
        self.assertEqual(tr.commands[:3], [0x21, 0x00, 127])
        self.assertEqual(tr.commands[3:6], [0x22, 0x00, 3])

    def test_display_auto_inits(self):
        tr = RecordingTransport()
        SSD1306(tr, 128, 32).display()
        self.assertIn(0xAF, tr.commands)

    def test_contrast_clamped(self):
        tr = RecordingTransport()
        dev = SSD1306(tr, 128, 32)
        dev.contrast(999)
        cmds = tr.commands
        self.assertEqual(cmds[cmds.index(0x81) + 1], 255)


    def test_connection_lifecycle_is_logged_without_frame_noise(self):
        class Boom:
            def send(self, control, payload):
                raise RuntimeError("bridge offline")

        with tempfile.TemporaryDirectory() as td:
            ok_path = Path(td) / "ok.log"
            ok = Ssd1306Display(RecordingTransport(), log=HardwareLog(str(ok_path)),
                                log_spec="serial:TEST")
            ok.show({"black_winrate": 0.5})
            ok.show({"black_winrate": 0.6})
            ok_text = ok_path.read_text(encoding="utf-8")
            self.assertEqual(ok_text.count("status=ok"), 1)
            self.assertNotIn("hardware_send", ok_text)

            bad_path = Path(td) / "bad.log"
            Ssd1306Display(Boom(), log=HardwareLog(str(bad_path)),
                           log_spec="serial:TEST")
            self.assertIn("status=error", bad_path.read_text(encoding="utf-8"))


class RenderWinrateTest(unittest.TestCase):
    def test_dimensions(self):
        self.assertEqual(len(render_winrate_frame(demo_view(), 128, 32).to_bytes()), 128 * 4)
        self.assertEqual(len(render_winrate_frame(demo_view(), 128, 64).to_bytes()), 128 * 8)

    def test_bar_grows_with_winrate(self):
        lo = render_winrate_frame({"black_winrate": 0.05, "move_number": 1}).to_bytes()
        hi = render_winrate_frame({"black_winrate": 0.95, "move_number": 1}).to_bytes()
        lit = lambda b: sum(bin(x).count("1") for x in b)      # noqa: E731
        self.assertLess(lit(lo), lit(hi))

    def test_winrate_is_clamped(self):
        self.assertEqual(render_winrate_frame({"black_winrate": 5.0}).height, 32)
        self.assertEqual(render_winrate_frame({"black_winrate": -3.0}).height, 32)

    def test_white_only_view(self):
        fb = render_winrate_frame({"white_winrate": 0.7, "move_number": 3})
        self.assertGreater(sum(fb.to_bytes()), 0)

    def test_defaults_to_half(self):
        fb = render_winrate_frame({})
        self.assertGreater(sum(fb.to_bytes()), 0)

    def test_64_shows_status(self):
        txt = render_winrate_frame({"black_winrate": 0.9, "verdict": "black_win"}, 128, 64)
        self.assertTrue(any("#" in ln for ln in txt.to_ascii().splitlines()))


class Ssd1306DisplayTest(unittest.TestCase):
    def test_show_pushes_frame(self):
        tr = RecordingTransport()
        disp = Ssd1306Display(tr, width=128, height=32)
        disp.show({"black_winrate": 0.75, "move_number": 10, "engine": "katago"})
        self.assertTrue(disp.frames)
        self.assertEqual(len(tr.data_bytes), 128 * 4)
        self.assertIsNone(disp.error)

    def test_transport_failure_is_swallowed(self):
        class Boom:
            def send(self, control, payload):
                raise RuntimeError("i2c down")

        disp = Ssd1306Display(Boom(), width=128, height=32)
        disp.show({"black_winrate": 0.5})                    # 不应抛出
        self.assertIsNotNone(disp.error)

    def test_preview_ascii_size(self):
        disp = Ssd1306Display(RecordingTransport(), width=128, height=32)
        self.assertEqual(len(disp.preview(demo_view()).splitlines()), 32)


class MakeDisplayTest(unittest.TestCase):
    def test_mock_and_console(self):
        self.assertIsInstance(make_display(""), MemoryDisplay)
        self.assertIsInstance(make_display("mock"), MemoryDisplay)
        self.assertIsInstance(make_display("console"), ConsoleDisplay)

    def test_i2c_spec_geometry(self):
        disp = make_display("i2c:1:0x3c@128x64")
        self.assertIsInstance(disp, Ssd1306Display)
        self.assertEqual((disp.driver.width, disp.driver.height), (128, 64))
        self.assertIsNotNone(disp.error)                     # 无 smbus -> 记录错误但不崩

    def test_serial_spec(self):
        self.assertIsInstance(make_display("serial:COM99"), Ssd1306Display)

    def test_unknown_spec_raises(self):
        with self.assertRaises(ValueError):
            make_display("bogus")


class SerialFrameTest(unittest.TestCase):
    def test_encode_frame(self):
        frame = SerialOledTransport.encode_frame(0x40, b"\x01\x02\x03")
        self.assertEqual(frame, bytes([0xAA, 0x40, 0x03, 0x00, 1, 2, 3]))


class DisplayPumpTest(unittest.TestCase):
    @staticmethod
    def _view(black=0.6):
        return {"black_winrate": black, "white_winrate": 1.0 - black,
                "move_number": 5, "engine": "katago", "verdict": "ongoing"}

    def test_renders_on_state_event(self):
        bus, disp = EventBus(), MemoryDisplay()
        pump = DisplayPump(bus, disp).start()
        try:
            bus.publish({"type": "state", "code": "AB12", "payload": self._view(0.7)})
            self.assertIsNotNone(disp.last)
            self.assertAlmostEqual(disp.last["black_winrate"], 0.7)
        finally:
            pump.stop()

    def test_filters_by_room(self):
        bus, disp = EventBus(), MemoryDisplay()
        pump = DisplayPump(bus, disp, room_code="AB12").start()
        try:
            disp.frames.clear()
            bus.publish({"type": "state", "code": "ZZ99", "payload": self._view(0.9)})
            self.assertEqual(disp.frames, [])
            bus.publish({"type": "state", "code": "ab12", "payload": self._view(0.4)})
            self.assertEqual(len(disp.frames), 1)
        finally:
            pump.stop()

    def test_idle_frame_on_start(self):
        disp = MemoryDisplay()
        DisplayPump(EventBus(), disp).start()
        self.assertTrue(disp.frames)

    def test_stop_detaches(self):
        bus, disp = EventBus(), MemoryDisplay()
        pump = DisplayPump(bus, disp).start()
        pump.stop()
        disp.frames.clear()
        bus.publish({"type": "state", "code": "AB12", "payload": self._view()})
        self.assertEqual(disp.frames, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)