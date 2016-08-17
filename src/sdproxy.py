"""
Python proxy supporting 

Caches an in-memory copy of Google Sheet sheets and updates them using the same REST interface as slidoc_sheets.js.

Updates the Google Sheets version, using one active REST request at a time.

admin commands:
    /_shutdown         Initiate clean shutdown (transmitting cache updates)
    /_lock/session     Lock session (before direct editing of Google Sheet)
    /_unlock/session   Unlock session (after direct edits are completed)
    /_lock             List locked sessions (* => still trasmitting cache updates)
    /_stats            Display update statistics
"""

import datetime
import json
import math
import md5
import re
import sys
import time
import urllib
import urllib2

import tornado.httpclient
from tornado.ioloop import IOLoop

import sliauth

MIN_WAIT_TIME = 0       # Minimum time (sec) between successful Google Sheet requests
RETRY_WAIT_TIME = 5     # Minimum time (sec) before retrying failed Google Sheet requests
RETRY_MAX_COUNT = 5     # Maximum number of failed Google Sheet requests
CACHE_HOLD_TIME = 3600  # Maximum time (sec) to hold sheet in cache

DEBUG = None           # Set by sdserver after import
SHEET_URL = None       # Set by sdserver after import
HMAC_KEY = None        # Set by sdserver after import

# Should be consistent with slidoc_sheets.js
ADMIN_USER = 'admin'

REQUIRE_LOGIN_TOKEN = True
REQUIRE_LATE_TOKEN = True
SHARE_AVERAGES = False

MAXSCORE_ID = '_max_score'
AVERAGE_ID = '_average'
TESTUSER_ID = '_test_user'   #var

MIN_HEADERS = ['name', 'id', 'email', 'altid']
TESTUSER_ROSTER = ['-user, -test', TESTUSER_ID, '', '']  #var

INDEX_SHEET = 'sessions_slidoc'
ROSTER_SHEET = 'roster_slidoc'
SCORES_SHEET = 'scores_slidoc'

TRUNCATE_DIGEST = 8

QFIELD_RE = re.compile(r"^q(\d+)_([a-z]+)(_[0-9\.]+)?$")

def http_post(url, params_dict):
    data = urllib.urlencode(params_dict)
    req = urllib2.Request(url, data)
    try:
        response = urllib2.urlopen(req)
    except Exception, excp:
        raise Exception('ERROR in accessing URL %s: %s' % (url, excp))
    result = response.read()
    try:
        result = json.loads(result)
    except Exception, excp:
        pass
    return result

Shutting_down = False
Sheet_cache = {}
Lock_cache = {}

def getSheet(sheetName, optional=False):
    if Shutting_down or sheetName in Lock_cache:
        raise Exception('Sheet %s is locked!' % sheetName)

    if sheetName in Sheet_cache:
        return Sheet_cache[sheetName]

    user = 'admin'
    userToken = sliauth.gen_admin_token(HMAC_KEY, user)

    getParams = {'sheet': sheetName, 'proxy': '1', 'get': '1', 'all': '1', 'admin': user, 'token': userToken}
    if DEBUG:
        print "DEBUG:getSheet", sheetName, getParams

    if DEBUG and not SHEET_URL:
        return None

    retval = http_post(SHEET_URL, getParams) if SHEET_URL else {'result': 'error', 'error': 'No Sheet URL'}
    if DEBUG:
        print "DEBUG:getSheet", sheetName, retval['result']
    if retval['result'] != 'success':
        if optional and retval['error'].startswith('Error:NOSHEET:'):
            return None
        else:
            raise Exception("Error in accessing sheet '%s': %s" % (sheetName, retval['error']))
    rows = retval.get('value')
    if not rows:
        raise Exception("Empty sheet '%s'" % sheetName)
    keyHeader = '' if sheetName.endswith('_log') else 'id'
    Sheet_cache[sheetName] = Sheet(sheetName, rows, keyHeader=keyHeader)
    return Sheet_cache[sheetName]

