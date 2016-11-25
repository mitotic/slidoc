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

import cStringIO
import csv
import datetime
import json
import math
import os
import random
import re
import subprocess
import sys
import time
import urllib
import urllib2

from collections import defaultdict, OrderedDict

import tornado.httpclient
from tornado.ioloop import IOLoop

import reload
import sliauth

VERSION = '0.96.6l'

scriptdir = os.path.dirname(os.path.realpath(__file__))

# Usually modified by importing module
Options = {
    'backup_dir': '_BACKUPS/', # Backup directory prefix, including slash
    'debug': None,      
    'dry_run': None,      # Dry run (read from, but do not update, Google Sheets)
    'gsheet_url': None,   # Google Sheet URL
    'lock_proxy_url': '', # URL of proxy server to lock sheet
    'auth_key': None,     # Digest authentication key
    'min_wait_sec': 0,     # Minimum time (sec) between successful Google Sheet requests
    'require_login_token': True,
    'require_late_token': True,
    'share_averages': True
    }

DEFAULT_SETTINGS = [ ['require_login_token', 'true', "true/false"],
			         ['require_late_token', 'true', "true/false"],
			         ['share_averages', 'true', "true/false"] ]
    
RETRY_WAIT_TIME = 5      # Minimum time (sec) before retrying failed Google Sheet requests
RETRY_MAX_COUNT = 15     # Maximum number of failed Google Sheet requests
CACHE_HOLD_SEC = 3600    # Maximum time (sec) to hold sheet in cache

ADMINUSER_ID = 'admin'
MAXSCORE_ID = '_max_score'
AVERAGE_ID = '_average'
RESCALE_ID = '_rescale'
TESTUSER_ID = '_test_user'   #var

MIN_HEADERS = ['name', 'id', 'email', 'altid']
TESTUSER_ROSTER = ['#user, test', TESTUSER_ID, '', '']  #var

SETTINGS_SHEET = 'settings_slidoc'
INDEX_SHEET = 'sessions_slidoc'
ROSTER_SHEET = 'roster_slidoc'
SCORES_SHEET = 'scores_slidoc'

BASIC_PACE    = 1
QUESTION_PACE = 2
ADMIN_PACE    = 3

SKIP_ANSWER = 'skip'

LATE_SUBMIT = 'late'
PARTIAL_SUBMIT = 'partial'

TRUNCATE_DIGEST = 8

QFIELD_RE = re.compile(r"^q(\d+)_([a-z]+)$")

class Dummy():
    pass
    
Sheet_cache = {}    # Cache of sheets
Miss_cache = {}     # For optional sheets that are missing
Lock_cache = {}     # Locked sheets
Refresh_sheets = set()

Global = Dummy()

Global.remoteVersions = set()

def delSheet(sheetName):
    for cache in (Sheet_cache, Miss_cache, Lock_cache):
        if sheetName in cache:
            del cache[sheetName]

    if sheetName in Refresh_sheets:
        Refresh_sheets.discard(sheetName)


def initCache():
    Sheet_cache.clear()
    Miss_cache.clear()
    Lock_cache.clear()

    Global.cacheRequestTime = 0
    Global.cacheResponseTime = 0
    Global.cacheUpdateTime = sliauth.epoch_ms()

    Global.cacheRetryCount = 0
    Global.cacheWaitTime = 0

    Global.totalCacheResponseInterval = 0
    Global.totalCacheResponseCount = 0
    Global.totalCacheRetryCount = 0
    Global.totalCacheRequestBytes = 0
    Global.totalCacheResponseBytes = 0

    Global.cachePendingUpdate = None
    Global.suspended = ""

initCache()

def backupCache(dirpath=''):
    # Returns null string on success or error string
    dirpath = dirpath or Options['backup_dir'] or '_backup'
    if dirpath.endswith('-'):
        dirpath += sliauth.iso_date()[:16].replace(':','-')
    suspend_cache("backup")
    if Options['debug']:
        print("DEBUG:backupCache: %s started %s" % (dirpath, datetime.datetime.now()), file=sys.stderr)
    errorList = []
    try:
        if not os.path.exists(dirpath):
            os.makedirs(dirpath)

        for sheetName in (SETTINGS_SHEET, ROSTER_SHEET):
            sheet = getSheet(sheetName, optional=True)
            if sheet:
                backupSheet(sheetName, sheet, dirpath, errorList)

        indexSheet = getSheet(INDEX_SHEET, optional=True)
        if indexSheet:
            sessionNames = getColumns('id', indexSheet)
            backupSheet(INDEX_SHEET, indexSheet, dirpath, errorList)
        else:
            sessionNames = []
            errorList.append('Error: Index sheet %s not found' % INDEX_SHEET)

        for sheetName in sessionNames:
            alreadyCached = sheetName in Sheet_cache
            sessionSheet = getSheet(sheetName, optional=True)
            if not sessionSheet:
                errorList.append('Error: Session sheet %s not found' % sheetName)
                continue
            backupSheet(sheetName, sessionSheet, dirpath, errorList)
            if not alreadyCached:
                del Sheet_cache[sheetName]
    except Exception, excp:
        errorList.append('Error in backup: '+str(excp))

    errors = '\n'.join(errorList)+'\n' if errorList else ''
    if errors:
        try:
            with  open(dirpath+'/ERRORS_IN_BACKUP.txt', 'w') as errfile:
                errfile.write(errors)
        except Exception, excp:
            print("ERROR:backupCache: ", str(excp), file=sys.stderr)

    if Options['debug']:
        if errors:
            print(errors, file=sys.stderr)
        print("DEBUG:backupCache: %s completed %s" % (dirpath, datetime.datetime.now()), file=sys.stderr)
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


def backupSheet(name, sheet, dirpath, errorList):
    try:
        rowNum = 0
        with open(dirpath+'/'+name+'.csv', 'wb') as csvfile:
            writer = csv.writer(csvfile)
            for rowNum in range(1,sheet.getLastRow()+1):
                row = sheet.getSheetValues(rowNum, 1, 1, sheet.getLastColumn())[0]
                rowStr = [backupCell(x) for x in row]
                writer.writerow(rowStr)
    except Exception, excp:
        errorList.append('Error in saving sheet %s (row %d): %s' % (name, rowNum, excp))

def getSheet(sheetName, optional=False):
    check_if_locked(sheetName, get=True)

    if sheetName in Sheet_cache:
        return Sheet_cache[sheetName]
    elif optional and sheetName in Miss_cache:
        # If optional sheets are later created, will need to clear cache
        if (sliauth.epoch_ms() - Miss_cache[sheetName]) < 0.5*1000*CACHE_HOLD_SEC:
            return None
        # Retry retrieving optional sheet
        del Miss_cache[sheetName]

    if Options['lock_proxy_url'] and not sheetName.endswith('_slidoc') and not sheetName.endswith('_log'):
        lockURL = Options['lock_proxy_url']+'/_lock/'+sheetName
        try:
            req = urllib2.Request(lockURL+'?token='+Options['auth_key']+'&type=proxy')
            response = urllib2.urlopen(req)
            if Options['debug']:
                print("DEBUG:getSheet: %s LOCKED %s (%s)" % (sheetName, lockURL, response.read()), file=sys.stderr)
        except Exception, excp:
            errMsg = 'ERROR:getSheet: Unable to lock sheet '+sheetName+': '+str(excp)
            print(errMsg, file=sys.stderr)
            raise Exception(errMsg)
        time.sleep(6)

    user = 'admin'
    userToken = sliauth.gen_admin_token(Options['auth_key'], user)

    getParams = {'sheet': sheetName, 'proxy': '1', 'get': '1', 'all': '1', 'admin': user, 'token': userToken}
    if Options['debug']:
        print("DEBUG:getSheet", sheetName, getParams, file=sys.stderr)

    if Options['debug'] and not Options['gsheet_url']:
        return None

    retval = sliauth.http_post(Options['gsheet_url'], getParams) if Options['gsheet_url'] else {'result': 'error', 'error': 'No Sheet URL'}
    if Options['debug']:
        print("DEBUG:getSheet", sheetName, retval['result'], retval.get('info',{}).get('version'), retval.get('messages'), file=sys.stderr)

    Global.remoteVersions.add( retval.get('info',{}).get('version','') )
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

