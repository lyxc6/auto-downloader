"""HTML解析器 - 页面内容解析和分页信息提取"""

import hashlib
import logging
import re
from typing import cast

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


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
                items.append(("dir", text, href))
            else:
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