def createSheet(sheetName, headers):
    if Shutting_down or sheetName in Lock_cache:
        raise Exception('Sheet %s is locked!' % sheetName)

    if not headers:
        raise Exception("Must specify headers to create sheet %s" % sheetName)
    keyHeader = '' if sheetName.endswith('_log') else 'id'
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

    def insertRowBefore(self, rowNum, keyValue=None):
        if rowNum < 2 or rowNum > len(self.xrows)+1:
            raise Exception('Invalid row number for insertion: %s' % rowNum)
        self.modTime = sliauth.epoch_ms()
        self.accessTime = self.modTime
        newRow = [None]*self.nCols
        if self.keyHeader:
            if keyValue is None:
                raise Exception('Must specify key for row insertion in sheet '+self.name)
            if keyValue in self.keyMap:
                raise Exception('Duplicate key %s for row insertion in sheet %s' % (self.name, keyValue))
            self.keyMap[keyValue] = self.modTime
            newRow[self.keyCol-1] = keyValue
        else:
            if rowNum != len(self.xrows)+1:
                raise Exception('Can only append row for non-keyed spreadsheet')
            self.keyMap[rowNum] = self.modTime

        self.xrows.insert(rowNum-1, newRow)

    def checkRange(self, rowMin, colMin, rowCount, colCount):
        if rowMin < 1 or rowMin > len(self.xrows):
            raise Exception('Invalid min row number for range: %s' % rowMin)
        if rowCount < 0 or rowCount > len(self.xrows)-rowMin+1:
            raise Exception('Invalid row count for range: %s' % rowCount)

        if colMin < 1 or colMin > self.nCols:
            raise Exception('Invalid min col number for range: %s' % colMin)
        if colCount < 0 or colCount > self.nCols-colMin+1:
            raise Exception('Invalid col count for range: %s' % colCount)

    def getRange(self, rowMin, colMin, rowCount, colCount):
        self.checkRange(rowMin, colMin, rowCount, colCount)
        return Range(self, rowMin, colMin, rowCount, colCount)

    def getSheetValues(self, rowMin, colMin, rowCount, colCount):
        self.accessTime = sliauth.epoch_ms()
        self.checkRange(rowMin, colMin, rowCount, colCount)
        return [row[colMin-1:colMin+colCount-1] for row in self.xrows[rowMin-1:rowMin+rowCount-1]]

    def setSheetValues(self, rowMin, colMin, rowCount, colCount, values):
        if Shutting_down or self.name in Lock_cache:
            raise Exception('Sheet %s is locked!' % self.name)
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


CacheRequestTime = 0
CacheResponseTime = 0
CacheUpdateTime = sliauth.epoch_ms()

CacheRetryCount = 0
CacheWaitTime = 0

TotalCacheResponseInterval = 0
TotalCacheResponseCount = 0
TotalCacheRetryCount = 0

CachePendingUpdate = None
def schedule_update(waitSec=0, force=False):
    global CachePendingUpdate
    if CachePendingUpdate:
        IOLoop.current().remove_timeout(CachePendingUpdate)
        CachePendingUpdate = None

    if waitSec:
        CachePendingUpdate = IOLoop.current().call_later(waitSec, update_remote_sheets)
    else:
        update_remote_sheets(force=force)

def start_shutdown():
    global Shutting_down
    Shutting_down = True
    print >> sys.stderr, "Initiated shutdown"
    schedule_update(force=True)

def check_shutdown():
    if not Shutting_down:
        return
    print >> sys.stderr, "Completing shutdown"
    IOLoop.current().stop()

def get_locked():
    # Return list of locked sheet name (* if updates not yet send to Google sheets)
    locked = []
    for sheetName in Lock_cache:
        if sheetName in Sheet_cache and Sheet_cache[sheetName].get_updates(CacheUpdateTime) is not None:
            locked.append(sheetName+'*')
        else:
            locked.append(sheetName)
    locked.sort()
    return locked

def update_remote_sheets(force=False):
    global CacheRequestTime

    if not SHEET_URL:
        check_shutdown()
        return

    if CacheRequestTime:
        return

    cur_time = sliauth.epoch_ms()
    if not force and (cur_time - CacheResponseTime) < MIN_WAIT_TIME:
        schedule_update(cur_time-CacheResponseTime)
        return

    modRequests = []
    curTime = sliauth.epoch_ms()
    for sheetName, sheet in Sheet_cache.items():
        # Check each cached sheet for updates
        updates = sheet.get_updates(CacheUpdateTime)
        if updates is None:
            if curTime-sheet.accessTime > CACHE_HOLD_TIME:
                # Cache entry has expired
                del Sheet_cache[sheetName]
            continue
        # sheet_name, headers_list, keys_dictionary, modified_rows
        modRequests.append([sheetName, updates[0], updates[1], updates[2]])

    if not modRequests:
        # Nothing to update
        check_shutdown()
        return

    if DEBUG:
        print "update_remote_sheets:", [(x[0], [y[0] for y in x[3]]) for x in modRequests]

    user = 'admin'
    userToken = sliauth.gen_admin_token(HMAC_KEY, user)

    http_client = tornado.httpclient.AsyncHTTPClient()
    post_data = { 'proxy': '1', 'allupdates': '1', 'admin': user, 'token': userToken,
                  'data': json.dumps(modRequests, default=sliauth.json_default) }
    post_data['create'] = 1
    body = urllib.urlencode(post_data)
    http_client.fetch(SHEET_URL, handle_http_response, method='POST', headers=None, body=body)
    CacheRequestTime = cur_time


