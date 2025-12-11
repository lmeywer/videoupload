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


class VideoUploaderGUI:
    def __init__(self, root):
        self.root = root
        self.center_window(1100, 700)
        self.root.title("批量视频切片上传工具")
        self.root.configure(bg="#f0f4f8")

        ensure_dirs()

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        # 按钮样式（有边框与 hover）
        style.configure("TButton",
                        font=("Microsoft YaHei", 11),
                        padding=6,
                        relief="raised",
                        borderwidth=1,
                        background="#f0f4f8",
                        foreground="#333333")
        style.map("TButton",
                  background=[("active", "#e6f2ff")],
                  relief=[("pressed", "sunken")])

        # 停止按钮红色突出
        style.configure("Stop.TButton",
                        font=("Microsoft YaHei", 11),
                        padding=6,
                        relief="raised",
                        borderwidth=1,
                        background="#ffe6e6",
                        foreground="#cc0000")
        style.map("Stop.TButton",
                  background=[("active", "#ffcccc")])

        style.configure("TLabel", font=("Microsoft YaHei", 11),
                        background="#f0f4f8", foreground="#333333")
        style.configure("TEntry", font=("Microsoft YaHei", 11),
                        fieldbackground="white", foreground="#333333")

        # 表格样式 + 斑马纹 + 选中高亮
        style.configure("Treeview", background="white", foreground="#333333",
                        fieldbackground="white", bordercolor="#cccccc", rowheight=24)
        style.map("Treeview", background=[("selected", "#cce5ff")])
        style.layout("Treeview", [('Treeview.treearea', {'sticky': 'nswe'})])

        # 进度条与边框风格
        style.configure("Custom.Horizontal.TProgressbar",
                        troughcolor="#e6f2ff", background="#3399ff",
                        bordercolor="#3399ff", lightcolor="#3399ff", darkcolor="#3399ff")
        style.configure("Custom.TLabelframe", bordercolor="#3399ff", background="#f0f4f8")
        style.configure("Custom.TLabelframe.Label", foreground="#3399ff", background="#f0f4f8")

        self.files = []
        self.log_q = queue.Queue()
        self.is_running = False

        main = ttk.Frame(root, padding=10)
        main.pack(fill="both", expand=True)

        # 左侧文件列表区：使用 LabelFrame 加标题
        left_box = ttk.LabelFrame(main, text="文件列表", padding=8, style="Custom.TLabelframe")
        left_box.pack(side="left", fill="both", expand=True, padx=(0, 10))

        columns = ("name", "path", "status")
        self.tree = ttk.Treeview(left_box, columns=columns, show="headings", height=16)
        self.tree.heading("name", text="文件名")
        self.tree.heading("path", text="路径")
        self.tree.heading("status", text="状态")
        # 保留你的自定义列宽与对齐
        self.tree.column("name", width=200, anchor="w")
        self.tree.column("path", width=420, anchor="w")
        self.tree.column("status", width=60, anchor="center")
        self.tree.pack(fill="both", expand=True)

        # 斑马纹行配置
        self.tree.tag_configure("oddrow", background="#f9f9f9")
        self.tree.tag_configure("evenrow", background="white")

        # 拖拽绑定 + 右键菜单
        self.tree.drop_target_register(DND_FILES)
        self.tree.dnd_bind("<<Drop>>", self.on_drop)
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="添加文件", command=self.add_file)
        self.menu.add_command(label="删除文件", command=self.delete_selected)
        self.tree.bind("<Button-3>", self.show_context_menu)

        # 文件列表下方的总体进度条
        prog_frame = ttk.Frame(left_box)
        prog_frame.pack(fill="x", pady=(10, 4))
        self.progress = ttk.Progressbar(prog_frame, orient="horizontal", mode="determinate",
                                        length=320, style="Custom.Horizontal.TProgressbar")
        self.progress.pack(side="left", fill="x", expand=True)
        self.progress_label = ttk.Label(prog_frame, text="0%")
        self.progress_label.pack(side="left", padx=8)

        # 左侧按钮区
        left_btns = ttk.Frame(left_box)
        left_btns.pack(fill="x", pady=8)
        ttk.Button(left_btns, text="选择目录", command=self.choose_dir).pack(side="left")
        ttk.Button(left_btns, text="清空数据", command=self.clear_data).pack(side="left", padx=8)

        # 右侧参数栏（固定宽度）
        right = ttk.Frame(main)
        right.pack(side="right", fill="y")
        right.config(width=400)  # 保留你的自定义

        param_frame = ttk.LabelFrame(right, text="参数设置", style="Custom.TLabelframe")
        param_frame.pack(fill="x", pady=8)
        ttk.Label(param_frame, text="切片间隔(秒):").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        self.seg_entry = ttk.Entry(param_frame, width=8)
        self.seg_entry.insert(0, str(DEFAULT_SEGMENT_SECONDS))
        self.seg_entry.grid(row=0, column=1, padx=6, pady=6)

        ttk.Label(param_frame, text="上传线程数:").grid(row=1, column=0, sticky="w", padx=6, pady=6)
        self.thr_entry = ttk.Entry(param_frame, width=8)
        self.thr_entry.insert(0, str(DEFAULT_UPLOAD_THREADS))
        self.thr_entry.grid(row=1, column=1, padx=6, pady=6)

        self.after_delete_var = tk.BooleanVar(value=False)
        self.after_shutdown_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(param_frame, text="上传完成后删除切片", variable=self.after_delete_var).grid(row=2, column=0, sticky="w", padx=6, pady=6)
        ttk.Checkbutton(param_frame, text="上传完成后关机", variable=self.after_shutdown_var).grid(row=2, column=1, sticky="w", padx=6, pady=6)

        # 控制区按钮
        ctrl_frame = ttk.Frame(right)
        ctrl_frame.pack(fill="x", pady=12)
        self.start_btn = ttk.Button(ctrl_frame, text="开始处理", command=self.start_process)
        self.start_btn.pack(side="left", padx=6)
        self.stop_btn = ttk.Button(ctrl_frame, text="停止", style="Stop.TButton", command=self.stop_process)
        self.stop_btn.pack(side="left", padx=6)
        self.stop_btn.state(["disabled"])
        ttk.Button(right, text="退出程序", command=self.exit_app).pack(pady=(0, 10))

        # 运行日志区（去掉 Text 的内层边框）
        log_box = ttk.LabelFrame(root, text="运行日志", padding=8, style="Custom.TLabelframe")
        log_box.pack(fill="both", expand=True, padx=10, pady=(4, 6))
        self.log_text = tk.Text(
            log_box,
            height=10,
            wrap="none",
            font=("Consolas", 10),
            state="disabled",
            background="white",
            foreground="#333333",
            relief="flat",
            borderwidth=0
        )
        self.log_text.pack(fill="both", expand=True)

        # 可选：上传进度条（日志区下方，用于分块上传时展示）
        self.upload_progress = ttk.Progressbar(log_box, orient="horizontal",
                                               mode="determinate", length=500,
                                               style="Custom.Horizontal.TProgressbar")
        self.upload_progress.pack(fill="x", pady=(6, 0))
        self.upload_progress["value"] = 0
        self.upload_progress["maximum"] = 100

        self._schedule_log_drain()
    # 居中窗口
    def center_window(self, width, height):
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        self.root.geometry(f"{width}x{height}+{x}+{y}")

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
            self.tree.selection_set(row_id)
            self.menu.entryconfig("删除文件", state="normal")
        else:
            self.menu.entryconfig("删除文件", state="disabled")
        self.menu.post(event.x_root, event.y_root)

    def add_file(self):
        filetypes = [("视频文件", "*.mp4 *.mkv *.ts")]
        fp = filedialog.askopenfilename(title="选择视频文件", filetypes=filetypes)
        if fp:
            if fp.lower().endswith(VIDEO_EXTS):
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
                self.log(f"删除文件：{fp}")

    # 选择目录
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
        self.log(f"已添加 {len(self.files)} 个视频文件")

    # 刷新文件表（斑马纹标签）
    def refresh_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for idx, fp in enumerate(self.files):
            name = os.path.basename(fp)
            tag = "evenrow" if idx % 2 == 0 else "oddrow"
            self.tree.insert("", "end", values=(name, fp, "未处理"), tags=(tag,))

    def clear_data(self):
        self.files = []
        self.refresh_table()
        self.log("已清空数据")

    def exit_app(self):
        if self.is_running:
            messagebox.showinfo("提示", "任务正在进行，建议稍后退出。")
        else:
            self.root.destroy()

    # 开始处理
    def start_process(self):
        if self.is_running:
            return
        if not self.files:
            messagebox.showwarning("警告", "请先加载视频文件。")
            return
        try:
            seg = int(self.seg_entry.get().strip())
            thr = int(self.thr_entry.get().strip())
            if seg <= 0 or thr <= 0:
                raise ValueError()
        except ValueError:
            messagebox.showwarning("警告", "切片间隔和上传线程需为正整数。")
            return

        self.is_running = True
        self.start_btn.state(["disabled"])
        self.stop_btn.state(["!disabled"])

        self.progress["maximum"] = 1.0
        self.progress["value"] = 0.0
        self.progress_label.config(text="0%")

        t = threading.Thread(target=self._process_thread, args=(seg, thr), daemon=True)
        t.start()

    def stop_process(self):
        messagebox.showinfo("提示", "当前不支持强制中断 ffmpeg/上传，请等待当前视频完成。")

    # 后台线程（整体进度 + 统一删除输出目录）
    def _process_thread(self, segment_seconds, upload_threads):
        total = len(self.files)
        completed = 0
        all_videos_success = True
        try:
            for fp in self.files:
                base = os.path.splitext(os.path.basename(fp))[0]
                self._set_row_status(fp, "切片中")
                ok = self._process_single_video(fp, base, segment_seconds, upload_threads)
                if not ok:
                    self._set_row_status(fp, "部分失败")
                    all_videos_success = False
                else:
                    self._set_row_status(fp, "上传完成")
                completed += 1
                ratio = completed / total
                self.root.after(0, lambda r=ratio: (self.progress.configure(value=r),
                                                    self.progress_label.config(text=f"{r:.0%}")))
            else:
                self.log("全部视频处理完成")
                messagebox.showinfo("完成", "全部视频已处理完成！")

                # 所有视频成功且勾选时，删除整个输出目录
                if self.after_delete_var.get() and all_videos_success:
                    try:
                        import shutil
                        shutil.rmtree(OUTPUT_DIR)
                        self.log(f"已删除整个切片输出文件夹：{OUTPUT_DIR}")
                    except Exception as e:
                        self.log(f"删除输出文件夹失败：{e}")

                if self.after_shutdown_var.get():
                    shutdown_windows()
        finally:
            self.is_running = False
            self.root.after(0, lambda: (self.start_btn.state(["!disabled"]), self.stop_btn.state(["disabled"])))

    # 单视频处理：切片 -> 并发上传 -> 生成 m3u8 -> 条件清理
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
        self.log(f"开始切片：{input_file}")
        try:
            subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError:
            self.log("错误：未找到 ffmpeg，请安装并配置到 PATH。")
            messagebox.showerror("错误", "未找到 ffmpeg，请安装并配置到 PATH。")
            return False
        except subprocess.CalledProcessError as e:
            self.log("ffmpeg 错误：" + e.stderr.decode(errors="ignore"))
            messagebox.showerror("错误", f"切片失败：{os.path.basename(input_file)}")
            return False
        except Exception as e:
            self.log(f"切片失败：{e}")
            messagebox.showerror("错误", f"切片失败：{os.path.basename(input_file)}")
            return False
        self.log(f"切片完成：{input_file}")

        ts_files = sorted([f for f in os.listdir(video_dir) if f.endswith(".ts")])
        if not ts_files:
            self.log("未生成 TS 切片")
            messagebox.showerror("错误", "未生成 TS 切片")
            return False

        urls = {}
        uploaded_count = 0
        all_success = True

        def on_piece_uploaded():
            nonlocal uploaded_count
            uploaded_count += 1
            percent = uploaded_count / len(ts_files)
            self._set_row_status(input_file, f"已上传 {percent:.0%}")

        self._set_row_status(input_file, "已上传 0%")
        with ThreadPoolExecutor(max_workers=upload_threads) as ex:
            futures = {ex.submit(self._upload_with_retry, os.path.join(video_dir, fname)): fname for fname in ts_files}
            for fut in as_completed(futures):
                fname = futures[fut]
                try:
                    url, attempt = fut.result()
                    urls[fname] = url
                    prefix = f"第{attempt}次上传成功：" if attempt > 1 else "上传成功："
                    self.log(f"{prefix}{fname} -> {url}")
                    self.root.after(0, on_piece_uploaded)
                except Exception as e:
                    self.log(f"最终上传失败：{fname} -> {e}")
                    all_success = False
                    continue

        # 生成 m3u8（成功的 ts 用 URL，失败的保留原文件名）
        try:
            with open(tmp_playlist, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            self.log(f"读取临时 m3u8 失败：{e}")
            return False

        new_lines = []
        for line in lines:
            text = line.strip()
            if text.endswith(".ts") and text in urls:
                new_lines.append(urls[text] + "\n")
            else:
                new_lines.append(line)
        try:
            with open(playlist_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except Exception as e:
            self.log(f"写入 m3u8 失败：{e}")
            return False

        self.log(f"生成 m3u8：{playlist_path}")

        # 仅当所有 ts 成功且勾选时才删除该视频子文件夹
        if self.after_delete_var.get() and all_success:
            for f in ts_files:
                try:
                    os.remove(os.path.join(video_dir, f))
                except Exception:
                    pass
            try:
                if os.path.exists(tmp_playlist):
                    os.remove(tmp_playlist)
            except Exception:
                pass
            try:
                if not os.listdir(video_dir):
                    os.rmdir(video_dir)
            except Exception:
                pass
            self.log(f"已删除 TS 切片：{base}")

        return all_success

    # 上传重试（允许一次重试）
    def _upload_with_retry(self, file_path, max_attempts=2):
        last_err = None
        for attempt in range(1, max_attempts + 1):
            try:
                url = upload_file(file_path)
                return url, attempt
            except Exception as e:
                name = os.path.basename(file_path)
                if attempt > 1:
                    self.log(f"第{attempt}次上传失败：{name} -> {e}")
                else:
                    self.log(f"上传失败：{name} -> {e}")
                last_err = e
                time.sleep(1.0)
        raise last_err

    # 表格状态更新
    def _set_row_status(self, file_path, status):
        for iid in self.tree.get_children():
            vals = self.tree.item(iid, "values")
            if vals and vals[1] == file_path:
                self.tree.item(iid, values=(vals[0], vals[1], status))
                break


# 入口
def main():
    root = TkinterDnD.Tk()
    app = VideoUploaderGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
