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
OUTPUT_DIR = "output_slices"
M3U8_DIR = "m3u8"
DEFAULT_SEGMENT_SECONDS = 10
DEFAULT_UPLOAD_THREADS = 5

UPLOAD_URL = "https://img1.freeforever.club/upload"
UPLOAD_PARAMS = {
    "serverCompress": "false",
    "uploadChannel": "telegram",
    "uploadNameType": "default",
    "autoRetry": "true",
    "uploadFolder": ""
}
COOKIE_AUTHCODE = "97"  # 请替换为你的有效 authcode

VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv")


def upload_file(file_path):
    # 拼接完整 URL（带参数）
    url = (
        "https://img1.freeforever.club/upload"
        "?serverCompress=false"
        "&uploadChannel=telegram"
        "&uploadNameType=default"
        "&autoRetry=true"
        "&uploadFolder="
    )

    # 设置请求头（authcode 放在 Header 和 Cookie）
    headers = {
        "authcode": "97",  # 放在 Header
        "Accept": "application/json, text/plain, */*",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Origin": "https://img1.freeforever.club",
        "Referer": "https://img1.freeforever.club/",
    }

    cookies = {
        "authCode": "97"  # 放在 Cookie
    }

    # 只允许上传 ts 文件
    ext = os.path.splitext(file_path)[1].lower()
    if ext != ".ts":
        raise ValueError("只允许上传 .ts 文件")

    with open(file_path, "rb") as f:
        files = {
            "file": (os.path.basename(file_path), f, "video/vnd.dlna.mpeg-tts")
        }
        response = requests.post(url, headers=headers, cookies=cookies, files=files)
        response.raise_for_status()
        data = response.json()
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
        self.root.title("批量视频切片上传工具")
        self.root.geometry("980x700")

        ensure_dirs()

        # 样式（自定义边框颜色与浅灰背景）
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TButton", font=("Microsoft YaHei", 11), padding=6)
        style.configure("TLabel", font=("Microsoft YaHei", 11))
        style.configure("TEntry", font=("Microsoft YaHei", 11))
        style.configure("Horizontal.TProgressbar", thickness=18)
        style.configure("Custom.TLabelframe", background="#f8f8f8", bordercolor="#3399cc")
        style.configure("Custom.TLabelframe.Label", background="#f8f8f8", foreground="#333")

        self.files = []
        self.log_q = queue.Queue()
        self.is_running = False

        # 顶部标题
        header = ttk.Label(root, text="批量视频切片上传工具", font=("Microsoft YaHei", 16, "bold"))
        header.pack(pady=10)

        # 主区域：左侧文件表格，右侧参数与控制
        main = ttk.Frame(root, padding=10)
        main.pack(fill="both", expand=True)

        # 左侧：视频列表 + 按钮
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

        # 右侧：参数设置 + 控制按钮 + 进度条
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
        self.start_btn = ttk.Button(ctrl_frame, text="开始上传", command=self.start_process)
        self.start_btn.pack(side="left", padx=6)
        self.stop_btn = ttk.Button(ctrl_frame, text="停止", command=self.stop_process)
        self.stop_btn.pack(side="left", padx=6)
        self.stop_btn.state(["disabled"])

        self.progress = ttk.Progressbar(right, orient="horizontal", mode="determinate", length=320)
        self.progress.pack(fill="x", pady=10)

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
            self.tree.insert("", "end", values=(name, fp, "待处理"))

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
        self.progress["value"] = 0
        self.progress["maximum"] = len(self.files)

        t = threading.Thread(target=self._process_thread, args=(seg, thr), daemon=True)
        t.start()

    def stop_process(self):
        messagebox.showinfo("提示", "当前不支持强制中断 ffmpeg/上传，请等待当前视频完成。")

    # -------------------
    # 后台线程：处理所有视频
    # -------------------
    def _process_thread(self, segment_seconds, upload_threads):
        try:
            for idx, fp in enumerate(self.files, start=1):
                base = os.path.splitext(os.path.basename(fp))[0]
                self._set_row_status(fp, "切片中")
                ok = self._process_single_video(fp, base, segment_seconds, upload_threads)
                if not ok:
                    self._set_row_status(fp, "失败")
                    break
                self._set_row_status(fp, "完成")
                self.root.after(0, lambda v=idx: self.progress.configure(value=v))
            else:
                self.log("全部视频处理完成")
                messagebox.showinfo("完成", "全部视频已上传完成！")
                if self.after_shutdown_var.get():
                    shutdown_windows()
        finally:
            self.is_running = False
            self.root.after(0, lambda: (self.start_btn.state(["!disabled"]), self.stop_btn.state(["disabled"])))

    # -------------------
    # 单视频处理流程
    # -------------------
    def _process_single_video(self, input_file, base, segment_seconds, upload_threads):
        ensure_dirs()

        playlist_path = os.path.join(OUTPUT_DIR, f"{base}_playlist.m3u8")
        ts_pattern = os.path.join(OUTPUT_DIR, f"{base}_%03d.ts")

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

        ts_files = sorted([f for f in os.listdir(OUTPUT_DIR) if f.startswith(base + "_") and f.endswith(".ts")])

        # 并发上传切片
        self._set_row_status(input_file, "上传切片")
        urls = {}
        with ThreadPoolExecutor(max_workers=upload_threads) as ex:
            futures = {ex.submit(self._upload_with_retry, os.path.join(OUTPUT_DIR, fname)): fname for fname in ts_files}
            for fut in as_completed(futures):
                fname = futures[fut]
                try:
                    url = fut.result()
                    urls[fname] = url
                    self.log(f"上传成功：{fname} -> {url}")
                except Exception as e:
                    self.log(f"上传失败：{fname} -> {e}")
                    self._cleanup_video_files(ts_files, playlist_path)
                    messagebox.showerror("错误", f"切片上传失败：{fname}\n已清理该视频的切片和临时 m3u8。")
                    return False

        # 重写 m3u8 到 m3u8/ 目录
        try:
            with open(playlist_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            self.log(f"读取 m3u8 失败：{e}")
            messagebox.showerror("错误", f"读取 m3u8 失败：{e}")
            self._cleanup_video_files(ts_files, playlist_path)
            return False

        new_lines = []
        for line in lines:
            text = line.strip()
            if text.endswith(".ts") and text in urls:
                new_lines.append(urls[text] + "\n")
            else:
                new_lines.append(line)

        final_m3u8 = os.path.join(M3U8_DIR, f"final_{base}.m3u8")
        try:
            with open(final_m3u8, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except Exception as e:
            self.log(f"写入最终 m3u8 失败：{e}")
            messagebox.showerror("错误", f"写入最终 m3u8 失败：{e}")
            self._cleanup_video_files(ts_files, playlist_path)
            return False

        self.log(f"生成最终 m3u8：{final_m3u8}")

        # 上传最终 m3u8
        self._set_row_status(input_file, "上传 m3u8")
        try:
            m3u8_url = upload_file(final_m3u8)
            self.log(f"m3u8 上传成功：{m3u8_url}")
            self.append_result(f"{os.path.basename(input_file)} -> {m3u8_url}")
        except Exception as e:
            self.log(f"m3u8 上传失败：{e}")
            messagebox.showerror("错误", f"m3u8 上传失败：{e}")
            self._cleanup_video_files(ts_files, playlist_path)
            return False

        # 完成后删除切片
        if self.after_delete_var.get():
            self._cleanup_video_files(ts_files, playlist_path, silent=True)
            self.log(f"已删除切片与临时 m3u8：{base}")

        return True

    # -------------------
    # 上传重试
    # -------------------
    def _upload_with_retry(self, file_path, max_attempts=2):
        last_err = None
        for i in range(max_attempts):
            try:
                return upload_file(file_path)
            except Exception as e:
                last_err = e
                time.sleep(1.0)
        raise last_err

    # -------------------
    # 清理文件
    # -------------------
    def _cleanup_video_files(self, ts_files, playlist_path, silent=False):
        for f in ts_files:
            try:
                os.remove(os.path.join(OUTPUT_DIR, f))
            except Exception:
                pass
        try:
            os.remove(playlist_path)
        except Exception:
            pass
        if not silent:
            self.log("已清理切片与临时 m3u8")

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