def createSheet(sheetName, headers):
    check_if_locked(sheetName)

    if not headers:
        raise Exception("Must specify headers to create sheet %s" % sheetName)
    keyHeader = '' if sheetName.startswith('settings_') or sheetName.endswith('_log') else 'id'
    Sheet_cache[sheetName] = Sheet(sheetName, [headers], keyHeader=keyHeader)
    return Sheet_cache[sheetName]


class Sheet(object):
    # Implements a simple spreadsheet with fixed number of columns
    def __init__(self, name, rows, modTime=0, keyHeader=''):
        if not rows:
            raise Exception('Must specify at least header row for sheet')
        self.name = name
        self.modTime = modTime
        self.keyHeader = keyHeader

        self.accessTime = sliauth.epoch_ms()
        self.nCols = len(rows[0])
        for j, row in enumerate(rows[1:]):
            if len(row) != self.nCols:
                raise Exception('Incorrect number of cols in row %d: expected %d but found %d' % (j+1, self.nCols, len(row)))

        self.xrows = [ row[:] for row in rows ]  # Shallow copy

        if self.keyHeader:
            if not self.xrows:
                raise Exception('Must specify at least header row for keyed sheet')

            headers = self.xrows[0]
            for j, colName in enumerate(headers):
                if colName.endswith('Timestamp') or colName.lower().endswith('date') or colName.lower().endswith('time'):
                    # Parse time string
                    for row in self.xrows[1:]:
                        if row[j]:
                            row[j] = createDate(row[j])

            self.keyCol= 1 + headers.index(keyHeader)
            self.keyMap = dict( (row[self.keyCol-1], modTime) for row in self.xrows[1:] )
            if 1+len(self.keyMap) != len(self.xrows):
                raise Exception('Duplicate key in initial rows for sheet '+self.name)
        else:
            self.keyCol= 0
            self.keyMap = dict( (j+2, modTime) for j in range(len(self.xrows)-1) )

    def getLastColumn(self):
        return self.nCols

    def getLastRow(self):
        return len(self.xrows)

    def getRows(self):
        # Return shallow copy
        return [ row[:] for row in self.xrows ]

    def deleteRow(self, rowNum):
        if not self.keyHeader:
            raise Exception('Cannot delete row for non-keyed spreadsheet')
        if rowNum < 1 or rowNum > len(self.xrows):
            raise Exception('Invalid row number for deletion: %s' % rowNum)
        self.modTime = sliauth.epoch_ms()
        self.accessTime = self.modTime
        keyValue = self.xrows[rowNum-1][self.keyCol-1]
        del self.xrows[rowNum-1]
        del self.keyMap[keyValue]

    def insertRowBefore(self, rowNum, keyValue=None):
        if self.keyHeader:
            if rowNum < 2 or rowNum > len(self.xrows)+1:
                raise Exception('Invalid row number for insertion: %s' % rowNum)
        else:
            if rowNum != len(self.xrows)+1:
                raise Exception('Can only append row for non-keyed spreadsheet')

        self.modTime = sliauth.epoch_ms()
        self.accessTime = self.modTime
        newRow = ['']*self.nCols
        if self.keyHeader:
            if keyValue is None:
                raise Exception('Must specify key for row insertion in sheet '+self.name)
            if keyValue in self.keyMap:
                raise Exception('Duplicate key %s for row insertion in sheet %s' % (self.name, keyValue))
            self.keyMap[keyValue] = self.modTime
            newRow[self.keyCol-1] = keyValue
        else:
            self.keyMap[rowNum] = self.modTime

        self.xrows.insert(rowNum-1, newRow)

    def appendColumns(self, headers):
        if Options['gsheet_url'] and not Options['dry_run']:
            # Proxy caching currently does not work with varying columns
            raise Exception("Cannot append columns for session '"+self.name+"' via proxy; use direct URL")
        self.modTime = sliauth.epoch_ms()
        self.nCols += len(headers)
        self.xrows[0] += headers
        for j in range(1, len(self.xrows)):
            self.xrows[j] += ['']*len(headers)

    def trimColumns(self, ncols):
        if Options['gsheet_url'] and not Options['dry_run']:
            # Proxy caching currently does not work with varying columns
            raise Exception("Cannot delete columns for session '"+self.name+"' via proxy; use direct URL")
        self.modTime = sliauth.epoch_ms()
        self.nCols -= ncols
        for j in range(len(self.xrows)):
            self.xrows[j] = self.xrows[j][:-ncols]

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
        self.accessTime = sliauth.epoch_ms()
        self.checkRange(rowMin, colMin, rowCount, colCount)
        return [row[colMin-1:colMin+colCount-1] for row in self.xrows[rowMin-1:rowMin+rowCount-1]]

    def setSheetValues(self, rowMin, colMin, rowCount, colCount, values):
        ##if Options['debug']:
        ##    print("setSheetValues:", self.name, rowMin, colMin, rowCount, colCount, file=sys.stderr)
        check_if_locked(self.name)
        if rowMin < 2:
            raise Exception('Cannot overwrite header row')
        self.checkRange(rowMin, colMin, rowCount, colCount)
        if rowCount != len(values):
            raise Exception('Row count mismatch for setSheetValues %s: expected %d but found %d' % (self.name, rowCount, len(values)) )

        for j, rowValues in enumerate(values):
            if colCount != len(rowValues):
                raise Exception('Col count mismatch for setSheetValues %s in row %d: expected %d but found %d' % (self.name, j+rowMin, colCount, len(rowValues)) )

        self.modTime = sliauth.epoch_ms()
        self.accessTime = self.modTime
        for j, rowValues in enumerate(values):
            if self.keyCol:
                oldKeyValue = self.xrows[j+rowMin-1][self.keyCol-1]
                if self.keyCol >= colMin and self.keyCol <= colMin+colCount-1:
                    newKeyValue = rowValues[self.keyCol-colMin]
                    if newKeyValue != oldKeyValue:
                        raise Exception('Cannot alter key value %s to %s in sheet %s' % (oldKeyValue, newKeyValue, self.name))
                self.keyMap[oldKeyValue] = self.modTime

            self.xrows[j+rowMin-1][colMin-1:colMin+colCount-1] = rowValues

        update_remote_sheets()

    def get_updates(self, lastUpdateTime):
        if self.modTime < lastUpdateTime:
            return None

        rows = []
        if self.keyCol:
            keys = dict( (key, 1) for key in self.keyMap )
            for row in self.xrows[1:]:
                keyValue = row[self.keyCol-1]
                if self.keyMap[keyValue] > lastUpdateTime:
                    rows.append([keyValue, row])
        else:
            keys = None
            for j, row in enumerate(self.xrows[1:]):
                if self.keyMap[j+2] > lastUpdateTime:
                    rows.append([j+2, row])
        return [self.xrows[0], keys, rows]
                    

