"""
Python proxy supporting 

Caches an in-memory copy of Google Sheet sheets and updates them using the same REST interface as slidoc_sheets.js.

Updates the Google Sheets version, using one active REST request at a time.

admin commands:
    /_status                 Display update status
    /_clear                  Clear cache
    /_backup/dir             Backup to directory (append timestamp, if dir ends with a hyphen)
    /_shutdown               Initiate clean shutdown (transmitting cache updates)
    /_lock/session           Lock session (before direct editing of Google Sheet)
    /_unlock/session         Unlock session (after direct edits are completed)
    /_lock                   List locked sessions (* => still trasmitting cache updates)
    /_getcol/session;colname   Return column
    /_getrow/session;rowid     Return row
"""
from __future__ import print_function

import base64
import cStringIO
import csv
import datetime
import functools
import io
import json
import math
import os
import pprint
import random
import re
import sys
import time
import urllib
import urllib2
import uuid

from collections import defaultdict, OrderedDict

import tornado.httpclient
from tornado.ioloop import IOLoop

import sliauth

UPDATE_PARTIAL_ROWS = True

scriptdir = os.path.dirname(os.path.realpath(__file__))

# Usually modified by importing module
Settings = {
    'update_time': '',
                          # Site specific settings from server
    'auth_key': '',     # Site digest authentication key
    'gsheet_url': '',   # Site google Sheet URL

    'site_name': '',      # Site name
    'site_access': '',    # '' OR 'adminonly' OR 'adminguest' OR 'locked' OR 'inactive'

    'site_label': '',
    'site_title': '',

    'admin_users': '',
    'grader_users': '',
    'guest_users': '',

    'server_url': '',     # Base URL of server (if any); e.g., http://example.com'
    'lock_date': '',    # Date when all user mods are disabled
    'end_date': '',       # Date when all mods are disabled

    'no_login_token': False,
    'no_late_token': False,
    'no_roster': False,
    'log_call': '',        # > 0 to log calls to sheet call_log; may generate large output over time

    'gradebook_release': '', # List of released items: average,cumulative_total,cumulative_grade (comma-separated)

                          # General settings from server
    'debug': '',
    'dry_run': '',      # Dry run (read from, but do not update, Google Sheets)
    'email_addr': '',
    'gapps_url': '',
    'root_users': [],

    'lock_proxy_url': '', # URL of proxy server to lock sheet (used to "safely" allow direct access to Google Sheets from an auxiliary server)
    'min_wait_sec': 0,    # Minimum time (sec) between successful Google Sheet requests

    'request_timeout': 75,   # Proxy update request timeout (sec)
    }

COPY_FROM_CONFIG = ['gsheet_url', 'site_label', 'site_title', 'site_access',
                    'admin_users', 'grader_users', 'guest_users',
                    'lock_date', 'end_date', 'gradebook_release',
                    'no_login_token', 'no_late_token', 'no_roster', 'log_call',
                   ]
    
COPY_FROM_SERVER = ['auth_key', 'auth_type', 'site_name',  'server_url',
                    'debug', 'dry_run', 'email_addr', 'gapps_url', 'root_users',
                    'lock_proxy_url', 'min_wait_sec', 'request_timeout',]

# Site access:
#  adminonly: Only admin/grader has access
#  adminguest: Only admin/grader and guest users have access
#  locked: no user modifications permitted
#  inactive: script access deactivated

SITE_ADMINONLY = 'adminonly'
SITE_ADMINGUEST = 'adminguest'
SITE_LOCKED = 'locked'
SITE_INACTIVE = 'inactive'
SITE_ACCESS = [SITE_ADMINONLY, SITE_ADMINGUEST, SITE_LOCKED]

DAY_PREFIX = '_day_'
ACTION_FORMULAS = False
TOTAL_COLUMN = 'q_total'        # session total column name (to avoid formula in session sheet)

RETRY_WAIT_TIME = 5             # Minimum time (sec) before retrying failed Google Sheet requests
RETRY_MAX_COUNT = 5             # Maximum number of failed Google Sheet requests
CACHE_HOLD_SEC = 3600           # Maximum time (sec) to hold sheet in cache
MISS_RETRY_SEC = 1800           # Time period between attempts to access missed optional sheets
TIMED_GRACE_SEC = 15            # Grace period for timed submissions (usually about 15 seconds)

PROXY_UPDATE_ROW_LIMIT = 200    # Max. no of rows per sheet, per proxy update request
# (Set to 0 for no limit to update row count, approximating transactional behavior for databases,
#  because remote cache updates occur between web requests, except when shutting down.)

ADMIN_ROLE = 'admin'
GRADER_ROLE = 'grader'

ADMINUSER_ID = 'admin'
MAXSCORE_ID = '_max_score'
AVERAGE_ID = '_average'
RESCALE_ID = '_rescale'
TIMESTAMP_ID = '_timestamp'
TESTUSER_ID = '_test_user'
DISCUSS_ID = '_discuss'

MIN_HEADERS = ['name', 'id', 'email', 'altid']
STATUS_HEADER = 'status'
TEAM_HEADER = 'team'
TWITTER_HEADER = 'twitter'
GRADE_HEADERS = ['total', 'grade', 'numGrade']
COPY_HEADERS = ['source', 'team', 'lateToken', 'lastSlide', 'retakes']

BLOCKED_STATUS = 'blocked'
DROPPED_STATUS = 'dropped'

HIDE_HEADERS = ['attributes', 'questions', 'teams', 'questionConcepts']

TESTUSER_ROSTER = {'name': '#user, test', 'id': TESTUSER_ID, 'email': '', 'altid': '', 'extratime': ''}

SETTINGS_SHEET = 'settings_slidoc'
INDEX_SHEET = 'sessions_slidoc'
ROSTER_SHEET = 'roster_slidoc'
GRADES_SHEET = 'grades_slidoc'
DISCUSS_SHEET = 'discuss_slidoc'

BACKUP_SHEETS = [SETTINGS_SHEET, INDEX_SHEET, ROSTER_SHEET, GRADES_SHEET, DISCUSS_SHEET]

RELATED_SHEETS = ['answers', 'correct', 'discuss', 'stats']
AUXILIARY_SHEETS = ['discuss']    # Related sheets with original content

RESERVED_SUFFIXES = ['log', 'slidoc'] + RELATED_SHEETS

LOG_MAX_ROWS = 500

ROSTER_START_ROW = 2
SESSION_MAXSCORE_ROW = 2                                # Set to zero, if no MAXSCORE row
SESSION_START_ROW = 3 if SESSION_MAXSCORE_ROW else 2

BASIC_PACE    = 1
QUESTION_PACE = 2
ADMIN_PACE    = 3

SKIP_ANSWER = 'skip'
LATE_SUBMIT = 'late'
FUTURE_DATE = 'future'

USERID_RE = re.compile(r'^[-\w.@]+$')

PLUGIN_RE = re.compile(r"^(.*)=\s*(\w+)\.(expect|response)\(\s*(\d*)\s*\)$")
QFIELD_RE = re.compile(r"^q(\d+)_([a-z]+)$")
QFIELD_MOD_RE = re.compile(r"^(q_other|q_comments|q(\d+)_(comments|grade))$")
QFIELD_TOTAL_RE = re.compile(r"^(q_scores|q_other|q(\d+)_grade)$")

ANSWER_POST = 'answer'
DELETED_POST = 'deleted'
FLAGGED_POST = 'flagged'

# Post|team|number|state1,state2|yyyy-mm-ddThh:mm text
POST_MAKE_FMT = '%s%s|%03d|%s|%s %s'
POST_PREFIX_RE = re.compile(r'^Post:([\w-]*)\|(\d+)\|([,\w-]*)\|([-\d:T]+)(\s|$)')
POST_NUM_RE    = re.compile(       r'([\w-]*)\|(\d+)\|([,\w-]*)\|([-\d:T]+)([\s\S]*)$')
TEAMNAME_RE = re.compile(r'[\w-]+')

class Dummy():
    pass
    
Sheet_cache = {}    # Cache of sheets
Miss_cache = {}     # For optional sheets that are missing
Lock_cache = {}     # Locked sheets
Lock_passthru = defaultdict(int)  # Count of passthru

Locked_proxy_sheets = set()  # Set of sheets locked on upstream proxy

Global = Dummy()

Global.remoteVersions = set()
Global.dryDeletedSheets = set()
Global.shuttingDown = False
Global.updatePartial = UPDATE_PARTIAL_ROWS

Global.displayNameMap = {}

Global.gradebookActive = False
Global.accessCodeCallback = None
Global.teamSetupCallback = None
Global.discussPostCallback = None


def mapDisplayName(userId, displayName):
    if displayName and (',' in displayName or userId not in Global.displayNameMap):
        # Comma-formatted names override
        Global.displayNameMap[userId] = displayName

def getDisplayNames(includeNonRoster=False):
    # Returns id->name mapping, sorted by name
    rosterNameMap = lookupRoster('name')
    if rosterNameMap is None and not includeNonRoster:
        return None
    nameMap = Global.displayNameMap.copy() if includeNonRoster else {}
    if rosterNameMap:
        nameMap.update(rosterNameMap)
    return OrderedDict(sorted(nameMap.items(), key=lambda x:x[1]))


def initProxy(gradebookActive=False, accessCodeCallback=None, teamSetupCallback=None, discussPostCallback=None):
    Global.gradebookActive = gradebookActive
    Global.accessCodeCallback = accessCodeCallback
    Global.teamSetupCallback = teamSetupCallback
    Global.discussPostCallback = discussPostCallback

def copySiteConfig(siteConfig):
    for key in COPY_FROM_CONFIG:
        if key in siteConfig:
            Settings[key] = siteConfig[key]
    Settings['update_time'] = sliauth.create_date()

def copyServerOptions(serverOptions):
    for key in COPY_FROM_SERVER:
        Settings[key] = serverOptions[key]

def split_list(list_str, sep=',', lower=False, keep_null=False):
    # Split comma-separated list, stripping it
    if lower:
        list_str = list_str.lower()
    if keep_null:
        return [x.strip() for x in list_str.split(sep)]
    else:
        return [x.strip() for x in list_str.split(sep) if x.strip()]
    
def delSheet(sheetName, deleteRemote=False):
    Sheet.relateSheet(sheetName, remove=True)

    for cache in (Sheet_cache, Miss_cache, Lock_cache, Lock_passthru):
        if sheetName in cache:
            del cache[sheetName]

    if deleteRemote:
        if Settings['dry_run']:
            Global.dryDeletedSheets.add(sheetName)
        elif Settings['gsheet_url']:
            user = ADMINUSER_ID
            userToken = gen_proxy_token(user, ADMIN_ROLE)
            delParams = {'sheet': sheetName, 'delsheet': '1', 'admin': user, 'token': userToken}
            retval = sliauth.http_post(Settings['gsheet_url'], delParams)
            print('sdproxy.delSheet: %s: %s' % (sheetName, retval), file=sys.stderr)
            if retval['result'] != 'success':
                return False
    return True


def initCache():
    Sheet_cache.clear()
    Miss_cache.clear()
    Lock_cache.clear()
    Lock_passthru.clear()

    Global.httpRequestId = ''
    Global.notifiedAdmin = ''

    Global.cacheResponseTime = 0
    Global.cacheUpdateTime = sliauth.epoch_ms()
    Global.cacheUpdateError = ''

    Global.totalCacheResponseInterval = 0
    Global.totalCacheResponseCount = 0
    Global.totalCacheRetryCount = 0
    Global.totalCacheRequestBytes = 0
    Global.totalCacheResponseBytes = 0

    Global.cachePendingUpdate = None
    Global.suspended = ''
    Global.previewStatus = {}

    Global.transactSessions = {}

initCache()

def transactionalSession(sessionName):
    return sessionName in Global.transactSessions

def previewOrTransactionalSession(sessionName):
    return sessionName in Global.transactSessions or sessionName == Global.previewStatus.get('sessionName')

def startTransactSession(sessionName):
    # (Delay upstream updates to session sheet; also lock index sheet row for the session)
    if Global.suspended:
        return 'Cannot transact when cache is suspended'

    if sessionName == previewingSession():
        return 'Cannot transact when previewing session '+sessionName

    if sessionName in Global.transactSessions:
        raise Exception('Transaction already active for sheet %s' % sessionName)

    sessionSheet = getSheet(sessionName)
    if not sessionSheet:
        raise Exception('Transact sheet %s not in cache' % sessionName)
    Global.transactSessions[sessionName] = sessionSheet.copy()
    if Settings['debug']:
        print("DEBUG:startTransactSession: %s " % sessionName, file=sys.stderr)

    return ''

def rollbackTransactSession(sessionName, noupdate=False):
    # Revert to session state at start of transaction
    if sessionName not in Global.transactSessions:
        return
    Sheet_cache[sessionName] = Global.transactSessions[sessionName]
    endTransactSession(sessionName, noupdate=noupdate)
    if Settings['debug']:
        print("DEBUG:rollbackTransactSession: %s " % sessionName, file=sys.stderr)

def endTransactSession(sessionName, noupdate=False):
    # End transaction and schedule cache updates (unless noupdate is True)
    if sessionName not in Global.transactSessions:
        return
    del Global.transactSessions[sessionName]
    if not noupdate:
        schedule_update(force=True)
    if Settings['debug']:
        print("DEBUG:endTransactSession: %s " % sessionName, file=sys.stderr)

def previewingSession():
    return Global.previewStatus.get('sessionName', '')

def startPreview(sessionName, rollingOver=False):
    # Initiate preview of session
    # (Delay upstream updates to session sheet and index sheet; also lock all index sheet rows except for this session)
    # Return error message or null string
    if not sessionName:
        raise Exception('Null session name for preview')

    if Global.previewStatus:
        return 'Cannot start preview for %s during active preview for %s' % (sessionName, Global.previewStatus['sessionName'])

    if sessionName in Global.transactSessions:
        return 'Cannot start preview during transact session '+sessionName
    
    if Global.suspended:
        return 'Cannot preview when cache is suspended'

    if Lock_passthru or Lock_cache:
        return 'Cannot preview when lock_passthru session or locked sessions'

    if sessionName in Miss_cache:
        del Miss_cache[sessionName]
    sessionSheet = Sheet_cache.get(sessionName)
    if sessionSheet:
        if sessionSheet.get_updates() is not None:
            if Global.cacheUpdateError:
                return 'Cache update error (%s); need to restart server' % Global.cacheUpdateError
            return 'PENDING:Pending updates for session %s; retry preview after about 5 seconds (reqid=%s)' % (sessionName, Global.httpRequestId)
    else:
        sessionSheet = getSheet(sessionName)

    indexSheet = Sheet_cache.get(INDEX_SHEET)
    if indexSheet:
        if indexSheet.get_updates() is not None and not rollingOver:
            return 'PENDING:Pending updates for sheet '+INDEX_SHEET+'; retry preview after about 5 seconds'
    else:
        indexSheet = getSheet(INDEX_SHEET)

    Global.previewStatus = {'sessionName': sessionName, 'sessionSheetOrig': sessionSheet.copy() if sessionSheet else None,
                            'indexSheetOrig': indexSheet.copy() if indexSheet else None}

    if Settings['debug']:
        print("DEBUG:startPreview: %s " % sessionName, file=sys.stderr)

    return ''

def endPreview(noupdate=False):
    # End preview; enable upstream updates
    if not Global.previewStatus:
        return
    if Settings['debug']:
        print("DEBUG:endPreview: %s " % Global.previewStatus.get('sessionName'), file=sys.stderr)
    Global.previewStatus = {}
    if not noupdate:
        schedule_update(force=True)

def savePreview():
    # Save snapshot of preview (usually after compiling)
    sessionName = Global.previewStatus.get('sessionName', '')
    if not sessionName:
        raise Exception('No preview session to save')
    sessionSheet = Sheet_cache.get(sessionName)
    if not sessionSheet:
        raise Exception('Preview session %s sheet not cached for saving' % sessionName)
    indexSheet = Sheet_cache.get(INDEX_SHEET)
    if not indexSheet:
        raise Exception('Preview index sheet not cached to save')
    Global.previewStatus['sessionSheetSave'] = sessionSheet.copy()
    Global.previewStatus['indexSheetSave'] = indexSheet.copy()

def revertPreview(saved=False, noupdate=False):
    # Discard all changes to session sheet and session index sheet and revert to original (or saved) sheet values
    # and end preview
    sessionName = Global.previewStatus.get('sessionName', '')
    if not sessionName:
        raise Exception('No preview session to revert')

    if saved:
        Sheet_cache[sessionName] = Global.previewStatus['sessionSheetSave']
        Sheet_cache[INDEX_SHEET] = Global.previewStatus['indexSheetSave']
    else:
        if Global.previewStatus['sessionSheetOrig']:
            Sheet_cache[sessionName] = Global.previewStatus['sessionSheetOrig']
        else:
            delSheet(sessionName)
        if Global.previewStatus['indexSheetOrig']:
            Sheet_cache[INDEX_SHEET] = Global.previewStatus['indexSheetOrig']
        else:
            delSheet(INDEX_SHEET)

    endPreview(noupdate=noupdate)

def freezeCache(fill=False):
    # Freeze cache (clear when done)
    if Global.previewStatus:
        raise Exception('Cannot freeze when previewing session '+Global.previewStatus['sessionName'])
    elif Global.transactSessions:
        raise Exception('Cannot freeze when transacting sessions '+str(Global.transactSessions.keys()))

    if Global.suspended == 'freeze':
        return
    if fill:
        # Fill cache
        sessionNames = []
        for sheetName in BACKUP_SHEETS:
            sheet = getSheet(sheetName)
            if sheet and sheetName == INDEX_SHEET:
                sessionNames = getColumns('id', sheet)

        for sheetName in sessionNames:
            sessionSheet = getSheet(sheetName)
    suspend_cache('freeze')


def backupSheets(dirpath):
    # Returns null string on success or error string list
    # (synchronous)
    if Global.previewStatus:
        return [ 'Cannot backup when previewing session '+Global.previewStatus['sessionName'] ]

    suspend_cache('backup')
    if Settings['debug']:
        print("DEBUG:backupSheets: %s started %s" % (dirpath, datetime.datetime.now()), file=sys.stderr)
    errorList = []
    try:
        if not os.path.exists(dirpath):
            os.makedirs(dirpath)

        sessionAttributes = None
        for sheetName in BACKUP_SHEETS:
            rows = backupSheet(sheetName, dirpath, errorList, optional=True)
            if sheetName == INDEX_SHEET and rows and 'id' in rows[0]:
                try:
                    idCol = rows[0].index('id')
                    attributesCol = rows[0].index('attributes')
                    sessionAttributes = [(row[idCol], json.loads(row[attributesCol])) for row in rows[1:]]
                except Exception, excp:
                    errorList.append('Error: Session attributes not loadable %s' % excp)

        if sessionAttributes is None and not errorList:
            errorList.append('Error: Session attributes not found in index sheet %s' % INDEX_SHEET)

        for name, attributes in (sessionAttributes or []):
            backupSheet(name, dirpath, errorList)
            if attributes.get('discussSlides'):
                backupSheet(name+'_discuss', dirpath, errorList, optional=True)
    except Exception, excp:
        errorList.append('Error in backup: '+str(excp))

    suspend_cache('')
    return errorList


def backupCell(value):
    if value is None:
        return ''
    if isinstance(value, datetime.datetime):
        return sliauth.iso_date(value, utc=True)
    if isinstance(value, unicode):
        return value.encode('utf-8')
    return str(value)


def backupSheet(name, dirpath, errorList, optional=False):
    if not isFormulaSheet(name) and name in Sheet_cache:
        rows = Sheet_cache[name].xrows   # Not a copy

    else:
        retval = downloadSheet(name, backup=True)

        if retval['result'] != 'success':
            errorList.append('Error in downloading %s sheet %s: %s' % (Settings['site_name'], name, retval['error']))
            return None

        rows = retval.get('value')
        if not rows:
            if not optional:
                errorList.append('Error in downloading %s sheet %s: sheet empty or not accessible' % (Settings['site_name'], name))
            return None

    try:
        rowNum = 0
        with open(dirpath+'/'+name+'.csv', 'wb') as csvfile:
            writer = csv.writer(csvfile)
            for j, row in enumerate(rows):
                rowNum = j+1
                rowStr = [backupCell(x) for x in row]
                writer.writerow(rowStr)
    except Exception, excp:
        errorList.append('Error in saving sheet %s (row %d): %s' % (name, rowNum, excp))
        return None

    return rows


def isReadOnly(sheetName):
    return (sheetName.endswith('_slidoc') and sheetName not in (INDEX_SHEET, ROSTER_SHEET, DISCUSS_SHEET))

def isFormulaSheet(sheetName):
    return sheetName == GRADES_SHEET or (not TOTAL_COLUMN and sheetName not in (INDEX_SHEET, ROSTER_SHEET))

def refreshGradebook(sessionName):
    if previewOrTransactionalSession(sessionName):
        return False
    scoreSheet = Sheet_cache.get(GRADES_SHEET)
    if not scoreSheet:
        return False
    if '_'+sessionName not in scoreSheet.xrows[0]:
        return False
    scoreSheet.expire()
    return True

def getSheetCache(sheetName):
    # Return cached sheet, if present (for Google Sheets compatibility)
    return getSheet(sheetName)


def getKeyHeader(sheetName):
    if sheetName.startswith('settings_') or sheetName.endswith('_log'):
        return ''
    comps = sheetName.split('_')
    if len(comps) > 1 and comps[-1] in ('answers', 'correct', 'stats'):
        return ''
    return 'id'


def upstreamLockable(sheetName):
    # Check if sheet should be locked of upstream proxy
    return Settings['lock_proxy_url'] and not sheetName.endswith('_log') and (not sheetName.endswith('_slidoc') or sheetName in (INDEX_SHEET, ROSTER_SHEET))

def lockUpstreamProxy(sheetName, unlock=False):
    # Lock (or unlock) sheet in upstream proxy
    lockURL = Settings['lock_proxy_url']
    if Settings['site_name']:
        lockURL += '/' + Settings['site_name']
    lockURL += '/_%s/%s' % ('unlock' if unlock else 'lock', sheetName)
    req = urllib2.Request(lockURL+'?token='+Settings['auth_key']+'&type=proxy')
    response = urllib2.urlopen(req)
    if unlock:
        Locked_proxy_sheets.discard(sheetName)
    else:
        Locked_proxy_sheets.add(sheetName)
    if Settings['debug']:
        print("DEBUG:lockUpstreamProxy: %s %s %s (%s)" % (unlock, sheetName, lockURL, response.read()), file=sys.stderr)

def getSheet(sheetName, require=False, backup=False, display=False):
    cached = sheetName in Sheet_cache

    if not display or not cached:
        check_if_locked(sheetName, get=True, backup=backup, cached=cached)

    if cached:
        return Sheet_cache[sheetName]
    elif not require and sheetName in Miss_cache:
        # Wait for minimum time before re-checking for sheet
        if not backup and (sliauth.epoch_ms() - Miss_cache[sheetName]) < 1000*MISS_RETRY_SEC:
            return None
        # Retry retrieving sheet
        del Miss_cache[sheetName]

    if upstreamLockable(sheetName):
        try:
            lockUpstreamProxy(sheetName)
        except Exception, excp:
            errMsg = 'ERROR:getSheet: Unable to lock sheet '+sheetName+': '+str(excp)
            print(errMsg, file=sys.stderr)
            raise Exception(errMsg)
        time.sleep(6)

    # Retrieve sheet
    if Settings['debug'] and not Settings['gsheet_url']:
        return None

    retval = downloadSheet(sheetName)

    if retval['result'] != 'success':
        raise Exception("%s (Error in accessing sheet '%s')" % (retval['error'], sheetName))

    rows = retval.get('value')
    if not rows:
        if require:
            raise Exception("Error: Sheet '%s' empty or not accessible" % sheetName)
        Miss_cache[sheetName] = sliauth.epoch_ms()
        return None

    Sheet_cache[sheetName] = Sheet(sheetName, rows, keyHeader=getKeyHeader(sheetName), updated=True,
                                   relatedSheets=retval.get('info',{}).get('sheetsAvailable',[]))
    return Sheet_cache[sheetName]

def downloadSheet(sheetName, backup=False):
    # Download sheet synchronously
    # If backup, retrieve formulas rather than values
    if Global.previewStatus.get('sessionName') == sheetName:
        raise Exception('Cannot download when previewing session '+Global.previewStatus['sessionName'])

    if Settings['dry_run'] and sheetName in Global.dryDeletedSheets:
        return  {'result': 'success', 'value': []}

    user = ADMINUSER_ID
    userToken = gen_proxy_token(user, ADMIN_ROLE)

    getParams = {'sheet': sheetName, 'proxy': '1', 'get': '1', 'all': '1', 'admin': user, 'token': userToken}
    if backup:
        getParams['formula'] = 1

    if parseNumber(Settings['log_call']) and parseNumber(Settings['log_call']) > 1:
        getParams['logcall'] = str(Settings['log_call'])

    ##if Settings['debug']:
    ##    print("DEBUG:downloadSheet", sheetName, getParams, file=sys.stderr)

    if Settings['gsheet_url']:
        retval = sliauth.http_post(Settings['gsheet_url'], getParams, add_size_info=True)
    else:
        retval =  {'result': 'error', 'error': 'No Sheet URL'}

    if Settings['debug'] and Settings['dry_run']:
        print("DEBUG:downloadSheet", sheetName, retval['result'], retval.get('info',{}).get('version'), retval.get('bytes'), retval.get('messages'), file=sys.stderr)

    remoteVersion = retval.get('info',{}).get('version','')
    if sliauth.get_version(sub=1) != sliauth.sub_version(remoteVersion):
        suspend_cache('version_mismatch')
    Global.remoteVersions.add(remoteVersion)

    return retval

def createSheet(sheetName, headers, overwrite=False, rows=[]):
    # Overwrite should be true only for related sheets without original content (e.g., _answers, _correct, _stats)
    check_if_locked(sheetName)

    if not headers:
        raise Exception("Must specify headers to create sheet %s" % sheetName)

    sheet = getSheet(sheetName)

    if sheet:
        if overwrite:
            delSheet(sheetName, deleteRemote=True)
        else:
            raise Exception("Cannote create sheet %s because it is already present in the cache" % sheetName)

    if Settings['dry_run'] and sheetName in Global.dryDeletedSheets:
        Global.dryDeletedSheets.discard(sheetName)

    Sheet.relateSheet(sheetName)

    Sheet_cache[sheetName] = Sheet(sheetName, [headers]+rows, keyHeader=getKeyHeader(sheetName), modTime=sliauth.epoch_ms())
    Sheet_cache[sheetName].modifiedSheet()
    return Sheet_cache[sheetName]


