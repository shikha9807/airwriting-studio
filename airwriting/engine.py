"""Realtime hand tracking and stroke engine. Camera/MediaPipe are optional at runtime."""
from __future__ import annotations
import math, time, os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from pathlib import Path

class Gesture(str, Enum):
    NONE = "NO HAND"
    WRITE = "WRITING"
    HOVER = "HOVER"
    ERASE = "ERASING"

class OneEuro:
    """Vector One-Euro filter: adaptive cutoff suppresses slow jitter with little fast-motion lag."""
    def __init__(self, min_cutoff=1.2, beta=0.035, derivative_cutoff=1.0):
        self.min_cutoff=min_cutoff; self.beta=beta; self.derivative_cutoff=derivative_cutoff
        self.x=None; self.dx=None; self.t=None
    @staticmethod
    def alpha(cutoff, dt):
        tau=1/(2*math.pi*cutoff); return 1/(1+tau/max(dt,1e-4))
    def reset(self): self.x=self.dx=self.t=None
    def __call__(self, value, now=None):
        now=now or time.monotonic(); value=(float(value[0]),float(value[1]))
        if self.x is None: self.x=value; self.dx=(0.,0.); self.t=now; return value
        dt=max(1e-4,now-self.t); raw=((value[0]-self.x[0])/dt,(value[1]-self.x[1])/dt)
        a=self.alpha(self.derivative_cutoff,dt)
        self.dx=tuple(a*v+(1-a)*d for v,d in zip(raw,self.dx))
        cutoff=self.min_cutoff+self.beta*math.hypot(*self.dx); a=self.alpha(cutoff,dt)
        self.x=tuple(a*v+(1-a)*x for v,x in zip(value,self.x)); self.t=now; return self.x

class Debouncer:
    def __init__(self, frames=3): self.frames=frames; self.current=Gesture.NONE; self.candidate=None; self.count=0
    def update(self, g):
        if g==self.current: self.candidate=None; self.count=0; return self.current
        if g!=self.candidate: self.candidate=g; self.count=1
        else: self.count+=1
        if self.count>=self.frames: self.current=g; self.candidate=None; self.count=0
        return self.current

@dataclass
class Stroke:
    points:list[tuple[int,int]] = field(default_factory=list)
    color:str="#1565c0"
    thickness:int=6
    timestamp:float=field(default_factory=time.time)

class StrokeManager:
    MAX_JUMP_THRESHOLD=120
    def __init__(self): self.strokes=[]; self.redo_stack=[]; self.active=None; self.prev_point=None
    def break_stroke(self): self.active=None; self.prev_point=None
    def add(self, point, color="#1565c0", thickness=6):
        """Add a point; return True only when it connects to the prior point."""
        p=(int(point[0]),int(point[1])); connected=self.prev_point is not None
        if connected and math.dist(self.prev_point,p)>self.MAX_JUMP_THRESHOLD:
            self.break_stroke(); connected=False
        if self.active is None:
            self.active=Stroke(color=color,thickness=thickness); self.strokes.append(self.active); self.redo_stack.clear()
        self.active.points.append(p); self.prev_point=p
        return connected
    def undo(self):
        self.break_stroke()
        if self.strokes: self.redo_stack.append(self.strokes.pop())
    def redo(self):
        self.break_stroke()
        if self.redo_stack: self.strokes.append(self.redo_stack.pop())
    def clear(self): self.break_stroke(); self.strokes.clear(); self.redo_stack.clear()
    def serialize(self): return [dict(points=s.points,color=s.color,thickness=s.thickness,timestamp=s.timestamp) for s in self.strokes]

class GestureClassifier:
    """Orientation resilient extension: normalized wrist→tip distance + joint-vector straightness."""
    @staticmethod
    def extended(lm, tip, pip, mcp):
        wrist=lm[0]; scale=max(1e-5,math.dist((wrist.x,wrist.y),(lm[mcp].x,lm[mcp].y)))
        reach=math.dist((wrist.x,wrist.y),(lm[tip].x,lm[tip].y))/scale
        a=(lm[pip].x-lm[mcp].x,lm[pip].y-lm[mcp].y); b=(lm[tip].x-lm[pip].x,lm[tip].y-lm[pip].y)
        denom=max(1e-6,math.hypot(*a)*math.hypot(*b)); straight=(a[0]*b[0]+a[1]*b[1])/denom
        return reach>1.55 and straight>0.05
    def classify(self,lm):
        idx=self.extended(lm,8,6,5); mid=self.extended(lm,12,10,9)
        ring=self.extended(lm,16,14,13); pinky=self.extended(lm,20,18,17)
        pinch=math.dist((lm[4].x,lm[4].y),(lm[8].x,lm[8].y))<0.055
        if pinch:return Gesture.ERASE
        if idx and mid:return Gesture.HOVER
        if idx and not(mid or ring or pinky):return Gesture.WRITE
        return Gesture.HOVER