def handle_http_response(response):
    global CacheRequestTime, CacheResponseTime, CacheUpdateTime, CacheRetryCount, CacheWaitTime, TotalCacheResponseInterval, TotalCacheResponseCount, TotalCacheRetryCount

    CacheResponseTime = sliauth.epoch_ms()
    TotalCacheResponseInterval += (CacheResponseTime - CacheRequestTime)
    TotalCacheResponseCount += 1

    errMsg = ""
    if response.error:
        print >> sys.stderr, "handle_http_response: Update error:", response.error
        errMsg = response.error
        if Shutting_down or CacheRetryCount > RETRY_MAX_COUNT:
            sys.exit('Failed to update cache after %d tries' % RETRY_MAX_COUNT)
        CacheRequestTime = 0
        CacheRetryCount += 1
        TotalCacheRetryCount += 1
        CacheWaitTime += RETRY_WAIT_TIME
        schedule_update(CacheWaitTime)
    else:
        if DEBUG:
            print "handle_http_response:", response.body
        try:
            respObj = json.loads(response.body)
            if respObj['result'] == 'error':
                errMsg = respObj['error']
        except Exception, err:
            errMsg = 'JSON parsing error: '+str(err)

        if errMsg:
            print >> sys.stderr, "handle_http_response: Update error:", errMsg
            sys.exit(errMsg)

    if not errMsg:
        # Update succeeded
        if DEBUG:
            print "handle_http_response:", CacheUpdateTime, respObj

        CacheUpdateTime = CacheRequestTime
        CacheRequestTime = 0
        CacheRetryCount = 0
        CacheWaitTime = 0
        schedule_update(0 if Shutting_down else MIN_WAIT_TIME)

        
