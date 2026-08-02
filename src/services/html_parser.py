"""HTML解析器 - 页面内容解析和分页信息提取"""

import hashlib
import logging
import re
from typing import cast

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def _decode_dir_name_from_href(href: str) -> str | None:
    """从目录 href 中解码真实目录名

    服务器列表页的 href 形如 ``?dir=audio%2FC%25E9%2599%2588...``（双重编码），
    其中的 ``+`` 以 ``%2B`` 表示；而页面显示文本可能把 ``+`` 渲染成空格。
    从 href 解码可得到与真实路径一致的目录名，避免刷新时 404。

    Args:
        href: 目录链接的 href 属性

    Returns:
        解码出的目录名（路径最后一段），失败或无法解析时返回 None
    """
    from urllib.parse import unquote

    m = re.search(r"[?&]dir=([^&]+)", href)
    if not m:
        return None
    encoded = m.group(1)
    try:
        # dir 参数是双重编码路径（外层 %XX 编码 + 内层 UTF-8 编码）
        path = unquote(unquote(encoded))
    except Exception:
        logger.warning("解码目录 href 失败: %s", href)
        return None
    if not path:
        return None
    name = path.rstrip("/").rsplit("/", 1)[-1]
    return name or None


def _decode_file_name_from_href(href: str) -> str | None:
    """从文件 href（完整 URL）中解码真实文件名

    服务器显示文本可能把 ``+`` 渲染成空格（如 ``[WAV CUE]``），而文件 URL
    中 ``+`` 是字面字符。从 URL 最后一段解码可保留真实字符。

    Args:
        href: 文件链接的 href 属性（完整 URL 或相对链接）

    Returns:
        解码出的文件名，失败时返回 None
    """
    from urllib.parse import unquote

    if not href or href.startswith("?"):
        return None
    try:
        last = href.rstrip("/").rsplit("/", 1)[-1]
        if not last or ("=" in last and "?" in last):
            return None
        return unquote(last) or None
    except Exception:
        logger.warning("解码文件 href 失败: %s", href)
        return None