class Range(object):
    def __init__(self, sheet, rowMin, colMin, rowCount, colCount):
        self.sheet = sheet
        self.rng = [rowMin, colMin, rowCount, colCount]

    def getValues(self):
        return self.sheet.getSheetValues(*self.rng)

    def setValues(self, values):
        self.sheet.setSheetValues(*(self.rng+[values]))

def getCacheStatus():
    out = 'Cache: version %s (%s)\n' % (VERSION, list(Global.remoteVersions))
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
            if sheet and sheet.get_updates(Global.cacheUpdateTime) is not None:
                sheetStr = sheetName+' (locking...)'
            else:
                action = 'unlock'
        else:
            action = 'lock'
        if not sheetStr:
            sheetStr = '<a href="/_%s/%s">%s</a> %s' % (action, sheetName, action, Lock_cache.get(sheetName,''))
    
        accessTime =  str(int((curTime-sheet.accessTime)/1000.))+'s' if sheet else '(not cached)'
        out += 'Sheet_cache: %s: %s %s\n' % (sheetName, accessTime, sheetStr)
    out += '\n'
    for sheetName in Miss_cache:
        out += 'Miss_cache: %s: %ds\n' % (sheetName, (curTime-Miss_cache[sheetName])/1000.)
    out += '\n'
    return out

def lockSheet(sheetName, lockType='user', refresh=False):
    # Returns True if lock is immediately effective; False if it will take effect later
    # If refresh, automatically unlock after updates
    if sheetName not in Lock_cache:
        Lock_cache[sheetName] = lockType
    if refresh:
        Refresh_sheets.add(sheetName)
        return unlockSheet(sheetName)
    if sheetName in Sheet_cache and Sheet_cache[sheetName].get_updates(Global.cacheUpdateTime) is not None:
        return False
    return True

def unlockSheet(sheetName):
    if sheetName in Sheet_cache and Sheet_cache[sheetName].get_updates(Global.cacheUpdateTime) is not None:
        return False
    if sheetName in Lock_cache:
        del Lock_cache[sheetName]
    if sheetName in Sheet_cache:
        del Sheet_cache[sheetName]
    Refresh_sheets.discard(sheetName)
    return True

def check_if_locked(sheetName, get=False):
    if Options['lock_proxy_url'] and sheetName.endswith('_slidoc') and not get:
        raise Exception('Only get operation allowed for special sheet '+sheetName+' in locked proxy mode')

    if sheetName in Lock_cache or (Global.suspended and (not get or Global.suspended != 'backup')):
        raise Exception('Sheet %s is locked!' % sheetName)

def get_locked():
    # Return list of locked sheet name (* if updates not yet send to Google sheets)
    locked = []
    for sheetName in Lock_cache:
        if sheetName in Sheet_cache and Sheet_cache[sheetName].get_updates(Global.cacheUpdateTime) is not None:
            locked.append(sheetName+'*')
        else:
            locked.append(sheetName)
    locked.sort()
    return locked

def schedule_update(waitSec=0, force=False):
    if Global.cachePendingUpdate:
        IOLoop.current().remove_timeout(Global.cachePendingUpdate)
        Global.cachePendingUpdate = None

    if waitSec:
        Global.cachePendingUpdate = IOLoop.current().call_later(waitSec, update_remote_sheets)
    else:
        update_remote_sheets(force=force)

def suspend_cache(action="shutdown"):
    Global.suspended = action
    if action:
        print("Suspended for", action, file=sys.stderr)
        schedule_update(force=True)

def updates_current():
    if not Global.suspended:
        return
    if Global.suspended == "shutdown":
        print("Completing shutdown", file=sys.stderr)
        IOLoop.current().stop()
    elif Global.suspended == "clear":
        initCache()
        print("Cleared cache", file=sys.stderr)
    elif Global.suspended == "reload":
        try:
            os.utime(scriptdir+'/reload.py', None)
            print("Reloading...", file=sys.stderr)
        except Exception, excp:
            print("Reload failed: "+str(excp), file=sys.stderr)
    elif Global.suspended == "pull":
        try:
            if os.environ.get('SUDO_USER'):
                cmd = ["sudo", "-u", os.environ['SUDO_USER'], "git", "pull"]
            else:
                cmd = ["git", "pull"]
            print("Updating via pull: %s" % cmd, file=sys.stderr)
            subprocess.check_call(cmd, cwd=scriptdir)
        except Exception, excp:
            print("Update via git pull failed: "+str(excp), file=sys.stderr)

def update_remote_sheets(force=False):
    if Options['debug']:
        print("update_remote_sheets:A", Global.cacheRequestTime, file=sys.stderr)

    if not Options['gsheet_url'] or Options['dry_run']:
        # No updates if no sheet URL or dry run
        updates_completed(sliauth.epoch_ms())
        updates_current()
        return

    if Global.cacheRequestTime:
        return

    cur_time = sliauth.epoch_ms()
    if not force and (cur_time - Global.cacheResponseTime) < 1000*Options['min_wait_sec']:
        schedule_update(cur_time-Global.cacheResponseTime)
        return

    modRequests = []
    curTime = sliauth.epoch_ms()
    for sheetName, sheet in Sheet_cache.items():
        # Check each cached sheet for updates
        updates = sheet.get_updates(Global.cacheUpdateTime)
        if updates is None:
            if curTime-sheet.accessTime > 1000*CACHE_HOLD_SEC:
                # Cache entry has expired
                del Sheet_cache[sheetName]
            continue
        # sheet_name, headers_list, keys_dictionary, modified_rows
        modRequests.append([sheetName, updates[0], updates[1], updates[2]])

    if Options['debug']:
            print("update_remote_sheets:B", modRequests is not None, file=sys.stderr)
    if not modRequests:
        # Nothing to update
        updates_current()
        return

    if Options['debug']:
        print("update_remote_sheets:C", [(x[0], [y[0] for y in x[3]]) for x in modRequests], file=sys.stderr)

    user = 'admin'
    userToken = sliauth.gen_admin_token(Options['auth_key'], user)

    http_client = tornado.httpclient.AsyncHTTPClient()
    json_data = json.dumps(modRequests, default=sliauth.json_default)
    post_data = { 'proxy': '1', 'allupdates': '1', 'admin': user, 'token': userToken,
                  'data':  json_data}
    post_data['create'] = 'proxy'
    body = urllib.urlencode(post_data)
    http_client.fetch(Options['gsheet_url'], handle_proxy_response, method='POST', headers=None, body=body)
    Global.totalCacheRequestBytes += len(json_data)
    Global.cacheRequestTime = cur_time

