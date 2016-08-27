#!/usr/bin/env python

"""
sdserver: Tornado-based web server to serve Slidoc html files (with authentication)
          - Handles digest authentication using HMAC key
          - Can be used as a simple static file server (with authentication), AND
          - As a proxy server that handles spreadsheet operations on cached data and copies them to Google sheets

        Use 'sdserver.py --proxy_wait=0 --gsheet_url=...' and
            'slidoc.py --gsheet_url=... --proxy_url=/_websocket/ ...' to proxy user calls to Google sheet (but not slidoc.py setup calls, which are still directed to gsheet_url)
        Can specify 'slidoc.py --gsheet_url=http:/hostname/_proxy/ --proxy_url=/_websocket/ ...' to re-direct session setup calls to proxy as well.

        For proxying without websocket:
            'slidoc.py --gsheet_url=... --proxy_url=http://localhost/_proxy'
        
Command arguments:
    config: config file containing command line options as python assignment statements
    debug: Enable debug mode (can be used for testing local proxy data without gsheet_url)
    gsheet_url: Google sheet URL (required if proxy and not debugging)
    auth_key: Digest authentication key for admin user (enables login protection for website)
    port: Web server port number to listen on (default=8888)
    public: Public web site (no login required, except for paths containing _private/_restricted)
    proxy: Enable proxy mode (cache copies of Google Sheets)
    site_label: Site label, e.g., 'calc101'
    static_dir: path to static files directory containing Slidoc html files (default='static')
    twitter: path to Twitter JSON config file (to sign in via Twitter)
    xsrf: Enable XSRF cookies for security

Twitter auth workflow:
  - Register your application with Twitter at http://twitter.com/apps, using the Callback URL http://website/_oauth/twitter
  - Then copy your Consumer Key and Consumer Secret to file twitter.json
     {"consumer_key": ..., "consumer_secret": ...}
     sudo python sdserver.py --auth_key=... --gsheet_url=... --static_dir=... --port=80 --proxy_wait=0 --site_label=... --twitter=twitter.json
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
import functools
import importlib
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

from tornado.options import define, options, parse_config_file, parse_command_line
from tornado.ioloop import IOLoop, PeriodicCallback

import sliauth
import plugins

Options = {
    '_index_html': '',  # Non-command line option
    'auth_key': '',
    'auth_type': '',
    'debug': False,
    'gsheet_url': '',
    'no_auth': False,
    'proxy_wait': None,
    'port': 8888,
    'public': False,
    'site_label': 'Slidoc',
    'site_url': '',
    'static_dir': 'static',
    'plugindata_dir': '',
    'xsrf': False,
    }

class Dummy():
    pass
    
Global = Dummy()
Global.rename = {}

PLUGINDATA_PATH = '_plugindata'
PRIVATE_PATH    = '_private'
RESTRICTED_PATH = '_restricted'

ADMINUSER_ID = 'admin'
TESTUSER_ID = '_test_user'
    
USER_COOKIE_SECURE = "slidoc_user_secure"
SERVER_COOKIE = "slidoc_server"
EXPIRES_DAYS = 30

WS_TIMEOUT_SEC = 3600
EVENT_BUFFER_SEC = 3


class UserIdMixin(object):
    def set_id(self, username, origId='', token='', displayName=''):
        if Options['debug']:
            print >> sys.stderr, 'sdserver.UserIdMixin.set_id', username, origId, token, displayName
        if ':' in username or ':' in origId or ':' in token or ':' in displayName:
            raise Exception('Colon character not allowed in username/origId/token/name')
        if username == ADMINUSER_ID:
            token = token + ',' + sliauth.gen_user_token(token, TESTUSER_ID)
        cookieStr = username+':'+origId+':'+urllib.quote(token, safe='')+':'+urllib.quote(displayName, safe='')
        self.set_secure_cookie(USER_COOKIE_SECURE, cookieStr, expires_days=EXPIRES_DAYS)
        self.set_cookie(SERVER_COOKIE, cookieStr, expires_days=EXPIRES_DAYS)

    def clear_id(self):
        self.clear_cookie(USER_COOKIE_SECURE)
        self.clear_cookie(SERVER_COOKIE)

    def get_path_base(self, path):
        # Extract basename, without file extension, from URL path
        basename = path.split('/')[-1]
        if '.' in basename:
            basename, sep, suffix = basename.rpartition('.')
        return basename

    def get_alt_name(self, username):
        if username in Global.rename:
            alt_name, _, session_prefix = Global.rename[username].partition(':')
            # Alt name may be followed by an option session name prefix for which the altname is valid, e.g., admin:ex
            if not session_prefix or self.get_path_base(self.get_argument("next", "/")).startswith(session_prefix):
                return alt_name
        return username

    def check_access(self, username, token):
        if username == ADMINUSER_ID:
            return token == Options['auth_key']
        else:
            return token == sliauth.gen_user_token(Options['auth_key'], username)

    def get_id_from_cookie(self, orig=False):
        # Ensure SERVER_COOKIE is also set before retrieving id from secure cookie (in case one of them gets deleted)
        cookieStr = self.get_secure_cookie(USER_COOKIE_SECURE) if self.get_cookie(SERVER_COOKIE) else ''
        if not cookieStr:
            return None
        try:
            userId, origId, token, displayName = cookieStr.split(':')
            return origId if orig else userId
        except Exception, err:
            print >> sys.stderr, 'sdserver: Cookie error - '+str(err)
            self.clear_id()
            return None

    def custom_error(self, errCode, html_msg, clear_cookies=False):
        if clear_cookies:
            self.clear_all_cookies() 
        self.clear()
        self.set_status(errCode)
        self.finish(html_msg)


class BaseHandler(tornado.web.RequestHandler, UserIdMixin):
    def get_current_user(self):
        if not Options['auth_key']:
            self.clear_id()
            return "noauth"
        return self.get_id_from_cookie() or None


class HomeHandler(BaseHandler):
    def get(self):
        if Options.get('_index_html'):
            # Not authenticated
            self.write(Options['_index_html'])
        else:
            # Authenticated by static file handler, if need be
            self.redirect("/index.html")


class ActionHandler(BaseHandler):
    @tornado.web.authenticated
    def get(self, subpath, inner=None):
        if self.get_current_user() not in (ADMINUSER_ID, TESTUSER_ID):
            self.write('Action not permitted: '+self.get_current_user())
            return
        import sdproxy
        action, sep, sessionName = subpath.partition('/')
        if action == '_dash':
            self.render('dashboard.html')
        elif action == '_clear':
            sdproxy.start_shutdown('clear')
            self.write('Clearing cache')
        elif action == '_shutdown':
            sdproxy.start_shutdown('shutdown')
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
            self.write('  No. of updates (retries): %d (%d)\n  Average update time = %ss\n' % (sdproxy.Global.totalCacheResponseCount, sdproxy.Global.totalCacheRetryCount, sdproxy.Global.totalCacheResponseInterval/(1000*max(1,sdproxy.Global.totalCacheRetryCount)) ) )
            curTime = time.time()
            wsKeys = WSHandler._connections.keys()
            wsConnections = WSHandler.get_connections()
            sorted(wsConnections)
            wsInfo = []
            for path, user, connections in wsConnections:
                wsInfo += [(path, user+('/'+ws.origId if ws.origId else ''), math.floor(curTime-ws.msgTime)) for ws in connections]
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

        if Options['debug']:
            print "DEBUG: URI", self.request.uri

        retObj = sdproxy.handleResponse(args)

        self.set_header('Content-Type', mimeType)
        self.write(jsonPrefix+json.dumps(retObj, default=sliauth.json_default)+jsonSuffix)

class WSHandler(tornado.websocket.WebSocketHandler, UserIdMixin):
    _connections = collections.defaultdict(functools.partial(collections.defaultdict,list))
    @classmethod
    def get_connections(cls):
        # Return list of tuples [ (path, user, connections) ]
        lst = []
        for path, path_dict in cls._connections.items():
            for user, connections in path_dict.items():
                lst.append( (path, user, connections) )
        return lst

    def open(self, path=''):
        self.msgTime = time.time()
        self.locked = ''
        self.timeout = None
        self.userId = self.get_id_from_cookie()
        self.origId = self.get_id_from_cookie(orig=True)
        if self.origId == self.userId:
            self.origId = ''
        self.pathUser = (path, self.userId)
        self._connections[self.pathUser[0]][self.pathUser[1]].append(self)
        self.pluginInstances = {}
        self.awaitBinary = None

        if Options['debug']:
            print "DEBUG: WSopen", self.userId
        if not self.userId:
            self.close()

        self.eventBuffer = []
        self.eventFlusher = PeriodicCallback(self.flushEventBuffer, EVENT_BUFFER_SEC*1000)
        self.eventFlusher.start()

    def on_close(self):
        try:
            if self.eventFlusher:
                self.eventFlusher.stop()
                self.eventFlusher = None
            self._connections[self.pathUser[0]][self.pathUser[1]].remove(self)
            if not self._connections[self.pathUser[0]][self.pathUser[1]]:
                del self._connections[self.pathUser[0]][self.pathUser[1]]
            if not self._connections[self.pathUser[0]]:
                del self._connections[self.pathUser[0]]
        except Exception, err:
            pass


    def flushEventBuffer(self):
        while self.eventBuffer:
            # sendEvent: source, evName, evArg1, ...
            sendEvent = self.eventBuffer.pop(0)
            # Message: source, evName, [args]
            msg = [0, 'event', [sendEvent[0], sendEvent[1], sendEvent[2:]] ]
            self.write_message(json.dumps(msg, default=sliauth.json_default))

    def _close_on_timeout(self):
        if self.ws_connection:
            self.close()

    def getPluginMethod(self, pluginName, pluginMethodName):
        if pluginName not in self.pluginInstances:
            pluginModule = getattr(plugins, pluginName, None)
            if not pluginModule:
                raise Exception('Plugin '+pluginName+' not loaded!')
            pluginClass = getattr(pluginModule, pluginName)
            if not pluginClass:
                raise Exception('Plugin class '+pluginName+'.'+pluginName+' not defined!')
            try:
                self.pluginInstances[pluginName] = pluginClass(PluginManager.getManager(pluginName), self.pathUser[0], self.pathUser[1])
            except Exception, err:
                raise Exception('Error in creating instance of plugin '+pluginName+': '+err.message)

        pluginMethod = getattr(self.pluginInstances[pluginName], pluginMethodName, None)
        if not pluginMethod:
            raise Exception('Plugin '+pluginName+' has no method '+pluginMethodName)
        return pluginMethod

    def on_message(self, message):
        outMsg = self.on_message_aux(message)
        if outMsg:
            self.write_message(outMsg)
        self.timeout = IOLoop.current().call_later(WS_TIMEOUT_SEC, self._close_on_timeout)

    def on_message_aux(self, message):
        binaryContent = None
        if isinstance(message, bytes):
            # Binary message (treat as additional argument for last text message)
            if not self.awaitBinary:
                # Not waiting for binary message ignore
                return None
            binaryContent = message
            message = self.awaitBinary   # Restore buffered text message
            self.awaitBinary = None

        elif self.awaitBinary:
            # New text message; discard previous text message awaiting binary data
            print >> sys.stderr, 'sdserver: Discarded upload message due to lack of data: '+self.awaitBinary[:40]+'...'
            self.awaitBinary = None

        self.msgTime = time.time()
        if self.timeout:
            IOLoop.current().remove_timeout(self.timeout)
            self.timeout = None
        import sdproxy
        callback_index = None
        try:
            obj = json.loads(message)
            callback_index = obj[0]
            method = obj[1]
            args = obj[2]
            retObj = None
            if method == 'close':
                self.close()

            elif method == 'proxy':
                if args.get('write'):
                    if self.locked:
                        raise Exception(self.locked)
                    else:
                        for connection in self._connections[self.pathUser[0]][self.pathUser[1]]:
                            if connection is self:
                                continue
                            if not connection.locked:
                                connection.locked = 'Session locked due to modifications by another user. Reload page, if necessary.'
                                connection.write_message(json.dumps([0, 'lock', connection.locked]))

                retObj = sdproxy.handleResponse(args)

            elif method == 'plugin':
                if len(args) < 2:
                    raise Exception('Too few arguments to invoke plugin method: '+' '.join(args))
                pluginName, pluginMethodName = args[:2]
                pluginMethod = self.getPluginMethod(pluginName, pluginMethodName)

                if pluginMethodName.startswith('_upload'):
                    # plugin._upload*(arg1, ..., content=None)
                    print >> sys.stderr, 'sdserver: %s._upload...' % pluginName, args, not binaryContent
                    if not binaryContent:
                        # Buffer text message and wait for final binary argument
                        self.awaitBinary = message
                        return None
                    # Append binary data as final argument
                    args.append(binaryContent)
                    binaryContent = None
                try:
                    retObj = pluginMethod(*args[2:])
                except Exception, err:
                    raise Exception('Error in calling method '+pluginMethodName+' of plugin '+pluginName+': '+err.message)

            elif method == 'event':
                # event_target: '*' OR 'admin' or '' (for server) (IGNORED FOR NOW)
                # event_type = -1 immediate, 0 buffer, n >=1 (overwrite matching n name+args else buffer)
                # event_name = [plugin.]event_name
                evTarget, evType, evName, evArgs = args
                if Options['debug']:
                    print >> sys.stderr, 'sdserver.on_message_aux: event', self.userId, evType, evName

                pathConnections = self._connections[self.pathUser[0]]
                for toUser, connections in pathConnections.items():
                    if toUser == self.userId:
                        continue
                    if self.userId in (ADMINUSER_ID, TESTUSER_ID):
                        # From special user: broadcast to all but the sender
                        pass
                    elif toUser in (ADMINUSER_ID, TESTUSER_ID):
                        # From non-special user: send only to special users
                        pass
                    else:
                        continue

                    # Event [source, name, arg1, arg2, ...]
                    sendEvent = [self.userId, evName] + evArgs
                    for conn in connections:
                        if evType > 0:
                            # If evType > 0, only the latest occurrence of an event type with same evType name+arguments is buffered
                            for j in range(len(conn.eventBuffer)):
                                if conn.eventBuffer[j][1:evType+1] == sendEvent[1,evType+1]:
                                    conn.eventBuffer[j] = sendEvent
                                    sendEvent = None
                                    break
                            if sendEvent:
                                conn.eventBuffer.append(sendEvent)
                        else:
                            # evType <= 0
                            conn.eventBuffer.append(sendEvent)
                            if evType == -1:
                                conn.flushEventBuffer()


            if callback_index:
                return json.dumps([callback_index, '', retObj], default=sliauth.json_default)
        except Exception, err:
            if Options['debug']:
                raise Exception('Error in response: '+err.message)
            elif callback_index:
                    retObj = {"result":"error", "error": err.message, "value": None, "messages": ""}
                    return json.dumps([callback_index, '', retObj], default=sliauth.json_default)

class PluginManager(object):
    _managers = {}

    @classmethod
    def getManager(cls, pluginName):
        if pluginName not in cls._managers:
            cls._managers[pluginName] = PluginManager(pluginName)
        return cls._managers[pluginName]

    def __init__(self, pluginName):
        self.pluginName = pluginName

    def makePath(self, filepath, restricted=True, private=True):
        if not Options['plugindata_dir']:
            raise Exception('sdserver.PluginManager.makePath: ERROR No plugin data directory!')
        if '..' in filepath:
            raise Exception('sdserver.PluginManager.makePath: ERROR Invalid .. in file path: '+filepath)
            
        fullpath = filepath
        if restricted:
            fullpath = RESTRICTED_PATH + '/' + fullpath
        elif private:
            fullpath = PRIVATE_PATH + '/' + fullpath

        return '/'.join([ Options['plugindata_dir'], PLUGINDATA_PATH, self.pluginName, fullpath ])

    def readFile(self, filepath, restricted=True, private=True):
        # Returns file content from relative path
        fullpath = self.makePath(filepath, restricted=restricted, private=private)
        try:
            with open(fullpath) as f:
                content = f.read()
            return content
        except Exception, err:
            raise Exception('sdserver.PluginManager.readFile: ERROR in reading file %s: %s' % (fullpath, err))

    def writeFile(self, filepath, content, restricted=True, private=True):
        # Returns relative file URL
        fullpath = self.makePath(filepath, restricted=restricted, private=private)
        try:
            filedir = os.path.dirname(fullpath)
            if not os.path.exists(filedir):
                os.makedirs(filedir)
            with open(fullpath, 'w') as f:
                f.write(content)
            return fullpath[len(Options['plugindata_dir']):]
        except Exception, err:
            raise Exception('sdserver.PluginManager.writeFile: ERROR in writing file %s: %s' % (fullpath, err))

class BaseStaticFileHandler(tornado.web.StaticFileHandler):
    def set_extra_headers(self, path):
        # Disable cache
        self.set_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
    

class AuthStaticFileHandler(BaseStaticFileHandler, UserIdMixin):
    def get_current_user(self):
        userId = self.get_id_from_cookie() or None

        if ('/'+RESTRICTED_PATH) in self.request.path:
            # For paths containing '/_restricted', all filenames must end with *-userId[.extn] to be accessible by userId
            if not userId:
                return None
            if self.get_path_base(self.request.path).endswith('-'+userId) or userID == ADMINUSER_ID:
                return userId
            raise tornado.web.HTTPError(404)

        elif ('/'+PRIVATE_PATH) in self.request.path:
            # Paths containing '/_private' are always protected
            return userId

        if not Options['auth_key']:
            self.clear_id()   # Clear any cookies
            return "noauth"
        elif Options['public']:
            return "noauth"

        return userId

    # Override this method because overriding the get method of StaticFileHandler is problematic
    @tornado.web.authenticated
    def validate_absolute_path(self, *args, **kwargs):
        return super(AuthStaticFileHandler, self).validate_absolute_path(*args, **kwargs)
    

class AuthLoginHandler(BaseHandler):
    def get(self):
        error_msg = self.get_argument("error", "")
        username = self.get_argument("username", "")
        token = self.get_argument("token", "")
        next = self.get_argument("next", "/")
        if not error_msg and username and token:
            self.login(username, token, next=next)
        else:
            self.render("login.html", error_msg=error_msg, next=next, site_label=Options['site_label'],
                        login_url=Global.login_url, password='NO AUTHENTICATION' if Options['no_auth'] else 'Token:')

    def post(self):
        self.login(self.get_argument("username", ""), self.get_argument("token", ""), next=self.get_argument("next", "/"))

    def login(self, username, token, next="/"):
        if Options['no_auth'] and Options['debug'] and not Options['gsheet_url'] and username != ADMINUSER_ID:
            # No authentication option for testing local-only proxy
            token = sliauth.gen_user_token(Options['auth_key'], username)
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

class GoogleLoginHandler(tornado.web.RequestHandler,
                         tornado.auth.GoogleOAuth2Mixin, UserIdMixin):
    @tornado.gen.coroutine
    def get(self):
        if self.get_argument('code', False):
            user = yield self.get_authenticated_user(
                redirect_uri=self.settings['google_oauth']['redirect_uri'],
                code=self.get_argument('code'))
            if Options['debug']:
                print >>sys.stderr, "GoogleAuth: step 1", user

            if not user:
                self.custom_error(500, '<h2>Google authentication failed</h2><a href="/">Home</a>', clear_cookies=True)

            access_token = str(user['access_token'])
            http_client = self.get_auth_http_client()
            response =  yield http_client.fetch('https://www.googleapis.com/oauth2/v1/userinfo?access_token='+access_token)
            if not response:
                self.custom_error(500, '<h2>Google profile access failed</h2><a href="/">Home</a>', clear_cookies=True)

            user = json.loads(response.body)
            if Options['debug']:
                print >>sys.stderr, "GoogleAuth: step 2", user

            username = user['email'].lower()
            if Global.login_domain:
                if not username.endswith(Global.login_domain):
                    self.custom_error(500, '<h2>Authentication requires account '+Global.login_domain+'</h2><a href="https://mail.google.com/mail/u/0/?logout&hl=en">Logout of google (to sign in with a different account)</a><br><a href="/">Home</a>', clear_cookies=True)
                    return
                username = username[:-len(Global.login_domain)]

            if username in (ADMINUSER_ID, TESTUSER_ID):
                self.custom_error(500, 'Disallowed username: '+username, clear_cookies=True)

            displayName = user.get('family_name','').replace(',', ' ')
            if displayName and user.get('given_name',''):
                displayName += ', '
            displayName += user.get('given_name','')
            if not displayName:
                displayName = username

            username = self.get_alt_name(username)
            token = Options['auth_key'] if username == ADMINUSER_ID else sliauth.gen_user_token(Options['auth_key'], username)
            self.set_id(username, user['email'], token, displayName)
            self.redirect(self.get_argument("next", "/"))
            return

            # Save the user with e.g. set_secure_cookie
        else:
            yield self.authorize_redirect(
                redirect_uri=self.settings['google_oauth']['redirect_uri'],
                client_id=self.settings['google_oauth']['key'],
                scope=['profile', 'email'],
                response_type='code',
                extra_params={'approval_prompt': 'auto'})

class TwitterLoginHandler(tornado.web.RequestHandler,
                          tornado.auth.TwitterMixin, UserIdMixin):
    @tornado.gen.coroutine
    def get(self):
        if self.get_argument("oauth_token", None):
            user = yield self.get_authenticated_user()
            # Save the user using e.g. set_secure_cookie()
            username = user['username']
            if username in (ADMINUSER_ID, TESTUSER_ID):
                self.custom_error(500, 'Disallowed username: '+username, clear_cookies=True)
            username = self.get_alt_name(username)
            displayName = user['name']
            token = Options['auth_key'] if username == ADMINUSER_ID else sliauth.gen_user_token(Options['auth_key'], username)
            self.set_id(username, user['username'], token, displayName)
            self.redirect(self.get_argument("next", "/"))
        else:
            yield self.authorize_redirect()


class Application(tornado.web.Application):
    def __init__(self):
        handlers = [
            (r"/", HomeHandler),
            (r"/_auth/logout/", AuthLogoutHandler),
            (r"/_auth/login/", AuthLoginHandler),
            ]

        settings = {}
        Global.login_domain = ''
        Global.login_url = '/_auth/login'
        if Options['auth_type']:
            Global.login_url = '/_oauth/login'
            comps = Options['auth_type'].split(',')

            if Options['site_url']:
                redirect_uri = Options['site_url'] + Global.login_url
            else:
                redirect_uri = 'http://localhost'+ ('' if Options['port'] == 80 else ':'+str(Options['port'])) + Global.login_url

            Global.login_domain = comps[0] if comps[0][0] == '@' else ''

            if comps[0] == 'google' or Global.login_domain:
                settings.update(google_oauth={'key': comps[1],
                                            'secret': comps[2],
                                            'redirect_uri': redirect_uri})
                handlers += [ (Global.login_url, GoogleLoginHandler) ]

            elif comps[0] == 'twitter':
                settings.update(twitter_consumer_key=comps[1],
                                twitter_consumer_secret=comps[2])
                handlers += [ (Global.login_url, TwitterLoginHandler) ]

            else:
                raise Exception('sdserver: Invalid auth_type: '+comps[0])

            Global.rename = {}
            for name_map in comps[3:]:
                auth_name, slidoc_name = name_map.split('=')
                Global.rename[auth_name] = slidoc_name
                print >> sys.stderr, 'RENAME %s user %s -> %s' % (comps[0], auth_name, slidoc_name)


        settings.update(
            template_path=os.path.join(os.path.dirname(__file__), "server_templates"),
            xsrf_cookies=Options['xsrf'],
            cookie_secret=Options['auth_key'],
            login_url=Global.login_url,
            debug=Options['debug'],
        )

        if Options['proxy_wait'] is not None:
            handlers += [ (r"/_proxy", ProxyHandler),
                          (r"/_websocket/(.*)", WSHandler),
                          (r"/(_lock)", ActionHandler),
                          (r"/(_lock/[-\w.]+)", ActionHandler),
                          (r"/(_unlock/[-\w.]+)", ActionHandler),
                          (r"/(_(dash|clear|shutdown|stats))", ActionHandler),
                           ]

        fileHandler = BaseStaticFileHandler if Options['no_auth'] else AuthStaticFileHandler

        if Options['static_dir']:
            handlers += [ (r'/([^_].*)', fileHandler, {"path": Options['static_dir']}) ]

        for path in [PLUGINDATA_PATH, PRIVATE_PATH, RESTRICTED_PATH]:
            dir = Options['plugindata_dir'] if path == PLUGINDATA_PATH else Options['static_dir']
            if dir:
                handlers += [ (r'/(%s/.*)' % path, fileHandler, {"path": dir}) ]
            

        super(Application, self).__init__(handlers, **settings)


def main():
    define("config", type=str, help="Path to config file",
        callback=lambda path: parse_config_file(path, final=False))

    define("auth_key", default=Options["auth_key"], help="Digest authentication key for admin user")
    define("auth_type", default=Options["auth_type"], help="@example.com|google|twitter,key,secret,tuser1=suser1,...")
    define("debug", default=False, help="Debug mode")
    define("gsheet_url", default="", help="Google sheet URL")
    define("ssl", default="", help="SSL certs options file (JSON)")
    define("plugins", default="", help="List of plugin paths (comma separated)")
    define("no_auth", default=False, help="No authentication mode (for testing)")
    define("public", default=Options["public"], help="Public web site (no login required, except for _private/_restricted)")
    define("proxy_wait", type=int, help="Proxy wait time (>=0; omit argument for no proxy)")
    define("site_label", default=Options["site_label"], help="Site label for Login page")
    define("site_url", default=Options["site_url"], help="Site URL, e.g., http://example.com")
    define("plugindata_dir", default=Options["plugindata_dir"], help="Path to plugin data files directory")
    define("static_dir", default=Options["static_dir"], help="Path to static files directory")
    define("xsrf", default=False, help="XSRF cookies for security")

    define("port", default=Options['port'], help="Web server port", type=int)
    parse_command_line()

    if not options.auth_key and not options.public:
        sys.exit('Must specify one of --public or --auth_key=...')

    for key in Options:
        if not key.startswith('_'):
            Options[key] = getattr(options, key)

    if not options.debug:
        logging.getLogger('tornado.access').disabled = True

    if options.proxy_wait is not None:
        import sdproxy
        sdproxy.Options.update(AUTH_KEY=options.auth_key, SHEET_URL=options.gsheet_url, DEBUG=options.debug,
                               MIN_WAIT_TIME=options.proxy_wait)

    scriptdir = os.path.dirname(os.path.realpath(__file__))
    pluginsDir = scriptdir + '/plugins'
    pluginPaths = [pluginsDir+'/'+fname for fname in os.listdir(pluginsDir) if fname[0] not in '._' and fname.endswith('.py')]
    if options.plugins:
        # Plugins with same name will override earlier plugins
        pluginPaths += options.plugins.split(',')

    plugins = []
    for pluginPath in pluginPaths:
        pluginName = os.path.basename(pluginPath).split('.')[0]
        plugins.append(pluginName)
        importlib.import_module('plugins.'+pluginName)

    if plugins:
        print >> sys.stderr, 'sdserver: Loaded plugins: '+', '.join(plugins)

    if options.ssl:
        with open(options.ssl) as f:
            ssl_options = json.loads(f.read())
        http_server = tornado.httpserver.HTTPServer(Application(), ssl_options=ssl_options)
    else:
        http_server = tornado.httpserver.HTTPServer(Application())
    http_server.listen(options.port)
    print >> sys.stderr, "Listening on port", options.port
    IOLoop.current().start()


if __name__ == "__main__":
    main()
