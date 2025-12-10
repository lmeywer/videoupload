import os
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import requests

class HLSUploaderGUI:
    def __init__(self, root, upload_func):
        self.root = root
        self.upload_func = upload_func
        self.output_dir = "output_slices"
        self.playlist_name = "playlist.m3u8"

        self.root.title("视频切片上传工具")
        self.root.geometry("650x500")

        # 选择视频按钮
        self.select_btn = tk.Button(root, text="选择视频文件(可多选)", command=self.select_files)
        self.select_btn.pack(pady=5)

        # 切片时长输入框
        self.segment_label = tk.Label(root, text="切片时长 (秒):")
        self.segment_label.pack(pady=5)
        self.segment_entry = tk.Entry(root)
        self.segment_entry.insert(0, "10")  # 默认 10 秒
        self.segment_entry.pack(pady=5)

        # 开始按钮
        self.start_btn = tk.Button(root, text="开始切片并上传", command=self.process_videos)
        self.start_btn.pack(pady=5)

        # 进度条
        self.progress = ttk.Progressbar(root, orient="horizontal", length=500, mode="determinate")
        self.progress.pack(pady=5)

        # 日志窗口
        self.log_text = tk.Text(root, height=15, width=80, state="disabled")
        self.log_text.pack(pady=5)

        # 显示结果
        self.result_label = tk.Label(root, text="提示信息会显示在这里", wraplength=600)
        self.result_label.pack(pady=5)

        self.input_files = []

    def log(self, message):
        """在日志窗口追加信息"""
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")
        self.root.update_idletasks()

    def select_files(self):
        self.input_files = filedialog.askopenfilenames(
            title="选择视频文件",
            filetypes=[("视频文件", "*.mp4;*.mov;*.avi;*.mkv")]
        )
        if self.input_files:
            messagebox.showinfo("提示", f"已选择 {len(self.input_files)} 个文件")
            self.log(f"已选择文件: {self.input_files}")

    def slice_video(self, input_file, segment_time):
        os.makedirs(self.output_dir, exist_ok=True)
        ts_pattern = os.path.join(self.output_dir, os.path.splitext(os.path.basename(input_file))[0] + "_%03d.ts")
        playlist_path = os.path.join(self.output_dir, os.path.splitext(os.path.basename(input_file))[0] + "_" + self.playlist_name)

        cmd = [
            "ffmpeg",
            "-i", input_file,
            "-c", "copy",
            "-map", "0",
            "-f", "segment",
            "-segment_time", str(segment_time),
            "-segment_list", playlist_path,
            ts_pattern
        ]
        self.log(f"开始切片视频: {input_file}")
        subprocess.run(cmd, check=True)
        self.log(f"视频切片完成: {input_file}")
        return playlist_path

    def upload_and_generate_m3u8(self, playlist_path):
        files = [f for f in sorted(os.listdir(self.output_dir)) if f.endswith(".ts")]
        total = len(files) + 1  # ts 文件 + m3u8
        self.progress["maximum"] = total
        self.progress["value"] = 0

        urls = {}
        for i, fname in enumerate(files, start=1):
            fpath = os.path.join(self.output_dir, fname)
            self.log(f"上传切片: {fname}")

            success = False
            for attempt in range(2):  # 最多尝试两次
                try:
                    url = self.upload_func(fpath)
                    urls[fname] = url
                    self.log(f"上传成功: {url}")
                    success = True
                    break
                except Exception as e:
                    self.log(f"上传失败 (第{attempt+1}次): {str(e)}")

            if not success:
                messagebox.showerror("错误", f"切片 {fname} 上传失败，两次尝试均未成功，上传终止！")
                return None

            self.progress["value"] = i
            self.root.update_idletasks()

        # 替换 m3u8 内容
        with open(playlist_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        new_lines = []
        for line in lines:
            if line.strip().endswith(".ts"):
                fname = line.strip()
                new_lines.append(urls[fname] + "\n")
            else:
                new_lines.append(line)

        video_name = os.path.splitext(os.path.basename(playlist_path))[0].replace("_playlist", "")
        final_playlist_path = os.path.join(self.output_dir, f"final_{video_name}.m3u8")

        with open(final_playlist_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        self.log(f"生成最终 m3u8 文件: {final_playlist_path}")
        playlist_url = self.upload_func(final_playlist_path)
        self.log(f"m3u8 上传成功: {playlist_url}")

        self.progress["value"] = total
        self.root.update_idletasks()
        return playlist_url

    def process_videos(self):
        if not self.input_files:
            messagebox.showwarning("警告", "请先选择视频文件！")
            return
        try:
            try:
                segment_time = int(self.segment_entry.get())
            except ValueError:
                messagebox.showwarning("警告", "请输入有效的数字作为切片时长！")
                return

            for input_file in self.input_files:
                playlist_path = self.slice_video(input_file, segment_time)
                final_url = self.upload_and_generate_m3u8(playlist_path)
                if final_url is None:
                    return  # 如果某个切片上传失败，直接终止
                self.log(f"{os.path.basename(input_file)} 已上传完成")

            self.result_label.config(text="视频已上传完成！")
            messagebox.showinfo("完成", "视频已上传完成！")
        except Exception as e:
            self.log(f"错误: {str(e)}")
            messagebox.showerror("错误", str(e))


# 🔗 上传函数：使用你提供的接口
def upload_file(file_path):
    url = "https://img1.freeforever.club/upload"
    params = {
        "serverCompress": "false",
        "uploadChannel": "telegram",
        "uploadNameType": "default",
        "autoRetry": "true",
        "uploadFolder": "",
        "authcode": "97"
    }

    files = {
        "file": (os.path.basename(file_path), open(file_path, "rb"), "video/vnd.dlna.mpeg-tts")
    }

    response = requests.post(url, params=params, files=files)
    response.raise_for_status()
    data = response.json()
    src = data[0]["src"]
    return "https://img1.freeforever.club" + src


if __name__ == "__main__":
    root = tk.Tk()
    app = HLSUploaderGUI(root, upload_func=upload_file)
    root.mainloop()
