"""更新检查器空字段回归测试

验证:
- GitHub release 的 body/tag_name 为 null 时,payload 中 notes/version 兜底为空字符串
- _check_stable / _check_test 对 null 字段不抛异常
- _show_manual_update_dialog 对 None notes 不崩溃(防御性兜底)
"""

from src.services.update_checker import UpdateCheckWorker
from src.update_flow import UpdateFlow


def _release(body=None, tag=None, html_url=None, prerelease=False, assets=None):
    return {
        "tag_name": tag,
        "body": body,
        "html_url": html_url,
        "prerelease": prerelease,
        "assets": assets or [],
    }


def _collect(worker):
    results = []
    worker.finished.connect(lambda r: results.append(r))
    return results


def test_stable_body_none_normalized():
    worker = UpdateCheckWorker("stable", "1.0.0")
    results = _collect(worker)
    worker._check_stable([_release(body=None, tag="v1.1.0")])
    assert results[0]["notes"] == ""
    assert results[0]["version"] == "1.1.0"


def test_stable_all_null_fields_safe():
    """tag 为 None 时版本无法比较 → 优雅降级为无更新+错误提示，不崩溃"""
    worker = UpdateCheckWorker("stable", "1.0.0")
    results = _collect(worker)
    worker._check_stable([_release(body=None, tag=None, html_url=None)])
    r = results[0]
    assert r["has_update"] is False
    assert r.get("error") == "版本号格式错误"


def test_test_body_none_normalized():
    worker = UpdateCheckWorker("test", "1.0.0", "2000-01-01T00:00:00Z")
    results = _collect(worker)
    worker._check_test([_release(body=None, tag=None, html_url=None, prerelease=True)])
    r = results[0]
    assert r["notes"] == ""
    assert r["version"] == ""
    assert r["tag"] == ""


def test_show_manual_update_dialog_notes_none_safe(monkeypatch):
    """None notes 传入真实对话框拼装逻辑不崩溃、不显示 None"""
    captured = {}

    class FakeDialog:
        def __init__(self, title, text, parent):
            captured["text"] = text

        def exec(self):
            return False

    FakeDialog.yesButton = type("B", (), {"setText": lambda self, t: None})()
    FakeDialog.cancelButton = FakeDialog.yesButton

    monkeypatch.setattr("src.update_flow.MessageDialog", FakeDialog)
    flow = UpdateFlow.__new__(UpdateFlow)
    flow._window = object()
    flow._show_manual_update_dialog("http://x", "1.1.0", None)
    assert "None" not in captured["text"]