def handle_proxy_response(response):
    Global.cacheResponseTime = sliauth.epoch_ms()
    Global.totalCacheResponseInterval += (Global.cacheResponseTime - Global.cacheRequestTime)
    Global.totalCacheResponseCount += 1

    errMsg = ""
    if response.error:
        print("handle_proxy_response: Update ERROR:", response.error, file=sys.stderr)
        errMsg = response.error
        if Global.suspended or Global.cacheRetryCount > RETRY_MAX_COUNT:
            sys.exit('Failed to update cache after %d tries' % RETRY_MAX_COUNT)
        Global.cacheRequestTime = 0
        Global.cacheRetryCount += 1
        Global.totalCacheRetryCount += 1
        Global.cacheWaitTime += RETRY_WAIT_TIME
        schedule_update(Global.cacheWaitTime)
    else:
        Global.totalCacheResponseBytes += len(response.body)
        if Options['debug']:
            print("handle_proxy_response: Update RESPONSE", response.body[:256], file=sys.stderr)
        try:
            respObj = json.loads(response.body)
            if respObj['result'] == 'error':
                errMsg = respObj['error']
        except Exception, err:
            errMsg = 'JSON parsing error: '+str(err)

        if errMsg:
            print("handle_proxy_response: Update ERROR:", errMsg, file=sys.stderr)
            sys.exit(errMsg)

        for errSessionName, proxyErrMsg in respObj['info'].get('updateErrors',[]):
            Lock_cache[errSessionName] = proxyErrMsg
            print("handle_proxy_response: Update LOCKED %s: %s" % (errSessionName, proxyErrMsg), file=sys.stderr)

    if not errMsg:
        # Update succeeded
        if Options['debug']:
            print("handle_proxy_response:", Global.cacheUpdateTime, respObj, file=sys.stderr)

        updates_completed(Global.cacheRequestTime)
        schedule_update(0 if Global.suspended else Options['min_wait_sec'])