class Sheet(object):
    # Implements a simple spreadsheet with fixed number of columns
    @classmethod
    def relateSheet(cls, sheetName, remove=False):
        sessionName, _, suffix = sheetName.partition('_')
        if suffix not in RELATED_SHEETS:
            return
        sessionSheet = Sheet_cache.get(sessionName)
        if not sessionSheet:
            return
        if not remove and sheetName not in sessionSheet.relatedSheets:
            sessionSheet.relatedSheets.append(sheetName)
        elif remove and sheetName in sessionSheet.relatedSheets:
            sessionSheet.relatedSheets.remove(sheetName)


    def __init__(self, name, rows, keyHeader='', modTime=0, accessTime=None, keyMap=None, actions='', updated=False,
                 deletedRowCount=0, modifiedHeaders=False, relatedSheets=[]):
        # updated => current, i.e., just created from downloaded sheet
        # modifiedHeaders => headers different from before
        if not rows:
            raise Exception('Must specify at least header row for sheet')
        self.name = name
        self.keyHeader = keyHeader
        self.deletedRowCount = deletedRowCount
        self.modTime = modTime
        self.accessTime = sliauth.epoch_ms() if accessTime is None else accessTime
        self.relatedSheets = relatedSheets[:]

        self.actionsRequested = [x.strip() for x in actions.split(',')] if actions else []
        self.modifiedHeaders = modifiedHeaders

        self.readOnly = isReadOnly(name)
        self.holdSec = CACHE_HOLD_SEC

        self.nCols = len(rows[0])

        for j, row in enumerate(rows[1:]):
            if len(row) != self.nCols:
                raise Exception('Incorrect number of cols in row %d: expected %d but found %d' % (j+1, self.nCols, len(row)))

        self.xrows = [ row[:] for row in rows ]  # Shallow copy

        if not self.keyHeader:
            self.keyCol= 0
        else:
            if not self.xrows:
                raise Exception('Must specify at least header row for keyed sheet')

            headers = self.xrows[0]
            self.keyCol = 1 + headers.index(self.keyHeader)

            for j, colName in enumerate(headers):
                if colName.endswith('Timestamp') or colName.lower().endswith('date') or colName.lower().endswith('time'):
                    for row in self.xrows[1:]:
                        if row[j] and not isinstance(row[j], datetime.datetime):
                            # Parse time string
                            row[j] = createDate(row[j])

        self.update_total_formula()

        if keyMap is not None:
            # Create 3-level copy of key map
            self.keyMap = dict( (k, [v[0], v[1], v[2].copy()]) for k, v in keyMap.items() )
        else:
            # New key map
            inserted = 0 if updated else 1
            self.keyMap = {}
            for j, row in enumerate(self.xrows[1:]):
                key = row[self.keyCol-1] if self.keyCol else j+2+self.deletedRowCount
                self.keyMap[key] = [modTime, inserted, set()]  # [modTime, insertedFlag, modColsSet]

        if self.keyCol and 1+len(self.keyMap) != len(self.xrows):
            raise Exception('Duplicate key in initial rows for sheet %s: %s' % (self.name, [x[self.keyCol-1] for x in self.xrows[1:]]))

        if not updated:
            self.modifiedSheet(modTime)

        if self.totalCols and len(self.xrows) > 1:
            # Recompute total column, and update remote sheet if necessary
            for rowNum in range(2,len(self.xrows)+1):
                self.update_total(rowNum)  # Will update row and sheet mod times, as needed

            if Settings['debug']:
                headers = self.xrows[0]
                print("DEBUG:Sheet %s, %s=sum([%s])" % (self.name, headers[self.totalCols[0]-1], [headers[colNum-1] for colNum in self.totalCols[1:]]), file=sys.stderr)

    def update_total_formula(self):
        self.totalCols = []
        self.totalColSet = set()
        if not self.keyCol:
            return
        headers = self.xrows[0]
        if TOTAL_COLUMN and TOTAL_COLUMN in headers:
            totalCol = 1+headers.index(TOTAL_COLUMN)
            self.totalCols = [ totalCol ]
            for j, header in enumerate(headers[totalCol:]):
                if QFIELD_TOTAL_RE.match(header):
                    self.totalCols.append(j+totalCol+1)
            self.totalColSet = set(self.totalCols)

    def update_total(self, rowNum):
        totalCol = self.totalCols[0]
        row = self.xrows[rowNum-1]     # Not a copy!

        newVal = ''
        if row[self.keyCol-1]:
            # Only compute totals for rows with keys
            try:
                newVal = sum((parseNumber(row[j-1]) or 0) for j in self.totalCols[1:] if row[j-1])
            except Exception, excp:
                print("DEBUG:update_total: Error in computing %s for user %s in session %s " % (TOTAL_COLUMN, row[self.keyCol-1], self.name), file=sys.stderr)
                print("DEBUG:update_total:", [repr(row[j-1]) for j in self.totalCols[1:] if row[j-1]], file=sys.stderr)
                if Settings['debug']:
                    import traceback
                    traceback.print_exc()
                newVal = ''

        if row[totalCol-1] == newVal:
            return False
        # Modify total value
        row[totalCol-1] = newVal
        modTime = sliauth.epoch_ms()
        key = self.xrows[rowNum-1][self.keyCol-1] if self.keyCol else rowNum+self.deletedRowCount
        if not self.keyMap[key][1]:
            # Not inserted row; mark total column as modified
            self.keyMap[key][2].add(totalCol)
        self.keyMap[key][0] = modTime
        self.modifiedSheet(modTime)
        return True

    def copy(self):
        # Returns "shallow" copy
        return Sheet(self.name, self.xrows, keyHeader=self.keyHeader, modTime=self.modTime, accessTime=self.accessTime, keyMap=self.keyMap,
                     deletedRowCount=self.deletedRowCount, actions=','.join(self.actionsRequested), modifiedHeaders=self.modifiedHeaders,
                     relatedSheets=self.relatedSheets)

    def expire(self):
        # Delete after any updates are processed
        self.holdSec = 0

    def requestActions(self, actions=''):
        # Actions to be carried out after cache updates to this sheet are completed
        if actions:
            self.actionsRequested += [x.strip() for x in actions.split(',')]
        else:
            self.actionsRequested = []
        schedule_update()

    def export(self, keepHidden=False, allUsers=False, csvFormat=False, idRename='', altidRename=''):
        headers = self.xrows[0][:]
        if idRename and 'id' in headers:
            headers[headers.index('id')] = idRename
        if altidRename and 'altid' in headers:
            headers[headers.index('altid')] = altidRename

        hideCols = []
        if not keepHidden:
            for k, header in enumerate(headers):
                if header.lower().endswith('hidden') or header in HIDE_HEADERS:
                    hideCols.append(k)
        skipName = None
        if not allUsers and 'name' in headers:
            skipName = headers.index('name')

        dataRows =[]
        for j in range(len(self.xrows)-1):
            # Ensure all rows have the same number of columns
            temRow = self.xrows[j+1][:] + ['']*(len(headers)-len(self.xrows[j+1]))
            if skipName is not None and (not temRow[skipName] or temRow[skipName].startswith('#')):
                continue
            for k in hideCols:
                temRow[k] = 'hidden'
            dataRows.append(temRow)

        if csvFormat:
            memfile = io.BytesIO()
            writer = csv.writer(memfile)
            writer.writerow(headers)
            for row in dataRows:
                writer.writerow([backupCell(x) for x in row])
            content = memfile.getvalue()
            memfile.close()
            return content
        else:
            return [headers] + dataRows

    def getLastColumn(self):
        return self.nCols

    def getLastRow(self):
        return len(self.xrows)

    def getHeaders(self):
        return self.xrows[0] if self.xrows else None
    
    def getRows(self):
        # Return shallow copy
        return [ row[:] for row in self.xrows ]

    def deleteRow(self, rowNum):
        if not self.keyHeader:
            raise Exception('Cannot delete row for non-keyed spreadsheet '+self.name)
        if rowNum < 1 or rowNum > len(self.xrows):
            raise Exception('Invalid row number %s for deletion in sheet %s' % (rowNum, self.name))
        keyValue = self.xrows[rowNum-1][self.keyCol-1]
        self.check_lock_status(keyValue)
        del self.xrows[rowNum-1]
        del self.keyMap[keyValue]
        self.modifiedSheet()

    def deleteRows(self, startRow, nRows):
        if self.keyHeader:
            raise Exception('Cannot delete multiple rows for keyed spreadsheet '+self.name)
        if startRow != 2:
            raise Exception('Invalid start row value '+startRow+' for deleteRows in spreadsheet '+self.name)
        lastDelRow = 2+nRows-1  # Delete rows starting from row 2
        if lastDelRow > len(self.xrows):
            raise Exception('Invalid delete rows %s for deletion in sheet %s (maxrows=%s)' % (nRows, self.name, len(self.xrows)))
        self.xrows = [self.xrows[0]] + self.xrows[lastDelRow:]
        for j in range(nRows):
            key = 2+self.deletedRowCount
            del self.keyMap[key]
            self.deletedRowCount += 1
        self.modifiedSheet()

    def insertRowBefore(self, rowNum, keyValue=None):
        self.check_lock_status(keyValue)
        if self.keyHeader:
            if rowNum < 2 or rowNum > len(self.xrows)+1:
                raise Exception('Invalid row number %s for insertion in sheet %s' % (rowNum, self.name))
        else:
            if rowNum != len(self.xrows)+1:
                raise Exception('Can only append row for non-keyed spreadsheet')

        modTime = sliauth.epoch_ms()
        newRow = ['']*self.nCols

        if self.keyHeader:
            if keyValue is None:
                raise Exception('Must specify key for row insertion in sheet '+self.name)
            if keyValue in self.keyMap:
                raise Exception('Duplicate key %s for row insertion in sheet %s' % (keyValue, self.name))
            newRow[self.keyCol-1] = keyValue
            self.keyMap[keyValue] = [modTime, 1, set()]
        else:
            self.keyMap[rowNum+self.deletedRowCount] = [modTime, 1, set()]

        if self.totalCols:
            newRow[self.totalCols[0]-1] = 0
            
        self.xrows.insert(rowNum-1, newRow)
        self.modifiedSheet(modTime)

    def appendColumns(self, headers):
        self.check_lock_status()
        if self.modifiedHeaders:
            raise Exception('Cannot append columns now while updating sheet '+self.name)
        self.nCols += len(headers)
        self.xrows[0] += headers
        for j in range(1, len(self.xrows)):
            self.xrows[j] += ['']*len(headers)

        self.update_total_formula()
        self.modifiedHeaders = True
        self.modifiedSheet()

    def trimColumns(self, ncols, delayMods=False):
        # Set delayMods to true if appending right after trimming
        self.check_lock_status()
        if self.modifiedHeaders:
            raise Exception('Cannot trim columns now while updating sheet '+self.name)

        modTime = sliauth.epoch_ms()
        self.nCols -= ncols
        trimmedCols = set( range(self.nCols+1, self.nCols+ncols+1) )
        self.xrows[0] = self.xrows[0][:-ncols]
        for j in range(1, len(self.xrows)):
            self.xrows[j] = self.xrows[j][:-ncols]
            if j:
                key = self.xrows[j][self.keyCol-1] if self.keyCol else j+1+self.deletedRowCount
                if self.keyMap[key][2]:
                    self.keyMap[key][2].difference_update(trimmedCols)

        if delayMods:
            return
        self.update_total_formula()
        self.modifiedHeaders = True
        self.modifiedSheet(modTime)

    def checkRange(self, rowMin, colMin, rowCount, colCount):
        rng = [rowMin, colMin, rowCount, colCount]
        if rowMin < 1 or rowMin > len(self.xrows):
            raise Exception('Invalid min row number for range %s in sheet %s (maxrows=%s)' % (rng, self.name, len(self.xrows)))
        if rowCount < 0 or rowCount > len(self.xrows)-rowMin+1:
            raise Exception('Invalid row count for range %s in sheet %s (maxrows=%s)' % (rng, self.name, len(self.xrows)))

        if colMin < 1 or colMin > self.nCols:
            raise Exception('Invalid min col number for range %s in sheet %s (maxcols=%s)' % (rng, self.name, self.nCols))
        if colCount < 0 or colCount > self.nCols-colMin+1:
            raise Exception('Invalid col count for range %s in sheet %s (maxcols=%s)' % (rng, self.name, self.nCols))

    def getRange(self, rowMin, colMin=None, rowCount=None, colCount=None):
        if isinstance(rowMin, (str, unicode)):
            # 'row1:row2' range string
            comps = rowMin.split(':')
            if len(comps) != 2 or not comps[0].isdigit() or not comps[1].isdigit():
                raise Exception('Invalid range "%s"' % rowMin)
            rowMin = int(comps[0])
            rowCount = int(comps[1]) - rowMin + 1
            colMin = 1
            colCount = self.nCols

        if not self.keyHeader:
            # For unkeyed sheets, append blank rows as needed to create range
            rowMax = rowMin+rowCount-1
            if rowMax > len(self.xrows):
                for rowNum in range(len(self.xrows)+1, rowMax+1):
                    self.insertRowBefore(rowNum)

        self.checkRange(rowMin, colMin, rowCount, colCount)
        return Range(self, rowMin, colMin, rowCount, colCount)

    def getSheetValues(self, rowMin, colMin, rowCount, colCount):
        if not self.readOnly:
            # Access time is not updated for read-only files => they will be periodically refreshed
            self.accessTime = sliauth.epoch_ms()
        self.checkRange(rowMin, colMin, rowCount, colCount)
        return [row[colMin-1:colMin+colCount-1] for row in self.xrows[rowMin-1:rowMin+rowCount-1]]

    def check_lock_status(self, keyValue=None):
        if self.readOnly:
            raise Exception('Cannot modify read only sheet '+self.name)

        if self.name == INDEX_SHEET:
            if keyValue and Global.previewStatus and keyValue != Global.previewStatus['sessionName']:
                raise Exception('Cannot modify index values for non-previewed session '+keyValue+' when previewing session '+Global.previewStatus['sessionName'])

            if keyValue in Global.transactSessions:
                raise Exception('Cannot modify index values for transactional session '+keyValue)

        elif Global.previewStatus:
            if self.name == Global.previewStatus['sessionName']+'_discuss':
                raise Exception('Cannot modify discuss sheet %s when previewing session %s' % (self.name, Global.previewStatus['sessionName']))

        check_if_locked(self.name)

    def _setSheetValues(self, rowMin, colMin, rowCount, colCount, values):
        ##if Settings['debug']:
        ##    print("_setSheetValues:", self.name, rowMin, colMin, rowCount, colCount, file=sys.stderr)
        if rowMin < 2:
            raise Exception('Cannot overwrite header row')

        self.checkRange(rowMin, colMin, rowCount, colCount)
        if rowCount != len(values):
            raise Exception('Row count mismatch for _setSheetValues %s: expected %d but found %d' % (self.name, rowCount, len(values)) )

        for j, rowValues in enumerate(values):
            if colCount != len(rowValues):
                raise Exception('Col count mismatch for _setSheetValues %s in row %d: expected %d but found %d' % (self.name, j+rowMin, colCount, len(rowValues)) )

        self.check_lock_status(self.xrows[rowMin-1][self.keyCol-1] if self.keyCol and rowCount==1 else '')

        headers = self.xrows[0]
        modTime = 0
        for irow, rowValues in enumerate(values):
            rowNum = irow+rowMin
            if not self.keyCol:
                keyValue = rowNum+self.deletedRowCount
            else:
                keyValue = self.xrows[irow+rowMin-1][self.keyCol-1]
                if self.keyCol >= colMin and self.keyCol <= colMin+colCount-1:
                    newKeyValue = rowValues[self.keyCol-colMin]
                    if newKeyValue != keyValue:
                        raise Exception('Cannot alter key value %s to %s in sheet %s' % (keyValue, newKeyValue, self.name))

            if self.keyMap[keyValue][1]:
                # Newly inserted row; assume all columns are being updated
                updateSheet = True
                updateTotal = bool(self.totalCols)

            else:
                # Keep track of which columns are being updated
                updateSheet = False
                updateTotal = False
                oldValues = self.xrows[irow+rowMin-1][colMin-1:colMin+colCount-1]
                for icol in range(len(oldValues)):
                    oldValue = oldValues[icol]
                    newValue = rowValues[icol]

                    if isinstance(newValue, datetime.datetime) and isinstance(oldValue, datetime.datetime):
                        isEqual = (sliauth.iso_date(newValue, nosubsec=True) == sliauth.iso_date(oldValue, nosubsec=True))
                    else:
                        isEqual = (newValue == oldValue)

                    if not isEqual:
                        # Column value not equal; expand set of modified columns
                        updateSheet = True
                        diffCol = icol+colMin
                        self.keyMap[keyValue][2].add(diffCol)
                        if diffCol in self.totalColSet:
                            # Column affecting total being updated
                            updateTotal = True

            if updateSheet:
                # At least one column value not equal or inserted row; update row
                modTime = sliauth.epoch_ms()
                self.keyMap[keyValue][0] = modTime
                self.xrows[rowNum-1][colMin-1:colMin+colCount-1] = rowValues

                if updateTotal:
                    if self.update_total(rowNum):
                        refreshGradebook(self.name)
        if modTime:
            self.modifiedSheet(modTime)

    def modifiedSheet(self, modTime=None):
        self.modTime = sliauth.epoch_ms() if modTime is None else modTime
        self.accessTime = self.modTime
        schedule_update()

    def get_updates(self, row_limit=None):
        if self.readOnly:
            return None

        if Global.previewStatus and self.name in (INDEX_SHEET, Global.previewStatus['sessionName']):
            if self.name == INDEX_SHEET:
                origSheet = Global.previewStatus['indexSheetOrig']
            else:
                origSheet = Global.previewStatus['sessionSheetOrig']
            
            if not origSheet:
                # Delay all cache updates for preview/transactional sheet
                return None

            if origSheet is not self:
                # Obtain updates for preview session from original sheet
                return origSheet.get_updates()

        if self.name in Global.transactSessions:
            # Obtain updates for transact session from original sheet
            origSheet = Global.transactSessions[self.name]
            if origSheet is not self:
                return origSheet.get_updates()

        actions = ','.join(self.actionsRequested)
            
        headers = self.xrows[0]
        nameCol = 1+headers.index('name') if 'name' in headers else 0

        incompleteUpdate = False
        updateRows = {}
        updateColSet = set()
        insertNames = []
        insertRows = []
        updateSel = []
        updateElemCount = 0

        colSet, colList, curUpdate = None, None, None
        allKeys = [row[self.keyCol-1] for row in self.xrows[1:] if row[self.keyCol-1]] if self.keyCol else None

        for j, row in enumerate(self.xrows[1:]):
            rowNum = j+2
            key = row[self.keyCol-1] if self.keyCol else rowNum+self.deletedRowCount
            if not key:  # Do not update any non-key rows
                continue

            inserted = self.keyMap[key][1]
            newColSet = self.keyMap[key][2]

            if not inserted and not newColSet:
                # No updates for this unmodified row
                # (Note: this condition will not be true for rows whose updating was skipped due to request limits; see self.complete_update())
                colSet, colList, curUpdate = None, None, None
                continue

            if self.keyCol and row_limit and (len(insertRows) >= row_limit or updateElemCount >= 10*row_limit):
                # Update request limit reached, with at least one update left; delay any actions (for keyed sheets only)
                actions = ''
                incompleteUpdate = True
                break

            # Update key and modtime
            updateRows[key] = self.keyMap[key][0]

            if Global.updatePartial and self.keyCol and not inserted:
                # Partial update (note: do not use partial update for non-keyed sheets as last row number must be valid)
                if colSet is not None and colSet.issuperset(newColSet) and len(colSet)-len(newColSet) <= 2:
                    # Extend "contiguous" block for modified/unmodified row; append to previous row update
                    curUpdate[0].append(key)
                    subRow = [row[jcol-1] for jcol in colList]
                    curUpdate[2].append(subRow)

                else:
                    # New update block for modified row
                    updateColSet.update(newColSet)
                    colSet = newColSet
                    colList = list(colSet)
                    colList.sort()

                    subRow = [row[jcol-1] for jcol in colList]
                    curUpdate = [[key], colList, [subRow] ]   # [keysList, colList, [rowSelected]]
                    updateSel.append(curUpdate)

                updateElemCount += len(colSet)

            else:
                # Full/insertion/non-keyed updates
                colSet, colList, curUpdate = None, None, None
                keyRow = key if self.keyCol else rowNum
                if inserted:
                    # Insert row
                    insertNames.append( [row[nameCol-1] if nameCol else '', keyRow] )
                    insertRows.append( row )
                elif not self.keyCol and updateSel and updateSel[-1][0][-1] == keyRow-1:
                    # Consecutive non-keyed modified row
                    updateSel[-1][0].append(keyRow)
                    updateSel[-1][2].append(row)
                else:
                    # Non-partial or non-keyed; update full rows
                    updateSel.append( [[keyRow], None, [row]] )

        if not insertRows and not updateSel and not actions and not self.modifiedHeaders and (not self.modTime or self.modTime < Global.cacheUpdateTime):
            # No updates
            return None

        # Send updateColList if non-null and non-full row
        updateColList = sorted(list(updateColSet)) if (updateColSet and len(updateColSet) < self.nCols) else None

        updateParams = {'incompleteUpdate': incompleteUpdate, 'actions': actions, 'modifiedHeaders': self.modifiedHeaders}
        return [updateRows, updateParams, headers, self.getLastRow(), allKeys, insertNames, updateColList, insertRows, updateSel]
                    
    def clear_update(self):
        self.actionsRequested = []
        self.modifiedHeaders = False
        for j, row in enumerate(self.xrows[1:]):
            key = row[self.keyCol-1] if self.keyCol else j+2+self.deletedRowCount
            if self.keyMap[key][1] or self.keyMap[key][2]:
                self.keyMap[key][1:3] = [0, set()]

    def complete_update(self, updateRows, updateParams):
        # Update sheet status after remote update has completed
        actions = updateParams.get('actions', '')
        if actions:
            if Settings['debug']:
                print("Sheet.complete_update:", self.name, actions, file=sys.stderr)
            for action in actions.split(','):
                if action in self.actionsRequested:
                    self.actionsRequested.remove(action)
                if action.endswith('gradebook'):
                    refreshGradebook(self.name)

        if not updateParams.get('incompleteUpdate') and updateParams.get('modifiedHeaders'):
            self.modifiedHeaders = False

        for j, row in enumerate(self.xrows[1:]):
            key = row[self.keyCol-1] if self.keyCol else j+2+self.deletedRowCount

            if key in updateRows:
                if updateRows[key] == self.keyMap[key][0]:
                    # Row update completed for row not modified since update
                    # (Note: Rows that were not updated due request limits being reached will not be subject to this reset)
                    self.keyMap[key][1:3] = [0, set()]
                elif not self.keyCol:
                    # Non-keyed row has been inserted, but modified later
                    self.keyMap[key][1:3] = [0, set(range(1,self.nCols+1))]


class Range(object):
    def __init__(self, sheet, rowMin, colMin, rowCount, colCount):
        self.sheet = sheet
        self.rng = [rowMin, colMin, rowCount, colCount]

    def getValues(self):
        return self.sheet.getSheetValues(*self.rng)

    def getValue(self):
        return self.sheet.getSheetValues(*self.rng)[0][0]

    def setValues(self, values):
        self.sheet._setSheetValues(*(self.rng+[values]))

    def setValue(self, value):
        self.sheet._setSheetValues(*(self.rng+[[[value]]]))

    def setFontStyle(self, *args, **kwargs):
        pass

    def setFontWeight(self, *args, **kwargs):
        pass

    def setNumberFormat(self, *args, **kwargs):
        pass

def getCacheStatus():
    out = 'Cache: version %s (remote: %s)\n' % (sliauth.get_version(), list(Global.remoteVersions))
    if Global.cacheUpdateError:
        out += '  ERROR in last cache update: <b>%s</b>\n' % Global.cacheUpdateError
        
    out += '  Suspend status: <b>%s</b>\n' % Global.suspended
    out += '  No. of updates (retries): %d (%d)\n' % (Global.totalCacheResponseCount, Global.totalCacheRetryCount)
    out += '  Average update time = %.2fs\n\n' % (Global.totalCacheResponseInterval/(1000*max(1,Global.totalCacheResponseCount)) )
    out += '  Average request bytes = %d\n\n' % (Global.totalCacheRequestBytes/max(1,Global.totalCacheResponseCount) )
    out += '  Average response bytes = %d\n\n' % (Global.totalCacheResponseBytes/max(1,Global.totalCacheResponseCount) )
    curTime = sliauth.epoch_ms()
    sitePrefix = Settings['site_name']+'/' if Settings['site_name'] else ''
    keys = list( set(Sheet_cache.keys() + Lock_cache.keys()) )
    keys.sort()
    for sheetName in keys:
        sheetStr = ''
        sheet = Sheet_cache.get(sheetName)
        if sheetName in Lock_cache:
            if sheet and sheet.get_updates() is not None:
                sheetStr = sheetName+' (locking...)'
            else:
                action = 'unlock'
        else:
            action = 'lock'
        if not sheetStr:
            sheetStr = '<a href="/%s/%s">%s</a> %s' % (sitePrefix+'_'+action, sheetName, action, Lock_cache.get(sheetName,''))
    
        updateStr = ''
        if sheet:
            accessTime = 'accessed:'+str(int((curTime-sheet.accessTime)/1000.))+'s'
            if sheet.modTime:
                accessTime += '/modified:'+str(int((curTime-sheet.modTime)/1000.))+'s'

            if Settings['debug']:
                updates = sheet.get_updates(row_limit=PROXY_UPDATE_ROW_LIMIT)
                if updates:
                    updateStr = '['+','.join(sorted(updates[0].keys()))+']'
                else:
                    updateStr = '[no pending updates]'
        else:
            accessTime = '(not cached)'


        out += 'Sheet_cache: %s: %s %s %s\n' % (sheetName, accessTime, sheetStr, updateStr)
    out += '\n'
    for sheetName in Miss_cache:
        out += 'Miss_cache: %s, %ds\n' % (sheetName, (curTime-Miss_cache[sheetName])/1000.)
    out += '\n'
    return out

def lockSheet(sheetName, lockType='user'):
    # Returns True if lock is immediately effective; False if it will take effect later
    if transactionalSession(sheetName):
        raise Exception('Cannot lock when transacting session '+sheetName)
    if sheetName == Global.previewStatus.get('sessionName'):
        return False
    if sheetName not in Lock_cache and not isReadOnly(sheetName):
        Lock_cache[sheetName] = lockType
    if sheetName in Sheet_cache and Sheet_cache[sheetName].get_updates() is not None:
        return False
    return True

def unlockSheet(sheetName):
    # Unlock and refresh sheet (if no updates pending)
    if previewOrTransactionalSession(sheetName):
        return False
    if sheetName in Sheet_cache and Sheet_cache[sheetName].get_updates() is not None:
        return False
    delSheet(sheetName)
    return True

def expireSheet(sheetName):
    # Expire sheet from cache (delete after any updates are processed)
    if previewOrTransactionalSession(sheetName):
        return False
    sheet = Sheet_cache.get(sheetName)
    if sheet:
        sheet.expire()

def refreshSheet(sheetName):
    # Refresh sheet, if unlocked (after any updates)
    if previewOrTransactionalSession(sheetName):
        return False
    if sheetName in Lock_cache or sheetName in Lock_passthru:
        return False
    sheet = Sheet_cache.get(sheetName)
    if not sheet:
        return True
    if sheet.get_updates() is None:
        delSheet(sheetName)
    else:
        sheet.expire()
    return True

def startPassthru(sheetName):
    Lock_passthru[sheetName] += 1
    return lockSheet(sheetName, lockType='passthru')

def endPassthru(sheetName):
    if sheetName not in Lock_passthru or not Lock_passthru[sheetName]:
        return
    Lock_passthru[sheetName] -= 1
    if Lock_cache.get(sheetName) == 'passthru' and not Lock_passthru[sheetName]:
        unlockSheet(sheetName)

def check_if_locked(sheetName, get=False, backup=False, cached=False):
    if Settings['lock_proxy_url'] and not (upstreamLockable(sheetName) or get):
        raise Exception('Only get operation allowed for upstream unlocked sheet '+sheetName+' in locked proxy mode')

    if sheetName in Lock_cache:
        raise Exception('Sheet %s is locked!' % sheetName)

    if get and backup and Global.suspended == 'backup':
        return True

    if get and cached and Global.suspended == 'freeze':
        return True

    if Global.suspended:
        raise Exception('Error:SUSPENDED:Cannot access sheet %s when suspended (%s)' % (sheetName, Global.suspended))

    return True

def get_locked():
    # Return list of locked sheet name (* if updates not yet send to Google sheets)
    locked = []
    for sheetName in Lock_cache:
        if sheetName in Sheet_cache and Sheet_cache[sheetName].get_updates() is not None:
            locked.append(sheetName+'*')
        else:
            locked.append(sheetName)
    locked.sort()
    return locked

def schedule_update(waitSec=0, force=False, synchronous=False):
    # Schedule update
    # If force, ignore any minimum wait restrictions and cancel any previously scheduled updates
    # waitSec=0 will trigger update immediately after this request
    # otherwise, a delayed update will be scheduled
    # If synchronous, force update and wait for it to complete before returning

    if Global.cachePendingUpdate:
        if not force and not synchronous:
            # Update already scheduled
            return
        IOLoop.current().remove_timeout(Global.cachePendingUpdate)
        Global.cachePendingUpdate = None

    if synchronous:
        update_remote_sheets(synchronous=True)
    elif waitSec:
        # Delayed update
        Global.cachePendingUpdate = IOLoop.current().call_later(waitSec, functools.partial(update_remote_sheets, force))
    else:
        # Update after request
        Global.cachePendingUpdate = IOLoop.current().add_callback(functools.partial(update_remote_sheets, force))

def suspend_cache(action=''):
    # action=shutdown must be called from a stand-alone request as it triggers non-transactional synchronous updates
    if Global.suspended == 'freeze' and action != 'clear':
        raise Exception('Must clear after freeze')

    Global.suspended = action
    if action == 'shutdown':
        if previewingSession():
            revertPreview(noupdate=True)
        for sessionName in list(Global.transactSessions):
            endTransactSession(sessionName, noupdate=True)
        schedule_update(synchronous=True)
    elif action:
        print('Suspended for', action, file=sys.stderr)
        if action == 'clear' and Global.cacheUpdateError:
            print('Cleared cache update error', Global.cacheUpdateError, file=sys.stderr)
            Global.cacheUpdateError = ''
        schedule_update(force=True)

def shutdown_loop():
    print("Completed IO loop shutdown", file=sys.stderr)
    for sheetName in sorted(list(Locked_proxy_sheets)):
        try:
            lockUpstreamProxy(sheetName, unlock=True)
        except Exception, excp:
            print("shutdown_loop: Failed to unlock sheet %s in upstream proxy %s: %s" % (sheetName, Settings['lock_proxy_url'], excp), file=sys.stderr)
    IOLoop.current().stop()

def sheet_proxy_error(errMsg=''):
    err = sliauth.iso_date(nosubsec=True) + ': ' + errMsg
    Global.cacheUpdateError = err
    print('sheet_proxy_error: '+err, file=sys.stderr)
    notify_admin(err)

def notify_admin(msg, msgType=''):
    if not msgType and Global.notifiedAdmin:
        return
    url = Settings['server_url']
    if Settings['site_name']:
        url += '/' + Settings['site_name']

    subject = '[Slidoc-notify] %s %s' % (Settings['site_name'], msgType or 'Cache update error')
    if not msgType:
        url += '/_cache'
        Global.notifiedAdmin = subject + ' ' + msg

    email_admin(subject, content=url+'\n\n'+msg)

def email_admin(subject='', content=''):
    if not Settings['email_addr']:
        return
    try:
        send_email(Settings['email_addr'], subject=subject, content=content)
        print('email_admin:Sent email', subject, content, file=sys.stderr)
    except Exception, excp:
        print('email_admin:Error: ', str(excp), file=sys.stderr)

def send_email(toAddr, subject='', content=''):
    if not Settings['gapps_url']:
        return
    params = {'action': 'mail_send', 'to': toAddr, 'subject': subject, 'content': content}
    url = tornado.httputil.url_concat(Settings['gapps_url'], params)

    http_client = tornado.httpclient.AsyncHTTPClient()

    def handle_request(response):
        if response.error:
            print('send_email:Error: ', response.error, file=sys.stderr)

    http_client.fetch(url, handle_request)

def proxy_error_status():
    return Global.cacheUpdateError
        
def updates_current():
    if not Global.suspended:
        return

    if Global.suspended == 'freeze':
        return

    if Global.suspended == 'clear':
        initCache()
        print("Cleared cache", file=sys.stderr)
    elif Global.suspended == 'shutdown':
        if not Global.shuttingDown:
            Global.shuttingDown = True
            IOLoop.current().add_callback(shutdown_loop)

def update_remote_sheets(force=False, synchronous=False):
    # If force, do not enforce minimum time delay restriction
    # If synchronous, wait for update to complete before returning
    if synchronous and previewingSession():
        sheet_proxy_error('update_remote_sheets: Exit preview session %s before synchronous updates' % previewingSession())
        return
    try:
        # Need to trap exception because it fails silently otherwise
        return update_remote_sheets_aux(force=force, synchronous=synchronous)
    except Exception, excp:
        if Settings['debug']:
            import traceback
            traceback.print_exc()
        sheet_proxy_error('Unexpected error in update_remote_sheets: %s' % excp)

def update_remote_sheets_aux(force=False, synchronous=False):
    if Global.cacheUpdateError or (Global.httpRequestId and not synchronous):
        # Request currently active/disabled
        # (synchronous request will supersede any active previous request)
        return

    curTime = sliauth.epoch_ms()
    if not force and not synchronous and (curTime - Global.cacheResponseTime) < 1000*Settings['min_wait_sec']:
        schedule_update(waitSec=curTime-Global.cacheResponseTime)
        return

    specialMods = []
    sessionMods = []
    sheetUpdateInfo = {}
    for sheetName, sheet in Sheet_cache.items():
        # Check each cached sheet for updates
        updates = sheet.get_updates(row_limit=PROXY_UPDATE_ROW_LIMIT)
        if updates is None:
            previewSession = previewingSession()
            if curTime-sheet.accessTime > 1000*sheet.holdSec and sheetName not in Lock_cache and sheetName not in Global.transactSessions and (not previewSession or sheetName not in (INDEX_SHEET, previewSession)):
                # Cache entry has expired
                if Settings['gsheet_url']:
                    delSheet(sheetName)
            continue

        # update_rows, update_params
        sheetUpdateInfo[sheetName] = updates[0:2]
        # sheet_name, update_params, headers_list, last_row, all_keys, insert_names_keys, update_cols_list or None, insert_rows, modified_rows
        modVals = [sheetName] + updates[1:]

        if sheetName.endswith('_slidoc'):
            # Update '*_slidoc' sheets before regular sessions (better for re-computing score totals etc.)
            specialMods.append(modVals)
        else:
            sessionMods.append(modVals)

    modRequests = specialMods + sessionMods

    if not modRequests:
        # Nothing to update
        updates_current()
        return

    json_data = json.dumps(modRequests, default=sliauth.json_default)

    ##if Settings['debug']:
    ##    print("update_remote_sheets_aux: REQUEST %s partial=%s, log=%s, sheets=%s, ndata=%d" % (sliauth.iso_date(nosubsec=True), Global.updatePartial, Settings['log_call'], sorted(sheetUpdateInfo.keys()), len(json_data)), file=sys.stderr)

    ##if Settings['debug']:
    ##    for x in modRequests:
    ##        print("update_remote_sheets_aux: REQUEST2", (x[0], x[1], len(x[2]), x[3], len(x[4]) if x[4] else 0, x[5], x[6], len(x[7]), len(x[7][0])if x[7] else 0, len(x[8]), len(x[8][0]) if x[8] else 0), file=sys.stderr)

    if not Settings['gsheet_url'] or Settings['dry_run']:
        # "Immediate" updates if no sheet URL or dry run
        Global.cacheUpdateTime = sliauth.epoch_ms()
        Global.cacheResponseTime = Global.cacheUpdateTime
        for sheetName, sheet in Sheet_cache.items():
            if sheetName in sheetUpdateInfo:
                sheet.clear_update()
        updates_current()
        return

    proxy_updater = ProxyUpdater(sheetUpdateInfo, json_data, modRequests, synchronous=synchronous)
    proxy_updater.update(curTime)


class ProxyUpdater(object):
    def __init__(self, sheetUpdateInfo, json_data, modRequests, synchronous=False):
        self.sheetUpdateInfo = sheetUpdateInfo
        self.json_data = json_data
        self.modRequests = modRequests
        self.synchronous = synchronous

        user = ADMINUSER_ID
        userToken = gen_proxy_token(user, ADMIN_ROLE)

        self.requestId = sliauth.iso_date(nosubsec=True)+'-'+uuid.uuid4().hex[:8]

        post_data = { 'proxy': '1', 'allupdates': '1', 'admin': user, 'token': userToken,
                      'data':  self.json_data}
        post_data['create'] = 'proxy'
        post_data['requestid'] = self.requestId
        if Global.updatePartial:
            post_data['partialrows'] = '1'
        if Settings['log_call']:
            post_data['logcall'] = str(Settings['log_call'])

        self.body = urllib.urlencode(post_data)

        self.cacheRequestTime = 0
        self.httpRequest = None
        if self.synchronous:
            self.http_client = tornado.httpclient.HTTPClient()
        else:
            self.http_client = tornado.httpclient.AsyncHTTPClient()

        self.cacheRetryCount = 0
        self.cacheWaitTime = 0

    def update(self, curTime):
        Global.httpRequestId = self.requestId
        self.cacheRequestTime = curTime
        Global.totalCacheRequestBytes += len(self.json_data)

        ##if Settings['debug']:
        ##    print("ProxyUpdater.update: UPDATE requestid=%s, retry=%d" % (Global.httpRequestId, self.cacheRetryCount), file=sys.stderr)

        if self.synchronous:
            self.handle_proxy_response(self.http_client.fetch(Settings['gsheet_url'], method='POST', headers=None, body=self.body))
            updates_current()
        else:
            self.httpRequest = tornado.httpclient.HTTPRequest(Settings['gsheet_url'], method='POST', headers=None, body=self.body,
                                                 connect_timeout=20, request_timeout=Settings['request_timeout'])
            self.async_fetch()

    def async_fetch(self):
        self.http_client.fetch(self.httpRequest, self.handle_proxy_response)
    
    def handle_proxy_response(self, response):
        try:
            # Need to trap exception because it fails silently otherwise
            return self.handle_proxy_response_aux(response)
        except Exception, excp:
            if Settings['debug']:
                import traceback
                traceback.print_exc()
            sheet_proxy_error('Unexpected error in handle_proxy_response: %s' % excp)

    def handle_proxy_response_aux(self, response):
        if self.requestId != Global.httpRequestId:
            # Cache has been cleared since update request; ignore response
            print("ProxyUpdater.handle_proxy_response_aux: DROPPED response to update request %s" % self.requestId, file=sys.stderr)
            return

        errMsg = ''
        errTrace = ''
        messages = ''
        respObj = None
        if response.error:
            errMsg = str(response.error)  # Need to convert to string for later use
        else:
            try:
                respObj = json.loads(response.body)
                if respObj['result'] == 'error':
                    errMsg = respObj['error']
                    errTrace = respObj.get('errtrace','')
                    messages = respObj.get('messages','')
            except Exception, err:
                errMsg = 'JSON parsing error: '+str(err)

            if Settings['debug']:
                cachedResp = respObj['info'].get('cachedResponse', '') if respObj else ''
                ##print("handle_proxy_response_aux: Update RESPONSE", sliauth.iso_date(nosubsec=True), cachedResp, errMsg, respObj, response.body[:256]+'\n', errTrace, file=sys.stderr)

        if errMsg or not respObj:
            # Handle update errors
            retry_after = RETRY_WAIT_TIME
            if errMsg.lower().find('timeout') >= 0:
                retry_after = 5 * retry_after

            if errMsg.find('PROXY_PARTIAL') >= 0:
                # Disable partial row updates
                Global.updatePartial = False

            if Global.suspended or self.cacheRetryCount >= RETRY_MAX_COUNT:
                msg = 'Failed to update cache after %d tries: %s' % (RETRY_MAX_COUNT, errMsg)
                sheet_proxy_error(msg)
                return

            self.cacheRetryCount += 1
            self.cacheWaitTime += retry_after
            Global.totalCacheRetryCount += 1

            print("ProxyUpdater.handle_proxy_response_aux: %s Update ERROR (tries %d of %d; retry_after=%ss): %s" % (Settings['site_name'], self.cacheRetryCount, RETRY_MAX_COUNT, self.cacheWaitTime, errMsg), file=sys.stderr)

            if Settings['debug'] and self.cacheRetryCount == 1:
                if errTrace:
                    print('ProxyUpdater.handle_proxy_response_aux: errtrace\n', errTrace)
                if messages:
                    print('ProxyUpdater.handle_proxy_response_aux: messages\n', messages)

                print("ProxyUpdater.handle_proxy_response_aux: REQUEST %s partial=%s, log=%s, sheets=%s, ndata=%d" % (sliauth.iso_date(nosubsec=True), Global.updatePartial, Settings['log_call'], sorted(self.sheetUpdateInfo.keys()), len(self.json_data)), file=sys.stderr)

                for x in self.modRequests:
                    print("ProxyUpdater.handle_proxy_response_aux: REQUEST2", (x[0], x[1], len(x[2]), x[3], len(x[4]) if x[4] else 0, x[5], x[6], len(x[7]), len(x[7][0])if x[7] else 0, len(x[8]), len(x[8][0]) if x[8] else 0), file=sys.stderr)


            # Retry same request after some time
            IOLoop.current().call_later(self.cacheWaitTime, self.async_fetch)
            return

        # Update request succeeded
        Global.cacheUpdateTime = self.cacheRequestTime
        Global.cacheResponseTime = sliauth.epoch_ms()

        Global.totalCacheResponseInterval += (Global.cacheResponseTime - self.cacheRequestTime)
        Global.totalCacheResponseCount += 1
        Global.totalCacheResponseBytes += len(response.body)

        refreshNeeded = []
        for sheetName, sheet in Sheet_cache.items():
            if sheetName in self.sheetUpdateInfo:
                sheet.complete_update(*self.sheetUpdateInfo[sheetName])

                if sheetName in Global.transactSessions:
                    Global.transactSessions[sheetName].complete_update(*self.sheetUpdateInfo[sheetName])

                if sheetName == previewingSession():
                    origSheet = Global.previewStatus['sessionSheetOrig']
                    if origSheet:
                        origSheet.complete_update(*self.sheetUpdateInfo[sheetName])

            if not sheet.holdSec:
                # Refresh expired sheet
                refreshNeeded.append(sheetName)

        for sheetName in respObj['info'].get('refreshSheets',[]):
            refreshNeeded.append(sheetName)
            refreshSheet(sheetName)

        for errSessionName, proxyErrMsg, proxyErrTrace, proxyDebugMsg in respObj['info'].get('updateErrors',[]):
            if 'NOGRADEUPDATE' in proxyErrMsg:
                # Gradebook not updated; OK for proxy
                continue
            temMsg = 'Update LOCKED %s: %s \n%s\n%s\n' % (errSessionName, proxyErrMsg, proxyErrTrace, proxyDebugMsg)
            if errSessionName not in Lock_cache:
                Lock_cache[errSessionName] = proxyErrMsg
                notify_admin(temMsg)
            print('ProxyUpdater.handle_proxy_response_aux: '+temMsg, file=sys.stderr)

        ##if Settings['debug']:
        ##    print("ProxyUpdater.handle_proxy_response_aux: UPDATED", sliauth.iso_date(nosubsec=True), file=sys.stderr)

        next_cache_update(0 if (refreshNeeded or Global.suspended) else Settings['min_wait_sec'])

