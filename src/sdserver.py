#!/usr/bin/env python

"""
sdserver: Tornado-based web server to serve Slidoc html files (with authentication)
          - Handles authentication using HMAC key
          - Can be used as a simple static file server (with authentication), AND
          - As a proxy server that handles spreadsheet operations on cached data and copies them to Google sheets

        Use 'sdserver.py --proxy --gsheet_url=...' and 'slidoc.py --gsheet_url=... --proxy_url=/_websocket/ ...' to proxy user calls to Google sheet (but not slidoc.py setup calls, which are still directed to gsheet_url)
        Also specify --gsheet_url=http:/hostname/_proxy/ (for slidoc.py) to re-direct slidoc.py setup calls to proxy as well.

Command arguments:
    port: Web server port number to listen on (default=8888)
    site_label: Site label, e.g., 'calc101'
    static: path to static files directory containing Slidoc html files (default='static')
    hmac_key: HMAC key for admin user
    proxy: Enable proxy mode (
    gsheet_url: Google sheet URL (required if proxy and not debugging)
    debug: Enable debug mode (can be used for testing local proxy data)
    xsrf: Enable XSRF cookies for security

"""

import datetime
import json
import os.path
import sys

import tornado.escape
import tornado.httpserver
import tornado.ioloop
import tornado.options
import tornado.web
import tornado.websocket

from tornado.options import define, options

import sliauth

USER_COOKIE_SECURE = "slidoc_user_secure"
SERVER_COOKIE = "slidoc_server"

class BaseHandler(tornado.web.RequestHandler):
    def get_current_user(self):
        if not options.hmac_key:
            self.clear_cookie(USER_COOKIE_SECURE)
            self.clear_cookie(SERVER_COOKIE)
            return "noauth"
        user_id = self.get_secure_cookie(USER_COOKIE_SECURE)
        return user_id or None


class HomeHandler(BaseHandler):
    @tornado.web.authenticated
    def get(self):
        self.redirect("/index.html")


class ProxyHandler(BaseHandler):
    def get(self):
        self.handleResponse()

    def post(self):
        self.handleResponse()

    def handleResponse(self):
        jsonPrefix = ''
        jsonSuffix = ''
        mimeType = 'application/json'
        if self.get_argument('prefix',''):
            jsonPrefix = self.get_argument('prefix','') + '(' + (self.get_argument('callback') or '0') + ', '
            jsonSuffix = ')'
            mimeType = 'application/javascript'

        import sdproxy
        args = {}
        for arg_name in self.request.arguments:
            args[arg_name] = self.get_argument(arg_name)

        if options.debug:
            print "DEBUG: URI", self.request.uri

        retObj = sdproxy.handleResponse(args)

        self.set_header('Content-Type', mimeType)
        self.write(jsonPrefix+json.dumps(retObj, default=sliauth.json_default)+jsonSuffix)

class WSHandler(tornado.websocket.WebSocketHandler):
    def open(self):
        if options.debug:
            print "DEBUG: WSopen", self.get_secure_cookie(USER_COOKIE_SECURE)
        if not self.get_secure_cookie(USER_COOKIE_SECURE):
            self.close()

    def on_close(self):
        pass

    def on_message(self, message):
        import sdproxy
        try:
            obj = json.loads(message)
            callback_index = obj[0]
            args = obj[1]
            retObj = sdproxy.handleResponse(args)
            self.write_message(json.dumps([callback_index, retObj], default=sliauth.json_default))
        except Exception, err:
            pass


class AuthStaticFileHandler(tornado.web.StaticFileHandler): 
    def get_current_user(self):
        if not options.hmac_key:
            self.clear_cookie(USER_COOKIE_SECURE)
            self.clear_cookie(SERVER_COOKIE)
            return "noauth"
        user_id = self.get_secure_cookie(USER_COOKIE_SECURE)
        return user_id or None

    # Override this method because overriding the get method of StaticFileHandler is problematic
    @tornado.web.authenticated
    def validate_absolute_path(self, *args, **kwargs):
        return super(AuthStaticFileHandler, self).validate_absolute_path(*args, **kwargs)

    def set_extra_headers(self, path):
        # Disable cache
        self.set_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
    
class AuthLoginHandler(BaseHandler):
    def get(self):
        error_msg = self.get_argument("error", "")
        username = self.get_argument("username", "")
        token = self.get_argument("token", "")
        next = self.get_argument("next", "/")
        if not error_msg and username and token:
            self.login(username, token, next=next)
        else:
            self.render("login.html", error_msg=error_msg, next=next, site_label=options.site_label)

    def post(self):
        self.login(self.get_argument("username", ""), self.get_argument("token", ""), next=self.get_argument("next", "/"))

    def check_access(self, username, token):
        if username == "admin":
            return token == options.hmac_key
        else:
            return token == sliauth.gen_user_token(options.hmac_key, username)

    def login(self, username, token, next="/"):
        auth = self.check_access(username, token)
        if auth:
            self.set_secure_cookie(USER_COOKIE_SECURE, tornado.escape.json_encode(username))
            self.set_cookie(SERVER_COOKIE, username+":"+token)
            self.redirect(next)
        else:
            error_msg = "?error=" + tornado.escape.url_escape("Incorrect username or token")
            self.redirect("/_auth/login/" + error_msg)

            
class AuthLogoutHandler(BaseHandler):
    def get(self):
        self.clear_cookie(USER_COOKIE_SECURE)
        self.clear_cookie(SERVER_COOKIE)
        self.write('Logged out.<p></p><a href="/">Home</a>')


class Application(tornado.web.Application):
    def __init__(self):
        handlers = [
            (r"/", HomeHandler),
            (r"/_auth/login/", AuthLoginHandler),
            (r"/_auth/logout/", AuthLogoutHandler),
            ]

        if options.proxy:
            handlers += [ (r"/_proxy/", ProxyHandler),
                           (r"/_websocket/", WSHandler)]

        handlers += [ (r"/(.+)", AuthStaticFileHandler, {"path": options.static}) ]

        settings = dict(
            template_path=os.path.join(os.path.dirname(__file__), "server_templates"),
            xsrf_cookies=options.xsrf,
            cookie_secret=options.hmac_key,
            login_url="/_auth/login/",
            debug=options.debug,
        )
        super(Application, self).__init__(handlers, **settings)


def main():
    define("port", default=8888, help="Web server port", type=int)
    define("site_label", default="Slidoc", help="Site label")
    define("static", default="static", help="Path to static files directory")
    define("hmac_key", default="", help="HMAC key for admin user")
    define("gsheet_url", default="", help="Google sheet URL")
    define("debug", default=False, help="Debug mode")
    define("proxy", default=False, help="Proxy mode")
    define("xsrf", default=False, help="XSRF cookies for security")
    tornado.options.parse_command_line()

    if options.proxy:
        import sdproxy
        sdproxy.HMAC_KEY = options.hmac_key
        sdproxy.SHEET_URL = options.gsheet_url
        sdproxy.DEBUG = options.debug

    http_server = tornado.httpserver.HTTPServer(Application())
    http_server.listen(options.port)
    print >> sys.stderr, "Listening on port", options.port
    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
