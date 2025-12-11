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

# 颜色配置 (现代配色)
COLOR_BG = "#F5F7FA"          # 整体背景淡灰
COLOR_WHITE = "#FFFFFF"
COLOR_PRIMARY = "#2563EB"     # 主色调 蓝
COLOR_PRIMARY_HOVER = "#1D4ED8"
COLOR_DANGER = "#DC2626"      # 危险色 红
COLOR_DANGER_HOVER = "#B91C1C"
COLOR_TEXT = "#1F2937"        # 深灰字体
COLOR_TEXT_LIGHT = "#6B7280"  # 浅灰字体
COLOR_BORDER = "#E5E7EB"      # 边框色
COLOR_CONSOLE_BG = "#1E1E1E"  # 日志深色背景
COLOR_CONSOLE_FG = "#10B981"  # 日志绿色字体

# ================= 核心逻辑部分 (保持不变) =================
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

# ================= 界面 GUI 部分 (重构) =================
class VideoUploaderGUI:
    def __init__(self, root):
        self.root = root
        self.center_window(1100, 720)
        self.root.title("批量视频切片上传工具 Pro")
        self.root.configure(bg=COLOR_BG)

        ensure_dirs()
        self._setup_styles() # 初始化样式

        self.files = []
        self.log_q = queue.Queue()
        self.is_running = False

        # --- 主容器 ---
        main_container = ttk.Frame(root, style="Main.TFrame")
        main_container.pack(fill="both", expand=True, padx=20, pady=20)

        # === 上半部分：左右布局 ===
        top_area = ttk.Frame(main_container, style="Main.TFrame")
        top_area.pack(fill="both", expand=True)

        # --- 左侧：文件列表 ---
        left_panel = ttk.Frame(top_area, style="Main.TFrame")
        left_panel.pack(side="left", fill="both", expand=True, padx=(0, 15))

        # 标题栏
        lbl_title = ttk.Label(left_panel, text="任务列表", font=("Microsoft YaHei", 12, "bold"), foreground=COLOR_TEXT)
        lbl_title.pack(anchor="w", pady=(0, 10))

        # 表格区域 (带滚动条)
        tree_frame = ttk.Frame(left_panel)
        tree_frame.pack(fill="both", expand=True)
        
        columns = ("name", "path", "status")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=15, selectmode="extended")
        
        # 滚动条
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        # 表头与列设置
        self.tree.heading("name", text="文件名")
        self.tree.heading("path", text="完整路径")
        self.tree.heading("status", text="当前状态")
        self.tree.column("name", width=220, anchor="w")
        self.tree.column("path", width=380, anchor="w")
        self.tree.column("status", width=120, anchor="center")
        
        # 拖拽与菜单
        self.tree.drop_target_register(DND_FILES)
        self.tree.dnd_bind("<<Drop>>", self.on_drop)
        self.create_context_menu()

        # 进度条区域
        prog_frame = ttk.Frame(left_panel, style="Main.TFrame")
        prog_frame.pack(fill="x", pady=(15, 5))
        
        prog_info_frame = ttk.Frame(prog_frame, style="Main.TFrame")
        prog_info_frame.pack(fill="x", pady=(0, 5))
        ttk.Label(prog_info_frame, text="总进度", font=("Microsoft YaHei", 9), foreground=COLOR_TEXT_LIGHT).pack(side="left")
        self.progress_label = ttk.Label(prog_info_frame, text="0%", font=("Microsoft YaHei", 9, "bold"), foreground=COLOR_PRIMARY)
        self.progress_label.pack(side="right")

        self.progress = ttk.Progressbar(prog_frame, orient="horizontal", mode="determinate", style="Thinking.Horizontal.TProgressbar")
        self.progress.pack(fill="x", ipady=2) # ipady让进度条变厚

        # 左侧按钮栏 (次要操作)
        action_bar = ttk.Frame(left_panel, style="Main.TFrame")
        action_bar.pack(fill="x", pady=10)
        
        self.btn_add = ttk.Button(action_bar, text="📂 选择目录", style="Secondary.TButton", command=self.choose_dir)
        self.btn_add.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        self.btn_clear = ttk.Button(action_bar, text="🗑️ 清空列表", style="Secondary.TButton", command=self.clear_data)
        self.btn_clear.pack(side="left", fill="x", expand=True, padx=(5, 0))


        # --- 右侧：控制面板 ---
        right_panel = ttk.Frame(top_area, style="Card.TFrame", padding=20)
        right_panel.pack(side="right", fill="y", padx=(5, 0))
        right_panel.pack_propagate(False)
        right_panel.config(width=320) # 固定宽度

        # 参数设置区
        ttk.Label(right_panel, text="参数配置", font=("Microsoft YaHei", 12, "bold"), foreground=COLOR_TEXT).pack(anchor="w", pady=(0, 15))

        # 使用 Grid 布局参数
        param_grid = ttk.Frame(right_panel, style="Card.TFrame")
        param_grid.pack(fill="x")

        ttk.Label(param_grid, text="切片间隔 (s):", style="Param.TLabel").grid(row=0, column=0, sticky="w", pady=8)
        self.seg_entry = ttk.Entry(param_grid, width=10, font=("Microsoft YaHei", 10))
        self.seg_entry.insert(0, str(DEFAULT_SEGMENT_SECONDS))
        self.seg_entry.grid(row=0, column=1, sticky="e", pady=8)

        ttk.Label(param_grid, text="上传线程数:", style="Param.TLabel").grid(row=1, column=0, sticky="w", pady=8)
        self.thr_entry = ttk.Entry(param_grid, width=10, font=("Microsoft YaHei", 10))
        self.thr_entry.insert(0, str(DEFAULT_UPLOAD_THREADS))
        self.thr_entry.grid(row=1, column=1, sticky="e", pady=8)

        ttk.Separator(right_panel, orient="horizontal").pack(fill="x", pady=20)

        # 选项
        self.after_delete_var = tk.BooleanVar(value=False)
        self.after_shutdown_var = tk.BooleanVar(value=False)
        
        chk_del = ttk.Checkbutton(right_panel, text="上传完成后删除切片", variable=self.after_delete_var, style="Custom.TCheckbutton")
        chk_del.pack(anchor="w", pady=5)
        
        chk_off = ttk.Checkbutton(right_panel, text="任务完成后自动关机", variable=self.after_shutdown_var, style="Custom.TCheckbutton")
        chk_off.pack(anchor="w", pady=5)

        ttk.Separator(right_panel, orient="horizontal").pack(fill="x", pady=20)

        # 大按钮区域
        self.start_btn = ttk.Button(right_panel, text="▶ 开始处理", style="Primary.TButton", command=self.start_process)
        self.start_btn.pack(fill="x", pady=(0, 10), ipady=5)

        self.stop_btn = ttk.Button(right_panel, text="⏹ 停止任务", style="Danger.TButton", command=self.stop_process)
        self.stop_btn.pack(fill="x", pady=(0, 10), ipady=5)
        self.stop_btn.state(["disabled"])

        spacer = ttk.Frame(right_panel, style="Card.TFrame")
        spacer.pack(fill="both", expand=True) # 占位符，把退出按钮顶到底部

        ttk.Button(right_panel, text="退出程序", style="Secondary.TButton", command=self.exit_app).pack(fill="x")

        # === 下半部分：日志 ===
        log_frame = ttk.LabelFrame(main_container, text=" 运行日志 ", style="Log.TLabelframe", padding=(2, 2, 2, 2))
        log_frame.pack(fill="both", expand=True, pady=(20, 0))
        # 限制日志高度
        log_frame.config(height=180) 

        self.log_text = tk.Text(
            log_frame,
            height=8,
            bg=COLOR_CONSOLE_BG,
            fg=COLOR_CONSOLE_FG,
            font=("Consolas", 10),
            state="disabled",
            relief="flat",
            padx=10,
            pady=10,
            insertbackground="white" # 光标颜色
        )
        self.log_text.pack(fill="both", expand=True)

        self._schedule_log_drain()

    def _setup_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam") # clam 引擎最容易自定义颜色
        except:
            pass
        
        # 通用背景
        style.configure("Main.TFrame", background=COLOR_BG)
        style.configure("Card.TFrame", background=COLOR_WHITE, relief="flat") # 右侧卡片背景

        # Label 样式
        style.configure("TLabel", background=COLOR_BG, foreground=COLOR_TEXT, font=("Microsoft YaHei", 10))
        style.configure("Param.TLabel", background=COLOR_WHITE, foreground=COLOR_TEXT)
        style.configure("Custom.TCheckbutton", background=COLOR_WHITE, foreground=COLOR_TEXT, font=("Microsoft YaHei", 10))

        # --- 按钮样式 ---
        # 1. 主要按钮 (Primary - Blue)
        style.configure("Primary.TButton",
                        font=("Microsoft YaHei", 11, "bold"),
                        background=COLOR_PRIMARY,
                        foreground="white",
                        borderwidth=0,
                        focuscolor=COLOR_PRIMARY)
        style.map("Primary.TButton",
                  background=[("active", COLOR_PRIMARY_HOVER), ("disabled", "#9CA3AF")])

        # 2. 危险按钮 (Danger - Red)
        style.configure("Danger.TButton",
                        font=("Microsoft YaHei", 11),
                        background=COLOR_DANGER,
                        foreground="white",
                        borderwidth=0,
                        focuscolor=COLOR_DANGER)
        style.map("Danger.TButton",
                  background=[("active", COLOR_DANGER_HOVER), ("disabled", "#FCA5A5")])

        # 3. 次要按钮 (Secondary - White/Gray)
        style.configure("Secondary.TButton",
                        font=("Microsoft YaHei", 10),
                        background=COLOR_WHITE,
                        foreground=COLOR_TEXT,
                        borderwidth=1,
                        bordercolor="#D1D5DB",
                        relief="solid")
        style.map("Secondary.TButton",
                  background=[("active", "#F3F4F6"), ("pressed", "#E5E7EB")])

        # --- Treeview 表格样式 ---
        style.configure("Treeview", 
                        background=COLOR_WHITE,
                        fieldbackground=COLOR_WHITE,
                        foreground=COLOR_TEXT,
                        font=("Microsoft YaHei", 10),
                        rowheight=30, # 增加行高
                        borderwidth=0)
        style.map("Treeview", background=[("selected", "#E0F2FE")], foreground=[("selected", COLOR_PRIMARY)])
        
        style.configure("Treeview.Heading", 
                        font=("Microsoft YaHei", 10, "bold"),
                        background="#F3F4F6", 
                        foreground=COLOR_TEXT,
                        relief="flat")

        # --- 进度条 ---
        style.configure("Thinking.Horizontal.TProgressbar",
                        troughcolor="#E5E7EB",
                        background=COLOR_PRIMARY,
                        bordercolor="#E5E7EB",
                        lightcolor=COLOR_PRIMARY, 
                        darkcolor=COLOR_PRIMARY)
        
        # --- LabelFrame ---
        style.configure("Log.TLabelframe", background=COLOR_BG, bordercolor=COLOR_BORDER)
        style.configure("Log.TLabelframe.Label", background=COLOR_BG, foreground=COLOR_TEXT_LIGHT, font=("Microsoft YaHei", 9))

    def center_window(self, width, height):
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def create_context_menu(self):
        self.menu = tk.Menu(self.root, tearoff=0, bg="white", fg=COLOR_TEXT, relief="flat", font=("Microsoft YaHei", 10))
        self.menu.add_command(label="➕ 添加文件", command=self.add_file)
        self.menu.add_separator()
        self.menu.add_command(label="❌ 删除选中", command=self.delete_selected)
        self.tree.bind("<Button-3>", self.show_context_menu)

    # 日志
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

    # 拖拽事件
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

    # 右键菜单
    def show_context_menu(self, event):
        row_id = self.tree.identify_row(event.y)
        if row_id:
            # 如果点的不是当前选中的，就选中它
            if row_id not in self.tree.selection():
                self.tree.selection_set(row_id)
            self.menu.entryconfig("❌ 删除选中", state="normal")
        else:
            self.menu.entryconfig("❌ 删除选中", state="disabled")
        self.menu.post(event.x_root, event.y_root)

    def add_file(self):
        filetypes = [("视频文件", "*.mp4 *.mkv *.ts")]
        fps = filedialog.askopenfilenames(title="选择视频文件", filetypes=filetypes) # 支持多选
        if fps:
            for fp in fps:
                if fp.lower().endswith(VIDEO_EXTS):
                    self.files.append(fp)
            self.files = list(dict.fromkeys(self.files))
            self.refresh_table()
            self.log(f"添加 {len(fps)} 个文件")

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
        self.log(f"删除 {len(selected)} 个文件")

    def choose_dir(self):
        d = filedialog.askdirectory(title="选择视频目录")
        if not d:
            return
        self.files = []
        for rootdir, _, filenames in os.walk(d):
            for fn in filenames:
                if fn.lower().endswith(VIDEO_EXTS):
                    self.files.append(os.path.join(rootdir, fn))
        self.files.sort(key=lambda x: os.path.basename(x).lower())
        self.refresh_table()
        self.log(f"已加载目录，共 {len(self.files)} 个视频")

    def refresh_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for idx, fp in enumerate(self.files):
            name = os.path.basename(fp)
            # 奇偶行颜色交替由Treeview style处理，这里直接插
            self.tree.insert("", "end", values=(name, fp, "等待处理"))

    def clear_data(self):
        self.files = []
        self.refresh_table()
        self.log("列表已清空")

    def exit_app(self):
        if self.is_running:
            if not messagebox.askyesno("确认退出", "任务正在进行中，强制退出可能导致数据不完整。\n确定要退出吗？"):
                return
        self.root.destroy()

    def start_process(self):
        if self.is_running:
            return
        if not self.files:
            messagebox.showwarning("提示", "列表为空，请先添加视频文件。")
            return
        try:
            seg = int(self.seg_entry.get().strip())
            thr = int(self.thr_entry.get().strip())
            if seg <= 0 or thr <= 0:
                raise ValueError()
        except ValueError:
            messagebox.showwarning("参数错误", "切片间隔和线程数必须为正整数。")
            return

        self.is_running = True
        self.start_btn.state(["disabled"])
        self.stop_btn.state(["!disabled"])
        self.btn_add.state(["disabled"])
        self.btn_clear.state(["disabled"])

        self.progress["maximum"] = 1.0
        self.progress["value"] = 0.0
        self.progress_label.config(text="0%")

        t = threading.Thread(target=self._process_thread, args=(seg, thr), daemon=True)
        t.start()

    def stop_process(self):
        messagebox.showinfo("提示", "程序逻辑当前不支持强行中断 FFmpeg/上传。\n请等待当前单个视频完成后，关闭程序重试。")

    def _process_thread(self, segment_seconds, upload_threads):
        total = len(self.files)
        completed = 0
        all_videos_success = True
        
        self.log("-" * 40)
        self.log(f"任务开始：共 {total} 个视频")

        try:
            for fp in self.files:
                base = os.path.splitext(os.path.basename(fp))[0]
                self._set_row_status(fp, "⚡ 切片中...")
                
                # 滚动到当前行
                self._focus_row(fp)

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
            else:
                self.log("所有任务队列执行完毕")
                messagebox.showinfo("完成", "全部视频处理完成！")

                if self.after_delete_var.get() and all_videos_success:
                    try:
                        import shutil
                        shutil.rmtree(OUTPUT_DIR)
                        self.log(f"清理临时目录：{OUTPUT_DIR}")
                    except Exception as e:
                        self.log(f"清理失败：{e}")

                if self.after_shutdown_var.get():
                    self.log("准备关机...")
                    shutdown_windows()
        finally:
            self.is_running = False
            self.root.after(0, self._reset_ui_state)

    def _reset_ui_state(self):
        self.start_btn.state(["!disabled"])
        self.stop_btn.state(["disabled"])
        self.btn_add.state(["!disabled"])
        self.btn_clear.state(["!disabled"])

    def _focus_row(self, file_path):
        for iid in self.tree.get_children():
            vals = self.tree.item(iid, "values")
            if vals and vals[1] == file_path:
                self.tree.see(iid)
                self.tree.selection_set(iid)
                break

    # 单视频处理逻辑 (FFmpeg + Upload)
    def _process_single_video(self, input_file, base, segment_seconds, upload_threads):
        video_dir = os.path.join(OUTPUT_DIR, base)
        os.makedirs(video_dir, exist_ok=True)

        playlist_path = os.path.join(M3U8_DIR, f"{base}.m3u8")
        ts_pattern = os.path.join(video_dir, "%03d.ts")
        tmp_playlist = os.path.join(video_dir, f"{base}.m3u8")

        # 1. 切片
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
            # startupinfo 用于隐藏 Windows 下的 ffmpeg 黑框
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
            subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
        except FileNotFoundError:
            self.log("❌ 错误：未找到 ffmpeg，请检查环境变量。")
            return False
        except subprocess.CalledProcessError as e:
            self.log(f"❌ 切片出错：{e}")
            return False
        except Exception as e:
            self.log(f"❌ 未知错误：{e}")
            return False

        ts_files = sorted([f for f in os.listdir(video_dir) if f.endswith(".ts")])
        if not ts_files:
            self.log("❌ 切片后未发现 TS 文件")
            return False

        # 2. 上传
        urls = {}
        uploaded_count = 0
        all_success = True
        total_ts = len(ts_files)

        def on_piece_uploaded(fname):
            nonlocal uploaded_count
            uploaded_count += 1
            percent = int((uploaded_count / total_ts) * 100)
            self._set_row_status(input_file, f"上传 {percent}%")
            self.log(f"上传进度 [{uploaded_count}/{total_ts}]: {fname}")

        self._set_row_status(input_file, "🚀 上传中...")
        
        with ThreadPoolExecutor(max_workers=upload_threads) as ex:
            futures = {ex.submit(self._upload_with_retry, os.path.join(video_dir, fname)): fname for fname in ts_files}
            for fut in as_completed(futures):
                fname = futures[fut]
                try:
                    url, _ = fut.result()
                    urls[fname] = url
                    self.root.after(0, lambda n=fname: on_piece_uploaded(n))
                except Exception:
                    self.log(f"❌ 文件最终上传失败：{fname}")
                    all_success = False

        # 3. 生成 m3u8
        if not os.path.exists(tmp_playlist):
             self.log("❌ 原始 m3u8 文件丢失")
             return False

        try:
            with open(tmp_playlist, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            new_lines = []
            for line in lines:
                text = line.strip()
                if text.endswith(".ts"):
                    if text in urls:
                        new_lines.append(urls[text] + "\n")
                    else:
                        # 失败的保留原样或做标记
                        new_lines.append(line) 
                else:
                    new_lines.append(line)
            
            with open(playlist_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            self.log(f"✨ m3u8 生成完毕：{playlist_path}")
        except Exception as e:
            self.log(f"❌ 写 m3u8 失败：{e}")
            return False

        # 4. 清理子文件夹
        if self.after_delete_var.get() and all_success:
            try:
                for f in ts_files:
                    os.remove(os.path.join(video_dir, f))
                if os.path.exists(tmp_playlist):
                    os.remove(tmp_playlist)
                os.rmdir(video_dir)
                self.log(f"已清理临时切片：{base}")
            except Exception as e:
                self.log(f"清理临时文件出错：{e}")

        return all_success

    def _upload_with_retry(self, file_path, max_attempts=3):
        for attempt in range(1, max_attempts + 1):
            try:
                url = upload_file(file_path)
                return url, attempt
            except Exception as e:
                if attempt == max_attempts:
                    raise e
                time.sleep(1.0) # 失败等待1秒

    def _set_row_status(self, file_path, status):
        # 在主线程更新UI
        self.root.after(0, lambda: self._update_tree_item(file_path, status))

    def _update_tree_item(self, file_path, status):
        for iid in self.tree.get_children():
            vals = self.tree.item(iid, "values")
            if vals and vals[1] == file_path:
                self.tree.item(iid, values=(vals[0], vals[1], status))
                break

if __name__ == "__main__":
    # 高分屏适配 (Windows)
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass

    root = TkinterDnD.Tk()
    app = VideoUploaderGUI(root)
    root.mainloop()