def next_cache_update(waitSec=0, resetError=False):
    if resetError:
        Global.cacheUpdateError = ''
    Global.httpRequestId = ''
    schedule_update(waitSec=waitSec)
        

def sheetAction(params, notrace=False):
    # Returns a JSON object
    # object.result = 'success' or 'error'
    # object.value contains updated row values list if get=1; otherwise it is [].
    # object.headers contains column headers list, if getheaders=1
    # object.info is an object contains timestamp and dueDate values
    # PARAMETERS
    # sheet: 'sheet name' (required)
    # admin: admin user name (optional)
    # token: authentication token
    # actions: ''|'discuss_posts'|'answer_stats'|'gradebook' (last two not for proxy)
    # headers: ['name', 'id', 'email', 'altid', 'Timestamp', 'initTimestamp', 'submitTimestamp', 'field1', ...] (name and id required for sheet creation)
    # name: sortable name, usually 'Last name, First M.' (required if creating a row, and row parameter is not specified)
    # id: unique userID or lowercase email (required if creating or updating a row, and row parameter is not specified)
    # email: optional
    # altid: alternate, perhaps numeric, id (optional, used for information only)
    # update: [('field1', 'val1'), ...] (list of fields+values to be updated, excluding the unique field 'id')
    # If the special name initTimestamp occurs in the list, the timestamp is initialized when the row is added.
    # If the special name Timestamp occurs in the list, the timestamp is automatically updated on each write.
    # row: ['name_value', 'id_value', 'email_value', 'altid_value', null, null, null, 'field1_value', ...]
    #       null value implies no update (except for Timestamp)
    # nooverwrite: 1 => do not overwrite row; return previous row, if present, else create new row
    # submit: 1 if submitting row
    # timestamp: previous timestamp value (for sequencing updates)
    # update: 1 to modify part of row
    # get: 1 to retrieve row (id must be specified)
    # getheaders: 1 to return headers as well
    # all: 1 to retrieve all rows
    # formula: 1 retrieve formulas (proxy only)
    # create: 1 to create and initialize non-existent rows (for get/put)
    # seed: optional random seed to re-create session (admin use only)
    # delrow: 1 to delete row
    # resetrow: 1 to reset row (for get)
    # late: lateToken (set when creating row)
    # Can add row with fewer columns than already present.
    # This allows user to add additional columns without affecting script actions.
    # (User added columns are returned on gets and selective updates, but not row updates.)
    # delsheet: 1 to delete sheet (and any associated session index entry)
    # copysheet: name to copy sheet to new sheet (but not session index entry)
    # shortly after my original solution Google announced the LockService[1]
    # this prevents concurrent access overwritting data
    # [1] http://googleappsdeveloper.blogspot.co.uk/2011/10/concurrency-and-google-apps-script.html
    # we want a public lock, one that locks for all invocations

    ##if Settings['debug'] and not notrace:
    ##    print("DEBUG: sheetAction PARAMS", params.get('sheet'), params.get('id'), file=sys.stderr)

    returnValues = None
    returnHeaders = None
    returnInfo = {'version': sliauth.get_version()}
    returnMessages = []
    completeActions = []

    try:
        if params.get('settings',''):
            raise Exception('Error:SETTINGS:Settings cannot be changed for proxy')

        if Settings['site_access'] == SITE_INACTIVE:
            raise Exception('Error:INACTIVE:Site deactivated')

        if not Settings['no_login_token'] and not Settings['auth_key']:
            raise Exception('Error:SETUP:No auth_key for login')

        sheetName = params.get('sheet','')
        if not sheetName:
            raise Exception('Error:SHEETNAME:No sheet name specified')

        returnInfo['sheet'] = sheetName

        origUser = ''
        adminUser = ''
        readOnlyAccess = False
        gradebookRelease = set( split_list(Settings.get('gradebook_release', ''), lower=True) )

        paramId = params.get('id','')
        paramTeam = params.get('team','')
        authToken = params.get('token', '')
        accessCode = params.get('access','')

        if ':' in authToken:
            comps = authToken.split(':')   # effectiveId:userid:role:sites:hmac
            if len(comps) != 5:
                raise Exception('Error:INVALID_TOKEN:Invalid auth token format');
            subToken = ':' + ':'.join(comps[1:])
            if not validateHMAC(subToken, Settings['auth_key']):
                raise Exception('Error:INVALID_TOKEN:Invalid authentication token')

            effectiveUser = comps[0]
            origUser = comps[1]
            temRole = comps[2]
            temSites = comps[3]

            if not temRole and temSites and Settings['site_name']:
                temRole = getSiteRole(Settings['site_name'], temSites) or ''
                        
            if params.get('admin'):
                if temRole != ADMIN_ROLE and temRole != GRADER_ROLE:
                    raise Exception('Error:INVALID_TOKEN:Invalid token admin role: '+temRole)
                adminUser = temRole
            elif effectiveUser:
                if effectiveUser != origUser and temRole != ADMIN_ROLE:
                    raise Exception('Error:INVALID_TOKEN:Not allowed to change from user: '+origUser+' to '+effectiveUser)
                if effectiveUser != paramId:
                    raise Exception('Error:INVALID_TOKEN:Incorrect effective user: '+effectiveUser+' != '+paramId)
                readOnlyAccess = (origUser != effectiveUser) and (effectiveUser != TESTUSER_ID)
            else:
                raise Exception('Error:INVALID_TOKEN:Unexpected admin token for regular access')

        elif params.get('admin'):
            raise Exception('Error:NEED_TOKEN:Need admin token for admin authentication')

        elif not Settings['no_login_token']:
            if not authToken:
                raise Exception('Error:NEED_TOKEN:Need token for id authentication')
            if not paramId:
                raise Exception('Error:NEED_ID:Need id for authentication')
            if not validateHMAC(sliauth.gen_auth_prefix(paramId,'','')+':'+authToken, Settings['auth_key']):
                raise Exception('Error:INVALID_TOKEN:Invalid token for authenticating id '+paramId)
            origUser = paramId

        proxy = params.get('proxy','');

        # Read-only sheets
        protectedSheet = (sheetName.endswith('_slidoc') and sheetName != ROSTER_SHEET and sheetName != DISCUSS_SHEET and sheetName != INDEX_SHEET) or sheetName.endswith('_answers') or sheetName.endswith('_stats')

        # Admin-only access sheets (ROSTER_SHEET modifications will be restricted later)
        restrictedSheet = (sheetName.endswith('_slidoc') and sheetName != ROSTER_SHEET and sheetName != DISCUSS_SHEET and sheetName != GRADES_SHEET)

        loggingSheet = sheetName.endswith('_log')
        discussingSession = sheetName[0:-len('_discuss')] if sheetName.endswith('_discuss') else ''

        previewingSheet = (sheetName == previewingSession())

        indexedSession = not restrictedSheet and not protectedSheet and not loggingSheet and not discussingSession and sheetName != ROSTER_SHEET and getSheet(INDEX_SHEET)

        getRow = params.get('get','')
        createRow = params.get('create', '')
        allRows = params.get('all','')

        nooverwriteRow = params.get('nooverwrite','')
        delRow = params.get('delrow','')
        resetRow = params.get('resetrow','')

        getShare = params.get('getshare', '')
        importSession = params.get('import','')
        seedRow = params.get('seed', None) if adminUser else None

        selectedUpdates = json.loads(params.get('update','')) if params.get('update','') else None
        rowUpdates = json.loads(params.get('row','')) if params.get('row','') else None

        removeSheet = params.get('delsheet')
        performActions = params.get('actions', '')
        if params.get('completeactions', '').strip():
            completeActions =  params['completeactions'].split(',')

        curDate = createDate()
        curTime = sliauth.epoch_ms(curDate)

        modifyingRow = delRow or resetRow or selectedUpdates or (rowUpdates and not nooverwriteRow)
        if adminUser or paramId == TESTUSER_ID:
            if modifyingRow and not TOTAL_COLUMN:
                # Refresh cached gradebook (because scores/grade may be updated)
                refreshGradebook(sheetName)
            if removeSheet and previewingSheet:
                raise Exception('Error:PREVIEW_MODS:Cannot delete sheet when previewing it');

        lockedSite = Settings['site_access'] == SITE_LOCKED or (Settings['lock_date'] and sliauth.epoch_ms(curDate) > sliauth.epoch_ms(Settings['lock_date']))

        expiredSite = not Settings['site_access'] and Settings['end_date'] and sliauth.epoch_ms(curDate) > sliauth.epoch_ms(Settings['end_date'])

        limitedAccess = ''
        if readOnlyAccess:
            limitedAccess = 'Error::Admin user '+origUser+' cannot modify row for user '+paramId
        elif expiredSite:
            limitedAccess = 'Error:EXPIRED:Cannot modify expired site '+Settings['site_name']
        elif not adminUser and paramId != TESTUSER_ID:
            if lockedSite:
                limitedAccess = 'Error:LOCKED_MODS:All sessions are locked. No user modifications permitted'
            elif previewingSheet:
                limitedAccess = 'Error:PREVIEW_MODS:No user modifications permitted at this time'

        if modifyingRow or removeSheet:
            if Global.cacheUpdateError:
                raise Exception('Error::All sessions are frozen due to cache update error: '+Global.cacheUpdateError);
            if limitedAccess:
                raise Exception(limitedAccess)

        rosterName = ''
        rosterValues = None
        rosterSheet = getSheet(ROSTER_SHEET)

        if adminUser:
            rosterName = '#' + TESTUSER_ID
        elif rosterSheet:
            # Check user access
            if not paramId:
                raise Exception('Error:NEED_ID:Must specify userID to lookup roster')
            # Copy user info from roster
            rosterValues = getRosterEntry(paramId)
            if rosterValues and rosterValues.get('name'):
                rosterName = rosterValues['name']
            else:
                rosterName = '#' + paramId
        elif not Settings['no_roster']:
            raise Exception('Error:NEED_ROSTER:Need roster for non-admin access')
		
        if performActions:
            if performActions == 'discuss_posts':
                returnValues = getDiscussPosts(sheetName, params.get('discuss', ''), paramId, rosterName)
                return {"result": "success", "value": returnValues, "headers": returnHeaders,
                        "info": returnInfo, "messages": '\n'.join(returnMessages)}
            elif not all(x in ('answer_stats', 'correct') for x in performActions.split(',')):
                raise Exception('Error:ACTION:Some actions %s not supported by proxy' % performActions)
            else:
                if not adminUser:
                    raise Exception("Error:ACTION:Must be admin user to perform action on sheet "+sheetName)
                if protectedSheet or restrictedSheet or loggingSheet:
                    raise Exception('Error:ACTION:Action not allowed for sheet '+sheetName)
        elif not proxy and not sheetName:
            raise Exception('Error:SHEETNAME:No sheet name specified')

        sessionEntries = None
        sessionAttributes = None
        sessionWeight = None
        questions = None
        paceLevel = None
        adminPaced = None
        releaseDate = None
        dueDate = None
        gradeDate = None
        voteDate = None
        discussableSession = None
        sessionTeam = None
        timedSec = None

        computeTotalScore = False

        if proxy and adminUser != ADMIN_ROLE:
            raise Exception("Error::Must be admin user for proxy access sheet '"+sheetName+"'")

        if sheetName == SETTINGS_SHEET and adminUser != ADMIN_ROLE:
            raise Exception('Error::Must be admin user to access settings')

        if restrictedSheet and not adminUser:
            raise Exception("Error::Must be admin/grader user to access sheet '"+sheetName+"'")

        returnInfo['prevTimestamp'] = None
        returnInfo['timestamp'] = None
        processed = False

        if performActions:
            actionHandler(performActions, sheetName, True)
            processed = True
            returnValues = []

        elif proxy and getRow and allRows:
            # Return all sheet values to proxy
            processed = True
            modSheet = getSheet(sheetName)
            if not modSheet:
                returnValues = []
            else:
                allRange = modSheet.getRange(1, 1, modSheet.getLastRow(), modSheet.getLastColumn())
                returnValues = allRange.getValues()

        elif removeSheet:
            # Delete sheet+related (and session entry)
            processed = True
            returnValues = []
            if not adminUser:
                raise Exception("Error:DELSHEET:Only admin can delete sheet "+sheetName)
            if sheetName.endswith('_slidoc'):
                raise Exception("Error:DELSHEET:Cannot delete special sheet "+sheetName)
            indexSheet = getSheet(INDEX_SHEET)
            if indexSheet:
                # Delete session entry
                delRowCol = lookupRowIndex(sheetName, indexSheet, 2)
                if delRowCol:
                    indexSheet.deleteRow(delRowCol)

            delSheet(sheetName, deleteRemote=True)
                    
            for j in range(len(RELATED_SHEETS)):
                if getSheet(sheetName+'_'+RELATED_SHEETS[j]):
                    delSheet(sheetName+'_'+RELATED_SHEETS[j], deleteRemote=True)

            # Blank out any discussion access column for session
            axsSheet = getSheet(DISCUSS_SHEET)
            if axsSheet:
                blankColumn(axsSheet, '_'+sheetName)
                    
        elif params.get('copysheet'):
            # Copy sheet (but not session entry)
            processed = True
            returnValues = []
            if not adminUser:
                raise Exception("Error:COPYSHEET:Only admin can copy sheet "+sheetName)
            modSheet = getSheet(sheetName)
            if not modSheet:
                raise Exception("Error:COPYSHEET:Source sheet "+sheetName+" not found!")

            newName = params.get('copysheet')
            indexSheet = getSheet(INDEX_SHEET)
            if indexSheet:
                newRowCol = lookupRowIndex(newName, indexSheet, 2)
                if newRowCol:
                    raise Exception("Error:COPYSHEET:Destination session entry "+newName+" already exists!")

            if newName in Sheet_cache or getSheet(newName):
                raise Exception("Error:COPYSHEET:Destination sheet "+newName+" already exists!")
            if Settings['gsheet_url'] and not Settings['dry_run']:
                user = ADMINUSER_ID
                userToken = gen_proxy_token(user, ADMIN_ROLE)
                copyParams = {'sheet': sheetName, 'copysheet': newName, 'admin': user, 'token': userToken}
                retval = sliauth.http_post(Settings['gsheet_url'], copyParams)
                print('sdproxy: copysheet %s: %s' % (sheetName, retval), file=sys.stderr)
                if retval['result'] != 'success':
                    return retval
            else:
                keyHeader = '' if newName.startswith('settings_') or newName.endswith('_log') else 'id'
                Sheet_cache[newName] = Sheet(newName, modSheet.getRows(), keyHeader=keyHeader)
        else:
            # Update/access single sheet
            headers = json.loads(params.get('headers','')) if params.get('headers','') else None

            updatingSingleColumn = ''
            alterSubmission = False
            twitterSetting = False
            discussionPost = None
            if not rowUpdates and selectedUpdates and len(selectedUpdates) == 2 and selectedUpdates[0][0] == 'id':
                updatingSingleColumn = selectedUpdates[1][0]
                if discussingSession and updatingSingleColumn.startswith('discuss'):
                    discNum = int(updatingSingleColumn[len('discuss'):])
                    if paramId == TESTUSER_ID:
                        postTeam = paramTeam
                    else:
                        postTeam = getUserTeam(discussingSession, paramId, discussNum=discNum)
                    discussionPost = [discussingSession, discNum, postTeam]

                if updatingSingleColumn == 'submitTimestamp':
                    alterSubmission = True

                if updatingSingleColumn == TWITTER_HEADER and sheetName == ROSTER_SHEET:
                    twitterSetting = True

            if discussionPost:
                # Create session_discuss sheet, if need be, to post
                modSheet = updateSessionDiscussSheet(discussingSession)
                if not modSheet:
                    raise Exception('Cannot post discussion for session '+discussingSession)
                addDiscussUser(discussingSession, paramId, rosterName)
            else:
                modSheet = getSheet(sheetName)

            if not modSheet:
                # Create new sheet
                if not adminUser:
                    raise Exception("Error:NOSHEET:Sheet '"+sheetName+"' not found")
                if headers is None:
                    raise Exception("Error:NOSHEET:Headers must be specified for new sheet '"+sheetName+"'")

                if indexedSession:
                    for j in range(len(AUXILIARY_SHEETS)):
                        temName = sheetName+'_'+AUXILIARY_SHEETS[j]
                        temSheet = getSheet(temName)
                        if temSheet:
                            raise Exception("Error:NOSHEET:Session '"+sheetName+"' cannot be created without deleting auxiliary sheet "+temName)

                modSheet = createSheet(sheetName, headers)

            if not modSheet.getLastColumn():
                raise Exception("Error::No columns in sheet '"+sheetName+"'")

            if indexedSession:
                sessionEntries = lookupValues(sheetName, ['sessionWeight', 'releaseDate', 'dueDate', 'gradeDate', 'paceLevel', 'adminPaced', 'scoreWeight', 'gradeWeight', 'otherWeight', 'fieldsMin', 'questions', 'attributes'], INDEX_SHEET)
                sessionAttributes = json.loads(sessionEntries['attributes'])
                sessionWeight = parseNumber(sessionEntries.get('sessionWeight'))
                questions = json.loads(sessionEntries['questions'])
                paceLevel = sessionEntries.get('paceLevel')
                adminPaced = sessionEntries.get('adminPaced')
                releaseDate = sessionEntries.get('releaseDate')
                dueDate = sessionEntries.get('dueDate')
                gradeDate = sessionEntries.get('gradeDate')
                voteDate = createDate(sessionAttributes['params']['plugin_share_voteDate']) if sessionAttributes['params'].get('plugin_share_voteDate') else None
                discussableSession = sessionAttributes.get('discussSlides') and len(sessionAttributes['discussSlides'])
                sessionTeam = sessionAttributes.get('sessionTeam')
                timedSec = sessionAttributes['params'].get('timedSec')
                if timedSec and rosterValues:
                    extraTime = parseNumber(rosterValues.get('extratime',''))
                    if extraTime:
                        timedSec = timedSec * (1.0 + extraTime)

                if parseNumber(sessionEntries.get('scoreWeight')):
                    # Compute total score?
                    if sessionAttributes['params']['features'].get('delay_answers') or sessionAttributes['params']['features'].get('remote_answers'):
                        # Delayed or remote answers; compute total score only after grading
                        computeTotalScore = gradeDate
                    else:
                        computeTotalScore = True

            # Check parameter consistency
            columnHeaders = modSheet.getSheetValues(1, 1, 1, modSheet.getLastColumn())[0]
            columnIndex = indexColumns(modSheet)

            updatingMaxScoreRow = sessionEntries and rowUpdates and rowUpdates[columnIndex['id']-1] == MAXSCORE_ID
            if headers:
                modifyStartCol = int(params['modify']) if params.get('modify') else 0
                if modifyStartCol:
                    if not updatingMaxScoreRow:
                        raise Exception("Error::Must be updating max scores row to modify headers in sheet "+sheetName)
                    checkCols = modifyStartCol-1
                else:
                    if len(headers) != len(columnHeaders):
                        raise Exception("Error:MODIFY_SESSION:Number of headers does not match that present in sheet '"+sheetName+"'; delete it or modify headers.");
                    checkCols = len(columnHeaders)

                for j in range( checkCols ):
                    if headers[j] != columnHeaders[j]:
                        raise Exception("Error:MODIFY_SESSION:Column header mismatch: Expected "+headers[j]+" but found "+columnHeaders[j]+" in sheet '"+sheetName+"'; delete it or modify headers.")

                if modifyStartCol:
                    # Updating maxscore row; modify headers if needed
                    startRow = 2
                    nRows = modSheet.getLastRow()-startRow+1
                    idValues = None
                    if nRows:
                        idValues = modSheet.getSheetValues(startRow, columnIndex['id'], nRows, 1)
                        if paceLevel == BASIC_PACE or paceLevel == QUESTION_PACE:
                            submitValues = modSheet.getSheetValues(startRow, columnIndex['submitTimestamp'], nRows, 1)
                            for k in range(nRows):
                                if submitValues[k][0]:
                                    raise Exception( "Error::Cannot modify sheet "+sheetName+" with submissions")

                    if modifyStartCol <= len(columnHeaders):
                        # Truncate columns; ensure truncated columns are empty
                        startCol = modifyStartCol
                        nCols = len(columnHeaders)-startCol+1
                        if nRows:
                            modRows = nRows
                            if idValues[0][0] == MAXSCORE_ID:
                                startRow += 1
                                modRows -= 1
                            if modRows:
                                values = modSheet.getSheetValues(startRow, startCol, modRows, nCols)
                                for j in range(nCols):
                                    for k in range(modRows):
                                        if values[k][j] != '':
                                            raise Exception( "Error:TRUNCATE_ERROR:Cannot truncate non-empty column "+str(startCol+j)+" ("+columnHeaders[startCol+j-1]+") in sheet "+sheetName+" (modcol="+str(modifyStartCol)+")")

                        modSheet.trimColumns( nCols, delayMods=(len(headers) > (modSheet.getLastColumn()-nCols)) )
                        ##modSheet.deleteColumns(startCol, nCols)

                    nTemCols = modSheet.getLastColumn()
                    if len(headers) > nTemCols:
                        # Extend columns
                        startCol = nTemCols+1
                        nCols = len(headers)-startCol+1
                        modSheet.appendColumns(headers[nTemCols:])
                        ##modSheet.insertColumnsAfter(startCol-1, nCols)
                        ##modSheet.getRange(1, startCol, 1, nCols).setValues([ headers.slice(nTemCols) ])

                    columnHeaders = modSheet.getSheetValues(1, 1, 1, modSheet.getLastColumn())[0]
                    columnIndex = indexColumns(modSheet)

            if updatingMaxScoreRow and computeTotalScore:
                completeActions.append('answer_stats')
                completeActions.append('correct')
                if updateTotalScores(modSheet, sessionAttributes, questions, True) and not Settings['dry_run']:
                    completeActions.append('gradebook')
                    if not TOTAL_COLUMN:
                        # Refresh cached gradebook (because scores/grade may be updated)
                        refreshGradebook(sheetName)

            userId = None
            displayName = None

            voteSubmission = ''
            if updatingSingleColumn and updatingSingleColumn.endswith('_vote') and sessionAttributes.get('shareAnswers'):
                qprefix = updatingSingleColumn.split('_')[0]
                voteSubmission = sessionAttributes['shareAnswers'][qprefix].get('share', '') if sessionAttributes['shareAnswers'].get(qprefix) else ''

            if not adminUser and selectedUpdates and not voteSubmission and not discussionPost and not twitterSetting:
                raise Exception("Error::Only admin user allowed to make selected updates to sheet '"+sheetName+"'")

            if importSession and not adminUser:
                raise Exception("Error::Only admin user allowed to import to sheet '"+sheetName+"'")

            if sheetName == ROSTER_SHEET and rowUpdates and not adminUser:
                raise Exception("Error::Only admin user allowed to add/modify rows to sheet '"+sheetName+"'")

            if protectedSheet and (rowUpdates or selectedUpdates) :
                raise Exception("Error::Cannot modify protected sheet '"+sheetName+"'")

            numStickyRows = 1  # Headers etc.

            if params.get('getheaders',''):
                returnHeaders = columnHeaders
                if sessionEntries and paramId == TESTUSER_ID:
                    returnInfo['maxRows'] = modSheet.getLastRow()
                    if columnIndex.get('lastSlide'):
                        returnInfo['maxLastSlide'] = getColumnMax(modSheet, 2, columnIndex['lastSlide'])

            if params.get('getstats',''):
                try:
                    temIndexRow = indexRows(modSheet, indexColumns(modSheet)['id'], 2)
                    if Settings.get('gradebook_release'):
                        returnInfo['gradebookRelease'] = Settings.get('gradebook_release')

                    if temIndexRow.get(TIMESTAMP_ID) and columnIndex.get('total'):
                        returnInfo['lastUpdate'] = modSheet.getSheetValues(temIndexRow.get(TIMESTAMP_ID), columnIndex['total'], 1, 1)[0][0]
                    if temIndexRow.get(MAXSCORE_ID):
                        returnInfo['maxScores'] = modSheet.getSheetValues(temIndexRow.get(MAXSCORE_ID), 1, 1, len(columnHeaders))[0]
                    if temIndexRow.get(AVERAGE_ID) and 'average' in gradebookRelease:
                        returnInfo['averages'] = modSheet.getSheetValues(temIndexRow.get(AVERAGE_ID), 1, 1, len(columnHeaders))[0]
                    if temIndexRow.get(RESCALE_ID):
                        returnInfo['rescale'] = modSheet.getSheetValues(temIndexRow.get(RESCALE_ID), 1, 1, len(columnHeaders))[0]
                        if not adminUser and columnIndex.get(STATUS_HEADER):
                            returnInfo['rescale'][columnIndex[STATUS_HEADER]-1] = ''
                except Exception, err:
                    if Settings['debug']:
                        import traceback
                        traceback.print_exc()

        if processed:
            # Already processed
            pass
        elif delRow:
            # Delete row only allowed for session sheet and admin/test user
            if not sessionEntries or ( not adminUser and paramId != TESTUSER_ID):
                raise Exception("Error:DELETE_ROW:userID '"+paramId+"' not allowed to delete row in sheet "+sheetName)
            delRowCol = lookupRowIndex(paramId, modSheet, 2)
            if delRowCol:
                modSheet.deleteRow(delRowCol)
            returnValues = []
        elif not rowUpdates and not selectedUpdates and not getRow and not getShare:
            # No row updates/gets
            returnValues = []
        elif getRow and allRows:
            # Get all rows and columns
            if not adminUser:
                raise Exception("Error::Only admin user allowed to access all rows in sheet '"+sheetName+"'")
            if modSheet.getLastRow() <= numStickyRows:
                returnValues = []
            else:
                if sessionEntries and dueDate:
                    # Force submit all non-sticky regular user rows past effective due date
                    idCol = columnIndex.get('id')
                    submitCol = columnIndex.get('submitTimestamp')
                    lateTokenCol = columnIndex.get('lateToken')
                    allValues = modSheet.getSheetValues(1+numStickyRows, 1, modSheet.getLastRow()-numStickyRows, len(columnHeaders))
                    for j in range(len(allValues)):
                        if allValues[j][submitCol-1] or allValues[j][idCol-1] == MAXSCORE_ID or allValues[j][idCol-1] == TESTUSER_ID:
                            continue
                        lateToken = allValues[j][lateTokenCol-1]
                        if lateToken == LATE_SUBMIT:
                            continue
                        if lateToken and ':' in lateToken:
                            effectiveDueDate = getNewDueDate(allValues[j][idCol-1], Settings['site_name'], sheetName, lateToken) or dueDate
                        else:
                            effectiveDueDate = dueDate
                        pastSubmitDeadline = sliauth.epoch_ms(curDate) > sliauth.epoch_ms(effectiveDueDate)
                        if pastSubmitDeadline:
                            # Force submit
                            modSheet.getRange(j+1+numStickyRows, submitCol, 1, 1).setValues([[curDate]])

                returnValues = modSheet.getSheetValues(1+numStickyRows, 1, modSheet.getLastRow()-numStickyRows, len(columnHeaders))
            if sessionEntries:
                if adminPaced:
                    returnInfo['adminPaced'] = adminPaced
                if dueDate:
                    returnInfo['dueDate'] = dueDate
                if columnIndex.get('lastSlide'):
                    returnInfo['maxLastSlide'] = getColumnMax(modSheet, 2, columnIndex['lastSlide'])
                if computeTotalScore:
                    returnInfo['remoteAnswers'] = sessionAttributes.get('remoteAnswers')
        elif getShare:
            # Sharing: return adjacent columns (if permitted by session index and corresponding user entry is non-null)
            if not sessionAttributes or not sessionAttributes.get('shareAnswers'):
                raise Exception('Error::Denied access to answers of session '+sheetName)
            shareParams = sessionAttributes['shareAnswers'].get(getShare)
            if not shareParams or not shareParams.get('share'):
                raise Exception('Error::Sharing not enabled for '+getShare+' of session '+sheetName)

            if shareParams.get('vote') and voteDate:
                returnInfo['voteDate'] = voteDate

            qno = int(getShare[1:])
            teamAttr = questions[qno-1].get('team','')

            if not adminUser and shareParams.get('share') == 'after_grading' and not gradeDate:
                returnMessages.append("Warning:SHARE_AFTER_GRADING:")
                returnValues = []
            elif not adminUser and shareParams.get('share') == 'after_due_date' and (not dueDate or sliauth.epoch_ms(dueDate) > sliauth.epoch_ms(curDate)):
                returnMessages.append("Warning:SHARE_AFTER_DUE_DATE:")
                returnValues = []
            elif modSheet.getLastRow() <= numStickyRows:
                returnMessages.append("Warning:SHARE_NO_ROWS:")
                returnValues = []
            elif sessionAttributes and sessionAttributes['params']['features'].get('share_answers'):
                # share_answers: share using session_answers sheet
                answerSheet = getSheet(sheetName+'_answers')
                if not answerSheet:
                    raise Exception('Error::Sharing not possible without answer sheet '+sheetName+'_answers')
                ansColumnHeaders = answerSheet.getSheetValues(1, 1, 1, answerSheet.getLastColumn())[0]
                ansCol = 0
                for j in range(len(ansColumnHeaders)):
                    if ansColumnHeaders[j][:len(getShare)+1] == getShare+'_':
                        ansCol = j+1
                        break
                if not ansCol:
                    raise Exception('Error::Column '+getShare+'_* not present in headers for answer sheet '+sheetName+'_answers')
                nRows = answerSheet.getLastRow()-1
                ansColIndex = indexColumns(answerSheet)
                ids    = answerSheet.getSheetValues(2, ansColIndex['id'], nRows, 1)
                names  = answerSheet.getSheetValues(2, ansColIndex['name'], nRows, 1)
                values = answerSheet.getSheetValues(2, ansCol, nRows, 1)
                returnHeaders = [ 'id', getShare+'_response' ]
                returnValues = []
                for j in range(len(values)):
                    if names[j][0] and names[j][0][0] != '#' and values[j][0]:
                        returnValues.append([ids[j][0], values[j][0]])
                # Sort by response value
                returnValues.sort(key=lambda x: x[1])
            else:
                # Share using columns in session sheet (e.g., feature=share_all)
                nRows = modSheet.getLastRow()-numStickyRows
                respCol = getShare+'_response'
                respIndex = columnIndex.get(getShare+'_response')
                if not respIndex:
                    raise Exception('Error::Column '+respCol+' not present in headers for session '+sheetName)

                respOffset = 1

                nCols = 1

                explainOffset = 0
                if columnIndex.get(getShare+'_explain') == respIndex+nCols:
                    nCols += 1
                    explainOffset = nCols

                shareOffset = 0
                if columnIndex.get(getShare+'_share') == respIndex+nCols:
                    nCols += 1
                    shareOffset = nCols

                voteOffset = 0
                if shareParams.get('vote') and columnIndex.get(getShare+'_vote') == respIndex+nCols:
                    nCols += 1
                    voteOffset = nCols
                    if not shareOffset:
                        raise Exception('Error::Column '+respCol+' must have share and vote info for session '+sheetName)

                returnHeaders = columnHeaders[respIndex-1:respIndex-1+nCols]

                shareSubrow  = modSheet.getSheetValues(1+numStickyRows, respIndex, nRows, nCols)

                idValues     = modSheet.getSheetValues(1+numStickyRows, columnIndex['id'], nRows, 1)
                nameValues   = modSheet.getSheetValues(1+numStickyRows, columnIndex['name'], nRows, 1)
                timeValues   = modSheet.getSheetValues(1+numStickyRows, columnIndex['Timestamp'], nRows, 1)
                submitValues = modSheet.getSheetValues(1+numStickyRows, columnIndex['submitTimestamp'], nRows, 1)
                teamValues   = modSheet.getSheetValues(1+numStickyRows, columnIndex['team'], nRows, 1)
                lateValues   = modSheet.getSheetValues(1+numStickyRows, columnIndex['lateToken'], nRows, 1)

                curUserVals = None
                testUserVals = None
                curUserSubmitted = None
                testUserSubmitted = None

                returnHeaders = ['id'] + returnHeaders
                nCols += 1

                for j in range(nRows):
                    shareSubrow[j] = [idValues[j][0]] +  shareSubrow[j] # Prepend id

                    if shareSubrow[j][respOffset] == SKIP_ANSWER:
                        shareSubrow[j][respOffset] = ''
                    if idValues[j][0] == paramId:
                        curUserVals = shareSubrow[j]
                        curUserSubmitted = submitValues[j][0]
                    elif idValues[j][0] == TESTUSER_ID:
                        testUserVals = shareSubrow[j]
                        testUserSubmitted = submitValues[j][0]


                if not curUserVals and not adminUser:
                    raise Exception('Error::Sheet has no row for user '+paramId+' to share in session '+sheetName)

                votingCompleted = voteDate and sliauth.epoch_ms(voteDate) < sliauth.epoch_ms(curDate)

                voteParam = shareParams.get('vote')
                tallyVotes = voteParam and (adminUser or voteParam == 'show_live' or (voteParam == 'show_completed' and votingCompleted))
                curUserResponded = curUserVals and curUserVals[respOffset] and (not explainOffset or curUserVals[explainOffset])

                if not adminUser and paramId != TESTUSER_ID:
                    if paceLevel == ADMIN_PACE and (not testUserVals or (not testUserVals[respOffset] and not testUserSubmitted)):
                        raise Exception('Error:NOSHARE:Instructor must respond to question '+getShare+' or Submit before sharing in session '+sheetName)

                    if shareParams.get('share') == 'after_answering' and not curUserResponded and not curUserSubmitted:
                        raise Exception('Error:NOSHARE:User '+paramId+' must respond to question '+getShare+' or Submit before sharing on '+sheetName)

                disableVoting = False

                # If test/admin user, or current user has provided no response/no explanation, disallow voting
                if paramId == TESTUSER_ID or not curUserResponded:
                    disableVoting = True

                # If voting not enabled or voting completed, disallow voting.
                if not voteParam or votingCompleted:
                    disableVoting = True

                if voteOffset:
                    # Return user vote codes
                    if curUserVals:
                        returnInfo['vote'] = curUserVals[voteOffset]
                    if tallyVotes:
                        votes = {}
                        for j in range(nRows):
                            for voteCode in (shareSubrow[j][voteOffset] or '').split(','):
                                if not voteCode:
                                    continue
                                if voteCode in votes:
                                    votes[voteCode] += 1
                                else:
                                    votes[voteCode] = 1

                        # Replace vote code with vote counts
                        for j in range(nRows):
                            shareCode = shareSubrow[j][shareOffset]
                            shareSubrow[j][voteOffset] = votes.get(shareCode,0)

                    else:
                        # Voting results not yet released
                        for j in range(nRows):
                            shareSubrow[j][voteOffset] = None

                selfShare = ''
                if shareOffset:
                    if curUserVals:
                        selfShare = curUserVals[shareOffset]
                        returnInfo['share'] = '' if disableVoting else selfShare
                        
                    # Disable voting/self voting
                    # This needs to be done after vote tallying, because vote codes are cleared
                    for j in range(nRows):
                        if disableVoting or shareSubrow[j][shareOffset] == selfShare:
                            shareSubrow[j][shareOffset] = ''

                sortVotes = tallyVotes and (votingCompleted or adminUser or (voteParam == 'show_live' and paramId == TESTUSER_ID))
                sortVals = []
                teamResponded = {}
                responderTeam = {}
                includeId = {}

                # Traverse by reverse timestamp order
                timeIndex = []
                for j in range(nRows):
                    timeVal = sliauth.epoch_ms(timeValues[j][0]) if timeValues[j][0] else 0
                    timeIndex.append([timeVal, j])
                timeIndex.sort(reverse=True)

                for k in range(nRows):
                    j = timeIndex[k][1]

                    idValue = idValues[j][0]
                    if idValue == TESTUSER_ID:
                        # Ignore test user response
                        continue

                    # Always skip null responses and ungraded lates
                    if not shareSubrow[j][respOffset] or lateValues[j][0] == LATE_SUBMIT:
                        continue

                    # If voting, skip incomplete/late submissions
                    if voteParam and lateValues[j][0]:
                        continue

                    # If voting, skip if explanations expected and not provided
                    if voteParam and explainOffset and not shareSubrow[j][explainOffset]:
                        continue

                    # Process only one non-null response per team
                    if teamAttr and teamValues[j][0]:
                        teamName = teamValues[j][0]
                        if teamName in teamResponded:
                            continue
                        teamResponded[teamName] = 1
                        responderTeam[idValue] = teamName

                    includeId[idValue] = 1

                    # Use earlier of submit time or timestamp to sort
                    timeVal = submitValues[j][0] or timeValues[j][0]
                    timeVal = sliauth.epoch_ms(timeVal) if timeVal else 0

                    respVal = shareSubrow[j][respOffset]
                    if parseNumber(respVal) is not None:
                        respSort = parseNumber(respVal)
                    else:
                        respSort = respVal.lower()

                    if sortVotes:
                        # Voted: sort by (-) vote tally and then by response
                        sortVals.append( [-shareSubrow[j][voteOffset], respSort, j])
                    elif voteParam and not explainOffset:
                        # Voting on responses: sort by time and then response value
                        sortVals.append( [timeVal, respSort, j])
                    else:
                        # Explaining response or not voting; sort by response value and then time
                        sortVals.append( [respSort, timeVal, j] )

                sortVals.sort()

                if adminUser or paramId == TESTUSER_ID:
                    nameMap = getDisplayNames(includeNonRoster=True)
                    shortMap = makeShortNames(nameMap, first=True) if nameMap else {}
                    returnInfo['responders'] = []
                    if teamAttr == 'assign':
                        teamMembers = {}
                        for j in range(nRows):
                            idValue = idValues[j][0]
                            if shortMap and shortMap.get(idValue):
                                name = shortMap[idValue]
                            else:
                                name = idValue
                            teamName = shareSubrow[j][respOffset]
                            if teamName:
                                if teamName in teamMembers:
                                    teamMembers[teamName].append(name)
                                else:
                                    teamMembers[teamName] = [name]
                        teamNames = teamMembers.keys()
                        teamNames.sort()
                        for k in range(len(teamNames)):
                            returnInfo['responders'].append(teamNames[k]+': '+', '.join(teamMembers[teamNames[k]]))
                    else:
                        activeSession = releaseDate != FUTURE_DATE and not dueDate
                        sources = getRowMap(sheetName, 'source', regular=True)
                        for j in range(nRows):
                            idValue = idValues[j][0]
                            if not includeId.get(idValue):
                                continue
                            iSuffix = ''
                            if activeSession and sources.get(idValue) == 'interact':
                                iSuffix += '-'
                            if responderTeam.get(idValue):
                                returnInfo['responders'].append(responderTeam[idValue])
                            else:
                                returnInfo['responders'].append(idValue+'/'+shortMap.get(idValue,idValue)+iSuffix+'/'+nameMap.get(idValue,idValue))
                    returnInfo['responders'].sort()

                ##returnMessages.append('Debug::getShare: '+str(nCols)+', '+str(nRows)+', '+str(sortVals)+', '+str(curUserVals)+'')
                returnValues = []
                for x, y, j in sortVals:
                    returnValues.append( shareSubrow[j] )

        else:
            # Process single row get/put
            if rowUpdates and selectedUpdates:
                raise Exception('Error::Cannot specify both rowUpdates and selectedUpdates')
            elif rowUpdates:
                if len(rowUpdates) != len(columnHeaders):
                    raise Exception("Error::row_headers length (%s) differs from no. of columns (%s) in sheet %s; delete sheet or edit headers." % (len(rowUpdates), len(columnHeaders), sheetName) )

                userId = rowUpdates[columnIndex['id']-1] or ''
                displayName = rowUpdates[columnIndex['name']-1] or ''

                # Security check
                if paramId and paramId != userId:
                    raise Exception("Error::Mismatch between id '%s' and userId in row '%s'" % (paramId, userId))
                if params.get('name','') and params.get('name','') != displayName:
                    raise Exception("Error::Mismatch between params.get('name','') '%s' and displayName in row '%s'" % (params.get('name',''), displayName))
                if not adminUser and userId == MAXSCORE_ID:
                    raise Exception("Error::Only admin user may specify ID '%s'" % MAXSCORE_ID)
            else:
                userId = paramId or None

            if not userId:
                raise Exception('Error::userID must be specified for updates/gets')

            userRow = 0
            if modSheet.getLastRow() > numStickyRows and not loggingSheet:
                # Locate unique ID row (except for log files)
                userRow = lookupRowIndex(userId, modSheet, 1+numStickyRows)

            ##returnMessages.append('Debug::userRow, userid, rosterValues: '+userRow+', '+userId+', '+str(rosterValues))
            newRow = (not userRow)

            if newRow or resetRow or selectedUpdates or (rowUpdates and not nooverwriteRow):
                # Modifying sheet (somewhat redundant due to prior checks; just to be safe due to newRow creation)
                if Global.cacheUpdateError:
                    raise Exception('Error::All sessions are frozen due to cache update error: '+Global.cacheUpdateError);
                if limitedAccess:
                    raise Exception(limitedAccess)

            if adminUser and not restrictedSheet and newRow and userId != MAXSCORE_ID and not importSession:
                raise Exception("Error:ADMIN_NEW_ROW:Admin user not allowed to create new row in sheet '"+sheetName+"'")

            retakesCol = columnIndex.get('retakes')
            if resetRow:
                # Reset row
                if newRow:
                    raise Exception('Error:RETAKES:Cannot reset new row')
                if not sessionEntries:
                    raise Exception('Error:RETAKES:Reset only allowed for sessions')
                fieldsMin = sessionEntries['fieldsMin']
                newRow = True

                origVals = modSheet.getRange(userRow, 1, 1, len(columnHeaders)).getValues()[0]
                if adminUser or paramId == TESTUSER_ID:
                    # For admin or test user, also reset retakes count
                    retakesVal = ''
                else:
                    if origVals[columnIndex['submitTimestamp']-1]:
                        raise Exception('Error:RETAKES:Retakes not allowed for submitted sessions')

                    maxRetakes = sessionAttributes['params'].get('maxRetakes')
                    if not maxRetakes:
                        raise Exception('Error:RETAKES:Retakes not allowed')

                    retakesList = origVals[retakesCol-1].split(',') if origVals[retakesCol-1] else []
                    if len(retakesList) >= maxRetakes:
                        raise Exception('Error:RETAKES:No more retakes available')

                    # Save score for last take
                    lastTake = '0'
                    if computeTotalScore:
                        userScores = recomputeUserScores(columnHeaders, origVals, questions, sessionAttributes)
                        if userScores:
                            lastTake = str(scores.get('weightedCorrect') or 0)

                    # Update retakes score list
                    retakesList.append(lastTake)
                    retakesVal = ','.join(retakesList)

                createRow = origVals[columnIndex['source']-1]
                rowUpdates = createSessionRow(sheetName, sessionEntries['fieldsMin'], sessionAttributes['params'], questions,
                                              userId, origVals[columnIndex['name']-1], origVals[columnIndex['email']-1],
                                              origVals[columnIndex['altid']-1], createRow, retakesVal, seedRow)

                # Preserve name and lateToken on reset
                rowUpdates[columnIndex['name']-1] = origVals[columnIndex['name']-1]
                rowUpdates[columnIndex['lateToken']-1] = params.get('late') or origVals[columnIndex['lateToken']-1]
                returnInfo['resetRow'] = 1

            elif newRow and (not rowUpdates) and createRow:
                # Initialize new row
                if sessionEntries:
                    rowUpdates = createSessionRow(sheetName, sessionEntries['fieldsMin'], sessionAttributes['params'], questions,
                                                  userId, params.get('name', ''), params.get('email', ''), params.get('altid', ''),
                                                  createRow, seedRow)
                    displayName = rowUpdates[columnIndex['name']-1] or ''
                    if params.get('late') and columnIndex.get('lateToken'):
                        rowUpdates[columnIndex['lateToken']-1] = params['late']
                    returnInfo['createRow'] = 1
                else:
                    rowUpdates = []
                    for j in range(len(columnHeaders)):
                        rowUpdates.append(None)
                    if discussingSession:
                        displayName = params.get('name', '')
                        rowUpdates[columnIndex['id']-1] = userId
                        rowUpdates[columnIndex['name']-1] = displayName
                        
            teamCol = columnIndex.get('team')
            if newRow and rowUpdates and userId != MAXSCORE_ID:
                # New row
                if userId != TESTUSER_ID and paceLevel == ADMIN_PACE and not dueDate and Global.accessCodeCallback:
                    Global.accessCodeCallback(accessCode, userId, sheetName)

                if teamCol and sessionTeam and sessionTeam['session'] not in ('_assign', '_generate'):
                    # Set up teams, if not live setup
                    setupErrMsg = setupSessionTeam(sheetName)
                    if setupErrMsg:
                        raise Exception(setupErrMsg)
                    rowUpdates[teamCol-1] = getUserTeam(sheetName, userId)


            if newRow and getRow and not rowUpdates:
                # Row does not exist return empty list
                returnValues = []
                if not adminUser and timedSec:
                    returnInfo['timedSecLeft'] = timedSec

            elif newRow and selectedUpdates:
                raise Exception('Error::Selected updates cannot be applied to new row')
            else:
                pastSubmitDeadline = False
                autoSubmission = False
                fieldsMin = len(columnHeaders)
                submitTimestampCol = columnIndex.get('submitTimestamp')

                prevSubmitted = None
                if not newRow and submitTimestampCol:
                    prevSubmitted = modSheet.getSheetValues(userRow, submitTimestampCol, 1, 1)[0][0] or None

                if sessionEntries:
                    # Indexed session
                    fieldsMin = sessionEntries.get('fieldsMin')

                    if rowUpdates and not nooverwriteRow and prevSubmitted:
                        raise Exception("Error::Cannot re-submit session for user "+userId+" in sheet '"+sheetName+"'")

                    if voteDate:
                        returnInfo['voteDate'] = voteDate

                    if dueDate and not prevSubmitted and not voteSubmission and not discussionPost and not alterSubmission and userId != MAXSCORE_ID:
                        # Check if past submission deadline
                        lateToken = ''
                        pastSubmitDeadline = curTime > sliauth.epoch_ms(dueDate)
                        if pastSubmitDeadline:
                            lateTokenCol = columnIndex.get('lateToken')
                            lateToken = (rowUpdates[lateTokenCol-1] or None) if (rowUpdates and len(rowUpdates) >= lateTokenCol) else None
                            if not lateToken and not newRow:
                                lateToken = modSheet.getRange(userRow, lateTokenCol, 1, 1).getValues()[0][0] or ''

                            if not lateToken and (previewingSheet and userId == TESTUSER_ID):
                                lateToken = LATE_SUBMIT

                            if lateToken and ':' in lateToken:
                                # Check against new due date
                                newDueDate = getNewDueDate(userId, Settings['site_name'], sheetName, lateToken)
                                if not newDueDate:
                                    raise Exception("Error:INVALID_LATE_TOKEN:Invalid token for late submission by user "+(displayName or "")+" to session '"+sheetName+"'")

                                dueDate = newDueDate
                                pastSubmitDeadline = curTime > sliauth.epoch_ms(dueDate)

                        returnInfo['dueDate'] = dueDate # May have been updated

                        allowLateMods = adminUser or importSession or Settings['no_late_token'] or lateToken == LATE_SUBMIT
                        if not allowLateMods:
                            if pastSubmitDeadline:
                                if getRow and not (newRow or rowUpdates or selectedUpdates):
                                    # Reading existing row; force submit
                                    autoSubmission = True
                                    selectedUpdates = [ ['id', userId], ['Timestamp', None], ['submitTimestamp', None] ]
                                    returnMessages.append("Warning:FORCED_SUBMISSION:Forced submission of user "+(displayName or userId)+" for session "+sheetName)
                                else:
                                    # Creating/modifying row
                                    raise Exception("Error:PAST_SUBMIT_DEADLINE:Past submit deadline ("+str(dueDate)+") for session "+sheetName)
                            elif (sliauth.epoch_ms(dueDate) - curTime) < 2*60*60*1000:
                                returnMessages.append("Warning:NEAR_SUBMIT_DEADLINE:Nearing submit deadline ("+str(dueDate)+") for session "+sheetName)

                numRows = modSheet.getLastRow()
                if newRow and not resetRow:
                    # New user; insert row in sorted order of name (except for log files)
                    if (userId != MAXSCORE_ID and not displayName and not loggingSheet) or not rowUpdates:
                        raise Exception('Error::User name and row parameters required to create a new row for id '+userId+' in sheet '+sheetName)

                    if loggingSheet and numRows > LOG_MAX_ROWS+10:
                        # Limit size of log file
                        nDelRows = numRows - LOG_MAX_ROWS
                        modSheet.deleteRows(2, nDelRows)
                        numRows -= nDelRows

                    if numRows > numStickyRows and not loggingSheet:
                        displayNames = modSheet.getSheetValues(1+numStickyRows, columnIndex['name'], numRows-numStickyRows, 1)
                        userIds = modSheet.getSheetValues(1+numStickyRows, columnIndex['id'], numRows-numStickyRows, 1)
                        userRow = numStickyRows + locateNewRow(displayName, userId, displayNames, userIds)
                        if userId == MAXSCORE_ID and userRow != numStickyRows+1:
                            raise Exception('Error::Inconsistent _maxscore row insert in row '+str(userRow)+' in sheet '+sheetName)
                    else:
                        userRow = numRows+1

                    modSheet.insertRowBefore(userRow, keyValue=userId)
                    numRows += 1
                    # (q_total formula will be updated by proxy handler in script)

                elif rowUpdates and nooverwriteRow:
                    if getRow:
                        # Simply return existing row
                        rowUpdates = None
                    else:
                        raise Exception('Error::Do not specify nooverwrite=1 to overwrite existing rows')

                maxCol = len(rowUpdates) if rowUpdates else len(columnHeaders)
                totalCol = columnIndex.get('q_total', 0)
                scoresCol = columnIndex.get('q_scores', 0)
                userRange = modSheet.getRange(userRow, 1, 1, maxCol)
                rowValues = userRange.getValues()[0]

                if not adminUser and timedSec:
                    # Updating timed session
                    initTime = rowValues[columnIndex['initTimestamp']-1]
                    if initTime:
                        timedSecLeft = timedSec - (curTime - sliauth.epoch_ms(initTime))/1000.
                    else:
                        timedSecLeft = timedSec
                        IOLoop.current().call_later(timedSecLeft+TIMED_GRACE_SEC+5, submit_timed_session, userId, sheetName)
                    if timedSecLeft >= 1:
                        if not prevSubmitted:
                            returnInfo['timedSecLeft'] = int(timedSecLeft)
                    elif timedSecLeft < -TIMED_GRACE_SEC and rowUpdates:
                        raise Exception('Error:TIMED_EXPIRED:Past deadline for timed session.')

                returnInfo['prevTimestamp'] = sliauth.epoch_ms(rowValues[columnIndex['Timestamp']-1]) if ('Timestamp' in columnIndex and rowValues[columnIndex['Timestamp']-1]) else None
                if returnInfo['prevTimestamp'] and params.get('timestamp','') and parseNumber(params.get('timestamp','')) and returnInfo['prevTimestamp'] > 1+parseNumber(params.get('timestamp','')):
                    ##returnMessages.append('Debug::prevTimestamp, timestamp: %s %s' % (returnInfo['prevTimestamp'] , params.get('timestamp','')) )
                    raise Exception('Error::Row timestamp too old by '+str(math.ceil(returnInfo['prevTimestamp']-parseNumber(params.get('timestamp',''))) / 1000)+' seconds. Conflicting modifications from another active browser session?')

                teamCopyCols = []
                if rowUpdates:
                    # Update all non-null and non-id row values
                    # Timestamp is always updated, unless it is specified by admin
                    if adminUser and sessionEntries and userId != MAXSCORE_ID and not importSession and not resetRow:
                        raise Exception("Error::Admin user not allowed to update full rows in sheet '"+sheetName+"'")

                    if submitTimestampCol and rowUpdates[submitTimestampCol-1] and userId != TESTUSER_ID:
                        raise Exception("Error::Submitted session cannot be re-submitted for sheet '"+sheetName+"'")

                    if (not adminUser or importSession) and len(rowUpdates) > fieldsMin:
                        # Check if there are any user provided non-null values for "extra" columns (i.e., response/explain values:
                        nonNullExtraColumn = False
                        adminColumns = {}
                        for j in range(fieldsMin, len(columnHeaders)):
                            if rowUpdates[j] is not None:
                                nonNullExtraColumn = True
                            hmatch = QFIELD_RE.match(columnHeaders[j])
                            if not hmatch or (hmatch.group(2) != 'response' and hmatch.group(2) != 'explain' and hmatch.group(2) != 'plugin'):
                                # Non-response/explain/plugin admin column
                                adminColumns[columnHeaders[j]] = 1

                        if nonNullExtraColumn and not adminUser:
                            # Blank out admin columns if any extra column is non-null
                            # Failsafe: ensures admin-entered grades will be blanked out if response/explain are updated
                            for j in range(fieldsMin, len(columnHeaders)):
                                if columnHeaders[j] in adminColumns:
                                    rowUpdates[j] = ''

                        if totalCol:
                            # Filled by array formula
                            rowUpdates[totalCol-1] = ''

                        ##returnMessages.append("Debug::"+str(nonNullExtraColumn)+str(adminColumns.keys())+totalGradesFormula)

                    ##returnMessages.append("Debug:ROW_UPDATES:"+str(rowUpdates))
                    for j in range(len(rowUpdates)):
                        colHeader = columnHeaders[j]
                        colValue = rowUpdates[j]
                        if colHeader == 'retakes' and not newRow:
                            # Retakes are always updated separately
                            pass
                        elif colHeader == 'Timestamp':
                            # Timestamp is always updated, unless it is explicitly specified by admin
                            if adminUser and colValue:
                                rowValues[j] = createDate(colValue)
                            else:
                                rowValues[j] = curDate

                        elif colHeader == 'initTimestamp' and newRow:
                            rowValues[j] = curDate
                        elif colHeader == 'submitTimestamp' and params.get('submit',''):
                            if userId == TESTUSER_ID and colValue:
                                # Only test user may overwrite submitTimestamp
                                rowValues[j] = createDate(colValue)
                            else:
                                if paceLevel == ADMIN_PACE and userId != TESTUSER_ID and not dueDate:
                                    raise Exception("Error::Cannot submit instructor-paced session before instructor for sheet '"+sheetName+"'")
                                rowValues[j] = curDate
                                if teamCol and rowValues[teamCol-1]:
                                    teamCopyCols.append(j+1)
                            returnInfo['submitTimestamp'] = rowValues[j]

                        elif colHeader.endswith('_share'):
                            # Generate share value by computing message digest of 'response [: explain]'
                            if j >= 1 and rowValues[j-1] and rowValues[j-1] != SKIP_ANSWER and columnHeaders[j-1].endswith('_response'):
                                # Upvote response
                                rowValues[j] = sliauth.digest_hex(normalizeText(rowValues[j-1]))
                            elif j >= 2 and rowValues[j-1] and columnHeaders[j-1].endswith('_explain') and columnHeaders[j-2].endswith('_response'):
                                # Upvote response: explanation
                                rowValues[j] = sliauth.digest_hex(rowValues[j-1]+': '+normalizeText(rowValues[j-2]))
                            else:
                                rowValues[j] = ''

                        elif colValue is None:
                            # Do not modify field
                            pass
                        elif newRow or (colHeader not in MIN_HEADERS and not colHeader.endswith('Timestamp')):
                            # Id, name, email, altid, *Timestamp cannot be updated programmatically
                            # (If necessary to change name manually, then re-sort manually)
                            if colHeader.lower().endswith('date') or colHeader.lower().endswith('time'):
                                try:
                                    rowValues[j] = createDate(colValue)
                                except Exception, err:
                                    pass
                            else:
                                hmatch = QFIELD_RE.match(colHeader)
                                teamAttr = ''
                                if hmatch and (hmatch.group(2) == 'response' or hmatch.group(2) == 'explain' or hmatch.group(2) == 'plugin'):
                                    qno = int(hmatch.group(1))
                                    if questions and qno <= len(questions):
                                        teamAttr = questions[qno-1].get('team','')
                                if teamAttr == 'response' and rowValues[teamCol-1]:
                                    # Copy response/explain/plugin for team
                                    teamCopyCols.append(j+1)
                                    if hmatch and hmatch.group(2) == 'response':
                                        shareCol = columnIndex.get('q'+hmatch.group(1)+'_share')
                                        if shareCol:
                                            # Copy share code
                                            teamCopyCols.append(shareCol)

                                rowValues[j] = colValue
                        else:
                            if rowValues[j] != colValue:
                                raise Exception("Error::Cannot modify column '"+colHeader+"'. Specify as 'null'")

                    if userId != MAXSCORE_ID and scoresCol and computeTotalScore:
                        # Tally user scores after row updates
                        userScores = recomputeUserScores(columnHeaders, rowValues, questions, sessionAttributes)
                        if userScores:
                            rowValues[scoresCol-1] = userScores.get('weightedCorrect', '')

                    # Copy user info from roster (if available)
                    if rosterValues:
                        for j in range(len(MIN_HEADERS)):
                            rowValues[j] = rosterValues.get(MIN_HEADERS[j], '')

                    # Save updated row
                    userRange.setValues([rowValues])

                    if userId == MAXSCORE_ID and not TOTAL_COLUMN:
                        # Refresh sheet cache if max score row is updated (for re-computed totals)
                        modSheet.expire()
                        expireSheet(GRADES_SHEET)

                    if sessionEntries and adminPaced and paramId == TESTUSER_ID:
                        # AdminPaced test user row update
                        lastSlideCol = columnIndex.get('lastSlide')
                        if lastSlideCol and rowValues[lastSlideCol-1]:
                            # Copy test user last slide number as new adminPaced value
                            adminPaced = rowValues[lastSlideCol-1]
                            setValue(sheetName, 'adminPaced', adminPaced, INDEX_SHEET)

                            if discussableSession:
                                # Close all open discussions
                                closeDiscussion(sheetName)

                        if params.get('submit'):
                            # Use test user submission time as due date for admin-paced sessions
                            adminPacedUpdate(sheetName, modSheet, numStickyRows, rowValues[submitTimestampCol-1])

                elif selectedUpdates:
                    # Update selected row values
                    # Timestamp is updated only if specified in list
                    if not autoSubmission and not voteSubmission and not discussionPost and not twitterSetting:
                        if not adminUser:
                            raise Exception("Error::Only admin user allowed to make selected updates to sheet '"+sheetName+"'")

                        if sessionEntries:
                            # Admin can modify grade columns only for submitted sessions before 'effective' due date
                            # and only for non-late submissions thereafter
                            allowGrading = prevSubmitted or (pastSubmitDeadline and lateToken != LATE_SUBMIT)
                            if not allowGrading and not importSession and not alterSubmission:
                                raise Exception("Error::Cannot selectively update non-submitted/non-late session for user "+userId+" in sheet '"+sheetName+"'")

                    if voteSubmission:
                        # Allow vote submissions only after due date and before voting deadline
                        if voteSubmission == 'after_due_date' and (not dueDate or sliauth.epoch_ms(dueDate) > sliauth.epoch_ms(curDate)):
                            raise Exception("Error:TOO_EARLY_TO_VOTE:Voting only allowed after due date for sheet '"+sheetName+"'")
                        if voteSubmission == 'after_grading' and not gradeDate:
                            raise Exception("Error:TOO_EARLY_TO_VOTE:Voting only allowed after grading for sheet '"+sheetName+"'")
                        if voteDate and sliauth.epoch_ms(voteDate) < sliauth.epoch_ms(curDate):
                            raise Exception("Error:TOO_LATE_TO_VOTE:Voting not allowed after vote date for sheet '"+sheetName+"'")

                    for j in range(len(selectedUpdates)):
                        colHeader = selectedUpdates[j][0]
                        colValue = selectedUpdates[j][1]

                        if not (colHeader in columnIndex):
                            raise Exception("Error::Field "+colHeader+" not found in sheet '"+sheetName+"'")

                        headerColumn = columnIndex[colHeader]
                        modValue = None

                        if colHeader == 'Timestamp':
                            # Timestamp is always updated, unless it is explicitly specified by admin
                            if voteSubmission:
                                # Do not modify timestamp for voting (to avoid race conditions with grading etc.)
                                pass
                            elif adminUser and colValue:
                                modValue = createDate(colValue)
                            else:
                                modValue = curDate

                        elif colHeader == 'submitTimestamp':
                            if autoSubmission:
                                modValue = curDate
                            elif alterSubmission:
                                if colValue is None:
                                    modValue = curDate
                                elif colValue:
                                    modValue = createDate(colValue)
                                else:
                                    # Unsubmit if blank value (also clear lateToken)
                                    modValue = ''
                                    modSheet.getRange(userRow, columnIndex['lateToken'], 1, 1).setValues([[ '' ]])

                                if sessionEntries and adminPaced and paramId == TESTUSER_ID:
                                    # Update/clear due date and submit others if necessary
                                    adminPacedUpdate(sheetName, modSheet, numStickyRows, modValue)

                                if modValue:
                                    returnInfo['submitTimestamp'] = modValue
                            elif adminUser and colValue:
                                modValue = createDate(colValue)

                            if rowValues[teamCol-1]:
                                # Broadcast submission to all team members
                                teamCopyCols.append(headerColumn)

                        elif colHeader.endswith('_vote'):
                            if voteSubmission and colValue:
                                # Cannot un-vote, vote can be transferred
                                otherCol = columnIndex.get('q_other')
                                if not rowValues[headerColumn-1] and otherCol and sessionEntries.get('otherWeight') and sessionAttributes.get('shareAnswers'):
                                    # Tally newly added vote
                                    qshare = sessionAttributes['shareAnswers'].get(colHeader.split('_')[0])
                                    if qshare:
                                        rowValues[otherCol-1] = str(int(rowValues[otherCol-1] or 0) + qshare.get('voteWeight',0))
                                        modSheet.getRange(userRow, otherCol, 1, 1).setValues([[ rowValues[otherCol-1] ]])
                            modValue = colValue

                        elif colHeader.startswith('discuss') and discussionPost:
                            prevValue = rowValues[headerColumn-1]
                            if prevValue and not POST_PREFIX_RE.match(prevValue):
                                raise Exception('Invalid discussion post entry in column '+colHeader+' for session '+sheetName)
                            if colValue.lower().startswith('delete:'):
                                # Delete post
                                modValue = deletePost(prevValue, colValue, userId, rosterName, adminUser, discussionPost[0], discussionPost[1])
                            else:
                                # New post; append
                                modValue, newPost = postDiscussEntry(discussionPost[0], discussionPost[1], discussionPost[2], userId, rosterName, prevValue, colValue)
                                notifyDiscussUsers(discussionPost[0], discussionPost[1], discussionPost[2], 'new', userId, rosterName, newPost)

                        elif colValue is None:
                            # Do not modify field
                            pass

                        elif colHeader not in MIN_HEADERS and not colHeader.endswith('Timestamp'):
                            # Update row values for header (except for id, name, email, altid, *Timestamp)
                            if not restrictedSheet and not twitterSetting and not importSession and (headerColumn <= fieldsMin or not QFIELD_MOD_RE.match(colHeader)):
                                raise Exception("Error::Cannot selectively update user-defined column '"+colHeader+"' in sheet '"+sheetName+"'")

                            if colHeader.lower().endswith('date') or colHeader.lower().endswith('time'):
                                try:
                                    colValue = createDate(colValue)
                                except Exception, err:
                                    pass
                            else:
                                hmatch = QFIELD_RE.match(colHeader)
                                if hmatch and (hmatch.group(2) == 'grade' or hmatch.group(2) == 'comments'):
                                    qno = int(hmatch.group(1))
                                    if rowValues[teamCol-1] and questions and qno <= len(questions) and questions[qno-1].get('team','') == 'response':
                                        # Broadcast question grade/comments to all team members (q_other/q_comments are not broadcast)
                                        teamCopyCols.append(headerColumn)

                            modValue = colValue
                        else:
                            if rowValues[headerColumn-1] != colValue:
                                raise Exception("Error::Cannot modify column '"+colHeader+"'. Specify as 'null'")

                        if modValue is not None:
                            rowValues[headerColumn-1] = modValue
                            modSheet.getRange(userRow, headerColumn, 1, 1).setValues([[ rowValues[headerColumn-1] ]])

                    if discussionPost:
                        returnInfo['discussPosts'] = getDiscussPosts(discussionPost[0], discussionPost[1], TESTUSER_ID if adminUser else userId, rosterName)

                if len(teamCopyCols):
                    nCopyRows = numRows-numStickyRows
                    idValues = modSheet.getSheetValues(1+numStickyRows, columnIndex['id'], nCopyRows, 1)
                    teamValues = modSheet.getSheetValues(1+numStickyRows, teamCol, nCopyRows, 1)
                    userOffset = userRow-numStickyRows-1
                    teamName = teamValues[userOffset][0]
                    if teamName:
                        returnInfo['teamModifiedIds'] = []
                        for j in range(len(idValues)):
                            if teamValues[j][0] == teamName:
                                returnInfo['teamModifiedIds'].append(idValues[j][0])

                        for j in range(len(teamCopyCols)):
                            # Broadcast modified team values
                            teamCopy(modSheet, numStickyRows, userRow, teamCol, teamCopyCols[j])

                if (paramId != TESTUSER_ID or prevSubmitted or params.get('submit')) and sessionEntries and adminPaced:
                    # Set adminPaced for testuser only upon submission
                    returnInfo['adminPaced'] = adminPaced

                if sessionEntries and adminPaced:
                    teamStatus = getTeamStatus(sheetName)
                    if teamStatus and len(teamStatus):
                        returnInfo['teamStatus'] = teamStatus

                if sessionEntries and getRow:
                    # Return user/team file access keys
                    today = str(datetime.date.today())
                    returnInfo['userFileKey'] = sliauth.gen_file_key(Settings['auth_key'], sheetName, paramId, timestamp=today)
                    if teamCol and rowValues[teamCol-1]:
                        returnInfo['team'] = rowValues[teamCol-1]
                        returnInfo['teamFileKey'] = sliauth.gen_file_key(Settings['auth_key'], sheetName, rowValues[teamCol-1], timestamp=today)

                # Return updated timestamp
                returnInfo['timestamp'] = sliauth.epoch_ms(rowValues[columnIndex['Timestamp']-1]) if ('Timestamp' in columnIndex) else None
                returnValues = rowValues if getRow else []

                if not adminUser and (not gradeDate or not rowValues[submitTimestampCol-1]):
                    # If session not graded/submitted, blank out grade-related columns
                    for j in range(fieldsMin, len(returnValues)):
                        if not columnHeaders[j].endswith('_response') and not columnHeaders[j].endswith('_explain') and not columnHeaders[j].endswith('_plugin'):
                            returnValues[j] = None
                elif not adminUser and gradeDate:
                    returnInfo['gradeDate'] = sliauth.iso_date(gradeDate, utc=True)

                if not adminUser and params.get('getstats',''):
                    # Blank out cumulative grade-related columns from gradebook
                    for j in range(len(GRADE_HEADERS)):
                        cname = GRADE_HEADERS[j]
                        cindex = columnIndex.get(cname)
                        if not cindex:
                            continue
                        if ( (cname == 'total' and not('cumulative_total' in gradebookRelease)) or
                             (cname != 'total' and not('cumulative_grade' in gradebookRelease)) or
                             not returnInfo.get('lastUpdate') ):
                            returnValues[cindex-1] = ''
                            if returnInfo.get('maxScores'):
                                returnInfo['maxScores'][cindex-1] = ''
                            if returnInfo.get('rescale'):
                                returnInfo['rescale'][cindex-1] = ''
                            if returnInfo.get('averages'):
                                returnInfo['averages'][cindex-1] = ''

                if getRow and createRow and discussableSession and userId != MAXSCORE_ID:
                    # Accessing discussable session
                    returnInfo['discussStats'] = getDiscussStats(userId, sheetName)

                if computeTotalScore and getRow:
                    returnInfo['remoteAnswers'] = sessionAttributes.get('remoteAnswers')

        if sessionEntries and getRow and allRows and adminUser:
            returnInfo['sessionFileKey'] = sliauth.gen_file_key(Settings['auth_key'], sheetName, '')

        if sessionEntries and getRow and (allRows or (createRow and paramId == TESTUSER_ID) or params.get('getheaders','')):
            # Getting all session rows or test user row (with creation option); return related sheet names
            returnInfo['sheetsAvailable'] = modSheet.relatedSheets[:]

        if getRow and createRow and proxy_error_status():
            returnInfo['proxyError'] = 'Read-only mode; session modifications are disabled'

        if completeActions:
            actionHandler(','.join(completeActions), sheetName);

        # return json success results
        retObj = {"result": "success", "value": returnValues, "headers": returnHeaders,
                  "info": returnInfo,
                  "messages": '\n'.join(returnMessages)}

    except Exception, err:
        # if error, return this
        if Settings['debug'] and not notrace and (not err.message or not err.message.startswith('Error:NOSHEET:Sheet')):
            import traceback
            traceback.print_exc()

        retObj = {"result": "error", "error": err.message, "value": None,
                  "info": returnInfo,
                  "messages": '\n'.join(returnMessages)}

    if Settings['debug'] and not notrace and retObj['result'] != 'success':
        print("DEBUG: RETOBJ", retObj['result'], retObj.get('error'), retObj.get('messages'), file=sys.stderr)
    
    return retObj

