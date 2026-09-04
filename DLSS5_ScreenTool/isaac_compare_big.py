# -*- coding: utf-8 -*-
"""
isaac_compare_big.py — DLSS5 视频素材：抽同一帧做大尺寸 2x2 对比（视频版模板）

流程: 从 4 个视频（原版 + 3 个 DLSS5 变体）各取同一帧号 -> 拼对比图。
所有路径都是相对的——素材目录用 --dir 指定（默认当前工作目录），
输出对比图与素材放同一目录。

中文文件名的视频会先复制成 ASCII 临时副本再读（OpenCV 的 VideoCapture
在 Windows 不支持非 ASCII 路径），临时目录脚本结束时自动清理。

用法:
    python isaac_compare_big.py --dir "C:\\...\\DLSS5Compare"
    python isaac_compare_big.py --dir . --frame 100            # 换抽帧位置
    python isaac_compare_big.py --dir . --crop 0.2,0.8,0.3,0.8 --zoom 4
    python isaac_compare_big.py --dir . --orig a.mp4 --v1 b.mp4 --v2 c.mp4 --v3 d.mp4
"""
import argparse
import os
import shutil
import sys
import tempfile

import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compare_grid import grid4  # noqa: E402  (公共库在脚本同目录)

HERE = os.path.dirname(os.path.abspath(__file__))   # 脚本目录（兜底搜索路径）

# ---------- 默认配置（全部可被命令行覆盖） ----------
DEFAULTS = {
    "orig": "Isaac_test.mp4",                # 原视频
    "v1": "Isaac_test_dlss_v1_标准.mp4",      # 仿真保真: 强度 1.0 + 运动矢量
    "v2": "Isaac_test_dlss_v2_超分2x.mp4",    # 细节重建: 超分 2x + 运动矢量
    "v3": "Isaac_test_dlss_v3_电影.mp4",      # 电影感: style2 + Preset2 + 强度 1.5
}
LABELS = ["Original", "V1 std", "V2 SR2x", "V3 cinema"]
DEFAULT_CROP = (0.15, 0.75, 0.30, 0.75)     # 默认对比区: 上半身人物 (画面比例 y0,y1,x0,x1)
DEFAULT_FRAME = 200                          # 默认抽帧号


def parse_args():
    ap = argparse.ArgumentParser(description="DLSS5 视频 2x2 对比图生成")
    ap.add_argument("--dir", default=".",
                    help="素材所在目录（默认: 当前工作目录）")
    ap.add_argument("--frame", type=int, default=DEFAULT_FRAME,
                    help="抽帧号（默认 %d）" % DEFAULT_FRAME)
    ap.add_argument("--crop", default=None,
                    help="对比区 y0,y1,x0,x1（画面比例 0~1，默认 %.2f,%.2f,%.2f,%.2f）"
                         % DEFAULT_CROP)
    ap.add_argument("--zoom", type=int, default=3, help="每格放大倍数（默认 3）")
    ap.add_argument("--orig", help="原视频文件名（覆盖默认）")
    ap.add_argument("--v1", help="变体1 视频文件名")
    ap.add_argument("--v2", help="变体2 视频文件名")
    ap.add_argument("--v3", help="变体3 视频文件名")
    ap.add_argument("--out", default="isaac_dlss_compare.png", help="输出文件名")
    return ap.parse_args()


def resolve(dirpath, key, override):
    """按优先级查找文件: 素材目录 -> 脚本目录；都找不到时给出可操作的提示。"""
    name = override or DEFAULTS[key]
    for base in (dirpath, HERE):
        path = os.path.join(base, name)
        if os.path.isfile(path):
            return path
    raise FileNotFoundError(
        "找不到 %s (%s)\n  已尝试: %s 和 %s\n"
        "  -> 用 --dir 指定素材目录，或 --%s 直接指定文件名"
        % (key, name, dirpath, HERE, key))


def grab_frame(path, idx):
    """从视频取指定帧；打不开或取不到返回 None（不做二次解释，交给调用方）。"""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return None
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, fr = cap.read()
        return fr if ok else None
    finally:
        cap.release()


def load_frame(path, idx, tmpdir, tag):
    """
    优先直接读；打不开（最常见原因是中文路径）则复制成 ASCII 临时副本再读。
    shutil.copy 走 Windows 原生 API，中文路径没问题——只有 OpenCV 不行。
    """
    fr = grab_frame(path, idx)
    if fr is not None:
        return fr
    tmp = os.path.join(tmpdir, "%s%s" % (tag, os.path.splitext(path)[1]))
    shutil.copy(path, tmp)
    fr = grab_frame(tmp, idx)
    if fr is None:
        raise IOError("无法读取视频帧（文件损坏、编解码器缺失或帧号越界？）: %s" % path)
    return fr


def main():
    a = parse_args()
    dirpath = os.path.abspath(a.dir)

    # 解析对比区: 命令行 "y0,y1,x0,x1" (比例) -> 像素（读入第一帧后换算）
    if a.crop:
        fy0, fy1, fx0, fx1 = (float(v) for v in a.crop.split(","))
    else:
        fy0, fy1, fx0, fx1 = DEFAULT_CROP

    # tempfile 自动清理: 中文文件名视频的 ASCII 副本只活在本函数作用域内
    frames = []
    with tempfile.TemporaryDirectory(prefix="dlss_cmp_") as tmpdir:
        for i, key in enumerate(("orig", "v1", "v2", "v3")):
            path = resolve(dirpath, key, getattr(a, key))
            fr = load_frame(path, a.frame, tmpdir, "v%d" % i)
            frames.append(fr)
            print("loaded frame %d from %s" % (a.frame, os.path.basename(path)),
                  flush=True)

    # 尺寸一致性检查：变体若做过不同倍率超分，分辨率可能不同
    h, w = frames[0].shape[:2]
    for i, fr in enumerate(frames[1:], 1):
        if fr.shape[:2] != (h, w):
            raise SystemExit("第 %d 个视频帧尺寸 (%dx%d) 与原视频 (%dx%d) 不一致"
                             % (i, fr.shape[1], fr.shape[0], w, h))

    crop = (int(fy0 * h), int(fy1 * h), int(fx0 * w), int(fx1 * w))
    grid4(frames, LABELS, crop, os.path.join(dirpath, a.out), zoom=a.zoom)


if __name__ == "__main__":
    main()
