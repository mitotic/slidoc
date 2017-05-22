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
import subprocess
import sys
import time
import urllib
import urllib2
import uuid

from collections import defaultdict, OrderedDict

import tornado.httpclient
from tornado.ioloop import IOLoop

import reload
import sliauth

VERSION = '0.97.5j'

UPDATE_PARTIAL_ROWS = True

scriptdir = os.path.dirname(os.path.realpath(__file__))

# Usually modified by importing module
Settings = {
    'update_time': None,
                          # Site specific settings from server
    'auth_key': None,     # Site digest authentication key
    'gsheet_url': None,   # Site google Sheet URL
    'site_name': '',      # Site name

                          # General settings from server
    'backup_dir': '_BACKUPS/', # Backup directory prefix, including slash
    'debug': None,      
    'dry_run': None,      # Dry run (read from, but do not update, Google Sheets)
    'lock_proxy_url': '', # URL of proxy server to lock sheet
    'log_call': 0,        # Enable call debugging (logs calls to sheet 'call_log'; may generate very large amounts of output)
    'min_wait_sec': 0,    # Minimum time (sec) between successful Google Sheet requests
    'server_url': '',     # Base URL of server (if any); e.g., http://example.com'

                          # Settings from SETTINGS_SLIDOC
    'freeze_date': '',    # Date when all user mods are disabled
    'request_timeout': 75,  # Proxy update request timeout (sec)
    'require_login_token': True,
    'require_late_token': True,
    'share_averages': True, # Share class averages for tests etc.
    'site_label': '',
    'site_restricted': '',
    'site_title': '',
    'admin_users': '',
    'grader_users': '',
    'guest_users': '',
    'total_column': ''
    }

COPY_FROM_SHEET = ['freeze_date',  'require_login_token', 'require_late_token',
                   'share_averages', 'site_label', 'site_title',
                   'admin_users', 'grader_users', 'guest_users', 'total_column']
    
COPY_FROM_SERVER = ['auth_key', 'gsheet_url', 'site_name',
                    'backup_dir', 'debug', 'dry_run',
                    'lock_proxy_url', 'log_call', 'min_wait_sec', 'request_timeout', 'server_url']
    
RETRY_WAIT_TIME = 5           # Minimum time (sec) before retrying failed Google Sheet requests
RETRY_MAX_COUNT = 5           # Maximum number of failed Google Sheet requests
CACHE_HOLD_SEC = 3600         # Maximum time (sec) to hold sheet in cache
PROXY_UPDATE_ROW_LIMIT = 200  # Max. no of rows per sheet, per proxy update request

TIMED_GRACE_SEC = 15          # Grace period for timed submissions (usually about 15 seconds)

ADMIN_ROLE = 'admin'
GRADER_ROLE = 'grader'

ADMINUSER_ID = 'admin'
MAXSCORE_ID = '_max_score'
AVERAGE_ID = '_average'
RESCALE_ID = '_rescale'
TESTUSER_ID = '_test_user'
DISCUSS_ID = '_discuss'

MIN_HEADERS = ['name', 'id', 'email', 'altid']
COPY_HEADERS = ['source', 'team', 'lateToken', 'lastSlide', 'retakes']

TESTUSER_ROSTER = ['#user, test', TESTUSER_ID, '', '']

SETTINGS_SHEET = 'settings_slidoc'
INDEX_SHEET = 'sessions_slidoc'
ROSTER_SHEET = 'roster_slidoc'
SCORES_SHEET = 'scores_slidoc'

BACKUP_SHEETS = [SETTINGS_SHEET, INDEX_SHEET, ROSTER_SHEET, SCORES_SHEET]

BASIC_PACE    = 1
QUESTION_PACE = 2
ADMIN_PACE    = 3

SKIP_ANSWER = 'skip'

LATE_SUBMIT = 'late'

FUTURE_DATE = 'future'

TRUNCATE_DIGEST = 8

QFIELD_RE = re.compile(r"^q(\d+)_([a-z]+)$")
QFIELD_MOD_RE = re.compile(r"^(q_other|q_comments|q(\d+)_(comments|grade))$")

DELETED_POST = '(deleted)'
POST_PREFIX_RE = re.compile(r'^Post:(\d+):([-\d:T]+)(\s|$)')
POST_NUM_RE = re.compile(r'(\d+):([-\d:T]+)([\s\S]*)$')
AXS_RE = re.compile(r'access(\d+)')

class Dummy():
    pass
    
Sheet_cache = {}    # Cache of sheets
Miss_cache = {}     # For optional sheets that are missing
Lock_cache = {}     # Locked sheets
Lock_passthru = defaultdict(int)  # Count of passthru

Global = Dummy()

Global.remoteVersions = set()
Global.shuttingDown = False
Global.updatePartial = UPDATE_PARTIAL_ROWS

def copyServerOptions(serverOptions):
    for key in COPY_FROM_SERVER:
        Settings[key] = serverOptions[key]

def copySheetOptions(sheetSettings):
    # May need to restart server if certain SETTINGS_SHEET parameters changed
    if not sheetSettings:
        return
    for key in COPY_FROM_SHEET:
        if key in sheetSettings:
            Settings[key] = sheetSettings[key]
    Settings['update_time'] = sliauth.create_date()

def delSheet(sheetName):
    for cache in (Sheet_cache, Miss_cache, Lock_cache, Lock_passthru):
        if sheetName in cache:
            del cache[sheetName]


def initCache():
    Sheet_cache.clear()
    Miss_cache.clear()
    Lock_cache.clear()
    Lock_passthru.clear()

    Global.httpRequestId = ''

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

initCache()

def previewingSession():
    return Global.previewStatus.get('sessionName', '')

def startPreview(sessionName):
    # Initiate/end preview of session
    # (Delay upstream updates to session sheet and index sheet; also lock all index sheet rows except for this session)
    # Return error message or null string
    if not sessionName:
        raise Exception('Null session name for preview')

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
            return 'Pending updates for session %s; retry preview after 10-20 seconds (reqid=%s)' % (sessionName, Global.httpRequestId)
    else:
        sessionSheet = getSheet(sessionName, optional=True)

    indexSheet = Sheet_cache.get(INDEX_SHEET)
    if indexSheet:
        if indexSheet.get_updates() is not None:
            return 'Pending updates for sheet '+INDEX_SHEET+'; retry preview after 10-20 seconds'
    else:
        indexSheet = getSheet(INDEX_SHEET)

    Global.previewStatus = {'sessionName': sessionName, 'sessionSheetOrig': sessionSheet.copy() if sessionSheet else None,
                              'indexSheetOrig': indexSheet.copy()}

    if Settings['debug']:
        print("DEBUG:startPreview: %s " % sessionName, file=sys.stderr)

    return ''

def endPreview():
    # End preview; enable upstream updates
    if not Global.previewStatus:
        return
    if Settings['debug']:
        print("DEBUG:endPreview: %s " % Global.previewStatus.get('sessionName'), file=sys.stderr)
    Global.previewStatus = {}
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

def revertPreview(saved=False):
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
        Sheet_cache[INDEX_SHEET] = Global.previewStatus['indexSheetOrig']

    endPreview()

def freezeCache(fill=False):
    # Freeze cache (clear when done)
    if Global.previewStatus:
        raise Exception('Cannot freeze when previewing session '+Global.previewStatus['sessionName'])
    if Global.suspended == "freeze":
        return
    if fill:
        # Fill cache
        sessionNames = []
        for sheetName in BACKUP_SHEETS:
            sheet = getSheet(sheetName, optional=True)
            if sheet and sheetName == INDEX_SHEET:
                sessionNames = getColumns('id', sheet)

        for sheetName in sessionNames:
            sessionSheet = getSheet(sheetName, optional=True)
    suspend_cache('freeze')


def backupSheets(dirpath=''):
    # Returns null string on success or error string list
    # (synchronous)
    if Global.previewStatus:
        return [ 'Cannot freeze when previewing session '+Global.previewStatus['sessionName'] ]
    dirpath = dirpath or Settings['backup_dir'] or '_BACKUPS'
    if dirpath.endswith('-'):
        dirpath += sliauth.iso_date(nosec=True).replace(':','-')
    if Settings['site_name']:
        dirpath += '/' + Settings['site_name']
    suspend_cache("backup")
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

        if sessionAttributes is None:
            errorList.append('Error: Session attributes not found in index sheet %s' % INDEX_SHEET)

        for name, attributes in (sessionAttributes or []):
            backupSheet(name, dirpath, errorList)
            if attributes.get('discussSlides'):
                backupSheet(name+'-discuss', dirpath, errorList, optional=True)
    except Exception, excp:
        errorList.append('Error in backup: '+str(excp))

    errors = '\n'.join(errorList)+'\n' if errorList else ''
    if errors:
        try:
            with  open(dirpath+'/ERRORS_IN_BACKUP.txt', 'w') as errfile:
                errfile.write(errors)
        except Exception, excp:
            print("ERROR:backupSheets: ", str(excp), file=sys.stderr)

    if Settings['debug']:
        if errors:
            print(errors, file=sys.stderr)
        print("DEBUG:backupSheets: %s completed %s" % (dirpath, datetime.datetime.now()), file=sys.stderr)
    suspend_cache("")
    return errors


