#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/ace2swam.py - Convert ACE .acep (ACEP2) into SWAM-violin MIDI (SMF).
Default params tuned by ear (DEFAULT).
"""
import sys, struct, math
import zstandard, mido

DEFAULT = {
    'amp':30.0, 'attack':0.20, 'release':0.15, 'pbrange':2.0,
    'dyn_lo':0, 'dyn_hi':127, 'sec_lo':45, 'sec_hi':88,
    'min_sustain':0.5, 'vib_min_hz':4.0, 'vib_max_hz':8.0,
    'rms_thr':0.15, 'clamp':6.0, 'instrument':40, 'ppq':480,
    'bowpos_cc':4, 'bowpos_val':64,
    'cc_dyn':11, 'cc_sec':2, 'vibrato':True,
}

class CBOR:
    def __init__(self,b): self.b=b; self.i=0
    def _ai(self,ai):
        if ai<24: return ai
        if ai==24: v=self.b[self.i]; self.i+=1; return v
        if ai==25: v=struct.unpack('>H',self.b[self.i:self.i+2])[0]; self.i+=2; return v
        if ai==26: v=struct.unpack('>I',self.b[self.i:self.i+4])[0]; self.i+=4; return v
        if ai==27: v=struct.unpack('>Q',self.b[self.i:self.i+8])[0]; self.i+=8; return v
        raise ValueError('ai')
    def decode(self):
        ib=self.b[self.i]; self.i+=1; mt=ib>>5; ai=ib&0x1f
        if mt==0: return self._ai(ai)
        if mt==1: return -1-self._ai(ai)
        if mt==2: n=self._ai(ai); v=self.b[self.i:self.i+n]; self.i+=n; return v
        if mt==3: n=self._ai(ai); v=self.b[self.i:self.i+n].decode('utf-8','replace'); self.i+=n; return v
        if mt==4: return [self.decode() for _ in range(self._ai(ai))]
        if mt==5:
            n=self._ai(ai); o={}
            for _ in range(n): k=self.decode(); o[k]=self.decode()
            return o
        if mt==6: return self.decode()
        if mt==7:
            if ai==20: return False
            if ai==21: return True
            if ai in (22,23): return None
            if ai==25: v=struct.unpack('>e',self.b[self.i:self.i+2])[0]; self.i+=2; return v
            if ai==26: v=struct.unpack('>f',self.b[self.i:self.i+4])[0]; self.i+=4; return v
            if ai==27: v=struct.unpack('>d',self.b[self.i:self.i+8])[0]; self.i+=8; return v
            raise ValueError('simple')
        raise ValueError('mt')

def decode_acep(path):
    b=open(path,'rb').read()
    assert b[:5]==b'ACEP2', 'not ACEP2 (only v2 supported)'
    off=struct.unpack('<Q',b[8:16])[0]; clen=struct.unpack('<Q',b[16:24])[0]; ulen=struct.unpack('<Q',b[24:32])[0]
    raw=zstandard.ZstdDecompressor().decompress(b[off:off+clen], max_output_size=ulen or (1<<30))
    if not isinstance(raw,bytes): raw=bytes(raw)
    return CBOR(raw).decode()

def tickmap(curves):
    m={}; mx=0
    for c in (curves or []):
        for i,v in enumerate(c.get('values') or []):
            if v is None: continue
            if isinstance(v,float) and math.isnan(v): continue
            t=c['offset']+i; m[t]=v; mx=max(mx,t)
    return m,mx

def _smooth(v,w):
    out=[]
    for i in range(len(v)):
        a=0.0;c=0
        for j in range(i-w,i+w+1):
            if 0<=j<len(v): a+=v[j]; c+=1
        out.append(a/c if c else v[i])
    return out
def _detect_vibrato_curve(vals, tps, cfg):
    amp=cfg.get('amp',DEFAULT['amp'])
    clamp=cfg.get('clamp',DEFAULT['clamp'])
    min_hz=cfg.get('vib_min_hz',DEFAULT['vib_min_hz'])
    max_hz=cfg.get('vib_max_hz',DEFAULT['vib_max_hz'])
    rms_thr=cfg.get('rms_thr',DEFAULT['rms_thr'])
    if len(vals)<250: return None
    vals=[max(-clamp,min(clamp,v)) for v in vals]
    slowwin=max(60, len(vals)//6)
    slow=_smooth(vals,slowwin)
    r1=[vals[i]-slow[i] for i in range(len(vals))]
    n=len(r1)
    tix=list(range(n)); tx=sum(tix); ty=sum(r1)
    txx=sum(i*i for i in tix); txy=sum(i*r1[i] for i in tix)
    den=n*txx-tx*tx
    slope=(n*txy-tx*ty)/den if den else 0
    intercept=(ty-slope*tx)/n
    centered=[r1[i]-(intercept+slope*i) for i in range(n)]
    cm=sum(centered)/n
    centered=[x-cm for x in centered]
    a0=int(n*0.15); a1=int(n*0.85)
    if a1<=a0+30: return None
    mid=centered[a0:a1]
    zc=0; last=1 if mid[0]>=0 else -1
    for i in range(1,len(mid)):
        sg=1 if mid[i]>=0 else -1
        if sg!=last: zc+=1
        last=sg
    dur=len(mid)/tps; f=(zc/2/dur) if dur>0 else 0
    rms=math.sqrt(sum(x*x for x in mid)/len(mid)) if mid else 0
    if not (min_hz<=f<=max_hz): return None
    if rms<rms_thr: return None
    bm=sum(centered[a0:a1])/(a1-a0)
    centered=[c-bm for c in centered]
    return centered

def _pb_lsb(cent, lsb): return int(max(-8192,min(8191,round(cent*lsb))))

def convert(prj, cfg=None):
    cfg=dict(DEFAULT if cfg is None else {**DEFAULT,**cfg})
    # ---- 音源 CC 方案 (可由 GUI 覆盖) ----
    # cc_dyn:  主动态 CC(接 mambaEnergy)  默认 SWAM 弦乐 = 11
    # cc_sec:  次级 CC(接 mambaTension)   默认 SWAM 弦乐 = 2 (弓压)
    # bowpos_cc/value: 固定弓位 CC(可为 None 关闭)
    # vibrato: 是否做 pitchDelta -> pitch bend 颤音
    cc_dyn=int(cfg.get('cc_dyn',11)); cc_sec=cfg.get('cc_sec',2)
    bowpos_cc=cfg.get('bowpos_cc',4); bowpos_val=int(cfg.get('bowpos_val',64))
    vibrato=bool(cfg.get('vibrato', True))
    pats=[p for t in prj['tracks'] if t.get('type')=='sing' for p in t.get('patterns',[]) if p.get('notes')]
    if not pats: raise ValueError('no vocal pattern with notes')
    pat=max(pats,key=lambda p:len(p['notes']))
    notes=sorted(pat['notes'],key=lambda n:n['pos'])
    par=pat.get('parameters') or {}
    e_m,_=tickmap(par.get('mambaEnergy')); t_m,_=tickmap(par.get('mambaTension')); p_m,_=tickmap(par.get('pitchDelta'))
    bpm=prj['tempos'][0]['bpm']; ppq=cfg.get('ppq',480); tps=bpm*ppq/60
    e_vals=[v for v in e_m.values() if v>0.02]; t_vals=list(t_m.values())
    emin,emax=(min(e_vals),max(e_vals)) if e_vals else (0,1); tmin,tmax=(min(t_vals),max(t_vals)) if t_vals else (0,1)
    if emax-emin<1e-6: emax=emin+1
    if tmax-tmin<1e-6: tmax=tmin+1
    lsb=8192.0/(cfg['pbrange']*100)
    amp=cfg['amp']; attack=cfg['attack']; release=cfg['release']
    msgs=[]; base=notes[0]['pos']; t_end=max(n['pos']+n['dur'] for n in notes)
    if bowpos_cc is not None:
        msgs.append((0, mido.Message('control_change', control=int(bowpos_cc), value=bowpos_val)))
    e_prev=t_prev=None
    for ta in range(base,t_end+1,10):
        tk=ta-base
        if ta in e_m:
            v=e_m[ta]; norm=max(0,min(1,(v-emin)/(emax-emin)))
            cv=int(round(cfg['dyn_lo']+norm*(cfg['dyn_hi']-cfg['dyn_lo'])))
            if cv!=e_prev: msgs.append((tk,mido.Message('control_change',control=cc_dyn,value=cv))); e_prev=cv
        if ta in t_m:
            v=t_m[ta]; norm=max(0,min(1,(v-tmin)/(tmax-tmin)))
            cv=int(round(cfg['sec_lo']+norm*(cfg['sec_hi']-cfg['sec_lo'])))
            if cv!=t_prev: msgs.append((tk,mido.Message('control_change',control=cc_sec,value=cv))); t_prev=cv
    for n in notes:
        pos=n['pos']; end=n['pos']+n['dur']; pitch=n['pitch']
        acc=[e_m[t] for t in range(pos,end) if t in e_m]
        avg_e=sum(acc)/len(acc) if acc else 0
        vel=int(40+70*max(0,min(1,(avg_e-emin)/(emax-emin))))
        p0=pos-base; p1=end-base
        msgs.append((p0,mido.Message('note_on',note=pitch,velocity=max(1,vel))))
        msgs.append((p1,mido.Message('note_off',note=pitch,velocity=0)))
    pb_notes=0
    if vibrato:
        for n in notes:
            pos=n['pos']; end=n['pos']+n['dur']
            if (end-pos)/tps < cfg['min_sustain']: continue
            abs_ticks=[t for t in range(pos,end) if t in p_m]
            vals=[p_m[t] for t in abs_ticks]
            centered=_detect_vibrato_curve(vals,tps,cfg)
            if centered is None: continue
            nv=len(centered)
            mid=centered[int(nv*0.2):int(nv*0.8)] if nv>50 else centered
            rms=math.sqrt(sum(x*x for x in mid)/len(mid)) if mid else 1
            gain=(amp/2.0)/rms if rms>0 else 0
            p0=pos-base; p1=end-base
            msgs.append((p0, mido.Message('pitchwheel',pitch=0)))
            step=max(1,nv//700)
            atk=int(nv*attack); rel=int(nv*release)
            for i in range(0,nv,step):
                env=1.0
                if i<atk: env=float(i)/atk if atk>0 else 1.0
                elif i>nv-rel: env=max(0.0,float(nv-i)/rel) if rel>0 else 0.0
                cent=max(-amp,min(amp,centered[i]*gain*env))
                ti=abs_ticks[i] if i<len(abs_ticks) else pos
                msgs.append((ti-base, mido.Message('pitchwheel',pitch=_pb_lsb(cent,lsb))))
            msgs.append((p1-2 if p1-2>p0 else p0, mido.Message('pitchwheel',pitch=0)))
            pb_notes+=1
    msgs.sort(key=lambda x:x[0])
    mf=mido.MidiFile(type=1,ticks_per_beat=ppq)
    tr0=mido.MidiTrack(); mf.tracks.append(tr0)
    tr0.append(mido.MetaMessage('set_tempo',tempo=round(60_000_000/bpm),time=0))
    tr0.append(mido.MetaMessage('time_signature',numerator=4,denominator=4,time=0))
    tr0.append(mido.MetaMessage('end_of_track',time=0))
    tr1=mido.MidiTrack(); mf.tracks.append(tr1)
    tr1.append(mido.Message('program_change',program=cfg['instrument'],time=0))
    last=0
    for tk,msg in msgs:
        msg.time=max(0,tk-last); last=tk; tr1.append(msg)
    tr1.append(mido.MetaMessage('end_of_track',time=0))
    return mf, len(notes), pb_notes

def convert_file(inp, out, cfg=None):
    prj=decode_acep(inp)
    mf,notes,pb=convert(prj,cfg)
    mf.save(out)
    return dict(midi=out, notes=notes, pb_notes=pb)

def main():
    import argparse
    ap=argparse.ArgumentParser(description='ACE .acep -> SWAM violin MIDI')
    ap.add_argument('inp'); ap.add_argument('out')
    for k,d in DEFAULT.items():
        ap.add_argument('--'+k.replace('_','-'), type=float if isinstance(d,float) else int, default=None)
    a=ap.parse_args()
    cfg={k: (getattr(a,k.replace('-','_')) if getattr(a,k.replace('-','_')) is not None else v) for k,v in DEFAULT.items()}
    r=convert_file(a.inp,a.out,cfg)
    print(r)

if __name__=='__main__': main()