import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, unquote, quote
import os
import time
import re
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL = "https://www.flyingfry.cc/index.php/224.html"
DOWNLOAD_DIR = "downloads"
MAX_WORKERS = 3
RETRY_TIMES = 3


class DownloaderConfig:
    """下载器配置类，避免全局变量滥用"""
    def __init__(self, base_url=None, download_dir=None, max_workers=3, retry_times=3):
        self.base_url = base_url or BASE_URL
        self.download_dir = download_dir or DOWNLOAD_DIR
        self.max_workers = max_workers
        self.retry_times = retry_times


def new_session():
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
    return s


def get_page(url, session=None, retries=RETRY_TIMES):
    if session is None:
        session = new_session()
    for i in range(retries + 1):
        try:
            resp = session.get(url, timeout=60)
            resp.encoding = "utf-8"
            return resp.text
        except Exception as e:
            if i < retries:
                time.sleep(2)
                continue
            print(f"  获取页面失败: {e}")
            return None


def parse_items(html):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for li in soup.select("li"):
        a = li.find("a")
        if not a:
            continue
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if not href or href == "#":
            continue
        if "flyingfry.cc" in href and "dir=" not in href:
            continue
        if "返回上级" in text:
            continue
        if text.startswith("📁"):
            items.append({"type": "dir", "name": text[2:].strip(), "href": href})
        elif text.startswith("📄"):
            name = text[2:].strip()
            items.append({"type": "file", "name": name, "href": href})
    return items


def get_total_pages(html):
    match = re.search(r'(\d+)/(\d+)', html)
    if match:
        return int(match.group(2))
    return 1


def download_file(url, filepath, retries=RETRY_TIMES, session=None):
    if session is None:
        session = new_session()
    
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    if os.path.exists(filepath):
        size = os.path.getsize(filepath)
        if size > 0:
            print(f"  跳过已存在: {filepath}")
            return True
    for i in range(retries + 1):
        try:
            resp = session.get(url, stream=True, timeout=120)
            resp.raise_for_status()
            size = int(resp.headers.get("content-length", 0))
            downloaded = 0
            with open(filepath, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
            print(f"  下载完成: {filepath}")
            return True
        except Exception as e:
            if i < retries:
                print(f"  重试 ({i+1}/{retries}): {e}")
                time.sleep(2)
                continue
            print(f"  下载失败: {e}")
            return False


def collect_all_items(dir_path="", session=None, config=None):
    """收集目录下所有文件和子目录，处理分页"""
    if config is None:
        config = DownloaderConfig()
    if session is None:
        session = new_session()
    all_dirs, all_files = [], []
    page = 1
    while True:
        params = f"?dir={quote(dir_path)}" if dir_path else ""
        page_param = f"&page={page}" if page > 1 else ""
        url = config.base_url + params + page_param
        html = get_page(url, session)
        if not html:
            break
        items = parse_items(html)
        for item in items:
            if item["type"] == "dir":
                full_path = f"{dir_path}/{item['name']}" if dir_path else item["name"]
                if (full_path, item["name"]) not in all_dirs:
                    all_dirs.append((full_path, item["name"]))
            else:
                file_url = urljoin(config.base_url, item["href"])
                if (item["name"], file_url) not in all_files:
                    all_files.append((item["name"], file_url))
        total = get_total_pages(html)
        if page >= total:
            break
        page += 1
        time.sleep(0.2)
    return all_dirs, all_files


crawl_stats = {"files": 0, "dirs": 0, "skipped": 0, "failed": 0}


def crawl_and_download(dir_path="", local_path="", depth=0, max_depth=10, config=None, session=None):
    """递归下载目录"""
    global crawl_stats
    if config is None:
        config = DownloaderConfig()
    if session is None:
        session = new_session()
    
    if depth > max_depth:
        return

    dirs, files = collect_all_items(dir_path, session=session, config=config)
    crawl_stats["dirs"] += len(dirs)

    for fname, furl in files:
        filepath = os.path.join(config.download_dir, local_path, fname)
        ok = download_file(furl, filepath, session=session)
        crawl_stats["files"] += 1
        if ok:
            print(f"  [{crawl_stats['files']}] ✓ {fname}", flush=True)
        else:
            crawl_stats["failed"] += 1
            print(f"  [{crawl_stats['files']}] ✗ {fname}", flush=True)

    for full_path, name in dirs:
        new_local = os.path.join(local_path, name)
        crawl_and_download(full_path, new_local, depth + 1, max_depth, config=config, session=session)
        time.sleep(0.2)


def show_tree(dir_path="", prefix="", is_root=True, depth=0, max_depth=3, config=None):
    """显示目录树"""
    if config is None:
        config = DownloaderConfig()
    
    if depth > max_depth:
        return
    dirs, files = collect_all_items(dir_path, config=config)
    if is_root:
        print("📁 根目录", flush=True)
    items = [(n, "file") for n, _ in files] + [(p, "dir") for p, n in dirs]
    names_set = set()
    deduped = []
    for item in items:
        if item[0] not in names_set:
            names_set.add(item[0])
            deduped.append(item)
    items = deduped
    for i, (item, typ) in enumerate(items):
        is_last = i == len(items) - 1
        conn = "└── " if is_last else "├── "
        if typ == "file":
            print(f"{prefix}{conn}📄 {item}", flush=True)
        else:
            display_name = item.split("/")[-1]
            print(f"{prefix}{conn}📁 {display_name}", flush=True)
            ext = "    " if is_last else "│   "
            show_tree(item, prefix + ext, False, depth + 1, max_depth, config=config)


def main():
    parser = argparse.ArgumentParser(description="网站文件自动下载器")
    parser.add_argument("--url", default=None, help="目标网站URL")
    parser.add_argument("--dir", default=None, help="本地下载目录")
    parser.add_argument("--tree", action="store_true", help="仅显示目录树，不下载")
    parser.add_argument("--workers", type=int, default=3, help="下载并发数")
    parser.add_argument("--retry", type=int, default=3, help="重试次数")
    parser.add_argument("--depth", type=int, default=10, help="最大递归深度")
    parser.add_argument("--verbose", action="store_true", help="显示详细信息")
    args = parser.parse_args()

    # 使用配置类，避免修改全局变量
    config = DownloaderConfig(
        base_url=args.url,
        download_dir=args.dir,
        max_workers=args.workers,
        retry_times=args.retry
    )

    if args.tree:
        print("目录树:\n")
        show_tree(max_depth=args.depth, config=config)
        return

    os.makedirs(config.download_dir, exist_ok=True)
    print(f"目标: {config.base_url}")
    print(f"下载目录: {config.download_dir}")

    global crawl_stats
    crawl_stats = {"files": 0, "dirs": 0, "skipped": 0, "failed": 0}
    t0 = time.time()
    crawl_and_download(max_depth=args.depth, config=config)

    elapsed = time.time() - t0
    print(f"\n全部下载完成！", flush=True)
    print(f"文件: {crawl_stats['files']}, 目录: {crawl_stats['dirs']}", flush=True)
    print(f"耗时: {elapsed:.1f}秒", flush=True)


if __name__ == "__main__":
    main()