def updates_completed(updateTime):
        Global.cacheUpdateTime = updateTime
        Global.cacheRequestTime = 0
        Global.cacheRetryCount = 0
        Global.cacheWaitTime = 0
        for sheetName in Refresh_sheets:
            unlockSheet(sheetName)
        

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
    # create: 1 to create and initialize non-existent rows (for get/put)
    # delrow: 1 to delete row
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

    if Options['debug']:
        print("DEBUG: sheetAction PARAMS", params.get('sheet'), params.get('id'), file=sys.stderr)

    returnValues = None
    returnHeaders = None
    returnInfo = {'version': VERSION}
    returnMessages = []

    try:
        sheetName = params.get('sheet','')
        if not sheetName:
            raise Exception('Error:SHEETNAME::No sheet name specified')

        adminUser = ''
        paramId = params.get('id','') #var

        if params.get('admin',''):
            if not params.get('token',''):
                raise Exception('Error:NEED_ADMIN_TOKEN:Need token for admin authentication')
            if not validateHMAC('admin:'+params.get('admin','')+':'+params.get('token',''), Options['auth_key']):
                raise Exception("Error:INVALID_ADMIN_TOKEN:Invalid token for authenticating admin user '"+params.get('admin','')+"'")
            adminUser = params.get('admin','')
        elif Options['require_login_token']:
            if not paramId:
                raise Exception('Error:NEED_ID:Need id for authentication')
            if not params.get('token',''):
                raise Exception('Error:NEED_TOKEN:Need token for id authentication')
            if not validateHMAC('id:'+paramId+':'+params.get('token',''), Options['auth_key']):
                raise Exception("Error:INVALID_TOKEN:Invalid token for authenticating id '"+paramId+"'")

        # Read-only sheets
        protectedSheet = (sheetName.endswith('_slidoc') and sheetName != INDEX_SHEET) or sheetName.endswith('-answers') or sheetName.endswith('-stats')
        # Admin-only access sheets
        restrictedSheet = (sheetName.endswith('_slidoc') and sheetName != SCORES_SHEET)

        loggingSheet = sheetName.endswith('_log')

        sessionEntries = None
        sessionAttributes = None
        questions = None
        paceLevel = None
        adminPaced = None
        dueDate = None
        gradeDate = None
        voteDate = None
        curDate = createDate()

        if restrictedSheet:
            if not adminUser:
                raise Exception("Error::Must be admin user to access sheet '"+sheetName+"'")

        rosterValues = []
        rosterSheet = getSheet(ROSTER_SHEET, optional=True)
        if rosterSheet and not adminUser:
            # Check user access
            if not paramId:
                raise Exception('Error:NEED_ID:Must specify userID to lookup roster')
            try:
                # Copy user info from roster
                rosterValues = lookupValues(paramId, MIN_HEADERS, ROSTER_SHEET, listReturn=True)
            except Exception, err:
                if paramId == TESTUSER_ID:
                    rosterValues = TESTUSER_ROSTER
                else:
                    raise Exception("Error:NEED_ROSTER_ENTRY:userID '"+paramId+"' not found in roster")

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
                    
            if Options['gsheet_url'] and not Options['dry_run']:
                user = 'admin'
                userToken = sliauth.gen_admin_token(Options['auth_key'], user)
                delParams = {'sheet': sheetName, 'delsheet': '1', 'admin': user, 'token': userToken}
                retval = sliauth.http_post(Options['gsheet_url'], delParams)
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
            if Options['gsheet_url'] and not Options['dry_run']:
                user = 'admin'
                userToken = sliauth.gen_admin_token(Options['auth_key'], user)
                copyParams = {'sheet': sheetName, 'copysheet': newName, 'admin': user, 'token': userToken}
                retval = sliauth.http_post(Options['gsheet_url'], copyParams)
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

            if not restrictedSheet and not protectedSheet and not loggingSheet and getSheet(INDEX_SHEET):
                # Indexed session
                sessionEntries = lookupValues(sheetName, ['dueDate', 'gradeDate', 'paceLevel', 'adminPaced', 'otherWeight', 'fieldsMin', 'questions', 'attributes'], INDEX_SHEET)
                sessionAttributes = json.loads(sessionEntries['attributes'])
                questions = json.loads(sessionEntries['questions'])
                paceLevel = sessionEntries.get('paceLevel')
                adminPaced = sessionEntries.get('adminPaced')
                dueDate = sessionEntries.get('dueDate')
                gradeDate = sessionEntries.get('gradeDate')
                voteDate = createDate(sessionAttributes['params']['plugin_share_voteDate']) if sessionAttributes['params'].get('plugin_share_voteDate') else None

            # Check parameter consistency
            getRow = params.get('get','')
            getShare = params.get('getshare', '')
            allRows = params.get('all','')
            createRow = params.get('create', '')
            nooverwriteRow = params.get('nooverwrite','')
            delRow = params.get('delrow','')
            importSession = params.get('import','')

            columnHeaders = modSheet.getSheetValues(1, 1, 1, modSheet.getLastColumn())[0]
            columnIndex = indexColumns(modSheet)

            selectedUpdates = json.loads(params.get('update','')) if params.get('update','') else None
            rowUpdates = json.loads(params.get('row','')) if params.get('row','') else None

            if headers:
                modifyStartCol = int(params['modify']) if params.get('modify') else 0
                if modifyStartCol:
                    if not sessionEntries or not rowUpdates or rowUpdates[columnIndex['id']-1] != MAXSCORE_ID:
                        raise Exception("Error::Must be updating max scores row to modify headers in sheet "+sheetName)
                    checkCols = modifyStartCol-1
                else:
                    if len(headers) != len(columnHeaders):
                        raise Exception("Error::Number of headers does not match that present in sheet '"+sheetName+"'; delete it or modify headers.");
                    checkCols = len(columnHeaders)

                for j in range( checkCols ):
                    if headers[j] != columnHeaders[j]:
                        raise Exception("Error::Column header mismatch: Expected "+headers[j]+" but found "+columnHeaders[j]+" in sheet '"+sheetName+"'; delete it or modify headers.")

                if modifyStartCol:
                    # Updating maxscore row; modify headers if needed
                    if modifyStartCol <= len(columnHeaders):
                        # Truncate columns; ensure truncated columns are empty
                        startCol = modifyStartCol
                        nCols = len(columnHeaders)-startCol+1
                        startRow = 2
                        nRows = modSheet.getLastRow()-startRow+1
                        if nRows:
                            idValues = modSheet.getSheetValues(startRow, columnIndex['id'], nRows, 1)
                            if idValues[0][0] == MAXSCORE_ID:
                                startRow += 1
                                nRows -= 1
                            if nRows:
                                values = modSheet.getSheetValues(startRow, startCol, nRows, nCols)
                                for j in range(nCols):
                                    for k in range(nRows):
                                        if values[k][j] != '':
                                            raise Exception( "Error:TRUNCATE_ERROR:Cannot truncate non-empty column "+str(startCol+j)+" ("+columnHeaders[startCol+j-1]+") in sheet "+sheetName )

                        modSheet.trimColumns( nCols )
                        ##modSheet.deleteColumns(startCol, nCols)

                    nTemCols = modSheet.getLastColumn()
                    if len(headers) > nTemCols:
                        # Extend columns
                        startCol = nTemCols+1
                        nCols = len(headers)-startCol+1
                        modSheet.appendColumns(headers[nTemCols:])
                        ##modSheet.insertColumnsAfter(startCol-1, nCols);
                        ##modSheet.getRange(1, startCol, 1, nCols).setValues([ headers.slice(nTemCols) ]);

                    columnHeaders = modSheet.getSheetValues(1, 1, 1, modSheet.getLastColumn())[0]
                    columnIndex = indexColumns(modSheet)

            userId = None
            displayName = None

            voteSubmission = ''
            if not rowUpdates and selectedUpdates and len(selectedUpdates) == 2 and selectedUpdates[0][0] == 'id' and selectedUpdates[1][0].endswith('_vote') and sessionAttributes.get('shareAnswers'):
                qprefix = selectedUpdates[1][0].split('_')[0]
                voteSubmission = sessionAttributes['shareAnswers'][qprefix].get('share', '') if sessionAttributes['shareAnswers'].get(qprefix) else ''

            alterSubmission = False
            if not rowUpdates and selectedUpdates and len(selectedUpdates) == 2 and selectedUpdates[0][0] == 'id' and selectedUpdates[1][0] == 'submitTimestamp':
                alterSubmission = True

            if not adminUser and selectedUpdates and not voteSubmission:
                raise Exception("Error::Only admin user allowed to make selected updates to sheet '"+sheetName+"'")

            if importSession and not adminUser:
                raise Exception("Error::Only admin user allowed to import to sheet '"+sheetName+"'")

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
                    if Options['share_averages'] and temIndexRow.get(AVERAGE_ID):
                        returnInfo['averages'] = modSheet.getSheetValues(temIndexRow.get(AVERAGE_ID), 1, 1, len(columnHeaders))[0]
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
            if modSheet.getLastRow() > numStickyRows:
                returnValues = modSheet.getSheetValues(1+numStickyRows, 1, modSheet.getLastRow()-numStickyRows, len(columnHeaders))
            else:
                returnValues = []
            if sessionEntries and adminPaced:
                returnInfo['adminPaced'] = adminPaced
            if sessionEntries and columnIndex.get('lastSlide'):
                returnInfo['maxLastSlide'] = getColumnMax(modSheet, 2, columnIndex['lastSlide'])
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

                votingCompleted = voteDate and sliauth.epoch_ms(voteDate) < sliauth.epoch_ms(curDate);

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
                    # Return user's vote codes
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

                    # If voting, skip incomplete/late submissions (but allow partials)
                    if voteParam and (lateValues[j][0] and lateValues[j][0] != PARTIAL_SUBMIT):
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
                if len(rowUpdates) > len(columnHeaders):
                    raise Exception("Error::row_headers length exceeds no. of columns in sheet '"+sheetName+"'; delete it or edit headers.")

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

            if adminUser and not restrictedSheet and newRow and userId != MAXSCORE_ID and not importSession:
                raise Exception("Error::Admin user not allowed to create new row in sheet '"+sheetName+"'")

            teamCol = columnIndex.get('team')
            if newRow and (not rowUpdates) and createRow:
                # Initialize new row
                if sessionEntries:
                    rowUpdates = createSessionRow(sheetName, sessionEntries['fieldsMin'], sessionAttributes['params'],
                                                  userId, params.get('name', ''), params.get('email', ''), params.get('altid', ''), createRow);
                    displayName = rowUpdates[columnIndex['name']-1] or ''
                    if params.get('late') and columnIndex.get('lateToken'):
                        rowUpdates[columnIndex['lateToken']-1] = params['late']

                    if teamCol and sessionAttributes.get('sessionTeam') == 'roster':
                        # Copy team name from roster
                        teamName = lookupRoster('team', userId)
                        if teamName:
                            rowUpdates[teamCol-1] = teamName
                else:
                    rowUpdates = []
                    for j in range(len(columnHeaders)):
                        rowUpdates[j] = None

            if newRow and getRow and not rowUpdates:
                # Row does not exist return empty list
                returnValues = []

            elif newRow and selectedUpdates:
                raise Exception('Error::Selected updates cannot be applied to new row')
            else:
                pastSubmitDeadline = False
                partialSubmission = False
                fieldsMin = len(columnHeaders)
                submitTimestampCol = columnIndex.get('submitTimestamp')

                prevSubmitted = None
                if not newRow and submitTimestampCol:
                    prevSubmitted = modSheet.getSheetValues(userRow, submitTimestampCol, 1, 1)[0][0] or None

                if sessionEntries:
                    # Indexed session
                    fieldsMin = sessionEntries.get('fieldsMin')

                    if rowUpdates and not nooverwriteRow and prevSubmitted:
                        raise Exception("Error::Cannot re-submit session for user "+userId+" in sheet '"+sheetName+"'");

                    if voteDate:
                        returnInfo['voteDate'] = voteDate

                    if dueDate and not prevSubmitted and not voteSubmission and not alterSubmission:
                        # Check if past submission deadline
                        lateTokenCol = columnIndex.get('lateToken')
                        lateToken = None
                        lateDueDate = None
                        if lateTokenCol:
                            lateToken = (rowUpdates[lateTokenCol-1] or None)  if (rowUpdates and len(rowUpdates) >= lateTokenCol) else None
                            if not lateToken and not newRow:
                                lateToken = modSheet.getRange(userRow, lateTokenCol, 1, 1).getValues()[0][0] or None

                            if lateToken and ':' in lateToken:
                                comps = splitToken(lateToken)
                                dateStr = comps[0]
                                tokenStr = comps[1]
                                if sliauth.gen_late_token(Options['auth_key'], userId, sheetName, dateStr) == lateToken:
                                    lateDueDate = True
                                    dueDate = createDate(dateStr) # Date format: '1995-12-17T03:24Z'
                                else:
                                    returnMessages.append("Warning:INVALID_LATE_TOKEN:Invalid token "+lateToken+" for late submission by user '"+(displayName or "")+"' to session '"+sheetName+"'")

                        returnInfo['dueDate'] = dueDate # May have been updated

                        curTime = sliauth.epoch_ms(curDate)
                        pastSubmitDeadline = (dueDate and curTime > sliauth.epoch_ms(dueDate))

                        allowLateMods = not Options['require_late_token'] or adminUser
                        if not allowLateMods and pastSubmitDeadline and lateToken:
                            if lateToken == PARTIAL_SUBMIT:
                                if newRow or not rowUpdates:
                                    raise Exception("Error::Partial submission only works for pre-existing rows")
                                if sessionAttributes['params'].get('participationCredit'):
                                    raise Exception("Error::Partial submission not allowed for participation credit")
                                partialSubmission = True
                                rowUpdates = None
                                selectedUpdates = [ ['Timestamp', None], ['submitTimestamp', None], ['lateToken', lateToken] ]
                                returnMessages.append("Warning:PARTIAL_SUBMISSION:Partial submission by user '"+(displayName or "")+"' to session '"+sheetName+"'")
                            elif lateToken == LATE_SUBMIT:
                                # Late submission for reduced/no credit
                                allowLateMods = True
                            elif not lateDueDate:
                                # Invalid token
                                returnMessages.append("Warning:INVALID_LATE_TOKEN:Invalid token '"+lateToken+"' for late submission by user '"+(displayName or "")+"' to session '"+sheetName+"'")

                        if not allowLateMods and not partialSubmission:
                            if pastSubmitDeadline:
                                if not importSession and (newRow  or selectedUpdates or (rowUpdates and not nooverwriteRow)):
                                    # Creating/modifying row; require valid lateToken
                                    if not lateToken:
                                        raise Exception("Error:PAST_SUBMIT_DEADLINE:Past submit deadline (%s) for session '%s'." % (dueDate, sheetName))
                                    else:
                                        raise Exception("Error:INVALID_LATE_TOKEN:Invalid token for late submission to session '"+sheetName+"'")
                                else:
                                    returnMessages.append("Warning:PAST_SUBMIT_DEADLINE:Past submit deadline (%s) for session '%s'." % (dueDate, sheetName))
                            elif (sliauth.epoch_ms(dueDate) - curTime) < 2*60*60*1000:
                                returnMessages.append("Warning:NEAR_SUBMIT_DEADLINE:Nearing submit deadline (%s) for session '%s'." % (dueDate, sheetName))

                if newRow:
                    # New user; insert row in sorted order of name (except for log files)
                    if (userId != MAXSCORE_ID and not displayName) or not rowUpdates:
                        raise Exception('Error::User name and row parameters required to create a new row for id '+userId+' in sheet '+sheetName)

                    if userId == MAXSCORE_ID:
                        userRow = numStickyRows+1
                    elif userId == TESTUSER_ID and not loggingSheet:
                        # Test user always appears after max score
                        maxScoreRow = lookupRowIndex(MAXSCORE_ID, modSheet, numStickyRows+1)
                        userRow = maxScoreRow+1 if maxScoreRow else numStickyRows+1
                    elif modSheet.getLastRow() > numStickyRows and not loggingSheet:
                        displayNames = modSheet.getSheetValues(1+numStickyRows, columnIndex['name'], modSheet.getLastRow()-numStickyRows, 1)
                        userIds = modSheet.getSheetValues(1+numStickyRows, columnIndex['id'], modSheet.getLastRow()-numStickyRows, 1)
                        userRow = numStickyRows + locateNewRow(displayName, userId, displayNames, userIds, TESTUSER_ID)
                    else:
                        userRow = modSheet.getLastRow()+1

                    modSheet.insertRowBefore(userRow, keyValue=userId)
                elif rowUpdates and nooverwriteRow:
                    if getRow:
                        # Simply return existing row
                        rowUpdates = None
                    else:
                        raise Exception('Error::Do not specify nooverwrite=1 to overwrite existing rows')

                maxCol = len(rowUpdates) if rowUpdates else len(columnHeaders)
                totalCol = fieldsMin+1 if (len(columnHeaders) > fieldsMin and columnHeaders[fieldsMin] == 'q_grades') else 0
                userRange = modSheet.getRange(userRow, 1, 1, maxCol)
                rowValues = userRange.getValues()[0]

                returnInfo['prevTimestamp'] = sliauth.epoch_ms(rowValues[columnIndex['Timestamp']-1]) if ('Timestamp' in columnIndex and rowValues[columnIndex['Timestamp']-1]) else None
                if returnInfo['prevTimestamp'] and params.get('timestamp','') and parseNumber(params.get('timestamp','')) and returnInfo['prevTimestamp'] > 1+parseNumber(params.get('timestamp','')):
                    ##returnMessages.append('Debug::prevTimestamp, timestamp: %s %s' % (returnInfo['prevTimestamp'] , params.get('timestamp','')) )
                    raise Exception('Error::Row timestamp too old by '+str(math.ceil(returnInfo['prevTimestamp']-parseNumber(params.get('timestamp','')))/1000)+' seconds. Conflicting modifications from another active browser session?')

                teamCopyCols = []
                if rowUpdates:
                    # Update all non-null and non-id row values
                    # Timestamp is always updated, unless it is specified by admin
                    if adminUser and sessionEntries and userId != MAXSCORE_ID and not importSession:
                        raise Exception("Error::Admin user not allowed to update full rows in sheet '"+sheetName+"'")

                    if submitTimestampCol and rowUpdates[submitTimestampCol-1] and userId != TESTUSER_ID:
                        raise Exception("Error::Submitted session cannot be re-submitted for sheet '"+sheetName+"'")

                    if (not adminUser or importSession) and len(rowUpdates) > fieldsMin:
                        # Check if there are any user provided non-null values for "extra" columns (i.e., response/explain values:
                        nonNullExtraColumn = False
                        totalCells = []
                        adminColumns = {}
                        for j in range(fieldsMin, len(columnHeaders)):
                            if rowUpdates[j] is not None:
                                nonNullExtraColumn = True
                            hmatch = QFIELD_RE.match(columnHeaders[j])
                            if hmatch and hmatch.group(2) == 'grade':
                                # Grade value to summed
                                totalCells.append(colIndexToChar(j+1) + str(userRow))
                            if not hmatch or (hmatch.group(2) != 'response' and hmatch.group(2) != 'explain' and hmatch.group(2) != 'plugin'):
                                # Non-response/explain/plugin admin column
                                adminColumns[columnHeaders[j]] = 1

                        if nonNullExtraColumn and not adminUser:
                            # Blank out admin columns if any extra column is non-null
                            # Failsafe: ensures admin-entered grades will be blanked out if response/explain are updated
                            for j in range(fieldsMin, len(columnHeaders)):
                                if columnHeaders[j] in adminColumns:
                                    rowUpdates[j] = ''

                        if totalCol and len(totalCells):
                            # Computed admin column to hold sum of all grades
                            rowUpdates[totalCol-1] = ( '=' + '+'.join(totalCells) )

                        ##returnMessages.append("Debug::"+str(nonNullExtraColumn)+str(adminColumns.keys())+'=' + '+'.join(totalCells))

                    ##returnMessages.append("Debug:ROW_UPDATES:"+str(rowUpdates))
                    for j in range(len(rowUpdates)):
                        colHeader = columnHeaders[j]
                        colValue = rowUpdates[j]
                        if colHeader == 'Timestamp':
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

                    # Copy user info from roster (if available)
                    for j in range(len(rosterValues)):
                        rowValues[j] = rosterValues[j]

                    # Save updated row
                    userRange.setValues([rowValues])

                    if paramId == TESTUSER_ID and sessionEntries and adminPaced:
                        lastSlideCol = columnIndex.get('lastSlide')
                        if lastSlideCol and rowValues[lastSlideCol-1]:
                            # Copy test user last slide number as new adminPaced value
                            setValue(sheetName, 'adminPaced', rowValues[lastSlideCol-1], INDEX_SHEET)
                        if params.get('submit'):
                            # Use test user submission time as due date for admin-paced sessions
                            submitTimestamp = rowValues[submitTimestampCol-1]
                            setValue(sheetName, 'dueDate', submitTimestamp, INDEX_SHEET)
                            idColValues = getColumns('id', modSheet, 1, 1+numStickyRows)
                            initColValues = getColumns('initTimestamp', modSheet, 1, 1+numStickyRows)
                            for j in range(len(idColValues)):
                                # Submit all other users who have started a session
                                if initColValues[j] and idColValues[j] and idColValues != TESTUSER_ID and idColValues[j] != MAXSCORE_ID:
                                    setValue(idColValues[j], 'submitTimestamp', submitTimestamp, sheetName)

                elif selectedUpdates:
                    # Update selected row values
                    # Timestamp is updated only if specified in list
                    if not voteSubmission and not partialSubmission:
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
                            if alterSubmission:
                                if colValue is None:
                                    modValue = curDate
                                elif colValue:
                                    modValue = createDate(colValue)
                                else:
                                    # Unsubmit if blank value (also clear lateToken)
                                    modValue = ''
                                    modSheet.getRange(userRow, columnIndex['lateToken'], 1, 1).setValues([[ '' ]])
                                if modValue:
                                    returnInfo['submitTimestamp'] = modValue
                            elif partialSubmission:
                                modValue = curDate
                                returnInfo['submitTimestamp'] = modValue
                            elif adminUser and colValue:
                                modValue = createDate(colValue)

                        elif colHeader.endswith('_vote'):
                            if voteSubmission and colValue:
                                # Cannot un-vote, vote can be transferred
                                otherCol = columnIndex.get('q_other')
                                if not rowValues[headerColumn-1] and otherCol and sessionEntries.get('otherWeight') and sessionAttributes.get('shareAnswers'):
                                    # Tally newly added vote
                                    qshare = sessionAttributes['shareAnswers'].get(colHeader.split('_')[0]);
                                    if qshare:
                                        rowValues[otherCol-1] = str(int(rowValues[otherCol-1] or 0) + qshare.get('voteWeight',0))
                                        modSheet.getRange(userRow, otherCol, 1, 1).setValues([[ rowValues[otherCol-1] ]])
                            modValue = colValue

                        elif colValue is None:
                            # Do not modify field
                            pass

                        elif colHeader not in MIN_HEADERS and not colHeader.endswith('Timestamp'):
                            # Update row values for header (except for id, name, email, altid, *Timestamp)
                            if not restrictedSheet and not partialSubmission and not importSession and (headerColumn <= fieldsMin or not re.match("^q\d+_(comments|grade)$", colHeader)):
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
                                        # Broadcast grade/comments to all team members
                                        teamCopyCols.append(headerColumn)

                            modValue = colValue
                        else:
                            if rowValues[headerColumn-1] != colValue:
                                raise Exception("Error::Cannot modify column '"+colHeader+"'. Specify as 'null'")

                        if modValue is not None:
                            rowValues[headerColumn-1] = modValue
                            modSheet.getRange(userRow, headerColumn, 1, 1).setValues([[ rowValues[headerColumn-1] ]])


                if len(teamCopyCols):
                    nRows = modSheet.getLastRow()-numStickyRows
                    idValues = modSheet.getSheetValues(1+numStickyRows, columnIndex['id'], nRows, 1)
                    teamValues = modSheet.getSheetValues(1+numStickyRows, teamCol, nRows, 1)
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

                if (paramId != TESTUSER_ID or prevSubmitted) and sessionEntries and adminPaced:
                    returnInfo['adminPaced'] = adminPaced

                # Return updated timestamp
                returnInfo['timestamp'] = sliauth.epoch_ms(rowValues[columnIndex['Timestamp']-1]) if ('Timestamp' in columnIndex) else None

                returnValues = rowValues if getRow else []

                if not adminUser and not gradeDate and len(returnValues) > fieldsMin:
                    # If session not graded, Nullify columns to be graded
                    for j in range(fieldsMin, len(columnHeaders)):
                        if not columnHeaders[j].endswith('_response') and not columnHeaders[j].endswith('_explain') and not columnHeaders[j].endswith('_plugin'):
                            returnValues[j] = None
                elif not adminUser and gradeDate:
                    returnInfo['gradeDate'] = sliauth.iso_date(gradeDate, utc=True)

        # return json success results
        retObj = {"result": "success", "value": returnValues, "headers": returnHeaders,
                  "info": returnInfo,
                  "messages": '\n'.join(returnMessages)}

    except Exception, err:
        # if error, return this
        if Options['debug'] and not notrace:
            import traceback
            traceback.print_exc()

        retObj = {"result": "error", "error": err.message, "value": None,
                  "info": returnInfo,
                  "messages": '\n'.join(returnMessages)}

    if Options['debug'] and not notrace:
        print("DEBUG: RETOBJ", retObj['result'], retObj['messages'], file=sys.stderr)
    
    return retObj

