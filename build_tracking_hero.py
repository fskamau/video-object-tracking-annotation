#!/usr/bin/env python3
"""
Create four computer-vision portfolio panels and a 2x2 hero image from one video.

Outputs:
  01_detection.jpg
  02_tracking.jpg
  03_trajectories.jpg
  04_segmentation.jpg
  video-tracking-hero.png
"""
import argparse
from collections import defaultdict
from pathlib import Path
import cv2
import numpy as np
from ultralytics import YOLO

TRACK_COLORS=[(57,211,181),(90,176,255),(244,200,91),(204,131,255),(255,125,125),(88,214,130)]
history=defaultdict(list)

def label_box(im, xyxy, text, color):
    x1,y1,x2,y2=map(int,xyxy)
    cv2.rectangle(im,(x1,y1),(x2,y2),color,3)
    (w,h),_=cv2.getTextSize(text,cv2.FONT_HERSHEY_SIMPLEX,.55,2)
    y=max(y1,h+10)
    cv2.rectangle(im,(x1,y-h-10),(x1+w+10,y),color,-1)
    cv2.putText(im,text,(x1+5,y-6),cv2.FONT_HERSHEY_SIMPLEX,.55,(15,18,20),2,cv2.LINE_AA)

def header(im,title,subtitle):
    overlay=im.copy()
    cv2.rectangle(overlay,(0,0),(im.shape[1],72),(14,18,22),-1)
    cv2.addWeighted(overlay,.92,im,.08,0,im)
    cv2.putText(im,title,(22,30),cv2.FONT_HERSHEY_SIMPLEX,.72,(245,247,249),2,cv2.LINE_AA)
    cv2.putText(im,subtitle,(22,55),cv2.FONT_HERSHEY_SIMPLEX,.43,(170,180,188),1,cv2.LINE_AA)

def fit_panel(im,w=800,h=350):
    ih,iw=im.shape[:2]; scale=max(w/iw,h/ih)
    r=cv2.resize(im,(int(iw*scale),int(ih*scale)))
    y=(r.shape[0]-h)//2; x=(r.shape[1]-w)//2
    return r[y:y+h,x:x+w].copy()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out",default="hero_output")
    ap.add_argument("--frame",type=int,default=-1,help="Frame to showcase; -1 selects ~55%%")
    ap.add_argument("--conf",type=float,default=.35)
    args=ap.parse_args()
    out=Path(args.out); out.mkdir(parents=True,exist_ok=True)

    cap=cv2.VideoCapture(args.video)
    total=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    target=args.frame if args.frame>=0 else max(1,int(total*.55))

    detect=YOLO("yolo11n.pt")
    segment=YOLO("yolo11n-seg.pt")

    chosen=None; tracked=None
    for idx in range(target+1):
        ok,frame=cap.read()
        if not ok: break
        res=detect.track(frame,persist=True,tracker="bytetrack.yaml",conf=args.conf,verbose=False)[0]
        if idx==target:
            chosen=frame.copy(); tracked=res
            break
    cap.release()
    if chosen is None: raise RuntimeError("Could not read target frame.")

    # 1 detection
    d=chosen.copy()
    pred=detect.predict(chosen,conf=args.conf,verbose=False)[0]
    if pred.boxes is not None:
        for b in pred.boxes:
            cls=int(b.cls.item()); conf=float(b.conf.item())
            label_box(d,b.xyxy[0].cpu().numpy(),f"{detect.names[cls]} {conf:.2f}",(57,211,181))
    header(d,"OBJECT DETECTION","Bounding boxes · class labels · confidence")
    d=fit_panel(d); cv2.imwrite(str(out/"01_detection.jpg"),d)

    # 2 persistent IDs
    t=chosen.copy()
    if tracked.boxes is not None:
        ids=tracked.boxes.id.int().cpu().tolist() if tracked.boxes.id is not None else [-1]*len(tracked.boxes)
        for i,b in enumerate(tracked.boxes):
            cls=int(b.cls.item()); tid=ids[i]; color=TRACK_COLORS[tid%len(TRACK_COLORS)]
            label_box(t,b.xyxy[0].cpu().numpy(),f"{detect.names[cls]}  track #{tid}",color)
    header(t,"MULTI-OBJECT TRACKING","Persistent IDs · ByteTrack · frame-to-frame association")
    t=fit_panel(t); cv2.imwrite(str(out/"02_tracking.jpg"),t)

    # 3 trajectories: replay to target so histories are meaningful
    cap=cv2.VideoCapture(args.video); history.clear(); traj=chosen.copy()
    detect2=YOLO("yolo11n.pt")
    for idx in range(target+1):
        ok,frame=cap.read()
        if not ok: break
        r=detect2.track(frame,persist=True,tracker="bytetrack.yaml",conf=args.conf,verbose=False)[0]
        if r.boxes is not None and r.boxes.id is not None:
            boxes=r.boxes.xywh.cpu().numpy(); ids=r.boxes.id.int().cpu().tolist()
            for box,tid in zip(boxes,ids):
                history[tid].append((int(box[0]),int(box[1])))
                history[tid]=history[tid][-35:]
        if idx==target:
            traj=frame.copy()
            if r.boxes is not None and r.boxes.id is not None:
                for b,tid in zip(r.boxes,r.boxes.id.int().cpu().tolist()):
                    cls=int(b.cls.item()); color=TRACK_COLORS[tid%len(TRACK_COLORS)]
                    label_box(traj,b.xyxy[0].cpu().numpy(),f"{detect2.names[cls]}  #{tid}",color)
            for tid,pts in history.items():
                if len(pts)>1:
                    cv2.polylines(traj,[np.array(pts,np.int32)],False,TRACK_COLORS[tid%len(TRACK_COLORS)],3)
            break
    cap.release()
    header(traj,"TRACK TRAJECTORIES","Track continuity · motion history · identity persistence")
    traj=fit_panel(traj); cv2.imwrite(str(out/"03_trajectories.jpg"),traj)

    # 4 segmentation
    s=chosen.copy()
    sr=segment.predict(chosen,conf=args.conf,verbose=False)[0]
    if sr.masks is not None:
        masks=sr.masks.data.cpu().numpy()
        boxes=sr.boxes
        for i,mask in enumerate(masks):
            color=TRACK_COLORS[i%len(TRACK_COLORS)]
            mask=cv2.resize(mask,(s.shape[1],s.shape[0]))>.5
            layer=np.zeros_like(s); layer[:]=color
            s[mask]=cv2.addWeighted(s,.55,layer,.45,0)[mask]
            b=boxes[i]; cls=int(b.cls.item())
            label_box(s,b.xyxy[0].cpu().numpy(),segment.names[cls],color)
    header(s,"INSTANCE SEGMENTATION","Object masks · class boundaries · pixel-level localization")
    s=fit_panel(s); cv2.imwrite(str(out/"04_segmentation.jpg"),s)

    gap=8; bg=(17,22,28)
    hero=np.full((350*2+gap,800*2+gap,3),bg,np.uint8)
    hero[0:350,0:800]=d; hero[0:350,808:1608]=t
    hero[358:708,0:800]=traj; hero[358:708,808:1608]=s
    cv2.imwrite(str(out/"video-tracking-hero.png"),hero)
    print(f"Created: {out/'video-tracking-hero.png'}")

if __name__=="__main__":
    main()