class HtmlParser:
    """HTML解析器 - 页面内容解析和分页信息提取"""

    def parse_items_from_soup(self, soup: BeautifulSoup) -> list[tuple[str, str, str]]:
        """从已解析的 soup 中提取项目

        Returns:
            List of (type, name, href)
        """
        from urllib.parse import unquote

        items: list[tuple[str, str, str]] = []

        # 检测服务端错误页面
        error_div = soup.find("div", style=lambda s: s and "background:#f8d7da" in s)
        if error_div:
            error_text = error_div.get_text(strip=True)
            if "错误" in error_text or "XML Parsing Failed" in error_text:
                logger.warning("检测到服务端错误页面: %s", error_text)
                return items

        # 严格模式：必须找到 #webdav-list 容器
        webdav_list = soup.find(id="webdav-list")
        if not webdav_list:
            logger.warning("未找到 #webdav-list 容器")
            return items

        # 遍历 #webdav-list 下的 li 元素，宽松匹配 style 包含 margin:8px
        for li in webdav_list.find_all("li", style=lambda s: s and "margin:8px" in s):
            a = li.find("a")
            if not a:
                continue

            href = str(a.get("href", ""))
            text = a.get_text(strip=True)
            # 去除开头的 Emoji 字符（📁、📄 等）
            text = re.sub(r"^[\U0001F4C0-\U0001F4FF\u2600-\u26FF\u2700-\u27BF]+\s*", "", text)

            # 优先使用 data-url 属性（新版服务器格式：href="#" + data-url="..."）
            data_url = str(a.get("data-url", ""))
            if data_url and (not href or href == "#"):
                href = data_url

            # 优先使用 data-filename 属性（URL编码的正确文件名）
            data_filename = str(a.get("data-filename", ""))
            if data_filename:
                text = unquote(data_filename)

            if not href or href == "#":
                continue
            if "返回上级" in text:
                continue

            # 根据 href 判断类型
            if "dir=" in href:
                # 目录名以 href 中 dir 参数解码为准：
                # 服务器显示文本可能把 "+" 显示为空格（如 "flac MP3"），
                # 而 href 中的 dir 参数是双重编码的真实路径（如 "flac%2BMP3"）。
                # 从 href 解码可避免名称与真实路径不一致，导致刷新时 404。
                if not data_filename:
                    dir_name = _decode_dir_name_from_href(href)
                    if dir_name:
                        text = dir_name
                items.append(("dir", text, href))
            else:
                # 文件名同理：显示文本可能丢失 "+"，从 URL 最后一段解码更可靠
                if not data_filename:
                    file_name = _decode_file_name_from_href(href)
                    if file_name:
                        text = file_name
                items.append(("file", text, href))

        return items

    def parse_items(self, html: str) -> list[tuple[str, str, str]]:
        """解析页面项目

        Returns:
            List of (type, name, href)
        """
        soup = BeautifulSoup(html, "html.parser")
        return self.parse_items_from_soup(soup)

    def get_total_pages_from_soup(self, soup: BeautifulSoup) -> int:
        """从已解析的 soup 中获取总页数

        解析优先级：
        1. 分页链接 ``?page=N`` 中的最大页码（最可靠）
        2. 分页容器（class 含 pag/page）内的 ``N/M`` 文本
        3. 含分页语义关键词（当前/第 ... 页）的 ``N/M`` 文本
        4. 默认 1
        """
        # 1. 从分页链接提取最大页码
        max_page = 1
        for a in soup.find_all("a", href=True):
            href = str(a["href"])
            if "page=" in href:
                m = re.search(r"[?&]page=(\d+)", href)
                if m:
                    p = int(m.group(1))
                    if p > max_page:
                        max_page = p
        if max_page > 1:
            return max_page

        # 2. 从分页容器（class 含 pag/page）内的 N/M 提取
        for el in soup.find_all(True):
            raw_cls = cast("str | list[str]", el.get("class") or [])
            cls: list[str] = [raw_cls] if isinstance(raw_cls, str) else raw_cls
            cls_str = " ".join(cls).lower() if cls else ""
            if "pag" in cls_str or "page" in cls_str:
                m = re.search(r"(\d+)\s*/\s*(\d+)", el.get_text(" "))
                if m:
                    return int(m.group(2))

        # 3. 含分页语义关键词的 N/M 文本回退
        text = soup.get_text(" ")
        m = re.search(r"(?:当前|第)\s*\d+\s*/\s*(\d+)", text)
        if m:
            return int(m.group(1))

        return 1

    def get_total_pages(self, html: str) -> int:
        """解析总页数（原始逻辑）"""
        soup = BeautifulSoup(html, "html.parser")
        return self.get_total_pages_from_soup(soup)

    def get_content_hash_from_soup(self, soup: BeautifulSoup) -> str:
        """从已解析的 soup 中计算内容哈希（用于分页缓存）"""
        # 提取分页相关元素
        page_elements = []
        for a in soup.find_all("a", href=True):
            href = str(a["href"])
            if "page=" in href:
                page_elements.append(href)

        # 提取分页容器
        for el in soup.find_all(True):
            raw_cls = cast("str | list[str]", el.get("class") or [])
            cls: list[str] = [raw_cls] if isinstance(raw_cls, str) else raw_cls
            cls_str = " ".join(cls).lower() if cls else ""
            if "pag" in cls_str or "page" in cls_str:
                page_elements.append(el.get_text(" "))

        content = "|".join(sorted(page_elements))
        return hashlib.md5(content.encode()).hexdigest()

    def get_content_hash(self, html: str) -> str:
        """计算内容哈希（用于分页缓存）"""
        soup = BeautifulSoup(html, "html.parser")
        return self.get_content_hash_from_soup(soup)

    def is_error_page_from_soup(self, soup: BeautifulSoup) -> bool:
        """从已解析的 soup 中检查是否为错误页面"""
        error_div = soup.find("div", style=lambda s: s and "background:#f8d7da" in s)
        return error_div is not None

    def is_error_page(self, html: str) -> bool:
        """检查是否为错误页面"""
        soup = BeautifulSoup(html, "html.parser")
        return self.is_error_page_from_soup(soup)
