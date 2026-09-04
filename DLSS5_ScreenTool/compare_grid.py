# -*- coding: utf-8 -*-
"""
compare_grid.py — DLSS5 对比图公共库（re_compare_big.py / isaac_compare_big.py 共用）

提供:
    imread_u(path)                        支持中文/Unicode 路径的读图
    imwrite_u(path, im)                   支持 Unicode 路径的写图
    grid4(images, labels, crop, ...)      四图拼 2x2 大尺寸对比网格

为什么需要这个库:
    OpenCV 的 imread/imwrite 在 Windows 上不支持非 ASCII 路径（中文文件夹直接失败），
    所以统一走 "内存字节 <-> imdecode/imencode" 通道。

对比图规格（实测确定的模板）:
    2x2 网格 + 每格 2~3 倍最近邻放大 + 大号标签，输出宽度 >=1700px。
    早期版本曾用"四联横排 + 整体缩小"，每格只剩 300 多像素，完全看不清——已废弃。
"""
import os

import cv2
import numpy as np


def imread_u(path):
    """按字节读入再解码，绕过 OpenCV 的 ASCII 路径限制；失败给出明确提示。"""
    if not os.path.isfile(path):
        raise FileNotFoundError("文件不存在: %s" % os.path.abspath(path))
    im = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if im is None:
        raise IOError("图片解码失败（格式不支持或文件损坏）: %s" % path)
    return im


def imwrite_u(path, im):
    """先编码到内存缓冲再按字节写出；扩展名决定输出格式（.png/.jpg 均可）。"""
    ext = os.path.splitext(path)[1] or ".png"
    ok, buf = cv2.imencode(ext, im)
    if not ok:
        raise IOError("图片编码失败: %s" % path)
    buf.tofile(path)


def grid4(images, labels, crop, out_path, zoom=3):
    """
    把 4 张同尺寸图拼成一张 2x2 网格对比图并写盘。

    参数:
        images   : [原图, 变体1, 变体2, 变体3]，BGR、尺寸必须一致
        labels   : 每格标题（英文——OpenCV 的 putText 不支持中文）
        crop     : (y0, y1, x0, x1) 像素裁剪区；None = 使用整幅画面
        out_path : 输出路径（支持中文目录）
        zoom     : 每格最近邻放大倍数；像素级细节对比建议 2~3

    返回:
        实际写出的路径。
    """
    # ---- 裁剪 ----
    if crop is None:
        h, w = images[0].shape[:2]
        crop = (0, h, 0, w)
    y0, y1, x0, x1 = crop
    tiles = [im[y0:y1, x0:x1] for im in images]

    # ---- 放大（最近邻：不插值，保留原始像素边界，便于对比处理前后的锐度差异）----
    ch, cw = y1 - y0, x1 - x0
    tiles = [cv2.resize(t, (cw * zoom, ch * zoom),
                        interpolation=cv2.INTER_NEAREST) for t in tiles]
    th, tw = tiles[0].shape[:2]

    # ---- 拼接：每行 = 标签条 + 两列图，行/列之间留缝隙 ----
    gap, labh = 8, 44                       # 缝隙宽 / 标签条高（像素）
    W = tw * 2 + gap                        # 每行总宽
    rows = []
    for r in range(2):
        lab = np.full((labh, W, 3), 18, np.uint8)          # 深色标签条
        for c in range(2):
            cv2.putText(lab, labels[r * 2 + c], (12 + c * (tw + gap), 32),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                        (255, 255, 255), 2, cv2.LINE_AA)
        row = np.hstack([tiles[r * 2],
                         np.full((th, gap, 3), 45, np.uint8),
                         tiles[r * 2 + 1]])
        rows.append(np.vstack([lab, row]))
    out = np.vstack([rows[0],
                     np.full((gap, W, 3), 45, np.uint8),
                     rows[1]])

    imwrite_u(out_path, out)
    print("saved %s  (%d x %d)" % (out_path, out.shape[1], out.shape[0]),
          flush=True)
    return out_path
