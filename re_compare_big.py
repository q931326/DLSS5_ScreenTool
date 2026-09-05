# -*- coding: utf-8 -*-
"""
re_compare_big.py — DLSS5 图片素材：处理前后大尺寸 2x2 对比图（图片版模板）

默认对比 4 个版本：原图 / V1 标准 / V2 超分2x / V3 电影。
所有路径都是相对的——素材目录用 --dir 指定（默认当前工作目录），
输出对比图与素材放同一目录。中文文件夹/中文文件名均可。

用法（在任意目录下执行均可）:
    python re_compare_big.py --dir "C:\\...\\DLSS5Compare"        # 指定素材目录
    python re_compare_big.py --dir . --orig a.jpg --v1 b.png    # 逐个指定文件名
    python re_compare_big.py --dir . --no-street                # 只出人脸对比图

默认文件名对应"官网示例图三版本"的实测产物；换素材时用
--orig / --v1 / --v2 / --v3 覆盖即可。
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compare_grid import imread_u, grid4  # noqa: E402  (公共库在脚本同目录)

HERE = os.path.dirname(os.path.abspath(__file__))   # 脚本目录（兜底搜索路径）

# ---------- 默认配置（全部可被命令行覆盖） ----------
DEFAULTS = {
    "orig": "1a45487e-ee18-4d28-aef8-d298c80a59b1.jpeg",  # 原图（官网 DLSS5 Off 示例）
    "v1": "re_v1_std.png",    # DLSS5 标准: 强度 1.0
    "v2": "re_v2_sr.png",     # DLSS5 超分 2x: 强度 1.2
    "v3": "re_v3_cine.png",   # DLSS5 电影: style 2 + Preset 2 + 强度 1.5
}
LABELS = ["Original", "V1 std", "V2 SR2x", "V3 cinema"]

# 对比区域：(y0, y1, x0, x1) 均为画面比例 0~1，与分辨率无关，换素材不用改
CROPS = [
    ("re_compare_face.png",   (0.15, 0.49, 0.28, 0.53), 3),  # 人脸区，3x 放大
    ("re_compare_street.png", (0.18, 0.61, 0.52, 0.89), 2),  # 街道/招牌区，2x 放大
]


def parse_args():
    ap = argparse.ArgumentParser(description="DLSS5 图片 2x2 对比图生成")
    ap.add_argument("--dir", default=".",
                    help="素材所在目录（默认: 当前工作目录）")
    ap.add_argument("--orig", help="原图文件名（覆盖默认）")
    ap.add_argument("--v1", help="变体1 文件名（标准参数）")
    ap.add_argument("--v2", help="变体2 文件名（超分）")
    ap.add_argument("--v3", help="变体3 文件名（电影）")
    ap.add_argument("--no-face", action="store_true", help="跳过人脸对比图")
    ap.add_argument("--no-street", action="store_true", help="跳过街道对比图")
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


def main():
    a = parse_args()
    dirpath = os.path.abspath(a.dir)

    # 依次读入 4 个版本
    imgs = [imread_u(resolve(dirpath, k, getattr(a, k)))
            for k in ("orig", "v1", "v2", "v3")]

    # 尺寸一致性检查：不一致会导致裁剪越界、拼图错位，提前拦下
    h, w = imgs[0].shape[:2]
    for i, im in enumerate(imgs[1:], 1):
        if im.shape[:2] != (h, w):
            raise SystemExit("第 %d 张图尺寸 (%dx%d) 与原图 (%dx%d) 不一致，"
                             "请先统一尺寸" % (i, im.shape[1], im.shape[0], w, h))

    # 逐个区域出图：比例 -> 像素
    for fname, (fy0, fy1, fx0, fx1), zoom in CROPS:
        if (a.no_face and "face" in fname) or (a.no_street and "street" in fname):
            continue
        crop = (int(fy0 * h), int(fy1 * h), int(fx0 * w), int(fx1 * w))
        grid4(imgs, LABELS, crop, os.path.join(dirpath, fname), zoom=zoom)


if __name__ == "__main__":
    main()
