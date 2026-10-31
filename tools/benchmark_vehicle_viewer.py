"""Measure real-resource viewer redraws, including GPU readback and Tk copy.

Requires a display, WOT_0922_CLIENT and launcher build dependencies. This is a
renderer benchmark, not simulated game input or a gameplay acceptance test.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import tkinter as tk
from unittest import mock
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'launcher'))
import vehicle_armor_viewer as viewer
import vehicle_overlays


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frames',type=int,default=80)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--max-p95-ms',type=float,default=33.3)
    parser.add_argument('--compare-cpu',action='store_true')
    args=parser.parse_args()
    game=os.environ['WOT_0922_CLIENT']
    root=tk.Tk();root.geometry('660x940')
    panel=viewer.ArmorViewerPanel(root,tk,lambda key:None,'en',game)
    panel.frame.pack(fill='both',expand=True)
    root.update()
    results=[]
    try:
        for vehicle in ('china/Ch06_Renault_NC31','usa/A11_T29','germany/G114_Skorpian'):
            member='scripts/item_defs/vehicles/'+vehicle+'.xml'
            records=vehicle_overlays.list_vehicle_field_choices(game,member)
            with mock.patch('tkinter.messagebox.showwarning'):
                panel.load_vehicle(member,records)
                root.update()
            if panel._gpu is None:raise RuntimeError('OpenGL 3.3 benchmark requires a working context')
            for mode in ('armor','internal'):
                with mock.patch('tkinter.messagebox.showwarning'):panel.set_view_mode(mode)
                root.update()
                uploaded=panel._gpu.uploads
                panel._frame_times=[]
                for _ in range(args.frames):
                    panel._yaw+=.025;panel._redraw();root.update_idletasks()
                if panel._gpu.uploads!=uploaded:raise AssertionError('Camera movement reuploaded geometry')
                times=panel._frame_times
                result=dict(vehicle=vehicle,mode=mode,frames=len(times),
                    p50_ms=float(np.percentile(times,50)),p95_ms=float(np.percentile(times,95)),
                    layers=len(panel._gpu_objects),size=panel._pick_size,device=panel._gpu.info)
                if args.compare_cpu:
                    gpu=panel._gpu
                    panel._gpu=None
                    elapsed=[]
                    try:
                        for _ in range(3):
                            start=time.perf_counter()
                            panel._redraw();root.update_idletasks()
                            elapsed.append((time.perf_counter()-start)*1000)
                    finally:panel._gpu=gpu
                    result['cpu_p50_ms']=float(np.percentile(elapsed,50))
                results.append(result)
                print(json.dumps(result),flush=True)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(results,indent=2),encoding='utf-8')
        if any(r['p95_ms']>args.max_p95_ms for r in results):
            raise AssertionError('A real-resource GPU redraw exceeded the p95 budget')
    finally:root.destroy()


if __name__=='__main__':main()
