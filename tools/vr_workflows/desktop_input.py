"""Small X11 input driver for an owned native desktop evaluation window."""
import ctypes as c
import ctypes.util
import subprocess
import time


class DesktopInput:
    def __init__(self):
        self.x=c.CDLL(ctypes.util.find_library('X11'));self.t=c.CDLL(ctypes.util.find_library('Xtst'))
        self.x.XOpenDisplay.argtypes=[c.c_char_p];self.x.XOpenDisplay.restype=c.c_void_p
        for name,args in {'XSync':[c.c_void_p,c.c_int], 'XCloseDisplay':[c.c_void_p],
                          'XMapRaised':[c.c_void_p,c.c_ulong], 'XSetInputFocus':[c.c_void_p,c.c_ulong,c.c_int,c.c_ulong],
                          'XMoveResizeWindow':[c.c_void_p,c.c_ulong,c.c_int,c.c_int,c.c_uint,c.c_uint]}.items():getattr(self.x,name).argtypes=args
        self.x.XStringToKeysym.argtypes=[c.c_char_p];self.x.XStringToKeysym.restype=c.c_ulong
        self.x.XKeysymToKeycode.argtypes=[c.c_void_p,c.c_ulong];self.x.XKeysymToKeycode.restype=c.c_uint
        self.t.XTestFakeMotionEvent.argtypes=[c.c_void_p,c.c_int,c.c_int,c.c_int,c.c_ulong]
        self.t.XTestFakeButtonEvent.argtypes=[c.c_void_p,c.c_uint,c.c_int,c.c_ulong]
        self.t.XTestFakeKeyEvent.argtypes=[c.c_void_p,c.c_uint,c.c_int,c.c_ulong]
        self.display=self.x.XOpenDisplay(None)
        if not self.display:raise RuntimeError('Cannot open desktop display')
    def window(self,pid):
        tree=subprocess.check_output(['xwininfo','-root','-tree'],text=True)
        for line in tree.splitlines():
            if 'NADOC Keyboard Gallery' not in line:continue
            window=line.strip().split()[0]
            prop=subprocess.check_output(['xprop','-id',window,'_NET_WM_PID'],text=True)
            if prop.strip().endswith('= '+str(pid)):return window
        raise LookupError('Owned keyboard window not ready')
    def reveal(self,window):
        w=int(window,16);self.x.XMapRaised(self.display,w)
        self.x.XMoveResizeWindow(self.display,w,20,30,1280,960)
        self.x.XSetInputFocus(self.display,w,1,0);self.x.XSync(self.display,0)
    def move(self,x,y):
        self.t.XTestFakeMotionEvent(self.display,-1,int(x),int(y),0);self.x.XSync(self.display,0)
    def click(self):
        self.t.XTestFakeButtonEvent(self.display,1,1,0);self.x.XSync(self.display,0);time.sleep(.08)
        self.t.XTestFakeButtonEvent(self.display,1,0,0);self.x.XSync(self.display,0)
    def key(self,key):
        code=self.x.XKeysymToKeycode(self.display,self.x.XStringToKeysym(key.encode()))
        self.t.XTestFakeKeyEvent(self.display,code,1,0);self.x.XSync(self.display,0);time.sleep(.08)
        self.t.XTestFakeKeyEvent(self.display,code,0,0);self.x.XSync(self.display,0)
    def close(self):self.x.XCloseDisplay(self.display)
