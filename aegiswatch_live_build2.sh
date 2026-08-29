#!/usr/bin/env bash
set -euo pipefail
cd aegiswatch-live-app
go build -o ../aegiswatch-server .
cd ..
chmod +x aegiswatch-server
