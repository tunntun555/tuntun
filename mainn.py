#!/usr/bin/env python3
"""
ScreenFlow Display Client — Android (Kivy)
รันบนแท็บเล็ต Android แสดง wallpaper/screensaver อัตโนมัติ
"""

import os
import sys
import time
import json
import threading
import queue
from pathlib import Path
from datetime import datetime

# ─── Android wake lock (กันหน้าจอดับ) ─────────────────────────────────────────
def acquire_wake_lock():
    """ป้องกันหน้าจอดับขณะรัน screensaver"""
    try:
        from android.permissions import request_permissions, Permission
        request_permissions([
            Permission.WAKE_LOCK,
            Permission.INTERNET,
            Permission.WRITE_EXTERNAL_STORAGE,
            Permission.READ_EXTERNAL_STORAGE,
        ])
        from jnius import autoclass
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        Context = autoclass('android.content.Context')
        activity = PythonActivity.mActivity
        pm = activity.getSystemService(Context.POWER_SERVICE)
        PowerManager = autoclass('android.os.PowerManager')
        wake_lock = pm.newWakeLock(
            PowerManager.SCREEN_BRIGHT_WAKE_LOCK | PowerManager.ACQUIRE_CAUSES_WAKEUP,
            'ScreenFlow::WakeLock'
        )
        wake_lock.acquire()
        print("[WakeLock] หน้าจอถูกล็อกไม่ให้ดับ")
        return wake_lock
    except Exception as e:
        print(f"[WakeLock] ไม่สามารถ acquire ได้ (อาจรันบน Desktop): {e}")
        return None

# ─── Kivy config ต้องตั้งก่อน import kivy ─────────────────────────────────────
import kivy
kivy.require("2.3.0")

from kivy.config import Config
Config.set("graphics", "fullscreen", "auto")
Config.set("graphics", "borderless", "1")
Config.set("kivy", "log_level", "warning")

from kivy.app import App
from kivy.uix.widget import Widget
from kivy.uix.image import Image as KivyImage
from kivy.uix.video import Video as KivyVideo
from kivy.uix.label import Label
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.screenmanager import ScreenManager, Screen, NoTransition, FadeTransition
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.popup import Popup
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle
from kivy.animation import Animation
from kivy.utils import platform

import requests
import tempfile

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
VIDEO_EXT  = {".mp4", ".webm", ".mov", ".mkv"}

# ─── Config ───────────────────────────────────────────────────────────────────
def get_config_path():
    if platform == "android":
        from android.storage import app_storage_path
        return Path(app_storage_path()) / "screenflow_client.json"
    return Path.home() / ".screenflow_client.json"

def get_cache_dir():
    if platform == "android":
        from android.storage import app_storage_path
        return Path(app_storage_path()) / "screenflow_cache"
    return Path.home() / ".screenflow_cache"

CONFIG_FILE = get_config_path()

def load_config():
    import socket
    default = {
        "server_url": "https://michael-insider-interfaces-quiz.trycloudflare.com",
        "device_name": socket.gethostname(),
        "check_interval": 5,
        "cache_dir": str(get_cache_dir()),
        "slide_duration": 10,
        "idle_timeout": 60,
    }
    if CONFIG_FILE.exists():
        try:
            saved = json.loads(CONFIG_FILE.read_text())
            default.update(saved)
        except:
            pass
    return default

def save_config(cfg):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))

