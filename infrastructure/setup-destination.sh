#!/bin/bash
set -euo pipefail

sudo install -d -m 755 /opt/cloudlink-test
echo 'CloudLink destination is healthy' | sudo tee /opt/cloudlink-test/index.html >/dev/null

sudo tee /etc/systemd/system/cloudlink-test.service >/dev/null <<'UNIT'
[Unit]
Description=CloudLink test HTTP server
After=network.target

[Service]
User=ec2-user
ExecStart=/usr/bin/python3 -m http.server 8000 --bind 0.0.0.0 --directory /opt/cloudlink-test
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now cloudlink-test
sudo systemctl is-active cloudlink-test

curl --fail --retry 5 --retry-connrefused --retry-delay 1 http://127.0.0.1:8000/
