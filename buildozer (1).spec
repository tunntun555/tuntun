[app]

title = ScreenFlow Display Client
package.name = screenflow
package.domain = org.screenflow

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json

version = 1.0.0

# ตัด ffpyplayer ออก — avfft.h ถูกลบใน ffmpeg ใหม่
requirements = python3,kivy==2.3.0,requests,pillow,certifi,urllib3,charset-normalizer,idna

orientation = landscape
fullscreen = 1

android.permissions = INTERNET,WAKE_LOCK,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE
android.wakelock = True

android.minapi = 21
android.api = 33
android.ndk = 25b
android.archs = arm64-v8a, armeabi-v7a

android.window_softinput_mode = adjustPan

[buildozer]
log_level = 2
warn_on_root = 1
