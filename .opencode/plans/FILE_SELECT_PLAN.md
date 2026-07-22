# 文件选择下载功能计划

## 目标
实现获取网站文件夹内容，然后让用户选择要下载的文件/文件夹，并支持文件预览。

## 用户需求
1. 扫描网站目录结构（全部层级）
2. 使用目录树+复选框显示
3. 用户可以选择要下载的内容
4. 只下载选中的内容
5. 支持文件预览（图片、文本、视频信息等）

## 技术方案

### 1. 界面设计

**布局：**
```
+----------------------------------------------------+
|              网站文件自动下载器                      |
+----------------------------------------------------+
| [URL输入框] [扫描按钮] [进度条]                    |
+----------------------------------------------------+
| 左侧：目录树     | 中间：预览      | 右侧：日志    |
| (带复选框)       | (文件预览)      | (下载日志)    |
|                  |                 |               |
| ☑ 根目录         | [图片预览区域]  | [00:00] 开始..|
|   ☑ github_backup|                 | [00:01] ✓ 文件|
|     ☑ 2022       | 文件名: 1.png   | [00:02] ✓ 文件|
|       ☑ 04       | 大小: 2.5 MB    |               |
|         ☑ 1.png  | 类型: PNG       |               |
|         ☐ 2.png  | 尺寸: 1920x1080 |               |
|   ☐ papers       |                 |               |
|                  |                 |               |
+----------------------------------------------------+
| [全选] [反选] [展开] [收起]                        |
| [开始下载] [停止] [退出]               状态: 就绪  |
+----------------------------------------------------
```

### 2. 核心组件

**Treeview + 复选框：**
- 使用tkinter.ttk.Treeview显示目录树
- 使用tag标记选中状态
- 点击节点切换选中状态
- 父子节点联动

**预览面板：**
- 右侧显示预览内容
- 支持图片预览（缩略图）
- 支持文本预览（前几行）
- 支持视频信息预览（大小、时长等）
- 支持文件信息预览（类型、大小等）

**数据结构：**
```python
# 节点数据
{
    "id": "github_backup/2022/04",
    "name": "04",
    "type": "dir",  # 或 "file"
    "url": "https://...",  # 文件URL
    "checked": True,
    "children": [...]
}

# 预览数据
{
    "file_type": "image",  # image, text, video, other
    "preview_data": "...",  # 预览内容或缩略图
    "file_info": {
        "name": "photo.jpg",
        "size": "2.5 MB",
        "type": "JPEG Image",
        "dimensions": "1920x1080"
    }
}
```

### 3. 功能实现

**扫描功能：**
1. 点击"扫描"按钮
2. 后台线程扫描网站目录
3. 实时更新Treeview
4. 扫描完成后显示统计信息

**选择功能：**
1. 点击节点切换选中状态
2. 勾选父节点自动勾选所有子节点
3. 取消勾选子节点时，父节点变为半选状态
4. 全选/反选按钮

**预览功能：**
1. 点击文件节点时触发预览
2. 根据文件类型显示不同预览内容
3. 图片：下载缩略图并显示（使用PIL/Pillow）
4. 文本：下载前1KB内容并显示
5. 视频：显示文件信息（大小、格式等）
6. 其他：显示文件信息（类型、大小等）

**下载功能：**
1. 遍历Treeview，收集选中的文件
2. 后台线程下载
3. 实时更新日志
4. 支持停止下载

### 4. 代码结构