def recomputeUserScores(columnHeaders, rowValues, questions, sessionAttributes):
    savedSession = unpackSession(columnHeaders, rowValues)
    if savedSession and len(savedSession.get('questionsAttempted').keys()):
        return tallyScores(questions, savedSession.get('questionsAttempted'), savedSession.get('hintsUsed'), sessionAttributes.get('params'), sessionAttributes.get('remoteAnswers'))
    return None

def submit_timed_session(userId, sessionName):
    sessionSheet = getSheet(sessionName)
    if not sessionSheet:
        return
    userRow = lookupRowIndex(userId, sessionSheet)
    if not userRow:
        return
    columnIndex = indexColumns(sessionSheet)
    submitTimestampCol = columnIndex.get('submitTimestamp')
    submittedRange = sessionSheet.getRange(userRow, submitTimestampCol, 1, 1)
    if submittedRange.getValues()[0][0]:
        return

    # Submit session for user
    submittedRange.setValues([[ createDate() ]])

    if Settings['debug']:
        print("DEBUG: submit_timed_session: SUBMITTED", userId, sessionName, file=sys.stderr)

def adminPacedUpdate(sheetName, modSheet, numStickyRows, submitTimestamp):
    # Use test user submission time as due date for admin-paced sessions
    setValue(sheetName, 'dueDate', submitTimestamp, INDEX_SHEET)

    if not submitTimestamp:
        return

    # Submit all other users who have started a session
    columnIndex = indexColumns(modSheet)
    submitTimestampCol = columnIndex.get('submitTimestamp')

    idRowIndex = indexRows(modSheet, columnIndex['id'])
    idColValues = getColumns('id', modSheet, 1, 1+numStickyRows)
    nameColValues = getColumns('name', modSheet, 1, 1+numStickyRows)
    initColValues = getColumns('initTimestamp', modSheet, 1, 1+numStickyRows)
    for j in range(len(idColValues)):
        if initColValues[j] and idColValues[j] and idColValues != TESTUSER_ID and idColValues[j] != MAXSCORE_ID:
            modSheet.getRange(idRowIndex[idColValues[j]], submitTimestampCol, 1, 1).setValues([[submitTimestamp]])

