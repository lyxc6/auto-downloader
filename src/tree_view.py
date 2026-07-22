import requests
from bs4 import BeautifulSoup
from urllib.parse import quote
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError

BASE_URL = "https://www.flyingfry.cc/index.php/224.html"
MAX_SECOND_LEVEL = 30  # 二级目录扫描上限


def new_session():
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
    return s


def get_page(url, session, retries=2):
    for i in range(retries + 1):
        try:
            resp = session.get(url, timeout=60)
            resp.encoding = "utf-8"
            return resp.text
        except Exception as e:
            if i < retries:
                time.sleep(1)
                continue
            print(f"获取页面失败: {e}")
            return None


def parse_items(html):
    soup = BeautifulSoup(html, "html.parser")
    dirs, files = [], []
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
            dirs.append(text[2:].strip())
        elif text.startswith("📄"):
            files.append(text[2:].strip())
    return dirs, files


def get_all_pages(dir_path="", session=None):
    if session is None:
        session = new_session()
    all_dirs, all_files = [], []
    page = 1
    while True:
        params = f"?dir={quote(dir_path)}" if dir_path else ""
        page_param = f"&page={page}" if page > 1 else ""
        url = BASE_URL + params + page_param
        html = get_page(url, session)
        if not html:
            break
        dirs, files = parse_items(html)
        all_dirs.extend(dirs)
        all_files.extend(files)
        match = re.search(r'(\d+)/(\d+)', html)
        total = int(match.group(2)) if match else 1
        if page >= total:
            break
        page += 1
        time.sleep(0.15)
    return all_dirs, all_files


def print_tree(node, prefix="", is_root=True, max_depth=2, depth=0):
    if is_root:
        print("📁 根目录", flush=True)
    if depth > max_depth:
        remaining = len(node.get("files", [])) + len(node.get("dirs", {}))
        print(f"{prefix}└── ... 还有 {remaining} 项", flush=True)
        return
    files = sorted(node.get("files", []))
    dirs = sorted(node.get("dirs", {}).items())
    items = [(n, "file") for n in files] + [(n, "dir") for n, _ in dirs]
    for i, (name, typ) in enumerate(items):
        is_last = i == len(items) - 1
        conn = "└── " if is_last else "├── "
        if typ == "file":
            print(f"{prefix}{conn}📄 {name}", flush=True)
        else:
            print(f"{prefix}{conn}📁 {name}", flush=True)
            ext = "    " if is_last else "│   "
            sub = node["dirs"].get(name, {})
            if sub:
                print_tree(sub, prefix + ext, False, max_depth, depth + 1)
            else:
                print(f"{prefix}{ext}└── (未扫描)", flush=True)


def count_stats(node):
    dirs_count = len(node.get("dirs", {}))
    files_count = len(node.get("files", []))
    for sub in node.get("dirs", {}).values():
        sd, sf = count_stats(sub)
        dirs_count += sd
        files_count += sf
    return dirs_count, files_count


def main():
    t0 = time.time()
    tree = {"files": [], "dirs": {}}

    print("扫描根目录...", flush=True)
    root_dirs, root_files = get_all_pages()
    tree["files"] = root_files
    for d in root_dirs:
        tree["dirs"][d] = None

    # 并行扫描一级目录
    with ThreadPoolExecutor(max_workers=8) as pool:
        fut_map = {}
        for d in root_dirs:
            fut = pool.submit(get_all_pages, d, new_session())
            fut_map[fut] = d
        for f in as_completed(fut_map):
            d = fut_map[f]
            try:
                sub_dirs, sub_files = f.result()
            except Exception as e:
                print(f"扫描目录 {d} 失败: {e}")
                sub_dirs, sub_files = [], []
            tree["dirs"][d] = {"files": sub_files, "dirs": {}}
            for sd in sub_dirs:
                tree["dirs"][d]["dirs"][sd] = {"files": [], "dirs": {}}
            print(f"  ✓ {d}: {len(sub_dirs)}子目录, {len(sub_files)}文件", flush=True)

    # 并行扫描二级目录（限制数量，避免超时）
    second_level = []
    for d1, node in tree["dirs"].items():
        sub_dirs = list(node.get("dirs", {}).keys())
        if len(sub_dirs) > MAX_SECOND_LEVEL:
            print(f"  → {d1} 有 {len(sub_dirs)} 个子目录，跳过二级扫描", flush=True)
            continue
        for d2 in sub_dirs:
            second_level.append((d1, d2))

    if second_level:
        print(f"扫描二级目录 ({len(second_level)}个)...", flush=True)
        with ThreadPoolExecutor(max_workers=8) as pool:
            fut_map = {}
            for d1, d2 in second_level:
                path = f"{d1}/{d2}"
                fut = pool.submit(get_all_pages, path, new_session())
                fut_map[fut] = (d1, d2)
            for f in as_completed(fut_map):
                d1, d2 = fut_map[f]
                try:
                    sub_dirs, sub_files = f.result()
                except Exception as e:
                    print(f"扫描目录 {d1}/{d2} 失败: {e}")
                    sub_dirs, sub_files = [], []
                node = tree["dirs"][d1]["dirs"][d2]
                node["files"] = sub_files
                node["dirs"] = {sd: {"files": [], "dirs": {}} for sd in sub_dirs}
                print(f"  ✓ {d1}/{d2}: {len(sub_dirs)}子目录, {len(sub_files)}文件", flush=True)

    print("\n目录树 (显示2层):\n", flush=True)
    print_tree(tree, max_depth=2)

    total_dirs, total_files = count_stats(tree)
    print(f"\n{'='*50}", flush=True)
    print(f"总目录数: {total_dirs}", flush=True)
    print(f"总文件数: {total_files}", flush=True)
    print(f"耗时: {time.time()-t0:.1f}秒", flush=True)


if __name__ == "__main__":
    main()