def backupCell(value):
    if value is None:
        return ''
    if isinstance(value, datetime.datetime):
        return sliauth.iso_date(value, utc=True)
    if isinstance(value, unicode):
        return value.encode('utf-8')
    return str(value)


def backupSheet(name, dirpath, errorList, optional=False):
    retval = downloadSheet(name, backup=True)

    if retval['result'] != 'success':
        if optional and retval['error'].startswith('Error:NOSHEET:'):
            pass
        else:
            errorList.append('Error in downloading sheet %s: %s' % (name, retval['error']))
        return None

    rows = retval.get('value')
    try:
        rowNum = 0
        with open(dirpath+'/'+name+'.csv', 'wb') as csvfile:
            writer = csv.writer(csvfile)
            for j, row in enumerate(rows):
                rowStr = [backupCell(x) for x in row]
                writer.writerow(rowStr)
    except Exception, excp:
        errorList.append('Error in saving sheet %s (row %d): %s' % (name, j+1, excp))
        return None

    return rows


def isReadOnly(sheetName):
    return (sheetName.endswith('_slidoc') and sheetName not in (INDEX_SHEET, ROSTER_SHEET)) or sheetName.endswith('-answers') or sheetName.endswith('-stats')

def getSheet(sheetName, optional=False, backup=False, display=False):
    cached = sheetName in Sheet_cache

    if not display or not cached:
        check_if_locked(sheetName, get=True, backup=backup, cached=cached)

    if cached:
        return Sheet_cache[sheetName]
    elif optional and sheetName in Miss_cache:
        # If optional sheets are later created, will need to clear cache
        if not backup and (sliauth.epoch_ms() - Miss_cache[sheetName]) < 0.5*1000*CACHE_HOLD_SEC:
            return None
        # Retry retrieving optional sheet
        del Miss_cache[sheetName]

    if Settings['lock_proxy_url'] and not sheetName.endswith('_slidoc') and not sheetName.endswith('_log'):
        # Lock sheet in upstream proxy
        lockURL = Settings['lock_proxy_url']
        if Settings['site_name']:
            lockURL += '/' + Settings['site_name']
        lockURL += '/_proxy/_lock/'+sheetName
        try:
            req = urllib2.Request(lockURL+'?token='+Settings['auth_key']+'&type=proxy')
            response = urllib2.urlopen(req)
            if Settings['debug']:
                print("DEBUG:getSheet: %s LOCKED %s (%s)" % (sheetName, lockURL, response.read()), file=sys.stderr)
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
        if optional and retval['error'].startswith('Error:NOSHEET:'):
            Miss_cache[sheetName] = sliauth.epoch_ms()
            return None
        else:
            raise Exception("%s (Error in accessing sheet '%s')" % (retval['error'], sheetName))
    rows = retval.get('value')
    if not rows:
        raise Exception("Empty sheet '%s'" % sheetName)
    keyHeader = '' if sheetName.startswith('settings_') or sheetName.endswith('_log') else 'id'
    Sheet_cache[sheetName] = Sheet(sheetName, rows, keyHeader=keyHeader)
    return Sheet_cache[sheetName]

def downloadSheet(sheetName, backup=False):
    # Download sheet synchronously
    # If backup, retrieve formulas rather than values
    if Global.previewStatus.get('sessionName') == sheetName:
        raise Exception('Cannot download when previewing session '+Global.previewStatus['sessionName'])
    user = ADMINUSER_ID
    userToken = gen_proxy_token(user, ADMIN_ROLE)

    getParams = {'sheet': sheetName, 'proxy': '1', 'get': '1', 'all': '1', 'admin': user, 'token': userToken}
    if backup:
        getParams['formula'] = 1

    if Settings['log_call'] > 1:
        getParams['logcall'] = str(Settings['log_call'])

    if Settings['debug']:
        print("DEBUG:downloadSheet", sheetName, getParams, file=sys.stderr)

    if Settings['gsheet_url']:
        retval = sliauth.http_post(Settings['gsheet_url'], getParams, add_size_info=True)
    else:
        retval =  {'result': 'error', 'error': 'No Sheet URL'}

    if Settings['debug']:
        print("DEBUG:downloadSheet", sheetName, retval['result'], retval.get('info',{}).get('version'), retval.get('bytes'), retval.get('messages'), file=sys.stderr)

    Global.remoteVersions.add( retval.get('info',{}).get('version','') )

    return retval

def createSheet(sheetName, headers, rows=[]):
    check_if_locked(sheetName)

    if not headers:
        raise Exception("Must specify headers to create sheet %s" % sheetName)
    if sheetName in Sheet_cache:
        raise Exception("Cannote create sheet %s because it is already present in the cache" % sheetName)

    keyHeader = '' if sheetName.startswith('settings_') or sheetName.endswith('_log') else 'id'
    Sheet_cache[sheetName] = Sheet(sheetName, [headers]+rows, keyHeader=keyHeader, modTime=sliauth.epoch_ms())
    Sheet_cache[sheetName].modifiedSheet()
    return Sheet_cache[sheetName]


