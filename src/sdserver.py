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
    private_port: Base port number for private servers
    public: Public web site (no login required, except for paths containing _private/_restricted)
    proxy: Enable proxy mode (cache copies of Google Sheets)
    sites: Site names, e.g., 'chem101,math101,...'
    site_label: Site label, e.g., 'MATH101'
    static_dir: path to static files directory containing Slidoc html files (default='static')
    xsrf: Enable XSRF cookies for security

    For Twitter auth workflow, see sdstream.py

"""

import base64
import cStringIO
import csv
import datetime
import functools
import importlib
import json
import logging
import math
import random
import os.path
import re
import socket
import sys
import time
import urllib
import uuid

from collections import defaultdict, OrderedDict

import tornado.auth
import tornado.autoreload
import tornado.gen
import tornado.escape
import tornado.httpserver
import tornado.netutil
import tornado.options
import tornado.web
import tornado.websocket

from tornado.options import define, options, parse_config_file, parse_command_line
from tornado.ioloop import IOLoop, PeriodicCallback

import sdproxy
import sliauth
import plugins

scriptdir = os.path.dirname(os.path.realpath(__file__))

Options = {
    '_index_html': '',  # Non-command line option
    'auth_key': '',
    'auth_type': '',
    'debug': False,
    'dry_run': False,
    'freeze_date': '',    # Date when all user mods are disabled
    'gsheet_url': '',
    'lock_proxy_url': '',
    'no_auth': False,
    'plugindata_dir': 'plugindata',
    'port': 8888,
    'private_port': 8900,
    'proxy_wait': None,
    'public': False,
    'release_required': r'(exam|quiz|test)',
    'reload': False,
    'require_login_token': True,
    'require_late_token': True,
    'root_key': None,
    'server_url': '',
    'share_averages': True,
    'site_label': 'Slidoc',
    'site_name': '',
    'site_number': 0,
    'sites': [],
    'static_dir': 'static',
    'twitter_stream': '',
    'xsrf': False,
    }

class Dummy():
    pass
    
Global = Dummy()
Global.rename = {}
Global.backup = None
Global.twitter_config = {}
Global.relay_list = []

FUTURE_DATE = 'future'

PLUGINDATA_PATH = '_plugindata'
PRIVATE_PATH    = '_private'
RESTRICTED_PATH = '_restricted'

ADMIN_PATH = 'admin'

ADMINUSER_ID = 'admin'
TESTUSER_ID = '_test_user'
    
USER_COOKIE_SECURE = "slidoc_user_secure"
SERVER_COOKIE = "slidoc_server"
EXPIRES_DAYS = 30
BATCH_AGE = 60      # Age of batch cookies (sec)

WS_TIMEOUT_SEC = 3600
EVENT_BUFFER_SEC = 3

SETTINGS_SHEET = 'settings_slidoc'
SCORES_SHEET = 'scores_slidoc'

LATE_SUBMIT = 'late'
PARTIAL_SUBMIT = 'partial'

class UserIdMixin(object):
    @classmethod
    def get_path_base(cls, path, sessions_only=True):
        # Extract basename, without file extension, from URL path
        # If sessions_only, return None if not html file or is index.html
        if sessions_only and not path.endswith('.html'):
            return None
        basename = path.split('/')[-1]
        if '.' in basename:
            basename, sep, suffix = basename.rpartition('.')
        if sessions_only and basename == 'index':
            return None
        return basename

    def set_id(self, username, origId='', token='', displayName='', email='', altid='', prefix='', data={}):
        if Options['debug']:
            print >> sys.stderr, 'sdserver.UserIdMixin.set_id', username, origId, token, displayName, email, altid, prefix, data

        if ':' in username or ':' in origId or ':' in token or ':' in displayName:
            raise Exception('Colon character not allowed in username/origId/token/name')
        if username == ADMINUSER_ID:
            tokenList = [token, sliauth.gen_user_token(str(token), TESTUSER_ID)]
            if origId and origId != username:
                tokenList.append(sliauth.gen_user_token(str(token), origId))
            token = ','.join(tokenList)
        cookieStr = ':'.join( sliauth.safe_quote(x) for x in [username, origId, token, displayName, email, altid, prefix, base64.b64encode(json.dumps(data))] )
        if data.get('batch'):
            self.set_secure_cookie(USER_COOKIE_SECURE, cookieStr, max_age=BATCH_AGE)
            self.set_cookie(SERVER_COOKIE, cookieStr, max_age=BATCH_AGE)
        else:
            self.set_secure_cookie(USER_COOKIE_SECURE, cookieStr, expires_days=EXPIRES_DAYS)
            self.set_cookie(SERVER_COOKIE, cookieStr, expires_days=EXPIRES_DAYS)

    def clear_id(self):
        self.clear_cookie(USER_COOKIE_SECURE)
        self.clear_cookie(SERVER_COOKIE)

    def get_alt_name(self, username):
        if username in Global.rename:
            alt_name, _, session_prefix = Global.rename[username].partition(':')
            # Alt name may be followed by an option session name prefix for which the altname is admin, e.g., dummy:assignments
            return alt_name, session_prefix
        return username, ''

    def check_access(self, username, token):
        if username == ADMINUSER_ID:
            return token == Options['auth_key']
        else:
            return token == sliauth.gen_user_token(Options['auth_key'], username)

    def get_id_from_cookie(self, orig=False, name=False, email=False, altid=False, prefix=False, data=False):
        # Ensure SERVER_COOKIE is also set before retrieving id from secure cookie (in case one of them gets deleted)
        if options.insecure_cookie:
            cookieStr = self.get_cookie(SERVER_COOKIE)
        else:
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
            if data:
                return json.loads(base64.b64decode(comps[7])) if len(comps) > 7 else {}
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

    def write_error(self, status_code, **kwargs):
        err_cls, err, traceback = kwargs['exc_info']
        if getattr(err, 'log_message', None) and err.log_message.startswith('CUSTOM:'):
            self.write('<html><body><h3>%s</h3></body></html>' % err.log_message[len('CUSTOM:'):])
        else:
            super(BaseHandler, self).write_error(status_code, **kwargs)
    

class HomeHandler(BaseHandler):
    def get(self):
        if Options['sites'] and not Options['site_number']:
            html = '<div style="font-family: sans-serif;"><h3>Select site:</h3><ul>\n'
            for site in Options['sites']:
                html += '''<li><a href="/%s" style="text-decoration: none;"><b>%s</b></a></li>\n''' % (site, site)
            html += '</ul></div>\n'
            self.write(html)
            return
        elif Options.get('_index_html'):
            # Not authenticated
            self.write(Options['_index_html'])
        else:
            # Authenticated by static file handler, if need be
            self.redirect("/"+Options['site_name']+"/index.html" if Options['site_number'] else "/index.html")


class ActionHandler(BaseHandler):
    def get(self, subpath, inner=None):
        if Options['debug']:
            print >> sys.stderr, 'DEBUG: getAction', self.get_current_user(), Options['site_number'], subpath
        if subpath == '_logout':
            self.clear_id()
            self.render('logout.html')
            return
        root = str(self.get_argument("root", ""))
        token = str(self.get_argument("token", ""))
        if root == Options['root_key'] or token == Options['auth_key'] or (self.get_current_user() in (ADMINUSER_ID, TESTUSER_ID) and not self.get_id_from_cookie(prefix=True)):
            try:
                return self.getAction(subpath)
            except Exception, excp:
                msg = str(excp)
                if msg.startswith('CUSTOM:') and not Options['debug']:
                    print >> sys.stderr, 'sdserver: '+msg
                    self.custom_error(500, '<html><body><h3>%s</h3></body></html>' % msg[len('CUSTOM:'):])
                    return
                else:
                    raise
        raise tornado.web.HTTPError(403)

    def post(self, subpath, inner=None):
        if self.get_current_user() in (ADMINUSER_ID, TESTUSER_ID) and not self.get_id_from_cookie(prefix=True):
            return self.postAction(subpath)
        raise tornado.web.HTTPError(403)

    def getAction(self, subpath):
        action, sep, sessionName = subpath.partition('/')
        site_label = Options['site_label'] or 'Home'
        if Options['site_number']:
            # Secondary server
            root = str(self.get_argument("root", ""))
            if action in ('_update', '_reload'):
                raise tornado.web.HTTPError(403)
            elif action == '_shutdown' and root != Options['root_key']:
                raise tornado.web.HTTPError(403)
        elif Options['sites']:
            # Primary server
            if action not in ('_backup', '_update', '_reload', '_shutdown'):
                raise tornado.web.HTTPError(403)
            
        if action not in ('_dash', '_sessions', '_roster', '_twitter', '_cache', '_freeze', '_clear', '_backup', '_update', '_reload', '_shutdown', '_lock'):
            if not sessionName:
                self.write('<a href="/_dash">Dashboard</a><p></p>')
                self.write('Please specify /%s/session name' % action)
                return
        if action == '_dash':
            self.render('dashboard.html', site_label=site_label, version=sdproxy.VERSION, suspended=sdproxy.Global.suspended, interactive=WSHandler.getInteractiveSession())

        elif action == '_sessions':
            colNames = ['dueDate', 'gradeDate']
            sessionParamList = sdproxy.lookupSessions(colNames)
            self.write('<a href="/_dash">Dashboard</a><p></p>')
            self.write('<h3>Sessions</h3><p></p><table><tr>\n')
            self.write('<th>Manage</th>\n')
            self.write('<th>Session</th>\n')
            for colName in colNames:
                self.write('<th>%s</th>' % colName)
            self.write('</tr>\n')
            for sessionId, sessionParams in sessionParamList:
                self.write('<td><a href="/_manage/%s" style="text-decoration: none;">&#9881;</a></td>' % sessionId)
                self.write('<td><a href="/_sheet/%s">%s</a></td>' % (sessionId, sessionId))
                for value in sessionParams:
                    self.write('<td>%s</td>' % value)
                self.write('</tr>\n')
            self.write('</table>\n')

        elif action in ('_roster'):
            nameMap = sdproxy.lookupRoster('name', userId=None)
            if not nameMap:
                self.render('roster.html', site_label=site_label)
            else:
                for idVal, name in nameMap.items():
                    if name.startswith('#'):
                        del nameMap[idVal]
                lastMap = sdproxy.makeShortNames(nameMap)
                firstMap = sdproxy.makeShortNames(nameMap, first=True)
                self.write('<a href="/_dash">Dashboard</a><p></p>')
                self.write('Roster: \n')
                for nMap in [nameMap, lastMap, firstMap]:
                    vals = nMap.values()
                    vals.sort()
                    lines = ['<hr><table>\n']
                    for val in vals:
                        lines.append('<tr><td>%s</td></tr>\n' % val)
                    lines += ['</table>\n']
                    self.write(''.join(lines))

        elif action == '_cache':
            self.write('<h2>Proxy cache and connection status</h2>')
            self.write('<a href="/_dash">Dashboard</a><br>')
            self.write('<pre>')
            self.write(sdproxy.getCacheStatus())
            curTime = time.time()
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

        elif action == '_twitter':
            self.set_header('Content-Type', 'text/plain')
            if not twitterStream:
                self.write('No twitter stream active')
            else:
                self.write('Twitter stream status: '+twitterStream.status+'\n\n')
                self.write('Twitter stream log: '+'\n'.join(twitterStream.log_buffer)+'\n')

        elif action == '_freeze':
            sdproxy.freezeCache(fill=True)
            self.write('Freezing cache<br><a href="/_dash">Dashboard</a>')

        elif action == '_clear':
            sdproxy.suspend_cache('clear')
            self.write('Clearing cache<br><a href="/_dash">Dashboard</a>')

        elif action == '_backup':
            backupSite(sessionName) # sessionName is actually directory name

        elif action in ('_reload', '_update'):
            if not Options['reload']:
                self.write('Please restart server with --reload option<p></p><a href="/_dash">Dashboard</a>')
            else:
                if Global.backup:
                    Global.backup.stop()
                    Global.backup = None
                sdproxy.suspend_cache(action[1:])
                self.write('Starting %s<p></p><a href="/_dash">Dashboard</a>' % action[1:])

        elif action == '_shutdown':
            self.clear_id()
            self.write('Starting shutdown (also cleared cookies)<p></p><a href="/_dash">Dashboard</a>')
            if Options['sites'] and not Options['site_number']:
                # Primary server
                shutdown_all()
            else:
                if Global.backup:
                    Global.backup.stop()
                    Global.backup = None
                sdproxy.suspend_cache('shutdown')

        elif action == '_lock':
            lockType = self.get_argument('type','')
            if sessionName:
                prefix = 'Locked'
                locked = sdproxy.lockSheet(sessionName, lockType or 'user')
                if not locked:
                    if lockType == 'proxy':
                        raise Exception('Failed to lock sheet '+sessionName+'. Try again after a few seconds?')
                    prefix = 'Locking'
            self.write(prefix +' sessions: %s<p></p><a href="/_cache">Cache status</a><p></p><a href="/_dash">Dashboard</a>' % (', '.join(sdproxy.get_locked())) )

        elif action == '_unlock':
            if not sdproxy.unlockSheet(sessionName):
                raise Exception('Failed to unlock sheet '+sessionName)
            self.write('Unlocked '+sessionName+'<p></p><a href="/_cache">Cache status</a><p></p><a href="/_dash">Dashboard</a>')

        elif action in ('_manage'):
            sheet = sdproxy.getSheet(sessionName, optional=True)
            if not sheet:
                self.write('<a href="/_dash">Dashboard</a><p></p>')
                self.write('No such session: '+sessionName)
                return
            self.render('manage.html', site_label=site_label, session=sessionName)

        elif action == '_export':
            self.set_header('Content-Type', 'text/csv')
            self.set_header('Content-Disposition', 'attachment; filename="%s.csv"' % (sessionName+'_answers'))
            content = sdproxy.exportAnswers(sessionName)
            self.write(content)

        elif action in ('_sheet'):
            sheet = sdproxy.getSheet(sessionName, optional=True)
            if not sheet:
                self.write('Unable to retrieve sheet '+sessionName)
                return
            self.render('table.html', table_name=sessionName, table_data=sheet.getRows(), table_fixed='fixed')

        elif action in ('_getcol', '_getrow'):
            sessionName, sep, label = sessionName.partition(';')
            sheet = sdproxy.getSheet(sessionName, optional=True)
            if not sheet:
                self.write('Unable to retrieve session '+sessionName)
            else:
                self.write('<a href="/_dash">Dashboard</a><br>')
                if label.isdigit():
                    labelNum = int(label)
                elif len(label) == 1:
                    labelNum = ord(label) - ord('A') + 1
                else:
                    colIndex = sdproxy.indexColumns(sheet)
                    if action == '_getcol':
                        labelNum = colIndex.get(label, 0) if label else colIndex['id']
                    else:
                        labelNum = sdproxy.indexRows(sheet, colIndex['id'], 2).get(label, 0) if label else 1
                if action == '_getcol':
                    if labelNum < 1 or labelNum > sheet.getLastColumn():
                        self.write('Column '+label+' not found in cached session '+sessionName)
                    elif not label or label == 'id':
                        self.write('<pre>'+'\n'.join('<a href="/_getrow/%s;%s">%s</a>' % (sessionName, x[0], x[0]) for x in sheet.getSheetValues(1, labelNum, sheet.getLastRow(), 1))+'</pre>')
                    else:
                        self.write('<pre>'+'\n'.join(str(x) for x in json.loads(json.dumps([x[0] for x in sheet.getSheetValues(1, labelNum, sheet.getLastRow(), 1)], default=sliauth.json_default)))+'</pre>')
                else:
                    if labelNum < 1 or labelNum > sheet.getLastRow():
                        self.write('Row '+label+' not found in cached session '+sessionName)
                    else:
                        headerVals = sheet.getSheetValues(1, 1, 1, sheet.getLastColumn())[0]
                        if not label or labelNum == 1:
                            self.write('<pre>'+'\n'.join(['<a href="/_getcol/%s;%s">%s</a>' % (sessionName, headerVals[j], headerVals[j]) for j in range(len(headerVals))]) +'</pre>')
                        else:
                            rowVals = sheet.getSheetValues(labelNum, 1, 1, sheet.getLastColumn())[0]
                            self.write('<pre>'+'\n'.join(headerVals[j]+':\t'+str(json.loads(json.dumps(rowVals[j], default=sliauth.json_default))) for j in range(len(headerVals))) +'</pre>')

        elif action == '_delete':
            user = 'admin'
            userToken = sliauth.gen_admin_token(Options['auth_key'], user)
            args = {'sheet': sessionName, 'delsheet': '1', 'admin': user, 'token': userToken}
            retObj = sdproxy.sheetAction(args)
            self.write('<a href="/_dash">Dashboard</a><p></p>')
            if retObj['result'] == 'success':
                self.write('Deleted session '+sessionName)
            else:
                self.write('Error in deleting session '+sessionName+': '+retObj.get('error',''))

        elif action == '_import':
            self.render('import.html', site_label=site_label, session=sessionName, submit_date=sliauth.iso_date())

        elif action == '_prefill':
            nameMap = sdproxy.lookupRoster('name')
            count = 0
            for userId, name in nameMap.items():
                if not name or name.startswith('#'):
                    continue
                count += 1
                sdproxy.importUserAnswers(sessionName, userId, name, source='prefill')
            self.write('Prefilled session '+sessionName+' with '+str(count)+' users')

        elif action in ('_qstats'):
            sheetName = sessionName + '-answers'
            sheet = sdproxy.getSheet(sheetName, optional=True)
            if not sheet:
                self.write('Unable to retrieve sheet '+sheetName)
                return
            qrows = sheet.getSheetValues(1, 1, 2, sheet.getLastColumn())
            qaverages = []
            for j, header in enumerate(qrows[0]):
                qmatch = re.match(r'^q(\d+)_score', header)
                if qmatch:
                    qaverages.append([float(qrows[1][j]), int(qmatch.group(1))])
            qaverages.sort()
            lines = []
            for j, qavg in enumerate(qaverages):
                lines.append('Q%02d: %2d%%' % (qavg[1], int(qavg[0]*100)) )
                if j%5 == 4:
                    lines.append('')
            self.write('<a href="/_dash">Dashboard</a><br>')
            self.write(('<h3>%s: percentage of correct answers</h3>\n' % sessionName) + '<pre>\n'+'\n'.join(lines)+'\n</pre>\n')

        elif action == '_refresh':
            if sessionName:
                if sdproxy.refreshSheet(sessionName):
                    msg = ' Refreshed session '+sessionName
                else:
                    msg = ' Cannot refresh locked session '+sessionName+' ...'
                self.write(msg+'<p></p><a href="/_cache">Cache status</a><p></p><a href="/_dash">Dashboard</a>')

        elif action in ('_respond'):
            sessionName, sep, respId = sessionName.partition(';')
            self.write('<a href="/_dash">Dashboard</a><p></p>')
            if not sessionName:
                self.write('Please specify /_respond/session name')
                return
            sheet = sdproxy.getSheet(sessionName, optional=True)
            if not sheet:
                self.write('Unable to retrieve session '+sessionName)
                return
            nameMap = sdproxy.lookupRoster('name')
            if respId:
                if respId in nameMap:
                    sdproxy.importUserAnswers(sessionName, respId, nameMap[respId], source='manual', submitDate='dueDate')
                else:
                    self.write('User ID '+respId+' not in roster')
                    return
            colIndex = sdproxy.indexColumns(sheet)
            idSet = set([x[0] for x in sheet.getSheetValues(1, colIndex['id'], sheet.getLastRow(), 1)])
            lines = ['<ul style="font-family: sans-serif;">\n']
            count = 0
            for idVal, name in nameMap.items():
                if idVal in idSet:
                    count += 1
                    lines.append('<li>'+name+'</li>\n')
                else:
                    lines.append('<li>%s (<a href="/_respond/%s;%s">set responded</a>)</li>\n' % (name, sessionName, idVal))
            lines.append('</ul>\n')
            self.write(('Responders to session %s (%d/%d):' % (sessionName, count, len(nameMap)))+''.join(lines))

        elif action in ('_submissions'):
            comps = sessionName.split(';')
            sessionName = comps[0]
            userId = comps[1] if len(comps) >= 2 else ''
            dateStr = comps[2] if len(comps) >= 3 else ''
            sheet = sdproxy.getSheet(sessionName, optional=True)
            if not sheet:
                self.write('Unable to retrieve session '+sessionName)
                return
            sessionConnections = WSHandler.get_connections(sessionName)
            nameMap = sdproxy.lookupRoster('name')
            if userId:
                if not dateStr:
                    self.write('Please specify date')
                    return
                if 'T' not in dateStr:
                    dateStr += 'T23:59'
                if userId in nameMap:
                    # Close any active connections associated with user for session
                    for connection in sessionConnections.get(userId, []):
                        connection.close()
                    newLatetoken = sliauth.gen_late_token(Options['auth_key'], userId, sessionName, dateStr)
                    sdproxy.createUserRow(sessionName, userId, lateToken=newLatetoken, source='allow')
                else:
                    self.write('User ID '+userId+' not in roster')
                    return
            colIndex = sdproxy.indexColumns(sheet)
            idVals = sheet.getSheetValues(1, colIndex['id'], sheet.getLastRow(), 1)
            lastSlides = sheet.getSheetValues(1, colIndex['lastSlide'], sheet.getLastRow(), 1)
            submitTimes = sheet.getSheetValues(1, colIndex['submitTimestamp'], sheet.getLastRow(), 1)
            lateTokens = sheet.getSheetValues(1, colIndex['lateToken'], sheet.getLastRow(), 1)
            userMap = {}
            for j in range(len(idVals)):
                userMap[idVals[j][0]] = (lastSlides[j][0], submitTimes[j][0], lateTokens[j][0])
            lines = ['<ul>\n']
            for idVal, name in nameMap.items():
                labels = []
                if idVal in userMap:
                    lastSlide, submitTime, lateToken = userMap[idVal]
                else:
                    lastSlide, submitTime, lateToken = 0, '', ''

                if submitTime:
                    labels.append('(<em>submitted '+submitTime.ctime()+'</em>)')
                else:
                    if lastSlide:
                        labels.append('<code>#%s</code>' % lastSlide)
                    if sessionConnections.get(idVal, []):
                        labels.append('<em>connected</em>')
                    if lateToken:
                        labels.append('<em>token=%s</em>' % lateToken[:16])
                    labels.append('''(<a href="javascript:submit('session','%s;%s')">allow late</a>)''' % (sessionName, idVal) )
                lines.append('<li>%s %s</li>\n' % (name, ' '.join(labels)))

            lines.append('</ul>\n')
            self.render('submissions.html', site_label=site_label, submissions_label='Late submission',
                         submissions_html=('Status of session '+sessionName+':<p></p>'+''.join(lines)) )

        elif action == '_submit':
            self.render('submit.html', site_label=site_label, session=sessionName)

    def postAction(self, subpath):
        action, sep, sessionName = subpath.partition('/')
        submitDate = ''
        if action in ('_import', '_submit'):
            if not sessionName:
                self.write('Must specify session name')
                return
            submitDate = self.get_argument('submitdate','')
        if action in ('_roster', '_import', '_submit'):
            self.set_header('Content-Type', 'text/plain')
            if action == '_submit':
                # Submit test user
                try:
                    sdproxy.importUserAnswers(sessionName, TESTUSER_ID, '', submitDate=submitDate, source='submit')
                    self.write('Submit '+TESTUSER_ID+' row')
                except Exception, excp:
                    self.write('Error in submit for '+TESTUSER_ID+': '+str(excp))

            elif action in ('_roster', '_import'):
                # Import from CSV file
                if 'upload' not in self.request.files:
                    self.write('No file to upload!')
                    return
                fileinfo = self.request.files['upload'][0]
                fname = fileinfo['filename']
                fbody = fileinfo['body']
                if Options['debug']:
                    print >> sys.stderr, 'ActionHandler:upload', fname, len(fbody), sessionName, submitDate
                uploadedFile = cStringIO.StringIO(fbody)
                if action == '_roster':
                    errors = importRosterAux(fname, uploadedFile)
                    if not errors:
                        self.write('Imported roster from '+fname)
                    else:
                        if errors:
                            self.write('\n'.join(errors)+'\n')
                elif action == '_import':
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

class AuthActionHandler(ActionHandler):
    @tornado.web.authenticated
    def get(self, subpath, inner=None):
        if self.get_current_user() in (ADMINUSER_ID, TESTUSER_ID):
            return self.getAction(subpath)
        raise tornado.web.HTTPError(403)

class ProxyHandler(BaseHandler):
    @tornado.gen.coroutine
    def get(self):
        yield self.handleResponse()

    @tornado.gen.coroutine
    def post(self):
        yield self.handleResponse()

    @tornado.gen.coroutine
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

        if (args.get('action') or args.get('modify')) and sdproxy.Settings['gsheet_url'] and not sdproxy.Settings['dry_run']:
            sessionName = args.get('sheet','')
            errMsg = ''
            if args.get('modify'):
                if not sdproxy.startPassthru(sessionName):
                    errMsg = 'Failed to lock sheet '+sessionName+' for passthru. Try again after a few seconds?'

            if errMsg:
                retObj = {'result': 'error', 'error': errMsg}
            else:
                http_client = tornado.httpclient.AsyncHTTPClient()
                body = urllib.urlencode(args)
                response = yield http_client.fetch(sdproxy.Settings['gsheet_url'], method='POST', headers=None, body=body)
                if response.error:
                    retObj = {'result': 'error', 'error': 'Error in passthru: '+str(response.error) }
                else:
                    # Successful return
                    if args.get('modify'):
                        sdproxy.endPassthru(sessionName)
                    elif args.get('action'):
                        # Clear cached sheets
                        if args.get('action') == 'scores':
                            sdproxy.refreshSheet(SCORES_SHEET)
                        elif sessionName:
                            sdproxy.refreshSheet(sessionName+'-'+args.get('action'))
                        else:
                            for name in sdproxy.Sheet_cache:
                                if name.endswith('-'+action):
                                    sdproxy.refreshSheet(name)
                    try:
                        retObj = json.loads(response.body)
                    except Exception, err:
                        retObj = {'result': 'error', 'error': 'passthru: JSON parsing error: '+str(err) }
        else:
            retObj = sdproxy.sheetAction(args)

        self.set_header('Content-Type', mimeType)
        self.write(jsonPrefix+json.dumps(retObj, default=sliauth.json_default)+jsonSuffix)


class WSHandler(tornado.websocket.WebSocketHandler, UserIdMixin):
    _connections = defaultdict(functools.partial(defaultdict,list))
    _interactiveSession = (None, None, None)
    _interactiveErrors = {}
    @classmethod
    def get_connections(cls, sessionName=''):
        # Return dict((user, connections_list)) if sessionName
        # else return list of tuples [ (path, user, connections) ]
        lst = []
        for path, path_dict in cls._connections.items():
            if sessionName:
                if cls.get_path_base(path) == sessionName:
                    return path_dict
            else:
                for user, connections in path_dict.items():
                    lst.append( (path, user, connections) )
        if sessionName:
            return {}
        else:
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
    def closeConnections(cls, path, userIdList, excludeId=None):
        sessionConnections = cls._connections[path]
        for userId in userIdList:
            if excludeId and userId == excludeId:
                continue
            if Options['debug']:
                print >> sys.stderr, "DEBUG: sdserver.closeConnections", 'Closing connections for user:', userId
            for connection in sessionConnections.get(userId,[]):
                connection.close()

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

        teamModifiedIds = retval.get('info', {}).get('teamModifiedIds')
        if teamModifiedIds:
            # Close all connections for the team
            cls.closeConnections(sessionName, teamModifiedIds)

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
            print >> sys.stderr, "DEBUG: WSon_close", getattr(self, 'pathUser', 'NOT OPENED')
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

                teamModifiedIds = retObj.get('info', {}).get('teamModifiedIds')
                if teamModifiedIds:
                    # Close other connections for the same team
                    self.closeConnections(self.pathUser[0], teamModifiedIds, excludeId=self.userId)

            elif method == 'interact':
                if self.userId == ADMINUSER_ID:
                    self.setupInteractive(self.pathUser[0], args[0], args[1])

            elif method == 'plugin':
                if len(args) < 2:
                    raise Exception('Too few arguments to invoke plugin method: '+' '.join(args))
                pluginName, pluginMethodName = args[:2]
                pluginMethod = self.getPluginMethod(pluginName, pluginMethodName)

                params = {'pastDue': ''}
                sessionName = self.get_path_base(self.pathUser[0], sessions_only=True)
                userId = self.pathUser[1]
                if sessionName and sdproxy.getSheet(sdproxy.INDEX_SHEET, optional=True):
                    sessionEntries = sdproxy.lookupValues(sessionName, ['dueDate'], sdproxy.INDEX_SHEET)
                    if sessionEntries['dueDate']:
                        # Check if past due date
                        try:
                            userEntries = sdproxy.lookupValues(userId, ['lateToken'], sessionName)
                            effectiveDueDate = userEntries['lateToken'] or sessionEntries['dueDate']
                        except Exception, excp:
                            print >> sys.stderr, 'sdserver.on_message_aux', str(excp)
                            effectiveDueDate = sessionEntries['dueDate']
                        if isinstance(effectiveDueDate, datetime.datetime):
                            if sliauth.epoch_ms() > sliauth.epoch_ms(effectiveDueDate):
                                params['pastDue'] = sliauth.iso_date(effectiveDueDate)
                        elif effectiveDueDate:
                            # late/partial; use late submission option
                            params['pastDue'] = str(effectiveDueDate)
                
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
                    retObj = pluginMethod(*([params] + args[2:]))
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
        if ':' not in key and '%' in key:
            key = sliauth.safe_unquote(key)
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

    def dirFiles(self, dirpath, restricted=True, private=True):
        # Returns list of [filepath, /url] in directory
        fullpath = self.makePath(dirpath, restricted=restricted, private=private)
        if not os.path.exists(fullpath):
            return []
        try:
            fpaths = [os.path.join(fullpath, f) for f in os.listdir(fullpath) if os.path.isfile(os.path.join(fullpath, f))]
            return [ [fpath, fpath[len(Options['plugindata_dir']):]] for fpath in fpaths]
        except Exception, err:
            raise Exception('sdserver.PluginManager.dirFiles: ERROR in directory listing %s: %s' % (fullpath, err))

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
    
    def write_error(self, status_code, **kwargs):
        err_cls, err, traceback = kwargs['exc_info']
        if getattr(err, 'log_message', None) and err.log_message.startswith('CUSTOM:'):
            self.write('<html><body><h3>%s</h3></body></html>' % err.log_message[len('CUSTOM:'):])
        else:
            super(BaseStaticFileHandler, self).write_error(status_code, **kwargs)

class AuthStaticFileHandler(BaseStaticFileHandler, UserIdMixin):
    def get_current_user(self):
        # Return None only to request login; else raise HTTPError do deny access (to avoid looping)
        userId = self.get_id_from_cookie() or None
        if Options['debug']:
            print >> sys.stderr, "AuthStaticFileHandler.get_current_user", Options['site_number'], self.request.path, self.request.query, userId, Options['dry_run'], Options['lock_proxy_url']

        if Options['server_url'] == 'http://localhost' or Options['server_url'].startswith('http://localhost:'):
            # Batch auto login for localhost through query parameter: ?auth=userId:token
            query = self.request.query
            if query.startswith('auth='):
                qauth = query[len('auth='):]
                userId, token = qauth.split(':')
                if token == Options['auth_key']:
                    data = {'batch':1}
                elif token == sliauth.gen_user_token(Options['auth_key'], userId):
                    data = {}
                else:
                    raise tornado.web.HTTPError(404)
                name = sdproxy.lookupRoster('name', userId) or ''
                print >> sys.stderr, "AuthStaticFileHandler.get_current_user: BATCH ACCESS", self.request.path, userId, name
                self.set_id(userId, userId, token, name, data=data)

        if self.request.path.startswith('/'+ADMIN_PATH):
            # Admin path accessible only to dry_run (draft/preview) or wet run using proxy_url
            if not Options['dry_run'] and not Options['lock_proxy_url']:
                raise tornado.web.HTTPError(404)

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
            elif self.get_path_base(self.request.path, sessions_only=False).endswith('-'+userId) or userId == ADMINUSER_ID:
                return userId
            raise tornado.web.HTTPError(404)

        elif ('/'+PRIVATE_PATH) in self.request.path:
            # Paths containing '/_private' are always protected
            errMsg = ''
            sessionName = self.get_path_base(self.request.path, sessions_only=True)
            if sessionName and sessionName != 'index':
                releaseDate = None
                indexSheet = sdproxy.getSheet(sdproxy.INDEX_SHEET, optional=True)
                if indexSheet:
                    sessionEntries = sdproxy.lookupValues(sessionName, ['releaseDate'], sdproxy.INDEX_SHEET)
                    releaseDate = sessionEntries['releaseDate']
                if Options['release_required']:
                    # Failsafe: ensure assessment sessions always have a release date specified
                    match = re.search(Options['release_required'], sessionName, re.IGNORECASE)
                    if match and not releaseDate:
                        errMsg = '--release_date must be specified for assessment session '+sessionName
                
                if releaseDate and not errMsg and not Options['dry_run'] and userId not in (ADMINUSER_ID, TESTUSER_ID):
                    # Check release date for session (admin/test user always has access, allowing delayed release of live lectures and exams)
                    if isinstance(releaseDate, datetime.datetime):
                        if sliauth.epoch_ms() < sliauth.epoch_ms(sessionEntries['releaseDate']):
                            errMsg = 'Session %s not yet available' % sessionName
                    else:
                        # Future release date
                        errMsg = 'Session %s unavailable' % sessionName
            if errMsg:
                print >> sys.stderr, "AuthStaticFileHandler.get_current_user", errMsg
                raise tornado.web.HTTPError(404, log_message=errMsg)
            sessionPrefix = self.get_id_from_cookie(prefix=True)
            if not sessionPrefix or not userId:
                return userId

            # Handle restricted admin access for domain example.com:
            # --auth_type='@example.com,...,owner=admin,grader@gmail.com=grader:assignments|tests,tester@gmail.com=dummy'
            # owner@example.com has complete admin access, grader@gmail.com has admin access to _private/(assignments|tests)/*, tester has no admin access
            # owner can test as special user _test_user
            # grader and dummy should be added to roster, with last names starting with hash (#) to exclude from stats
            head, _, tail = self.request.path.partition('/'+PRIVATE_PATH+'/')
            if re.match(r'^('+sessionPrefix+')', tail):
                # Admin access allowed for this session prefix
                if userId != ADMINUSER_ID:
                    # Switch to admin user
                    userId = ADMINUSER_ID
                    self.set_id(ADMINUSER_ID, self.get_id_from_cookie(orig=True), Options['auth_key'], self.get_id_from_cookie(name=True), email=self.get_id_from_cookie(email=True), prefix=sessionPrefix)
            elif userId == ADMINUSER_ID:
                # Switch to regular user
                userId = self.get_id_from_cookie(orig=True)
                self.set_id(userId, userId, sliauth.gen_user_token(Options['auth_key'], userId), self.get_id_from_cookie(name=True), email=self.get_id_from_cookie(email=True), prefix=sessionPrefix)
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
            data = {}
            if Global.twitter_config:
                data['site_twitter'] = Global.twitter_config['screen_name']
            self.set_id(username, '', token, username, data=data)
            self.redirect(next)
        else:
            error_msg = "?error=" + tornado.escape.url_escape("Incorrect username or token")
            self.redirect("/_auth/login/" + error_msg)

            
class AuthLogoutHandler(BaseHandler):
    def get(self):
        self.clear_id()
        self.render('logout.html')

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

            mapname, prefix = self.get_alt_name(username)
            token = Options['auth_key'] if mapname == ADMINUSER_ID else sliauth.gen_user_token(Options['auth_key'], mapname)
            data = {}
            if Global.twitter_config:
                data['site_twitter'] = Global.twitter_config['screen_name']
            self.set_id(mapname, mapname if prefix else username, token, displayName, email=user['email'].lower(), prefix=prefix,
                        data=data)
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
            mapname, prefix = self.get_alt_name(username)
            displayName = user['name']
            token = Options['auth_key'] if mapname == ADMINUSER_ID else sliauth.gen_user_token(Options['auth_key'], mapname)
            self.set_id(mapname, mapname if prefix else username, token, displayName, prefix=prefix)
            self.redirect(self.get_argument("next", "/"))
        else:
            yield self.authorize_redirect()

class PlainHTTPHandler(tornado.web.RequestHandler):
    def prepare(self):
        if self.request.protocol == 'http':
            self.redirect('https://' + self.request.host, permanent=False)

    def get(self):
        self.write("Hello, world")

def createApplication():
    pathPrefix = '/'+Options['site_name'] if Options['site_number'] else ''
        
    home_handlers = [
                     (pathPrefix+r"/", HomeHandler),
                    ]
    if Options['sites']:
        if not Options['site_number']:
            home_handlers += [ (pathPrefix+r"/index.html", HomeHandler) ]
        else:
            home_handlers += [ (pathPrefix+r"$", HomeHandler) ]

    auth_handlers = [
                     (r"/_auth/logout/", AuthLogoutHandler),
                     (r"/_auth/login/", AuthLoginHandler),
                    ]

    # Only root can auto reload
    settings = {'autoreload': False if Options['site_number'] else Options['reload'] }
    if settings['autoreload']:
        tornado.autoreload.add_reload_hook(shutdown_all)

    Global.login_domain = ''
    Global.login_url = '/_auth/login/'
    if Options['auth_type']:
        Global.login_url = '/_oauth/login'
        comps = Options['auth_type'].split(',')

        if Options['server_url']:
            redirect_uri = Options['server_url'] + Global.login_url
        else:
            redirect_uri = 'http://localhost'+ ('' if Options['port'] == 80 else ':'+str(Options['port'])) + Global.login_url

        Global.login_domain = comps[0] if comps[0][0] == '@' else ''

        if comps[0] == 'google' or Global.login_domain:
            settings.update(google_oauth={'key': comps[1],
                                        'secret': comps[2],
                                        'redirect_uri': redirect_uri})
            auth_handlers += [ (Global.login_url, GoogleLoginHandler) ]

        elif comps[0] == 'twitter':
            settings.update(twitter_consumer_key=comps[1],
                            twitter_consumer_secret=comps[2])
            auth_handlers += [ (Global.login_url, TwitterLoginHandler) ]

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
        site_handlers = [
                      (pathPrefix+r"/_proxy", ProxyHandler),
                      (pathPrefix+r"/_websocket/(.*)", WSHandler),
                      (pathPrefix+r"/interact", AuthMessageHandler),
                      (pathPrefix+r"/interact/(.*)", AuthMessageHandler),
                      (pathPrefix+r"/(_dash)", AuthActionHandler)
                      ]

        patterns= [   r"/(_(reload|shutdown|update))",
                      r"/(_(backup|cache|clear|freeze))",
                      r"/(_backup/[-\w.]+)",
                      r"/(_delete/[-\w.]+)",
                      r"/(_export/[-\w.]+)",
                      r"/(_(getcol|getrow|sheet)/[-\w.;]+)",
                      r"/(_import/[-\w.]+)",
                      r"/(_lock)",
                      r"/(_lock/[-\w.]+)",
                      r"/(_logout)",
                      r"/(_manage/[-\w.]+)",
                      r"/(_prefill/[-\w.]+)",
                      r"/(_qstats/[-\w.]+)",
                      r"/(_refresh/[-\w.]+)",
                      r"/(_respond/[-\w.;]+)",
                      r"/(_roster)",
                      r"/(_sessions)",
                      r"/(_submissions/[-\w.:;]+)",
                      r"/(_submit/[-\w.:;]+)",
                      r"/(_twitter)",
                      r"/(_unlock/[-\w.]+)",
                       ]
        action_handlers = [(pathPrefix+pattern, ActionHandler) for pattern in patterns]
    else:
        site_handlers = []
        action_handlers = []

    file_handler = BaseStaticFileHandler if Options['no_auth'] else AuthStaticFileHandler

    for path in [PLUGINDATA_PATH, PRIVATE_PATH, RESTRICTED_PATH]:
        dir = (Options['plugindata_dir'] if path == PLUGINDATA_PATH else Options['static_dir']) + pathPrefix
        if dir:
            site_handlers += [ (r'/(%s/.*)' % path+pathPrefix, file_handler, {"path": dir}) ]

    if Options['static_dir']:
        site_handlers += [ (r'/([^_].*)', file_handler, {"path": Options['static_dir']}) ]

    if Options['sites']:
        if not Options['site_number']:
            handlers = home_handlers + auth_handlers + action_handlers
        else:
            handlers = home_handlers + action_handlers + site_handlers
    else:
        handlers = home_handlers + auth_handlers + action_handlers + site_handlers

    ##if Options['debug']:
    ##    print >> sys.stderr, 'createApplication', Options['site_number'], [x[0] for x in handlers]
    return tornado.web.Application(handlers, **settings)


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

def importAnswersAux(sessionName, submitDate, filepath, csvfile):
    missed = []
    errors = []
    try:
        ##dialect = csv.Sniffer().sniff(csvfile.read(1024))
        ##csvfile.seek(0)
        reader = csv.reader(csvfile, delimiter=',')  # Ignore dialect for now
        headers = reader.next()
        rows = [row for row in reader]
        idCol = 0
        nameCol = 0
        lastNameCol = 0
        firstNameCol = 0
        twitterCol = 0
        formCol = 0
        qresponse = {}
        for j, header in enumerate(headers):
            hmatch = re.match(r'^(q?[gx]?)(\d+)$', header)
            if hmatch:
                qnumber = int(hmatch.group(2))
                qresponse[qnumber] = (j, hmatch.group(1))
            elif header == 'id':
                idCol = j+1
            elif header == 'name':
                nameCol = j+1
            elif header == 'twitter':
                twitterCol = j+1
            elif header.lower() == 'form':
                formCol = j+1
            elif header.lower() in ('last', 'lastname', 'last name'):
                lastNameCol = j+1
            elif header.lower() in ('first', 'firstname', 'first name'):
                firstNameCol = j+1

        qnumbers = qresponse.keys()
        qnumbers.sort()
        qnumberMap = [[]]
        if formCol:
            qnumberMap.append([])
        if qnumbers:
            if qnumbers[0] != 1 or qnumbers[-1] != len(qnumbers):
                raise Exception('Invalid sequence of question numbers: '+','.join(qnumbers))
            midoffset = len(qnumbers) % 2
            midnumber = (len(qnumbers)-midoffset) / 2
            for qnumber in qnumbers:
                qnumberMap[0].append(qnumber)
                if not formCol:
                    continue
                # Mid-point swap
                if qnumber > midnumber:
                    qnumberMap[1].append(qnumber - midnumber)
                else:
                    qnumberMap[1].append(qnumber + midnumber + midoffset)
        print >> sys.stderr, 'qnumberMap=', qnumberMap
                
        nameMap = sdproxy.lookupRoster('name')
        idMap = {}
        if twitterCol:
            idMap = sdproxy.makeRosterMap('twitter', lowercase=True)
            if not idMap:
                raise Exception('No twitter ids found in roster')
        elif not idCol:
            if lastNameCol and firstNameCol:
                idMap = sdproxy.makeRosterMap('name')
                names = [ row[lastNameCol-1]+', '+row[firstNameCol-1] for row in rows]
                missing = []
                for name in names:
                    if name not in idMap:
                        missing.append(name)
                        print >> sys.stderr, 'Name', name, 'not found in roster'
                if missing:
                    raise Exception('One or more names not found in roster: '+', '.join(missing))
            else:
                raise Exception('No id or twitter or name columns for importing answers from '+filepath)

        for row in rows:
            answers = {}
            formSwitch = 0
            if formCol and row[formCol-1] and row[formCol-1].upper() != 'A':
                formSwitch = 1
            for qnumber in qnumbers:
                qnumberMapped = qnumberMap[formSwitch][qnumber-1]
                value = qresponse[qnumberMapped]
                cellValue = row[value[0]].strip()
                if not cellValue:
                    continue
                if value[1] == 'qg':
                    answers[qnumber] = {'grade': cellValue}
                    continue
                explain = ''
                if value[1] == 'qx':
                    comps = cellValue.split()
                    if len(comps) > 1:
                        explain = cellValue[len(comps[0]):].strip()
                        cellValue = comps[0]
                answers[qnumber] = {'response': cellValue}
                if value[1] == 'qx':
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
            else:
                userId = idMap[ row[lastNameCol-1]+', '+row[firstNameCol-1] ]

            displayName = row[nameCol-1] if nameCol else ''
            try:
                if Options['debug']:
                    print >> sys.stderr, 'DEBUG: importAnswersAux', sessionName, userId, displayName
                sdproxy.importUserAnswers(sessionName, userId, displayName, answers=answers, submitDate=submitDate, source='import')
            except Exception, excp:
                errors.append('Error in import for '+str(userId)+': '+str(excp))
                missed.append(userId)
                missed.append('... and others')
                break
    except Exception, excp:
        if Options['debug']:
            import traceback
            traceback.print_exc()
        errors = [ 'Error in importAnswersAux: '+str(excp)] + errors

    return missed, errors

def importRosterAux(filepath, csvfile):
    errors = []
    try:
        ##dialect = csv.Sniffer().sniff(csvfile.read(1024))
        ##csvfile.seek(0)
        reader = csv.reader(csvfile, delimiter=',')  # Ignore dialect for now
        headers = reader.next()
        rows = [row for row in reader]
        sdproxy.createRoster(headers, rows)
    except Exception, excp:
        if Options['debug']:
            import traceback
            traceback.print_exc()
        errors = ['Error in importRosterAux: '+str(excp)]

    return errors

def makePrivateRequest(relay_address, path='/', proto='http'):
    if Options['debug']:
        print >> sys.stderr, 'DEBUG: sdserver.makePrivateRequest:', relay_address, path
    if isinstance(relay_address, tuple):
        http_client = tornado.httpclient.HTTPClient()
        url = proto+('://%s:%d' % relay_address)
        return http_client.fetch(url+path)
    else:
        import multiproxy
        sock = multiproxy.create_unix_client_socket(relay_address)
        retval = sock.sendall('''GET %s HTTP/1.1\r\nHost: localhost\r\n\r\n''' % path)
        sock.close()
        return retval

def backupSite(dirpath=''):
    if Options['debug']:
        print >> sys.stderr, 'sdserver.backupSite:', dirpath
    if Options['sites'] and not Options['site_number']:
        # Primary server
        for j, site in enumerate(Options['sites']):
            relay_addr = Global.relay_list[j+1]
            retval = makePrivateRequest(relay_addr, path='/'+site+'/_backup?root='+Options['root_key'])
    else:
        errors = sdproxy.backupSheets(dirpath)
        self.set_header('Content-Type', 'text/plain')
        self.write('Backed up site %s to directory %s' % (Options['site_name'], sessionName))
        if errors:
            self.write(errors)

def shutdown_all():
    if Options['debug']:
        print >> sys.stderr, 'sdserver.shutdown_all:'
    for j, site in enumerate(Options['sites']):
        # Shutdown child servers
        relay_addr = Global.relay_list[j+1]
        retval = makePrivateRequest(relay_addr, path='/'+site+'/_shutdown?root='+Options['root_key'])

    # Shutdown parent
    IOLoop.current().add_callback(shutdown_loop)

def shutdown_loop():
    if Options['debug']:
        print >> sys.stderr, 'sdserver.shutdown_loop:'
    IOLoop.current().stop()
    
twitterStream = None
def main():
    global twitterStream
    define("config", type=str, help="Path to config file",
        callback=lambda path: parse_config_file(path, final=False))

    define("allow_replies", default=False, help="Allow replies to twitter direct messages")
    define("auth_key", default=Options["auth_key"], help="Digest authentication key for admin user")
    define("auth_type", default=Options["auth_type"], help="@example.com|google|twitter,key,secret,tuser1=suser1,...")
    define("backup", default="", help="=Backup_dir[,HH:MM] End Backup_dir with hyphen to automatically append timestamp")
    define("debug", default=False, help="Debug mode")
    define("dry_run", default=False, help="Dry run (read from Google Sheets, but do not write to it)")
    define("forward_port", default=0, help="Forward port for default web server with multiproxy)")
    define("freeze_date", default="", help="Date when all user mods are disabled")
    define("gsheet_url", default="", help="Google sheet URL1;...")
    define("lock_proxy_url", default="", help="Proxy URL to lock sheet(s), e.g., http://example.com")
    define("import_answers", default="", help="sessionName,CSV_spreadsheet_file,submitDate; with CSV file containing columns id/twitter, q1, qx2, q3, qx4, ...")
    define("insecure_cookie", default=False, help="Insecure cookies (for printing)")
    define("no_auth", default=False, help="No authentication mode (for testing)")
    define("plugindata_dir", default=Options["plugindata_dir"], help="Path to plugin data files directory")
    define("plugins", default="", help="List of plugin paths (comma separated)")
    define("private_port", Options["private_port"], help="Base private port for multiproxy)")
    define("proxy_wait", type=int, help="Proxy wait time (>=0; omit argument for no proxy)")
    define("public", default=Options["public"], help="Public web site (no login required, except for _private/_restricted)")
    define("reload", default=False, help="Enable autoreload mode (for updates)")
    define("sites", default="", help="Site names for multi-site server (comma-separated)")
    define("site_label", default=Options["site_label"], help="Site label")
    define("server_url", default=Options["server_url"], help="Server URL, e.g., http://example.com")
    define("socket_dir", default="", help="Directory for creating unix-domain socket pairs")
    define("ssl", default="", help="SSLcertfile,SSLkeyfile")
    define("static_dir", default=Options["static_dir"], help="Path to static files directory")
    define("twitter_stream", default="", help="Twitter stream access info: username,consumer_key,consumer_secret,access_key,access_secret;...")
    define("xsrf", default=False, help="XSRF cookies for security")

    define("port", default=Options['port'], help="Web server port", type=int)
    parse_command_line()

    if not options.auth_key and not options.public:
        sys.exit('Must specify one of --public or --auth_key=...')

    settings = {}
    if options.gsheet_url:
        # Need to restart server if SETTINGS_SHEET is changed
        settings = sliauth.read_settings(options.gsheet_url, options.auth_key or '', SETTINGS_SHEET)

    for key in Options:
        if not key.startswith('_'):
            if hasattr(options, key):
                # Command line overrides settings
                Options[key] = getattr(options, key)
            elif key in settings:
                Options[key] = settings[key]

    Split_opts = {}
    if Options['sites']:
        Options['sites'] = [x.strip() for x in Options['sites'].split(',')]
        for key in ('gsheet_url', 'twitter_stream'):
            if Options[key]:
                Split_opts[key] = [x.strip() for x in Options[key].split(';')]
                if len(Split_opts[key]) != len(Options['sites']):
                    raise Exception('No. of values for --'+key+'=...;... should match number of sites')
                Options[key] = ''
            else:
                Split_opts[key] = ['']*len(Options['sites'])

    if not options.debug:
        logging.getLogger('tornado.access').disabled = True

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

    print >> sys.stderr, ''
    print >> sys.stderr, 'sdserver: Starting **********************************************'

    if plugins:
        print >> sys.stderr, 'sdserver: Loaded plugins: '+', '.join(plugins)

    ssl_options = None
    if options.port == 443:
        if not options.ssl:
            sys.exit('SSL options must be specified for port 443')
        certfile, keyfile = options.ssl.split(',')
        ssl_options = {"certfile": certfile, "keyfile": keyfile}

    Options['root_key'] = str(random.randrange(0,2**60))
    if Options['debug']:
        print >> sys.stderr, 'sdserver: ROOT_KEY', Options['root_key']
    child_pids = []
    Global.relay_list = []
    socket_name_fmt = options.socket_dir + '/uds_socket'
    if Options['sites']:
        if options.forward_port:
            Global.relay_list.append( ('localhost', options.forward_port) )
        elif options.socket_dir:
            Global.relay_list = [ options.socket_dir+'/uds_socket'+str(Options['private_port']) ]
        else:
            Global.relay_list.append( ('localhost', Options['private_port'] ) )
            

        for j, site_name in enumerate(Options['sites']):
            port = Options['private_port']+j+1
            if options.socket_dir:
                Global.relay_list.append(options.socket_dir+'/uds_socket'+str(port))
            else:
                Global.relay_list.append( ("localhost", port) )

            pid = os.fork()
            if Options['debug']:
                print >> sys.stderr, 'DEBUG: sdserver.fork:', pid

            if pid:
                # Primary server
                child_pids.append(pid)
            else:
                # Secondary server
                Options['site_number'] = j+1
                Options['site_name'] = site_name
                Options['site_label'] = site_name
                for key in Split_opts:
                    Options[key] = Split_opts[key][j]
                break

    if options.proxy_wait is not None:
        # Copy options to proxy
        for key in sdproxy.Settings:
            if not key.startswith('_') and key in Options:
                sdproxy.Settings[key] = Options[key]

    if options.backup and not Options['site_name']:
        # Sole or primary server
        comps = options.backup.split(',')
        sdproxy.Settings['backup_dir'] = comps[0]
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
            backupSite()
            Global.backup = PeriodicCallback(backupSite, backupInterval*1000.0)
            Global.backup.start()
        
        IOLoop.current().call_at(backupTimeSec, start_backup)

    if Options['twitter_stream']:
        comps = Options['twitter_stream'].split(',')
        Global.twitter_config = {
            'screen_name': comps[0],
            'consumer_token': {'consumer_key': comps[1], 'consumer_secret': comps[2]},
            'access_token': {'key': comps[3], 'secret': comps[4]}
            }

        import sdstream
        twitterStream = sdstream.TwitterStreamReader(Global.twitter_config, processTwitterMessage,
                                                     allow_replies=options.allow_replies)
        twitterStream.start_stream()

    if Options['debug']:
        print >> sys.stderr, 'DEBUG: sdserver.main:', Options['site_number'], Options['site_name'], Options['sites']

    if Options['sites']:
        listen_port = Options['private_port'] + Options['site_number']
        if not Options['site_number']:
            # Primary server
            import multiproxy
            class ProxyRequestHandler(multiproxy.RequestHandler):
                def get_relay_addr_uri(self, pipeline, header_list):
                    """ Returns relay host, port.
                    May modify self.request_uri or header list (excluding the first element)
                    Raises exception if connection not allowed.
                    """
                    comps = self.request_uri.split('/')
                    if len(comps) > 1 and comps[1] and comps[1] in Options['sites']:
                        site_number = 1+Options['sites'].index(comps[1])
                    else:
                        site_number = 0
                    retval = Global.relay_list[site_number]
                    print >> sys.stderr, 'ABC: get_relay_addr_uri: ', self.request_uri, site_number, retval
                    return retval

            Proxy_server = multiproxy.ProxyServer("localhost", options.port, ProxyRequestHandler, log_interval=0,
                              io_loop=IOLoop.current(), xheaders=True, masquerade="server/1.2345", ssl_options=ssl_options, debug=True)
    else:
        # Sole server
        listen_port = options.port

    if Options['debug']:
        print >> sys.stderr, 'DEBUG: sdserver.main2:', Options['site_number']

    if ssl_options and not Options['sites']:
        http_server = tornado.httpserver.HTTPServer(createApplication(), ssl_options=ssl_options)

        # Redirect plain HTTP to HTTPS
        handlers = [ (r'/', PlainHTTPHandler) ]
        plain_http_app = tornado.web.Application(handlers)
        plain_http_app.listen(80)
        print >> sys.stderr, "Listening on HTTP port"
    else:
        http_server = tornado.httpserver.HTTPServer(createApplication())

    if Options['debug']:
        print >> sys.stderr, 'DEBUG: sdserver.main3:', Global.relay_list, Options['site_number']
    if Options['sites']:
        relay_addr = Global.relay_list[Options['site_number']]
        if not Options['site_number'] and options.forward_port:
            print >> sys.stderr, "Forward by default to port", relay_addr[1]
        else:
            if isinstance(relay_addr, tuple):
                http_server.listen(relay_addr[1])
            else:
                import multiproxy
                sock = multiproxy.make_unix_server_socket(relay_addr)
                http_server.add_socket(sock)
            print >> sys.stderr, "Listening to socket %s: %s" % (relay_addr, Options['site_name'])
    else:
        http_server.listen(listen_port)
        print >> sys.stderr, "Listening on port", listen_port, Options['site_name']

    IOLoop.current().start()


if __name__ == "__main__":
    main()
