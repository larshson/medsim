#!/usr/bin/env bash
# Opens the dashboard fullscreen (kiosk) on the Pi's HDMI/projector.
# Requires chromium. Run after the pump has started.
URL="http://localhost:8080/"
exec chromium-browser --kiosk --incognito --noerrdialogs \
  --disable-infobars --check-for-update-interval=31536000 "$URL" 2>/dev/null \
  || chromium --kiosk --incognito "$URL"
