import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from urllib.request import HTTPRedirectHandler, Request, build_opener, ProxyHandler, HTTPSHandler


class NoProviderRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *args):
        pass

    def do_POST(self):
        try:
            if self.path != '/gateway' or not hmac.compare_digest(
                    self.headers.get('Authorization',''), 'Bearer '+os.environ['TEAM_GATEWAY_TOKEN']):
                print('ERR bad path or token', flush=True)
                self.send_error(403); return
            size = int(self.headers.get('Content-Length','0'))
            if not 0 < size <= 65536: raise ValueError('size')
            frame = json.loads(self.rfile.read(size))
            if set(frame) != {'messages','max_output_tokens'}: raise ValueError('frame keys')
            if not isinstance(frame['messages'],list) or not 1 <= len(frame['messages']) <= 24: raise ValueError('messages')
            if type(frame['max_output_tokens']) is not int or not 16 <= frame['max_output_tokens'] <= 2048: raise ValueError('tokens')
            url = os.environ['TEAM_PROVIDER_URL'].strip()
            if not url.startswith('https://'): raise ValueError('url')
           request = Request(url, data=json.dumps({'model':os.environ['TEAM_MODEL'].strip(),
                'messages':frame['messages'], 'max_tokens':max(frame['max_output_tokens'],1024), 'reasoning_effort':'low'}).encode(),
                headers={'Content-Type':'application/json', 'Accept':'application/json',
                         'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36',
                         'Authorization':'Bearer '+os.environ['TEAM_PROVIDER_KEY'].strip()})
            opener = build_opener(ProxyHandler({}), HTTPSHandler(), NoProviderRedirect())
            with opener.open(request, timeout=35) as response:
                raw = response.read(131073)
            if len(raw)>131072: raise ValueError('too big')
            result=json.loads(raw)
            text=result['choices'][0]['message']['content']
            if not isinstance(text,str) or not 0<len(text.encode())<=65536: raise ValueError('text')
            usage=result.get('usage',{})
            body=json.dumps({'text':text, 'usage':{out:usage[key] for key,out in (
                ('prompt_tokens','input_tokens'),('completion_tokens','output_tokens'))
                if type(usage.get(key)) is int and usage[key]>=0}}).encode()
            self.send_response(200); self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
        except Exception as e:
            detail = ''
            try:
                detail = e.read(300).decode('utf-8', 'replace')
            except Exception:
                pass
            print('ERR', repr(e), detail, flush=True)
            self.send_error(503, 'Team gateway unavailable')


if __name__ == '__main__':
    for key in ('TEAM_PROVIDER_URL','TEAM_PROVIDER_KEY','TEAM_MODEL','TEAM_GATEWAY_TOKEN'):
        if not os.environ.get(key): raise SystemExit('Configure team provider and gateway environment')
    HTTPServer(('0.0.0.0',int(os.environ.get('PORT','8080'))),Handler).serve_forever()
