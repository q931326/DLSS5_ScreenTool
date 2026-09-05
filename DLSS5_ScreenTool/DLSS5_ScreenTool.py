# -*- coding: utf-8 -*-
"""
DLSS5_ScreenTool — 给图片/视频附加 DLSS5 神经渲染效果的应用
=========================================================
通过 dlssnr_bridge.dll 直接驱动 NVIDIA DLSSNR (Feature 18, 310.x) 运行时,
绕过驱动核心对非白名单应用的门控。需 RTX 50 系显卡 + 616.56+ 驱动。

用法:
    python DLSS5_ScreenTool.py                 # 打开图形界面
    python DLSS5_ScreenTool.py --input 文件    # 无界面批处理(图片或视频)

输出:
    图片 -> 同目录 <原名>_dlss.png
    视频 -> 同目录 <原名>_dlss.mp4 (mp4v 编码)
"""
import os
import sys
import ctypes
import threading
import queue
import argparse

APP_DIR = os.path.dirname(os.path.abspath(__file__))
BRIDGE_DLL = os.path.join(APP_DIR, "bridge", "dlssnr_bridge.dll")
RUNTIME_DLL = os.path.join(APP_DIR, "runtime", "nvngx_dlssnr.dll")

STYLE_CHOICES = ("默认", "自然", "电影")

VIDEO_EXT = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".webm"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}


def find_ngx_core():
    """从注册表定位驱动商店里的 nvngx.dll (NGX 核心)。"""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\NVIDIA Corporation\Global\NGXCore") as k:
            path, _ = winreg.QueryValueEx(k, "FullPath")
            p = os.path.join(path, "nvngx.dll")
            if os.path.isfile(p):
                return p
    except OSError:
        pass
    # 注册表失败时, 在 DriverStore 里扫一遍
    ds = r"C:\Windows\System32\DriverStore\FileRepository"
    if os.path.isdir(ds):
        for root, _dirs, files in os.walk(ds):
            if "nvngx.dll" in files and "nvngx_dlssnr.dll" not in files:
                # 排除 dlssnr 文件夹, 优先找仅含 nvngx.dll 的标准驱动位置
                candidate = os.path.join(root, "nvngx.dll")
                # 选第一个; 多数机器只会有一个匹配的 NVIDIA 驱动目录
                return candidate
        # 没找到纯 NGX 目录, 再退一步: 返回第一个含 nvngx.dll 的位置
        for root, _dirs, files in os.walk(ds):
            if "nvngx.dll" in files:
                return os.path.join(root, "nvngx.dll")
    raise RuntimeError("找不到 nvngx.dll - 请安装/更新 NVIDIA 驱动 (>= 555.85)")


def find_dlssnr_runtime():
    """定位 nvngx_dlssnr.dll (DLSSNR 运行时, Feature 18)。

    优先级: 项目 runtime/ -> 注册表 NGXCore 同目录 ->
            Steam/Origin 常见游戏目录 -> DriverStore -> 提示用户。
    """
    candidates = []
    project = os.path.join(APP_DIR, "runtime", "nvngx_dlssnr.dll")
    candidates.append(project)
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\NVIDIA Corporation\Global\NGXCore") as k:
            path, _ = winreg.QueryValueEx(k, "FullPath")
            candidates.append(os.path.join(path, "nvngx_dlssnr.dll"))
    except OSError:
        pass
    # Steam 常见游戏目录
    steam_root = r"C:\Program Files (x86)\Steam\steamapps\common"
    if os.path.isdir(steam_root):
        for root, _dirs, files in os.walk(steam_root):
            if "nvngx_dlssnr.dll" in files:
                candidates.append(os.path.join(root, "nvngx_dlssnr.dll"))
                break  # 一个就够了
    # DriverStore (部分驱动版本自带)
    ds = r"C:\Windows\System32\DriverStore\FileRepository"
    if os.path.isdir(ds):
        for root, _dirs, files in os.walk(ds):
            if "nvngx_dlssnr.dll" in files:
                candidates.append(os.path.join(root, "nvngx_dlssnr.dll"))
                break
    for c in candidates:
        if os.path.isfile(c):
            return c
    return project  # 返回项目路径, 让上层报错时用户能看到该路径


CORE_DLL = find_ngx_core()
RUNTIME_DLL = find_dlssnr_runtime()


