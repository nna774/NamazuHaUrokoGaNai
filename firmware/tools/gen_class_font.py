#!/usr/bin/env python3
"""震度階級表示用の大型フォントヘッダを生成する。

LCDの震度階級表示は '0'-'7' と '+','-'（精密値用に '8','9','.' も）しか
使わないので、その字種だけを収めた Adafruit GFX 形式のフォントを TTF から
起こして TFT_eSPI の setFreeFont() で使う。内蔵 font6(48px) は '+' を
持たず、font4 の setTextSize(3) 拡大はギザギザになるための代替。

使い方:
    python3 gen_class_font.py DejaVuSans-Bold.ttf > ../lib/Display/ClassFont.h

TTF は DejaVu Sans Bold を想定（Bitstream Vera 系ライセンスで埋め込み自由）:
    https://github.com/dejavu-fonts/dejavu-fonts/releases/tag/version_2_37

依存: Pillow（リポジトリの .venv に入っている）
"""

import sys

from PIL import Image, ImageDraw, ImageFont

# 生成する字種。Adafruit GFX 形式は first..last の連続レンジ必須なので
# '+'(0x2B)〜'9'(0x39) を通しで持ち、使わない ',' '/' は空グリフにする。
FIRST = 0x2B
LAST = 0x39
UNUSED = {ord(","), ord("/")}

# 数字の字面高さ(px)。画面は横240x縦135で、上段(〜y20)と継続ステート(y110〜)の
# 間の帯をほぼ使い切る値。MC_DATUM の中央揃えはフォント内の最大アセント
# (=数字の高さ)基準になる。
DIGIT_HEIGHT = 80


def glyph_bitmap(font, ascent, ch):
    """1文字を描画して (bitmap(0/1の2次元), width, height, xOffset, yOffset, xAdvance) を返す。"""
    pad = 32
    size = DIGIT_HEIGHT * 3
    img = Image.new("L", (size, size), 0)
    ImageDraw.Draw(img).text((pad, pad), ch, font=font, fill=255)
    box = img.getbbox()
    advance = round(font.getlength(ch))
    if box is None:  # 空グリフ
        return [], 0, 0, 0, 0, advance
    x0, y0, x1, y1 = box
    rows = []
    px = img.load()
    for y in range(y0, y1):
        rows.append([1 if px[x, y] >= 128 else 0 for x in range(x0, x1)])
    # xOffset/yOffset はペン位置(ベースライン左端)からの字面左上の相対位置
    return rows, x1 - x0, y1 - y0, x0 - pad, y0 - (pad + ascent), advance


def pick_size(path):
    """'0' の字面高さが DIGIT_HEIGHT になる em サイズを探す。"""
    for size in range(DIGIT_HEIGHT, DIGIT_HEIGHT * 2):
        font = ImageFont.truetype(path, size)
        ascent, _ = font.getmetrics()
        _, _, h, _, _, _ = glyph_bitmap(font, ascent, "0")
        if h >= DIGIT_HEIGHT:
            return font
    raise RuntimeError("target size not reached")


def main():
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <font.ttf>")
    path = sys.argv[1]
    font = pick_size(path)
    ascent, _ = font.getmetrics()

    bitmaps = []  # 全グリフ連結のビット列
    glyphs = []  # (offset, w, h, adv, xo, yo, ch)
    for code in range(FIRST, LAST + 1):
        ch = chr(code)
        if code in UNUSED:
            glyphs.append((len(bitmaps) // 8 + (1 if len(bitmaps) % 8 else 0), 0, 0, 0, 0, 0, ch))
            continue
        rows, w, h, xo, yo, adv = glyph_bitmap(font, ascent, ch)
        # Adafruit GFX はビットを行またぎで詰める(行ごとのバイト境界なし)
        offset_bits = len(bitmaps)
        assert offset_bits % 8 == 0
        bits = [b for row in rows for b in row]
        bits += [0] * (-len(bits) % 8)  # グリフ単位でバイト境界に揃える
        bitmaps.extend(bits)
        glyphs.append((offset_bits // 8, w, h, adv, xo, yo, ch))

    data = bytes(
        sum(bit << (7 - i) for i, bit in enumerate(bitmaps[p : p + 8]))
        for p in range(0, len(bitmaps), 8)
    )
    max_ascent = max(-yo for _, _, _, _, _, yo, _ in glyphs)
    y_advance = round(font.size * 1.2)

    out = sys.stdout
    out.write("// 震度階級表示用フォント。firmware/tools/gen_class_font.py で生成(手で編集しない)。\n")
    out.write(f"// 元フォント: DejaVu Sans Bold / 数字の字面高さ {DIGIT_HEIGHT}px / 字種 '+'-'9'\n")
    out.write("#pragma once\n#include <TFT_eSPI.h>\n\n")
    out.write(f"const uint8_t ClassFontBitmaps[] PROGMEM = {{\n")
    for p in range(0, len(data), 12):
        out.write("  " + ", ".join(f"0x{b:02X}" for b in data[p : p + 12]) + ",\n")
    out.write("};\n\n")
    out.write("const GFXglyph ClassFontGlyphs[] PROGMEM = {\n")
    for off, w, h, adv, xo, yo, ch in glyphs:
        out.write(f"  {{{off:5d}, {w:3d}, {h:3d}, {adv:3d}, {xo:3d}, {yo:4d}}},  // '{ch}'\n")
    out.write("};\n\n")
    out.write("const GFXfont ClassFont PROGMEM = {\n")
    out.write("    (uint8_t*)ClassFontBitmaps, (GFXglyph*)ClassFontGlyphs,\n")
    out.write(f"    0x{FIRST:02X}, 0x{LAST:02X}, {y_advance}}};\n\n")
    out.write("// 数字の字面高さ(=フォント内最大アセント)。MC_DATUM の中央揃えや\n")
    out.write("// 下端座標の計算はこの値基準になる。\n")
    out.write(f"constexpr int kClassFontAscent = {max_ascent};\n")


if __name__ == "__main__":
    main()