class Sheet(object):
    # Implements a simple spreadsheet with fixed number of columns
    def __init__(self, name, rows, keyHeader='', modTime=0, accessTime=None, keyMap=None, actions='', modifiedHeaders=False):
        if not rows:
            raise Exception('Must specify at least header row for sheet')
        self.name = name
        self.keyHeader = keyHeader
        self.modTime = modTime
        self.accessTime = sliauth.epoch_ms() if accessTime is None else accessTime

        self.actionsRequested = actions
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
        if self.totalCols:
            for rowNum in range(2,len(self.xrows)):
                self.update_total(rowNum)

        if keyMap is not None:
            # Create 3-level copy of key map
            self.keyMap = dict( (k, [v[0], v[1], v[2].copy()]) for k, v in keyMap.items() )
        else:
            # New key map
            self.keyMap = {}
            for j, row in enumerate(self.xrows[1:]):
                key = row[self.keyCol-1] if self.keyCol else j+2
                self.keyMap[key] = [modTime, 0, set()]  # [modTime, insertedFlag, modColsSet]

        if self.keyCol and 1+len(self.keyMap) != len(self.xrows):
            raise Exception('Duplicate key in initial rows for sheet %s: %s' % (self.name, [x[self.keyCol-1] for x in self.xrows[1:]]))

    def update_total_formula(self):
        self.totalCols = []
        self.totalColSet = set()
        if not self.keyCol:
            return
        headers = self.xrows[0]
        if Settings['total_column'] and Settings['total_column'] in headers:
            totalCol = 1+headers.index(Settings['total_column'])
            self.totalCols = [ totalCol ]
            for j, header in enumerate(headers[totalCol:]):
                if header in ('q_scores', 'q_other') or QFIELD_RE.match(header):
                    self.totalCols.append(j+totalCol+1)
            self.totalColSet = set(self.totalCols)

    def update_total(self, rowNum):
        totalCol = self.totalCols[0]
        row = self.xrows[rowNum-1]     # Not a copy!

        if not row[self.keyCol-1]:
            # Only update totals for rows with keys
            row[totalCol-1] = ''
            return

        try:
            row[totalCol-1] = sum(row[j-1] for j in self.totalCols[1:] if row[j-1])
        except Exception, excp:
            row[totalCol-1] = ''

    def clear_update(self):
        for j, row in enumerate(self.xrows[1:]):
            key = row[self.keyCol-1] if self.keyCol else j+2
            if self.keyMap[key][1] or self.keyMap[key][2]:
                self.keyMap[key][1:3] = [0, set()]

    def copy(self):
        # Returns "shallow" copy
        return Sheet(self.name, self.xrows, keyHeader=self.keyHeader, modTime=self.modTime, accessTime=self.accessTime, keyMap=self.keyMap,
                     actions=self.actionsRequested, modifiedHeaders=self.modifiedHeaders)

    def expire(self):
        # Delete after any updates are processed
        self.holdSec = 0

    def requestActions(self, actions=''):
        # Actions to be carried after cache updates to this sheet are completed
        self.actionsRequested = actions
        need_update(self.name)

    def export(self, keepHidden=False, allUsers=False, csvFormat=False, idRename='', altidRename=''):
        headers = self.xrows[0][:]
        if idRename and 'id' in headers:
            headers[headers.index('id')] = idRename
        if altidRename and 'altid' in headers:
            headers[headers.index('altid')] = altidRename

        hideCols = []
        if not keepHidden:
            for k, header in enumerate(headers):
                if header.lower().endswith('hidden'):
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
                writer.writerow(row)
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
            self.keyMap[rowNum] = [modTime, 1, set()]

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

    def trimColumns(self, ncols):
        self.check_lock_status()
        if self.modifiedHeaders:
            raise Exception('Cannot trim columns now while updating sheet '+self.name)

        modTime = sliauth.epoch_ms()
        self.nCols -= ncols
        self.xrows[0] = self.xrows[0][:-ncols]
        for j in range(1, len(self.xrows)):
            self.xrows[j] = self.xrows[j][:-ncols]
            key = self.xrows[j][self.keyCol-1] if self.keyCol else j+1
            self.keyMap[key] = [modTime, 1, set()]  # Pretend all rows are newly "inserted", to force complete update

        self.update_total_formula()
        self.modifiedHeaders = True
        self.modifiedSheet(modTime)

    def checkRange(self, rowMin, colMin, rowCount, colCount):
        if rowMin < 1 or rowMin > len(self.xrows):
            raise Exception('Invalid min row number for range %s in sheet %s' % (rowMin, self.name))
        if rowCount < 0 or rowCount > len(self.xrows)-rowMin+1:
            raise Exception('Invalid row count for range %s in sheet %s' % (rowCount, self.name))

        if colMin < 1 or colMin > self.nCols:
            raise Exception('Invalid min col number for range %s in sheet %s' % (colMin, self.name))
        if colCount < 0 or colCount > self.nCols-colMin+1:
            raise Exception('Invalid col count for range %s in sheet %s' % (colCount, self.name))

    def getRange(self, rowMin, colMin, rowCount, colCount):
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
        if self.name == INDEX_SHEET and keyValue and Global.previewStatus and keyValue != Global.previewStatus['sessionName']:
            raise Exception('Cannot modify index values for non-previewed session '+keyValue+' when previewing session '+Global.previewStatus['sessionName'])
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
                keyValue = rowNum
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
                    totalCol = self.totalCols[0]
                    prevTotal = self.xrows[rowNum-1][totalCol-1]
                    self.update_total(rowNum)

                    if not self.keyMap[keyValue][1] and prevTotal != self.xrows[rowNum-1][totalCol-1]:
                        # Not inserting and total column updated
                        self.keyMap[keyValue][2].add(totalCol)

        if modTime:
            self.modifiedSheet(modTime)

    def modifiedSheet(self, modTime=None):
        self.modTime = sliauth.epoch_ms() if modTime is None else modTime
        self.accessTime = self.modTime
        need_update(self.name)

    def get_updates(self, row_limit=None):
        if Global.previewStatus and self.name in (Global.previewStatus['sessionName'], INDEX_SHEET):
            # Delay updates for preview session and index sheet
            return None

        actions = self.actionsRequested
            
        headers = self.xrows[0]
        nameCol = 1+headers.index('name') if 'name' in headers else 0

        updateKeys = []
        updateColSet = set()
        insertNames = []
        insertRows = []
        updateSel = []
        updateElemCount = 0

        colSet, colList, curUpdate = None, None, None
        allKeys = [row[self.keyCol-1] for row in self.xrows[1:] if row[self.keyCol-1]] if self.keyCol else None
        for j, row in enumerate(self.xrows[1:]):
            key = row[self.keyCol-1] if self.keyCol else j+2
            if not key:  # Do not update any non-key rows
                continue

            inserted = self.keyMap[key][1]
            newColSet = self.keyMap[key][2]

            if not inserted and not newColSet:
                # No updates for this unmodified row
                # (Note: this condition will not be true for rows whose updating was skipped due to request limits; see self.complete_update())
                colSet, colList, curUpdate = None, None, None
                continue

            if row_limit and (len(insertRows) >= row_limit or updateElemCount >= 10*row_limit):
                # Update request limit reached, with at least one update left; delay any actions
                actions = ''
                break

            # Update (non-insert) key
            updateKeys.append(key)

            if Global.updatePartial and self.keyCol and not inserted:
                # Partial update
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
                # Full/insertion updates
                colSet, colList, curUpdate = None, None, None
                if inserted:
                    # Insert row
                    insertNames.append( [row[nameCol-1] if nameCol else '', key] )
                    insertRows.append( row )
                else:
                    # Non-partial or non-keyed; update full rows
                    updateSel.append([key], None, [row])

        if not insertRows and not updateSel and not actions and not self.modifiedHeaders:
            # No updates
            return None

        # Send updateColList if non-null and non-full row
        updateColList = sorted(list(updateColSet)) if (updateColSet and len(updateColSet) < self.nCols) else None

        return [updateKeys, actions, self.modifiedHeaders, headers, allKeys, insertNames, updateColList, insertRows, updateSel]
                    
    def complete_update(self, updateKeys, actions, modifiedHeaders):
        # Update sheet status after remote update has completed
        if actions and actions == self.actionsRequested:
            self.actionsRequested = ''

        if modifiedHeaders:
            self.modifiedHeaders = False

        updateKeySet = set(updateKeys)
        for j, row in enumerate(self.xrows[1:]):
            key = row[self.keyCol-1] if self.keyCol else j+2

            if key in updateKeySet:
                # Row update completed
                # (Note: Rows that were not updated due request limits being reached will not be subject to this reset)
                self.keyMap[key][1:3] = [0, set()]


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

def getCacheStatus():
    out = 'Cache: version %s (%s)\n' % (VERSION, list(Global.remoteVersions))
    if Global.cacheUpdateError:
        out += '  ERROR in last cache update: <b>%s</b>\n' % Global.cacheUpdateError
        
    out += '  Suspend status: <b>%s</b>\n' % Global.suspended
    out += '  No. of updates (retries): %d (%d)\n' % (Global.totalCacheResponseCount, Global.totalCacheRetryCount)
    out += '  Average update time = %.2fs\n\n' % (Global.totalCacheResponseInterval/(1000*max(1,Global.totalCacheResponseCount)) )
    out += '  Average request bytes = %d\n\n' % (Global.totalCacheRequestBytes/max(1,Global.totalCacheResponseCount) )
    out += '  Average response bytes = %d\n\n' % (Global.totalCacheResponseBytes/max(1,Global.totalCacheResponseCount) )
    curTime = sliauth.epoch_ms()
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
            sheetStr = '<a href="/_%s/%s">%s</a> %s' % (action, sheetName, action, Lock_cache.get(sheetName,''))
    
        accessTime = str(int((curTime-sheet.accessTime)/1000.))+'s' if sheet else '(not cached)'
        out += 'Sheet_cache: %s: %s %s\n' % (sheetName, accessTime, sheetStr)
    out += '\n'
    for sheetName in Miss_cache:
        out += 'Miss_cache: %s: %ds\n' % (sheetName, (curTime-Miss_cache[sheetName])/1000.)
    out += '\n'
    return out

def lockSheet(sheetName, lockType='user'):
    # Returns True if lock is immediately effective; False if it will take effect later
    if sheetName == Global.previewStatus.get('sessionName'):
        return False
    if sheetName not in Lock_cache and not isReadOnly(sheetName):
        Lock_cache[sheetName] = lockType
    if sheetName in Sheet_cache and Sheet_cache[sheetName].get_updates() is not None:
        return False
    return True

def unlockSheet(sheetName):
    # Unlock and refresh sheet (if no updates pending)
    if sheetName == Global.previewStatus.get('sessionName'):
        return False
    if sheetName in Sheet_cache and Sheet_cache[sheetName].get_updates() is not None:
        return False
    delSheet(sheetName)
    return True

def expireSheet(sheetName):
    # Expire sheet from cache (delete after any updates are processed)
    if sheetName == Global.previewStatus.get('sessionName'):
        return
    sheet = Sheet_cache.get(sheetName)
    if sheet:
        sheet.expire()

def refreshSheet(sheetName):
    # Refresh sheet, if unlocked (after any updates)
    if sheetName == Global.previewStatus.get('sessionName'):
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
    if Settings['lock_proxy_url'] and sheetName.endswith('_slidoc') and not get:
        raise Exception('Only get operation allowed for special sheet '+sheetName+' in locked proxy mode')

    if sheetName in Lock_cache:
        raise Exception('Sheet %s is locked!' % sheetName)

    if get and backup and Global.suspended == 'backup':
        return True

    if get and cached and Global.suspended == 'freeze':
        return True

    if Global.suspended:
        raise Exception('Cannot access sheet %s when suspended (%s)' % (sheetName, Global.suspended))

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

def need_update(sheetName):
    # Schedule an update if one not already scheduled
    if Global.cachePendingUpdate:
        return
    Global.cachePendingUpdate = IOLoop.current().add_callback(update_remote_sheets)

def schedule_update(waitSec=0, force=False, synchronous=False):
    if Global.cachePendingUpdate:
        IOLoop.current().remove_timeout(Global.cachePendingUpdate)
        Global.cachePendingUpdate = None

    if waitSec and not force:
        Global.cachePendingUpdate = IOLoop.current().call_later(waitSec, update_remote_sheets)
    else:
        update_remote_sheets(force=True, synchronous=synchronous)

def suspend_cache(action="shutdown"):
    if Global.suspended == "freeze" and action != "clear":
        raise Exception("Must clear after freeze")

    Global.suspended = action
    if action == "shutdown":
        schedule_update(force=True, synchronous=True)
    elif action:
        print("Suspended for", action, file=sys.stderr)
        schedule_update(force=True)

def shutdown_loop():
    print("Completed IO loop shutdown", file=sys.stderr)
    IOLoop.current().stop()

def sheet_proxy_error(errMsg=''):
    Global.cacheUpdateError = sliauth.iso_date(nosubsec=True) + ': ' + errMsg
    print('sheet_proxy_error: '+errMsg, file=sys.stderr)

def proxy_error_status():
    return Global.cacheUpdateError
        
