#!/usr/bin/env python

"""
sdserver: Tornado-based web server to serve Slidoc html files (with authentication)
          - Handles authentication using HMAC key
          - Can be used as a simple static file server (with authentication), AND
          - As a proxy server that handles spreadsheet operations on cached data and copies them to Google sheets

        Use 'sdserver.py --proxy --gsheet_url=...' and 'slidoc.py --gsheet_url=... --proxy_url=/_websocket/ ...' to proxy user calls to Google sheet (but not slidoc.py setup calls, which are still directed to gsheet_url)
        Also specify --gsheet_url=http:/hostname/_proxy/ (for slidoc.py) to re-direct slidoc.py setup calls to proxy as well.

Command arguments:
    debug: Enable debug mode (can be used for testing local proxy data)
    gsheet_url: Google sheet URL (required if proxy and not debugging)
    hmac_key: HMAC key for admin user (enables login protection for website)
    port: Web server port number to listen on (default=8888)
    private: path component string identifying private files (if omitted, entire website is login protected if hmac_key is specified)
    proxy: Enable proxy mode (cache copies of Google Sheets)
    site_label: Site label, e.g., 'calc101'
    static_dir: path to static files directory containing Slidoc html files (default='static')
    twitter: path to Twitter JSON config file (to sign in via Twitter)
    xsrf: Enable XSRF cookies for security

Twitter auth workflow:
  - Register your application with Twitter at http://twitter.com/apps, using the Callback URL http://website/_oauth/twitter
  - Then copy your Consumer Key and Consumer Secret to file twitter.json
     {"consumer_key": ..., "consumer_secret": ...}
     sudo python sdserver.py --hmac_key=... --gsheet_url=... --static_dir=... --port=80 --proxy --site_label=... --twitter=twitter.json
  - Create an initial Slidoc, say ex00-setup.md
  - Ask all users to ex00-setup.html using their Twitter login
  - In Google Docs, copy the first four columns of the ex00-setup sheet to a new roster_slidoc sheet
  - Once the roster_slidoc sheet is created, only users listed in that sheet can login
    Correct any name entries in the sheet, and add emails and/or ID values as needed
  - For additional users, manually add rows to roster_slidoc later
  - If some users need to change their Twitter IDs later, include a dict in twitter.json, {..., "rename": {"old_id": "new_id", ...}}
  - For admin user, include "admin_id": "admin" in rename dict
    
"""

import collections
import datetime
import json
import logging
import math
import os.path
import sys
import time
import urllib

import tornado.auth
import tornado.escape
import tornado.httpserver
import tornado.options
import tornado.web
import tornado.websocket

from tornado.options import define, options
from tornado.ioloop import IOLoop

import sliauth

USER_COOKIE_SECURE = "slidoc_user_secure"
SERVER_COOKIE = "slidoc_server"
EXPIRES_DAYS = 30

WS_TIMEOUT_SEC = 600

class UserIdMixin(object):
    def set_id(self, username, origId='', token='', displayName=''):
        if ':' in username or ':' in origId:
            raise Exception('Colon character not allowed in username/origId')
        cookieStr = username+':'+origId+':'+urllib.quote(token, safe='')+':'+urllib.quote(displayName, safe='')
        self.set_secure_cookie(USER_COOKIE_SECURE, cookieStr, expires_days=EXPIRES_DAYS)
        self.set_cookie(SERVER_COOKIE, cookieStr, expires_days=EXPIRES_DAYS)

    def clear_id(self):
        self.clear_cookie(USER_COOKIE_SECURE)
        self.clear_cookie(SERVER_COOKIE)

    def check_access(self, username, token):
        if username == "admin":
            return token == options.hmac_key
        else:
            return token == sliauth.gen_user_token(options.hmac_key, username)

    def get_id_from_cookie(self, orig=False):
        # Ensure SERVER_COOKIE is also set before retrieving id from secure cookie (in case one of them gets deleted)
        cookieStr = self.get_secure_cookie(USER_COOKIE_SECURE) if self.get_cookie(SERVER_COOKIE) else ''
        if not cookieStr:
            return None
        userId, origId, token, displayName = cookieStr.split(':')
        return origId if orig else userId


class BaseHandler(tornado.web.RequestHandler, UserIdMixin):
    def get_current_user(self):
        if not options.hmac_key:
            self.clear_id()
            return "noauth"
        return self.get_id_from_cookie() or None


class HomeHandler(BaseHandler):
    def get(self):
        self.redirect("/index.html")


