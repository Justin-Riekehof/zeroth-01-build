"""Print scalar/tensor curves from an xax/ksim run: python tb_read.py <run_dir> [substrings...]  (use 'tags' to list)"""
import sys, os, numpy as np
from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
from tensorflow.python.framework import tensor_util
run = sys.argv[1]; want = [w for w in sys.argv[2:] if w != "tags"]; list_only = "tags" in sys.argv[2:] or not want
for split in ("train", "valid"):
    d = os.path.join(run, "tensorboard", split)
    if not os.path.isdir(d): continue
    acc = EventAccumulator(d, size_guidance={"scalars": 0, "tensors": 0}); acc.Reload()
    tg = acc.Tags(); scal, tens = tg.get("scalars", []), tg.get("tensors", [])
    if list_only: print(f"[{split}] scalars: {scal}\n[{split}] tensors: {tens}"); continue
    for t in scal + tens:
        if not any(w in t for w in want): continue
        if t in scal: ev = [(e.step, float(e.value)) for e in acc.Scalars(t)]
        else:
            ev = []
            for e in acc.Tensors(t):
                v = tensor_util.MakeNdarray(e.tensor_proto)
                if v.size == 1: ev.append((e.step, float(v)))
        if ev: print(f"[{split}] {t}: n={len(ev)} first={[(s, round(v,3)) for s,v in ev[:2]]} last={[(s, round(v,3)) for s,v in ev[-4:]]}")