def updates_current():
    if not Global.suspended:
        return

    if Global.suspended == "freeze":
        return

    if Global.suspended == "clear":
        initCache()
        print("Cleared cache", file=sys.stderr)
    elif Global.suspended == "shutdown":
        if not Global.shuttingDown:
            Global.shuttingDown = True
            IOLoop.current().add_callback(shutdown_loop)
    elif Global.suspended == "reload":
        try:
            os.utime(scriptdir+'/reload.py', None)
            print("Reloading...", file=sys.stderr)
        except Exception, excp:
            print("Reload failed: "+str(excp), file=sys.stderr)
    elif Global.suspended == "update":
        try:
            if os.environ.get('SUDO_USER'):
                cmd = ["sudo", "-u", os.environ['SUDO_USER'], "git", "pull"]
            else:
                cmd = ["git", "pull"]
            print("Updating: %s" % cmd, file=sys.stderr)
            subprocess.check_call(cmd, cwd=scriptdir)
        except Exception, excp:
            print("Updating via git pull failed: "+str(excp), file=sys.stderr)

def update_remote_sheets(force=False, synchronous=False):
    try:
        # Need to trap exception because it fails silently otherwise
        return update_remote_sheets_aux(force=force, synchronous=synchronous)
    except Exception, excp:
        sheet_proxy_error('Unexpected error in update_remote_sheets: %s' % excp)

def update_remote_sheets_aux(force=False, synchronous=False):
    if not Settings['gsheet_url'] or Settings['dry_run']:
        # No updates if no sheet URL or dry run
        Global.cacheUpdateTime = sliauth.epoch_ms()
        for sheetName, sheet in Sheet_cache.items():
            sheet.clear_update()
        updates_current()
        return

    if Global.cacheUpdateError or (Global.httpRequestId and not synchronous):
        # Request currently active/disabled
        # (synchronous request will supersede any active previous request)
        return

    curTime = sliauth.epoch_ms()
    if not force and not synchronous and (curTime - Global.cacheResponseTime) < 1000*Settings['min_wait_sec']:
        schedule_update(curTime-Global.cacheResponseTime)
        return

    specialMods = []
    sessionMods = []
    sheetUpdateInfo = {}
    for sheetName, sheet in Sheet_cache.items():
        # Check each cached sheet for updates
        updates = sheet.get_updates(row_limit=PROXY_UPDATE_ROW_LIMIT)
        if updates is None:
            if curTime-sheet.accessTime > 1000*sheet.holdSec and previewingSession() != sheetName:
                # Cache entry has expired
                del Sheet_cache[sheetName]
            continue

        # sheet_name, actions, modified_headers, headers_list, all_keys, insert_names_keys, update_cols_list or None, insert_rows, modified_rows
        sheetUpdateInfo[sheetName] = updates[0:3]
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

    if Settings['debug']:
        print("update_remote_sheets_aux: REQUEST %s partial=%s, log=%s, nsheets=%d, ndata=%d" % (sliauth.iso_date(nosubsec=True), Global.updatePartial, Settings['log_call'], len(modRequests), len(json_data)), file=sys.stderr)

    ##if Settings['debug']:
    ##    print("update_remote_sheets_aux: REQUEST2", [(x[0], x[4:]) for x in modRequests], file=sys.stderr)

    proxy_updater = ProxyUpdater(sheetUpdateInfo, json_data, synchronous=synchronous)
    proxy_updater.update(curTime)


class ProxyUpdater(object):
    def __init__(self, sheetUpdateInfo, json_data, synchronous=False):
        self.sheetUpdateInfo = sheetUpdateInfo
        self.json_data = json_data
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

        if Settings['debug']:
            print("ProxyUpdater.update: UPDATE requestid=%s, retry=%d" % (Global.httpRequestId, self.cacheRetryCount), file=sys.stderr)

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
            sheet_proxy_error('Unexpected error in handle_proxy_response: %s' % excp)

    def handle_proxy_response_aux(self, response):
        if self.requestId != Global.httpRequestId:
            # Cache has been cleared since update request; ignore response
            print("ProxyUpdater.handle_proxy_response_aux: DROPPED response to update request %s" % self.requestId, file=sys.stderr)
            return

        errMsg = ''
        errTrace = ''
        respObj = None
        if response.error:
            errMsg = str(response.error)  # Need to convert to string for later use
        else:
            try:
                respObj = json.loads(response.body)
                if respObj['result'] == 'error':
                    errMsg = respObj['error']
                    errTrace = respObj.get('errtrace','')
            except Exception, err:
                errMsg = 'JSON parsing error: '+str(err)

            if Settings['debug']:
                cachedResp = respObj['info'].get('cachedResponse', '') if respObj else ''
                print("handle_proxy_response_aux: Update RESPONSE", sliauth.iso_date(nosubsec=True), cachedResp, errMsg, response.body[:256]+'\n', errTrace, file=sys.stderr)

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

            print("ProxyUpdater.handle_proxy_response_aux: Update ERROR (tries %d of %d; retry_after=%ss): %s" % (self.cacheRetryCount, RETRY_MAX_COUNT, self.cacheWaitTime, errMsg), file=sys.stderr)

            # Retry same request after some time
            IOLoop.current().call_later(self.cacheWaitTime, self.async_fetch)
            return

        # Update request succeeded
        Global.cacheUpdateTime = self.cacheRequestTime
        Global.cacheResponseTime = sliauth.epoch_ms()

        Global.totalCacheResponseInterval += (Global.cacheResponseTime - self.cacheRequestTime)
        Global.totalCacheResponseCount += 1
        Global.totalCacheResponseBytes += len(response.body)

        for sheetName, sheet in Sheet_cache.items():
            if sheetName in self.sheetUpdateInfo:
                sheet.complete_update(*self.sheetUpdateInfo[sheetName])

        for sheetName in respObj['info'].get('refreshSheets',[]):
            refreshSheet(sheetName)

        for errSessionName, proxyErrMsg, proxyErrTrace in respObj['info'].get('updateErrors',[]):
            Lock_cache[errSessionName] = proxyErrMsg
            print("ProxyUpdater.handle_proxy_response_aux: Update LOCKED %s: %s %s" % (errSessionName, proxyErrMsg, proxyErrTrace), file=sys.stderr)

        if Settings['debug']:
            print("ProxyUpdater.handle_proxy_response_aux: UPDATED", sliauth.iso_date(nosubsec=True), respObj, file=sys.stderr)

        next_cache_update(0 if Global.suspended else Settings['min_wait_sec'])

