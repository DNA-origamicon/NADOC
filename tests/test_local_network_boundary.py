"""Launchers stay local unless the operator explicitly chooses LAN or Tailscale.

NADOC's backend can browse host directories, create folders, launch local/remote
simulations, and use configured cloud credentials.  CORS is not authentication, so
the binding address is the security boundary for this single-user application.
"""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_combined_launcher_defaults_to_loopback_and_requires_explicit_lan_flag():
    script = (ROOT / "start.sh").read_text()
    assert 'BACKEND_HOST="127.0.0.1"' in script
    assert 'FRONTEND_HOST="127.0.0.1"' in script
    assert '--lan) BACKEND_HOST="0.0.0.0"; FRONTEND_HOST="0.0.0.0"' in script
    assert '--tailscale) TAILSCALE_MODE=1' in script
    assert 'elif have tailscale.exe' in script
    assert 'TAILSCALE_IP="$("${TAILSCALE_CMD[@]}" ip -4' in script
    assert '["Self"]["DNSName"]' in script
    assert 'PUBLIC_URL="https://${TAILSCALE_DNS_NAME}:5173"' in script
    assert 'serve --bg --https=5173 http://127.0.0.1:5173' in script
    assert 'serve --https=5173 off' in script
    assert 'FRONTEND_HOST="$TAILSCALE_IP"' not in script
    assert '--host "$BACKEND_HOST" --port 8000' in script
    assert 'npm run dev -- --host "$FRONTEND_HOST"' in script
    assert "NADOC has no user authentication" in script
    assert 'export NADOC_PEER_TOKEN=' in script


def test_separate_development_servers_are_loopback_only():
    justfile = (ROOT / "justfile").read_text()
    dev = re.search(r"(?m)^dev:\n(?P<body>(?:    .*\n)+)", justfile).group("body")
    frontend = re.search(
        r"(?m)^frontend:\n(?P<body>(?:    .*\n)+)", justfile
    ).group("body")
    assert "--host 127.0.0.1" in dev
    assert "--host 0.0.0.0" not in dev
    assert "--host 127.0.0.1" in frontend
    assert "--host 0.0.0.0" not in frontend


def test_vite_accepts_only_tailnet_dns_hosts_for_remote_serve():
    config = (ROOT / "frontend" / "vite.config.js").read_text()
    assert "allowedHosts: ['.ts.net']" in config
    assert "allowedHosts: true" not in config
