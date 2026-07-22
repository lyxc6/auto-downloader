"""DownloadItem.from_dict 不变性回归测试 (#13)"""
from src.models.download_item import DownloadItem, DownloadStatus, ItemType


def _sample_dict():
    return {
        "item_id": "a/b",
        "name": "b",
        "url": "http://x",
        "item_type": "file",
        "parent_id": "",
        "full_path": "a/b",
        "size": 0,
        "downloaded_size": 0,
        "status": "pending",
        "error_message": "",
        "created_at": 1.0,
    }


def test_from_dict_does_not_mutate_input():
    """from_dict 不应修改传入的字典"""
    d = _sample_dict()
    item = DownloadItem.from_dict(d)
    # 原始 dict 应保持字符串形式
    assert d["status"] == "pending"
    assert d["item_type"] == "file"
    # 返回的 item 应为枚举
    assert isinstance(item.status, DownloadStatus)
    assert isinstance(item.item_type, ItemType)


def test_from_dict_roundtrip():
    d = _sample_dict()
    item = DownloadItem.from_dict(d)
    out = item.to_dict()
    assert out["item_id"] == "a/b"
    assert out["status"] == "pending"
    assert out["item_type"] == "file"


def test_from_dict_two_calls_independent():
    """同一 dict 调用两次应都能正确解析（不因第一次被改坏而失败）"""
    d = _sample_dict()
    item1 = DownloadItem.from_dict(d)
    item2 = DownloadItem.from_dict(d)
    assert item1.status == DownloadStatus.PENDING
    assert item2.status == DownloadStatus.PENDING
