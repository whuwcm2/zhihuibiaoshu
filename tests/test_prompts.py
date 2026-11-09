from __future__ import annotations

from zhibiao.prompts import PROMPT_SPECS, PromptHub


def test_local_prompt_rendering():
    hub = PromptHub(enabled=False)

    system, user = hub.render(
        "zhibiao-technical-writer",
        overview="项目概况",
        key_dates="工期信息",
        scoring="评分因素",
        profile_json="投标人资料",
    )

    assert "投标文件编写专家" in system
    assert all(value in user for value in ["项目概况", "工期信息", "评分因素", "投标人资料"])

    _, review_user = hub.render(
        "zhibiao-reviewer-technical",
        scoring="评分",
        headings="标题",
        missing="字段",
        placeholder_count=3,
    )
    assert all(value in review_user for value in ["评分", "标题", "字段", "3"])
    assert '"issues"' in review_user


def test_prompt_hub_falls_back_when_pull_fails(capsys):
    class BrokenClient:
        def pull_prompt(self, name, **kwargs):
            raise RuntimeError("prompt hub unavailable")

    hub = PromptHub(enabled=True, client=BrokenClient())
    system, user = hub.render(
        "zhibiao-format-writer",
        overview="O",
        items="I",
        key_dates="D",
        profile_json="P",
    )

    assert "投标文件编写专家" in system
    assert "O" in user
    assert "拉取 zhibiao-format-writer 失败" in capsys.readouterr().out


def test_push_all_uses_client_push_prompt():
    class FakeClient:
        def __init__(self):
            self.calls = []

        def push_prompt(self, name, **kwargs):
            self.calls.append((name, kwargs))
            return f"commit-{name}"

    client = FakeClient()
    hub = PromptHub(enabled=True, client=client)
    results = hub.push_all()

    assert len(results) == len(PROMPT_SPECS)
    assert all(value.startswith("commit-") for value in results.values())
    assert {name for name, _ in client.calls} == set(PROMPT_SPECS)
    assert all(kwargs["object"] is not None for _, kwargs in client.calls)


def test_prompt_hub_permission_error_stops_further_pulls():
    class DeniedClient:
        def __init__(self):
            self.calls = 0

        def pull_prompt(self, name, **kwargs):
            self.calls += 1
            raise RuntimeError(
                "Permission prompts:read is not allowed for tracing keys"
            )

    client = DeniedClient()
    hub = PromptHub(enabled=True, client=client)
    for name in ("zhibiao-technical-writer", "zhibiao-commercial-qualification"):
        spec = PROMPT_SPECS[name]
        system, user = hub.render(
            name, **{variable: "X" for variable in spec.template.input_variables}
        )
        assert system and user

    assert client.calls == 1


def test_push_all_permission_error_reports_all_prompts():
    class DeniedClient:
        def __init__(self):
            self.calls = 0

        def push_prompt(self, name, **kwargs):
            self.calls += 1
            raise RuntimeError(
                "Permission prompts:read is not allowed for tracing keys"
            )

    client = DeniedClient()
    results = PromptHub(enabled=True, client=client).push_all()

    assert client.calls == 1
    assert len(results) == len(PROMPT_SPECS)
    assert all("tracing-only" in value for value in results.values())