class ActionHandler(BaseHandler):
    @tornado.web.authenticated
    def get(self, subpath, inner=None):
        if self.get_current_user() != '"admin"':
            self.write('Action not permitted')
            return
        action, sep, sessionName = subpath.partition('/')
        import sdproxy
        if action == '_shutdown':
            sdproxy.start_shutdown()
            self.write('Starting shutdown')
        elif action == '_unlock':
            if sessionName in Lock_cache:
                del sdproxy.Lock_cache[sessionName]
            if sessionName in Sheet_cache:
                del sdproxy.Sheet_cache[sessionName]
            self.write('Unlocked '+sessionName)
        elif action == '_lock':
            if sessionName:
                sdproxy.Lock_cache[sessionName] = True
            self.write('Locked sessions: %s' % (', '.join(sdproxy.get_locked())) )
        elif action == '_stats':
            self.write('<pre>')
            self.write('Cache:\n')
            self.write('  No. of updates (retries): %d (%d)\n  Average update time = %ss\n' % (sdproxy.TotalCacheResponseCount, sdproxy.TotalCacheRetryCount, sdproxy.TotalCacheResponseInterval/(1000*max(1,sdproxy.TotalCacheRetryCount)) ) )
            curTime = time.time()
            wsKeys = WSHandler._connections.keys()
            sorted(wsKeys)
            wsInfo = []
            for pathUser in wsKeys:
                wsInfo += [(pathUser[0], pathUser[1]+('/'+ws.origId if ws.origId else ''), math.floor(curTime-ws.msgTime)) for ws in WSHandler._connections[pathUser]]
            sorted(wsInfo)
            self.write('\nConnections:\n')
            for x in wsInfo:
                self.write("  %s: %s (idle: %ds)\n" % x)
            self.write('</pre>')


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

class WSHandler(tornado.websocket.WebSocketHandler, UserIdMixin):
    _connections = collections.defaultdict(list)
    def open(self, path=''):
        self.msgTime = time.time()
        self.locked = ''
        self.timeout = None
        self.userId = self.get_id_from_cookie()
        self.origId = self.get_id_from_cookie(orig=True)
        if self.origId == self.userId:
            self.origId = ''
        self.pathUser = (path, self.userId)
        self._connections[self.pathUser].append(self)
        if options.debug:
            print "DEBUG: WSopen", self.userId
        if not self.userId:
            self.close()

    def on_close(self):
        try:
            self._connections[self.pathUser].remove(self)
            if not self._connections[self.pathUser]:
                del self._connections[self.pathUser]
        except Exception, err:
            pass

    def _close_on_timeout(self):
        if self.ws_connection:
            self.close()

    def on_message(self, message):
        self.msgTime = time.time()
        if self.timeout:
            IOLoop.current().remove_timeout(self.timeout)
            self.timeout = None
        import sdproxy
        outMsg = None
        callback_index = None
        try:
            obj = json.loads(message)
            callback_index = obj[0]
            method = obj[1]
            args = obj[2]
            if method == 'proxy':
                if args.get('write'):
                    if self.locked:
                        raise Exception(self.locked)
                    else:
                        for connection in self._connections[self.pathUser]:
                            if connection is self:
                                continue
                            if not connection.locked:
                                connection.locked = 'Session locked due to modifications by another user. Reload page, if necessary.'
                                connection.write_message(json.dumps([0, 'lock', connection.locked]))

                retObj = sdproxy.handleResponse(args)
            elif method == 'close':
                self.close()
            if callback_index:
                outMsg = json.dumps([callback_index, '', retObj], default=sliauth.json_default)
        except Exception, err:
            if options.debug:
                raise Exception('Error in response: '+err.message)
            elif callback_index:
                    retObj = {"result":"error", "error": err.message, "value": None, "messages": ""}
                    outMsg = json.dumps([callback_index, '', retObj], default=sliauth.json_default)

        if outMsg:
            self.write_message(outMsg)
        self.timeout = IOLoop.current().call_later(WS_TIMEOUT_SEC, self._close_on_timeout)