class DlssnrSettingsC(ctypes.Structure):
    _fields_ = [
        ("style", ctypes.c_int),
        ("intensity", ctypes.c_float),
        ("localTone", ctypes.c_float),
        ("localStructure", ctypes.c_float),
        ("autoMask", ctypes.c_int),
        ("reset", ctypes.c_int),
        ("skinStructure", ctypes.c_float),
        ("uiCorrection", ctypes.c_int),
        ("depthInverted", ctypes.c_int),
        ("motionScaleX", ctypes.c_float),
        ("motionScaleY", ctypes.c_float),
        ("paperWhiteScale", ctypes.c_float),
        ("colorTransfer", ctypes.c_int),
    ]


class Bridge:
    """dlssnr_bridge.dll 的 ctypes 封装, 含会话缓存。"""

    def __init__(self):
        self.dll = ctypes.CDLL(BRIDGE_DLL)
        d = self.dll
        d.dlssnr_create.restype = ctypes.c_void_p
        d.dlssnr_create.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint,
                                    ctypes.c_uint, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_char_p, ctypes.c_int]
        d.dlssnr_process.restype = ctypes.c_int
        d.dlssnr_process.argtypes = [ctypes.c_void_p,
                                     ctypes.c_char_p, ctypes.c_uint,
                                     ctypes.c_void_p, ctypes.c_uint,
                                     ctypes.c_void_p, ctypes.c_uint,
                                     ctypes.POINTER(DlssnrSettingsC),
                                     ctypes.c_char_p, ctypes.c_uint,
                                     ctypes.c_char_p, ctypes.c_int]
        d.dlssnr_destroy.argtypes = [ctypes.c_void_p]
        d.dlssnr_restore_color.argtypes = [ctypes.c_char_p, ctypes.c_uint,
                                           ctypes.c_char_p, ctypes.c_uint,
                                           ctypes.c_uint, ctypes.c_uint, ctypes.c_float]
        self._sessions = {}  # (w, h, preset) -> handle

    def _session(self, w, h, preset):
        key = (w, h, int(preset))
        if key not in self._sessions:
            if not os.path.isfile(RUNTIME_DLL):
                raise RuntimeError(
                    "DLSSNR 运行时未找到:\n  %s\n"
                    "请将 nvngx_dlssnr.dll 放入项目的 runtime/ 目录, "
                    "或确认 RTX 50 系显卡 + 616.56+ 驱动已安装。" % RUNTIME_DLL)
            if not os.path.isfile(CORE_DLL):
                raise RuntimeError(
                    "NGX 核心未找到:\n  %s\n"
                    "请安装/更新 NVIDIA 驱动 (>= 555.85)。" % CORE_DLL)
            if w <= 0 or h <= 0:
                raise RuntimeError("图像尺寸无效: %dx%d" % (w, h))
            # 运行时每进程仅允许一个活会话: 创建前必须先销毁旧会话
            for k, hnd in list(self._sessions.items()):
                self.dll.dlssnr_destroy(hnd)
                del self._sessions[k]
            err = ctypes.create_string_buffer(1024)
            handle = self.dll.dlssnr_create(RUNTIME_DLL, CORE_DLL, w, h, 0,
                                            int(preset), err, 1024)
            if not handle:
                raise RuntimeError("DLSS5 会话创建失败: %s\n  RUNTIME=%s\n  CORE=%s\n  SIZE=%dx%d" %
                                   (err.value.decode(errors="replace"),
                                    RUNTIME_DLL, CORE_DLL, w, h))
            self._sessions[key] = handle
        return self._sessions[key]

    def process(self, rgba, preset=1, style=0, intensity=1.0, local_tone=1.0,
                local_struct=1.0, skin_struct=1.0, auto_mask=0, reset=True,
                color_fidelity=0.0, motion=None):
        """rgba: HxWx4 uint8 (RGB)。motion: HxWx2 float32 像素位移(当前->上一帧)。
        返回处理后的 HxWx4 uint8。"""
        h, w = rgba.shape[:2]
        handle = self._session(w, h, preset)
        err = ctypes.create_string_buffer(1024)
        out = np.zeros_like(rgba)
        if motion is None:
            m_ptr, m_stride = None, 0
        else:
            m = np.ascontiguousarray(motion.astype(np.float16).view(np.uint16))
            m_ptr = m.ctypes.data_as(ctypes.c_char_p)
            m_stride = w * 4  # RG16F: 2通道 x 2字节
        st = DlssnrSettingsC(
            style=int(style), intensity=float(intensity),
            localTone=float(local_tone), localStructure=float(local_struct),
            autoMask=int(auto_mask), reset=1 if reset else 0,
            skinStructure=float(skin_struct), uiCorrection=0,
            depthInverted=0, motionScaleX=1.0, motionScaleY=1.0,
            paperWhiteScale=1.0, colorTransfer=0)
        ok = self.dll.dlssnr_process(
            handle,
            rgba.ctypes.data_as(ctypes.c_char_p), w * 4,
            None, 0,
            m_ptr, m_stride,
            ctypes.byref(st),
            out.ctypes.data_as(ctypes.c_char_p), w * 4,
            err, 1024)
        if not ok:
            raise RuntimeError("DLSS5 处理失败: %s" % err.value.decode(errors="replace"))
        if color_fidelity > 0:
            self.dll.dlssnr_restore_color(
                rgba.ctypes.data_as(ctypes.c_char_p), w * 4,
                out.ctypes.data_as(ctypes.c_char_p), w * 4,
                w, h, float(color_fidelity))
        return out


