"""Serve the unified VR inspector locally: --socket --path-file --output [--port]."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import secrets
from urllib.parse import unquote, urlsplit
from .service import Inspector

STATIC=Path(__file__).resolve().parents[2]/'frontend/scrywrite/inspector'


def make_handler(service, port, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):
            pass

        def send(self,code,data,kind='application/json'):
            payload=data if isinstance(data,bytes) else json.dumps(data,allow_nan=False).encode()
            self.send_response(code)
            self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(payload)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'")
            self.end_headers();self.wfile.write(payload)

        def authorized(self,write=False):
            if self.headers.get('Host') not in (f'127.0.0.1:{port}',f'localhost:{port}'):
                raise PermissionError('local host required')
            if write:
                if self.headers.get('X-Inspector-Token')!=token:
                    raise PermissionError('invalid inspector token')
                origin=self.headers.get('Origin')
                if origin and origin not in (f'http://127.0.0.1:{port}',f'http://localhost:{port}'):
                    raise PermissionError('same origin required')

        def do_GET(self):
            try:
                self.authorized()
                route=unquote(urlsplit(self.path).path)
                if route=='/api/status':
                    return self.send(200,service.status())
                if route=='/api/config':
                    return self.send(200,{'token':token})
                if route.startswith('/artifacts/'):
                    root=service.output.resolve();file=(root/route.removeprefix('/artifacts/')).resolve()
                else:
                    root=STATIC.resolve();file=(root/('index.html' if route=='/' else route.lstrip('/'))).resolve()
                if not file.is_relative_to(root) or not file.is_file():
                    return self.send(404,{'error':'not found'})
                return self.send(200,file.read_bytes(),mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
            except PermissionError as error:
                self.send(403,{'error':str(error)})
            except Exception as error:
                self.send(503,{'error':str(error)})

        def do_POST(self):
            try:
                self.authorized(write=True)
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=4096:
                    raise ValueError('invalid request size')
                data=json.loads(self.rfile.read(size))
                route=urlsplit(self.path).path
                if route=='/api/capture':result=service.capture()
                elif route=='/api/measure':result=service.measure(data.get('roi'),data.get('expectations'))
                elif route=='/api/visibility':result=service.visibility(data['visibility'])
                elif route=='/api/pick':result=service.pick(data['capture'],data['eye'],data['x'],data['y'])
                elif route=='/api/run':result=service.start(data.get('final',False),data.get('review',False))
                elif route=='/api/stop':service.cancel.set();result={'stopping':True}
                else:return self.send(404,{'error':'unknown operation'})
                self.send(200,result)
            except PermissionError as error:self.send(403,{'error':str(error)})
            except Exception as error:self.send(409,{'error':str(error)})
    return Handler


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket',required=True,type=Path)
    parser.add_argument('--path-file',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--port',type=int,default=8766)
    args=parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error('use a new/empty output directory')
    service=Inspector(args.socket,args.path_file,args.output)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),make_handler(service,args.port,secrets.token_urlsafe(32)))
    print(f'ScryWrite inspector: http://127.0.0.1:{args.port}',flush=True)
    try:server.serve_forever()
    finally:service.cancel.set();server.server_close()


if __name__=='__main__':main()
