
# Ace-CC-Creater-SwamStrings

把 ACE Studio 的人声工程 .acep 转成 SWAM Solo Violin 可用的 MIDI - 用 ACE 的 AI 演唱动态(力度/张力/颤音)驱动一把小提琴音源。

## 它做什么

ACE Studio 渲染工程时会在内部生成人声动态参数并写入 .acep(需在 ACE 里固定/渲染后保存才会落盘)。本工具把这些参数提取并映射成 SWAM 小提琴的演奏控制:

| ACE 参数 | MIDI 控制 | 说明 |
|---|---|---|
| Energy(力度) | CC11 Expression | 强弱动态 0-127 |
| Tension(张力) | CC2 Bow Pressure | 弓压(需在 SWAM 指派)45-88 |
| 颤音(pitchDelta) | Pitch Bend | ±30 cent + 渐入渐出,每音结束归 0 |

ACE 负责想出一段自然的人声表现,SWAM 小提琴负责拉出来。

## 安装

需要 Python 3.9+,建议 3.10+。

    git clone <your-repo-url>
    cd Ace-CC-Creater-SwamStrings
    pip install -r requirements.txt

GUI 使用 Python 自带标准库 tkinter(Windows Python 一般自带)。

## 使用

### 方式一:桌面 GUI(推荐)

- Windows:双击 启动Ace-CC-Creater.bat,或双击 Ace-CC-Creater-SwamStrings.pyw
- 其他:python -m gui.main

1. 点 浏览... 选择 .acep 工程(需固定/渲染后保存,才有 pitchDelta/颤音曲线)
2. 拖动滑块调参(默认即调好的值,可用 重置为默认 还原)
3. 点 生成 MIDI,导入 Cubase/音源试听

### 方式二:命令行

    python -m core.ace2swam <in.acep> <out.mid>                    # 默认参数
    python -m core.ace2swam <in.acep> <out.mid> --amp 40 --attack 0.3

## 参数

| 参数 | 含义 | 默认 |
|---|---|---|
| amp | 颤音半峰幅度(cent) | 30 |
| attack | 颤音渐入比例 | 0.20 |
| release | 颤音渐出比例 | 0.15 |
| pbrange | 弯音范围(半音) | 2 |
| dyn_lo/dyn_hi | CC11 动态范围 | 0 / 127 |
| bow_lo/bow_hi | CC2 弓压范围 | 45 / 88 |
| min_sustain | 最短颤音音符(秒) | 0.5 |
| instrument | MIDI program | 40(小提琴) |

## 目录结构

    Ace-CC-Creater-SwamStrings/
    +- core/ace2swam.py       # 核心库:解码 ACEP2 + 转换(CLI 与可 import)
    +- gui/main.py            # 桌面 GUI(tkinter)
    +- Ace-CC-Creater-SwamStrings.pyw   # GUI 启动器
    +- 启动Ace-CC-Creater.bat          # Windows 双击启动
    +- requirements.txt
    +- output/               # 生成的 MIDI(自动 gitignore)

## 技术背景 / 致谢

- 本工具解析的 ACE .acep 格式(ACEP2 -> zstd -> CBOR)依赖社区逆向成果,主要参考 SoulMelody/LibreSVIP 与 flutydeer/AceCompressor。
- SWAM 控制映射参考 Audio Modeling SWAM Strings 官方文档。
- MIDI 写入使用 mido,zstd 解压使用 zstandard。

## 局限与提醒

- 需要 ACE Studio 导出固定/渲染后保存的 .acep(未渲染工程缺少 pitchDelta/颤音曲线)。
- 默认参数针对 SWAM Solo Violin 键盘预设调优;换音源/乐器需重调。
- 仅供个人创作使用,请遵守相关软件与服务条款。
