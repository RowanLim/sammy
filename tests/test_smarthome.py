"""智能家居：协议构造、回复解析、"缺什么"的如实报告。

为什么这些要测：这部分全是**和硬件/网络打交道**的代码，出错的形态很讨厌 ——
- 命令拼错 → 设备回 error，但界面看起来"发了"；
- 回复解析太乐观 → 把 `{"error":...}` 当成成功；
- 端口认错 → 对着一个 Tuya 设备喊 Yeelight 命令，然后报"设备没反应"。
所以协议这一层要能用固定样本测，不依赖现场有没有设备。
"""

from __future__ import annotations

import json
import pathlib
import socket
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from sammy import smarthome as sh

SSDP_SAMPLE = "\r\n".join(
    [
        "HTTP/1.1 200 OK",
        "Cache-Control: max-age=3600",
        "Location: yeelight://192.168.110.30:55443",
        "Server: POSIX UPnP/1.0 YGLC/1",
        "id: 0x0000000012345678",
        "model: color",
        "fw_ver: 45",
        "support: get_prop set_default set_power toggle",
        "power: on",
        "bright: 60",
        "ct: 4000",
        "rgb: 16711680",
        "name: 客厅灯",
        "",
    ]
)


# ── SSDP 解析 ─────────────────────────────────────


def test_parse_ssdp_reads_the_fields_we_need():
    b = sh.parse_ssdp(SSDP_SAMPLE, "192.168.110.30")
    assert b.ip == "192.168.110.30"
    assert b.did == "0x0000000012345678"
    assert b.model == "color"
    assert b.name == "客厅灯"
    assert b.is_on and b.bright == "60" and b.ct == "4000"


def test_parse_ssdp_tolerates_missing_fields():
    """不同型号回的字段不一样 —— 缺字段不能崩，也不能当成"设备坏了"。"""
    b = sh.parse_ssdp("HTTP/1.1 200 OK\r\nid: x\r\npower: off\r\n", "10.0.0.5")
    assert b.did == "x" and not b.is_on
    assert b.name == "" and b.bright == ""


def test_describe_shows_state():
    b = sh.parse_ssdp(SSDP_SAMPLE, "192.168.110.30")
    out = b.describe()
    assert "客厅灯" in out and "开" in out and "60%" in out


# ── 命令构造 ──────────────────────────────────────


def test_commands_are_one_json_line_each():
    for payload in (sh.cmd_power(True), sh.cmd_bright(50), sh.cmd_temp(4000), sh.cmd_state()):
        assert payload.endswith(b"\r\n")
        obj = json.loads(payload.decode())
        assert obj["method"] and isinstance(obj["params"], list) and obj["id"]


def test_power_command_uses_a_smooth_transition():
    """渐变是**必须的**：灯"啪"地跳亮很吓人，尤其半夜。"""
    params = json.loads(sh.cmd_power(True).decode())["params"]
    assert params[0] == "on" and "smooth" in params


def test_brightness_is_clamped_to_the_protocol_range():
    """协议只认 1~100，越界设备会回 error —— 与其发出去被拒，不如夹住。"""
    assert json.loads(sh.cmd_bright(0).decode())["params"][0] == 1
    assert json.loads(sh.cmd_bright(150).decode())["params"][0] == 100
    assert json.loads(sh.cmd_bright(42).decode())["params"][0] == 42


def test_color_temp_is_clamped():
    assert json.loads(sh.cmd_temp(1000).decode())["params"][0] == 1700
    assert json.loads(sh.cmd_temp(9000).decode())["params"][0] == 6500


# ── 回复解析 ──────────────────────────────────────


def test_reply_with_single_result_returns_the_value():
    ok, val = sh.parse_reply('{"id":1,"result":["ok"]}')
    assert ok and val == "ok"


def test_reply_with_many_results_returns_the_list():
    """get_prop 回的是数组（power/bright/ct/rgb/name）—— 不能只取第一个。"""
    ok, val = sh.parse_reply('{"id":2,"result":["on","60","4000","16711680","客厅灯"]}')
    assert ok and val == ["on", "60", "4000", "16711680", "客厅灯"]


def test_device_error_is_not_treated_as_success():
    """`{"error":...}` **绝不能被当成成功** —— 那样界面会显示"已打开"而灯没动。"""
    ok, msg = sh.parse_reply('{"id":1,"error":{"code":-5000,"message":"general error"}}')
    assert not ok and "-5000" in str(msg)


def test_garbage_reply_is_a_failure_not_a_crash():
    for line in ("", "not json", "[]", "{}", "null"):
        ok, msg = sh.parse_reply(line)
        assert not ok and msg


def test_sending_to_a_dead_host_fails_gracefully():
    """连不上要返回失败，**不抛异常** —— 一个设备掉线不该让整个语音助手崩。"""
    ok, msg = sh.Yeelight("127.0.0.1", port=1, timeout=0.5).state()
    assert not ok and "连不上" in str(msg)


# ── 发现（用假 socket，不依赖现场有没有灯）──────────


class FakeSock:
    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []

    def settimeout(self, *_):
        pass

    def setsockopt(self, *_):
        pass

    def sendto(self, data, _addr):
        self.sent.append(data)

    def recvfrom(self, _n):
        if not self.replies:
            raise TimeoutError
        return self.replies.pop(0)

    def close(self):
        pass


def test_discover_parses_replies_and_dedupes(monkeypatch):
    fake = FakeSock([(SSDP_SAMPLE.encode(), ("192.168.110.30", 1982))] * 2)
    monkeypatch.setattr(socket, "socket", lambda *a, **k: fake)
    bulbs = sh.discover(timeout=0.1)
    assert len(bulbs) == 1, "同一盏灯回两次只算一台"
    assert bulbs[0].name == "客厅灯"
    assert any(b"wifi_bulb" in s for s in fake.sent), "发出去的不是 Yeelight 的查询包"


def test_discover_with_nothing_found_is_empty_not_an_error(monkeypatch):
    fake = FakeSock([])
    monkeypatch.setattr(socket, "socket", lambda *a, **k: fake)
    assert sh.discover(timeout=0.1) == []


# ── 网段普查与"缺什么" ─────────────────────────────


def test_scan_reports_only_hosts_with_open_ports(monkeypatch):
    monkeypatch.setattr(sh, "port_open", lambda ip, port, timeout=0.35: ip.endswith(".7"))
    found = sh.scan("10.0.0.", ports=(80,), timeout=0.01)
    assert list(found) == ["10.0.0.7"]


def test_every_probed_port_has_an_explanation():
    """扫到的端口必须都能解释"这是什么、还缺什么" —— 否则用户看到的是"端口 6668"。
    （这条是防"新加了端口忘了加说明"）"""
    for port in (80, 443, 22, 55443, 6668, 54321, 6445, 62078, 7000):
        assert port in sh.NEEDS_KEY_PORT


def test_tuya_device_is_reported_as_needing_a_key():
    """Tuya/Cozylife 要如实说"需要 localKey"，不能含糊成"暂不支持"。"""
    text = sh.describe_host("192.168.110.245", [6668])
    assert "localKey" in text and "Tuya" in text


def test_yeelight_is_reported_as_not_needing_an_account():
    text = sh.describe_host("192.168.110.30", [55443])
    assert "不需要账号" in text


@pytest.mark.parametrize("port", [54321, 6445])
def test_devices_that_need_cloud_credentials_say_so(port):
    text = sh.describe_host("10.0.0.9", [port])
    assert "需要" in text, "得说清楚缺什么，不能只说'不支持'"
