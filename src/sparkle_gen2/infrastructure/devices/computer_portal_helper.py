from __future__ import annotations
import hashlib,json,math,os,struct,sys,time,urllib.parse,uuid
import gi
gi.require_version('Gio','2.0');gi.require_version('GLib','2.0');gi.require_version('Gst','1.0')
from gi.repository import Gio,GLib,Gst

BUS='org.freedesktop.portal.Desktop';OBJ='/org/freedesktop/portal/desktop'
REQUEST_IFACE='org.freedesktop.portal.Request';SESSION_IFACE='org.freedesktop.portal.Session'
REMOTE='org.freedesktop.portal.RemoteDesktop';SCREENCAST='org.freedesktop.portal.ScreenCast';SCREENSHOT='org.freedesktop.portal.Screenshot'
MAX_INPUT=16384;MAX_IMAGE_BYTES=16*1024*1024;TIMEOUT_MS=60000
KEYSYMS={'Escape':0xff1b,'Tab':0xff09,'Left':0xff51,'Up':0xff52,'Right':0xff53,'Down':0xff54,'PageUp':0xff55,'PageDown':0xff56}
BTN_LEFT=0x110

def norm(v):
    if hasattr(v,'unpack'):return norm(v.unpack())
    if isinstance(v,dict):return {str(k):norm(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)):return [norm(x) for x in v]
    return v

def png_dimensions(data:bytes):
    if len(data)>=24 and data[:8]==b'\x89PNG\r\n\x1a\n' and data[12:16]==b'IHDR':return struct.unpack('>II',data[16:24])
    return (0,0)

class PortalError(RuntimeError):pass

