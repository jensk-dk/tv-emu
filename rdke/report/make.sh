#!/bin/sh
# Makes rdke/rdke-report.pdf from report.html and its four pictures, with a
# Chrome or Chromium of the host. Nothing else reads these files.
set -e
cd "$(dirname "$0")"
for chrome in "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
              google-chrome chromium chromium-browser; do
    if command -v "$chrome" >/dev/null 2>&1; then
        "$chrome" --headless --disable-gpu --no-pdf-header-footer \
            --print-to-pdf="$PWD/../rdke-report.pdf" "$PWD/report.html"
        exit 0
    fi
done
echo "make.sh: no Chrome or Chromium found on this host" >&2
exit 1
