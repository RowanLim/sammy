"""智能家居（PRD P2-2）：**能离线做的做扎实，做不到的如实说做不到。**

为什么不搞一个"统一设备接口"：本地控制协议各家差得远，硬套一个统一接口最后只会
变成**假接口** —— 看着能调，实际不通，比没有更坏。

实测现场（Rowan 的局域网 192.168.110.0/24，2026-10-05）：

| 生态 | 本地协议 | 能不能离线控制 |
|---|---|---|
| **Yeelight** | SSDP 发现 + TCP 55443 JSON | ✅ **能** —— 开放协议，不需要账号（但设备上要先开「局域网控制」） |
| Tuya / Cozylife | TCP 6668（扫到 `192.168.110.245`） | ✗ 需要 **localKey**（从云账号里掏），3.3+ 还是 AES 加密 |
| 米家 miIO | **UDP** 54321 | ✗ 需要 **token**（同样得从云端掏） |
| 美的 | TCP 6445 / 云 | ✗ 需要云注册 |

所以本模块做三件正经事：
1. **Yeelight 全功能**（发现 / 读状态 / 开关 / 亮度 / 色温）—— 用真协议，不是模拟；
2. **局域网普查**：把网段上活着的设备列出来，并标明**每种设备还缺什么才能控制**；
3. **清楚说明"缺什么"**：需要 token/密钥的，直接告诉用户去哪儿拿 —— 不假装能用。

约定：`--home` 只**读**（发现 + 读状态）。要开关设备必须显式下命令 ——
灯突然亮了比灯调不了更吓人。
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import socket
from dataclasses import dataclass, field

# ── Yeelight：开放的局域网协议 ─────────────────────

MCAST = "239.255.255.250"
SSDP_PORT = 1982  # Yeelight 专用的发现端口
CMD_PORT = 55443  # 命令通道（TCP，一行一条 JSON）

DISCOVERY_REQUEST = "\r\n".join(
    [
        "M-SEARCH * HTTP/1.1",
        f"HOST: {MCAST}:{SSDP_PORT}",
        'MAN: "ssdp:discover"',
        "ST: wifi_bulb",
        "",
        "",
    ]
).encode()

# 各生态的"本地端口 → 还缺什么"。**这张表就是"如实报告"的依据。**
NEEDS_KEY_PORT = {
    55443: ("Yeelight", "开放协议，不需要账号（设备端要开「局域网控制」）"),
    6668: ("Tuya / Cozylife", "需要 localKey：从手机 App 的云账号里导出来才能本地控制"),
    54321: ("米家 miIO", "需要 token：得从米家云端导出（UDP 协议，TCP 探不到）"),
    6445: ("美的", "需要云注册，本地协议未公开"),
    62078: ("Apple 设备", "不是家居设备"),
    7000: ("AirPlay", "不是家居设备"),
    22: ("SSH 主机", "不是家居设备"),
    80: ("Web 界面", "多半是路由器/摄像头/NAS，看具体牌子"),
    443: ("HTTPS", "同上"),
}


@dataclass
class Bulb:
    """一台 Yeelight。字段名照协议原文（`power`/`bright`/`ct`）。"""

    ip: str
    did: str = ""
    model: str = ""
    name: str = ""
    power: str = ""
    bright: str = ""
    ct: str = ""
    rgb: str = ""
    support: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def is_on(self) -> bool:
        return self.power.lower() == "on"

    def describe(self) -> str:
        state = "开" if self.is_on else "关"
        extra = f" · 亮度 {self.bright}%" if self.bright else ""
        temp = f" · 色温 {self.ct}K" if self.ct else ""
        label = self.name or self.model or "Yeelight"
        return f"{self.ip:<16} {label}  [{state}{extra}{temp}]"


def parse_ssdp(text: str, ip: str) -> Bulb:
    """把 SSDP 回复解析成 Bulb（**纯函数**，可以拿固定样本测）。

    ⚠️ 别写成"缺字段就崩"：不同型号回的字段不一样（有的没 `name`、有的没 `rgb`），
    我们只需要其中几项，缺了就当空。
    """
    b = Bulb(ip=ip)
    for line in str(text).split("\r\n"):
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip().lower(), v.strip()
        if k == "id":
            b.did = v
        elif k == "model":
            b.model = v
        elif k == "name":
            b.name = v
        elif k == "power":
            b.power = v
        elif k == "bright":
            b.bright = v
        elif k == "ct":
            b.ct = v
        elif k == "rgb":
            b.rgb = v
        elif k == "support":
            b.support = v
    b.raw = {"text": text}
    return b


def discover(timeout: float = 4.0) -> list[Bulb]:
    """发 SSDP 找 Yeelight。找不到就是找不到（**不编造**）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    found: dict[str, Bulb] = {}
    try:
        s.sendto(DISCOVERY_REQUEST, (MCAST, SSDP_PORT))
        while True:
            try:
                data, addr = s.recvfrom(8192)
            except TimeoutError:
                break
            bulb = parse_ssdp(data.decode("utf-8", "replace"), addr[0])
            found[bulb.did or addr[0]] = bulb
    except OSError as e:
        print(f"  ⚠️ 发现失败（多播发不出去？）: {e}")
    finally:
        s.close()
    return list(found.values())


# ── Yeelight 命令（纯函数，方便测）─────────────────


