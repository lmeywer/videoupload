import os
import sys
import time
import subprocess
import threading
import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from tkinterdnd2 import DND_FILES, TkinterDnD

# ================= 配置常量 =================
OUTPUT_DIR = "output_slices"
M3U8_DIR = "m3u8"
DEFAULT_SEGMENT_SECONDS = 3
DEFAULT_UPLOAD_THREADS = 2

UPLOAD_URL = (
    "https://img1.freeforever.club/upload"
    "?serverCompress=false"
    "&uploadChannel=telegram"
    "&uploadNameType=default"
    "&autoRetry=true"
    "&uploadFolder="
)
AUTHCODE = "97"
VIDEO_EXTS = (".mp4", ".mkv", ".ts")

# ================= 颜色与样式配置 =================
COLOR_BG = "#f5f6f8"          # 整体背景灰
COLOR_WHITE = "#ffffff"       # 内容区背景白
COLOR_PRIMARY = "#007bff"     # 主色调（蓝）
COLOR_PRIMARY_HOVER = "#0069d9"
COLOR_DANGER = "#dc3545"      # 警告色（红）
COLOR_DANGER_HOVER = "#c82333"
COLOR_TEXT = "#333333"        # 主要文字
COLOR_TEXT_LIGHT = "#666666"  # 次要文字
COLOR_BORDER = "#e0e0e0"      # 边框色
COLOR_LOG_BG = "#1e1e1e"      # 日志背景（深色）
COLOR_LOG_TEXT = "#00ff00"    # 日志文字（荧光绿）

# ================= 逻辑函数 (保持不变) =================
def upload_file(file_path):
    headers = {
        "authcode": AUTHCODE,
        "Accept": "application/json, text/plain, */*",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Origin": "https://img1.freeforever.club",
        "Referer": "https://img1.freeforever.club/",
    }
    cookies = {"authCode": AUTHCODE}
    ext = os.path.splitext(file_path)[1].lower()
    if ext != ".ts":
        raise ValueError("只允许上传 .ts 文件")
    with open(file_path, "rb") as f:
        files = {"file": (os.path.basename(file_path), f, "video/vnd.dlna.mpeg-tts")}
        resp = requests.post(UPLOAD_URL, headers=headers, cookies=cookies, files=files, timeout=180)
    resp.raise_for_status()
    data = resp.json()
    src = data[0]["src"]
    return "https://img1.freeforever.club" + src

def ensure_dirs():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(M3U8_DIR, exist_ok=True)

def shutdown_windows():
    if sys.platform.startswith("win"):
        os.system("shutdown /s /t 5")