def run_opencv_camera(camera_index=0, canvas_size=(1280,800), brightness_normalize=True, reconnect_delay=1.5, max_reconnect_attempts=0, model_path=None):
    """Run local camera HUD; reconnect indefinitely by default and always release native resources."""
    try:
        import cv2
        import mediapipe as mp
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("Install opencv-python, mediapipe, and numpy to use the desktop camera runner") from exc
    cap=None; tracker=None; windows=False; attempts=0; frame_timestamp=0
    manager=StrokeManager(); filt=OneEuro(); debounce=Debouncer(3); classifier=GestureClassifier(); gesture=Gesture.NONE
    w,h=canvas_size; layer=np.full((h,w,3),255,dtype=np.uint8)
    try:
        asset=Path(model_path or os.getenv("AIRWRITING_HAND_MODEL",Path(__file__).resolve().parent.parent/"models"/"hand_landmarker.task")).expanduser().resolve()
        if not asset.is_file():
            raise RuntimeError(f"MediaPipe model not found: {asset}. Set AIRWRITING_HAND_MODEL to a hand_landmarker.task file.")
        vision=mp.tasks.vision
        options=vision.HandLandmarkerOptions(base_options=mp.tasks.BaseOptions(model_asset_path=str(asset)),running_mode=vision.RunningMode.VIDEO,num_hands=1,min_hand_detection_confidence=.65,min_hand_presence_confidence=.65,min_tracking_confidence=.65)
        tracker=vision.HandLandmarker.create_from_options(options)
        cap=cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            cap.release(); cap=None
            raise RuntimeError(f"Could not open camera {camera_index}")
        cap.set(cv2.CAP_PROP_BUFFERSIZE,1)
        while True:
            ok,frame=cap.read()
            if not ok or frame is None:
                manager.break_stroke(); filt.reset(); attempts+=1
                if cap is not None: cap.release(); cap=None
                if max_reconnect_attempts and attempts>max_reconnect_attempts:
                    raise RuntimeError(f"Camera read failed after {max_reconnect_attempts} reconnect attempts")
                cv2.waitKey(1)
                time.sleep(max(0.1,reconnect_delay))
                cap=cv2.VideoCapture(camera_index)
                if cap.isOpened(): cap.set(cv2.CAP_PROP_BUFFERSIZE,1); attempts=0
                else: cap.release(); cap=None
                continue
            attempts=0; frame=cv2.flip(frame,1); fh,fw=frame.shape[:2]
            if brightness_normalize:
                gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
                if float(gray.std())<35 or float(gray.mean())<65: frame=cv2.convertScaleAbs(frame,alpha=1.18,beta=14)
            frame_timestamp=max(frame_timestamp+1,int(time.monotonic()*1000))
            rgb=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
            image=mp.Image(image_format=mp.ImageFormat.SRGB,data=rgb)
            out=tracker.detect_for_video(image,frame_timestamp); lm=out.hand_landmarks[0] if out.hand_landmarks else None
            if lm:
                gesture=debounce.update(classifier.classify(lm))
                sm=filt((lm[8].x*w,lm[8].y*h)); px=(int(sm[0]),int(sm[1]))
                cv2.circle(frame,(int(lm[8].x*fw),int(lm[8].y*fh)),8,(80,230,150),-1)
                if gesture==Gesture.WRITE:
                    old=manager.prev_point; connected=manager.add(px)
                    if connected and old is not None:
                        cv2.line(layer,old,manager.prev_point,(192,101,21),6,cv2.LINE_AA)
                else: manager.break_stroke()
            else:
                # Tracking loss must sever a stroke immediately, without waiting for debounce.
                gesture=Gesture.NONE; debounce.update(Gesture.NONE); manager.break_stroke(); filt.reset()
            cv2.putText(frame,gesture.value,(18,32),cv2.FONT_HERSHEY_SIMPLEX,.8,(0,190,80),2)
            cv2.imshow("Air Writing — camera",frame); cv2.imshow("Air Writing — canvas",layer); windows=True
            key=cv2.waitKey(1)&0xff
            if key in (27,ord('q')): break
            if key==ord('c'): layer[:]=255; manager.clear()
            if key==ord('u'):
                manager.undo(); layer[:]=255
                for stroke in manager.strokes:
                    for a,b in zip(stroke.points,stroke.points[1:]): cv2.line(layer,a,b,(192,101,21),stroke.thickness,cv2.LINE_AA)
    finally:
        manager.break_stroke()
        if tracker is not None: tracker.close()
        if cap is not None: cap.release()
        if windows: cv2.destroyAllWindows()
