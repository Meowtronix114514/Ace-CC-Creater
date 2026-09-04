#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ace-CC-Creater-SwamStrings - Desktop GUI
选择 .acep -> 调整参数 -> 生成 SWAM 小提琴 MIDI

运行: python gui/main.py   (或 gui/main.pyw 双击)
"""
import os, sys, pathlib, threading, traceback, tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP=pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
from core import ace2swam as A

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
    ('min_sustain','最短颤音音符(秒)', 0.2, 2.0, 0.05, 'float'),
    ('bowpos_val', '弓位/把位 CC 值', 0, 127, 1, 'int'),
    ('instrument', 'MIDI 音色(40=小提琴)', 0, 127, 1, 'int'),
]

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Ace-CC-Creater-SwamStrings')
        self.geometry('560x760')
        self.cfg=dict(A.DEFAULT)
        self.vars={}
        self._build()

    def _build(self):
        pad={'padx':10,'pady':4}
        # 文件选择
        fr=ttk.LabelFrame(self,text='工程文件 (.acep)',padding=8)
        fr.pack(fill='x',**pad)
        row=ttk.Frame(fr); row.pack(fill='x')
        self.inp_var=tk.StringVar()
        e=ttk.Entry(row,textvariable=self.inp_var,width=50); e.pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='浏览…',command=self._pick).pack(side='left',padx=4)
        # 输出
        row2=ttk.Frame(fr); row2.pack(fill='x',pady=(6,0))
        self.out_var=tk.StringVar(value=str(APP/'output'))
        ttk.Label(row2,text='输出目录:').pack(side='left')
        ttk.Entry(row2,textvariable=self.out_var,width=30).pack(side='left',padx=4,fill='x',expand=True)
        ttk.Button(row2,text='浏览…',command=self._pick_out).pack(side='left',padx=4)

        # 参数区
        pf=ttk.LabelFrame(self,text='参数 (当前默认 = 试听调优值)',padding=8)
        pf.pack(fill='x',**pad)
        self.widgets={}
        for key,label,vmin,vmax,step,typ in PARAMS:
            r=ttk.Frame(pf); r.pack(fill='x',pady=2)
            self.vars[key]=tk.DoubleVar(value=A.DEFAULT[key])
            ttk.Label(r,text=label,width=26,anchor='w').pack(side='left')
            s=ttk.Scale(r,from_=vmin,to=vmax,orient='horizontal',
                      variable=self.vars[key],command=lambda k=key: self._show(k))
            s.pack(side='left',fill='x',expand=True,padx=6)
            lbl=ttk.Label(r,text=str(round(A.DEFAULT[key],2)),width=7,anchor='e')
            lbl.pack(side='left')
            self.widgets[key]=(s,lbl)
        ttk.Button(pf,text='重置为默认',command=self._reset).pack(anchor='e',pady=(6,0))

        # 动作
        act=ttk.Frame(self); act.pack(fill='x',**pad)
        ttk.Button(act,text='生成 MIDI',command=self._generate).pack(side='left')
        self.status=tk.StringVar(value='就绪')
        ttk.Label(act,textvariable=self.status).pack(side='left',padx=12)

    def _show(self,key):
        v=self.vars[key].get()
        _,lbl=self.widgets[key]
        lbl.config(text=('%.2f'%v) if isinstance(v,float) and v!=int(v) else str(int(round(v))))

    def _pick(self):
        f=filedialog.askopenfilename(title='选择 ACE 工程',filetypes=[('ACE project','*.acep'),('All','*.*')])
        if f: self.inp_var.set(f)
    def _pick_out(self):
        d=filedialog.askdirectory(title='输出目录')
        if d: self.out_var.set(d)
    def _reset(self):
        for key in self.vars: self.vars[key].set(A.DEFAULT[key]); self._show(key)

    def _read_cfg(self):
        cfg=dict(A.DEFAULT)
        for key,label,vmin,vmax,step,typ in PARAMS:
            v=self.vars[key].get()
            cfg[key]= int(round(v)) if typ=='int' else v
        # sanity: lo<=hi
        if cfg['dyn_lo']>cfg['dyn_hi']: cfg['dyn_lo'],cfg['dyn_hi']=cfg['dyn_hi'],cfg['dyn_lo']
        if cfg['bow_lo']>cfg['bow_hi']: cfg['bow_lo'],cfg['bow_hi']=cfg['bow_hi'],cfg['bow_lo']
        return cfg

    def _generate(self):
        inp=self.inp_var.get().strip()
        if not inp or not os.path.exists(inp):
            messagebox.showerror('错误','请先选择有效的 .acep 文件'); return
        outdir=self.out_var.get().strip() or str(APP/'output')
        os.makedirs(outdir,exist_ok=True)
        base=os.path.splitext(os.path.basename(inp))[0]
        out=os.path.join(outdir, base+'_swam.mid')
        cfg=self._read_cfg()
        self.status.set('生成中…')
        def work():
            try:
                r=A.convert_file(inp,out,cfg)
                self.after(0,lambda: self.status.set('完成: %d 音符, %d 颤音音 -> %s'%(r['notes'],r['pb_notes'],out)))
                self.after(0,lambda: messagebox.showinfo('完成','已生成: %s'%out))
            except Exception as e:
                traceback.print_exc()
                self.after(0,lambda: messagebox.showerror('错误',str(e)))
                self.after(0,lambda: self.status.set('失败'))
        threading.Thread(target=work,daemon=True).start()

if __name__=='__main__':
    App().mainloop()