def cmd(method: str, params: list, seq: int = 1) -> bytes:
    """一条命令 = 一行 JSON + `\\r\\n`（协议就是这么约定的）。"""
    return (
        json.dumps({"id": seq, "method": method, "params": params}, ensure_ascii=False) + "\r\n"
    ).encode()


def cmd_power(on: bool, seq: int = 1, smooth_ms: int = 500) -> bytes:
    """开关。带 `smooth` 渐变 —— 灯"啪"地跳亮很吓人，尤其是半夜。"""
    return cmd("set_power", ["on" if on else "off", "smooth", smooth_ms], seq)


def cmd_bright(percent: int, seq: int = 1) -> bytes:
    """亮度 1~100（协议只认这个区间，越界要夹住）。"""
    pct = max(1, min(100, int(percent)))
    return cmd("set_bright", [pct, "smooth", 500], seq)


def cmd_temp(kelvin: int, seq: int = 1) -> bytes:
    """色温 1700~6500K（同样夹住 —— 超范围设备会回 error）。"""
    k = max(1700, min(6500, int(kelvin)))
    return cmd("set_ct_abx", [k, "smooth", 500], seq)


def cmd_state(seq: int = 1) -> bytes:
    return cmd("get_prop", ["power", "bright", "ct", "rgb", "name"], seq)


def parse_reply(line: str) -> tuple[bool, object]:
    """解析一行回复 → `(成功?, 结果或错误说明)`。

    设备可能**每一行都是完整 JSON**（粘包由调用方按行切开）。
    出错时它回 `{"error": {"code": -1, "message": "..."}}` —— 这个要往上抛，
    不能当成"成功了但结果为空"。
    """
    try:
        data = json.loads(str(line).strip())
    except json.JSONDecodeError:
        return False, "回复不是 JSON"
    if not isinstance(data, dict):
        return False, "回复不是对象"
    if "error" in data:
        err = data["error"] or {}
        return False, f"设备报错 {err.get('code')}: {err.get('message')}"
    if "result" in data:
        res = data["result"]
        return True, res[0] if isinstance(res, list) and len(res) == 1 else res
    return False, "回复里既没有 result 也没有 error"


class Yeelight:
    """一盏灯的连接（一次性短连接，用完就关 —— 长期挂着反而容易僵）。"""

    def __init__(self, ip: str, port: int = CMD_PORT, timeout: float = 3.0) -> None:
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self._seq = 0

    def _next(self) -> int:
        self._seq += 1
        return self._seq

    def send(self, payload: bytes) -> tuple[bool, object]:
        """发一条、读一行回复。连不上就返回失败（**不抛异常**）。"""
        try:
            with socket.create_connection((self.ip, self.port), timeout=self.timeout) as s:
                s.settimeout(self.timeout)
                s.sendall(payload)
                buf = b""
                while b"\r\n" not in buf:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                    if len(buf) > 65536:
                        break
        except OSError as e:
            return False, f"连不上 {self.ip}:{self.port}（{e.__class__.__name__}）"
        line = buf.decode("utf-8", "replace").split("\r\n")[0]
        return parse_reply(line)

    def state(self) -> tuple[bool, object]:
        return self.send(cmd_state(self._next()))

    def set_power(self, on: bool) -> tuple[bool, object]:
        return self.send(cmd_power(on, self._next()))

    def set_bright(self, percent: int) -> tuple[bool, object]:
        return self.send(cmd_bright(percent, self._next()))

    def set_temp(self, kelvin: int) -> tuple[bool, object]:
        return self.send(cmd_temp(kelvin, self._next()))


# ── 局域网普查（不依赖多播；能连上就算活着）───────


def port_open(ip: str, port: int, timeout: float = 0.35) -> bool:
    with socket.socket() as s:
        s.settimeout(timeout)
        try:
            return s.connect_ex((ip, port)) == 0
        except OSError:
            return False


def scan(
    subnet: str = "192.168.110.",
    ports: tuple[int, ...] | None = None,
    timeout: float = 0.35,
    workers: int = 64,
) -> dict[str, list[int]]:
    """扫一段网段，返回 `{ip: [开着的端口]}`。

    为什么用 TCP connect 而不是 ping：ping 会被防火墙挡掉，
    而"某个端口连得上"是**服务真的在**的证据。
    """
    ports = ports or (80, 443, 22, 55443, 6668, 54321, 6445)
    out: dict[str, list[int]] = {}

    def probe(ip: str) -> list[int]:
        return [p for p in ports if port_open(ip, p, timeout)]

    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(probe, f"{subnet}{i}"): f"{subnet}{i}" for i in range(1, 255)}
        for fut in cf.as_completed(futures):
            ip = futures[fut]
            try:
                open_ports = fut.result()
            except Exception:
                continue
            if open_ports:
                out[ip] = sorted(open_ports)
    return out


def describe_host(ip: str, ports: list[int]) -> str:
    """一台主机 → 一行说明（含"要控制它还缺什么"）。"""
    parts = []
    for p in ports:
        name, need = NEEDS_KEY_PORT.get(p, (f"端口 {p}", "协议未知"))
        parts.append(f"{name}｜{need}")
    return f"  {ip:<16} " + "；".join(parts)


__all__ = [
    "CMD_PORT",
    "Bulb",
    "Yeelight",
    "cmd",
    "cmd_bright",
    "cmd_power",
    "cmd_state",
    "cmd_temp",
    "describe_host",
    "discover",
    "parse_reply",
    "parse_ssdp",
    "port_open",
    "scan",
]
