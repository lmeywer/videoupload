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

# ================= 视觉配色 =================
COLOR_BG_MAIN = "#F2F6FC"       # 窗口大背景
COLOR_CARD_BG = "#FFFFFF"       # 卡片背景
COLOR_BORDER_BLUE = "#3399ff"   # 核心蓝色边框
COLOR_BORDER_GRAY = "#DCDFE6"   # 退出按钮/普通边框

# 按钮颜色
COLOR_BTN_START = "#409EFF"     # 现代蓝
COLOR_BTN_START_HOVER = "#66b1ff"
COLOR_BTN_STOP = "#F56C6C"      # 现代红
COLOR_BTN_STOP_HOVER = "#f78989"

# 进度条
COLOR_PROG_BAR = "#3399ff"

# 日志
COLOR_LOG_BG = "#1E1E1E"
COLOR_LOG_FG = "#00FF00"

# ================= 核心逻辑 =================
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

def ensure_m3u8_dir():
    # 只预先创建m3u8目录，切片目录在开始处理时创建
    os.makedirs(M3U8_DIR, exist_ok=True)

# ================= GUI 界面类 =================
class VideoUploaderGUI:
    def __init__(self, root):
        self.root = root
        self.center_window(1000, 720)
        self.root.title("批量视频切片上传工具 Pro")
        self.root.configure(bg=COLOR_BG_MAIN)

        ensure_m3u8_dir()
        self._setup_styles()

        self.files = []
        self.log_q = queue.Queue()
        self.is_running = False

        # === 主布局容器 ===
        top_container = tk.Frame(root, bg=COLOR_BG_MAIN)
        top_container.pack(side="top", fill="both", expand=True, padx=20, pady=20)

        # ---------------------------------------------------------
        # 左侧卡片：任务列表
        # ---------------------------------------------------------
        left_card = tk.Frame(top_container, bg=COLOR_CARD_BG, 
                             highlightbackground=COLOR_BORDER_BLUE, highlightthickness=1)
        left_card.pack(side="left", fill="both", expand=True, padx=(0, 15))

        # 1. 顶部工具栏
        header_frame = tk.Frame(left_card, bg=COLOR_CARD_BG, height=50)
        header_frame.pack(fill="x", padx=15, pady=15)

        tk.Label(header_frame, text="任务列表", font=("Microsoft YaHei", 12, "bold"), 
                 bg=COLOR_CARD_BG, fg="black").pack(side="left")

        btn_box = tk.Frame(header_frame, bg=COLOR_CARD_BG)
        btn_box.pack(side="right")

        self._create_outline_btn(btn_box, "🗑 清空列表", self.clear_data)
        self._create_outline_btn(btn_box, "📄 添加文件", self.add_file)
        self._create_outline_btn(btn_box, "📂 添加目录", self.choose_dir)

        # 2. 表格区域
        # 【关键修复】蓝色容器只负责显示1px的蓝色边框
        table_border = tk.Frame(left_card, bg=COLOR_BORDER_BLUE, padx=1, pady=1)
        table_border.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        columns = ("name", "path", "status")
        # 【关键修复】bd=0 去除Treeview自身边框，避免与外层蓝色重叠
        self.tree = ttk.Treeview(table_border, columns=columns, show="headings", 
                                 selectmode="extended", style="Custom.Treeview", bd=0)
        
        vsb = ttk.Scrollbar(table_border, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        self.tree.heading("name", text="文件名")
        self.tree.heading("path", text="完整路径")
        self.tree.heading("status", text="当前状态")
        self.tree.column("name", width=200, anchor="w")
        self.tree.column("path", width=350, anchor="w")
        self.tree.column("status", width=120, anchor="center")

        self.tree.tag_configure("evenrow", background="#f2f8ff")
        self.tree.tag_configure("oddrow", background="#FFFFFF")

        self.tree.drop_target_register(DND_FILES)
        self.tree.dnd_bind("<<Drop>>", self.on_drop)
        
        self.menu = tk.Menu(root, tearoff=0, bg="white", fg="black")
        self.menu.add_command(label="删除选中", command=self.delete_selected)
        self.tree.bind("<Button-3>", self.show_context_menu)

        # 3. 底部进度条
        footer_frame = tk.Frame(left_card, bg="#FAFAFA", height=45)
        footer_frame.pack(fill="x", side="bottom")
        
        tk.Label(footer_frame, text="总进度:", bg="#FAFAFA", fg="black", 
                 font=("Microsoft YaHei", 9)).pack(side="left", padx=(15, 5), pady=12)
        
        self.progress = ttk.Progressbar(footer_frame, orient="horizontal", mode="determinate", 
                                        style="Blue.Horizontal.TProgressbar")
        self.progress.pack(side="left", fill="x", expand=True, padx=5, pady=12)
        
        self.progress_label = tk.Label(footer_frame, text="0%", bg="#FAFAFA", fg="black", 
                                       font=("Microsoft YaHei", 9, "bold"))
        self.progress_label.pack(side="right", padx=(5, 15), pady=12)


        # ---------------------------------------------------------
        # 右侧卡片：参数与控制
        # ---------------------------------------------------------
        right_card = tk.Frame(top_container, bg=COLOR_CARD_BG, width=280, 
                              highlightbackground=COLOR_BORDER_BLUE, highlightthickness=1)
        right_card.pack(side="right", fill="y")
        right_card.pack_propagate(False)

        tk.Label(right_card, text="⚙ 参数设置", font=("Microsoft YaHei", 12, "bold"), 
                 bg=COLOR_CARD_BG, fg="black").pack(anchor="w", padx=20, pady=20)

        form_frame = tk.Frame(right_card, bg=COLOR_CARD_BG)
        form_frame.pack(fill="x", padx=20)

        # 输入框配置：居中，蓝色边框，无焦点变色
        entry_conf = {
            "font": ("Microsoft YaHei", 10),
            "highlightbackground": COLOR_BORDER_BLUE,
            "highlightcolor": COLOR_BORDER_BLUE,
            "highlightthickness": 1,
            "relief": "flat",
            "justify": "center"
        }

        tk.Label(form_frame, text="切片间隔 (秒):", bg=COLOR_CARD_BG, fg="black", font=("Microsoft YaHei", 10)).grid(row=0, column=0, sticky="w", pady=8)
        self.seg_entry = tk.Entry(form_frame, width=8, **entry_conf)
        self.seg_entry.insert(0, str(DEFAULT_SEGMENT_SECONDS))
        self.seg_entry.grid(row=0, column=1, sticky="e", pady=8)

        tk.Label(form_frame, text="上传线程数:", bg=COLOR_CARD_BG, fg="black", font=("Microsoft YaHei", 10)).grid(row=1, column=0, sticky="w", pady=8)
        self.thr_entry = tk.Entry(form_frame, width=8, **entry_conf)
        self.thr_entry.insert(0, str(DEFAULT_UPLOAD_THREADS))
        self.thr_entry.grid(row=1, column=1, sticky="e", pady=8)

        # 分割线
        tk.Frame(right_card, bg=COLOR_BORDER_BLUE, height=1).pack(fill="x", padx=20, pady=20)

        # === 按钮区域 ===
        # 1. 开始处理
        self.start_btn = tk.Button(right_card, text="▶ 开始处理", bg=COLOR_BTN_START, fg="white",
                                   font=("Microsoft YaHei", 12, "bold"), relief="flat",
                                   activebackground=COLOR_BTN_START_HOVER, activeforeground="white",
                                   cursor="hand2", command=self.start_process)
        self.start_btn.pack(fill="x", padx=20, pady=(5, 10), ipady=8)

        # 2. 停止任务
        self.stop_btn = tk.Button(right_card, text="■ 停止任务", bg=COLOR_BTN_STOP, fg="white",
                                  font=("Microsoft YaHei", 12, "bold"), relief="flat",
                                  activebackground=COLOR_BTN_STOP_HOVER, activeforeground="white",
                                  state="disabled", cursor="arrow", command=self.stop_process)
        self.stop_btn.pack(fill="x", padx=20, pady=(0, 10), ipady=8)

        # 3. 退出程序 (修复：白底，灰色实线边框，不同于外围蓝色)
        tk.Button(right_card, text="退出程序", bg="white", fg="black",
                  font=("Microsoft YaHei", 10), 
                  relief="solid", bd=1,             # 灰色细实线边框
                  activebackground="#f2f2f2", 
                  cursor="hand2",
                  command=self.exit_app).pack(fill="x", padx=20, pady=(10, 10), ipady=4)

        tk.Label(right_card, text="提示: 拖拽文件夹可快速添加", bg=COLOR_CARD_BG, fg="#909399", 
                 font=("Microsoft YaHei", 8)).pack(side="bottom", pady=20)


        # ---------------------------------------------------------
        # 底部日志
        # ---------------------------------------------------------
        log_container = tk.Frame(root, bg="white", height=160,
                                 highlightbackground=COLOR_BORDER_BLUE, highlightthickness=1)
        log_container.pack(side="bottom", fill="x", padx=20, pady=(0, 20))
        log_container.pack_propagate(False)

        log_header = tk.Frame(log_container, bg="#E9EEF3", height=28)
        log_header.pack(fill="x")
        tk.Label(log_header, text=" 📄 运行日志", bg="#E9EEF3", fg="black", 
                 font=("Microsoft YaHei", 9, "bold")).pack(side="left")

        self.log_text = tk.Text(log_container, bg=COLOR_LOG_BG, fg=COLOR_LOG_FG,
                                font=("Consolas", 10), relief="flat", padx=10, pady=5, state="disabled")
        self.log_text.pack(fill="both", expand=True)

        self._schedule_log_drain()

    def _create_outline_btn(self, parent, text, command):
        btn = tk.Button(parent, text=text, font=("Microsoft YaHei", 9), width=10,
                        bg="white", fg="black",
                        relief="flat", bd=0,
                        highlightbackground=COLOR_BORDER_BLUE, highlightthickness=1,
                        highlightcolor=COLOR_BORDER_BLUE,
                        activebackground="#ecf5ff", 
                        cursor="hand2", command=command)
        btn.pack(side="right", padx=5)

    def _setup_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except:
            pass
        
        # 树形列表样式
        style.configure("Custom.Treeview", 
                        background="white",
                        fieldbackground="white",
                        foreground="black",
                        font=("Microsoft YaHei", 10),
                        rowheight=32,
                        borderwidth=0) # 关键：去边框
        
        # 【关键修复】表头样式：
        # relief="flat" 去除灰色框，避免与外层蓝框重叠
        # background="#E1E4E8" 加深背景色，区分表头与内容
        style.configure("Custom.Treeview.Heading", 
                        font=("Microsoft YaHei", 9, "bold"),
                        background="#e1e4e8", 
                        foreground="#303133",
                        relief="flat")
        
        style.map("Custom.Treeview.Heading", 
                  background=[("active", "#e1e4e8")], # 移入不变色
                  foreground=[("active", "#303133")])
        
        style.map("Custom.Treeview", background=[("selected", "#cce5ff")], foreground=[("selected", "black")])

        # 蓝色进度条
        style.configure("Blue.Horizontal.TProgressbar",
                        troughcolor="#E6E6E6",
                        background=COLOR_PROG_BAR,
                        lightcolor=COLOR_PROG_BAR, 
                        darkcolor=COLOR_PROG_BAR,
                        bordercolor=COLOR_PROG_BAR)

    def center_window(self, width, height):
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    # ================= 业务逻辑 =================
    def log(self, msg):
        t = time.strftime("[%H:%M:%S]")
        self.log_q.put(f"{t} {msg}")

    def _schedule_log_drain(self):
        while not self.log_q.empty():
            line = self.log_q.get()
            self.log_text.config(state="normal")
            self.log_text.insert("end", line + "\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")
        self.root.after(120, self._schedule_log_drain)

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
            if row_id not in self.tree.selection():
                self.tree.selection_set(row_id)
            self.menu.post(event.x_root, event.y_root)

    def add_file(self):
        fps = filedialog.askopenfilenames(title="选择视频", filetypes=[("视频文件", "*.mp4 *.mkv *.ts")])
        if fps:
            for fp in fps:
                self.files.append(fp)
            self.files = list(dict.fromkeys(self.files))
            self.refresh_table()
            self.log(f"添加 {len(fps)} 个文件")

    def choose_dir(self):
        d = filedialog.askdirectory(title="选择目录")
        if not d: return
        cnt = 0
        for rootdir, _, filenames in os.walk(d):
            for fn in filenames:
                if fn.lower().endswith(VIDEO_EXTS):
                    self.files.append(os.path.join(rootdir, fn))
                    cnt += 1
        self.refresh_table()
        self.log(f"目录添加 {cnt} 个文件")

    def delete_selected(self):
        selected = self.tree.selection()
        for iid in selected:
            vals = self.tree.item(iid, "values")
            if vals and vals[1] in self.files:
                self.files.remove(vals[1])
            self.tree.delete(iid)

    def clear_data(self):
        self.files = []
        self.refresh_table()
        self.log("列表已清空")

    def refresh_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for i, fp in enumerate(self.files):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            self.tree.insert("", "end", values=(os.path.basename(fp), fp, "等待中"), tags=(tag,))

    def exit_app(self):
        if self.is_running:
            if not messagebox.askyesno("警告", "任务进行中，确定退出？"): return
        self.root.destroy()

    def start_process(self):
        if self.is_running or not self.files:
            if not self.files: messagebox.showwarning("提示", "请先添加文件")
            return
        try:
            seg = int(self.seg_entry.get())
            thr = int(self.thr_entry.get())
        except: return

        # 逻辑修改：点击开始后才创建目录
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        
        self.is_running = True
        self.start_btn.config(state="disabled", bg="#a0cfff") 
        self.stop_btn.config(state="normal", bg=COLOR_BTN_STOP)
        self.progress["value"] = 0
        self.progress_label.config(text="0%")
        
        threading.Thread(target=self._process_thread, args=(seg, thr), daemon=True).start()

    def stop_process(self):
        messagebox.showinfo("提示", "当前不支持强行中断，请等待当前文件完成")

    def _process_thread(self, seg, thr):
        total = len(self.files)
        for i, fp in enumerate(self.files):
            base = os.path.splitext(os.path.basename(fp))[0]
            self._update_status(fp, "⚡ 切片中")
            self._focus_row(fp)
            
            ok = self._process_single(fp, base, seg, thr)
            self._update_status(fp, "✅ 完成" if ok else "❌ 失败")
            
            ratio = (i + 1) / total * 100
            self.root.after(0, lambda r=ratio: (self.progress.configure(value=r), self.progress_label.config(text=f"{int(r)}%")))
        
        self.log("全部任务完成")
        
        try:
             import shutil
             if os.path.exists(OUTPUT_DIR):
                shutil.rmtree(OUTPUT_DIR)
             self.log("已清理切片临时目录")
        except: pass
        
        self.is_running = False
        self.root.after(0, self._reset_btn)

    def _reset_btn(self):
        self.start_btn.config(state="normal", bg=COLOR_BTN_START)
        self.stop_btn.config(state="disabled", bg="#ff9999")

    def _update_status(self, fp, status):
        self.root.after(0, lambda: self._tree_set(fp, status))

    def _tree_set(self, fp, status):
        for iid in self.tree.get_children():
            if self.tree.item(iid, "values")[1] == fp:
                self.tree.item(iid, values=(os.path.basename(fp), fp, status))

    def _focus_row(self, fp):
        for iid in self.tree.get_children():
            if self.tree.item(iid, "values")[1] == fp:
                self.root.after(0, lambda: self.tree.see(iid))
                self.root.after(0, lambda: self.tree.selection_set(iid))

    def _process_single(self, input_file, base, seg, thr):
        video_dir = os.path.join(OUTPUT_DIR, base)
        os.makedirs(video_dir, exist_ok=True)
        
        cmd = ["ffmpeg", "-y", "-i", input_file, "-c", "copy", "-map", "0", "-f", "segment", "-segment_time", str(seg), "-segment_list", os.path.join(video_dir, f"{base}.m3u8"), os.path.join(video_dir, "%03d.ts")]
        
        self.log(f"开始切片: {base}")
        try:
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
        except Exception as e:
            self.log(f"切片失败: {e}")
            return False

        ts_files = sorted([f for f in os.listdir(video_dir) if f.endswith(".ts")])
        if not ts_files: return False
        
        self._update_status(input_file, "☁ 上传中")
        urls = {}
        done = 0
        total = len(ts_files)
        
        def _u(fpath):
            for _ in range(3):
                try: return upload_file(fpath)
                except: time.sleep(1)
            raise Exception("Fail")

        with ThreadPoolExecutor(thr) as pool:
            futs = {pool.submit(_u, os.path.join(video_dir, f)): f for f in ts_files}
            for f in as_completed(futs):
                name = futs[f]
                try:
                    urls[name] = f.result()
                    done += 1
                    percent = int(done/total*100)
                    self._update_status(input_file, f"☁ {percent}%")
                    self.log(f"上传成功 [{percent}%]: {name}")
                except: pass
        
        lines = []
        try:
            with open(os.path.join(video_dir, f"{base}.m3u8"), "r", encoding="utf-8") as f:
                for line in f:
                    t = line.strip()
                    if t in urls: lines.append(urls[t]+"\n")
                    else: lines.append(line)
            with open(os.path.join(M3U8_DIR, f"{base}.m3u8"), "w", encoding="utf-8") as f:
                f.writelines(lines)
            
            try:
                for f in ts_files: os.remove(os.path.join(video_dir, f))
                os.rmdir(video_dir)
            except: pass
            return True
        except: return False

if __name__ == "__main__":
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except: pass
    
    root = TkinterDnD.Tk()
    app = VideoUploaderGUI(root)
    root.mainloop()