import numpy as np  # noqa: E402  (bridge 依赖 numpy 数组传参)
BRIDGE = Bridge()


# ---------- 处理核心 ----------
def _imread_unicode(path):
    """cv2.imread 不支持非 ASCII 路径, 用 fromfile+imdecode 兼容中文路径。"""
    import cv2
    data = np.fromfile(path, dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _imwrite_unicode(path, img):
    """cv2.imwrite 不支持非 ASCII 路径, 用 imencode+tofile 兼容中文路径。"""
    import cv2
    ext = os.path.splitext(path)[1] or ".png"
    ok, buf = cv2.imencode(ext, img)
    if ok:
        buf.tofile(path)
    return ok


def _ascii_temp(path):
    """路径含非 ASCII 字符时复制一份到临时 ASCII 路径。
    返回 (可用路径, 临时文件或 None), 调用方负责用完删除临时文件。"""
    try:
        path.encode("ascii")
        return path, None
    except UnicodeEncodeError:
        import tempfile
        import shutil
        tmp = tempfile.mktemp(suffix=os.path.splitext(path)[1].lower() or ".tmp")
        shutil.copy2(path, tmp)
        return tmp, tmp


def _pre_upscale(bgr, upscale):
    """超分模式: 先缩小模拟低内部分辨率, 再放大回目标尺寸(带模糊), 交给 DLSS5 修复。"""
    if upscale and upscale > 1.0:
        import cv2
        h, w = bgr.shape[:2]
        sw, sh = max(1, round(w / upscale)), max(1, round(h / upscale))
        small = cv2.resize(bgr, (sw, sh), interpolation=cv2.INTER_AREA)
        bgr = cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)
    return bgr


def process_image(path, settings):
    import cv2
    bgr = _imread_unicode(path)
    if bgr is None:
        raise RuntimeError("无法读取图片: %s" % path)
    bgr = _pre_upscale(bgr, settings.pop("_upscale", 1.0))
    settings.pop("_use_motion", None)  # 图片无时域, 仅视频使用
    h, w = bgr.shape[:2]
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    rgba = np.dstack([rgb, np.full((h, w), 255, np.uint8)])
    out = BRIDGE.process(rgba, **settings)
    out_bgr = cv2.cvtColor(out[..., :3], cv2.COLOR_RGB2BGR)
    root, _ = os.path.splitext(path)
    dst = root + "_dlss.png"
    if not _imwrite_unicode(dst, out_bgr):
        raise RuntimeError("写入失败: %s" % dst)
    return dst


