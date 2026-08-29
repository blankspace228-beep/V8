#!/usr/bin/env bash
set -euo pipefail
rm -rf aegiswatch-live
mkdir -p aegiswatch-live
base64 -d aegiswatch_bundle.tar.gz.b64 | tar -xzf - -C aegiswatch-live
cd aegiswatch-live
go build -o ../aegiswatch-server .
cd ..
chmod +x aegiswatch-server
