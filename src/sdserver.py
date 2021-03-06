#!/usr/bin/env python

"""
sdserver: Tornado-based web server to serve Slidoc html files (with authentication)
          - Handles digest authentication using HMAC key
          - Can be used as a simple static file server (with authentication), AND
          - As a proxy server that handles spreadsheet operations on cached data and copies them to Google sheets

        Use 'sdserver.py --gsheet_url=...' and
            'slidoc.py --gsheet_url=... --proxy_url=/_websocket/ ...' to proxy user calls to Google sheet (but not slidoc.py setup calls, which are still directed to gsheet_url)
        Can specify 'slidoc.py --gsheet_url=http:/hostname/_proxy/ --proxy_url=/_websocket/ ...' to re-direct session setup calls to proxy as well.

        For proxying without websocket:
            'slidoc.py --gsheet_url=... --proxy_url=http://localhost/_proxy'
        
Command arguments:
    config: config file containing command line options as python assignment statements
    debug: Enable debug mode (can be used for testing local proxy data without gsheet_url)
    gsheet_url: Google sheet URL (required if proxy and not debugging)
    auth_key: Digest authentication key for admin user (enables login protection for website)
    port: Web server port number to listen on (default=8899)
    private_port: Base port number for private servers
    public_pages: Public pages (no login required for home page etc., except for paths containing _private/_restricted)
    proxy: Enable proxy mode (cache copies of Google Sheets)
    sites: Site names, e.g., 'chem101,math101,...'
    site_label: Site label, e.g., 'MATH101'
    libraries_dir: path to shared libraries directory
    source_dir: path to source files directory containing Slidoc .md files (default='source')
    web_dir: path to web files directory containing Slidoc html files (default='web')
    xsrf: Enable XSRF cookies for security

    For Twitter auth workflow, see sdstream.py

"""

import argparse
import base64
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
import subprocess
import os.path
import re
import shutil
import socket
import sys
import time
import urllib
import uuid
import zipfile

from collections import defaultdict, OrderedDict, namedtuple

import tornado.auth
import tornado.autoreload
import tornado.gen
import tornado.escape
import tornado.httpserver
import tornado.netutil
import tornado.process
import tornado.web
import tornado.websocket

from tornado.options import define, options, parse_command_line, parse_config_file
from tornado.ioloop import IOLoop, PeriodicCallback

import md2md
import md2nb
import nb2md
import sdproxy
import sliauth
import slidoc
import plugins

scriptdir = os.path.dirname(os.path.realpath(__file__))
script_parentdir = os.path.abspath(os.path.join(scriptdir, os.pardir))

DEBUG_PATH_RE = re.compile(r'(/_auth/)')

CUMULATIVE_TOTAL_RE = re.compile(r'^(\d*(\.\d*)?|(\d*(\.\d*)?\*)?[a-z][-\w]*[a-z](\d\d|_(avg|normavg|sum)(_(\d+))?))$', re.IGNORECASE)

Options = {
    '_index_html': '',  # Non-command line option
    'root_auth_key': '',
    'admin_users': '',
    'allow_replies': None,
    'auth_key': '',
    'auth_type': '',
    'backup_dir': '_DEFAULT_BACKUPS',
    'backup_hhmm': '',
    'backup_options': [],
    'debug': False,
    'dry_run': False,
    'dry_run_file_modify': False,  # If true, allow source/web/plugin file mods even for dry run (e.g., local copy)
    'email_addr': '',
    'end_date': '',
    'gapps_url': '',
    'grader_users': '',
    'gsheet_url': '',
    'guest_users': '',
    'host': 'localhost',
    'import_params': '',
    'insecure_cookie': False,
    'lock_proxy_url': '',
    'log_call': '',
    'min_wait_sec': 0,
    'missing_choice': '*',
    'multisite': False,
    'notebook_extn': 'ipynb',
    'old_auth_key': '',
    'plugindata_dir': 'plugindata',
    'port': 8899,
    'private_port': 8900,
    'public_pages': False,
    'reload': False,
    'request_timeout': 60,
    'libraries_dir': '',
    'remote_logging': 0,
    'restore_backup': [],
    'root_users': [],
    'roster_columns': 'lastname,firstname,,id,email,altid',
    'server_key': None,
    'server_nonce': None,
    'server_start': None,
    'server_url': '',
    'site_label': '',        # E.g., Calculus 101
    'site_name': '',         # E.g., calc101
    'site_number': 0,
    'site_title': '',        # E.g., Elementary Calculus, Fall 2000
    'site_list': [],
    'sites': '',             # Original comma separated list of site names
    'socket_dir': '',
    'source_dir': '',
    'ssl_options': None,
    'start_date': '',
    'web_dir': 'web',
    'timezone': '',
    'twitter_config': '',
    'xsrf': False,
    }

SITE_OPTS = ['gsheet_url', 'site_label', 'site_title', 'site_access', 'sort_key', 'twitter_config', 'server_url']

SHEET_OPTS = ['admin_users', 'grader_users', 'guest_users', 'start_date', 'lock_date', 'end_date']

SETTINGS_LABELS = [ ('gsheet_url', 'Google Sheet URL'),
                    ('site_label', "Site label e.g., 'Calc101, F16'"),
                    ('site_title', 'Site title (one line)'),
                    ('site_access', "blank '' OR 'adminonly' OR 'adminguest' OR 'locked' OR 'inactive'"),
                    ('sort_key', 'Alternative label to be used for determining order of site display'),
                    ('', ''),
                    ('admin_users', 'User IDs or email addresses with admin access (comma-separated)'),
                    ('grader_users', 'User IDs or email addresses with grader access'),
                    ('guest_users', 'User IDs or email addresses with guest access'),
                    ('', ''),
                    ('start_date', 'Date after which all session releases must start (yyyy-mm-dd)'),
                    ('lock_date', 'Date when all user modifications are disabled (yyyy-mm-dd)'),
                    ('end_date', 'Date after which all user access is disabled (yyyy-mm-dd)'),
                    ('', ''),
                    ('site_menu', 'List of top menu items: files,gradebook (comma-separated)'),
                    ('session_properties', 'List of session_name:pace:[public/restricted]:[description] (semicolon-separated)'),
                    ('twitter_config', 'Twitter config (username,consumer_key,consumer_secret,access_key,access_secret)'),
                    ('', ''),
                    ('gradebook_release', 'List of released items: average,cumulative_total,cumulative_grade (comma-separated)'),
                    ('cumulative_total', 'Formula for gradebook total column, e.g., 0.4*assignment_avg_1+0.5*quiz_sum+10*test_normavg+0.1*extra01'),
                    ('cumulative_grade', 'A:90%:4,B:80%:3,C:70%:2,D:60%:1,F:0%:0'),
                    ('', ''),
                    ('no_login_token', 'Non-null string for true'),
                    ('no_late_token',  'Non-null string for true'),
                    ('no_roster',      'Non-null string for true'),
                    ('log_call',       '> 0 to log calls to sheet call_log; may generate large output over time'),
                    ]

SiteOpts = OrderedDict()

def root_add_site(site_name, site_settings, overwrite=False):
    if site_name in SiteOpts and not overwrite:
        raise Exception('Cannot add duplicate site: %s' % site_name)
    SiteOpts[site_name] = dict( (key, site_settings.get(key,'')) for key, value in SETTINGS_LABELS if key)
    root_update_site_list()

def root_remove_site(site_name):
    if site_name in SiteOpts:
        SiteOpts[site_name] = {}
    root_update_site_list()

def root_update_site_list():
    all_sites = [ (site_settings['sort_key'] or site_name, site_name) for site_name, site_settings in SiteOpts.items() if site_settings]
    all_sites.sort()    # Sort sites in lexical order of sort_key or site_name
    Options['site_list'] = [site_name for sort_key, site_name in all_sites]

def get_site_number(site_name):
    if SiteOpts.get(site_name):
        return 1+SiteOpts.keys().index(site_name)
    else:
        return 0

RELOAD_WATCH_FILE = '_slidoc_reload'

SLIDOC_CONFIGFILE = '_slidoc_config.py'

SINGLE_SETTINGSFILE = '_site_settings.json'

SERVER_LOGFILE = 'screenlog.0'

SESSION_OPTS_RE = re.compile(r'^session_(\w+)$')

class Dummy():
    pass

CommandOpts = options

Global = Dummy()
Global.config_path = ''
Global.config_file = ''
Global.config_digest = ''
Global.site_settings_file = ''
Global.site_settings = {}
Global.userRoles = None
Global.backup = None
Global.remoteShutdown = False
Global.twitter_params = {}
Global.relay_forward = None
Global.http_server = None
Global.server_socket = None
Global.proxy_server = None
Global.session_options = {}
Global.email2id = None
Global.predefined_sites = []
Global.split_site_opts = {}
Global.accessCodes = {}

Global.twitterStream = None
Global.twitterSpecial = {}
Global.twitterVerify = {}

Global.previewModifiedCount = 0

PLUGINDATA_PATH = '_plugindata'
PRIVATE_PATH    = '_private'
RESTRICTED_PATH = '_restricted'
RESOURCE_PATH = '_resource'
LIBRARIES_PATH = '_libraries'
FILES_PATH = '_files'
DOCS_PATH = '_docs'

NOTEBOOKS_PATH = FILES_PATH + '/' + RESTRICTED_PATH + '/notebooks'

ACME_PATH = '.well-known/acme-challenge'

ADMIN_PATH = 'admin'

USER_COOKIE_SECURE = sliauth.USER_COOKIE_PREFIX+'_secure'
USER_COOKIE        = sliauth.USER_COOKIE_PREFIX
SITE_COOKIE_SECURE = sliauth.SITE_COOKIE_PREFIX+'_secure_'
SITE_COOKIE        = sliauth.SITE_COOKIE_PREFIX+'_'
EXPIRES_DAYS = 30
BATCH_AGE = 60      # Age of batch cookies (sec)

WS_TIMEOUT_SEC = 1200    # Aggressive websocket timeout OK, since clients can re-connect (with session versioning)
EVENT_BUFFER_SEC = 3

BACKUP_VERSION_FILE = '_version.txt'

SETTINGS_SHEET = 'settings_slidoc'

LATE_SUBMIT = 'late'
PARTIAL_SUBMIT = 'partial'

COOKIE_VERSION = '0.97.21a'             # Update version if cookie format changes (automatically deletes previous secure cookies)
SERVER_NAME = 'Webster0.9'

RAW_UPLOAD = 'raw'
TOP_LEVEL = 'top'

def preElement(content):
    return '<pre>'+tornado.escape.xhtml_escape(str(content))+'</pre>'

def checkAccessCode(inputCode, userId, sessionName):
    requireCode = Global.accessCodes.get(sessionName)
    if requireCode and (not inputCode.isdigit() or int(inputCode) != requireCode):
        raise Exception('Error:NEED_ACCESS_CODE:Need access code for session')

def updateAccessCode(sessionName, paceLevel, dueDate, accessCode):
    if sessionName in Global.accessCodes:
        if not accessCode or dueDate:
            del Global.accessCodes[sessionName]
    else:
        if accessCode and not dueDate:
            Global.accessCodes[sessionName] = random.randrange(1+10**(accessCode-1), 10**accessCode)

def getSessionType(sessionName):
    if '--' in sessionName:
        raise Exception('Invalid session name "%s"; must not include double hyphen "--"' % sessionName)

    if '_' in sessionName:
        # This restriction could be relaxed in the future
        raise Exception('Invalid session name "%s"; must not include underscore (for now)' % sessionName)

    suffix = sessionName.rpartition('_')[2]
    if suffix in sdproxy.RESERVED_SUFFIXES:
        raise Exception('Invalid session name "%s"; must not end in reserved suffix _%s' % (sessionName, suffix))

    smatch = sliauth.SESSION_NAME_RE.match(sessionName)
    if smatch:
        sessionType = smatch.group(1)
        sessionNumber = int(smatch.group(2))
        return (sessionType, sessionNumber)

    if sliauth.SESSION_NAME_TOP_RE.match(sessionName):
        return (TOP_LEVEL, 0)

    raise Exception('Invalid session name "%s"; must be of the form "word.md" or "word01.md", with exactly two digits before the file extension and a letter before the digits' % sessionName)

def getResponderCount(sessionName, uploadType):
    if sessionName != 'index' and uploadType != TOP_LEVEL:
        sheet = sdproxy.getSheet(sessionName)
        if sheet and sheet.getLastRow() > 2:
            return sheet.getLastRow() - 2
    return 0

def getSessionLabel(sessionName, sessionType):
    sessionLabel = sessionName
    if sessionType != TOP_LEVEL and sessionName == 'index':
        sessionLabel = sessionType+'/index'
    return sessionLabel

def getSessionPath(sessionName, sessionType='', site_prefix=False, toc=False):
    # Return path to session HTML file, including '/' prefix and optionally site_prefix
    # If toc, return path to session ToC
    if not sessionType and sessionName:
        sessionType, _ = getSessionType(sessionName)

    if sessionType:
        path = '/' + ('index' if toc else sessionName) + '.html'
        if sessionType != TOP_LEVEL:
            path = SiteProps.private_prefix(sessionType) + '/' + sessionType + path
    else:
        path = '/'

    if site_prefix and Options['site_name']:
        path = '/' + Options['site_name'] + path
    return path

def nextSession(sessionName, back=False):
    # Returns name of nextSession if it can be navigated to else null string
    smatch = sliauth.SESSION_NAME_RE.match(sessionName)
    if not smatch:
        return ''

    sessionType = smatch.group(1)
    sessionNumber = int(smatch.group(2))
    nextSessionNumber = (-1 if back else 1) + sessionNumber
    if not nextSessionNumber:
        return ''

    nextSessionName = sliauth.SESSION_NAME_FMT % (sessionType, nextSessionNumber)

    nextSessionFile = os.path.join(BaseHandler.site_web_dir, getSessionPath(nextSessionName, sessionType)[1:])
    if not os.path.isfile(nextSessionFile):
        return ''
        
    if SiteProps.paced_session(sessionType):
        try:
            sessionEntries = sdproxy.lookupValues(nextSessionName, ['releaseDate'], sdproxy.INDEX_SHEET)
            releaseDate = sessionEntries['releaseDate']
        except Exception, excp:
            return ''
    else:
        with open(nextSessionFile) as f:
            fileOpts = slidoc.parse_merge_args(sliauth.read_header_opts(io.BytesIO(f.read()))[0], '', slidoc.Conf_parser, {})
        releaseDate = sliauth.parse_date(fileOpts.release_date)

    if releaseDate and (not isinstance(releaseDate, datetime.datetime) or sliauth.epoch_ms(releaseDate) > sliauth.epoch_ms()):
        # Unreleased session
        return ''

    return nextSessionName

def restricted_user_access(start_date, end_date, site_role=None, site_access='', batch_mode=''):
    if site_role:
        # Admin.grader access
        return ''

    if batch_mode and site_access == sdproxy.SITE_ADMINONLY:
        return ''

    if site_access and site_access != sdproxy.SITE_LOCKED:
        # Restricted site
        if site_access == sdproxy.SITE_ADMINGUEST and site_role is not None:
            # Restricted guest access
            return ''
        return 'restricted'

    cur_time_ms = sliauth.epoch_ms()
    if start_date and cur_time_ms < sliauth.epoch_ms(sliauth.parse_date(start_date)):
        # Prerelease site
        return 'prerelease'
    elif end_date and cur_time_ms > sliauth.epoch_ms(sliauth.parse_date(end_date)):
        # Expired site
        return 'expired'

    # Open, unexpired site
    return ''

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

def discussStats(userId, sessionName=''):
    nameMap = sdproxy.getDisplayNames()
    stats = sdproxy.getDiscussStats(userId, sessionName)
    paths = {}
    for session in stats['sessions']:
        paths[session] = getSessionPath(session, site_prefix=True)
    blocks = {}
    for blockedId in stats['blocked']:
        blocks[blockedId] = nameMap.get(blockedId, blockedId)
    return {'sessions': stats['sessions'], 'paths': paths, 'flags': stats['flags'], 'blocks': blocks}

def zipdir(dirpath, inner=False):
    basedir = dirpath if inner else os.path.dirname(dirpath)
    stream = io.BytesIO()
    zfile = zipfile.ZipFile(stream, 'w')
    for dirname, subdirs, files in os.walk(dirpath):
        if dirname != basedir:
            zfile.write(dirname, os.path.relpath(dirname, basedir))
        for filename in files:
            fpath = os.path.join(dirname, filename)
            relpath = os.path.relpath(fpath, basedir)
            zfile.write(fpath, relpath)
    zfile.close()
    return stream.getvalue()

class SiteMixin(object):
    def set_site_cookie(self, cookieStr):
        self.set_secure_cookie(SITE_COOKIE_SECURE+Options['site_name'], cookieStr, expires_days=EXPIRES_DAYS)
        self.set_cookie(SITE_COOKIE+Options['site_name'], cookieStr, expires_days=EXPIRES_DAYS)

    def get_site_cookie(self):
        if Options['insecure_cookie']:
            cookieStr = self.get_cookie(SITE_COOKIE+Options['site_name'])
        else:
            cookieStr = self.get_secure_cookie(SITE_COOKIE_SECURE+Options['site_name']) if self.get_cookie(SITE_COOKIE+Options['site_name']) else ''
        return cookieStr

    def clear_site_cookie(self):
        self.clear_cookie(SITE_COOKIE+Options['site_name'])
        self.clear_cookie(SITE_COOKIE_SECURE+Options['site_name'])

    def site_cookie_data(self):
        siteName = Options['site_name'] or ''
        cookie_data = {'version': COOKIE_VERSION, 'site': siteName, 'pluginDataPath': '/'+PLUGINDATA_PATH}
        if Options['source_dir']:
            cookie_data['editable'] = 'edit'

        siteMenu = SiteProps.get_site_menu()
        if 'gradebook' in siteMenu:
            cookie_data['gradebook'] = 1
        if 'files' in siteMenu:
            cookie_data['files'] = 1

        return sliauth.safe_quote( base64.b64encode(json.dumps(cookie_data,sort_keys=True)) )

class UserIdMixin(object):
    user_nonces = defaultdict(dict)
    image_path = re.compile(r'^(.*)/([^/]+)_images/([^/]+)$')
    @classmethod
    def get_path_base(cls, path, special=False, handle_image=False):
        # Extract basename, without file extension, from URL path
        # If not special, return None if non-html file or index.html
        if ('/'+FILES_PATH) in path:
            return None

        if handle_image:
            imatch = cls.image_path.match(path)
            if imatch:
                return imatch.group(2)

        if not special and not path.endswith('.html'):
            return None
        basename = path.split('/')[-1]
        if '.' in basename:
            basename, sep, suffix = basename.rpartition('.')
        if not special and basename == 'index':
            return None
        return basename

    def is_web_view(self):
        # Check if web view (for locked access)
        return re.search(r';\s*wv', self.request.headers.get('User-Agent',''), re.IGNORECASE)

    def set_id(self, username, role='', sites='', displayName='', email='', altid='', data={}):
        if Options['debug']:
            print >> sys.stderr, 'sdserver.UserIdMixin.set_id', username, role, sites, displayName, email, altid, data

        if ':' in username or ':' in role or ':' in sites or ':' in displayName:
            raise Exception('Colon character not allowed in username/role/name')

        cookie_data = {'version': COOKIE_VERSION}
        cookie_data['name'] = displayName or username
        if email:
            cookie_data['email'] = email
        if altid:
            cookie_data['altid'] = altid

        cookie_data.update(data or {})

        token = gen_proxy_auth_token(username, role, sites, root=True)
        cookieStr = ':'.join( sliauth.safe_quote(x) for x in [username, role, sites, token, base64.b64encode(json.dumps(cookie_data,sort_keys=True))] )

        self.set_user_cookie(cookieStr, batch=cookie_data.get('batch'))

    def set_user_cookie(self, cookieStr, batch=False):
        if batch:
            self.set_secure_cookie(USER_COOKIE_SECURE, cookieStr, max_age=BATCH_AGE)
            self.set_cookie(USER_COOKIE, cookieStr, max_age=BATCH_AGE)
        else:
            self.set_secure_cookie(USER_COOKIE_SECURE, cookieStr, expires_days=EXPIRES_DAYS)
            self.set_cookie(USER_COOKIE, cookieStr, expires_days=EXPIRES_DAYS)

    def get_user_cookie(self):
        # Ensure USER_COOKIE is also set before retrieving id from secure cookie (in case one of them gets deleted)
        if Options['insecure_cookie']:
            cookieStr = self.get_cookie(USER_COOKIE)
        else:
            cookieStr = self.get_secure_cookie(USER_COOKIE_SECURE) if self.get_cookie(USER_COOKIE) else ''
        return cookieStr

    def clear_user_cookie(self):
        username = self.get_id_from_cookie()
        for root_user in Options['root_users']:
            if username != root_user and username == Global.userRoles.map_user(root_user):
                # Remove alias from root user to user logging out
                Global.userRoles.add_alias(root_user, '')

        self.clear_cookie(USER_COOKIE)
        self.clear_cookie(USER_COOKIE_SECURE)

    def revert_to_plain_user(self):
        username = self.get_id_from_cookie()
        role, sites = Global.userRoles.id_role_sites(username)
        if role:
            # Global role; switch to guest in all sites
            plainSites = ','.join(Options['site_list'])
        else:
            # Site roles; switch to guest in sites
            plainSites = ','.join(site.split('+')[0] for site in sites.split(','))

        name = self.get_id_from_cookie(name=True)
        data = self.get_id_from_cookie(data=True)
        self.set_id(username, displayName=name, role='', sites=plainSites, email=self.get_id_from_cookie(email=True), data=data)

    def check_locked_token(self, username, token, site, session):
        return token == sliauth.gen_locked_token(sliauth.gen_site_key(Options['root_auth_key'], site), username, site, session)

    def check_access_token(self, username, token, role=''):
        return token == gen_proxy_auth_token(username, role, root=True)

    def get_id_from_cookie(self, role=False, for_site='', sites=False, name=False, email=False, altid=False, data=False):
        # If for_site and site name does not appear in cookie.sites, None will be returned for role
        # Null string will be returned for role, if site name is present
        cookieStr = self.get_user_cookie()
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
            self.clear_user_cookie()
            return None

    def check_site_access(self):
        userId = self.get_id_from_cookie() or None
        siteRole = self.get_id_from_cookie(role=True, for_site=Options['site_name'])

        # Check if pre-authorized for site access
        if Options['site_name']:
            # Check if site is explicitly authorized (user has global admin/grader role, or has explicit site listed, including guest users)
            preAuthorized = siteRole is not None
        else:
            # Single site: check if userid is special (admin/grader/guest)
            preAuthorized = Global.userRoles.is_special_user(userId)

        if preAuthorized:
            return

        if Global.login_domain and '@' in userId:
            # External user
            raise tornado.web.HTTPError(403, log_message='CUSTOM:User %s not pre-authorized to access site' % userId)

        # Check if userId appears in roster
        if sdproxy.getSheet(sdproxy.ROSTER_SHEET):
            if not sdproxy.lookupRoster('id', userId):
                raise tornado.web.HTTPError(403, log_message='CUSTOM:Userid %s not found in roster for site %s' % (userId, Options['site_name']))
        elif not sdproxy.Settings['no_roster']:
                raise tornado.web.HTTPError(403, log_message='CUSTOM:No roster available for site %s' % Options['site_name'])

    def create_nonce(self, token, site_name='', userId=''):
        site_key = sliauth.gen_site_key(Options['root_auth_key'], site_name) if site_name else Options['root_auth_key']
        upload_key = sliauth.gen_hmac_token(site_key, 'upload:')
        if token != sliauth.gen_hmac_token(upload_key, 'nonce:'+userId):
            return None
        nonce = str(random.randint(10000001,99999999))
        self.user_nonces[site_name][userId] = nonce
        return nonce

    def use_nonce(self, site_name='', userId=''):
        return self.user_nonces[site_name].pop(userId, None)

    def batch_login(self, site_name=''):
        # Batch auto login for localhost through query parameter: ...?auth=userId:token
        # To print exams using headless browser: ...?auth=userId:token&print=1
        site_key = sliauth.gen_site_key(Options['root_auth_key'], site_name) if site_name else Options['root_auth_key']
        upload_key = sliauth.gen_hmac_token(site_key, 'upload:')

        userId, batchMode, siteRole, cookieData = None, None, None, None
        query = self.request.query
        if query.startswith('auth='):
            query = query.split('&')[0]
            qauth = urllib.unquote(query[len('auth='):])
            temUserId, token = qauth.split(':')
            nonce = self.use_nonce(site_name, temUserId)
            if nonce:
                batchToken = sliauth.gen_hmac_token(upload_key, 'batch:'+temUserId+':'+nonce)
                if token == upload_key or token == batchToken:
                    batchMode = site_name or '_root'
                    cookieData = {'batch': batchMode}
                elif token == gen_proxy_auth_token(temUserId, root=True):
                    cookieData = {}
                else:
                    print >> sys.stderr, 'sdserver: Invalid auth= for temUserId '+temUserId
                    temUserId = None

                if temUserId is not None:
                    userId = temUserId
                    print >> sys.stderr, "UserIdMixin.batch_login: BATCH ACCESS", self.request.path, site_name, userId
                    self.set_id(userId, displayName=userId, data=cookieData)
        return userId, batchMode, siteRole, cookieData

    def custom_error(self, errCode, html_msg, clear_cookies=False):
        if clear_cookies:
            self.clear_user_cookie() 
        self.clear()
        self.set_status(errCode)
        self.finish(html_msg)


