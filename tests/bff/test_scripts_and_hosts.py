"""The start and stop scripts (static checks: they are PowerShell, not run here) and the Host-header rule the scripts configure."""
from __future__ import annotations

import re
from dataclasses import replace

import pytest
from conftest import AUTH, REPO, make_client

START = (REPO / "bff" / "start_bff.ps1").read_text(encoding="utf-8")
STOP = (REPO / "bff" / "stop_bff.ps1").read_text(encoding="utf-8")

TS_IP, TS_NAME = "100.125.195.111", "laptop.tail0118ce.ts.net"


def test_start_script_binds_only_to_the_tailscale_address():
    assert "0.0.0.0" not in START
    assert "$env:STOCKBOT_BFF_HOST          = $ip" in START
    assert "tailscale.exe" in START and "ip -4" in START and "status --json" in START
    # the address must be inside the Tailscale range 100.64.0.0/10 or the script refuses
    assert "REFUSED: Tailscale has no IPv4 address" in START
    pattern = re.search(r"-notmatch '(\^100[^']+)'", START).group(1)
    assert re.match(pattern, "100.125.195.111") and re.match(pattern, "100.64.0.1") and re.match(pattern, "100.127.255.255")
    assert not re.match(pattern, "100.63.0.1") and not re.match(pattern, "100.128.0.1") and not re.match(pattern, "192.168.1.5") and not re.match(pattern, "0.0.0.0")


def test_start_script_allows_exactly_the_documented_hosts():
    assert "$hosts = @($ip)" in START and "$hosts += $dns" in START and "'localhost', '127.0.0.1'" in START
    assert "STOCKBOT_BFF_ALLOWED_HOSTS" in START


def test_start_script_runs_run_py_detached_minimized_from_the_main_folder_and_refuses_a_second_copy():
    assert r"C:\Users\ravit\AppData\Local\Programs\Python\Python313\python.exe" in START
    assert "-WindowStyle Minimized" in START and "-WorkingDirectory $repo" in START and "'bff\\run.py'" in START
    assert "REFUSED: the BFF is already running" in START and "exit 2" in START
    assert "REFUSED: port" in START


def test_scripts_never_read_print_or_set_the_token():
    for text in (START, STOP):
        assert "token.txt" not in text.replace("F:\\Projects\\Ravi\\StockBotData\\bff\\token.txt", "")      # only a mention in the header comment
        assert not re.search(r"Get-Content[^\n]*token", text, re.I)
        assert "STOCKBOT_BFF_TOKEN" not in text.replace("STOCKBOT_BFF_TOKEN or", "")
        assert not re.search(r"Write-(Output|Host)[^\n]*\$(env:STOCKBOT_BFF_TOKEN|token)", text, re.I)


def test_stop_script_stops_only_the_bff_process():
    assert "bff\\\\run\\.py" in STOP
    assert STOP.count("Stop-Process") == 1 and "Stop-Process -Id $p.ProcessId" in STOP
    assert "scheduler" not in STOP.lower().replace("not the scheduler service", "")


@pytest.fixture
def tailscale_client(worlds):
    w = worlds["empty"]
    hosts = (TS_IP, TS_NAME, "localhost", "127.0.0.1")
    return make_client(type(w)(**{**w.__dict__, "settings": replace(w.settings, allowed_hosts=hosts)}))


@pytest.mark.parametrize("host", [TS_IP, f"{TS_IP}:8765", TS_NAME, f"{TS_NAME}:8765", "localhost", "127.0.0.1:8765"])
def test_the_configured_hosts_are_accepted(tailscale_client, host):
    assert tailscale_client.get("/v1/health", headers={**AUTH, "Host": host}).status_code == 200


@pytest.mark.parametrize("host", ["evil.example", "100.125.195.112", "other.tail0118ce.ts.net", "192.168.1.20:8765"])
def test_other_hosts_are_refused(tailscale_client, host):
    assert tailscale_client.get("/v1/health", headers={**AUTH, "Host": host}).status_code == 400