def gen_proxy_token(username, role=''):
    prefixed = role in (ADMIN_ROLE, GRADER_ROLE)
    return sliauth.gen_auth_token(Settings['auth_key'], username, role=role, prefixed=prefixed)

def getSiteRole(siteName, siteRoles):
    # Return role for site or None
    scomps = siteRoles.split(',')
    for j in range(len(scomps)):
        smatch = re.match(r'^([^\+]+)(\+(\w+))?$', scomps[j])
        if smatch and smatch.group(1) == siteName:
            return smatch.group(3) or ''
    return None

def isSpecialUser(userId):
    if userId in Settings['root_users']:
        return True

    for key in ('admin_users', 'grader_users', 'guest_users'):
        idList = [x.strip() for x in Settings[key].strip().split(',')]
        if userId in idList:
            return True

    return False

def getRosterEntry(userId):
    if userId == TESTUSER_ID:
        return TESTUSER_ROSTER
    try:
        # Copy user info from roster
        return lookupValues(userId, TESTUSER_ROSTER.keys(), ROSTER_SHEET, False, True)
    except Exception, err:
        if isSpecialUser(userId):
            return {'name': '#'+userId+', '+userId, 'id': userId}
        raise Exception("Error:NEED_ROSTER_ENTRY:userID '"+userId+"' not found in roster")

class LCRandomClass(object):
    # Set to values from http://en.wikipedia.org/wiki/Numerical_Recipes
    # m is basically chosen to be large (as it is the max period)
    # and for its relationships to a and c
    nbytes = 4
    m = 2**(nbytes*8)
    # a - 1 should be divisible by prime factors of m
    a = 1664525
    # c and m should be co-prime
    c = 1013904223
    @classmethod
    def makeSeed(cls, val=None):
        return (val % cls.m) if val else random.randint(0,cls.m)

    def __init__(self):
        self.sequences = {}

    def setSeed(self, seedValue=None):
        # Start new random number sequence using seed value as the label
        label = seedValue or ''
        self.sequences[label] = self.makeSeed(seedValue)
        return label

    def uniform(self, seedValue=None):
        # define the recurrence relationship
        label = seedValue or ''
        if label not in self.sequences:
            raise Exception('Random number generator not initialized properly:'+str(label))
        self.sequences[label] = (self.a * self.sequences[label] + self.c) % self.m
        # return a float in [0, 1) 
        # if sequences[label] = m then sequences[label] / m = 0 therefore (sequences[label] % m) / m < 1 always
        return self.sequences[label] / float(self.m)

    def randomNumber(self, *args):
        # randomNumber(seedValue, min, max)
	    # Equally probable integer values between min and max (inclusive)
        # If min is omitted, equally probable integer values between 1 and max
        # If both omitted, value uniformly distributed between 0.0 and 1.0 (<1.0)
        if len(args) <= 1:
            return self.uniform(*args);
        if len(args) == 2:
            maxVal = args[1]
            minVal = 1
        else:
            maxVal = args[2]
            minVal = args[1]
	    return min(maxVal, int(math.floor( minVal + (maxVal-minVal+1)*self.uniform(args[0]) )))

LCRandom = LCRandomClass()

RandomChoiceOffset = 1
RandomParamOffset = 2
def makeRandomChoiceSeed(randomSeed):
    return LCRandom.makeSeed(RandomChoiceOffset+randomSeed)

def makeRandomParamSeed(randomSeed):
    return LCRandom.makeSeed(RandomParamOffset+randomSeed)

def makeRandomFunction(seed):
    LCRandom.setSeed(seed);
    return functools.partial(LCRandom.randomNumber, seed)

def shuffleArray(array, randFunc=None):
    # Durstenfeld shuffle
    randFunc = randFunc or random.randint;
    for i in reversed(range(1,len(array))):
        j = randFunc(0, i)
        temp = array[i]
        array[i] = array[j]
        array[j] = temp
    return array

def randomLetters(n, noshuffle, randFunc=None):
    letters = []
    for i in range(n):
        letters.append(chr(ord('A')+i))

    nmix = max(0, n - noshuffle)
    if nmix > 1:
        cmix = letters[:nmix]
        shuffleArray(cmix, randFunc)
        letters = cmix + letters[nmix:]
    return ''.join(letters)

NUM_RE = re.compile(r'^[+-]?(\d+)(\.\d*)?([eE][+-]?\d+)?$')
def defaultDelta(minval, maxval, mincount, maxcount):
    # Return "nice" delta interval (10/5/1/0.5/0.1, ...) for dividing the range minval to maxval
    minmatch = NUM_RE.match(str(minval))
    maxmatch = NUM_RE.match(str(maxval))
    if not minmatch or not maxmatch:
        return mincount
    values = []
    exponents = []
    for match in (minmatch, maxmatch):
        if not match.group(2) and not match.group(3):
            values.append( int(match.group(1)) )
        else:
            values.append( float(match.group(0)) )
        if match.group(2):
            exp = -(len(match.group(2))-1)
        else:
            num = match.group(1)
            exp = 0
            while num[-1] == '0':
                exp += 1
                num = num[:-1]
        if match.group(3):
            exp += int(match.group(3)[1:])
        exponents.append(exp)
    diff = abs(values[1] - values[0])
    if not diff:
        return 1
    minexp = min(exponents)
    delta = 10**minexp
    mulfac = 5

    while (diff/delta) > maxcount:
        delta = delta * mulfac
        mulfac = 2 if mulfac == 5 else 5

    while (diff/delta) < mincount:
        mulfac = 2 if mulfac == 5 else 5
        if delta > 1:
            delta = delta / mulfac
        else:
            delta = float(delta) / mulfac
    return delta

def rangeVals(minstr, maxstr, delstr='', mincount=20, maxcount=200):
    # Returns range of values from minstr to maxstr, spaced by delstr
    minval = parseNumber(minstr)
    maxval = parseNumber(maxstr)
    if minval == None or maxval == None:
        return []
    if not delstr:
        delta = defaultDelta(minstr, maxstr, mincount, maxcount)
    else:
        delta = parseNumber(delstr)
    if not delta or minval > maxval:
        return []
    elif minval == maxval:
        return [minval]
    else:
        nvals = int(1.001 + (maxval - minval) / abs(delta))
        return [minval + m*delta for m in range(0,nvals)]

def createSession(sessionName, params, questions=None, retakes='', randomSeed=None):
    persistPlugins = {}
    for pluginName in params['plugins']:
        persistPlugins[pluginName] = {}

    if not randomSeed:
        randomSeed = LCRandom.makeSeed()

    qshuffle = None
    if questions is not None and params['features'].get('shuffle_choice'):
        randFunc = makeRandomFunction(makeRandomChoiceSeed(randomSeed))
        qshuffle = {}
        for qno in range(1,len(questions)+1):
            choices = questions[qno-1].get('choices',0)
            alternatives = min(9, questions[qno-1].get('alternatives') or 0)
            noshuffle = questions[qno-1].get('noshuffle',0)

            if qno > 1 and questions[qno-1].get('followup',0):
                qshuffle[qno] = qshuffle[qno-1][0]
            else:
                qshuffle[qno] = str(randFunc(0,alternatives))

            if choices:
                qshuffle[qno] +=  randomLetters(choices, noshuffle, randFunc)

    paramValues = None
    if params.get('paramDefinitions') and len(params.get('paramDefinitions')):
        randFunc = makeRandomFunction(makeRandomParamSeed(randomSeed))
        paramValues = []
        paramDefinitions = params.get('paramDefinitions')
        for j in range(0,len(paramDefinitions)):
            slideValues = {}
            try:
                pcomps = paramDefinitions[j].split(';')
                for k in range(0,len(pcomps)):
                    dcomps = pcomps[k].split('=')
                    defname  =  dcomps[0]
                    defrange =  '='.join(dcomps[1:])
                    rcomps = defrange.split(':')
                    if len(rcomps) == 1:
                        vals = []
                        svals = rcomps[0].split(',')
                        for m in range(0,len(svals)):
                            val = parseNumber(svals[m])
                            if val != None:
                                vals.append(val)
                    else:
                        vals = rangeVals(rcomps[0], rcomps[1], rcomps[2] if len(rcomps) > 2 else '')
                    if len(vals):
                        slideValues[defname] = vals[ randFunc(0,len(vals)-1) ]
            except Exception, excp:
                pass
            paramValues.append(slideValues)

    return {'version': params.get('sessionVersion'),
	    'revision': params.get('sessionRevision'),
	    'paced': params.get('paceLevel', 0),
	    'submitted': None,
	    'displayName': '',
	    'source': '',
	    'team': '',
	    'lateToken': '',
	    'lastSlide': 0,
        'retakes': retakes,
	    'randomSeed': randomSeed,        # Save random seed
        'expiryTime': sliauth.epoch_ms() + 180*86400*1000,  # 180 day lifetime
        'startTime': sliauth.epoch_ms(),
        'lastTime': 0,
        'lastTries': 0,
        'remainingTries': 0,
        'tryDelay': 0,
	    'showTime': None,
	    'paramValues': paramValues,
        'questionShuffle': qshuffle,
        'questionsAttempted': {},
	    'hintsUsed': {},
	    'plugins': persistPlugins
	   }

def createSessionRow(sessionName, fieldsMin, params, questions, userId, displayName='', email='', altid='', source='', retakes='', randomSeed=None):
    headers = params['sessionFields'] + params['gradeFields']
    idCol = headers.index('id') + 1
    nameCol = headers.index('name') + 1
    emailCol = headers.index('email') + 1
    altidCol = headers.index('altid') + 1
    session = createSession(sessionName, params, questions, retakes, randomSeed)
    rowVals = []
    for j in range(len(headers)):
        rowVals.append('')
        header = headers[j]
        if header in session and header in COPY_HEADERS:
            rowVals[j] = session[header]

    rowVals[headers.index('source')] = source
    rowVals[headers.index('session_hidden')] = sliauth.ordered_stringify(session)

    rosterSheet = getSheet(ROSTER_SHEET)
    if rosterSheet:
        rosterValues = getRosterEntry(userId)

        if rosterValues:
            for j in range(len(MIN_HEADERS)):
                if rosterValues.get(MIN_HEADERS[j]):
                    rowVals[j] = rosterValues[MIN_HEADERS[j]]

    # Management fields
    rowVals[idCol-1] = userId

    if not rowVals[nameCol-1]:
        if not displayName:
            raise Exception('Name parameter must be specified to create row')
        rowVals[nameCol-1] = displayName

    if not rowVals[emailCol-1] and email:
        rowVals[emailCol-1] = email
    
    if not rowVals[altidCol-1] and altid:
        rowVals[altidCol-1] = altid
    
    return rowVals

    
def getUserRow(sessionName, userId, displayName, opts={}, notrace=False):
    if opts.get('admin'):
        token = gen_proxy_token(ADMINUSER_ID, ADMIN_ROLE)
    else:
        token = gen_proxy_token(userId)
    getParams = {'id': userId, 'token': token,'sheet': sessionName,
                 'name': displayName, 'get': '1'}
    getParams.update(opts)

    return sheetAction(getParams, notrace=notrace)

def getAllRows(sessionName, opts={}, notrace=False):
    token = gen_proxy_token(ADMINUSER_ID, ADMIN_ROLE)
    getParams = {'admin': ADMINUSER_ID, 'token': token,'sheet': sessionName,
                 'get': '1', 'all': '1'}
    getParams.update(opts)

    return sheetAction(getParams, notrace=notrace)

def putUserRow(sessionName, userId, rowValues, opts={}, notrace=False):
    if opts.get('admin'):
        token = gen_proxy_token(ADMINUSER_ID, ADMIN_ROLE)
    else:
        token = gen_proxy_token(userId)
    putParams = {'id': userId, 'token': token,'sheet': sessionName,
                 'row': json.dumps(rowValues, default=sliauth.json_default)}
    putParams.update(opts)

    return sheetAction(putParams, notrace=notrace)

def updateUserRow(sessionName, headers, updateObj, opts={}, notrace=False):
    if opts.get('admin'):
        token = gen_proxy_token(ADMINUSER_ID, ADMIN_ROLE)
    else:
        token = gen_proxy_token(updateObj['id'])
    updates = []
    for j, header in enumerate(headers):
        if header in updateObj:
            updates.append( [header, updateObj[header]] )

    params = {'id': updateObj['id'], 'token': token,'sheet': sessionName,
                    'update': json.dumps(updates, default=sliauth.json_default)}
    params.update(opts)

    return sheetAction(params, notrace=notrace)

def makeRosterMap(colName, lowercase=False, unique=False):
    # Return map of other IDs from colName to roster ID
    # If unique, raise exception for duplicated values in colName
    colValues = lookupRoster(colName) or {}
    rosterMap = OrderedDict()
    for userId, otherIds in colValues.items():
        if colName == 'name':
            comps = [otherIds]
        elif colName == 'altid':
            comps = [str(otherIds)]
        else:
            comps = otherIds.strip().split(',')
        for otherId in comps:
            otherId = otherId.strip()
            if lowercase:
                otherId = otherId.lower()
            if otherId:
                if unique and otherId in rosterMap:
                    raise Exception('Duplicate occurrence of %s value %s' % (colName, otherId))
                rosterMap[otherId] = userId
    return rosterMap

def exportAnswers(sessionName):
    retval = getAllRows(sessionName, {'getheaders': '1'}, notrace=True)
    if retval['result'] != 'success':
	    raise Exception('Error in exporting session '+sessionName+': '+retval.get('error'))
    headers = retval['headers']
    allRows = retval['value']
    headerCols = dict((hdr, j+1) for j, hdr in enumerate(headers))
    sessionCol = headerCols['session_hidden']
    responseCols = {}
    explainCols = {}
    qmaxCols = 0
    for j, header in enumerate(headers):
        hmatch = QFIELD_RE.match(header)
        if hmatch:
            qnumber = int(hmatch.group(1))
            qmaxCols = max( qmaxCols, qnumber )
            if hmatch.group(2) == 'response':
                responseCols[qnumber] = j+1
            elif hmatch.group(2) == 'explain':
                explainCols[qnumber] = j+1
        
    if Settings['debug']:
        print("DEBUG:exportAnswers", sessionName, qmaxCols, file=sys.stderr)
    outRows = []
    qmaxAll = qmaxCols
    explainSet = set(explainCols.keys())
    for j, rowValues in enumerate(allRows):
        qmaxRow = qmaxCols
        qShuffle = None
        qAttempted = None
        session_hidden = rowValues[sessionCol-1]
        if session_hidden:
            session = loadSession(session_hidden)
            qShuffle = session.get('questionShuffle')
            qAttempted = session['questionsAttempted']
            if qAttempted:
                qmaxRow = max(qmaxRow, max(int(key) for key in qAttempted.keys()) ) # Because JSON serialization converts integer keys to strings
        qmaxAll = max(qmaxAll, qmaxRow)

        rowOutput = [sliauth.str_encode(rowValues[headerCols[hdr]-1]) for hdr in MIN_HEADERS]
        for qnumber in range(1,qmaxRow+1):
            cellValue = ''
            if qnumber in responseCols:
                cellValue = rowValues[responseCols[qnumber]-1]
                if qnumber in explainCols:
                    cellValue += ' ' + rowValues[explainCols[qnumber]-1]
            elif qAttempted and qnumber in qAttempted:
                cellValue = qAttempted[qnumber].get('response','')
                if qAttempted[qnumber].get('explain',''):
                    explainSet.add(qnumber)
                    cellValue += ' ' + sliauth.str_encode(qAttempted[qnumber]['explain'])
            if cellValue == SKIP_ANSWER:
                cellValue = ''
            if cellValue and qShuffle:
                shuffleStr = qShuffle.get(qnumber,'')
                if shuffleStr:
                    try:
                        indexVal = shuffleStr.index(cellValue.upper())
                        cellValue = chr(ord('A') + indexVal-1)
                    except Exception, excp:
                        raise Exception("Unable to unshuffle choice '"+cellValue+"' for user "+rowOutput[0]+"when exporting session "+sessionName)
            rowOutput.append(cellValue)
        outRows.append(rowOutput)

    memfile = cStringIO.StringIO()
    writer = csv.writer(memfile)
    outHeaders = MIN_HEADERS + [ ('qx' if qnumber in explainSet else 'q')+str(qnumber) for qnumber in range(1,qmaxAll+1)]
    writer.writerow(outHeaders)
    for j in range(len(outRows)):
        # Ensure all rows have the same number of columns
        temRow = outRows[j] + ['']*(len(outHeaders)-len(outRows[j]))
        writer.writerow(temRow)

    content = memfile.getvalue()
    memfile.close()
    return content


def createUserRow(sessionName, userId, displayName='', lateToken='', source=''):
    create = source or 'import'
    retval = getUserRow(sessionName, userId, displayName, {'admin': ADMINUSER_ID, 'import': '1', 'create': create, 'getheaders': '1'}, notrace=False)
    if retval['result'] != 'success':
	    raise Exception('Error in creating session for user '+userId+': '+retval.get('error'))
    headers = retval['headers']
    if lateToken:
        updateObj = {'id': userId, 'lateToken': lateToken}
        retval = updateUserRow(sessionName, headers, updateObj, {'admin': ADMINUSER_ID, 'import': '1'})
        if retval['result'] != 'success':
            raise Exception('Error in setting late token for user '+userId+': '+retval.get('error'))

def timeColumn(header):
    return header.lower().endswith('date') or header.lower().endswith('time') or header.endswith('Timestamp');

def randomTime():
    return datetime.datetime.fromtimestamp( sliauth.epoch_ms() * random.uniform(0.1, 1.05)/1000. )

def unsafeTriggerUpdates(sessionName, modCols, insertRows, startRow=3):
    # WARNING: Destructive testing of sheet updates. Use only on test sessions, NEVER on production sessions
    # Inserts random values in specified list of columns to trigger updates
    testSheet = getSheet(sessionName)
    headers = testSheet.getSheetValues(1, 1, 1, testSheet.getLastColumn())[0]
    nrows = testSheet.getLastRow() - startRow + 1
    retval = ''

    print("WARNING:unsafeTestUpdates: Destructive testing of sheet updates", sessionName, modCols, insertRows, file=sys.stderr)
    if modCols:
        randCols = []
        randVals = [[]]
        for m in range(nrows):
            randVals.append([])

        for j in range(len(modCols)):
            modCol = modCols[j]
            header = headers[modCol-1]
            randCols.append(header)
            randVals[0].append(header)
            for m in range(nrows):
                randValue = randomTime() if timeColumn(header) else random.randint(0,100)
                testSheet.getRange(startRow+m, modCol, 1, 1).setValue(randValue)
                randVals[m+1].append(randValue)

        f = io.BytesIO()
        pprint.pprint(randVals, stream=f)
        retval = f.getvalue()

    for j in range(len(insertRows)):
        randNum = random.randint(1111,9999)
        randId = 'I%d' % randNum
        if insertRows[j] > 3:
            randName = '%s%d' % (testSheet.getSheetValues(insertRows[j]-1, 1, 1, 1)[0][0], randNum)
        else:
            randName = '#name%d' % randNum
        testSheet.insertRowBefore(insertRows[j], randId);
        testSheet.getRange(insertRows[j], 1, 1, 2).setValues([[randName, randId]])

    return retval
        
def updateTotalScores(modSheet, sessionAttributes, questions, force, startRow=0, nRows=0):
    # If not force, only update non-blank entries
    # Return number of rows updated
    if not questions:
        return 0
    columnHeaders = modSheet.getSheetValues(1, 1, 1, modSheet.getLastColumn())[0]
    columnIndex = indexColumns(modSheet)
    nUpdates = 0
    startRow = startRow or 2
    nRows = nRows or modSheet.getLastRow()-startRow+1

    if Settings['debug']:
        print("DEBUG:updateTotalScores", nRows)
    if nRows > 0:
        # Update total scores
        idVals = modSheet.getSheetValues(startRow, columnIndex['id'], nRows, 1)
        scoreValues = modSheet.getSheetValues(startRow, columnIndex['q_scores'], nRows, 1)
        for k in range(nRows):
            if idVals[k][0] != MAXSCORE_ID and (force or scoreValues[k][0] != ''):
                temRowVals = modSheet.getSheetValues(startRow+k, 1, 1, len(columnHeaders))[0]
                savedSession = unpackSession(columnHeaders, temRowVals)
                newScore = '';
                if savedSession and savedSession.get('questionsAttempted'):
                    scores = tallyScores(questions, savedSession['questionsAttempted'], savedSession['hintsUsed'], sessionAttributes['params'], sessionAttributes['remoteAnswers'])
                    newScore = scores.get('weightedCorrect', '')
                if scoreValues[k][0] != newScore:
                    modSheet.getRange(startRow+k, columnIndex['q_scores'], 1, 1).setValues([[newScore]])
                    nUpdates += 1
    return nUpdates


def clearQuestionResponses(sessionName, questionNumber, userId=''):
    if Settings['debug']:
        print("DEBUG:clearResponse", sessionName, questionNumber, userId, file=sys.stderr)
    sessionSheet = getSheet(sessionName)
    if not sessionSheet:
        raise Exception('Session '+sessionName+' not found')

    columnHeaders = sessionSheet.getSheetValues(1, 1, 1, sessionSheet.getLastColumn())[0]
    columnIndex = indexColumns(sessionSheet)

    if userId:
        idRowIndex = indexRows(sessionSheet, columnIndex['id'])
        startRow = idRowIndex.get(userId)
        if not startRow:
            raise Exception('User id '+userId+' not found in session '+sessionName)
        nRows = 1
    else:
        startRow = 3
        nRows = sessionSheet.getLastRow()-startRow+1

    submitTimestampCol = columnIndex.get('submitTimestamp')
    submits = sessionSheet.getSheetValues(startRow, submitTimestampCol, nRows, 1)
    for j in range(len(submits)):
        if submits[j][0]:
            raise Exception('Cannot clear question response for submitted sessions');

    blanks = []
    for k in range(nRows):
        blanks.append([''])

    qprefix = 'q'+str(questionNumber)
    clearedResponse = False
    for j in range(len(columnHeaders)):
        header = columnHeaders[j]
        if header.split('_')[0] == qprefix:
            clearedResponse = True
            sessionSheet.getRange(startRow, j+1, nRows, 1).setValues(blanks)

    if not clearedResponse:
        sessionCol = columnIndex.get('session_hidden')
        for k in range(nRows):
            sessionRange = sessionSheet.getRange(k+startRow, sessionCol, 1, 1)
            session_hidden = sessionRange.getValue()
            if not session_hidden:
                continue
            if session_hidden[0] != '{':
                session_hidden = base64.b64decode(session_hidden)
            session = loadSession(session_hidden)
            if 'questionsAttempted' in session and questionNumber in session['questionsAttempted']:
                clearedResponse = True
                del session['questionsAttempted'][questionNumber]
                sessionRange.setValue(sliauth.ordered_stringify(session))

    if clearedResponse:
        # Update total score
        sessionEntries = lookupValues(sessionName, ['questions', 'attributes'], INDEX_SHEET)
        sessionAttributes = json.loads(sessionEntries['attributes'])
        questions = json.loads(sessionEntries['questions'])
        updateTotalScores(sessionSheet, sessionAttributes, questions, True, startRow, nRows)
        return True
    else:
        return False


def deleteSlide(sessionName, slideNumber):
    # Return deleted question number or 0
    if Settings['debug']:
        print("DEBUG:deleteSlide", sessionName, slideNumber, file=sys.stderr)
    sessionSheet = getSheet(sessionName)
    if not sessionSheet:
        raise Exception('Session '+sessionName+' not found')

    columnHeaders = sessionSheet.getSheetValues(1, 1, 1, sessionSheet.getLastColumn())[0]
    columnIndex = indexColumns(sessionSheet)
    idRowIndex = indexRows(sessionSheet, columnIndex['id'])

    testRow = idRowIndex.get(TESTUSER_ID)
    if testRow:
        testSubmitted = sessionSheet.getSheetValues(testRow, columnIndex['submitTimestamp'], 1, 1)[0][0]
    else:
        testSubmitted = ''

    sessionEntries = lookupValues(sessionName, ['adminPaced', 'questions', 'attributes'], INDEX_SHEET)
    adminPaced = sessionEntries.get('adminPaced')
    questions = json.loads(sessionEntries['questions'])
    sessionAttributes = json.loads(sessionEntries['attributes'])

    maxLastSlide = sessionAttributes['params']['pacedSlides'] - 1

    if not maxLastSlide:
        raise Exception('Cannot delete sole slide in session')
    
    if adminPaced:
        if slideNumber <= adminPaced and testSubmitted:
            raise Exception('Cannot delete viewed slide from submitted admin-paced session')

        if slideNumber == adminPaced:
            # Deleting last viewed slide
            maxLastSlide = adminPaced-1
            setValue(sessionName, 'adminPaced', adminPaced-1, INDEX_SHEET)
        else:
            maxLastSlide = adminPaced
    else:
        raise Exception('Delete slide only implemented for admin-paced sessions')

    # Reset last slide value
    setColumnMax(sessionSheet, 3, columnIndex.get('lastSlide'), maxLastSlide)

    delete_qno = 0
    for qno in range(1,len(questions)+1):
        if questions[qno-1].get('slide') == slideNumber:
            delete_qno = qno
            break

    if delete_qno:
        # Deleting question slide; Clear any responses
        if clearQuestionResponses(sessionName, delete_qno):
            # Update answer stats
            sessionSheet.requestActions('answer_stats')

    return delete_qno


