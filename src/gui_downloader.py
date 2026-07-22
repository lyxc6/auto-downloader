import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import queue
import os
import sys
import time
import json
import requests
from io import BytesIO
import atexit
import signal

# 在文件顶部导入downloader模块，避免在线程中重复导入
from downloader import new_session, get_page, parse_items, get_total_pages, download_file

# 缓存文件位置：跟exe在同一个目录
if getattr(sys, 'frozen', False):
    CACHE_FILE = os.path.join(os.path.dirname(sys.executable), "cache.json")
else:
    CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache.json")


class DownloaderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("网站文件自动下载器")
        self.root.geometry("1400x800")
        self.root.resizable(True, True)

        self.log_queue = queue.Queue()
        self.is_downloading = False
        self.is_scanning = False
        self.stop_download_flag = threading.Event()
        self.stop_scan_flag = threading.Event()
        self.download_thread = None
        self.scan_thread = None

        # 线程锁保护共享数据
        self.data_lock = threading.Lock()
        
        # 复用session，避免重复创建
        self.session = new_session()
        
        self.tree_data = {}
        self.checked_items = set()
        self.old_tree_data = {}
        self.old_checked_items = set()

        self._create_widgets()
        self._update_log()
        self._load_cache()

        # 注册退出保存
        atexit.register(self._emergency_save)
        self._setup_signal_handlers()

    def _create_widgets(self):
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        title_label = tk.Label(main_frame, text="网站文件自动下载器", font=("微软雅黑", 16, "bold"))
        title_label.pack(pady=(0, 10))

        url_frame = tk.Frame(main_frame)
        url_frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(url_frame, text="目标URL:", font=("微软雅黑", 10)).pack(side=tk.LEFT, padx=(0, 5))
        self.url_entry = tk.Entry(url_frame, font=("微软雅黑", 10), width=50)
        self.url_entry.pack(side=tk.LEFT, padx=(0, 10), fill=tk.X, expand=True)
        self.url_entry.insert(0, "https://www.flyingfry.cc/index.php/224.html")

        self.scan_btn = tk.Button(
            url_frame, text="扫描目录", command=self.scan_website,
            bg="#0e639c", fg="white", font=("微软雅黑", 10), width=10, relief=tk.FLAT
        )
        self.scan_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.stop_scan_btn = tk.Button(
            url_frame, text="停止扫描", command=self.stop_scan,
            bg="#c42b1c", fg="white", font=("微软雅黑", 10), width=10, relief=tk.FLAT, state=tk.DISABLED
        )
        self.stop_scan_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.progress = ttk.Progressbar(url_frame, mode='indeterminate', length=100)
        self.progress.pack(side=tk.LEFT, padx=(0, 5))

        content_frame = tk.Frame(main_frame)
        content_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        tree_frame = tk.LabelFrame(content_frame, text="目录树", font=("微软雅黑", 10))
        tree_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        self.tree = ttk.Treeview(tree_frame, columns=("type", "size"), selectmode="none")
        self.tree.heading("#0", text="名称")
        self.tree.heading("type", text="类型")
        self.tree.heading("size", text="大小")
        self.tree.column("#0", width=300, minwidth=200)
        self.tree.column("type", width=80, minwidth=60)
        self.tree.column("size", width=100, minwidth=80)

        tree_scroll_y = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        tree_scroll_x = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll_y.grid(row=0, column=1, sticky="ns")
        tree_scroll_x.grid(row=1, column=0, sticky="ew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        self.tree.bind("<ButtonRelease-1>", self.on_tree_click)
        self.tree.bind("<Double-1>", self.on_tree_double_click)

        right_frame = tk.Frame(content_frame, width=400)
        right_frame.pack(side=tk.LEFT, fill=tk.BOTH, padx=(5, 0))
        right_frame.pack_propagate(False)

        preview_frame = tk.LabelFrame(right_frame, text="预览", font=("微软雅黑", 10))
        preview_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        self.preview_image_label = tk.Label(preview_frame, text="双击文件查看预览", anchor=tk.CENTER)
        self.preview_image_label.pack(fill=tk.X, padx=5, pady=5)

        self.preview_text = scrolledtext.ScrolledText(
            preview_frame, wrap=tk.WORD, font=("Consolas", 9), height=8, state=tk.DISABLED
        )
        self.preview_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        selected_frame = tk.LabelFrame(right_frame, text="已选择的文件", font=("微软雅黑", 10))
        selected_frame.pack(fill=tk.BOTH, expand=True, pady=(5, 0))

        self.selected_listbox = tk.Listbox(selected_frame, font=("Consolas", 9), selectmode=tk.EXTENDED)
        selected_scroll = ttk.Scrollbar(selected_frame, orient=tk.VERTICAL, command=self.selected_listbox.yview)
        self.selected_listbox.configure(yscrollcommand=selected_scroll.set)
        self.selected_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        selected_scroll.pack(side=tk.RIGHT, fill=tk.Y, pady=5)

        selected_btn_frame = tk.Frame(selected_frame)
        selected_btn_frame.pack(fill=tk.X, padx=5, pady=(0, 5))

        self.remove_selected_btn = tk.Button(
            selected_btn_frame, text="移除选中", command=self.remove_selected,
            font=("微软雅黑", 9), width=10, relief=tk.FLAT
        )
        self.remove_selected_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.clear_selected_btn = tk.Button(
            selected_btn_frame, text="清空列表", command=self.clear_selected,
            font=("微软雅黑", 9), width=10, relief=tk.FLAT
        )
        self.clear_selected_btn.pack(side=tk.LEFT)

        log_frame = tk.LabelFrame(content_frame, text="下载日志", font=("微软雅黑", 10))
        log_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))

        self.log_text = scrolledtext.ScrolledText(
            log_frame, wrap=tk.WORD, font=("Consolas", 9),
            bg="#1e1e1e", fg="#d4d4d4", insertbackground="white", state=tk.DISABLED
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.log_text.tag_configure("info", foreground="#d4d4d4")
        self.log_text.tag_configure("success", foreground="#6a9955")
        self.log_text.tag_configure("error", foreground="#f44747")
        self.log_text.tag_configure("warning", foreground="#cca700")
        self.log_text.tag_configure("header", foreground="#569cd6", font=("Consolas", 10, "bold"))

        select_frame = tk.Frame(main_frame)
        select_frame.pack(fill=tk.X, pady=(0, 5))

        self.select_all_btn = tk.Button(
            select_frame, text="全选", command=self.select_all, font=("微软雅黑", 9), width=8, relief=tk.FLAT
        )
        self.select_all_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.deselect_all_btn = tk.Button(
            select_frame, text="反选", command=self.deselect_all, font=("微软雅黑", 9), width=8, relief=tk.FLAT
        )
        self.deselect_all_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.expand_all_btn = tk.Button(
            select_frame, text="展开全部", command=self.expand_all, font=("微软雅黑", 9), width=8, relief=tk.FLAT
        )
        self.expand_all_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.collapse_all_btn = tk.Button(
            select_frame, text="收起全部", command=self.collapse_all, font=("微软雅黑", 9), width=8, relief=tk.FLAT
        )
        self.collapse_all_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.stats_label = tk.Label(
            select_frame, text="文件: 0 | 目录: 0 | 已选: 0", font=("微软雅黑", 9), anchor=tk.W
        )
        self.stats_label.pack(side=tk.LEFT, padx=(20, 0))

        button_frame = tk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(0, 5))

        self.start_btn = tk.Button(
            button_frame, text="开始下载", command=self.start_download,
            bg="#0e639c", fg="white", font=("微软雅黑", 10), width=12, relief=tk.FLAT, state=tk.DISABLED
        )
        self.start_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.stop_btn = tk.Button(
            button_frame, text="停止下载", command=self.stop_download,
            bg="#c42b1c", fg="white", font=("微软雅黑", 10), width=12, relief=tk.FLAT, state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.clear_btn = tk.Button(
            button_frame, text="清空日志", command=self.clear_log, font=("微软雅黑", 10), width=12, relief=tk.FLAT
        )
        self.clear_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.exit_btn = tk.Button(
            button_frame, text="退出", command=self.on_exit, font=("微软雅黑", 10), width=12, relief=tk.FLAT
        )
        self.exit_btn.pack(side=tk.RIGHT)

        status_frame = tk.Frame(main_frame, relief=tk.SUNKEN, bd=1)
        status_frame.pack(fill=tk.X)

        self.status_label = tk.Label(
            status_frame, text="状态: 就绪", font=("微软雅黑", 9), anchor=tk.W, padx=5, pady=3
        )
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _emergency_save(self):
        """紧急保存方法，静默保存不输出日志"""
        try:
            if self.tree_data:
                # 安全获取URL，避免访问已销毁的控件
                try:
                    url = self.url_entry.get().strip()
                except Exception:
                    url = ""
                
                cache_data = {
                    "url": url,
                    "tree_data": self.tree_data,
                    "checked_items": list(self.checked_items),
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                with open(CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(cache_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            # 记录错误但不抛出
            print(f"紧急保存失败: {e}", file=sys.stderr)

    def _start_auto_save(self):
        """启动定时自动保存（每30秒）"""
        self._auto_save_timer = self.root.after(30000, self._auto_save_tick)

    def _auto_save_tick(self):
        """定时保存回调"""
        if self.is_scanning or self.is_downloading:
            self._emergency_save()
            self._auto_save_timer = self.root.after(30000, self._auto_save_tick)

    def _stop_auto_save(self):
        """停止定时自动保存"""
        if hasattr(self, '_auto_save_timer'):
            self.root.after_cancel(self._auto_save_timer)

    def log_message(self, message, tag="info"):
        self.log_queue.put((message, tag))

    def _update_log(self):
        while not self.log_queue.empty():
            try:
                message, tag = self.log_queue.get_nowait()
                self.log_text.config(state=tk.NORMAL)
                self.log_text.insert(tk.END, message + "\n", tag)
                self.log_text.see(tk.END)
                self.log_text.config(state=tk.DISABLED)
            except queue.Empty:
                break
        self.root.after(100, self._update_log)

    def _save_cache(self):
        try:
            cache_data = {
                "url": self.url_entry.get().strip(),
                "tree_data": self.tree_data,
                "checked_items": list(self.checked_items),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            self.log_message(f"缓存已保存: {CACHE_FILE}", "info")
        except Exception as e:
            self.log_message(f"保存缓存失败: {e}", "error")

    def _load_cache(self):
        try:
            if not os.path.exists(CACHE_FILE):
                return

            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache_data = json.load(f)

            # 数据校验
            if not isinstance(cache_data, dict):
                raise ValueError("缓存数据格式错误")
            
            url = cache_data.get("url", "")
            if not isinstance(url, str):
                raise ValueError("URL格式错误")
            
            tree_data = cache_data.get("tree_data", {})
            if not isinstance(tree_data, dict):
                raise ValueError("tree_data格式错误")
            
            # 校验每个item的结构
            for item_id, data in tree_data.items():
                if not isinstance(data, dict):
                    raise ValueError(f"item {item_id} 数据格式错误")
                required_keys = ["name", "type", "url", "full_path", "parent"]
                for key in required_keys:
                    if key not in data:
                        raise ValueError(f"item {item_id} 缺少键 {key}")
            
            checked_items = cache_data.get("checked_items", [])
            if not isinstance(checked_items, list):
                raise ValueError("checked_items格式错误")

            self.url_entry.delete(0, tk.END)
            self.url_entry.insert(0, url)

            self.tree_data = tree_data
            self.checked_items = set(checked_items)
            if self.tree_data:
                self._restore_tree()
                self.log_message(f"已加载缓存 ({cache_data.get('timestamp', '未知时间')})", "info")
                self.log_message(f"文件: {sum(1 for d in self.tree_data.values() if d['type'] == 'file')}, "
                               f"目录: {sum(1 for d in self.tree_data.values() if d['type'] == 'dir')}", "info")
                self.start_btn.config(state=tk.NORMAL)
        except Exception as e:
            self.log_message(f"加载缓存失败: {e}", "error")

    def _restore_tree(self):
        self.tree.delete(*self.tree.get_children())
        for item_id, data in self.tree_data.items():
            parent_id = data.get("parent", "")
            icon = "📁" if data["type"] == "dir" else "📄"
            text = f"{icon} {data['name']}"
            self._add_tree_node(parent_id, item_id, text, data["type"], "")
        
        for item_id in self.checked_items:
            if self.tree.exists(item_id):
                self.tree.item(item_id, tags=("checked",))
        
        self._update_stats_display()
        self._update_selected_list()

    def scan_website(self):
        if self.is_scanning:
            return

        url = self.url_entry.get().strip()
        if not url:
            messagebox.showerror("错误", "请输入目标URL")
            return

        self.is_scanning = True
        self.stop_scan_flag.clear()
        self.scan_btn.config(state=tk.DISABLED)
        self.stop_scan_btn.config(state=tk.NORMAL)
        self.status_label.config(text="状态: 扫描中...")
        self.progress.start()

        self.old_tree_data = self.tree_data.copy()
        self.old_checked_items = self.checked_items.copy()

        self.log_message("=" * 50, "header")
        self.log_message("开始扫描目录结构（增量更新）", "header")
        self.log_message("=" * 50, "header")

        self.scan_thread = threading.Thread(target=self._scan_worker, args=(url,), daemon=True)
        self.scan_thread.start()
        self._start_auto_save()

    def stop_scan(self):
        if not self.is_scanning:
            return
        self.stop_scan_flag.set()
        self.log_message("正在停止扫描...", "warning")
        self.status_label.config(text="状态: 正在停止扫描...")

    def _scan_worker(self, base_url):
        try:
            from urllib.parse import urljoin, quote

            session = self.session
            new_tree_data = {}

            def get_all_pages(dir_path=""):
                all_dirs, all_files = [], []
                page = 1
                while True:
                    if self.stop_scan_flag.is_set():
                        return all_dirs, all_files
                    params = f"?dir={quote(dir_path)}" if dir_path else ""
                    page_param = f"&page={page}" if page > 1 else ""
                    url = base_url + params + page_param
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
                            file_url = urljoin(base_url, item["href"])
                            if (item["name"], file_url) not in all_files:
                                all_files.append((item["name"], file_url))
                    total = get_total_pages(html)
                    if page >= total:
                        break
                    page += 1
                    time.sleep(0.15)
                return all_dirs, all_files

            file_count = 0
            dir_count = 0

            def scan_directory(dir_path="", parent_id="", depth=0):
                nonlocal file_count, dir_count
                if depth > 20 or self.stop_scan_flag.is_set():
                    return

                dirs, files = get_all_pages(dir_path)

                for full_path, name in dirs:
                    if self.stop_scan_flag.is_set():
                        return
                    item_id = full_path
                    new_tree_data[item_id] = {
                        "name": name, "type": "dir", "url": "",
                        "full_path": full_path, "parent": parent_id
                    }
                    dir_count += 1
                    self.root.after(0, self._update_scan_stats, file_count, dir_count)
                    time.sleep(0.02)
                    scan_directory(full_path, item_id, depth + 1)

                for fname, furl in files:
                    if self.stop_scan_flag.is_set():
                        return
                    item_id = f"{dir_path}/{fname}" if dir_path else fname
                    new_tree_data[item_id] = {
                        "name": fname, "type": "file", "url": furl,
                        "full_path": item_id, "parent": parent_id
                    }
                    file_count += 1
                    self.root.after(0, self._update_scan_stats, file_count, dir_count)
                    time.sleep(0.02)

            scan_directory()

            if self.stop_scan_flag.is_set():
                to_add = {k: v for k, v in new_tree_data.items() if k not in self.old_tree_data}
                to_remove = {}
                to_keep = {k: v for k, v in self.old_tree_data.items()}
                self.tree_data = {**self.old_tree_data, **new_tree_data}
            else:
                to_add = {k: v for k, v in new_tree_data.items() if k not in self.old_tree_data}
                to_remove = {k: v for k, v in self.old_tree_data.items() if k not in new_tree_data}
                to_keep = {k: v for k, v in new_tree_data.items() if k in self.old_tree_data}
                self.tree_data = new_tree_data

            self.root.after(0, self._update_tree_incremental, to_add, to_remove, to_keep)

            self.log_message("", "info")
            self.log_message("=" * 50, "header")
            if self.stop_scan_flag.is_set():
                self.log_message(f"扫描已中止！已扫描: 文件: {file_count}, 目录: {dir_count}", "warning")
            else:
                self.log_message(f"扫描完成！文件: {file_count}, 目录: {dir_count}", "success")
            self.log_message(f"新增: {len(to_add)} 项, 删除: {len(to_remove)} 项, 保留: {len(to_keep)} 项", "info")
            self.log_message("=" * 50, "header")

        except Exception as e:
            self.log_message(f"扫描失败: {e}", "error")
        finally:
            self.is_scanning = False
            self.root.after(0, self._scan_complete)

    def _update_scan_stats(self, file_count, dir_count):
        self.status_label.config(text=f"状态: 扫描中... 文件: {file_count}, 目录: {dir_count}")

    def _update_tree_incremental(self, to_add, to_remove, to_keep):
        for item_id in to_remove:
            if self.tree.exists(item_id):
                self.tree.delete(item_id)
                self.checked_items.discard(item_id)

        for item_id, data in to_add.items():
            parent_id = data.get("parent", "")
            icon = "📁" if data["type"] == "dir" else "📄"
            text = f"{icon} {data['name']}"
            self._add_tree_node(parent_id, item_id, text, data["type"], "")

        for item_id in self.old_checked_items:
            if item_id in self.tree_data and self.tree.exists(item_id):
                self.tree.item(item_id, tags=("checked",))
                self.checked_items.add(item_id)

        self._update_stats_display()
        self._update_selected_list()

    def _add_tree_node(self, parent, item_id, text, node_type, size):
        tag = "unchecked"
        self.tree.insert(parent, "end", iid=item_id, text=text, values=(node_type, size), tags=(tag,))
        self.tree.tag_configure("unchecked", background="")
        self.tree.tag_configure("checked", background="#e6f3ff")

    def _scan_complete(self):
        self.scan_btn.config(state=tk.NORMAL)
        self.stop_scan_btn.config(state=tk.DISABLED)
        self.start_btn.config(state=tk.NORMAL)
        self.progress.stop()
        self.status_label.config(text="状态: 就绪")
        self._save_cache()
        self._stop_auto_save()

    def on_tree_click(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        region = self.tree.identify_region(event.x, event.y)
        if region in ("tree", "text"):
            self.toggle_check(item)

    def on_tree_double_click(self, event):
        item = self.tree.identify_row(event.y)
        if item and item in self.tree_data:
            self.preview_file(item)

    def toggle_check(self, item_id):
        if item_id not in self.tree_data:
            return

        tags = self.tree.item(item_id, "tags")
        if "checked" in tags:
            self.tree.item(item_id, tags=("unchecked",))
            self.checked_items.discard(item_id)
            self._update_children_check(item_id, False)
        else:
            self.tree.item(item_id, tags=("checked",))
            self.checked_items.add(item_id)
            self._update_children_check(item_id, True)

        self._update_parent_check(item_id)
        self._update_stats_display()
        self._update_selected_list()

    def _update_children_check(self, parent_id, checked):
        for child in self.tree.get_children(parent_id):
            if checked:
                self.tree.item(child, tags=("checked",))
                self.checked_items.add(child)
            else:
                self.tree.item(child, tags=("unchecked",))
                self.checked_items.discard(child)
            self._update_children_check(child, checked)

    def _update_parent_check(self, item_id):
        parent = self.tree.parent(item_id)
        if not parent:
            return

        children = self.tree.get_children(parent)
        checked_count = sum(1 for c in children if "checked" in self.tree.item(c, "tags"))

        if checked_count == 0:
            self.tree.item(parent, tags=("unchecked",))
            self.checked_items.discard(parent)
        elif checked_count == len(children):
            self.tree.item(parent, tags=("checked",))
            self.checked_items.add(parent)
        else:
            self.tree.item(parent, tags=("halfchecked",))
            self.checked_items.discard(parent)

        self._update_parent_check(parent)

    def _update_stats_display(self):
        total_files = sum(1 for d in self.tree_data.values() if d["type"] == "file")
        total_dirs = sum(1 for d in self.tree_data.values() if d["type"] == "dir")
        checked_count = len(self.checked_items)
        self.stats_label.config(text=f"文件: {total_files} | 目录: {total_dirs} | 已选: {checked_count}")

    def _update_selected_list(self):
        self.selected_listbox.delete(0, tk.END)
        for item_id in sorted(self.checked_items):
            if item_id in self.tree_data and self.tree_data[item_id]["type"] == "file":
                self.selected_listbox.insert(tk.END, self.tree_data[item_id]["name"])

    def remove_selected(self):
        selected_indices = self.selected_listbox.curselection()
        if not selected_indices:
            return

        items_to_remove = []
        for idx in selected_indices:
            name = self.selected_listbox.get(idx)
            for item_id, data in self.tree_data.items():
                if data["name"] == name and data["type"] == "file" and item_id in self.checked_items:
                    items_to_remove.append(item_id)
                    break

        for item_id in items_to_remove:
            self.tree.item(item_id, tags=("unchecked",))
            self.checked_items.discard(item_id)
            self._update_children_check(item_id, False)
            self._update_parent_check(item_id)

        self._update_stats_display()
        self._update_selected_list()

    def clear_selected(self):
        for item_id in list(self.checked_items):
            self.tree.item(item_id, tags=("unchecked",))
            self.checked_items.discard(item_id)
            self._update_children_check(item_id, False)

        self._update_stats_display()
        self._update_selected_list()

    def select_all(self):
        for item in self.tree.get_children(""):
            self._select_all_recursive(item)
        self._update_stats_display()
        self._update_selected_list()

    def _select_all_recursive(self, item_id):
        self.tree.item(item_id, tags=("checked",))
        self.checked_items.add(item_id)
        for child in self.tree.get_children(item_id):
            self._select_all_recursive(child)

    def deselect_all(self):
        for item in self.tree.get_children(""):
            self._deselect_all_recursive(item)
        self._update_stats_display()
        self._update_selected_list()

    def _deselect_all_recursive(self, item_id):
        self.tree.item(item_id, tags=("unchecked",))
        self.checked_items.discard(item_id)
        for child in self.tree.get_children(item_id):
            self._deselect_all_recursive(child)

    def expand_all(self):
        for item in self.tree.get_children(""):
            self._expand_all_recursive(item)

    def _expand_all_recursive(self, item_id):
        self.tree.item(item_id, open=True)
        for child in self.tree.get_children(item_id):
            self._expand_all_recursive(child)

    def collapse_all(self):
        for item in self.tree.get_children(""):
            self._collapse_all_recursive(item)

    def _collapse_all_recursive(self, item_id):
        self.tree.item(item_id, open=False)
        for child in self.tree.get_children(item_id):
            self._collapse_all_recursive(child)

    def preview_file(self, item_id):
        if item_id not in self.tree_data:
            return

        data = self.tree_data[item_id]
        if data["type"] != "file":
            self.preview_text.config(state=tk.NORMAL)
            self.preview_text.delete(1.0, tk.END)
            self.preview_text.insert(tk.END, f"文件夹: {data['name']}\n路径: {data['full_path']}\n")
            self.preview_text.config(state=tk.DISABLED)
            self.preview_image_label.config(image="", text="双击文件查看预览")
            return

        self.preview_text.config(state=tk.NORMAL)
        self.preview_text.delete(1.0, tk.END)
        self.preview_text.insert(tk.END, "正在加载预览...\n")
        self.preview_text.config(state=tk.DISABLED)
        self.preview_image_label.config(image="", text="加载中...")

        threading.Thread(target=self._preview_worker, args=(item_id,), daemon=True).start()

    def _preview_worker(self, item_id):
        try:
            data = self.tree_data[item_id]
            file_url = data["url"]
            file_name = data["name"]
            file_ext = os.path.splitext(file_name)[1].lower()

            if file_ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp"]:
                self._preview_image(file_url, file_name)
            elif file_ext in [".txt", ".py", ".js", ".html", ".css", ".json", ".md", ".csv", ".xml"]:
                self._preview_text_content(file_url, file_name)
            elif file_ext in [".mp4", ".mkv", ".avi", ".mov", ".wmv"]:
                self._preview_video_info(file_url, file_name)
            else:
                self._preview_file_info(file_url, file_name)
        except Exception as e:
            self.root.after(0, self._update_preview_text, f"预览失败: {e}\n")

    def _preview_image(self, url, file_name):
        try:
            from PIL import Image, ImageTk
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            image = Image.open(BytesIO(response.content))
            original_size = image.size
            max_size = (280, 280)
            image.thumbnail(max_size, Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image)
            self.root.after(0, self._update_preview_image, photo)
            self.root.after(0, self._update_preview_text,
                           f"文件名: {file_name}\n格式: {image.format}\n"
                           f"原始尺寸: {original_size[0]}x{original_size[1]}\n模式: {image.mode}\n")
        except ImportError:
            self.root.after(0, self._update_preview_text,
                           f"文件名: {file_name}\n类型: 图片\n\n"
                           f"需要安装Pillow库才能预览图片\n运行: pip install Pillow")
        except Exception as e:
            self.root.after(0, self._update_preview_text, f"文件名: {file_name}\n预览失败: {e}\n")

    def _preview_text_content(self, url, file_name):
        try:
            headers = {"Range": "bytes=0-2047"}
            response = self.session.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            content = response.text
            self.root.after(0, self._update_preview_text,
                           f"文件名: {file_name}\n类型: 文本文件\n\n--- 预览 ---\n{content}\n\n(显示前2KB内容)")
        except Exception as e:
            self.root.after(0, self._update_preview_text, f"文件名: {file_name}\n预览失败: {e}\n")

    def _preview_video_info(self, url, file_name):
        try:
            response = self.session.head(url, timeout=10)
            response.raise_for_status()
            content_length = response.headers.get("Content-Length", 0)
            file_size = int(content_length) if content_length else 0
            self.root.after(0, self._update_preview_text,
                           f"文件名: {file_name}\n类型: 视频文件\n"
                           f"大小: {self.format_size(file_size)}\n格式: {os.path.splitext(file_name)[1]}\n\n"
                           f"视频预览需要下载后播放")
        except Exception as e:
            self.root.after(0, self._update_preview_text, f"文件名: {file_name}\n获取信息失败: {e}\n")

    def _preview_file_info(self, url, file_name):
        try:
            response = self.session.head(url, timeout=10)
            response.raise_for_status()
            content_length = response.headers.get("Content-Length", 0)
            file_size = int(content_length) if content_length else 0
            self.root.after(0, self._update_preview_text,
                           f"文件名: {file_name}\n类型: {os.path.splitext(file_name)[1] or '未知'}\n"
                           f"大小: {self.format_size(file_size)}\n\nURL:\n{url}")
        except Exception as e:
            self.root.after(0, self._update_preview_text, f"文件名: {file_name}\n获取信息失败: {e}\n")

    def _update_preview_image(self, photo):
        self.preview_image_label.config(image=photo, text="")
        self.preview_image_label.image = photo

    def _update_preview_text(self, text):
        self.preview_text.config(state=tk.NORMAL)
        self.preview_text.delete(1.0, tk.END)
        self.preview_text.insert(tk.END, text)
        self.preview_text.config(state=tk.DISABLED)

    def format_size(self, size):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"

    def collect_checked_files(self):
        files = []
        for item_id in self.checked_items:
            if item_id in self.tree_data and self.tree_data[item_id]["type"] == "file":
                files.append({
                    "name": self.tree_data[item_id]["name"],
                    "url": self.tree_data[item_id]["url"],
                    "path": self.tree_data[item_id]["full_path"]
                })
        return files

    def start_download(self):
        if self.is_downloading:
            return

        checked_files = self.collect_checked_files()
        if not checked_files:
            messagebox.showwarning("警告", "请先选择要下载的文件")
            return

        self.is_downloading = True
        self.stop_download_flag.clear()
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_label.config(text="状态: 下载中...")

        self.log_message("=" * 50, "header")
        self.log_message("开始下载任务", "header")
        self.log_message(f"已选择 {len(checked_files)} 个文件", "info")
        self.log_message("=" * 50, "header")

        self.download_thread = threading.Thread(target=self._download_worker, args=(checked_files,), daemon=True)
        self.download_thread.start()
        self._start_auto_save()

    def stop_download(self):
        if not self.is_downloading:
            return
        self.stop_download_flag.set()
        self.log_message("正在停止下载...", "warning")
        self.status_label.config(text="状态: 正在停止...")

    def _download_worker(self, files):
        try:
            if getattr(sys, 'frozen', False):
                download_dir = os.path.join(os.path.dirname(sys.executable), "downloads")
            else:
                download_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
            os.makedirs(download_dir, exist_ok=True)

            stats = {"done": 0, "failed": 0}

            for file_info in files:
                if self.stop_download_flag.is_set():
                    self.log_message("下载已停止", "warning")
                    break

                file_name = file_info["name"]
                file_url = file_info["url"]
                file_path = file_info["path"]

                local_dir = os.path.dirname(file_path)
                filepath = os.path.join(download_dir, local_dir, file_name)

                ok = download_file(file_url, filepath)
                stats["done"] += 1

                if ok:
                    self.log_message(f"[{stats['done']}/{len(files)}] ✓ {file_name}", "success")
                else:
                    stats["failed"] += 1
                    self.log_message(f"[{stats['done']}/{len(files)}] ✗ {file_name}", "error")

                self.root.after(0, lambda d=stats['done']: self.status_label.config(
                    text=f"状态: 下载中... {d}/{len(files)}"))

            self.log_message("", "info")
            self.log_message("=" * 50, "header")
            if self.stop_download_flag.is_set():
                self.log_message("下载已停止", "warning")
            else:
                self.log_message("全部下载完成！", "success")
            self.log_message(f"成功: {stats['done'] - stats['failed']}, 失败: {stats['failed']}", "info")
            self.log_message("=" * 50, "header")

        except Exception as e:
            self.log_message(f"发生错误: {e}", "error")
        finally:
            self.is_downloading = False
            self.root.after(0, self._download_complete)

    def _download_complete(self):
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.status_label.config(text="状态: 就绪")
        self._stop_auto_save()

    def _setup_signal_handlers(self):
        """设置安全的信号处理器"""
        def signal_handler(sig, frame):
            # 设置标志位，让主循环处理
            self.root.after(0, self._handle_shutdown)
        
        signal.signal(signal.SIGINT, signal_handler)

    def _handle_shutdown(self):
        """处理关闭信号"""
        self._emergency_save()
        self.root.destroy()

    def clear_log(self):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)

    def on_exit(self):
        if self.is_downloading:
            if messagebox.askokcancel("确认退出", "下载正在进行中，确定要退出吗？"):
                self.stop_download_flag.set()
                self._emergency_save()
                self.root.after(500, self.root.destroy)
        else:
            self._emergency_save()
            self.root.destroy()


def main():
    root = tk.Tk()
    app = DownloaderGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()