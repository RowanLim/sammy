"""工具层 —— 联网思考的底座。

这里最要紧的两条：**工具失败必须是返回值而不是异常**、**抓网页不能抓进内网**。
"""

import pytest

from sammy import tools

# ── schema ────────────────────────────────────────


def test_schemas_are_valid_function_calling_shape():
    for schema in tools.schemas():
        assert schema["type"] == "function"
        fn = schema["function"]
        assert fn["name"] and isinstance(fn["description"], str)
        params = fn["parameters"]
        assert params["type"] == "object"
        assert isinstance(params.get("properties", {}), dict)
        assert isinstance(params.get("required", []), list)
        # required 里提到的字段必须在 properties 里声明
        for key in params.get("required", []):
            assert key in params["properties"], f"{fn['name']} 的 required 里有未声明的 {key}"


def test_schemas_can_be_filtered():
    only = tools.schemas(["web_search"])
    assert len(only) == 1
    assert only[0]["function"]["name"] == "web_search"
    assert tools.schemas(["没有这个工具"]) == []


# ── 调用层：永不抛异常 ────────────────────────────


def test_unknown_tool_returns_string_not_raise():
    out = tools.call("不存在的工具", {})
    assert isinstance(out, str)
    assert "没有叫" in out


def test_bad_json_arguments_return_string():
    out = tools.call("web_search", "{这不是 json")
    assert isinstance(out, str)
    assert "JSON" in out


def test_arguments_string_is_parsed():
    out = tools.call("current_time", "{}")
    assert "现在是" in out


def test_non_dict_arguments_return_string():
    out = tools.call("web_search", "[]")
    assert isinstance(out, str)
    assert "格式不对" in out


def test_tool_exception_becomes_string(monkeypatch):
    """工具内部炸了也要变成一句话返回 —— 否则整个对话会被一个工具炸掉。"""

    def boom(_):
        raise RuntimeError("我炸了")

    monkeypatch.setitem(
        tools.REGISTRY, "boom", tools.Tool("boom", "测试", {"type": "object"}, boom)
    )
    out = tools.call("boom", {})
    assert isinstance(out, str)
    assert "我炸了" in out


# ── 具体工具 ──────────────────────────────────────


def test_current_time_mentions_date_and_weekday():
    out = tools.current_time({})
    assert "现在是" in out
    assert "星期" in out


def test_web_search_empty_query():
    assert "空的" in tools.web_search({"query": "  "})


def test_fetch_url_empty():
    assert "空的" in tools.fetch_url({"url": ""})


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",  # 协议不在白名单
        "http://localhost:8080/",  # 回环
        "http://127.0.0.1/",  # 回环 IP
        "http://192.168.110.1/",  # 内网
        "http://169.254.169.254/",  # 云元数据（最经典的 SSRF 目标）
        "not-a-url",
    ],
)
def test_fetch_url_blocked_targets(url):
    """SSRF 护栏：Sammy 能上公网，但不该变成扫你局域网的工具。"""
    out = tools.fetch_url({"url": url})
    assert "抓取失败" in out or "空的" in out


def test_host_is_public_rejects_private():
    ok, why = tools._host_is_public("127.0.0.1")
    assert not ok and "非公网" in why

    ok, why = tools._host_is_public("localhost")
    assert not ok

    ok, _ = tools._host_is_public("example.com")
    assert ok


# ── HTML 处理 ─────────────────────────────────────


def test_html_to_text_strips_scripts_and_tags():
    raw = """
    <html><head><style>p{color:red}</style>
    <script>alert('xss')</script></head>
    <body><h1>标题</h1><p>第一段</p><p>第二段 &amp; 符号</p>
    <!-- 注释 --></body></html>
    """
    text = tools.html_to_text(raw)
    assert "标题" in text and "第一段" in text and "第二段" in text
    assert "alert" not in text
    assert "color:red" not in text
    assert "注释" not in text
    assert "&amp;" not in text  # 实体要被解码
    assert "&" in text


def test_html_to_text_collapses_whitespace():
    assert tools.html_to_text("<p>a</p>\n\n\n\n<p>b</p>") == "a\nb"


def test_parse_ddg_extracts_hits():
    """用真实结构的片段做夹具 —— 解析器是靠正则活的，必须钉住。"""
    fixture = """
    <div class="result">
      <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fnews&amp;rut=abc">示例新闻 &amp; 标题</a>
      <a class="result__snippet" href="x">这是<strong>摘要</strong>内容</a>
    </div>
    <div class="result">
      <a class="result__a" href="https://second.example.org/page">第二条</a>
      <a class="result__snippet" href="y">第二条摘要</a>
    </div>
    """
    hits = tools.parse_ddg(fixture, limit=5)
    assert len(hits) == 2
    assert hits[0]["title"] == "示例新闻 & 标题"
    assert hits[0]["url"] == "https://example.com/news"  # 跳转链接被还原
    assert "摘要" in hits[0]["snippet"]
    assert hits[1]["url"] == "https://second.example.org/page"