class BaseHandler(tornado.web.RequestHandler, UserIdMixin):
    site_src_dir = None
    site_web_dir = None
    site_data_dir = None
    site_backup_dir = None
    site_files_dir = None
    @classmethod
    def setup_dirs(cls, site_name=''):
        sitePrefix = '/'+site_name if site_name else ''
        cls.site_src_dir    = Options['source_dir'] + sitePrefix if Options['source_dir'] else None
        cls.site_web_dir    = Options['web_dir'] + sitePrefix
        cls.site_data_dir   = Options['plugindata_dir'] + sitePrefix + '/' + PLUGINDATA_PATH if Options['plugindata_dir'] else None
        cls.site_backup_dir = Options['backup_dir'] + sitePrefix if Options['backup_dir'] else None

        if site_name and Options['restore_backup'] and Options['dry_run'] and not Options['dry_run_file_modify']:
            # Restoring from backup, dry run without file modification; override source/web/data directories with backup directories
            site_bak_dir = os.path.join(Options['restore_backup'][0], site_name, Options['restore_backup'][1])
            if cls.site_src_dir:
                temdir = os.path.join(site_bak_dir, '_source')
                if os.path.exists(temdir):
                    cls.site_src_dir = temdir
            if cls.site_web_dir:
                temdir = os.path.join(site_bak_dir, '_web')
                if os.path.exists(temdir):
                    cls.site_web_dir = temdir
            if cls.site_data_dir:
                temdir = os.path.join(site_bak_dir, PLUGINDATA_PATH)
                if os.path.exists(temdir):
                    cls.site_data_dir = temdir

        cls.site_files_dir = os.path.join(cls.site_web_dir, FILES_PATH)

        if Options['dry_run'] and not Options['dry_run_file_modify']:
            return

        if Options['web_dir'] and os.path.exists(Options['web_dir']) and Options['auth_type'] != 'none':
            homeWeb = cls.site_web_dir+'/index.html'
            try:
                # Create dummy home web page
                if not os.path.exists(cls.site_web_dir):
                    os.makedirs(cls.site_web_dir)
                if not os.path.exists(homeWeb):
                    with open(homeWeb, 'w') as f:
                        f.write('<b>%s Site Page</b> (<a href="_edit/index">edit</a> this page)' % site_name)
                    print >> sys.stderr, 'sdserver: Created %s' % homeWeb
            except Exception, excp:
                print >> sys.stderr, 'sdserver: Failed to create home web page %s' % homeWeb

        if Options['source_dir'] and os.path.exists(Options['source_dir']):
            homeSrc = cls.site_src_dir+'/index.md' if cls.site_src_dir else None
            try:
                # Create dummy home source page
                if not os.path.exists(cls.site_src_dir):
                    os.makedirs(cls.site_src_dir)
                if not os.path.exists(homeSrc):
                    with open(homeSrc, 'w') as f:
                        f.write('**%s Site Page** ([edit](_edit/index) this page)' % site_name)
                    print >> sys.stderr, 'sdserver: Created %s' % homeSrc
            except Exception, excp:
                print >> sys.stderr, 'sdserver: Failed to create home source %s' % homeSrc

    def set_default_headers(self):
        # Completely disable cache
        self.set_header('Server', SERVER_NAME)
        self.set_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')

    def get_current_user(self):
        if not Options['auth_key']:
            self.clear_user_cookie()
            return "noauth"
        return self.get_id_from_cookie() or None

    def write_error(self, status_code, **kwargs):
        err_cls, err, traceback = kwargs['exc_info']
        if getattr(err, 'log_message', None) and err.log_message.startswith('CUSTOM:'):
            print >> sys.stderr, err.log_message
            customMsg = err.log_message[len('CUSTOM:'):].strip()
            if customMsg.startswith('<'):
                self.write('<html><body><h3>%s</h3></body></html>' % customMsg)
            else:
                self.write('<pre>%s</pre>' % customMsg.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;'))
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

    def check_root_admin(self, token=''):
        if Options['root_auth_key'] and token == Options['root_auth_key']:
            return True
        return self.get_id_from_cookie(role=True) == sdproxy.ADMIN_ROLE

    def check_site_admin(self, site_name=''):
        role = self.get_id_from_cookie(role=True, for_site=site_name)
        if role == sdproxy.ADMIN_ROLE:
            return True
        return self.get_id_from_cookie(role=True) == sdproxy.ADMIN_ROLE

    def displayMessage(self, message, html_prefix='', back_url=''):
        if isinstance(message, list):
            message = preElement('\n'+'\n'.join(message)+'\n')+'\n'
        self.render('message.html', site_name=Options['site_name'], message=html_prefix+message, back_url=back_url)


class InvalidHandler(BaseHandler):
    def get(self):
        self.set_header('Content-Type', 'text/plain')
        self.write('Invalid path: %s (%d:%s)' % (self.request.path, Options['site_number'], Options['site_name']))

class HomeHandler(BaseHandler):
    def get(self, subpath='', subsubpath=''):
        if self.is_web_view():
            # For embedded browsers ("web views"), Google login does not work; use token authentication
            self.redirect('/_auth/login/')
            return
        if subpath == '_nonce':
            userId = self.get_argument('userid', '')
            token = self.get_argument('token', '')
            nonce = self.create_nonce(token, subsubpath, userId)
            if not nonce:
                raise tornado.web.HTTPError(403)
            self.write(nonce)
            return
        if subpath == '_batch_login':
            next = self.get_argument('next', '/')
            userId, _, _, _ = self.batch_login(subsubpath)
            if not userId:
                raise tornado.web.HTTPError(403)
            self.redirect(next)
            return
            
        if Options['multisite'] and not Options['site_number']:
            # Primary server
            openSites = []
            restrictedSites = []
            SiteInfo = namedtuple('SiteInfo', ['name', 'restrict', 'role', 'hide', 'label', 'title'])
            for siteName in Options['site_list']:
                siteConfig = SiteOpts[siteName]
                siteRole = self.get_id_from_cookie(role=True, for_site=siteName)
                siteAccess = siteConfig.get('site_access','')
                startDate = siteConfig.get('start_date','')
                endDate = siteConfig.get('end_date','')
                hideStr = restricted_user_access(startDate, endDate, siteRole, siteAccess)
                siteRestriction = restricted_user_access(startDate, endDate)  # 'prerelease' or 'expired' or ''
                if siteAccess:
                    # Expired
                    siteRestriction = siteAccess+' '+siteRestriction if siteRestriction else siteAccess
                child = Global.child_procs.get(siteName)
                if siteName in SiteProps.sitesDeactivated:
                    siteRestriction += ' DEACTIVATED'
                if not child or child.proc.poll() is not None:
                    siteRestriction += ' <a href="/_restart/%s">RESTART</a>' % siteName

                tem_tuple = SiteInfo(siteName, siteRestriction, siteRole, hideStr, siteConfig['site_label'], siteConfig['site_title'])
                if siteRestriction:
                    restrictedSites.append(tem_tuple)
                else:
                    openSites.append(tem_tuple)

            cookieData = self.get_id_from_cookie(data=True) or {}
            self.render('index.html', user=self.get_current_user(), status='',
                         login_url=Global.login_url, logout_url=Global.logout_url, global_role=self.get_id_from_cookie(role=True),
                         batch_mode=cookieData.get('batch',''), sites=openSites+restrictedSites)
            return
        elif Options.get('_index_html'):
            # Not authenticated
            self.write(Options['_index_html'])
        else:
            index_path = os.path.join(self.site_web_dir, 'index.html')
            if not os.path.exists(index_path):
                self.write('No home page found for site %s' % Options['site_name'])
            else:
                url = '/'+Options['site_name']+'/index.html' if Options['site_number'] else '/index.html'
                if sdproxy.proxy_error_status():
                    self.write('Read-only mode; session modifications are disabled. Proceed to <a href="%s">Site Page</a>' % url)
                else:
                    # Authenticated by static file handler, if need be
                    self.redirect(url)

class RootActionHandler(BaseHandler):
    def get(self, action='', skip='', subsubpath=''):
        userId = self.get_current_user()
        if Options['debug']:
            print >> sys.stderr, 'DEBUG: RootActionHandler.get', userId, Options['site_number'], action
        if action == '_logout':
            self.clear_user_cookie()
            self.render('logout.html')
            return
        root = str(self.get_argument("root", ""))
        token = str(self.get_argument("token", ""))

        if not self.check_admin_access(token=token, root=root):
            raise tornado.web.HTTPError(403)

        # Global admin user
        link_html = '<p></p><b><a href="/">Root home</a><p></p><a href="/_setup">Setup</a></b>'

        if not Options['reload'] and (action == '_reload' or (action == '_update' and subsubpath == 'pull')):
            self.write('Please restart server with --reload option for action '+action)
            self.write(link_html)

        if action == '_setup':
            cert_expiry = ''
            days_left = cert_daysleft()
            if days_left is not None:
                cert_expiry = str(days_left) + ' days'
            self.render('setup.html', site_name='', session_name='', status='', site_updates=[],
                        multisite=Options['multisite'], aliases=Global.userRoles.list_aliases(),
                        sites=Options['site_list'], cert_expiry=cert_expiry,
                        server_version=sliauth.VERSION, versions=SiteProps.siteScriptVersions)

        elif action == '_alias':
            amaps = []
            for alias in subsubpath.split(','):
                origId, sep, userId = alias.strip().partition('=')
                origId = origId.strip()
                userId = userId.strip() if sep else origId
                    
                Global.userRoles.add_alias(origId, userId)
                amaps.append('%s=%s' % (origId, userId))
            self.displayMessage('Aliases '+','.join(amaps), back_url='/_setup')

        elif action == '_backup':
            self.displayMessage(backupSite(subsubpath, broadcast=True), back_url='/_setup')

        elif action == '_deactivate':
            msgs = []
            if Options['multisite']:
                sites = Options['site_list']
            else:
                sites = ['']
            for site_name in sites:
                site_settings = SiteOpts[site_name] if site_name else Global.site_settings
                if SiteProps.root_site_deactivate(site_name, site_settings['gsheet_url']):
                    msgs.append('Deactivated site %s' % site_name)
            self.displayMessage('\n'.join(msgs), back_url='/_setup')

        elif action == '_terminate':
            # Terminate site(s) gracelessly
            site_name = subsubpath
            if site_name:
                child = Global.child_procs.get(site_name)
                if child and child.proc.poll() is None:
                    try:
                        child.proc.kill()
                        self.displayMessage('Terminated site %s' % site_name, back_url='/_setup')
                    except Exception, excp:
                        self.displayMessage('Error in restarting site %s: %s' % (site_name, excp), back_url='/_setup')
                else:
                    self.displayMessage('Site %s already terminated' % site_name, back_url='/_setup')
            else:
                self.write('Starting termination for all sites<p></p>')
                self.write(link_html)
                for site_name, child in Global.child_procs.items():
                    try:
                        child.proc.kill()
                    except Exception, excp:
                        self.write('Error in terminating site %s: %s<br>' % (site_name, excp))

        elif action == '_restart':
            site_name = subsubpath
            child = Global.child_procs.get(site_name)
            if not child:
                self.displayMessage('Site %s not found!' % site_name, back_url='/_setup')
            elif child.proc.poll() is None:
                self.displayMessage('Site %s already active' % site_name, back_url='/_setup')
            else:
                root_start_secondary(get_site_number(site_name), site_name)
                self.displayMessage('<b>Restarting site: <a href="/%s">%s</a><br>Please wait a bit before accessing it</b>' % (site_name, site_name), back_url='/_setup')

        elif action == '_reload':
            print >> sys.stderr, 'sdserver: Shutting down sites (blocking)'
            shutdown_sites(wait=True)
            reload_server()
            self.displayMessage('Reloading...', back_url='/_setup')

        elif action == '_renewssl':
            outHtml = ''
            renew_status = renew_ssl(force=True)
            if renew_status:
                outHtml += preElement(renew_status + '\n')
            self.displayMessage(outHtml+'<p></p>Reloading...', back_url='/_setup')

        elif action == '_update':
            outHtml = ''
            try:
                sudo_prefix = ['sudo', '-u', os.environ['SUDO_USER']] if os.environ.get('SUDO_USER') else []

                cmd = sudo_prefix + ['git', 'fetch', 'origin']

                print >> sys.stderr, 'Executing: '+' '.join(cmd)
                fetchOutput = subprocess.check_output(cmd, cwd=scriptdir)

                cmd = sudo_prefix + ['git', 'log', 'HEAD..origin/master', '--oneline']

                print >> sys.stderr, 'Executing: '+' '.join(cmd)
                logOutput = subprocess.check_output(cmd, cwd=scriptdir)

                if not logOutput.strip():
                    self.displayMessage('Software is up to date', back_url='/_setup')
                    return

                if subsubpath != 'pull':
                    self.displayMessage('Software updates are available:'+('\n\n'+logOutput if Options['debug'] else ''), back_url='/_setup')
                    return

                print >> sys.stderr, 'sdserver: Shutting down sites (blocking)'
                shutdown_sites(wait=True)

                if Global.backup:
                    Global.backup.stop()
                    Global.backup = None

                cmd = sudo_prefix + ['git', 'pull']

                print >> sys.stderr, 'Executing: '+' '.join(cmd)
                outHtml += preElement('Executing: '+' '.join(cmd))
                pullOutput = subprocess.check_output(cmd, cwd=scriptdir)

                print >> sys.stderr, 'Output:\n%s' % pullOutput
                outHtml += preElement('Output:\n'+pullOutput)

                # Schedule reload (update may already have triggered reloading)
                outHtml += 'Reloading server(s) ... (wait 30-60s)'
                reload_server()

            except Exception, excp:
                errMsg = 'Updating via git pull failed: '+str(excp)
                print >> sys.stderr, errMsg
                outHtml += preElement(errMsg + '\n')

            self.displayMessage(outHtml, back_url='/_setup')

        elif action == '_shutdown':
            # Shutdown gracefully (specfy root as subsubpath to shutdown root as well)
            self.clear_user_cookie()
            self.write('Starting shutdown (also cleared cookies)<p></p>')
            self.write(link_html)
            if Options['multisite'] and not Options['site_number']:
                # Root server
                shutdown_all(wait=True)
            else:
                if Global.backup:
                    Global.backup.stop()
                    Global.backup = None
                    
                if Global.twitterStream:
                    try:
                        Global.twitterStream.end_stream()
                        Global.twitterStream = None
                    except Exception, err:
                        pass

                sdproxy.suspend_cache('shutdown')

        else:
            raise tornado.web.HTTPError(403, log_message='CUSTOM:Invalid root action '+action)

class SiteActionHandler(BaseHandler):
    def get(self, action='', skip='', subsubpath=''):
        userId = self.get_current_user()
        site_name = subsubpath
        if Options['debug']:
            print >> sys.stderr, 'DEBUG: SiteActionHandler.get', userId, action, site_name

        new_site = self.get_argument('new_site', '')
        if Options['multisite'] and site_name not in Options['site_list'] and not new_site:
            raise tornado.web.HTTPError(404)

        if not self.check_site_admin(site_name):
            raise tornado.web.HTTPError(403)

        # Global admin user
        if action == '_site_settings':
            if not site_name:
                site_settings = Global.site_settings
            else:
                if new_site:
                    with open(Global.config_file) as f:
                        if Global.config_digest != sliauth.digest_hex(f.read()):
                            err_msg = 'Config file %s has changed; unable to create site' % Global.config_file

                site_settings_file = os.path.join(Global.config_path, site_name+'.json') if os.path.isdir(Global.config_path) else ''
                if new_site:
                    if site_name in Options['site_list']:
                        self.displayMessage('ERROR:Site %s already present!' % site_name, back_url='/_setup')
                        return

                    if site_settings_file and os.path.exists(site_settings_file) and not Options['dry_run']:
                        self.displayMessage('ERROR:Configuration file %s already exists for new site!' % site_settings_file, back_url='/_setup')
                        return

                    site_settings = dict( (key, '') for key, value in SETTINGS_LABELS if key)
                    site_settings['site_label'] = site_name+'-label'
                    site_settings['site_title'] = 'Title for '+site_name
                else:
                    # Old site
                    if site_name not in Options['site_list']:
                        self.displayMessage('Site %s not found!' % site_name, back_url='/_setup')
                        return
                    if not Options['dry_run'] and site_settings_file and not os.path.exists(site_settings_file):
                        self.displayMessage('Site settings file %s not found!' % site_settings_file, back_url='/_setup')
                        return
                    if not Options['reload']:
                        self.displayMessage('Enable --reload option to edit site settings', back_url='/_setup')
                        return

                    site_settings = SiteOpts[site_name]

            site_key = sliauth.gen_site_key(Options['root_auth_key'], site_name) if site_name else Options['root_auth_key']
            self.render('settings.html', site_name=site_name, new_site=new_site, err_msg='',
                        settings_labels=SETTINGS_LABELS, site_key=site_key, site_settings=site_settings)

        elif action == '_site_delete':
            self.displayMessage(SiteProps.root_site_delete(site_name), back_url='/_setup')

        else:
            raise tornado.web.HTTPError(403, log_message='CUSTOM:Invalid root site action '+action)

    @tornado.gen.coroutine
    def post(self, action='', skip='', subsubpath=''):
        userId = self.get_current_user()
        site_name = subsubpath
        if Options['debug']:
            print >> sys.stderr, 'DEBUG: SiteActionHandler.post', userId, action, site_name

        new_site = self.get_argument('new_site', '')
        if Options['multisite'] and site_name not in Options['site_list'] and not new_site:
            raise tornado.web.HTTPError(404)

        if not self.check_site_admin(site_name):
            raise tornado.web.HTTPError(403)

        if action == '_site_settings':

            errMsg = ''
            site_settings = dict( (argname, self.get_argument(argname, '')) for argname, arglabel in SETTINGS_LABELS if argname)
            sec_config = site_settings
            cumulative_total = site_settings.get('cumulative_total','').replace(' ','')
            errTerms =  [term for term in cumulative_total.split('+') if not CUMULATIVE_TOTAL_RE.match(term)] if cumulative_total else []

            gsheet_url = site_settings['gsheet_url']
            if not Options['dry_run'] and not gsheet_url:
                errMsg = 'gsheet_url must be specified for site (if not dry run)'

            elif site_settings['site_access'] and site_settings['site_access'] not in sdproxy.SITE_ACCESS:
                errMsg = 'site_access must be one of: '+', '.join(sdproxy.SITE_ACCESS)

            elif errTerms:
                errMsg = 'Invalid term(s) in cumulative_total formula: %s.\n Expecting terms like 0.2*assignment_avg_1' % (', '.join(errTerms))

            elif not new_site and not Options['reload']:
                errMsg = 'Enable --reload sdserver option to modify site settings'

            if not errMsg and new_site:
                with open(Global.config_file) as f:
                    if Global.config_digest != sliauth.digest_hex(f.read()):
                        errMsg = 'Config file %s has changed; unable to create site' % Global.config_file

            if errMsg:
                site_key = sliauth.gen_site_key(Options['root_auth_key'], site_name) if site_name else Options['root_auth_key']
                self.render('settings.html', site_name=site_name, new_site=new_site, err_msg=errMsg,
                            settings_labels=SETTINGS_LABELS, site_key=site_key, site_settings=site_settings)
                return

            site_settings_file = ''
            try:
                if not site_name:
                    SiteProps.root_site_setup(0, '', gsheet_url)
                else:
                    if not new_site:
                        site_number = get_site_number(site_name)
                        if not site_number:
                            self.displayMessage('Unknown/invalid site name %s' % site_name, back_url='/_setup')
                            return

                        child = Global.child_procs.get(site_name)
                        if child and child.proc.poll() is None:
                            # Shutdown site
                            relay_addr = SiteProps.relay_map(site_number)
                            retval = sendPrivateRequest(relay_addr, path='/'+site_name+'/_shutdown?root='+sliauth.safe_quote(Options['server_key']))

                            # Wait for running process to exit
                            print >> sys.stderr, 'sdserver.site_settings: Waiting for site %s process to exit' % site_name
                            ret = yield child.wait_for_exit(raise_error=False)

                        root_add_site(site_name, site_settings, overwrite=True)
                        SiteProps.root_site_setup(site_number, site_name, gsheet_url, update=True)
                    else:
                        root_add_site(site_name, site_settings, overwrite=True)
                        SiteProps.root_site_setup(get_site_number(site_name), site_name, gsheet_url, new=True)

                if not Options['dry_run']:
                    if site_name and os.path.isdir(Global.config_path):
                        site_settings_file = os.path.join(Global.config_path, site_name+'.json')
                    else:
                        site_settings_file = Global.site_settings_file
                    if site_settings_file:
                        sec_config = {}
                        with open(site_settings_file, 'w') as f:
                            json.dump(site_settings, f, indent=4, sort_keys=True)

            except Exception, excp:
                errMsg = str(excp)
                if Options['debug']:
                    import traceback
                    traceback.print_exc()

            if errMsg:
                self.displayMessage('Error in creating/editing site settings: '+errMsg, back_url='/')
                return

            msg = '<b>Created/updated site: <a href="/%s">%s</a><br>'  % (site_name, site_name or 'Home')
            if site_settings_file:
                msg += 'Updated site settings file '+tornado.escape.xhtml_escape(site_settings_file)+'<br>'
            if Options['multisite']:
                root_start_secondary(get_site_number(site_name), site_name, sec_config)
                msg += 'Please wait a bit before accessing site</b>'
            elif Options['reload'] and not sec_config:
                msg += 'Reloading server'
            else:
                msg += 'Restart server for changes to take effect'

            self.displayMessage(msg, back_url='/')

        else:
            raise tornado.web.HTTPError(403, log_message='CUSTOM:Invalid root site action '+action)


class ActionHandler(BaseHandler):
    previewState = {}
    cmd_opts =   { 'base': dict(debug=True),
                   'other': dict(),
                  }
    default_opts = { 'base':  dict(),
                     'other': dict(),
                     }
    fix_opts = set()
    unsafe_code = [random.randint(1000,6999)]

    def previewActive(self):
        return self.previewState.get('name', '')

    def get_config_opts(self, uploadType, text='', topnav=False, paced=False, dest_dir='', session_name='', image_dir='', make=''):
        # Return (cmd_args, default_args)
        defaultOpts = {}
        configOpts = slidoc.cmd_args2dict(slidoc.alt_parser.parse_args([]))
        for key, value in configOpts.items():
            if value is not None:
                defaultOpts[key] = value
                configOpts[key] = None

        defaultOpts.update(self.default_opts['base'])
        if uploadType in self.default_opts:
            defaultOpts.update(self.default_opts[uploadType])
        else:
            defaultOpts.update(self.default_opts['other'])

        if image_dir:
            defaultOpts.update(image_dir=image_dir)

        configOpts = slidoc.cmd_args2dict(slidoc.alt_parser.parse_args([]))
        configOpts.update(self.cmd_opts['base'])

        if make:
            configOpts['make'] = make

        if uploadType in self.cmd_opts:
            configOpts.update(self.cmd_opts[uploadType])
        else:
            configOpts.update(self.cmd_opts['other'])

        if uploadType in Global.session_options:
            # session-specific options (TBD)
            pass

        if SiteProps.paced_session(uploadType):
            defaultOpts['pace'] = 1
        else:
            configOpts['pace'] = 0

        if uploadType == TOP_LEVEL:
            defaultOpts['strip'] = 'chapters,contents'
        else:
            configOpts['create_toc'] = True
            configOpts['session_type'] = uploadType

        if text and 0:
            # DISABLED because this applies to single file edit but not whole directory rebuilds
            # Results in file options being treated like command line options for single files, but not rebuilds
            # leading to minimum pace level requirement not working for single file edits
            # TODO: Eliminate unused text argument for this function
            fileOpts = vars(slidoc.parse_merge_args(sliauth.read_header_opts(io.BytesIO(text))[0], '', slidoc.Conf_parser, {}))
            for key, value in fileOpts.items():
                if key not in self.fix_opts and value is not None:
                    # Override with file opts
                    configOpts[key] = value

        configOpts.update(site_name=Options['site_name'])
        configOpts.update(server_url=Options['server_url'])
        if topnav:
            configOpts.update(topnav=','.join(self.get_topnav_list(uploadType=uploadType, session_name=session_name)))

        if Options['remote_logging']:
            configOpts.update(remote_logging=Options['remote_logging'])

        if Options['start_date']:
            configOpts.update(start_date=Options['start_date'])

        if SiteProps.paced_session(uploadType):
            site_prefix = '/'+Options['site_name'] if Options['site_name'] else ''
            configOpts.update(auth_key=Options['auth_key'], gsheet_url=site_prefix+'/_proxy',
                              proxy_url=site_prefix+'/_websocket')

        if dest_dir:
            configOpts.update(dest_dir=dest_dir)

        if Options['dry_run'] and not Options['dry_run_file_modify']:
            configOpts.update(dry_run=True)

        if Options['libraries_dir']:
            configOpts.update(libraries_url='/'+LIBRARIES_PATH)

        return configOpts, defaultOpts

    def get(self, subpath, inner=None):
        userId = self.get_current_user()
        if Options['debug'] and not self.get_argument('reload', ''):
            print >> sys.stderr, 'DEBUG: ActionHandler.get', userId, Options['site_number'], subpath
        if subpath == '_logout':
            self.clear_user_cookie()
            self.render('logout.html')
            return
        root = str(self.get_argument("root", ""))
        token = str(self.get_argument("token", ""))
        if not self.check_admin_access(token=token, root=root):
            if self.previewActive() and subpath.startswith('_preview/') and not self.get_user_cookie():
                next_url = '/' + subpath
                if Options['site_name']:
                    next_url = '/'+Options['site_name']+next_url
                self.redirect(Global.login_url+'?next='+urllib.quote_plus(next_url))
                return
            raise tornado.web.HTTPError(403, log_message='CUSTOM:<a href="/">Login</a> as admin to proceed %s' % self.previewActive())
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
            print >> sys.stderr, 'DEBUG: postAction', sliauth.iso_date(nosubsec=True), userId, Options['site_number'], subpath
        if not self.check_admin_access():
            raise tornado.web.HTTPError(403)
        return self.postAction(subpath)

    def put(self, subpath):
        if Options['debug']:
            print >> sys.stderr, 'DEBUG: putAction', Options['site_number'], subpath, len(self.request.body), self.request.arguments, self.request.headers.get('Content-Type')
        action, sep, subsubpath = subpath.partition('/')
        if action == '_remoteupload':
            uploadKey = sliauth.gen_hmac_token(Options['auth_key'], 'upload:')
            token = sliauth.gen_hmac_token(uploadKey, 'upload:'+sliauth.digest_hex(self.request.body))
            if self.get_argument('token') != token:
                raise tornado.web.HTTPError(404, log_message='CUSTOM:Invalid remote upload token')
            fname, fext = os.path.splitext(subsubpath)
            uploadType, sessionNumber, src_path, web_path, web_images = self.getUploadType(fname)
            errMsg = ''
            if fext == '.zip':
                fname1, fbody1, fname2, fbody2 = '', '', subsubpath, self.request.body
            else:
                fname1, fbody1, fname2, fbody2 = subsubpath, self.request.body, '', ''
                if fbody1 and fext == '.md':
                    fbody1 = sliauth.normalize_newlines(fbody1)

            try:
                errMsg = self.uploadSession(uploadType, sessionNumber, fname1, fbody1, fname2, fbody2, modimages='clear')
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

    @tornado.gen.coroutine
    def getAction(self, subpath):
        action, sep, subsubpath = subpath.partition('/')
        sessionName = subsubpath
        site_label = Options['site_label'] or 'Home'
        site_prefix = '/'+Options['site_name'] if Options['site_name'] else ''
        dash_url = site_prefix + '/_dash'
        json_return = self.get_argument('json', '')
        slideNumber = self.get_argument('slide', '')
        if slideNumber.isdigit():
            slideNumber = int(slideNumber)
        else:
            slideNumber = None
        previewingSession = self.previewActive()
        if not Options['multisite'] or Options['site_number']:
            # Secondary server
            root = str(self.get_argument('root', ''))
            modifiedStr = self.get_argument('modified', '')
            modifiedNum = sdproxy.parseNumber(modifiedStr) or 0

            if action == '_preview' or (action == '_startpreview' and previewingSession == sessionName):
                if not previewingSession:
                    self.displayMessage('Not previewing any session')
                    return
                cachePreview = sdproxy.previewingSession()
                if cachePreview and cachePreview != previewingSession:
                    # Inconsistent preview
                    self.discardPreview()
                    raise tornado.web.HTTPError(404, log_message='CUSTOM:Preview state inconsistent; resetting')

                if action == '_preview' and (subsubpath and subsubpath != 'index.html'):
                    # Messages/image preview (passthru)
                    self.displayPreview(subsubpath)
                    return

                # Ensure that current preview modification version is an URL parameter for content preview
                if modifiedStr and modifiedNum == self.previewState['modified']:
                    self.displayPreview(subsubpath)
                    return

                self.redirectPreview(update=self.get_argument('update', ''), slideId=self.get_argument('slideid', ''))
                return

            elif action == '_startpreview':
                if not previewingSession:
                    slideId = self.get_argument('slideid', '')
                    self.createUnmodifiedPreview(sessionName, slideId=slideId)
                    self.redirectPreview(slideId=slideId)
                    return
                else:
                    self.displayMessage('Already previewing session: <a href="%s/_preview/index.html">%s</a><p></p>' % (site_prefix, previewingSession))
                    return

            elif action == '_downloadpreview':
                if not previewingSession:
                    self.displayMessage('Not previewing any session')
                    return
                self.downloadPreview()
                return

            elif action == '_accept':
                if not Options['source_dir']:
                    raise tornado.web.HTTPError(403, log_message='CUSTOM:Must specify source_dir to upload')
                if not previewingSession:
                    self.displayMessage('Not previewing any session')
                    return
                self.acceptPreview(modified=modifiedNum, slideId=self.get_argument('slideid', ''))
                return

            elif action == '_edit':
                if not Options['source_dir']:
                    raise tornado.web.HTTPError(403, log_message='CUSTOM:Must specify source_dir to edit')
                if not sessionName:
                    sessionName = self.get_argument('sessionname', '')
                sessionType = self.get_argument('sessiontype', '')
                startPreview = self.get_argument('preview', '')
                if previewingSession:
                    if previewingSession != sessionName:
                        if slideNumber:
                            self.set_header('Content-Type', 'application/json')
                            self.write( json.dumps( {'result': 'error', 'error': 'Cannot edit sessions while previewing another session '+previewingSession} ) )
                        else:
                            self.displayMessage('Cannot edit sessions while previewing session: <a href="%s/_preview/index.html">%s</a><p></p>' % (site_prefix, previewingSession))
                        return
                    if not self.previewState['modified']:
                        # Clear any unmodified preview
                        self.previewClear()
                self.editSession(sessionName, sessionType=sessionType, start=True, slideNumber=slideNumber, startPreview=startPreview)
                return

            elif action == '_closepreview':
                self.discardPreview(sessionName, modified=modifiedNum)
                return

            elif action == '_discard':
                self.discardPreview(sessionName, modified=modifiedNum)
                return

            elif action == '_reloadpreview':
                if not previewingSession:
                    raise tornado.web.HTTPError(404, log_message='CUSTOM:Not previewing session')
                self.reloadPreview()
                self.write('reloadpreview')
                return

            elif action == '_release':
                if previewingSession:
                    raise tornado.web.HTTPError(404, log_message='CUSTOM:Cannot release when previewing session')
                releaseDate = self.get_argument('releasedate', '')
                postGrades = self.get_argument('gradebook', '')
                if self.get_argument('submit', ''):
                    yield self.submitSession(sessionName, postGrades=postGrades)
                self.releaseModule(sessionName, releaseDate=releaseDate)
                return

        if Options['multisite'] and not Options['site_number']:
            # Primary server
            if action not in ('_backup',):
                raise tornado.web.HTTPError(403)

        if previewingSession:
            self.write('<h3>Previewing session <b>%s</b>: <a href="%s/_preview/index.html">Continue preview</a> OR <a href="%s/_discard?modified=-1">Discard</a></h3>' % (previewingSession, site_prefix, site_prefix))
            return

        if action not in ('_dash', '_actions', '_addtype', '_modules', '_restore', '_attend', '_editroster', '_roster', '_browse', '_twitter', '_cache', '_freeze', '_clear', '_backup', '_edit', '_upload', '_lock', '_interactcode'):
            if not sessionName:
                self.displayMessage('Please specify /%s/session name' % action)
                return

        if action == '_unsafe_trigger_updates':
            ucode = int(self.get_argument('code','0'))
            if not ucode or ucode != self.unsafe_code[0]:
                tem_url = '/_unsafe_trigger_updates/%s?modcols=%s&insertrows=%s&code=%d' % (sessionName, self.get_argument('modcols',''), self.get_argument('insertrows',''), self.unsafe_code[0])
                if Options['site_name']:
                    tem_url = '/'+Options['site_name']+tem_url
                self.displayMessage('Click <a href="%s">%s</a> to destructively modify columns in session %s' % (tem_url, tem_url, sessionName))
            else:
                self.unsafe_code[0] += 1
                modCols = [int(x) for x in self.get_argument('modcols','').split(',') if x]
                insertRows = [int(x) for x in self.get_argument('insertrows','').split(',') if x]
                valTable = sdproxy.unsafeTriggerUpdates(sessionName, modCols, insertRows)
                self.displayMessage('Unsafe column updates triggered for session %s: <br>%s' % (sessionName, preElement(valTable)))

        elif action == '_dash':
            upload_key = sliauth.gen_hmac_token(Options['auth_key'], 'upload:')
            active_users = sorted( list(set(x[1] for x in WSHandler.get_connections())) )
            idle_time = math.floor(time.time() - max([max(ws.msgTime for ws in x[2]) for x in WSHandler.get_connections() if x[2]] or [0])) if active_users else ''
            site_status = ''
            days_left = cert_daysleft()
            if days_left is not None and days_left < 30:
                site_status = 'SSL certificate expires in %s days' % days_left

            self.render('dashboard.html', site_name=Options['site_name'], site_label=Options['site_label'],
                        site_title=Options['site_title'], site_access=sdproxy.Settings['site_access'],
                        version=sliauth.get_version(), status=site_status, interactive=WSHandler.getInteractiveSession()[0],
                        admin_users=Options['admin_users'], grader_users=Options['grader_users'], guest_users=Options['guest_users'],
                        start_date=sliauth.print_date(Options['start_date'],not_now=True),
                        lock_date=sliauth.print_date(sdproxy.Settings['lock_date'],not_now=True),
                        end_date=sliauth.print_date(Options['end_date'],not_now=True),
                        site_menu=SiteProps.get_site_menu(), upload_key=upload_key,
                        gradebook_release=sdproxy.Settings['gradebook_release'],
                        server_start=sliauth.print_date(Options['server_start'], weekday=True, long_date=True, prefix_time=True),
                        active_users=active_users, idle_time=idle_time)

        elif action == '_actions':
            self.render('actions.html', site_name=Options['site_name'], session_name='', root_admin=self.check_root_admin(),
                         suspended=sdproxy.Global.suspended)

        elif action == '_addtype':
            self.render('addtype.html', site_name=Options['site_name'], session_types=SiteProps.session_types(),
                         session_props=self.get_session_props())

        elif action == '_modules':
            self.displaySessions()

        elif action == '_browse':
            delete = self.get_argument('delete', '')
            download = self.get_argument('download', '')
            newFolder = self.get_argument('newfolder', '')
            self.browse('_browse', subsubpath, site_admin=self.check_admin_access(), delete=delete, download=download,
                        newFolder=newFolder)

        elif action in ('_restore',):
            self.render('restore.html', site_name=Options['site_name'], session_name='')

        elif action == '_editroster':
            headers = sdproxy.getRosterHeaders()
            userId = self.get_argument('user', '')
            delete = self.get_argument('delete', '')
            if userId:
                edit = True
                oldValues = sdproxy.getRosterValues(userId, delete=delete)
                if not oldValues:
                    self.displayMessage('Roster entry not found for user %s' % userId,
                                        back_url=site_prefix+'/_roster')
                    return
                elif delete:
                    self.displayMessage('Roster entry deleted for user %s' % userId,
                                        back_url=site_prefix+'/_roster')
                    return
            else:
                oldValues = ['']*len(headers)
                edit = False
            self.render('editroster.html', site_name=Options['site_name'], session_name='',
                         headers=headers, values=oldValues, err_msg='', edit=edit)

        elif action in ('_attend',):
            userId = self.get_argument('user', '')
            toggle = self.get_argument('toggle', '')
            selectedDay = self.get_argument('selectedday', '')
            if userId:
                self.set_header('Content-Type', 'text/plain')
                try:
                    present = sdproxy.toggleAttendance(selectedDay, userId)
                    self.write('&#x2714;' if present else '&#x2718;')
                except Exception, excp:
                    self.write('Error: '+str(excp))
                return
            attendanceDays = list( reversed( sdproxy.getAttendanceDays() ))

            if attendanceDays:
                if not selectedDay or selectedDay not in attendanceDays:
                    selectedDay = attendanceDays[0]
                attendanceInfo = sdproxy.getAttendance(selectedDay)
                recent = (selectedDay == attendanceDays[0])
            else:
                selectedDay = ''
                attendanceInfo = []
                recent = False
                
            self.render('attendance.html', site_name=Options['site_name'], session_name='', attendance_days=attendanceDays,
                        selected_day=selectedDay, attendance_info=attendanceInfo, recent=recent)

        elif action in ('_roster',):
            overwrite = self.get_argument('overwrite', '')
            nameMap = sdproxy.getDisplayNames()
            if not nameMap or overwrite:
                lastname_col, firstname_col, midname_col, id_col, email_col, altid_col = Options["roster_columns"].split(',')
                self.render('newroster.html', site_name=Options['site_name'], overwrite=overwrite,
                             lastname_col=lastname_col, firstname_col=firstname_col, midname_col=midname_col,
                             id_col=id_col, email_col=email_col, altid_col=altid_col)
            else:
                for idVal, name in nameMap.items():
                    if name.startswith('#'):
                        del nameMap[idVal]
                lastMap = sdproxy.makeShortNames(nameMap)
                firstMap = sdproxy.makeShortNames(nameMap, first=True)
                statusMap = sdproxy.lookupRoster('status')

                wheelNames = []
                for idVal, shortName in firstMap.items():
                    lastName, _, firstNames = nameMap[idVal].partition(',')
                    if firstNames.strip():
                        fullName = firstNames.strip().split(' ')[0] + ' ' + lastName
                    else:
                        fullName = lastName
                    wheelNames.append(shortName+'/'+fullName)
                wheelNames.sort()

                site_name = Options['site_name'] or ''
                qwheel_link = 'https://mitotic.github.io/wheel/?session=' + urllib.quote_plus(site_name)
                qwheel_new = qwheel_link + '&names=' + ';'.join(urllib.quote_plus(x,safe='/') for x in wheelNames)

                self.render('roster.html', site_name=site_name, gradebook='gradebook' in SiteProps.get_site_menu(),
                             session_name='', qwheel_link=qwheel_link, qwheel_new=qwheel_new,
                             name_map=nameMap, last_map=lastMap, first_map=firstMap, status_map=statusMap)

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
                wsInfo += [(path, user, math.floor(curTime-ws.msgTime), ws.clientVersion) for ws in connections]
            sorted(wsInfo)
            self.write('\nConnections:\n')
            for x in wsInfo:
                self.write("  %s: %s (idle: %ds, v%s)\n" % x)
            self.write('</pre>')

        elif action == '_twitter':
            if not Global.twitterStream:
                self.displayMessage('No twitter stream active', back_url=site_prefix+'/_actions')
            else:
                self.displayMessage(['Twitter stream status: '+Global.twitterStream.status+'\n\n',
                                     'Twitter stream log: '+'\n'.join(Global.twitterStream.log_buffer)+'\n'],
                                     back_url=site_prefix+'/_actions')

        elif action == '_freeze':
            sdproxy.freezeCache(fill=True)
            self.displayMessage('Freezing cache<br>', back_url=site_prefix+'/_dash')

        elif action == '_clear':
            sdproxy.suspend_cache('clear')
            self.displayMessage('Clearing cache<br>', back_url=site_prefix+'/_actions')

        elif action == '_backup':
            self.displayMessage(backupSite(subsubpath), back_url=site_prefix+'/_actions')

        elif action == '_lock':
            lockType = self.get_argument('type','')
            if sessionName:
                prefix = 'Locked'
                locked = sdproxy.lockSheet(sessionName, lockType or 'user')
                if not locked:
                    if lockType == 'proxy':
                        raise Exception('Failed to lock sheet '+sessionName+'. Try again after a few seconds?')
                    prefix = 'Locking'
            self.write(prefix +' sessions: %s<p></p><a href="%s/_cache">Cache status</a><p></p>' % (', '.join(sdproxy.get_locked()), site_prefix) )

        elif action == '_unlock':
            if not sdproxy.unlockSheet(sessionName):
                raise Exception('Failed to unlock sheet '+sessionName)
            self.displayMessage('Unlocked '+sessionName+('<p></p><a href="%s/_cache">Cache status</a><p></p>' % site_prefix))

        elif action == '_reset_cache_updates':
            sdproxy.next_cache_update(resetError=True)
            self.displayMessage('Cache updates have been restarted')

        elif action in ('_manage',):
            sheet = sdproxy.getSheet(sessionName)
            if not sheet:
                self.displayMessage('No such session: '+sessionName)
                return
            sessionType, _ = getSessionType(sessionName)
            self.render('manage.html', site_name=Options['site_name'], session_name=sessionName,
                        session_type=sessionType, private=SiteProps.private_prefix(sessionType))

        elif action == '_download':
            if not Options['source_dir']:
                raise tornado.web.HTTPError(403, log_message='CUSTOM:Must specify source_dir to download')

            downloadFormat = self.get_argument('downloadformat','') or 'md'

            uploadType, sessionNumber, src_path, web_path, web_images = self.getUploadType(subsubpath)
            sessionFile = os.path.basename(src_path)
            image_dir = os.path.basename(web_images)
            try:
                with open(src_path) as f:
                    sessionText = f.read()
            except Exception, excp:
                raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in reading file %s: %s' % (src_path, excp))

            if downloadFormat == 'pptx':
                import md2pptx
                outfile = subsubpath+'.pptx'
                stream = io.BytesIO()
                md_parser = md2pptx.MDParser(dict(image_dir=web_images if os.path.isdir(web_images) else ''))
                md_parser.parse_md(sessionText, stream, outfile)
                content = stream.getvalue()
                self.set_header('Content-Type', 'application/vnd.openxmlformats-officedocument.presentationml.presentation')

            elif downloadFormat == 'ipynb':
                outfile = subsubpath+'.ipynb'
                md_parser = md2nb.MDParser(argparse.Namespace(embed_images=True, indented=True, site_url='', strip='',
                                                              image_dir=web_images if os.path.isdir(web_images) else ''))
                content = md_parser.parse_cells(sessionText, src_path)
                self.set_header('Content-Type', 'application/x-ipynb+json')

            elif os.path.isdir(web_images):
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
                # Plain markdown
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
            allUsers = self.get_argument("allusers", '')
            if sessionName.endswith('_discuss'):
                allUsers = True
            self.displaySheet(sessionName, download=self.get_argument("download", ''),
                               allUsers=allUsers, keepHidden=self.get_argument("keephidden", ''))

        elif action in ('_getcol', '_getrow'):
            subsubpath, sep, label = subsubpath.partition(';')
            sheet = sdproxy.getSheet(subsubpath)
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

        elif action in ('_republish', '_reindex'):
            if not Options['source_dir']:
                raise tornado.web.HTTPError(403, log_message='CUSTOM:Must specify source_dir to republish/reindex')

            republishForce = bool(self.get_argument('republishforce',''))

            if subsubpath == 'all':
                uploadType = ''
            else:
                uploadType, sessionNumber, src_path, web_path, web_images = self.getUploadType(subsubpath)

            if action == '_republish':
                buildMsgs = self.rebuild(uploadType, make='' if republishForce else 'all', log_dict=True)
                # Re-index after complete rebuild
                indMsgs = self.rebuild(uploadType, indexOnly=True)
            else:
                buildMsgs = {}
                indMsgs = self.rebuild(uploadType, indexOnly=True)

            if action == '_republish' and (1 or any(buildMsgs.values()) or any(indMsgs)):
                self.displaySessions(buildMsgs, indMsgs, msg='Completed republishing')
            elif action == '_reindex' and indMsgs and any(indMsgs):
                self.displayMessage(['Error in %s:' % action] + indMsgs)
            else:
                self.redirect("/"+Options['site_name']+"/index.html" if Options['site_number'] else "/index.html")

        elif action == '_delete':
            reset = bool(self.get_argument('reset',''))
            errMsgs = self.deleteSession(subsubpath, reset=reset)
            tocPath = getSessionPath(sessionName, site_prefix=True, toc=True)
            if errMsgs and any(errMsgs):
                self.displayMessage(errMsgs, back_url=tocPath)
            elif reset:
                self.displayMessage('Reset session '+sessionName, back_url=tocPath)
            else:
                self.displayMessage('Deleted session '+sessionName, back_url=tocPath)

        elif action == '_import':
            self.render('import.html', site_name=Options['site_name'], session_name=sessionName, import_params=updateImportParams(Options['import_params']) if Options['import_params'] else {}, submit_date=sliauth.iso_date())

        elif action == '_upload':
            if not Options['source_dir']:
                raise tornado.web.HTTPError(403, log_message='CUSTOM:Must specify source_dir to upload')
            if sessionName == RAW_UPLOAD:
                upload_type = RAW_UPLOAD
                session_number = ''
            else:
                try:
                    upload_type, session_number = getSessionType(sessionName)
                except Exception, excp:
                    self.displayMessage(str(excp))
                    return
            self.render('upload.html', site_name=Options['site_name'],
                        upload_type=upload_type, session_name=sessionName, session_number=session_number, session_types=SiteProps.session_types(), err_msg='')

        elif action == '_prefill':
            if sdproxy.getRowMap(sessionName, 'Timestamp', regular=True):
                raise tornado.web.HTTPError(403, log_message='CUSTOM:Error: Session %s already filled' % sessionName)
            nameMap = sdproxy.getDisplayNames()
            if not nameMap:
                raise tornado.web.HTTPError(403, log_message='CUSTOM:Error: Session %s has no roster for prefill' % sessionName)
            count = 0
            for userId, name in nameMap.items():
                if not name or name.startswith('#'):
                    continue
                count += 1
                sdproxy.importUserAnswers(sessionName, userId, name, source='prefill')
            self.displayMessage('Prefilled session '+sessionName+' with '+str(count)+' users')

        elif action == '_refresh':
            if subsubpath:
                if sdproxy.refreshSheet(subsubpath):
                    msg = ' Refreshed sheet '+subsubpath
                else:
                    msg = ' Cannot refresh locked sheet '+subsubpath+' ...'
                self.displayMessage(msg+('<p></p><a href="%s/_cache">Cache status</a><p></p>' % site_prefix))

        elif action == '_responders':
            sessionName, sep, respId = sessionName.partition(';')
            if not sessionName:
                self.displayMessage('Please specify /_responders/session_name')
                return
            sheet = sdproxy.getSheet(sessionName)
            if not sheet:
                self.displayMessage('Unable to retrieve session '+sessionName)
                return

            sessionEntries = sdproxy.lookupValues(sessionName, ['dueDate', 'gradeDate', 'paceLevel', 'adminPaced', 'attributes'], sdproxy.INDEX_SHEET)
            sessionAttributes = json.loads(sessionEntries['attributes'])
            adminPaced = sessionEntries.get('adminPaced','')
            dueDate = sessionEntries.get('dueDate','')
            timedSec = sessionAttributes['params'].get('timedSec')

            pastDue = sliauth.epoch_ms() > sliauth.epoch_ms(dueDate) if dueDate else False
            sessionConnections = WSHandler.get_connections(sessionName)

            userId = self.get_argument('user','')
            dateStr = self.get_argument('date','')
            nameMap = sdproxy.getDisplayNames()
            if dateStr:
                if not userId:
                    self.displayMessage('Please specify user id for late token')
                    return
                if userId in nameMap:
                    # Close any active connections associated with user for session
                    for connection in sessionConnections.get(userId, []):
                        connection.close()
                    newLatetoken = sliauth.gen_late_token(Options['auth_key'], userId, Options['site_name'], sessionName,
                                                          sliauth.get_utc_date(dateStr, pre_midnight=True))
                    if timedSec:
                        self.displayMessage('Late toke for user '+userId+' = '+newLatetoken, back_url=site_prefix+'/_responders/'+sessionName)
                    else:
                        sdproxy.createUserRow(sessionName, userId, lateToken=newLatetoken, source='allow')
                        self.redirect(site_prefix+'/_responders/'+sessionName)
                    return
                else:
                    self.displayMessage('User ID '+userId+' not in roster', back_url=site_prefix+'/_responders/'+sessionName)
                    return
            elif userId:
                if userId in nameMap:
                    sdproxy.importUserAnswers(sessionName, userId, nameMap[userId], source='manual', submitDate='dueDate')
                    self.redirect(site_prefix+'/_responders/'+sessionName)
                    return
                else:
                    self.displayMessage('User ID '+userId+' not in roster')
                    return

            nRows = sheet.getLastRow()
            userMap = {}
            if nRows > 2:
                # Skip headers and maxscore rows
                colIndex = sdproxy.indexColumns(sheet)
                idVals      = sheet.getSheetValues(3, colIndex['id'], nRows-2, 1)
                lastSlides  = sheet.getSheetValues(3, colIndex['lastSlide'], nRows-2, 1)
                startTimes  = sheet.getSheetValues(3, colIndex['initTimestamp'], nRows-2, 1)
                submitTimes = sheet.getSheetValues(3, colIndex['submitTimestamp'], nRows-2, 1)
                lateTokens  = sheet.getSheetValues(3, colIndex['lateToken'], nRows-2, 1)

                for j in range(len(idVals)):
                    userMap[idVals[j][0]] = (lastSlides[j][0], startTimes[j][0], submitTimes[j][0], lateTokens[j][0])

            sessionStatus = []
            totalCount = 0
            startedCount = 0
            submittedCount = 0
            idResponders = set()
            curTime = time.time()
            for idVal, name in nameMap.items():
                normalUser = name and not name.startswith('#')
                if normalUser:
                    totalCount += 1

                if idVal in userMap:
                    if normalUser:
                        startedCount += 1
                    lastSlide, startTime, submitTime, lateToken = userMap[idVal]
                    if submitTime:
                        submittedCount += 1
                else:
                    lastSlide, startTime, submitTime, lateToken = 0, '', '', ''

                submitTimeStr = sliauth.print_date(submitTime, prefix_time=True) if submitTime else ''
                startTimeStr = sliauth.print_date(startTime, prefix_time=True) if startTime else ''
                dueDateStr = sliauth.print_date(dueDate, prefix_time=True) if dueDate else ''
                accessTime = None
                for connection in sessionConnections.get(idVal, []):
                    elapsedTime = math.floor(curTime-connection.msgTime)
                    accessTime = elapsedTime if accessTime is None else min(accessTime, elapsedTime)
                idleStatus = '' if accessTime is None else ('idle %ds' % accessTime)
                lateTokenStr =  sliauth.print_date(lateToken[:17], prefix_time=True) if lateToken and lateToken not in (LATE_SUBMIT,PARTIAL_SUBMIT) else lateToken
                sessionStatus.append( [name, idVal, lastSlide, startTimeStr, submitTimeStr, lateTokenStr, idleStatus] )

            self.render('responders.html', site_name=Options['site_name'], session_name=sessionName,
                         total_count=totalCount, started_count=startedCount, submitted_count=submittedCount,
                         due_date=dueDateStr, past_due=pastDue, session_status=sessionStatus)

        elif action == '_lockcode':
            comps = sessionName.split(';')
            sessionName = comps[0]
            userId = comps[1] if len(comps) >= 2 else ''
            if not userId:
                raise tornado.web.HTTPError(403, log_message='CUSTOM:Error: Invalid lockcode userid %s' % userId)
            sheet = sdproxy.getSheet(sessionName)
            if not sheet:
                self.displayMessage('Unable to retrieve session '+sessionName)
                return
            token = sliauth.gen_locked_token(Options['auth_key'], userId, Options['site_name'], sessionName)
            accessToken = '%s:%s' % (userId, token)
            accessURL = '%s/_auth/login/?usertoken=%s' % (Options['server_url'], urllib.quote_plus(accessToken))
            if Options['debug']:
                print >> sys.stderr, 'DEBUG: locked access URL', accessURL
            img_data_uri = sliauth.gen_qr_code(accessToken, img_html='<img class="slidoc-lockcode" src="%s">')
            self.displayMessage('<h3>Lockdown access token for user %s, session %s</h3><a href="%s" target="_blank"><b>Click or copy this link for locked access</b></a><p></p>%s' % (userId, sessionName, accessURL, img_data_uri) )
            return

        elif action == '_interactcode':
            interactURL = Options['server_url'] + site_prefix
            if self.get_argument('dest',''):
                interactURL += '/' + self.get_argument('dest','')
            img_data_uri = sliauth.gen_qr_code(interactURL, img_html='<img class="slidoc-lockcode" src="%s">')
            self.displayMessage('<h3>To interact, type URL or scan code</h3><h2>%s</h2>%s' % (interactURL, img_data_uri) )
            return

        elif action == '_submit':
            self.render('submit.html', site_name=Options['site_name'], session_name=sessionName)
        else:
            self.displayMessage('Invalid get action: '+action)

    def redirectPreview(self, update='', slideId=''):
        sessionType, _ = getSessionType(self.previewState['name'])
        if sessionType != TOP_LEVEL:
            prefix = sliauth.safe_quote( (SiteProps.private_prefix(sessionType) + '/' + sessionType)[1:] )
        else:
            prefix = ''

        site_prefix = '/'+Options['site_name'] if Options['site_name'] else ''
        redirURL = site_prefix + '/_preview/index.html?modified=%d&prefix=%s' % (self.previewState['modified'], prefix)
        if update:
            redirURL += '&update=' + update
        if slideId:
            redirURL += '&slideid=' + slideId
        self.redirect(redirURL)

    def deleteSession(self, sessionName, reset=False):
        if Options['debug']:
            print >> sys.stderr, 'DEBUG: deleteSession', Options['site_name'], sessionName, reset
        user = sdproxy.ADMINUSER_ID
        userToken = gen_proxy_auth_token(user, sdproxy.ADMIN_ROLE, prefixed=True)
        args = {'sheet': sessionName, 'delsheet': '1', 'admin': user, 'token': userToken}
        retObj = sdproxy.sheetAction(args)
        if retObj['result'] != 'success':
            return ['Error in deleting sheet '+sessionName+': '+retObj.get('error','')]

        if not Options['source_dir'] or (Options['dry_run'] and not Options['dry_run_file_modify']):
            return []

        uploadType, sessionNumber, src_path, web_path, web_images = self.getUploadType(sessionName)

        if reset:
            return self.rebuild(uploadType, make=sessionName)

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

    def get_session_props(self, buildMsgs={}, indMsgs=[]):
        colNames = ['sessionWeight', 'releaseDate', 'dueDate', 'gradeDate']
        sessionParamDict = dict(sdproxy.lookupSessions(colNames))
        session_props = []
        for sessionType in self.get_session_names(top=True):
            session_props.append( [sessionType, 0, None, [], '\n'.join(buildMsgs.get(TOP_LEVEL, [])+indMsgs) if sessionType == 'index' else ''] )

        for sessionType in self.get_session_names():
            fnames = [os.path.splitext(os.path.basename(x))[0] for x in self.get_md_list(sessionType)]
            session_props.append( [sessionType,
                                    1 if SiteProps.private_prefix(sessionType) else 0,
                                    fnames,
                                    sessionParamDict,
                                    '\n'.join(buildMsgs.get(sessionType, []))] )
        return session_props

    def displaySessions(self, buildMsgs={}, indMsgs=[], msg=''):
        session_props = self.get_session_props(buildMsgs=buildMsgs, indMsgs=indMsgs)
        self.render('modules.html', site_name=Options['site_name'], session_types=SiteProps.session_types(), session_props=session_props, message=msg)


    def browse(self, url_path, filepath, site_admin=False, delete='', download='', newFolder='', uploadName='', uploadContent=''):
        if Options['debug']:
            print >> sys.stderr, 'DEBUG: browse', Options['site_name'], repr(url_path), repr(filepath), site_admin, delete, download, newFolder, uploadName, len(uploadContent)

        if '..' in filepath:
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Invalid path')

        if not site_admin:
            self.check_site_access()

        user_browse = (url_path != '_browse')
        site_prefix = '/'+Options['site_name'] if Options['site_name'] else ''
        status = ''
        if not filepath and not user_browse and site_admin:
            file_list = [ ['source', 'source', False, '', ''],
                          ['web', 'web', False, '', ''],
                          ['files', 'files', False, '', ''],
                          ['data', 'data', False, '', ''],
                          ['backup', 'backup', False, '', ''] ]
            up_path = ''
        else:
            predir, _, subpath = filepath.partition('/')
            if predir != 'files':
                if user_browse:
                    raise tornado.web.HTTPError(404, log_message='CUSTOM:Directory must start with files')
                if not site_admin:
                    # Failsafe check to prevent user access to non-files directories
                    raise tornado.web.HTTPError(403)

            if predir == 'source':
                rootdir = self.site_src_dir
            elif predir == 'web':
                rootdir = self.site_web_dir
            elif predir == 'data':
                rootdir = self.site_data_dir
            elif predir == 'backup':
                rootdir = self.site_backup_dir
            elif predir == 'files':
                rootdir = self.site_files_dir
            else:
                raise tornado.web.HTTPError(404, log_message='CUSTOM:Directory must start with source|web|data|backup|files')

            up_path = os.path.dirname(filepath)
            fullpath = os.path.join(rootdir, subpath) if subpath else rootdir
            if not os.path.exists(fullpath):
                if not subpath:
                    os.makedirs(fullpath)
                    if predir == 'files':
                        os.makedirs(os.path.join(fullpath, PRIVATE_PATH))
                        os.makedirs(os.path.join(fullpath, RESTRICTED_PATH))
                        os.makedirs(os.path.join(fullpath, RESTRICTED_PATH, 'notebooks'))
                else:
                    self.displayMessage('Path %s (%s) does not exist!' % (filepath, fullpath))
                    return

            basename= os.path.basename(fullpath)
            if download:
                if os.path.isdir(fullpath):
                    try:
                        content = zipdir(fullpath, inner=not subpath)
                    except Exception, excp:
                        raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in archiving directory %s: %s' % (fullpath, excp))
                    outfile = (basename if subpath else predir) +'.zip'
                    self.set_header('Content-Type', 'application/zip')
                else:
                    try:
                        with open(fullpath) as f:
                            content = f.read()
                    except Exception, excp:
                        raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in reading file %s: %s' % (fullpath, excp))
                    outfile = basename
                    self.set_header('Content-Type', 'text/plain')
                self.set_header('Content-Disposition', 'attachment; filename="%s"' % outfile)
                self.write(content)
                return

            if site_admin:
                # Admin-only actions
                if delete:
                    if not subpath:
                        raise tornado.web.HTTPError(404, log_message='CUSTOM:Cannot delete root directory' % predir)
                    if not os.path.exists(fullpath):
                        raise tornado.web.HTTPError(404, log_message='CUSTOM:Path %s does not exist' % fullpath)
                    try:
                        if os.path.isdir(fullpath):
                            shutil.rmtree(fullpath)
                        else:
                            os.remove(fullpath)
                    except Exception, excp:
                        raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in deleting file %s: %s' % (fullpath, excp))
                    self.redirect(site_prefix+'/'+url_path+'/'+os.path.dirname(filepath))
                    return

                if predir == 'files' and newFolder:
                    if not os.path.isdir(fullpath):
                        raise tornado.web.HTTPError(404, log_message='CUSTOM:Path %s does not exist' % fullpath)

                    newpath = os.path.join(fullpath, newFolder)
                    if os.path.exists(newpath):
                        raise tornado.web.HTTPError(404, log_message='CUSTOM:Folder/file %s already exists' % newpath)
                    try:
                        os.makedirs(newpath)
                    except Exception, excp:
                        raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in creating folder %s: %s' % (newpath, excp))
                    self.redirect(site_prefix+'/'+url_path+'/'+filepath)
                    return

                if uploadName:
                    if not os.path.isdir(fullpath):
                        raise tornado.web.HTTPError(404, log_message='CUSTOM:Browse path not a directory %s' % fullpath)

                    if Options['dry_run'] and not Options['dry_run_file_modify']:
                        raise Exception('Cannot upload files during dry run without file modify option')

                    file_list = []
                    errMsgs = []
                    if uploadName.endswith('.zip'):
                        try:
                            zfile = zipfile.ZipFile(io.BytesIO(uploadContent))
                            file_list = zfile.namelist()
                            zfile.extractall(fullpath)
                        except Exception, excp:
                            raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in unzipping archive to %s: %s' % (fullpath, excp))
                    else:
                        try:
                            outpath = os.path.join(fullpath, uploadName)
                            with open(outpath, 'wb') as f:
                                f.write(uploadContent)
                        except Exception, excp:
                            raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in writing file %s: %s' % (outpath, excp))
                        uname = os.path.splitext(os.path.basename(uploadName))[0]
                        try:
                            uploadType, _ = getSessionType(sessionName)
                        except Exception, excp:
                            self.displayMessage(str(excp))
                            return
                        if uploadType != TOP_LEVEL:
                            filePaths = self.get_md_list(uploadType)
                            if filePaths:
                                errMsgs = self.rebuild(uploadType, indexOnly=True)

                    status = 'Uploaded '+uploadName
                    if file_list:
                        status += ' (' + ' '.join(file_list) + ')'
                        if errMsgs and any(errMsgs):
                            status += ' Notebook reindex log:' + '\n'.join(errMsgs)

            if not os.path.isdir(fullpath):
                self.displayMessage('Path %s not a directory!' % filepath)
                return

            file_list = []
            for fname in sorted(os.listdir(fullpath)):
                fpath = os.path.join(fullpath, fname)
                fext = os.path.splitext(fname)[1]
                subdirpath = os.path.join(filepath, fname)
                isfile = os.path.isfile(fpath)
                linkpath, viewpath = '', ''
                if isfile:
                    _, _, linkpath = subdirpath.partition('/')
                    if predir == 'data':
                        linkpath = PLUGINDATA_PATH + '/' + linkpath
                    elif predir == 'files':
                        linkpath = FILES_PATH + '/' + linkpath

                    if predir in ('web', 'data', 'files') and fext.lower() in ('.gif', '.ipynb', '.jpeg','.jpg','.pdf','.png','.txt'):
                        # Viewable files
                        linkpath, viewpath = self.viewer_link(linkpath, site_admin=site_admin)
                    else:
                        linkpath = urllib.quote(linkpath)

                file_list.append( [fname, urllib.quote(subdirpath), isfile, linkpath, viewpath] )

        self.render('browse.html', site_name=Options['site_name'], status=status, server_url=Options['server_url'],
                    url_path=url_path, site_admin=site_admin, root_admin=self.check_root_admin(),
                    up_path=urllib.quote(up_path), browse_path=filepath, file_list=file_list)

    def viewer_link(self, relpath, site_admin=False):
        # Returns (linkpath, viewpath) quoted URL links to restricted file with key appended as query parameter, given relative path
        fext = os.path.splitext(relpath)[1]
        toppath = '/' + relpath
        if Options['site_name']:
            toppath = '/' + Options['site_name'] + toppath

        linkpath = urllib.quote(relpath)

        files_path = relpath.startswith(FILES_PATH+'/')

        if not (files_path or site_admin):
            return linkpath, linkpath

        # files_path or site_admin: generate viewable links
        viewpath = urllib.quote(toppath)
        if ('/'+RESTRICTED_PATH) in relpath:
            # Restricted _files; viewable by anyone with file key in link
            fileKey = '?' + PluginManager.getFileKey(toppath)

            viewpath += fileKey
            linkpath += fileKey

            if fext.lower() == '.ipynb':
                # Render link for notebooks
                if Options['server_url'].startswith('https://'):
                    nbprefix = 'https://nbviewer.jupyter.org/urls/' + Options['server_url'][len('https://'):]
                elif Options['server_url'].startswith('http://'):
                    nbprefix = 'http://nbviewer.jupyter.org/url/' + Options['server_url'][len('http://'):]
                else:
                    raise Exception('Invalid server URL :' + Options['server_url'])

                # Append "query" using "%3F" as nbviewer chomps up normal queries
                viewpath = nbprefix + viewpath.replace('?', '%3F')

        return linkpath, viewpath

    def getUploadType(self, sessionName, siteName=''):
        if not Options['source_dir']:
            raise tornado.web.HTTPError(403, log_message='CUSTOM:Must specify source_dir to get session type')

        if siteName:
            # Check permissions to retrieve session from another site
            siteRole = self.get_id_from_cookie(role=True, for_site=siteName)
            if siteRole != sdproxy.ADMIN_ROLE:
                raise tornado.web.HTTPError(404, log_message='CUSTOM:Denied access to site %s to retrieve session %s' % (siteName, sessionName))

            src_dir = Options['source_dir'] + '/' + siteName
            web_dir = Options['web_dir'] + '/' + siteName
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

        web_prefix = web_dir+SiteProps.private_prefix(uploadType)+'/'+uploadType+'/'+fname
        return uploadType, sessionNumber, src_dir+'/'+uploadType+'/'+fname+'.md', web_prefix+'.html', web_prefix+'_images'

    def displaySheet(self, sessionName, download=False, allUsers=False, keepHidden=False):
            sheet = sdproxy.getSheet(sessionName, display=True)
            if not sheet:
                self.displayMessage('Unable to retrieve sheet '+sessionName)
                return
            lastname_col, firstname_col, midname_col, id_col, email_col, altid_col = Options["roster_columns"].split(',')
            timestamp = ''
            if sessionName.endswith('_answers') or sessionName.endswith('_correct') or sessionName.endswith('_stats'):
                try:
                    timestamp = sliauth.iso_date(sdproxy.lookupValues('_average', ['Timestamp'], sessionName)['Timestamp'])
                except Exception, excp:
                    pass

            rows = sheet.export(csvFormat=download, allUsers=allUsers, keepHidden=keepHidden, idRename=id_col, altidRename=altid_col)
            if download:
                self.set_header('Content-Type', 'text/csv')
                self.set_header('Content-Disposition', 'attachment; filename="%s.csv"' % sessionName)
                self.write(rows)
            else:
                self.render('table.html', site_name=Options['site_name'], table_name=sessionName, table_data=rows, table_fixed='fixed',
                            timestamp=timestamp)

    def postAction(self, subpath):
        previewingSession = self.previewActive()
        site_prefix = '/'+Options['site_name'] if Options['site_name'] else ''
        action, sep, subsubpath = subpath.partition('/')
        sessionName = subsubpath
        if not sessionName:
            sessionName = self.get_argument('sessionname', '')

        if action == '_edit':
            if not Options['source_dir']:
                raise tornado.web.HTTPError(403, log_message='CUSTOM:Must specify source_dir to edit')
            sessionType = self.get_argument('sessiontype', '')
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

            if previewingSession and previewingSession != sessionName:
                if slideNumber:
                    self.set_header('Content-Type', 'application/json')
                    self.write( json.dumps( {'result': 'error', 'error': 'Cannot edit sessions while previewing another session '+previewingSession} ) )
                else:
                    self.displayMessage('Cannot edit sessions while previewing session: <a href="%s/_preview/index.html">%s</a><p></p>' % (site_prefix, previewingSession))
                return

            if self.get_argument('rollover',''):
                # Close all session websockets (forcing reload)
                IOLoop.current().add_callback(WSHandler.closeSessionConnections, sessionName)
                return self.rollover(sessionName, slideNumber)

            if self.get_argument('truncate',''):
                # Close all session websockets (forcing reload)
                IOLoop.current().add_callback(WSHandler.closeSessionConnections, sessionName)
                return self.rollover(sessionName, slideNumber, truncateOnly=True)

            sessionText = self.get_argument('sessiontext', '')
            fromSession = self.get_argument('fromsession', '')
            fromSite = self.get_argument('fromsite', '')
            deleteSlide = self.get_argument('deleteslide', '')
            sessionModify = sessionName if self.get_argument('sessionmodify', '') else ''
            update = self.get_argument('update', '')

            imageZip = None
            if 'zipimages' in self.request.files:
                fileinfo = self.request.files['zipimages'][0]
                try:
                    imageZip = zipfile.ZipFile(io.BytesIO(fileinfo['body']))
                except Exception, excp:
                    raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in reading image zip file: '+str(excp))
                zfile = zipfile.ZipFile(io.BytesIO(), 'w')
                for ipath in zfile.namelist():
                    zfile.writestr(sessionNext+'_images/'+os.path.basename(ipath), ifile.read(ipath))

            return self.editSession(sessionName, sessionType=sessionType, update=update, sessionText=sessionText, fromSession=fromSession, fromSite=fromSite,
                                    slideNumber=slideNumber, newNumber=newNumber, deleteSlide=deleteSlide, modify=sessionModify, imageZip=imageZip)

        elif action == '_imageupload':
            if not previewingSession:
                raise tornado.web.HTTPError(403, log_message='CUSTOM:Can only upload images in preview mode')
            fileinfo = self.request.files['upload'][0]
            fname = fileinfo['filename']
            fbody = fileinfo['body']
            sessionName = self.get_argument("sessionname")
            imageFile = self.get_argument("imagefile", "")
            autonumber = self.get_argument("autonumber", "")
            return self.imageUpload(sessionName, imageFile, fname, fbody, autonumber=autonumber)

        if action in ('_sheet',):
            self.displaySheet(sessionName, download=self.get_argument("download", ''),
                               allUsers=self.get_argument("allusers", ''), keepHidden=self.get_argument("keephidden", ''))
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

        if action in ('_browse', '_import', '_restore', '_editroster', '_teamgen', '_attend', '_roster', '_submit', '_upload'):
            if action == '_submit':
                # Submit test user
                try:
                    sdproxy.importUserAnswers(sessionName, sdproxy.TESTUSER_ID, '', submitDate=submitDate, source='submit')
                    self.displayMessage('Submit '+sdproxy.TESTUSER_ID+' row')
                except Exception, excp:
                    if Options['debug']:
                        import traceback
                        traceback.print_exc()
                    self.displayMessage('Error in submit for '+sdproxy.TESTUSER_ID+': '+str(excp))

            elif action == '_browse':
                fileinfo = self.request.files['upload'][0]
                fname = fileinfo['filename']
                self.browse('_browse', subsubpath, site_admin=self.check_admin_access(), uploadName=fname, uploadContent=fileinfo['body'])

            elif action == '_editroster':
                headers = sdproxy.getRosterHeaders()
                edit = self.get_argument('edit', '')
                rowDict = {}
                for header in headers:
                    rowDict[header] = self.get_argument(header, '')
                try:
                    oldValues = sdproxy.editRosterValues(rowDict, overwrite=edit)
                    if not oldValues:
                        self.displayMessage('Roster entry %s for user %s' % ('edited' if edit else 'added', rowDict.get('name')),
                                            back_url=site_prefix+'/_roster')
                    else:
                        self.render('editroster.html', site_name=Options['site_name'], session_name='',
                                     headers=headers, values=oldValues, edit=False,
                                     err_msg='Id %s already present in roster. Use edit option to overwrite values' % rowDict['id'])
                except Exception, excp:
                    self.render('editroster.html', site_name=Options['site_name'], session_name='',
                                 headers=headers, values=[rowDict[header] for header in headers], err_msg=str(excp), edit=False)

            elif action == '_teamgen':
                try:
                    count = int(self.get_argument('count', '') or '0')
                    minsize = int(self.get_argument('minsize', '') or '0')
                    inc_null = self.get_argument('includenull', '')
                    grade_cols = [x.strip() for x in self.get_argument('gradecols', '').split(',') if x.strip()]
                    user_ranks = []
                    if not self.get_argument('overwrite', ''):
                        if any(sdproxy.lookupRoster(sdproxy.TEAM_HEADER, regular=True).values()):
                            raise Exception('Teams already present in roster; select overwrite option')
                    statusMap = sdproxy.lookupRoster('status', regular=True)
                    for idValue, status in statusMap.items():
                        if status == sdproxy.DROPPED_STATUS:
                            continue
                        rank = 0
                        if grade_cols:
                            try:
                                grade_vals = sdproxy.lookupValues(idValue, grade_cols, sdproxy.GRADES_SHEET, listReturn=True)
                                rank = sum(x or 0 for x in grade_vals)
                            except Exception, excp:
                                if Options['debug']:
                                    print >> sys.stderr, 'ActionHandler:teamgen ERROR', idValue, str(excp)
                        if not rank and not inc_null:
                            continue
                        user_ranks.append([idValue, rank])
                        
                    props = sliauth.team_props(user_ranks, min_size=minsize, composition=self.get_argument('composition', ''),
                                               alias=self.get_argument('alias', ''), random_seed='_roster')
                    team_lines = []
                    total_count = 0
                    team_names = props['members'].keys()
                    team_names.sort(key=sdproxy.teamSortKey)
                    for j, team_name in enumerate(team_names):
                        # Define teams
                        members = props['members'][team_name]
                        for idValue in members:
                            sdproxy.setValue(idValue, sdproxy.TEAM_HEADER, team_name, sdproxy.ROSTER_SHEET)

                        team_ranks = props['ranks'][team_name]
                        team_count = len(team_ranks)
                        total_count += team_count
                        team_desc = ', '.join('%s(%.2f)' % tuple(user_rank) for user_rank in team_ranks)
                        if str(team_ranks[0][1]).isalpha():
                            team_avg = sum(ord(user_rank[1].upper())-ord('A') for user_rank in team_ranks) / float(team_count)
                        else:
                            team_avg = sum(user_rank[1] for user_rank in team_ranks) / float(team_count)
                        team_lines.append( '%d: name=%s, count=%d, avg_rank=%.2f, members=%s\n' % (j+1, team_name, team_count, team_avg, team_desc))

                    team_lines = ['Generated teams for %d members:\n' % total_count] + team_lines
                    self.displayMessage(team_lines, back_url=site_prefix+'/_roster')

                    if Options['debug']:
                        print >> sys.stderr, 'ActionHandler:teamgen', minsize, count, self.get_argument('composition', ''), grade_cols, user_ranks
                        for team_line in team_lines:
                            print >> sys.stderr, 'ActionHandler:teamgen    ', team_line.rstrip()
                except Exception, excp:
                    if Options['debug']:
                        import traceback
                        traceback.print_exc()
                    self.displayMessage('Error in team generation: '+str(excp))
                    return

            elif action == '_attend':
                selectedDay = self.get_argument('newday', '').strip().lower()
                if not selectedDay:
                    selectedDay = sliauth.print_date()
                else:
                    match = re.match(r'^(\d\d\d\d)-(\d+)-(\d+)$', selectedDay)
                    if not match:
                        self.displayMessage('Invalid attendance date "%s"; must be of the form "yyyy-mm-dd"' % selectedDay, back_url=site_prefix+'/_attend')
                        return
                    selectedDay = '%04d-%02d-%02d' % (int(match.group(1)), int(match.group(2)), int(match.group(3)))
                try:
                    attendanceInfo = sdproxy.getAttendance(selectedDay, new=True)
                    attendanceDays = sdproxy.getAttendanceDays()
                    self.render('attendance.html', site_name=Options['site_name'], session_name='', attendance_days=attendanceDays,
                                selected_day=selectedDay, attendance_info=attendanceInfo, recent=True)
                except Exception, excp:
                    self.displayMessage('Error in creating attendance record: %s' % excp, back_url=site_prefix+'/_attend')

            elif action in ('_import', '_restore', '_roster',):
                # Import from CSV file
                if 'upload' not in self.request.files:
                    self.displayMessage('No file to upload!')
                    return
                fileinfo = self.request.files['upload'][0]
                fname = fileinfo['filename']
                fbody = fileinfo['body']
                if Options['debug']:
                    print >> sys.stderr, 'ActionHandler:upload', action, fname, len(fbody), sessionName, submitDate
                uploadedFile = io.TextIOWrapper(io.BytesIO(fbody), newline=None)   # Universal newline mode for CSV files

                if action == '_restore':
                    overwrite = self.get_argument('overwrite', '')
                    if not sessionName:
                        errMsg = 'Must specify sheet name to restore'
                    else:
                        errMsg = restoreSheet(sessionName, fname, uploadedFile, overwrite=overwrite)
                    if not errMsg:
                        self.displayMessage('Restored sheet %s from file %s' % (sessionName, fname))
                    else:
                        self.displayMessage(errMsg+'\n')

                elif action == '_roster':
                    overwrite = self.get_argument('overwrite', '')
                    lastname_col = self.get_argument('lastnamecol','').strip().lower() 
                    firstname_col = self.get_argument('firstnamecol','').strip().lower() 
                    midname_col = self.get_argument('midnamecol','').strip().lower() 
                    id_col = self.get_argument('idcol','').strip().lower() 
                    email_col = self.get_argument('emailcol','').strip().lower() 
                    altid_col = self.get_argument('altidcol','').strip().lower() 
                    errMsg = importRoster(fname, uploadedFile, overwrite=overwrite, lastname_col=lastname_col, firstname_col=firstname_col,
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
                            self.displayMessage(preElement(errMsg))

            elif action in ('_upload',):
                # Import two files
                if not Options['source_dir']:
                    raise tornado.web.HTTPError(403, log_message='CUSTOM:Must specify source_dir to upload')

                uploadType = self.get_argument('sessiontype', '')
                topName = self.get_argument('topname', '')
                sessionCreate = self.get_argument('sessioncreate', '')
                fname1 = ''
                fbody1 = ''
                fname2 = ''
                fbody2 = ''

                if not uploadType:
                    raise tornado.web.HTTPError(403, log_message='CUSTOM:Must select session type')

                if not sessionCreate:
                    if 'upload1' not in self.request.files and 'upload2' not in self.request.files:
                        self.displayMessage('No file(s) to upload!')
                        return

                    if 'upload1' in self.request.files:
                        fileinfo1 = self.request.files['upload1'][0]
                        fname1 = fileinfo1['filename']
                        fbody1 = fileinfo1['body']

                    if 'upload2' in self.request.files:
                        fileinfo2 = self.request.files['upload2'][0]
                        fname2 = fileinfo2['filename']
                        fbody2 = fileinfo2['body']

                sessionNumber = self.get_argument('sessionnumber', '0')
                if uploadType == RAW_UPLOAD:
                    if sessionCreate:
                        raise tornado.web.HTTPError(403, log_message='CUSTOM:Cannot create blank raw; upload a file')
                    sessionNumber = 0
                    sessionName = ''
                elif uploadType == TOP_LEVEL:
                    if sessionCreate:
                        if not topName:
                            self.render('upload.html', site_name=Options['site_name'], upload_type=TOP_LEVEL, session_name='', session_number='',
                                         session_types=SiteProps.session_types(), err_msg='')
                            return
                        fname1 = topName + '.md'
                        fbody1 = '*Markdown* content'
                    sessionNumber = 0
                    sessionName = os.path.splitext(os.path.basename(fname1 or fname2))[0]
                else:
                    if uploadType not in SiteProps.get_session_props():
                        raise tornado.web.HTTPError(404, log_message='CUSTOM:Unrecognized session type: '+uploadType)

                    if not sessionNumber.isdigit():
                        self.displayMessage('Invalid session number!')
                        return

                    sessionNumber = int(sessionNumber)
                    sessionName = sliauth.SESSION_NAME_FMT % (uploadType, sessionNumber) if sessionNumber else 'index'
                    if sessionCreate:
                        fname1 = sessionName + '.md'
                        fbody1 = '**Table of Contents**\n' if sessionName == 'index' else 'Slidoc: release_date=future\n\nBLANK SESSION\n'

                sessionModify = sessionName if self.get_argument('sessionmodify', '') else None
                    
                if Options['debug']:
                    print >> sys.stderr, 'ActionHandler:upload', uploadType, sessionName, sessionModify, fname1, len(fbody1), fname2, len(fbody2)

                try:
                    if fbody1 and fname1.endswith('.md'):
                        fbody1 = sliauth.normalize_newlines(fbody1)
                    errMsg = self.uploadSession(uploadType, sessionNumber, fname1, fbody1, fname2, fbody2, modify=sessionModify, create=sessionCreate, modimages='clear')
                except Exception, excp:
                    if Options['debug']:
                        import traceback
                        traceback.print_exc()
                    raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in uploading session: '+str(excp))

                if errMsg:
                    self.render('upload.html', site_name=Options['site_name'],
                                upload_type=uploadType, session_name=sessionName, session_number=(sessionNumber or ''), session_types=SiteProps.session_types(), err_msg=errMsg)
                elif uploadType != RAW_UPLOAD:
                    site_prefix = '/'+Options['site_name'] if Options['site_name'] else ''
                    self.redirect(site_prefix+'/_preview/index.html')
                    return
        else:
            self.displayMessage('Invalid post action: '+action)

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
            if os.path.exists(os.path.join(self.site_src_dir, fname, 'index.md')) or self.get_md_list(fname):
                fnames.append(fname)
        fnames.sort()
        return fnames

    def get_topnav_list(self, folders_only=False, uploadType='', session_name=''):
        topFiles = [] if folders_only else [os.path.basename(fpath) for fpath in glob.glob(self.site_web_dir+'/[!_]*.html')]
        topFolders = [ os.path.basename(os.path.dirname(fpath)) for fpath in glob.glob(self.site_web_dir+'/[!_]*/index.html')]
        topFolders2 = [ os.path.basename(os.path.dirname(fpath)) for fpath in glob.glob(self.site_web_dir+'/'+PRIVATE_PATH+'/[!_]*/index.html')]
        if 'index.html' in topFiles:
            del topFiles[topFiles.index('index.html')]

        if uploadType:
            # Include self folder, if not already listed
            if uploadType == TOP_LEVEL:
                if session_name and session_name not in topFiles:
                    topFiles += [session_name]
            elif SiteProps.private_prefix(uploadType):
                if uploadType not in topFolders2:
                    topFolders2 += [uploadType]
            elif uploadType not in topFolders:
                topFolders += [uploadType]

        topFiles.sort()
        topFolders.sort()
        topFolders2.sort()

        topnavList = []

        for j, flist in enumerate([topFolders2, topFiles, topFolders]):
            for fname in flist:
                entry = fname if j > 0 else PRIVATE_PATH+'/'+fname
                if not entry.endswith('.html'):
                    entry += '/index.html'
                if entry not in topnavList:
                    topnavList.append(entry)
        if not folders_only:
            topnavList = ['index.html'] + topnavList
        return topnavList

    def uploadSession(self, uploadType, sessionNumber, fname1, fbody1, fname2='', fbody2='', modify=None, create=False, rollingOver=False, modimages='', deleteSlideNum=0):
        # Return null string on success or error message
        if self.previewActive():
            raise Exception('Already previewing session')

        if Options['debug']:
            print >> sys.stderr, 'sdserver.uploadSession:', uploadType, sessionNumber, fname1, len(fbody1 or ''), fname2, len(fbody2 or ''), modify, modimages, deleteSlideNum

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
                return 'Error: Must enter text or provide .md/.pptx file for upload'
            # Extract Markdown file from zip archive
            topNames = [name for name in zfile.namelist() if name.endswith('.md') or name.endswith('.pptx')]
            if len(topNames) != 1:
                return 'Error: Expecting single .md/.pptx file in zip archive. ' + ', '.join(topNames)
            fname1 = topNames[0]
            fbody1 = zfile.read(fname1)

        fname, fext = os.path.splitext(fname1)
        if uploadType == TOP_LEVEL:
            sessionName = fname
            src_dir = self.site_src_dir
            web_dir = self.site_web_dir
        else:
            sessionName = sliauth.SESSION_NAME_FMT % (uploadType, sessionNumber) if sessionNumber else 'index'
            src_dir = self.site_src_dir + '/' + uploadType
            web_dir = self.site_web_dir + SiteProps.private_prefix(uploadType) + '/' + uploadType

        if sessionName != 'index':
            WSHandler.lockSessionConnections(sessionName, 'Session being modified. Wait ...', reload=False)

        startedPreview = False
        if SiteProps.paced_session(uploadType) and sessionName != 'index':
            # Lock proxy for preview
            temMsg = sdproxy.startPreview(sessionName, rollingOver=rollingOver)
            if temMsg:
                raise Exception('Unable to preview session: '+temMsg)
            startedPreview = True

        try:
            if startedPreview and deleteSlideNum:
                delete_qno = sdproxy.deleteSlide(sessionName, deleteSlideNum)
                if delete_qno:
                    modify = 'overwrite'

            images_zipdata = None
            if fext == '.pptx':
                md_text, images_zipdata = self.pptx2md(sessionName, fbody1, slides_zip=fbody2, zip_images=True)
                fbody1 = md_text.encode('utf8')
            elif fext == '.ipynb':
                nb_dict = json.loads(fbody1)
                nb_parser = nb2md.NBParser(argparse.Namespace(image_dir=sessionName+'_images', output_notes=False, zip_images=True))
                md_text, images_zipdata = nb_parser.parse(nb_dict)
                fbody1 = md_text.encode('utf8')
            else:
                if fext != '.md':
                    raise Exception('Invalid file extension %s; expecting .pptx or .md' % fext)
                if zfile:
                    images_zipdata = fbody2

            src_path = os.path.join(src_dir, sessionName+'.md')
            overwrite = os.path.exists(src_path)
            image_dir = sessionName+'_images'

            extraOpts = {}
            extraOpts['preview_mode'] = True
            extraOpts['overwrite'] = 1 if overwrite else 0
            if modify:
                extraOpts['modify_sessions'] = modify

            retval = self.compile(uploadType, src_path=src_path, contentText=fbody1, images_zipdata=images_zipdata, dest_dir=web_dir,
                                              image_dir=image_dir, extraOpts=extraOpts)

            if 'md_params' not in retval:
                print >> sys.stderr, 'sdserver.uploadSession: Error', uploadType, src_path, len(fbody1), retval
                messages = retval.get('messages',[])
                if any('NOIMAGE:' in message for message in messages):
                    ipaths = []
                    for idir in [os.path.join(src_dir, image_dir), os.path.join(src_dir, '_images')]:
                        if os.path.isdir(idir):
                            ipaths += os.listdir(idir)
                    if zfile:
                        ipaths += zfile.namelist()
                    iset = set()
                    for ipath in ipaths:
                        fname = os.path.basename(ipath)
                        fext = os.path.splitext(fname)[1]
                        if sliauth.IMAGE_MIME_TYPES.get(fext.lower()):
                            iset.add(fname)
                    messages.append('Images loaded:')
                    for iname in sorted(list(iset)):
                        messages.append('    _images/'+iname)
                raise Exception('\n'.join(messages)+'\n')

            md_params = retval['md_params']

            # Save current preview state (allowing user to navigate and answer questions, without saving those changes)
            if startedPreview:
                sdproxy.savePreview()

            # NOTE: If adding any preview fields here, also modify createUnmodifiedPreview below
            self.previewState['md'] = fbody1
            self.previewState['md_defaults'] = md_params.get('md_defaults', '')
            self.previewState['md_slides'] = md_params.get('md_slides', [])
            self.previewState['new_image_number'] = md_params.get('new_image_number', 0)
            self.previewState['HTML'] = retval['out_html']
            self.previewState['TOC'] = retval['toc_html']
            self.previewState['messages'] = retval['messages']
            self.previewState['type'] = uploadType
            self.previewState['number'] = sessionNumber
            self.previewState['name'] = sessionName
            self.previewState['label'] = getSessionLabel(sessionName, uploadType)
            self.previewState['src_dir'] = src_dir       # Parent directory of session file
            self.previewState['web_dir'] = web_dir       # Parent directory of session file
            self.previewState['image_dir'] = image_dir
            self.previewState['image_zipbytes'] = io.BytesIO(images_zipdata) if images_zipdata else None
            self.previewState['image_zipfile'] = zipfile.ZipFile(self.previewState['image_zipbytes'], 'a') if images_zipdata else None
            self.previewState['image_paths'] = sliauth.map_images(self.previewState['image_zipfile'].namelist()) if images_zipdata else {}

            Global.previewModifiedCount += 1
            self.previewState['modified'] = Global.previewModifiedCount
            self.previewState['modify_session'] = modify
            self.previewState['modimages'] = modimages
            self.previewState['overwrite'] = overwrite
            self.previewState['rollover'] = None
            self.previewState['session_responders'] = getResponderCount(sessionName, uploadType)
            return ''

        except Exception, err:
            if Options['debug']:
                import traceback
                traceback.print_exc()
            self.previewClear()
            if sessionName != 'index':
                WSHandler.lockSessionConnections(sessionName, '', reload=False)
            temMsg = err.message+'\n'
            if temMsg.strip() and not temMsg.lower().startswith('error'):
                temMsg = 'Error:\n' + temMsg
            return temMsg

    def createUnmodifiedPreview(self, sessionName, slideId=''):
        uploadType, sessionNumber, src_path, web_path, web_images = self.getUploadType(sessionName)

        if self.previewState:
            self.previewClear()

        if SiteProps.paced_session(uploadType) and sessionName != 'index':
            temMsg = sdproxy.startPreview(sessionName)
            if temMsg:
                if temMsg.startswith('PENDING:'):
                    site_prefix = '/'+Options['site_name'] if Options['site_name'] else ''
                    temURL = site_prefix + '/_startpreview/' + sliauth.safe_quote(sessionName) + '?slideid=' + slideId
                    temMsg = '<a href="%s">Retry preview</a>. %s' % (temURL, temMsg[len('PENDING:'):])
                    raise tornado.web.HTTPError(404, log_message='CUSTOM:'+temMsg)

                raise Exception('Unable to preview session: '+temMsg)

        try:
            with open(web_path) as f:
                sessionHTML = f.read()
        except Exception, excp:
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in reading preview file %s: %s' % (web_path, excp))

        if sessionName == 'index' and uploadType != TOP_LEVEL:
            self.previewState['TOC'] = sessionHTML
            self.previewState['HTML'] = ''
        else:
            self.previewState['TOC'] = ''
            self.previewState['HTML'] = sessionHTML

        self.previewState['md'] = ''
        self.previewState['md_defaults'] = ''
        self.previewState['md_slides'] = []
        self.previewState['new_image_number'] = 0
        self.previewState['messages'] = ['Unmodified preview of '+sessionName]
        self.previewState['type'] = uploadType
        self.previewState['number'] = sessionNumber
        self.previewState['name'] = sessionName
        self.previewState['label'] = getSessionLabel(sessionName, uploadType)
        self.previewState['src_dir'] = os.path.dirname(src_path)
        self.previewState['web_dir'] = os.path.dirname(web_path)
        self.previewState['image_dir'] = ''
        self.previewState['image_zipbytes'] = None
        self.previewState['image_zipfile'] = None
        self.previewState['image_paths'] = {}

        self.previewState['modified'] = 0
        self.previewState['modify_session'] = ''
        self.previewState['modimages'] = ''
        self.previewState['overwrite'] = False
        self.previewState['rollover'] = None
        self.previewState['session_responders'] = getResponderCount(sessionName, uploadType)


    def reloadPreview(self, slideNumber=0):
        previewingSession = self.previewActive()
        if not previewingSession:
            return
        previewPath = '_preview/index.html'
        if Options['site_name']:
            previewPath = Options['site_name'] + '/' + previewPath
        userId = self.get_id_from_cookie()
        userRole = self.get_id_from_cookie(role=True, for_site=Options['site_name'])
        if Options['debug']:
            print >> sys.stderr, 'sdserver.reloadPreview: slide=%s, userId=%s' % (slideNumber, userId)
        # Broadcast reload event to admin user accessing preview
        WSHandler.sendEvent(previewPath, '', userRole, False, True, [userId, 1, 'ReloadPage', [slideNumber]])

    def compile(self, uploadType, src_path='', contentText='', images_zipdata='', dest_dir='', image_dir='', indexOnly=False,
                make='', extraOpts={}):
        # If src_path, compile single .md file, returning output
        # Else, compile all files of that type, updating index etc.
        images_zipdict = {}
        if src_path:
            sessionName = os.path.splitext(os.path.basename(src_path))[0]
            if images_zipdata:
                images_zipdict[sessionName] = images_zipdata
        else:
            sessionName = ''

        filePaths = self.get_md_list(uploadType, newSession=sessionName)
        if not filePaths and src_path and sessionName != 'index':
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Empty session folder '+uploadType)

        fileNames = [os.path.basename(fpath) for fpath in filePaths]

        configOpts, defaultOpts = self.get_config_opts(uploadType, text=contentText, topnav=True, dest_dir=dest_dir,
                                                       session_name=sessionName, image_dir=image_dir, make=make)

        configOpts.update(extraOpts)

        nb_links = {}
        if uploadType != TOP_LEVEL:
            if sessionName == 'index':
                configOpts['toc_header'] = io.BytesIO(contentText)
            else:
                src_dir = os.path.dirname(filePaths[0]) if filePaths else self.site_src_dir + '/' + uploadType
                ind_path = os.path.join(src_dir, 'index.md')
                if os.path.exists(ind_path):
                    configOpts['toc_header'] = ind_path

            if Options['notebook_extn']:
                notebooks_dir = Options['web_dir']
                if Options['site_name']:
                    notebooks_dir = os.path.join(notebooks_dir, Options['site_name'])
                notebooks_dir = os.path.join(notebooks_dir, *NOTEBOOKS_PATH.split('/'))
                if os.path.isdir(notebooks_dir):
                    for fname in fileNames:
                        sname = os.path.splitext(fname)[0]
                        nb_name = sname+'.'+Options['notebook_extn']
                        if os.path.exists( os.path.join(notebooks_dir, nb_name) ):
                            _, nb_links[sname] = self.viewer_link(NOTEBOOKS_PATH + '/' + nb_name)

        if src_path:
            fileHandles = [io.BytesIO(contentText) if fpath == src_path else None for fpath in filePaths]
        elif indexOnly:
            fileHandles = [None for fpath in filePaths]
        else:
            fileHandles = [open(fpath) for fpath in filePaths]

        if Options['debug']:
            print >> sys.stderr, Options['server_url'], 'sdserver.compile: %s type=%s, src=%s, index=%s, server=%s, make=%s, create_toc=%s, topnav=%s, strip=%s:%s, pace=%s:%s, nb=%s, files=%s' % (sliauth.iso_date(nosubsec=True), uploadType, repr(src_path), indexOnly, configOpts.get('server_url'), configOpts.get('make'), configOpts.get('create_toc'), configOpts.get('topnav'), configOpts.get('strip'), defaultOpts.get('strip'), configOpts.get('pace'), defaultOpts.get('pace'), nb_links.keys(), fileNames)

        return_html = bool(src_path)

        try:
            extra_attributes = {'privateSession': 1 if SiteProps.private_prefix(uploadType) else 0}
            retval = slidoc.process_input(fileHandles, filePaths, configOpts, default_args_dict=defaultOpts, return_html=return_html,
                                          images_zipdict=images_zipdict, nb_links=nb_links, http_post_func=http_sync_post,
                                          restricted_sessions_re=sliauth.RESTRICTED_SESSIONS_RE, return_messages=True,
                                          extra_attributes=extra_attributes)
        except Exception, excp:
            if Options['debug']:
                import traceback
                traceback.print_exc()
            # Error return
            return {'messages': ['Error in compile: '+(excp.message or str(excp))]}
            
        if return_html:
            if Options['debug'] and retval.get('messages'):
                print >> sys.stderr, 'sdserver.compile:', src_path, ' '.join(fileNames)+'\n', '\n'.join(retval['messages'])
            return retval
        else:
            # Normal return
            return {'messages': retval.get('messages', []) if retval else []}

    def rebuild(self, uploadType='', indexOnly=False, make='', log_dict=False):
        if uploadType:
            utypes = [uploadType] if uploadType != TOP_LEVEL else []
        else:
            utypes = self.get_session_names()

        if not indexOnly:
            WSHandler.lockAllConnections('Site rebuilt. Reload page', reload=True)

        msg_dict = {}
        msg_list = []
        if Options['debug'] :
            print >> sys.stderr, 'sdserver.rebuild:', make, utypes
        for utype in utypes:
            retval = self.compile(utype, dest_dir=self.site_web_dir+SiteProps.private_prefix(utype)+'/'+utype, indexOnly=indexOnly, make=make)
            msgs = retval.get('messages',[])
            msg_dict[utype] = msgs
            if msgs:
                msg_list += msgs + ['']

        retval = self.compile(TOP_LEVEL, dest_dir=self.site_web_dir, indexOnly=False, make='')
        msgs = retval.get('messages',[])
        msg_dict[TOP_LEVEL] = msgs
        if msgs:
            msg_list += msgs

        return msg_dict if log_dict else msg_list


    def imageUpload(self, sessionName, imageFile, fname, fbody, autonumber=None):
        if Options['debug']:
            print >> sys.stderr, 'ActionHandler:imageUpload', sessionName, imageFile, fname, autonumber, len(fbody)
        if not self.previewActive():
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Not previewing session')
        if not imageFile:
            imgName = re.sub(r'[^\w,.+-]', '', fname.strip().replace(' ','_'))
            if imgName and not autonumber:
                imageFile = imgName
            else:
                imageFile = (md2md.IMAGE_FMT % self.previewState['new_image_number']) + os.path.splitext(fname)[1].lower()
            self.previewState['new_image_number'] += 1
        if not self.previewState['image_zipfile']:
            self.previewState['image_zipbytes'] = io.BytesIO()
            self.previewState['image_zipfile'] = zipfile.ZipFile(self.previewState['image_zipbytes'], 'a')
        imagePath = sessionName+'_images/' + imageFile
        self.previewState['image_zipfile'].writestr(imagePath, fbody)
        self.previewState['image_paths'][imageFile] = imagePath
        self.previewState['modimages'] = 'append'

        self.set_header('Content-Type', 'application/json')
        self.write( json.dumps( {'result': 'success', 'imageFile': imageFile} ) )


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
            mime_type = sliauth.IMAGE_MIME_TYPES.get(fext.lower())
            if mime_type:
                if self.previewState['image_zipfile'] and fname+fext in self.previewState['image_paths']:
                    content = self.previewState['image_zipfile'].read(self.previewState['image_paths'][fname+fext])
                else:
                    web_dir = self.site_web_dir if uploadType == TOP_LEVEL else self.site_web_dir + SiteProps.private_prefix(uploadType)+'/' + uploadType
                    img_path = web_dir+'/'+sessionName+'_images/'+fname+fext
                    if os.path.exists(img_path):
                        with open(img_path) as f:
                            content = f.read()

        if mime_type and content is not None:
            self.set_header('Content-Type', mime_type)
            self.write(content)
        else:
            raise tornado.web.HTTPError(404)

    def extractFolder(self, zfile, dirpath, folder, clear=False):
        # Extract all folder files in zfile to a single folder named dirpath/folder
        # If clear, clear old files in dirpath/folder
        renameFolder = False
        extractList = []
        for name in zfile.namelist():
            if '/' not in name or name.endswith('/'):
                continue
            # File in folder
            extractList.append(name)
            if not name.startswith(folder+'/'):
                renameFolder = True

        folderpath = folder
        if dirpath:
            folderpath = os.path.join(dirpath, folderpath)
        if os.path.exists(folderpath):
            if clear:
                for fname in os.listdir(folderpath):
                    fpath = os.path.join(folderpath, fname)
                    if os.path.isfile(fpath):
                        os.remove(fpath)
        elif extractList:
            os.makedirs(folderpath)

        if not extractList:
            return

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
            

    def downloadPreview(self):
        if not self.previewState:
            raise tornado.web.HTTPError(403, log_message='CUSTOM:No preview state to download')

        sessionName = self.previewState['name']

        if Options['debug']:
            print >> sys.stderr, 'ActionHandler:downloadPreview', sessionName, self.previewState['type']

        if self.previewState['image_zipfile']:
            # Create zip archive with Markdown file and images
            stream = io.BytesIO()
            zfile = zipfile.ZipFile(stream, 'w')
            zfile.writestr(sessionName+'.md', self.previewState['md'])
            for name in self.previewState['image_zipfile'].namelist():
                if '/' not in name or name.endswith('/'):
                    continue
                imgPath = sessionName+'_images/' + name.split('/')[-1]
                zfile.writestr(imgPath, self.previewState['image_zipfile'].read(name))
            zfile.close()
            content = stream.getvalue()
            outfile = sessionName+'-preview.zip'
            self.set_header('Content-Type', 'application/zip')

        else:
            # Plain markdown
            content = self.previewState['md']
            outfile = sessionName+'-preview.md'
            self.set_header('Content-Type', 'text/plain')

        self.set_header('Content-Disposition', 'attachment; filename="%s"' % outfile)
        self.write(content)


    def acceptPreview(self, modified=0, acceptMessages=[], slideId=''):
        # Modified == -1 disables version checking
        if Options['dry_run'] and not Options['dry_run_file_modify']:
            raise tornado.web.HTTPError(403, log_message='CUSTOM:Cannot accept edits during dry run')

        if not self.previewState:
            raise tornado.web.HTTPError(403, log_message='CUSTOM:No preview state to accept')

        sessionName = self.previewState['name']
        uploadType = self.previewState['type']
        src_dir = self.previewState['src_dir']
        web_dir = self.previewState['web_dir']

        if Options['debug']:
            print >> sys.stderr, 'ActionHandler:acceptPreview', sessionName, slideId, uploadType, src_dir, web_dir, modified, self.previewState['modimages']

        if not self.previewState['modified']:
            raise tornado.web.HTTPError(403, log_message='CUSTOM:Cannot accept unmodified preview for session '+sessionName)

        if  modified >= 0 and modified != self.previewState['modified']:
            raise tornado.web.HTTPError(403, log_message='CUSTOM:Modified version mismatch when accepting preview for session %s (%s vs %s)' % (sessionName, modified, self.previewState['modified']))

        try:
            if not os.path.exists(src_dir):
                os.makedirs(src_dir)

            with open(src_dir+'/'+sessionName+'.md', 'w') as f:
                f.write(self.previewState['md'])

            if self.previewState['image_zipfile'] and self.previewState['modimages']:
                self.extractFolder(self.previewState['image_zipfile'], src_dir, self.previewState['image_dir'],
                                   clear=(self.previewState['modimages'] == 'clear'))

        except Exception, excp:
            if Options['debug']:
                import traceback
                traceback.print_exc()
            self.previewClear()   # Revert to original version
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in saving edited session %s to source directory %s: %s' % (sessionName, src_dir, excp))

        try:
            if not os.path.exists(web_dir):
                os.makedirs(web_dir)

            if sessionName != 'index' or uploadType == TOP_LEVEL:
                with open(web_dir+'/'+sessionName+'.html', 'w') as f:
                    f.write(self.previewState['HTML'])

            if self.previewState['TOC'] and (sessionName != 'index' or uploadType != TOP_LEVEL):
                with open(web_dir+'/index.html', 'w') as f:
                    f.write(self.previewState['TOC'])

            if self.previewState['image_zipfile']:
                self.extractFolder(self.previewState['image_zipfile'], web_dir, self.previewState['image_dir'],
                                   clear=(self.previewState['modimages'] == 'clear'))

        except Exception, excp:
            if Options['debug']:
                import traceback
                traceback.print_exc()
            self.previewClear()   # Revert to original version
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in saving edited session %s to web directory %s: %s' % (sessionName, web_dir, excp))

        sessionLabel = self.previewState['label']
        rolloverParams = self.previewState['rollover']

        if self.previewState['modify_session']:
            # Being conservative in updating session version to avoid client reloads; update only if "modifying" session
            WSHandler.getSessionVersion(sessionName, update=True)

        # Success. Revert to saved version of preview (discarding any navigation/answer info); this may trigger proxy updates
        self.previewClear(saved_version=True)   

        if sessionName != 'index':
            WSHandler.lockSessionConnections(sessionName, 'Session modified. Reload page', reload=True)
        errMsgs = self.rebuild(uploadType, indexOnly=True)

        msgs = []
        if errMsgs and any(errMsgs):
            msgs = ['Saved changes to session ' + sessionLabel] + errMsgs
        if acceptMessages:
            msgs = acceptMessages + msgs

        logErrors = 'error' in ''.join(msgs).lower()

        previewOnly = False
        if sessionName != 'index' and SiteProps.paced_session(uploadType):
            sessionEntries = sdproxy.lookupValues(sessionName, ['releaseDate', 'paceLevel', 'adminPaced'], sdproxy.INDEX_SHEET)
            if sessionEntries['paceLevel'] == sdproxy.ADMIN_PACE:
                if not getResponderCount(sessionName, uploadType):
                    previewOnly = True
            elif sessionEntries['releaseDate'] == sliauth.FUTURE_DATE:
                previewOnly = True
            
        site_prefix = '/'+Options['site_name'] if Options['site_name'] else ''

        if slideId and not logErrors:
            # Redisplay slide
            if previewOnly:
                redirPath = site_prefix + '/_startpreview/' + sliauth.safe_quote(sessionName) + '?slideid=' + slideId
            else:
                redirPath = getSessionPath(sessionName, site_prefix=True) + '?slideid=' + slideId
        else:
            # Display ToC
            redirPath = getSessionPath(sessionName, site_prefix=True, toc=True)

        if rolloverParams:
            self.truncateSession(rolloverParams, prevSessionName=sessionName, prevMsgs=msgs, rollingOver=True)
        elif previewOnly or (msgs and (logErrors or not slideId)):
            self.displayMessage(msgs, back_url=redirPath)
        else:
            self.redirect(redirPath)


    def truncateSession(self, truncateParams, prevSessionName='', prevMsgs=[], rollingOver=False):
        # Truncate session (possibly after rollover)
        sessionName = truncateParams['sessionName']
        sessionPath = getSessionPath(sessionName, site_prefix=True)

        try:
            errMsg = self.uploadSession(truncateParams['uploadType'], truncateParams['sessionNumber'], truncateParams['sessionName']+'.md', truncateParams['sessionText'], truncateParams['fname2'], truncateParams['fbody2'], modify='truncate', rollingOver=rollingOver)

        except Exception, excp:
            if Options['debug']:
                import traceback
                traceback.print_exc()
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in truncating rolled over session %s: %s' % (sessionName, excp))

        if errMsg:
            if self.previewState:
                self.discardPreview()
            if prevSessionName:
                self.displayMessage('Error in truncating rolled over session '+sessionName+': '+errMsg, back_url=sessionPath)
            else:
                self.set_header('Content-Type', 'application/json')
                retval = {'result': 'error', 'error': errMsg}
                self.write( json.dumps(retval) )
            return

        self.previewState['modimages'] = 'clear'

        previewPath = '/_preview/index.html'
        if Options['site_name']:
            previewPath = '/'+Options['site_name']+previewPath

        if prevSessionName:
            html_prefix = 'Rolled over %s slides from session %s to session %s. <b>Proceed to preview of truncated session <a href="%s">%s</a></b>' % (truncateParams['slidesRolled'], sessionName, prevSessionName, previewPath, sessionName)
            self.displayMessage(prevMsgs, html_prefix=html_prefix)
        else:
            self.set_header('Content-Type', 'application/json')
            retval = {'result': 'success'}
            self.write( json.dumps(retval) )

    def discardPreview(self, sessionName='', modified=0):
        # Modified == -1 disables version checking
        if self.previewActive():
            sessionName = self.previewState['name']
            if modified >= 0 and modified != self.previewState['modified']:
                self.displayMessage('Failed to discard obsolete preview for session '+sessionName)
                return
            self.previewClear()
            if sessionName != 'index':
                WSHandler.lockSessionConnections(sessionName, 'Session mods discarded. Reload page', reload=True)
        self.displayMessage('Discarded changes' if modified else 'Closed preview', back_url=getSessionPath(sessionName, site_prefix=True, toc=True))

    def previewClear(self, saved_version=False, final_version=False):
        if sdproxy.previewingSession():
            if final_version:
                sdproxy.endPreview()
            else:
                sdproxy.revertPreview(saved=saved_version)
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


    def editSession(self, sessionName, sessionType='', sessionText='', start=False, startPreview=False, update=False, modify=None, fromSession='', fromSite='', slideNumber=None, newNumber=None, deleteSlide='', imageZip=None):
        # sessiontext may be modified text for all slides or just a single slide, depending upon slideNumber
        sessionName, sessionText, fromSession, fromSite = md2md.stringify(sessionName, sessionText, fromSession, fromSite)

        if Options['debug']:
            print >> sys.stderr, 'ActionHandler:editSession: session=%s, type=%s, start=%s, startPreview=%s, update=%s, modify=%s, ntext=%s, from=%s:%s, slide=%s, new=%s, del=%s' % (sessionName, sessionType, start, startPreview, update, modify, len(sessionText), fromSession, fromSite, slideNumber, newNumber, deleteSlide)

        sessionLabel = sessionName
        temSessionName = sessionType+'00' if sessionName == 'index' and sessionType else sessionName
        uploadType, sessionNumber, src_path, web_path, web_images = self.getUploadType(temSessionName)
        if uploadType != TOP_LEVEL and not sessionNumber:
            sessionName = 'index'
            sessionLabel = uploadType+'/index'

        sameSession = (not fromSession or fromSession == sessionName) and (not fromSite or fromSite == Options['site_name'])

        if self.previewState and sessionName != self.previewState['name']:
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Edit session %s does not match preview session %s' % (sessionName, self.previewState['name']))

        if start or startPreview:
            if slideNumber:
                if self.previewState:
                    if self.previewState['md_slides'] is None:
                        raise tornado.web.HTTPError(404, log_message='CUSTOM:Unable to edit individual slides in preview')
                    md_defaults = self.previewState['md_defaults']
                    md_slides = self.previewState['md_slides']
                    new_image_number = self.previewState['new_image_number']
                    if slideNumber > len(md_slides):
                        raise tornado.web.HTTPError(404, log_message='CUSTOM:Invalid preview slide number %d of %d' % (slideNumber, len(md_slides)) )
                    sessionText = md_slides[slideNumber-1]
                    sessionResponders = self.previewState['session_responders']

                else:
                    md_defaults, sessionText, _, md_header, new_image_number = self.extract_slide_range(src_path, web_path, start_slide=slideNumber, end_slide=slideNumber)
                    sessionResponders = getResponderCount(sessionName, uploadType)

                sessionText = strip_slide(sessionText)
                if not startPreview:
                    # Edit single slide
                    retval = {'slideText': sessionText, 'sessionResponders': sessionResponders, 'newImageName': md2md.IMAGE_FMT % new_image_number}
                    self.set_header('Content-Type', 'application/json')
                    self.write( json.dumps(retval) )
                    return

            else:
                if self.previewState:
                    sessionText = self.previewState['md']
                    sessionResponders = self.previewState['session_responders']

                else:
                    # Setup preview by uploading file
                    try:
                        with open(src_path) as f:
                            sessionText = f.read()
                        if isinstance(sessionText, unicode):
                            sessionText = sessionText.encode('utf-8')
                    except Exception, excp:
                        raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in reading session file %s: %s' % (src_path, excp))
                    sessionResponders = getResponderCount(sessionName, uploadType)


                if not startPreview:
                    # Edit all slides
                    self.render('edit.html', site_name=Options['site_name'], session_name=temSessionName, session_label=sessionLabel,
                                session_text=sessionText, session_responders=sessionResponders, discard_url='_preview/index.html', err_msg='')
                    return

        prevPreviewState = self.previewState.copy() if self.previewState else None
        slide_images_zip = None
        image_zipdata = ''
        deleteSlideNum = 0
        if slideNumber:
            # Editing slide
            if self.previewState and self.previewState['modified']:
                if self.previewState['md_slides'] is None:
                    raise tornado.web.HTTPError(404, log_message='CUSTOM:Unable to edit individual slides in preview')
                md_defaults = self.previewState['md_defaults']
                md_slides = self.previewState['md_slides'][:]  # Shallow copy of slides so as not overwrite any backup copy
                new_image_number = self.previewState['new_image_number']
            else:
                if self.previewState and not self.previewState['modified']:
                    # Clear any unmodified preview
                    self.previewClear()
                    
                md_defaults, md_slides, md_header, new_image_number = self.extract_slides(src_path, web_path)
                if not sameSession:
                    _, _, image_zipdata, _, _ = self.extract_slide_range(src_path, web_path) # Redundant, but need images

            if sameSession and slideNumber > len(md_slides):
                raise tornado.web.HTTPError(404, log_message='CUSTOM:Invalid slide number %d of %d' % (slideNumber, len(md_slides)) )

            if not sameSession:
                # Insert slide from another session
                _, _, from_src, from_web, _ = self.getUploadType(fromSession, siteName=fromSite)
                _, slideText, slide_images_zip, _, new_image_number = self.extract_slide_range(from_src, from_web, start_slide=slideNumber, end_slide=slideNumber, renumber=new_image_number, session_name=sessionName)

                if not newNumber or newNumber > len(md_slides)+1:
                    raise tornado.web.HTTPError(404, log_message='CUSTOM:Invalid insert slide number %d' % newNumber)
                insertText = pad_slide(slideText)
                md_slides.insert(newNumber-1, insertText)
                splice_slides(md_slides, newNumber-2)
                splice_slides(md_slides, newNumber-1)

            elif deleteSlide:
                # Delete slide
                deleteSlideNum = slideNumber
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
        modimages = ''
        if self.previewState:
            if self.previewState['image_zipbytes']:
                self.previewState['image_zipfile'].close()
                fbody2 = self.previewState['image_zipbytes'].getvalue()
                fname2 = sessionName+'_images.zip'
                modimages = self.previewState['modimages']
            self.previewClear()    # Revert to original version
        elif image_zipdata:
            fbody2 = image_zipdata
            fname2 = sessionName+'_images.zip'

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

        imageZipPaths = []
        if imageZip:
            # Append referred image(s) from edit page zip upload
            refpaths = []
            for ipath in imageZip.namelist():
                fname = os.path.basename(ipath)
                fext = os.path.splitext(fname)[1]
                if not sliauth.IMAGE_MIME_TYPES.get(fext.lower()):
                    continue
                imageZipPaths.append('_images/'+fname)
                if '_images/'+fname in sessionText:
                    # Image file reference found in text
                    refpaths.append(ipath)
            imageZipPaths.sort()
            if refpaths:
                modimages = 'append'
                stream = io.BytesIO(fbody2)
                zfile = zipfile.ZipFile(stream, 'a')
                for ipath in refpaths:
                    zfile.writestr(sessionName+'_images/'+os.path.basename(ipath), imageZip.read(ipath))
                zfile.close()
                fbody2 = stream.getvalue()
                fname2 = sessionName+'_images.zip'

        try:
            errMsg = self.uploadSession(uploadType, sessionNumber, sessionName+'.md', sessionText, fname2, fbody2, modify=modify, modimages=modimages, deleteSlideNum=deleteSlideNum)
        except Exception, excp:
            if Options['debug']:
                import traceback
                traceback.print_exc()
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in editing session %s: %s' % (sessionName, excp))

        if errMsg:
            if prevPreviewState:
                self.previewState.update(prevPreviewState)

            if not errMsg.lower().startswith('error'):
                errMsg = 'Error in editing session '+sessionName+': '+errMsg
            else:
                if 'NOIMAGE:' in errMsg and imageZipPaths:
                    errMsg += 'Images available:\n' + '\n'.join(imageZipPaths) + '\n'
                errMsg += ' (session: '+sessionName+')'
            raise tornado.web.HTTPError(404, log_message='CUSTOM:'+errMsg)

        self.previewState['modimages'] = modimages
        site_prefix = '/'+Options['site_name'] if Options['site_name'] else ''
        if update:
            self.reloadPreview(slideNumber)
        if startPreview:
            self.redirect(site_prefix+'/_preview/index.html')
        else:
            self.set_header('Content-Type', 'application/json')
            self.write( json.dumps( {'result': 'success'} ) )


    @tornado.gen.coroutine
    def submitSession(self, sessionName, postGrades=''):
        user = sdproxy.TESTUSER_ID
        try:
            userEntries = sdproxy.lookupValues(user, ['submitTimestamp'], sessionName, listReturn=True)
        except Exception, excp:
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Failed to submit session '+sessionName+':'+str(excp))
            
        if Options['debug']:
            print >> sys.stderr, 'ActionHandler:submitSession', userEntries, sessionName, postGrades
        if userEntries[0]:
            # test user has already submitted
            return
        userToken = gen_proxy_auth_token(sdproxy.ADMINUSER_ID, sdproxy.ADMIN_ROLE, prefixed=True)
        args = {'sheet': sessionName, 'id': user, 'admin': sdproxy.ADMINUSER_ID, 'token': userToken}
        args['update'] = json.dumps([['id', user], ['submitTimestamp', sdproxy.createDate()]], default=sliauth.json_default)
        if postGrades:
            args['completeactions'] = '*gradebook'     # * => create if needed

        retObj = sdproxy.sheetAction(args)
        if retObj['result'] != 'success':
            raise Exception('Error in submitting session '+sessionName+': '+retObj.get('error',''))
        for j in range(20):
            sessionSheet = sdproxy.getSheet(sessionName)
            if sessionSheet and sessionSheet.get_updates() is not None:
                print >> sys.stderr, 'ActionHandler:submitSession.SLEEP', j
                yield tornado.gen.sleep(1)

    def releaseModule(self, sessionName, releaseDate=''):
        releaseDate = str(releaseDate)  # Unicode releaseDate contaminates the UTF-8 strings
        if releaseDate and releaseDate != sliauth.FUTURE_DATE and not sliauth.parse_date(releaseDate):
            self.displayMessage('Invalid release date "%s" specified for module %s' % (releaseDate, sessionName),
                                back_url=getSessionPath(sessionName, site_prefix=True, toc=True))
            return

        uploadType, sessionNumber, src_path, web_path, web_images = self.getUploadType(sessionName)
        try:
            with open(src_path) as f:
                sessionText = f.read()
                if isinstance(sessionText, unicode):
                    sessionText = sessionText.encode('utf-8')
        except Exception, excp:
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in reading module file %s: %s' % (src_path, excp))

        newReleaseOpt = 'release_date='+releaseDate if releaseDate else ''

        slidocOptions, nskip = sliauth.read_header_opts(io.BytesIO(sessionText))
        if nskip:
            # First line(s) with slidoc options found
            sessionText = sessionText[nskip:]
            rmatch = re.search(r'\b(release_date=(\S+))(\s|$)', slidocOptions)
            if rmatch:
                # Replace option
                slidocOptions = slidocOptions.replace('--'+rmatch.group(1), '--'+newReleaseOpt if newReleaseOpt else '')
                slidocOptions = slidocOptions.replace(rmatch.group(1), newReleaseOpt)
            elif newReleaseOpt:
                # Add option
                slidocOptions += ' ' + newReleaseOpt
        elif newReleaseOpt:
            # Insert new first line with slidoc options
            slidocOptions = newReleaseOpt

        if slidocOptions:
            sessionText = '<!--Slidoc: ' + slidocOptions + ' -->\n' + sessionText

        if Options['debug']:
            print >> sys.stderr, 'ActionHandler:releaseModule', releaseDate, sessionName, slidocOptions

        try:
            errMsg = self.uploadSession(uploadType, sessionNumber, sessionName+'.md', sessionText, '', '')
        except Exception, excp:
            if Options['debug']:
                import traceback
                traceback.print_exc()
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in releasing module %s: %s' % (sessionName, excp))

        if errMsg:
            if not errMsg.lower().startswith('error'):
                errMsg = 'Error in releasing session '+sessionName+': '+errMsg
            else:
                errMsg += ' (session: '+sessionName+')'
            raise tornado.web.HTTPError(404, log_message='CUSTOM:'+errMsg)

        self.acceptPreview(modified=-1, acceptMessages=['Released module '+sessionName, ''] + self.previewState['messages'])

    def rollover(self, sessionName, slideNumber=None, truncateOnly=False):
        sessionName = md2md.stringify(sessionName)
        if self.previewState:
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Rollover not permitted in preview state')

        uploadType, sessionNumber, src_path, web_path, web_images = self.getUploadType(sessionName)
        if uploadType == TOP_LEVEL:
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Rollover not permitted for top-level pages')

        sessionEntries = sdproxy.lookupValues(sessionName, ['attributes', 'paceLevel'], sdproxy.INDEX_SHEET)
        sessionAttributes = json.loads(sessionEntries['attributes'])
        adminPaced = (sessionEntries['paceLevel'] == sdproxy.ADMIN_PACE)
        discussSlides = sessionAttributes.get('discussSlides', [])

        lastSlide = None
        submitted = ''
        try:
            userEntries = sdproxy.lookupValues(sdproxy.TESTUSER_ID, ['submitTimestamp', 'lastSlide'], sessionName)
            submitted = userEntries['submitTimestamp']
            lastSlide = userEntries['lastSlide']
        except Exception, excp:
            print >> sys.stderr, 'sdserver.rollover', excp
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Unable to access rollover testuser entry for session '+sessionName)

        if not lastSlide:
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Zero last slide entry to rollover session '+sessionName)

        if discussSlides and submitted:
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Truncation/rollover does not yet work with discussions for submitted session '+sessionName)

        _, md_slides, _, _ = self.extract_slides(src_path, web_path)

        slideNumber = slideNumber or lastSlide
        end_slide = slideNumber if truncateOnly else lastSlide
        start_slide = min(slideNumber+1, lastSlide+1)

        if Options['debug']:
            print >> sys.stderr, 'ActionHandler:rollover', sessionName, slideNumber, lastSlide, len(md_slides)

        if end_slide > len(md_slides):
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Invalid end slide %d for truncating session %s with %d slides' % (end_slide, sessionName, len(md_slides)))

        if adminPaced:
            if truncateOnly:
                if end_slide != lastSlide:
                    raise tornado.web.HTTPError(404, log_message='CUSTOM:Truncation only allowed at end for admin-paced session '+sessionName)

        truncate_defaults, truncateText, truncate_images_zip, truncateHeader, _ = self.extract_slide_range(src_path, web_path, start_slide=1, end_slide=end_slide, renumber=1, session_name=sessionName)

        if end_slide < len(md_slides):
            truncateText = truncate_defaults + strip_slide(truncateText)
            rolloverParams = {'uploadType': uploadType,
                              'sessionNumber': sessionNumber,
                              'sessionName': sessionName,
                              'sessionText': truncateText,
                              'slidesCut': len(md_slides)-end_slide,
                              'slidesRolled': len(md_slides)-start_slide+1,
                              'fname2': '',
                              'fbody2': ''}
            if truncate_images_zip:
                rolloverParams['fbody2'] = truncate_images_zip
                rolloverParams['fname2'] = sessionName+'_images.zip'
        else:
            if truncateOnly:
                raise tornado.web.HTTPError(404, log_message='CUSTOM:Cannot truncate because end slide is %d for session %s with %d slides' % (end_slide, sessionName, len(md_slides)))
            rolloverParams = None

        if truncateOnly:
            self.truncateSession(rolloverParams)
            return

        # Rollover slides to next session
        _, rolloverText, rollover_images_zip, rolloverHeader, new_image_number = self.extract_slide_range(src_path, web_path, start_slide=start_slide, renumber=1, session_name=sessionName)

        sessionNext = sliauth.SESSION_NAME_FMT % (uploadType, sessionNumber+1)
        _, _, src_next, web_next, web_images_next = self.getUploadType(sessionNext)

        next_prefix = ''
        if os.path.exists(src_next):
            # Next session exists
            next_defaults, nextText, next_images_zip, nextHeader, new_image_number = self.extract_slide_range(src_next, web_next, renumber=new_image_number, session_name=sessionNext)
        else:
            # Create next session
            next_defaults, nextText, next_images_zip, nextHeader, new_image_number = truncate_defaults, '', None, '', new_image_number

            if rolloverHeader:
                next_prefix = '\n# cont. %s\n\n----\n\n' % rolloverHeader

            # Do not release it by default
            if not next_defaults:
                next_defaults = 'Slidoc: \n\n'

            if not re.search(r'\brelease_date=', next_defaults):
                # "Unrelease" rolled over session
                replaceStr = None
                if 'Slidoc:' in next_defaults:
                    replaceStr = 'Slidoc:'
                elif 'slidoc-options' in next_defaults:
                    replaceStr = 'slidoc-options'
                elif 'slidoc-defaults' in next_defaults:
                    replaceStr = 'slidoc-defaults'
                if replaceStr:
                    next_defaults = next_defaults.replace(replaceStr, replaceStr+' release_date=future')

        combine_slides = [pad_slide(rolloverText), nextText]
        splice_slides(combine_slides, 0)

        combineText = next_defaults + next_prefix + strip_slide( ''.join(combine_slides) )

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
            errMsg = self.uploadSession(uploadType, sessionNumber+1, sessionNext+'.md', combineText, fname2, fbody2, modify='overwrite', modimages='clear')
        except Exception, excp:
            if Options['debug']:
                import traceback
                traceback.print_exc()
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in rolling over session %s: %s' % (sessionName, excp))

        if errMsg:
            if self.previewState:
                self.discardPreview()
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Error in rolling over session '+sessionNext+': '+errMsg)

        self.previewState['rollover'] = rolloverParams
        self.previewState['modimages'] = 'clear'
        self.set_header('Content-Type', 'application/json')
        self.write( json.dumps( {'result': 'success'} ) )

            
SECTION_HEADER_RE = re.compile(r''' {0,3}(Slide:|#{1,2}[^#])''')
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
    user_delays = set()

    @tornado.web.authenticated
    @tornado.gen.coroutine
    def get(self, subpath=''):
        action, sep, subsubpath = subpath.partition('/')
        if not action.startswith('_user_'):
            raise tornado.web.HTTPError(403, log_message='CUSTOM:Invalid user action %s' % action)
        userId = self.get_id_from_cookie()
        cookieData = self.get_id_from_cookie(data=True) or {}
        admin_access = self.check_admin_access()
        if action == '_user_grades':
            if admin_access:
                if not subsubpath:
                    self.redirect(('/'+Options['site_name'] if Options['site_name'] else '') + '/_roster')
                    return
                userId = subsubpath
            rawHTML = self.get_argument('raw','')
            gradeVals = sdproxy.lookupGrades(userId, admin=admin_access)
            if not gradeVals:
                raise tornado.web.HTTPError(403, log_message='CUSTOM:Failed to access grades for user %s' % userId)
            gradebookStatus = ''
            if admin_access:
                gradebookStatus = gradeVals['status']
            sessionGrades = []
            for sessionName, vals in gradeVals['sessions']:
                sessionPath = getSessionPath(sessionName[1:]) if sessionName.startswith('_') else ''
                sessionGrades.append([sessionName, sessionPath, vals])
            self.render('gradebase.html' if rawHTML else 'grades.html', site_name=Options['site_name'], user_id=userId,
                        total_grade=gradeVals.get('total'), letter_grade=gradeVals.get('grade'), last_update=gradeVals['lastUpdate'],
                        session_grades=sessionGrades, gradebook_release=sdproxy.Settings['gradebook_release'],
                        gradebook_status=gradebookStatus)
            return

        elif action in ('_user_canceldelay',):
            if userId in self.user_delays:
                self.user_delays.discard(userId)
                print >> sys.stderr, 'UserActionHandler:blank DELAY cancel', userId
            return

        elif action in ('_user_blankimage',):
            delay = self.get_argument('delay','')
            cancel = self.get_argument('cancel','')
            if delay.isdigit():
                if cancel:
                    self.user_delays.add(userId)
                print >> sys.stderr, 'UserActionHandler:blank DELAY start', delay
                for delay_indx in range(int(delay)):
                    yield tornado.gen.sleep(1)
                    if cancel and userId not in self.user_delays:
                        break
                print >> sys.stderr, 'UserActionHandler:blank DELAY end'
                self.user_delays.discard(userId)
            self.set_header('Content-Type', 'image/gif')
            self.write(sliauth.blank_gif())
            return

        elif action == '_user_browse':
            if subsubpath != 'files' and not subsubpath.startswith('files/'):
                raise tornado.web.HTTPError(403)
            url_path = '_browse' if admin_access else '_user_browse'
            self.browse(url_path, subsubpath, site_admin=admin_access, download=self.get_argument('download', ''))
            return

        elif action in ('_user_discussclose',):
            self.user_discussclose(self.get_argument('session',''), self.get_argument('discussion',''), userId,
                                   reopen=self.get_argument('reopen',''), admin=admin_access)
            return

        elif action in ('_user_discuss',):
            self.discuss_stats(sdproxy.TESTUSER_ID if admin_access else userId)
            return

        elif action in ('_user_flag',):
            self.user_flag(self.get_argument('session',''), self.get_argument('discussion',''), self.get_argument('team',''),
                           self.get_argument('post',''), self.get_argument('posterid'), userId, self.get_argument('unflag',''),
                           admin=admin_access)
            return

        elif action in ('_user_message',):
            if not cookieData.get('batch'):
                raise tornado.web.HTTPError(403)
            sdproxy.notify_admin(sliauth.str_encode(self.get_argument('message','')), msgType='(from batch user %s)' % userId)
            self.displayMessage('Message received')
            return

        elif action in ('_user_plain',):
            self.revert_to_plain_user()
            self.displayMessage('Now logged in as a plain user')
            return

        elif action in ('_user_qstats',):
            self.qstats(subsubpath)
            return

        elif action in ('_user_status',):
            self.user_status(userId, admin=admin_access)
            return

        elif action in ('_user_twitterlink',):
            yield self.twitter_link(subsubpath)
            return

        elif action in ('_user_twitterverify',):
            yield self.twitter_verify(subsubpath)
            return

        raise tornado.web.HTTPError(404)

    def user_status(self, userId, admin=False):
        retval = {'result': 'success'}
        retval['previewingSession'] = ActionHandler.previewState.get('name', '')
        retval['interactiveSession'] = WSHandler.getInteractiveSession()[0]

        if admin:
            colNames = ['sessionWeight', 'releaseDate', 'dueDate', 'gradeDate', 'paceLevel', 'adminPaced', 'gradeWeight']
            sessionProperties = {}
            for sessionName, propList in sdproxy.lookupSessions(colNames):
                sessionProperties[sessionName] = {}
                for j, colName in enumerate(colNames):
                    sessionProperties[sessionName][colName] = propList[j]
            retval['sessionProperties'] = sessionProperties
        else:
            retval['sessionProperties'] = None

        self.set_header('Content-Type', 'application/json')
        self.write( json.dumps(retval, default=sliauth.json_default) )

    def user_discussclose(self, sessionName, discussNumStr, userId, reopen=False, admin=False):
        errMsg = ''
        if not admin:
            errMsg = 'Only admin user can close discussion'
        elif not discussNumStr.isdigit():
            errMsg = 'Invalid discussion number: '+discussNumStr
        else:
            try:
                sdproxy.closeDiscussion(sessionName, int(discussNumStr), reopen=reopen)
            except Exception, excp:
                if Options['debug']:
                    import traceback
                    traceback.print_exc()
                errMsg = 'Error in closing/reopening discussion'
                if admin:
                    errMsg += ': '+str(excp)

        if errMsg:
             retval = {'result': 'error', 'error': errMsg}
        else:
            retval = {'result': 'success'}

        self.set_header('Content-Type', 'application/json')
        self.write( json.dumps(retval, default=sliauth.json_default) )

    def user_flag(self, sessionName, discussNumStr, postTeam, postNumberStr, posterId, userId, unflag, admin=False):
        flaggerId = sdproxy.TESTUSER_ID if admin else userId
        errMsg = ''
        if unflag and not admin:
            errMsg = 'Only admin user can unflag'
        elif not discussNumStr.isdigit():
            errMsg = 'Invalid discussion number: '+discussNumStr
        elif not postNumberStr.isdigit():
            errMsg = 'Invalid post number: '+postNumberStr
        else:
            try:
                sdproxy.flagPost(sessionName, int(discussNumStr), postTeam, int(postNumberStr), posterId, flaggerId, unflag)
            except Exception, excp:
                if Options['debug']:
                    import traceback
                    traceback.print_exc()
                errMsg = 'Error in ' + ('unflagging' if unflag else 'flagging')
                if admin:
                    errMsg += ': '+str(excp)

        if errMsg:
             retval = {'result': 'error', 'error': errMsg}
        else:
            retval = {'result': 'success'}
            retval['discussPosts'] = sdproxy.getDiscussPosts(sessionName, int(discussNumStr), flaggerId, '')

        self.set_header('Content-Type', 'application/json')
        self.write( json.dumps(retval, default=sliauth.json_default) )

    def discuss_stats(self, userId):
        retval = {'result': 'success'}
        retval['discuss'] = discussStats(userId)

        self.set_header('Content-Type', 'application/json')
        self.write( json.dumps(retval) )

    def qstats(self, sessionName):
        json_return = self.get_argument('json', '')
        sheetName = sessionName + '_answers'
        sheet = sdproxy.getSheet(sheetName)
        if not sheet:
            if json_return:
                self.set_header('Content-Type', 'application/json')
                retval = {'result': 'error', 'error': 'Unable to retrieve question difficulty stats'}
                self.write( json.dumps(retval) )
            else:
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
            self.displayMessage(('<h3>%s: percentage of correct answers</h3>\n' % sessionName) + preElement('\n'+'\n'.join(lines)+'\n')+'\n')

    @tornado.gen.coroutine
    def twitter_link(self, twitterName):
        twitterName = twitterName.lower()
        userId = self.get_id_from_cookie()
        if Options['debug']:
            print >> sys.stderr, 'DEBUG: twitter_link:', twitterName, userId

        try:
            twitterVals = getColumns(sdproxy.TWITTER_HEADER, sdproxy.getSheet(sdproxy.ROSTER_SHEET))
            if twitterName in twitterVals:
                raise tornado.web.HTTPError(403, log_message='CUSTOM:Twitter name %s already linked' % twitterName)
        except tornado.web.HTTPError:
            raise
        except Exception, excp:
            pass

        retval = None
        try:
            import sdstream

            response = yield tornado.gen.Task(sdstream.twitter_task, Global.twitter_params, "getuserid", target_name=twitterName)
            retval = json.loads(response.body)
            twitter_id = retval[0]['id']
            retval = None

            response = yield tornado.gen.Task(sdstream.twitter_task, Global.twitter_params, "followers")
            retval = json.loads(response.body)
            followers = retval['ids']
            retval = None

            ##if Options['debug']:
            ##    print >> sys.stderr, 'DEBUG: twitter_link2:', twitter_id, followers

            if twitter_id not in followers:
                self.set_header('Content-Type', 'application/json')
                retval = {'result': 'error', 'error': '@%s should be following @%s for interaction' % (twitterName, Global.twitter_params['screen_name'])}
                self.write( json.dumps(retval) )
                return

            response = yield tornado.gen.Task(sdstream.twitter_task, Global.twitter_params, "friends")
            retval = json.loads(response.body)
            friends = retval['ids']
            retval = None

            ##if Options['debug']:
            ##    print >> sys.stderr, 'DEBUG: twitter_link3:', friends

            if twitter_id not in friends:
                response = yield tornado.gen.Task(sdstream.twitter_task, Global.twitter_params, "follow", target_name=twitterName)
                retval = json.loads(response.body)
                if twitterName != retval.get('screen_name'):
                    raise tornado.web.HTTPError(403, log_message='CUSTOM:Failed to follow @%s: %s' % (twitterName, retval.get('errors')) )
                retval = None

            verifyCode = str(random.randint(100001,999999))
            Global.twitterVerify[userId] = (twitterName, verifyCode)
            text = 'Your verification code is '+verifyCode
            if Options['site_name']:
                text += ' for site '+Options['site_name']
            response = yield tornado.gen.Task(sdstream.twitter_task, Global.twitter_params, "direct", target_name=twitterName,
                                              text=text)
            retval = json.loads(response.body)
            if retval.get('errors'):
                raise tornado.web.HTTPError(403, log_message='CUSTOM:Failed to send direct message to @%s: %s' % (twitterName, retval.get('errors')) )
            retval = None

        except tornado.web.HTTPError:
            raise
        except Exception, excp:
            if retval and retval.get('errors'):
                raise tornado.web.HTTPError(403, log_message='CUSTOM:Error in twitter setup for @%s: %s' % (twitterName, retval.get('errors')) )
            else:
                raise tornado.web.HTTPError(403, log_message='CUSTOM:Error in twitter setup for @%s: %s' % (twitterName, excp))

        self.set_header('Content-Type', 'application/json')
        retval = {'result': 'success'}
        self.write( json.dumps(retval) )

    @tornado.gen.coroutine
    def twitter_verify(self, verifyCode):
        userId = self.get_id_from_cookie()
        if Options['debug']:
            print >> sys.stderr, 'DEBUG: twitter_verify:', verifyCode, userId

        if userId not in Global.twitterVerify or Global.twitterVerify[userId][1] != verifyCode.strip():
            raise tornado.web.HTTPError(403, log_message='CUSTOM:Invalid or unknown twitter verification code for user '+userId)

        twitterName = Global.twitterVerify[userId][0]
        if Options['debug']:
            print >> sys.stderr, 'DEBUG: twitter_verify:', twitterName, userId

        message = ''
        try:
            retval = sdproxy.getUserRow(sdproxy.ROSTER_SHEET, userId, '', opts={'getheaders': '1'})
            if retval.get('values'):
                rosterHeaders = retval.get('headers')

                if sdproxy.TWITTER_HEADER not in rosterHeaders:
                    raise tornado.web.HTTPError(403, log_message='CUSTOM:No twitter column in roster')

                updateObj = {'id': userId, 'twitter': twitterName}
                retobj = sdproxy.updateUserRow(sdproxy.ROSTER_SHEET, rosterHeaders, updateObj, {})

                if retobj.get('result') != 'success':
                    raise tornado.web.HTTPError(403, log_message='CUSTOM:Error in twitter setup for @%s: %s' % (twitterName, retobj.get('error')) )

            elif Global.userRoles.is_known_user(userId):
                Global.twitterSpecial[twitterName] = userId
                message = 'User %s temporarily linked to @%s' % (userId, twitterName)

            else:
                raise tornado.web.HTTPError(403, log_message='CUSTOM:User %s not found in roster for site %s' % (userId, Options['site_name']))

            retval = None

        except tornado.web.HTTPError:
            raise
        except Exception, excp:
            if Options['debug']:
                import traceback
                traceback.print_exc()
            if retval and retval.get('errors'):
                raise tornado.web.HTTPError(403, log_message='CUSTOM:Error in twitter setup for @%s: %s' % (twitterName, retval.get('errors')) )
            else:
                raise tornado.web.HTTPError(403, log_message='CUSTOM:Error in twitter setup for @%s: %s' % (twitterName, excp))

        self.set_header('Content-Type', 'application/json')
        retval = {'result': 'success', 'message': message}
        self.write( json.dumps(retval) )

def modify_user_auth(args, socketId=None):
    # Re-create args.token for each site
    # Replace root-signed tokens with site-specific tokens
    # Note: Requires site server to have access to root key, for now
    if not Options['site_name'] or not args.get('token'):
        return

    if ':' in args['token']:
        effectiveId, adminId, role, sites, userToken = args['token'].split(':')
        siteAdminToken = effectiveId+gen_proxy_auth_token(adminId, role, prefixed=True)

        if args['token'] == siteAdminToken:
            # Token already site specific
            return

        if userToken != gen_proxy_auth_token(adminId, role=role, sites=sites, root=True):
            raise Exception('Invalid admin token: '+args['token'])

        if socketId and socketId != adminId:
            raise Exception('Token admin id mismatch: %s != %s' % (socketId, adminId))

        siteRole = ''
        if not role and sites and Options['site_name']:
            siteRole = sdproxy.getSiteRole(Options['site_name'], sites) or ''
        else:
            siteRole = role

        if not siteRole:
            if effectiveId == adminId and not args.get('admin'):
                # Allow non-admin access to site
                args['token'] = gen_proxy_auth_token(adminId)
                return
            raise Exception('Token disallowed by site for admin %s: %s' % (adminId, Options['site_name']))

        if siteRole in (sdproxy.ADMIN_ROLE, sdproxy.GRADER_ROLE):
            # Site admin token
            if role:
                args['token'] = siteAdminToken
            else:
                temSites = Options['site_name']
                if siteRole and temSites:
                    temSites += '+' + siteRole
                args['token'] = effectiveId+gen_proxy_auth_token(adminId, sites=temSites, prefixed=True)
        else:
            raise Exception('Invalid role %s for admin user %s' % (role, adminId))

    elif args.get('id'):
        userId = args['id']
        if socketId and socketId != userId:
            raise Exception('Token user id mismatch: %s != %s' % (socketId, userId))

        siteUserToken = gen_proxy_auth_token(userId)
        if args['token'] == siteUserToken:
            # Token already site specific
            return

        if args['token'] == gen_proxy_auth_token(userId, root=True):
            # Site user token
            args['token'] = siteUserToken
        else:
            raise Exception('Invalid token %s for user %s' % (args['token'], userId))

class ProxyHandler(BaseHandler):
    @tornado.gen.coroutine
    def get(self, subpath):
        yield self.handleResponse(subpath)

    @tornado.gen.coroutine
    def post(self, subpath):
        yield self.handleResponse(subpath)

    @tornado.gen.coroutine
    def handleResponse(self, subpath):
        dryProxy = (subpath == '_dryproxy')
        jsonPrefix = ''
        jsonSuffix = ''
        mimeType = 'application/json'
        if self.get_argument('prefix',''):
            jsonPrefix = self.get_argument('prefix','') + '(' + (self.get_argument('callback') or '0') + ', '
            jsonSuffix = ')'
            mimeType = 'application/javascript'

        args = {}
        for arg_name in self.request.arguments:
            if arg_name != 'prefix':
                args[arg_name] = self.get_argument(arg_name)

        ##if Options['debug']:
        ##    print >> sys.stderr, "DEBUG: ProxyHandler:", self.request.uri, dryProxy, 'sheet=', args.get('sheet'), args.keys(), args.get('actions'), args.get('modify')

        if dryProxy:
            # Already has site-specific tokens
            if not (args.get('proxy') and args.get('get') and args.get('all')):
                raise tornado.web.HTTPError(403, log_message='CUSTOM:Only proxy/get/all action allowed for _dryproxy')
        else:
            # Replace root-signed tokens with site-specific tokens
            try:
                modify_user_auth(args)
            except Exception, excp:
                if Options['debug']:
                    import traceback
                    traceback.print_exc()
                raise tornado.web.HTTPError(403, log_message='CUSTOM:Error in modify_user_auth')

        if (args.get('actions') and ',' not in args['actions'] and args['actions'] not in ('discuss_posts', 'answer_stats', 'correct')) and Options['gsheet_url']:
            # Handle action remotely
            # NOTE: No longer using proxy passthru for args.get('modify') (to allow revert preview)

            if Options['log_call']:
                args['logcall'] = str(Options['log_call'])
            sessionName = args.get('sheet','')

            errMsg = ''
            if args.get('actions'):
                if Options['dry_run']:
                    errMsg = 'Actions/modify not permitted in dry run'
                elif sdproxy.previewingSession():
                    errMsg = 'Actions/modify not permitted during session preview'

            if not errMsg and args.get('modify'):   ## passthru not used anymore
                if not sdproxy.startPassthru(sessionName):
                    errMsg = 'Failed to lock sheet '+sessionName+' for passthru. Try again after a few seconds?'

            if errMsg:
                retObj = {'result': 'error', 'error': errMsg}
            else:
                http_client = tornado.httpclient.AsyncHTTPClient()
                body = urllib.urlencode(args)
                response = yield http_client.fetch(Options['gsheet_url'], method='POST', headers=None, body=body, request_timeout=90)
                if response.error:
                    retObj = {'result': 'error', 'error': 'Error in passthru: '+str(response.error) }
                else:
                    # Successful return
                    if args.get('modify'):
                        sdproxy.endPassthru(sessionName)
                    try:
                        retObj = json.loads(response.body)
                    except Exception, err:
                        retObj = {'result': 'error', 'error': 'passthru: JSON parsing error: '+str(err) }

                    for sheetName in retObj.get('info',{}).get('refreshSheets',[]):
                        sdproxy.refreshSheet(sheetName)
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
    _interactiveSession = (None, None, None, None)
    _interactiveErrors = {}
    _sessionVersions = {}

    @classmethod
    def get_connections(cls, sessionName=''):
        # Return dict((user, connections_list)) if sessionName
        # else return list of tuples [ (path, user, connections) ]
        lst = []
        for path, path_dict in cls._connections.items():
            if sessionName:
                if cls.get_path_base(path, special=True) == sessionName:
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
        # Return (name of interactive session or '', question attributes)
        if cls._interactiveSession[2]:
            return (UserIdMixin.get_path_base(cls._interactiveSession[1]) or '', cls._interactiveSession[2], cls._interactiveSession[3])
        else:
            return ('', '', {})

    @classmethod
    def setupInteractive(cls, connection, path, action, slideId='', questionAttrs=None, rollbackOption=None):
        ##if Options['debug']:
        ##    print >> sys.stderr, 'sdserver.setupInteractive:', path, action, cls._interactiveSession

        interactiveSession = UserIdMixin.get_path_base(cls._interactiveSession[1]) if cls._interactiveSession[1] else ''
        basePath = UserIdMixin.get_path_base(path) if path else ''
        if action == 'start':
            if interactiveSession and interactiveSession != basePath:
                raise Exception('There is already an interactive session: '+interactiveSession)
            if not basePath:
                return
            cls._interactiveSession = (connection, path, slideId, questionAttrs)
            cls._interactiveErrors = {}
            if rollbackOption:
                sdproxy.startTransactSession(basePath)

        elif action in ('rollback', 'end'):
            if not interactiveSession:
                return
            cls._interactiveSession = (None, '', '', None)
            cls._interactiveErrors = {}
            if sdproxy.transactionalSession(interactiveSession):
                if action == 'rollback':
                    sdproxy.rollbackTransactSession(interactiveSession)
                else:
                    sdproxy.endTransactSession(interactiveSession)

    @classmethod
    def closeConnections(cls, path, userIdList, excludeId=None):
        # Note: closed connections may be automatically re-opened; use lockConnection to force reloads
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
            connection.write_message_safe(json.dumps([0, 'lock', [connection.locked, reload] ]))

    @classmethod
    def lockSessionConnections(cls, sessionName, lock_msg, reload=False):
        # Lock all socket connections for specified session (for uploads/modifications)
        # (Null string value for lock_msg unlocks)
        if Options['debug']:
            print >> sys.stderr, 'DEBUG: lockSessionConnections', sessionName, lock_msg, reload
        for userId, connections in cls.get_connections(sessionName).items():
            for connection in connections:
                connection.locked = lock_msg
                connection.write_message_safe(json.dumps([0, 'lock', [connection.locked, reload]] ))
        if Options['debug']:
            print >> sys.stderr, 'DEBUG: lockSessionConnections', 'DONE'

    @classmethod
    def lockAllConnections(cls, lock_msg, reload=False):
        for path, user, connections in  cls.get_connections():
            for connection in connections:
                connection.locked = lock_msg
                connection.write_message_safe(json.dumps([0, 'lock', [connection.locked, reload]] ))

    @classmethod
    def getSessionVersion(cls, sessionName, update=False):
        # TODO: Integrate this with separate session versioning in sessions_slidoc
        if not sessionName:
            return ''
        
        if not CommandOpts.session_versioning:
            return 'noversioning'

        if sessionName not in cls._sessionVersions:
            cls._sessionVersions[sessionName] = random.randint(100000,999999)*1000
        elif update:
            cls._sessionVersions[sessionName] += 1

        return str(cls._sessionVersions[sessionName])

    @classmethod
    def closeSessionConnections(cls, sessionName):
        # Close all socket connections for specified session
        for userId, connections in cls.get_connections(sessionName).items():
            for connection in connections:
                connection.close()

    @classmethod
    def processMessage(cls, fromUser, fromRole, fromName, message, allStatus=False, source='', accessCode=0, adminBroadcast=False):
        # Return null string on success or error message
        print >> sys.stderr, 'sdserver.processMessage:', sliauth.iso_date(nosubsec=True), fromUser, fromRole, fromName, message

        conn, path, slideId, questionAttrs = cls._interactiveSession
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
        if session_connections:
            for connId, connections in session_connections.items():
                if connections.sd_role == sdproxy.ADMIN_ROLE:
                    admin_found = connId
                    break

        if not admin_found:
            cls._interactiveSession = (None, None, None, None)
            msg = 'Message from '+fromUser+' discarded. No active controller for session '+sessionName
            if Options['debug']:
                print >> sys.stderr, 'sdserver.processMessage:', msg
            return msg if allStatus else ''

        if adminBroadcast and source in ('twitter', 'interact'):
            interactiveMsg = {'sender': fromUser, 'name': fromName, 'text': message}
            sessionPath = getSessionPath(sessionName, site_prefix=True)
            # Broadcast interactive message to admin users
            WSHandler.sendEvent(sessionPath[1:], '', sdproxy.ADMIN_ROLE, False, True, ['', -1, 'InteractiveMessage', [interactiveMsg]])

        # Close any active connections associated with user for interactive session
        for connection in session_connections.get(fromUser,[]):
            connection.close()

        create = source or 'message'
        opts = {'getheaders': '1', 'create': create}
        if accessCode:
            opts['access'] =  str(accessCode)
        retval = sdproxy.getUserRow(sessionName, fromUser, fromName, opts=opts)
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
        # Send answerNotify event to admin users
        cls.sendEvent(path, fromUser, sdproxy.ADMIN_ROLE, False, True, ['', 2, 'Share.answerNotify.%d' % sliauth.get_slide_number(slideId), [qnumber, cls._interactiveErrors]])
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
            for teamModifiedId in teamModifiedIds:
                cls.lockConnections(path, teamModifiedId, 'Team member responded. Reload page', reload=True)

        return ''
            
    @classmethod
    def sendEvent(cls, path, fromUser, fromRole, toNormal, toAdmin, args):
        # event_target: '' (default) OR 'userid1,userid2,...'
        # event_type = -1 immediate, 0 buffer, n >=1 (overwrite matching n name+args else buffer)
        # event_name = [plugin.]event_name[.slide_id]
        # if fromRole == sdproxy.ADMIN_ROLE, send message to all users (or to toUsers, if specified)
        # else send only to admin users (except for Discuss.activeNotify, which is sent to all users)
        # if toNormal, send to normal users (requires admin role for sender)
        # if toAdmin, always send to admin

        evTarget, evType, evName, evArgs = args

        toUsers = set(evTarget.split(',') if evTarget else [])

        ##if Options['debug'] and not evName.startswith('Timer.clockTick'):
        ##    print >> sys.stderr, 'sdserver.sendEvent: event', path, fromUser, fromRole, toNormal, toAdmin, toUsers, evType, evName
        pathConnections = cls._connections[path]
        for connId, connections in pathConnections.items():
            adminSender = fromRole == sdproxy.ADMIN_ROLE
            adminDestination = connections.sd_role == sdproxy.ADMIN_ROLE
            if fromUser and connId == fromUser:
                # Do not send to self
                continue
            elif toAdmin and adminDestination:
                # Always send to admin
                pass
            elif toUsers and connId not in toUsers:
                # Send only to specific users (if allowed below)
                continue
            elif adminSender:
                # Must explicitly send to normal users
                if not adminDestination and not toNormal:
                    continue
            else:
                # Normal sender (can only send activeNotify to other normal users)
                if not adminDestination and not evName.startswith('Discuss.activeNotify.'):
                    continue

            # Event [source, role, name, arg1, arg2, ...]
            sendList = [fromUser, fromRole, evName] + evArgs
            for conn in connections:
                if evType > 0:
                    # If evType > 0, only the latest occurrence of an event type with same evType name+arguments is buffered
                    buffered = False
                    for j in range(len(conn.eventBuffer)):
                        if conn.eventBuffer[j][2:evType+2] == sendList[2:evType+2]:
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

    @classmethod
    def teamNotify(cls, sessionName, teamIds, teamName):
        # Broadcast team setup event to team+admin users
        if Options['debug']:
            print >> sys.stderr, 'DEBUG: sdserver.teamNotify: ', sessionName, teamIds, teamName
        sessionPath = getSessionPath(sessionName, site_prefix=True)
        cls.sendEvent(sessionPath[1:], '', sdproxy.ADMIN_ROLE, True, True, [teamIds, -1, 'TeamSetup', [teamName]])

    @classmethod
    def postNotify(cls, sessionName, discussNum, closed, teamIds, teamName, postMsg, userId, userName, discussPost):
        # Broadcast postNotify event to team+admin users
        if Options['debug']:
            print >> sys.stderr, 'DEBUG: sdserver.postNotify: ', sessionName, discussNum, closed, teamIds, teamName, postMsg, userId, userName, discussPost[:40]
        sessionPath = getSessionPath(sessionName, site_prefix=True)

        cls.sendEvent(sessionPath[1:], userId, sdproxy.ADMIN_ROLE, True, True, [teamIds, -1, 'Discuss.postNotify', [discussNum, closed, postMsg, userName, teamName, discussPost]])

    def open(self, path=''):
        try:
            self.clientVersion = self.get_argument('version','')
            self.msgTime = time.time()
            self.locked = ''
            self.timeout = None
            self.userId = self.get_id_from_cookie()
            self.pathUser = (path, self.userId)
            self.sessionName = self.get_path_base(path) or ''
            self.sessionVersion = self.getSessionVersion(self.sessionName)
            self.userRole = self.get_id_from_cookie(role=True, for_site=Options['site_name'])
            joined = False
            activeUsers = None
            if self.sessionName:
                activeUserIds = []
                for connId, connections in WSHandler.get_connections(self.sessionName).items():
                    if connections.sd_role != sdproxy.ADMIN_ROLE:
                        activeUserIds.append(connId)
                if self.userId not in activeUserIds and self.userRole != sdproxy.ADMIN_ROLE:
                    joined = True
                    activeUserIds.append(self.userId)
                if joined or self.userRole == sdproxy.ADMIN_ROLE:
                    nameMap = sdproxy.getDisplayNames(includeNonRoster=True)
                    shortMap = sdproxy.makeShortNames(nameMap, first=True) if nameMap else {}
                    activeUsers = [ [nameMap.get(x,x), x, shortMap.get(x,x)] for x in activeUserIds]
                    activeUsers.sort()

            # Add connection
            connectionList = self._connections[self.pathUser[0]][self.pathUser[1]]
            if not connectionList:
                connectionList.sd_role = self.userRole
            connectionList.append(self)
            self.pluginInstances = {}
            self.awaitBinary = None

            ##if Options['debug']:
            ##    print >> sys.stderr, "DEBUG: WSopen", sliauth.iso_date(nosubsec=True), self.pathUser, self.clientVersion
            if not self.userId:
                self.close()

            self.eventBuffer = []
            self.eventFlusher = PeriodicCallback(self.flushEventBuffer, EVENT_BUFFER_SEC*1000)
            self.eventFlusher.start()

            interactSessionName, interactSlideId, _ = self.getInteractiveSession()
            if not self.sessionName or self.sessionName != interactSessionName:
                interactSlideId = ''

            dispAccessCode = Global.accessCodes.get(self.sessionName,'') if self.userRole == sdproxy.ADMIN_ROLE else ''

            sessionParams = {'dispAccessCode':dispAccessCode, 'interactSlideId':interactSlideId, 'noRoster': sdproxy.Settings['no_roster'] or '',
                             'activeUsers':activeUsers}

            sessionParams['nextSession'] = nextSession(self.sessionName)
            sessionParams['prevSession'] = nextSession(self.sessionName, back=True)
            self.write_message_safe(json.dumps([0, 'session_setup', [self.sessionVersion, sessionParams] ]))

            if joined and self.userRole != sdproxy.ADMIN_ROLE:
                WSHandler.sendEvent(self.pathUser[0], self.pathUser[1], sdproxy.ADMIN_ROLE, False, True, ['', -1, 'ActiveUsers', [self.pathUser[1], activeUsers]])
        except Exception, excp:
            if Options['debug']:
                import traceback
                traceback.print_exc()

    def on_close(self):
        ##if Options['debug']:
        ##    print >> sys.stderr, "DEBUG: WSon_close", getattr(self, 'pathUser', 'NOT OPENED')
        try:
            if self.eventFlusher:
                self.eventFlusher.stop()
                self.eventFlusher = None
            self._connections[self.pathUser[0]][self.pathUser[1]].remove(self)
            if not self._connections[self.pathUser[0]][self.pathUser[1]]:
                del self._connections[self.pathUser[0]][self.pathUser[1]]
            if not self._connections[self.pathUser[0]]:
                del self._connections[self.pathUser[0]]

            if self._interactiveSession[0] is self:
                # Disable interactivity associated with this connection
                self._interactiveSession = (None, None, None, None)

            if self.sessionName:
                if self.pathUser[1] not in WSHandler.get_connections(self.sessionName):
                    # Notify that user has disconnected
                    WSHandler.sendEvent(self.pathUser[0], self.pathUser[1], sdproxy.ADMIN_ROLE, False, True, ['', -1, 'ActiveUsers', [self.pathUser[1], None]])

        except Exception, err:
            pass

    def write_message_safe(self, msg):
        try:
            self.write_message(msg)
        except Exception, excp:
            if Options['debug']:
                print >> sys.stderr, 'DEBUG: write_message_safe: Error in write_message', self.pathUser, self.locked, str(excp)

    def flushEventBuffer(self):
        while self.eventBuffer:
            # sendEvent: source, role, evName, evArg1, ...
            sendList = self.eventBuffer.pop(0)
            # Message: source, role, evName, [args]
            msg = [0, 'event', [sendList[0], sendList[1], sendList[2], sendList[3:]] ]
            self.write_message_safe(json.dumps(msg, default=sliauth.json_default))

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
                pluginPath = self.pathUser[0]
                if Options['site_name']:
                    pluginPath = '/'.join( pluginPath.split('/')[1:] )
                if pluginPath.startswith(PRIVATE_PATH+'/'):
                    pluginPath = '/'.join( pluginPath.split('/')[1:] )
                self.pluginInstances[pluginName] = pluginClass(PluginManager.getManager(pluginName), pluginPath, self.pathUser[1], self.userRole)
            except Exception, err:
                raise Exception('Error in creating instance of plugin '+pluginName+': '+err.message)

        pluginMethod = getattr(self.pluginInstances[pluginName], pluginMethodName, None)
        if not pluginMethod:
            raise Exception('Plugin '+pluginName+' has no method '+pluginMethodName)
        return pluginMethod

    def on_message(self, message):
        outMsg = self.on_message_aux(message)
        if outMsg:
            self.write_message_safe(outMsg)
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
            if obj[0] and obj[0] != self.sessionVersion:
                self.write_message_safe(json.dumps([0, 'close', ['Outdated version of session: %s vs %s' % (obj[0], self.sessionVersion), 'Outdated version of session. Reload page'] ]))
                return

            callback_index = obj[1]
            method = obj[2]
            args = obj[3]

            retObj = {"result":"success"}
            ##if Options['debug']:
            ##    print >> sys.stderr, 'sdserver.on_message_aux', method, len(args)

            ALLOWED_USER_METHODS = set(['close', 'discuss_stats', 'event', 'plugin', 'proxy', 'switch_session'])
            if self.userRole != sdproxy.ADMIN_ROLE:
                if method not in ALLOWED_USER_METHODS:
                    raise Exception('User %s not allowed to access WS method %s for session %s' % (self.pathUser[1], method, self.sessionName))
            
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
                    for teamModifiedId in teamModifiedIds:
                        if teamModifiedId != self.userId:
                            self.lockConnections(self.pathUser[0], teamModifiedId, 'Redundant team connection')

            elif method == 'discuss_stats':
                retObj['discuss'] = discussStats(sdproxy.TESTUSER_ID if self.userRole == sdproxy.ADMIN_ROLE else self.pathUser[1])

            elif method == 'switch_session':
                # Args: sessionName, backward
                retObj['switchSession'] = nextSession(args[0], args[1])

            elif method == 'generate_team':
                # Args: questionNum, params
                if self.userRole == sdproxy.ADMIN_ROLE:
                    sdproxy.generateTeam(self.sessionName, args[0], args[1])
                    teamStatus = sdproxy.getTeamStatus(self.sessionName)
                    if teamStatus and len(teamStatus):
                        retObj['teamStatus'] = teamStatus

            elif method == 'get_seeds':
                # Args: questionNum, discussNum
                if self.userRole == sdproxy.ADMIN_ROLE:
                    retObj.update( sdproxy.getDiscussionSeed(self.sessionName, args[0], args[1]) )

            elif method == 'interact':
                # args: action, slideId, questionAttrs, rollbackOption
                if self.userRole == sdproxy.ADMIN_ROLE:
                    self.setupInteractive(self, self.pathUser[0], args[0], args[1], args[2], args[3])

            elif method == 'rollback':
                # args:
                if self.userRole == sdproxy.ADMIN_ROLE:
                    # Rollback interactive session to the slide of the last answered question (or start slide)
                    WSHandler.setupInteractive(None, '', 'rollback', '', None, '')
                    # Close all session websockets (forcing reload)
                    IOLoop.current().add_callback(WSHandler.lockSessionConnections, self.sessionName, 'Last question rolled back. Reload page', True)

            elif method == 'reset_question':
                # args: qno, userid 
                if self.userRole == sdproxy.ADMIN_ROLE:
                    # Do not accept interactive responses
                    WSHandler.setupInteractive(None, '', 'end', '', None, '')
                    sdproxy.clearQuestionResponses(self.sessionName, args[0], args[1])
                    # Close all session websockets (forcing reload)
                    IOLoop.current().add_callback(WSHandler.lockSessionConnections, self.sessionName, 'Question reset. Reload page', True)

            elif method == 'plugin':
                if len(args) < 2:
                    raise Exception('Too few arguments to invoke plugin method: '+' '.join(args))
                pluginName, pluginMethodName = args[:2]
                pluginMethod = self.getPluginMethod(pluginName, pluginMethodName)

                params = {'pastDue': ''}
                userId = self.pathUser[1]
                if self.sessionName and sdproxy.getSheet(sdproxy.INDEX_SHEET):
                    sessionEntries = sdproxy.lookupValues(self.sessionName, ['dueDate'], sdproxy.INDEX_SHEET)
                    if sessionEntries['dueDate']:
                        # Check if past due date
                        effectiveDueDate = sessionEntries['dueDate']
                        try:
                            userEntries = sdproxy.lookupValues(userId, ['lateToken'], self.sessionName)
                            if userEntries['lateToken'] and userEntries['lateToken'] not in (LATE_SUBMIT,PARTIAL_SUBMIT):
                                # late/partial; use late submission option
                                effectiveDueDate = userEntries['lateToken'][:17]
                        except Exception, excp:
                            ##print >> sys.stderr, 'sdserver.on_message_aux: plugin '+pluginName+'.'+pluginMethodName, str(excp)
                            pass
                        if effectiveDueDate and sliauth.epoch_ms() > sliauth.epoch_ms(effectiveDueDate):
                            params['pastDue'] = sliauth.iso_date(effectiveDueDate)
                
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
                    if Options['dry_run'] and not Options['dry_run_file_modify']:
                        raise Exception('Cannot upload files during dry run without file modify option')

                try:
                    retObj = pluginMethod(*([params] + args[2:]))
                except Exception, err:
                    if Options['debug']:
                        import traceback
                        traceback.print_exc()
                    raise Exception('Error in calling method '+pluginMethodName+' of plugin '+pluginName+': '+err.message)

            elif method == 'event':
                # args: evTarget, evType, evName, evArgs
                # Broadcast event to all if from admin, else send to admins only
                self.sendEvent(self.pathUser[0], self.pathUser[1], self.userRole, True, True, args)

            else:
                raise Exception('User %s accessing invalid WS method %s for session %s' % (self.pathUser[1], method, self.sessionName))

            if callback_index:
                return json.dumps([callback_index, '', retObj], default=sliauth.json_default)
        except Exception, err:
            if Options['debug']:
                import traceback
                traceback.print_exc()
                ##raise Exception('Error in response: '+err.message)
            if callback_index:
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
    def getFileKey(cls, filepath, salt='', custom_key=''):
        today = str(datetime.date.today())
        filename = os.path.basename(filepath)
        if not salt:
            salt = today + '-' + uuid.uuid4().hex[:8]
            if custom_key:
                salt = custom_key + '-' + salt
        if salt.startswith('s-') or salt.startswith('su-'):
            # Session-user key
            fhead = os.path.splitext(filename)[0]
            if '--' in fhead:
                sep = '--'
            else:
                sep = '-'   # For legacy compatibility only

            fprefix, _, uname = fhead.rpartition(sep)
            sname, _, _ = fprefix.partition(sep)
            if salt.startswith('s-'):
                hmac_key = sliauth.gen_file_key(Options['auth_key'], sname, '')
            else:
                hmac_key = sliauth.gen_file_key(Options['auth_key'], sname, uname, timestamp=today)
        else:
            hmac_key = Options['auth_key']
        subkey = sliauth.gen_hmac_token(hmac_key, salt+':'+filename)
        return sliauth.safe_quote(salt+':'+subkey)

    @classmethod
    def validFileKey(cls, filepath, key):
        today = str(datetime.date.today())
        if ':' not in key and '%' in key:
            key = sliauth.safe_unquote(key)
        salt, _, subkey = key.partition(':')
        if sliauth.safe_quote(key) == cls.getFileKey(filepath, salt=salt):
            return True
        if salt.startswith('su-') and not salt.startswith('su-'+today):
            # Key may not be current
            return None
        return False

    @classmethod
    def adminRole(cls, userRole, alsoGrader=False):
        if userRole == sdproxy.GRADER_ROLE and alsoGrader:
            return True
        return userRole == sdproxy.ADMIN_ROLE

    def __init__(self, pluginName):
        self.pluginName = pluginName

    def makePath(self, filepath, restricted=True, private=True, relpath=False):
        # If relpath, return '/...' for use in URL, else return full path relative to run directory
        if not Options['plugindata_dir']:
            raise Exception('sdserver.PluginManager.makePath: ERROR No plugin data directory!')
        if '..' in filepath:
            raise Exception('sdserver.PluginManager.makePath: ERROR Invalid .. in file path: '+filepath)
            
        dataPath = filepath
        if restricted:
            dataPath = os.path.join(RESTRICTED_PATH, dataPath)
        elif private:
            dataPath = os.path.join(PRIVATE_PATH, dataPath)

        if relpath:
            dataPath = '/'+dataPath
        else:
            dataPath = os.path.join(PLUGINDATA_PATH, self.pluginName, dataPath)
            if Options['site_name']:
                dataPath = os.path.join(Options['site_name'], dataPath)
            dataPath = os.path.join(Options['plugindata_dir'], dataPath)

        return dataPath
    
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
            fpaths = [os.path.join(fullpath, f) for f in sorted(os.listdir(fullpath)) if os.path.isfile(os.path.join(fullpath, f))]
            return [ [fpath, fpath[len(Options['plugindata_dir']):]] for fpath in fpaths]
        except Exception, err:
            raise Exception('sdserver.PluginManager.dirFiles: ERROR in directory listing %s: %s' % (fullpath, err))

    def writeFile(self, filepath, content, restricted=True, private=True):
        # Returns relative file URL
        fullpath = self.makePath(filepath, restricted=restricted, private=private)
        relpath = self.makePath(filepath, restricted=restricted, private=private, relpath=True)
        try:
            filedir = os.path.dirname(fullpath)
            if not os.path.exists(filedir):
                os.makedirs(filedir)
            with open(fullpath, 'w') as f:
                f.write(content)
            return relpath
        except Exception, err:
            raise Exception('sdserver.PluginManager.writeFile: ERROR in writing file %s: %s' % (fullpath, err))

class CachedStaticFileHandler(tornado.web.StaticFileHandler):
    def set_extra_headers(self, path):
        # Cacheable static files (no site cookies are set)
        self.set_header('Server', SERVER_NAME)
        self.set_header('Cache-Control', 'public, max-age=900')
    
class UncachedStaticFileHandler(tornado.web.StaticFileHandler):
    def set_extra_headers(self, path):
        # Force validation of cache (no site cookies are set)
        self.set_header('Server', SERVER_NAME)
        self.set_header('Cache-Control', 'no-cache, must-revalidate, max-age=0')

class SiteStaticFileHandler(UncachedStaticFileHandler, SiteMixin):
    def set_extra_headers(self, path):
        super(SiteStaticFileHandler, self).set_extra_headers(path)
        # Set site cookies
        cookieStr = self.site_cookie_data()
        if self.get_site_cookie() != cookieStr:
            self.set_site_cookie(cookieStr)
    
    def write_error(self, status_code, **kwargs):
        err_cls, err, traceback = kwargs['exc_info']
        if getattr(err, 'log_message', None) and err.log_message.startswith('CUSTOM:'):
            self.write('<html><body><h3>%s</h3></body></html>' % err.log_message[len('CUSTOM:'):])
        else:
            super(SiteStaticFileHandler, self).write_error(status_code, **kwargs)

class AuthStaticFileHandler(SiteStaticFileHandler, UserIdMixin):
    def get_current_user(self):
        # Return None only to request login; else raise HTTPError do deny access (to avoid looping)
        sessionName = self.get_path_base(self.request.path, handle_image=True)
        filename = self.get_path_base(self.request.path, special=True)

        if self.request.path.endswith('.md'):
            # Failsafe - no direct web access to *.md files
            raise tornado.web.HTTPError(404)

        userId = self.get_id_from_cookie() or None
        cookieData = self.get_id_from_cookie(data=True) or {}
        batchMode = cookieData.get('batch')
        if batchMode:
            if Options['site_name'] and batchMode != Options['site_name']:
                raise tornado.web.HTTPError(404)
            siteRole = None
        else:
            siteRole = self.get_id_from_cookie(role=True, for_site=Options['site_name'])  # May be None

        lockedAccess = False
        if cookieData.get('locked_access'):
            if cookieData['locked_access'] == '/'+Options['site_name']:
                # Allow locked site access
                pass
            else:
                expectSession = os.path.splitext(cookieData['locked_access'].split('/')[-1])[0]
                if ('/'+RESTRICTED_PATH) in self.request.path and (filename.startswith(expectSession+'-') or siteRole == sdproxy.ADMIN_ROLE):
                    # Restricted content for locked session
                    pass
                elif sessionName and cookieData['locked_access'] == getSessionPath(sessionName, site_prefix=True):
                    # Allow locked session access
                    lockedAccess = True
                else:
                    raise tornado.web.HTTPError(404, log_message='CUSTOM:Restricted access to %s only' % cookieData['locked_access'])
        elif self.is_web_view():
            raise tornado.web.HTTPError(404, log_message='CUSTOM:Restricted access to locked sessions only')

        if DEBUG_PATH_RE and DEBUG_PATH_RE.search(self.request.path):
            print >> sys.stderr, "AuthStaticFileHandler.get_current_user", userId, repr(siteRole), Options['site_number'], sessionName, self.request.path, self.request.query, Options['dry_run'], Options['dry_run_file_modify'], Options['lock_proxy_url']

        if ActionHandler.previewState.get('name'):
            if sessionName and sessionName.startswith(ActionHandler.previewState['name']):
                if siteRole == sdproxy.ADMIN_ROLE:
                    preview_url = '/_preview/index.html'
                    if Options['site_name']:
                        preview_url = '/' + Options['site_name'] + preview_url
                    raise tornado.web.HTTPError(404, log_message='CUSTOM:Click <a href="%s">here</a> to preview session %s' % (preview_url, ActionHandler.previewState['name']))
                else:
                    raise tornado.web.HTTPError(404, log_message='CUSTOM:Session not currently accessible')

        if self.request.path.startswith('/'+ADMIN_PATH):
            # Admin path accessible only to dry_run (preview) or wet run using proxy_url
            if not Options['dry_run'] and not Options['lock_proxy_url']:
                raise tornado.web.HTTPError(404)

        denyStr = restricted_user_access(Options['start_date'], Options['end_date'], siteRole, sdproxy.Settings['site_access'],
                                         batch_mode=batchMode)
        if ('/'+RESTRICTED_PATH) in self.request.path:
            # For paths containing '/_restricted', all filenames must end with *-userId[.extn] to be accessible by userId
            path = self.request.path
            query = self.request.query
            if getattr(self,'abs_query',''):
                path, _, tail = path.partition('%3F')
                query = getattr(self,'abs_query','')

            if userId and siteRole == sdproxy.ADMIN_ROLE:
                return userId

            if not denyStr and userId and filename.endswith('--'+userId):
                return userId

            valid = PluginManager.validFileKey(path, query)
            if valid:
                return "noauth"
            elif valid is None:
                tornado.web.HTTPError(404, log_message='CUSTOM:Invalid/expired file access key; reloading page may help')
            elif not userId:
                return None
            raise tornado.web.HTTPError(404)

        if denyStr:
            if not userId:
                # Force login
                return None

            raise tornado.web.HTTPError(404, log_message='CUSTOM:<b>Site %s not accessible (%s)<br><a href="/_logout">Logout</a><b>' % (Options['site_name'], denyStr))

        if ('/'+PRIVATE_PATH) in self.request.path:
            # Paths containing '/'+PRIVATE_PATH are always protected and used for session-related content
            if not userId:
                return None

            if sessionName and sessionName != 'index':
                # Session access checks (for files with /_files in path, sessionName will be None)
                gradeDate = None
                releaseDate = None
                sessionType, _ = getSessionType(sessionName)
                if SiteProps.paced_session(sessionType):
                    indexSheet = sdproxy.getSheet(sdproxy.INDEX_SHEET)
                    if not indexSheet:
                        raise tornado.web.HTTPError(404, log_message='CUSTOM:No index sheet for paced session '+sessionName)
                    try:
                        sessionEntries = sdproxy.lookupValues(sessionName, ['paceLevel', 'dueDate', 'gradeDate', 'releaseDate', 'attributes'], sdproxy.INDEX_SHEET)
                        paceLevel = sessionEntries['paceLevel']
                        dueDate = sessionEntries.get('dueDate','')
                        gradeDate = sessionEntries['gradeDate']
                        releaseDate = sessionEntries['releaseDate']
                        sessionAttributes = json.loads(sessionEntries['attributes'])
                        accessCode = sessionAttributes['params'].get('accessCode')
                            
                    except Exception, excp:
                        excpMsg = str(excp)
                        print >> sys.stderr, "AuthStaticFileHandler.get_current_user: ERROR", excpMsg
                        if ':SUSPENDED:' in excpMsg and sdproxy.Global.suspended == 'version_mismatch':
                            raise tornado.web.HTTPError(404, log_message='CUSTOM:Proxy version mismatch for site %s' % Options['site_name'])
                        else:
                            raise tornado.web.HTTPError(404, log_message='CUSTOM:Session %s unavailable' % sessionName)

                    updateAccessCode(sessionName, paceLevel, dueDate, accessCode)

                if Options['start_date']:
                    startDateMS = sliauth.epoch_ms(sliauth.parse_date(Options['start_date']))
                    if isinstance(releaseDate, datetime.datetime) and sliauth.epoch_ms(releaseDate) < startDateMS:
                        raise tornado.web.HTTPError(404, log_message='CUSTOM:release_date %s must be after start_date %s for session %s' % (releaseDate, Options['start_date'], sessionName) )
                    elif gradeDate and sliauth.epoch_ms(gradeDate) < startDateMS:
                        raise tornado.web.HTTPError(404, log_message='CUSTOM:grade date %s must be after start_date %s for session %s' % (gradeDate, Options['start_date'], sessionName) )

                if siteRole != sdproxy.ADMIN_ROLE and not batchMode:
                    # Non-admin access
                    # (Admin has access regardless of release date, allowing delayed release of live lectures and exams)
                    if lockedAccess:
                        return userId
                    elif isinstance(releaseDate, datetime.datetime):
                        # Check release date for session
                        if sliauth.epoch_ms() < sliauth.epoch_ms(sessionEntries['releaseDate']):
                            raise tornado.web.HTTPError(404, log_message='CUSTOM:Session %s not yet available' % sessionName)
                    elif releaseDate:
                        # Future release date
                        raise tornado.web.HTTPError(404, log_message='CUSTOM:Session %s unavailable' % sessionName)

                    if SiteProps.restricted_session(sessionType):
                        # Failsafe check to prevent premature release of restricted exams etc.
                        if Options['start_date'] and releaseDate:
                            # Valid start_date and release_date must be specified to access restricted session
                            pass
                        else:
                            raise tornado.web.HTTPError(404, log_message='CUSTOM:Restricted session '+sessionName+' not yet released')
                            
            if not batchMode:
                self.check_site_access()  # For _private files
            return userId

        # Not restricted or private files
        if Options['public_pages'] or Options['auth_type'] == 'none':
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

    
class UnauthMessageHandler(BaseHandler):
    def post(self):
        temUser = self.get_argument('username', '')
        dispName = self.get_argument('dispname', '')
        accessToken = self.get_argument('token', '')
        print >> sys.stderr, "UnauthMessageHandler.post", temUser

        comps = accessToken.split(':')
        if len(comps) != 3:
            raise Exception('Invalid access token for user '+temUser)
        temSiteName, sessionName, _ = comps
        if not self.check_locked_token(temUser, accessToken, temSiteName, sessionName):
            raise Exception('Invalid access token for user '+temUser)
        userId = temUser
        userRole = ''
        choice = self.get_argument('choice', '')
        number = self.get_argument('number', '')
        message = self.get_argument('message', '')
        source = self.get_argument('source', 'interact')
        if choice:
            message = choice + ' ' + message
        elif number:
            message = number + ' ' + message

        status = WSHandler.processMessage(userId, userRole, dispName or userId, message, allStatus=True, source=source, adminBroadcast=True)
        if not status:
            status = 'Accepted answer: '+message

        self.set_header('Content-Type', 'application/json')
        self.write( json.dumps( {'result': 'success', 'status': status} ) )


class AuthMessageHandler(BaseHandler):
    @tornado.web.authenticated
    def get(self, subpath=''):
        status = self.get_argument('status', '')
        inputCode = self.get_argument('access', '').strip()
        sessionName, slideId, questionAttrs = WSHandler.getInteractiveSession()
        requireCode = Global.accessCodes.get(sessionName) or ''
        if requireCode:
            if not inputCode:
                inputCode = 'Enter code'
        else:
            inputCode = ''
        label = 'User %s: %s' % (self.get_id_from_cookie(), sessionName or 'No interactive session')
        self.render("send.html", status=status, access=inputCode,
                    site_name=Options['site_name'], site_label=Options['site_label'], session_label=label,
                    session_name=sessionName, qnumber=questionAttrs.get('qnumber',0),  qtype=questionAttrs.get('qtype',''),
                    choices=questionAttrs.get('choices',0), explain=bool(questionAttrs.get('explain')))

    @tornado.web.authenticated
    def post(self, subpath=''):
        sessionName, slideId, questionAttrs = WSHandler.getInteractiveSession()
        qnumberStr = self.get_argument('qnumber', '')
        inputCode = self.get_argument('access', '').strip()
        requireCode = Global.accessCodes.get(sessionName) or ''
        if not sessionName:
            status = 'Error: No interactive session'
        elif qnumberStr != str(questionAttrs.get('qnumber',0)):
            status = 'Error: Discarded answer for inactive Question %s; re-submit answer' % qnumberStr
        elif requireCode and (not inputCode.isdigit() or int(inputCode) != requireCode):
            status = 'Error: Invalid access code '+inputCode
        else:
            try:
                userRole = self.get_id_from_cookie(role=True, for_site=Options['site_name'])
                choice = self.get_argument('choice', '')
                number = self.get_argument('number', '')
                message = self.get_argument('message', '')
                if choice:
                    message = choice + ' ' + message
                elif number:
                    message = number + ' ' + message
                displayName = self.get_id_from_cookie(name=True)
                userId = self.get_id_from_cookie()
                if displayName:
                    sdproxy.mapDisplayName(userId, displayName)
                status = WSHandler.processMessage(userId, userRole, displayName, message, allStatus=True, source='interact', accessCode=requireCode, adminBroadcast=True)
                if not status:
                    status = 'Accepted answer: '+message
            except Exception, excp:
                if Options['debug']:
                    import traceback
                    traceback.print_exc()
                    status = 'Error in processing message: '+str(excp)
                    print >> sys.stderr, "AuthMessageHandler.post", status
                else:
                    status = 'Error in processing message'
        site_prefix = '/'+Options['site_name'] if Options['site_name'] else ''
        self.redirect(site_prefix+'/send/?access='+sliauth.safe_quote(inputCode)+'&status='+sliauth.safe_quote(status))


class AuthLoginHandler(BaseHandler):
    # Token-based login
    def get(self):
        error_msg = self.get_argument('error', '')
        username = str(self.get_argument('username', ''))
        token = str(self.get_argument('token', ''))
        usertoken = str(self.get_argument('usertoken', ''))
        device_id = str(self.get_argument('deviceid', ''))
        next = self.get_argument('next', '/')
        if not error_msg and ':' in usertoken:
            username, _, token = usertoken.partition(':')
        
        locked_access_link = None
        if self.is_web_view():
            cookieData = self.get_id_from_cookie(data=True) or {}
            locked_access_link = cookieData.get('locked_access', '')

        if Options['debug']:
            print >> sys.stderr, "AuthLoginHandler.get", username, token, usertoken, next, 'devid='+device_id, error_msg

        no_auth_user = Options['auth_type'] == 'adminonly' and username not in (sdproxy.ADMIN_ROLE, sdproxy.GRADER_ROLE)
        if not error_msg and username and (token or no_auth_user):
            self.login(username, token, next=next)
        else:
            self.render("login.html", error_msg=error_msg, next=next, login_label='Slidoc',
                        login_url='/_auth/login/', locked_access_link=locked_access_link,
                        username=username, password_label='' if no_auth_user else 'Token:')

    def post(self):
        username = str(self.get_argument('username', ''))
        token = str(self.get_argument('token', ''))
        next = self.get_argument('next', '/')
        if not username or (not token and username in (sdproxy.ADMIN_ROLE, sdproxy.GRADER_ROLE)):
            self.render("login.html", error_msg='', next=next, login_label='Slidoc',
                        login_url='/_auth/login/', locked_access_link=None,
                        username=username, password_label='Auth key:' if username else 'Token:')
        else:
            self.login(username, token, next=next)

    def login(self, username, token, next="/"):
        generateToken = False
        if token == Options['auth_key'] and Options['auth_type'] in ('none', 'adminonly', 'token'):
            # Auth_key token option for admin user
            generateToken = True

        role = ''
        if username == sdproxy.ADMIN_ROLE:
            role = sdproxy.ADMIN_ROLE
        elif username == sdproxy.GRADER_ROLE:
            role = sdproxy.GRADER_ROLE
        elif Options['auth_type'] == 'adminonly':
            # Allow no-password access for normal user
            generateToken = True

        if generateToken:
            token = gen_proxy_auth_token(username, role=role)

        data = {}
        comps = token.split(':')
        if not role and (self.is_web_view() or len(comps) > 1):
            # Locked access
            if len(comps) != 3:
                self.redirect('/_auth/login/' + '?error=' + tornado.escape.url_escape('Invalid locked access token. Expecting site:session:code'))
                return
            siteName, sessionName, _ = comps
            if not sessionName:
                # Locked site access
                next = '/' + siteName
            else:
                # Locked session access
                next = getSessionPath(sessionName)
                if siteName:                         # Add site prefix separately because this is root site
                    next = '/' + siteName + next
            data['locked_access'] = next
            auth = self.check_locked_token(username, token, siteName, sessionName)
        else:
            auth = self.check_access_token(username, token, role=role)

        if auth:
            if Global.twitter_params:
                data['site_twitter'] = Global.twitter_params['site_twitter']
            self.set_id(username, data=data, role=role)
            self.redirect(next)
        else:
            error_msg = "?error=" + tornado.escape.url_escape("Incorrect username or token")
            self.redirect("/_auth/login/" + error_msg)

            
class AuthLogoutHandler(BaseHandler):
    def get(self):
        self.clear_user_cookie()
        self.render('logout.html')

class GoogleLoginHandler(tornado.web.RequestHandler,
                         tornado.auth.GoogleOAuth2Mixin, UserIdMixin):
    def set_default_headers(self):
        # Completely disable cache
        self.set_header('Server', SERVER_NAME)

    @tornado.gen.coroutine
    def get(self):
        if self.is_web_view():
            # For embedded browsers ("web views"), Google login does not work; use token authentication
            self.redirect('/_auth/login/')
            return

        if self.get_argument('code', False):
            user = yield self.get_authenticated_user(
                redirect_uri=self.settings['google_oauth']['redirect_uri'],
                code=self.get_argument('code'))

            if Options['debug']:
                print >> sys.stderr, 'GoogleAuth: step 1', sliauth.iso_date(nosubsec=True), user.get('token_type'), 'state=', self.get_argument('state', '')

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

            orig_email = user['email'].lower()
            username = orig_email
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

            if displayName:
                sdproxy.mapDisplayName(username, displayName)
            else:
                displayName = username
            
            role, sites = Global.userRoles.id_role_sites(username)
            userId = username
            if not role and not sites and Global.email2id is not None:
                # Map email to id for users with no roles
                siteRoles = []
                tem_email = username if '@' in username else orig_email
                idValsDict = Global.email2id.get(tem_email)
                if not idValsDict:
                    self.custom_error(500, 'Email %s not found in any site rosters. Please register it.' % tem_email)
                    return

                if len(idValsDict) == 1:
                    userId = idValsDict.keys()[0]
                    sites = ','.join( idValsDict[userId] )
                else:
                    state = self.get_argument('state', '/')
                    match = re.search(r'\?seluser=([\w-]+)$', state)
                    temId = urllib.unquote_plus(match.group(1)) if match else ''
                    if temId in idValsDict:
                        userId = temId
                        sites = ','.join( idValsDict[userId] )
                    else:
                        html = '<h3>Select user for Slidoc sites:<h3> ' + ''.join([ '''<b><a href="%s?seluser=%s">%s</a></b><p></p> ''' % (Global.login_url, urllib.quote_plus(x), x) for x in sorted(idValsDict.keys()) ])
                        self.custom_error(500, html, clear_cookies=True)
                        return

            if sdproxy.isSpecialUser(userId) and not displayName.startswith('#'):
                displayName = '#' + displayName

            # Set cookie
            data = {}
            if Global.twitter_params:
                data['site_twitter'] = Global.twitter_params['site_twitter']
            self.set_id(userId, displayName=displayName, role=role, sites=sites, email=orig_email, data=data)
            self.redirect(self.get_argument('state', '') or self.get_argument('next', '/'))
            return

            # Save the user with e.g. set_secure_cookie
        else:
            nextPath = self.get_argument('next', '/')
            seluser = self.get_argument('seluser', '')
            if seluser:
                nextPath = '/?seluser=' + urllib.quote_plus(seluser)
            yield self.authorize_redirect(
                redirect_uri=self.settings['google_oauth']['redirect_uri'],
                client_id=self.settings['google_oauth']['key'],
                scope=['profile', 'email'],
                response_type='code',
                extra_params={'approval_prompt': 'auto', 'state': nextPath})

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
            self.redirect('https:'+self.request.full_url()[len("http:"):], permanent=False)

    def get(self):
        self.write("Hello, world")

def createApplication():
    pathPrefix = '/'+Options['site_name'] if Options['site_number'] else ''
        
    home_handlers = [
                     (pathPrefix+r"/", HomeHandler)
                     ]
    if not Options['site_number']:
        # Single/root server
        home_handlers += [ (r"/(_(backup|deactivate|logout|reload|renewssl|setup|shutdown|terminate))", RootActionHandler) ]
        home_handlers += [ (r"/(_(alias))/([-\w.,@=]+)", RootActionHandler) ]
        home_handlers += [ (r"/(_(backup|restart|terminate|update))/([a-zA-Z][-\w.]*)", RootActionHandler) ]
        if Options['multisite']:
            home_handlers += [ (r"/(_(site_settings|site_delete))/([a-zA-Z][-\w.]*)", SiteActionHandler) ]
        else:
            home_handlers += [ (r"/(_(site_settings))", SiteActionHandler) ]

        home_handlers += [ (r"/"+RESOURCE_PATH+"/(.*)", UncachedStaticFileHandler, {'path': os.path.join(scriptdir,'templates')}) ]
        home_handlers += [ (r"/"+ACME_PATH+"/(.*)", UncachedStaticFileHandler, {'path': 'acme-web/'+ACME_PATH}) ]
        if Options['libraries_dir']:
            home_handlers += [ (r"/"+LIBRARIES_PATH+"/(.*)", CachedStaticFileHandler, {'path': Options['libraries_dir']}) ]

        if Options['multisite']:
            home_handlers += [
                     (pathPrefix+r"/(_nonce)/([a-zA-Z][-\w.]*)", HomeHandler),
                     (pathPrefix+r"/(_batch_login)/([a-zA-Z][-\w.]*)", HomeHandler)
                     ]
        else:
            home_handlers += [
                     (pathPrefix+r"/(_nonce)", HomeHandler),
                     (pathPrefix+r"/(_batch_login)", HomeHandler)
                    ]
    else:
        # Site server
        home_handlers += [ (pathPrefix+r"/(_shutdown)", RootActionHandler) ]

    if Options['web_dir']:
        # Maps any path containing .../_docs/... (can be used as /site_name/session_name/_docs/... for session-aware help docs)
        docs_dir = os.path.join(Options['web_dir'],'_docs')
        home_handlers += [ (r"[^_]*/"+DOCS_PATH+"/(.*)", UncachedStaticFileHandler, {'path': docs_dir}) ]
        home_handlers += [ (r"[^_]*/_private/[^_]*/"+DOCS_PATH+"/(.*)", UncachedStaticFileHandler, {'path': docs_dir}) ]

    Root_server = Options['multisite'] and not Options['site_number']
    if Options['multisite']:
        if not Options['site_number']:
            # Root server (no site associated with it)
            home_handlers += [ (pathPrefix+r"/index.html", HomeHandler) ]
        else:
            # Secondary server
            home_handlers += [ (pathPrefix+r"$", HomeHandler) ]

    auth_handlers = [
                     (r"/_auth/logout/", AuthLogoutHandler),
                     (r"/_auth/login/", AuthLoginHandler),
                    ]

    # Only root can auto reload
    appSettings = {'autoreload': False if Options['site_number'] else Options['reload'] }
    if appSettings['autoreload']:
        tornado.autoreload.add_reload_hook(shutdown_all)

    Global.login_domain = ''
    Global.login_url = '/_auth/login/'
    Global.logout_url = '/_logout'
    if ',' in Options['auth_type']:
        Global.login_url = '/_oauth/login'
        comps = Options['auth_type'].split(',')

        if Options['server_url']:
            redirect_uri = Options['server_url'] + Global.login_url
        else:
            redirect_uri = 'http://localhost'+ ('' if Options['port'] == 80 else ':'+str(Options['port'])) + Global.login_url

        Global.login_domain = comps[0] if comps[0] and comps[0][0] == '@' else ''

        if comps[0] == 'google' or Global.login_domain:
            appSettings.update(google_oauth={'key': comps[1],
                                        'secret': comps[2],
                                        'redirect_uri': redirect_uri})
            auth_handlers += [ (Global.login_url, GoogleLoginHandler) ]

        elif comps[0] == 'twitter':
            appSettings.update(twitter_consumer_key=comps[1],
                            twitter_consumer_secret=comps[2])
            auth_handlers += [ (Global.login_url, TwitterLoginHandler) ]

        else:
            raise Exception('sdserver: Invalid login auth_type: '+comps[0])

    cookie_secret = sliauth.gen_hmac_token(Options['root_auth_key'], 'cookie:'+COOKIE_VERSION, truncate=sliauth.TRUNCATE_SITE)
    appSettings.update(
        template_path=os.path.join(os.path.dirname(__file__), "server_templates"),
        xsrf_cookies=Options['xsrf'],
        cookie_secret=cookie_secret,
        login_url=Global.login_url,
        debug=Options['debug'],
    )

    if Options['auth_type'] != 'none' and not Root_server:
        site_handlers = [
                      (pathPrefix+r"/(_proxy)", ProxyHandler),
                      (pathPrefix+r"/(_dryproxy)", ProxyHandler),
                      (pathPrefix+r"/_websocket/(.*)", WSHandler),
                      (pathPrefix+r"/send", AuthMessageHandler),
                      (pathPrefix+r"/send/(.*)", AuthMessageHandler),
                      (pathPrefix+r"/(_dash)", AuthActionHandler),
                      (pathPrefix+r"/(_user_blankimage)", UserActionHandler),
                      (pathPrefix+r"/(_user_browse)", UserActionHandler),
                      (pathPrefix+r"/(_user_browse/.+)", UserActionHandler),
                      (pathPrefix+r"/(_user_canceldelay)", UserActionHandler),
                      (pathPrefix+r"/(_user_discuss)", UserActionHandler),
                      (pathPrefix+r"/(_user_discussclose)", UserActionHandler),
                      (pathPrefix+r"/(_user_flag)", UserActionHandler),
                      (pathPrefix+r"/(_user_grades)", UserActionHandler),
                      (pathPrefix+r"/(_user_grades/[-\w.%]+)", UserActionHandler),
                      (pathPrefix+r"/(_user_message)", UserActionHandler),
                      (pathPrefix+r"/(_user_plain)", UserActionHandler),
                      (pathPrefix+r"/(_user_qstats/[-\w.]+)", UserActionHandler),
                      (pathPrefix+r"/(_user_status)", UserActionHandler),
                      (pathPrefix+r"/(_user_twitterlink/[-\w.]+)", UserActionHandler),
                      (pathPrefix+r"/(_user_twitterverify/[-\w.]+)", UserActionHandler),
                      ]

        if Options['server_url'].startswith('http://localhost:'):
            site_handlers += [ (pathPrefix+r"/_testsend", UnauthMessageHandler) ]

        patterns= [   r"/(_(backup|cache|clear|freeze))",
                      r"/(_accept)",
                      r"/(_actions)",
                      r"/(_addtype)",
                      r"/(_attend)",
                      r"/(_backup/[-\w.]+)",
                      r"/(_browse)",
                      r"/(_browse/.+)",
                      r"/(_closepreview)",
                      r"/(_delete/[-\w.]+)",
                      r"/(_discard)",
                      r"/(_discard/[-\w.]+)",
                      r"/(_download/[-\w.]+)",
                      r"/(_downloadpreview)",
                      r"/(_edit)",
                      r"/(_edit/[-\w.]+)",
                      r"/(_editroster)",
                      r"/(_export/[-\w.]+)",
                      r"/(_(getcol|getrow|sheet)/[-\w.;]+)",
                      r"/(_imageupload)",
                      r"/(_import/[-\w.]+)",
                      r"/(_interactcode)",
                      r"/(_lock)",
                      r"/(_lock/[-\w.]+)",
                      r"/(_lockcode/[-\w.;%]+)",
                      r"/(_logout)",
                      r"/(_manage/[-\w.]+)",
                      r"/(_modules)",
                      r"/(_prefill/[-\w.]+)",
                      r"/(_preview/[-\w./]+)",
                      r"/(_refresh/[-\w.]+)",
                      r"/(_reindex/[-\w.]+)",
                      r"/(_release/[-\w.]+)",
                      r"/(_reloadpreview)",
                      r"/(_remoteupload/[-\w.]+)",
                      r"/(_republish/[-\w.]+)",
                      r"/(_reset_cache_updates)",
                      r"/(_responders/[-\w.]+)",
                      r"/(_restore)",
                      r"/(_roster)",
                      r"/(_startpreview/[-\w.]+)",
                      r"/(_submit/[-\w.:;]+)",
                      r"/(_twitter)",
                      r"/(_teamgen)",
                      r"/(_unlock/[-\w.]+)",
                      r"/(_unsafe_trigger_updates/[-\w.]+)",
                      r"/(_upload)",
                      r"/(_upload/[-\w.]+)",
                      r"/(_lock/[-\w.]+)",
                       ]
        action_handlers = [(pathPrefix+pattern, ActionHandler) for pattern in patterns]
    else:
        site_handlers = []
        action_handlers = []

    file_handler = SiteStaticFileHandler if Options['auth_type'] == 'none' else AuthStaticFileHandler

    if Options['web_dir']:
        sprefix = Options['site_name']+'/' if Options['site_name'] else ''
        # Handle special paths
        for path in [FILES_PATH, PRIVATE_PATH, RESTRICTED_PATH, PLUGINDATA_PATH]:
            if path == PLUGINDATA_PATH:
                if not Options['plugindata_dir']:
                    continue
                dir = Options['plugindata_dir'] + pathPrefix
            else:
                dir = Options['web_dir'] + pathPrefix
            site_handlers += [ (r'/%s(%s/.*)' % (sprefix, path), file_handler, {'path': dir}) ]

        # Default web path
        site_handlers += [ (r'/%s([^_].*)' % sprefix, file_handler, {'path': Options['web_dir']+pathPrefix}) ]

    if Options['multisite']:
        if not Options['site_number']:
            handlers = home_handlers + auth_handlers + action_handlers
        else:
            handlers = home_handlers + action_handlers + site_handlers
    else:
        handlers = home_handlers + auth_handlers + action_handlers + site_handlers

    handlers += [ (r'.*', InvalidHandler) ]
    ##if Options['debug']:
    ##    print >> sys.stderr, 'createApplication', Options['site_number'], Options['site_name'], [x[0] for x in handlers]

    return tornado.web.Application(handlers, **appSettings)


def processTwitterMessage(msg):
    # Return null string on success or error message
    interactiveSession = WSHandler.getInteractiveSession()[0]
    print >> sys.stderr, 'sdserver.processTwitterMessage:', interactiveSession, msg

    fromUser = msg['sender']
    fromName = msg['name']
    message = msg['text']
    status = None
    fromRole = ''
    rosterSheet = sdproxy.getSheet(sdproxy.ROSTER_SHEET)

    if Options['auth_type'].startswith('twitter,') or (not rosterSheet and sdproxy.Settings['no_roster']):
        if not Options['auth_type'].startswith('twitter,'):
            # Using non-twitter auth; distinguish twitter userid
            fromUser = '@' + fromUser
            if fromName:
                sdproxy.mapDisplayName(fromUser, fromName)
        status = WSHandler.processMessage(fromUser, fromRole, fromName, message, source='twitter', adminBroadcast=True)


    elif rosterSheet:
        idMap = sdproxy.makeRosterMap(sdproxy.TWITTER_HEADER, lowercase=True)
        userId = idMap.get(fromUser.lower())
        if not userId:
            userId = Global.twitterSpecial.get(fromUser.lower())

        if userId:
            status = WSHandler.processMessage(userId, fromRole, sdproxy.lookupRoster('name', userId), message, source='twitter', adminBroadcast=True)
        else:
            status = 'Error - twitter ID %s not found in roster for site %s' % (fromUser, Options['site_name'])

    print >> sys.stderr, 'processTwitterMessage:', status
    return status

def restoreSite(bak_dir):
    csv_list = glob.glob(bak_dir+'/*.csv')
    csv_list.sort()

    for fpath in csv_list:
        fname = os.path.basename(fpath)
        sheetName, _ = os.path.splitext(fname)
        with open(fpath, 'rb') as f:       # Important to open in 'rb' mode for universal newline recognition
            errMsg = restoreSheet(sheetName, fname, f, overwrite=False)
            if errMsg:
                raise Exception('Error in restoring %s: %s' % (fpath, errMsg))
            else:
                ##print >> sys.stderr, 'Restored sheet %s from backup directory %s' % (sheetName, bak_dir)
                pass

def restoreSheet(sheetName, filepath, csvfile, overwrite=None):
    # Restore sheet from backup CSV file
    try:
        ##dialect = csv.Sniffer().sniff(csvfile.read(1024))
        ##csvfile.seek(0)
        reader = csv.reader(csvfile, delimiter=',')  # Ignore dialect for now
        rows = [row for row in reader]
        if not rows:
            raise Exception('No rows in CSV file %s for sheet %s' % (filepath, sheetName))

        sdproxy.importSheet(sheetName, rows[0], rows[1:], overwrite=overwrite)
        return ''

    except Exception, excp:
        if Options['debug']:
            import traceback
            traceback.print_exc()
        return 'Error in restoreSheet: '+str(excp)

def importRoster(filepath, csvfile, overwrite=False, lastname_col='', firstname_col='', midname_col='',
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

        rosterHeaders = sdproxy.MIN_HEADERS + [sdproxy.STATUS_HEADER, sdproxy.TEAM_HEADER, sdproxy.TWITTER_HEADER]
        rosterTwitterCol = 1 + rosterHeaders.index(sdproxy.TWITTER_HEADER)
        rosterRows = []
        singleDomain = None

        for row in rows:
            altid = row[altidCol-1].lower() if altidCol else ''
            email = row[emailCol-1].lower() if emailCol else ''
            name = sdproxy.makeName(row[lastNameCol-1], row[firstNameCol-1], row[midNameCol-1] if midNameCol else '')

            if email:
                emailid, _, domain = email.partition('@')
                if domain:
                    if singleDomain is None:
                        singleDomain = domain
                    elif singleDomain != domain:
                        singleDomain = ''
                
            userId = ''
            if idCol:
                userId = row[idCol-1].strip().lower()

            if not userId and name and CommandOpts.multi_email_id:
                userId = sdproxy.makeId(name, idVals)

            if not userId:
                userId = email

            if not userId:
                raise Exception('No userId for name: %s %s' % (name, email))
            elif not sdproxy.USERID_RE.match(userId) or '--' in userId:
                raise Exception("Invalid character sequence in userId '%s'; only digits/letters/hyphen/periods/at-symbols are allowed" % userId)

            rosterRow = [name, userId, email, altid] + ['']*(len(rosterHeaders)-4)
            if twitterCol:
                rosterRow[rosterTwitterCol-1] = row[twitterCol-1]
            rosterRows.append(rosterRow)

        if (not idCol or idCol == emailCol) and singleDomain:
            # Strip out common domain from email used as ID
            endStr = '@'+singleDomain
            endLen = len(endStr)
            for j in range(len(rosterRows)):
                if rosterRows[j][1].endswith(endStr):
                    rosterRows[j][1] = rosterRows[j][1][:-endLen]

        sdproxy.createRoster(rosterHeaders, rosterRows, overwrite=overwrite)
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
        if importParams['importKey'] == sdproxy.TWITTER_HEADER:
            # Special case of test user; not really Twitter ID
            keyMap[sdproxy.TESTUSER_ID] = sdproxy.TESTUSER_ID

        nameMap = sdproxy.getDisplayNames()

        missingKeys = []
        userKeys = set()
        idRows = []
        for row in rows:
            if nameKey:
                userKey = sdproxy.makeName(row[lastNameCol-1], row[firstNameCol-1], row[midNameCol-1] if midNameCol else '').lower()
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
        return http_client.fetch(url+path, request_timeout=300)
    else:
        import multiproxy
        sock = multiproxy.create_unix_client_socket(relay_address)
        retval = sock.sendall('''GET %s HTTP/1.1\r\nHost: localhost\r\n\r\n''' % path)
        sock.close()
        return retval

def exec_cmd(cmd_name, options=[], arg_list=[]):
    # Execute command and return empty list on success or list of output/error messages
    cmd = [cmd_name] + options + arg_list
    print >> sys.stderr, 'exec_cmd:', ' '.join(cmd)
    try:
        output = subprocess.check_output(cmd)
    except Exception, excp:
        output = str(excp)
        print >> sys.stderr, 'ERROR:exec_cmd', cmd_name, output
    if output.strip():
        return ['Error in command %s: %s' % (cmd_name, output.strip())]
    else:
        return []

def backupCopy(filepath, dest_dir, if_exists=False):
    if if_exists and (not filepath or not os.path.exists(filepath)):
        return ''
    try:
        shutil.copy2(filepath, dest_dir)
        return ''
    except Exception, excp:
        errMsg = 'backupCopy: Error in copying file %s to %s: %s' % (filepath, dest_dir, excp)
        print >> sys.stderr, errMsg
        return errMsg

def backupWrite(dirpath, filename, content, create_dir=False):
    if create_dir and not os.path.isdir(dirpath):
        os.makedirs(dirpath)
    try:
        filepath = os.path.join(dirpath, filename)
        with open(filepath, 'w') as f:
            f.write(content)
        return ''
    except Exception, excp:
        errMsg = 'backupWrite: Error in writing file %s: %s' % (filepath, excp)
        print >> sys.stderr, errMsg
        return errMsg
    
def backupLink(backup_path):
    return  # DISABLED; symlinks do not work well with Dropbox
    if not Options['site_name']:
        return
    backup_name = os.path.basename(backup_path)
    subnames = ['_source', '_web', PLUGINDATA_PATH]
    for subname in subnames:
        try:
            alt_link_dir = os.path.join(Options['backup_dir'], backup_name, subname)
            alt_link = os.path.join(alt_link_dir, Options['site_name'])
            source = os.path.join('..', '..', Options['site_name'], backup_name, subname)

            if not os.path.isdir(alt_link_dir):
                os.makedirs(alt_link_dir)

            if os.path.exists(os.path.join(alt_link_dir, source)):
                if os.path.islink(alt_link):
                    os.remove(alt_link)
                os.symlink(source, alt_link)

        except Exception, excp:
            print >> sys.stderr, 'backupLink: Error in creating symlink for', backup_name, subname, Options['site_name'], excp

def backupSite(dirname='', broadcast=False):
    if not dirname and Options['dry_run']:
        return sliauth.errlog('Warning: Dry run; no auto backup')

    if (not dirname or dirname == 'daily') and (not Options['multisite'] or Options['site_name']):
        if Options['end_date'] and (sliauth.epoch_ms() - sliauth.epoch_ms(sliauth.parse_date(Options['end_date']))) > 8*84600*1000:
            return sliauth.errlog('Warning: Expired site %s; no auto backup' % Options['site_name'])

    if dirname.endswith('-'):
        dirname += sliauth.iso_date(nosec=True).replace(':','-')

    if Options['debug']:
        print >> sys.stderr, 'sdserver.backupSite:', Options['site_name'], dirname, broadcast

    backup_name = dirname or 'daily'
    backup_url = '/_browse/backup/' + backup_name

    if Options['site_name']:
        backup_url = '/' + Options['site_name'] + backup_url

    if backup_name == Options['site_name'] or backup_name in Global.predefined_sites:
        raise Exception('Backup directory name %s conflicts with site name' % backup_name)

    if not os.path.isdir(BaseHandler.site_backup_dir):
        return sliauth.errlog('ERROR: BACKUP FAILED - no backup directory for site '+Options['site_name']+': '+BaseHandler.site_backup_dir)

    backup_path = os.path.join(BaseHandler.site_backup_dir, backup_name)

    save_prefix, save_fmt = '', ''
    if 'weekly' in Options['backup_options']:
        save_prefix = 'week'
        save_fmt = '%U'
    elif 'monthly' in Options['backup_options']:
        save_prefix = 'month'
        save_fmt = '%M'

    if backup_name == 'daily' and os.path.exists(backup_path) and (save_fmt or 'seven_day' in Options['backup_options']):
        # Copy previous daily backup to corresponding day/week/month backup before updating it
        try:
            with open(os.path.join(backup_path,BACKUP_VERSION_FILE), 'r') as f:
                prev_bak_date = sliauth.parse_date(f.read().split()[0])
                if prev_bak_date:
                    rsync_cmd = ['-rpt', '--delete']
                    if 'exclude_images' in Options['backup_options']:
                        # Exclude *_images dir from copy of daily backup (to save space)
                        rsync_cmd += ['--exclude=*_images/']

                    if 'seven_day' in Options['backup_options']:
                        # Save daily backup for last seven days
                        day_path = os.path.join(BaseHandler.site_backup_dir, 'day'+prev_bak_date.strftime('%w'))

                        exec_cmd('rsync', rsync_cmd, [backup_path+'/', day_path])
                        backupLink(day_path)

                    if save_fmt and (datetime.datetime.now().strftime(save_fmt) != prev_bak_date.strftime(save_fmt)):
                        # New week/month; save last daily backup from previous week/month (including *_images)
                        save_path = os.path.join(BaseHandler.site_backup_dir, save_prefix+prev_bak_date.strftime(save_fmt))
                        exec_cmd('rsync', rsync_cmd, [backup_path+'/', save_path])
                        backupLink(save_path)
                        if os.path.exists(SERVER_LOGFILE):
                            if not backupCopy(SERVER_LOGFILE, save_path):
                                # Remove logfile on successful weekly/monthly backup copy (it should be recreated)
                                try:
                                    os.remove(SERVER_LOGFILE)
                                except Exception, excp:
                                    print >> sys.stderr, 'ERROR:backupSite: Failed to remove logfile', SERVER_LOGFILE, excp

        except Exception, excp:
            print >> sys.stderr, 'ERROR:backupSite: daily/weekly/monthly backup', Options['site_name'], excp

    backupWrite(backup_path, BACKUP_VERSION_FILE, '%s v%s\n' % (sliauth.iso_date(nosec=True), sliauth.get_version()),
                create_dir=True)

    errorList = []
    if not Options['site_name']:
        # Root/single server; backup slidoc source code and log file
        errorList += exec_cmd('rsync', ['-rpt', '--delete', '--executability', '--exclude=.*', '--exclude=.*/', '--exclude=*.pyc', '--exclude=*~'],
                                       [script_parentdir+'/src', script_parentdir+'/scripts', script_parentdir+'/docs', os.path.join(backup_path, '_slidoc')])

        makefile_path = os.path.join(script_parentdir, 'Makefile')

        if os.path.isdir(Global.config_path):
            config_files = [SLIDOC_CONFIGFILE]
            if Options['multisite']:
                config_files += sorted([os.path.basename(f) for f in glob.glob(Global.config_path+'/[!_]*.json')])
            elif Global.site_settings_file:
                config_files.append(os.path.basename(Global.site_settings_file))

            config_dir = os.path.join(backup_path, 'config')
            if not os.path.exists(config_dir):
                os.makedirs(config_dir)
            for fname in config_files:
                backupCopy(os.path.join(Global.config_path,fname), os.path.join(config_dir,fname), if_exists=True)
        else:
            backupCopy(Global.config_path, backup_path, if_exists=True)

        backupCopy(makefile_path, backup_path, if_exists=True)
        if dirname.lower().startswith('full'):
            backupCopy(SERVER_LOGFILE, backup_path, if_exists=True)

    if Options['multisite'] and not Options['site_number']:
        # Root server
        if not broadcast:
            if not errorList:
                return sliauth.errlog('Backed up root')
        else:
            # Broadcast backup command
            path = '/_backup'
            if dirname:
                path += '/' + urllib.quote(dirname)
            path += '?root='+sliauth.safe_quote(Options['server_key'])

            for site_name in Options['site_list']:
                relay_addr = SiteProps.relay_map(get_site_number(site_name))
                try:
                    retval = sendPrivateRequest(relay_addr, path='/'+site_name+path)
                except Exception, excp:
                    errorList.append('Error in remote backup of site %s: %s' % (site_name, excp))
            if not errorList:
                return sliauth.errlog('Backed up module sessions for each site to directory %s\n' % backup_name)
    else:
        # Sole or site server
        errorList += sdproxy.backupSheets(backup_path)

        sublist = [('_source', BaseHandler.site_src_dir), ('_web', BaseHandler.site_web_dir), (PLUGINDATA_PATH, BaseHandler.site_data_dir)]

        for subname, relpath in sublist:
            # Backup source directory and any additional directories if "full" backup
            if relpath and os.path.isdir(relpath) and (subname in ['_source'] or dirname.lower().startswith('full')):
                reldir = os.path.join(backup_path, subname)
                if not os.path.isdir(reldir):
                    os.makedirs(reldir)
                errorList += exec_cmd('rsync', ['-rpt', '--delete'], [relpath+'/', reldir])

        backupLink(backup_path)

    errorStr = '\n'.join(errorList)+'\n' if errorList else ''
    if errorStr:
        backupWrite(backup_path, '_ERRORS_IN_BACKUP.txt', errorStr)

    if Options['debug']:
        if errorStr:
            print >> sys.stderr, errorStr
        sliauth.errlog("DEBUG:backupSite: [%s] %s completed %s" % (Options['site_name'], backup_path, datetime.datetime.now()))

    if errorList:
        return preElement('\n'+'\n'.join(errorList)+'\n')+'\n'
    else:
        return '<p></p><b>Backed up module sessions to directory <a href="%s">%s</a></b>\n' % (backup_url, backup_name)

def shutdown_all(keep_root=False, wait=False):
    if Options['debug']:
        print >> sys.stderr, 'sdserver.shutdown_all:'

    if not Global.remoteShutdown:
        Global.remoteShutdown = True
        shutdown_sites(wait=wait)

    if not keep_root:
        shutdown_root()

def shutdown_sites(wait=False):
    # Shutdown child servers
    active = []
    for site_name, child in Global.child_procs.items():
        if child and child.proc.poll() is None:
            active.append( (site_name, child) )
            relay_addr = SiteProps.relay_map(get_site_number(site_name))
            try:
                retval = sendPrivateRequest(relay_addr, path='/'+site_name+'/_shutdown?root='+sliauth.safe_quote(Options['server_key']))
                print >> sys.stderr, 'sdserver.shutdown_sites: ****Shutting down site', site_name
            except Exception, excp:
                print >> sys.stderr, 'sdserver.shutdown_sites: Error in shutting down site', site_name, excp

    if wait:
        for site_name, child in active:
            print >> sys.stderr, 'sdserver.shutdown_sites: ****Waiting for site %s to exit (blocking)' % site_name
            child.proc.wait()
            print >> sys.stderr, 'sdserver.shutdown_sites: ****Exited site %s' % site_name

    if Global.proxy_server:
        Global.proxy_server.stop()
        Global.proxy_server = None
        print >> sys.stderr, 'sdserver: ****STOPPED proxy'

def shutdown_root():
    IOLoop.current().add_callback(shutdown_loop)

def shutdown_loop():
    print >> sys.stderr, 'sdserver.shutdown_loop: ****starting...', Options['site_name']
    shutdown_server()
    IOLoop.current().stop()
    print >> sys.stderr, 'sdserver.shutdown_loop: ****COMPLETED', Options['site_name']

def shutdown_server():
    if Global.http_server:
        Global.http_server.stop()
        Global.http_server = None
    if Global.server_socket:
        try:
            Global.server_socket.close()
        except Exception, excp:
            print >> sys.stderr, 'sdserver.shutdown_server: ERROR', sexcp
            
    print >> sys.stderr, 'sdserver.shutdown_server:', '****Completed SHUTDOWN of server', Options['site_name']
    

def reload_server():
    try:
        os.utime(RELOAD_WATCH_FILE, None)
        print >> sys.stderr, 'sdserver.Reloading server****'
    except Exception, excp:
        print >> sys.stderr, 'sdserver.ERROR: Reload server failed - %s' % excp


def cert_daysleft():
    if not Options['ssl_options'] or not Options['ssl_options']['certfile'].startswith('certbot/'):
        return None
    try:
        cmd = ['openssl', 'x509', '-enddate', '-noout', '-in', Options['ssl_options']['certfile']]
        expdatestr = subprocess.check_output(cmd).split('=')[-1].strip()
        expdate = datetime.datetime.strptime(expdatestr,'%b %d %H:%M:%S %Y %Z')
        return (expdate - datetime.datetime.today()).days
    except Exception, excp:
        print >> sys.stderr, 'sdserver/cert_daysleft: ERROR: '+' '.join(cmd) + ': '+ str(excp)
        return -9999

def renew_ssl(force=False):
    outText = ''
    if not force:
        days_left = cert_daysleft()
        if days_left is None or days_left <= -9999 or days_left >= 30:
            return outText
        print >> sys.stderr, 'sdserver: Reloading after renewing SSL cert', days_left, 'days before expiry:', sliauth.iso_date(nosubsec=True)

    try:
        server_domain = Options['server_url'].split('//')[1].split(':')[0]
        cmd = ['certbot', 'certonly', '-n', '--webroot', '--config-dir', './certbot/config', '--logs-dir', './certbot/log', '--work-dir', './certbot/work', '-w', './acme-web', '-d', server_domain]

        print >> sys.stderr, 'Executing: '+' '.join(cmd)
        outText += 'Executing: '+' '.join(cmd) + '\n'
        certOutput = subprocess.check_output(cmd)

        print >> sys.stderr, 'Output:\n%s' % certOutput
        outText += 'Renewal status:\n'+certOutput
    except Exception, excp:
        errMsg = 'Error in renewal of SSL cert: '+str(excp)
        print >> sys.stderr, errMsg
        outText += errMsg + '\n'

    print >> sys.stderr, 'sdserver: Shutting down sites (blocking)'
    shutdown_sites(wait=True)
    reload_server()

    return outText

class UserRoles(object):
    def __init__(self):
        self.alias_map = {}
        self.root_role = {}
        self.external_users = set()
        self.site_roles = {}
        self.site_special_users = {}

    def map_user(self, username):
        return self.alias_map.get(username, username)
            
    def is_known_user(self, userId):
        return self.is_special_user(userId) or userId in self.external_users

    def is_special_user(self, userId):
        if userId in self.root_role:
            return True
        for users in self.site_special_users.values():
            if userId in users:
                return True
        return False

    def list_aliases(self):
        return ','.join('%s=%s' % (k, v) for k, v in self.alias_map.items())

    def add_alias(self, origId, userId):
        if not userId:
            if origId in self.alias_map:
                del self.alias_map[origId]
            if '@' in origId:
                self.external_users.discard(origId)
        else:
            self.alias_map[origId] = userId
            if '@' in origId:
                self.external_users.add(origId)

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
                self.add_alias(origId, userId)

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
                if userId not in Options['root_users']:
                    Options['root_users'].append(userId)

            if not Options['site_number']:
                print >> sys.stderr, 'sdserver:   USER %s: %s -> %s:%s:' % (user_map, origId, userId, userRole)

        if Options['root_auth_key'] and not admin_user:
            raise Exception('There must be at least one user with admin access')


    def update_site_roles(self, siteName, adminIds, graderIds, guestIds):
        roles = (sdproxy.ADMIN_ROLE, sdproxy.GRADER_ROLE, '')
        idLists = [adminIds, graderIds, guestIds]
        self.site_roles[siteName] = {}
        self.site_special_users[siteName] = set()

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
                self.site_special_users[siteName].add(userId)

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

def start_multiproxy():
    if Options['ssl_options'] and (not os.path.exists(Options['ssl_options']['certfile']) or not os.path.exists(Options['ssl_options']['keyfile'])):
        print >> sys.stderr, 'ERROR: SSL options file', Options['ssl_options'], 'not found'
        return

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
                retval = SiteProps.relay_map(get_site_number(comps[1]))
            elif Global.relay_forward and not self.request_uri.startswith('/_'):
                # Not URL starting with '_'; forward to underlying website
                retval = Global.relay_forward
            else:
                # Root server
                retval = SiteProps.relay_map(0)
            if DEBUG_PATH_RE and DEBUG_PATH_RE.search(self.request_uri):
                print >> sys.stderr, 'sdserver: get_relay_addr_uri:', sliauth.iso_date(nosubsec=True), self.ip_addr, self.request_uri, retval
            return retval

    Global.proxy_server = multiproxy.ProxyServer(Options['host'], Options['port'], ProxyRequestHandler, log_interval=0,
                      xheaders=True, masquerade="server/1.2345", ssl_options=Options['ssl_options'], debug=True)

def start_server(site_number=0, restart=False):
    # Start site/root server
    Options['server_start'] = sliauth.create_date()
    if Options['ssl_options'] and not site_number:
        # Redirect plain HTTP to HTTPS
        handlers = [ (r'/'+ACME_PATH+'/(.*)', UncachedStaticFileHandler, {'path': 'acme-web/'+ACME_PATH}) ]
        handlers += [ (r'/.*', PlainHTTPHandler) ]
        plain_http_app = tornado.web.Application(handlers)
        plain_http_app.listen(80 + (CommandOpts.port - (CommandOpts.port % 1000)), address=Options['host'])
        if not os.path.exists(Options['ssl_options']['certfile']) or not os.path.exists(Options['ssl_options']['keyfile']):
            print >> sys.stderr, 'ERROR: SSL options file', Options['ssl_options'], 'not found'
            print >> sys.stderr, 'Listening on HTTP port for SSL cert validation'
            IOLoop.current().start()
            return
        days_left = cert_daysleft()
        if days_left is not None:
            print >> sys.stderr, '*****SSL cert:', days_left, 'days before expiry'
        print >> sys.stderr, 'Listening on HTTP port to redirect to HTTPS'

    if Options['ssl_options'] and not Options['multisite']:
        Global.http_server = tornado.httpserver.HTTPServer(createApplication(), ssl_options=Options['ssl_options'])
    else:
        Global.http_server = tornado.httpserver.HTTPServer(createApplication())

    if Options['reload'] and not site_number:
        try:
            open(RELOAD_WATCH_FILE, 'a').close()
            tornado.autoreload.watch(RELOAD_WATCH_FILE)
        except Exception, excp:
            print >> sys.stderr, 'Site %s: ERROR: Failed to create reload watch file %s - %s' % (Options['site_name'], RELOAD_WATCH_FILE, excp)
        if Global.site_settings_file:
            tornado.autoreload.watch(Global.site_settings_file)

    if not Options['multisite']:
        # Start single site server
        print >> sys.stderr, "Listening on host, port:", Options['host'], Options['port'], Options['site_name']
        Global.http_server.listen(Options['port'], address=Options['host'])
    else:
        relay_addr = SiteProps.relay_map(site_number)
        if isinstance(relay_addr, tuple):
            Global.http_server.listen(relay_addr[1])
        else:
            import multiproxy
            Global.server_socket = multiproxy.make_unix_server_socket(relay_addr)
            Global.http_server.add_socket(Global.server_socket)
        print >> sys.stderr, "  Site %02d:%s listening on %s (%s: admins=%s, graders=%s, guests=%s, start=%s, end=%s)" % (site_number, Options['site_name'], relay_addr,
                Options['site_name'], Options['admin_users'], Options['grader_users'], Options['guest_users'], Options['start_date'], Options['end_date'])

    if not restart:
        IOLoop.current().start()

def getBakDir(site_name):
    if not Options['restore_backup']:
        return None
    bak_dir, bak_name = Options['restore_backup']
    if site_name:
        bak_dir = os.path.join(bak_dir, site_name)
    bak_dir = os.path.join(bak_dir, bak_name)
    return bak_dir

def getSiteRosterMaps(gsheet_url, site_name=''):
    try:
        rows, headers = sliauth.read_sheet(gsheet_url, Options['root_auth_key'], sdproxy.ROSTER_SHEET, site=site_name)
        nameCol  = 1 + headers.index('name')
        idCol    = 1 + headers.index('id')
        emailCol = 1 + headers.index('email')
        rosterMaps = {}
        rosterMaps['id2email'] = dict( (x[idCol-1], x[emailCol-1]) for x in rows[1:] if x[idCol-1] )
        rosterMaps['id2name']  = dict( (x[idCol-1], x[nameCol-1])  for x in rows[1:] if x[idCol-1] )
        return rosterMaps

    except Exception, excp:
        ##if Options['debug']:
        ##    import traceback
        ##    traceback.print_exc()
        print >> sys.stderr, 'Error:site %s: Failed to read Google Sheet roster_slidoc from %s: %s' % (site_name, gsheet_url, excp)
        return {}

class SiteProps(object):
    siteRosterMaps = {}
    siteScriptVersions = {}
    sitesDeactivated = set()

    defaultSessionTypes = [
        TOP_LEVEL+':0:public:Top level web page',
        'announce:0::Announcements',
        'assignment:1::Assigments',
        'exam:1:restricted:Exams',
        'exercise:0::Exercises',
        'final:1:restricted:Final exam',
        'help:0:public:Help info',
        'lecture:1::Lectures',
        'midterm:1:restricted:Midterms',
        'notes:0::Notes',
        'project:1::Projects',
        'quiz:1:restricted:Quizzes',
        'test:1:restricted:Tests'
    ]
    
    @classmethod
    def reset_site(cls):
        cls.siteRosterMaps = {}

    @classmethod
    def get_site_menu(cls):
        return sdproxy.split_list(Global.site_settings.get('site_menu',''))
    
    @classmethod
    def get_session_props(cls):
        propStr = Global.site_settings.get('session_properties','')
        if propStr.strip():
            propsList = propStr.strip().split(';')
        else:
            propsList = cls.defaultSessionTypes
        propsDict = OrderedDict()
        for sessionProp in propsList:
            comps = sessionProp.strip().split(':')
            sessionName = comps[0].strip()
            if sessionName:
                props = {}
                if len(comps) > 1 and comps[1].strip().isdigit():
                    props['pace'] = int(comps[1].strip())
                else:
                    props['pace'] = 0

                props['access'] = comps[2].strip().lower() if len(comps) > 2 else ''
                props['description'] = comps[3].strip() if len(comps) > 3 else ''
                    
                propsDict[sessionName] = props
        return propsDict
            
    @classmethod
    def session_types(cls):
        type_labels = []
        for sessionType, sessionProp in cls.get_session_props().items():
            sessionDesc = sessionProp['description']
            if sessionProp['access']:
                sessionDesc += ' (' + sessionProp['access'] + ')'
            if sessionProp['pace']:
                sessionDesc += ' (paced)'
            type_labels.append( [sessionType, sessionDesc] )
        return type_labels

    @classmethod
    def private_prefix(cls, sessionType):
        sessionProps = cls.get_session_props()
        if sessionType in sessionProps:
            if sessionProps[sessionType]['access'] == 'public':
                return ''
        elif sessionType == TOP_LEVEL:
            return ''
        return '/' + PRIVATE_PATH

    @classmethod
    def paced_session(cls, sessionType):
        sessionProps = cls.get_session_props()
        if sessionType in sessionProps:
            return sessionProps[sessionType]['pace']
        elif sessionType == TOP_LEVEL:
            return 0
        return 1

    @classmethod
    def restricted_session(cls, sessionType):
        sessionProps = cls.get_session_props()
        if sessionType in sessionProps and sessionProps[sessionType]['access'] == 'restricted':
            return True
        elif sliauth.RESTRICTED_SESSIONS_RE and sliauth.RESTRICTED_SESSIONS_RE.search(sessionType):
            return True
        return False

    @classmethod
    def relay_map(cls, site_number):
        port = Options['private_port'] + site_number
        if Options['socket_dir']:
            return Options['socket_dir']+'/uds_socket'+str(port)
        else:
            return ('localhost', port)

    @classmethod
    def root_site_setup(cls, site_number, site_name, gsheet_url, new=False, update=False):
        # For single or root server
        retval = {}
        if gsheet_url and not Options['dry_run']:
            site_settings = SiteOpts[site_name] if site_name else Global.site_settings
            retval = sliauth.uploadSettings(sdproxy.SETTINGS_SHEET, site_name, gsheet_url, Options['root_auth_key'],
                                            old_auth_key=Options['old_auth_key'], site_settings=site_settings,
                                            server_url=Options['server_url'], debug=Options['debug'])
            cls.sitesDeactivated.discard(site_name)
            if retval.get('sessionsAvailable') and Options['restore_backup']:
                raise Exception('ERROR: Cannot restore from backup for site %s because sessions are already present' % site_name)

        cls.siteScriptVersions[site_name] = retval.get('version', '')
        cls.siteRosterMaps[site_name] = getSiteRosterMaps(gsheet_url, site_name) if gsheet_url and CommandOpts.multi_email_id else {}

        if site_name:
            siteConfig = SiteOpts[site_name]
            Global.userRoles.update_site_roles(site_name, siteConfig.get('admin_users',''), siteConfig.get('grader_users',''), siteConfig.get('guest_users','') )

    @classmethod
    def root_site_delete(cls, site_name):
        if site_name in Global.predefined_sites:
            return 'Cannot delete predefined site %s' % site_name
        site_number = get_site_number(site_name)
        if not site_number:
            return 'Site %s not found!' % site_name
        site_settings = SiteOpts[site_name]
        site_settings_file = os.path.join(Global.config_path, site_name+'.json') if os.path.isdir(Global.config_path) else ''
        if site_settings_file and os.path.exists(site_settings_file) and not Options['dry_run']:
            try:
                os.remove(site_settings_file)
            except Exception, excp:
                return 'Error in deleting site %s config file: %s' % (site_name, excp)

        relay_addr = SiteProps.relay_map(site_number)
        try:
            retval = sendPrivateRequest(relay_addr, path='/'+site_name+'/_shutdown?root='+sliauth.safe_quote(Options['server_key']))
        except Exception, excp:
            print >> sys.stderr, 'sdserver.site_delete: Error in shutting down site', site_name, excp
        cls.root_site_deactivate(site_name, site_settings['gsheet_url'])
        root_remove_site(site_name)
        Global.child_procs[site_name] = None
        return 'Deleted site %s' % site_name

    @classmethod
    def root_site_deactivate(cls, site_name, gsheet_url):
        if not gsheet_url or Options['dry_run']:
            return False
        sliauth.uploadSettings(sdproxy.SETTINGS_SHEET, site_name, gsheet_url, Options['root_auth_key'],
                               site_access=sdproxy.SITE_INACTIVE, server_url=Options['server_url'], debug=Options['debug'])
        cls.sitesDeactivated.add(site_name)
        return True

def root_start_secondary(site_number, site_name, site_settings={}):
    # Return error message or null string
    # site_settings should be specified for transient (no conf file) sites
    if not SiteOpts.get(site_name):
        raise Exception('ERROR: Cannot start site %s not found in root site list %s' % (site_name, Options['site_list']))
    if site_name != SiteOpts.keys()[site_number-1]:
        raise Exception('ERROR: Inconsistent name %s for site number %d: expecting %s' % (site_name, site_number, SiteOpts.keys()[site_number-1]))

    child = Global.child_procs.get(site_name)
    if child and child.proc.poll() is None:
        # Running process
        raise Exception('ERROR: Site %s process still running' % site_name)

    mod_args = sys.argv[:1]
    for arg in sys.argv[1:]:
        argname, _, val = arg.lstrip('-').partition('=')
        if argname != 'sites' and argname not in site_settings:
            mod_args.append(arg)
    mod_args += ['--multisite']
    mod_args += ['--server_version='+sliauth.get_version()]
    mod_args += ['--server_nonce='+Options['server_nonce']]
    mod_args += ['--config_digest='+Global.config_digest]
    mod_args += ['--site_number='+str(site_number)]
    mod_args += ['--site_name='+site_name]
    if site_settings:
        mod_args += ['--%s=%s' % (key, site_settings[key]) for key in SITE_OPTS if key in site_settings]
    else:
        for key in SITE_OPTS:
            # Handle split options for backwards compatibility
            if key in Global.split_site_opts and site_name in Global.split_site_opts[key]:
                mod_args += ['--%s=%s' % (key, Global.split_site_opts[key][site_name]) ]

    Global.child_procs[site_name] = tornado.process.Subprocess(mod_args)

def setup_backup():
    if not Options['backup_hhmm']:
        return
    curTimeSec = sliauth.epoch_ms()/1000.0
    curDate = sliauth.iso_date(sliauth.create_date(curTimeSec*1000.0))[:10]
    backupTimeSec = sliauth.epoch_ms(sliauth.parse_date(curDate+'T'+Options['backup_hhmm']))/1000.0
    backupInterval = 86400
    if curTimeSec+60 > backupTimeSec:
        backupTimeSec += backupInterval
    print >> sys.stderr, Options['site_name'] or 'ROOT', 'Scheduled daily backup in dir %s, starting at %s' % (Options['backup_dir'], sliauth.iso_date(sliauth.create_date(backupTimeSec*1000.0))), Options['backup_options']
    def start_backup():
        if Options['debug']:
            print >> sys.stderr, Options['site_name'] or 'ROOT', 'Setting up periodic backup at', Options['backup_hhmm']
        periodic_backup()
        Global.backup = PeriodicCallback(periodic_backup, backupInterval*1000.0)
        Global.backup.start()

    IOLoop.current().call_at(backupTimeSec, start_backup)

def periodic_backup():
    print >> sys.stderr, Options['site_name'] or 'ROOT', 'Starting periodic backup', sliauth.iso_date(nosubsec=True)
    if 'no_backup' not in Options['backup_options']:
        backupSite('', True)
    if 'renew_ssl' in Options['backup_options']:
        renew_ssl()
    print >> sys.stderr, Options['site_name'] or 'ROOT', 'Ending periodic backup', sliauth.iso_date(nosubsec=True)

def update_session_settings(site_settings):
    # For single or secondary server (NOT CURRENTLY USED)

    Global.session_options = {}
    for key in site_settings:
        smatch = SESSION_OPTS_RE.match(key)
        if smatch:
            # Default session options
            sessionName = smatch.group(1)
            opts_dict = {}
            opts = [x.lstrip('-') for x in site_settings[key].split()]
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

def site_server_setup():
    # For single or secondary server
    if Options['auth_type'] != 'none':
        # Copy server options to proxy
        sdproxy.copyServerOptions(Options)

        # Copy site config to proxy
        sdproxy.copySiteConfig(Global.site_settings)

        update_session_settings(Global.site_settings)

    sdproxy.initProxy(gradebookActive=('gradebook' in SiteProps.get_site_menu()),
                      accessCodeCallback=checkAccessCode, teamSetupCallback=WSHandler.teamNotify, discussPostCallback=WSHandler.postNotify)

    bak_dir = getBakDir(Options['site_name'])
    if bak_dir:
        restoreSite(bak_dir)

    if Options['twitter_config']:
        comps = [x.strip() for x in Options['twitter_config'].split(',')]
        Global.twitter_params = {
            'screen_name': comps[0],
            'consumer_token': {'consumer_key': comps[1], 'consumer_secret': comps[2]},
            'access_token': {'key': comps[3], 'secret': comps[4]}
            }

        Global.twitter_params['site_twitter'] = Global.twitter_params['screen_name']
        if sdproxy.Settings['no_roster']:
            Global.twitter_params['site_twitter'] = '@' + Global.twitter_params['site_twitter']

        import sdstream
        Global.twitterStream = sdstream.TwitterStreamReader(Global.twitter_params, processTwitterMessage,
                                                     allow_replies=Options['allow_replies'])
        Global.twitterStream.start_stream()

def get_site_settings(site_name, commandOpts, cmd_arg_set):
    site_settings_file = ''
    if os.path.isdir(Global.config_path):
        if site_name:
            filename = site_name+'.json'
        elif not commandOpts.multisite:
            filename = getattr(commandOpts, 'settings_file', '') or SINGLE_SETTINGSFILE
        else:
            raise Exception('No config for root server')
        site_settings_file = os.path.join(Global.config_path, filename)
    elif not commandOpts.multisite:
        site_settings_file = getattr(commandOpts, 'settings_file', '')

    if site_settings_file and os.path.exists(site_settings_file):
        print >> sys.stderr, 'sdserver: '+site_name+' settings file=', site_settings_file
        with open(site_settings_file, 'r') as f:
            site_settings = json.load(f)
    else:
        site_settings = {}

    for key in site_settings:
        if key in cmd_arg_set:
            # Site config file overrides root config settings, but not command line settings
            site_settings[key] = getattr(commandOpts, key)

    for key in SITE_OPTS+SHEET_OPTS:
        # Ensure that SITE_OPTS+SHEET_OPTS are always defined
        if key not in site_settings:
            if hasattr(commandOpts, key):
                site_settings[key] = getattr(commandOpts, key)
            elif key in ('site_label', 'site_title'):
                site_settings[key] = key + ' for ' + site_name
            else:
                site_settings[key] = ''

    if site_name and commandOpts.dry_proxy_url and 'gsheet_url' not in cmd_arg_set:
        site_settings['gsheet_url'] = commandOpts.dry_proxy_url+'/'+site_name+'/_dryproxy'

    if commandOpts.auth_type in ('none', 'adminonly'):
        site_settings['no_roster'] = 'yes'

    return site_settings_file, site_settings

def main():
    def config_parse(path):
        Global.config_path = path
        if os.path.isdir(path):
            Global.config_file = os.path.join(path, SLIDOC_CONFIGFILE)
        else:
            Global.config_file = path
        with open(Global.config_file) as f:
            Global.config_digest = sliauth.digest_hex(f.read())
        parse_config_file(Global.config_file, final=False)

    define("config", type=str, help="Path to config file", callback=config_parse)

    define("allow_replies", default=False, help="Allow replies to twitter direct messages")
    define("auth_key", default=Options["auth_key"], help="Authentication key for admin user (at least 20 characters if not localhost; SHOULD be randomly generated, e.g., using 'sliauth.py -g >> _slidoc_config.py')")
    define("auth_type", default=Options["auth_type"], help="none|adminonly|token|@example.com|google|twitter,key,secret,,...")
    define("auth_users", default='', help="filename.txt or [userid]=username[@domain][:role[:site1,site2...];...")
    define("backup", default="", help="=Backup_dir,HH:MM,seven_day,weekly,monthly,exclude_images,no_backup,renew_ssl; End Backup_dir with hyphen to automatically append timestamp")
    define("config_digest", default="", help="Config file digest (used for secondary server only)")
    define("debug", default=False, help="Debug mode")
    define("dry_proxy_url", default="", help="Dry proxy server URL (used for secondary server only)")
    define("dry_run", default=False, help="Dry run (read from Google Sheets, but do not write to it)")
    define("dry_run_file_modify", default=False, help="Allow source/web/plugin file mods even for dry run (e.g., local copy)")
    define("email_addr", default="", help="Admin notification email address for server errors")
    define("forward_port", default=0, help="Forward port for default (root) web server with multiproxy, allowing slidoc sites to overlay a regular website, using '_' prefix for admin")
    define("gapps_url", default="", help="Google app URL, e.g. URL?action=mail_send&to=&subject=&content=")
    define("gsheet_url", default="", help="Google sheet URL1;...")
    define("host", default=Options['host'], help="Server hostname or IP address, specify '' for all (default: localhost)")
    define("import_params", default=Options['import_params'], help="KEY;KEYCOL;SKIP_KEY1,... parameters for importing answers")
    define("insecure_cookie", default=False, help="Insecure cookies (for direct PDF printing)")
    define("lock_proxy_url", default="", help="Proxy URL to lock sheet(s), e.g., http://example.com")
    define("min_wait_sec", default=0, help="Minimum time (sec) between Google Sheet updates")
    define("missing_choice", default=Options['missing_choice'], help="Missing choice value (default: *)")
    define("multisite", default=False, help="Enable multiple sites")
    define("multi_email_id", default=False, help="Allow multiple ids for same email")
    define("notebook_extn", default=Options["notebook_extn"], help="Extension for notebook/journal files (default: ipynb)")
    define("old_auth_key", default='', help="Old auth_key (for key migration)")
    define("plugindata_dir", default=Options["plugindata_dir"], help="Path to plugin data files directory")
    define("plugins", default="", help="List of plugin paths (comma separated)")
    define("private_port", default=Options["private_port"], help="Base private port for multiproxy)")
    define("public_pages", default=Options["public_pages"], help="Public pages (no login required for home page etc., except for _private/_restricted)")
    define("reload", default=False, help="Enable autoreload mode (for updates)")
    define("remote_logging", default=0, help="Remote logging level (0/1/2)")
    define("request_timeout", default=Options["request_timeout"], help="Proxy update request timeout (sec)")
    define("restore_backup", default='', help="back_up_directory,back_up_name (to restore entire site from backup)")
    define("libraries_dir", default=Options["libraries_dir"], help="Path to shared libraries directory, e.g., 'libraries')")
    define("roster_columns", default=Options["roster_columns"], help="Roster column names: lastname_col,firstname_col,midname_col,id_col,email_col,altid_col")
    define("single_site", default="", help="Single site name for testing")
    define("settings_file", default="", help="Site settings file (for single server; name only if config_path is directory)")
    define("sites", default="", help="Site names for multi-site server (comma-separated)")
    define("site_access", default='', help="Site access")
    define("site_label", default='', help="Site label")
    define("site_name", default='', help="Site name")
    define("site_number", default=0, help="Site number")
    define("site_title", default='', help="Site title")
    define("sort_key", default='', help="Site name sort key")
    define("server_nonce", default='', help="Server nonce (random value)")
    define("server_version", default='', help="Server version (for checking)")
    define("server_url", default=Options["server_url"], help="Server URL, e.g., http://example.com")
    define("session_versioning", default=True, help="Session versioning on proxy server, with version updated after modifications (default: True)")
    define("socket_dir", default="", help="Directory for creating unix-domain socket pairs")
    define("source_dir", default=Options["source_dir"], help="Path to source files directory (required for edit/upload)")
    define("ssl", default="", help="SSLcertfile,SSLkeyfile")
    define("start_delay", default=0, help="Delay at start (in sec) to cleanly restart for port binding etc.")
    define("web_dir", default=Options["web_dir"], help="Path to web files directory")
    define("timezone", default=Options["timezone"], help="Local timezone for date/time values, e.g., US/Central")
    define("twitter_config", default="", help="Twitter stream access info: username,consumer_key,consumer_secret,access_key,access_secret;...")
    define("xsrf", default=False, help="XSRF cookies for security")

    define("port", default=Options['port'], help="Web server port", type=int)
    parse_command_line()

    # Set of command line arguments
    cmd_arg_set = set()
    for arg in sys.argv[1:]:
        argname, _, val = arg.lstrip('-').partition('=')
        cmd_arg_set.add(argname)

    if CommandOpts.server_version and CommandOpts.server_version != sliauth.get_version():
        sys.exit('Site %s: ERROR: Expecting server version %s but found %s' % (CommandOpts.site_name, CommandOpts.server_version, sliauth.get_version()))

    if CommandOpts.site_name and CommandOpts.config_digest != Global.config_digest:
        sys.exit('Site %s: ERROR: Config file %s has changed compared to root; start cancelled' % (CommandOpts.site_name, Global.config_file))

    if not CommandOpts.auth_type:
        sys.exit('ERROR: Must specify --auth_type=...; use --auth_type=none if no authentication required')

    if ',' not in CommandOpts.auth_type and CommandOpts.auth_type not in ('none', 'adminonly', 'token'):
        sys.exit('ERROR: Invalid auth_type=%s; must be none|adminonly|token|@example.com|google|twitter,key,secret,,...')

    Global.split_site_opts = {}
    sites = getattr(CommandOpts, 'sites', '')
    if sites:
        # Pre-defined site names
        Global.predefined_sites = sdproxy.split_list(sites, sep=',' if ',' in sites else ';') # Allow comma separation for backwards compatibility
        CommandOpts.multisite = True

        # Handle split options for backwards compatibility
        for key in SITE_OPTS:
            optval = getattr(CommandOpts, key, '')
            if ';' in optval:
                comps = optval.split(';')
                if len(comps) != len(Global.predefined_sites):
                    sys.exit('ERROR: Incorrect number of values for site option %s=%s: expecting %d values' % (key, optval, len(Global.predefined_sites)))
                Global.split_site_opts[key] = {}
                for j, sname in enumerate(Global.predefined_sites):
                    Global.split_site_opts[key][sname] = comps[j]
                setattr(CommandOpts, key, '')
        
    Root_server = CommandOpts.multisite and not CommandOpts.site_number

    if CommandOpts.multisite and CommandOpts.single_site:
        Global.predefined_sites = [ CommandOpts.single_site ]
        if Root_server:
            print >> sys.stderr, 'DEBUG: sdserver.main: SINGLE SITE TESTING', CommandOpts.single_site

    if CommandOpts.site_name or not CommandOpts.multisite:
        Global.site_settings_file, Global.site_settings = get_site_settings(CommandOpts.site_name, CommandOpts, cmd_arg_set)


    if Root_server:
        # Create sites
        site_names = Global.predefined_sites[:]
        if os.path.isdir(Global.config_path) and not CommandOpts.single_site:
            # Initialize additional sites from config directory filenames
            snames = sorted(glob.glob(Global.config_path+'/[!_]*.json'))
            for spath in snames:
                site_name = os.path.splitext(os.path.basename(spath))[0]
                if not sliauth.SITE_NAME_RE.match(site_name):
                    sys.exit('Invalid site name %s in %s; site name must start with letter and include only letters/digits/hyphens' % (site_name, Global.config_path))
                if site_name not in site_names:
                    site_names.append(site_name)

        for site_name in site_names:
            _, site_settings = get_site_settings(site_name, CommandOpts, cmd_arg_set)
            for key in SITE_OPTS:
                # Handle split options for backwards compatibility
                if key in Global.split_site_opts and site_name in Global.split_site_opts[key]:
                    if site_settings[key]:
                        # Site config overrides root config
                        del Global.split_site_opts[key][site_name]
                    else:
                        site_settings[key] = Global.split_site_opts[key][site_name]
            root_add_site(site_name, site_settings)

    for key in Options:
        # Set site options and other options
        if key.startswith('_'):
            continue

        if key in Global.site_settings:
            Options[key] = Global.site_settings[key]
        elif hasattr(CommandOpts, key):
            # Root config + command line
            Options[key] = getattr(CommandOpts, key)

    if not Options['dry_run'] and not Root_server:
        if not Options['gsheet_url'] and Options['auth_type'] != 'none':
            sys.exit('Site %s: ERROR: Must specify gsheet_url for proxied site in config file' % (Options['site_name']))

    if Options['auth_type'] == 'none':
        if not Options['auth_key']:
            Options['auth_key'] = 'testkey'
    else:
        if not Options['auth_key']:
            sys.exit("ERROR: --auth_key=... must be specified for authentication")

        if not Options['server_url'].startswith('http://localhost:'):
            if len(Options['auth_key']) < 20:
                sys.exit("ERROR: --auth_key=... must be a RANDOM string with at least 20 characters (use sliauth.py -g to generate it)")
                

    if not CommandOpts.multisite and CommandOpts.single_site:
        # Single site selected from multisite config
        Options['auth_key'] = sliauth.gen_site_key(Options['auth_key'], CommandOpts.single_site)

    Options['root_auth_key'] = Options['auth_key']
    if Options['site_number']:
        Options['auth_key'] = sliauth.gen_site_key(Options['root_auth_key'], Options['site_name'])

    if Options['server_url'].startswith('http://localhost:'):
        Options['server_nonce'] = ''
        Options['server_key'] = Options['root_auth_key'] or 'testkey'
    else:
        if not Options['site_number']:
            Options['server_nonce'] = str(sliauth.gen_random_number())
        Options['server_key'] = sliauth.gen_server_key(Options['root_auth_key'], Options['server_nonce'])
        
    if not CommandOpts.debug:
        logging.getLogger('tornado.access').disabled = True

    if CommandOpts.auth_users:
        Global.userRoles.update_root_roles(CommandOpts.auth_users)

    if Options['restore_backup']:
        Options['restore_backup'] = Options['restore_backup'].split(',')
        if len(Options['restore_backup']) != 2:
            sys.exit('ERROR: Restore backup should be of the form : back_up_directory,back_up_name')
        if not os.path.isdir(Options['restore_backup'][0]):
            sys.exit('ERROR: Backup directory %s for restore not found' % Options['restore_backup'][0])

        if Options['gsheet_url'] and not Options['site_number']:
            confirm = raw_input('CAUTION: To confirm Google Sheet restore from backup directory %s, please re-enter full directory name: ' % Options['restore_backup'][0])
            if confirm.strip() != Options['restore_backup'][0]:
                sys.exit('ERROR: Cancelled restore from %s' % Options['restore_backup'][0])

    pluginsDir = scriptdir + '/plugins'
    pluginPaths = [pluginsDir+'/'+fname for fname in os.listdir(pluginsDir) if fname[0] not in '._' and fname.endswith('.py')]
    if CommandOpts.plugins:
        # Plugins with same name will override earlier plugins
        pluginPaths += CommandOpts.plugins.split(',')

    plugins = []
    for pluginPath in pluginPaths:
        pluginName = os.path.basename(pluginPath).split('.')[0]
        plugins.append(pluginName)
        importlib.import_module('plugins.'+pluginName)

    socket_name_fmt = CommandOpts.socket_dir + '/uds_socket'

    Global.child_procs = OrderedDict()

    if CommandOpts.backup:
        comps = CommandOpts.backup.split(',')
        Options['backup_dir'] = comps[0]
        Options['backup_hhmm'] = comps[1] if len(comps) > 1 else '03:00'
        Options['backup_options'] = comps[2:]

    BaseHandler.setup_dirs(Options['site_name'])

    if Options['site_number']:
        # Start secondary server
        site_server_setup()
        start_server(Options['site_number'])
        print >> sys.stderr, '****Exiting secondary server', Options['site_name']
        return

    # Single or primary server
    if len(Options['roster_columns'].split(',')) != 6:
        sys.exit('ERROR: Must specify --roster_columns=lastname_col,firstname_col,midname_col,id_col,email_col,altid_col')

    print >> sys.stderr, ''
    print >> sys.stderr, 'sdserver: Version %s **********************************************' % sliauth.get_version()
    if CommandOpts.timezone:
        os.environ['TZ'] = CommandOpts.timezone
        time.tzset()
        print >> sys.stderr, 'sdserver: Timezone =', CommandOpts.timezone, sliauth.iso_date(nosubsec=True)

    print >> sys.stderr, 'sdserver: ---------- AUTHENTICATION %s ----------' % CommandOpts.auth_type.split(',')[0]

    if Options['email_addr']:
        print >> sys.stderr, 'sdserver: admin email', Options['email_addr']

    if sliauth.RESTRICTED_SESSIONS_RE:
        print >> sys.stderr, 'sdserver: Restricted sessions matching:', '('+'|'.join(sliauth.RESTRICTED_SESSIONS)+')'
    if Global.config_path:
        print >> sys.stderr, 'sdserver: Config path =', Global.config_path

    if Options['server_url']:
        print >> sys.stderr, 'sdserver: Server URL =', Options['server_url']

    print >> sys.stderr, 'sdserver: OPTIONS', ', '.join(x for x in ('multisite',) if x in Options and Options[x]), ', '.join(x for x in ('debug', 'dry_run', 'dry_run_file_modify', 'insecure_cookie', 'public_pages', 'reload', 'session_versioning', 'xsrf') if getattr(CommandOpts, x))

    if Options['debug']:
        print >> sys.stderr, 'sdserver: SERVER_NONCE =', Options['server_nonce']
    if plugins:
        print >> sys.stderr, 'sdserver: Loaded plugins: '+', '.join(plugins)
    if CommandOpts.start_delay:
        print >> sys.stderr, 'sdserver: Start DELAY = %s sec ...' % CommandOpts.start_delay
        time.sleep(CommandOpts.start_delay)
    print >> sys.stderr, ''

    if CommandOpts.forward_port:
        Global.relay_forward = ('localhost', forward_port)

    Options['ssl_options'] = None
    if CommandOpts.port % 1000 == 443:
        if not CommandOpts.ssl:
            sys.exit('SSL options must be specified for http port ending in 443')
        certfile, keyfile = CommandOpts.ssl.split(',')
        Options['ssl_options'] = {"certfile": certfile, "keyfile": keyfile}

    if Options['multisite']:
        # Start secondary servers
        print >> sys.stderr, 'DEBUG: sdserver.main:', SiteOpts.keys()
        for j, site_name in enumerate(SiteOpts.keys()):
            gsheet_url = SiteOpts[site_name]['gsheet_url']
            SiteProps.root_site_setup(j+1, site_name, gsheet_url)
            root_start_secondary(j+1, site_name)
        print >> sys.stderr, 'DEBUG: sdserver.relay:', [SiteProps.relay_map(j) for j in range(1+len(SiteOpts))]

        print >> sys.stderr, 'DEBUG: sdserver.userRoles:', Global.userRoles.root_role, Global.userRoles.site_roles, Global.userRoles.external_users
        start_multiproxy()

    else:
        # Setup single site server
        SiteProps.root_site_setup(0, '', Options['gsheet_url'])
        site_server_setup()

    if CommandOpts.multi_email_id:
        print >> sys.stderr, 'DEBUG: sdserver.id2email: Allowing multiple ids for a single email address'
        Global.email2id = defaultdict(lambda : defaultdict(list))
        id2email = {}
        for siteName, rosterMaps in SiteProps.siteRosterMaps.items():
            for idVal, emailVal in rosterMaps.get('id2email',{}).items():
                if idVal in id2email:
                    print >> sys.stderr, 'sdserver.id2email: ERROR Ignored conflicting emails for id %s: %s vs. %s' (idVal, id2email[idVal], siteName+':'+emailVal)
                elif emailVal:
                    id2email[idVal] = siteName+':'+emailVal
                    Global.email2id[emailVal][idVal].append(siteName)

    # Root/primary controls backup
    setup_backup()
    
    # Start primary server
    start_server()
    print >> sys.stderr, '****Exiting root/primary server'

if __name__ == "__main__":
    main()
