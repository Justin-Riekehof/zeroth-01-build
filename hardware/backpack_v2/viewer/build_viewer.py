"""Build the standalone 3D assembly viewer (robot from the pinned GLB + backpack v2 STLs).

Usage: python build_viewer.py   -> writes viewer.html (~7.5 MB, gitignored) next to this file.
Needs trimesh + numpy (e.g. the same venv as backpack_v2.py plus `uv pip install trimesh numpy`).
Geometry is embedded as int16-quantised (0.02 mm) positions; robot frame (x,y,z) -> three.js (x, z, -y).
"""
import base64, json, os, glob, numpy as np, trimesh
HERE=os.path.dirname(os.path.abspath(__file__)); REPO=os.path.abspath(os.path.join(HERE,"..","..",".."))
STL=f"{REPO}/hardware/backpack_v2/stl"
GLB=f"{REPO}/resources/cad/z001-opus-m-93de7567.glb"
OUT=os.path.join(HERE,"viewer_data.js")
sc=trimesh.load(GLB,force='scene'); g=sc.graph
R=np.array([[1,0,0],[0,0,1],[0,-1,0]],float)   # robot (x,y,z) -> three (x, z, -y), det=+1
def to_three(m):
    m=m.copy(); m.vertices=m.vertices@R.T; return m
def color_of(m):
    try:
        c=np.array(m.visual.material.baseColorFactor[:3],float)
        if c.max()>1: c=c/255.0
        return tuple(np.round(c,2))
    except Exception:
        try:
            c=np.array(m.visual.main_color[:3],float)/255.0; return tuple(np.round(c,2))
        except Exception:
            return (0.7,0.7,0.7)
groups={}   # color -> list of meshes
orig=None; excluded=('Bus Servo Adaptor','Battery')
for n in g.nodes_geometry:
    T,gn=g[n]; m=sc.geometry[gn].copy(); m.apply_transform(T); m.apply_scale(1000.0)
    if n=='BackPack': orig=m; continue
    if n.startswith(excluded): continue
    groups.setdefault(color_of(m),[]).append(m)
print("color groups:", {k:sum(len(x.faces) for x in v) for k,v in groups.items()})
total=sum(len(x.faces) for v in groups.values() for x in v); budget=140000
SCALE=0.02
def encode(m, name, color, opacity=1.0):
    m.merge_vertices()
    v=np.asarray(m.vertices,np.float64); f=np.asarray(m.faces)
    q=np.clip(np.round(v/SCALE),-32767,32767).astype(np.int16)
    if len(v)<65535: idx=f.astype(np.uint16); it='u16'
    else: idx=f.astype(np.uint32); it='u32'
    return dict(name=name,color=[round(float(c),3) for c in color],opacity=opacity,nv=len(v),nf=len(f),idxType=it,scale=SCALE,
                pos=base64.b64encode(q.tobytes()).decode(),idx=base64.b64encode(idx.tobytes()).decode())
def greyify(col):
    L=0.30*col[0]+0.59*col[1]+0.11*col[2]
    g=0.42+0.50*L                      # keep relative lightness, compress range
    return (g*0.97, g*0.99, g*1.03)     # slight cool tint
out=[]
for i,(col,ms) in enumerate(sorted(groups.items(), key=lambda kv:-sum(len(x.faces) for x in kv[1]))):
    m=to_three(trimesh.util.concatenate(ms))
    out.append(encode(m,f"robot_{i}",greyify(col))); out[-1]['role']='robot'
print("robot faces total:", sum(d['nf'] for d in out))
o=to_three(orig); out.append(encode(o,'orig_backpack',(0.85,0.3,0.3),0.45)); out[-1]['role']='orig'
for k,col in (('base',(0.19,0.44,0.84)),('deck',(0.88,0.54,0.18)),('lid',(0.50,0.70,0.35))):
    m=trimesh.load(f"{STL}/backpack_v2_{k}_robotframe.stl"); m=to_three(m)
    out.append(encode(m,k,col)); out[-1]['role']='part'
    print(k, len(m.faces),'faces')
for grp,names in (('components_base',('lipo','waveshare','switch','fuse_holder')),('components_deck',('cutoff','pi','pi_usb_plugs','pololu','warner'))):
    ph=[to_three(trimesh.load(f"{STL}/placeholder_{n}.stl")) for n in names]
    out.append(encode(trimesh.util.concatenate(ph),grp,(0.80,0.20,0.20),0.4)); out[-1]['role']=grp
# robot bounds (three frame) for camera framing
allv=np.vstack([np.frombuffer(base64.b64decode(d['pos']),np.int16).reshape(-1,3).astype(float)*SCALE for d in out if d['role']=='robot'])
meta=dict(bounds=[allv.min(0).round(1).tolist(), allv.max(0).round(1).tolist()])
js="const DATA="+json.dumps(dict(meta=meta,groups=out))+";\n"
open(OUT,'w').write(js); print("written", OUT, f"{os.path.getsize(OUT)/1e6:.2f} MB", "bounds", meta)

tpl=open(os.path.join(HERE,"viewer_template.html")).read()
open(os.path.join(HERE,"viewer.html"),"w").write(tpl.replace("/*__DATA__*/", js))
os.remove(OUT); print("viewer.html written")