def next_cache_update(waitSec=0, resetError=False):
    if resetError:
        Global.cacheUpdateError = ''
    Global.httpRequestId = ''
    schedule_update(waitSec)
        

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

    if Settings['debug'] and not notrace:
        print("DEBUG: sheetAction PARAMS", params.get('sheet'), params.get('id'), file=sys.stderr)

    returnValues = None
    returnHeaders = None
    returnInfo = {'version': VERSION}
    returnMessages = []

    try:
        sheetName = params.get('sheet','')
        if not sheetName:
            raise Exception('Error:SHEETNAME:No sheet name specified')

        returnInfo['sheet'] = sheetName

        freezeDate = createDate(Settings['freeze_date']) or None
        
        origUser = ''
        adminUser = ''
        readOnlyAccess = False

        paramId = params.get('id','')
        authToken = params.get('token', '')

        if ':' in authToken:
            comps = authToken.split(':')   # effectiveId:userid:role:sites:hmac
            if len(comps) != 5:
                raise Exception('Error:INVALID_TOKEN:Invalid auth token format '+authToken);
            subToken = ':' + ':'.join(comps[1:])
            if not validateHMAC(subToken, Settings['auth_key']):
                raise Exception('Error:INVALID_TOKEN:Invalid authentication token '+subToken)

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

        elif Settings['require_login_token']:
            if not authToken:
                raise Exception('Error:NEED_TOKEN:Need token for id authentication')
            if not paramId:
                raise Exception('Error:NEED_ID:Need id for authentication')
            if not validateHMAC(sliauth.gen_auth_prefix(paramId,'','')+':'+authToken, Settings['auth_key']):
                raise Exception('Error:INVALID_TOKEN:Invalid token '+authToken+' for authenticating id '+paramId)
            origUser = paramId

        # Read-only sheets
        protectedSheet = (sheetName.endswith('_slidoc') and sheetName != ROSTER_SHEET and sheetName != INDEX_SHEET) or sheetName.endswith('-answers') or sheetName.endswith('-stats')
        # Admin-only access sheets (ROSTER_SHEET modifications will be restricted later)
        restrictedSheet = (sheetName.endswith('_slidoc') and sheetName != ROSTER_SHEET and sheetName != SCORES_SHEET)

        loggingSheet = sheetName.endswith('_log')
        discussionSheet = sheetName.endswith('-discuss')

        performActions = params.get('actions', '')
        if performActions:
            if performActions == 'discuss_posts':
                returnValues = getDiscussPosts(sheetName, params.get('slide', ''), paramId)
                return {"result": "success", "value": returnValues, "headers": returnHeaders,
                        "info": returnInfo, "messages": '\n'.join(returnMessages)}
            else:
                raise Exception('Error:ACTION:Actions %s not supported by proxy' % performActions)

        sessionEntries = None
        sessionAttributes = None
        questions = None
        paceLevel = None
        adminPaced = None
        dueDate = None
        gradeDate = None
        timedSec = None
        voteDate = None
        discussableSession = None
        computeTotalScore = False
        curDate = createDate()
        curTime = sliauth.epoch_ms(curDate)

        if sheetName == SETTINGS_SHEET and adminUser != ADMIN_ROLE:
            raise Exception('Error::Must be admin user to access settings')

        if restrictedSheet and not adminUser:
            raise Exception("Error::Must be admin/grader user to access sheet '"+sheetName+"'")

        rosterValues = []
        rosterSheet = getSheet(ROSTER_SHEET, optional=True)
        if rosterSheet and not adminUser:
            # Check user access
            if not paramId:
                raise Exception('Error:NEED_ID:Must specify userID to lookup roster')
            # Copy user info from roster
            rosterValues = getRosterEntry(paramId)

        returnInfo['prevTimestamp'] = None
        returnInfo['timestamp'] = None
        processed = False

        if params.get('delsheet'):
            # Delete sheet (and session entry)
            processed = True
            returnValues = []
            if not adminUser:
                raise Exception("Error:DELSHEET:Only admin can delete sheet "+sheetName)
            if sheetName.endswith('_slidoc'):
                raise Exception("Error:DELSHEET:Cannot delete special sheet "+sheetName)
            indexSheet = getSheet(INDEX_SHEET, optional=True)
            if indexSheet:
                # Delete session entry
                delRowCol = lookupRowIndex(sheetName, indexSheet, 2)
                if delRowCol:
                    indexSheet.deleteRow(delRowCol)

            delSheet(sheetName)
                    
            if Settings['gsheet_url'] and not Settings['dry_run']:
                user = ADMINUSER_ID
                userToken = gen_proxy_token(user, ADMIN_ROLE)
                delParams = {'sheet': sheetName, 'delsheet': '1', 'admin': user, 'token': userToken}
                retval = sliauth.http_post(Settings['gsheet_url'], delParams)
                print('sdproxy: delsheet %s: %s' % (sheetName, retval), file=sys.stderr)
                if retval['result'] != 'success':
                    return retval

        elif params.get('copysheet'):
            # Copy sheet (but not session entry)
            processed = True
            returnValues = []
            if not adminUser:
                raise Exception("Error:COPYSHEET:Only admin can copy sheet "+sheetName)
            modSheet = getSheet(sheetName, optional=True)
            if not modSheet:
                raise Exception("Error:COPYSHEET:Source sheet "+sheetName+" not found!")

            newName = params.get('copysheet')
            indexSheet = getSheet(INDEX_SHEET, optional=True)
            if indexSheet:
                newRowCol = lookupRowIndex(newName, indexSheet, 2)
                if newRowCol:
                    raise Exception("Error:COPYSHEET:Destination session entry "+newName+" already exists!")

            if newName in Sheet_cache or getSheet(newName, optional=True):
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

            modSheet = getSheet(sheetName, optional=True)
            if not modSheet:
                if adminUser and headers is not None:
                    modSheet = createSheet(sheetName, headers)
                else:
                    raise Exception("Error:NOSHEET:Sheet '"+sheetName+"' not found")

            if not modSheet.getLastColumn():
                raise Exception("Error::No columns in sheet '"+sheetName+"'")

            if not restrictedSheet and not protectedSheet and not loggingSheet and not discussionSheet and sheetName != ROSTER_SHEET and getSheet(INDEX_SHEET):
                # Indexed session
                sessionEntries = lookupValues(sheetName, ['dueDate', 'gradeDate', 'paceLevel', 'adminPaced', 'scoreWeight', 'gradeWeight', 'otherWeight', 'fieldsMin', 'questions', 'attributes'], INDEX_SHEET)
                sessionAttributes = json.loads(sessionEntries['attributes'])
                questions = json.loads(sessionEntries['questions'])
                paceLevel = sessionEntries.get('paceLevel')
                adminPaced = sessionEntries.get('adminPaced')
                dueDate = sessionEntries.get('dueDate')
                gradeDate = sessionEntries.get('gradeDate')
                timedSec = sessionAttributes['params'].get('timedSec')
                voteDate = createDate(sessionAttributes['params']['plugin_share_voteDate']) if sessionAttributes['params'].get('plugin_share_voteDate') else None
                discussableSession = sessionAttributes.get('discussSlides') and len(sessionAttributes['discussSlides'])

                if parseNumber(sessionEntries.get('scoreWeight')):
                    # Compute total score?
                    if sessionAttributes['params']['features'].get('delay_answers') or sessionAttributes['params']['features'].get('remote_answers'):
                        # Delayed or remote answers; compute total score only after grading
                        computeTotalScore = gradeDate
                    else:
                        computeTotalScore = True

            # Check parameter consistency
            getRow = params.get('get','')
            getShare = params.get('getshare', '')
            allRows = params.get('all','')
            createRow = params.get('create', '')
            seedRow = params.get('seed', None) if adminUser else None
            nooverwriteRow = params.get('nooverwrite','')
            delRow = params.get('delrow','')
            resetRow = params.get('resetrow','')
            importSession = params.get('import','')

            columnHeaders = modSheet.getSheetValues(1, 1, 1, modSheet.getLastColumn())[0]
            columnIndex = indexColumns(modSheet)

            selectedUpdates = json.loads(params.get('update','')) if params.get('update','') else None
            rowUpdates = json.loads(params.get('row','')) if params.get('row','') else None

            modifyingRow = delRow or resetRow or selectedUpdates or (rowUpdates and not nooverwriteRow)
            if modifyingRow:
                if readOnlyAccess:
                    raise Exception('Error::Admin user '+origUser+' cannot modify row for user '+paramId)
                if adminUser:
                    # Refresh cached gradebook (because scores/grade may be updated)
                    refreshSheet(SCORES_SHEET)
                
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

                        modSheet.trimColumns( nCols )
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
                if updateTotalScores(modSheet, sessionAttributes, questions, True) and not Settings['dry_run']:
                    modSheet.requestActions('answer_stats,gradebook,correct')

            userId = None
            displayName = None

            voteSubmission = ''
            alterSubmission = False
            twitterSetting = False
            discussionPost = None
            if not rowUpdates and selectedUpdates and len(selectedUpdates) == 2 and selectedUpdates[0][0] == 'id':
                if selectedUpdates[1][0].endswith('_vote') and sessionAttributes.get('shareAnswers'):
                    qprefix = selectedUpdates[1][0].split('_')[0]
                    voteSubmission = sessionAttributes['shareAnswers'][qprefix].get('share', '') if sessionAttributes['shareAnswers'].get(qprefix) else ''

                if sheetName.endswith('-discuss') and selectedUpdates[1][0].startswith('discuss'):
                    discussionPost = [sheetName[:-len('-discuss')], int(selectedUpdates[1][0][len('discuss'):])]

                if selectedUpdates[1][0] == 'submitTimestamp':
                    alterSubmission = True

                if selectedUpdates[1][0] == 'twitter' and sheetName == ROSTER_SHEET:
                    twitterSetting = True

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
                    if temIndexRow.get(MAXSCORE_ID):
                        returnInfo['maxScores'] = modSheet.getSheetValues(temIndexRow.get(MAXSCORE_ID), 1, 1, len(columnHeaders))[0]
                    if temIndexRow.get(RESCALE_ID):
                        returnInfo['rescale'] = modSheet.getSheetValues(temIndexRow.get(RESCALE_ID), 1, 1, len(columnHeaders))[0]
                    if Settings.get('share_averages') and temIndexRow.get(AVERAGE_ID):
                        returnInfo['averages'] = modSheet.getSheetValues(temIndexRow.get(AVERAGE_ID), 1, 1, len(columnHeaders))[0]
                    # TODO: Need to implement retrieving settings from settings_slidoc
                except Exception, err:
                    pass

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
                if columnIndex.get('lastSlide'):
                    returnInfo['maxLastSlide'] = getColumnMax(modSheet, 2, columnIndex['lastSlide'])
                if computeTotalScore:
                    returnInfo['remoteAnswers'] = sessionAttributes.get('remoteAnswers')
        elif getShare:
            # Return adjacent columns (if permitted by session index and corresponding user entry is non-null)
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
                answerSheet = getSheet(sheetName+'-answers', optional=True)
                if not answerSheet:
                    raise Exception('Error::Sharing not possible without answer sheet '+sheetName+'-answers')
                ansColumnHeaders = answerSheet.getSheetValues(1, 1, 1, answerSheet.getLastColumn())[0]
                ansCol = 0
                for j in range(len(ansColumnHeaders)):
                    if ansColumnHeaders[j][:len(getShare)+1] == getShare+'_':
                        ansCol = j+1
                        break
                if not ansCol:
                    raise Exception('Error::Column '+getShare+'_* not present in headers for answer sheet '+sheetName+'-answers')
                returnHeaders = [ getShare+'_response' ]
                nRows = answerSheet.getLastRow()-1
                names = answerSheet.getSheetValues(2, 1, nRows, 1)
                values = answerSheet.getSheetValues(2, ansCol, nRows, 1)
                returnValues = []
                for j in range(len(values)):
                    if names[j][0] and names[j][0][0] != '#' and values[j][0]:
                        returnValues.append(values[j][0])
                returnValues.sort()
            else:
                nRows = modSheet.getLastRow()-numStickyRows
                respCol = getShare+'_response'
                respIndex = columnIndex.get(getShare+'_response')
                if not respIndex:
                    raise Exception('Error::Column '+respCol+' not present in headers for session '+sheetName)

                explainOffset = 0
                shareOffset = 1
                nCols = 2
                if columnIndex.get(getShare+'_explain') == respIndex+1:
                    explainOffset = 1
                    shareOffset = 2
                    nCols += 1

                voteOffset = 0
                if shareParams.get('vote') and columnIndex.get(getShare+'_vote') == respIndex+nCols:
                    voteOffset = shareOffset+1
                    nCols += 1

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
                for j in range(nRows):
                    if shareSubrow[j][0] == SKIP_ANSWER:
                        shareSubrow[j][0] = ''
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
                curUserResponded = curUserVals and curUserVals[0] and (not explainOffset or curUserVals[explainOffset])

                if not adminUser and paramId != TESTUSER_ID:
                    if paceLevel == ADMIN_PACE and (not testUserVals or (not testUserVals[0] and not testUserSubmitted)):
                        raise Exception('Error::Instructor must respond to question '+getShare+' before sharing in session '+sheetName)

                    if shareParams.get('share') == 'after_answering' and not curUserResponded and not curUserSubmitted:
                        raise Exception('Error::User '+paramId+' must respond to question '+getShare+' before sharing in session '+sheetName)

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
                    if not shareSubrow[j][0] or lateValues[j][0] == LATE_SUBMIT:
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

                    respVal = shareSubrow[j][0]
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
                    nameMap = lookupRoster('name', userId=None)
                    if not nameMap:
                        nameMap = {}
                        for j in range(nRows):
                            nameMap[idValues[j][0]] = nameValues[j][0]
                    nameMap = makeShortNames(nameMap)
                    returnInfo['responders'] = []
                    if teamAttr == 'setup':
                        teamMembers = {}
                        for j in range(nRows):
                            idValue = idValues[j][0]
                            if nameMap and nameMap.get(idValue):
                                name = nameMap[idValue]
                            else:
                                name = idValue
                            teamName = shareSubrow[j][0]
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
                        for j in range(nRows):
                            idValue = idValues[j][0]
                            if not includeId.get(idValue):
                                continue
                            if responderTeam.get(idValue):
                                returnInfo['responders'].append(responderTeam[idValue])
                            elif nameMap and nameMap.get(idValue):
                                returnInfo['responders'].append(nameMap[idValue])
                            else:
                                returnInfo['responders'].append(idValue)
                    returnInfo['responders'].sort()

                ##returnMessages.append('Debug::getShare: '+str(nCols)+', '+str(nRows)+', '+str(sortVals)+', '+str(curUserVals)+'')
                returnValues = []
                for x, y, j in sortVals:
                    returnValues.append( shareSubrow[j] )

        else:
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

            ##returnMessages.append('Debug::userRow, userid, rosterValues: '+userRow+', '+userId+', '+rosterValues)
            newRow = (not userRow)

            if (readOnlyAccess or adminUser) and not restrictedSheet and newRow and userId != MAXSCORE_ID and not importSession:
                raise Exception("Error::Admin user not allowed to create new row in sheet '"+sheetName+"'")

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
                    savedSession = unpackSession(columnHeaders, origVals)
                    if savedSession and savedSession.get('questionsAttempted') and computeTotalScore:
                        scores = tallyScores(questions, savedSession['questionsAttempted'], savedSession['hintsUsed'], sessionAttributes['params'], sessionAttributes['remoteAnswers'])
                        lastTake = str(scores.get('weightedCorrect') or 0)
                    else:
                        lastTake = '0'

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

            elif newRow and (not rowUpdates) and createRow:
                # Initialize new row
                if sessionEntries:
                    rowUpdates = createSessionRow(sheetName, sessionEntries['fieldsMin'], sessionAttributes['params'], questions,
                                                  userId, params.get('name', ''), params.get('email', ''), params.get('altid', ''),
                                                  createRow, seedRow)
                    displayName = rowUpdates[columnIndex['name']-1] or ''
                    if params.get('late') and columnIndex.get('lateToken'):
                        rowUpdates[columnIndex['lateToken']-1] = params['late']
                else:
                    rowUpdates = []
                    for j in range(len(columnHeaders)):
                        rowUpdates.append(None)
                    if sheetName.endswith('-discuss'):
                        displayName = params.get('name', '')
                        rowUpdates[columnIndex['id']-1] = userId
                        rowUpdates[columnIndex['name']-1] = displayName
                        
            if newRow or rowUpdates or selectedUpdates:
                # Modifying sheet
                if Global.cacheUpdateError:
                    raise Exception('Error::All sessions are frozen due to cache update error: '+Global.cacheUpdateError);
                elif not adminUser and freezeDate and sliauth.epoch_ms(curDate) > sliauth.epoch_ms(freezeDate):
                    raise Exception('Error::All sessions are frozen. No user modifications permitted');
                        
            teamCol = columnIndex.get('team')
            if newRow and rowUpdates and teamCol and sessionAttributes and sessionAttributes.get('sessionTeam') == 'roster':
                # Copy team name from roster
                teamName = lookupRoster('team', userId)
                if teamName:
                    rowUpdates[teamCol-1] = teamName

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

                            if lateToken and ':' in lateToken:
                                # Check against new due date
                                newDueDate = getNewDueDate(userId, Settings['site_name'], sheetName, lateToken)
                                if not newDueDate:
                                    raise Exception("Error:INVALID_LATE_TOKEN:Invalid token '"+lateToken+"' for late submission by user "+(displayName or "")+" to session '"+sheetName+"'")

                                dueDate = newDueDate
                                pastSubmitDeadline = curTime > sliauth.epoch_ms(dueDate)

                        returnInfo['dueDate'] = dueDate # May have been updated

                        allowLateMods = adminUser or importSession or not Settings['require_late_token'] or lateToken == LATE_SUBMIT
                        if not allowLateMods:
                            if pastSubmitDeadline:
                                if getRow and not (newRow or rowUpdates or selectedUpdates):
                                    # Reading existing row; force submit
                                    autoSubmission = True
                                    selectedUpdates = [ ['id', userId], ['Timestamp', None], ['submitTimestamp', None] ]
                                    returnMessages.append("Warning:FORCED_SUBMISSION:Forced submission for user '"+(displayName or "")+"' to session '"+sheetName+"'")
                                else:
                                    # Creating/modifying row
                                    raise Exception("Error:PAST_SUBMIT_DEADLINE:Past submit deadline ("+str(dueDate)+") for session "+sheetName)
                            elif (sliauth.epoch_ms(dueDate) - curTime) < 2*60*60*1000:
                                returnMessages.append("Warning:NEAR_SUBMIT_DEADLINE:Nearing submit deadline ("+str(dueDate)+") for session "+sheetName)

                numRows = modSheet.getLastRow()
                if newRow and not resetRow:
                    # New user; insert row in sorted order of name (except for log files)
                    if (userId != MAXSCORE_ID and not displayName) or not rowUpdates:
                        raise Exception('Error::User name and row parameters required to create a new row for id '+userId+' in sheet '+sheetName)

                    if userId == MAXSCORE_ID:
                        userRow = numStickyRows+1
                    elif userId == TESTUSER_ID and not loggingSheet:
                        # Test user always appears after max score
                        maxScoreRow = lookupRowIndex(MAXSCORE_ID, modSheet, numStickyRows+1)
                        userRow = maxScoreRow+1 if maxScoreRow else numStickyRows+1
                    elif numRows > numStickyRows and not loggingSheet:
                        displayNames = modSheet.getSheetValues(1+numStickyRows, columnIndex['name'], numRows-numStickyRows, 1)
                        userIds = modSheet.getSheetValues(1+numStickyRows, columnIndex['id'], numRows-numStickyRows, 1)
                        userRow = numStickyRows + locateNewRow(displayName, userId, displayNames, userIds, TESTUSER_ID)
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
                    raise Exception('Error::Row timestamp too old by '+str(math.ceil(returnInfo['prevTimestamp']-parseNumber(params.get('timestamp','')))/1000)+' seconds. Conflicting modifications from another active browser session?')

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
                                if teamAttr == 'setup':
                                    if hmatch.group(2) == 'response' and colValue != SKIP_ANSWER:
                                        # Set up team name (capitalized)
                                        rowValues[teamCol-1] = safeName(colValue, True)
                                        returnInfo['team'] = rowValues[teamCol-1]
                                elif teamAttr == 'response' and rowValues[teamCol-1]:
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
                        # Tally user scores
                        savedSession = unpackSession(columnHeaders, rowValues)
                        if savedSession and len(savedSession.get('questionsAttempted').keys()):
                            scores = tallyScores(questions, savedSession.get('questionsAttempted'), savedSession.get('hintsUsed'), sessionAttributes.get('params'), sessionAttributes.get('remoteAnswers'))
                            rowValues[scoresCol-1] = scores.get('weightedCorrect', '')

                    # Copy user info from roster (if available)
                    for j in range(len(rosterValues)):
                        rowValues[j] = rosterValues[j]

                    # Save updated row
                    userRange.setValues([rowValues])

                    if userId == MAXSCORE_ID and not Settings['total_column']:
                        # Refresh sheet cache if max score row is updated (for re-computed totals)
                        modSheet.expire()
                        expireSheet(SCORES_SHEET)

                    discussRowOffset = 2
                    discussNameCol = 1
                    discussIdCol = 2
                    if sessionEntries and adminPaced and paramId == TESTUSER_ID:
                        # AdminPaced test user row update
                        lastSlideCol = columnIndex.get('lastSlide')
                        if lastSlideCol and rowValues[lastSlideCol-1]:
                            # Copy test user last slide number as new adminPaced value
                            adminPaced = rowValues[lastSlideCol-1]
                            setValue(sheetName, 'adminPaced', adminPaced, INDEX_SHEET)

                        if params.get('submit'):
                            # Use test user submission time as due date for admin-paced sessions
                            submitTimestamp = rowValues[submitTimestampCol-1]
                            setValue(sheetName, 'dueDate', submitTimestamp, INDEX_SHEET)

                            discussSheet = None
                            discussRowCount = 0
                            if discussableSession:
                                # Create discussion sheet
                                discussHeaders = ['name', 'id']
                                discussRow = ['', DISCUSS_ID]
                                for j in range(len(sessionAttributes['discussSlides'])):
                                    slideNum = sessionAttributes['discussSlides'][j]
                                    discussHeaders.append('access%03d' % slideNum)
                                    discussHeaders.append('discuss%03d' % slideNum)
                                    discussRow.append(0)
                                    discussRow.append('')
                                discussSheet = createSheet(sheetName+'-discuss', discussHeaders)
                                discussSheet.insertRowBefore(2, keyValue=DISCUSS_ID)
                                discussSheet.getRange(2, 1, 1, len(discussRow)).setValues([discussRow])
                                discussRowCount = discussRowOffset

                            idRowIndex = indexRows(modSheet, columnIndex['id'])
                            idColValues = getColumns('id', modSheet, 1, 1+numStickyRows)
                            nameColValues = getColumns('name', modSheet, 1, 1+numStickyRows)
                            initColValues = getColumns('initTimestamp', modSheet, 1, 1+numStickyRows)
                            for j in range(len(idColValues)):
                                # Submit all other users who have started a session
                                if initColValues[j] and idColValues[j] and idColValues != TESTUSER_ID and idColValues[j] != MAXSCORE_ID:
                                    modSheet.getRange(idRowIndex[idColValues[j]], submitTimestampCol, 1, 1).setValues([[submitTimestamp]])

                                    if discussSheet:
                                        # Add submitted user to discussion sheet
                                        discussRowCount += 1
                                        discussSheet.insertRowBefore(discussRowCount, keyValue=idColValues[j])
                                        discussSheet.getRange(discussRowCount, discussNameCol, 1, 1).setValues([[nameColValues[j]]])

                    elif sessionEntries and adminPaced and dueDate and discussableSession and params.get('submit'):
                        discussSheet = getSheet(sheetName+'-discuss', optional=True)
                        if discussSheet:
                            discussRows = discussSheet.getLastRow()
                            discussNames = discussSheet.getSheetValues(1+discussRowOffset, discussNameCol, numRows-discussRowOffset, 1)
                            discussIds = discussSheet.getSheetValues(1+discussRowOffset, discussIdCol, numRows-discussRowOffset, 1)
                            temRow = discussRowOffset + locateNewRow(displayName, userId, discussNames, discussIds, DISCUSS_ID)
                            discussSheet.insertRowBefore(temRow, keyValue=userId)
                            discussSheet.getRange(temRow, discussNameCol, 1, 1).setValues([[displayName]])
                            
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
                                    # Unsubmit if blank value (also clear lateToken and due date, if admin paced)
                                    modValue = ''
                                    modSheet.getRange(userRow, columnIndex['lateToken'], 1, 1).setValues([[ '' ]])
                                    if sessionEntries and adminPaced and paramId == TESTUSER_ID:
                                        setValue(sheetName, 'dueDate', '', INDEX_SHEET)
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
                                userPosts = ('\n'+prevValue).split('\nPost:')[1:]
                                deleteLabel = '%03d:' % int(colValue[len('delete:'):])
                                for j in range(len(userPosts)):
                                    if userPosts[j].startswith(deleteLabel):
                                        # "Delete" post by prefixing it with (deleted)
                                        comps = userPosts[j].split(' ')
                                        userPosts[j] = comps[0]+' '+DELETED_POST+' '+' '.join(comps[1:])
                                        modValue = 'Post:' + '\nPost:'.join(userPosts)
                                        break
                            else:
                                # New post
                                discussRow = lookupRowIndex(DISCUSS_ID, modSheet)
                                if not discussRow:
                                    raise Exception('Row with id %s not found in sheet %s' % (DISCUSS_ID, sheetName))

                                # Update post count and last post time
                                axsHeader = 'access%03d' % discussionPost[1]
                                axsColumn = columnIndex[axsHeader]

                                axsRange = modSheet.getRange(discussRow, axsColumn, 1, 1)

                                postCount = (axsRange.getValues()[0][0] or 0) + 1
                                axsRange.setValues([[ postCount ]])

                                modValue = prevValue + '\n' if prevValue else ''
                                modValue += 'Post:%03d:%s ' % (postCount, sliauth.iso_date(curDate, nosubsec=True))
                                modValue += colValue
                                if not modValue.endswith('\n'):
                                    modValue += '\n'

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
                        returnInfo['discussPosts'] = getDiscussPosts(discussionPost[0], discussionPost[1], userId)

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
                    returnInfo['adminPaced'] = adminPaced

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

                if getRow and createRow and discussableSession and dueDate:
                    returnInfo['discussStats'] = getDiscussStats(sheetName, userId)

                if computeTotalScore and getRow:
                    returnInfo['remoteAnswers'] = sessionAttributes.get('remoteAnswers')

        if getRow and createRow and proxy_error_status():
            returnInfo['proxyError'] = 'Read-only mode; session modifications are disabled'

        # return json success results
        retObj = {"result": "success", "value": returnValues, "headers": returnHeaders,
                  "info": returnInfo,
                  "messages": '\n'.join(returnMessages)}

    except Exception, err:
        # if error, return this
        if Settings['debug'] and not notrace:
            import traceback
            traceback.print_exc()

        retObj = {"result": "error", "error": err.message, "value": None,
                  "info": returnInfo,
                  "messages": '\n'.join(returnMessages)}

    if Settings['debug'] and not notrace and retObj['result'] != 'success':
        print("DEBUG: RETOBJ", retObj['result'], retObj['messages'], file=sys.stderr)
    
    return retObj

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
        return lookupValues(userId, MIN_HEADERS, ROSTER_SHEET, listReturn=True)
    except Exception, err:
        if isSpecialUser(userId):
            return ['#'+userId+', '+userId, userId, '', '']
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
def makeRandomChoiceSeed(randomSeed):
    return LCRandom.makeSeed(RandomChoiceOffset+randomSeed)

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
            noshuffle = questions[qno-1].get('noshuffle',0)
            if choices:
                qshuffle[qno] = str(randFunc(0,1)) + randomLetters(choices, noshuffle, randFunc)

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
    rowVals[headers.index('session_hidden')] = json.dumps(session)

    rosterSheet = getSheet(ROSTER_SHEET, optional=True)
    if rosterSheet:
        rosterValues = getRosterEntry(userId)

        for j in range(len(rosterValues)):
            if rosterValues[j]:
                rowVals[j] = rosterValues[j]

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

    updateParams = {'id': updateObj['id'], 'token': token,'sheet': sessionName,
                    'update': json.dumps(updates, default=sliauth.json_default)}
    updateParams.update(opts)

    return sheetAction(updateParams, notrace=notrace)

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
    sessionSheet = getSheet(sessionName, optional=True)
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
                sessionRange.setValue(json.dumps(session))

    if clearedResponse:
        # Update total score and answer stats
        sessionEntries = lookupValues(sessionName, ['questions', 'attributes'], INDEX_SHEET)
        sessionAttributes = json.loads(sessionEntries['attributes'])
        questions = json.loads(sessionEntries['questions'])
        updateTotalScores(sessionSheet, sessionAttributes, questions, True, startRow, nRows)
        sessionSheet.requestActions('answer_stats')