def importUserAnswers(sessionName, userId, displayName='', answers={}, submitDate=None, source=''):
    # answers = {1:{'response':, 'explain':},...}
    # If source == "prefill", only row creation occurs
    if Settings['debug']:
        print("DEBUG:importUserAnswers", userId, displayName, sessionName, len(answers), submitDate, file=sys.stderr)
    if not getSheet(sessionName):
        raise Exception('Session '+sessionName+' not found')
    sessionEntries = lookupValues(sessionName, ['dueDate', 'paceLevel', 'adminPaced', 'attributes'], INDEX_SHEET)
    dueDate = sessionEntries.get('dueDate')
    paceLevel = sessionEntries.get('paceLevel')
    adminPaced = sessionEntries.get('adminPaced')
    sessionAttributes = json.loads(sessionEntries['attributes'])
    timedSec = sessionAttributes['params'].get('timedSec')
    if timedSec and source == "prefill":
        raise Exception('Cannot prefill timed session '+sessionName)

    if submitDate == 'dueDate':
        submitDate = dueDate or None

    if submitDate:
        # Check that it is a valid date
        createDate(submitDate)

    create = source or 'import'
    retval = getUserRow(sessionName, userId, displayName, {'admin': ADMINUSER_ID, 'import': '1', 'create': create, 'getheaders': '1'}, notrace=True)
    if retval['result'] != 'success':
	    raise Exception('Error in creating session for user '+userId+': '+retval.get('error'))
    if source == "prefill":
        return
    headers = retval['headers']
    rowValues = retval['value']
    headerCols = dict((hdr, j+1) for j, hdr in enumerate(headers))
    sessionCol = headerCols['session_hidden']
    session = loadSession(rowValues[sessionCol-1])
    qShuffle = session.get('questionShuffle')
    qAttempted = session['questionsAttempted']
    qnumbers = answers.keys()
    qnumbers.sort()
    for qnumber in qnumbers:
        q_response = 'q%d_response' % qnumber
        q_explain = 'q%d_explain' % qnumber
        q_grade = 'q%d_grade' % qnumber
        answer = answers[qnumber]
        respVal = answer.get('response', '')
        if qShuffle:
            shuffleStr = qShuffle.get(qnumber,'') or qShuffle.get(qnumber,'')
            if shuffleStr and respVal:
                # Import shuffled response value
                indexVal = ord(respVal.upper()) - ord('A')
                if indexVal < 0 or indexVal >= len(shuffleStr[1:]):
                    if Settings['debug']:
                        print('DEBUG:importUserAnswers: ERROR for user %s, question %d: Invalid choice %s (%s)' % (userId, qnumber, respVal, shuffleStr), file=sys.stderr)
                    respVal = ''
                else:
                    respVal = shuffleStr[1:][indexVal].upper()
        if q_response in headers:
            rowValues[headerCols[q_response]-1] = respVal or SKIP_ANSWER
            if q_explain in headers:
                rowValues[headerCols[q_explain]-1] = answer.get('explain', '')
        else:
            qAttempted[qnumber] = createQuestionAttempted( respVal )
            if 'explain' in answer:
                qAttempted[qnumber]['explain'] = answer['explain']
        if q_grade in headers and 'grade' in answer:
            rowValues[headerCols[q_grade]-1] = answer['grade']

    rowValues[sessionCol-1] = sliauth.ordered_stringify(session)
    for j, header in enumerate(headers):
        if header.endswith('Timestamp'):
            rowValues[j] = None             # Do not modify (most) timestamps

    putOpts = {'admin': ADMINUSER_ID, 'import': '1' }
    submitTimestamp = None
    if paceLevel == ADMIN_PACE:
        if userId == TESTUSER_ID:
            # Import first to set paced slides etc.
            rowValues[headerCols['lastSlide']-1] = sessionAttributes['params']['pacedSlides']
            if submitDate:
                rowValues[headerCols['submitTimestamp']-1] = submitDate
                putOpts['submit'] = '1'
        else:
            rowValues[headerCols['lastSlide']-1] = adminPaced or sessionAttributes['params']['pacedSlides']
            if submitDate:
                submitTimestamp = submitDate
    else:
        rowValues[headerCols['lastSlide']-1] = sessionAttributes['params']['pacedSlides']
        if submitDate:
            submitTimestamp = submitDate

    retval = putUserRow(sessionName, userId, rowValues, putOpts, notrace=True)
    if retval['result'] != 'success':
	    raise Exception('Error in importing session for user '+userId+': '+retval.get('error'))

    if submitTimestamp:
        updateObj = {'id': userId, 'submitTimestamp': submitTimestamp}
        retval = updateUserRow(sessionName, headers, updateObj, {'admin': ADMINUSER_ID, 'import': '1'}, notrace=True)
        if retval['result'] != 'success':
            raise Exception('Error in submitting imported session for user '+userId+': '+retval.get('error'))

def importSheet(sheetName, headers, rows, overwrite=None):
    # Restore sheet from backup file
    ##if Settings['debug']:
    ##    print("DEBUG:importSheet", sheetName, ','.join(headers), len(rows), overwrite, file=sys.stderr)
    oldSheet = getSheet(sheetName)
    if oldSheet:
        if overwrite:
            delSheet(sheetName)
        else:
            raise Exception('Cannot overwrite sheet %s for import' % sheetName)

    # Convert numeric strings to numbers
    rows = [ [parseNumber(x) if isNumber(x) else x for x in row] for row in rows]

    if Settings['gsheet_url']:
        # Synchronously create sheet
        user = ADMINUSER_ID
        userToken = gen_proxy_token(user, ADMIN_ROLE)

        post_data = {'sheet': sheetName, 'proxy': '1', 'createsheet': '1', 'admin': user, 'token': userToken}
        post_data['headers'] = json.dumps(headers)
        post_data['rows'] = json.dumps(rows, default=sliauth.json_default)
        if overwrite:
            post_data['overwrite'] = 1

        http_client = tornado.httpclient.HTTPClient()
        response = http_client.fetch(Settings['gsheet_url'], method='POST', headers=None, body=urllib.urlencode(post_data))
        errMsg = ''
        if response.error:
            errMsg = str(response.error)
        else:
            try:
                respObj = json.loads(response.body)
                if respObj['result'] == 'error':
                    errMsg = respObj['error']
            except Exception, err:
                errMsg = 'JSON parsing error: '+str(err)

            ##if Settings['debug']:
            ##    print("DEBUG:importSheet: resp=", respObj, file=sys.stderr)

        if errMsg:
            raise Exception('Error in importing sheet %s: %s' % (sheetName, errMsg))
        newSheet = getSheet(sheetName, require=True)
    else:
        newSheet = createSheet(sheetName, headers, rows=rows)
        ## Expire sheet to force re-read from update remote cache (essential if sheet contains formulas) NOT NEEDED ANYMORE
        ## newSheet.expire()

def createRoster(headers, rows, overwrite=False):
    if headers[:4] != MIN_HEADERS:
        raise Exception('Error: Invalid headers for roster_slidoc; first four should be "'+', '.join(MIN_HEADERS)+'", but found "'+', '.join(headers or [])+'"')

    idSet = set()
    rosterRows = []
    for row in rows:
        row = row[:]
        if len(row) != len(headers):
            raise Exception('Incorrect no. of columns in imported roster row: '+str(row))
        if not row[0] :
            raise Exception('Null name field not allowed in imported roster row: '+str(row))
        if not row[1]:
            raise Exception('Null ID field not allowed in imported roster row: '+str(row))
        if row[1] in idSet:
            raise Exception('Duplicate id found in imported roster row: '+row[1])
        idSet.add(row[1])
        if row[1][0] == '_':
            raise Exception('Underscore not allowed at start of id in imported roster row: '+row[1])

        if not row[0][0].isalpha() and row[0][0] != '#':
            raise Exception('Invalid start character in imported name '+row[0])
        if row[0].count(',') > 1:
            raise Exception('Multiple commas not allowed in imported name: '+row[0])
        lastName, _, firstNames = row[0].partition(',')
        row[0] = makeName(lastName, firstNames)
        rosterRows.append(row)
        
    test_user_row = ['#User, Test', TESTUSER_ID] + ['']*(len(headers)-2)
    rosterRows.insert(0, test_user_row)
    rosterRows.sort()
    rosterSheet = getSheet(ROSTER_SHEET)
    if rosterSheet and not overwrite:
        raise Exception('Roster sheet already present; specify overwrite during import')
    return createSheet(ROSTER_SHEET, headers, overwrite=overwrite, rows=rosterRows)
        
def getRowMap(sheetName, colName, regular=False, optional=False, startRow=2):
    # Return dict of id->value in sheet (if regular, only for names defined and not starting with #)
    # if optional, return None if column not found
    sheet = getSheet(sheetName)
    if not sheet:
        raise Exception('Sheet '+sheetName+' not found')
    colIndex = indexColumns(sheet)
    if colName not in colIndex:
        if optional:
            return None
        raise Exception('Column '+colName+' not found in sheet '+sheetName)
    nRows = sheet.getLastRow()-startRow+1
    rowMap = {}
    if nRows > 0:
        names = sheet.getSheetValues(startRow, colIndex['name'], nRows, 1)
        rowIds = sheet.getSheetValues(startRow, colIndex['id'], nRows, 1)
        vals = sheet.getSheetValues(startRow, colIndex[colName], nRows, 1)
        for j, rowId in enumerate(rowIds):
            if not rowId[0]:
                continue
            if regular and (not names[j][0] or names[j][0].startswith('#')):
                continue
            rowMap[rowId[0]] = vals[j][0]
    return rowMap

def lookupRoster(field, userId=None, regular=False):
    # If not userId, return all entries for field as a dict
    # if regular, only for names defined and not starting with #)
    rosterSheet = getSheet(ROSTER_SHEET)
    if not rosterSheet:
        return None

    headers = rosterSheet.getHeaders()
    if not headers or headers[:4] != MIN_HEADERS:
        raise Exception('CUSTOM:Error: Invalid headers in roster_slidoc; first four should be "'+', '.join(MIN_HEADERS)+'", but found "'+', '.join(headers or [])+'"')

    colIndex = indexColumns(rosterSheet)
    if not colIndex.get(field):
        return None

    if userId:
        rowIndex = indexRows(rosterSheet, colIndex['id'], 2)
        if not rowIndex.get(userId):
            return None
        return lookupValues(userId, [field], ROSTER_SHEET, True)[0]

    idVals = getColumns('id', rosterSheet, 1, 2)
    names = getColumns('name', rosterSheet, 1, 2)
    fieldVals = getColumns(field, rosterSheet, 1, 2)
    fieldDict = OrderedDict()
    for j, idVal in enumerate(idVals):
        if regular and (not names[j] or names[j].startswith('#')):
            continue
        fieldDict[idVal] = fieldVals[j]
    return fieldDict

NAME_RE = re.compile(r'[a-z][a-z-]*( +[a-z][a-z-]*)* *(,( *[a-z][a-z-]*)( +[a-z][a-z-]*)*)?$', re.IGNORECASE)
def makeId(displayName, idVals):
    # Creates ids of the form: 'lastname-firstname@'
    # (guaranteed to be different from any email id)
    if not NAME_RE.match(displayName):
        raise Exception('Invalid name "%s"; must be of the form "Last Name, First And Middle"' % displayName)

    lastnames, _, firstnames = displayName.partition(',')
    lastnames = lastnames.strip().split()
    firstnames = firstnames.strip().split() if firstnames else []
    idPrefix = '-'.join(lastnames).lower()
    if firstnames:
        j = 0
        idPrefix += '-' + firstnames[j].lower()
        while idPrefix+'@' in idVals:
            j += 1
            if j < len(firstnames):
                idPrefix = idPrefix + '-' + firstnames[j].lower()
            else:
                raise Exception('Unable to generate unique id for name "%s"' % displayName)
    return idPrefix+'@'
    

def splitCapitalize(names):
    return ' '.join( name.capitalize() for name in names.strip().split() )

def makeName(lastName, firstNames, middleNames=''):
    name = splitCapitalize(lastName)
    if name.startswith('#'):
        name = name[0] + name[1:].capitalize()
    if firstNames.strip():
        name += ', ' + splitCapitalize(firstNames)
        if middleNames.strip():
            name += ' ' +splitCapitalize(middleNames)
    return name

def getRosterHeaders():
    # Return list of user profile-related headers
    rosterSheet = getSheet(ROSTER_SHEET)
    if not rosterSheet:
        return None
    headers = []
    for header in rosterSheet.getHeaders():
        if header.startswith('_'):
            break
        headers.append(header)
    return headers

def editRosterValues(rowDict, overwrite=False):
    rosterSheet = getSheet(ROSTER_SHEET)
    if not rosterSheet:
        return None

    headers = getRosterHeaders()
    nameVals = getColumns('name', rosterSheet, 1, 2)
    idVals = getColumns('id', rosterSheet, 1, 2)

    if 'name' not in rowDict:
        raise Exception('Name required for new roster entry')

    if not NAME_RE.match(rowDict['name']):
        raise Exception('Invalid name "%s"; must be of the form "Last Name, First And Middle"' % rowDict['name'])

    if 'status' in rowDict:
        rowDict['status'] = rowDict['status'].strip()
        if rowDict['status'] and rowDict['status'] not in (BLOCKED_STATUS, DROPPED_STATUS):
            raise Exception('Invalid status value "%s"; must be one of %s' % (rowDict['status'], (BLOCKED_STATUS, DROPPED_STATUS)))

    if not rowDict.get('id','').strip():
        idVal = makeId(rowDict['name'], idVals)
        rowDict = rowDict.copy()
        rowDict['id'] = idVal
        
    if rowDict['id'] in idVals:
        userRow = 2 + idVals.index(rowDict['id'])
        if not overwrite:
            return rosterSheet.getSheetValues(userRow, 1, 1, len(headers))[0]
    else:
        if overwrite:
            raise Exception('Id %s not found in roster for editing' % rowDict['id'])
        userRow = 1 + locateNewRow(rowDict['name'], rowDict['id'], nameVals, idVals)
        rosterSheet.insertRowBefore(userRow, keyValue=rowDict['id'])

    rowVals = [ rowDict.get(header, '') for header in  headers]
    rosterSheet.getRange(userRow, 1, 1, len(rowVals)).setValues([rowVals])
    return None
    
def getRosterValues(idVal, delete=False):
    rosterSheet = getSheet(ROSTER_SHEET)
    if not rosterSheet:
        return None

    idVals = getColumns('id', rosterSheet, 1, 2)
    if idVal not in idVals:
        return None
    userRow = 2 + idVals.index(idVal)
    headers = getRosterHeaders()
    oldValues = rosterSheet.getSheetValues(userRow, 1, 1, len(headers))[0]
    if delete:
        rosterSheet.deleteRow(userRow)
    return oldValues

def getAttendanceDays():
    # Return list of attendance days ['yyyy-mm-dd', ...]
    rosterSheet = getSheet(ROSTER_SHEET)
    if not rosterSheet:
        return []
    return [header[len(DAY_PREFIX):] for header in rosterSheet.getHeaders() if header.startswith(DAY_PREFIX)]

def getAttendance(day, new=False):
    # Return list [ [name, userid, 1/0/''], ... ] for column _day_yyyy-mm-dd
    rosterSheet = getSheet(ROSTER_SHEET)
    if not rosterSheet:
        return None

    dayColName = DAY_PREFIX+day
    dayCol = indexColumns(rosterSheet).get(DAY_PREFIX+day)
    if not dayCol and not new:
        raise Exception('Attendance column %s not found in roster sheet' % dayColName)
    if new:
        if dayCol:
            raise Exception('New attendance column %s already present in roster sheet' % dayColName)
        rosterSheet.appendColumns([dayColName])
        dayCol = len(rosterSheet.getHeaders())
    nameVals = getColumns('name', rosterSheet, 2, 2)
    dayVals = getColumns(dayColName, rosterSheet, 1, 2)
    retVals = []
    for j, dayVal in enumerate(dayVals):
        if not nameVals[j][0].startswith('#'):
            retVals.append(nameVals[j]+[dayVal])
    return retVals

def toggleAttendance(day, userId):
    rosterSheet = getSheet(ROSTER_SHEET)
    dayColName = DAY_PREFIX+day
    colIndex = indexColumns(rosterSheet)
    dayCol = colIndex.get(dayColName)
    dayRow = indexRows(rosterSheet, colIndex['id'], 2).get(userId)
    if not dayCol:
        raise Exception('Attendance column %s not found in roster sheet' % dayColName)
    if not dayRow:
        raise Exception('Attendance for user %s not found in roster sheet' % userId)
    rng = rosterSheet.getRange(dayRow, dayCol, 1, 1)
    newVal = 0 if rng.getValue() else 1
    rng.setValue(newVal)
    return newVal


AGGREGATE_COL_RE = re.compile(r'\b(_\w+)_(avg|normavg|sum)(_(\d+))?$', re.IGNORECASE)
def lookupGrades(userId, admin=False):
    scoreSheet = getSheet(GRADES_SHEET)
    if not scoreSheet:
        return None

    colIndex = indexColumns(scoreSheet)
    rowIndex = indexRows(scoreSheet, colIndex['id'], 2)
    userRow = lookupRowIndex(userId, scoreSheet)
    if not userRow:
        return None

    gradebookRelease = set( split_list(Settings.get('gradebook_release', ''), lower=True) )

    headers = scoreSheet.getHeaders()
    nCols = len(headers)
    lastUpdate = scoreSheet.getSheetValues(rowIndex['_timestamp'], colIndex['total'], 1, 1)[0][0].strip()
    userScores = scoreSheet.getSheetValues(userRow, 1, 1, nCols)[0]
    rescale = scoreSheet.getSheetValues(rowIndex['_rescale'], 1, 1, nCols)[0]
    average = scoreSheet.getSheetValues(rowIndex['_average'], 1, 1, nCols)[0]
    maxscore = scoreSheet.getSheetValues(rowIndex['_max_score'], 1, 1, nCols)[0]

    grades = {}
    sessionGrades = []
    gradebookStatus = ''
    for j, header in enumerate(headers):
        if header in ('total', 'grade'):
            if admin:
                pass
            elif not lastUpdate:
                continue
            elif header == 'total' and not('cumulative_total' in gradebookRelease):
                continue
            elif header != 'total' and not('cumulative_grade' in gradebookRelease):
                continue
        elif header == 'status' and admin:
            gradebookStatus = rescale[j]
        elif not header.startswith('_'):
            continue

        colGrades = {'score': parseNumber(userScores[j]) if header != 'grade' else userScores[j],
                     'rescale': rescale[j],
                     'average': parseNumber(average[j]),
                     'maxscore': parseNumber(maxscore[j])
                     } 
        if header.startswith('_'):
            amatch = AGGREGATE_COL_RE.match(header)
            if amatch:
                header = amatch.group(1)[1:] + '_' + amatch.group(2)
            sessionGrades.append( [header, colGrades] )
        else:
            grades[header] = colGrades

    grades['sessions'] = sessionGrades
    grades['lastUpdate'] = lastUpdate
    grades['status'] = gradebookStatus
    return grades

def lookupSessions(colNames):
    indexSheet = getSheet(INDEX_SHEET)
    if not indexSheet:
        return []

    colIndex = indexColumns(indexSheet)
    rowIndex = indexRows(indexSheet, colIndex['id'], 2)
    idVals = getColumns('id', indexSheet, 1, 2)
    fieldVals = []
    for idVal in idVals:
        fieldVals.append( [idVal, lookupValues(idVal, colNames, INDEX_SHEET, listReturn=True)] )
    return fieldVals


WUSCORE_RE = re.compile(r'[_\W]')
ARTICLE_RE = re.compile(r'\b(a|an|the) ')
MSPACE_RE  = re.compile(r'\s+')

def normalizeText(s):
    # Lowercase, replace single/double quotes with null, all other non-alphanumerics with spaces,
    # replace 'a', 'an', 'the' with space, and then normalize spaces
    if isinstance(s, unicode):
        s = s.encode('utf-8')
    s = str(s)
    return MSPACE_RE.sub(' ', WUSCORE_RE.sub(' ', ARTICLE_RE.sub(' ', s.lower().replace("'",'').replace('"','') ))).strip()

def isNumber(x):
    return parseNumber(x) is not None

def parseNumber(x):
    try:
        if type(x) in (str, unicode):
            if '.' in x or 'e' in x or 'E' in x:
                return float(x)
            else:
                return int(x)
        elif type(x) is float:
            return x
        else:
            return int(x)
    except Exception, err:
        return None


def createDate(date=None):
    if isinstance(date, datetime.datetime):
        return date
    elif type(date) in (str, unicode):
        if date.lower() == FUTURE_DATE:
            return FUTURE_DATE
        return sliauth.parse_date(date) if date else ''
    else:
        # Create date from local epoch time (in ms)
        return sliauth.create_date(date)

def getNewDueDate(userId, siteName, sessionName, lateToken):
    comps = splitToken(lateToken)
    dateStr = comps[0]
    tokenStr = comps[1]
    if sliauth.gen_late_token(Settings['auth_key'], userId, siteName, sessionName, dateStr) == lateToken:
        return createDate(dateStr) # Date format: '1995-12-17T03:24Z'
    else:
        return None

def splitToken(token):
    if ':' not in token:
        raise Exception('Invalid HMAC token; no colon')
    prefix, sep, suffix = token.rpartition(':')
    return prefix, suffix


def validateHMAC(token, key):
    # Validates HMAC token of the form message:signature
    message, signature = splitToken(token)
    return sliauth.gen_hmac_token(key, message) == signature


def colIndexToChar(col):
    suffix = (col - 1) % 26
    prefix = (col - 1 - suffix) / 26
    c = chr(ord('A') + suffix)
    if prefix:
        c = chr(ord('A') + prefix - 1) + c
    return c


def indexColumns(sheet):
    columnHeaders = sheet.getSheetValues(1, 1, 1, sheet.getLastColumn())[0]
    columnIndex = {}
    for j, columnHeader in enumerate(columnHeaders):
        columnIndex[columnHeader] = j+1
    return columnIndex


def indexRows(sheet, indexCol, startRow=2):
    rowIndex = {}
    nRows = sheet.getLastRow()-startRow+1
    if nRows > 0:
        rowIds = sheet.getSheetValues(startRow, indexCol, sheet.getLastRow()-startRow+1, 1)
        for j, rowId in enumerate(rowIds):
            rowIndex[rowId[0]] = j+startRow
    return rowIndex


def getColumns(header, sheet, colCount=1, startRow=2):
    colIndex = indexColumns(sheet)
    if header not in colIndex:
        raise Exception('Column '+header+' not found in sheet '+sheetName)

    if colCount and colCount > 1:
        # Multiple columns (list of lists)
        return sheet.getSheetValues(startRow, colIndex[header], sheet.getLastRow()-startRow+1, colCount)
    else:
        # Single column
        if sheet.getLastRow() < startRow:
            vals = []
        else:
            vals = sheet.getSheetValues(startRow, colIndex[header], sheet.getLastRow()-startRow+1, 1)
        retvals = []
        for val in vals:
            retvals.append(val[0])
        return retvals


def getColumnMax(sheet, startRow, colNum):
    values = sheet.getSheetValues(startRow, colNum, sheet.getLastRow()-startRow+1, 1)
    maxVal = 0
    for j in range(len(values)):
        if values[j][0]:
            maxVal = max(maxVal, int(values[j][0]))
    return maxVal


def setColumnMax(sheet, startRow, colNum, maxValue):
    modified = False
    if sheet.getLastRow() < startRow:
        return modified
    vrange = sheet.getRange(startRow, colNum, sheet.getLastRow()-startRow+1, 1)
    values = vrange.getValues()

    for j in range(len(values)):
        if values[j][0] and values[j][0] > maxValue:
            values[j][0] = maxValue
            modified = True

    if modified:
        vrange.setValues(values)

    return modified

def lookupRowIndex(idValue, sheet, startRow=2):
    # Return row number for idValue in sheet or return 0
    # startRow defaults to 2
    nRows = sheet.getLastRow()-startRow+1
    if not nRows:
        return 0
    rowIds = sheet.getSheetValues(startRow, indexColumns(sheet)['id'], nRows, 1)
    for j, rowId in enumerate(rowIds):
        if idValue == rowId[0]:
            return j+startRow
    return 0


def lookupValues(idValue, colNames, sheetName, listReturn=False, blankValues=False):
    # Return parameters in list colNames for idValue from sheet
    # If blankValues, return blanks for columns not found
    indexSheet = getSheet(sheetName)
    if not indexSheet:
        raise Exception('Lookup sheet '+sheetName+' not found')
    indexColIndex = indexColumns(indexSheet)
    indexRowIndex = indexRows(indexSheet, indexColIndex['id'], 2)
    sessionRow = indexRowIndex.get(idValue)
    if not sessionRow:
        raise Exception('ID value '+idValue+' not found in index sheet '+sheetName+': '+str(colNames))
    retVals = {}
    listVals = []
    for colName in colNames:
        colValue = ''
        if colName in indexColIndex:
            colValue = indexSheet.getSheetValues(sessionRow, indexColIndex[colName], 1, 1)[0][0]
        elif not blankValues:
            raise Exception('Column '+colName+' not found in index sheet '+sheetName)
        retVals[colName] = colValue
        listVals.append(retVals[colName])

    return listVals if listReturn else retVals

def setValue(idValue, colName, colValue, sheetName):
    # Set parameter in colName for idValue in sheet
    indexSheet = getSheet(sheetName)
    if not indexSheet:
        raise Exception('Index sheet '+sheetName+' not found')
    indexColIndex = indexColumns(indexSheet)
    indexRowIndex = indexRows(indexSheet, indexColIndex['id'], 2)
    sessionRow = indexRowIndex.get(idValue)
    if not sessionRow:
        raise Exception('ID value '+idValue+' not found in index sheet '+sheetName+': '+colName)
    if colName not in indexColIndex:
        raise Exception('Column '+colName+' not found in index sheet '+sheetName)
    indexSheet.getRange(sessionRow, indexColIndex[colName], 1, 1).setValues([[colValue]])

def locateNewRow(newName, newId, nameValues, idValues):
    # Return row number before which new name/id combination should be inserted
    for j in range(len(nameValues)):
        if nameValues[j][0] > newName or (nameValues[j][0] == newName and idValues[j][0] > newId):
            # Sort by name and then by id (blank names will be first)
            return j+1
    return len(nameValues)+1

def numericKeys(dct):
    # copy dict, replacing numeric string keys with numbers
    return dict( (parseNumber(k), v) if isNumber(k) else (k,v) for k, v in dct.items() )

def numericKeysJSON(jsonStr):
    # parse JSON object, replacing numeric string keys with numbers
    return numericKeys(json.loads(jsonStr))

def blankColumn(sheet, colName, startRow=None):
    startRow = startRow or 2
    lastRow = sheet.getLastRow()
    blankCol = indexColumns(sheet).get(colName, 0)
    if not blankCol or lastRow < startRow:
        return
    blankRange = sheet.getRange(startRow, blankCol, lastRow-startRow+1, 1)
    blankVals = blankRange.getValues()
    for j in range(len(blankVals)):
        blankVals[j][0] = ''
    blankRange.setValues(blankVals)

def getUserTeam(sessionName, userId, discussNum=0):
    teamSettings = getTeamSettings(sessionName, discussNum=discussNum)
    for teamName in teamSettings.get('members',{}).keys():
        memberIds = teamSettings['members'][teamName]
        if userId in memberIds:
            return teamName
    return ''
    
def getDiscussStats(userId, sessionName=''):
    # Returns discussion stats { sessionName1: {discussNum1: {closed: 0/1, teams{team1: [nPosts, unreadPosts], ...}, discussNum2:...}, sessionName2: ...}
    sessionStats = {}
    flagStats = {}
    blocked = []
    stats = {'sessions': sessionStats, 'flags': flagStats, 'blocked': blocked}

    axsSheet = getSheet(DISCUSS_SHEET)
    if not axsSheet:
        return stats
    topRow = lookupRowIndex(DISCUSS_ID, axsSheet)
    if not topRow:
        raise Exception('Row with id '+DISCUSS_ID+' not found in sheet '+DISCUSS_SHEET)
    userRow = lookupRowIndex(userId, axsSheet)

    adminUser = (userId == TESTUSER_ID)

    ncols = axsSheet.getLastColumn()
    headers = axsSheet.getSheetValues(1, 1, 1, ncols)[0]
    topVals = axsSheet.getSheetValues(topRow, 1, 1, ncols)[0]
    userVals = axsSheet.getSheetValues(userRow, 1, 1, ncols)[0]  if userRow  else None
    for j in range(0,ncols):
        if headers[j].startswith('_'):
            temSessionName = headers[j][1:]
            if sessionName and sessionName != temSessionName:
                continue
            if not topVals[j]:  # Blanked out column
                continue
            discussStats = {}
            try:
                discussState = json.loads(topVals[j])
                lastPostsAll = discussState['lastPost']
                lastReadPostsAll = json.loads(userVals[j] or '{}')  if userVals  else {}
                discussNums = lastPostsAll.keys()
                for idisc in range(0,len(discussNums)):
                    discussNumStr = discussNums[idisc]
                    lastPosts = lastPostsAll.get(discussNumStr, {})
                    lastReadPosts = lastReadPostsAll.get(discussNumStr, {})

                    if adminUser:
                        # Display posts for all teams
                        postTeams = []
                        # Return stats on blocked users and flagged posts
                        for posterId, postLabels in discussState['flagged'].items():
                            if len(postLabels) >= 2:
                                blocked.append(posterId)
                            for postLabel in postLabels:
                                discussNumStr, teamName, postNumberStr = postLabel.split(':')
                                discussNum = int(discussNumStr)
                                if temSessionName not in flagStats:
                                    flagStats[temSessionName] = {}
                                if discussNumStr not in flagStats[temSessionName]: 
                                    flagStats[temSessionName][discussNumStr] = []
                                flagStats[temSessionName][discussNumStr].append(teamName+':'+postNumberStr)
                    else:
                        # Display only posts for user or user's team
                        postTeams = ['']
                        userTeam = getUserTeam(temSessionName, userId, discussNum=int(discussNumStr))
                        if userTeam:
                            postTeams.append(userTeam)

                    teamNames = postTeams if postTeams else lastPosts.keys()
                    if len(teamNames):
                        teamReadPosts = {}
                        discussStats[discussNumStr] = {'teams': teamReadPosts, 'closed': (discussState['closed'].get(discussNumStr,0)) }
                        for iteam in range(0,len(teamNames)):
                            postTeam = teamNames[iteam];
                            lastPost = lastPosts.get(postTeam, 0)
                            lastReadPost = lastReadPosts.get(postTeam, 0)
                            teamReadPosts[postTeam] = [lastPost, lastPost-lastReadPost]
            except Exception:
                if Settings['debug']:
                    import traceback
                    traceback.print_exc()
            sessionStats[temSessionName] = discussStats
    return stats

def getDiscussionSeed(sessionName, questionNum, discussNum):
    startRow = 3
    discussSheet = getSheet(sessionName+'_discuss')
    if not discussSheet:
        raise Exception('Discussion sheet not foud for session '+sessionName)
    discussColIndex = indexColumns(discussSheet)
    discussCol =  discussColIndex[DISCUSS_COL_FMT % discussNum]
    if not discussCol:
        raise Exception('Discussion %s not found for session ' % (discussNum, sessionName))
    nRows = discussSheet.getLastRow()-startRow+1
    postEntries = discussSheet.getSheetValues(startRow, discussCol, nRows, 1)
    idValues = discussSheet.getSheetValues(startRow, discussColIndex['id'], nRows, 1)
    nameValues = discussSheet.getSheetValues(startRow, discussColIndex['name'], nRows, 1)
    nameMap = getDisplayNames(includeNonRoster=True)
    shortMap = makeShortNames(nameMap, first=True) if nameMap else {}
    subrows = []
    responders = []
    for j in range(nRows):
        idValue = idValues[j][0]
        postEntry = postEntries[j][0]
        userPosts = splitPosts(postEntry)
        for k in range(len(userPosts)):
            postComps = parsePost(userPosts[k])
            if postComps and postComps['state'].get(ANSWER_POST):
                # Extract response and explanation
                subrows.append([idValue, postComps['answer'], postComps['text']])
                responders.append(idValue+'/'+shortMap.get(idValue,idValue)+'/'+nameMap.get(idValue,idValue))
    subrows.sort(key=lambda x: parseNumber(x[1]) if isNumber(x[1]) else x[1])
    qprefix = 'q'+str(questionNum)+'_'
    return {'id': [x[0] for x in subrows], qprefix+'response': [x[1] for x in subrows], qprefix+'explain': [x[2] for x in subrows], 'responders': responders}

