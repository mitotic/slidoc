#!/usr/bin/env python

"""
sdviewer: Web service to convert slidoc documents to HTML
Usage: ./sliweb.py
"""

from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
from SocketServer import ForkingMixIn
from cStringIO import StringIO

import base64
import cgi
import hashlib
import hmac
import os.path
import sys
import threading
import urlparse
import urllib2

import slidoc

html_form = '''<!DOCTYPE html>
<html>
<head>
<script   src="https://code.jquery.com/jquery-2.2.4.min.js"   integrity="sha256-BbhdlvQf/xTY9gja0Dq3HiwQF8LaCRTXxZKRutelT44="   crossorigin="anonymous"></script>
<script>
$(document).on("dragover drop", function(e) {
    e.preventDefault();
  $("#dropbox").css("border", "dashed 2px");
}).on("drop", function(e) {
    $("input[type='file']")
        .prop("files", e.originalEvent.dataTransfer.files)
        .closest("form")
          .submit();
$("#processing").show();
$("#form").hide();
});
$(document).on("dragleave", function(e) {
  e.preventDefault();
  $("#dropbox").css("border", "solid 2px");
});
</script>
</head>
<body>
<h3 id="processing" style="display: none;">Processing file ...</h3>
<form id="form" enctype="multipart/form-data" method="POST">
  <h2>Slidoc viewer</h2>
  <h3>Command options:</h3>
  <blockquote>
  <p>Indexed: <input type="checkbox" name="indexed" value="indexed"></p>
  <p>Printable: <input type="checkbox" name="printable" value="printable"></p>
  <p>Verbose: <input type="checkbox" name="verbose" value="verbose"></p>
  <p></p>
  <p>Pace: <input name="pace" type="text" value=""></input> (paceLevel,delaySec,tryCount,tryDelay)</p>
  <p>Google Sheet URL: <input name="gsheet_url" type="text" value=""></input></p>
  <p>Google Sheet HMAC key: <input name="gsheet_login" type="text" value=""></input></p>
  </blockquote>
  <hr>
  <div id="dropbox" style="padding: 3px; border: solid 2px;">
    <b>Drag-and-drop file here (or select file below to upload)</b>
    <p>File: <input type="file" name="file"></input></p>
    <p><input type="submit" value="Upload"></input></p>
    <p></p>
  </div>
  <hr>
  Tip: To directly generate and view a Slidoc file located at <code>http://example.com/file.md</code>, use URL of the form:<br>
  <code>http://%(host)s/http://example.com/file.md</code>
</form>

</body>
</html>
'''

html_response = '''<!DOCTYPE html>
<html>
<head>
<script   src="https://code.jquery.com/jquery-2.2.4.min.js"   integrity="sha256-BbhdlvQf/xTY9gja0Dq3HiwQF8LaCRTXxZKRutelT44="   crossorigin="anonymous"></script>
<body>
<a href="/"><b>Home</b></a>
<p></p>
<p>Command: <code>slidoc.py %(args)s</code></p>
<p>Generated file: <code><b>%(filename)s</b></code></p>
<form method="POST" action="/generated">
  <input name="hmac" type="text" value="%(hmac)s" style="display: none;"></input>
  <input name="filename" type="text" value="%(filename)s" style="display: none;"></input>
  <textarea name="html" style="display: none;">%(html)s</textarea>
  <p><input name="view" type="submit" value="View file"></input></p>
  <p><input name="download" type="submit" value="Download file"></input></p>
</form>
Command output:
<blockquote>
<pre style="max-width: 960px; word-wrap: break-word;">%(messages)s</pre>
</blockquote>
</body>
</html>
'''

HMAC_KEY = 'testkey'
TRUNCATE_DIGEST = 16
def gen_hmac_token(message):
    token = base64.b64encode(hmac.new(HMAC_KEY, message, hashlib.md5).digest())
    return token[:TRUNCATE_DIGEST]