def importUserAnswers(sessionName, userId, displayName='', answers={}, submitDate=None, source=''):
    # answers = {1:{'response':, 'explain':},...}
    # If source == "prefill", only row creation occurs
    if Settings['debug']:
        print("DEBUG:importUserAnswers", userId, displayName, sessionName, len(answers), submitDate, file=sys.stderr)
    if not getSheet(sessionName, optional=True):
        raise Exception('Session '+sessionName+' not found')
    sessionEntries = lookupValues(sessionName, ['dueDate', 'paceLevel', 'adminPaced', 'attributes'], INDEX_SHEET)
    sessionAttributes = json.loads(sessionEntries['attributes'])
    dueDate = sessionEntries.get('dueDate')
    paceLevel = sessionEntries.get('paceLevel')
    adminPaced = sessionEntries.get('adminPaced')

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

    rowValues[sessionCol-1] = json.dumps(session)
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

def createRoster(headers, rows):
    if headers[:4] != MIN_HEADERS:
        raise Exception('Error: Invalid headers for roster_slidoc; first four should be "'+', '.join(MIN_HEADERS)+'", but found "'+', '.join(headers or [])+'"')

    test_user_row = ['#User, Test', TESTUSER_ID] + ['']*(len(headers)-2)
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
        if row[1] == TESTUSER_ID:
            test_user_row = row
            continue
        if row[1][0] == '_':
            raise Exception('Underscore not allowed at start of id in imported roster row: '+row[1])

        if row[0].count(',') > 1:
            raise Exception('Multiple commas not allowed in imported name: '+row[0])
        if row[0][0].isalpha():
            row[0] = row[0][0].upper() + row[0][1:]
        elif row[0][0] == '#' and len(row[0]) > 1:
            row[0] = row[0][0] + row[0][1].upper() + row[0][2:]
        else:
            raise Exception('Invalid start character in imported name '+row[0])
        rosterRows.append(row)
        
    rosterRows.sort()
    rosterRows.insert(0, test_user_row)
    rosterSheet = getSheet(ROSTER_SHEET, optional=True)
    if rosterSheet:
        raise Exception('Roster sheet already present; delete it before importing')
    return createSheet(ROSTER_SHEET, headers, rosterRows)
        