def getRandomSeed():
    return int(random.random() * (2**32))

def createSession(sessionName, params):
    persistPlugins = {}
    for pluginName in params['plugins']:
        persistPlugins[pluginName] = {}

    return {'version': params.get('sessionVersion'),
	    'revision': params.get('sessionRevision'),
	    'paced': params.get('paceLevel', 0),
	    'submitted': None,
	    'displayName': '',
	    'source': '',
	    'team': '',
	    'lateToken': '',
	    'lastSlide': 0,
	    'randomSeed': getRandomSeed(),                     # Save random seed
        'expiryTime': sliauth.epoch_ms() + 180*86400*1000, # 180 day lifetime
        'startTime': sliauth.epoch_ms(),
        'lastTime': 0,
        'lastTries': 0,
        'remainingTries': 0,
        'tryDelay': 0,
	    'showTime': None,
        'questionShuffle': None,
        'questionsAttempted': {},
	    'hintsUsed': {},
	    'plugins': persistPlugins
	   }

def createSessionRow(sessionName, fieldsMin, params, userId, displayName='', email='', altid='', source=''):
    headers = params['sessionFields'] + params['gradeFields']
    idCol = headers.index('id') + 1
    nameCol = headers.index('name') + 1
    emailCol = headers.index('email') + 1
    altidCol = headers.index('altid') + 1
    session = createSession(sessionName, params)
    rowVals = []
    for header in headers:
        rowVals.append(None)
        if not header.endswith('_hidden') and not header.endswith('Timestamp'):
            if header in session:
                rowVals[-1] = session[header]

    rowVals[headers.index('source')] = source
    rowVals[headers.index('session_hidden')] = json.dumps(session)

    rosterSheet = getSheet(ROSTER_SHEET, optional=True)
    if rosterSheet:
        rosterVals = lookupValues(userId, MIN_HEADERS, ROSTER_SHEET, True)
        if not rosterVals:
            raise Exception('User ID '+userId+' not found in roster')

        for j in range(len(rosterVals)):
            if rosterVals[j]:
                rowVals[j] = rosterVals[j]

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
        token = sliauth.gen_admin_token(Options['auth_key'], 'admin')
    else:
        token = sliauth.gen_user_token(Options['auth_key'], userId)
    getParams = {'id': userId, 'token': token,'sheet': sessionName,
                 'name': displayName, 'get': '1'}
    getParams.update(opts)

    return sheetAction(getParams, notrace=notrace)