# ─── API Client ───────────────────────────────────────────────────────────────
class ScreenFlowAPI:
    def __init__(self, server_url):
        self.base = server_url.rstrip("/")

    def get_settings(self):
        r = requests.get(f"{self.base}/api/settings", timeout=10)
        r.raise_for_status()
        return r.json()

    def get_media_version(self):
        r = requests.get(f"{self.base}/api/media/version", timeout=10)
        r.raise_for_status()
        return r.json()

    def get_media_list(self):
        r = requests.get(f"{self.base}/api/media", timeout=15)
        r.raise_for_status()
        return r.json()

    def download_media(self, download_url, filename, dest_dir):
        dest = Path(dest_dir) / filename
        if dest.exists() and dest.stat().st_size > 0:
            return str(dest)

        ext = Path(filename).suffix.lower()
        is_video = ext in VIDEO_EXT
        timeout = (10, 300) if is_video else (10, 60)
        chunk_size = 1024 * 1024 if is_video else 65536

        tmp = dest.with_suffix(dest.suffix + ".tmp")
        try:
            r = requests.get(download_url, timeout=timeout, stream=True)
            r.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size):
                    if chunk:
                        f.write(chunk)
            tmp.rename(dest)
        except Exception:
            if tmp.exists():
                try:
                    tmp.unlink()
                except:
                    pass
            raise
        return str(dest)

    def ping(self, device_name):
        try:
            requests.post(f"{self.base}/api/ping",
                          json={"device": device_name}, timeout=3)
        except:
            pass

# ─── Idle Tracker (ใช้ touch แทน mouse/keyboard) ─────────────────────────────
class IdleTracker:
    def __init__(self):
        self.last_activity = time.time()
        self._lock = threading.Lock()

    def reset(self):
        with self._lock:
            self.last_activity = time.time()

    def idle_seconds(self):
        with self._lock:
            return time.time() - self.last_activity

# ─── Screensaver Screen ───────────────────────────────────────────────────────
class ScreensaverScreen(Screen):
    def __init__(self, client, **kwargs):
        super().__init__(**kwargs)
        self.client = client
        self.index = 0
        self.running = False
        self._slide_event = None
        self._clock_event = None
        self._current_video = None

        self.layout = FloatLayout()
        with self.layout.canvas.before:
            Color(0, 0, 0, 1)
            self._bg_rect = Rectangle(size=Window.size, pos=(0, 0))
        self.layout.bind(size=self._update_bg, pos=self._update_bg)

        # Media widget placeholder
        self._media_widget = None

        # Clock label
        self.clock_label = Label(
            text="",
            font_size="48sp",
            bold=True,
            color=(1, 1, 1, 1),
            size_hint=(None, None),
            size=(400, 80),
            pos_hint={"center_x": 0.5, "y": 0.05},
        )
        self.layout.add_widget(self.clock_label)
        self.add_widget(self.layout)

    def _update_bg(self, *args):
        self._bg_rect.size = self.layout.size
        self._bg_rect.pos = self.layout.pos

    @property
    def media_list(self):
        return self.client.media_cache

    def show(self, settings=None):
        self.running = True
        self.index = 0
        self._settings = settings or {}
        self._show_media()
        if self._settings.get("show_clock", True):
            self._clock_event = Clock.schedule_interval(self._update_clock, 1)

    def stop(self):
        self.running = False
        if self._slide_event:
            self._slide_event.cancel()
            self._slide_event = None
        if self._clock_event:
            self._clock_event.cancel()
            self._clock_event = None
        self._stop_video()

    def _show_media(self, *args):
        self._slide_event = None
        if not self.running:
            return
        if not self.media_list:
            self._show_no_media()
            return

        self._clear_media()
        media = self.media_list[self.index % len(self.media_list)]
        ext = Path(media).suffix.lower()

        if ext in VIDEO_EXT:
            self._play_video(media)
        else:
            self._display_image(media)
            duration = float(self._settings.get("slide_duration",
                             self.client.config.get("slide_duration", 10)))
            self._slide_event = Clock.schedule_once(self._next_media, duration)

    def _clear_media(self):
        self._stop_video()
        if self._media_widget and self._media_widget in self.layout.children:
            self.layout.remove_widget(self._media_widget)
        self._media_widget = None

    def _show_no_media(self):
        lbl = Label(
            text="ไม่มีรูปภาพ\nเพิ่มรูปที่ Web Admin",
            font_size="24sp",
            color=(0.2, 0.2, 0.2, 1),
            halign="center",
            pos_hint={"center_x": 0.5, "center_y": 0.5},
        )
        self.layout.add_widget(lbl)

    def _display_image(self, path):
        try:
            img = KivyImage(
                source=path,
                allow_stretch=True,
                keep_ratio=True,
                size_hint=(1, 1),
                pos_hint={"x": 0, "y": 0},
            )
            self._media_widget = img
            self.layout.add_widget(img)
            # ให้ clock_label อยู่บนสุดเสมอ
            self.layout.remove_widget(self.clock_label)
            self.layout.add_widget(self.clock_label)
        except Exception as e:
            lbl = Label(
                text=f"โหลดรูปไม่ได้\n{e}",
                font_size="18sp",
                color=(0.4, 0.2, 0.2, 1),
                pos_hint={"center_x": 0.5, "center_y": 0.5},
            )
            self._media_widget = lbl
            self.layout.add_widget(lbl)

    def _play_video(self, path):
        try:
            vid = KivyVideo(
                source=path,
                state="play",
                allow_stretch=True,
                keep_ratio=True,
                size_hint=(1, 1),
                pos_hint={"x": 0, "y": 0},
                options={"eos": "loop"},
            )
            vid.bind(eos=self._on_video_eos)
            self._current_video = vid
            self._media_widget = vid
            self.layout.add_widget(vid)
            self.layout.remove_widget(self.clock_label)
            self.layout.add_widget(self.clock_label)
        except Exception as e:
            print(f"วิดีโอ error: {e}")
            self._next_media()

    def _on_video_eos(self, video, value):
        """เมื่อวิดีโอจบ — ถ้ามีหลายไฟล์ให้ไปต่อ"""
        if not self.running:
            return
        if len(self.media_list) > 1:
            Clock.schedule_once(self._next_media, 0)
        else:
            # loop วิดีโอเดียว
            try:
                video.seek(0)
                video.state = "play"
            except:
                pass

    def _stop_video(self):
        if self._current_video:
            try:
                self._current_video.state = "stop"
                self._current_video.unload()
            except:
                pass
            self._current_video = None

    def _next_media(self, *args):
        if self.running:
            self.index += 1
            self._show_media()

    def _update_clock(self, *args):
        if self.running:
            self.clock_label.text = datetime.now().strftime("%H:%M")

    def on_touch_down(self, touch):
        """touch = activity → reset idle tracker และซ่อน screensaver"""
        self.client.idle.reset()
        if self._settings.get("hide_on_activity", True):
            self.client.exit_screensaver()
        return True