def getRowMap(sheetName, colName, regular=False, startRow=2):
    # Return dict of id->value in sheet (if regular, only for names defined and not starting with #)
    sheet = getSheet(sheetName)
    if not sheet:
        raise Exception('Sheet '+sheetName+' not found')
    colIndex = indexColumns(sheet)
    if colName not in colIndex:
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

def lookupRoster(field, userId=None):
    rosterSheet = getSheet(ROSTER_SHEET, optional=True)
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
    fieldVals = getColumns(field, rosterSheet, 1, 2)
    fieldDict = OrderedDict()
    for j, idVal in enumerate(idVals):
        fieldDict[idVal] = fieldVals[j]
    return fieldDict

AGGREGATE_COL_RE = re.compile(r'\b(_\w+)_(avg|normavg|sum)(_(\d+))?$', re.IGNORECASE)
def lookupGrades(userId):
    scoreSheet = getSheet(SCORES_SHEET, optional=True)
    if not scoreSheet:
        return None

    colIndex = indexColumns(scoreSheet)
    rowIndex = indexRows(scoreSheet, colIndex['id'], 2)
    userRow = lookupRowIndex(userId, scoreSheet)
    if not userRow:
        return None

    headers = scoreSheet.getHeaders()
    nCols = len(headers)
    userScores = scoreSheet.getSheetValues(userRow, 1, 1, nCols)[0]
    rescale = scoreSheet.getSheetValues(rowIndex['_rescale'], 1, 1, nCols)[0]
    average = scoreSheet.getSheetValues(rowIndex['_average'], 1, 1, nCols)[0]
    maxscore = scoreSheet.getSheetValues(rowIndex['_max_score'], 1, 1, nCols)[0]

    grades = {}
    sessionGrades = []
    for j, header in enumerate(headers):
        if not header.startswith('_') and header not in ('total', 'grade'):
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
    return grades

