import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from PIL import Image
from io import BytesIO

from app.services.collector_service import CollectorService

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/img.jpg':
            im = Image.new('RGB', (12, 8), (255, 0, 0))
            buf = BytesIO(); im.save(buf, format='JPEG')
            data = buf.getvalue(); self.send_response(200); self.send_header('Content-Type','image/jpeg'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data); return
        html = '<html><head><title>图片网页</title></head><body><article><h1>测试文章</h1><p>正文内容。</p><img src="/img.jpg"></article></body></html>'
        data = html.encode(); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
    def log_message(self, *args): pass

def test_web_image_download(tmp_path):
    from app.database.migrations import migrate
    db = tmp_path / 'db.sqlite'; migrate(db)
    server = HTTPServer(('127.0.0.1',0), Handler); t=threading.Thread(target=server.serve_forever,daemon=True); t.start()
    try:
        svc=CollectorService(db,tmp_path/'data')
        result=svc.collect_url(f'http://127.0.0.1:{server.server_port}/article')
        assert result['status']=='created'
        assert result['metadata']['images']['downloaded']==1
        assert len(svc.images.list(10, 0))==1
        assert Path(svc.images.list(10, 0)[0]['file_path']).exists()
    finally: server.shutdown(); t.join(timeout=2)