def getDiscussState(sessionName, optional=False):
    if sessionName == previewingSession():
        raise Exception('Cannot access discussions when previewing session %s' % sessionName)

    axsSession = '_'+sessionName

    axsSheet = getSheet(DISCUSS_SHEET)
    if not axsSheet:
        return None

    axsColumn = indexColumns(axsSheet).get(axsSession)
    if not axsColumn:
        if optional:
            return None
        raise Exception('Column '+axsSession+' not found in sheet '+DISCUSS_SHEET)

    axsTopRow = lookupRowIndex(DISCUSS_ID, axsSheet)
    if not axsTopRow:
        if optional:
            return None
        raise Exception('Row with id '+DISCUSS_ID+' not found in sheet '+DISCUSS_SHEET)

    discussStateEntry = axsSheet.getRange(axsTopRow, axsColumn, 1, 1).getValues()[0][0]
    if not discussStateEntry.strip():
        if optional:
            return None
        raise Exception('Row with id '+DISCUSS_ID+' empty for session '+axsSession+' in sheet '+DISCUSS_SHEET)

    return json.loads(discussStateEntry)

def setDiscussState(sessionName, discussState):
    if sessionName == previewingSession():
        raise Exception('Cannot access discussions when previewing session %s' % sessionName)

    axsSession = '_'+sessionName

    axsSheet = getSheet(DISCUSS_SHEET)
    if not axsSheet:
        return None

    axsColumn = indexColumns(axsSheet).get(axsSession)
    if not axsColumn:
        raise Exception('Column '+axsSession+' not found in sheet '+DISCUSS_SHEET)

    axsTopRow = lookupRowIndex(DISCUSS_ID, axsSheet)
    if not axsTopRow:
        raise Exception('Row with id '+DISCUSS_ID+' not found in sheet '+DISCUSS_SHEET)
    axsSheet.getRange(axsTopRow, axsColumn, 1, 1).setValue(json.dumps(discussState))

def postDiscussEntry(sessionName, discussNum, postTeam, userId, userName, prevText, newText, answer=''):
    discussNumStr = str(discussNum)
    discussState = getDiscussState(sessionName)
    closed = discussState['closed'].get(discussNumStr,0)
    if closed:
        raise Exception('Discussion '+discussNumStr+' in session '+sessionName+' is closed for new postings')

    if userId:
        rosterStatus = lookupRoster(STATUS_HEADER, userId=userId)
        if rosterStatus:
            raise Exception('User %s with %s status not allowed to post' % (userId, rosterStatus))
        if len(discussState['flagged'].get(userId, {}).keys()) >= 2:
            raise Exception('You have at least two flagged posts; please contact moderator to clear them to continue posting')
        # Update post count for user
        userDiscussRange(sessionName, discussNum, userId, userName, increment='postCount')

    # New post for session/discussion
    lastPost = discussState['lastPost'].get(discussNumStr,{})
    if not lastPost.get(postTeam):
        lastPost[postTeam] = 1
    else:
        lastPost[postTeam] += 1
    discussState['lastPost'][discussNumStr] = lastPost
    setDiscussState(sessionName, discussState)

    postCount = lastPost[postTeam]

    newPost = makePost(postTeam, postCount, newText, answer=answer)
    return appendPosts(prevText, newPost, postCount), newPost

def closeDiscussion(sessionName, discussNum=0, reopen=False):
    if sessionName == previewingSession():
        return
    discussState = getDiscussState(sessionName, optional=True)
    if reopen and not discussState:
        updateSessionDiscussSheet(sessionName)
        discussState = getDiscussState(sessionName)
    if not discussState:
        return

    dNums = [discussNum] if discussNum else discussState['closed'].keys()
    for dNum in dNums:
        discussNumStr = str(dNum)
        closed = discussState['closed'].get(discussNumStr,0)
        if not closed and not reopen:
            discussState['closed'][discussNumStr] = 1
            setDiscussState(sessionName, discussState)
            notifyDiscussUsers(sessionName, discussNum, '', 'close', '', '', '')
        elif closed and reopen:
            discussState['closed'][discussNumStr] = 0
            setDiscussState(sessionName, discussState)
            notifyDiscussUsers(sessionName, discussNum, '', 'open', '', '', '')

def flagPost(sessionName, discussNum, postTeam, postNumber, posterId, flaggerId, unflag=False):
    discussState = getDiscussState(sessionName)
    flagged = discussState['flagged']
    teamSettings = getTeamSettings(sessionName, discussNum=discussNum)
    teamAliases = teamSettings.get('aliases') or {}
    posterId = unaliasDiscussUser(posterId, sessionName, teamSettings)

    flagLabel = postLabel(discussNum, postTeam, postNumber)

    if unflag:
        if posterId in flagged and flagLabel in flagged[posterId]:
            del flagged[posterId][flagLabel]
            if not flagged[posterId].keys():
                del flagged[posterId]
    else:
        if posterId not in flagged:
            flagged[posterId] = {}
        elif flaggerId in flagged[posterId].values():
            raise Exception('You have already flagged a post by this user')

        if flagLabel in flagged[posterId]:
            raise Exception('Post already flagged')
        flagged[posterId][flagLabel] = flaggerId
        discussState['flagCount'][posterId] = discussState['flagCount'].get(posterId,0) + 1

        notifyMsg = 'Post by user '+posterId+' flagged by user '+flaggerId+' in session '+sessionName+', Discussion '+str(discussNum);
        if postTeam:
            notifyMsg += ' team '+postTeam
        notify_admin(notifyMsg, msgType='flagged')
    setDiscussState(sessionName, discussState)

def deletePost(prevValue, colValue, userId, userName, adminUser, sessionName, discussNum):
    # Delete post
    newValue = prevValue
    userPosts = splitPosts(prevValue)
    dcomps = colValue.split(':')
    if len(dcomps) != 3 or not dcomps[2].isdigit():
        raise Exception('Invalid delete post entry %s' % dcomps)
    teamName = dcomps[1]
    postNumber = int(dcomps[2])

    flagLabel = postLabel(discussNum, teamName, postNumber)
    discussState = getDiscussState(sessionName)
    flagged = discussState['flagged']
    if userId in flagged and flagLabel in flagged[userId]:
        if adminUser:
            # Unflag post before deleting
            flagPost(sessionName, discussNum, teamName, postNumber, userId, TESTUSER_ID, unflag=True)
        else:
            raise Exception('Cannot delete flagged post in session '+sessionName)

    for j in range(len(userPosts)):
        postComps = parsePost(userPosts[j])
        if postComps['team'] == teamName and postComps['number'] == postNumber:
            # Delete post
            userPosts[j] = makePost(postComps['team'], postComps['number'], postComps['text'], date=postComps['date'], state=postComps['state'], delete=True, noprefix=True)
            newValue = joinPosts(userPosts)
            userDiscussRange(sessionName, discussNum, userId, userName, increment='deleteCount')
            break
    return newValue

def userDiscussRange(sessionName, discussNum, userId, userName, increment=''):
    # Return user discuss range containing JSON lastRead, postCount, deleteCount, creating it if needed
    discussNumStr = str(discussNum)
    axsSheet = getSheet(DISCUSS_SHEET)
    if not axsSheet:
        raise Exception('Sheet '+DISCUSS_SHEET+' not found')

    axsSession = '_'+sessionName
    axsRowOffset = 2
    axsNameCol = 1
    axsIdCol = 2

    axsColumn = indexColumns(axsSheet).get(axsSession)
    if not axsColumn:
        raise Exception('Column '+axsSession+' not found in sheet '+DISCUSS_SHEET)

    axsRow = lookupRowIndex(userId, axsSheet)
    if not axsRow:
        # Add discuss access row for user
        axsRows = axsSheet.getLastRow()
        if axsRows > axsRowOffset:
            axsNames = axsSheet.getSheetValues(1+axsRowOffset, axsNameCol, axsRows-axsRowOffset, 1)
            axsIds = axsSheet.getSheetValues(1+axsRowOffset, axsIdCol, axsRows-axsRowOffset, 1)
            temRow = axsRowOffset + locateNewRow(userName or '#'+userId, userId, axsNames, axsIds)
        else:
            temRow = axsRowOffset + 1
        axsSheet.insertRowBefore(temRow, keyValue=userId)
        axsSheet.getRange(temRow, axsNameCol, 1, 1).setValue(userName or '#'+userId)
        axsRow = lookupRowIndex(userId, axsSheet)
    axsRange = axsSheet.getRange(axsRow, axsColumn, 1, 1)
    userEntry = axsRange.getValue()
    if not userEntry:
        userEntry = '{"lastRead": {}, "postCount": {}, "deleteCount": {}}'
        axsRange.setValue(userEntry)
    if increment:
        userDiscuss = json.loads(userEntry)
        userDiscuss[increment][discussNumStr] = userDiscuss[increment].get(discussNumStr,0) + 1
        axsRange.setValue(json.dumps(userDiscuss))
    return axsRange

def accessDiscussion(sessionName, discussNum, userId, userName, postTeam='', noread=False):
    # Returns lastReadPost number 
    # If noread, do not update read state

    discussNumStr = str(discussNum)
    axsSession = '_'+sessionName
    axsRowOffset = 2
    axsNameCol = 1
    axsIdCol = 2

    try:
        # Record last read post for user for this session/slide
        axsSheet = getSheet(DISCUSS_SHEET)
        if not axsSheet:
            raise Exception('Sheet '+DISCUSS_SHEET+' not found')

        axsColumn = indexColumns(axsSheet).get(axsSession)
        if not axsColumn:
            raise Exception('Column '+axsSession+' not found in sheet '+DISCUSS_SHEET)

        discussState = getDiscussState(sessionName)
        lastPost = discussState['lastPost'].get(discussNumStr,{})
        teamLastPost = lastPost.get(postTeam, 0)

        axsRange = userDiscussRange(sessionName, discussNum, userId, userName)
        userDiscussEntry = axsRange.getValue()
        if not userDiscussEntry:
            raise Exception('Internal error: No discuss entry found for user '+userId+' in discussion '+str(discussNum)+' for session '+sessionName)
        userDiscuss = json.loads(userDiscussEntry)
        lastReadPostsAll = userDiscuss['lastRead']
        lastReadPosts = lastReadPostsAll.get(discussNumStr, {})
        teamLastReadPost = lastReadPosts.get(postTeam, 0)
        if not noread and teamLastReadPost < teamLastPost:
            lastReadPosts[postTeam] = teamLastPost
            lastReadPostsAll[discussNumStr] = lastReadPosts;
            axsRange.setValue(json.dumps(userDiscuss))
        return teamLastReadPost
    except Exception, excp:
        if Settings['debug']:
            import traceback
            traceback.print_exc()
        raise Exception('Error in discussion access for session '+sessionName+', discussion '+discussNumStr+': '+str(excp))

def postLabel(discussNum, teamName, postNumber):
    return ':'.join([str(discussNum), teamName, str(postNumber)])

def splitPosts(posts):
    return ('\n\n\n'+posts.strip()).split('\n\n\nPost:')[1:]

def joinPosts(posts):
    return 'Post:' + '\n\n\nPost:'.join(posts)

def makePost(postTeam, postNumber, postText, date=None, state={}, answer='', delete=False, noprefix=False):
    postDate = date or sliauth.iso_date(createDate(), nosubsec=True)
    postText = postText.strip()
    postState = state.copy()
    prefix = '' if noprefix else 'Post:'
    
    if answer.strip():
        postText = answer.strip() + ': ' + postText
        postState[ANSWER_POST] = 1

    if delete:
        postState[DELETED_POST] = 1

    while '\n\n\n' in postText:
        postText = postText.replace('\n\n\n', '\n\n')

    return POST_MAKE_FMT % (prefix, postTeam, postNumber, ','.join(sorted(postState.keys())), postDate, postText)

def parsePost(post):
    pmatch = POST_NUM_RE.match(post)
    if not pmatch:
        return None
    state = dict((key, 1) for key in pmatch.group(3).split(',') if key)
    text = pmatch.group(5).strip()
    comps = {'team': pmatch.group(1), 'number': int(pmatch.group(2)), 'state': state, 'date': pmatch.group(4)}

    if state.get(ANSWER_POST):
        answer, _, text = text.partition(':')
        comps['answer'] = answer.strip()

    comps['text'] = text.strip()
    return comps
    
def appendPosts(prevPosts, newPost, postCount):
    prevPosts = prevPosts.strip()
    retValue = prevPosts + '\n\n\n'  if prevPosts  else ''
    retValue += sliauth.str_encode(newPost)
    if not retValue.endswith('\n'):
        retValue += '\n'
    return retValue

DISCUSS_COL_FMT = 'discuss%03d'
TEAM_NAME_RE = re.compile(r'^([^\d])*(\d+)$')
def teamSortKey(name):
    tmatch = TEAM_NAME_RE.match(name)
    return '%s%04d' % (tmatch.group(1), int(tmatch.group(2))) if tmatch else name

def getDiscussPosts(sessionName, discussNum, userId, name, postTeams=[], noread=False):
    # Return sorted list of discussion posts [ closedFlag, teamNames, [ [userTeam, postNum, userId, userName, postTime, unreadFlag, postText] ] ]
    # If noread, do not update read stats
    discussNumStr = str(discussNum)
    sessionEntries = lookupValues(sessionName, ['adminPaced', 'attributes'], INDEX_SHEET)
    adminPaced = sessionEntries.get('adminPaced')
    sessionAttributes = json.loads(sessionEntries['attributes'])

    if not getSheet(sessionName+'_discuss'):
        return [adminPaced, [''], []]

    teamSettings = getTeamSettings(sessionName, discussNum=discussNum)

    if teamSettings:
        teamNames = teamSettings.get('members',{}).keys()
        teamNames.sort(key=teamSortKey)
    else:
        teamNames = ['']

    discussState = getDiscussState(sessionName)
    closedFlag = discussState['closed'].get(discussNumStr,0)

    if userId == TESTUSER_ID:
        # Retrieve posts for all teams, if no team specified
        postTeams = postTeams or teamNames
    else :
        userTeam = getUserTeam(sessionName, userId, discussNum=discussNum)
        if not postTeams:
            postTeams = [ userTeam ]
        elif postTeams != [ userTeam ]:
            raise Exception('User '+userId+' not allowed to access discussion '+discussNumStr+' for team '+userTeam)
    
    sheetName = sessionName+'_discuss'
    discussSheet = getSheet(sheetName)
    if not discussSheet:
        return [closedFlag, postTeams, []]

    colIndex = indexColumns(discussSheet)
    axsColName = DISCUSS_COL_FMT % discussNum
    if not colIndex.get(axsColName):
        return [closedFlag, postTeams, []]

    lastReadPosts = {}
    # Last read post
    for postTeam in postTeams:
        lastReadPosts[postTeam] = accessDiscussion(sessionName, discussNum, userId, name or '#'+userId, postTeam, noread=noread)

    idVals = getColumns('id', discussSheet)
    nameVals = getColumns('name', discussSheet)
    colVals = getColumns(axsColName, discussSheet)
    allPosts = []
    for j in range(0,len(colVals)):
        idValue = idVals[j]
        nameValue = nameVals[j]
        if not idValue or (idValue.startswith('_') and idValue != TESTUSER_ID):
            continue
        flaggedIdPosts = discussState['flagged'].get(idValue,{})
        modIdValue, modNameValue = aliasDiscussUser(idValue, nameValue, sessionName, teamSettings, selfId=userId)
        userPosts = splitPosts(colVals[j])
        for k in range(len(userPosts)):
            postComps = parsePost(userPosts[k])
            if postComps and postComps['team'] in postTeams:
                teamName = postComps['team']
                postNumber = postComps['number']
                postState = postComps['state']
                flagLabel = postLabel(discussNum, teamName, postNumber)
                flaggerId = flaggedIdPosts.get(flagLabel)
                if flaggerId:
                    if userId != idValue and userId != flaggerId and userId != TESTUSER_ID:
                        # Only display flagged posts to poster/flagger/admin
                        continue
                unreadFlag = postNumber > lastReadPosts[teamName] if not noread else False
                text = postComps['text']+'\n'
                if postState.get(DELETED_POST):
                    # Hide text from deleted messages
                    text = '('+DELETED_POST+')'
                elif flaggerId:
                    # Flagged stats is temporary
                    postState[FLAGGED_POST] = 1
                    if userId == idValue or userId == TESTUSER_ID:
                        # Display flagged text to poster and admin
                        text = '('+FLAGGED_POST+') ' + text
                    else:
                        text = '('+FLAGGED_POST+')'
                elif postState.get(ANSWER_POST):
                    # Prefix answer post
                    text = '('+ANSWER_POST+') ' + postComps['answer'] + ': ' + text
                allPosts.append([teamName, postNumber, postState, modIdValue, modNameValue, postComps['date'], unreadFlag, text])

    allPosts.sort(key=lambda x: (teamSortKey(x[0]), x[1]))  #  (sorting by team name and then by post number)
    return [closedFlag, postTeams, allPosts]

def addDiscussUser(sessionName, userId, userName=''):
    discussSheet = getSheet(sessionName+'_discuss')

    if userId.startswith('_') and userId != TESTUSER_ID:
        return
    if lookupRowIndex(userId, discussSheet):
        return

    discussRowOffset = 2
    discussNameCol = 1
    discussIdCol = 2

    # Add user row to discussion sheet
    temName = userName or '#'+userId
    discussRows = discussSheet.getLastRow()
    if discussRows == discussRowOffset:
        temRow = discussRowOffset + 1
    else:
        discussNames = discussSheet.getSheetValues(1+discussRowOffset, discussNameCol, discussRows-discussRowOffset, 1)
        discussIds = discussSheet.getSheetValues(1+discussRowOffset, discussIdCol, discussRows-discussRowOffset, 1)
        temRow = discussRowOffset + locateNewRow(temName, userId, discussNames, discussIds)
    discussSheet.insertRowBefore(temRow, keyValue=userId)
    discussSheet.getRange(temRow, discussNameCol, 1, 1).setValues([[temName]])

def getTeamStatus(sessionName):
    sessionEntries = lookupValues(sessionName, ['attributes'], INDEX_SHEET)
    sessionAttributes = json.loads(sessionEntries['attributes'])
    discussSlides = sessionAttributes['discussSlides']
    teamIndices = []
    if discussSlides:
        for discussNum in range(1+len(discussSlides)):
            if getTeamSettings(sessionName, discussNum=discussNum, optional=True):
                teamIndices.append(discussNum)
    return teamIndices

def getTeamSettings(sessionName, discussNum=0, optional=False):
    if discussNum:
        if optional and not getSheet(sessionName+'_discuss'):
            return None
        colValue = lookupValues(DISCUSS_ID, [DISCUSS_COL_FMT % discussNum], sessionName+'_discuss', listReturn=True, blankValues=True)[0]
        if colValue != 'SESSIONTEAM':
            return json.loads(colValue or '{}')
    return json.loads(lookupValues(sessionName, ['teams'], INDEX_SHEET, listReturn=True)[0] or '{}')

def setTeamSettings(sessionName, members, aliases, responses=None, discussNum=0):
    teamSettings = {'members': members, 'aliases': aliases}
    if responses:
        teamSettings['responses'] = responses
    if discussNum:
        if not getSheet(sessionName+'_discuss'):
            updateSessionDiscussSheet(sessionName)
        setValue(DISCUSS_ID, DISCUSS_COL_FMT % discussNum, json.dumps(teamSettings, default=sliauth.json_default), sessionName+'_discuss')
    else:
        setValue(sessionName, 'teams', json.dumps(teamSettings, default=sliauth.json_default), INDEX_SHEET)

def aliasDiscussUser(userId, userName, sessionName, teamSettings, selfId=''):
    teamAliases = teamSettings.get('aliases')
    if teamAliases and teamAliases.get(userId):
        # Replace name with aliased ID
        userName = teamAliases[userId]
        if selfId and userId == selfId:
            userName = 'self-' + userName
        elif selfId != TESTUSER_ID:
            # Replace id with aliased ID (for normal users)
            userId = userName

    return userId, userName

def unaliasDiscussUser(posterId, sessionName, teamSettings):
    teamAliases = teamSettings.get('aliases') or {}
    for key, value in teamAliases.items():
        if value == posterId:
            return key
    return posterId

def notifyDiscussUsers(sessionName, discussNum, teamName, postMsg, userId, userName, newPost):
    if not Global.discussPostCallback:
        return
    closed = 0
    try:
        teamSettings = getTeamSettings(sessionName, discussNum=discussNum, optional=True)
        if teamSettings and teamName:
            teamIds = ','.join(teamSettings['members'][teamName])
        else:
            teamIds = ''

        if teamSettings and userId:
            userId, userName = aliasDiscussUser(userId, userName, sessionName, teamSettings)

        discussState = getDiscussState(sessionName)
        closed = discussState['closed'].get(str(discussNum),0)

        Global.discussPostCallback(sessionName, discussNum, closed, teamIds, teamName, postMsg, userId, userName, newPost)
    except Exception, excp:
        if Settings['debug']:
            import traceback
            traceback.print_exc()
        print('sdproxy: notifyDiscussUsers ERROR %s-%s, %s %s %s %s: %s' % (sessionName, discussNum, closed, teamName, postMsg, userId, excp), file=sys.stderr)

def createTeam(sessionName, fromSession, fromQuestion, alias='', count=None, min_size=3, composition='', teamNames=[]):
    if fromSession.startswith('_'):
        if fromSession == '_roster':
            # Assigned teams from roster
            userTeams = lookupRoster('team', regular=True)
            userNames = lookupRoster('name')
        else:
            # Assigned teams from response in current session
            userTeams = getRowMap(sessionName, 'q'+str(fromQuestion)+'_response', regular=True)
            userNames = getRowMap(sessionName, 'name', regular=True)

        members = {}
        for temId in userTeams.keys():
            teamName = userTeams[temId]
            if teamName in members:
                members[teamName].append(temId)
            elif teamName:
                members[teamName] = [temId]
        aliases = None
        explanations = None
        ranks = None

    elif fromSession and not fromQuestion:
        # Copy teams from previous session
        teamSettings = getTeamSettings(fromSession)
        members = teamSettings.get('members')
        aliases = teamSettings.get('aliases') if alias else None
        if not members:
            raise Exception('Unable to generate team for session '+sessionName+' from session '+fromSession)
        explanations = None
        ranks = None

    else:
        # Ranked/randomized teams from response in previous or current session
        fromSession = fromSession or sessionName
        userNames = getRowMap(fromSession, 'name', regular=True)
        sources = getRowMap(fromSession, 'source', regular=True)
        responses = getRowMap(fromSession, 'q'+str(fromQuestion)+'_response', regular=True)
        explanations = getRowMap(fromSession, 'q'+str(fromQuestion)+'_explain', regular=True, optional=True) or {}

        statusMap = lookupRoster(STATUS_HEADER) or {}
        user_ranks = []
        for user in responses.keys():
            if sources[user] == 'interact':
                # Skip non-browser responses
                continue
            respVal = responses[user]
            if not isinstance(respVal, (str, unicode)):
                respVal = str(respVal)
            if respVal and user in statusMap and not statusMap[user]:
                # Include only non-blocked and non-dropped users in roster
                user_ranks.append([user, respVal])

        # Generate team names
        props = sliauth.team_props(user_ranks, count=count, min_size=min_size, composition=composition, alias=alias, team_names=teamNames, random_seed=fromSession)

        members = props['members']
        aliases = props['aliases'] if alias else None
        ranks = props['ranks']

    return members, aliases, ranks, explanations

DOCS_LINK_POST_FMT = '''A shared Google Doc has been created for this team. [Click here](%s) to access it. You may use this document, which any team member can edit, to work on collaboratively on your project. Some helpful links:

- [Collaborating using Google Docs](https://mashable.com/2016/03/18/collaborate-google-docs/#ynJ3Qt7KL5q5)
- [Chat with others while editing Google Docs](https://support.google.com/docs/answer/2494891?co=GENIE.Platform%%3DDesktop&hl=en)
'''

def createSharedDoc(sessionName, discussNum, teamName, memberIds, loginDomain='', content=''):
    params = {'action': 'file_create'}
    _, _, serverDomain = Settings['server_url'].rpartition('//')
    params['path'] = sliauth.shared_doc_path(serverDomain, sessionName, discussNum, teamName, siteName=Settings['site_name'])
    params['editors'] = ','.join(memberId if '@' in memberId else memberId+loginDomain for memberId in memberIds)
    if content:
        params['content'] = content
    retval = sliauth.http_post(Settings['gapps_url'], params)
    gdoc_id = ''
    if retval and retval.get('result') == 'success':
        gdoc_id = retval.get('value')
        gdoc_link = sliauth.GDOC_LINK_FMT % gdoc_id
        postText = DOCS_LINK_POST_FMT % gdoc_link
    else:
        errMsg = retval.get('error','') if retval else ''
        postText = 'Error in creating shared Google Doc for team: '+errMsg
        print('sdproxy.createSharedDoc: Error in creating shared doc for team %s in session %s, discussion %s: %s' % (teamName, sessionName, discussNum, errMsg), file=sys.stderr)

    sheetName = sessionName+'_discuss'
    colName = DISCUSS_COL_FMT % discussNum
    addDiscussUser(sessionName, TESTUSER_ID, '')
    prevValue = lookupValues(TESTUSER_ID, [colName], sheetName, listReturn=True)[0]
    newValue, newPost = postDiscussEntry(sessionName, discussNum, teamName, TESTUSER_ID, '', prevValue, postText)
    setValue(TESTUSER_ID, colName, newValue, sheetName)
    return gdoc_id

def seedDiscussion(seedType, sharedDoc, sessionName, discussNum, members, aliases, ranks, explanations, userNames):
    # Ranked session seedType='answer'/'explanation'/'name'
    # sharedDoc = None or content string
    print('sdproxy: seedDiscussion', seedType, sharedDoc, sessionName, discussNum, file=sys.stderr)
    teamNameList = members.keys()
    teamNameList.sort()
    updateSessionDiscussSheet(sessionName)
    discussState = getDiscussState(sessionName)
    if not discussState:
        raise Exception('Discussion not setup for session '+sessionName)

    closeDiscussion(sessionName, discussNum, reopen=True)

    loginDomain = ''
    if Settings['auth_type'] and ',' in Settings['auth_type']:
        comps = Settings['auth_type'].split(',')
        if comps[0] and comps[0][0] == '@':
            loginDomain = comps[0]
    
    colName = DISCUSS_COL_FMT % discussNum
    discuss_gdocs = {}
    if seedType == 'name':
        for teamName, memberList in members.items():
            if sharedDoc is not None:
                discuss_gdocs[teamName] = createSharedDoc(sessionName, discussNum, teamName, memberList, loginDomain=loginDomain, content=sharedDoc)

            for teamUserId in memberList:
                postText = teamUserId + loginDomain
                if userNames.get(teamUserId):
                    postText += ' (' + userNames.get(teamUserId) + ')'
                colValue, newPost = postDiscussEntry(sessionName, discussNum, teamName, '', '', '', postText)
                addDiscussUser(sessionName, teamUserId, userNames[teamUserId])
                setValue(teamUserId, colName, colValue, sessionName+'_discuss')
    elif ranks:
        for iteam in range(len(teamNameList)):
            teamName = teamNameList[iteam]
            teamRanks = ranks[teamName]
            if sharedDoc is not None:
                discuss_gdocs[teamName] = createSharedDoc(sessionName, discussNum, teamName, [x[0] for x in teamRanks], loginDomain=loginDomain, content=sharedDoc)

            for imem in range(len(teamRanks)):
                teamUserId, rankValue = teamRanks[imem]
                if not rankValue:
                    continue
                try:
                    postText = ''
                    answerText = ''
                    postText = sliauth.str_encode(explanations.get(teamUserId,'')).strip()
                    if seedType == 'answer':
                        answerText = str(rankValue)
                    if postText or answerText:
                        colValue, newPost = postDiscussEntry(sessionName, discussNum, teamName, '', '', '', postText, answer=answerText)
                        addDiscussUser(sessionName, teamUserId, userNames[teamUserId])
                        setValue(teamUserId, colName, colValue, sessionName+'_discuss')
                except Exception, excp:
                    print('sdproxy.seedDiscuss: Error in team seed post for user %s in session %s, discussion %s: %s' % (teamUserId, sessionName, discussNum, excp), file=sys.stderr)

    if discuss_gdocs:
        gdoc_ids = discussState.get('gdoc_ids', {})
        gdoc_ids[str(discussNum)] = discuss_gdocs
        discussState['gdoc_ids'] = gdoc_ids
        setDiscussState(sessionName, discussState)

def finalizeSessionTeam(sessionName, members, aliases, ranks, explanations, delayed=False):

    sessionEntries = lookupValues(sessionName, ['attributes'], INDEX_SHEET)
    sessionAttributes = json.loads(sessionEntries['attributes'])
    discussSlides = sessionAttributes['discussSlides']

    setTeamSettings(sessionName, members, aliases)

    if  delayed:
        # Delayed setup; initialize team column (done separately for session=_roster/_setup/sessionname)
        for teamName, teamUserIds in members.items():
            for teamUserId in teamUserIds:
                setValue(teamUserId, 'team', teamName, sessionName)

            # Notify team membership
            Global.teamSetupCallback(sessionName, ','.join(teamUserIds), teamName)

    if discussSlides and len(discussSlides):
        for idisc in range(len(discussSlides)):
            discussNum = idisc+1
            if discussSlides[idisc].get('team') and not getTeamSettings(sessionName, discussNum=discussNum, optional=True):
                updateSessionDiscussSheet(sessionName)
                setValue(DISCUSS_ID, DISCUSS_COL_FMT % discussNum, 'SESSIONTEAM', sessionName+'_discuss')
                seedType = discussSlides[idisc].get('seed')
                sharedDoc = discussSlides[idisc]['gdoc'] if 'gdoc' in discussSlides[idisc] else None
                if sharedDoc is not None:
                    # Substitute escaped newlines in content
                    sharedDoc = sharedDoc.replace(r'\n', '\n')
                userNames = lookupRoster('name') or getRowMap(sessionName, 'name', regular=True)
                if seedType and (ranks or seedType == 'name'):
                    seedDiscussion(seedType, sharedDoc, sessionName, discussNum, members, aliases, ranks, explanations, userNames)
            notifyDiscussUsers(sessionName, discussNum, '', 'setup', '', '', '')

def generateTeam(sessionName, questionNum, params):
    # params = {discussNum:, alias:, count:, minSize:, composition:, sessionTeam:, seedDiscuss:, sharedDoc:}
    if sessionName == previewingSession():
        # No team creation during preview
        return

    print('sdproxy.generateTeam:', sessionName, questionNum, params, file=sys.stderr)

    discussNum = params.get('discussNum')

    if discussNum and getTeamSettings(sessionName, discussNum=discussNum, optional=True):
        raise Exception('Discuss team already set up for session %s; reset session to re-create team from discussion %s' % (sessionName, discussNum))

    members, aliases, ranks, explanations = createTeam(sessionName, sessionName, questionNum, alias=params.get('alias',''), count=params.get('count'), min_size=params.get('minSize'), composition=params.get('composition'))

    if not discussNum or params.get('sessionTeam'):
        if getTeamSettings(sessionName):
            raise Exception('Session team already set up for session %s; reset session to re-create session team from question %s' % (sessionName, questionNum))
        finalizeSessionTeam(sessionName, members, aliases, ranks, explanations, delayed=True)

    elif not getTeamSettings(sessionName, discussNum=discussNum, optional=True):
        setTeamSettings(sessionName, members, aliases, discussNum=discussNum)

        seedType = params.get('seedDiscuss')
        sharedDoc = params['sharedDoc'] if 'sharedDoc' in params else None
        if seedType:
            userNames = getRowMap(sessionName, 'name', regular=True)
            seedDiscussion(seedType, sharedDoc, sessionName, discussNum, members, aliases, ranks, explanations, userNames)
        notifyDiscussUsers(sessionName, discussNum, '', 'teamgen', '', '', '')


def setupSessionTeam(sessionName):
    # Return error message or null string
    if sessionName == previewingSession():
        # No team creation during preview
        return ''

    print('sdproxy.setupSessionTeam:', sessionName, file=sys.stderr)

    prevTeamSetttings = getTeamSettings(sessionName)
    if len(prevTeamSetttings.keys()):
        return ''

    sessionEntries = lookupValues(sessionName, ['adminPaced', 'dueDate', 'attributes'], INDEX_SHEET)
    adminPaced = sessionEntries.get('adminPaced')
    sessionAttributes = json.loads(sessionEntries['attributes'])
    sessionTeam = sessionAttributes['sessionTeam']

    if not sessionTeam or sessionTeam['session'] in ('_assign', '_generate'):
        return ''

    try:
        qno = sessionTeam.get('question') or 0

        if adminPaced and not sessionTeam['session'] and sessionTeam['slide'] >= adminPaced:
            return ''

        if sessionTeam['session'] and not sessionTeam['session'].startswith('_'):
            # Setup teams from previous session
            if not qno:
                raise Exception('Must specify valid question number to create team for session '+sessionName+' from session '+sessionTeam['session'])

        members, aliases, ranks, explanations = createTeam(sessionName, sessionTeam['session'], qno, alias=sessionTeam.get('alias',''), count=sessionTeam.get('count'), min_size=sessionTeam.get('minsize'), composition=sessionTeam.get('composition'), teamNames=sessionTeam.get('names'))

        finalizeSessionTeam(sessionName, members, aliases, ranks, explanations)
        
    except Exception, excp:
        if Settings['debug']:
            import traceback
            traceback.print_exc()
        errMsg = ' Unable to form teams for session %s from session %s: %s' % (sessionName, sessionTeam['session'], excp)
        print('sdproxy: '+errMsg, file=sys.stderr)
        return errMsg

    return ''