def getAllRows(sessionName, opts={}, notrace=False):
    token = sliauth.gen_admin_token(Options['auth_key'], 'admin')
    getParams = {'admin': 'admin', 'token': token,'sheet': sessionName,
                 'get': '1', 'all': '1'}
    getParams.update(opts)

    return sheetAction(getParams, notrace=notrace)

def putUserRow(sessionName, userId, rowValues, opts={}, notrace=False):
    if opts.get('admin'):
        token = sliauth.gen_admin_token(Options['auth_key'], 'admin')
    else:
        token = sliauth.gen_user_token(Options['auth_key'], userId)
    putParams = {'id': userId, 'token': token,'sheet': sessionName,
                 'row': json.dumps(rowValues, default=sliauth.json_default)}
    putParams.update(opts)

    return sheetAction(putParams, notrace=notrace)

def updateUserRow(sessionName, headers, updateObj, opts={}, notrace=False):
    if opts.get('admin'):
        token = sliauth.gen_admin_token(Options['auth_key'], 'admin')
    else:
        token = sliauth.gen_user_token(Options['auth_key'], updateObj['id'])
    token = sliauth.gen_admin_token(Options['auth_key'], 'admin')
    updates = []
    for j, header in enumerate(headers):
        if header in updateObj:
            updates.append( [header, updateObj[header]] )

    updateParams = {'id': updateObj['id'], 'token': token,'sheet': sessionName,
                    'update': json.dumps(updates, default=sliauth.json_default)}
    updateParams.update(opts)

    return sheetAction(updateParams, notrace=notrace)

