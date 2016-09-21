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
    xsrf: Enable XSRF cookies for security

    For Twitter auth workflow, see sdstream.py

"""

import collections
import cStringIO
import csv
import datetime
import functools
import importlib
import json
import logging
import math
import os.path
import re
import sys
import time
import urllib
import uuid

import tornado.auth
import tornado.escape
import tornado.httpserver
import tornado.options
import tornado.web
import tornado.websocket

from tornado.options import define, options, parse_config_file, parse_command_line
from tornado.ioloop import IOLoop, PeriodicCallback

import sdproxy
import sliauth
import plugins

Options = {
    '_index_html': '',  # Non-command line option
    'auth_key': '',
    'auth_type': '',
    'debug': False,
    'dry_run': False,
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
Global.backup = None

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
    @classmethod
    def get_path_base(cls, path):
        # Extract basename, without file extension, from URL path
        basename = path.split('/')[-1]
        if '.' in basename:
            basename, sep, suffix = basename.rpartition('.')
        return basename

    def set_id(self, username, origId='', token='', displayName='', email='', altid='', restrict=''):
        if Options['debug']:
            print >> sys.stderr, 'sdserver.UserIdMixin.set_id', username, origId, token, displayName, email, altid, restrict
        if ':' in username or ':' in origId or ':' in token or ':' in displayName:
            raise Exception('Colon character not allowed in username/origId/token/name')
        if username == ADMINUSER_ID:
            token = token + ',' + sliauth.gen_user_token(str(token), TESTUSER_ID)
        cookieStr = ':'.join( sliauth.safe_quote(x) for x in [username, origId, token, displayName, email, altid, restrict] );
        self.set_secure_cookie(USER_COOKIE_SECURE, cookieStr, expires_days=EXPIRES_DAYS)
        self.set_cookie(SERVER_COOKIE, cookieStr, expires_days=EXPIRES_DAYS)

    def clear_id(self):
        self.clear_cookie(USER_COOKIE_SECURE)
        self.clear_cookie(SERVER_COOKIE)

    def get_alt_name(self, username):
        if username in Global.rename:
            alt_name, _, session_prefix = Global.rename[username].partition(':')
            # Alt name may be followed by an option session name prefix for which the altname is valid, e.g., admin:assignments
            return alt_name, session_prefix
        return username, ''

    def check_access(self, username, token):
        if username == ADMINUSER_ID:
            return token == Options['auth_key']
        else:
            return token == sliauth.gen_user_token(Options['auth_key'], username)

    def get_id_from_cookie(self, orig=False, name=False, email=False, altid=False, prefix=False):
        # Ensure SERVER_COOKIE is also set before retrieving id from secure cookie (in case one of them gets deleted)
        cookieStr = self.get_secure_cookie(USER_COOKIE_SECURE) if self.get_cookie(SERVER_COOKIE) else ''
        if not cookieStr:
            return None
        try:
            comps = [urllib.unquote(x) for x in cookieStr.split(':')]
            if Options['debug']:
                print >> sys.stderr, "DEBUG: sdserver.UserIdMixin.get_id_from_cookie", comps
            userId, origId, token, displayName = comps[:4]
            if name:
                return displayName
            if email:
                return comps[4] if len(comps) > 4 else ''
            if altid:
                return comps[5] if len(comps) > 5 else ''
            if prefix:
                return comps[6] if len(comps) > 6 else ''
            return origId if orig else userId
        except Exception, err:
            print >> sys.stderr, 'sdserver: COOKIE ERROR - '+str(err)
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
        action, sep, sessionName = subpath.partition('/')
        if action == '_dash':
            self.render('dashboard.html', interactive=WSHandler.getInteractiveSession())
        elif action == '_clear':
            sdproxy.suspend_cache('clear')
            self.write('Clearing cache<br><a href="/_dash">Dashboard</a>')
        elif action == '_shutdown':
            self.clear_id()
            if Global.backup:
                Global.backup.stop()
                Global.backup = None
            sdproxy.suspend_cache('shutdown')
            self.write('Starting shutdown (also cleared cookies)<br><a href="/_dash">Dashboard</a>')
        elif action in ('_respond'):
            sessionName, sep, respId = sessionName.partition(';')
            if not sessionName:
                self.write('Please specify /_respond/session name')
                return
            nameMap = sdproxy.lookupRoster('name')
            if respId:
                if respId in nameMap:
                    sdproxy.importUserAnswers(sessionName, respId, nameMap[respId], source='manual')
                else:
                    self.write('User ID '+respId+' not in roster')
                    return
            sheet = sdproxy.Sheet_cache[sessionName]
            colIndex = sdproxy.indexColumns(sheet)
            idSet = set([x[0] for x in sheet.getSheetValues(1, colIndex['id'], sheet.getLastRow(), 1)])
            lines = ['<ul>\n']
            count = 0
            for idVal, name in nameMap.items():
                if idVal in idSet:
                    count += 1
                    lines.append('<li>'+name+'</li>\n')
                else:
                    lines.append('<li>%s (<a href="/_respond/%s;%s">respond</a>)</li>\n' % (name, sessionName, idVal))
            lines.append('</ul>\n')
            self.write(('Responders to session %s (%d/%d):' % (sessionName, count, len(nameMap)))+''.join(lines))
        elif action in ('_getcol', '_getrow'):
            sessionName, sep, label = sessionName.partition(';')
            sheet = sdproxy.Sheet_cache[sessionName]
            self.write('<a href="/_dash">Dashboard</a><br>')
            if not sheet:
                self.write('Session '+sessionName+' not in cache')
            else:
                if label.isdigit():
                    labelNum = int(label)
                elif len(label) == 1:
                    labelNum = ord(label) - ord('A') + 1
                else:
                    colIndex = sdproxy.indexColumns(sheet)
                    if action == '_getcol':
                        labelNum = colIndex.get(label, 0)
                    else:
                        labelNum = sdproxy.indexRows(sheet, colIndex['id'], 2).get(label, 0)
                if action == '_getcol':
                    if labelNum < 1 or labelNum > sheet.getLastColumn():
                        self.write('Column '+label+' not found in cached session '+sessionName)
                    else:
                        self.write('<pre>'+'\n'.join(str(x) for x in json.loads(json.dumps([x[0] for x in sheet.getSheetValues(1, labelNum, sheet.getLastRow(), 1)], default=sliauth.json_default)))+'</pre>')
                else:
                    if labelNum < 1 or labelNum > sheet.getLastRow():
                        self.write('Row '+label+' not found in cached session '+sessionName)
                    else:
                        headerVals = sheet.getSheetValues(1, 1, 1, sheet.getLastColumn())[0]
                        rowVals = sheet.getSheetValues(labelNum, 1, 1, sheet.getLastColumn())[0]
                        self.write('<pre>'+'\n'.join(headerVals[j]+':\t'+str(json.loads(json.dumps(rowVals[j], default=sliauth.json_default))) for j in range(len(rowVals))) +'</pre>')
        elif action == '_unlock':
            if sessionName in sdproxy.Lock_cache:
                del sdproxy.Lock_cache[sessionName]
            if sessionName in sdproxy.Sheet_cache:
                del sdproxy.Sheet_cache[sessionName]
            self.write('Unlocked '+sessionName+'<br><a href="/_dash">Dashboard</a>')
        elif action == '_lock':
            if sessionName:
                sdproxy.Lock_cache[sessionName] = 'user'
            self.write('Locked sessions: %s<br><a href="/_dash">Dashboard</a>' % (', '.join(sdproxy.get_locked())) )
        elif action == '_backup':
            errors = sdproxy.backupCache(sessionName)
            self.set_header('Content-Type', 'text/plain')
            self.write('Backed up cache to directory '+sessionName)
            if errors:
                self.write(errors)
        elif action == '_import':
            self.render('import.html', site_label=Options['site_label'])
        elif action == '_export':
            self.set_header('Content-Type', 'text/csv')
            self.set_header('Content-Disposition', 'attachment; filename="%s.csv"' % (sessionName+'_answers'))
            content = sdproxy.exportAnswers(sessionName)
            self.write(content)
        elif action == '_status':
            self.write('<a href="/_dash">Dashboard</a><br>')
            self.write('<pre>')
            self.write(sdproxy.getCacheStatus())
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

    def post(self, subpath, inner=None):
        if self.get_current_user() not in (ADMINUSER_ID, TESTUSER_ID):
            self.write('Action not permitted: '+self.get_current_user())
            return
        action, sep, sessionName = subpath.partition('/')
        if action == '_import':
            if 'upload' not in self.request.files:
                self.write('No file to upload!')
                return
            fileinfo = self.request.files['upload'][0]
            fname = fileinfo['filename']
            fbody = fileinfo['body']
            sessionName = self.get_argument('session','')
            submitDate = self.get_argument('submitdate','')
            if Options['debug']:
                print >> sys.stderr, 'ActionHandler:_import', sessionName, submitDate, fname, len(fbody)
            self.set_header('Content-Type', 'text/plain')
            if not sessionName:
                self.write('Must specify session name')
                return
            uploadedFile = cStringIO.StringIO(fbody)
            missed, errors = importAnswersAux(sessionName, submitDate, fname, uploadedFile)
            if not missed and not errors:
                self.write('Imported answers from '+fname)
            else:
                if missed:
                    self.write('ERROR: Missed uploading IDs: '+' '.join(missed)+'\n\n')
                if errors:
                    self.write('\n'.join(errors)+'\n')
        else:
            self.write('Invalid post action: '+action)

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

        args = {}
        for arg_name in self.request.arguments:
            args[arg_name] = self.get_argument(arg_name)

        if Options['debug']:
            print >> sys.stderr, "DEBUG: URI", self.request.uri

        retObj = sdproxy.sheetAction(args)

        self.set_header('Content-Type', mimeType)
        self.write(jsonPrefix+json.dumps(retObj, default=sliauth.json_default)+jsonSuffix)

class WSHandler(tornado.websocket.WebSocketHandler, UserIdMixin):
    _connections = collections.defaultdict(functools.partial(collections.defaultdict,list))
    _interactiveSession = (None, None, None)
    _interactiveErrors = {}
    @classmethod
    def get_connections(cls):
        # Return list of tuples [ (path, user, connections) ]
        lst = []
        for path, path_dict in cls._connections.items():
            for user, connections in path_dict.items():
                lst.append( (path, user, connections) )
        return lst

    @classmethod
    def getInteractiveSession(cls):
        if cls._interactiveSession[1]:
            return UserIdMixin.get_path_base(cls._interactiveSession[0])
        else:
            return ''

    @classmethod
    def setupInteractive(cls, path, slideId='', questionAttrs=None):
        cls._interactiveSession = (path, slideId, questionAttrs)
        cls._interactiveErrors = {}
        if Options['debug']:
            print >> sys.stderr, 'sdserver.setupInteractive:', cls._interactiveSession

    @classmethod
    def processMessage(cls, fromUser, fromName, message, allStatus=False, source=''):
        # Return null string on success or error message
        print >> sys.stderr, 'sdserver.processMessage:', fromUser, fromName, message

        path, slideId, questionAttrs = cls._interactiveSession
        if not path or not slideId:
            msg = 'Message from '+fromUser+' discarded. No active session'
            if Options['debug']:
                print >> sys.stderr, 'sdserver.processMessage:', msg
            return msg if allStatus else ''

        sessionName = cls.get_path_base(path)
        if not questionAttrs:
            msg = 'Message from '+fromUser+' discarded. No active slide/question for '+sessionName
            if Options['debug']:
                print >> sys.stderr, 'sdserver.processMessage:', msg
            return msg if allStatus else ''

        session_connections = cls._connections.get(path)
        if ADMINUSER_ID not in session_connections:
            cls._interactiveSession = (None, None, None)
            msg = 'Message from '+fromUser+' discarded. No active controller for session '+sessionName
            if Options['debug']:
                print >> sys.stderr, 'sdserver.processMessage:', msg
            return msg if allStatus else ''

        # Close any active connections associated with user for interactive session
        for connection in session_connections.get(fromUser,[]):
            connection.close()

        create = source or 'message'
        retval = sdproxy.getUserRow(sessionName, fromUser, fromName, opts={'getheaders': '1', 'create': create})
        if retval['result'] != 'success':
            msg = 'Error in processing message from '+fromUser+': '+retval['error']
            print >> sys.stderr, 'sdserver.processMessage:', msg
            return msg

        qnumber = questionAttrs['qnumber']
        if 'q'+str(qnumber)+'_response' not in retval['headers']:
            msg = 'Message from '+fromUser+' discarded. No shared response expected for '+sessionName
            if Options['debug']:
                print >> sys.stderr, 'sdserver.processMessage:', msg
            return msg

        errMsg = cls.processMessageAux(sessionName, fromUser, retval['value'], retval['headers'], questionAttrs, message)

        if errMsg:
            cls._interactiveErrors[fromUser] = errMsg
            if Options['debug']:
                print >> sys.stderr, 'sdserver.processMessage:', errMsg
        else:
            if fromUser in cls._interactiveErrors:
                del cls._interactiveErrors[fromUser]
            
        cls.sendEvent(path, fromUser, ['', 2, 'Share.answerNotify.'+slideId, [qnumber, cls._interactiveErrors]])
        return errMsg

    @classmethod
    def processMessageAux(cls, sessionName, fromUser, row, headers, questionAttrs, message):
        qnumber = questionAttrs['qnumber']
        qResponse = 'q'+str(qnumber)+'_response'
        qExplain = 'q'+str(qnumber)+'_explain'
        message = message.strip()

        if not message:
            return 'Null answer'

        qmatch = re.match(r'^q(\d+)\s', message)
        if qmatch:
            message = message[len(qmatch.group(0)):].strip()
            if int(qmatch.group(1)) != qnumber:
                return 'Wrong question'

        response = message.strip()
        explain = ''
        if questionAttrs['qtype'] in ('number', 'choice', 'multichoice'):
            comps = response.split()
            if len(comps) > 1:
                if qExplain in headers:
                    explain = response[len(comps[0]):].strip()
                response = comps[0]    # Ignore tail portion of message

        if questionAttrs['qtype'] == 'number' and sdproxy.parseNumber(response) is None:
            return 'Expecting number'
        elif questionAttrs['qtype'] == 'choice' and len(response) != 1:
            return 'Expecting letter'
        elif questionAttrs['qtype'] in ('choice', 'multichoice'):
            response = response.upper()
            for ch in response:
                offset = ord(ch) - ord('A')
                if offset < 0 or offset >= questionAttrs['choices']:
                    return 'Invalid choice'
                    
        row[headers.index(qResponse)] = response
        if qExplain in headers:
            row[headers.index(qExplain)] = explain
        row[headers.index('lastSlide')] = questionAttrs['slide']

        for j, header in enumerate(headers):
            if header.endswith('Timestamp'):
                row[j] = None

        retval = sdproxy.putUserRow(sessionName, fromUser, row)
        if retval['result'] != 'success':
            print >> sys.stderr, 'sdserver.processMessage:', 'Error in updating response from '+fromUser+': '+retval['error']
            return 'Unknown error'

        return ''
            
    @classmethod
    def sendEvent(cls, path, fromUser, args):
        # event_target: '*' OR 'admin' or '' (for server) (IGNORED FOR NOW)
        # event_type = -1 immediate, 0 buffer, n >=1 (overwrite matching n name+args else buffer)
        # event_name = [plugin.]event_name[.slide_id]
        evTarget, evType, evName, evArgs = args
        if Options['debug'] and not evName.startswith('Timer.clockTick'):
            print >> sys.stderr, 'sdserver.sendEvent: event', fromUser, evType, evName
        pathConnections = cls._connections[path]
        for toUser, connections in pathConnections.items():
            if toUser == fromUser:
                continue
            if fromUser in (ADMINUSER_ID, TESTUSER_ID):
                # From special user: broadcast to all but the sender
                pass
            elif toUser in (ADMINUSER_ID, TESTUSER_ID):
                # From non-special user: send only to special users
                pass
            else:
                continue

            # Event [source, name, arg1, arg2, ...]
            sendList = [fromUser, evName] + evArgs
            for conn in connections:
                if evType > 0:
                    # If evType > 0, only the latest occurrence of an event type with same evType name+arguments is buffered
                    buffered = False
                    for j in range(len(conn.eventBuffer)):
                        if conn.eventBuffer[j][1:evType+1] == sendList[1:evType+1]:
                            conn.eventBuffer[j] = sendList
                            buffered = True
                            break
                    if not buffered:
                        conn.eventBuffer.append(sendList)
                else:
                    # evType <= 0
                    conn.eventBuffer.append(sendList)
                    if evType == -1:
                        conn.flushEventBuffer()

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
            print >> sys.stderr, "DEBUG: WSopen", self.pathUser
        if not self.userId:
            self.close()

        self.eventBuffer = []
        self.eventFlusher = PeriodicCallback(self.flushEventBuffer, EVENT_BUFFER_SEC*1000)
        self.eventFlusher.start()

    def on_close(self):
        if Options['debug']:
            print >> sys.stderr, "DEBUG: WSon_close", self.pathUser
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
            sendList = self.eventBuffer.pop(0)
            # Message: source, evName, [args]
            msg = [0, 'event', [sendList[0], sendList[1], sendList[2:]] ]
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

        callback_index = None
        try:
            obj = json.loads(message)
            callback_index = obj[0]
            method = obj[1]
            args = obj[2]
            retObj = None
            if Options['debug']:
                print >> sys.stderr, 'sdserver.on_message_aux', method, len(args)
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

                retObj = sdproxy.sheetAction(args)

            elif method == 'interact':
                if self.userId == ADMINUSER_ID:
                    self.setupInteractive(self.pathUser[0], args[0], args[1])

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
                self.sendEvent(self.pathUser[0], self.pathUser[1], args)

            if callback_index:
                return json.dumps([callback_index, '', retObj], default=sliauth.json_default)
        except Exception, err:
            if Options['debug']:
                import traceback
                traceback.print_exc()
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

    @classmethod
    def getFileKey(cls, filepath, salt=''):
        filename = os.path.basename(filepath)
        salt = salt or uuid.uuid4().hex[:12]
        key = sliauth.gen_hmac_token(Options['auth_key'], salt+':'+filename)
        if salt == '_filename':
            # Backwards compatibility
            return sliauth.safe_quote(key)
        else:
            return sliauth.safe_quote(salt+':'+key)

    @classmethod
    def validFileKey(cls, filepath, key):
        salt, _, oldpath = key.partition(':')
        return sliauth.safe_quote(key) == cls.getFileKey(filepath, salt=salt)

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

    def lockFile(self, relativeURL):
        fullpath = Options['plugindata_dir']+relativeURL
        if os.path.exists(fullpath):
            try:
                os.chmod(fullpath, 0400)
            except Exception:
                pass

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
        # Return None only to request login; else raise HTTPError do deny access (to avoid looping)
        userId = self.get_id_from_cookie() or None
        if Options['debug']:
            print >> sys.stderr, "AuthStaticFileHandler.get_current_user", userId

        if ('/'+RESTRICTED_PATH) in self.request.path:
            # For paths containing '/_restricted', all filenames must end with *-userId[.extn] to be accessible by userId
            path = self.request.path
            query = self.request.query
            if getattr(self,'abs_query',''):
                path, _, tail = path.partition('%3F')
                query = getattr(self,'abs_query','')

            if PluginManager.validFileKey(path, query) or query == PluginManager.getFileKey(path, salt='_filename'):
                # Last check for backward compatibility with earlier non-salted version of file key
                return "noauth"
            elif not userId:
                return None
            elif self.get_path_base(self.request.path).endswith('-'+userId) or userId == ADMINUSER_ID:
                return userId
            raise tornado.web.HTTPError(404)

        elif ('/'+PRIVATE_PATH) in self.request.path:
            # Paths containing '/_private' are always protected
            sessionPrefix = self.get_id_from_cookie(prefix=True)
            if not sessionPrefix:
                return userId
            head, _, tail = self.request.path.partition('/'+PRIVATE_PATH+'/')
            if tail.startswith(sessionPrefix):
                return userId
            raise tornado.web.HTTPError(404)

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

    # Workaround for nbviewer chomping up query strings
    def get_absolute_path(self, *args, **kwargs):
        abs_path = super(AuthStaticFileHandler, self).get_absolute_path(*args, **kwargs)
        if '?' in abs_path:
            # Treat ? in path as the query delimiter (but not in get_current_user)
            abs_path, _, self.abs_query = abs_path.partition('?')
            if Options['debug']:
                print >>sys.stderr, "AuthStaticFileHandler.get_absolute_path", abs_path, self.abs_query
        return abs_path

    
class AuthMessageHandler(BaseHandler):
    @tornado.web.authenticated
    def get(self, subpath=''):
        note = self.get_argument("note", "")
        interactiveSession = WSHandler.getInteractiveSession()
        label = '%s: %s' % (self.get_id_from_cookie(), interactiveSession if interactiveSession else 'No interactive session')
        self.render("interact.html", note=note, site_label=Options['site_label'], session_label=label)

    @tornado.web.authenticated
    def post(self, subpath=''):
        try:
            msg = WSHandler.processMessage(self.get_id_from_cookie(), self.get_id_from_cookie(name=True), self.get_argument("message", ""), allStatus=True, source='interact')
            if not msg:
                msg = 'Previous message accepted'
        except Exception, excp:
            if Options['debug']:
                import traceback
                traceback.print_exc()
                msg = 'Error in processing message: '+str(excp)
                print >> sys.stderr, "AuthMessageHandler.post", msg
            else:
                msg = 'Error in processing message'
        self.redirect('/interact/?note='+sliauth.safe_quote(msg))            


class AuthLoginHandler(BaseHandler):
    def get(self):
        error_msg = self.get_argument("error", "")
        username = str(self.get_argument("username", ""))
        token = str(self.get_argument("token", ""))
        next = self.get_argument("next", "/")
        if Options['debug']:
            print >> sys.stderr, "AuthLoginHandler.get", username, token, next, error_msg
        if not error_msg and username and (token or Options['no_auth']):
            self.login(username, token, next=next)
        else:
            self.render("login.html", error_msg=error_msg, next=next, site_label=Options['site_label'],
                        login_url=Global.login_url, password='NO AUTHENTICATION' if Options['no_auth'] else 'Token:')

    def post(self):
        self.login(self.get_argument("username", ""), self.get_argument("token", ""), next=self.get_argument("next", "/"))

    def login(self, username, token, next="/"):
        if username != ADMINUSER_ID:
            if token == Options['auth_key'] or (Options['no_auth'] and Options['debug'] and not Options['gsheet_url']):
                # Auth_key token option or No authentication option for testing local-only proxy; generate token
                token = sliauth.gen_user_token(Options['auth_key'], username)
        auth = self.check_access(username, token)
        if auth:
            self.set_id(username, '', token, username)
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
                print >> sys.stderr, "GoogleAuth: step 1", user.get('token_type')

            if not user:
                self.custom_error(500, '<h2>Google authentication failed</h2><a href="/">Home</a>', clear_cookies=True)

            access_token = str(user['access_token'])
            http_client = self.get_auth_http_client()
            response =  yield http_client.fetch('https://www.googleapis.com/oauth2/v1/userinfo?access_token='+access_token)
            if not response:
                self.custom_error(500, '<h2>Google profile access failed</h2><a href="/">Home</a>', clear_cookies=True)

            user = json.loads(response.body)
            if Options['debug']:
                print >> sys.stderr, "GoogleAuth: step 2", user

            username = user['email'].lower()
            if username in Global.rename:
                # Special out-of-domain case; retain full email addr (to be translated to a name)
                pass
            else:
                if Global.login_domain:
                    if not username.endswith(Global.login_domain):
                        self.custom_error(500, '<h2>Authentication requires account '+Global.login_domain+'</h2><a href="https://mail.google.com/mail/u/0/?logout&hl=en">Logout of google (to sign in with a different account)</a><br><a href="/">Home</a>', clear_cookies=True)
                        return
                    username = username[:-len(Global.login_domain)]

                if username.startswith('_') or username in (ADMINUSER_ID, TESTUSER_ID):
                    self.custom_error(500, 'Disallowed username: '+username, clear_cookies=True)

            displayName = user.get('family_name','').replace(',', ' ')
            if displayName and user.get('given_name',''):
                displayName += ', '
            displayName += user.get('given_name','')
            if not displayName:
                displayName = username

            username, prefix = self.get_alt_name(username)
            token = Options['auth_key'] if username == ADMINUSER_ID else sliauth.gen_user_token(Options['auth_key'], username)
            self.set_id(username, user['email'], token, displayName, email=user['email'].lower(), restrict=prefix)
            self.redirect(self.get_argument("state", "") or self.get_argument("next", "/"))
            return

            # Save the user with e.g. set_secure_cookie
        else:
            yield self.authorize_redirect(
                redirect_uri=self.settings['google_oauth']['redirect_uri'],
                client_id=self.settings['google_oauth']['key'],
                scope=['profile', 'email'],
                response_type='code',
                extra_params={'approval_prompt': 'auto', 'state': self.get_argument("next", "/")})

class TwitterLoginHandler(tornado.web.RequestHandler,
                          tornado.auth.TwitterMixin, UserIdMixin):
    @tornado.gen.coroutine
    def get(self):
        if self.get_argument("oauth_token", None):
            user = yield self.get_authenticated_user()
            # Save the user using e.g. set_secure_cookie()
            if Options['debug']:
                print >> sys.stderr, "TwitterAuth: step 2 access_token =", user.get('access_token')
            username = user['username']
            if username.startswith('_') or username in (ADMINUSER_ID, TESTUSER_ID):
                self.custom_error(500, 'Disallowed username: '+username, clear_cookies=True)
            username, prefix = self.get_alt_name(username)
            displayName = user['name']
            token = Options['auth_key'] if username == ADMINUSER_ID else sliauth.gen_user_token(Options['auth_key'], username)
            self.set_id(username, user['username'], token, displayName, restrict=prefix)
            self.redirect(self.get_argument("next", "/"))
        else:
            yield self.authorize_redirect()

class PlainHTTPHandler(tornado.web.RequestHandler):
    def prepare(self):
        if self.request.protocol == 'http':
            self.redirect('https://' + self.request.host, permanent=False)

    def get(self):
        self.write("Hello, world")

class Application(tornado.web.Application):
    def __init__(self):
        handlers = [
            (r"/", HomeHandler),
            (r"/_auth/logout/", AuthLogoutHandler),
            (r"/_auth/login/", AuthLoginHandler),
            ]

        settings = {}
        Global.login_domain = ''
        Global.login_url = '/_auth/login/'
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
                          (r"/interact(/.*)?", AuthMessageHandler),
                          (r"/(_backup/[-\w.]+)", ActionHandler),
                          (r"/(_export/[-\w.]+)", ActionHandler),
                          (r"/(_lock)", ActionHandler),
                          (r"/(_lock/[-\w.]+)", ActionHandler),
                          (r"/(_unlock/[-\w.]+)", ActionHandler),
                          (r"/(_respond)", ActionHandler),
                          (r"/(_respond/[-\w.;]+)", ActionHandler),
                          (r"/(_(getcol|getrow)/[-\w.;]+)", ActionHandler),
                          (r"/(_(clear|dash|import|shutdown|status))", ActionHandler),
                           ]

        fileHandler = BaseStaticFileHandler if Options['no_auth'] else AuthStaticFileHandler

        if Options['static_dir']:
            handlers += [ (r'/([^_].*)', fileHandler, {"path": Options['static_dir']}) ]

        for path in [PLUGINDATA_PATH, PRIVATE_PATH, RESTRICTED_PATH]:
            dir = Options['plugindata_dir'] if path == PLUGINDATA_PATH else Options['static_dir']
            if dir:
                handlers += [ (r'/(%s/.*)' % path, fileHandler, {"path": dir}) ]
            
        super(Application, self).__init__(handlers, **settings)

def processTwitterMessage(msg):
    # Return null string on success or error message
    print >> sys.stderr, 'sdserver.processTwitterMessage:', msg
    fromUser = msg['sender']
    fromName = msg['name']
    message = msg['text']
    status = None
    if Options['auth_type'].startswith('twitter,'):
        status = WSHandler.processMessage(fromUser, fromName, message, source='twitter')
    else:
        idMap = sdproxy.makeRosterMap('twitter', lowercase=True)
        if not idMap:
            status = 'Error - no twitter entries in roster. Message from '+fromUser+' dropped'
        else:
            userId = idMap.get(fromUser.lower())
            if userId:
                status = WSHandler.processMessage(userId, sdproxy.lookupRoster('name', userId), message, source='twitter')
            else:
                status = 'Error - twitter ID '+fromUser+' not found in roster'
    print >> sys.stderr, 'processTwitterMessage:', status
    return status

def importAnswers():
    comps = options.import_answers.split(',')
    sessionName = comps[0]
    filepath = comps[1] if len(comps) > 1 else ''
    submitDate = comps[2] if len(comps) > 2 else ''
    if not filepath:
        filepath = sessionName+'.csv'
    print >> sys.stderr, "Importing answers from", filepath

    with open(filepath, 'rb') as csvfile:
        missed, errors = importAnswersAux(sessionName, submitDate, filepath, csvfile)

    if not missed and not errors:
        print >> sys.stderr, 'Imported answers from', filepath
    else:
        if errors:
            print >> sys.stderr, '\n'.join(errors)
        if missed:
            print >> sys.stderr, "ERROR: Missed uploading IDs: ", ' '.join(missed)

def importAnswersAux(sessionName, submitDate, filepath, csvfile):
    missed = []
    errors = []
    try:
        dialect = csv.Sniffer().sniff(csvfile.read(1024))
        csvfile.seek(0)
        reader = csv.reader(csvfile, dialect)
        headers = reader.next()
        idCol = 0
        nameCol = 0
        twitterCol = 0
        qresponse = {}
        for j, header in enumerate(headers):
            hmatch = re.match(r'^(qx?)(\d+)$', header)
            if hmatch:
                qnumber = int(hmatch.group(2))
                qresponse[qnumber] = (j, (hmatch.group(1) == 'qx'))
            elif header == 'id':
                idCol = j+1
            elif header == 'name':
                nameCol = j+1
            elif header == 'twitter':
                twitterCol = j+1

        nameMap = sdproxy.lookupRoster('name')
        idMap = {}
        if twitterCol:
            idMap = sdproxy.makeRosterMap('twitter', lowercase=True)
            if not idMap:
                raise Exception('No twitter ids found in roster')
        elif not idCol:
            raise Exception('No id or twitter column for importing answers from '+filepath)

        for row in reader:
            answers = {}
            for qnumber, value in qresponse.items():
                response = row[value[0]].strip()
                if not response:
                    continue
                explain = ''
                if value[1]:
                    comps = response.split()
                    if len(comps) > 1:
                        explain = response[len(comps[0]):].strip()
                        response = comps[0]
                answers[qnumber] = {'response': response}
                if value[1]:
                    answers[qnumber]['explain'] = explain
            userId = None
            if idCol:
                userId = row[idCol-1]
                if nameMap and userId not in nameMap:
                    missed.append(userId)
                    errors.append('MISSING: User ID '+userId+' not found in roster')
                    continue
            elif twitterCol:
                twitterId = row[twitterCol-1]
                if twitterId == TESTUSER_ID:
                    # Special case of test user; not really Twitter ID
                    userId = twitterId
                else:
                    # Map Twitter ID to user ID
                    userId = idMap.get(twitterId.lower())
                if not userId:
                    missed.append('@'+twitterId)
                    errors.append('MISSING: Twitter ID '+twitterId+' not found in roster')
                    continue

            displayName = row[nameCol-1] if nameCol else ''
            try:
                if Options['debug']:
                    print >> sys.stderr, 'DEBUG: importAnswersAux', sessionName, userId, displayName, answers
                sdproxy.importUserAnswers(sessionName, userId, displayName, answers=answers, submitDate=submitDate, source='import')
            except Exception, excp:
                errors.append('Error in import for '+userId+': '+str(excp))
                missed.append(userId)
                missed.append('... and others')
                break
    except Exception, excp:
        errors = [ 'Error in importAnswersAux: '+str(excp)] + errors

    return missed, errors

def main():
    define("config", type=str, help="Path to config file",
        callback=lambda path: parse_config_file(path, final=False))

    define("allow_replies", default=False, help="Allow replies to twitter direct messages")
    define("auth_key", default=Options["auth_key"], help="Digest authentication key for admin user")
    define("auth_type", default=Options["auth_type"], help="@example.com|google|twitter,key,secret,tuser1=suser1,...")
    define("backup", default="", help="=Backup_dir[,HH:MM] End Backup_dir with hyphen to automatically append timestamp")
    define("debug", default=False, help="Debug mode")
    define("dry_run", default=False, help="Dry run (read from Google Sheets, but do not write to it)")
    define("gsheet_url", default="", help="Google sheet URL")
    define("import_answers", default="", help="sessionName,CSV_spreadsheet_file,submitDate; with CSV file containing columns id/twitter, q1, qx2, q3, qx4, ...")
    define("no_auth", default=False, help="No authentication mode (for testing)")
    define("plugindata_dir", default=Options["plugindata_dir"], help="Path to plugin data files directory")
    define("plugins", default="", help="List of plugin paths (comma separated)")
    define("proxy_wait", type=int, help="Proxy wait time (>=0; omit argument for no proxy)")
    define("public", default=Options["public"], help="Public web site (no login required, except for _private/_restricted)")
    define("site_label", default=Options["site_label"], help="Site label for Login page")
    define("site_url", default=Options["site_url"], help="Site URL, e.g., http://example.com")
    define("ssl", default="", help="SSLcertfile,SSLkeyfile")
    define("static_dir", default=Options["static_dir"], help="Path to static files directory")
    define("twitter_stream", default="", help="Twitter stream access info: username,consumer_key,consumer_secret,access_key,access_secret")
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
        sdproxy.Options.update(AUTH_KEY=options.auth_key, SHEET_URL=options.gsheet_url, DEBUG=options.debug,
                               DRY_RUN=options.dry_run, MIN_WAIT_TIME=options.proxy_wait)

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

    if options.backup:
        comps = options.backup.split(',')
        sdproxy.Options['BACKUP_DIR'] = comps[0]
        hhmm = comps[1] if len(comps) > 1 else '03:00'
        curTimeSec = sliauth.epoch_ms()/1000.0
        curDate = sliauth.iso_date(sliauth.create_date(curTimeSec*1000.0))[:10]
        if hhmm:
            backupTimeSec = sliauth.epoch_ms(sliauth.parse_date(curDate+'T'+hhmm))/1000.0
        else:
            backupTimeSec = curTimeSec + 31
        backupInterval = 86400
        if backupTimeSec - curTimeSec < 30:
            backupTimeSec += backupInterval
        print >> sys.stderr, 'Scheduled backup in dir %s every %s hours, starting at %s' % (comps[0], backupInterval/3600, sliauth.iso_date(sliauth.create_date(backupTimeSec*1000.0)))
        def start_backup():
            if Options['debug']:
                print >> sys.stderr, "Starting periodic backup"
            sdproxy.backupCache()
            Global.backup = PeriodicCallback(sdproxy.backupCache, backupInterval*1000.0)
            Global.backup.start()
        
        IOLoop.current().call_at(backupTimeSec, start_backup)

    if options.twitter_stream:
        comps = options.twitter_stream.split(',')
        Global.twitter_config = {
            'screen_name': comps[0],
            'consumer_token': {'consumer_key': comps[1], 'consumer_secret': comps[2]},
            'access_token': {'key': comps[3], 'secret': comps[4]}
            }

        import sdstream
        twitterStream = sdstream.TwitterStreamReader(Global.twitter_config, processTwitterMessage,
                                                     allow_replies=options.allow_replies)
        twitterStream.start_stream()

    if options.port != 443:
        http_server = tornado.httpserver.HTTPServer(Application())
    elif options.ssl:
        certfile, keyfile = options.ssl.split(',')
        ssl_options = {"certfile": certfile, "keyfile": keyfile}
        http_server = tornado.httpserver.HTTPServer(Application(), ssl_options=ssl_options)

        # Redirect plain HTTP to HTTPS
        handlers = [ (r'/', PlainHTTPHandler) ]
        plain_http_app = tornado.web.Application(handlers)
        plain_http_app.listen(80)
        print >> sys.stderr, "Listening on HTTP port"
    else:
        sys.exit('SSL options must be specified for port 443')
    http_server.listen(options.port)
    print >> sys.stderr, "Listening on port", options.port
    if options.import_answers:
        IOLoop.current().add_callback(importAnswers)
    IOLoop.current().start()


if __name__ == "__main__":
    main()
