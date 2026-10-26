import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from server import Handler,Store,ThreadingHTTPServer

class HttpsConfigTests(unittest.TestCase):
 def test_https_origin_secure_cookie_and_cli_only_setup(self):
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'QKT_PUBLIC_ORIGIN':'https://app.example.test','QKT_SECURE_COOKIE':'1','QKT_DISABLE_WEB_SETUP':'1'}):
   store=Store(Path(tmp)/'db.sqlite3');http=ThreadingHTTPServer(('127.0.0.1',0),Handler);http.store=store;http.attempts=[]
   thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
   def post(path,data,origin='https://app.example.test'):
    return urlopen(Request(f'http://127.0.0.1:{http.server_port}'+path,data=json.dumps(data).encode(),headers={'Origin':origin,'X-QKT-Request':'1','Content-Type':'application/json'}))
   credentials={'name':'Admin','email':'admin@example.test','password':'qa-password-123'}
   try:
    with self.assertRaises(HTTPError) as err:post('/api/setup',credentials)
    self.assertEqual(err.exception.code,403)
    with store.connection() as db:
     self.assertEqual(store.all(db,'users'),[]);store.login(db,credentials,True)
    with post('/api/login',credentials) as response:self.assertIn('; Secure',response.headers['Set-Cookie'])
    with self.assertRaises(HTTPError) as err:post('/api/login',credentials,'https://evil.example.test')
    self.assertEqual(err.exception.code,403)
   finally:http.shutdown();http.server_close();thread.join()
