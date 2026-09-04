#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ace-CC-Creater - Desktop GUI
选择 .acep -> 选音源种类 -> 按乐器目录选参数预设(可另存) -> 生成 MIDI

目录预设结构 (presets/ 下):
    presets/<音源种类>/<乐器族>/<乐器>/<预设名>.json

运行: python gui/main.py   (或 gui/main.pyw 双击)
"""
import os, sys, json, pathlib, threading, traceback, tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
from core import ace2swam as A

PRESETS_ROOT = APP / 'presets'

# ---- 音源种类: (内部名, 显示名) ----
# 目前只做了 SWAM 弦乐; 以后加其它音源直接在此追加。
SOURCES = [
    ('SWAM', 'SWAM Solo Strings'),
]

# ---- 每音源的乐器族/乐器注册表: 源 -> dict(family=乐器族, instruments=[(乐器名, GM program)]) ----
# GM 提琴音色号: 小提琴40 / 中提琴41 / 大提琴42 / 低音提琴43
SOURCE_INSTRUMENTS = {
    'SWAM': {
        'family': '提琴',
        'instruments': [
            ('小提琴', 40),
            ('中提琴', 41),
            ('大提琴', 42),
            ('低音提琴', 43),
        ],
    },
}
DEFAULT_PRESET = '默认.json'   # 每乐器的默认(种子)预设文件名

# ---- 参数定义: key -> (标签, 最小值, 最大值, 步长, 类型) ----
PARAMS = [
    ('amp',        '颤音幅度(±cent)', 5, 120, 1, 'float'),
    ('attack',     '颤音渐入比例', 0.0, 0.6, 0.01, 'float'),
    ('release',    '颤音渐出比例', 0.0, 0.6, 0.01, 'float'),
    ('pbrange',    '弯音范围(半音)', 1, 12, 1, 'float'),
    ('dyn_lo',     'CC11 动态 下限', 0, 127, 1, 'int'),
    ('dyn_hi',     'CC11 动态 上限', 0, 127, 1, 'int'),
    ('bow_lo',     'CC2 弓压 下限', 0, 127, 1, 'int'),
    ('bow_hi',     'CC2 弓压 上限', 0, 127, 1, 'int'),
    ('min_sustain', '最短颤音音符(秒)', 0.2, 2.0, 0.05, 'float'),
    ('bowpos_val', '弓位/把位 CC 值', 0, 127, 1, 'int'),
    ('instrument', 'MIDI 音色号(GM)', 0, 127, 1, 'int'),
]
def source_dir(source_id):
    return PRESETS_ROOT / source_id


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Ace-CC-Creater')
        # 高度自适应屏幕(避免小屏幕窗口超出可视区, 底部按钮被截掉)
        sw = self.winfo_screenwidth(); sh = self.winfo_screenheight()
        w = min(660, sw - 80); h = min(820, sh - 140)
        self.geometry(f'{max(560, w)}x{max(480, h)}')
        self.cfg = dict(A.DEFAULT)
        self.vars = {}
        self._source = tk.StringVar(value=SOURCES[0][1])
        self._instrument = tk.StringVar()
        self._cur_preset = None          # 当前已载入预设的绝对路径
        self._preset_meta = None         # 当前预设的元数据(用于识别)
        self._build()
        self._rescan_sources()
        # 默认选中该源第一个乐器,并确保其默认预设存在
        self._init_instrument_dropdown()
        self._load_instrument_default()

    # ============ UI 构建 ============
    def _make_scrollable_body(self):
        """创建一个可垂直滚动的 body 容器(小屏幕也能滚到底看到生成按钮)。"""
        container = ttk.Frame(self)
        container.pack(fill='both', expand=True)
        canvas = tk.Canvas(container, highlightthickness=0, borderwidth=0)
        vsb = ttk.Scrollbar(container, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        body = ttk.Frame(canvas)
        win = canvas.create_window((0, 0), window=body, anchor='nw')
        def _on_body_cfg(_e):
            canvas.configure(scrollregion=canvas.bbox('all'))
        def _on_canvas_cfg(e):
            canvas.itemconfig(win, width=e.width)
        body.bind('<Configure>', _on_body_cfg)
        canvas.bind('<Configure>', _on_canvas_cfg)
        def _wheel(e):
            canvas.yview_scroll(int(-e.delta / 120), 'units')
        canvas.bind_all('<MouseWheel>', _wheel)
        self._body = body

    def _build(self):
        pad = {'padx': 10, 'pady': 4}
        self._make_scrollable_body()
        B = self._body  # 内容都挂到可滚动 body

        # 0) 音源种类 (打开先选)
        sf = ttk.LabelFrame(B, text='① 音源种类 与 目标乐器', padding=8)
        sf.pack(fill='x', **pad)
        row = ttk.Frame(sf); row.pack(fill='x')
        ttk.Label(row, text='音源:').pack(side='left')
        self.src_combo = ttk.Combobox(row, textvariable=self._source, state='readonly',
                                      values=[s[1] for s in SOURCES], width=22)
        self.src_combo.pack(side='left', padx=6)
        self.src_combo.bind('<<ComboboxSelected>>', lambda e: self._on_source_change())
        self._source_meta = {s[1]: s[0] for s in SOURCES}  # 显示名->内部名
        ttk.Label(sf, text='(目前仅 SWAM; 预设按此源分组存放)', foreground='gray').pack(side='left', padx=8)

        row2 = ttk.Frame(sf); row2.pack(fill='x', pady=(6, 0))
        ttk.Label(row2, text='目标乐器:').pack(side='left')
        self.inst_combo = ttk.Combobox(row2, textvariable=self._instrument, state='readonly', width=22)
        self.inst_combo.pack(side='left', padx=6)
        self.inst_combo.bind('<<ComboboxSelected>>', lambda e: self._on_instrument_change())
        ttk.Label(row2, text='(载入该乐器默认预设,可再调/另存)', foreground='gray').pack(side='left', padx=8)

        # 1) 参数预设 (按乐器目录)
        pf = ttk.LabelFrame(B, text='② 参数预设 (按乐器目录: 音源/乐器族/乐器)', padding=8)
        pf.pack(fill='x', **pad)
        brow = ttk.Frame(pf); brow.pack(fill='x')
        ttk.Label(brow, text='预设根目录:').pack(side='left')
        self.preset_root_var = tk.StringVar(value=str(PRESETS_ROOT))
        ttk.Label(brow, textvariable=self.preset_root_var, foreground='gray').pack(side='left', padx=6)
        ttk.Button(brow, text='打开预设目录…', command=self._pick_presets_root).pack(side='left', padx=4)
        ttk.Button(brow, text='刷新', command=self._rescan_preset_tree).pack(side='left', padx=4)

        # 目录树: 音源/乐器族/乐器,叶子为 .json 预设
        treewrap = ttk.Frame(pf); treewrap.pack(fill='both', expand=True, pady=(6, 0))
        self.tree = ttk.Treeview(treewrap, columns=('meta',), show='tree', height=9)
        self.tree.column('#0', width=220, anchor='w')
        self.tree.column('meta', width=230, anchor='w')
        self.tree.heading('meta', text='')
        ysb = ttk.Scrollbar(treewrap, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side='left', fill='both', expand=True)
        ysb.pack(side='right', fill='y')
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)
        self.tree.bind('<Double-1>', lambda e: self._load_selected_preset(confirm=False))
        brow2 = ttk.Frame(pf); brow2.pack(fill='x', pady=(6, 0))
        self.lbl_loaded = ttk.Label(brow2, text='未载入预设', foreground='gray')
        self.lbl_loaded.pack(side='left')
        ttk.Button(brow2, text='载入所选预设', command=lambda: self._load_selected_preset(confirm=False)).pack(side='right', padx=4)
        ttk.Button(brow2, text='删除所选预设', command=self._delete_selected_preset).pack(side='right', padx=4)
        ttk.Button(brow2, text='另存为预设…', command=self._save_as_preset).pack(side='right', padx=4)

        # 2) 工程文件 (.acep)
        fr = ttk.LabelFrame(B, text='③ 工程文件 (.acep)', padding=8)
        fr.pack(fill='x', **pad)
        row = ttk.Frame(fr); row.pack(fill='x')
        self.inp_var = tk.StringVar()
        e = ttk.Entry(row, textvariable=self.inp_var, width=50); e.pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='浏览…', command=self._pick).pack(side='left', padx=4)
        row2 = ttk.Frame(fr); row2.pack(fill='x', pady=(6, 0))
        self.out_var = tk.StringVar(value=str(APP / 'output'))
        ttk.Label(row2, text='输出目录:').pack(side='left')
        ttk.Entry(row2, textvariable=self.out_var, width=30).pack(side='left', padx=4, fill='x', expand=True)
        ttk.Button(row2, text='浏览…', command=self._pick_out).pack(side='left', padx=4)

        # 3) 参数滑块区
        gp = ttk.LabelFrame(B, text='④ 参数 (载入预设或手动调整)', padding=8)
        gp.pack(fill='x', **pad)
        self.widgets = {}
        for key, label, vmin, vmax, step, typ in PARAMS:
            r = ttk.Frame(gp); r.pack(fill='x', pady=2)
            self.vars[key] = tk.DoubleVar(value=A.DEFAULT[key])
            ttk.Label(r, text=label, width=26, anchor='w').pack(side='left')
            s = ttk.Scale(r, from_=vmin, to=vmax, orient='horizontal',
                          variable=self.vars[key], command=lambda k=key: self._show(k))
            s.pack(side='left', fill='x', expand=True, padx=6)
            lbl = ttk.Label(r, text=str(round(A.DEFAULT[key], 2)), width=7, anchor='e')
            lbl.pack(side='left')
            self.widgets[key] = (s, lbl)
        ttk.Button(gp, text='重置为默认', command=self._reset).pack(anchor='e', pady=(6, 0))

        # 4) 动作
        act = ttk.Frame(B); act.pack(fill='x', **pad)
        ttk.Button(act, text='生成 MIDI', command=self._generate).pack(side='left')
        self.status = tk.StringVar(value='就绪')
        ttk.Label(act, textvariable=self.status).pack(side='left', padx=12)

    # ============ 音源 & 预设树 ============
    def _rescan_sources(self):
        """确保每个音源的目录结构存在。"""
        for sid, _name in SOURCES:
            d = source_dir(sid)
            d.mkdir(parents=True, exist_ok=True)

    # ---- 目标乐器 处理 ----
    def _sid(self):
        return self._source_meta.get(self._source.get(), SOURCES[0][0])

    def _family_and_instruments(self, sid):
        spec = SOURCE_INSTRUMENTS.get(sid)
        return (spec['family'], spec['instruments']) if spec else ('提琴', [])

    def _init_instrument_dropdown(self):
        """按当前源填充乐器下拉;若无选择则取第一个。"""
        sid = self._sid()
        _fam, instruments = self._family_and_instruments(sid)
        names = [n for n, _p in instruments]
        self.inst_combo.configure(values=names)
        if not self._instrument.get() or self._instrument.get() not in names:
            self._instrument.set(names[0] if names else '')

    def _on_source_change(self):
        self._init_instrument_dropdown()
        self._load_instrument_default()

    def _on_instrument_change(self):
        self._load_instrument_default()

    def _default_preset_path(self, sid, instrument_name):
        fam, instruments = self._family_and_instruments(sid)
        return source_dir(sid) / fam / instrument_name / DEFAULT_PRESET

    def _instrument_program(self, sid, instrument_name):
        _fam, instruments = self._family_and_instruments(sid)
        for n, p in instruments:
            if n == instrument_name: return p
        return A.DEFAULT['instrument']

    def _load_instrument_default(self, reselect_tree=True):
        """载入当前源+目标乐器的默认预设;不存在则先生成种子。"""
        sid = self._sid()
        inst = self._instrument.get()
        if not inst: return
        path = self._default_preset_path(sid, inst)
        if not path.exists():
            self._ensure_default_preset(sid, inst, path)
        ok, msg = self._load_preset_file(str(path), sid)
        if not ok:
            messagebox.showerror('错误', msg)
        if reselect_tree:
            self._rescan_preset_tree()

    def _ensure_default_preset(self, sid, instrument_name, path):
        """为该乐器生成默认(种子)预设: 以现滑块值或 core 默认为基, 只把 program 设为该乐器 GM 号。"""
        prog = self._instrument_program(sid, instrument_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        vals = dict(self._slider_values())
        for key, label, vmin, vmax, step, typ in PARAMS:
            if key not in vals:
                v = A.DEFAULT[key]
                vals[key] = int(round(v)) if typ == 'int' else v
        vals['instrument'] = prog
        fam = SOURCE_INSTRUMENTS[sid]['family']
        data = {'meta': {'source': sid, 'family': fam, 'instrument': instrument_name,
                         'label': f'默认种子(GM {prog}), 待校准'},
                'params': vals}
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return path

    def _pick_presets_root(self):
        global PRESETS_ROOT
        d = filedialog.askdirectory(initialdir=str(PRESETS_ROOT), title='选择预设根目录')
        if d:
            PRESETS_ROOT = pathlib.Path(d)
            self.preset_root_var.set(str(PRESETS_ROOT))
            self._rescan_preset_tree()

    def _rescan_preset_tree(self):
        """重建目录树。第一层=音源,往下按 乐器族/乐器,叶子=.json。"""
        # 记录展开状态
        open_paths = set()
        for iid in self.tree.get_children(''):
            if self.tree.item(iid, 'open'): open_paths.add(iid)
        self.tree.delete(*self.tree.get_children(''))
        self._tree_iid = {}  # 绝对路径 -> iid
        sid = self._source_meta.get(self._source.get(), SOURCES[0][0])
        root = source_dir(sid)
        root.mkdir(parents=True, exist_ok=True)
        # 第一层: 音源节点
        src_iid = self.tree.insert('', 'end', text=f'[{sid}]  {self._source.get()}', open=True)
        self._tree_iid[str(root)] = src_iid
        # 乐器族 / 乐器 / 预设
        self._add_dir_children(root, src_iid, sid)
        # 恢复展开 + 高亮当前载入预设
        self._expand_restore(open_paths)
        if self._cur_preset and os.path.exists(self._cur_preset):
            self._tree_select_path(self._cur_preset)

    def _add_dir_children(self, dir_path, parent_iid, sid):
        try:
            items = sorted(os.listdir(dir_path))
        except OSError:
            return
        dirs, files = [], []
        for name in items:
            p = os.path.join(dir_path, name)
            if os.path.isdir(p): dirs.append(name)
            elif name.lower().endswith('.json'): files.append(name)
        for name in dirs:
            p = os.path.join(dir_path, name)
            iid = self.tree.insert(parent_iid, 'end', text=name, values=('',))
            self._tree_iid[p] = iid
            self._add_dir_children(p, iid, sid)
        for name in sorted(files):
            p = os.path.join(dir_path, name)
            meta = self._read_preset_meta(p)
            display = name
            if meta and meta.get('label'):
                display = f"{name}   ({meta['label']})"
            iid = self.tree.insert(parent_iid, 'end', text=name, values=(display,))
            self._tree_iid[p] = iid

    def _expand_restore(self, open_paths):
        for iid, p in self._tree_iid.items():
            if p in open_paths and iid != '':
                self.tree.item(iid, open=True)

    def _tree_select_path(self, path):
        iid = self._tree_iid.get(path)
        if iid is None: return
        # 展开其父链使其可见
        pid = self.tree.parent(iid)
        while pid:
            self.tree.item(pid, open=True)
            pid = self.tree.parent(pid)
        self.tree.see(iid)
        self.tree.selection_set(iid)

    def _on_tree_select(self, _evt):
        sel = self.tree.selection()
        if not sel: return
        iid = sel[0]
        # 只对叶子(.json)显示,双击或按钮才载入
        path = next((p for p, v in self._tree_iid.items() if v == iid), None)
        if path and path.lower().endswith('.json'):
            pass

    # ---- 预设 读写 ----
    @staticmethod
    def _read_preset_meta(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                d = json.load(f)
            return d if isinstance(d, dict) else None
        except Exception:
            return None

    def _cur_source_id(self):
        return self._source_meta.get(self._source.get(), SOURCES[0][0])

    def _cur_source_name(self):
        for sid, name in SOURCES:
            if sid == self._cur_source_id(): return name
        return SOURCES[0][1]

    def _read_cfg(self):
        cfg = dict(A.DEFAULT)
        for key, label, vmin, vmax, step, typ in PARAMS:
            v = self.vars[key].get()
            cfg[key] = int(round(v)) if typ == 'int' else v
        if cfg['dyn_lo'] > cfg['dyn_hi']: cfg['dyn_lo'], cfg['dyn_hi'] = cfg['dyn_hi'], cfg['dyn_lo']
        if cfg['bow_lo'] > cfg['bow_hi']: cfg['bow_lo'], cfg['bow_hi'] = cfg['bow_hi'], cfg['bow_lo']
        return cfg

    def _slider_values(self):
        vals = {}
        for key, label, vmin, vmax, step, typ in PARAMS:
            v = self.vars[key].get()
            vals[key] = int(round(v)) if typ == 'int' else round(v, 4)
        return vals

    def _apply_cfg(self, cfg):
        for key, label, vmin, vmax, step, typ in PARAMS:
            if key not in cfg: continue
            v = min(max(float(cfg[key]), vmin), vmax)
            self.vars[key].set(v)
            self._show(key)

    def _load_preset_file(self, path, source_id):
        """载入 json,把其中参数应用到滑块。返回 (成功, 消息)。"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                d = json.load(f)
        except Exception as e:
            return False, f'读取失败: {e}'
        if not isinstance(d, dict) or 'params' not in d:
            return False, '文件不是 Ace-CC 预设格式(缺 params)'
        params = d.get('params', {})
        self._apply_cfg(params)
        # 记录来源与乐器族,用于“另存为”默认位置
        self._cur_preset = os.path.abspath(path)
        rel = os.path.relpath(path, source_dir(source_id))
        parts = rel.split(os.sep)
        meta = dict(d.get('meta', {}))
        self._cur_meta = meta
        self.lbl_loaded.config(text=f'已载入: {self._cur_preset}',
                               foreground='#0a7a0a')
        return True, f'已载入: {self._cur_preset}'

    def _load_selected_preset(self, confirm=True):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo('提示', '请先在目录树里选择一个预设文件'); return
        iid = sel[0]
        path = next((p for p, v in self._tree_iid.items() if v == iid), None)
        if not path or not path.lower().endswith('.json'):
            messagebox.showinfo('提示', '请选择一个 .json 预设文件'); return
        ok, msg = self._load_preset_file(path, self._cur_source_id())
        if not ok:
            messagebox.showerror('错误', msg)

    def _save_as_preset(self):
        """在当前音源下,让用户选/建 乐器族-乐器 目录并命名,写入预设。"""
        sid = self._cur_source_id()
        src_dir = source_dir(sid)
        # 现有乐器族/乐器 供下拉
        families = [d for d in sorted(os.listdir(src_dir)) if os.path.isdir(os.path.join(src_dir, d))] if os.path.isdir(src_dir) else []
        win = tk.Toplevel(self); win.title('另存为预设'); win.grab_set()
        win.geometry('400x230')
        body = ttk.Frame(win, padding=12); body.pack(fill='both', expand=True)
        ttk.Label(body, text=f'音源: {sid}').grid(row=0, column=0, sticky='w')
        f0 = ttk.Frame(body); f0.grid(row=1, column=0, sticky='we', pady=3)
        ttk.Label(body, text='乐器族(如 提琴):').grid(row=1, column=0, sticky='w')
        fam_var = tk.StringVar()
        fam = ttk.Combobox(body, textvariable=fam_var, values=families, width=22)
        fam.grid(row=1, column=1, sticky='we', pady=3); fam.bind('<<ComboboxSelected>>', lambda e: _refresh_inst())
        ttk.Label(body, text='乐器(如 小提琴):').grid(row=2, column=0, sticky='w')
        inst_var = tk.StringVar()
        inst = ttk.Combobox(body, textvariable=inst_var, width=22)
        inst.grid(row=2, column=1, sticky='we', pady=3)
        ttk.Label(body, text='预设文件名(.json):').grid(row=3, column=0, sticky='w')
        name_var = tk.StringVar()
        ttk.Entry(body, textvariable=name_var, width=22).grid(row=3, column=1, sticky='we', pady=3)
        ttk.Label(body, text='标签(可选,目录里备注):').grid(row=4, column=0, sticky='w')
        label_var = tk.StringVar()
        ttk.Entry(body, textvariable=label_var, width=22).grid(row=4, column=1, sticky='we', pady=3)
        state = {'ok': False, 'path': None}

        def _refresh_inst():
            f = fam_var.get().strip()
            if not f: inst.configure(values=[]); return
            d = os.path.join(src_dir, f)
            insts = [x for x in sorted(os.listdir(d)) if os.path.isdir(os.path.join(d, x))] if os.path.isdir(d) else []
            inst.configure(values=insts)

        # 预填当前载入预设的目录
        if self._cur_preset:
            rel = os.path.relpath(self._cur_preset, src_dir)
            parts = rel.split(os.sep)
            if len(parts) >= 2:
                fam_var.set(parts[0]); inst_var.set(parts[1])
                _refresh_inst()
            name_var.set(os.path.splitext(os.path.basename(self._cur_preset))[0])

        def _do_save():
            fam_name = fam_var.get().strip()
            inst_name = inst_var.get().strip()
            preset_name = name_var.get().strip()
            if not fam_name or not inst_name or not preset_name:
                messagebox.showwarning('缺少信息', '乐器族、乐器、文件名都不能为空'); return
            if not preset_name.lower().endswith('.json'): preset_name += '.json'
            outdir = os.path.join(src_dir, fam_name, inst_name)
            try:
                os.makedirs(outdir, exist_ok=True)
            except Exception as e:
                messagebox.showerror('错误', f'无法创建目录: {e}'); return
            out = os.path.join(outdir, preset_name)
            data = {
                'meta': {
                    'source': sid,
                    'family': fam_name,
                    'instrument': inst_name,
                    'label': label_var.get().strip(),
                },
                'params': self._slider_values(),
            }
            try:
                with open(out, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                messagebox.showerror('错误', f'保存失败: {e}'); return
            state['ok'] = True; state['path'] = out
            win.destroy()
            self._rescan_preset_tree()
            self._load_preset_file(out, sid)
            messagebox.showinfo('完成', f'已保存预设:\n{out}')

        btns = ttk.Frame(body); btns.grid(row=5, column=0, columnspan=2, sticky='e', pady=(10, 0))
        ttk.Button(btns, text='保存', command=_do_save).pack(side='right', padx=4)
        ttk.Button(btns, text='取消', command=win.destroy).pack(side='right', padx=4)
        win.wait_window()

    def _delete_selected_preset(self):
        sel = self.tree.selection()
        if not sel: messagebox.showinfo('提示', '请先选择要删除的预设'); return
        iid = sel[0]
        path = next((p for p, v in self._tree_iid.items() if v == iid), None)
        if not path or not path.lower().endswith('.json'):
            messagebox.showinfo('提示', '请选择一个 .json 预设文件'); return
        if not messagebox.askyesno('确认删除', f'删除预设文件?\n{path}'):
            return
        try:
            os.remove(path)
            if os.path.abspath(path) == self._cur_preset:
                self._cur_preset = None; self.lbl_loaded.config(text='未载入预设', foreground='gray')
            self._rescan_preset_tree()
        except Exception as e:
            messagebox.showerror('错误', str(e))

    # ============ 通用 ============
    def _show(self, key):
        v = self.vars[key].get()
        _, lbl = self.widgets[key]
        lbl.config(text=('%.2f' % v) if isinstance(v, float) and v != int(v) else str(int(round(v))))

    def _pick(self):
        f = filedialog.askopenfilename(title='选择 ACE 工程', filetypes=[('ACE project', '*.acep'), ('All', '*.*')])
        if f: self.inp_var.set(f)

    def _pick_out(self):
        d = filedialog.askdirectory(title='输出目录')
        if d: self.out_var.set(d)

    def _reset(self):
        for key in self.vars: self.vars[key].set(A.DEFAULT[key]); self._show(key)

    def _generate(self):
        inp = self.inp_var.get().strip()
        if not inp or not os.path.exists(inp):
            messagebox.showerror('错误', '请先选择有效的 .acep 文件'); return
        outdir = self.out_var.get().strip() or str(APP / 'output')
        os.makedirs(outdir, exist_ok=True)
        base = os.path.splitext(os.path.basename(inp))[0]
        out = os.path.join(outdir, base + '_swam.mid')
        cfg = self._read_cfg()
        self.status.set('生成中…')
        def work():
            try:
                r = A.convert_file(inp, out, cfg)
                self.after(0, lambda: self.status.set('完成: %d 音符, %d 颤音音 -> %s' % (r['notes'], r['pb_notes'], out)))
                self.after(0, lambda: messagebox.showinfo('完成', '已生成: %s' % out))
            except Exception as e:
                traceback.print_exc()
                self.after(0, lambda: messagebox.showerror('错误', str(e)))
                self.after(0, lambda: self.status.set('失败'))
        threading.Thread(target=work, daemon=True).start()


def _base_params():
    """core 默认值的 GUI 键子集。"""
    vals = {}
    for key, label, vmin, vmax, step, typ in PARAMS:
        v = A.DEFAULT[key]
        vals[key] = int(round(v)) if typ == 'int' else v
    return vals


def seed_all_defaults():
    """为所有注册源里的每种乐器生成 默认.json 种子(不存在才建)。返回生成/已存在路径列表。"""
    made = []
    for sid, _name in SOURCES:
        spec = SOURCE_INSTRUMENTS.get(sid)
        if not spec: continue
        fam = spec['family']
        for inst, prog in spec['instruments']:
            out = source_dir(sid) / fam / inst / DEFAULT_PRESET
            if out.exists():
                made.append(str(out)); continue
            out.parent.mkdir(parents=True, exist_ok=True)
            vals = _base_params()
            vals['instrument'] = prog
            data = {'meta': {'source': sid, 'family': fam, 'instrument': inst,
                             'label': f'默认种子(GM {prog}), 待校准'},
                    'params': vals}
            with open(out, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            made.append(str(out))
    return made


if __name__ == '__main__':
    seed_all_defaults()
    app = App()
    app.mainloop()