# ─── Setup Screen ─────────────────────────────────────────────────────────────
class SetupScreen(Screen):
    def __init__(self, client, on_done, **kwargs):
        super().__init__(**kwargs)
        self.client = client
        self.on_done = on_done
        self._build_ui()

    def _build_ui(self):
        layout = BoxLayout(orientation="vertical", padding=40, spacing=16)
        with layout.canvas.before:
            Color(0.05, 0.05, 0.1, 1)
            self._rect = Rectangle(size=Window.size)
        layout.bind(size=lambda *a: setattr(self._rect, "size", layout.size))

        layout.add_widget(Label(
            text="ScreenFlow\nDisplay Client",
            font_size="32sp",
            bold=True,
            color=(0.3, 0.9, 1, 1),
            halign="center",
            size_hint_y=None,
            height=120,
        ))

        layout.add_widget(Label(text="Server URL:", color=(1, 1, 1, 1),
                                size_hint_y=None, height=36, halign="left"))
        self.url_input = TextInput(
            text=self.client.config.get("server_url", ""),
            multiline=False,
            size_hint_y=None,
            height=50,
            font_size="18sp",
        )
        layout.add_widget(self.url_input)

        layout.add_widget(Label(text="ชื่ออุปกรณ์:", color=(1, 1, 1, 1),
                                size_hint_y=None, height=36, halign="left"))
        self.name_input = TextInput(
            text=self.client.config.get("device_name", ""),
            multiline=False,
            size_hint_y=None,
            height=50,
            font_size="18sp",
        )
        layout.add_widget(self.name_input)

        btn = Button(
            text="บันทึกและเริ่มต้น",
            font_size="20sp",
            size_hint_y=None,
            height=64,
            background_color=(0.2, 0.7, 1, 1),
        )
        btn.bind(on_press=self._save)
        layout.add_widget(btn)

        self.status_label = Label(text="", color=(1, 0.6, 0.2, 1),
                                  size_hint_y=None, height=40)
        layout.add_widget(self.status_label)

        self.add_widget(layout)

    def _save(self, *args):
        url = self.url_input.text.strip()
        name = self.name_input.text.strip()
        if url:
            self.client.config["server_url"] = url
        if name:
            self.client.config["device_name"] = name
        save_config(self.client.config)
        self.client.api = ScreenFlowAPI(self.client.config["server_url"])
        self.status_label.text = "บันทึกแล้ว กำลังเชื่อมต่อ..."
        self.on_done()


