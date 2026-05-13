[app]

# ชื่อแอป
title = ScreenFlow Display Client

# ชื่อ package
package.name = screenflow
package.domain = org.screenflow

# ไฟล์หลัก (ต้องชื่อ main.py)
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json

# เวอร์ชัน
version = 1.0.0

# dependencies ทั้งหมด
requirements = python3,kivy==2.3.0,requests,pillow,certifi,urllib3,charset-normalizer,idna,ffpyplayer

# orientation: landscape สำหรับแท็บเล็ต (เปลี่ยนเป็น portrait ถ้าต้องการ)
orientation = landscape

# fullscreen
fullscreen = 1

# Android permissions ที่ต้องการ
android.permissions = INTERNET,WAKE_LOCK,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE,RECEIVE_BOOT_COMPLETED

# Wake lock เพื่อกันหน้าจอดับ
android.wakelock = True

# API level
android.minapi = 21
android.api = 33
android.ndk = 25b

# Architecture (ครอบคลุมแท็บเล็ตส่วนใหญ่)
android.archs = arm64-v8a, armeabi-v7a

# ไม่แสดง title bar
android.window_softinput_mode = adjustPan

# icon (ใส่ไฟล์ icon.png ไว้ใน folder เดียวกับ main.py)
# icon.filename = %(source.dir)s/icon.png

[buildozer]
log_level = 2
warn_on_root = 1
