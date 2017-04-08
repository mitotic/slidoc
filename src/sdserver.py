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
    source_dir: path to static files directory containing Slidoc .md files (default='source')
    static_dir: path to static files directory containing Slidoc html files (default='static')
    xsrf: Enable XSRF cookies for security

    For Twitter auth workflow, see sdstream.py

"""

import argparse
import base64
import cStringIO
import csv
import datetime
import functools
import glob
import importlib
import io
import json
import logging
import math
import random
import os.path
import re
import shutil
import socket
import sys
import time
import urllib
import uuid
import zipfile

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

import md2md
import sdproxy
import sliauth
import slidoc
import plugins

scriptdir = os.path.dirname(os.path.realpath(__file__))

Options = {
    '_index_html': '',  # Non-command line option
    'root_auth_key': '',
    'admin_users': '',
    'allow_replies': None,
    'auth_key': '',
    'auth_type': '',
    'backup_dir': '',
    'backup_hhmm': '',
    'debug': False,
    'dry_run': False,
    'grader_users': '',
    'gsheet_url': '',
    'guest_users': '',
    'host': 'localhost',
    'import_params': '',
    'insecure_cookie': False,
    'lock_proxy_url': '',
    'min_wait_sec': 0,
    'missing_choice': '*',
    'no_auth': False,
    'offline_sessions': r'exam|final|midterm',
    'plugindata_dir': 'plugindata',
    'port': 8888,
    'private_port': 8900,
    'proxy_wait': None,
    'public': False,
    'reload': False,
    'roster_columns': 'lastname,firstname,,id,email,altid',
    'server_key': None,
    'server_start': None,
    'server_url': '',
    'site_name': '',         # E.g., calc101
    'site_label': '',        # E.g., Calculus 101
    'site_list': [],         # List of site names
    'site_restricted': '',
    'site_title': '',        # E.g., Elementary Calculus, Fall 2000
    'site_number': 0,
    'sites': '',             # Comma separated list of site names
    'socket_dir': '',
    'source_dir': '',
    'ssl_options': None,
    'start_date': '',
    'static_dir': 'static',
    'twitter_config': '',
    'xsrf': False,
    }

OPTIONS_FROM_SHEET = ['admin_users', 'grader_users', 'guest_users', 'start_date']
SPLIT_OPTS = ['gsheet_url', 'twitter_config', 'site_label', 'site_restricted', 'site_title']

SESSION_OPTS_RE = re.compile(r'^session_(\w+)$')

class Dummy():
    pass
    
Global = Dummy()
Global.userRoles = None
Global.backup = None
Global.twitter_params = {}
Global.relay_list = []
Global.relay_forward = None
Global.http_server = None
Global.server_socket = None
Global.proxy_server = None
Global.session_options = {}

Global.twitterStream = None
Global.split_opts = {}

PLUGINDATA_PATH = '_plugindata'
PRIVATE_PATH    = '_private'
RESTRICTED_PATH = '_restricted'

ADMIN_PATH = 'admin'

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

COOKIE_VERSION = '0.9'             # Update version if cookie format changes
SERVER_NAME = 'Webster0.9'

RAW_UPLOAD = 'raw'
TOP_LEVEL = 'top'

SESSION_TYPES = [
    [TOP_LEVEL, 'Top level web page'],
    ['announce', 'Announcements'],
    ['assignment', 'Assigments'],
    ['exam', 'Exams'],
    ['exercise', 'Exercises'],
    ['final', 'Final exam'],
    ['help', 'Help info'],
    ['lecture', 'Lectures'],
    ['midterm', 'Midterms'],
    ['notes', 'Notes'],
    ['project', 'Projects'],
    ['quiz', 'Quizzes'],
    ['test', 'Tests']
    ]

PUBLIC_SESSIONS = (TOP_LEVEL, 'help')
UNPACED_SESSIONS = (TOP_LEVEL, 'announce', 'exercise', 'help', 'notes')
OFFLINE_SESSIONS = ('exam', 'final', 'midterm')

SESSION_TYPE_SET = set()
for j, entry in enumerate(SESSION_TYPES):
    SESSION_TYPE_SET.add(entry[0])

    if entry[0] in PUBLIC_SESSIONS:
        entry[1] += ' (public)'

    if entry[0] not in UNPACED_SESSIONS:
        entry[1] += ' (paced)'

    if entry[0] in OFFLINE_SESSIONS:
        entry[1] += ' (offline)'

SESSION_NAME_FMT = '%s%02d'
SESSION_NAME_RE = re.compile(r'^(\w*[a-zA-Z_])(\d+)$')

def getSessionType(sessionName):
    smatch = SESSION_NAME_RE.match(sessionName)
    if not smatch:
        return (TOP_LEVEL, 0)

    sessionType = smatch.group(1)
    sessionNumber = int(smatch.group(2))

    if sessionType in SESSION_TYPE_SET:
        return (sessionType, sessionNumber)
    else:
        return (TOP_LEVEL, 0)
        
def privatePrefix(uploadType):
    if uploadType in PUBLIC_SESSIONS:
        return ''
    else:
        return '/' + PRIVATE_PATH

def pacedSession(uploadType):
    if uploadType in UNPACED_SESSIONS:
        return 0
    else:
        return 1

def gen_proxy_auth_token(username, role='', sites='', key='', prefixed=False, root=False):
    if not key:
        key = Options['root_auth_key'] if root else Options['auth_key']
    return sliauth.gen_auth_token(key, username, role=role, sites=sites, prefixed=prefixed)

def http_sync_post(url, params_dict=None):
    site_prefix = '/'+Options['site_name'] if Options['site_name'] else ''
    if url == site_prefix+'/_proxy':
        return sdproxy.sheetAction(params_dict)

    http_client = tornado.httpclient.HTTPClient()
    if params_dict:
        body = urllib.urlencode(params_dict)
        response = http_client.fetch(url, method='POST', headers=None, body=body)
    else:
        response = http_client.fetch(url, method='GET', headers=None, body=body)
    if response.error:
        raise Exception('ERROR in accessing URL %s: %s' % (url, excp))
    # Successful return
    result = response.read()
    try:
        result = json.loads(result)
    except Exception, excp:
        result = {'result': 'error', 'error': 'Error in http_sync_post: result='+str(result)+': '+str(excp)}
    return result
    

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

    def set_id(self, username, role='', sites='', displayName='', email='', altid='', data={}):
        if Options['debug']:
            print >> sys.stderr, 'sdserver.UserIdMixin.set_id', username, role, sites, displayName, email, altid, data

        if ':' in username or ':' in role or ':' in sites or ':' in displayName:
            raise Exception('Colon character not allowed in username/role/name')

        cookie_data = {}
        cookie_data['name'] = displayName or username
        if email:
            cookie_data['email'] = email
        if altid:
            cookie_data['altid'] = altid
        if Options['source_dir']:
            cookie_data['editable'] = 'edit'
        cookie_data.update(data)

        token = gen_proxy_auth_token(username, role, sites, root=True)
        cookieStr = ':'.join( sliauth.safe_quote(x) for x in [username, role, sites, token, base64.b64encode(json.dumps(cookie_data))] )

        if cookie_data.get('batch'):
            self.set_secure_cookie(USER_COOKIE_SECURE, cookieStr, max_age=BATCH_AGE)
            self.set_cookie(SERVER_COOKIE, cookieStr, max_age=BATCH_AGE)
        else:
            self.set_secure_cookie(USER_COOKIE_SECURE, cookieStr, expires_days=EXPIRES_DAYS)
            self.set_cookie(SERVER_COOKIE, cookieStr, expires_days=EXPIRES_DAYS)

    def clear_id(self):
        self.clear_cookie(USER_COOKIE_SECURE)
        self.clear_cookie(SERVER_COOKIE)

    def check_access(self, username, token, role=''):
        return token == gen_proxy_auth_token(username, role, root=True)

    def get_id_from_cookie(self, role=False, for_site='', sites=False, name=False, email=False, altid=False, data=False):
        # If for_site and site name does not appear in cookie.sites, None will be returned for role
        # Null string will be returned for role, if site name is present
        # Ensure SERVER_COOKIE is also set before retrieving id from secure cookie (in case one of them gets deleted)
        if Options['insecure_cookie']:
            cookieStr = self.get_cookie(SERVER_COOKIE)
        else:
            cookieStr = self.get_secure_cookie(USER_COOKIE_SECURE) if self.get_cookie(SERVER_COOKIE) else ''

        if not cookieStr:
            return None
        try:
            comps = [urllib.unquote(x) for x in cookieStr.split(':')]
            ##if Options['debug']:
                ##print >> sys.stderr, "DEBUG: sdserver.UserIdMixin.get_id_from_cookie", comps
            userId, userRole, userSites, token, data_json = comps[:5]
            userData = json.loads(base64.b64decode(data_json))

            if role:
                if not userRole and for_site:
                    if not userSites:
                        return None
                    return sdproxy.getSiteRole(for_site, userSites)
                return userRole

            if sites:
                return userSites
            if name:
                return userData.get('name', '')
            if email:
                return userData.get('email', '')
            if altid:
                return userData.get('altid', '')
            if data:
                return userData
            return userId
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
    site_src_dir = None
    site_web_dir = None
    site_uploads_dir = None
    def set_default_headers(self):
        # Completely disable cache
        self.set_header('Server', SERVER_NAME)
        self.set_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')

    def get_current_user(self):
        if not Options['auth_key']:
            self.clear_id()
            return "noauth"
        return self.get_id_from_cookie() or None

    def write_error(self, status_code, **kwargs):
        err_cls, err, traceback = kwargs['exc_info']
        if getattr(err, 'log_message', None) and err.log_message.startswith('CUSTOM:'):
            print >> sys.stderr, err.log_message
            customMsg = err.log_message[len('CUSTOM:'):]
            if customMsg.startswith('<'):
                self.write('<html><body><h3>%s</h3></body></html>' % customMsg)
            else:
                self.set_header('Content-Type', 'text/plain')
                self.write(customMsg)
        else:
            super(BaseHandler, self).write_error(status_code, **kwargs)
    
    def check_admin_access(self, token='', root=''):
        if root == Options['server_key']:
            return True
        if token == Options['auth_key']:
            return True
        role = self.get_id_from_cookie(role=True, for_site=Options['site_name'])
        if role == sdproxy.ADMIN_ROLE:
            return True
        return False


class HomeHandler(BaseHandler):
    def get(self):
        if sdproxy.proxy_error_status():
            self.write('<h3>Server error - restart required</h3> ('+sdproxy.proxy_error_status()+')')
            return
        if Options['site_list'] and not Options['site_number']:
            # Primary server
            admin_roles = []
            for siteName in Options['site_list']:
                admin_roles.append(self.get_id_from_cookie(role=True, for_site=siteName) == sdproxy.ADMIN_ROLE)
            self.render('index.html', user=self.get_current_user(),
                         login_url=Global.login_url, logout_url=Global.logout_url,
                         sites=Options['site_list'], admin_roles=admin_roles, site_labels=Global.split_opts['site_label'],
                         site_titles=Global.split_opts['site_title'], site_restricteds=Global.split_opts['site_restricted'])
            return
        elif Options.get('_index_html'):
            # Not authenticated
            self.write(Options['_index_html'])
        else:
            # Authenticated by static file handler, if need be
            self.redirect("/"+Options['site_name']+"/index.html" if Options['site_number'] else "/index.html")

class SiteActionHandler(BaseHandler):
    def get(self, action='', subsubpath=''):
        userId = self.get_current_user()
        if Options['debug']:
            print >> sys.stderr, 'DEBUG: SiteActionHandler', userId, Options['site_number'], action
        root = str(self.get_argument("root", ""))
        token = str(self.get_argument("token", ""))
        if not self.check_admin_access(token=token, root=root):
            raise tornado.web.HTTPError(403)

        # Global admin user
        setup_html = '<p></p><a href="/_setup">Setup</a>'
        if action == '_setup':
            new_site_name = self.get_argument('sitename', '').strip()
            new_site_url = self.get_argument('siteurl', '').strip()
            if not new_site_name:
                self.render('setup.html', status='STATUS', site_updates=[('TBD', 'TBD')])
                return
            elif new_site_name in Options['site_list']:
                self.write('Site %s already active' % new_site_name)
                self.write(setup_html)
                return
            elif not new_site_url:
                self.write('Please specify Google Sheets URL for new site')
                self.write(setup_html)
                return

            # New site
            errMsg = fork_site_server(new_site_name, new_site_url)
            if Options['site_number']:
                # Child process
                return
            if errMsg:
                self.write(errMsg)
            else:
                self.write('Created new site: %s' % new_site_name)
            self.write(setup_html)
            return

        elif action in ('_reload', '_update'):
            if not Options['reload']:
                self.write('Please restart server with --reload option')
                self.write(setup_html)
            else:
                if Global.backup:
                    Global.backup.stop()
                    Global.backup = None
                sdproxy.suspend_cache(action[1:])
                self.write('Starting %s' % action[1:])
                self.write(setup_html)

        elif action == '_backup':
            backupSite()

        elif action == '_shutdown':
            self.clear_id()
            self.write('Starting shutdown (also cleared cookies)<p></p>')
            self.write(setup_html)
            if Options['site_list'] and not Options['site_number']:
                # Primary server
                shutdown_all()
            else:
                if Global.backup:
                    Global.backup.stop()
                    Global.backup = None
                sdproxy.suspend_cache('shutdown')
        else:
            raise tornado.web.HTTPError(403, log_message='CUSTOM:Invalid home action '+action)

class ActionHandler(BaseHandler):
    previewState = {}
    mime_types = {'.gif': 'image/gif', '.jpg': 'image/jpg', '.jpeg': 'image/jpg', '.png': 'image/png'}
    cmd_opts =   { 'base': dict(debug=True),
                   'other': dict(),
                  }
    default_opts = { 'base':  dict(),
                     'other': dict(),
                     }
    fix_opts = set()

    def previewActive(self):
        return self.previewState.get('name', '')

    def get_config_opts(self, uploadType, text='', topnav=False, paced=False, dest_dir='', image_dir='', no_make=False):
        # Return (cmd_args, default_args) 
        defaultOpts = self.default_opts['base'].copy()
        if uploadType in self.default_opts:
            defaultOpts.update(self.default_opts[uploadType])
        else:
            defaultOpts.update(self.default_opts['other'])

        if image_dir:
            defaultOpts.update(image_dir=image_dir)

        configOpts = slidoc.cmd_args2dict(slidoc.alt_parser.parse_args([]))
        configOpts.update(self.cmd_opts['base'])

        if not no_make:
            configOpts['make'] = True

        if uploadType in self.cmd_opts:
            configOpts.update(self.cmd_opts[uploadType])
        else:
            configOpts.update(self.cmd_opts['other'])

        if uploadType in Global.session_options:
            # session-specific options (TBD)
            pass

        if pacedSession(uploadType):
            defaultOpts['pace'] = 1
        else:
            configOpts['pace'] = 0

        if uploadType == TOP_LEVEL:
            defaultOpts['strip'] = 'chapters,contents'
        else:
            configOpts['make_toc'] = True

        if text:
            fileOpts = vars(slidoc.parse_merge_args(text, '', slidoc.Conf_parser, {}, first_line=True))
            for key, value in fileOpts.items():
                if key not in self.fix_opts and value is not None:
                    # Override with file opts
                    configOpts[key] = value

        configOpts.update(site_name=Options['site_name'])
        if topnav:
            configOpts.update(topnav=','.join(self.get_topnav_list()))

        if pacedSession(uploadType):
            site_prefix = '/'+Options['site_name'] if Options['site_name'] else ''
            configOpts.update(auth_key=Options['auth_key'], gsheet_url=site_prefix+'/_proxy',
                              proxy_url=site_prefix+'/_websocket')
            if Options['start_date']:
                configOpts.update(start_date=Options['start_date'])

        if dest_dir:
            configOpts.update(dest_dir=dest_dir)

        return configOpts, defaultOpts

    def get(self, subpath, inner=None):
        userId = self.get_current_user()
        if Options['debug']:
            print >> sys.stderr, 'DEBUG: ActionHandler.get', userId, Options['site_number'], subpath
        if subpath == '_logout':
            self.clear_id()
            self.render('logout.html')
            return
        root = str(self.get_argument("root", ""))
        token = str(self.get_argument("token", ""))
        if not self.check_admin_access(token=token, root=root):
            raise tornado.web.HTTPError(403)

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

    def post(self, subpath, inner=None):
        userId = self.get_current_user()
        if Options['debug']:
            print >> sys.stderr, 'DEBUG: postAction', userId, Options['site_number'], subpath
        if not self.check_admin_access():
            raise tornado.web.HTTPError(403)
        return self.postAction(subpath)

    def put(self, subpath):
        if Options['debug']:
            print >> sys.stderr, 'DEBUG: putAction', Options['site_number'], subpath, len(self.request.body), self.request.arguments, self.request.headers.get('Content-Type')
        action, sep, subsubpath = subpath.partition('/')
        if action == '_remoteupload':
            token = sliauth.gen_hmac_token(Options['auth_key'], 'upload:'+sliauth.digest_hex(self.request.body))
            if self.get_argument('token') != token:
                raise tornado.web.HTTPError(404, log_message='CUSTOM:Invalid remote upload token')
            fname, fext = os.path.splitext(subsubpath)
            uploadType, sessionNumber, src_path, web_path, web_images = self.getUploadType(fname)
            errMsg = ''
            if fext == '.zip':
                fname1, fbody1, fname2, fbody2 = '', '', subsubpath, self.request.body
            else:
                fname1, fbody1, fname2, fbody2 = subsubpath, self.request.body, '', ''

            try:
                errMsg = self.uploadSession(uploadType, sessionNumber, fname1, fbody1, fname2, fbody2)
            except Exception, excp:
                if Options['debug']:
                    import traceback
                    traceback.print_exc()
                errMsg = str(excp)
            if errMsg:
                raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in remote uploading session: '+errMsg)
            self.set_status(200)
            self.finish()
            return
        raise tornado.web.HTTPError(403, log_message='CUSTOM:Invalid PUT action '+action)

    def getAction(self, subpath):
        action, sep, subsubpath = subpath.partition('/')
        sessionName = subsubpath
        site_label = Options['site_label'] or 'Home'
        site_prefix = '/'+Options['site_name'] if Options['site_name'] else ''
        dash_url = site_prefix + '/_dash'
        json_return = self.get_argument('json', '')
        previewingSession = self.previewActive()
        if not Options['site_list'] or Options['site_number']:
            # Secondary server
            root = str(self.get_argument('root', ''))
            if action == '_preview':
                if not previewingSession:
                    raise tornado.web.HTTPError(404, log_message='CUSTOM:Not previewing session')
                cachePreview = sdproxy.previewingSession()
                if cachePreview and cachePreview != previewingSession:
                    # Inconsistent preview
                    self.discardPreview()
                    raise tornado.web.HTTPError(404, log_message='CUSTOM:Preview state inconsistent; resetting')
                return self.displayPreview(subsubpath)
            elif action == '_accept':
                if not Options['source_dir']:
                    raise tornado.web.HTTPError(403, log_message='CUSTOM:Must specify source_dir to upload')
                if not previewingSession:
                    raise tornado.web.HTTPError(404, log_message='CUSTOM:Not previewing session')
                return self.acceptPreview()
            elif action == '_edit':
                if not Options['source_dir']:
                    raise tornado.web.HTTPError(403, log_message='CUSTOM:Must specify source_dir to edit')
                if not sessionName:
                    sessionName = self.get_argument('sessionname', '')
                if previewingSession and previewingSession != sessionName:
                    raise tornado.web.HTTPError(404, log_message='CUSTOM:Cannot edit other sessions while reviewing session '+previewingSession)
                return self.startEdit(sessionName)
            elif action == '_discard':
                return self.discardPreview()

        if Options['site_list'] and not Options['site_number']:
            # Primary server
            if action not in ('_backup',):
                raise tornado.web.HTTPError(403)

        if previewingSession:
            self.write('Previewing session <a href="%s/_preview/index.html">%s</a><p></p>' % (site_prefix, previewingSession))
            return

        if action not in ('_dash', '_actions', '_sessions', '_roster', '_browse', '_twitter', '_cache', '_freeze', '_clear', '_backup', '_edit', '_upload', '_lock'):
            if not sessionName:
                self.displayMessage('Please specify /%s/session name' % action)
                return

        if action == '_dash':
            self.render('dashboard.html', site_name=Options['site_name'], site_label=Options['site_label'] or 'Home',
                        version=sdproxy.VERSION, interactive=WSHandler.getInteractiveSession())

        elif action == '_actions':
            self.render('actions.html', site_name=Options['site_name'], session_name='', suspended=sdproxy.Global.suspended)

        elif action == '_sessions':
            self.displaySessions()

        elif action == '_browse':
            if '..' in subsubpath:
                raise tornado.web.HTTPError(404, log_message='CUSTOM:Invalid path')
            if not subsubpath:
                file_list = [ ['source', 'source', False, False],
                              ['web', 'web', False, False],
                              ['uploads', 'uploads', False, False] ]
                up_path = ''
            else:
                predir, _, dirpath = subsubpath.partition('/')
                if predir == 'source':
                    rootdir = self.site_src_dir
                elif predir == 'web':
                    rootdir = self.site_web_dir
                elif predir == 'uploads':
                    rootdir = self.site_uploads_dir
                else:
                    raise tornado.web.HTTPError(404, log_message='CUSTOM:Directory must start with source/ or web/ or uploads/')

                up_path = os.path.dirname(subsubpath)
                fullpath = os.path.join(rootdir, dirpath)
                if not os.path.exists(fullpath):
                    self.displayMessage('Path %s does not exist!' % subsubpath)
                    return
                if not os.path.isdir(fullpath):
                    self.displayMessage('Path %s not a directory!' % subsubpath)
                    return

                file_list = []
                for fname in os.listdir(fullpath):
                    fpath = os.path.join(fullpath, fname)
                    fext = os.path.splitext(fname)[1]
                    subpath = os.path.join(subsubpath, fname)
                    isfile = os.path.isfile(fpath)
                    if predir in ('web', 'uploads') and fext.lower() in ('.jpeg','.jpg','.pdf','.png'):
                        _, _, viewpath = subpath.partition('/')
                    else:
                        viewpath = ''
                    file_list.append( [fname, subpath, isfile, viewpath] )

            self.render('browse.html', site_name=Options['site_name'], up_path=up_path, browse_path=subsubpath, file_list=file_list)

        elif action in ('_roster',):
            nameMap = sdproxy.lookupRoster('name', userId=None)
            if not nameMap:
                lastname_col, firstname_col, midname_col, id_col, email_col, altid_col = Options["roster_columns"].split(',')
                self.render('newroster.html', site_name=Options['site_name'],
                             lastname_col=lastname_col, firstname_col=firstname_col, midname_col=midname_col,
                             id_col=id_col, email_col=email_col, altid_col=altid_col)
            else:
                for idVal, name in nameMap.items():
                    if name.startswith('#'):
                        del nameMap[idVal]
                lastMap = sdproxy.makeShortNames(nameMap)
                firstMap = sdproxy.makeShortNames(nameMap, first=True)
                firstNames = firstMap.values()
                firstNames.sort()

                qwheel_link = 'http://code.mitotic.org/wheel/?session=' + urllib.quote_plus(Options['site_name'])
                qwheel_new = qwheel_link + '&names=' + ';'.join(urllib.quote_plus(x) for x in firstNames)

                self.render('roster.html', site_name=Options['site_name'],
                             qwheel_link=qwheel_link, qwheel_new=qwheel_new,
                             name_map=nameMap, last_map=lastMap, first_map=firstMap)

        elif action == '_cache':
            self.write('<h2>Proxy cache and connection status</h2>')
            self.write('<a href="%s">Dashboard</a><br>' % dash_url)
            self.write('<pre>')
            self.write(sdproxy.getCacheStatus())
            curTime = time.time()
            wsConnections = WSHandler.get_connections()
            sorted(wsConnections)
            wsInfo = []
            for path, user, connections in wsConnections:
                wsInfo += [(path, user, math.floor(curTime-ws.msgTime)) for ws in connections]
            sorted(wsInfo)
            self.write('\nConnections:\n')
            for x in wsInfo:
                self.write("  %s: %s (idle: %ds)\n" % x)
            self.write('</pre>')

        elif action == '_twitter':
            self.set_header('Content-Type', 'text/plain')
            if not Global.twitterStream:
                self.displayMessage('No twitter stream active')
            else:
                self.displayMessage(['Twitter stream status: '+Global.twitterStream.status+'\n\n',
                                     'Twitter stream log: '+'\n'.join(Global.twitterStream.log_buffer)+'\n'])

        elif action == '_freeze':
            sdproxy.freezeCache(fill=True)
            self.displayMessage('Freezing cache<br>')

        elif action == '_clear':
            sdproxy.suspend_cache('clear')
            self.displayMessage('Clearing cache<br>')

        elif action == '_backup':
            backupSite(subsubpath)

        elif action == '_lock':
            lockType = self.get_argument('type','')
            if sessionName:
                prefix = 'Locked'
                locked = sdproxy.lockSheet(sessionName, lockType or 'user')
                if not locked:
                    if lockType == 'proxy':
                        raise Exception('Failed to lock sheet '+sessionName+'. Try again after a few seconds?')
                    prefix = 'Locking'
            self.displayMessage(prefix +' sessions: %s<p></p><a href="%s/_cache">Cache status</a><p></p>' % (site_prefix, ', '.join(sdproxy.get_locked())) )

        elif action == '_unlock':
            if not sdproxy.unlockSheet(sessionName):
                raise Exception('Failed to unlock sheet '+sessionName)
            self.displayMessage('Unlocked '+sessionName+('<p></p><a href="%s/_cache">Cache status</a><p></p>' % site_prefix))

        elif action in ('_manage',):
            sheet = sdproxy.getSheet(sessionName, optional=True)
            if not sheet:
                self.displayMessage('No such session: '+sessionName)
                return
            self.render('manage.html', site_name=Options['site_name'], session_name=sessionName)

        elif action == '_download':
            if not Options['source_dir']:
                raise tornado.web.HTTPError(403, log_message='CUSTOM:Must specify source_dir to download')

            uploadType, sessionNumber, src_path, web_path, web_images = self.getUploadType(subsubpath)
            sessionFile = os.path.basename(src_path)
            image_dir = os.path.basename(web_images)
            try:
                with open(src_path) as f:
                    sessionText = f.read()
            except Exception, excp:
                raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in reading file %s: %s' % (src_path, excp))

            if os.path.isdir(web_images):
                # Create zip archive with Markdown file and images
                stream = io.BytesIO()
                zfile = zipfile.ZipFile(stream, 'w')
                zfile.writestr(sessionFile, sessionText)
                for name in os.listdir(web_images):
                    with open(web_images+'/'+name) as f:
                        zfile.writestr(image_dir+'/'+name, f.read())
                zfile.close()
                content = stream.getvalue()
                outfile = subsubpath+'.zip'
                self.set_header('Content-Type', 'application/zip')
            else:
                content = sessionText
                outfile = sessionFile
                self.set_header('Content-Type', 'text/plain')
            self.set_header('Content-Disposition', 'attachment; filename="%s"' % outfile)
            self.write(content)

        elif action == '_export':
            self.set_header('Content-Type', 'text/csv')
            self.set_header('Content-Disposition', 'attachment; filename="%s.csv"' % (sessionName+'_answers'))
            content = sdproxy.exportAnswers(sessionName)
            self.write(content)

        elif action in ('_sheet',):
            sheet = sdproxy.getSheet(subsubpath, optional=True)
            if not sheet:
                self.displayMessage('Unable to retrieve sheet '+subsubpath)
                return
            lastname_col, firstname_col, midname_col, id_col, email_col, altid_col = Options["roster_columns"].split(',')
            rows = sheet.export(idRename=id_col,altidRename=altid_col)
            self.render('table.html', site_name=Options['site_name'], table_name=subsubpath, table_data=rows, table_fixed='fixed')

        elif action in ('_getcol', '_getrow'):
            subsubpath, sep, label = subsubpath.partition(';')
            sheet = sdproxy.getSheet(subsubpath, optional=True)
            if not sheet:
                self.displayMessage('Unable to retrieve sheet '+subsubpath)
            else:
                self.write('<a href="%s">Dashboard</a><br>' % dash_url)
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
                        self.write('Column '+label+' not found in cached sheet '+subsubpath)
                    elif not label or label == 'id':
                        self.write('<pre>'+'\n'.join('<a href="%s/_getrow/%s;%s">%s</a>' % (site_prefix, subsubpath, x[0], x[0]) for x in sheet.getSheetValues(1, labelNum, sheet.getLastRow(), 1))+'</pre>')
                    else:
                        self.write('<pre>'+'\n'.join(str(x) for x in json.loads(json.dumps([x[0] for x in sheet.getSheetValues(1, labelNum, sheet.getLastRow(), 1)], default=sliauth.json_default)))+'</pre>')
                else:
                    if labelNum < 1 or labelNum > sheet.getLastRow():
                        self.write('Row '+label+' not found in cached sheet '+subsubpath)
                    else:
                        headerVals = sheet.getSheetValues(1, 1, 1, sheet.getLastColumn())[0]
                        if not label or labelNum == 1:
                            self.write('<pre>'+'\n'.join(['<a href="%s/_getcol/%s;%s">%s</a>' % (site_prefix, subsubpath, headerVals[j], headerVals[j]) for j in range(len(headerVals))]) +'</pre>')
                        else:
                            rowVals = sheet.getSheetValues(labelNum, 1, 1, sheet.getLastColumn())[0]
                            self.write('<pre>'+'\n'.join(headerVals[j]+':\t'+str(json.loads(json.dumps(rowVals[j], default=sliauth.json_default))) for j in range(len(headerVals))) +'</pre>')

        elif action in ('_rebuild', '_reindex'):
            if not Options['source_dir']:
                raise tornado.web.HTTPError(403, log_message='CUSTOM:Must specify source_dir to reindex/rebuild')

            rebuildForce = bool(self.get_argument('rebuildforce',''))

            if subsubpath == 'all':
                uploadType = ''
            else:
                uploadType, sessionNumber, src_path, web_path, web_images = self.getUploadType(subsubpath)

            if action == '_rebuild':
                buildMsgs = self.rebuild(uploadType, force=rebuildForce, log_dict=True)
                # Re-index after complete rebuild
                indMsgs = self.rebuild(uploadType, indexOnly=True)
            else:
                buildMsgs = {}
                indMsgs = self.rebuild(uploadType, indexOnly=True)

            if action == '_rebuild' and (1 or any(buildMsgs.values()) or any(indMsgs)):
                self.displaySessions(buildMsgs, indMsgs, msg='Completed rebuild')
            elif action == '_reindex' and indMsgs and any(indMsgs):
                self.displayMessage(['Error in %s:' % action] + indMsgs)
            else:
                self.redirect("/"+Options['site_name']+"/index.html" if Options['site_number'] else "/index.html")

        elif action == '_delete':
            errMsgs = self.deleteSession(subsubpath)
            if errMsgs and any(errMsgs):
                self.displayMessage(errMsgs)
            else:
                self.displayMessage('Deleted session '+sessionName)

        elif action == '_import':
            self.render('import.html', site_name=Options['site_name'], session_name=sessionName, import_params=updateImportParams(Options['import_params']) if Options['import_params'] else {}, submit_date=sliauth.iso_date())

        elif action == '_upload':
            if not Options['source_dir']:
                raise tornado.web.HTTPError(403, log_message='CUSTOM:Must specify source_dir to upload')
            smatch = SESSION_NAME_RE.match(sessionName)
            if smatch:
                upload_type = smatch.group(1)
                session_number = smatch.group(2)
            else:
                upload_type = TOP_LEVEL if sessionName else ''
                session_number = ''
            self.render('upload.html', site_name=Options['site_name'],
                        upload_type=upload_type, session_number=session_number, session_types=SESSION_TYPES, err_msg='')

        elif action == '_prefill':
            if sdproxy.getRowMap(sessionName, 'Timestamp', regular=True):
                raise tornado.web.HTTPError(403, log_message='CUSTOM:Error: Session %s already filled' % sessionName)
            nameMap = sdproxy.lookupRoster('name')
            count = 0
            for userId, name in nameMap.items():
                if not name or name.startswith('#'):
                    continue
                count += 1
                sdproxy.importUserAnswers(sessionName, userId, name, source='prefill')
            self.displayMessage('Prefilled session '+sessionName+' with '+str(count)+' users')

        elif action in ('_qstats',):
            sheetName = sessionName + '-answers'
            sheet = sdproxy.getSheet(sheetName, optional=True)
            if not sheet:
                self.displayMessage('Unable to retrieve sheet '+sheetName)
                return
            qrows = sheet.getSheetValues(1, 1, 2, sheet.getLastColumn())
            qaverages = []
            for j, header in enumerate(qrows[0]):
                qmatch = re.match(r'^q(\d+)_score', header)
                if qmatch:
                    qaverages.append([float(qrows[1][j]), int(qmatch.group(1))])
            qaverages.sort()
            if json_return:
                self.set_header('Content-Type', 'application/json')
                retval = {'result': 'success', 'qcorrect': qaverages}
                self.write( json.dumps(retval) )
            else:
                lines = []
                for j, qavg in enumerate(qaverages):
                    lines.append('Q%02d: %2d%%' % (qavg[1], int(qavg[0]*100)) )
                    if j%5 == 4:
                        lines.append('')
                self.displayMessage(('<h3>%s: percentage of correct answers</h3>\n' % sessionName) + '<pre>\n'+'\n'.join(lines)+'\n</pre>\n')

        elif action == '_refresh':
            if subsubpath:
                if sdproxy.refreshSheet(subsubpath):
                    msg = ' Refreshed sheet '+subsubpath
                else:
                    msg = ' Cannot refresh locked sheet '+subsubpath+' ...'
                self.displayMessage(msg+('<p></p><a href="%s/_cache">Cache status</a><p></p>' % site_prefix))

        elif action in ('_respond',):
            sessionName, sep, respId = sessionName.partition(';')
            if not sessionName:
                self.displayMessage('Please specify /_respond/session name')
                return
            sheet = sdproxy.getSheet(sessionName, optional=True)
            if not sheet:
                self.displayMessage('Unable to retrieve session '+sessionName)
                return
            nameMap = sdproxy.lookupRoster('name')
            if respId:
                if respId in nameMap:
                    sdproxy.importUserAnswers(sessionName, respId, nameMap[respId], source='manual', submitDate='dueDate')
                else:
                    self.displayMessage('User ID '+respId+' not in roster')
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
                    lines.append('<li>%s (<a href="%s/_respond/%s;%s">set responded</a>)</li>\n' % (site_prefix, name, sessionName, idVal))
            lines.append('</ul>\n')
            self.displayMessage(('Responders to session %s (%d/%d):' % (sessionName, count, len(nameMap)))+''.join(lines))

        elif action in ('_submissions',):
            comps = sessionName.split(';')
            sessionName = comps[0]
            userId = comps[1] if len(comps) >= 2 else ''
            dateStr = comps[2] if len(comps) >= 3 else ''
            sheet = sdproxy.getSheet(sessionName, optional=True)
            if not sheet:
                self.displayMessage('Unable to retrieve session '+sessionName)
                return
            sessionConnections = WSHandler.get_connections(sessionName)
            nameMap = sdproxy.lookupRoster('name')
            if userId:
                if not dateStr:
                    self.displayMessage('Please specify date')
                    return
                if 'T' not in dateStr:
                    dateStr += 'T23:59'
                if userId in nameMap:
                    # Close any active connections associated with user for session
                    for connection in sessionConnections.get(userId, []):
                        connection.close()
                    newLatetoken = sliauth.gen_late_token(Options['auth_key'], userId, Options['site_name'], sessionName, dateStr)
                    sdproxy.createUserRow(sessionName, userId, lateToken=newLatetoken, source='allow')
                else:
                    self.displayMessage('User ID '+userId+' not in roster')
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
            self.render('submissions.html', site_name=Options['site_name'], submissions_label='Late submission',
                         submissions_html=('Status of session '+sessionName+':<p></p>'+''.join(lines)) )

        elif action == '_submit':
            self.render('submit.html', site_name=Options['site_name'], session_name=sessionName)
        else:
            self.displayMessage('Invalid get action: '+action)

    def deleteSession(self, sessionName):
        user = sdproxy.ADMINUSER_ID
        userToken = gen_proxy_auth_token(user, sdproxy.ADMIN_ROLE, prefixed=True)
        args = {'sheet': sessionName, 'delsheet': '1', 'admin': user, 'token': userToken}
        retObj = sdproxy.sheetAction(args)
        if retObj['result'] != 'success':
            return ['Error in deleting sheet '+sessionName+': '+retObj.get('error','')]

        if Options['source_dir']:
            uploadType, sessionNumber, src_path, web_path, web_images = self.getUploadType(sessionName)

            if sessionName != 'index':
                if os.path.exists(src_path):
                    os.remove(src_path)

                if os.path.exists(web_path):
                    os.remove(web_path)

                if os.path.isdir(web_images):
                    shutil.rmtree(web_images)

            filePaths = self.get_md_list(uploadType)
            if filePaths:
                # Rebuild session index
                errMsgs = self.rebuild(uploadType, indexOnly=True)
            else:
                # No more sessions of this type; remove session index
                ind_path = os.path.join(os.path.dirname(web_path), 'index.html')
                if os.path.exists(ind_path):
                    os.remove(ind_path)
                errMsgs = self.rebuild(indexOnly=True)

            if errMsgs and any(errMsgs):
                msgs = ['Re-indexing after deleting session '+sessionName+':'] + [''] + errMsgs
                return msgs

            return []


    def displaySessions(self, buildMsgs={}, indMsgs=[], msg=''):
        colNames = ['releaseDate', 'dueDate', 'gradeDate']
        sessionParamDict = dict(sdproxy.lookupSessions(colNames))
        session_props = []
        for sessionType in self.get_session_names(top=True):
            session_props.append( [sessionType, 0, None, [], '\n'.join(buildMsgs.get(TOP_LEVEL, [])+indMsgs) if sessionType == 'index' else ''] )
        for sessionType in self.get_session_names():
            fnames = [os.path.splitext(os.path.basename(x))[0] for x in self.get_md_list(sessionType)]
            session_props.append( [sessionType,
                                    1 if privatePrefix(sessionType) else 0,
                                    fnames,
                                    sessionParamDict.get(sessionType, ['','','']),
                                    '\n'.join(buildMsgs.get(sessionType, []))] )
        site_prefix = '/'+Options['site_name'] if Options['site_name'] else ''
        self.render('sessions.html', site_name=Options['site_name'], session_props=session_props, message=msg)

    def getUploadType(self, sessionName, siteName=''):
        if not Options['source_dir']:
            raise tornado.web.HTTPError(403, log_message='CUSTOM:Must specify source_dir to get session type')

        if siteName:
            # Check permissions to retrieve session from another site
            siteRole = self.get_id_from_cookie(role=True, for_site=siteName)
            if siteRole != sdproxy.ADMIN_ROLE:
                raise tornado.web.HTTPError(404, log_message='CUSTOM:Denied access to site %s to retrieve session %s' % (siteName, sessionName))

            src_dir = Options['source_dir'] + '/' + siteName
            web_dir = Options['static_dir'] + '/' + siteName
        else:
            src_dir = self.site_src_dir
            web_dir = self.site_web_dir

        # Return (uploadType, sessionNumber, src_path, web_path, web_images)
        fname, fext = os.path.splitext(sessionName)
        if fext and fext != '.md':
            tornado.web.HTTPError(404, log_message='CUSTOM:Invalid session name (must end in .md): '+sessionName)

        uploadType, sessionNumber = getSessionType(fname)
        if uploadType == TOP_LEVEL:
            return uploadType, sessionNumber, src_dir+'/'+fname+'.md', web_dir+'/'+fname+'.html', web_dir+'/'+fname+'_images'
        if not sessionNumber:
            fname = 'index'

        web_prefix = web_dir+privatePrefix(uploadType)+'/'+uploadType+'/'+fname
        return uploadType, sessionNumber, src_dir+'/'+uploadType+'/'+fname+'.md', web_prefix+'.html', web_prefix+'_images'


    def postAction(self, subpath):
        previewingSession = self.previewActive()
        site_prefix = '/'+Options['site_name'] if Options['site_name'] else ''
        action, sep, sessionName = subpath.partition('/')
        if not sessionName:
            sessionName = self.get_argument('sessionname', '')

        if action == '_edit':
            if not Options['source_dir']:
                raise tornado.web.HTTPError(403, log_message='CUSTOM:Must specify source_dir to edit')
            if previewingSession and previewingSession != sessionName:
                raise tornado.web.HTTPError(404, log_message='CUSTOM:Cannot edit other sessions while reviewing session '+previewingSession)
            slideNumber = self.get_argument('slide', '')
            newNumber = self.get_argument('move', '')
            if slideNumber.isdigit():
                slideNumber = int(slideNumber)
            else:
                slideNumber = None
            if newNumber.isdigit():
                newNumber = int(newNumber)
            else:
                newNumber = None

            rollover = self.get_argument('rollover', '')
            if rollover:
                return self.rollover(sessionName, slideNumber)

            sessionText = self.get_argument('sessiontext')
            fromSession = self.get_argument('fromsession', '')
            fromSite = self.get_argument('fromsite', '')
            deleteSlide = self.get_argument('deleteslide', '')
            sessionModify = sessionName if self.get_argument('sessionmodify', '') else ''

            return self.postEdit(sessionName, sessionText, fromSession=fromSession, fromSite=fromSite, slideNumber=slideNumber, newNumber=newNumber, deleteSlide=deleteSlide,
                                 modify=sessionModify)

        elif action == '_imageupload':
            if not previewingSession:
                raise tornado.web.HTTPError(403, log_message='CUSTOM:Can only upload images in preview mode')
            fileinfo = self.request.files['upload'][0]
            fname = fileinfo['filename']
            fbody = fileinfo['body']
            sessionName = self.get_argument("sessionname")
            imageFile = self.get_argument("imagefile")
            return self.imageUpload(sessionName, imageFile, fname, fbody)

        if action in ('_sheet',):
            keepHidden = self.get_argument("keephidden", '')
            allUsers = self.get_argument("allusers", '')
            sheet = sdproxy.getSheet(sessionName, optional=True)
            if not sheet:
                self.displayMessage('Unable to retrieve sheet '+sessionName)
                return
            self.set_header('Content-Type', 'text/csv')
            self.set_header('Content-Disposition', 'attachment; filename="%s.csv"' % sessionName)
            lastname_col, firstname_col, midname_col, id_col, email_col, altid_col = Options["roster_columns"].split(',')
            csvData = sheet.export(csvFormat=True, keepHidden=keepHidden, allUsers=allUsers, idRename=id_col, altidRename=altid_col)
            self.write(csvData)
            return

        if previewingSession:
            self.displayMessage('Previewing session <a href="%s/_preview/index.html">%s</a><p></p>' % (site_prefix, previewingSession))
            return

        submitDate = ''
        if action in ('_import', '_submit'):
            if not sessionName:
                self.displayMessage('Must specify session name')
                return
            submitDate = self.get_argument('submitdate','')

        if action in ('_roster', '_import', '_submit', '_upload'):
            if action == '_submit':
                # Submit test user
                try:
                    sdproxy.importUserAnswers(sessionName, sdproxy.TESTUSER_ID, '', submitDate=submitDate, source='submit')
                    self.displayMessage('Submit '+sdproxy.TESTUSER_ID+' row')
                except Exception, excp:
                    self.displayMessage('Error in submit for '+sdproxy.TESTUSER_ID+': '+str(excp))

            elif action in ('_roster', '_import'):
                # Import from CSV file
                if 'upload' not in self.request.files:
                    self.displayMessage('No file to upload!')
                    return
                fileinfo = self.request.files['upload'][0]
                fname = fileinfo['filename']
                fbody = fileinfo['body']
                if Options['debug']:
                    print >> sys.stderr, 'ActionHandler:upload', fname, len(fbody), sessionName, submitDate
                uploadedFile = cStringIO.StringIO(fbody)
                if action == '_roster':
                    lastname_col = self.get_argument('lastnamecol','').strip().lower() 
                    firstname_col = self.get_argument('firstnamecol','').strip().lower() 
                    midname_col = self.get_argument('midnamecol','').strip().lower() 
                    id_col = self.get_argument('idcol','').strip().lower() 
                    email_col = self.get_argument('emailcol','').strip().lower() 
                    altid_col = self.get_argument('altidcol','').strip().lower() 
                    errMsg = importRoster(fname, uploadedFile, lastname_col=lastname_col, firstname_col=firstname_col,
                                           midname_col=midname_col, id_col=id_col, email_col=email_col, altid_col=altid_col)
                    if not errMsg:
                        self.displayMessage('Imported roster from '+fname)
                    else:
                        self.displayMessage(errMsg+'\n')
                elif action == '_import':
                    overwrite = self.get_argument('overwrite', '')
                    if not overwrite and any(sdproxy.getRowMap(sessionName, 'submitTimestamp', regular=True).values()):
                        raise tornado.web.HTTPError(403, log_message='CUSTOM:Error: Session %s already has submitted entries. Specify overwrite' % sessionName)
                    if Options['import_params']:
                        importParams = updateImportParams(Options['import_params'])
                    else:
                        importKey = self.get_argument('importkey', '')
                        keyColName = self.get_argument('keycolname', '').strip()
                        skipKeys = self.get_argument('skipkeys', '').strip()
                        if not keyColName:
                            keyColName = importKey

                        importParams = dict(importKey=importKey, keyColName=keyColName, skipKeys=skipKeys)
                        importParams = updateImportParams(Options['import_params'], importParams)

                    missed, errors = importAnswers(sessionName, fname, uploadedFile, importParams, submitDate=submitDate)
                    if not missed and not errors:
                        self.displayMessage('Imported answers from '+fname)
                    else:
                        errMsg = ''
                        if missed:
                            errMsg += 'ERROR: Missed uploading IDs: '+' '.join(missed)+'\n\n'
                        if errors:
                             errMsg += '\n'.join(errors)+'\n'
                        if errMsg:
                            self.displayMessage('<pre>'+errMsg+'</pre>')
            elif action in ('_upload',):
                # Import two files
                if not Options['source_dir']:
                    raise tornado.web.HTTPError(403, log_message='CUSTOM:Must specify source_dir to upload')
                sessionCreate = self.get_argument('sessioncreate', '')

                uploadType = self.get_argument('sessiontype', '')

                sessionNumber = self.get_argument('sessionnumber')
                if uploadType in (RAW_UPLOAD, TOP_LEVEL):
                    sessionNumber = 0
                    sessionName = uploadType
                else:
                    if uploadType not in SESSION_TYPE_SET:
                        raise tornado.web.HTTPError(404, log_message='CUSTOM:Unrecognized session type: '+uploadType)

                    if not sessionNumber.isdigit():
                        self.displayMessage('Invalid session number!')
                        return

                    sessionNumber = int(sessionNumber)
                    sessionName = SESSION_NAME_FMT % (uploadType, sessionNumber) if sessionNumber else 'index'

                sessionModify = sessionName if self.get_argument('sessionmodify', '') else None
                    
                fname1 = ''
                fbody1 = ''
                fname2 = ''
                fbody2 = ''
                if sessionCreate:
                    fname1 = sessionName + '.md'
                    fbody1 = 'BLANK SESSION'
                else:
                    if 'upload1' not in self.request.files and 'upload2' not in self.request.files:
                        self.displayMessage('No session file(s) to upload!')
                        return

                    if 'upload1' in self.request.files:
                        fileinfo1 = self.request.files['upload1'][0]
                        fname1 = fileinfo1['filename']
                        fbody1 = fileinfo1['body']

                    if 'upload2' in self.request.files:
                        fileinfo2 = self.request.files['upload2'][0]
                        fname2 = fileinfo2['filename']
                        fbody2 = fileinfo2['body']

                if Options['debug']:
                    print >> sys.stderr, 'ActionHandler:upload', uploadType, sessionName, sessionModify, fname1, len(fbody1), fname2, len(fbody2)

                try:
                    errMsg = self.uploadSession(uploadType, sessionNumber, fname1, fbody1, fname2, fbody2, modify=sessionModify)
                except Exception, excp:
                    if Options['debug']:
                        import traceback
                        traceback.print_exc()
                    raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in uploading session: '+str(excp))

                if errMsg:
                    self.render('upload.html', site_name=Options['site_name'], session_types=SESSION_TYPES, err_msg=errMsg)
                elif uploadType != RAW_UPLOAD:
                    site_prefix = '/'+Options['site_name'] if Options['site_name'] else ''
                    self.redirect(site_prefix+'/_preview/index.html')
                    return
        else:
            self.displayMessage('Invalid post action: '+action)

    def displayMessage(self, message, back_url=''):
        if isinstance(message, list):
            message = '<pre>\n'+'\n'.join(message)+'\n</pre>\n'
        self.render('message.html', site_name=Options['site_name'], message=message, back_url=back_url)

    def pptx2md(self, filename, file_content, slides_zip=None, zip_images=False):
        import pptx2md
        pptx_opts = {}
        pptx_opts['img_dir'] = filename + '_images'
        if zip_images:
            pptx_opts['img_dir'] += '.zip'
        ppt_parser = pptx2md.PPTXParser(pptx_opts)
        slides_zip_handle = io.BytesIO(slides_zip) if slides_zip else None
        md_text, images_zipdata = ppt_parser.parse_pptx(io.BytesIO(file_content), filename+'.pptx', slides_zip_handle, nofile=True)
        return md_text, images_zipdata


    def get_md_list(self, uploadType, newSession=''):
        md_list = glob.glob(self.site_src_dir+'/*.md') if uploadType == TOP_LEVEL else glob.glob(self.site_src_dir+'/'+uploadType+'/'+uploadType+'[0-9][0-9].md')

        if newSession and (uploadType == TOP_LEVEL or newSession != 'index'):
            newPath = self.site_src_dir+'/'+newSession+'.md' if uploadType == TOP_LEVEL else self.site_src_dir+'/'+uploadType+'/'+newSession+'.md'
            if newPath not in md_list:
                md_list.append(newPath)
        md_list.sort()
        return md_list

    def get_session_names(self, top=False):
        if top:
            tnames = [os.path.splitext(os.path.basename(fpath))[0] for fpath in glob.glob(self.site_src_dir+'/*.md')]
            if 'index' in tnames:
                del tnames[tnames.index('index')]
            tnames.sort()
            return ['index'] + tnames

        fnames = []
        for fname in set(os.path.basename(os.path.dirname(fpath)) for fpath in glob.glob(self.site_src_dir+'/*/*.md')):
            if self.get_md_list(fname):
                fnames.append(fname)
        fnames.sort()
        return fnames

    def get_topnav_list(self, folders_only=False):
        topFiles = [] if folders_only else [os.path.basename(fpath) for fpath in glob.glob(self.site_web_dir+'/*.html')]
        topFolders = [ os.path.basename(os.path.dirname(fpath)) for fpath in glob.glob(self.site_web_dir+'/*/index.html')]
        topFolders2 = [ os.path.basename(os.path.dirname(fpath)) for fpath in glob.glob(self.site_web_dir+'/'+PRIVATE_PATH+'/*/index.html')]
        if 'index.html' in topFiles:
            del topFiles[topFiles.index('index.html')]

        topFiles.sort()
        topFolders.sort()
        topFolders2.sort()

        topnavList = []

        for j, flist in enumerate([topFolders2, topFiles, topFolders]):
            for fname in flist:
                entry = fname if j > 0 else PRIVATE_PATH+'/'+fname
                if entry not in topnavList:
                    topnavList.append(entry)
        if not folders_only:
            topnavList = ['index.html'] + topnavList
        return topnavList

    def uploadSession(self, uploadType, sessionNumber, fname1, fbody1, fname2, fbody2, modify=None):
        # Return null string on success or error message
        if self.previewActive():
            raise Exception('Already previewing session')

        zfile = None
        if fname2:
            if not fname2.endswith('.zip'):
                return 'Invalid zip archive name %s; must have extension .zip' % fname2
            try:
                zfile = zipfile.ZipFile(io.BytesIO(fbody2))
            except Exception, excp:
                raise Exception('Error in loading zip archive: ' + str(excp))

        if uploadType == RAW_UPLOAD:
            if not zfile:
                return 'Error: Must provide Zip archive for raw upload'
            try:
                # Unzip archive to web_dir
                zfile = zipfile.ZipFile(io.BytesIO(fbody2))
                src_list = []
                web_list = []
                for name in zfile.namelist():
                    if '/' not in name and name.endswith('.md'):
                        src_list.append(name)
                    else:
                        web_list.append(name)
                if src_list:
                    zfile.extractall(self.site_web_dir, src_list)
                if web_list:
                    zfile.extractall(self.site_web_dir, web_list)
                msgs = ['Zip archive uploaded']
                errMsgs = self.rebuild(TOP_LEVEL, indexOnly=True)
                if errMsgs and any(errMsgs):
                    msgs += [''] + errMsgs
                self.displayMessage(msgs)
                return ''
            except Exception, excp:
                raise Exception('Error in unzipping raw archive: ' + str(excp))

        if not fname1 or not fbody1:
            if not zfile:
                return 'Error: Must provide .md/.pptx file for upload'
            # Extract Markdown file from zip archive
            topNames = [name for name in zfile.namelist() if '/' not in name and name.endswith('.md')]
            if len(topNames) != 1:
                return 'Error: Expecting single .md file in zip archive'
            fname1 = topNames[0]
            fbody1 = zfile.read(fname1)

        fname, fext = os.path.splitext(fname1)
        if uploadType == TOP_LEVEL:
            sessionName = fname
            src_dir = self.site_src_dir
            web_dir = self.site_web_dir
        else:
            sessionName = SESSION_NAME_FMT % (uploadType, sessionNumber) if sessionNumber else 'index'
            src_dir = self.site_src_dir + '/' + uploadType
            web_dir = self.site_web_dir + privatePrefix(uploadType) + '/' + uploadType

        if sessionName != 'index':
            WSHandler.lockSessionConnections(sessionName, 'Session being modified. Wait ...', reload=False)

        if pacedSession(uploadType) and sessionName != 'index':
            # Lock proxy for preview
            sdproxy.startPreview(sessionName)

        try:
            images_zipdata = None
            if fext == '.pptx':
                md_text, images_zipdata = self.pptx2md(sessionName, fbody1, slides_zip=fbody2, zip_images=True)
                fbody1 = md_text.encode('utf8')
            else:
                if fext != '.md':
                    raise Exception('Invalid file extension %s; expecting .pptx or .md' % fext)
                if zfile:
                    images_zipdata = fbody2

            src_path = src_dir + '/' + sessionName + '.md'
            overwrite = os.path.exists(src_path)
            image_dir = sessionName+'_images'

            extraOpts = {}
            extraOpts['overwrite'] = 1 if overwrite else 0
            if modify:
                extraOpts['modify_sessions'] = modify

            retval = self.compile(uploadType, src_path=src_path, contentText=fbody1, images_zipdata=images_zipdata, dest_dir=web_dir,
                                              image_dir=image_dir, extraOpts=extraOpts)

            if 'md_params' not in retval:
                raise Exception('\n'.join(retval.get('messages',[]))+'\n')

            # Save current preview state
            if pacedSession(uploadType) and sessionName != 'index':
                sdproxy.savePreview()

            self.previewState['md'] = fbody1
            self.previewState['md_defaults'] = retval['md_params'].get('md_defaults', '')
            self.previewState['md_slides'] = retval['md_params'].get('md_slides', [])
            self.previewState['new_image_number'] = retval['md_params'].get('new_image_number', 0)
            self.previewState['HTML'] = retval['out_html']
            self.previewState['TOC'] = retval['toc_html']
            self.previewState['messages'] = retval['messages']
            self.previewState['type'] = uploadType
            self.previewState['number'] = sessionNumber
            self.previewState['name'] = sessionName
            self.previewState['src_dir'] = src_dir
            self.previewState['web_dir'] = web_dir
            self.previewState['image_dir'] = image_dir
            self.previewState['image_zipbytes'] = io.BytesIO(images_zipdata) if images_zipdata else None
            self.previewState['image_zipfile'] = zipfile.ZipFile(self.previewState['image_zipbytes'], 'a') if images_zipdata else None
            self.previewState['image_paths'] = dict( (os.path.basename(fpath), fpath) for fpath in self.previewState['image_zipfile'].namelist() if os.path.basename(fpath)) if images_zipdata else {}

            self.previewState['overwrite'] = overwrite
            self.previewState['modimages'] = ''
            self.previewState['rollover'] = None
            return ''

        except Exception, err:
            if Options['debug']:
                import traceback
                traceback.print_exc()
            self.previewClear(revert=True, original=True)
            if sessionName != 'index':
                WSHandler.lockSessionConnections(sessionName, '', reload=False)
            return 'Error:\n'+err.message+'\n'

    def compile(self, uploadType, src_path='', contentText='', images_zipdata='', dest_dir='', image_dir='', indexOnly=False,
                force=False, extraOpts={}):
        # If src_path, compile single .md file, returning output
        # Else, compile all files of that type, updating index etc.
        configOpts, defaultOpts = self.get_config_opts(uploadType, text=contentText, topnav=True, dest_dir=dest_dir,
                                                       image_dir=image_dir, no_make=force)

        configOpts.update(extraOpts)

        images_zipdict = {}
        if src_path:
            sessionName = os.path.splitext(os.path.basename(src_path))[0]
            if images_zipdata:
                images_zipdict[sessionName] = images_zipdata
        else:
            sessionName = ''

        filePaths = self.get_md_list(uploadType, newSession=sessionName)
        if not filePaths:
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Empty session folder '+uploadType)

        if uploadType != TOP_LEVEL:
            if sessionName == 'index':
                configOpts['toc_header'] = io.BytesIO(contentText)
            else:
                ind_path = os.path.join(os.path.dirname(filePaths[0]), 'index.md')
                if os.path.exists(ind_path):
                    configOpts['toc_header'] = ind_path

        fileNames = [os.path.basename(fpath) for fpath in filePaths]

        if src_path:
            fileHandles = [io.BytesIO(contentText) if fpath == src_path else None for fpath in filePaths]
        elif indexOnly:
            fileHandles = [None for fpath in filePaths]
        else:
            fileHandles = [open(fpath) for fpath in filePaths]

        if Options['debug']:
            print >> sys.stderr, 'sdserver.compile:', uploadType, repr(src_path), indexOnly, force, 'OPTS', configOpts.get('make'), configOpts.get('make_toc'), configOpts.get('strip'), defaultOpts.get('strip'), configOpts.get('pace'), defaultOpts.get('pace'), fileNames

        return_html = bool(src_path)

        try:
            retval = slidoc.process_input(fileHandles, filePaths, configOpts, default_args_dict=defaultOpts, return_html=return_html,
                                          images_zipdict=images_zipdict, http_post_func=http_sync_post, return_messages=True)
        except Exception, excp:
            if Options['debug']:
                import traceback
                traceback.print_exc()
            # Error return
            return {'messages': ['Error in compile: '+excp.message]}
            
        if return_html:
            if Options['debug'] and retval.get('messages'):
                print >> sys.stderr, 'sdserver.compile:', src_path, ' '.join(fileNames)+'\n', '\n'.join(retval['messages'])
            return retval
        else:
            # Normal return
            return {'messages': retval.get('messages', []) if retval else []}

    def rebuild(self, uploadType='', indexOnly=False, force=False, log_dict=False):
        if uploadType:
            utypes = [uploadType] if uploadType != TOP_LEVEL else []
        else:
            utypes = self.get_session_names()

        msg_dict = {}
        msg_list = []
        if Options['debug'] :
            print >> sys.stderr, 'sdserver.rebuild:', utypes
        for utype in utypes:
            retval = self.compile(utype, dest_dir=self.site_web_dir+privatePrefix(utype)+'/'+utype, indexOnly=indexOnly, force=force)
            msgs = retval.get('messages',[])
            msg_dict[utype] = msgs
            if msgs:
                msg_list += msgs + ['']

        retval = self.compile(TOP_LEVEL, dest_dir=self.site_web_dir, indexOnly=indexOnly)
        msgs = retval.get('messages',[])
        msg_dict[TOP_LEVEL] = msgs
        if msgs:
            msg_list += msgs

        return msg_dict if log_dict else msg_list


    def imageUpload(self, sessionName, imageFile, fname, fbody):
        if Options['debug']:
            print >> sys.stderr, 'ActionHandler:imageUpload', sessionName, imageFile, fname, len(fbody)
        if not self.previewActive():
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Not previewing session')
        if not self.previewState['image_zipfile']:
            self.previewState['image_zipbytes'] = io.BytesIO()
            self.previewState['image_zipfile'] = zipfile.ZipFile(self.previewState['image_zipbytes'], 'a')
        imagePath = sessionName+'_images/' + imageFile
        self.previewState['image_zipfile'].writestr(imagePath, fbody)
        self.previewState['image_paths'][imageFile] = imagePath
        self.set_header('Content-Type', 'application/json')
        self.write( json.dumps( {'result': 'success'} ) )

    def displayPreview(self, filepath=None):
        if not self.previewActive():
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Not previewing session')
        uploadType = self.previewState['type']
        sessionName = self.previewState['name']
        content = None
        mime_type = ''
        if not filepath or filepath == 'index.html':
            mime_type = 'text/html'
            if sessionName == 'index' and uploadType != TOP_LEVEL:
                content = self.previewState['TOC']
            else:
                content = self.previewState['HTML']
        elif filepath == '_messages':
            mime_type = 'text/plain'
            content = '\n'.join(self.previewState['messages'])
        else:
            # Image file?
            fname, fext = os.path.splitext(os.path.basename(filepath))
            mime_type = self.mime_types.get(fext.lower())
            if mime_type:
                if self.previewState['image_zipfile'] and fname+fext in self.previewState['image_paths']:
                    content = self.previewState['image_zipfile'].read(self.previewState['image_paths'][fname+fext])
                else:
                    web_dir = self.site_web_dir if uploadType == TOP_LEVEL else self.site_web_dir + privatePrefix(uploadType)+'/' + uploadType
                    img_path = web_dir+'/'+sessionName+'_images/'+fname+fext
                    if os.path.exists(img_path):
                        with open(img_path) as f:
                            content = f.read()

        if mime_type and content is not None:
            self.set_header('Content-Type', mime_type)
            self.write(content)
        else:
            raise tornado.web.HTTPError(404)

    def extractFolder(self, zfile, dirpath, folder='', clear=False):
        # Extract only files in a folder
        # If folder, rename folder
        # If clear, clear old files in folder
        renameFolder = False
        extractList = []
        for name in zfile.namelist():
            if '/' not in name:
                continue
            extractList.append(name)
            if folder and not name.startswith(folder+'/'):
                renameFolder = True

        if not extractList:
            return

        if clear:
            clearpath = folder
            if dirpath:
                clearpath = os.path.join(dirpath, clearpath)
            if clearpath:
                for fname in os.listdir(clearpath):
                    fpath = os.path.join(clearpath, fname)
                    if os.path.isfile(fpath):
                        os.remove(fpath)

        if not renameFolder:
            zfile.extractall(dirpath, extractList)
            return

        # Extract in renamed folder
        for name in extractList:
            outpath = os.path.join(folder, os.path.basename(name))
            if dirpath:
                outpath = os.path.join(dirpath, outpath)
            with open(outpath, 'wb') as f:
                f.write(zfile.read(name))
            

    def acceptPreview(self, rollover=False):
        sessionName = self.previewState['name']
        uploadType = self.previewState['type']

        try:
            if not os.path.exists(self.previewState['src_dir']):
                os.makedirs(self.previewState['src_dir'])

            with open(self.previewState['src_dir']+'/'+sessionName+'.md', 'w') as f:
                f.write(self.previewState['md'])

            if self.previewState['image_zipfile'] and self.previewState['modimages']:
                self.extractFolder(self.previewState['image_zipfile'], self.previewState['src_dir'], folder=self.previewState['image_dir'],
                                   clear=(self.previewState['modimages'] == 'clear'))

            if not os.path.exists(self.previewState['web_dir']):
                os.makedirs(self.previewState['web_dir'])

            if sessionName != 'index' or uploadType == TOP_LEVEL:
                with open(self.previewState['web_dir']+'/'+sessionName+'.html', 'w') as f:
                    f.write(self.previewState['HTML'])

            if sessionName != 'index' or uploadType != TOP_LEVEL:
                with open(self.previewState['web_dir']+'/index.html', 'w') as f:
                    f.write(self.previewState['TOC'])

            if self.previewState['image_zipfile']:
                self.extractFolder(self.previewState['image_zipfile'], self.previewState['web_dir'], folder=self.previewState['image_dir'])

        except Exception, excp:
            self.previewClear(revert=True)   # Revert to start of preview
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in saving session %s: %s' % (sessionName, excp))

        redirectURL = ''
        if Options['site_name']:
            redirectURL += '/' + Options['site_name']
        if uploadType == TOP_LEVEL:
            redirectURL += '/' + sessionName + '.html'
        else:
            redirectURL += privatePrefix(uploadType)+'/'+uploadType+'/index.html'

        rolloverParams = self.previewState['rollover']
        self.previewClear(revert=True)   # Revert to start of preview

        if sessionName != 'index':
            WSHandler.lockSessionConnections(sessionName, 'Session modified. Reload page', reload=True)
        errMsgs = self.rebuild(uploadType, indexOnly=True)
        if errMsgs and any(errMsgs):
            msgs = ['Saved changes to session '+sessionName] + [''] + errMsgs
            self.displayMessage(msgs)
            return

        if not rolloverParams:
            self.redirect(redirectURL)
            return

        # Truncate previous rolled over session
        try:
            errMsg = self.uploadSession(rolloverParams['uploadType'], rolloverParams['sessionNumber'], rolloverParams['sessionName']+'.md', rolloverParams['sessionText'], rolloverParams['fname2'], rolloverParams['fbody2'], modify='truncate')

        except Exception, excp:
            if Options['debug']:
                import traceback
                traceback.print_exc()
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in truncating rolled over session %s: %s' % (sessionName, excp))

        if errMsg:
            if self.previewState:
                self.discardPreview()
            self.displayMessage('Error in truncating rolled over session '+sessionName+': '+errMsg)
            return

        self.previewState['modimages'] = 'clear'
        if not rollover:
            self.acceptPreview(rollover=True)


    def discardPreview(self):
        if not self.previewActive():
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Not previewing session')
        sessionName = self.previewState['name']
        self.previewClear(revert=True, original=True)
        if sessionName != 'index':
            WSHandler.lockSessionConnections(sessionName, 'Session mods discarded. Reload page', reload=True)
        self.displayMessage('Discarded changes')

    def previewClear(self, revert=False, original=False):
        if sdproxy.previewingSession():
            if revert:
                sdproxy.revertPreview(original=original)
            else:
                sdproxy.endPreview()
        self.previewState.clear()

    def extract_slides(self, src_path, web_path):
        try:
            return slidoc.extract_slides(src_path, web_path)
        except Exception, excp:
            if Options['debug']:
                import traceback
                traceback.print_exc()
            raise tornado.web.HTTPError(404, log_message='CUSTOM:'+str(excp))

    def extract_slide_range(self, src_path, web_path, start_slide=0, end_slide=0, renumber=0, session_name=''):
        try:
            return slidoc.extract_slide_range(src_path, web_path, start_slide=start_slide, end_slide=end_slide,
                                              renumber=renumber, session_name=session_name)
        except Exception, excp:
            if Options['debug']:
                import traceback
                traceback.print_exc()
            raise tornado.web.HTTPError(404, log_message='CUSTOM:'+str(excp))

    def startEdit(self, sessionName):
        sessionName = md2md.stringify(sessionName)
        sessionText = None
        if self.previewState:
            sessionName = self.previewState['name']
            sessionText = self.previewState['md']
            uploadType = self.previewState['type']
            if uploadType != TOP_LEVEL and sessionName == 'index':
                sessionName = SESSION_NAME_FMT % (uploadType, 0)
        elif not sessionName:
            sessionName = self.get_argument('sessionname')

        uploadType, sessionNumber, src_path, web_path, web_images = self.getUploadType(sessionName)

        slideNumber = self.get_argument('slide', '')
        if slideNumber.isdigit():
            slideNumber = int(slideNumber)
        else:
            slideNumber = None

        if slideNumber:
            if self.previewState:
                if self.previewState['md_slides'] is None:
                    raise tornado.web.HTTPError(404, log_message='CUSTOM:Unable to edit individual slides in preview')
                md_defaults = self.previewState['md_defaults']
                md_slides = self.previewState['md_slides']
                new_image_number = self.previewState['new_image_number']
                if slideNumber > len(md_slides):
                    raise tornado.web.HTTPError(404, log_message='CUSTOM:Invalid slide number %d' % slideNumber)
                slideText = md_slides[slideNumber-1]
            else:
                md_defaults, slideText, _, new_image_number = self.extract_slide_range(src_path, web_path, start_slide=slideNumber, end_slide=slideNumber)

            slideText = strip_slide(slideText)
            retval = {'slideText': slideText, 'newImageName': md2md.IMAGE_FMT % new_image_number}
            self.set_header('Content-Type', 'application/json')
            self.write( json.dumps(retval) )
            return

        if sessionText is None:
            try:
                with open(src_path) as f:
                    sessionText = f.read()
            except Exception, excp:
                raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in reading session from %s: %s' % (src_path, excp))

        if isinstance(sessionText, unicode):
            sessionText = sessionText.encode('utf-8')

        if self.previewState:
            discard_url = '_preview/index.html'
        else:
            discard_url = ''

        self.render('edit.html', site_name=Options['site_name'], session_name=sessionName,
                     session_text=sessionText, discard_url=discard_url, err_msg='')

    def postEdit(self, sessionName, sessionText, fromSession='', fromSite='', slideNumber=None, newNumber=None, deleteSlide='', modify=None):
        sessionName, sessionText, fromSession, fromSite = md2md.stringify(sessionName, sessionText, fromSession, fromSite)

        sameSession = (not fromSession or fromSession == sessionName) and (not fromSite or fromSite == Options['site_name'])

        prevPreviewState = self.previewState.copy() 
        uploadType, sessionNumber, src_path, web_path, web_images = self.getUploadType(sessionName)
        if uploadType != TOP_LEVEL and not sessionNumber:
            sessionName = 'index'

        slide_images_zip = None
        image_zipdata = ''
        if slideNumber:
            # Editing slide
            if self.previewState:
                if self.previewState['md_slides'] is None:
                    raise tornado.web.HTTPError(404, log_message='CUSTOM:Unable to edit individual slides in preview')
                md_defaults = self.previewState['md_defaults']
                md_slides = self.previewState['md_slides'][:]  # Shallow copy of slides so as not overwrite any backup copy
                new_image_number = self.previewState['new_image_number']
            else:
                md_defaults, md_slides, new_image_number = self.extract_slides(src_path, web_path)
                if not sameSession:
                    _, _, image_zipdata, _ = self.extract_slide_range(src_path, web_path) # Redundant, but need images

            if sameSession and slideNumber > len(md_slides):
                raise tornado.web.HTTPError(404, log_message='CUSTOM:Invalid slide number %d' % slideNumber)

            if not sameSession:
                # Insert slide from another session
                _, _, from_src, from_web, _ = self.getUploadType(fromSession, siteName=fromSite)
                _, slideText, slide_images_zip, new_image_number = self.extract_slide_range(from_src, from_web, start_slide=slideNumber, end_slide=slideNumber, renumber=new_image_number, session_name=sessionName)

                if not newNumber or newNumber > len(md_slides)+1:
                    raise tornado.web.HTTPError(404, log_message='CUSTOM:Invalid insert slide number %d' % newNumber)
                insertText = pad_slide(slideText)
                md_slides.insert(newNumber-1, insertText)
                splice_slides(md_slides, newNumber-1)
                splice_slides(md_slides, newNumber)

            elif deleteSlide:
                # Delete slide
                del md_slides[slideNumber-1]
                splice_slides(md_slides, slideNumber-2)

            elif newNumber:
                # Move slide to new location
                if newNumber > len(md_slides) or newNumber == slideNumber:
                    raise tornado.web.HTTPError(404, log_message='CUSTOM:Invalid move to slide number %d' % newNumber)

                moveText = pad_slide(md_slides[slideNumber-1])

                if newNumber < slideNumber:
                    # Move before current position
                    md_slides.insert(newNumber-1, moveText)
                    splice_slides(md_slides, newNumber-2)
                    splice_slides(md_slides, newNumber-1)

                    del md_slides[slideNumber]
                    splice_slides(md_slides, slideNumber-1)

                elif newNumber > slideNumber:
                    # Move after current position
                    md_slides.insert(newNumber, moveText)
                    splice_slides(md_slides, newNumber-1)
                    splice_slides(md_slides, newNumber)

                    del md_slides[slideNumber-1]
                    splice_slides(md_slides, slideNumber-2)

            else:
                # Modify slide
                md_slides[slideNumber-1] = pad_slide(sessionText)
                splice_slides(md_slides, slideNumber-2)
                splice_slides(md_slides, slideNumber-1)

            sessionText = md_defaults + strip_slide( ''.join(md_slides) )

        fbody2 = ''
        fname2 = ''
        if self.previewState:
            if self.previewState['image_zipbytes']:
                self.previewState['image_zipfile'].close()
                fbody2 = self.previewState['image_zipbytes'].getvalue()
                fname2 = sessionName+'_images.zip'
            self.previewClear()
        elif image_zipdata:
            fbody2 = image_zipdata
            fname2 = sessionName+'_images.zip'

        modimages = ''
        if slide_images_zip:
            # Append new slide images
            modimages = 'append'
            ifile = zipfile.ZipFile(io.BytesIO(slide_images_zip))
            stream = io.BytesIO(fbody2)
            zfile = zipfile.ZipFile(stream, 'a')
            for ipath in ifile.namelist():
                zfile.writestr(sessionName+'_images/'+os.path.basename(ipath), ifile.read(ipath))
            zfile.close()
            fbody2 = stream.getvalue()
            fname2 = sessionName+'_images.zip'

        try:
            errMsg = self.uploadSession(uploadType, sessionNumber, sessionName+'.md', sessionText, fname2, fbody2, modify=modify)
        except Exception, excp:
            if Options['debug']:
                import traceback
                traceback.print_exc()
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in editing session %s: %s' % (sessionName, excp))

        if errMsg:
            if prevPreviewState:
                self.previewState.update(prevPreviewState)
            if slideNumber:
                raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in editing session %s: %s' % (sessionName, errMsg))

            if self.previewState:
                discard_url = '_preview/index.html'
            else:
                discard_url = ''
            self.render('edit.html', site_name=Options['site_name'], session_name=sessionName, session_text=sessionText, discard_url=discard_url, err_msg=errMsg)
            return

        self.previewState['modimages'] = modimages
        site_prefix = '/'+Options['site_name'] if Options['site_name'] else ''
        if slideNumber:
            self.set_header('Content-Type', 'application/json')
            self.write( json.dumps( {'result': 'success'} ) )
            return
        else:
            self.redirect(site_prefix+'/_preview/index.html')

    def rollover(self, sessionName, slideNumber=None):
        sessionName = md2md.stringify(sessionName)
        if self.previewState:
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Rollover not permitted in preview state')

        uploadType, sessionNumber, src_path, web_path, web_images = self.getUploadType(sessionName)
        if uploadType == TOP_LEVEL:
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Rollover not permitted for top-level sessions')

        sessionEntries = sdproxy.lookupValues(sessionName, ['paceLevel'], sdproxy.INDEX_SHEET)

        lastSlide = None
        try:
            userEntries = sdproxy.lookupValues(sdproxy.TESTUSER_ID, ['submitTimestamp', 'lastSlide'], sessionName)
            if sessionEntries['paceLevel'] == sdproxy.ADMIN_PACE and not userEntries['submitTimestamp']:
                raise tornado.web.HTTPError(404, log_message='CUSTOM:Rollover not permitted for unsubmitted admin-paced session '+sessionName)
            lastSlide = userEntries['lastSlide']
        except Exception, excp:
            print >> sys.stderr, 'sdserver.rollover', excp
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Unable to access rollover testuser entry for session '+sessionName)

        if not lastSlide:
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Invalid last slide entry to rollover session '+sessionName)

        _, md_slides, __ = self.extract_slides(src_path, web_path)

        if lastSlide >= len(md_slides):
            raise tornado.web.HTTPError(404, log_message='CUSTOM:No slides left to rollover session '+sessionName)

        if Options['debug']:
            print >> sys.stderr, 'ActionHandler:rollover', sessionName, slideNumber, lastSlide, len(md_slides)

        truncate_defaults, truncateText, truncate_images_zip, _ = self.extract_slide_range(src_path, web_path, start_slide=1, end_slide=lastSlide, renumber=1, session_name=sessionName)

        truncateText = truncate_defaults + strip_slide(truncateText)
        rolloverParams = {'uploadType': uploadType,
                          'sessionNumber': sessionNumber,
                          'sessionName': sessionName,
                          'sessionText': truncateText,
                          'fname2': '',
                          'fbody2': ''}
        if truncate_images_zip:
            rolloverParams['fbody2'] = truncate_images_zip
            rolloverParams['fname2'] = sessionName+'_images.zip'

        start_slide = min(slideNumber+1, lastSlide+1) if slideNumber else lastSlide+1
        _, rolloverText, rollover_images_zip, new_image_number = self.extract_slide_range(src_path, web_path, start_slide=start_slide, renumber=1, session_name=sessionName)

        sessionNext = SESSION_NAME_FMT % (uploadType, sessionNumber+1)
        _, __, src_next, web_next, web_images_next = self.getUploadType(sessionNext)

        if os.path.exists(src_next):
            next_defaults, nextText, next_images_zip, new_image_number = self.extract_slide_range(src_next, web_next, renumber=new_image_number, session_name=sessionNext)
        else:
            next_defaults, nextText, next_images_zip, new_image_number = truncate_defaults, '', None, new_image_number

        combine_slides = [pad_slide(rolloverText), nextText]
        splice_slides(combine_slides, 0)

        combineText = next_defaults + strip_slide( ''.join(combine_slides) )

        fbody2 = ''
        fname2 = ''
        if rollover_images_zip or next_images_zip:
            ifile = zipfile.ZipFile(io.BytesIO(rollover_images_zip or ''))
            stream = io.BytesIO(next_images_zip or '')
            zfile = zipfile.ZipFile(stream, 'a')
            for ipath in ifile.namelist():
                zfile.writestr(sessionNext+'_images/'+os.path.basename(ipath), ifile.read(ipath))
            zfile.close()
            fbody2 = stream.getvalue()
            fname2 = sessionNext+'_images.zip'

        try:
            errMsg = self.uploadSession(uploadType, sessionNumber+1, sessionNext+'.md', combineText, fname2, fbody2, modify='overwrite')
        except Exception, excp:
            if Options['debug']:
                import traceback
                traceback.print_exc()
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in rolling over session %s: %s' % (sessionName, excp))

        if errMsg:
            if self.previewState:
                self.discardPreview()
            self.displayMessage('Error in rolling over session '+sessionNext+': '+errMsg)
            return

        self.previewState['rollover'] = rolloverParams
        self.previewState['modimages'] = 'clear'
        self.set_header('Content-Type', 'application/json')
        self.write( json.dumps( {'result': 'success'} ) )

            
SECTION_HEADER_RE = re.compile(r' {0,3}#{1,2}[^#]')
def splice_slides(md_slides, offset):
    # Ensure that either --- or ## is present at slide boundary
    if offset < 0:
        return
    hrule = (offset+1 < len(md_slides)) and not SECTION_HEADER_RE.match(md_slides[offset+1].lstrip('\n'))
    md_slides[offset] = pad_slide(md_slides[offset], hrule=hrule)

def strip_slide(slide_text):
    # Strip any trailing ---
    if slide_text.rstrip()[-3:] == '---':
        return pad_slide( slide_text.rstrip().rstrip('-') )
    else:
        return slide_text

def pad_slide(slide_text, hrule=False):
    # Ensure that slide text ends with two newlines (preceded, optionally, by hrule ---)
    add_hrule = hrule and slide_text.rstrip()[-3:] != '---'
    if not slide_text.endswith('\n\n'):
        if slide_text.endswith('\n'):
            slide_text += '\n'
        else:
            slide_text += '\n\n'
    if add_hrule:
        slide_text += '---\n\n'
    return slide_text

class AuthActionHandler(ActionHandler):
    @tornado.web.authenticated
    def get(self, subpath, inner=None):
        if self.check_admin_access():
            return self.getAction(subpath)
        raise tornado.web.HTTPError(403)

class UserActionHandler(ActionHandler):
    @tornado.web.authenticated
    def get(self, subpath=''):
        action, sep, subsubpath = subpath.partition('/')
        if action == '_grades':
            if self.check_admin_access():
                if not subsubpath:
                    self.redirect(('/'+Options['site_name'] if Options['site_name'] else '') + '/_roster')
                    return
                userId = subsubpath
            else:
                userId = self.get_id_from_cookie()
            grades = sdproxy.lookupGrades(userId)
            if not grades:
                raise tornado.web.HTTPError(403, log_message='CUSTOM:Failed to access grades for user %s' % userId)
            self.render('grades.html', site_name=Options['site_name'], user_id=userId, grades=grades)

        raise tornado.web.HTTPError(404)

def modify_user_auth(args, socketId=None):
    # Re-create args.token for each site
    if not Options['site_name'] or not args.get('token'):
        return

    if ':' in args['token']:
        effectiveId, adminId, role, sites, userToken = args['token'].split(':')
        if userToken != gen_proxy_auth_token(adminId, role=role, sites=sites, root=True):
            raise Exception('Invalid admin token: '+args['token'])

        if socketId and socketId != adminId:
            raise Exception('Token admin id mismatch: %s != %s' % (socketId, adminId))

        if not role and sites and Options['site_name']:
            role = sdproxy.getSiteRole(Options['site_name'], sites) or ''

        if not role:
            if effectiveId == adminId and not args.get('admin'):
                # Allow non-admin access to site
                args['token'] = gen_proxy_auth_token(adminId)
                return
            raise Exception('Token disallowed by site for admin %s: %s' % (adminId, Options['site_name']))

        if role in (sdproxy.ADMIN_ROLE, sdproxy.GRADER_ROLE):
            # Site admin token
            args['token'] = effectiveId+gen_proxy_auth_token(adminId, role, prefixed=True)
        else:
            raise Exception('Invalid role %s for admin user %s' % (role, adminId))

    elif args.get('id'):
        userId = args['id']
        if socketId and socketId != userId:
            raise Exception('Token user id mismatch: %s != %s' % (socketId, userId))

        if args['token'] == gen_proxy_auth_token(userId, root=True):
            # Site user token
            args['token'] = gen_proxy_auth_token(userId)
        else:
            raise Exception('Invalid token %s for user %s' % (args['token'], userId))

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

        # Replace root-signed tokens with site-specific tokens
        modify_user_auth(args)
        if (args.get('action') or args.get('modify')) and Options['gsheet_url'] and not Options['dry_run']:
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
                response = yield http_client.fetch(Options['gsheet_url'], method='POST', headers=None, body=body)
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

class ConnectionList(list):
    def __init__(self, *args):
        list.__init__(self, *args)
        self.sd_role = None

class WSHandler(tornado.websocket.WebSocketHandler, UserIdMixin):
    _connections = defaultdict(functools.partial(defaultdict,ConnectionList))
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
        sessionConnections = cls._connections.get(path,{})
        for userId in userIdList:
            if excludeId and userId == excludeId:
                continue
            if Options['debug']:
                print >> sys.stderr, "DEBUG: sdserver.closeConnections", 'Closing connections for user:', userId
            for connection in sessionConnections.get(userId,[])[:]:  # connection list may be altered by close
                connection.close()

    @classmethod
    def lockConnections(cls, path, userId, lock_msg, excludeConnection=None, reload=False):
        # Lock all socket connections for specified path/user (to prevent write conflicts)
        # (Null string for lock_msg unlocks)
        for connection in cls._connections.get(path,{}).get(userId,[]):
            if connection is excludeConnection:
                continue
            connection.locked = lock_msg
            connection.write_message(json.dumps([0, 'lock', [connection.locked, reload] ]))

    @classmethod
    def lockSessionConnections(cls, sessionName, lock_msg, reload=False):
        # Lock all socket connections for specified session (for uploads/modifications)
        # (Null string for lock_msg unlocks)
        for userId, connections in cls.get_connections(sessionName).items():
            for connection in connections:
                connection.locked = lock_msg
                connection.write_message(json.dumps([0, 'lock', [connection.locked, reload]] ))

    @classmethod
    def processMessage(cls, fromUser, fromRole, fromName, message, allStatus=False, source=''):
        # Return null string on success or error message
        print >> sys.stderr, 'sdserver.processMessage:', fromUser, fromRole, fromName, message

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
        admin_found = ''
        for connId, connections in session_connections.items():
            if connections.sd_role == sdproxy.ADMIN_ROLE:
                admin_found = connId
                break

        if not admin_found:
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

        errMsg = cls.processMessageAux(path, fromUser, retval['value'], retval['headers'], questionAttrs, message)

        if errMsg:
            cls._interactiveErrors[fromUser] = errMsg
            if Options['debug']:
                print >> sys.stderr, 'sdserver.processMessage:', errMsg
        else:
            if fromUser in cls._interactiveErrors:
                del cls._interactiveErrors[fromUser]
            
        cls.sendEvent(path, fromUser, fromRole, ['', 2, 'Share.answerNotify.'+slideId, [qnumber, cls._interactiveErrors]])
        return errMsg

    @classmethod
    def processMessageAux(cls, path, fromUser, row, headers, questionAttrs, message):
        sessionName = cls.get_path_base(path)
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
            cls.closeConnections(path, teamModifiedIds)

        return ''
            
    @classmethod
    def sendEvent(cls, path, fromUser, fromRole, args):
        # event_target: '*' OR '' (for server) (IGNORED FOR NOW)
        # event_type = -1 immediate, 0 buffer, n >=1 (overwrite matching n name+args else buffer)
        # event_name = [plugin.]event_name[.slide_id]
        evTarget, evType, evName, evArgs = args
        if Options['debug'] and not evName.startswith('Timer.clockTick'):
            print >> sys.stderr, 'sdserver.sendEvent: event', fromUser, evType, evName
        pathConnections = cls._connections[path]
        for toUser, connections in pathConnections.items():
            if toUser == fromUser:
                continue
            if fromRole == sdproxy.ADMIN_ROLE:
                # From special user: broadcast to all but the sender
                pass
            elif connections.sd_role == sdproxy.ADMIN_ROLE:
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
        self.pathUser = (path, self.userId)
        self.userRole = self.get_id_from_cookie(role=True, for_site=Options['site_name'])
        connectionList = self._connections[self.pathUser[0]][self.pathUser[1]]
        if not connectionList:
            connectionList.sd_role = self.userRole
        connectionList.append(self)
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
                        self.lockConnections(self.pathUser[0], self.pathUser[1], 'Session locked due to modifications by another browser window. Reload page, if necessary.', excludeConnection=self)

                modify_user_auth(args, self.pathUser[1])
                retObj = sdproxy.sheetAction(args)

                teamModifiedIds = retObj.get('info', {}).get('teamModifiedIds')
                if teamModifiedIds:
                    # Close other connections for the same team
                    self.closeConnections(self.pathUser[0], teamModifiedIds, excludeId=self.userId)

            elif method == 'interact':
                if self.userRole == sdproxy.ADMIN_ROLE:
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
                self.sendEvent(self.pathUser[0], self.pathUser[1], self.userRole, args)

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
        # Force validation of cache
        self.set_header('Server', SERVER_NAME)
        self.set_header('Cache-Control', 'no-cache, must-revalidate, max-age=0')
    
    def write_error(self, status_code, **kwargs):
        err_cls, err, traceback = kwargs['exc_info']
        if getattr(err, 'log_message', None) and err.log_message.startswith('CUSTOM:'):
            self.write('<html><body><h3>%s</h3></body></html>' % err.log_message[len('CUSTOM:'):])
        else:
            super(BaseStaticFileHandler, self).write_error(status_code, **kwargs)

class AuthStaticFileHandler(BaseStaticFileHandler, UserIdMixin):
    def get_current_user(self):
        # Return None only to request login; else raise HTTPError do deny access (to avoid looping)
        sessionName = self.get_path_base(self.request.path, sessions_only=True)
        userId = self.get_id_from_cookie() or None
        siteRole = self.get_id_from_cookie(role=True, for_site=Options['site_name'])  # May be None

        if Options['debug']:
            print >> sys.stderr, "AuthStaticFileHandler.get_current_user", userId, repr(siteRole), Options['site_number'], sessionName, self.request.path, self.request.query, Options['dry_run'], Options['lock_proxy_url']

        if Options['server_url'] == 'http://localhost' or Options['server_url'].startswith('http://localhost:'):
            # Batch auto login for localhost through query parameter: ?auth=userId:token
            query = self.request.query
            if query.startswith('auth='):
                qauth = query[len('auth='):]
                userId, token = qauth.split(':')
                if token == Options['auth_key']:
                    data = {'batch':1}
                elif token == gen_proxy_auth_token(userId, root=True):
                    data = {}
                else:
                    raise tornado.web.HTTPError(404)
                name = sdproxy.lookupRoster('name', userId) or ''
                print >> sys.stderr, "AuthStaticFileHandler.get_current_user: BATCH ACCESS", self.request.path, userId, name
                self.set_id(userId, displayName=name, data=data)

        if ActionHandler.previewState.get('name'):
            if sessionName and sessionName.startswith(ActionHandler.previewState['name']):
                if siteRole == sdproxy.ADMIN_ROLE:
                    preview_url = '_preview/index.html'
                    raise tornado.web.HTTPError(404, log_message='CUSTOM:Use %s/%s to view session %s' % (Options['site_name'], preview_url, ActionHandler.previewState['name']))
                else:
                    raise tornado.web.HTTPError(404, log_message='CUSTOM:Session not currently accessible')

        if self.request.path.startswith('/'+ADMIN_PATH):
            # Admin path accessible only to dry_run (preview) or wet run using proxy_url
            if not Options['dry_run'] and not Options['lock_proxy_url']:
                raise tornado.web.HTTPError(404)

        if Options['site_restricted'] and not siteRole:
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
            elif sessionName and sessionName.endswith('-'+userId) or siteRole == sdproxy.ADMIN_ROLE:
                return userId
            raise tornado.web.HTTPError(404)

        elif ('/'+PRIVATE_PATH) in self.request.path:
            # Paths containing '/'+PRIVATE_PATH are always protected
            if not userId:
                return None
            if sessionName and sessionName != 'index':
                # Session access checks
                gradeDate = None
                releaseDate = None
                sessionType, _ = getSessionType(sessionName)
                if pacedSession(sessionType):
                    indexSheet = sdproxy.getSheet(sdproxy.INDEX_SHEET, optional=True)
                    if not indexSheet:
                        raise tornado.web.HTTPError(404, log_message='CUSTOM:No index sheet for paced session '+sessionName)
                    try:
                        sessionEntries = sdproxy.lookupValues(sessionName, ['gradeDate', 'releaseDate'], sdproxy.INDEX_SHEET)
                        gradeDate = sessionEntries['gradeDate']
                        releaseDate = sessionEntries['releaseDate']
                    except Exception, excp:
                        print >> sys.stderr, "AuthStaticFileHandler.get_current_user", str(excp)
                        raise tornado.web.HTTPError(404, log_message='CUSTOM:Session %s unavailable' % sessionName)

                if Options['start_date']:
                    startDate = sliauth.epoch_ms(Options['start_date'])
                    if isinstance(releaseDate, datetime.datetime) and sliauth.epoch_ms(releaseDate) < startDate:
                        raise tornado.web.HTTPError(404, log_message='CUSTOM:release_date %s must be after start_date %s for session %s' % (releaseDate, Options['start_date'], sessionName) )
                    elif gradeDate and sliauth.epoch_ms(gradeDate) < startDate:
                        raise tornado.web.HTTPError(404, log_message='CUSTOM:grade date %s must be after start_date %s for session %s' % (gradeDate, Options['start_date'], sessionName) )

                if siteRole != sdproxy.ADMIN_ROLE:
                    # Non-admin access
                    # (Admin has access regardless of release date, allowing delayed release of live lectures and exams)
                    if isinstance(releaseDate, datetime.datetime):
                        # Check release date for session
                        if sliauth.epoch_ms() < sliauth.epoch_ms(sessionEntries['releaseDate']):
                            raise tornado.web.HTTPError(404, log_message='CUSTOM:Session %s not yet available' % sessionName)
                    elif releaseDate:
                        # Future release date
                        raise tornado.web.HTTPError(404, log_message='CUSTOM:Session %s unavailable' % sessionName)

                    offlineCheck = Options['offline_sessions'] and re.search('('+Options['offline_sessions']+')', sessionName, re.IGNORECASE)
                    if offlineCheck:
                        # Failsafe check to prevent premature release of offline exams etc.
                        if gradeDate or (Options['start_date'] and releaseDate):
                            pass
                        else:
                            # Valid gradeDate or (start_date & release_date) must be specified to access offline session
                            raise tornado.web.HTTPError(404, log_message='CUSTOM:Session '+sessionName+' not yet released')
                            
            # Check if pre-authorized for site access
            if Options['site_name']:
                # Check if site is explicitly authorized (user has global admin/grader role, or has explicit site listed, including guest users)
                preAuthorized = siteRole is not None
            else:
                # Single site: check if userid is known
                preAuthorized = Global.userRoles.is_known_user(userId)

            if not preAuthorized:
                if Global.login_domain and '@' in userId:
                    # External user
                    raise tornado.web.HTTPError(403, log_message='CUSTOM:User not pre-authorized to access site')

                # Check userId appears in roster
                if sdproxy.getSheet(sdproxy.ROSTER_SHEET, optional=True) and not sdproxy.lookupRoster('id', userId):
                    raise tornado.web.HTTPError(403, log_message='CUSTOM:Userid not found in roster')

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
        self.render("interact.html", note=note, site_name=Options['site_name'], site_label=Options['site_label'], session_label=label)

    @tornado.web.authenticated
    def post(self, subpath=''):
        try:
            userRole = self.get_id_from_cookie(role=True, for_site=Options['site_name'])
            msg = WSHandler.processMessage(self.get_id_from_cookie(), userRole, self.get_id_from_cookie(name=True), self.get_argument("message", ""), allStatus=True, source='interact')
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
        site_prefix = '/'+Options['site_name'] if Options['site_name'] else ''
        self.redirect(site_prefix+'/interact/?note='+sliauth.safe_quote(msg))            


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
            self.render("login.html", error_msg=error_msg, next=next, login_label=Options['site_label'],
                        login_url=Global.login_url, password='NO AUTHENTICATION' if Options['no_auth'] else 'Token:')

    def post(self):
        self.login(self.get_argument("username", ""), self.get_argument("token", ""), next=self.get_argument("next", "/"))

    def login(self, username, token, next="/"):
        generateToken = False
        if token == Options['auth_key']:
            # Auth_key token option for testing local-only proxy
            generateToken = True

        elif Options['no_auth'] and Options['debug'] and not Options['gsheet_url']:
            # No authentication option for testing local-only proxy
            generateToken = True

        role = ''
        if username == sdproxy.ADMINUSER_ID:
            role = sdproxy.ADMIN_ROLE
        if username == 'grader':
            role = sdproxy.GRADER_ROLE

        if generateToken:
            token = gen_proxy_auth_token(username, role=role)

        auth = self.check_access(username, token, role=role)
        if auth:
            data = {}
            if Global.twitter_params:
                data['site_twitter'] = Global.twitter_params['screen_name']
            self.set_id(username, data=data, role=role)
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
    def set_default_headers(self):
        # Completely disable cache
        self.set_header('Server', SERVER_NAME)

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
            if Global.userRoles.is_known_user(username):
                # Special case: out-of-domain emails
                pass
            else:
                if Global.login_domain:
                    if not username.endswith(Global.login_domain):
                        self.custom_error(500, '<h2>Authentication requires account '+Global.login_domain+'</h2><a href="https://mail.google.com/mail/u/0/?logout&hl=en">Logout of google (to sign in with a different account)</a><br><a href="/">Home</a>', clear_cookies=True)
                        return
                    username = username[:-len(Global.login_domain)]

                if username.startswith('_') or username in (sdproxy.ADMINUSER_ID, sdproxy.TESTUSER_ID):
                    self.custom_error(500, 'Disallowed username: '+username, clear_cookies=True)

            username = Global.userRoles.map_user(username)

            displayName = user.get('family_name','').replace(',', ' ')
            if displayName and user.get('given_name',''):
                displayName += ', '
            displayName += user.get('given_name','')
            if not displayName:
                displayName = username
            
            data = {}
            if Global.twitter_params:
                data['site_twitter'] = Global.twitter_params['screen_name']
            role, sites = Global.userRoles.id_role_sites(username)
            self.set_id(username, displayName=displayName, role=role, sites=sites, email=user['email'].lower(), data=data)
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
            if username.startswith('_') or username in (sdproxy.ADMINUSER_ID, sdproxy.TESTUSER_ID):
                self.custom_error(500, 'Disallowed username: '+username, clear_cookies=True)
            displayName = user['name']
            role, sites = Global.userRoles.id_role_sites(username)
            self.set_id(username, displayName=displayName, role=role, sites=sites)
            self.redirect(self.get_argument("next", "/"))
        else:
            yield self.authorize_redirect()

class PlainHTTPHandler(tornado.web.RequestHandler):
    def set_default_headers(self):
        self.set_header('Server', SERVER_NAME)

    def prepare(self):
        if self.request.protocol == 'http':
            self.redirect('https://' + self.request.host, permanent=False)

    def get(self):
        self.write("Hello, world")

def createApplication():
    pathPrefix = '/'+Options['site_name'] if Options['site_number'] else ''
        
    home_handlers = [
                     (pathPrefix+r"/", HomeHandler)
                    ]
    if not Options['site_number']:
        # Single/root server
        home_handlers += [ (r"/(_(backup|reload|setup|shutdown|update))", SiteActionHandler) ]
    else:
        # Site server
        home_handlers += [ (pathPrefix+r"/(_shutdown)", SiteActionHandler) ]

    if Options['site_list']:
        if not Options['site_number']:
            # Primary server
            home_handlers += [ (pathPrefix+r"/index.html", HomeHandler) ]
        else:
            # Secondary server
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
    Global.logout_url = '/_logout'
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

    settings.update(
        template_path=os.path.join(os.path.dirname(__file__), "server_templates"),
        xsrf_cookies=Options['xsrf'],
        cookie_secret=(Options['root_auth_key'] or 'testkey')+COOKIE_VERSION,
        login_url=Global.login_url,
        debug=Options['debug'],
    )

    if Options['proxy_wait'] is not None:
        site_handlers = [
                      (pathPrefix+r"/_proxy", ProxyHandler),
                      (pathPrefix+r"/_websocket/(.*)", WSHandler),
                      (pathPrefix+r"/interact", AuthMessageHandler),
                      (pathPrefix+r"/interact/(.*)", AuthMessageHandler),
                      (pathPrefix+r"/(_dash)", AuthActionHandler),
                      (pathPrefix+r"/(_grades)", UserActionHandler),
                      (pathPrefix+r"/(_grades/[-\w.]+)", UserActionHandler),
                      ]

        patterns= [   r"/(_(backup|cache|clear|freeze))",
                      r"/(_accept)",
                      r"/(_actions)",
                      r"/(_backup/[-\w.]+)",
                      r"/(_browse)",
                      r"/(_browse/[-\w./]+)",
                      r"/(_delete/[-\w.]+)",
                      r"/(_discard)",
                      r"/(_download/[-\w.]+)",
                      r"/(_edit)",
                      r"/(_edit/[-\w.]+)",
                      r"/(_export/[-\w.]+)",
                      r"/(_(getcol|getrow|sheet)/[-\w.;]+)",
                      r"/(_imageupload)",
                      r"/(_import/[-\w.]+)",
                      r"/(_lock)",
                      r"/(_lock/[-\w.]+)",
                      r"/(_logout)",
                      r"/(_manage/[-\w.]+)",
                      r"/(_prefill/[-\w.]+)",
                      r"/(_preview/[-\w./]+)",
                      r"/(_qstats/[-\w.]+)",
                      r"/(_rebuild/[-\w.]+)",
                      r"/(_refresh/[-\w.]+)",
                      r"/(_reindex/[-\w.]+)",
                      r"/(_remoteupload/[-\w.]+)",
                      r"/(_respond/[-\w.;]+)",
                      r"/(_roster)",
                      r"/(_sessions)",
                      r"/(_submissions/[-\w.:;]+)",
                      r"/(_submit/[-\w.:;]+)",
                      r"/(_twitter)",
                      r"/(_unlock/[-\w.]+)",
                      r"/(_upload)",
                      r"/(_upload/[-\w.]+)",
                      r"/(_lock/[-\w.]+)",
                       ]
        action_handlers = [(pathPrefix+pattern, ActionHandler) for pattern in patterns]
    else:
        site_handlers = []
        action_handlers = []

    file_handler = BaseStaticFileHandler if Options['no_auth'] else AuthStaticFileHandler

    if Options['static_dir']:
        sprefix = Options['site_name']+'/' if Options['site_name'] else ''
        # Handle special paths
        for path in [PRIVATE_PATH, RESTRICTED_PATH, PLUGINDATA_PATH]:
            if path == PLUGINDATA_PATH:
                if not Options['plugindata_dir']:
                    continue
                dir = Options['plugindata_dir'] + pathPrefix
            else:
                dir = Options['static_dir'] + pathPrefix
            site_handlers += [ (r'/%s(%s/.*)' % (sprefix, path), file_handler, {"path": dir}) ]

        # Default static path
        site_handlers += [ (r'/%s([^_].*)' % sprefix, file_handler, {"path": Options['static_dir']+pathPrefix}) ]

    if Options['site_list']:
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
    fromRole = ''
    if Options['auth_type'].startswith('twitter,'):
        status = WSHandler.processMessage(fromUser, fromRole, fromName, message, source='twitter')
    else:
        idMap = sdproxy.makeRosterMap('twitter', lowercase=True)
        if not idMap:
            status = 'Error - no twitter entries in roster. Message from '+fromUser+' dropped'
        else:
            userId = idMap.get(fromUser.lower())
            if userId:
                status = WSHandler.processMessage(userId, fromRole, sdproxy.lookupRoster('name', userId), message, source='twitter')
            else:
                status = 'Error - twitter ID '+fromUser+' not found in roster'
    print >> sys.stderr, 'processTwitterMessage:', status
    return status

def makeName(lastName, firstName, middleName=''):
    name = lastName.strip()
    if firstName.strip():
        name += ', ' + firstName.strip()
        if middleName:
            name += ' ' +middleName
    return name

def importRoster(filepath, csvfile, lastname_col='', firstname_col='', midname_col='',
                            id_col='', email_col='', altid_col=''):
    try:
        ##dialect = csv.Sniffer().sniff(csvfile.read(1024))
        ##csvfile.seek(0)
        reader = csv.reader(csvfile, delimiter=',')  # Ignore dialect for now

        rows = []
        for row in reader:
            if not rows and (len(row) < 3 or row[2:] == ['']*(len(row)-2)):
                # Skip initial rows with fewer than 3 non-blank columns
                continue
            rows.append(row)

        if not rows:
            raise Exception('No rows with more than 3 columns in CSV file')

        headers = rows[0]
        rows = rows[1:]

        if not rows:
            raise Exception('No data rows in roster file')

        idCol = 0
        altidCol = 0
        emailCol = 0
        twitterCol = 0
        lastNameCol = 0
        firstNameCol = 0
        midNameCol = 0
        for j, header in enumerate(headers):
            lheader = header.lower()
            if lheader == id_col:
                idCol = j+1
            if not id_col and lheader == 'id':
                idCol = j+1
            elif lheader == altid_col:
                altidCol = j+1
            elif not altid_col and lheader == 'altid':
                altidCol = j+1
            elif lheader == email_col:
                emailCol = j+1
            elif not email_col and lheader == 'email':
                emailCol = j+1
            elif lheader == 'twitter':
                twitterCol = j+1
            elif lheader == lastname_col:
                lastNameCol = j+1
            elif not lastname_col and lheader in ('last', 'lastname', 'last name', 'surname'):
                lastNameCol = j+1
            elif lheader == firstname_col:
                firstNameCol = j+1
            elif not firstname_col and lheader in ('first', 'firstname', 'first name', 'given name', 'given names'):
                firstNameCol = j+1
            elif lheader == midname_col:
                midNameCol = j+1

        if not idCol and not emailCol:
            raise Exception('ID column %s not found in CSV file %s' % (id_col, filepath))

        rosterHeaders = ['name', 'id', 'email', 'altid']
        if twitterCol:
            rosterHeaders.append('twitter')
        rosterRows = []
        singleDomain = None

        for row in rows:
            altid = row[altidCol-1].lower() if altidCol else ''
            email = row[emailCol-1].lower() if emailCol else ''
            if email:
                emailid, _, domain = email.partition('@')
                if domain:
                    if singleDomain is None:
                        singleDomain = domain
                    elif singleDomain != domain:
                        singleDomain = ''
                
            if idCol:
                userId = row[idCol-1].strip().lower()
            else:
                userId = email

            name = makeName(row[lastNameCol-1], row[firstNameCol-1], row[midNameCol-1] if midNameCol else '')

            rosterRow = [name, userId, email, altid]
            if twitterCol:
                rosterRow.append(row[twitterCol-1] if twitterCol else '')
            rosterRows.append(rosterRow)

        if (not idCol or idCol == emailCol) and singleDomain:
            # Strip out common domain from email used as ID
            endStr = '@'+singleDomain
            endLen = len(endStr)
            for j in range(len(rosterRows)):
                if rosterRows[j][1].endswith(endStr):
                    rosterRows[j][1] = rosterRows[j][1][:-endLen]

        sdproxy.createRoster(rosterHeaders, rosterRows)
        return ''

    except Exception, excp:
        if Options['debug']:
            import traceback
            traceback.print_exc()
        return 'Error in importRoster: '+str(excp)

def updateImportParams(paramStr, prevParams={'importKey':'', 'keyColName':'', 'skipKeys':''}):
    params = prevParams.copy()
    if paramStr:
        comps = [x.strip() for x in paramStr.split(';')]
        if len(comps) > 0 and comps[0] and not params['importKey']:
            params['importKey'] = comps[0]
        if len(comps) > 1 and comps[1] and not params['keyColName']:
            params['keyColName'] = comps[1]
        if len(comps) > 2 and not params['skipKeys']:
            params['skipKeys'] = ';'.join(comps[2:])
    return params

def importAnswers(sessionName, filepath, csvfile, importParams, submitDate=''):
    missed = []
    errors = []

    if importParams['skipKeys']:
        skipKeySet = set(x.strip() for x in importParams['skipKeys'].split(';') if x.strip())
    else:
        skipKeySet = set()

    try:
        ##dialect = csv.Sniffer().sniff(csvfile.read(1024))
        ##csvfile.seek(0)
        reader = csv.reader(csvfile, delimiter=',')  # Ignore dialect for now

        rows = []
        for row in reader:
            if not rows and (len(row) < 3 or row[2:] == ['']*(len(row)-2)):
                # Skip initial rows with fewer than 3 non-blank columns
                continue
            rows.append(row)

        if not rows:
            raise Exception('No rows with more than 3 columns in CSV file')

        headers = rows[0]
        rows = rows[1:]

        if not rows:
            raise Exception('No data rows in CSV file')

        keyCol = 0
        formCol = 0
        lastNameCol = 0
        firstNameCol = 0
        midNameCol = 0
        qresponse = {}
        for j, header in enumerate(headers):
            lheader = header.lower()
            hmatch = re.match(r'^(q?[gx]?)(\d+)$', header)
            if hmatch:
                qnumber = int(hmatch.group(2))
                qresponse[qnumber] = (j, hmatch.group(1))
            elif lheader == importParams['keyColName'].lower():
                keyCol = j+1
            elif lheader == 'form':
                formCol = j+1
            elif lheader in ('last', 'lastname', 'last name', 'surname'):
                lastNameCol = j+1
            elif lheader in ('first', 'firstname', 'first name', 'given name', 'given names'):
                firstNameCol = j+1
            elif lheader in ('middle', 'middlename', 'middlenames', 'middle name', 'middle names', 'mid name'):
                midNameCol = j+1

        nameKey = False
        if not keyCol:
            if importParams['importKey'] != 'name':
                raise Exception('Import key column %s not found in CSV file %s' % (importParams['importKey'], filepath))
            if lastNameCol and firstNameCol:
                nameKey = True
            else:
                raise Exception('Name column(s) not found in imported CSV file %s' % filepath)
        
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
                # Mid-point swap (Form B)
                if qnumber > midnumber:
                    qnumberMap[1].append(qnumber - midnumber)
                else:
                    qnumberMap[1].append(qnumber + midnumber + midoffset)
        print >> sys.stderr, 'qnumberMap=', qnumberMap

        keyMap = sdproxy.makeRosterMap(importParams['importKey'], lowercase=True, unique=True)
        if not keyMap:
            raise Exception('Key column %s not found in roster for import' % importParams['importKey'])
        if importParams['importKey'] == 'twitter':
            # Special case of test user; not really Twitter ID
            keyMap[sdproxy.TESTUSER_ID] = sdproxy.TESTUSER_ID

        nameMap = sdproxy.lookupRoster('name')

        missingKeys = []
        userKeys = set()
        idRows = []
        for row in rows:
            if nameKey:
                userKey = makeName(row[lastNameCol-1], row[firstNameCol-1], row[midNameCol-1] if midNameCol else '').lower()
            else:
                userKey = row[keyCol-1].strip().lower()

            if not userKey or userKey in skipKeySet:
                continue
                
            if userKey in userKeys:
                raise Exception('Duplicate occurrence of user key %s in CSV file' % userKey)
            userKeys.add(userKey)

            userId = keyMap.get(userKey)
            if userId:
                idRows.append( (userId, row) )
            else:
                missingKeys.append(userKey)
                errors.append('MISSING: User key '+userKey+' not found in roster')
                print >> sys.stderr, 'Key', userKey, 'not found in roster'

        if missingKeys:
            raise Exception('One or more keys not found in roster: '+', '.join(missingKeys))

        if not idRows:
            raise Exception('No valid import keys in CSV file')

        for userId, row in idRows:
            answers = {}
            formSwitch = 0
            if formCol and row[formCol-1] and row[formCol-1].upper() != 'A':
                formSwitch = 1

            for qnumber in qnumbers:
                qnumberMapped = qnumberMap[formSwitch][qnumber-1]
                offset, prefix = qresponse[qnumberMapped]
                cellValue = row[offset].strip() if offset < len(row) else ''
                if not cellValue or cellValue in Options['missing_choice']:
                    continue
                if prefix == 'qg':
                    answers[qnumber] = {'grade': cellValue}
                    continue
                explain = ''
                if prefix == 'qx':
                    comps = cellValue.split()
                    if len(comps) > 1:
                        explain = cellValue[len(comps[0]):].strip()
                        cellValue = comps[0]
                answers[qnumber] = {'response': cellValue}
                if prefix == 'qx':
                    answers[qnumber]['explain'] = explain

            displayName = nameMap[userId] or 'Unknown, Name'
            try:
                if Options['debug']:
                    print >> sys.stderr, 'DEBUG: importAnswers', sessionName, userId, displayName
                sdproxy.importUserAnswers(sessionName, userId, displayName, answers=answers, submitDate=submitDate, source='import')
            except Exception, excp:
                errors.append('Error in import for user '+str(userId)+': '+str(excp))
                missed.append(userId)
                missed.append('... and others')
                break
    except Exception, excp:
        if Options['debug']:
            import traceback
            traceback.print_exc()
        errors = [ 'Error in importAnswers: '+str(excp)] + errors

    return missed, errors

def sendPrivateRequest(relay_address, path='/', proto='http'):
    if Options['debug']:
        print >> sys.stderr, 'DEBUG: sdserver.sendPrivateRequest:', relay_address, path
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
    if Options['site_list'] and not Options['site_number']:
        # Primary server
        for j, site in enumerate(Options['site_list']):
            relay_addr = Global.relay_list[j+1]
            retval = sendPrivateRequest(relay_addr, path='/'+site+'/_backup?root='+Options['server_key'])
    else:
        errors = sdproxy.backupSheets(dirpath)
        self.set_header('Content-Type', 'text/plain')
        self.write('Backed up site %s to directory %s' % (Options['site_name'], sessionName))
        if errors:
            self.write(errors)

def shutdown_all():
    if Options['debug']:
        print >> sys.stderr, 'sdserver.shutdown_all:'
    for j, site in enumerate(Options['site_list']):
        # Shutdown child servers
        relay_addr = Global.relay_list[j+1]
        retval = sendPrivateRequest(relay_addr, path='/'+site+'/_shutdown?root='+Options['server_key'])

    # Shutdown parent
    IOLoop.current().add_callback(shutdown_loop)

def shutdown_loop():
    shutdown_server()
    IOLoop.current().stop()
    if Options['debug']:
        print >> sys.stderr, 'sdserver.shutdown_loop:'

def shutdown_server():
    if Global.http_server:
        Global.http_server.stop()
        Global.http_server = None
    if Global.server_socket:
        try:
            Global.server_socket.close()
        except Exception, excp:
            print >> sys.stderr, 'sdserver.shutdown_server: ERROR', sexcp
    if Options['debug']:
        print >> sys.stderr, 'sdserver.shutdown_server:'
    
class UserRoles(object):
    def __init__(self):
        self.alias_map = {}
        self.root_role = {}
        self.external_users = set()
        self.site_known_users = set()
        self.site_roles = {}

    def map_user(self, username):
        return self.alias_map.get(username, username)
            
    def is_known_user(self, userId):
        return userId in self.root_role or userId in self.external_users or userId in self.site_known_users

    def update_root_roles(self, auth_users):
        # Process list of special authorized users
        if auth_users.endswith('.txt'):
            with open(auth_users) as f:
                file_data = f.read()
                auth_users = [x.strip() for x in file_data.split('\n') if x.strip()]
        else:
            auth_users = [x.strip() for x in auth_users.split(';') if x.strip()]

        self.alias_map = {}
        self.external_users = set()
        self.root_role[sdproxy.ADMINUSER_ID] = sdproxy.ADMIN_ROLE
        admin_user = ''
        for user_map in auth_users:
            # Format: [username[@domain]=]userid:role
            userId, _, userRole = user_map.partition(':')
            userId    = userId.strip()
            userRole  = userRole.strip()

            origId = ''
            if '=' in userId:
                origId, userId = userId.split('=')
                origId = origId.strip()
                userId = userId.strip()
                if origId in self.alias_map:
                    raise Exception('Error: Duplicate aliasing to %s; alias already defined: %s -> %s' % (userId, origId, self.alias_map[origId]))
                self.alias_map[origId] = userId
                if '@' in origId:
                    self.external_users.add(origId)

            if not userId:
                raise Exception('Null username')

            if userId in (sdproxy.ADMINUSER_ID, sdproxy.TESTUSER_ID) or userId.startswith('_'):
                raise Exception('Username %s is reserved' % userId)

            if '@' in userId:
                self.external_users.add(userId)

            if userRole:
                # Enter only userIds with roles in root_role
                if userRole not in (sdproxy.ADMIN_ROLE, sdproxy.GRADER_ROLE):
                    raise Exception('Invalid user role: '+userRole)

                if userRole == sdproxy.ADMIN_ROLE:
                    admin_user = userId

                self.root_role[userId] = userRole

            print >> sys.stderr, 'USER %s: %s -> %s:%s:' % (user_map, origId, userId, userRole)

        if Options['root_auth_key'] and not admin_user:
            raise Exception('There must be at least one user with admin access')


    def update_site_roles(self, siteName, adminIds, graderIds, guestIds):
        roles = (sdproxy.ADMIN_ROLE, sdproxy.GRADER_ROLE, '')
        idLists = [adminIds, graderIds, guestIds]
        self.site_roles[siteName] = {}
        for j, role in enumerate(roles):
            for userId in idLists[j].split(','):
                userId = userId.strip()
                if not userId:
                    continue
                if userId in self.root_role:
                    if role != self.root_role[userId]:
                        print >> sys.stderr, 'WARNING: User %s already has global %s role' % (userId, self.root_role[userId])
                    continue
                if userId in self.site_roles[siteName]:
                    print >> sys.stderr, 'WARNING: User %s already has site %s role in %s' % (userId, self.site_roles[siteName][userId], siteName)
                    continue
                self.site_roles[siteName][userId] = role
                self.site_known_users.add(userId)   # At present there is no way to delete userIds from this set (but static file preAuthorization check should handle it)

    def id_role_sites(self, userId):
        # Return (role, sites)
        if userId in self.root_role:
            return self.root_role[userId], ''

        siteRoles = []
        for siteName in Options['site_list']:
            if userId in self.site_roles[siteName]:
                siteRole = siteName
                if self.site_roles[siteName][userId]:
                    siteRole += '+' + self.site_roles[siteName][userId]
                siteRoles.append(siteRole)

        siteRoles.sort()
        return '', ','.join(siteRoles)

    def id_role(self, userId, for_site=''):
        # Return role for site (may return None if no role is found)
        if userId in self.root_role:
            return self.root_role[userId]
        if for_site and for_site in self.site_roles:
            return self.site_roles[for_site].get(userId)
        return ''


Global.userRoles = UserRoles()


def relay_setup(site_number):
    port = Options['private_port'] + site_number
    if Options['socket_dir']:
        Global.relay_list.append( Options['socket_dir']+'/uds_socket'+str(port) )
    else:
        Global.relay_list.append( ('localhost', port) )

def start_multiproxy():
    import multiproxy
    class ProxyRequestHandler(multiproxy.RequestHandler):
        def get_relay_addr_uri(self, pipeline, header_list):
            """ Returns relay host, port.
            May modify self.request_uri or header list (excluding the first element)
            Raises exception if connection not allowed.
            """
            comps = self.request_uri.split('/')
            if len(comps) > 1 and comps[1] and comps[1] in Options['site_list']:
                # Site server
                site_number = 1+Options['site_list'].index(comps[1])
                retval = Global.relay_list[site_number]
            elif Global.relay_forward and not self.request_uri.startswith('/_'):
                # Not URL starting with '_'; forward to underlying website
                retval = Global.relay_forward
            else:
                # Root server
                retval = Global.relay_list[0]
            print >> sys.stderr, 'ABC: get_relay_addr_uri: ', self.request_uri, retval
            return retval

    Global.proxy_server = multiproxy.ProxyServer(Options['host'], Options['port'], ProxyRequestHandler, log_interval=0,
                      io_loop=IOLoop.current(), xheaders=True, masquerade="server/1.2345", ssl_options=Options['ssl_options'], debug=True)

def start_server(site_number=0, restart=False):
    # Start site/root server
    Options['server_start'] = sliauth.create_date()
    if Options['ssl_options'] and not Options['site_list']:
        Global.http_server = tornado.httpserver.HTTPServer(createApplication(), ssl_options=Options['ssl_options'])
    else:
        Global.http_server = tornado.httpserver.HTTPServer(createApplication())

    if Options['ssl_options'] and not site_number:
        # Redirect plain HTTP to HTTPS
        handlers = [ (r'/', PlainHTTPHandler) ]
        plain_http_app = tornado.web.Application(handlers)
        plain_http_app.listen(80)
        print >> sys.stderr, "Listening on HTTP port"

    if not Options['site_list']:
        # Start single site server
        Global.http_server.listen(Options['port'])
        print >> sys.stderr, "Listening on port", Options['port'], Options['site_name']
    else:
        relay_addr = Global.relay_list[site_number]
        if isinstance(relay_addr, tuple):
            Global.http_server.listen(relay_addr[1])
        else:
            import multiproxy
            Global.server_socket = multiproxy.make_unix_server_socket(relay_addr)
            Global.http_server.add_socket(Global.server_socket)
        print >> sys.stderr, "Site %d listening on %s" % (site_number, relay_addr)

    if not restart:
        IOLoop.current().start()

def getSheetSettings(gsheet_url, site_name=''):
    try:
        return sliauth.read_settings(gsheet_url, Options['root_auth_key'], sdproxy.SETTINGS_SHEET, site=site_name)
    except Exception, excp:
        ##if Options['debug']:
        ##    import traceback
        ##    traceback.print_exc()
        print >> sys.stderr, 'Error:site %s: Failed to read  Google Sheet settings_slidoc from %s: %s' % (site_name, gsheet_url, excp)
        return {}

def fork_site_server(site_name, gsheet_url, **kwargs):
    # Return error message or null string
    # kwargs must match SPLIT_OPTS[1:]. Only gsheet_url is required
    if site_name in Options['site_list']:
        raise Exception('ERROR: duplicate site name: '+site_name)
    new_site = site_name not in Global.split_opts['site_list']

    errMsg = ''
    sheetSettings = getSheetSettings(gsheet_url, site_name) if gsheet_url else {}

    Options['site_list'].append(site_name)
    site_number = len(Options['site_list'])

    if new_site:
        Global.split_opts['site_list'].append(site_name)
        Global.split_opts['gsheet_url'].append(gsheet_url)
        for key in SPLIT_OPTS[1:]:
            Global.split_opts[key].append(kwargs.get(key,''))

    if sheetSettings:
        for key in SPLIT_OPTS[1:]:
            if key in sheetSettings:
                Global.split_opts[key][site_number-1] = sheetSettings[key]
    else:
        Global.split_opts['site_restricted'][site_number-1] = 'restricted'

    Global.userRoles.update_site_roles(site_name, sheetSettings.get('admin_users',''), sheetSettings.get('grader_users',''), sheetSettings.get('guest_users','') )

    relay_setup(site_number)
    process_pid = os.fork()
    ##if Options['debug']:
    ##    print >> sys.stderr, 'DEBUG: sdserver.fork:', site_name, site_number, process_pid

    if process_pid:
        # Primary (non-proxy) server
        Global.child_pids.append(process_pid)
        return errMsg
    else:
        # Secondary server
        restart = False
        if Global.http_server:
            restart = True
            shutdown_server()
        if Global.proxy_server:
            Global.proxy_server.stop()
            Global.proxy_server = None
        Options['server_start'] = sliauth.create_date()
        Options['sport'] = 0
        Options['site_number'] = site_number
        Options['site_name'] = site_name
        for key in SPLIT_OPTS:
            Options[key] = Global.split_opts[key][site_number-1]
        Options['auth_key'] = sliauth.gen_site_key(Options['auth_key'], site_name)
        BaseHandler.site_src_dir = Options['source_dir'] + '/' + site_name
        BaseHandler.site_web_dir = Options['static_dir'] + '/' + site_name
        BaseHandler.site_uploads_dir = Options['plugindata_dir'] + '/' + site_name
        setup_site_server(sheetSettings)
        start_server(site_number, restart=restart)
        return errMsg  # If not restart, returns only when server stops

def setup_site_server(sheetSettings):
    if Options['proxy_wait'] is not None:
        # Copy options to proxy
        sdproxy.copyServerOptions(Options)

        if sheetSettings:
            sdproxy.copySheetOptions(sheetSettings)
        else:
            Options['site_restricted'] = 'restricted'

        Global.session_options = {}
        for key in sheetSettings:
            smatch = SESSION_OPTS_RE.match(key)
            if key in OPTIONS_FROM_SHEET:
                # Copy sheet options
                Options[key] = sheetSettings[key]
            elif smatch:
                # Default session options
                sessionName = smatch.group(1)
                opts_dict = {}
                opts = [x.lstrip('-') for x in sheetSettings[key].split()]
                for opt in opts:
                    name, sep, value = opt.partition('=')
                    if not sep:
                        opts_dict[name] = True
                    else:
                        if value.startswith("'"):
                            value = value.strip("'")
                        elif value.startswith('"'):
                            value = value.strip('"')
                        if isdigit(value):
                            value = int(value)
                        opts_dict[name] = value
                Global.session_options[sessionName] = opts_dict

    if options.backup:
        curTimeSec = sliauth.epoch_ms()/1000.0
        curDate = sliauth.iso_date(sliauth.create_date(curTimeSec*1000.0))[:10]
        if Options['backup_hhmm']:
            backupTimeSec = sliauth.epoch_ms(sliauth.parse_date(curDate+'T'+Options['backup_hhmm']))/1000.0
        else:
            backupTimeSec = curTimeSec + 31
        backupInterval = 86400
        if backupTimeSec - curTimeSec < 30:
            backupTimeSec += backupInterval
        print >> sys.stderr, 'Scheduled backup in dir %s every %s hours, starting at %s' % (Options['backup_dir'], backupInterval/3600, sliauth.iso_date(sliauth.create_date(backupTimeSec*1000.0)))
        def start_backup():
            if Options['debug']:
                print >> sys.stderr, "Starting periodic backup"
            backupSite()
            Global.backup = PeriodicCallback(backupSite, backupInterval*1000.0)
            Global.backup.start()

        IOLoop.current().call_at(backupTimeSec, start_backup)

    if Options['twitter_config']:
        comps = Options['twitter_config'].split(',')
        Global.twitter_params = {
            'screen_name': comps[0],
            'consumer_token': {'consumer_key': comps[1], 'consumer_secret': comps[2]},
            'access_token': {'key': comps[3], 'secret': comps[4]}
            }

        import sdstream
        Global.twitterStream = sdstream.TwitterStreamReader(Global.twitter_params, processTwitterMessage,
                                                     allow_replies=Options['allow_replies'])
        Global.twitterStream.start_stream()

def main():
    define("config", type=str, help="Path to config file",
        callback=lambda path: parse_config_file(path, final=False))

    define("allow_replies", default=False, help="Allow replies to twitter direct messages")
    define("auth_key", default=Options["auth_key"], help="Digest authentication key for admin user")
    define("auth_type", default=Options["auth_type"], help="@example.com|google|twitter,key,secret,,...")
    define("auth_users", default='', help="filename.txt or [userid]=username[@domain][:role[:site1,site2...];...")
    define("backup", default="", help="=Backup_dir[,HH:MM] End Backup_dir with hyphen to automatically append timestamp")
    define("debug", default=False, help="Debug mode")
    define("dry_run", default=False, help="Dry run (read from Google Sheets, but do not write to it)")
    define("forward_port", default=0, help="Forward port for default (root) web server with multiproxy, allowing slidoc sites to overlay a regular website, using '_' prefix for admin")
    define("gsheet_url", default="", help="Google sheet URL1;...")
    define("host", default=Options['host'], help="Server hostname or IP address, specify '' for all (default: localhost)")
    define("lock_proxy_url", default="", help="Proxy URL to lock sheet(s), e.g., http://example.com")
    define("min_wait_sec", default=0, help="Minimum time (sec) between Google Sheet updates")
    define("missing_choice", default=Options['missing_choice'], help="Missing choice value (default: *)")
    define("import_params", default=Options['import_params'], help="KEY;KEYCOL;SKIP_KEY1,... parameters for importing answers")
    define("insecure_cookie", default=False, help="Insecure cookies (for printing)")
    define("no_auth", default=False, help="No authentication mode (for testing)")
    define("plugindata_dir", default=Options["plugindata_dir"], help="Path to plugin data files directory")
    define("plugins", default="", help="List of plugin paths (comma separated)")
    define("private_port", Options["private_port"], help="Base private port for multiproxy)")
    define("proxy_wait", type=int, help="Proxy wait time (>=0; omit argument for no proxy)")
    define("public", default=Options["public"], help="Public web site (no login required, except for _private/_restricted)")
    define("reload", default=False, help="Enable autoreload mode (for updates)")
    define("offline_sessions", default=Options["offline_sessions"], help="Pattern matching sessions that are offline assessments, default=(exam|quiz|test|midterm|final)")
    define("roster_columns", default=Options["roster_columns"], help="Roster column names: lastname_col,firstname_col,midname_col,id_col,email_col,altid_col")
    define("sites", default="", help="Site names for multi-site server (comma-separated)")
    define("site_label", default='', help="Site label")
    define("site_restricted", default='', help="Site restricted")
    define("site_title", default='', help="Site title")
    define("server_url", default=Options["server_url"], help="Server URL, e.g., http://example.com")
    define("socket_dir", default="", help="Directory for creating unix-domain socket pairs")
    define("ssl", default="", help="SSLcertfile,SSLkeyfile")
    define("source_dir", default=Options["source_dir"], help="Path to source files directory (required for edit/upload)")
    define("static_dir", default=Options["static_dir"], help="Path to static files directory")
    define("twitter_config", default="", help="Twitter stream access info: username,consumer_key,consumer_secret,access_key,access_secret;...")
    define("xsrf", default=False, help="XSRF cookies for security")

    define("port", default=Options['port'], help="Web server port", type=int)
    parse_command_line()
    
    if not options.auth_key and not options.public:
        sys.exit('Must specify one of --public or --auth_key=...')

    for key in Options:
        if not key.startswith('_') and hasattr(options, key):
            # Command line overrides settings
            Options[key] = getattr(options, key)

    if len(Options['roster_columns'].split(',')) != 6:
        sys.exit('Must specify --roster_columns=lastname_col,firstname_col,midname_col,id_col,email_col,altid_col')

    Options['root_auth_key'] = Options['auth_key']
    Options['server_key'] = str(random.randrange(0,2**60))

    if not options.debug:
        logging.getLogger('tornado.access').disabled = True

    if options.auth_users:
        Global.userRoles.update_root_roles(options.auth_users)

    Options['ssl_options'] = None
    if options.port == 443:
        if not options.ssl:
            sys.exit('SSL options must be specified for port 443')
        certfile, keyfile = options.ssl.split(',')
        Options['ssl_options'] = {"certfile": certfile, "keyfile": keyfile}

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
    if Options['debug']:
        print >> sys.stderr, 'sdserver: SERVER_KEY', Options['server_key']
    if plugins:
        print >> sys.stderr, 'sdserver: Loaded plugins: '+', '.join(plugins)

    if options.backup and not Options['site_name']:
        comps = options.backup.split(',')
        Options['backup_dir'] = comps[0]
        Options['backup_hhmm'] = comps[1] if len(comps) > 1 else '03:00'

    if Options['sites']:
        Global.split_opts['site_list'] = [x.strip() for x in Options['sites'].split(',')]
        nsites = len(Global.split_opts['site_list'])
        for key in SPLIT_OPTS:
            if Options[key]:
                Global.split_opts[key] = [x.strip() for x in Options[key].split(';')]
                if len(Global.split_opts[key]) != nsites:
                    raise Exception('No. of values for --'+key+'=...;... should match number of sites')
                # Clear gsheet_url, twitter_config, site label/title options
                Options[key] = ''
            else:
                Global.split_opts[key] = Global.split_opts['site_list'][:] if key == 'site_label' else ['']*nsites

    Global.child_pids = []
    socket_name_fmt = options.socket_dir + '/uds_socket'

    BaseHandler.site_src_dir = Options['source_dir']
    BaseHandler.site_web_dir = Options['static_dir']

    if options.forward_port:
        Global.relay_forward = ('localhost', forward_port)

    if Global.split_opts:
        print >> sys.stderr, 'DEBUG: sdserver.main:', Global.split_opts['site_list'], Global.relay_list
        relay_setup(0)
        for j, site_name in enumerate(Global.split_opts['site_list']):
            errMsg = fork_site_server(site_name, Global.split_opts['gsheet_url'][j])
            if Options['site_number']:
                # Child process
                return
            if errMsg:
                print >> sys.stderr, errMsg

        # After forking (secondary site servers are setup and started in fork_site_server)
        if not Options['site_number']:
            # Root server
            print >> sys.stderr, 'DEBUG: sdserver.userRoles:', Global.userRoles.root_role, Global.userRoles.site_roles, Global.userRoles.external_users
            start_multiproxy()
            start_server()
    else:
        # Start single site server
        sheetSettings = getSheetSettings(Options['gsheet_url']) if Options['gsheet_url'] else {}
        if sheetSettings:
            for key in SPLIT_OPTS[1:]:
                if key in sheetSettings:
                    Options[key] = sheetSettings[key]
        setup_site_server(sheetSettings)
        start_server()

if __name__ == "__main__":
    main()
