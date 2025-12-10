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

# =========================
# 配置
# =========================
OUTPUT_DIR = "output_slices"  # 每个视频独立子目录：output_slices/<视频名>/
DEFAULT_SEGMENT_SECONDS = 10
DEFAULT_UPLOAD_THREADS = 5

# 仅上传 TS 接口（参数拼在 URL 上）
UPLOAD_URL = (
    "https://img1.freeforever.club/upload"
    "?serverCompress=false"
    "&uploadChannel=telegram"
    "&uploadNameType=default"
    "&autoRetry=true"
    "&uploadFolder="
)
AUTHCODE = "97"  # 请替换为有效值

VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv")


# =========================
# 上传函数（只允许 TS）
# =========================
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


# =========================
# 工具
# =========================
def ensure_dirs():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def shutdown_windows():
    if sys.platform.startswith("win"):
        os.system("shutdown /s /t 5")


# =========================
# GUI
# =========================
class VideoUploaderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("批量视频切片上传工具")
        self.root.geometry("980x700")

        ensure_dirs()

        # 样式：白底蓝条进度、蓝色边框
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TButton", font=("Microsoft YaHei", 11), padding=6)
        style.configure("TLabel", font=("Microsoft YaHei", 11))
        style.configure("TEntry", font=("Microsoft YaHei", 11))
        style.configure("Custom.Horizontal.TProgressbar",
                        troughcolor="white",
                        background="#3399ff",
                        bordercolor="#3399ff",
                        lightcolor="#3399ff",
                        darkcolor="#3399ff")
        style.configure("Custom.TLabelframe", bordercolor="#3399ff")
        style.configure("Custom.TLabelframe.Label", foreground="#3399ff")

        # 状态
        self.files = []
        self.log_q = queue.Queue()
        self.is_running = False

        # 顶部标题
        header = ttk.Label(root, text="批量视频切片上传工具", font=("Microsoft YaHei", 16, "bold"))
        header.pack(pady=10)

        # 主区域：左侧表格，右侧参数+控制+进度
        main = ttk.Frame(root, padding=10)
        main.pack(fill="both", expand=True)

        # 左侧：文件表格
        left = ttk.Frame(main)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))

        columns = ("name", "path", "status")
        self.tree = ttk.Treeview(left, columns=columns, show="headings", height=16)
        self.tree.heading("name", text="文件名")
        self.tree.heading("path", text="路径")
        self.tree.heading("status", text="状态")
        self.tree.column("name", width=220, anchor="w")
        self.tree.column("path", width=520, anchor="w")
        self.tree.column("status", width=120, anchor="center")
        self.tree.pack(fill="both", expand=True)

        left_btns = ttk.Frame(left)
        left_btns.pack(fill="x", pady=8)
        ttk.Button(left_btns, text="选择目录", command=self.choose_dir).pack(side="left")
        ttk.Button(left_btns, text="清空数据", command=self.clear_data).pack(side="left", padx=8)
        ttk.Button(left_btns, text="退出程序", command=self.exit_app).pack(side="right")

        # 右侧：参数、控制、进度
        right = ttk.Frame(main)
        right.pack(side="right", fill="y")

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

        self.after_delete_var = tk.BooleanVar(value=True)
        self.after_shutdown_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(param_frame, text="上传完成后删除切片", variable=self.after_delete_var).grid(row=2, column=0, sticky="w", padx=6, pady=6)
        ttk.Checkbutton(param_frame, text="上传完成后关机", variable=self.after_shutdown_var).grid(row=2, column=1, sticky="w", padx=6, pady=6)

        ctrl_frame = ttk.Frame(right)
        ctrl_frame.pack(fill="x", pady=12)
        self.start_btn = ttk.Button(ctrl_frame, text="开始处理", command=self.start_process)
        self.start_btn.pack(side="left", padx=6)
        self.stop_btn = ttk.Button(ctrl_frame, text="停止", command=self.stop_process)
        self.stop_btn.pack(side="left", padx=6)
        self.stop_btn.state(["disabled"])

        prog_frame = ttk.Frame(right)
        prog_frame.pack(fill="x", pady=10)
        self.progress = ttk.Progressbar(prog_frame, orient="horizontal", mode="determinate",
                                        length=320, style="Custom.Horizontal.TProgressbar")
        self.progress.pack(side="left")
        self.progress_label = ttk.Label(prog_frame, text="0%")
        self.progress_label.pack(side="left", padx=8)

        # 日志区
        log_box = ttk.LabelFrame(root, text="运行日志", padding=8, style="Custom.TLabelframe")
        log_box.pack(fill="both", expand=True, padx=10, pady=(4, 6))
        self.log_text = tk.Text(log_box, height=10, wrap="none", font=("Consolas", 10), state="disabled")
        vsb = ttk.Scrollbar(log_box, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=vsb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self._schedule_log_drain()

        # 上传结果区
        result_box = ttk.LabelFrame(root, text="上传结果", padding=8, style="Custom.TLabelframe")
        result_box.pack(fill="x", padx=10, pady=(0, 10))
        self.result_text = tk.Text(result_box, height=6, wrap="word", font=("Consolas", 10), state="disabled")
        self.result_text.pack(fill="x")

    # -------------------
    # 日志
    # -------------------
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

    def append_result(self, msg):
        self.result_text.config(state="normal")
        self.result_text.insert("end", msg + "\n")
        self.result_text.see("end")
        self.result_text.config(state="disabled")

    # -------------------
    # 文件列表
    # -------------------
    def choose_dir(self):
        d = filedialog.askdirectory(title="选择视频目录")
        if not d:
            return
        self.files = []
        for rootdir, _, filenames in os.walk(d):
            for fn in filenames:
                if fn.lower().endswith(VIDEO_EXTS):
                    fp = os.path.join(rootdir, fn)
                    self.files.append(fp)
        self.refresh_table()
        self.log(f"已添加 {len(self.files)} 个视频文件")

    def refresh_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for fp in self.files:
            name = os.path.basename(fp)
            self.tree.insert("", "end", values=(name, fp, "未处理"))

    def clear_data(self):
        self.files = []
        self.refresh_table()
        self.log("已清空数据")

    def exit_app(self):
        if self.is_running:
            messagebox.showinfo("提示", "任务正在进行，建议稍后退出。")
        else:
            self.root.destroy()

    # -------------------
    # 控制流程
    # -------------------
    def start_process(self):
        if self.is_running:
            return
        if not self.files:
            messagebox.showwarning("警告", "请先选择目录并加载视频文件。")
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

        # 比例进度（0~1）
        self.progress["maximum"] = 1.0
        self.progress["value"] = 0.0
        self.progress_label.config(text="0%")

        t = threading.Thread(target=self._process_thread, args=(seg, thr), daemon=True)
        t.start()

    def stop_process(self):
        messagebox.showinfo("提示", "当前不支持强制中断 ffmpeg/上传，请等待当前视频完成。")

    # -------------------
    # 后台线程：逐视频切片后再上传
    # -------------------
    def _process_thread(self, segment_seconds, upload_threads):
        total = len(self.files)
        completed = 0
        try:
            for fp in self.files:
                base = os.path.splitext(os.path.basename(fp))[0]
                self._set_row_status(fp, "切片中")
                ok = self._process_single_video(fp, base, segment_seconds, upload_threads)
                if not ok:
                    self._set_row_status(fp, "失败")
                    break
                self._set_row_status(fp, "上传完成")
                completed += 1
                ratio = completed / total
                # 更新比例进度条与文本
                self.root.after(0, lambda r=ratio: (self.progress.configure(value=r),
                                                    self.progress_label.config(text=f"{r:.0%}")))
            else:
                self.log("全部视频处理完成")
                messagebox.showinfo("完成", "全部视频已上传完成！")
                if self.after_shutdown_var.get():
                    shutdown_windows()
        finally:
            self.is_running = False
            self.root.after(0, lambda: (self.start_btn.state(["!disabled"]), self.stop_btn.state(["disabled"])))

    # -------------------
    # 单视频处理：切片 -> 上传TS并实时状态 -> 重写m3u8（本地）
    # -------------------
    def _process_single_video(self, input_file, base, segment_seconds, upload_threads):
        # 子文件夹：output_slices/<视频名>/
        video_dir = os.path.join(OUTPUT_DIR, base)
        os.makedirs(video_dir, exist_ok=True)

        # m3u8 文件名为视频名；TS 命名 %03d.ts
        playlist_path = os.path.join(video_dir, f"{base}.m3u8")
        ts_pattern = os.path.join(video_dir, "%03d.ts")

        # 切片
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", input_file,
            "-c", "copy",
            "-map", "0",
            "-f", "segment",
            "-segment_time", str(segment_seconds),
            "-segment_list", playlist_path,
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
        self.log(f"切片完成：{input_file}")

        # 当前视频的全部 TS
        ts_files = sorted([f for f in os.listdir(video_dir) if f.endswith(".ts")])
        total_ts = len(ts_files)
        if total_ts == 0:
            self.log("未生成 TS 切片")
            messagebox.showerror("错误", "未生成 TS 切片")
            return False

        # 并发上传 TS，实时更新“已上传 xx%”
        urls = {}
        uploaded_count = 0

        def on_piece_uploaded():
            nonlocal uploaded_count, total_ts
            uploaded_count += 1
            percent = uploaded_count / total_ts
            self._set_row_status(input_file, f"已上传 {percent:.0%}")

        self._set_row_status(input_file, "已上传 0%")
        with ThreadPoolExecutor(max_workers=upload_threads) as ex:
            futures = {ex.submit(self._upload_with_retry, os.path.join(video_dir, fname)): fname for fname in ts_files}
            for fut in as_completed(futures):
                fname = futures[fut]
                try:
                    url = fut.result()
                    urls[fname] = url
                    self.log(f"上传成功：{fname} -> {url}")
                    self.root.after(0, on_piece_uploaded)
                except Exception as e:
                    self.log(f"上传失败：{fname} -> {e}")
                    self._cleanup_video_files(video_dir)
                    messagebox.showerror("错误", f"切片上传失败：{fname}\n已清理该视频的切片和 m3u8。")
                    return False

        # 重写 m3u8：把 TS 文件名替换为对应的 URL（本地保存）
        try:
            with open(playlist_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            self.log(f"读取 m3u8 失败：{e}")
            messagebox.showerror("错误", f"读取 m3u8 失败：{e}")
            self._cleanup_video_files(video_dir)
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
            messagebox.showerror("错误", f"写入 m3u8 失败：{e}")
            self._cleanup_video_files(video_dir)
            return False

        self.log(f"生成 m3u8：{playlist_path}")
        self.append_result(f"{os.path.basename(input_file)} -> m3u8 本地生成成功")

        # 完成后是否删除切片
        if self.after_delete_var.get():
            # 保留 m3u8，删除 TS
            for f in ts_files:
                try:
                    os.remove(os.path.join(video_dir, f))
                except Exception:
                    pass
            self.log(f"已删除 TS 切片：{base}")

        return True

    # -------------------
    # 上传重试
    # -------------------
    def _upload_with_retry(self, file_path, max_attempts=2):
        last_err = None
        for _ in range(max_attempts):
            try:
                return upload_file(file_path)
            except Exception as e:
                last_err = e
                time.sleep(1.0)
        raise last_err

    # -------------------
    # 清理文件（该视频目录）
    # -------------------
    def _cleanup_video_files(self, video_dir, keep_m3u8=False):
        for fn in os.listdir(video_dir):
            if keep_m3u8 and fn.endswith(".m3u8"):
                continue
            try:
                os.remove(os.path.join(video_dir, fn))
            except Exception:
                pass
        # 若目录空则尝试移除
        try:
            if not os.listdir(video_dir):
                os.rmdir(video_dir)
        except Exception:
            pass
        self.log("已清理切片与 m3u8")

    # -------------------
    # 表格状态更新
    # -------------------
    def _set_row_status(self, file_path, status):
        for iid in self.tree.get_children():
            vals = self.tree.item(iid, "values")
            if vals and vals[1] == file_path:
                self.tree.item(iid, values=(vals[0], vals[1], status))
                break


# =========================
# 入口
# =========================
def main():
    try:
        import requests  # noqa
    except Exception:
        messagebox.showerror("错误", "缺少 requests 依赖，请先安装：pip install requests")
        return

    root = tk.Tk()
    app = VideoUploaderGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