**gui_downloader.py：**
```python
class DownloaderGUI:
    def __init__(self, root):
        # 初始化界面
        self.tree_data = {}  # 存储目录树数据
        self.checked_items = set()  # 存储选中的项目
        pass
    
    def scan_website(self):
        # 扫描网站目录
        pass
    
    def _scan_worker(self):
        # 扫描工作线程
        pass
    
    def _update_tree(self, parent, items):
        # 更新Treeview
        pass
    
    def toggle_check(self, item_id):
        # 切换选中状态
        pass
    
    def _update_children_check(self, item_id, checked):
        # 更新子节点选中状态
        pass
    
    def _update_parent_check(self, item_id):
        # 更新父节点选中状态
        pass
    
    def select_all(self):
        # 全选
        pass
    
    def deselect_all(self):
        # 反选
        pass
    
    def start_download(self):
        # 开始下载选中的文件
        pass
    
    def _download_worker(self):
        # 下载工作线程
        pass
```

### 5. 实现步骤

**步骤1：修改gui_downloader.py**
- 添加Treeview组件
- 添加扫描功能
- 添加复选框功能
- 添加全选/反选功能
- 添加预览功能
- 修改下载逻辑，只下载选中的文件

**步骤2：修改downloader.py**
- 添加download_selected_files函数
- 支持只下载指定的文件/文件夹

**步骤3：安装依赖**
- 安装Pillow库（用于图片预览）
- 更新requirements.txt

**步骤4：测试**
- 测试扫描功能
- 测试选择功能
- 测试预览功能
- 测试下载功能

**步骤5：打包**
- 重新打包成exe文件

### 6. 关键代码片段

**Treeview + 复选框：**
```python
# 创建Treeview
self.tree = ttk.Treeview(tree_frame, columns=("type", "size"), selectmode="none")
self.tree.heading("#0", text="名称")
self.tree.heading("type", text="类型")
self.tree.heading("size", text="大小")

# 绑定点击事件
self.tree.bind("<ButtonRelease-1>", self.on_tree_click)

# 添加节点
def add_node(self, parent, name, node_type, checked=False):
    icon = "📁" if node_type == "dir" else "📄"
    tag = "checked" if checked else "unchecked"
    item_id = self.tree.insert(parent, "end", text=f"{icon} {name}", 
                                values=(node_type, ""), tags=(tag,))
    return item_id

# 切换选中状态
def on_tree_click(self, event):
    item = self.tree.identify_row(event.y)
    if item:
        tags = self.tree.item(item, "tags")
        if "checked" in tags:
            self.tree.item(item, tags=("unchecked",))
            self._update_children_check(item, False)
        else:
            self.tree.item(item, tags=("checked",))
            self._update_children_check(item, True)
        self._update_parent_check(item)
```