def makeRosterMap(colName, lowercase=False):
    # Return map of other IDs from colName to roster ID
    colValues = lookupRoster(colName) or {}
    rosterMap = OrderedDict()
    for userId, otherIds in colValues.items():
        if colName == 'name':
            comps = [otherIds]
        else:
            comps = otherIds.strip().split(',')
        for otherId in comps:
            otherId = otherId.strip()
            if lowercase:
                otherId = otherId.lower()
            if otherId:
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
        
    if Options['debug']:
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
            session = json.loads(session_hidden)
            qShuffle = session.get('questionShuffle')
            qAttempted = session['questionsAttempted']
            if qAttempted:
                qmaxRow = max(qmaxRow, max(int(key) for key in qAttempted.keys()) ) # Because JSON serialization converts integer keys to strings
        qmaxAll = max(qmaxAll, qmaxRow)

        rowOutput = [sliauth.str_encode(rowValues[headerCols[hdr]-1]) for hdr in MIN_HEADERS]
        for qnumber in range(1,qmaxRow+1):
            qnumberStr = str(qnumber)  # Because JSON serialization converts integer keys to strings
            cellValue = ''
            if qnumber in responseCols:
                cellValue = rowValues[responseCols[qnumber]-1]
                if qnumber in explainCols:
                    cellValue += ' ' + rowValues[explainCols[qnumber]-1]
            elif qAttempted and qnumberStr in qAttempted:
                cellValue = qAttempted[qnumberStr].get('response','')
                if qAttempted[qnumberStr].get('explain',''):
                    explainSet.add(qnumber)
                    cellValue += ' ' + sliauth.str_encode(qAttempted[qnumberStr]['explain'])
            if cellValue == SKIP_ANSWER:
                cellValue = ''
            if cellValue and qShuffle:
                shuffleStr = qShuffle.get(qnumberStr,'') or qShuffle.get(qnumber,'')
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
    retval = getUserRow(sessionName, userId, displayName, {'admin': 'admin', 'import': '1', 'create': create, 'getheaders': '1'}, notrace=True)
    if retval['result'] != 'success':
	    raise Exception('Error in creating session for user '+userId+': '+retval.get('error'))
    headers = retval['headers']
    if lateToken:
        updateObj = {'id': userId, 'lateToken': lateToken}
        retval = updateUserRow(sessionName, headers, updateObj, {'admin': 'admin', 'import': '1'})
        if retval['result'] != 'success':
            raise Exception('Error in setting late token for user '+userId+': '+retval.get('error'))

def createQuestionAttempted(response):
    return {'response': response or ''};


def importUserAnswers(sessionName, userId, displayName='', answers={}, submitDate=None, source=''):
    # answers = {1:{'response':, 'explain':},...}
    if Options['debug']:
        print("DEBUG:importUserAnswers", sessionName, submitDate, userId, displayName, answers, file=sys.stderr)
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
    retval = getUserRow(sessionName, userId, displayName, {'admin': 'admin', 'import': '1', 'create': create, 'getheaders': '1'}, notrace=True)
    if retval['result'] != 'success':
	    raise Exception('Error in creating session for user '+userId+': '+retval.get('error'))
    headers = retval['headers']
    rowValues = retval['value']
    headerCols = dict((hdr, j+1) for j, hdr in enumerate(headers))
    sessionCol = headerCols['session_hidden']
    session = json.loads(rowValues[sessionCol-1])
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
        qnumberStr = str(qnumber)  # Because JSON serialization converts integer keys to strings
        if qShuffle:
            shuffleStr = qShuffle.get(qnumberStr,'') or qShuffle.get(qnumber,'')
            if shuffleStr and respVal:
                # Import shuffled response value
                indexVal = ord(respVal.upper()) - ord('A')
                if indexVal < 0 or indexVal >= len(shuffleStr[1:]):
                    raise Exception('Error in creating session for user '+userId+': Invalid shuffle choice '+respVal+' ('+shuffleStr+')')
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

    putOpts = {'admin': 'admin', 'import': '1' }
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

    if Options['debug']:
        print("DEBUG:importUserAnswers2", sessionName, userId, adminPaced, file=sys.stderr)
            
    retval = putUserRow(sessionName, userId, rowValues, putOpts)
    if retval['result'] != 'success':
	    raise Exception('Error in importing session for user '+userId+': '+retval.get('error'))

    if submitTimestamp:
        updateObj = {'id': userId, 'submitTimestamp': submitTimestamp}
        retval = updateUserRow(sessionName, headers, updateObj, {'admin': 'admin', 'import': '1'})
        if retval['result'] != 'success':
            raise Exception('Error in submitting imported session for user '+userId+': '+retval.get('error'))


def lookupRoster(field, userId=None):
    rosterSheet = getSheet(ROSTER_SHEET, optional=True)
    if not rosterSheet:
        return None

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
    # Lowercase, replace '" with null, all other non-alphanumerics with spaces,
    # replace 'a', 'an', 'the' with space, and then normalize spaces
    if isinstance(s, unicode):
        s = s.encode('utf-8')
    s = str(s)
    return MSPACE_RE.sub(' ', WUSCORE_RE.sub(' ', ARTICLE_RE.sub(' ', s.lower().replace("'",'').replace('"','') ))).strip()


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
        return sliauth.parse_date(date) if date else ''
    else:
        # Create date from local epoch time (in ms)
        return sliauth.create_date(date)


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
    indexSheet.setSheetValues(sessionRow, indexColIndex[colName], 1, 1, [[colValue]])

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
        
        