def handleResponse(params):
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
    # Can add row with fewer columns than already present.
    # This allows user to add additional columns without affecting script actions.
    # (User added columns are returned on gets and selective updates, but not row updates.)
    
    # shortly after my original solution Google announced the LockService[1]
    # this prevents concurrent access overwritting data
    # [1] http://googleappsdeveloper.blogspot.co.uk/2011/10/concurrency-and-google-apps-script.html
    # we want a public lock, one that locks for all invocations

    if DEBUG:
        print "DEBUG: handleResponse PARAMS", params

    returnValues = None
    returnHeaders = None
    returnInfo = {}
    returnMessages = []

    try:
        sheetName = params.get('sheet','')
        if not sheetName:
            raise Exception('Error:SHEETNAME::No sheet name specified')

        adminUser = ''
        authUser = ''
        paramId = params.get('id','') #var

        if params.get('admin',''):
            if not params.get('token',''):
                raise Exception('Error:NEED_ADMIN_TOKEN:Need token for admin authentication')
            if not validateHMAC('admin:'+params.get('admin','')+':'+params.get('token',''), HMAC_KEY):
                raise Exception("Error:INVALID_ADMIN_TOKEN:Invalid token for authenticating admin user '"+params.get('admin','')+"'")
            adminUser = params.get('admin','')
        elif REQUIRE_LOGIN_TOKEN:
            if not paramId:
                raise Exception('Error:NEED_ID:Need id for authentication')
            if not params.get('token',''):
                raise Exception('Error:NEED_TOKEN:Need token for id authentication')
            if not validateHMAC('id:'+paramId+':'+params.get('token',''), HMAC_KEY):
                raise Exception("Error:INVALID_TOKEN:Invalid token for authenticating id '"+paramId+"'")
            authUser = paramId

        protectedSheet = (sheetName == SCORES_SHEET)
        restrictedSheet = (sheetName.endswith('_slidoc') and not protectedSheet)
        loggingSheet = sheetName.endswith('_log')

        sessionParams = None
        sessionAttributes = None
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

        # Update/access single sheet

        if not restrictedSheet and not protectedSheet and not loggingSheet and getSheet(INDEX_SHEET):
            # Indexed session
            sessionParams = lookupValues(sheetName, ['dueDate', 'gradeDate', 'otherWeight', 'fieldsMin', 'attributes'], INDEX_SHEET)
            if sessionParams.get('attributes'):
                sessionAttributes = json.loads(sessionParams['attributes'])
            dueDate = sessionParams.get('dueDate')
            gradeDate = sessionParams.get('gradeDate')
            voteDate = createDate(sessionAttributes['voteDate']) if sessionAttributes and sessionAttributes.get('voteDate') else None


        # Check parameter consistency
        headers = json.loads(params.get('headers','')) if params.get('headers','') else None

        modSheet = getSheet(sheetName, optional=True)
        if not modSheet:
            if adminUser and headers is not None:
                modSheet = createSheet(sheetName, headers)
            else:
                raise Exception("Sheet %s not found!" % sheetName)

        if not modSheet.getLastColumn():
            raise Exception("Error::No columns in sheet '"+sheetName+"'")

        columnHeaders = modSheet.getSheetValues(1, 1, 1, modSheet.getLastColumn())[0]
        columnIndex = indexColumns(modSheet)

        if headers:
            if len(headers) > len(columnHeaders):
                raise Exception("Error::Number of headers exceeds that present in sheet '"+sheetName+"'; delete it or edit headers.")
            for j in range(len(headers)):
                if headers[j] != columnHeaders[j]:
                    raise Exception("Error::Column header mismatch: Expected "+headers[j]+" but found "+columnHeaders[j]+" in sheet '"+sheetName+"'; delete it or edit headers.")

        getRow = params.get('get','')
        getShare = params.get('getshare', '');
        allRows = params.get('all','')
        nooverwriteRow = params.get('nooverwrite','')

        selectedUpdates = json.loads(params.get('update','')) if params.get('update','') else None
        rowUpdates = json.loads(params.get('row','')) if params.get('row','') else None

        userId = None
        displayName = None

        voteSubmission = ''
        if not rowUpdates and selectedUpdates and len(selectedUpdates) == 2 and selectedUpdates[0][0] == 'id' and selectedUpdates[1][0][-5:] == '_vote' and sessionAttributes and sessionAttributes.get('shareAnswers'):
            qno = selectedUpdates[1][0].split('_')[0]
            voteSubmission = sessionAttributes['shareAnswers'][qno].get('share', '') if sessionAttributes['shareAnswers'].get(qno) else ''

        if not adminUser and selectedUpdates and not voteSubmission:
            raise Exception("Error::Only admin user allowed to make selected updates to sheet '"+sheetName+"'")

        if protectedSheet and (rowUpdates or selectedUpdates) :
            raise Exception("Error::Cannot modify protected sheet '"+sheetName+"'")

        numStickyRows = 1  # Headers etc.

        if getRow and params.get('getheaders',''):
            returnHeaders = columnHeaders
            try:
                temIndexRow = indexRows(modSheet, indexColumns(modSheet)['id'], 2)
                if temIndexRow.get(MAXSCORE_ID):
                    returnInfo['maxScores'] = modSheet.getSheetValues(temIndexRow.get(MAXSCORE_ID), 1, 1, len(columnHeaders))[0]
                if SHARE_AVERAGES and temIndexRow.get(AVERAGE_ID):
                    returnInfo['averages'] = modSheet.getSheetValues(temIndexRow.get(AVERAGE_ID), 1, 1, len(columnHeaders))[0]
            except Exception, err:
                pass

        if not rowUpdates and not selectedUpdates and not getRow and not getShare:
            # No row updates/gets
            returnValues = []
        elif getRow and allRows:
            # Get all rows and columns
            if modSheet.getLastRow() > numStickyRows:
                returnValues = modSheet.getSheetValues(1+numStickyRows, 1, modSheet.getLastRow()-numStickyRows, len(columnHeaders))
            else:
                returnValues = []

        elif getShare:
            # Return adjacent columns (if permitted by session index and corresponding user entry is non-null)
            if not sessionAttributes or not sessionAttributes.get('shareAnswers'):
                raise Exception('Error::Denied access to answers of session '+sheetName)
            shareParams = sessionAttributes['shareAnswers'].get(getShare)
            if not shareParams or not shareParams.get('share'):
                raise Exception('Error::Sharing not enabled for '+getShare+' of session '+sheetName)

            if not adminUser and shareParams['share'] == 'after_grading' and not gradeDate:
                returnMessages.append("Warning:SHARE_AFTER_GRADING:")
                returnValues = []
            elif not adminUser and shareParams['share'] == 'after_due_date' and (not dueDate or sliauth.epoch_ms(dueDate) > sliauth.epoch_ms(curDate)):
                returnMessages.append("Warning:SHARE_AFTER_DUE_DATE:")
                returnValues = []
            elif modSheet.getLastRow() <= numStickyRows:
                returnMessages.append("Warning:SHARE_NO_ROWS:")
                returnValues = []
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
                timeValues   = modSheet.getSheetValues(1+numStickyRows, columnIndex['Timestamp'], nRows, 1)
                submitValues = modSheet.getSheetValues(1+numStickyRows, columnIndex['submitTimestamp'], nRows, 1)
                lateValues   = modSheet.getSheetValues(1+numStickyRows, columnIndex['lateToken'], nRows, 1)

                curUserVals = None
                for j in range(nRows):
                    if idValues[j][0] == paramId:
                        curUserVals = shareSubrow[j]
                        break

                if not curUserVals and not adminUser:
                    raise Exception('Error::Sheet has no row for user '+paramId+' to share in session '+sheetName)

                votingCompleted = voteDate and sliauth.epoch_ms(voteDate) < sliauth.epoch_ms(curDate);

                tallyVotes = adminUser or shareParams.get('vote') == 'show_live' or (shareParams.get('vote') == 'show_completed' and votingCompleted)

                disableVoting = False

                # If test/admin user, or current user has provided no response/no explanation, disallow voting
                if paramId == TESTUSER_ID or not curUserVals or not curUserVals[0] or (explainOffset and not curUserVals[explainOffset]):
                    disableVoting = True

                # If voting not enabled or voting completed, disallow  voting.
                if not shareParams.get('vote') or votingCompleted:
                    disableVoting = True

                if voteOffset:
                    # Return user's vote codes
                    if curUserVals:
                        returnInfo['vote'] = curUserVals[voteOffset]
                    if tallyVotes:
                        votes = {}
                        for j in range(nRows):
                            for voteCode in shareSubrow[j][voteOffset].split(','):
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

                if shareOffset:
                    if curUserVals:
                        returnInfo['share'] = '' if disableVoting else curUserVals[shareOffset]
                        # Disable self voting
                        curUserVals[shareOffset] = ''
                    if disableVoting:
                        # This needs to be done after vote tallying, because vote codes are cleared
                        for j in range(nRows):
                            shareSubrow[j][shareOffset] = ''

                sortVals = []
                for j in range(nRows):
                    if idValues[j][0] == TESTUSER_ID:
                        # Ignore test user response
                        continue
                    # Use earlier of submit time or timestamp to sort
                    timeVal = submitValues[j][0] or timeValues[j][0]
                    timeVal =  sliauth.epoch_ms(timeVal) if timeVal else 0

                    # Skip incomplete/late submissions (but allow partials)
                    if not timeVal or (lateValues[j][0] and lateValues[j][0] != 'partial'):
                        continue
                    if not shareSubrow[j][0] or (explainOffset and not shareSubrow[j][1]):
                        continue

                    respVal = shareSubrow[j][0]
                    if parseNumber(respVal) is not None:
                        respVal = parseNumber(respVal)

                    if tallyVotes and (votingCompleted or adminUser):
                        # Sort by (-) vote tally and then by response
                        sortVals.append( [-shareSubrow[j][voteOffset], respVal, j])
                    elif explainOffset:
                        # Sort by response value and then time
                        sortVals.append( [respVal, timeVal, j] )
                    else:
                        # Sort by time and then response value
                        sortVals.append( [timeVal, respVal, j])

                sortVals.sort()

                ##returnMessages.append('Debug::getShare: '+str(nCols)+', '+str(nRows)+', '+str(sortVals)+', '+str(curUserVals)+'')
                returnValues = []
                for x, y, offset in sortVals:
                    returnValues.append( shareSubrow[offset] )

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
            userRow = -1
            if modSheet.getLastRow() > numStickyRows and not loggingSheet:
                # Locate ID row (except for log files)
                userIds = modSheet.getSheetValues(1+numStickyRows, columnIndex['id'], modSheet.getLastRow()-numStickyRows, 1)
                for j in range(len(userIds)):
                    # Unique ID
                    if userIds[j][0] == userId:
                        userRow = j+1+numStickyRows
                        break

            ##returnMessages.append('Debug::userRow, userid, rosterValues: '+userRow+', '+userId+', '+rosterValues)
            newRow = (userRow < 0)

            if adminUser and not restrictedSheet and newRow and userId != MAXSCORE_ID:
                raise Exception("Error::Admin user not allowed to create new row in sheet '"+sheetName+"'")

            if newRow and getRow and not rowUpdates:
                # Row does not exist return empty list
                returnValues = []

            elif newRow and selectedUpdates:
                raise Exception('Error::Selected updates cannot be applied to new row')
            else:
                allowLateMods = not REQUIRE_LATE_TOKEN
                pastSubmitDeadline = False
                partialSubmission = False
                fieldsMin = len(columnHeaders)

                prevSubmitted = None
                if not newRow and columnIndex.get('submitTimestamp'):
                    prevSubmitted = modSheet.getSheetValues(userRow, columnIndex['submitTimestamp'], 1, 1)[0][0] or None

                if sessionParams:
                    # Indexed session
                    fieldsMin = sessionParams.get('fieldsMin')

                    if dueDate and not prevSubmitted and not adminUser and not voteSubmission:
                        # Check if past submission deadline
                        lateTokenCol = columnIndex.get('lateToken')
                        lateToken = None
                        if lateTokenCol:
                            lateToken = (rowUpdates[lateTokenCol-1] or None)  if (rowUpdates and len(rowUpdates) >= lateTokenCol) else None
                            if not lateToken and not newRow:
                                lateToken = modSheet.getRange(userRow, lateTokenCol, 1, 1).getValues()[0][0] or None

                        curTime = sliauth.epoch_ms(curDate)
                        pastSubmitDeadline = (dueDate and curTime > sliauth.epoch_ms(dueDate))
                        if not allowLateMods and pastSubmitDeadline and lateToken:
                            if lateToken == 'partial':
                                if newRow or not rowUpdates:
                                    raise Exception("Error::Partial submission only works for pre-existing rows")
                                partialSubmission = True
                                rowUpdates = None
                                selectedUpdates = [ ['Timestamp', None], ['submitTimestamp', None], ['lateToken', lateToken] ]
                                returnMessages.append("Warning:PARTIAL_SUBMISSION:Partial submission by user '"+(displayName or "")+"' to session '"+sheetName+"'")
                            elif lateToken == 'none':
                                # Late submission without token
                                allowLateMods = True
                            else:
                                comps = splitToken(lateToken)
                                dateStr = comps[0]
                                tokenStr = comps[1]
                                if sliauth.gen_late_token(HMAC_KEY, userId, sheetName, dateStr) == lateToken:
                                    dueDate = createDate(dateStr) # Date format: '1995-12-17T03:24Z'
                                    pastSubmitDeadline = (curTime > sliauth.epoch_ms(dueDate))
                                else:
                                    returnMessages.append("Warning:INVALID_LATE_TOKEN:Invalid token for late submission by user '"+(displayName or "")+"' to session '"+sheetName+"'")

                        returnInfo['dueDate'] = dueDate
                        if not allowLateMods and not partialSubmission:
                            if pastSubmitDeadline:
                                if newRow or selectedUpdates or (rowUpdates and not nooverwriteRow):
                                    # Creating/modifying row; require valid lateToken
                                    if not lateToken:
                                        raise Exception("Error:PAST_SUBMIT_DEADLINE:Past submit deadline (%s) for session '%s'. (If valid excuse, request late submission token.)" % (dueDate, sheetName))
                                    else:
                                        raise Exception("Error:INVALID_LATE_TOKEN:Invalid token for late submission to session '"+sheetName+"'")
                                else:
                                    returnMessages.append("Warning:PAST_SUBMIT_DEADLINE:Past submit deadline (%s) for session '%s'. (If valid excuse, request late submission token.)" % (dueDate, sheetName))
                            elif (sliauth.epoch_ms(dueDate) - curTime) < 2*60*60*1000:
                                returnMessages.append("Warning:NEAR_SUBMIT_DEADLINE:Nearing submit deadline (%s) for session '%s'." % (dueDate, sheetName))

                if newRow:
                    # New user; insert row in sorted order of name (except for log files)
                    if (userId != MAXSCORE_ID and not displayName) or not rowUpdates:
                        raise Exception('Error::User name and row parameters required to create a new row for id '+userId+' in sheet '+sheetName)

                    temIndexRow = indexRows(modSheet, indexColumns(modSheet)['id'], 1+numStickyRows)
                    if userId == MAXSCORE_ID:
                        userRow = numStickyRows+1
                    elif userId == TESTUSER_ID and not loggingSheet:
                        # Test user always appears after max score
                        userRow = temIndexRow[MAXSCORE_ID]+1 if temIndexRow[MAXSCORE_ID] else numStickyRows+1
                    elif modSheet.getLastRow() > numStickyRows and not loggingSheet:
                        displayNames = modSheet.getSheetValues(1+numStickyRows, columnIndex['name'], modSheet.getLastRow()-numStickyRows, 1)
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

                if rowUpdates:
                    # Update all non-null and non-id row values
                    # Timestamp is always updated, unless it is specified by admin
                    if adminUser and not restrictedSheet and userId != MAXSCORE_ID:
                        raise Exception("Error::Admin user not allowed to update full rows in sheet '"+sheetName+"'")

                    submitTimestampCol = columnIndex.get('submitTimestamp')
                    if submitTimestampCol and rowUpdates[submitTimestampCol-1]:
                        raise Exception("Error::Already submitted session once in sheet '"+sheetName+"'")

                    if not adminUser and len(rowUpdates) > fieldsMin:
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
                            if not hmatch or (hmatch.group(2) != 'response' and hmatch.group(2) != 'explain'):
                                # Non-response/explain admin column
                                adminColumns[columnHeaders[j]] = 1

                        if nonNullExtraColumn:
                            # Blank out admin columns if any extra column is non-null
                            # Failsafe: ensures admin-entered grades will be blanked out if response/explain are updated
                            for j in range(fieldsMin, len(columnHeaders)):
                                if columnHeaders[j] in adminColumns:
                                    rowUpdates[j] = ''

                        if totalCol and len(totalCells):
                            # Computed admin column to hold sum of all grades
                            rowUpdates[totalCol-1] = ( '=' + '+'.join(totalCells) )

                        returnMessages.append("Debug::"+str(nonNullExtraColumn)+str(adminColumns.keys())+'=' + '+'.join(totalCells))

                    ##returnMessages.append("Debug:ROW_UPDATES:"+str(rowUpdates))
                    for j in range(len(rowUpdates)):
                        colHeader = columnHeaders[j]
                        colValue = rowUpdates[j]
                        if colHeader == 'Timestamp':
                            # Timestamp is always updated, unless it is explicitly specified by admin
                            if adminUser and colValue:
                                try:
                                    rowValues[j] = createDate(colValue)
                                except Exception, err:
                                    pass
                            else:
                                rowValues[j] = curDate

                        elif colHeader == 'initTimestamp' and newRow:
                            rowValues[j] = curDate
                        elif colHeader == 'submitTimestamp' and params.get('submit',''):
                            rowValues[j] = curDate
                            returnInfo['submitTimestamp'] = curDate

                        elif colHeader[-6:] == '_share':
                            # Generate share value by computing MD5 digest of 'response [: explain]'
                            if j >= 1 and rowValues[j-1] and columnHeaders[j-1][-9:] == '_response':
                                rowValues[j] = md5hex(rowValues[j-1])
                            elif j >= 2 and rowValues[j-1] and columnHeaders[j-1][-8:] == '_explain' and columnHeaders[j-2][-9:] == '_response':
                                rowValues[j] = md5hex(rowValues[j-1]+': '+rowValues[j-2])
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
                                rowValues[j] = colValue
                        else:
                            if rowValues[j] != colValue:
                                raise Exception("Error::Cannot modify column '"+colHeader+"'. Specify as 'null'")

                    # Copy user info from roster (if available)
                    for j in range(len(rosterValues)):
                        rowValues[j] = rosterValues[j]

                    # Save updated row
                    userRange.setValues([rowValues])

                elif selectedUpdates:
                    # Update selected row values
                    # Timestamp is updated only if specified in list
                    if not voteSubmission and not partialSubmission:
                        if not adminUser:
                            raise Exception("Error::Only admin user allowed to make selected updates to sheet '"+sheetName+"'")
                        if sessionParams:
                            # Indexed session: selected updates only after submission
                            submitTimestampCol = columnIndex.get('submitTimestamp')
                            if not (submitTimestampCol and rowValues[submitTimestampCol-1]):
                                raise Exception("Error::Cannot selectively update non-submitted session for user "+userId+" in sheet '"+sheetName+"'")

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
                                try:
                                    modValue = createDate(colValue)
                                except Exception, err:
                                    pass
                            else:
                                modValue = curDate

                        elif colHeader == 'submitTimestamp':
                            if partialSubmission:
                                modValue = curDate
                                returnInfo['submitTimestamp'] = curDate

                        elif colHeader[-5:] == '_vote':
                            if voteSubmission and colValue:
                                # Cannot un-vote, vote can be transferred
                                otherCol = columnIndex.get('q_other')
                                if not rowValues[headerColumn-1] and otherCol and sessionParams.get('otherWeight') and sessionAttributes and sessionAttributes.get('shareAnswers'):
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
                            if not restrictedSheet and not partialSubmission and (headerColumn <= fieldsMin or not re.match("^q\d+_(comments|grade)$", colHeader)):
                                raise Exception("Error::Cannot selectively update user-defined column '"+colHeader+"' in sheet '"+sheetName+"'")

                            if colHeader.lower().endswith('date') or colHeader.lower().endswith('time'):
                                try:
                                    colValue = createDate(colValue)
                                except Exception, err:
                                    pass

                            modValue = colValue
                        else:
                            if rowValues[headerColumn-1] != colValue:
                                raise Exception("Error::Cannot modify column '"+colHeader+"'. Specify as 'null'")

                        if modValue is not None:
                            rowValues[headerColumn-1] = modValue
                            modSheet.getRange(userRow, headerColumn, 1, 1).setValues([[ rowValues[headerColumn-1] ]])


                # Return updated timestamp
                returnInfo['timestamp'] = sliauth.epoch_ms(rowValues[columnIndex['Timestamp']-1]) if ('Timestamp' in columnIndex) else None

                returnValues = rowValues if getRow else []

                if not adminUser and not gradeDate and len(returnValues) > fieldsMin:
                    # If session not graded, Nullify columns to be graded
                    for j in range(fieldsMin, len(columnHeaders)):
                        returnValues[j] = None
                elif not adminUser and gradeDate:
                    returnInfo['gradeDate'] = sliauth.iso_date(gradeDate, utc=True)

        # return json success results
        retObj = {"result": "success", "value": returnValues, "headers": returnHeaders,
                  "info": returnInfo,
                  "messages": '\n'.join(returnMessages)}

    except Exception, err:
        # if error, return this
        if DEBUG:
            import traceback
            traceback.print_exc()

        retObj = {"result": "error", "error": err.message, "value": None,
                  "messages": '\n'.join(returnMessages)}

    if DEBUG:
        print "DEBUG: RETOBJ", retObj['result'], retObj['messages']
    
    return retObj