def process_video(path, settings, progress_cb=None, stop_event=None):
    import cv2
    import shutil
    upscale = settings.pop("_upscale", 1.0)
    use_motion = settings.pop("_use_motion", False)

    # 中文路径兼容: 输入复制到临时 ASCII 路径
    src_use, tmp_src = _ascii_temp(path)
    cap = cv2.VideoCapture(src_use)
    if not cap.isOpened():
        if tmp_src:
            os.remove(tmp_src)
        raise RuntimeError("无法打开视频: %s" % path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    root, _ = os.path.splitext(path)
    dst = root + "_dlss.mp4"
    try:
        dst.encode("ascii")
        vw_path = dst
    except UnicodeEncodeError:
        import tempfile
        vw_path = tempfile.mktemp(suffix=".mp4")  # 先写临时, 最后移回
    vw = cv2.VideoWriter(vw_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    if not vw.isOpened():
        cap.release()
        if tmp_src:
            os.remove(tmp_src)
        raise RuntimeError("创建输出视频失败: %s" % dst)

    i = ok = 0
    prev_gray = None
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            ret, fr = cap.read()
            if not ret:
                break
            # 运动矢量: Farneback 光流, 单位像素, 方向=当前->上一帧
            motion = None
            if use_motion:
                gray = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
                if prev_gray is not None:
                    flow = cv2.calcOpticalFlowFarneback(
                        prev_gray, gray, None, 0.5, 3, 21, 3, 5, 1.2, 0)
                    motion = -flow
                prev_gray = gray
            if upscale and upscale > 1.0:
                fr = _pre_upscale(fr, upscale)
            rgb = cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)
            rgba = np.dstack([rgb, np.full(rgb.shape[:2], 255, np.uint8)])
            o = BRIDGE.process(rgba, reset=(i == 0), motion=motion, **settings)
            if o is not None:
                vw.write(cv2.cvtColor(o[..., :3], cv2.COLOR_RGB2BGR))
                ok += 1
            i += 1
            if progress_cb and (i % 10 == 0 or i == total):
                progress_cb(i, total, ok)
    finally:
        cap.release()
        vw.release()
        if tmp_src:
            try:
                os.remove(tmp_src)
            except OSError:
                pass
        if vw_path != dst:
            try:
                os.replace(vw_path, dst)
            except OSError as e:
                raise RuntimeError("输出移回目标路径失败: %s (%s)" % (dst, e))
    return dst, i, ok


def make_settings(style=0, intensity=1.0, local_tone=1.0, local_struct=1.0,
                  skin_struct=1.0, preset=1, color_fidelity=0.0,
                  upscale=1.0, use_motion=False):
    return {
        "style": int(style), "intensity": float(intensity),
        "local_tone": float(local_tone), "local_struct": float(local_struct),
        "skin_struct": float(skin_struct), "preset": int(preset),
        "color_fidelity": float(color_fidelity),
        "_upscale": float(upscale), "_use_motion": bool(use_motion),
    }


# ---------- 图形界面 ----------
def run_gui():
    import cv2
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    class App:
        def __init__(self, root):
            self.root = root
            root.title("DLSS5_ScreenTool — 图片/视频神经渲染")
            root.geometry("980x680")
            self.path = None
            self.kind = None  # 'image' | 'video'
            self.worker = None
            self.stop_event = None
            self.q = queue.Queue()
            self._build()
            root.after(100, self._poll)

        def _build(self):
            top = ttk.Frame(self.root, padding=8)
            top.pack(fill="x")

            ttk.Button(top, text="打开图片/视频…", command=self.open_file).pack(side="left")
            self.lbl_file = ttk.Label(top, text="(未选择文件)", width=48)
            self.lbl_file.pack(side="left", padx=8)

            # 参数区
            cfg = ttk.LabelFrame(self.root, text="DLSS5 参数", padding=8)
            cfg.pack(fill="x", padx=8, pady=(0, 6))

            ttk.Label(cfg, text="风格:").grid(row=0, column=0, sticky="e")
            self.v_style = tk.StringVar(value=STYLE_CHOICES[0])
            ttk.Combobox(cfg, textvariable=self.v_style, values=list(STYLE_CHOICES),
                         state="readonly", width=8).grid(row=0, column=1, padx=6)

            ttk.Label(cfg, text="Preset:").grid(row=0, column=2, sticky="e")
            self.v_preset = tk.StringVar(value="1")
            ttk.Combobox(cfg, textvariable=self.v_preset, values=["0", "1", "2", "3"],
                         state="readonly", width=4).grid(row=0, column=3, padx=6)

            ttk.Label(cfg, text="超分:").grid(row=0, column=6, sticky="e")
            self.v_upscale = tk.StringVar(value="关")
            ttk.Combobox(cfg, textvariable=self.v_upscale, values=["关", "2x", "3x"],
                         state="readonly", width=5).grid(row=0, column=7, padx=6)

            self.v_motion = tk.BooleanVar(value=False)
            ttk.Checkbutton(cfg, text="运动矢量(视频)",
                            variable=self.v_motion).grid(row=1, column=6, columnspan=2,
                                                         sticky="w", padx=6)

            def slider(row, col, label, var, vmax=1.0):
                ttk.Label(cfg, text=label).grid(row=row, column=col, sticky="e")
                ttk.Scale(cfg, from_=0.0, to=vmax, variable=var,
                          orient="horizontal", length=140).grid(row=row, column=col + 1, padx=6)
                ttk.Label(cfg, textvariable=var, width=5).grid(row=row, column=col + 2)

            self.v_intensity = tk.DoubleVar(value=1.0)
            self.v_tone = tk.DoubleVar(value=1.0)
            self.v_struct = tk.DoubleVar(value=1.0)
            self.v_fidelity = tk.DoubleVar(value=0.0)
            slider(0, 4, "强度:", self.v_intensity, vmax=2.0)
            slider(1, 0, "本地色调:", self.v_tone, vmax=2.0)
            slider(1, 4, "本地结构:", self.v_struct, vmax=2.0)
            slider(2, 0, "色彩保真:", self.v_fidelity, vmax=1.0)
            ttk.Label(cfg, text="(强度/色调/结构 0~2.0，色彩保真 0~1)").grid(
                row=2, column=2, columnspan=3, sticky="w", padx=6)

            # 一键方案预设 (实测配方)
            self.recipes = {
                "仿真保真": dict(style=0, intensity=1.0, local_tone=1.0,
                                 local_struct=1.0, preset=1, color_fidelity=0.0,
                                 upscale="关", motion=True),
                "细节重建": dict(style=0, intensity=1.0, local_tone=1.0,
                                 local_struct=1.0, preset=1, color_fidelity=0.0,
                                 upscale="2x", motion=True),
                "电影感": dict(style=2, intensity=1.5, local_tone=1.0,
                               local_struct=1.0, preset=2, color_fidelity=0.0,
                               upscale="关", motion=True),
            }
            ttk.Label(cfg, text="方案:").grid(row=0, column=8, sticky="e")
            self.v_recipe = tk.StringVar(value="自定义")
            cb_recipe = ttk.Combobox(cfg, textvariable=self.v_recipe,
                                     values=["自定义"] + list(self.recipes),
                                     state="readonly", width=9)
            cb_recipe.grid(row=0, column=9, padx=6)
            cb_recipe.bind("<<ComboboxSelected>>", self._apply_recipe)

            # 预览区
            self.canvas = tk.Canvas(self.root, bg="#141414", highlightthickness=0)
            self.canvas.pack(fill="both", expand=True, padx=8, pady=4)
            self.img_a = self.img_b = None  # 防 GC

            # 操作区
            bot = ttk.Frame(self.root, padding=8)
            bot.pack(fill="x")
            self.btn_run = ttk.Button(bot, text="✦ 应用 DLSS5", command=self.run, state="disabled")
            self.btn_run.pack(side="left")
            self.btn_stop = ttk.Button(bot, text="停止", command=self.stop, state="disabled")
            self.btn_stop.pack(side="left", padx=6)
            self.progress = ttk.Progressbar(bot, mode="determinate", length=320)
            self.progress.pack(side="left", padx=10)
            self.lbl_status = ttk.Label(bot, text="就绪")
            self.lbl_status.pack(side="left", padx=8)

        # ----- 文件 -----
        def open_file(self):
            f = filedialog.askopenfilename(title="选择图片或视频", filetypes=[
                ("媒体文件", "*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff "
                            "*.mp4 *.avi *.mov *.mkv *.wmv *.webm"),
                ("图片", "*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff"),
                ("视频", "*.mp4 *.avi *.mov *.mkv *.wmv *.webm"),
            ])
            if not f:
                return
            ext = os.path.splitext(f)[1].lower()
            if ext in IMAGE_EXT:
                self.kind = "image"
            elif ext in VIDEO_EXT:
                self.kind = "video"
            else:
                messagebox.showwarning("格式", "不支持的文件类型: " + ext)
                return
            self.path = f
            self.lbl_file.config(text=os.path.basename(f) + ("  [图片]" if self.kind == "image" else "  [视频]"))
            self.btn_run.config(state="normal")
            self.preview_source()

        # ----- 预览原图 -----
        def preview_source(self):
            try:
                if self.kind == "image":
                    bgr = _imread_unicode(self.path)
                else:
                    src, tmp = _ascii_temp(self.path)
                    cap = cv2.VideoCapture(src)
                    cap.read()
                    bgr = cap.read()[1]  # 取第2帧更接近画面
                    cap.release()
                    if tmp:
                        try:
                            os.remove(tmp)
                        except OSError:
                            pass
                self._show_pair(bgr, None)
            except Exception:
                pass

        def _photo(self, bgr, max_w, max_h):
            h, w = bgr.shape[:2]
            s = min(max_w / w, max_h / h, 1.0)
            if s < 1.0:
                bgr = cv2.resize(bgr, (int(w * s), int(h * s)))
            ok, buf = cv2.imencode(".png", bgr)
            import base64
            return tk.PhotoImage(data=base64.b64encode(buf.tobytes()).decode("ascii"))

        def _show_pair(self, bgr_a, bgr_b):
            self.canvas.delete("all")
            cw = self.canvas.winfo_width() or 900
            ch = self.canvas.winfo_height() or 500
            half = cw // 2 - 10
            pa = self._photo(bgr_a, half, ch - 30)
            self.img_a = pa
            ax = 5 + (half - pa.width()) // 2
            ay = 20 + (ch - 30 - pa.height()) // 2
            self.canvas.create_image(ax, ay, anchor="nw", image=pa)
            self.canvas.create_text(5 + half // 2, 10, text="原图", fill="#9ad", font=("Segoe UI", 10))
            if bgr_b is not None:
                pb = self._photo(bgr_b, half, ch - 30)
                self.img_b = pb
                bx = half + 15 + (half - pb.width()) // 2
                by = 20 + (ch - 30 - pb.height()) // 2
                self.canvas.create_image(bx, by, anchor="nw", image=pb)
                self.canvas.create_text(half + 15 + half // 2, 10, text="DLSS5", fill="#fa8",
                                        font=("Segoe UI", 10))

        # ----- 设置 -----
        def _apply_recipe(self, _event=None):
            r = self.recipes.get(self.v_recipe.get())
            if not r:
                return
            self.v_style.set(STYLE_CHOICES[r["style"]])
            self.v_intensity.set(r["intensity"])
            self.v_tone.set(r["local_tone"])
            self.v_struct.set(r["local_struct"])
            self.v_fidelity.set(r["color_fidelity"])
            self.v_preset.set(str(r["preset"]))
            self.v_upscale.set(r["upscale"])
            self.v_motion.set(r["motion"])
            self.v_recipe.set("自定义")

        def settings(self):
            up = {"关": 1.0, "2x": 2.0, "3x": 3.0}[self.v_upscale.get()]
            return make_settings(
                style=STYLE_CHOICES.index(self.v_style.get()),
                intensity=self.v_intensity.get(),
                local_tone=self.v_tone.get(),
                local_struct=self.v_struct.get(),
                preset=int(self.v_preset.get()),
                color_fidelity=self.v_fidelity.get(),
                upscale=up,
                use_motion=self.v_motion.get(),
            )

        # ----- 执行 -----
        def run(self):
            if self.worker and self.worker.is_alive():
                return
            self.btn_run.config(state="disabled")
            try:
                if self.kind == "image":
                    self._run_image()
                else:
                    self._run_video()
            finally:
                self.btn_run.config(state="normal")

        def _run_image(self):
            try:
                self.lbl_status.config(text="处理中…")
                self.root.update_idletasks()
                dst = process_image(self.path, self.settings())
                out = _imread_unicode(dst)
                self._show_pair(_imread_unicode(self.path), out)
                self.lbl_status.config(text="已保存: " + dst)
            except Exception as e:
                messagebox.showerror("错误", str(e))
                self.lbl_status.config(text="失败: %s" % e)

        def _run_video(self):
            self.stop_event = threading.Event()
            self.btn_stop.config(state="normal")
            self.progress.config(maximum=100, value=0)

            def work():
                try:
                    dst, n, ok = process_video(
                        self.path, self.settings(),
                        progress_cb=lambda i, t, o: self.q.put(("p", i, t, o)),
                        stop_event=self.stop_event)
                    self.q.put(("done", dst, n, ok))
                except Exception as e:
                    self.q.put(("err", str(e)))

            self.worker = threading.Thread(target=work, daemon=True)
            self.worker.start()

        def stop(self):
            if self.stop_event:
                self.stop_event.set()
            self.lbl_status.config(text="停止中…")

        # ----- 队列轮询 -----
        def _poll(self):
            try:
                while True:
                    msg = self.q.get_nowait()
                    if msg[0] == "p":
                        _, i, t, ok = msg
                        if t:
                            self.progress["value"] = i * 100.0 / t
                        self.lbl_status.config(text="帧 %d/%d (成功 %d)" % (i, t, ok))
                    elif msg[0] == "done":
                        self.progress["value"] = 100
                        self.lbl_status.config(text="已导出: %s (%d/%d 帧)" % (msg[1], msg[3], msg[2]))
                        self.btn_stop.config(state="disabled")
                    elif msg[0] == "err":
                        self.btn_stop.config(state="disabled")
                        messagebox.showerror("错误", msg[1])
                        self.lbl_status.config(text="失败: " + msg[1])
            except queue.Empty:
                pass
            self.root.after(120, self._poll)

    root = tk.Tk()
    App(root)
    root.mainloop()


# ---------- 命令行 ----------
def run_cli(args):
    p = args.input
    if os.path.isdir(p):
        media = sorted(f for f in os.listdir(p)
                       if os.path.splitext(f)[1].lower() in IMAGE_EXT | VIDEO_EXT)
        if not media:
            print("文件夹里没有可处理的媒体文件:", p)
            return 1
        print("批处理 %d 个文件 <- %s" % (len(media), p), flush=True)
        fail = 0
        for i, f in enumerate(media, 1):
            print("[%d/%d] %s" % (i, len(media), f), flush=True)
            one = argparse.Namespace(**vars(args))
            one.input = os.path.join(p, f)
            if run_cli(one) != 0:
                fail += 1
        print("批处理完成, 失败 %d 个" % fail)
        return 0 if fail == 0 else 1
    if not os.path.isfile(p):
        print("文件不存在:", p)
        return 1
    ext = os.path.splitext(p)[1].lower()
    settings = make_settings(style=args.style, intensity=args.intensity,
                             local_tone=args.local_tone, local_struct=args.local_struct,
                             skin_struct=args.skin_struct, preset=args.preset,
                             color_fidelity=args.color_fidelity,
                             upscale=args.upscale, use_motion=bool(args.motion))
    print("settings:", settings, flush=True)

    def cb(i, t, ok):
        print("frame %d/%d ok=%d" % (i, t, ok), flush=True)

    if ext in IMAGE_EXT:
        dst = process_image(p, settings)
        print("DONE ->", dst)
    elif ext in VIDEO_EXT:
        dst, n, ok = process_video(p, settings, progress_cb=cb)
        print("DONE -> %s (%d/%d frames)" % (dst, ok, n))
    else:
        print("不支持的类型:", ext)
        return 1
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="DLSS5_ScreenTool — 图片/视频神经渲染")
    ap.add_argument("--input", help="无界面模式: 处理指定图片/视频")
    ap.add_argument("--style", type=int, default=0, help="风格 0-2")
    ap.add_argument("--intensity", type=float, default=1.0)
    ap.add_argument("--local_tone", type=float, default=1.0)
    ap.add_argument("--local_struct", type=float, default=1.0)
    ap.add_argument("--skin_struct", type=float, default=1.0)
    ap.add_argument("--preset", type=int, default=1)
    ap.add_argument("--color_fidelity", type=float, default=0.0,
                    help="色彩保真 0-1, >0 时恢复部分原始色调减轻 AI 色偏")
    ap.add_argument("--upscale", type=float, default=1.0,
                    help="超分倍率 >1: 先缩小模拟低分辨率再放大, DLSS5 修复细节(2.0=2x)")
    ap.add_argument("--motion", type=int, default=0,
                    help="视频是否计算光流运动矢量(1=开, 激活时域分量)")
    a = ap.parse_args()
    if a.input:
        sys.exit(run_cli(a))
    else:
        run_gui()