def lookupSessions(colNames):
    indexSheet = getSheet(INDEX_SHEET, optional=True)
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


def lookupValues(idValue, colNames, sheetName, listReturn=False):
    # Return parameters in list colNames for idValue from sheet
    indexSheet = getSheet(sheetName)
    if not indexSheet:
        raise Exception('Index sheet '+sheetName+' not found')
    indexColIndex = indexColumns(indexSheet)
    indexRowIndex = indexRows(indexSheet, indexColIndex['id'], 2)
    sessionRow = indexRowIndex.get(idValue)
    if not sessionRow:
        raise Exception('ID value '+idValue+' not found in index sheet '+sheetName)
    retVals = {}
    listVals = []
    for colName in colNames:
        if colName not in indexColIndex:
            raise Exception('Column '+colName+' not found in index sheet '+sheetName)
        retVals[colName] = indexSheet.getSheetValues(sessionRow, indexColIndex[colName], 1, 1)[0][0]
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
        raise Exception('ID value '+idValue+' not found in index sheet '+sheetName)
    if colName not in indexColIndex:
        raise Exception('Column '+colName+' not found in index sheet '+sheetName)
    indexSheet.getRange(sessionRow, indexColIndex[colName], 1, 1).setValues([[colValue]])

def locateNewRow(newName, newId, nameValues, idValues, skipId=None):
    # Return row number before which new name/id combination should be inserted
    for j in range(len(nameValues)):
        if skipId and skipId == idValues[j][0]:
            continue
        if nameValues[j][0] > newName or (nameValues[j][0] == newName and idValues[j][0] > newId):
            # Sort by name and then by id
            return j+1
    return len(nameValues)+1

def safeName(s, capitalize=False):
    s = re.sub(r'[^A-Za-z0-9-]', '_', s)
    return s.capitalize() if capitalize else s

def getDiscussStats(sessionName, userId):
    # Returns per slide discussion stats { slideNum: [nPosts, unreadPosts, ...}
    sheetName = sessionName+'-discuss'
    discussSheet = getSheet(sheetName)
    discussStats = {}
    if not discussSheet:
        return discussStats

    discussRow = lookupRowIndex(DISCUSS_ID, discussSheet)
    if not discussRow:
        raise Exception('Row with id '+DISCUSS_ID+' not found in sheet '+sheetName)
    userRow = lookupRowIndex(userId, discussSheet)
    if not userRow:
        raise Exception('User with id '+userId+' not found in sheet '+sheetName)

    ncols = discussSheet.getLastColumn()
    headers = discussSheet.getSheetValues(1, 1, 1, ncols)[0]
    topVals = discussSheet.getSheetValues(discussRow, 1, 1, ncols)[0]
    userVals = discussSheet.getSheetValues(userRow, 1, 1, ncols)[0]
    for j in range(ncols):
        amatch = AXS_RE.match(headers[j])
        if not amatch or not topVals[j]:
            continue
        if j == ncols-1 or headers[j+1] != 'discuss'+amatch.group(1):
            continue
        slideNum = int(amatch.group(1))
        discussStats[slideNum] = [topVals[j], topVals[j]-(userVals[j] or 0)]
        
    return discussStats

def getDiscussPosts(sessionName, slideNum, userId=None):
    # Return sorted list of discussion posts [ [postNum, userId, userName, postTime, unreadFlag, postText] ]
    sheetName = sessionName+'-discuss'
    discussSheet = getSheet(sheetName)
    if not discussSheet:
        raise Exception('Discuss sheet '+sessionName+'-discuss not found')
    colIndex = indexColumns(discussSheet)
    axsColName = 'access%03d' % slideNum
    axsCol = colIndex.get(axsColName)
    if not axsCol:
        return []

    if userId:
        # Update last read post
        lastPost = lookupValues(DISCUSS_ID, [axsColName], sheetName, True)[0]
        lastReadPost = lookupValues(userId, [axsColName], sheetName, True)[0] or 0

        if lastReadPost < lastPost:
            setValue(userId, axsColName, lastPost, sheetName)
    else:
        lastReadPost = 0

    idVals = getColumns('id', discussSheet)
    nameVals = getColumns('name', discussSheet)
    colVals = getColumns('discuss%03d' % slideNum, discussSheet)
    allPosts = []
    for j in range(len(colVals)):
        if not idVals[j] or (idVals[j].startswith('_') and idVals[j] != TESTUSER_ID):
            continue
        userPosts = ('\n'+colVals[j]).split('\nPost:')[1:]
        for k in range(len(userPosts)):
            pmatch = POST_NUM_RE.match(userPosts[k])
            if pmatch:
                postNumber = int(pmatch.group(1))
                postTimeStr = pmatch.group(2)
                unreadFlag = postNumber > lastReadPost if userId else False
                text = pmatch.group(3).strip()+'\n'
                if text.startswith(DELETED_POST):
                    # Hide text from deleted messages
                    text = DELETED_POST
                allPosts.append([postNumber, idVals[j], nameVals[j], postTimeStr, unreadFlag, text])

    allPosts.sort()
    return allPosts

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
        firstmiddle = firstmiddle.strip()
        if first:
            # For Firstname, try suffixes in following order: middle_initials+Lastname
            comps = firstmiddle.split()
            firstName = comps[0] or idValue
            suffix = lastName
            if len(comps) > 1:
                suffix = ''.join(x[0] for x in comps[1:]).upper() + suffix
            prefixDict[firstName].append(idValue)
            suffixesDict[idValue] = suffix
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
        response = '' + response
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

        if effectiveScore > 0:
            questionsCorrect += 1 + qSkipCount
            weightedCorrect += effectiveScore*qWeight + qSkipWeight

    return { 'questionsCount': questionsCount, 'weightedCount': weightedCount,
                'questionsCorrect': questionsCorrect, 'weightedCorrect': weightedCorrect,
                'questionsSkipped': questionsSkipped, 'correctSequence': correctSequence, 'skipToSlide': skipToSlide,
                'correctSequence': correctSequence, 'lastSkipRef': lastSkipRef, 'qscores': qscores}