class PortalRuntime:
    def __init__(self):
        Gst.init(None);self.conn=Gio.bus_get_sync(Gio.BusType.SESSION,None);self.sender=self.conn.get_unique_name().lstrip(':').replace('.','_');self.session=None;self.devices=0;self.streams=[];self.pipewire_fd=None;self.pressed=set();self.closed=False
    def _property(self,iface,name):
        ret=self.conn.call_sync(BUS,OBJ,'org.freedesktop.DBus.Properties','Get',GLib.Variant('(ss)',(iface,name)),GLib.VariantType.new('(v)'),Gio.DBusCallFlags.NONE,5000,None);return norm(ret)[0]
    def discover(self):
        return {'remote_desktop_version':int(self._property(REMOTE,'version')),'remote_device_types':int(self._property(REMOTE,'AvailableDeviceTypes')),'screencast_version':int(self._property(SCREENCAST,'version')),'screen_source_types':int(self._property(SCREENCAST,'AvailableSourceTypes')),'screenshot_version':int(self._property(SCREENSHOT,'version')),'session_active':self.session is not None and not self.closed,'selected_devices':self.devices,'stream_count':len(self.streams),'pressed_keys':sorted(self.pressed)}
    def _request(self,iface,method,signature,values,options_index):
        token='sp'+uuid.uuid4().hex[:20];path=f'/org/freedesktop/portal/desktop/request/{self.sender}/{token}';values=list(values);opts=dict(values[options_index] or {});opts['handle_token']=GLib.Variant('s',token);values[options_index]=opts;box={};loop=GLib.MainLoop()
        def cb(_c,_sender,_path,_iface,_sig,params,_data):
            code,res=norm(params);box['code']=int(code);box['results']=norm(res);loop.quit()
        sid=self.conn.signal_subscribe(BUS,REQUEST_IFACE,'Response',path,None,Gio.DBusSignalFlags.NONE,cb,None)
        try:
            ret=self.conn.call_sync(BUS,OBJ,iface,method,GLib.Variant(signature,tuple(values)),GLib.VariantType.new('(o)'),Gio.DBusCallFlags.NONE,10000,None)
            if norm(ret)[0]!=path:raise PortalError('portal_request_handle_mismatch')
            def timed():box['timeout']=True;loop.quit();return False
            timer=GLib.timeout_add(TIMEOUT_MS,timed);loop.run();GLib.source_remove(timer) if not box.get('timeout') else None
        finally:self.conn.signal_unsubscribe(sid)
        if box.get('timeout'):raise PortalError('portal_request_timeout')
        if box.get('code')!=0:raise PortalError('portal_request_denied' if box.get('code')==1 else 'portal_request_cancelled')
        return box.get('results',{})
    def screenshot(self):
        res=self._request(SCREENSHOT,'Screenshot','(sa{sv})',['',{'interactive':GLib.Variant('b',False)}],1);uri=res.get('uri')
        if not isinstance(uri,str):raise PortalError('screenshot_uri_missing')
        parsed=urllib.parse.urlparse(uri)
        if parsed.scheme!='file':raise PortalError('screenshot_uri_not_file')
        path=urllib.parse.unquote(parsed.path)
        try:
            with open(path,'rb') as f:data=f.read(MAX_IMAGE_BYTES+1)
            if len(data)>MAX_IMAGE_BYTES:raise PortalError('screenshot_too_large')
            width,height=png_dimensions(data)
            if width<=0 or height<=0:raise PortalError('screenshot_dimensions_invalid')
            return {'source':'screenshot-portal','sha256':hashlib.sha256(data).hexdigest(),'size_bytes':len(data),'width':width,'height':height,'captured_at_ns':time.time_ns()}
        finally:
            try:os.unlink(path)
            except OSError:pass
    def create_session(self):
        if self.session is not None and not self.closed:return self.status()
        session_token='ss'+uuid.uuid4().hex[:20]
        res=self._request(REMOTE,'CreateSession','(a{sv})',[{'session_handle_token':GLib.Variant('s',session_token)}],0);handle=res.get('session_handle')
        if not isinstance(handle,str):raise PortalError('session_handle_missing')
        self.session=handle;self.closed=False
        try:
            self._request(SCREENCAST,'SelectSources','(oa{sv})',[handle,{'types':GLib.Variant('u',1),'multiple':GLib.Variant('b',False),'cursor_mode':GLib.Variant('u',2)}],1)
            self._request(REMOTE,'SelectDevices','(oa{sv})',[handle,{'types':GLib.Variant('u',3)}],1)
            started=self._request(REMOTE,'Start','(osa{sv})',[handle,'',{}],2)
            self.devices=int(started.get('devices',0));raw=started.get('streams',[]);streams=[]
            for item in raw:
                if not isinstance(item,(list,tuple)) or len(item)!=2:continue
                node=int(item[0]);props=norm(item[1]) if isinstance(item[1],dict) else {}
                size=props.get('size');width=height=0
                if isinstance(size,(list,tuple)) and len(size)==2:width,height=int(size[0]),int(size[1])
                streams.append({'node_id':node,'width':width,'height':height,'source_type':int(props.get('source_type',0) or 0)})
            self.streams=streams
            if not (self.devices&1) or not (self.devices&2):raise PortalError('required_remote_devices_not_granted')
            if not self.streams:raise PortalError('screen_stream_not_granted')
            return self.status()
        except Exception:
            self.close();raise
    def _open_pipewire(self):
        if self.pipewire_fd is not None:return self.pipewire_fd
        if self.session is None or self.closed:raise PortalError('stale_session')
        ret,fdlist=self.conn.call_with_unix_fd_list_sync(BUS,OBJ,SCREENCAST,'OpenPipeWireRemote',GLib.Variant('(oa{sv})',(self.session,{})),GLib.VariantType.new('(h)'),Gio.DBusCallFlags.NONE,10000,None,None)
        idx=int(norm(ret)[0]);fd=fdlist.get(idx);self.pipewire_fd=fd;return fd
    def observe(self):
        if self.session is None or self.closed:raise PortalError('session_authorization_required')
        stream=self.streams[0];fd=self._open_pipewire();node=stream['node_id'];desc=f'pipewiresrc fd={fd} path={node} do-timestamp=true ! videoconvert ! video/x-raw,format=RGB ! appsink name=sink max-buffers=1 drop=true sync=false'
        pipeline=Gst.parse_launch(desc);sink=pipeline.get_by_name('sink');pipeline.set_state(Gst.State.PLAYING)
        try:
            sample=sink.emit('try-pull-sample',5*Gst.SECOND)
            if sample is None:raise PortalError('pipewire_frame_timeout')
            caps=sample.get_caps();st=caps.get_structure(0);width=int(st.get_value('width'));height=int(st.get_value('height'));buf=sample.get_buffer();ok,mapinfo=buf.map(Gst.MapFlags.READ)
            if not ok:raise PortalError('pipewire_frame_map_failed')
            try:
                raw=bytes(mapinfo.data)
                if len(raw)>64*1024*1024:raise PortalError('pipewire_frame_too_large')
                digest=hashlib.sha256(raw).hexdigest();size=len(raw)
            finally:buf.unmap(mapinfo)
            stream['width']=width;stream['height']=height
            return {'source':'screencast-pipewire','sha256':digest,'size_bytes':size,'width':width,'height':height,'stream_node':node,'captured_at_ns':time.time_ns()}
        finally:pipeline.set_state(Gst.State.NULL)
    def status(self):
        d=self.discover();d['session_handle_present']=self.session is not None and not self.closed;d['stream_dimensions']=[{'width':x['width'],'height':x['height']} for x in self.streams];return d
    def _active(self):
        if self.session is None or self.closed:raise PortalError('stale_session')
    def pointer_move(self,x,y):
        self._active();stream=self.streams[0];w,h=stream.get('width',0),stream.get('height',0)
        if w<=0 or h<=0:raise PortalError('verified_stream_dimensions_required')
        if not isinstance(x,(int,float)) or isinstance(x,bool) or not math.isfinite(float(x)) or not isinstance(y,(int,float)) or isinstance(y,bool) or not math.isfinite(float(y)):raise PortalError('pointer_coordinates_invalid')
        if x<0 or y<0 or x>=w or y>=h:raise PortalError('pointer_coordinates_out_of_bounds')
        self.conn.call_sync(BUS,OBJ,REMOTE,'NotifyPointerMotionAbsolute',GLib.Variant('(oa{sv}udd)',(self.session,{},int(stream['node_id']),float(x),float(y))),None,Gio.DBusCallFlags.NONE,5000,None);return {'action':'pointer_move','accepted':True,'x':float(x),'y':float(y)}
    def pointer_click(self):
        self._active()
        for state in (1,0):self.conn.call_sync(BUS,OBJ,REMOTE,'NotifyPointerButton',GLib.Variant('(oa{sv}iu)',(self.session,{},BTN_LEFT,state)),None,Gio.DBusCallFlags.NONE,5000,None)
        return {'action':'pointer_click','accepted':True,'button':'left'}
    def pointer_scroll(self,dx,dy):
        self._active()
        for v in (dx,dy):
            if not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(float(v)) or abs(float(v))>10:raise PortalError('scroll_delta_invalid')
        self.conn.call_sync(BUS,OBJ,REMOTE,'NotifyPointerAxis',GLib.Variant('(oa{sv}dd)',(self.session,{},float(dx),float(dy))),None,Gio.DBusCallFlags.NONE,5000,None);return {'action':'pointer_scroll','accepted':True,'dx':float(dx),'dy':float(dy)}
    def key(self,name,pressed):
        self._active()
        if name not in KEYSYMS:raise PortalError('key_not_allowlisted')
        if pressed and name in self.pressed:raise PortalError('key_already_pressed')
        if not pressed and name not in self.pressed:raise PortalError('key_not_pressed')
        self.conn.call_sync(BUS,OBJ,REMOTE,'NotifyKeyboardKeysym',GLib.Variant('(oa{sv}iu)',(self.session,{},int(KEYSYMS[name]),1 if pressed else 0)),None,Gio.DBusCallFlags.NONE,5000,None)
        if pressed:self.pressed.add(name)
        else:self.pressed.remove(name)
        return {'action':'key_press' if pressed else 'key_release','accepted':True,'key':name,'pressed_keys':sorted(self.pressed)}
    def close(self):
        if self.session is not None and not self.closed:
            for name in list(self.pressed):
                try:self.conn.call_sync(BUS,OBJ,REMOTE,'NotifyKeyboardKeysym',GLib.Variant('(oa{sv}iu)',(self.session,{},int(KEYSYMS[name]),0)),None,Gio.DBusCallFlags.NONE,2000,None)
                except Exception:pass
            self.pressed.clear()
            try:self.conn.call_sync(BUS,self.session,SESSION_IFACE,'Close',None,None,Gio.DBusCallFlags.NONE,5000,None)
            except Exception:pass
        self.closed=True;self.session=None;self.devices=0;self.streams=[]
        if self.pipewire_fd is not None:
            try:os.close(self.pipewire_fd)
            except OSError:pass
            self.pipewire_fd=None
        return {'status':'closed'}