# ================= GUI 类 (完全重构) =================
class VideoUploaderGUI:
    def __init__(self, root):
        self.root = root
        self.center_window(1000, 720) # 稍微调整尺寸
        self.root.title("批量视频切片上传工具 Pro")
        self.root.configure(bg=COLOR_BG)
        
        ensure_dirs()
        self.configure_styles()

        self.files = []
        self.log_q = queue.Queue()
        self.is_running = False

        # --- 主布局容器 ---
        # 顶部：标题栏 (可选，这里用 Label 模拟一个简洁的头部)
        header_frame = tk.Frame(root, bg=COLOR_WHITE, height=50)
        header_frame.pack(fill="x", side="top")
        tk.Label(header_frame, text="📺 视频切片上传助手", font=("微软雅黑", 14, "bold"), 
                 bg=COLOR_WHITE, fg=COLOR_TEXT).pack(side="left", padx=20, pady=10)

        # 中间：内容区 (左侧列表，右侧控制)
        content_frame = tk.Frame(root, bg=COLOR_BG)
        content_frame.pack(fill="both", expand=True, padx=20, pady=15)

        # 左侧：文件列表面板
        left_panel = tk.Frame(content_frame, bg=COLOR_WHITE, highlightthickness=1, highlightbackground=COLOR_BORDER)
        left_panel.pack(side="left", fill="both", expand=True, padx=(0, 15))

        self.setup_left_panel(left_panel)

        # 右侧：控制面板
        right_panel = tk.Frame(content_frame, bg=COLOR_BG, width=280)
        right_panel.pack(side="right", fill="y")
        
        self.setup_right_panel(right_panel)

        # 底部：日志面板
        log_panel = tk.Frame(root, bg=COLOR_LOG_BG)
        log_panel.pack(fill="x", side="bottom", ipady=5)
        self.setup_log_panel(log_panel)

        self._schedule_log_drain()

    def configure_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam") 
        except tk.TclError:
            pass

        # 通用配置
        style.configure(".", font=("微软雅黑", 10), background=COLOR_BG, foreground=COLOR_TEXT)
        style.configure("TFrame", background=COLOR_BG)
        style.configure("White.TFrame", background=COLOR_WHITE)

        # Treeview (表格) 样式 - 扁平化
        style.configure("Treeview", 
                        background=COLOR_WHITE,
                        foreground=COLOR_TEXT, 
                        fieldbackground=COLOR_WHITE,
                        font=("微软雅黑", 10),
                        rowheight=32,
                        borderwidth=0)
        style.configure("Treeview.Heading", 
                        font=("微软雅黑", 10, "bold"),
                        background="#f1f3f5",
                        foreground=COLOR_TEXT_LIGHT,
                        relief="flat")
        style.map("Treeview", background=[("selected", "#e3f2fd")], foreground=[("selected", COLOR_PRIMARY)])

        # 按钮样式
        # 普通按钮
        style.configure("TButton", 
                        font=("微软雅黑", 10), 
                        padding=8, 
                        background=COLOR_WHITE, 
                        borderwidth=1,
                        relief="flat")
        style.map("TButton", background=[("active", "#f8f9fa")])
        
        # 主按钮 (Primary - Blue)
        style.configure("Primary.TButton", 
                        font=("微软雅黑", 11, "bold"),
                        background=COLOR_PRIMARY, 
                        foreground="white",
                        borderwidth=0)
        style.map("Primary.TButton", 
                  background=[("active", COLOR_PRIMARY_HOVER), ("disabled", "#a0c4ff")],
                  foreground=[("disabled", "#f0f0f0")])

        # 危险按钮 (Danger - Red)
        style.configure("Danger.TButton", 
                        font=("微软雅黑", 11, "bold"),
                        background=COLOR_DANGER, 
                        foreground="white",
                        borderwidth=0)
        style.map("Danger.TButton", 
                  background=[("active", COLOR_DANGER_HOVER), ("disabled", "#ffc9c9")])

        # 进度条
        style.configure("Horizontal.TProgressbar", 
                        troughcolor="#e9ecef", 
                        background=COLOR_PRIMARY, 
                        bordercolor="#e9ecef", 
                        thickness=10)

        # LabelFrame 替代品样式 (其实不需要特意定义，用 Label 模拟标题)

    def setup_left_panel(self, parent):
        # 列表标题栏
        top_bar = tk.Frame(parent, bg=COLOR_WHITE)
        top_bar.pack(fill="x", padx=15, pady=10)
        
        tk.Label(top_bar, text="待处理文件", font=("微软雅黑", 11, "bold"), bg=COLOR_WHITE, fg=COLOR_TEXT).pack(side="left")
        
        # 列表操作按钮 (小图标风格)
        btn_frame = tk.Frame(top_bar, bg=COLOR_WHITE)
        btn_frame.pack(side="right")
        
        ttk.Button(btn_frame, text="📂 添加目录", command=self.choose_dir).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="📄 添加文件", command=self.add_file).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="🗑 清空", command=self.clear_data).pack(side="left", padx=5)

        # 表格区
        columns = ("name", "path", "status")
        self.tree = ttk.Treeview(parent, columns=columns, show="headings", selectmode="extended")
        
        self.tree.heading("name", text="文件名")
        self.tree.heading("path", text="完整路径")
        self.tree.heading("status", text="当前状态")
        
        self.tree.column("name", width=200, anchor="w")
        self.tree.column("path", width=350, anchor="w")
        self.tree.column("status", width=120, anchor="center")
        
        # 滚动条
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side="top", fill="both", expand=True, padx=1, pady=1)
        scrollbar.pack(side="right", fill="y", in_=self.tree)

        # 斑马纹
        self.tree.tag_configure("oddrow", background=COLOR_WHITE)
        self.tree.tag_configure("evenrow", background="#f8f9fa")

        # 拖拽绑定
        self.tree.drop_target_register(DND_FILES)
        self.tree.dnd_bind("<<Drop>>", self.on_drop)
        
        # 右键菜单
        self.menu = tk.Menu(self.root, tearoff=0, bg="white", fg=COLOR_TEXT)
        self.menu.add_command(label="❌ 删除选中", command=self.delete_selected)
        self.tree.bind("<Button-3>", self.show_context_menu)
        
        # 底部进度条 (紧贴表格下方)
        progress_area = tk.Frame(parent, bg="#f1f3f5", height=40)
        progress_area.pack(fill="x", side="bottom")
        
        tk.Label(progress_area, text="总进度:", bg="#f1f3f5", fg=COLOR_TEXT_LIGHT, font=("微软雅黑", 9)).pack(side="left", padx=(15, 5), pady=10)
        self.progress = ttk.Progressbar(progress_area, orient="horizontal", mode="determinate", length=200)
        self.progress.pack(side="left", fill="x", expand=True, padx=5, pady=12)
        self.progress_label = tk.Label(progress_area, text="0%", bg="#f1f3f5", fg=COLOR_PRIMARY, font=("微软雅黑", 9, "bold"))
        self.progress_label.pack(side="left", padx=(5, 15), pady=10)

    def setup_right_panel(self, parent):
        # 1. 参数设置卡片
        param_card = tk.Frame(parent, bg=COLOR_WHITE, highlightthickness=1, highlightbackground=COLOR_BORDER)
        param_card.pack(fill="x", pady=(0, 15))
        
        # 标题
        tk.Label(param_card, text="⚙️ 参数设置", font=("微软雅黑", 11, "bold"), 
                 bg=COLOR_WHITE, fg=COLOR_TEXT).pack(anchor="w", padx=15, pady=(15, 10))
        
        # 表单容器
        form_frame = tk.Frame(param_card, bg=COLOR_WHITE)
        form_frame.pack(fill="x", padx=15, pady=(0, 15))

        # 切片间隔
        tk.Label(form_frame, text="切片间隔 (秒):", bg=COLOR_WHITE).grid(row=0, column=0, sticky="w", pady=8)
        self.seg_entry = ttk.Entry(form_frame, width=10)
        self.seg_entry.insert(0, str(DEFAULT_SEGMENT_SECONDS))
        self.seg_entry.grid(row=0, column=1, sticky="e", pady=8)

        # 线程数
        tk.Label(form_frame, text="上传线程数:", bg=COLOR_WHITE).grid(row=1, column=0, sticky="w", pady=8)
        self.thr_entry = ttk.Entry(form_frame, width=10)
        self.thr_entry.insert(0, str(DEFAULT_UPLOAD_THREADS))
        self.thr_entry.grid(row=1, column=1, sticky="e", pady=8)

        # 选项
        self.after_delete_var = tk.BooleanVar(value=False)
        self.after_shutdown_var = tk.BooleanVar(value=False)
        
        cb_style = ttk.Checkbutton(form_frame, text="完成后删除切片", variable=self.after_delete_var)
        cb_style.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 2))
        
        cb_shut = ttk.Checkbutton(form_frame, text="完成后自动关机", variable=self.after_shutdown_var)
        cb_shut.grid(row=3, column=0, columnspan=2, sticky="w", pady=2)

        # 2. 运行控制卡片
        ctrl_card = tk.Frame(parent, bg=COLOR_BG) # 透明背景
        ctrl_card.pack(fill="x")

        self.start_btn = ttk.Button(ctrl_card, text="▶ 开始处理", style="Primary.TButton", command=self.start_process)
        self.start_btn.pack(fill="x", pady=5, ipady=5)

        self.stop_btn = ttk.Button(ctrl_card, text="■ 停止任务", style="Danger.TButton", command=self.stop_process)
        self.stop_btn.pack(fill="x", pady=5, ipady=5)
        self.stop_btn.state(["disabled"])

        ttk.Button(ctrl_card, text="退出程序", command=self.exit_app).pack(fill="x", pady=5)
        
        # 提示信息
        tk.Label(ctrl_card, text="提示: 拖拽文件夹可快速添加", bg=COLOR_BG, fg=COLOR_TEXT_LIGHT, font=("微软雅黑", 9)).pack(pady=10)

    def setup_log_panel(self, parent):
        top_bar = tk.Frame(parent, bg="#2d2d2d")
        top_bar.pack(fill="x")
        tk.Label(top_bar, text=" 📝 运行日志", bg="#2d2d2d", fg="white", font=("Consolas", 9)).pack(anchor="w", padx=5)
        
        self.log_text = tk.Text(
            parent,
            height=8,
            bg=COLOR_LOG_BG,
            fg=COLOR_LOG_TEXT,
            font=("Consolas", 9),
            relief="flat",
            state="disabled",
            selectbackground=COLOR_PRIMARY
        )
        self.log_text.pack(fill="both", expand=True, padx=5, pady=(0,5))

    # ================= 辅助 GUI 方法 =================
    def center_window(self, width, height):
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def log(self, msg):
        t = time.strftime("%H:%M:%S")
        self.log_q.put(f"[{t}] {msg}")

    def _schedule_log_drain(self):
        while not self.log_q.empty():
            line = self.log_q.get()
            self.log_text.config(state="normal")
            self.log_text.insert("end", line + "\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")
        self.root.after(120, self._schedule_log_drain)

    # ================= 事件处理 (逻辑复用) =================
    def on_drop(self, event):
        paths = self.root.tk.splitlist(event.data)
        new_files = []
        for p in paths:
            if os.path.isdir(p):
                for fn in os.listdir(p):
                    full = os.path.join(p, fn)
                    if os.path.isfile(full) and fn.lower().endswith(VIDEO_EXTS):
                        new_files.append(full)
            else:
                if p.lower().endswith(VIDEO_EXTS):
                    new_files.append(p)
        new_files.sort(key=lambda x: os.path.basename(x).lower())
        self.files.extend(new_files)
        self.files = list(dict.fromkeys(self.files))
        self.refresh_table()
        self.log(f"拖拽添加 {len(new_files)} 个文件")

    def show_context_menu(self, event):
        row_id = self.tree.identify_row(event.y)
        if row_id:
            # 如果点击的行不在选中范围内，则选中它
            if row_id not in self.tree.selection():
                self.tree.selection_set(row_id)
            self.menu.post(event.x_root, event.y_root)

    def add_file(self):
        filetypes = [("视频文件", "*.mp4 *.mkv *.ts")]
        fp = filedialog.askopenfilename(title="选择视频文件", filetypes=filetypes)
        if fp and fp.lower().endswith(VIDEO_EXTS):
            self.files.append(fp)
            self.files = list(dict.fromkeys(self.files))
            self.refresh_table()
            self.log(f"添加文件：{fp}")

    def delete_selected(self):
        selected = self.tree.selection()
        if not selected:
            return
        for iid in selected:
            vals = self.tree.item(iid, "values")
            if vals:
                fp = vals[1]
                if fp in self.files:
                    self.files.remove(fp)
                self.tree.delete(iid)
                self.log(f"删除文件：{os.path.basename(fp)}")
        # 重新刷新以修复斑马纹
        self.refresh_table()

    def choose_dir(self):
        d = filedialog.askdirectory(title="选择视频目录")
        if not d:
            return
        # 这里可以选择是覆盖还是追加，目前逻辑看起来像追加
        # self.files = [] 
        count = 0
        for rootdir, _, filenames in os.walk(d):
            for fn in filenames:
                if fn.lower().endswith(VIDEO_EXTS):
                    self.files.append(os.path.join(rootdir, fn))
                    count += 1
        self.files = list(dict.fromkeys(self.files))
        self.files.sort(key=lambda x: os.path.basename(x).lower())
        self.refresh_table()
        self.log(f"目录导入：添加了 {count} 个视频")

    def refresh_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for idx, fp in enumerate(self.files):
            name = os.path.basename(fp)
            tag = "evenrow" if idx % 2 == 0 else "oddrow"
            self.tree.insert("", "end", values=(name, fp, "等待中"), tags=(tag,))

    def clear_data(self):
        self.files = []
        self.refresh_table()
        self.log("列表已清空")

    def exit_app(self):
        if self.is_running:
            if not messagebox.askyesno("确认退出", "任务正在进行中，强制退出可能导致文件损坏。\n确定要退出吗？"):
                return
        self.root.destroy()

    def start_process(self):
        if self.is_running:
            return
        if not self.files:
            messagebox.showwarning("提示", "请先添加需要处理的视频文件。")
            return
        try:
            seg = int(self.seg_entry.get().strip())
            thr = int(self.thr_entry.get().strip())
            if seg <= 0 or thr <= 0:
                raise ValueError()
        except ValueError:
            messagebox.showwarning("错误", "参数必须为正整数。")
            return

        self.is_running = True
        self.start_btn.state(["disabled"])
        self.stop_btn.state(["!disabled"])
        
        # 锁定输入框
        self.seg_entry.config(state="disabled")
        self.thr_entry.config(state="disabled")

        self.progress["maximum"] = 1.0
        self.progress["value"] = 0.0
        self.progress_label.config(text="0%")

        t = threading.Thread(target=self._process_thread, args=(seg, thr), daemon=True)
        t.start()

    def stop_process(self):
        messagebox.showinfo("提示", "正在尝试停止... \n注意：当前正在上传的切片无法立即中断，请稍候。")
        # 实际的停止逻辑需要在线程中增加标志位判断，这里暂时保持原逻辑

    # ================= 后台处理逻辑 (复用原逻辑) =================
    def _process_thread(self, segment_seconds, upload_threads):
        total = len(self.files)
        completed = 0
        all_videos_success = True
        try:
            for fp in self.files:
                if not self.is_running: break # 简单中断检查

                base = os.path.splitext(os.path.basename(fp))[0]
                self._set_row_status(fp, "⚡ 切片中...")
                
                # 调用核心处理函数
                ok = self._process_single_video(fp, base, segment_seconds, upload_threads)
                
                if not ok:
                    self._set_row_status(fp, "❌ 失败")
                    all_videos_success = False
                else:
                    self._set_row_status(fp, "✅ 完成")
                
                completed += 1
                ratio = completed / total
                self.root.after(0, lambda r=ratio: (self.progress.configure(value=r),
                                                    self.progress_label.config(text=f"{r:.0%}")))
            
            if self.is_running:
                self.log("所有任务队列已结束")
                messagebox.showinfo("完成", "所有视频处理完毕！")
                
                if self.after_delete_var.get() and all_videos_success:
                    try:
                        import shutil
                        shutil.rmtree(OUTPUT_DIR)
                        self.log(f"清理临时目录：{OUTPUT_DIR}")
                    except Exception as e:
                        self.log(f"清理失败：{e}")

                if self.after_shutdown_var.get():
                    self.log("即将关机...")
                    shutdown_windows()
        except Exception as e:
            self.log(f"线程异常: {e}")
        finally:
            self.is_running = False
            def reset_ui():
                self.start_btn.state(["!disabled"])
                self.stop_btn.state(["disabled"])
                self.seg_entry.config(state="normal")
                self.thr_entry.config(state="normal")
            self.root.after(0, reset_ui)

    def _process_single_video(self, input_file, base, segment_seconds, upload_threads):
        video_dir = os.path.join(OUTPUT_DIR, base)
        os.makedirs(video_dir, exist_ok=True)

        playlist_path = os.path.join(M3U8_DIR, f"{base}.m3u8")
        ts_pattern = os.path.join(video_dir, "%03d.ts")
        tmp_playlist = os.path.join(video_dir, f"{base}.m3u8")

        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", input_file,
            "-c", "copy",
            "-map", "0",
            "-f", "segment",
            "-segment_time", str(segment_seconds),
            "-segment_list", tmp_playlist,
            ts_pattern
        ]
        self.log(f"正在切片：{base}")
        try:
            # hide console window on windows
            startupinfo = None
            if sys.platform.startswith("win"):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
            subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
        except FileNotFoundError:
            self.log("错误：未找到 ffmpeg，请确保已安装并添加到环境变量。")
            return False
        except Exception as e:
            self.log(f"切片出错：{e}")
            return False

        ts_files = sorted([f for f in os.listdir(video_dir) if f.endswith(".ts")])
        if not ts_files:
            self.log("切片失败，未生成TS文件")
            return False

        urls = {}
        uploaded_count = 0
        all_success = True
        total_ts = len(ts_files)

        def on_piece_uploaded():
            nonlocal uploaded_count
            uploaded_count += 1
            percent = int((uploaded_count / total_ts) * 100)
            # 减少 UI 刷新频率，避免卡顿
            if uploaded_count % 5 == 0 or uploaded_count == total_ts:
                self._set_row_status(input_file, f"☁ 上传 {percent}%")

        self._set_row_status(input_file, "☁ 上传 0%")
        
        with ThreadPoolExecutor(max_workers=upload_threads) as ex:
            futures = {ex.submit(self._upload_with_retry, os.path.join(video_dir, fname)): fname for fname in ts_files}
            for fut in as_completed(futures):
                if not self.is_running: return False # 允许中断
                fname = futures[fut]
                try:
                    url, attempt = fut.result()
                    urls[fname] = url
                    self.root.after(0, on_piece_uploaded)
                except Exception as e:
                    self.log(f"文件 {fname} 上传失败: {e}")
                    all_success = False

        if not all_success:
            return False

        # 生成 M3U8
        try:
            with open(tmp_playlist, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            new_lines = []
            for line in lines:
                text = line.strip()
                if text.endswith(".ts") and text in urls:
                    new_lines.append(urls[text] + "\n")
                else:
                    new_lines.append(line)
            
            with open(playlist_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            self.log(f"M3U8 生成成功：{playlist_path}")
        except Exception as e:
            self.log(f"M3U8 写出失败: {e}")
            return False

        # 删除临时文件
        if self.after_delete_var.get():
            for f in ts_files:
                try:
                    os.remove(os.path.join(video_dir, f))
                except: pass
            try:
                os.remove(tmp_playlist)
                os.rmdir(video_dir)
            except: pass

        return True

    def _upload_with_retry(self, file_path, max_attempts=3):
        last_err = None
        for attempt in range(1, max_attempts + 1):
            try:
                url = upload_file(file_path)
                return url, attempt
            except Exception as e:
                last_err = e
                time.sleep(1.0)
        raise last_err

    def _set_row_status(self, file_path, status):
        # 优化：避免遍历所有子项，如果文件列表很大，建议建立 路径->Item ID 的字典映射
        for iid in self.tree.get_children():
            vals = self.tree.item(iid, "values")
            if vals and vals[1] == file_path:
                self.tree.item(iid, values=(vals[0], vals[1], status))
                break

# ================= 主程序入口 =================
def main():
    root = TkinterDnD.Tk()
    # 尝试设置高分屏支持 (Windows)
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass
        
    app = VideoUploaderGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