def process_files(files, filenames, cmd_args=[]):
    try:
        args_dict = slidoc.cmd_args2dict(slidoc.alt_parser.parse_args(cmd_args))
        outname, html, messages = slidoc.process_input(files, filenames, args_dict, return_html=True)
        return '', outname, html, messages
    except Exception, excp:
        import traceback
        traceback.print_exc()
        return str(excp) or 'Internal error', '', '', []
            
class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        parsed_url = urlparse.urlparse(self.path)
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={'REQUEST_METHOD':'POST',
                     'CONTENT_TYPE':self.headers['Content-Type'],
                     })
        if parsed_url.path == '/generated':
            html = base64.b64decode(form['html'].value)
            if gen_hmac_token(html) != form['hmac'].value:
                self.respond('ERROR: HMAC mismatch')
            else:
                if 'view' in form and form['view'].value:
                    self.respond(html)
                else:
                    self.respond(html, filename=form['filename'].value)
            return

        filename = form['file'].filename
        cmd_args = []
        for arg in ("printable", "verbose",):
            if arg in form and form[arg].value:
                cmd_args.append("--"+arg)
        if "indexed" in form and form["indexed"].value:
            cmd_args.append("--all=%s --indexed=toc,ind,qind" % filename)
        for arg in ("pace", "gsheet_url", "gsheet_login"):
            if arg in form and form[arg].value:
                cmd_args.append("--"+arg+"="+form[arg].value)
        errmsg, outname, html, messages = process_files([form['file'].file], [filename], cmd_args)
        if errmsg:
            self.respond('<p><a href="/"><b>Home</b></a></p>ERROR: '+cgi.escape(errmsg))
        else:
            self.respond(html_response % {'args':' '.join(cmd_args), 'filename': outname,
                                          'hmac': gen_hmac_token(html), 'html':base64.b64encode(html),
                                          'messages': '\n'.join(cgi.escape(x) for x in messages)})

    def do_GET(self):
        parsed_url = urlparse.urlparse(self.path)
        params = urlparse.parse_qs(parsed_url.query)
        if parsed_url.path.startswith('/http:') or parsed_url.path.startswith('/https:'):
            url = parsed_url.path[1:]
            if parsed_url.query:
                url += '?' + parsed_url.query
            parsed_suburl = urlparse.urlparse(url)
            filename = os.path.basename(parsed_suburl.path) or 'file.md'
            req = urllib2.Request(url)
            try:
                response = urllib2.urlopen(req)
                file = StringIO(response.read())
            except Exception, excp:
                self.respond(cgi.escape('ERROR in accessing URL %s: %s' % (url, excp)))
                return
            cmd_args = []
            for arg in ("pace", "gsheet_url"):
                if arg in params and params[arg][0]:
                    cmd_args.append("--"+arg+"="+params[arg][0])
                    if arg == "gsheet_url":
                        cmd_args.append("--gsheet_login=")
            errmsg, outname, html, messages = process_files([file], [filename], cmd_args)
            if errmsg:
                self.respond('ERROR: '+errmsg)
            else:
                self.respond(html)
        else:
            self.respond(html_form % {'host': self.headers["Host"]})

    def respond(self, response, status=200, filename=None):
        self.send_response(status)
        if filename:
            self.send_header("Content-Disposition", "attachment; filename="+filename)
            self.send_header("Content-type", "text/plain")
        else:
            self.send_header("Content-type", "text/html")
        self.send_header("Content-length", len(response))
        self.end_headers()
        self.wfile.write(response)

class ForkingHTTPServer(ForkingMixIn, HTTPServer):
    """Handle requests in a separate fork."""
    def verify_request(self, request, client_address):
        if 0:
            return False
        return HTTPServer.verify_request(self, request, client_address)
        
def run():
    import argparse
    parser = argparse.ArgumentParser(description='sdviewer: convert and display slidoc Markdown as HTML')
    parser.add_argument('--port', type=int, default=8181, help='HTTP port number (default: 8181)')
    cmd_args = parser.parse_args()
    server_address = ('', cmd_args.port)
    print >> sys.stderr, 'Listening on port', cmd_args.port
    server = ForkingHTTPServer(server_address, Handler)
    server.serve_forever()

run()
