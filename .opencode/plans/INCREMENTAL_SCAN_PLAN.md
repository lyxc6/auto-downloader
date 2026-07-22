# 增量扫描更新计划

## 用户需求
扫描不应该覆盖原来的结构，应该是在当前的目录树下检索遗漏的内容和移除的内容，应该是比较的方式更新。

## 当前问题
当前扫描会清空所有数据重新开始，导致：
1. 用户已选择的内容丢失
2. 无法看到哪些是新增的、哪些是删除的
3. 扫描过程中无法保留之前的结果

## 解决方案：增量更新

### 核心逻辑
1. **首次扫描**：建立完整的目录树
2. **后续扫描**：比较新旧数据，只更新变化的部分
   - 新增的文件/目录：添加到树中
   - 已删除的文件/目录：从树中移除
   - 未变化的：保留（包括选中状态）

### 数据结构
```python
# 旧数据
old_tree_data = {
    "github_backup": {"name": "github_backup", "type": "dir", ...},
    "github_backup/2022": {"name": "2022", "type": "dir", ...},
    "github_backup/2022/04/1.png": {"name": "1.png", "type": "file", ...},
}

# 新扫描的数据
new_tree_data = {
    "github_backup": {"name": "github_backup", "type": "dir", ...},
    "github_backup/2022": {"name": "2022", "type": "dir", ...},
    "github_backup/2022/04/1.png": {"name": "1.png", "type": "file", ...},
    "github_backup/2022/04/2.png": {"name": "2.png", "type": "file", ...},  # 新增
}

# 比较结果
to_add = ["github_backup/2022/04/2.png"]  # 新增的
to_remove = []  # 删除的（旧数据中有，新数据中没有）
to_keep = ["github_backup", "github_backup/2022", "github_backup/2022/04/1.png"]  # 保留的
```

### 实现步骤

#### 1. 修改 `scan_website` 方法
```python
def scan_website(self):
    if self.is_scanning:
        return

    url = self.url_entry.get().strip()
    if not url:
        messagebox.showerror("错误", "请输入目标URL")
        return

    self.is_scanning = True
    self.stop_scan_flag = False
    self.scan_btn.config(state=tk.DISABLED)
    self.stop_scan_btn.config(state=tk.NORMAL)
    self.status_label.config(text="状态: 扫描中...")
    self.progress.start()

    # 保存旧数据用于比较
    self.old_tree_data = self.tree_data.copy()
    self.old_checked_items = self.checked_items.copy()

    # 不再清空数据
    # self.tree.delete(*self.tree.get_children())
    # self.tree_data.clear()
    # self.checked_items.clear()
    # self.selected_listbox.delete(0, tk.END)

    self.log_message("=" * 50, "header")
    self.log_message("开始扫描目录结构（增量更新）", "header")
    self.log_message("=" * 50, "header")

    self.scan_thread = threading.Thread(target=self._scan_worker, args=(url,), daemon=True)
    self.scan_thread.start()
```

#### 2. 修改 `_scan_worker` 方法
```python
def _scan_worker(self, base_url):
    try:
        # ... 现有代码 ...

        # 扫描完成后，比较新旧数据
        new_tree_data = self.tree_data.copy()
        
        # 找出新增的
        to_add = {k: v for k, v in new_tree_data.items() if k not in self.old_tree_data}
        
        # 找出删除的
        to_remove = {k: v for k, v in self.old_tree_data.items() if k not in new_tree_data}
        
        # 找出保留的
        to_keep = {k: v for k, v in new_tree_data.items() if k in self.old_tree_data}

        # 更新树
        self.root.after(0, self._update_tree_incremental, to_add, to_remove, to_keep)

        # ... 现有代码 ...
```

#### 3. 添加 `_update_tree_incremental` 方法
```python
def _update_tree_incremental(self, to_add, to_remove, to_keep):
    """增量更新目录树"""
    
    # 1. 删除已不存在的节点
    for item_id in to_remove:
        if self.tree.exists(item_id):
            self.tree.delete(item_id)
            self.checked_items.discard(item_id)
    
    # 2. 添加新增的节点
    for item_id, data in to_add.items():
        parent_id = data.get("parent", "")
        icon = "📁" if data["type"] == "dir" else "📄"
        text = f"{icon} {data['name']}"
        self._add_tree_node(parent_id, item_id, text, data["type"], "")
    
    # 3. 保留的节点（不需要操作，已经在树中）
    
    # 4. 恢复选中状态
    for item_id in self.old_checked_items:
        if item_id in self.tree_data and self.tree.exists(item_id):
            self.tree.item(item_id, tags=("checked",))
            self.checked_items.add(item_id)
    
    # 5. 更新统计
    self._update_stats_display()
    self._update_selected_list()
    
    # 6. 显示变化
    self.log_message(f"新增: {len(to_add)} 项", "success")
    self.log_message(f"删除: {len(to_remove)} 项", "warning")
    self.log_message(f"保留: {len(to_keep)} 项", "info")
```

### 优势
1. **保留用户选择**：已选择的文件如果还存在，会保留选中状态
2. **增量更新**：只处理变化的部分，效率更高
3. **可视化变化**：用户可以看到新增和删除了哪些内容
4. **支持中止**：中止扫描时保留已扫描的内容
5. **安全中止**：扫描中止时保留旧数据，只添加新数据，不删除任何东西

### 修复方案：扫描中止处理
```python
# 修改 _scan_worker 方法中的比较逻辑
# 原代码：
to_add = {k: v for k, v in new_tree_data.items() if k not in self.old_tree_data}
to_remove = {k: v for k, v in self.old_tree_data.items() if k not in new_tree_data}
to_keep = {k: v for k, v in new_tree_data.items() if k in self.old_tree_data}

# 修改后：
if self.stop_scan_flag:
    # 扫描被中止：保留旧数据，只添加新数据，不删除任何东西
    to_add = {k: v for k, v in new_tree_data.items() if k not in self.old_tree_data}
    to_remove = {}  # 不删除任何东西
    to_keep = {k: v for k, v in self.old_tree_data.items()}  # 保留所有旧数据
    # 合并数据：旧数据 + 新数据
    self.tree_data = {**self.old_tree_data, **new_tree_data}
else:
    # 扫描完成：正常比较
    to_add = {k: v for k, v in new_tree_data.items() if k not in self.old_tree_data}
    to_remove = {k: v for k, v in self.old_tree_data.items() if k not in new_tree_data}
    to_keep = {k: v for k, v in new_tree_data.items() if k in self.old_tree_data}
    self.tree_data = new_tree_data
```

### 注意事项
1. 需要处理目录层级关系，确保父目录存在
2. 需要处理选中状态的恢复
3. 需要处理缓存的更新
4. **缓存文件位置**：cache.json应该跟exe在同一个目录，而不是源码目录
5. **扫描中止处理**：扫描被中止时，应该保留旧数据，只添加已扫描到的新数据，不删除任何东西

### 缓存文件位置修改
```python
# 修改前
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache.json")

# 修改后：支持exe和源码两种环境
if getattr(sys, 'frozen', False):
    # exe环境
    CACHE_FILE = os.path.join(os.path.dirname(sys.executable), "cache.json")
else:
    # 源码环境
    CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache.json")
```

## 预期成果
1. 首次扫描建立完整目录树
2. 后续扫描只更新变化的部分
3. 保留用户已选择的内容
4. 显示新增和删除的统计信息
5. 扫描中止时保留旧数据，只添加已扫描到的新数据