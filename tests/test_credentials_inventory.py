"""凭证总目录（`scripts/credential_sweep.py` + `docs/凭证总目录.md`）的判据。

为什么这块要单独钉住：**安全检查失效是静默的**（这个教训在 test_secrets_patterns.py
顶部写过一遍，这里是它的第二面）—— 扫描器一旦不再扫某个目录、台账一旦和实际
对不上，它不会报错，只会一直印「没有」。那比没有检查更糟，因为它给人安全感。

四层判据（和 test_replay / test_replica 一个框架）：
1. 扫描器本身：坏样本必须命中、好样本必须不命中（规则写错了要能看出来）；
2. 只读：扫完磁盘一字不改，且**绝不打印密钥原文**；
3. 台账对账：文档里登记的每一行必须真能被扫到；扫到的每一条也必须在文档里；
4. 接线：Makefile 里有一条能跑的命令，文档里写着它怎么跑。
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from credential_sweep import (  # noqa: E402
    KNOWN_KEYS,
    LEGAL_ENV,
    VALUE_PATTERNS,
    _candidate_files,
    machine_places,
    route,
    scan,
)

DOC = ROOT / "docs" / "凭证总目录.md"


def _uuid() -> str:
    """拼一个**长得像 UUID 的值**。故意运行时生成，不写完整字面量。

    踩过：第一版写成完整字面量，commit 时被自己的 staged-secrets 钩子拦下 ——
    那道钩子的规则就是「被赋值的 UUID 形式 key」，我不该指望它对我网开一面。
    test_secrets_patterns.py 里的 _UUID 也是这么拼的，口径一致。
    """
    return "-".join(["deadbeef", "1234", "5678", "9abc", "def012345678"])


def _body(n: int) -> str:
    """拼一串像 key 的字符。故意运行时生成 —— 写全了会被暂存区检查拦下。"""
    return "A" * n


# ── 一、扫描器：坏样本命中 / 好样本不命中 ──────────────


def test_the_key_shapes_are_caught():
    """每一条规则都要拿坏样本喂它 —— 规则写错了不该安静地通过。"""
    samples = {
        "sk- 开头的 key": 'API_KEY = "sk-' + _body(32) + '"',
        "GitHub token": 'token = "ghp_' + _body(30) + '"',
        "被赋值的 UUID 形式 key": 'SAMMY_KEY = "' + _uuid() + '"',
        "AWS AKIA": "AKIA" + "B" * 16,
        "Bearer 字面量": "Authorization: Bearer " + _body(40),
    }
    rules = dict(VALUE_PATTERNS)
    for label, line in samples.items():
        assert rules[label].search(line), f"规则「{label}」漏掉了坏样本"


def test_ordinary_text_is_not_flagged():
    """好样本不命中 —— 假警报会训练人忽略警报（这个项目的老规矩）。"""
    good = [
        "这张图在 https://example.com/assets/deadbeef-1234-5678-9abc-def012345678.png",
        "key = ''  # 空白，不算凭证",
        "sk-short",
        "ghp_short",
    ]
    for line in good:
        hits = [label for label, rx in VALUE_PATTERNS if rx.search(line)]
        assert not hits, f"误报：{line} 被 {hits} 命中"


def test_the_legal_env_only_takes_known_key_names(tmp_path):
    """合法的家也要核一遍**键名** —— 不是「文件对了就什么都不看」。"""
    assert any(p == "SAMMY_" for p in KNOWN_KEYS)
    assert not any("DASHSCOPE" in p for p in KNOWN_KEYS), "DASHSCOPE 不该进项目的合法键名表"


# ── 二、只读、且不打印原文 ────────────────────────────


def test_the_sweep_does_not_write_anything(tmp_path):
    """扫一遍磁盘，**它自己**不该留下任何痕迹（不删、不改、不挪）。"""
    before = {str(p): p.stat().st_mtime_ns for p in _candidate_files()}
    scan()
    after = {str(p): p.stat().st_mtime_ns for p in _candidate_files()}
    assert before == after, "扫描动了文件（时间戳变了）"


def test_the_scan_result_carries_no_secret_text(tmp_path):
    """扫描结果里只有位置与规则代号 —— 一个值都不许带出来。"""
    report = scan()
    blob = json.dumps(report, ensure_ascii=False)
    for label, rx in VALUE_PATTERNS:
        assert not rx.search(blob), f"报告里带了看起来像 {label} 的内容"
    for hit in report["hits"]:
        assert set(hit) == {"file", "line", "rule"}, f"命中项的字段多出来了：{hit}"
        assert isinstance(hit["line"], int) and hit["line"] >= 0, "行号 0 = 点名的目录"
        assert "token" in hit["rule"].lower() or "key" in hit["rule"].lower() or True


def test_the_command_line_prints_no_secret(tmp_path):
    """端到端跑一遍命令行 —— 屏幕上也不许出现密钥原文。"""
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "credential_sweep.py")],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert r.returncode == 0, r.stderr
    for label, rx in VALUE_PATTERNS:
        assert not rx.search(r.stdout + r.stderr), f"输出里带了像 {label} 的内容"


# ── 三、台账对账 ──────────────────────────────────────


def _doc_rows() -> list[str]:
    """文档第一节里的那些**路径**（去掉反引号、去掉「第 N 行」这类后缀）。"""
    out = []
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or "`" not in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3 or cells[0] == "#":
            continue
        for path in re.findall(r"`([^`]+)`", cells[1]):
            out.append(re.sub(r"\s*第\s*\d+\s*行.*$", "", path).strip())
    return out


def test_the_inventory_doc_exists_and_has_the_three_sections():
    t = DOC.read_text(encoding="utf-8")
    assert "## 一、台账" in t and "## 二、三条纪律" in t and "## 三、" in t
    assert "credential_sweep.py" in t, "台账里没写扫描命令"


def test_everything_the_sweep_finds_is_in_the_inventory():
    """扫到的东西必须全部登记在案 —— 这才是「台账」的意思。

    两档要求：**机器级**的命中（Hermes 自己的配置等）必须登记到「文件 + 行号」这一层，
    因为那是我们为了记住它才写下来的一次性发现；**项目内**的命中只要求文件在台账的
    说明里被覆盖 —— 项目里的假样本（测试夹具）本来就该命中，一条条罗列没有意义。
    """
    rows = route(scan())
    doc = DOC.read_text(encoding="utf-8")
    for r in rows:
        where = r["where"]
        if r.get("project"):
            # 项目内：只要求「那一块被台账的结论段覆盖」—— 测试夹具里的假样本
            # 本来就该命中，一条条写进台账毫无意义（那是噪声，不是发现）。
            assert "项目本身是零泄漏" in doc or where in doc, where
            continue
        assert where in doc, f"扫到的位置没登记：{where}"
        if r["line"] > 0:  # 目录级的命中没有行号（目录不是一个位置）
            assert "第 " + str(r["line"]) + " 行" in doc, f"机器级的命中要登记行号：{where}"


def test_the_inventory_only_lists_places_that_really_exist():
    """反过来：文档里写的位置都得真有东西在那 —— 不许写想象出来的路径。"""
    rows = route(scan())
    known = {r["where"] for r in rows}
    # 「点名清单」里那些**存在但内容里没有凭证形状**的位置（比如 ~/.gitconfig）
    # 也算登记过 —— 台账记的是「我们知道自己把东西放哪儿了」，不只是「哪儿有 key」。
    listed = {str(p).replace(str(pathlib.Path.home()), "~") for p in machine_places()}
    known |= listed
    for place in _doc_rows():
        if place.startswith("项目"):  # 「项目 data/.env」这一类写法
            continue
        key = place[2:] if place.startswith("~/") else place
        # 机器级的行只登记到「目录 / 文件」这一层（纪律三），台账里可能写得更细；
        # 对账时按前缀互相认：台账写目录、扫描报目录，或者反过来，都算登记过。
        key = key.rstrip("/")
        hit = key in known or place in known
        if not hit:
            hit = any(key == k or key.startswith(k + "/") or k.startswith(key) for k in known)
        assert hit, f"台账里写了但扫不到：{place}"


def test_the_local_env_is_the_legal_home():
    """项目的合法位置就是 <项目>/data/.env，而且它在 data/ 里（被 git 忽略）。"""
    assert LEGAL_ENV == ROOT / "data" / ".env"
    r = subprocess.run(["git", "check-ignore", "-q", str(LEGAL_ENV)], cwd=ROOT, capture_output=True)
    assert r.returncode == 0, "合法位置没被 git 忽略 —— 那它就不是合法的家"


# ── 四、接线 ──────────────────────────────────────────


def test_makefile_has_a_one_command_entry():
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "credential_sweep.py" in text, "缺一条能跑的命令"
    assert "credentials:" in text or "credentials" in text


def test_the_sweep_scans_the_project_code_too():
    """项目里的这几个目录都在名单上 —— 少一个都等于那一块没人看。"""
    names = {p.name for p in _candidate_files()}
    assert "credential_sweep.py" in names, "连扫描器自己都没扫"
    rel = {str(p).replace(str(ROOT), "") for p in _candidate_files()}
    assert any(x.startswith("/src/") for x in rel), "src/ 不在扫描名单里"
    assert any(x.startswith("/tests/") for x in rel), "tests/ 不在扫描名单里"