def md5hex(s, n=TRUNCATE_DIGEST):
    return md5.new(s).hexdigest()[:n];

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
    if type(date) in (str, unicode):
        return sliauth.parse_date(date)
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
    return chr(ord('A') + col - 1)


def indexColumns(sheet):
    columnHeaders = sheet.getSheetValues(1, 1, 1, sheet.getLastColumn())[0]
    columnIndex = {}
    for j, columnHeader in enumerate(columnHeaders):
        columnIndex[columnHeader] = j+1
    return columnIndex


def indexRows(sheet, indexCol, startRow):
    rowIndex = {}
    nRows = sheet.getLastRow()-startRow+1
    if nRows > 0:
        rowIds = sheet.getSheetValues(startRow, indexCol, sheet.getLastRow()-startRow+1, 1)
        for j, rowId in enumerate(rowIds):
            rowIndex[rowId[0]] = j+startRow
    return rowIndex


def getColumns(header, sheetName, colCount, skipRows):
    skipRows = skipRows or 1
    sheet = getSheet(sheetName)
    colIndex = indexColumns(sheet)
    if header not in colIndex:
        raise Exception('Column '+header+' not found in sheet '+sheetName)

    if colCount and colCount > 1:
        # Multiple columns (list of lists)
        return sheet.getSheetValues(1+skipRows, colIndex[header], sheet.getLastRow()-skipRows, colCount)
    else:
        # Single column
        vals = sheet.getSheetValues(1+skipRows, colIndex[header], sheet.getLastRow()-skipRows, 1)
        retvals = []
        for val in vals:
            retvals.append(val[0])
        return retvals


def lookupValues(idValue, colNames, sheetName, listReturn=False):
    # Return parameters in list colNames for idValue from sessions_slidoc sheet
    indexSheet = getSheet(sheetName)
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

def locateNewRow(newName, newId, nameValues, idValues, skipId=None):
    # Return row number before which new name/id combination should be inserted
    for j in range(len(nameValues)):
        if skipId and skipId == idValues[j][0]:
            continue
        if nameValues[j][0] > newName or (nameValues[j][0] == newName and idValues[j][0] > newId):
            # Sort by name and then by id
            return j+1
    return len(nameValues)+1