def updateSessionDiscussSheet(sessionName):
    # Create/update session_discuss sheet (which will contain rows for all users who have posted)
    if sessionName == previewingSession():
        # No sheet creation during preview
        return None

    sessionEntries = lookupValues(sessionName, ['adminPaced', 'dueDate', 'gradeDate', 'attributes'], INDEX_SHEET)
    adminPaced = sessionEntries.get('adminPaced')
    sessionAttributes = json.loads(sessionEntries['attributes'])
    discussSlides = sessionAttributes['discussSlides']

    if not discussSlides or not len(discussSlides):
        return None

    discussSheet = getSheet(sessionName+'_discuss')

    if not discussSheet:
        # Create discussion sheet for session
        sessionSheet = getSheet(sessionName)
        if not sessionSheet:
            return None

        discussHeaders = ['name', 'id']
        discussTopRow = ['', DISCUSS_ID]

        discussSheet = createSheet(sessionName+'_discuss', discussHeaders)
        discussSheet.insertRowBefore(2, keyValue=DISCUSS_ID)
        discussSheet.getRange(2, 1, 1, len(discussTopRow)).setValues([discussTopRow])

        # discuss_slidoc
        axsSheet = getSheet(DISCUSS_SHEET)
        if not axsSheet:
            # Create discussion access sheet (for posting)
            axsRowOffset = 2
            axsHeaders = ['name', 'id']
            axsTopRowVals = ['', DISCUSS_ID]
            axsSheet = createSheet(DISCUSS_SHEET, axsHeaders)
            axsSheet.insertRowBefore(axsRowOffset, keyValue=axsTopRowVals[1])
            axsSheet.getRange(axsRowOffset, 1, 1, len(axsTopRowVals)).setValues([axsTopRowVals])

        axsSession = '_'+sessionName
        axsColumn = indexColumns(axsSheet).get(axsSession)

        if axsColumn:
            blankColumn(axsSheet, axsSession)
        else:
            # Append column for session
            axsSheet.appendColumns([axsSession])
            axsColumn = indexColumns(axsSheet).get(axsSession)

        # Update top entry for column
        axsTopRow = lookupRowIndex(DISCUSS_ID, axsSheet)
        if not axsTopRow:
            raise Exception('Row with id '+DISCUSS_ID+' not found in sheet '+DISCUSS_SHEET)
        axsTopEntry = {'closed': {}, 'flagged': {}, 'flagCount': {}, 'lastPost': {}}

        axsSheet.getRange(axsTopRow, axsColumn, 1, 1).setValue(json.dumps(axsTopEntry))
        
    discussColIndex = indexColumns(discussSheet)
    appendHeaders = []
    for idisc in range(len(discussSlides)):
        discussNum = idisc + 1
        colHeader = DISCUSS_COL_FMT % discussNum
        if discussColIndex.get(colHeader):
            continue

        # Append discussNNN column
        appendHeaders.append(colHeader)

        if adminPaced:
            closeDiscussion(sessionName, discussNum)

    if len(appendHeaders):
        discussSheet.appendColumns(appendHeaders)

    return discussSheet


def teamCopy(sessionSheet, numStickyRows, userRow, teamCol, copyCol):
    # Copy column value from user row to entire team
    nRows = sessionSheet.getLastRow()-numStickyRows
    teamValues = sessionSheet.getSheetValues(1+numStickyRows, teamCol, nRows, 1)
    colRange = sessionSheet.getRange(1+numStickyRows, copyCol, nRows, 1)
    colValues = colRange.getValues()
    teamName = teamValues[userRow-numStickyRows-1][0]
    copyValue = colValues[userRow-numStickyRows-1][0]
    if not teamName:
        return
    for j in range(len(colValues)):
        if teamValues[j][0] == teamName:
            colValues[j][0] = copyValue
    colRange.setValues(colValues)

def makeShortNames(nameMap, first=False):
    # Make short versions of names from dict of the form {id: 'Last, First ...', ...}
    # If first, use first name as prefix, rather than last name
    # Returns map of id->shortName
    prefixDict = defaultdict(list)
    suffixesDict = {}
    for idValue, name in nameMap.items():
        lastName, _, firstmiddle = name.partition(',')
        lastName = lastName.strip()
        lastName = lastName[:1].upper() + lastName[1:]
        firstmiddle = firstmiddle.strip()
        if first:
            # For Firstname, try suffixes in following order: middle_initials+Lastname
            comps = firstmiddle.split()
            firstName = (comps and comps[0]) or idValue
            suffix = lastName
            if len(comps) > 1:
                suffix = ''.join(x[0] for x in comps[1:]).upper() + suffix
            prefixDict[firstName].append(idValue)
            suffixesDict[idValue] = [suffix]
        else:
            # For Lastname, try suffixes in following order: initials, first/middle names
            if not lastName:
                lastName = idValue
            initials = ''.join(x[0] for x in firstmiddle.split()).upper()
            prefixDict[lastName].append(idValue)
            suffixesDict[idValue] = [initials, firstmiddle]

    shortMap = {}
    for prefix, idValues in prefixDict.items():
        unique = None
        for j in range(1 if first else 2):
            suffixes = [suffixesDict[idValue][j] for idValue in idValues]
            maxlen = max([len(x) for x in suffixes])
            for k in range(maxlen+1):
                truncSet = set([x[:k] for x in suffixes])
                if len(suffixes) == len(truncSet):
                    # Suffixes uniquely map id for this truncation
                    unique = [j, k]
                    break
            if unique:
                break
        for idValue in idValues:
            if unique:
                shortMap[idValue] = prefix + suffixesDict[idValue][unique[0]][:unique[1]]
            else:
                shortMap[idValue] = prefix + '-' + idValue
                
    return shortMap
        

def createQuestionAttempted(response=''):
    return {'response': response or ''}

def loadSession(session_json):
    # Needed because JSON serialization converts integer keys to strings
    try:
        ustr = session_json.decode('utf8')
    except UnicodeError:
        try:
            ustr = session_json.decode('latin1')
        except UnicodeError:
            ustr = session_json.decode('utf8', 'ignore')

    session = json.loads(ustr)
    for attr in ('questionShuffle', 'questionsAttempted', 'hintsUsed'):
        if session.get(attr):
            dct = {}
            for k, v in session[attr].items():
                dct[int(k)] = v
            session[attr] = dct
    return session

def unpackSession(headers, row):
    # Unpacks hidden session object and adds response/explain fields from sheet row, as needed
    session_hidden = row[headers.index('session_hidden')]
    if not session_hidden:
        return None
    if session_hidden[0] != '{':
        session_hidden = base64.b64decode(session_hidden)
    session = loadSession(session_hidden)

    for j in range(len(headers)):
        header = headers[j]
        if header == 'name':
            session['displayName'] = row[j]
        if header in COPY_HEADERS:
            session[header] = (row[j] or 0) if  (header == 'lastSlide')  else (row[j] or '')
        elif row[j]:
            hmatch = QFIELD_RE.match(header)
            if hmatch and (hmatch.group(2) == 'response' or hmatch.group(2)  == 'explain' or hmatch.group(2)  == 'plugin'):
                # Copy only response/explain/plugin field to session
                qnumber = int(hmatch.group(1))
                if hmatch.group(2) == 'response':
                    if not row[j]:
                        # Null row entry deletes attempt
                        if qnumber in session.get('questionsAttempted'):
                            del session.get('questionsAttempted')[qnumber]
                    else:
                        if not (qnumber in session.get('questionsAttempted',{})):
                            session.get('questionsAttempted')[qnumber] = createQuestionAttempted()
                        # SKIP_ANSWER implies null answer attempt
                        session.get('questionsAttempted')[qnumber][hmatch.group(2)] = ''  if (row[j] == SKIP_ANSWER) else row[j]

                elif qnumber in session.get('questionsAttempted'):
                    # Explanation/plugin (ignored if no attempt)
                    if hmatch.group(2) == 'plugin':
                        if row[j]:
                            session.get('questionsAttempted')[qnumber][hmatch.group(2)] = json.loads(row[j])
                    else:
                        session.get('questionsAttempted')[qnumber][hmatch.group(2)] = row[j]
    return session


def splitNumericAnswer(corrAnswer):
    # Return [answer|null, error|null]
    if not corrAnswer:
        return [None, 0.0]
    comps = corrAnswer.split('+/-')
    corrValue = parseNumber(comps[0])
    corrError = 0.0
    if corrValue != None and len(comps) > 1:
        comps[1] = comps[1].strip()
        if comps[1][-1:] == '%':
            corrError = parseNumber(comps[1][:-1])
            if corrError and corrError > 0:
                corrError = (corrError/100.0)*corrValue
        else:
            corrError = parseNumber(comps[1])

    if corrError:
        corrError = abs(corrError)
    return [corrValue, corrError]


def scoreAnswer(response, qtype, corrAnswer):
    # Handle answer types: choice, number, text
    if not corrAnswer:
        return None

    if not response:
        return 0

    respValue = None

    # Check response against correct answer
    qscore = 0
    if qtype == 'number':
        # Check if numeric answer is correct
        respValue = parseNumber(response)
        corrComps = splitNumericAnswer(corrAnswer)

        if respValue != None and corrComps[0] != None and corrComps[1] != None:
            qscore = 1 if (abs(respValue-corrComps[0]) <= 1.001*corrComps[1]) else 0
        elif corrComps[0] == None:
            qscore = None
            if corrAnswer:
                raise Exception('scoreAnswer: Error in correct numeric answer:'+corrAnswer)
        elif corrComps[1] == None:
            qscore = None
            raise Exception('scoreAnswer: Error in correct numeric error:'+corrAnswer)

    else:
        # Check if non-numeric answer is correct (all spaces are removed before comparison)
        response = '' + str(response)
        normResp = response.strip().lower()
        # For choice, allow multiple correct answers (to fix grading problems)
        correctOptions = list(corrAnswer) if (qtype == 'choice')  else corrAnswer.split(' OR ')
        for j in range(len(correctOptions)):
            normCorr = re.sub(r'\s+', ' ', correctOptions[j].strip().lower())
            if ' ' in normCorr[1:]:
                # Correct answer has space(s); compare using normalized spaces
                qscore = 1 if (re.sub(r'\s+', ' ', normResp) == normCorr) else 0
            else:
                # Strip all spaces from response
                qscore = 1 if (re.sub(r'\s+', '', normResp) == normCorr) else 0

            if qscore:
                break

    return qscore


def tallyScores(questions, questionsAttempted, hintsUsed, params, remoteAnswers):
    skipAhead = 'skip_ahead' in params.get('features')

    questionsCount = 0
    weightedCount = 0
    questionsCorrect = 0
    weightedCorrect = 0
    questionsSkipped = 0

    correctSequence = 0
    lastSkipRef = ''

    skipToSlide = 0
    prevQuestionSlide = -1

    qscores = []
    for j in range(len(questions)):
        qnumber = j+1
        qAttempted = questionsAttempted.get(qnumber)
        if not qAttempted and params.get('paceLevel') >= QUESTION_PACE:
            # Process answers only in sequence
            break

        questionAttrs = questions[j]
        slideNum = questionAttrs.get('slide')
        if not qAttempted or slideNum < skipToSlide:
            # Unattempted or skipped
            qscores.append(None)
            continue

        if qAttempted.get('plugin'):
            qscore = parseNumber(qAttempted.get('plugin').get('score'))
        else:
            correctAns = qAttempted.get('expect') or questionAttrs.get('correct','')
            if not correctAns and remoteAnswers and len(remoteAnswers):
                correctAns = remoteAnswers[qnumber-1]
            qscore = scoreAnswer(qAttempted.get('response'), questionAttrs.get('qtype'), correctAns)

        qscores.append(qscore)
        qSkipCount = 0
        qSkipWeight = 0

        # Check for skipped questions
        if skipAhead and qscore == 1 and not hintsUsed.get(qnumber) and not qAttempted.get('retries'):
            # Correct answer (without hints and retries)
            if slideNum > prevQuestionSlide+1:
                # Question  not part of sequence
                correctSequence = 1
            elif correctSequence > 0:
                # Question part of correct sequence
                correctSequence += 1
        else:
            # Wrong/partially correct answer or no skipAhead
            correctSequence = 0

        prevQuestionSlide = slideNum

        lastSkipRef = ''
        if correctSequence and params.get('paceLevel') == QUESTION_PACE:
            skip = questionAttrs.get('skip')
            if skip and skip[0] > slideNum:
                # Skip ahead
                skipToSlide = skip[0]

                # Give credit for all skipped questions
                qSkipCount = skip[1]
                qSkipWeight = skip[2]
                lastSkipRef = skip[3]

        # Keep score for this question
        qWeight = questionAttrs.get('weight', 0)
        questionsSkipped += qSkipCount
        questionsCount += 1 + qSkipCount
        weightedCount += qWeight + qSkipWeight

        effectiveScore = qscore if (parseNumber(qscore) != None) else 1   # Give full credit to unscored answers

        if params.get('participationCredit'):
            # Full participation credit simply for attempting question (lateCredit applied in sheet)
            effectiveScore = 1

        elif hintsUsed.get(qnumber) and questionAttrs.get('hints') and len(questionAttrs.get('hints')):
            if hintsUsed[qnumber] > len(questionAttrs.get('hints')):
                raise Exception('Internal Error: Inconsistent hint count')
            for j in range(hintsUsed[qnumber]):
                effectiveScore -= abs(questionAttrs.get('hints')[j])

        if questionAttrs.get('participation'):  # Minimum (normalized) score for attempting question
            effectiveScore = max(effectiveScore, questionAttrs['participation']);
	
        if effectiveScore > 0:
            questionsCorrect += 1 + qSkipCount
            weightedCorrect += effectiveScore*qWeight + qSkipWeight

    return { 'questionsCount': questionsCount, 'weightedCount': weightedCount,
                'questionsCorrect': questionsCorrect, 'weightedCorrect': weightedCorrect,
                'questionsSkipped': questionsSkipped, 'correctSequence': correctSequence, 'skipToSlide': skipToSlide,
                'correctSequence': correctSequence, 'lastSkipRef': lastSkipRef, 'qscores': qscores}


def getSessionNames():
    indexSheet = getSheet(INDEX_SHEET)
    if not indexSheet:
        raise Exception('Session index sheet not found: '+INDEX_SHEET)

    return getColumns('id', indexSheet)

def actionHandler(actions, sheetName='', create=False):
    sessions = [sheetName]  if sheetName else getSessionNames()
    actionList = actions.split(',')
    print('sdproxy.actionHandler: %s' % actions, file=sys.stderr)
    refreshSheets = []
    for k in range(0,len(actionList)):
        action = actionList[k]
        createPrefix = '*' if create else ''
        if action[0] == '*':
            createPrefix = '*'
            action = action[1:];

        if action in ('answer_stats', 'correct'):
            try:
                if action == 'answer_stats':
                    for j in range(0,len(sessions)):
                        updateAnswers(sessions[j], createPrefix)
                        updateStats(sessions[j], createPrefix)
                        refreshSheets.append(sessions[j]+'_answers')
                        refreshSheets.append(sessions[j]+'_stats')
                elif action == 'correct':
                    for j in range(0,len(sessions)):
                        updateCorrect(sessions[j], createPrefix)
                        refreshSheets.append(sessions[j]+'_correct')
            except Exception, excp:
                if Settings['debug']:
                    import traceback
                    traceback.print_exc()
                raise Exception('Error:ACTION:Error in action %s for session(s) %s; may need to delete related sheet(s): %s' % (action, sessions, excp))
        elif action == 'gradebook':
            # Gradebook action will be handled remotely
            for j in range(0,len(sessions)):
                actSheet = getSheet(sessions[j])
                if actSheet:
                    actSheet.requestActions(createPrefix+action)
                    print('sdproxy.actionHandler2: %s %s' % (sessions[j], createPrefix+action), file=sys.stderr)
        else:
            raise Exception('Error:ACTION:Invalid action '+action+' for session(s) '+sessions)
    return refreshSheets

def getNormalUserRow(sessionSheet, sessionStartRow):
    # Returns starting row number for rows with non-special users (i.get('e')., names not starting with # and id's not starting with _)
    normalRow = sessionStartRow

    sessionColIndex = indexColumns(sessionSheet)
    nids = sessionSheet.getLastRow()-sessionStartRow+1
    if nids:
        temIds = sessionSheet.getSheetValues(sessionStartRow, sessionColIndex['id'], nids, 1)
        temNames = sessionSheet.getSheetValues(sessionStartRow, sessionColIndex['name'], nids, 1)
        for j in range(0,nids):
            # Skip any initial row(s) in the roster with test user or ID/names starting with underscore/hash
            # when computing averages and other stats
            if temIds[j][0] == TESTUSER_ID or temIds[j][0].startswith('_') or temNames[j][0].startswith('#'):
                normalRow += 1
            else:
                break
    return normalRow

def updateColumnAvg(sheet, colNum, avgRow, startRow, countBlanks=False):
    avgCell = sheet.getRange(avgRow, colNum, 1, 1)
    if ACTION_FORMULAS:
        avgFormula = '=AVERAGE('+colIndexToChar(colNum)+'$'+startRow+':'+colIndexToChar(colNum)+')'
        avgCell.setValue(avgFormula)
        return
    nRows = sheet.getLastRow()-startRow+1
    if not nRows:
        return
    colVals = sheet.getSheetValues(startRow, colNum, nRows, 1)
    accum = 0.0
    count = nRows
    for j in range(0,nRows):
        if isNumber(colVals[j][0]):
            accum += colVals[j][0]
        elif not countBlanks:
            count -= 1
    if count:
        avgCell.setValue(accum/count)
    else:
        avgCell.setValue('')

def updateAnswers(sessionName, create):
    try:
        sessionSheet = getSheetCache(sessionName)
        if not sessionSheet:
            raise Exception('Sheet not found: '+sessionName)
        if not sessionSheet.getLastColumn():
            raise Exception('No columns in sheet: '+sessionName)

        answerSheetName = sessionName+'_answers'
        answerSheet = getSheet(answerSheetName)
        if not answerSheet and not create:
            return ''

        sessionColIndex = indexColumns(sessionSheet)
        sessionColHeaders = sessionSheet.getSheetValues(1, 1, 1, sessionSheet.getLastColumn())[0]

        sessionEntries = lookupValues(sessionName, ['attributes', 'questions'], INDEX_SHEET)
        sessionAttributes = json.loads(sessionEntries.get('attributes'))
        questions = json.loads(sessionEntries.get('questions'))
        qtypes = []
        answers = []
        for j in range(0,len(questions)):
            qtypes.append(questions[j].get('qtype', ''))
            answers.append(questions[j].get('correct'))

        # Copy columns from session sheet
        sessionCopyCols = ['name', 'id', 'Timestamp']
        answerHeaders = sessionCopyCols + []
        baseCols = len(answerHeaders)

        respCols = []
        extraCols = ['expect', 'score', 'plugin', 'hints']
        for j in range(0,len(qtypes)):
            qprefix = 'q'+str(j+1)
            pluginMatch = PLUGIN_RE.match(answers[j] or '')
            pluginAction = pluginMatch.group(3)  if pluginMatch  else ''
            respColName = qprefix
            if answers[j] and pluginAction != 'expect':
                if qtypes[j] == 'choice':
                    respColName += '_'+answers[j]
                elif qtypes[j] == 'number':
                    respColName += '_'+answers[j].replace(' +/- ','_pm_').replace('+/-','_pm_').replace('%','pct').replace(' ','_')
            answerHeaders.append(respColName)
            respCols.append(len(answerHeaders))
            if pluginAction == 'expect':
                answerHeaders.append(qprefix+'_expect')
            if answers[j] or pluginAction == 'response':
                answerHeaders.append(qprefix+'_score')
            if pluginAction == 'response':
                answerHeaders.append(qprefix+'_plugin')
            if sessionAttributes.get('hints') and sessionAttributes.get('hints')[qprefix]:
                answerHeaders.append(qprefix+'_hints')

        # Session sheet columns
        sessionStartRow = SESSION_START_ROW

        # Answers sheet columns
        answerAvgRow = 2
        answerStartRow = 3

        # Session answers headers

        # New answers sheet
        answerSheet = createSheet(answerSheetName, answerHeaders, True)
        ansColIndex = indexColumns(answerSheet)

        answerSheet.getRange(str(answerAvgRow)+':'+str(answerAvgRow)).setFontStyle('italic')
        answerSheet.getRange(answerAvgRow, ansColIndex['id'], 1, 1).setValues([[AVERAGE_ID]])
        answerSheet.getRange(answerAvgRow, ansColIndex['Timestamp'], 1, 1).setValues([[createDate()]])

        avgStartRow = answerStartRow + getNormalUserRow(sessionSheet, sessionStartRow) - sessionStartRow

        # Number of ids
        nids = sessionSheet.getLastRow()-sessionStartRow+1

        if nids:
            # Copy session values
            for j in range(0,len(sessionCopyCols)):
                colHeader = sessionCopyCols[j]
                sessionCol = sessionColIndex[colHeader]
                ansCol = ansColIndex[colHeader]
                answerSheet.getRange(answerStartRow, ansCol, nids, 1).setValues(sessionSheet.getSheetValues(sessionStartRow, sessionCol, nids, 1))

        # Get hidden session values
        hiddenSessionCol = sessionColIndex['session_hidden']
        hiddenVals = sessionSheet.getSheetValues(sessionStartRow, hiddenSessionCol, nids, 1)
        qRows = []

        for j in range(0,nids):
            rowValues = sessionSheet.getSheetValues(j+sessionStartRow, 1, 1, len(sessionColHeaders))[0]
            savedSession = unpackSession(sessionColHeaders, rowValues)
            qAttempted = savedSession.get('questionsAttempted')
            qHints = savedSession.get('hintsUsed')
            scores = tallyScores(questions, savedSession.get('questionsAttempted'), savedSession.get('hintsUsed'), sessionAttributes.get('params'), sessionAttributes.get('remoteAnswers'))

            rowVals = []
            for k in range(0,len(answerHeaders)):
                rowVals.append('')

            for k in range(0,len(questions)):
                qno = k+1
                if qAttempted.get(qno):
                    qprefix = 'q'+str(qno)
                    # Copy responses
                    rowVals[respCols[qno-1]-1] = (qAttempted[qno].get('response') or '')
                    if qAttempted[qno].get('explain'):
                        rowVals[respCols[qno-1]-1] += '\nEXPLANATION: ' + qAttempted[qno].get('explain')
                    # Copy extras
                    for m in range(0,len(extraCols)):
                        attr = extraCols[m]
                        qcolName = qprefix+'_'+attr
                        if qcolName in ansColIndex:
                            if attr == 'hints':
                                rowVals[ansColIndex[qcolName]-1] = qHints[qno] or ''
                            elif attr == 'score':
                                rowVals[ansColIndex[qcolName]-1] = scores.get('qscores')[qno-1] or 0
                            elif attr in qAttempted[qno]:
                                rowVals[ansColIndex[qcolName]-1] = '' if (qAttempted[qno][attr]==None)  else qAttempted[qno][attr]
            qRows.append(rowVals[baseCols:])
        answerSheet.getRange(answerStartRow, baseCols+1, nids, len(answerHeaders)-baseCols).setValues(qRows)

        for ansCol in range(baseCols+1,len(answerHeaders)+1):
            if answerHeaders[ansCol-1][-6:] == '_score':
                answerSheet.getRange(answerAvgRow, ansCol, 1, 1).setNumberFormat('0.###')
                updateColumnAvg(answerSheet, ansCol, answerAvgRow, avgStartRow)
    finally:
        pass
    return answerSheetName


def updateCorrect(sessionName, create):
    try:
        sessionSheet = getSheetCache(sessionName)
        if not sessionSheet:
            raise Exception('Sheet not found: '+sessionName)
        if not sessionSheet.getLastColumn():
            raise Exception('No columns in sheet: '+sessionName)

        correctSheetName = sessionName+'_correct'
        correctSheet = getSheet(correctSheetName)
        if not correctSheet and not create:
            return ''

        sessionColIndex = indexColumns(sessionSheet)
        sessionColHeaders = sessionSheet.getSheetValues(1, 1, 1, sessionSheet.getLastColumn())[0]

        sessionEntries = lookupValues(sessionName, ['attributes', 'questions'], INDEX_SHEET)
        sessionAttributes = json.loads(sessionEntries.get('attributes'))
        questions = json.loads(sessionEntries.get('questions'))
        qtypes = []
        answers = []
        for j in range(0,len(questions)):
            qtypes.append(questions[j].get('qtype', ''))
            answers.append(questions[j].get('correct'))

        # Copy columns from session sheet
        sessionCopyCols = ['name', 'id', 'Timestamp']
        correctHeaders = sessionCopyCols + ['randomSeed']
        baseCols = len(correctHeaders)

        for j in range(0,len(questions)):
            correctHeaders.append('q'+str(j+1))

        # Session sheet columns
        sessionStartRow = SESSION_START_ROW

        # Correct sheet columns
        correctStartRow = 3

        # New correct sheet
        correctSheet = createSheet(correctSheetName, correctHeaders, True)
        corrColIndex = indexColumns(correctSheet)

        correctSheet.getRange('2:2').setFontStyle('italic')
        correctSheet.getRange(2, corrColIndex['id'], 1, 1).setValues([[AVERAGE_ID]])
        correctSheet.getRange(2, corrColIndex['Timestamp'], 1, 1).setValues([[createDate()]])

        # Number of ids
        nids = sessionSheet.getLastRow()-sessionStartRow+1

        # Copy session values
        for j in range(0,len(sessionCopyCols)):
            colHeader = sessionCopyCols[j]
            sessionCol = sessionColIndex[colHeader]
            corrCol = corrColIndex[colHeader]
            correctSheet.getRange(correctStartRow, corrCol, nids, 1).setValues(sessionSheet.getSheetValues(sessionStartRow, sessionCol, nids, 1))

        # Get hidden session values
        hiddenSessionCol = sessionColIndex['session_hidden']
        hiddenVals = sessionSheet.getSheetValues(sessionStartRow, hiddenSessionCol, nids, 1)
        qRows = []
        randomSeeds = []

        for j in range(0,nids):
            rowValues = sessionSheet.getSheetValues(j+sessionStartRow, 1, 1, len(sessionColHeaders))[0]
            savedSession = unpackSession(sessionColHeaders, rowValues)
            qAttempted = savedSession.get('questionsAttempted')
            qShuffle = savedSession.get('questionShuffle')
            randomSeeds.append([savedSession.get('randomSeed')])

            rowVals = []

            for k in range(0,len(questions)):
                qno = k+1
                correctAns = answers[k]
                if qno in qShuffle and correctAns:
                    shuffledAns = ''
                    for l in range(len(correctAns)):
                        if correctAns[l].upper() in qShuffle[qno]:
                            shuffledAns += chr(ord('A') + qShuffle[qno].index(correctAns[l].upper()) - 1)
                        else:
                            shuffledAns += 'X'
                    correctAns = shuffledAns
                elif qAttempted.get('expect'):
                    correctAns = qAttempted.get('expect')
                elif qAttempted.get('pluginResp') and 'correctAnswer' in qAttempted.get('pluginResp'):
                    correctAns = qAttempted.get('pluginResp').get('correctAnswer')
                rowVals.append(correctAns)
            qRows.append(rowVals)

        correctSheet.getRange(correctStartRow, baseCols+1, nids, len(questions)).setValues(qRows)
        correctSheet.getRange(correctStartRow, corrColIndex['randomSeed'], nids, 1).setValues(randomSeeds)
    finally:
        pass
    return correctSheetName

def updateStats(sessionName, create):
    try:
        sessionSheet = getSheetCache(sessionName)
        if not sessionSheet:
            raise Exception('Sheet not found '+sessionName)
        if not sessionSheet.getLastColumn():
            raise Exception('No columns in sheet '+sessionName)

        statSheetName = sessionName+'_stats'
        statSheet = getSheet(statSheetName)
        if not statSheet and not create:
            return ''

        sessionColIndex = indexColumns(sessionSheet)
        sessionColHeaders = sessionSheet.getSheetValues(1, 1, 1, sessionSheet.getLastColumn())[0]

        # Session sheet columns
        sessionStartRow = SESSION_START_ROW
        nids = sessionSheet.getLastRow()-sessionStartRow+1

        sessionEntries = lookupValues(sessionName, ['attributes', 'questions', 'questionConcepts', 'primary_qconcepts', 'secondary_qconcepts'], INDEX_SHEET)
        sessionAttributes = json.loads(sessionEntries.get('attributes'))
        questions = json.loads(sessionEntries.get('questions'))
        questionConcepts = json.loads(sessionEntries.get('questionConcepts'))
        p_concepts = sessionEntries.get('primary_qconcepts').split('; ')  if sessionEntries.get('primary_qconcepts')  else []
        s_concepts = sessionEntries.get('secondary_qconcepts').split('; ')  if sessionEntries.get('secondary_qconcepts')  else []
        allQuestionConcepts = [p_concepts, s_concepts]

        # Session stats headers
        sessionCopyCols = ['name', 'id', 'Timestamp', 'lateToken', 'lastSlide']
        statExtraCols = ['weightedCorrect', 'correct', 'count', 'skipped']

        statHeaders = sessionCopyCols + statExtraCols
        for j in range(0,len(p_concepts)):
            statHeaders.append('p:'+p_concepts[j])
        for j in range(0,len(s_concepts)):
            statHeaders.append('s:'+s_concepts[j])
        nconcepts = len(p_concepts) + len(s_concepts)

        # Stats sheet columns
        statAvgRow = 2
        statStartRow = 3# Leave blank row for formulas
        statQuestionCol = len(sessionCopyCols)+1
        nqstats = len(statExtraCols)
        statConceptsCol = statQuestionCol + nqstats

        avgStartRow = statStartRow + getNormalUserRow(sessionSheet, sessionStartRow) - sessionStartRow

        # New stat sheet
        statSheet = createSheet(statSheetName, statHeaders, True)

        statSheet.getRange(statAvgRow, len(sessionCopyCols)+1, 1, len(statHeaders)-len(sessionCopyCols)).setNumberFormat('0.###')

        statColIndex = indexColumns(statSheet)
        statSheet.getRange(statAvgRow, statColIndex['id'], 1, 1).setValues([[AVERAGE_ID]])
        statSheet.getRange(statAvgRow, statColIndex['Timestamp'], 1, 1).setValues([[createDate()]])
        statSheet.getRange(str(statAvgRow)+':'+str(statAvgRow)).setFontStyle('italic')

        for j in range(0,len(sessionCopyCols)):
            colHeader = sessionCopyCols[j]
            sessionCol = sessionColIndex[colHeader]
            statCol = statColIndex[colHeader]
            statSheet.getRange(statStartRow, statCol, nids, 1).setValues(sessionSheet.getSheetValues(sessionStartRow, sessionCol, nids, 1))

        hiddenSessionCol = sessionColIndex['session_hidden']
        hiddenVals = sessionSheet.getSheetValues(sessionStartRow, hiddenSessionCol, nids, 1)
        questionTallies = []
        conceptTallies = []
        nullConcepts = []
        for j in range(0,nconcepts):
            nullConcepts.append('')

        for j in range(0,nids):
            rowValues = sessionSheet.getSheetValues(j+sessionStartRow, 1, 1, len(sessionColHeaders))[0]
            savedSession = unpackSession(sessionColHeaders, rowValues)
            scores = tallyScores(questions, savedSession.get('questionsAttempted'), savedSession.get('hintsUsed'), sessionAttributes.get('params'), sessionAttributes.get('remoteAnswers'))

            questionTallies.append([scores.get('weightedCorrect'), scores.get('questionsCorrect'), scores.get('questionsCount'), scores.get('questionsSkipped')])

            qscores = scores.get('qscores')
            missedConcepts = trackConcepts(scores.get('qscores'), questionConcepts, allQuestionConcepts)
            if len(missedConcepts[0]) or len(missedConcepts[1]):
                missedFraction = []
                for m in range(0,len(missedConcepts)):
                    for k in range(0,len(missedConcepts[m])):
                        missedFraction.append(missedConcepts[m][k][0]/(1.0*max(1,missedConcepts[m][k][1])))
                conceptTallies.append(missedFraction)
            else:
                conceptTallies.append(nullConcepts)
        statSheet.getRange(statStartRow, statQuestionCol, nids, nqstats).setValues(questionTallies)
        if nconcepts:
            statSheet.getRange(statStartRow, statConceptsCol, nids, nconcepts).setValues(conceptTallies)

        for avgCol in range(len(sessionCopyCols)+1,len(statHeaders)+1):
            updateColumnAvg(statSheet, avgCol, statAvgRow, avgStartRow)
    finally:
        pass

    return statSheetName

def trackConcepts(qscores, questionConcepts, allQuestionConcepts):
    # Track missed concepts:  missedConcepts = [ [ [missed,total], [missed,total], ...], [...] ]
    missedConcepts = [ [], [] ]
    if len(allQuestionConcepts) != 2:
        return missedConcepts
    for m in range(0,2):
        for k in range(0,len(allQuestionConcepts[m])):
            missedConcepts[m].append([0,0])

    for qnumber in range(1,len(qscores)+1):
        qConcepts = questionConcepts[qnumber-1]
        if qscores[qnumber-1] == None or not len(qConcepts) or (not len(qConcepts[0]) and not len(qConcepts[1])):
            continue
        missed = qscores[qnumber-1] < 1

        for m in range(0,2):
            # Primary/secondary concept
            for j in range(0,len(qConcepts[m])):
                for k in range(0, len(allQuestionConcepts[m])):
                    if qConcepts[m][j] == allQuestionConcepts[m][k]:
                        if missed:
                            missedConcepts[m][k][0] += 1# Missed count
                        missedConcepts[m][k][1] += 1# Attempted count
    return missedConcepts
