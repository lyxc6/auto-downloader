"""get_total_pages 精确化回归测试 (#2)

验证不再误匹配页面正文中任意 N/M（日期、版本号、比例），
仍能从分页链接或分页容器中正确提取总页数。
"""

from src.services.scanner import ScanService


def svc():
    return ScanService()


def test_empty_html_returns_1():
    assert svc().get_total_pages("") == 1


def test_no_pagination_returns_1():
    html = "<html><body><ul><li>file1</li></ul></body></html>"
    assert svc().get_total_pages(html) == 1


def test_date_and_fraction_not_matched():
    """页面正文中的日期、比例等 N/M 不应被当作页数"""
    html = "<html><body>Date: 2026/07. Build 3/4 completed. <ul><li>file</li></ul></body></html>"
    assert svc().get_total_pages(html) == 1


def test_version_string_not_matched():
    html = "<html><body>Version 1.0/2.0 release notes</body></html>"
    assert svc().get_total_pages(html) == 1


def test_page_links_max():
    """从分页链接 ?page=N 中取最大页码"""
    html = (
        "<html><body>"
        '<a href="?dir=x&page=1">1</a> '
        '<a href="?dir=x&page=3">3</a> '
        '<a href="?dir=x&page=5">5</a>'
        "</body></html>"
    )
    assert svc().get_total_pages(html) == 5


def test_single_page_link_returns_1():
    """仅 page=1 链接应返回 1"""
    html = '<html><body><a href="?dir=x&page=1">1</a></body></html>'
    assert svc().get_total_pages(html) == 1


def test_pagination_class_container_n_m():
    """分页容器 (class 含 pag/page) 内的 N/M 应被提取"""
    html = '<html><body><ul><li>file</li></ul><div class="pagination">当前 1/5</div></body></html>'
    assert svc().get_total_pages(html) == 5


def test_pagination_class_with_page_links_prefers_links():
    """同时存在分页链接与容器文本时，链接优先"""
    html = (
        "<html><body>"
        '<div class="pagination">当前 1/3</div>'
        '<a href="?dir=x&page=1">1</a> '
        '<a href="?dir=x&page=7">7</a>'
        "</body></html>"
    )
    assert svc().get_total_pages(html) == 7


def test_current_text_fallback():
    """无分页容器但含 '当前 N/M' 文本时回退匹配"""
    html = "<html><body><ul><li>file</li></ul><span>当前 2/8</span></body></html>"
    assert svc().get_total_pages(html) == 8


def test_bogus_n_m_in_main_text_ignored_even_with_current_elsewhere():
    """正文 N/M 干扰即使存在 '第 N/M' 也只取分页语义"""
    html = "<html><body>Ratio 3/4. 第 1/6 页</body></html>"
    assert svc().get_total_pages(html) == 6
