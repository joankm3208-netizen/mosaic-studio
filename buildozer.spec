[app]
title = Mosaic Studio
package.name = mosaicstudio
package.domain = org.mosaic
source.dir = .
source.include_exts = py,png
version = 9.0
requirements = python3,kivy==2.3.0,pillow,pyjnius,android
orientation = portrait
fullscreen = 0
icon.filename = %(source.dir)s/icon.png
presplash.filename = %(source.dir)s/presplash.png
android.presplash_color = #0E1015
android.permissions = READ_MEDIA_IMAGES,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE
android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a
android.accept_sdk_license = True
p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 1