# ─── Main App ─────────────────────────────────────────────────────────────────
class DisplayClient:
    def __init__(self):
        self.config = load_config()
        self.api = ScreenFlowAPI(self.config["server_url"])
        self.idle = IdleTracker()
        self.screensaver_active = False
        self.media_cache = []
        self.settings = {}
        self._cmd_queue = queue.Queue()
        self._force_refresh = threading.Event()
        self._last_media_version = None
        self._fetch_error = None
        self._fetch_warnings = []
        self._wake_lock = None

    def fetch_settings(self):
        try:
            self.settings = self.api.get_settings()
        except Exception as e:
            print(f"⚠ ไม่สามารถโหลด settings: {e}")
            self.settings = {
                "idle_timeout": self.config.get("idle_timeout", 60),
                "slide_duration": self.config.get("slide_duration", 10),
                "show_clock": True,
                "hide_on_activity": True,
            }

    def fetch_media(self):
        self._fetch_warnings = []
        self._fetch_error = None
        try:
            version_info = self.api.get_media_version()
            server_count = version_info.get("count", 0)
            server_version = version_info.get("version", "0")
            server_filenames = set(version_info.get("filenames", []))

            if (server_version == self._last_media_version
                    and server_count == len(self.media_cache)
                    and all(Path(p).exists() for p in self.media_cache)):
                return len(self.media_cache)

            cache_dir = Path(self.config["cache_dir"])
            cache_dir.mkdir(parents=True, exist_ok=True)

            cached_names = {Path(p).name for p in self.media_cache}
            removed = cached_names - server_filenames
            for name in removed:
                try:
                    (cache_dir / name).unlink()
                except:
                    pass

            items = self.api.get_media_list()
            paths = []
            for item in items:
                filename     = item["filename"]
                download_url = item.get("download_url") or f"{self.api.base}/uploads/{filename}"
                ext = Path(filename).suffix.lower()
                if ext not in IMAGE_EXT and ext not in VIDEO_EXT:
                    self._fetch_warnings.append(f"ข้ามไฟล์ (ไม่รองรับ): {filename}")
                    continue
                try:
                    p = self.api.download_media(download_url, filename, cache_dir)
                    paths.append(p)
                except Exception as e:
                    self._fetch_warnings.append(f"โหลดไม่ได้: {filename} — {e}")

            self.media_cache = paths
            self._last_media_version = server_version

            if server_count > 0 and len(paths) == 0:
                tried = [item.get("download_url", "?") for item in items[:2]]
                self._fetch_error = (
                    f"server มี {server_count} รูปแต่โหลดไม่ได้เลย URL ที่ลอง: {tried}"
                )
            return len(paths)

        except Exception as e:
            self._fetch_error = str(e)
            return len(self.media_cache)

    def exit_screensaver(self):
        self._cmd_queue.put("close_screensaver")