**预览功能：**
```python
def preview_file(self, item_id):
    """预览文件"""
    file_url = self.tree_data[item_id]["url"]
    file_name = self.tree_data[item_id]["name"]
    file_ext = os.path.splitext(file_name)[1].lower()
    
    # 清空预览区域
    self.preview_text.delete(1.0, tk.END)
    self.preview_image_label.config(image="")
    
    # 根据文件类型显示预览
    if file_ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp"]:
        # 图片预览
        self._preview_image(file_url)
    elif file_ext in [".txt", ".py", ".js", ".html", ".css", ".json", ".md"]:
        # 文本预览
        self._preview_text(file_url)
    elif file_ext in [".mp4", ".mkv", ".avi", ".mov"]:
        # 视频信息预览
        self._preview_video_info(file_url, file_name)
    else:
        # 其他文件信息
        self._preview_file_info(file_url, file_name)

def _preview_image(self, url):
    """预览图片"""
    try:
        # 下载缩略图
        response = requests.get(url, stream=True, timeout=10)
        response.raise_for_status()
        
        # 使用PIL打开图片
        from PIL import Image, ImageTk
        import io
        
        image = Image.open(io.BytesIO(response.content))
        
        # 缩放图片
        max_size = (300, 300)
        image.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        # 显示图片
        photo = ImageTk.PhotoImage(image)
        self.preview_image_label.config(image=photo)
        self.preview_image_label.image = photo  # 保持引用
        
        # 显示图片信息
        self.preview_text.insert(tk.END, f"文件类型: {image.format}\n")
        self.preview_text.insert(tk.END, f"尺寸: {image.size[0]}x{image.size[1]}\n")
        self.preview_text.insert(tk.END, f"模式: {image.mode}\n")
        
    except Exception as e:
        self.preview_text.insert(tk.END, f"预览失败: {e}\n")

def _preview_text(self, url):
    """预览文本文件"""
    try:
        # 下载前1KB
        headers = {"Range": "bytes=0-1023"}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        # 显示文本内容
        content = response.text
        self.preview_text.insert(tk.END, content)
        
        if len(content) == 1024:
            self.preview_text.insert(tk.END, "\n... (已截断)")
            
    except Exception as e:
        self.preview_text.insert(tk.END, f"预览失败: {e}\n")

def _preview_video_info(self, url, file_name):
    """预览视频信息"""
    try:
        # 获取文件大小
        response = requests.head(url, timeout=10)
        response.raise_for_status()
        
        content_length = response.headers.get("Content-Length", 0)
        file_size = int(content_length) if content_length else 0
        
        # 显示视频信息
        self.preview_text.insert(tk.END, f"文件名: {file_name}\n")
        self.preview_text.insert(tk.END, f"文件大小: {self.format_size(file_size)}\n")
        self.preview_text.insert(tk.END, f"文件类型: {os.path.splitext(file_name)[1]}\n")
        self.preview_text.insert(tk.END, f"\n视频预览需要下载后播放")
        
    except Exception as e:
        self.preview_text.insert(tk.END, f"获取信息失败: {e}\n")

def _preview_file_info(self, url, file_name):
    """预览文件信息"""
    try:
        # 获取文件大小
        response = requests.head(url, timeout=10)
        response.raise_for_status()
        
        content_length = response.headers.get("Content-Length", 0)
        file_size = int(content_length) if content_length else 0
        
        # 显示文件信息
        self.preview_text.insert(tk.END, f"文件名: {file_name}\n")
        self.preview_text.insert(tk.END, f"文件大小: {self.format_size(file_size)}\n")
        self.preview_text.insert(tk.END, f"文件类型: {os.path.splitext(file_name)[1]}\n")
        self.preview_text.insert(tk.END, f"URL: {url}\n")
        
    except Exception as e:
        self.preview_text.insert(tk.END, f"获取信息失败: {e}\n")

def format_size(self, size):
    """格式化文件大小"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"
```

**收集选中的文件：**
```python
def collect_checked_items(self, parent=""):
    items = []
    for child in self.tree.get_children(parent):
        tags = self.tree.item(child, "tags")
        if "checked" in tags:
            item_type = self.tree.set(child, "type")
            if item_type == "file":
                items.append(child)
            else:
                items.extend(self.collect_checked_items(child))
    return items
```

### 7. 注意事项

1. **性能优化**
   - 使用后台线程扫描
   - 延迟加载子目录
   - 限制同时显示的节点数
   - 预览时只下载缩略图或部分内容

2. **用户体验**
   - 扫描时显示进度条
   - 显示文件数量统计
   - 支持展开/收起所有节点
   - 预览时显示加载状态

3. **错误处理**
   - 网络超时重试
   - 扫描中断处理
   - 下载失败记录
   - 预览失败时显示错误信息

4. **依赖管理**
   - 需要安装Pillow库用于图片预览
   - 更新requirements.txt
   - 打包时需要包含Pillow依赖

## 预期成果

1. **gui_downloader.py** - 带文件选择和预览功能的GUI界面
2. **downloader.py** - 支持选择性下载的下载逻辑
3. **requirements.txt** - 更新依赖列表（添加Pillow）

## 验证方法

1. 运行gui_downloader.py
2. 点击"扫描"按钮
3. 等待扫描完成
4. 勾选要下载的文件
5. 点击文件节点，查看预览功能
6. 确认图片、文本、视频等文件能正确预览
7. 点击"开始下载"
8. 确认只下载了选中的文件
9. 重新打包exe文件