class AuthStaticFileHandler(tornado.web.StaticFileHandler, UserIdMixin): 
    def get_current_user(self):
        if not options.hmac_key:
            self.clear_id()
            return "noauth"
        if options.private and options.private not in self.request.path:
            return "noauth"
        return self.get_id_from_cookie() or None

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
            self.render("login.html", error_msg=error_msg, next=next, site_label=options.site_label,
                        login_url=Login_url)

    def post(self):
        self.login(self.get_argument("username", ""), self.get_argument("token", ""), next=self.get_argument("next", "/"))

    def login(self, username, token, next="/"):
        auth = self.check_access(username, token)
        if auth:
            self.set_id(username, '', token)
            self.redirect(next)
        else:
            error_msg = "?error=" + tornado.escape.url_escape("Incorrect username or token")
            self.redirect("/_auth/login/" + error_msg)

            
class AuthLogoutHandler(BaseHandler):
    def get(self):
        self.clear_id()
        self.write('Logged out.<p></p><a href="/">Home</a>')


class TwitterLoginHandler(tornado.web.RequestHandler,
                          tornado.auth.TwitterMixin, UserIdMixin):
    @tornado.gen.coroutine
    def get(self):
        if self.get_argument("oauth_token", None):
            user = yield self.get_authenticated_user()
            # Save the user using e.g. set_secure_cookie()
            username = user['username']
            if 'rename' in Twitter_config and username in Twitter_config['rename']:
                username = Twitter_config['rename'][username]
            displayName = user['name']
            token = options.hmac_key if username == 'admin' else sliauth.gen_user_token(options.hmac_key, username)
            self.set_id(username, user['username'], token, displayName)
            self.redirect(self.get_argument("next", "/"))
        else:
            yield self.authorize_redirect()


class Application(tornado.web.Application):
    def __init__(self):
        settings = dict(
            template_path=os.path.join(os.path.dirname(__file__), "server_templates"),
            xsrf_cookies=options.xsrf,
            cookie_secret=options.hmac_key,
            login_url=Login_url,
            debug=options.debug,
        )

        handlers = [
            (r"/", HomeHandler),
            (r"/_auth/logout/", AuthLogoutHandler),
            (r"/_auth/login/", AuthLoginHandler),
            ]

        if options.twitter:
            settings.update(twitter_consumer_key=Twitter_config['consumer_key'],
                            twitter_consumer_secret=Twitter_config['consumer_secret'])

            handlers += [ ("/_oauth/twitter", TwitterLoginHandler) ]

        if options.proxy:
            handlers += [ (r"/_proxy", ProxyHandler),
                          (r"/_websocket/(.*)", WSHandler),
                          (r"/(_lock)", ActionHandler),
                          (r"/(_lock/[-\w.]+)", ActionHandler),
                          (r"/(_unlock/[-\w.]+)", ActionHandler),
                          (r"/(_shutdown)", ActionHandler),
                          (r"/(_stats)", ActionHandler),
                           ]

        handlers += [ (r"/(.+)", AuthStaticFileHandler, {"path": options.static_dir}) ]

        super(Application, self).__init__(handlers, **settings)


Login_url = '/_auth/login/'
Twitter_config = {}
def main():
    global Login_url
    define("port", default=8888, help="Web server port", type=int)
    define("site_label", default="Slidoc", help="Site label")
    define("private", default="", help="Private path component (to protect with login)")
    define("static_dir", default="static", help="Path to static files directory")
    define("hmac_key", default="", help="HMAC key for admin user")
    define("gsheet_url", default="", help="Google sheet URL")
    define("twitter", default="", help="'consumer_key,consumer_secret' OR JSON config file for twitter authentication")
    define("debug", default=False, help="Debug mode")
    define("proxy", default=False, help="Proxy mode")
    define("xsrf", default=False, help="XSRF cookies for security")
    tornado.options.parse_command_line()
    if not options.debug:
        logging.getLogger('tornado.access').disabled = True

    if options.proxy:
        import sdproxy
        sdproxy.HMAC_KEY = options.hmac_key
        sdproxy.SHEET_URL = options.gsheet_url
        sdproxy.DEBUG = options.debug

    if options.twitter:
        Login_url = "/_oauth/twitter"
        if ',' in options.twitter:
            comps = options.twitter.split(',')
            Twitter_config.update(consumer_key=comps[0], consumer_secret=comps[1])
        else:
            # Twitter config file (JSON): {"consumer_key": ..., "consumer_secret": ..., rename={"aaa":"bbb",...}}
            tfile = open(options.twitter)
            Twitter_config.update(json.loads(tfile.read()))
            tfile.close()

    http_server = tornado.httpserver.HTTPServer(Application())
    http_server.listen(options.port)
    print >> sys.stderr, "Listening on port", options.port
    IOLoop.current().start()


if __name__ == "__main__":
    main()