# ─── Kivy App ─────────────────────────────────────────────────────────────────
class ScreenFlowApp(App):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.client = DisplayClient()
        self._wake_lock = None
        self.sm = None
        self.ss_screen = None

    def build(self):
        # ตั้งหน้าต่างดำ fullscreen
        Window.clearcolor = (0, 0, 0, 1)
        Window.borderless = True

        # กัน screensaver/sleep ของ Android
        self._wake_lock = acquire_wake_lock()

        # ป้องกันหน้าจอดับด้วย Kivy (fallback สำหรับ desktop ด้วย)
        try:
            Window.request_keyboard(None, None)
        except:
            pass

        self.sm = ScreenManager(transition=FadeTransition(duration=0.4))

        # Setup screen
        setup = SetupScreen(
            name="setup",
            client=self.client,
            on_done=self._start_client,
        )
        self.sm.add_widget(setup)

        # Screensaver screen
        self.ss_screen = ScreensaverScreen(name="screensaver", client=self.client)
        self.sm.add_widget(self.ss_screen)

        # ไปหน้า screensaver ตรงถ้า config มีอยู่แล้ว
        if CONFIG_FILE.exists():
            self.sm.current = "screensaver"
            self._start_client()
        else:
            self.sm.current = "setup"

        # Poll command queue
        Clock.schedule_interval(self._poll_queue, 0.2)

        # Keep-awake: ส่ง touch event จำลองทุก 30 วิ เพื่อกัน Android หรี่จอ
        Clock.schedule_interval(self._keepawake_tick, 30)

        return self.sm

    def _start_client(self):
        """เชื่อมต่อ server และเริ่ม background thread"""
        self.sm.current = "screensaver"
        t = threading.Thread(target=self._init_connect, daemon=True)
        t.start()

        # Background loop
        bg = threading.Thread(target=self._background_loop, daemon=True)
        bg.start()

    def _init_connect(self):
        try:
            self.client.fetch_settings()
            count = self.client.fetch_media()
            print(f"✓ เชื่อมต่อสำเร็จ โหลด {count} รูป")
        except Exception as e:
            print(f"✗ เชื่อมต่อล้มเหลว: {e}")

    def _background_loop(self):
        """Logic thread: fetch media, ping, check idle"""
        last_fetch = 0
        last_ping = time.time()

        while True:
            now = time.time()
            force = self.client._force_refresh.is_set()

            if force or (now - last_fetch > 5):
                if force:
                    self.client._force_refresh.clear()
                self.client.fetch_settings()
                self.client.fetch_media()
                last_fetch = now

            if now - last_ping > 10:
                self.client.api.ping(self.client.config["device_name"])
                last_ping = now

            idle_sec = self.client.idle.idle_seconds()
            timeout = self.client.settings.get(
                "idle_timeout", self.client.config.get("idle_timeout", 60)
            )

            if not self.client.screensaver_active:
                if idle_sec >= timeout and self.client.media_cache:
                    self.client.screensaver_active = True
                    self.client._cmd_queue.put("show_screensaver")

            time.sleep(1)

    def _poll_queue(self, *args):
        """Main thread: handle commands from background"""
        try:
            while True:
                cmd = self.client._cmd_queue.get_nowait()
                if cmd == "show_screensaver":
                    self._open_screensaver()
                elif cmd == "close_screensaver":
                    self._close_screensaver()
                elif cmd == "refresh_media":
                    self.client._force_refresh.set()
        except queue.Empty:
            pass

    def _open_screensaver(self):
        self.ss_screen.stop()
        self.ss_screen.show(settings=self.client.settings)
        self.sm.current = "screensaver"

    def _close_screensaver(self):
        self.ss_screen.stop()
        self.client.screensaver_active = False
        self.client.idle.reset()
        # กลับไปหน้า screensaver แต่เคลียร์ content (แสดงพื้นดำ)
        self.sm.current = "screensaver"

    def _keepawake_tick(self, *args):
        """
        กัน Android ปิดหน้าจอ — reset idle tracker และ
        ลอง keep screen on ผ่าน wake lock อีกครั้ง
        """
        try:
            if self._wake_lock is None:
                self._wake_lock = acquire_wake_lock()
        except:
            pass

    def on_stop(self):
        """ปล่อย wake lock เมื่อปิดแอป"""
        try:
            if self._wake_lock and self._wake_lock.isHeld():
                self._wake_lock.release()
                print("[WakeLock] ปล่อยแล้ว")
        except:
            pass


# ─── Entry Point ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ScreenFlowApp().run()