def test_parse_ddg_respects_limit():
    block = (
        '<a class="result__a" href="https://x.com/%d">t</a>'
        '<a class="result__snippet" href="s">s</a>'
    )
    fixture = "".join(block % i for i in range(10))
    assert len(tools.parse_ddg(fixture, limit=3)) == 3


def test_parse_ddg_on_garbage_returns_empty():
    assert tools.parse_ddg("这不是搜索结果页") == []


def test_clean_ddg_url_passthrough():
    assert tools._clean_ddg_url("https://a.com/b") == "https://a.com/b"
    assert tools._clean_ddg_url("//a.com/b") == "https://a.com/b"


# ── 工具循环（用假的 HTTP 层） ────────────────────


class FakeBrain:
    """复用真实的 SammyBrain 逻辑，只把网络出口换掉。"""

    def __init__(self, replies):
        from sammy.brain import SammyBrain

        self.brain = SammyBrain.__new__(SammyBrain)  # 跳过 __init__，不要凭证
        self.brain.model = "fake"
        self.brain.base_url = "https://fake"
        self.brain.thinking = "off"
        self.brain.use_tools = True
        self.brain.timeout = 5
        self.brain.history_turns = 6
        self.brain.history = []
        self._replies = list(replies)
        self.sent_tools = []

    def install(self, monkeypatch):
        def fake_post(messages, temperature=0.8, tools=None):
            self.sent_tools.append(tools)
            if not self._replies:
                return {"content": "normal\n没话说了"}
            # 支持按顺序返回，并顺便验证回灌的消息结构
            return self._replies.pop(0)

        monkeypatch.setattr(self.brain, "_post_message", fake_post)


def test_tool_loop_executes_and_feeds_back(monkeypatch):
    fake = FakeBrain(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "current_time", "arguments": "{}"},
                    },
                ],
            },
            {"content": "thinking\n今天是几号我查到了"},
        ]
    )
    fake.install(monkeypatch)

    seen = []
    text, used = fake.brain._run_tools(
        [{"role": "user", "content": "今天几号"}], on_event=seen.append
    )
    assert used == ["current_time"]
    assert seen == ["current_time"], "界面要靠这个回调显示'正在联网'"
    assert "查到了" in text


def test_tool_loop_stops_when_model_answers(monkeypatch):
    fake = FakeBrain([{"content": "happy\n不用工具也能答"}])
    fake.install(monkeypatch)
    text, used = fake.brain._run_tools([{"role": "user", "content": "hi"}])
    assert used == []
    assert "不用工具" in text


def test_tool_loop_has_round_limit(monkeypatch):
    """模型陷入'搜了还想搜'时不能被它拖死 —— 用尽轮数就逼它收尾。"""
    always_calls = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"id": "c", "type": "function", "function": {"name": "current_time", "arguments": "{}"}}
        ],
    }
    fake = FakeBrain([always_calls] * 10)
    fake.install(monkeypatch)
    text, used = fake.brain._run_tools([{"role": "user", "content": "hi"}], max_rounds=3)
    assert len(used) == 3, f"轮数上限没生效，调了 {len(used)} 次"
    assert isinstance(text, str)


def test_tools_are_sent_to_the_model(monkeypatch):
    fake = FakeBrain([{"content": "normal\n好"}])
    fake.install(monkeypatch)
    fake.brain._run_tools([{"role": "user", "content": "hi"}])
    assert fake.sent_tools[0], "工具 schema 必须真的发给模型，否则它永远不知道能联网"
    names = {t["function"]["name"] for t in fake.sent_tools[0]}
    assert {"web_search", "fetch_url", "current_time"} <= names


def test_use_tools_false_skips_loop(monkeypatch):
    fake = FakeBrain([])
    fake.install(monkeypatch)
    fake.brain.use_tools = False
    text, used = fake.brain._call("hi")
    assert used == []
    assert isinstance(text, str)


# ── 供应商差异 ────────────────────────────────────


def test_thinking_param_only_for_volcengine():
    """火山引擎才有 thinking 参数；DeepSeek/OpenAI 发了可能 400。"""
    from sammy.brain import SammyBrain

    ark = SammyBrain.__new__(SammyBrain)
    ark.thinking = "off"
    ark.base_url = "https://ark.cn-beijing.volces.com/api/v3"
    assert ark._thinking_payload == {"thinking": {"type": "disabled"}}

    ds = SammyBrain.__new__(SammyBrain)
    ds.thinking = "off"
    ds.base_url = "https://api.deepseek.com/v1"
    assert ds._thinking_payload == {}