def serve():
    runtime=PortalRuntime()
    try:
        for line in sys.stdin:
            if len(line.encode())>MAX_INPUT:
                print(json.dumps({'ok':False,'error':'input_too_large'}),flush=True);continue
            try:
                req=json.loads(line);cmd=req.get('cmd');args=req.get('args') or {}
                if cmd=='discover':result=runtime.discover()
                elif cmd=='screenshot':result=runtime.screenshot()
                elif cmd=='create_session':result=runtime.create_session()
                elif cmd=='observe':result=runtime.observe()
                elif cmd=='status':result=runtime.status()
                elif cmd=='pointer_move':result=runtime.pointer_move(args.get('x'),args.get('y'))
                elif cmd=='pointer_click':result=runtime.pointer_click()
                elif cmd=='pointer_scroll':result=runtime.pointer_scroll(args.get('dx',0),args.get('dy',0))
                elif cmd=='key_press':result=runtime.key(str(args.get('key','')),True)
                elif cmd=='key_release':result=runtime.key(str(args.get('key','')),False)
                elif cmd=='close':result=runtime.close()
                else:raise PortalError('command_not_allowlisted')
                print(json.dumps({'ok':True,'result':result},separators=(',',':')),flush=True)
            except Exception as exc:print(json.dumps({'ok':False,'error':str(exc)[:120],'error_type':type(exc).__name__},separators=(',',':')),flush=True)
    finally:runtime.close()
if __name__=='__main__':
    if sys.argv[1:]!=['--serve']:raise SystemExit(2)
    serve()
