// slidoc_sheets.js: Google Sheets add-on to interact with Slidoc documents

var VERSION = '0.97.7b';

var DEFAULT_SETTINGS = [ ['auth_key', 'testkey', 'Secret value for secure administrative access (obtain from proxy for multi-site setup)'],

			 ['server_url', '', 'Base URL of server (if any); e.g., http://example.com'],
			 [],
                         ['site_name', '', 'Site name, e.g., calc101, for multi-site setup (must match proxy)'],
			 ['site_label', 'Site name', 'Site label, e.g., Calculus 101'],
			 ['site_title', 'Site description', 'Descriptive site title'],
			 ['site_access', '', "'' OR 'adminonly' OR 'adminguest' OR 'readonly'"],
                         ['twitter_config', '', 'Twitter stream config: username,consumer_key,consumer_secret,access_key,access_secret'],
			 [],
			 ['admin_users', '', 'User IDs or email addresses with admin access'],
			 ['grader_users', '', 'User IDs or email addresses with grader access'],
			 ['guest_users', '', 'User IDs or email addresses with guest access'],
			 [],
			 ['start_date', '', 'Date after which all session releases must start'],
			 ['freeze_date', '', 'Date when all user modifications are disabled'],
			 ['require_login_token', 'require', 'Non-null string for true'],
			 ['require_late_token', 'require', 'Non-null string for true'],
			 ['share_averages', 'require', 'Non-null string for true'],
		         ['total_formula', '', 'Formula for gradebook total column, e.g., 0.4*_Assignment_avg_1+0.5*_Quiz_sum+10*_Test_normavg+0.1*_Extra01'],
			 ['grading_scale', '', 'A:90%:4,B:80%:3,C:70%:2,D:60%:1,F:0%:0'], // Or A:180:4,B:160:3,...
			 ['proxy_update_cache', '', 'Used to cache response to last update request (not user configured)']   
		       ];

// Add settings of the form 'session_assignment' = '--pace=2 ...'

//
// SENDING FORM DATA TO GOOGLE SHEETS
//     http://railsrescue.com/blog/2015-05-28-step-by-step-setup-to-send-form-data-to-google-sheets/
//     https://gist.github.com/mhawksey/1276293

//  1. Navigate to drive.google.com and click on NEW > Google Sheets to create a new Sheet.
//     Rename it to your course/project name.
//
//  2. Click on Tools > Script Editor, creating the script Code.gs.
//     Overwrite the template code with this code and Save, using new project name Slidoc
//
//  3. Run > setup. Click on the right-pointing triangle to its left to run this function.
//     It should show 'Running function setup’ and then put up a dialog 'Authorization Required’.
//     Click on Continue.
//     In the next dialog select 'Review permissions'
//     When you see 'Slidoc would would like to manage spreadsheets ... data ...’ click on Allow.
//
//  4. The previous setup step will create a sheet named 'settings_slidoc'. In this sheet,
//       set auth_key to your secret key string (also used in the --auth_key=... option)
//       set require_login_token to true, if users need a login token.
//       set require_late_token to true, if users need a late submission token to submit late.
//       (These tokens can be generated using the command sliauth.py)
//       set share_averages to true if class averages for tests should be shared.
//
//  5. File > Manage Versions… We must save a version of the script for it to be called.
//     In the box labeled 'Describe what has changed’ type 'Initial version’ and click on 'Save New Version’, then on 'OK’.
//
//  6. Resources > Current project’s triggers.
//     In this dialog click on 'No triggers set up. Click here to add one now’.
//     In the dropdowns select 'onOpen’, 'From spreadsheet’, and 'On open’.
//     Click on 'Add a new trigger'
//     In the dropdowns select 'doPost’, 'From spreadsheet’, and 'On form submit’.
//     Then click on 'Save’.
// 
//  7. click on Publish > Deploy as web app…
//     Leave Project Version as '1’ and 'Execute the app as:’ set to 'Me’.
//     For 'Who has access to the app:’ select 'Anyone, even anonymous’.
//     Click the 'Deploy’ button.
//     This project is now deployed as a web app.
//     Copy the 'Current web app URL' from the dialog,
//     and use at as the argument to slidoc command:
//       slidoc.py --gsheet_url=https://script.google.com/macros/s/... --auth_key=AUTH_KEY ...
//
//  8. If you make any further changes to this script, Save it and then click on Publish > Deploy as web app…
//       Change Project Version to New and click Update (the web app URL remains the same)
//       (If you changed the menu, you may need to close the spreadsheet and re-open it to see the changes.)
//
// ROSTER
//  You may optionally create a 'roster_slidoc' sheet containing ['name', 'id', 'email', 'altid'] in the first four columns.
//  The 'name', 'email' and 'altid' values will be copied from this column to sesssion sheets (using 'id' as the index).
//  Names should be of the form 'last name(s), first_name middle_name ...'. Rows should be sorted by name.
//  If roster_slidoc sheet is present and userID is not present in it, user will not be allowed to access sessions.
//
//  The order and content of the roster entries determine the corresponding entries in the score sheet as well.
//
//  The first row after the header row may contain the special test user entry with TESTUSER_ID.
//  There can be zero or more additional rows with special display names starting with a hash (#).
//  Such rows and any test user row will be excluded from class averages etc.
//
//  An additional column named twitter may be used to map twitter IDs to session IDs.
//  
//
// USING THE SLIDOC MENU
//  - After installing this script, quit the spreadsheet and re-open to activate the Slidoc menu. You will see:
//
//  - "Display session answers" to create/overwrite the sheet
//    'sessionName-answers' displaying all the answers
//
//  - "Display session statistics" to create/overwrite the sheet
//    'sessionName-stats' displaying session statistics
//
//  - "Update scores for sessions" to update score for all sessions
//    in the 'scores_slidoc' sheet (which is automatically created, if need be)
//
// You may also create the 'scores_slidoc' sheet yourself:
//   - Put headers in the first row. The first four are usually 'name', 'id', 'email', 'altid'
//   - 'id' is the only required column, which should be unique for each user and used to index sessions.
//   - a column is created for each session, with an underscore prefixed to the session name.
//   - Any custom header names should not begin with an underscore, to avoid being mistaken for session names.
//   - "Update scores for session" menu action will only update session columns with lookup formulas.
//   - If you add new user rows, then you can simply copy the lookup formula from existing rows.

var ACTION_FORMULAS = false;
var TOTAL_COLUMN = 'q_total';       // session total column name (to avoid formula in session sheet)

var TIMED_GRACE_SEC = 15;           // Grace period for timed submissions (usually about 15 seconds)

var ADMIN_ROLE = 'admin';
var GRADER_ROLE = 'grader';

var ADMINUSER_ID = 'admin';
var MAXSCORE_ID = '_max_score';
var MAXSCOREORIG_ID = '_max_score_orig';
var AVERAGE_ID = '_average';
var RESCALE_ID = '_rescale';
var TIMESTAMP_ID = '_timestamp';
var TESTUSER_ID = '_test_user';
var DISCUSS_ID = '_discuss';

var MIN_HEADERS = ['name', 'id', 'email', 'altid'];
var COPY_HEADERS = ['source', 'team', 'lateToken', 'lastSlide', 'retakes'];

var TESTUSER_ROSTER = {'name': '#user, test', 'id': TESTUSER_ID, 'email': '', 'altid': '', 'extratime': ''};

var SETTINGS_SHEET = 'settings_slidoc';
var INDEX_SHEET = 'sessions_slidoc';
var ROSTER_SHEET = 'roster_slidoc';
var SCORES_SHEET = 'scores_slidoc';

var RELATED_SHEETS = ['answers', 'correct', 'discuss', 'stats'];

var ROSTER_START_ROW = 2;
var SESSION_MAXSCORE_ROW = 2;  // Set to zero, if no MAXSCORE row
var SESSION_START_ROW = SESSION_MAXSCORE_ROW ? 3 : 2;

var BASIC_PACE    = 1;
var QUESTION_PACE = 2;
var ADMIN_PACE    = 3;

var SKIP_ANSWER = 'skip';

var LATE_SUBMIT = 'late';

var FUTURE_DATE = 'future';

var TRUNCATE_DIGEST = 8;
var DIGEST_ALGORITHM = Utilities.DigestAlgorithm.MD5;
var HMAC_ALGORITHM   = Utilities.MacAlgorithm.HMAC_MD5;

var PLUGIN_RE = /^(.*)=\s*(\w+)\.(expect|response)\(\s*(\d*)\s*\)$/;
var QFIELD_RE = /^q(\d+)_([a-z]+)$/;
var QFIELD_MOD_RE = /^(q_other|q_comments|q(\d+)_(comments|grade))$/;

var DELETED_POST = '(deleted)';
var POST_PREFIX_RE = /^Post:(\d+):([-\d:T]+)(\s|$)/;
var POST_NUM_RE = /'(\d+):([-\d:T]+)([\s\S]*)$/;
var AXS_RE = /access(\d+)/;

var SCRIPT_PROP = PropertiesService.getScriptProperties(); // new property service

var Settings = {};

function onInstall(evt) {
    return onOpen(evt);
}

// The onOpen function is executed automatically every time a Spreadsheet is loaded
function onOpen(evt) {
   var ss = SpreadsheetApp.getActiveSpreadsheet();
   loadSettings();
   var menuEntries = [];
   menuEntries.push({name: "Display session answers", functionName: "sessionAnswerSheet"});
   menuEntries.push({name: "Display session statistics", functionName: "sessionStatSheet"});
   menuEntries.push({name: "Display correct answers", functionName: "sessionCorrectSheet"});
   menuEntries.push(null); // line separator
   menuEntries.push({name: "Post/refresh session in gradebook", functionName: "updateScoreSession"});
   menuEntries.push({name: "Refresh session total scores", functionName: "updateTotalSession"});
   menuEntries.push(null); // line separator
   menuEntries.push({name: "Refresh all posted sessions in gradebook", functionName: "updateScoreAll"});
   menuEntries.push(null); // line separator
   menuEntries.push({name: "Email authentication tokens", functionName: "emailTokens"});
   menuEntries.push({name: "Email late token", functionName: "emailLateToken"});
   menuEntries.push({name: "Insert late token", functionName: "insertLateToken"});
   menuEntries.push(null); // line separator
   menuEntries.push({name: "Reset settings", functionName: "resetSettings"});
   menuEntries.push(null); // line separator
   menuEntries.push({name: "Migrate to new schema", functionName: "MigrateAll"});

   ss.addMenu("Slidoc", menuEntries);
}

function setup() {
    var doc = SpreadsheetApp.getActiveSpreadsheet();
    SCRIPT_PROP.setProperty("key", doc.getId());
    // Create default settings sheet, if not already present (from migration)
    defaultSettings(false);
}

function getDoc() {
    return SpreadsheetApp.openById(SCRIPT_PROP.getProperty("key"));
}

function resetSettings() {
    var response = getPrompt('Reset settings?', "Confirm");
    if (response == null)
	return;
    var doc = getDoc();
    defaultSettings(true);
}

function defaultSettings(overwrite) {
    if (getSheet(SETTINGS_SHEET) && !overwrite)
	return;
    var settingsSheet = createSheet(SETTINGS_SHEET, ['name', 'value', 'description']);
    if (settingsSheet.getLastRow() > 1)
	settingsSheet.deleteRows(2, settingsSheet.getLastRow()-1);
    for (var j=0; j<DEFAULT_SETTINGS.length; j++) {
	var defaultRow = DEFAULT_SETTINGS[j];
	settingsSheet.insertRows(j+2);
	if (defaultRow.length && defaultRow[0].trim())
	    settingsSheet.getRange(j+2, 1, 1, defaultRow.length).setValues([defaultRow]);
    }
}

var ProxyCacheRange = null;
function loadSettings() {
    var settingsSheet = getSheet(SETTINGS_SHEET);
    if (!settingsSheet)
	throw('loadSettings: Sheet '+SETTINGS_SHEET+' not found!');
    var settingsData = settingsSheet.getSheetValues(2, 1, settingsSheet.getLastRow()-1, 2);
    for (var j=0; j<settingsData.length; j++) {
	if (!settingsData[j].length || !settingsData[j][0].trim())
	    continue;
	var settingsName = settingsData[j][0].trim();
	var settingsValue = (settingsData[j].length > 1) ? settingsData[j][1] : '';
	if (typeof settingsValue == 'string')
	    settingsValue = settingsValue.trim();
	else if (settingsValue)                    // null, false, or 0 become null string
	    settingsValue = '' + settingsValue;
	else
	    settingsValue = '';
	Settings[settingsName] = settingsValue;
	if (settingsName == 'proxy_update_cache') {
	    ProxyCacheRange = settingsSheet.getRange(j+2, 2, 1, 1);
	    if (settingsValue) {
		try {
		    Settings[settingsName] = JSON.parse(settingsValue);
		} catch(err) {
		    Settings[settingsName] = '';
		}
	    }
	}
    }
}

function getSiteRole(siteName, siteRoles) {
    // Return role for site or null
    var scomps = siteRoles.split(',');
    for (var j=0; j<scomps.length; j++) {
	var smatch = /^([^\+]+)(\+(\w+))?$/.exec(scomps[j]);
	if (smatch && smatch[1] == siteName) {
	    return smatch[3] || '';
	}
	return null;
    }
}

function isSpecialUser(userId) {
    var keys = ['admin_users', 'grader_users', 'guest_users'];
    for (var j=0; j<keys.length; j++) {
        var idList = Settings[keys[j]].trim().split(',');
        for (var k=0; k<idList.length; k++) {
            if (userId == idList[k].trim()) {
                return true;
            }
        }
    }
    return false;
}

function getRosterEntry(userId) {
    if (userId == TESTUSER_ID)
        return TESTUSER_ROSTER;
    try {
	// Copy user info from roster
	return lookupValues(userId, Object.keys(TESTUSER_ROSTER), ROSTER_SHEET, false, true);
    } catch(err) {
	if (isSpecialUser(userId)) {
	    return {'name': '#'+userId+', '+userId, 'id': userId};
	}
	throw("Error:NEED_ROSTER_ENTRY:userID '"+userId+"' not found in roster");
    }
}

// Cached (read-only) sheets
var SHEET_CACHING = true;

function getSheetCache(sheetName) {
    // Return cached sheet, if present
    return SHEET_CACHING ? (new SheetCache(sheetName)) : getSheet(sheetName);
}

function SheetCache(sheetName) {
    var sheet = getSheet(sheetName);
    if (!sheet)
	throw('SheetCache: sheet '+sheetName+' not found!');
    this._nrows = sheet.getLastRow();
    this._ncols = sheet.getLastColumn();
    this._data = sheet.getSheetValues(1, 1, this._nrows, this._ncols);
}

SheetCache.prototype.getLastRow = function() {
    return this._nrows;
}

SheetCache.prototype.getLastColumn = function() {
    return this._ncols;
}

SheetCache.prototype.getSheetValues = function(startRow, startCol, nRows, nCols) {
    var subrows = this._data.slice(startRow-1, startRow-1+nRows);
    var vals = [];
    for (var j=0; j<subrows.length; j++) {
	vals.push(subrows[j].slice(startCol-1, startCol-1+nCols));
    }
    return vals;
}

// Comparison function for sorting
function numSort(a,b) {return a-b;}

// Call tracking (level 0 => end of call)
function trackCall(level, msg) {}

function startCallTracking(logLevel, params, sheetName, origUser) {
    var curDate = new Date();
    var curTime = curDate.getTime();
    var callId = params.id || 'ID';
    if (origUser && origUser != callId)
	callId += '/'+origUser;
    var callType = '';
    var callParams = 'sheet='+(sheetName||'');
    if (params.get)
	callParams += ', get';
    if (params.all)
	callParams += ', all';
    if (params.create)
	callParams += ', create';
    if (params.proxy) {
	callType = 'proxy';
	if (params.allupdates)
	    callParams += ', allupdates='+params.data.length;
    } else if (params.actions) {
	callType = 'actions';
	callParams += ', actions='+params.actions;
    } else if (params.update) {
	callType = 'selectedUpdates';
    } else if (params.row) {
	callType = 'rowUpdate';
    }
    var callHeaders = ['id', 'type', 'params', 'startTime', 'elapsed', 'status'];
    var callValues = [callId, callType, callParams, curDate];

    var callSheet = getSheet('call_log');
    if (!callSheet) {
	callSheet = createSheet('call_log', callHeaders);
    }
    var callRows = callSheet.getLastRow();
    callSheet.insertRowBefore(callRows+1);
    callSheet.getRange(callRows+1, 1, 1, callValues.length).setValues([callValues]);
    var callEndRange = callSheet.getRange(callRows+1, callValues.length+1, 1, 2);
    var progressCol = callHeaders.length + 1;
    function trackCallAux(level, msg) {
	if (!level) {
	    callEndRange.setValues([[(new Date()).getTime() - curTime, msg]]);
	} else if (level <= logLevel) {
	    callSheet.getRange(callRows+1, progressCol, 1, 1).setValues([[((new Date()).getTime() - curTime)+': '+msg]]);
	    progressCol += 1;
	}
    }
    trackCall = trackCallAux;
}


// If you don't want to expose either GET or POST methods you can comment out the appropriate function
function doGet(evt){
  return handleResponse(evt);
}

function doPost(evt){
  return handleResponse(evt);
}

function handleResponse(evt) {
    var jsonPrefix = '';
    var jsonSuffix = '';
    var mimeType = ContentService.MimeType.JSON;
    var parmPrefix = evt.parameter.prefix || null;
    if (parmPrefix) {
	jsonPrefix = parmPrefix + '(' + (evt.parameter.callback || '0') + ', ';
        jsonSuffix = ')';
	mimeType = ContentService.MimeType.JAVASCRIPT;
    }
    return ContentService
        .createTextOutput(jsonPrefix+JSON.stringify(sheetAction(evt.parameter))+jsonSuffix)
        .setMimeType(mimeType);
}

function sheetAction(params) {
    // Returns an object
    // object.result = 'success' or 'error'
    // object.value contains updated row values list if get=1; otherwise it is [].
    // object.headers contains column headers list, if getheaders=1
    // object.info is an object contains timestamp and dueDate values
    // PARAMETERS
    // sheet: 'sheet name' (required, except for proxy/action)
    // admin: admin user name (optional)
    // token: authentication token
    // actions: ''|'discuss_posts'|'answer_stats'|'gradebook' (may be carried out directly or after proxy cache updates have been applied)
    // headers: ['name', 'id', 'email', 'altid', 'Timestamp', 'initTimestamp', 'submitTimestamp', 'field1', ...] (name and id required for sheet creation)
    // name: sortable name, usually 'Last name, First M.' (required if creating a row, and row parameter is not specified)
    // id: unique userID or lowercase email (required if creating or updating a row, and row parameter is not specified)
    // email: optional
    // altid: alternate, perhaps numeric, id (optional, used for information only)
    // update: [('field1', 'val1'), ...] (list of fields+values to be updated, excluding the unique field 'id')
    // If the special name initTimestamp occurs in the list, the timestamp is initialized when the row is added.
    // If the special name Timestamp occurs in the list, the timestamp is automatically updated on each write.
    // row: ['name_value', 'id_value', 'email_value', 'altid_value', null, null, null, 'field1_value', ...]
    //       null value implies no update (except for Timestamp)
    // nooverwrite: 1 => do not overwrite row; return previous row, if present, else create new row
    // submit: 1 if submitting row
    // timestamp: previous timestamp value (for sequencing updates)
    // update: 1 to modify part of row
    // get: 1 to retrieve row (id must be specified)
    // getheaders: 1 to return headers as well
    // all: 1 to retrieve all rows
    // formula: 1 retrieve formulas (proxy only)
    // create: 1 to create and initialize non-existent rows (for get/put)
    // seed: optional random seed to re-create session (admin use only)
    // delrow: 1 to delete row
    // resetrow: 1 to reset row (for get)
    // late: lateToken (set when creating row)
    // Can add row with fewer columns than already present.
    // This allows user to add additional columns without affecting script actions.
    // (User added columns are returned on gets and selective updates, but not row updates.)
    // delsheet: 1 to delete sheet (and any associated session index entry)
    // copysheet: name to copy sheet to new sheet (but not session index entry)
    // logcall: 0 or 1 or 2 to enable call debugging (logs calls to sheet 'call_log'; may generate very large amounts of output)
    // shortly after my original solution Google announced the LockService[1]
    // this prevents concurrent access overwritting data
    // [1] http://googleappsdeveloper.blogspot.co.uk/2011/10/concurrency-and-google-apps-script.html
    // we want a public lock, one that locks for all invocations
    var lock = LockService.getPublicLock();
    lock.waitLock(30000);  // wait 30 seconds before conceding defeat.

    var returnValues = null;
    var returnHeaders = null;
    var returnInfo = {version: VERSION};
    var returnMessages = [];
    var completeActions = [];
    try {
	loadSettings();

	var sheetName = params.sheet || '';
	returnInfo['sheet'] = sheetName;

        var origUser = '';
        var adminUser = '';
	var readOnlyAccess = false;

	var paramId = params.id || '';
        var authToken = params.token || '';

        if (authToken.indexOf(':') >= 0) {
            var comps = authToken.split(':');    // effectiveId:userid:role:sites:hmac
            if (comps.length != 5) {
                throw('Error:INVALID_TOKEN:Invalid auth token format '+authToken);
            }
            var subToken = ':' + comps.slice(1).join(':');
            if (!validateHMAC(subToken, Settings['auth_key'])) {
                throw('Error:INVALID_TOKEN:Invalid authentication token '+subToken);
            }

            var effectiveUser = comps[0];
            origUser = comps[1];
            var temRole = comps[2];
            var temSites = comps[3];

	    if (!temRole && temSites && Settings['site_name']) {
		temRole = getSiteRole(Settings['site_name'], temSites) || '';
	    }

            if (params.admin) {
                if (temRole != ADMIN_ROLE && temRole != GRADER_ROLE) {
                    throw('Error:INVALID_TOKEN:Invalid token admin role: '+temRole);
                }
                adminUser = temRole;
            } else if (effectiveUser) {
                if (effectiveUser != origUser && temRole != ADMIN_ROLE) {
                    throw('Error:INVALID_TOKEN:Not allowed to change from user: '+origUser+' to '+effectiveUser);
                }
                if (effectiveUser != paramId) {
                    throw('Error:INVALID_TOKEN:Incorrect effective user: '+effectiveUser+' != '+paramId);
                }
		readOnlyAccess = (origUser != effectiveUser) && (effectiveUser != TESTUSER_ID);
            } else {
                throw('Error:INVALID_TOKEN:Unexpected admin token for regular access');
            }

        } else if (params.admin) {
            throw('Error:NEED_TOKEN:Need admin token for admin authentication');

        } else if (Settings['require_login_token']) {
            if (!authToken) {
                throw('Error:NEED_TOKEN:Need token for id authentication');
            }
            if (!paramId) {
                throw('Error:NEED_ID:Need id for authentication');
            }
            if (!validateHMAC(genAuthPrefix(paramId,'','')+':'+authToken, Settings['auth_key'])) {
                throw('Error:INVALID_TOKEN:Invalid token '+authToken+' for authenticating id '+paramId);
            }
            origUser = paramId;
        }

	var proxy = params.proxy || '';

	// Read-only sheets
	var protectedSheet = (sheetName.match(/_slidoc$/) && sheetName != ROSTER_SHEET && sheetName != INDEX_SHEET) || sheetName.match(/-answers$/) || sheetName.match(/-stats$/);

	// Admin-only access sheets (ROSTER_SHEET modifications will be restricted later)
	var restrictedSheet = (sheetName.match(/_slidoc$/) && sheetName != ROSTER_SHEET && sheetName != SCORES_SHEET);

	var loggingSheet = sheetName.match(/_log$/);
	var discussionSheet = sheetName.match(/-discuss$/);

	var getRow = params.get || '';
	var createRow = params.create || '';
	var allRows = params.all || '';

	var nooverwriteRow = params.nooverwrite || '';
	var delRow = params.delrow || '';
	var resetRow = params.resetrow || '';

	var getShare = params.getshare || '';
	var importSession = params.import || '';
	var seedRow = adminUser ? (params.seed || null) : null;
	    
	var performActions = params.actions || '';

	var curDate = new Date();
	var curTime = curDate.getTime();

	var freezeDate = createDate(Settings['freeze_date']) || null;
	var frozenSessions = Settings['freeze_date'] == 'readonly' || (freezeDate && curDate.getTime() > freezeDate.getTime());

	var logCall = params.logcall ? (parseInt(params.logcall) || 0) : 0;
	if (logCall)
	    startCallTracking(logCall, params, sheetName, origUser);

	if (performActions) {
            if (performActions == 'discuss_posts') {
                returnValues = getDiscussPosts(sheetName, (params.slide || ''), paramId);
		trackCall(0, 'success');
                return {"result": "success", "value": returnValues, "headers": returnHeaders,
                        "info": returnInfo, "messages": returnMessages.join('\n')};
	    } else {
		if (!adminUser)
		    throw("Error:ACTION:Must be admin user to perform action on sheet "+sheetName);
		if (protectedSheet || restrictedSheet || loggingSheet)
		    throw('Error:ACTION:Action not allowed for sheet '+sheetName);
	    }
	} else if (!proxy && !sheetName) {
	    throw('Error:SHEETNAME:No sheet name specified');
	}

	var sessionEntries = null;
	var sessionAttributes = null;
	var questions = null;
	var paceLevel = null;
	var adminPaced = null;
	var dueDate = null;
	var gradeDate = null;
	var voteDate = null;
	var discussableSession = null;
	var timedSec = null;
	var computeTotalScore = false;

	if (proxy && adminUser != ADMIN_ROLE)
	    throw("Error::Must be admin user for proxy access to sheet '"+sheetName+"'");

        if (sheetName == SETTINGS_SHEET && adminUser != ADMIN_ROLE)
            throw('Error::Must be admin user to access settings')

	if (restrictedSheet && !adminUser)
	    throw("Error::Must be admin/grader user to access restricted sheet '"+sheetName+"'");

	var rosterValues = null;
	var rosterSheet = getSheet(ROSTER_SHEET);
	if (rosterSheet && !adminUser) {
	    // Check user access
	    if (!paramId)
		throw('Error:NEED_ID:Must specify userID to lookup roster')
	    // Copy user info from roster
	    rosterValues = getRosterEntry(paramId);
	}

	returnInfo.prevTimestamp = null;
	returnInfo.timestamp = null;

	if (performActions) {
	    returnInfo.refreshSheets = actionHandler(performActions, sheetName, true);

	} else if (proxy && params.get && params.all) {
	    // Return all sheet values to proxy
	    var modSheet = getSheet(sheetName);
	    if (!modSheet)
		throw("Error:NOSHEET:Sheet '"+sheetName+"' not found");
	    var allRange = modSheet.getRange(1, 1, modSheet.getLastRow(), modSheet.getLastColumn());
	    returnValues = allRange.getValues();
	    if (params.formula) {
		var formulaValues = allRange.getFormulas();
		for (var j=0; j<formulaValues.length; j++) {
		    var temFormulas = formulaValues[j];
		    for (var k=0; k<temFormulas.length; k++) {
			if (temFormulas[k])
			    returnValues[j][k] = temFormulas[k];
		    }
		}
	    }

	} else if (proxy && params.allupdates && params.requestid && Settings['proxy_update_cache'] && Settings['proxy_update_cache'][0] == params.requestid) {
	    // Proxy update request already handled; return cached response
	    returnValues = [];
	    returnInfo.cachedResponse = Settings['proxy_update_cache'][0];
	    returnInfo.refreshSheets = Settings['proxy_update_cache'][1];
	    returnInfo.updateErrors = Settings['proxy_update_cache'][2];

	} else if (proxy && params.allupdates) {
	    // Update multiple sheets from proxy
	    if (ProxyCacheRange) {
		ProxyCacheRange.setValue('');
	    }
	    returnValues = [];
	    var data = JSON.parse(params.data);
	    var retval = handleProxyUpdates(data, params.create, returnMessages);
	    returnInfo.refreshSheets = retval[0];
	    returnInfo.updateErrors = retval[1];

	    if (ProxyCacheRange) {
		ProxyCacheRange.setValue( JSON.stringify([params.requestid || '', retval[0], retval[1]]) );
	    }

        } else if (params.delsheet) {
	    // Delete sheet (and session entry)
	    returnValues = [];
	    if (!adminUser)
		throw("Error:DELSHEET:Only admin can delete sheet "+sheetName);
	    if (sheetName.match(/_slidoc$/))
		throw("Error:DELSHEET:Cannot delete special sheet "+sheetName);
	    var indexSheet = getSheet(INDEX_SHEET);
	    if (indexSheet) {
		// Delete session entry
		var delRowCol = lookupRowIndex(sheetName, indexSheet, 2);
		if (delRowCol)
                    indexSheet.deleteRow(delRowCol);
	    }
	    deleteSheet(sheetName);

	    // Delete any related sheets
            for (var j=0; j<RELATED_SHEETS.length; j++) {
                if (getSheet(sheetName+'-'+RELATED_SHEETS[j])) {
                    deleteSheet(sheetName+'-'+RELATED_SHEETS[j]);
                }
	    }
        } else if (params.copysheet) {
	    // Copy sheet (but not session entry)
	    returnValues = [];
	    if (!adminUser)
		throw("Error:COPYSHEET:Only admin can copy sheet "+sheetName);
	    var modSheet = getSheet(sheetName);
	    if (!modSheet)
		throw("Error:COPYSHEET:Source sheet "+sheetName+" not found!");

	    var newName = params.copysheet;
	    var indexSheet = getSheet(INDEX_SHEET);
	    if (indexSheet) {
		var newRowCol = lookupRowIndex(newName, indexSheet, 2);
		if (newRowCol)
		    throw("Error:COPYSHEET:Destination session entry "+newName+" already exists!");
	    }
	    if (getSheet(newName))
		throw("Error:COPYSHEET:Destination sheet "+newName+" already exists!");
	    modSheet.copy(newName);
	} else {
	    // Update/access single sheet
	    var headers = params.headers ? JSON.parse(params.headers) : null;

	    var modSheet = getSheet(sheetName);
	    if (!modSheet) {
		// Create new sheet
		if (!adminUser)
		    throw("Error:NOSHEET:Sheet '"+sheetName+"' not found");
		if (!headers)
		    throw("Error:NOSHEET:Headers must be specified for new sheet '"+sheetName+"'");
		modSheet = createSheet(sheetName, headers);
	    }

	    if (!modSheet.getLastColumn())
		throw("Error::No columns in sheet '"+sheetName+"'");

	    if (!restrictedSheet && !protectedSheet && !loggingSheet && !discussionSheet && sheetName != ROSTER_SHEET && getSheet(INDEX_SHEET)) {
		// Indexed session
		sessionEntries = lookupValues(sheetName, ['dueDate', 'gradeDate', 'paceLevel', 'adminPaced', 'scoreWeight', 'gradeWeight', 'otherWeight', 'fieldsMin', 'questions', 'attributes'], INDEX_SHEET);
		sessionAttributes = JSON.parse(sessionEntries.attributes);
		questions = JSON.parse(sessionEntries.questions);
		paceLevel = parseNumber(sessionEntries.paceLevel) || 0;
		adminPaced = sessionEntries.adminPaced;
		dueDate = sessionEntries.dueDate;
		gradeDate = sessionEntries.gradeDate;
		voteDate = sessionAttributes.params.plugin_share_voteDate ? createDate(sessionAttributes.params.plugin_share_voteDate) : null;
		discussableSession = sessionAttributes.discussSlides && sessionAttributes.discussSlides.length;
		timedSec = sessionAttributes['params'].timedSec || null;
		if (timedSec && rosterValues) {
                    var extraTime = parseNumber(rosterValues.extratime || '');
                    if (extraTime) {
			timedSec = timedSec * (1.0 + extraTime);
		    }
		}

		if (parseNumber(sessionEntries.scoreWeight)) {
		    // Compute total score?
		    if (sessionAttributes['params']['features'].delay_answers || sessionAttributes['params']['features'].remote_answers) {
			// Delayed or remote answers; compute total score only after grading
			computeTotalScore = gradeDate;
                    } else {
			computeTotalScore = true;
                    }
		}
	    }

	    // Check parameter consistency
	    var columnHeaders = modSheet.getSheetValues(1, 1, 1, modSheet.getLastColumn())[0];
	    var columnIndex = indexColumns(modSheet);
	    
	    var selectedUpdates = params.update ? JSON.parse(params.update) : null;
	    var rowUpdates = params.row ? JSON.parse(params.row) : null;

	    var modifyingRow = delRow || resetRow || selectedUpdates || (rowUpdates && !nooverwriteRow);
            if (modifyingRow) {
		if (readOnlyAccess) {
                    throw('Error::Admin user '+origUser+' cannot modify row for user '+paramId);
                }
            }

	    var updatingMaxScoreRow = sessionEntries && rowUpdates && rowUpdates[columnIndex['id']-1] == MAXSCORE_ID;
	    if (headers) {
		var modifyStartCol = params.modify ? parseInt(params.modify) : 0;
		if (modifyStartCol) {
                    if (!updatingMaxScoreRow)
			throw("Error::Must be updating max scores row to modify headers in sheet "+sheetName);
                    var checkCols = modifyStartCol-1;
		} else {
                    if (headers.length != columnHeaders.length)
			throw("Error:MODIFY_SESSION:Number of headers does not match that present in sheet '"+sheetName+"'; delete it or modify headers.");
                    var checkCols = columnHeaders.length;
		}

		for (var j=0; j< checkCols; j++) {
                    if (headers[j] != columnHeaders[j]) {
			throw("Error:MODIFY_SESSION:Column header mismatch: Expected "+headers[j]+" but found "+columnHeaders[j]+" in sheet '"+sheetName+"'; delete it or modify headers.")
                    }
		}
		if (modifyStartCol) {
		    // Updating maxscore row; modify headers if needed
                    var startRow = 2;
                    var nRows = modSheet.getLastRow()-startRow+1;
		    var idValues = null;
                    if (nRows) {
			idValues = modSheet.getSheetValues(startRow, columnIndex['id'], nRows, 1);
                        if (paceLevel == BASIC_PACE || paceLevel == QUESTION_PACE) {
                            var submitValues = modSheet.getSheetValues(startRow, columnIndex['submitTimestamp'], nRows, 1);
                            for (var k=0; k < nRows; k++) {
				if (submitValues[k][0]) {
                                    throw( "Error::Cannot modify sheet "+sheetName+" with submissions");
				}
			    }
			}
		    }
		    if (modifyStartCol <= columnHeaders.length) {
                        // Truncate columns; ensure truncated columns are empty
                        var startCol = modifyStartCol;
                        var nCols = columnHeaders.length-startCol+1;
                        if (nRows) {
			    var modRows = nRows;
			    if (idValues[0][0] == MAXSCORE_ID) {
                                startRow += 1;
                                modRows -= 1;
			    }
			    if (modRows) {
                                var values = modSheet.getSheetValues(startRow, startCol, modRows, nCols);
                                for (var j=0; j < nCols; j++) {
				    for (var k=0; k < modRows; k++) {
                                        if (values[k][j] != '') {
					    throw( "Error:TRUNCATE_ERROR:Cannot truncate non-empty column "+(startCol+j)+" ("+columnHeaders[startCol+j-1]+") in sheet "+sheetName+" (modcol="+modifyStartCol+")");
                                        }
				    }
                                }
			    }
                        }

                        ///modSheet.trimColumns( nCols )
                        modSheet.deleteColumns(startCol, nCols);
		    }
		    var nTemCols = modSheet.getLastColumn();
		    if (headers.length > nTemCols) {
                        // Extend columns
                        var startCol = nTemCols+1;
                        var nCols = headers.length-startCol+1;
                        ///modSheet.appendColumns(headers[nTemCols:])
                        modSheet.insertColumnsAfter(startCol-1, nCols);
                        modSheet.getRange(1, startCol, 1, nCols).setValues([ headers.slice(nTemCols) ]);
		    }
		    columnHeaders = modSheet.getSheetValues(1, 1, 1, modSheet.getLastColumn())[0];
		    columnIndex = indexColumns(modSheet);

		    updateTotalFormula(modSheet, modSheet.getLastRow());
		}

	    }
	    
	    if (updatingMaxScoreRow && computeTotalScore) {
		completeActions.push('answer_stats');
		completeActions.push('correct');
		if (updateTotalScores(modSheet, sessionAttributes, questions, true)) {
		    completeActions.push('gradebook');
		}
	    }

	    var userId = null;
	    var displayName = null;

	    var voteSubmission = '';
            var alterSubmission = false;
            var twitterSetting = false;
	    var discussionPost = null;
	    if (!rowUpdates && selectedUpdates && selectedUpdates.length == 2 && selectedUpdates[0][0] == 'id') {
		if (selectedUpdates[1][0].match(/_vote$/) && sessionAttributes.shareAnswers) {
		    var qprefix = selectedUpdates[1][0].split('_')[0];
		    voteSubmission = sessionAttributes.shareAnswers[qprefix] ? (sessionAttributes.shareAnswers[qprefix].share||'') : '';
		}

                if (sheetName.match(/-discuss$/) && selectedUpdates[1][0].match(/^discuss/)) {
                    discussionPost = [sheetName.slice(0, -('-discuss'.length)), parseInt(selectedUpdates[1][0].slice('discuss'.length) )];
                }

		if (selectedUpdates[1][0] == 'submitTimestamp')
		    alterSubmission = true;

		if (selectedUpdates[1][0] == 'twitter' && sheetName == ROSTER_SHEET)
		    twitterSetting = true;
	    }

	    if (!adminUser && selectedUpdates && !voteSubmission && !discussionPost && !twitterSetting)
		throw("Error::Only admin user allowed to make selected updates to sheet '"+sheetName+"'");

            if (importSession && !adminUser)
		throw("Error::Only admin user allowed to import to sheet '"+sheetName+"'")

	    if (sheetName == ROSTER_SHEET && rowUpdates && !adminUser)
		throw("Error::Only admin user allowed to add/modify rows to sheet '"+sheetName+"'");

	    if (protectedSheet && (rowUpdates || selectedUpdates) )
		throw("Error::Cannot modify protected sheet '"+sheetName+"'")

	    var numStickyRows = 1;  // Headers etc.

	    if (params.getheaders) {
		returnHeaders = columnHeaders;
		if (sessionEntries && paramId == TESTUSER_ID) {
		    returnInfo['maxRows'] = modSheet.getLastRow();
		    if (columnIndex.lastSlide)
			returnInfo['maxLastSlide'] = getColumnMax(modSheet, 2, columnIndex['lastSlide']);
		}
	    }
	    if (params.getstats) {
		try {
		    var temIndexRow = indexRows(modSheet, columnIndex['id'], 2);
		    if (temIndexRow[MAXSCORE_ID])
			returnInfo.maxScores = modSheet.getSheetValues(temIndexRow[MAXSCORE_ID], 1, 1, columnHeaders.length)[0];
		    if (temIndexRow[RESCALE_ID])
			returnInfo.rescale = modSheet.getSheetValues(temIndexRow[RESCALE_ID], 1, 1, columnHeaders.length)[0];
		    if (Settings['share_averages'] && temIndexRow[AVERAGE_ID])
			returnInfo.averages = modSheet.getSheetValues(temIndexRow[AVERAGE_ID], 1, 1, columnHeaders.length)[0];
		} catch (err) {}
	    }
	}

	if (proxy) {
	    // Already handled proxy get and updates
	} else if (delRow) {
            // Delete row only allowed for session sheet and admin/test user
            if (!sessionEntries || (!adminUser && paramId != TESTUSER_ID))
                throw("Error:DELETE_ROW:userID '"+paramId+"' not allowed to delete row in sheet "+sheetName)
            var delRowCol = lookupRowIndex(paramId, modSheet, 2);
            if (delRowCol)
                modSheet.deleteRow(delRowCol);
            returnValues = [];
	} else if (!rowUpdates && !selectedUpdates && !getRow && !getShare) {
	    // No row updates/gets
	    returnValues = [];
	} else if (getRow && allRows) {
	    // Get all rows and columns
            if (!adminUser)
		throw("Error::Only admin user allowed to access all rows in sheet '"+sheetName+"'")
	    if (modSheet.getLastRow() <= numStickyRows) {
                returnValues = [];
            } else {
                if (sessionEntries && dueDate) {
                    // Force submit all non-sticky regular user rows past effective due date
                    var idCol = columnIndex.id;
                    var submitCol = columnIndex.submitTimestamp;
                    var lateTokenCol = columnIndex.lateToken;
                    var allValues = modSheet.getSheetValues(1+numStickyRows, 1, modSheet.getLastRow()-numStickyRows, columnHeaders.length);
                    for (var j=0; j<allValues.length; j++) {
                        if (allValues[j][submitCol-1] || allValues[j][idCol-1] == MAXSCORE_ID || allValues[j][idCol-1] == TESTUSER_ID) {
                            continue;
                        }
                        var lateToken = allValues[j][lateTokenCol-1];
                        if (lateToken == LATE_SUBMIT) {
                            continue;
                        }
                        if (lateToken && lateToken.indexOf(':') > 0) {
                            var effectiveDueDate = getNewDueDate(allValues[j][idCol-1], Settings['site_name'], sheetName, lateToken) || dueDate;
                        } else {
                            var effectiveDueDate = dueDate;
                        }
                        var pastSubmitDeadline = curDate.getTime() > effectiveDueDate.getTime();
                        if (pastSubmitDeadline) {
                            // Force submit
                            modSheet.getRange(j+1+numStickyRows, submitCol, 1, 1).setValues([[curDate]]);
                        }
                    }
                }

                returnValues = modSheet.getSheetValues(1+numStickyRows, 1, modSheet.getLastRow()-numStickyRows, columnHeaders.length);
            }
	    if (sessionEntries) {
		if (adminPaced) {
                    returnInfo['adminPaced'] = adminPaced;
		}
		if (columnIndex.lastSlide) {
                    returnInfo['maxLastSlide'] = getColumnMax(modSheet, 2, columnIndex['lastSlide']);
		}
                if (computeTotalScore) {
                    returnInfo['remoteAnswers'] = sessionAttributes.remoteAnswers;
                }
	    }

	} else if (getShare) {
	    // Return adjacent columns (if permitted by session index and corresponding user entry is non-null)
	    if (!sessionAttributes || !sessionAttributes.shareAnswers)
		throw('Error::Denied access to answers of session '+sheetName);
	    var shareParams = sessionAttributes.shareAnswers[getShare];
	    if (!shareParams || !shareParams.share)
		throw('Error::Sharing not enabled for '+getShare+' of session '+sheetName);

	    if (shareParams.vote && voteDate)
		returnInfo.voteDate = voteDate;

            var qno = parseInt(getShare.slice(1));
            var teamAttr = questions[qno-1].team || '';

	    if (!adminUser && shareParams.share == 'after_grading' && !gradeDate) {
		returnMessages.push("Warning:SHARE_AFTER_GRADING:");
		returnValues = [];
	    } else if (!adminUser && shareParams.share == 'after_due_date' && (!dueDate || dueDate.getTime() > curDate.getTime())) {
		returnMessages.push("Warning:SHARE_AFTER_DUE_DATE:");
		returnValues = [];
	    } else if (modSheet.getLastRow() <= numStickyRows) {
		returnMessages.push("Warning:SHARE_NO_ROWS:");
		returnValues = [];
            } else if (sessionAttributes && sessionAttributes['params']['features'].share_answers) {
                var answerSheet = getSheet(sheetName+'-answers');
                if (!answerSheet) {
                    throw('Error::Sharing not possible without answer sheet '+sheetName+'-answers');
                }
                var ansColumnHeaders = answerSheet.getSheetValues(1, 1, 1, answerSheet.getLastColumn())[0];
                var ansCol = 0;
                for (var j=0; j < ansColumnHeaders.length; j++) {
                    if (ansColumnHeaders[j].slice(0,getShare.length+1) == getShare+'_') {
                        ansCol = j+1;
                        break;
                    }
                }
                if (!ansCol) {
                    throw('Error::Column '+getShare+'_* not present in headers for answer sheet '+sheetName+'-answers');
                }
                returnHeaders = [ getShare+'_response' ];
                var nRows = answerSheet.getLastRow()-1;
                var names = answerSheet.getSheetValues(2, 1, nRows, 1);
                var values = answerSheet.getSheetValues(2, ansCol, nRows, 1);
                returnValues = [];
                for (var j=0; j < values.length; j++) {
                    if (names[j][0] && names[j][0].charAt(0) != '#' && values[j][0]) {
                        returnValues.push(values[j][0]);
                    }
                }
                returnValues.sort();
	    } else {
		var nRows = modSheet.getLastRow()-numStickyRows;
		var respCol = getShare+'_response';
		var respIndex = columnIndex[getShare+'_response'];
		if (!respIndex)
		    throw('Error::Column '+respCol+' not present in headers for session '+sheetName);

		var explainOffset = 0;
		var shareOffset = 1;
		var nCols = 2;
		if (columnIndex[getShare+'_explain'] == respIndex+1) {
		    explainOffset = 1;
		    shareOffset = 2;
		    nCols += 1;
		}
		var voteOffset = 0;
		if (shareParams.vote && columnIndex[getShare+'_vote'] == respIndex+nCols) {
		    voteOffset = shareOffset+1;
		    nCols += 1;
		}
		returnHeaders = [];
		for (var j=respIndex; j<respIndex+nCols; j++)
		    returnHeaders.push(columnHeaders[j-1]);

		var shareSubrow = modSheet.getSheetValues(1+numStickyRows, respIndex, nRows, nCols);

		var idValues     = modSheet.getSheetValues(1+numStickyRows, columnIndex['id'], nRows, 1);
		var nameValues   = modSheet.getSheetValues(1+numStickyRows, columnIndex['name'], nRows, 1);
		var timeValues   = modSheet.getSheetValues(1+numStickyRows, columnIndex['Timestamp'], nRows, 1);
		var submitValues = modSheet.getSheetValues(1+numStickyRows, columnIndex['submitTimestamp'], nRows, 1);
		var teamValues   = modSheet.getSheetValues(1+numStickyRows, columnIndex['team'], nRows, 1);
		var lateValues   = modSheet.getSheetValues(1+numStickyRows, columnIndex['lateToken'], nRows, 1);

                var curUserVals = null;
                var testUserVals = null;
		var curUserSubmitted = null;
                var testUserSubmitted = null;
                for (var j=0; j<nRows; j++) {
		    if (shareSubrow[j][0] == SKIP_ANSWER)
                        shareSubrow[j][0] = '';
                    if (idValues[j][0] == paramId) {
                        curUserVals = shareSubrow[j];
			curUserSubmitted = submitValues[j][0];
                    } else if (idValues[j][0] == TESTUSER_ID) {
                        testUserVals = shareSubrow[j];
			testUserSubmitted = submitValues[j][0];
		    }
		}
                if (!curUserVals && !adminUser)
                    throw('Error::Sheet has no row for user '+paramId+' to share in session '+sheetName);

		var votingCompleted = voteDate && voteDate.getTime() < curDate.getTime();
		var voteParam = shareParams.vote;
		var tallyVotes = voteParam && (adminUser || voteParam == 'show_live' || (voteParam == 'show_completed' && votingCompleted));

		var curUserResponded = curUserVals && curUserVals[0] && (!explainOffset || curUserVals[explainOffset]);

                if (!adminUser && paramId != TESTUSER_ID) {
                    if (paceLevel == ADMIN_PACE && (!testUserVals || (!testUserVals[0] && !testUserSubmitted))) {
                        throw('Error::Instructor must respond to question '+getShare+' before sharing in session '+sheetName);
                    }

                    if (shareParams.share == 'after_answering' && !curUserResponded && !curUserSubmitted) {
                        throw('Error::User '+paramId+' must respond to question '+getShare+' before sharing in session '+sheetName);
                    }
                }

		var disableVoting = false;

		// If test/admin user, or current user has provided no response/no explanation, disallow voting
		if (paramId == TESTUSER_ID || !curUserResponded)
		    disableVoting = true;

		// If voting not enabled or voting completed, disallow voting.
		if (!voteParam || votingCompleted)
		    disableVoting = true;

		if (voteOffset) {
		    // Return user vote codes
		    if (curUserVals)
			returnInfo.vote = curUserVals[voteOffset];
		    if (tallyVotes) {
			var votes = {};
			for (var j=0; j<nRows; j++) {
			    var voteCodes = (shareSubrow[j][voteOffset]||'').split(',');
			    for (var k=0; k<voteCodes.length; k++) {
				var voteCode = voteCodes[k];
				if (!voteCode)
				    continue;
				if (voteCode in votes)
				    votes[voteCode] += 1;
				else
				    votes[voteCode] = 1;
			    }
			}
			// Replace vote code with vote counts
			for (var j=0; j<nRows; j++) {
			    var shareCode = shareSubrow[j][shareOffset];
			    shareSubrow[j][voteOffset] = votes[shareCode] || 0;
			}
		    } else {
			// Voting results not yet released
			for (var j=0; j<nRows; j++)
			    shareSubrow[j][voteOffset] = null;
		    }
		}

		var selfShare = '';
                if (shareOffset) {
                    if (curUserVals) {
                        selfShare = curUserVals[shareOffset];
                        returnInfo['share'] = disableVoting ? '' : selfShare;
                    }

                    // Disable voting/self voting
                    // This needs to be done after vote tallying, because vote codes are cleared
                    for (var j=0; j < nRows; j++) {
                        if (disableVoting || shareSubrow[j][shareOffset] == selfShare) {
                            shareSubrow[j][shareOffset] = '';
                        }
                    }
                }

                var sortVotes = tallyVotes && (votingCompleted || adminUser || (voteParam == 'show_live' && paramId == TESTUSER_ID));
		var sortVals = [];
                var teamResponded = {};
                var responderTeam = {};
                var includeId = {};

                // Traverse by reverse timestamp order
                var timeIndex = [];
                for (var j=0; j < nRows; j++) {
                    var timeVal = timeValues[j][0] ? timeValues[j][0].getTime() : 0;
                    timeIndex.push([timeVal, j]);
                }
                timeIndex.sort();
                timeIndex.reverse();

                for (var k=0; k < nRows; k++) {
                    var j = timeIndex[k][1];

                    var idValue = idValues[j][0];
                    if (idValue == TESTUSER_ID) {
                        // Ignore test user response
                        continue;
                    }

                    // Always skip null responses and ungraded lates
                    if (!shareSubrow[j][0] || lateValues[j][0] == LATE_SUBMIT) {
                        continue;
                    }

                    // If voting, skip incomplete/late submissions
                    if (voteParam && lateValues[j][0]) {
                        continue;
                    }

                    // If voting, skip if explanations expected and not provided
                    if (voteParam && explainOffset && !shareSubrow[j][explainOffset]) {
                        continue;
                    }

                    // Process only one non-null response per team
                    if (teamAttr && teamValues[j][0]) {
                        var teamName = teamValues[j][0];
                        if (teamName in teamResponded) {
                            continue;
                        }
                        teamResponded[teamName] = 1;
                        responderTeam[idValue] = teamName;
                    }

                    includeId[idValue] = 1;

		    // Use earlier of submit time or timestamp to sort
		    var timeVal = submitValues[j][0] || timeValues[j][0];
		    timeVal = timeVal ? timeVal.getTime() : 0;

                    var respVal = shareSubrow[j][0];
                    if (parseNumber(respVal) != null) {
                        var respSort = parseNumber(respVal);
                    } else {
                        var respSort = respVal.toLowerCase();
                    }

                    if (sortVotes) {
                        // Voted: sort by (-) vote tally and then by response
                        sortVals.push( [-shareSubrow[j][voteOffset], respSort, j]);
                    } else if (voteParam && !explainOffset) {
                        // Voting on responses: sort by time and then response value
                        sortVals.push( [timeVal, respSort, j]);
                    } else {
                        // Explaining response or not voting; sort by response value and then time
                        sortVals.push( [respSort, timeVal, j] );
                    }
		}
		if (sortVotes || (voteParam && !explainOffset))
		    sortVals.sort(numSort); // (sort numerically)
		else
		    sortVals.sort();

                if (adminUser || paramId == TESTUSER_ID) {
                    var nameMap = lookupRoster('name');
                    if (!nameMap) {
                        nameMap = {};
                        for (var j=0; j < nRows; j++) {
                            nameMap[idValues[j][0]] = nameValues[j][0];
                        }
                    }
                    nameMap = makeShortNames(nameMap);
                    returnInfo.responders = [];
                    if (teamAttr == 'setup') {
                        var teamMembers = {}
                        for (var j=0; j < nRows; j++) {
                            var idValue = idValues[j][0];
                            if (nameMap && nameMap[idValue]) {
                                var name = nameMap[idValue];
                            } else {
                                var name = idValue;
                            }
                            var teamName = shareSubrow[j][0];
                            if (teamName) {
                                if (teamName in teamMembers) {
                                    teamMembers[teamName].push(name);
                                } else {
                                    teamMembers[teamName] = [name];
                                }
                            }
                        }
                        var teamNames = Object.keys(teamMembers);
                        teamNames.sort();
                        for (var k=0; k < teamNames.length; k++) {
                            returnInfo['responders'].push(teamNames[k]+': '+(teamMembers[teamNames[k]]).join(', '));
                        }
                    } else {
                        for (var j=0; j < nRows; j++) {
                            var idValue = idValues[j][0];
                            if (!includeId[idValue]) {
                                continue;
                            }
                            if (responderTeam[idValue]) {
                                returnInfo['responders'].push(responderTeam[idValue]);
                            } else if (nameMap && nameMap[idValue]) {
                                returnInfo['responders'].push(nameMap[idValue]);
                            } else {
                                returnInfo['responders'].push(idValue);
                            }
                        }
                    }
                    returnInfo['responders'].sort();
                }

		//returnMessages.push('Debug::getShare: '+nCols+', '+nRows+', ['+curUserVals+']');
		returnValues = [];
		for (var j=0; j<sortVals.length; j++) {
                    returnValues.push( shareSubrow[sortVals[j][2]] );
		}
	    }
	} else {
	    if (rowUpdates && selectedUpdates) {
		throw('Error::Cannot specify both rowUpdates and selectedUpdates');
	    } else if (rowUpdates) {
		if (rowUpdates.length != columnHeaders.length)
		    throw("Error::row_headers length ("+rowUpdates.length+") differs from no. of columns ("+columnHeaders.length+") in sheet '"+sheetName+"'; delete sheet or edit headers.");

		userId = rowUpdates[columnIndex['id']-1] || '';
		displayName = rowUpdates[columnIndex['name']-1] || '';

		// Security check
		if (paramId && paramId != userId)
		    throw("Error::Mismatch between paramId '"+paramId+"' and userId in row '"+userId+"'")
		if (params.name && params.name != displayName)
		    throw("Error::Mismatch between params.name '"+params.name+"' and displayName in row '"+displayName+"'")
		if (!adminUser && userId == MAXSCORE_ID)
		    throw("Error::Only admin user may specify ID "+MAXSCORE_ID)
	    } else {
		userId = paramId || null;
	    }

	    if (!userId)
		throw('Error::userID must be specified for updates/gets');
	    var userRow = 0;
	    if (modSheet.getLastRow() > numStickyRows && !loggingSheet) {
		// Locate unique ID row (except for log files)
		userRow = lookupRowIndex(userId, modSheet, 1+numStickyRows);
	    }
	    //returnMessages.push('Debug::userRow, userid, rosterValues: '+userRow+', '+userId+', '+str(rosterValues));
	    var newRow = !userRow;

	    if ((readOnlyAccess || adminUser) && !restrictedSheet && newRow && userId != MAXSCORE_ID && !importSession)
		throw("Error::Admin user not allowed to create new row in sheet '"+sheetName+"'");

	    var retakesCol = columnIndex['retakes'];
	    if (resetRow) {
		// Reset row
		if (newRow)
		    throw('Error:RETAKES:Cannot reset new row');
		if (!sessionEntries)
		    throw('Error:RETAKES:Reset only allowed for sessions');
		var fieldsMin = sessionEntries['fieldsMin'];
		newRow = true;

		var origVals = modSheet.getRange(userRow, 1, 1, columnHeaders.length).getValues()[0];
		if (adminUser || paramId == TESTUSER_ID) {
		    // For admin or test user, also reset retakes count
		    var retakesVal = ''
		} else {
		    if (origVals[columnIndex['submitTimestamp']-1])
			throw('Error:RETAKES:Retakes not allowed for submitted sessions');

		    var maxRetakes = sessionAttributes.params.maxRetakes;
		    if (!maxRetakes)
			throw('Error:RETAKES:Retakes not allowed');

		    var retakesList = origVals[retakesCol-1] ? origVals[retakesCol-1].split(',') : [];
		    if (retakesList.length >= maxRetakes)
			throw('Error:RETAKES:No more retakes available');

		    // Save score for last take
		    var savedSession = unpackSession(columnHeaders, origVals);
		    if (savedSession && Object.keys(savedSession.questionsAttempted).length && computeTotalScore) {
			var scores = tallyScores(questions, savedSession['questionsAttempted'], savedSession['hintsUsed'], sessionAttributes['params'], sessionAttributes['remoteAnswers']);
			var lastTake = str(scores.weightedCorrect || 0);
                    } else {
			var lastTake = '0';
		    }

		    // Update retakes score list
		    retakesList.push(lastTake);
		    var retakesVal = retakesList.join(',');
		}

		createRow = origVals[columnIndex['source']-1];
		rowUpdates = createSessionRow(sheetName, sessionEntries.fieldsMin, sessionAttributes.params, questions,
					      userId, origVals[columnIndex['name']-1], origVals[columnIndex['email']-1],
					      origVals[columnIndex['altid']-1], createRow, retakesVal, seedRow);


		// Preserve name and lateToken on reset
		rowUpdates[columnIndex['name']-1] = origVals[columnIndex['name']-1];
		rowUpdates[columnIndex['lateToken']-1] = params.late || origVals[columnIndex['lateToken']-1];

	    } else if (newRow && !rowUpdates && createRow) {
		// Initialize new row
		if (sessionEntries) {
		    rowUpdates = createSessionRow(sheetName, sessionEntries.fieldsMin, sessionAttributes.params, questions,
						  userId, params.name, params.email, params.altid,
						  createRow, '', seedRow);
		    displayName = rowUpdates[columnIndex['name']-1] || '';
		    if (params.late && columnIndex['lateToken'])
			rowUpdates[columnIndex['lateToken']-1] = params.late;
		} else {
		    rowUpdates = [];
		    for (var j=0; j<columnHeaders.length; j++) {
			rowUpdates.push(null);
		    }
                    if (sheetName.match(/-discuss$/)) {
                        displayName = params.name || '';
                        rowUpdates[columnIndex['id']-1] = userId;
                        rowUpdates[columnIndex['name']-1] = displayName;
                    }
		}
	    }

	    if (!adminUser && frozenSessions && (newRow || rowUpdates || selectedUpdates))
		throw('Error::All sessions are frozen. No user modifications permitted');
	    
	    var teamCol = columnIndex.team;
            if (newRow && rowUpdates && teamCol && sessionAttributes && sessionAttributes.sessionTeam == 'roster') {
		// Copy team name from roster
		var teamName = lookupRoster('team', userId);
		if (teamName) {
                    rowUpdates[teamCol-1] = teamName;
		}
            }

	    if (newRow && getRow && !rowUpdates) {
		// Row does not exist; return empty list
		returnValues = [];
		if (!adminUser && timedSec)
		    returnInfo['timedSecLeft'] = timedSec;

	    } else if (newRow && selectedUpdates) {
		throw('Error::Selected updates cannot be applied to new row');
	    } else {
		var pastSubmitDeadline = false;
		var autoSubmission = false;
		var fieldsMin = columnHeaders.length;
		var submitTimestampCol = columnIndex['submitTimestamp'];
		var prevSubmitted = null;
		if (!newRow && submitTimestampCol)
		    prevSubmitted = modSheet.getSheetValues(userRow, submitTimestampCol, 1, 1)[0][0] || null;

		if (sessionEntries) {
		    // Indexed session
		    fieldsMin = sessionEntries.fieldsMin;

		    if (rowUpdates && !nooverwriteRow && prevSubmitted)
			throw("Error::Cannot re-submit session for user "+userId+" in sheet '"+sheetName+"'");

		    if (voteDate)
			returnInfo.voteDate = voteDate;

                    if (dueDate && !prevSubmitted && !voteSubmission && !discussionPost && !alterSubmission && userId != MAXSCORE_ID) {
                        // Check if past submission deadline
                        var lateToken = '';
			var pastSubmitDeadline = curTime > dueDate.getTime();
                        if (pastSubmitDeadline) {
                            var lateTokenCol = columnIndex.lateToken;
			    lateToken = (rowUpdates && rowUpdates.length >= lateTokenCol) ? (rowUpdates[lateTokenCol-1] || null) : null;
                            if (!lateToken && !newRow) {
                                lateToken = modSheet.getRange(userRow, lateTokenCol, 1, 1).getValues()[0][0] || '';
                            }

                            if (lateToken && lateToken.indexOf(':') > 0) {
                                // Check against new due date
                                var newDueDate = getNewDueDate(userId, Settings['site_name'], sheetName, lateToken);
                                if (!newDueDate) {
                                    throw("Error:INVALID_LATE_TOKEN:Invalid token '"+lateToken+"' for late submission by user "+(displayName || "")+" to session '"+sheetName+"'");
                                }

                                dueDate = newDueDate;
                                pastSubmitDeadline = curTime > dueDate.getTime();
                            }
                        }
			
			returnInfo.dueDate = dueDate; // May have been updated

			var allowLateMods = adminUser || importSession || !Settings['require_late_token'] || lateToken == LATE_SUBMIT;
                        if (!allowLateMods) {
                            if (pastSubmitDeadline) {
                                if (getRow && !(newRow || rowUpdates || selectedUpdates)) {
                                    // Reading existing row; force submit
                                    autoSubmission = true;
                                    selectedUpdates = [ ['id', userId], ['Timestamp', null], ['submitTimestamp', null] ];
                                    returnMessages.push("Warning:FORCED_SUBMISSION:Forced submission for user '"+(displayName || "")+"' to session '"+sheetName+"'");
                                } else {
                                    // Creating/modifying row
                                    throw("Error:PAST_SUBMIT_DEADLINE:Past submit deadline ("+dueDate+") for session "+sheetName);
                                }
                            } else if ((dueDate.getTime() - curTime) < 2*60*60*1000) {
                                returnMessages.push("Warning:NEAR_SUBMIT_DEADLINE:Nearing submit deadline ("+dueDate+") for session "+sheetName);
                            }
                        }

		    }
		}

		var numRows = modSheet.getLastRow();
		if (newRow && !resetRow) {
		    // New user; insert row in sorted order of name (except for log files)
		    if ((userId != MAXSCORE_ID && !displayName) || !rowUpdates)
			throw('Error::User name and row parameters required to create a new row for id '+userId+' in sheet '+sheetName);
			
		    if (numRows > numStickyRows && !loggingSheet) {
			var displayNames = modSheet.getSheetValues(1+numStickyRows, columnIndex['name'], numRows-numStickyRows, 1);
			var userIds = modSheet.getSheetValues(1+numStickyRows, columnIndex['id'], numRows-numStickyRows, 1);
			userRow = numStickyRows + locateNewRow(displayName, userId, displayNames, userIds);
			if (userId == MAXSCORE_ID && userRow != numStickyRows+1)
			    throw('Error::Inconsistent _maxscore row insert in row '+str(userRow)+' in sheet '+sheetName);
		    } else {
			userRow = numRows+1;
		    }
		    // NOTE: modSheet.getLastRow() is not updated immediately after row insertion!
		    modSheet.insertRowBefore(userRow);
		    numRows += 1;
		    if (columnIndex['q_total'] && userId != MAXSCORE_ID)
			updateTotalFormula(modSheet, numRows);
		} else if (rowUpdates && nooverwriteRow) {
		    if (getRow) {
			// Simply return existing row
			rowUpdates = null;
		    } else {
			throw('Error::Do not specify nooverwrite=1 to overwrite existing rows');
		    }
		}

		var maxCol = rowUpdates ? rowUpdates.length : columnHeaders.length;
		var totalCol = columnIndex['q_total'] || 0;
		var scoresCol = columnIndex['q_scores'] || 0;
		var userRange = modSheet.getRange(userRow, 1, 1, maxCol);
		var rowValues = userRange.getValues()[0];

                if (!adminUser && timedSec) {
                    // Updating timed session
                    var initTime = rowValues[columnIndex['initTimestamp']-1];
                    if (initTime) {
                        var timedSecLeft = timedSec - (curTime - initTime.getTime())/1000.
                    } else {
                        var timedSecLeft = timedSec;
                    }
		    if (timedSecLeft >= 1) {
			if (!prevSubmitted)
                            returnInfo['timedSecLeft'] = parseInt(timedSecLeft);
                    } else if (timedSecLeft < -TIMED_GRACE_SEC && rowUpdates) {
                        throw('Error:TIMED_EXPIRED:Past deadline for timed session.');
                    }
                }

		returnInfo.prevTimestamp = ('Timestamp' in columnIndex && rowValues[columnIndex['Timestamp']-1]) ? rowValues[columnIndex['Timestamp']-1].getTime() : null;
		if (returnInfo.prevTimestamp && params.timestamp && parseNumber(params.timestamp) && returnInfo.prevTimestamp > parseNumber(params.timestamp))
		    throw('Error::Row timestamp too old by '+Math.ceil((returnInfo.prevTimestamp-parseNumber(params.timestamp))/1000)+' seconds. Conflicting modifications from another active browser session?');

		var teamCopyCols = [];
		if (rowUpdates) {
		    // Update all non-null and non-id row values
		    // Timestamp is always updated, unless it is specified by admin
		    if (adminUser && sessionEntries && userId != MAXSCORE_ID && !importSession && !resetRow)
			throw("Error::Admin user not allowed to update full rows in sheet '"+sheetName+"'");

		    if (submitTimestampCol && rowUpdates[submitTimestampCol-1] && userId != TESTUSER_ID)
			throw("Error::Submitted session cannot be re-submitted for sheet '"+sheetName+"'");

		    if ((!adminUser || importSession) && rowUpdates.length > fieldsMin) {
			// Check if there are any user provided non-null values for "extra" columns (i.e., response/explain values)
			var nonNullExtraColumn = false;
			var adminColumns = {};
			for (var j=fieldsMin; j < columnHeaders.length; j++) {
			    if (rowUpdates[j] != null)
				nonNullExtraColumn = true;
			    var hmatch = QFIELD_RE.exec(columnHeaders[j]);
			    if (!hmatch || (hmatch[2] != 'response' && hmatch[2] != 'explain' && hmatch[2] != 'plugin')) // Non-response/explain/plugin admin column
				adminColumns[columnHeaders[j]] = 1;
			}
			if (nonNullExtraColumn && !adminUser) {
			    // Blank out admin columns if any extra column is non-null
			    // Failsafe: ensures admin-entered grades will be blanked out if response/explain are updated
			    for (var j=fieldsMin; j < columnHeaders.length; j++) {
				if (columnHeaders[j] in adminColumns)
				    rowUpdates[j] = '';
			    }
			}
                        if (totalCol) {
                            // Filled by array formula
                            rowUpdates[totalCol-1] = '';
                        }
			//returnMessages.push("Debug::"+nonNullExtraColumn+Object.keys(adminColumns));
		    }

		    //returnMessages.push("Debug:ROW_UPDATES:"+rowUpdates);
		    for (var j=0; j<rowUpdates.length; j++) {
			var colHeader = columnHeaders[j];
			var colValue = rowUpdates[j];
			if (colHeader == 'retakes' && !newRow) {
			    // Retakes are always updated separately
			} else if (colHeader == 'q_total') {
			    // Modify only for max score; otherwise leave blank (to be overwritten by array formula)
			    if (!TOTAL_COLUMN && userId == MAXSCORE_ID && totalCol)
				rowValues[j] = gradesFormula(columnHeaders, totalCol+1, numRows);
			    else
				rowValues[j] = '';
			} else if (colHeader == 'Timestamp') {
			    // Timestamp is always updated, unless it is explicitly specified by admin
			    if (adminUser && colValue) {
				rowValues[j] = createDate(colValue);
			    } else {
				rowValues[j] = curDate;
			    }
			} else if (colHeader == 'initTimestamp' && newRow) {
			    rowValues[j] = curDate;
			} else if (colHeader == 'submitTimestamp' && params.submit) {
			    if (userId == TESTUSER_ID && colValue) {
				// Only test user may overwrite submitTimestamp
				rowValues[j] = createDate(colValue);
			    } else {
                                if (paceLevel == ADMIN_PACE && userId != TESTUSER_ID && !dueDate) {
                                    throw("Error::Cannot submit instructor-paced session before instructor for sheet '"+sheetName+"'");
                                }
				rowValues[j] = curDate;
				if (teamCol && rowValues[teamCol-1]) {
                                    teamCopyCols.push(j+1);
                                }
			    }
			    returnInfo.submitTimestamp = rowValues[j];
			} else if (colHeader.match(/_share$/)) {
			    // Generate share value by computing message digest of 'response [: explain]'
			    if (j >= 1 && rowValues[j-1] && rowValues[j-1] != SKIP_ANSWER && columnHeaders[j-1].match(/_response$/)) {
				// Upvote response
				rowValues[j] = digestHex(normalizeText(rowValues[j-1]));
			    } else if (j >= 2 && rowValues[j-1] && columnHeaders[j-1].match(/_explain$/) && columnHeaders[j-2].match(/_response$/)) {
				// Upvote response: explanation
				rowValues[j] = digestHex(rowValues[j-1]+': '+normalizeText(rowValues[j-2]));
			    } else {
				rowValues[j] = '';
			    }
			} else if (colValue == null) {
			    // Do not modify field
			} else if (newRow || (MIN_HEADERS.indexOf(colHeader) == -1 && !colHeader.match(/Timestamp$/)) ) {
			    // Id, name, email, altid, *Timestamp cannot be updated programmatically
			    // (If necessary to change name manually, then re-sort manually)
			    var hmatch = QFIELD_RE.exec(colHeader);
                            var teamAttr = '';
                            if (hmatch && (hmatch[2] == 'response' || hmatch[2] == 'explain' || hmatch[2] == 'plugin')) {
                                var qno = parseInt(hmatch[1]);
                                if (questions && qno <= questions.length) {
                                    teamAttr = questions[qno-1].team || '';
                                }
                            }
                            if (teamAttr == 'setup') {
                                if (hmatch[2] == 'response' && colValue != SKIP_ANSWER) {
                                    // Set up team name (capitalized)
                                    rowValues[teamCol-1] = safeName(colValue, true);
                                    returnInfo['team'] = rowValues[teamCol-1];
                                }
                            } else if (teamAttr == 'response' && rowValues[teamCol-1]) {
				// Copy response/explain/plugin for team
                                teamCopyCols.push(j+1);
                                if (hmatch && hmatch[2] == 'response') {
                                    var shareCol = columnIndex['q'+hmatch[1]+'_share'];
                                    if (shareCol) {
					// Copy share code
                                        teamCopyCols.push(shareCol);
                                    }
                                }
                            }

			    rowValues[j] = parseInput(colValue, colHeader);
			} else {
			    if (rowValues[j] !== colValue)
				throw("Error::Cannot modify column '"+colHeader+"'. Specify as 'null'");
			}
		    }

		    if (userId != MAXSCORE_ID && scoresCol && computeTotalScore) {
			// Tally user scores
			var savedSession = unpackSession(columnHeaders, rowValues);
			if (savedSession && Object.keys(savedSession.questionsAttempted).length) {
			    var scores = tallyScores(questions, savedSession.questionsAttempted, savedSession.hintsUsed, sessionAttributes.params, sessionAttributes.remoteAnswers);
			    rowValues[scoresCol-1] = scores.weightedCorrect || '';
			}
		    }
		    // Copy user info from roster (if available)
		    if (rosterValues) {
			for (var j=0; j<MIN_HEADERS.length; j++)
			    rowValues[j] = rosterValues[MIN_HEADERS[j]] || '';
		    }
		    //returnMessages.push("Debug:ROW_VALUES:"+rowValues);
		    // Save updated row
		    userRange.setValues([rowValues]);

                    var discussRowOffset = 2;
                    var discussNameCol = 1;
                    var discussIdCol = 2;
                    if (sessionEntries && adminPaced && paramId == TESTUSER_ID) {
			// AdminPaced test user row update
                        var lastSlideCol = columnIndex['lastSlide'];
                        if (lastSlideCol && rowValues[lastSlideCol-1]) {
                            // Copy test user last slide number as new adminPaced value
			    adminPaced = rowValues[lastSlideCol-1];
                            setValue(sheetName, 'adminPaced', adminPaced, INDEX_SHEET);
                        }
                        if (params.submit) {
                            // Use test user submission time as due date for admin-paced sessions
			    var submitTimetamp = rowValues[submitTimestampCol-1];
                            setValue(sheetName, 'dueDate', submitTimetamp, INDEX_SHEET);

			    var discussSheet = null;
                            var discussRowCount = 0;
                            if (discussableSession) {
                                // Create discussion sheet
                                var discussHeaders = ['name', 'id'];
                                var discussRow = ['', DISCUSS_ID];
                                for (var j=0; j<sessionAttributes['discussSlides'].length; j++) {
				    var slideNum = sessionAttributes['discussSlides'][j];
                                    discussHeaders.push('access'+zeroPad(slideNum,3));
                                    discussHeaders.push('discuss'+zeroPad(slideNum,3));
                                    discussRow.push(0);
                                    discussRow.push('');
                                }
				if (getSheet(sheetName+'-discuss'))
				    throw('Discussions already posted for session '+sheetName+'; delete session to overwrite');
                                discussSheet = createSheet(sheetName+'-discuss', discussHeaders);
				discussSheet.insertRowBefore(2)
                                discussSheet.getRange(2, 1, 1, discussRow.length).setValues([discussRow]);
                                discussRowCount = discussRowOffset;
                            }

                            var idRowIndex = indexRows(modSheet, columnIndex['id']);
                            var idColValues = getColumns('id', modSheet, 1, 1+numStickyRows);
                            var nameColValues = getColumns('name', modSheet, 1, 1+numStickyRows);
                            var initColValues = getColumns('initTimestamp', modSheet, 1, 1+numStickyRows);
                            for (var j=0; j < idColValues.length; j++) {
                                // Submit all other users who have started a session
                                if (initColValues[j] && idColValues[j] && idColValues[j] != TESTUSER_ID && idColValues[j] != MAXSCORE_ID) {
                                    modSheet.getRange(idRowIndex[idColValues[j]], submitTimestampCol, 1, 1).setValues([[submitTimestamp]]);

                                    if (discussSheet) {
                                        // Add submitted user to discussion sheet
                                        discussRowCount += 1;
					discussSheet.insertRowBefore(discussRowCount);
                                        discussSheet.getRange(discussRowCount, discussIdCol, 1, 1).setValues([[idColValues[j]]]);
                                        discussSheet.getRange(discussRowCount, discussNameCol, 1, 1).setValues([[nameColValues[j]]]);
                                    }
                                }
                            }
                        }

                    } else if (sessionEntries && adminPaced && dueDate && discussableSession && params.submit) {
                        var discussSheet = getSheet(sheetName+'-discuss');
                        if (discussSheet) {
                            var discussRows = discussSheet.getLastRow();
                            var discussNames = discussSheet.getSheetValues(1+discussRowOffset, discussNameCol, numRows-discussRowOffset, 1);
                            var discussIds = discussSheet.getSheetValues(1+discussRowOffset, discussIdCol, numRows-discussRowOffset, 1);
                            var temRow = discussRowOffset + locateNewRow(displayName, userId, discussNames, discussIds);
                            discussSheet.insertRowBefore(temRow);
                            discussSheet.getRange(temRow, discussIdCol, 1, 1).setValues([[userId]]);
                            discussSheet.getRange(temRow, discussNameCol, 1, 1).setValues([[displayName]]);
                        }

                    }

		} else if (selectedUpdates) {
		    // Update selected row values
		    // Timestamp is updated only if specified in list
		    if (!autoSubmission && !voteSubmission && !discussionPost && !twitterSetting) {
			if (!adminUser)
			    throw("Error::Only admin user allowed to make selected updates to sheet '"+sheetName+"'");

			if (sessionEntries) {
			    // Admin can modify grade columns only for submitted sessions before 'effective' due date
			    // and only for non-late submissions thereafter
			    var allowGrading = prevSubmitted || (pastSubmitDeadline && lateToken != LATE_SUBMIT);
			    if (!allowGrading && !importSession && !alterSubmission)
				throw("Error::Cannot selectively update non-submitted/non-late session for user "+userId+" in sheet '"+sheetName+"'");
			}
		    }

		    if (voteSubmission) {
			// Allow vote submissions only after due date and before voting deadline
			if (voteSubmission == 'after_due_date' && (!dueDate || dueDate.getTime() > curDate.getTime()))
			    throw("Error:TOO_EARLY_TO_VOTE:Voting only allowed after due date for sheet '"+sheetName+"'");
			if (voteSubmission == 'after_grading' && !gradeDate)
			    throw("Error:TOO_EARLY_TO_VOTE:Voting only allowed after grading for sheet '"+sheetName+"'");
			if (voteDate && voteDate.getTime() < curDate.getTime())
			    throw("Error:TOO_LATE_TO_VOTE:Voting not allowed after vote date for sheet '"+sheetName+"'");
		    }


		    for (var j=0; j<selectedUpdates.length; j++) {
			var colHeader = selectedUpdates[j][0];
			var colValue = selectedUpdates[j][1];
			
			if (!(colHeader in columnIndex))
			    throw("Error::Field "+colHeader+" not found in sheet '"+sheetName+"'");

			var headerColumn = columnIndex[colHeader];
			var modValue = null;

			if (colHeader == 'Timestamp') {
			    // Timestamp is always updated, unless it is explicitly specified by admin or if voting
			    if (voteSubmission) {
				// Do not modify timestamp for voting (to avoid race conditions with grading etc.)
			    } else if (adminUser && colValue) {
				modValue = createDate(colValue);
			    } else {
				modValue = curDate;
			    }
			} else if (colHeader == 'submitTimestamp') {
                            if (autoSubmission) {
				modValue = curDate;
			    } else if (alterSubmission) {
                                if (colValue == null) {
                                    modValue = curDate;
                                } else if (colValue) {
                                    modValue = createDate(colValue);
                                } else {
                                    // Unsubmit if blank value (also clear lateToken and due date, if admin paced)
                                    modValue = '';
                                    modSheet.getRange(userRow, columnIndex['lateToken'], 1, 1).setValues([[ '' ]]);
				    if (sessionEntries && adminPaced && paramId == TESTUSER_ID) {
					setValue(sheetName, 'dueDate', '', INDEX_SHEET);
				    }
                                }
                                if (modValue) {
                                    returnInfo['submitTimestamp'] = modValue;
                                }
			    } else if (adminUser && colValue) {
				modValue = createDate(colValue);
			    }

                            if (rowValues[teamCol-1]) {
                                // Broadcast submission to all team members
                                teamCopyCols.push(headerColumn);
                            }
			} else if (colHeader.match(/_vote$/)) {
			    if (voteSubmission && colValue) {
				// Cannot un-vote, vote can be transferred
				var otherCol = columnIndex['q_other'];
				if (!rowValues[headerColumn-1] && otherCol && sessionEntries.otherWeight && sessionAttributes.shareAnswers) {
				    // Tally newly added vote
				    var qshare = sessionAttributes.shareAnswers[colHeader.split('_')[0]];
				    if (qshare) {
					rowValues[otherCol-1] = str( (parseInt(rowValues[otherCol-1] || 0) + (qshare.voteWeight || 0)) );
					modSheet.getRange(userRow, otherCol, 1, 1).setValues([[ rowValues[otherCol-1] ]])
				    }
				}
				modValue = colValue;
			    }
                        } else if (colHeader.match(/^discuss/) && discussionPost) {
                            var prevValue = rowValues[headerColumn-1];
			    if (prevValue && !POST_PREFIX_RE.exec(prevValue)) {
                                throw('Invalid discussion post entry in column '+colHeader+' for session '+sheetName);
                            }
                            if (colValue.toLowerCase().match(/^delete:/)) {
                                // Delete post
				var userPosts = ('\n'+prevValue).split('\nPost:').slice(1);
                                var deleteLabel = zeroPad( parseInt(colValue.slice('delete:'.length)), 3);
                                for (var j=0; j<userPosts.length; j++) {
                                    if (userPosts[j].slice(0,deleteLabel.length) == deleteLabel) {
                                        // "Delete" post by prefixing it with (deleted)
                                        var comps = userPosts[j].split(' ');
                                        userPosts[j] = comps[0]+' '+DELETED_POST+' '+comps.slice(1).join(' ');
                                        modValue = 'Post:' + userPosts.join('\nPost:');
                                        break;
                                    }
                                }
                            } else {
                                // New post
                                var discussRow = lookupRowIndex(DISCUSS_ID, modSheet);
                                if (!discussRow) {
                                    throw('Row with id '+DISCUSS_ID+' not found in sheet '+sheetName);
                                }

                                // Update post count and last post time
                                var axsHeader = 'access' + zeroPad(discussionPost[1],3);
                                var axsColumn = columnIndex[axsHeader];

                                var axsRange = modSheet.getRange(discussRow, axsColumn, 1, 1);

                                var postCount = (axsRange.getValues()[0][0] || 0) + 1;
                                axsRange.setValues([[ postCount ]]);

                                modValue = prevValue ? prevValue + '\n' : '';
                                modValue += 'Post:'+zeroPad(postCount,3)+':'+curDate.toISOString().slice(0,19);
                                modValue += colValue;
                                if (!modValue.match(/\n$/)) {
                                    modValue += '\n';
                                }
                            }
			} else if (colValue == null) {
			    // Do not modify field
			} else if (MIN_HEADERS.indexOf(colHeader) == -1 && colHeader.slice(-9) != 'Timestamp') {
			    // Update row values for header (except for id, name, email, altid, *Timestamp)
			    if (!restrictedSheet && !twitterSetting && !importSession && (headerColumn <= fieldsMin || !QFIELD_MOD_RE.exec(colHeader)) )
				throw("Error::Cannot selectively update user-defined column '"+colHeader+"' in sheet '"+sheetName+"'");
			    var hmatch = QFIELD_RE.exec(colHeader);
                            if (hmatch && (hmatch[2] == 'grade' || hmatch[2] == 'comments')) {
                                var qno = parseInt(hmatch[1]);
                                if (rowValues[teamCol-1] && questions && qno <= questions.length && questions[qno-1].team == 'response') {
                                    // Broadcast grade/comments to all team members (q_other/q_comments are not broadcast)
                                    teamCopyCols.push(headerColumn);
                                }
                            }
			    colValue = parseInput(colValue, colHeader);
			    modValue = colValue;
			} else {
			    if (rowValues[headerColumn-1] !== colValue)
				throw("Error::Cannot modify column '"+colHeader+"'. Specify as 'null'");
			}
			if (modValue !== null) {
			    rowValues[headerColumn-1] = modValue;
			    modSheet.getRange(userRow, headerColumn, 1, 1).setValues([[ rowValues[headerColumn-1] ]]);
			}
		    }

                    if (discussionPost) {
                        returnInfo['discussPosts'] = getDiscussPosts(discussionPost[0], discussionPost[1], userId);
                    }

		}

                if (teamCopyCols.length) {
		    var nCopyRows = numRows-numStickyRows;
		    var idValues = modSheet.getSheetValues(1+numStickyRows, columnIndex['id'], nCopyRows, 1);
                    var teamValues = modSheet.getSheetValues(1+numStickyRows, teamCol, nCopyRows, 1);
                    var userOffset = userRow-numStickyRows-1;
                    var teamName = teamValues[userOffset][0];
                    if (teamName) {
                        returnInfo['teamModifiedIds'] = [];
                        for (var j=0; j < idValues.length; j++) {
                            if (teamValues[j][0] == teamName) {
                                returnInfo['teamModifiedIds'].push(idValues[j][0]);
                            }
                        }

                        for (var j=0; j < teamCopyCols.length; j++) {
                            // Broadcast modified team values
                            teamCopy(modSheet, numStickyRows, userRow, teamCol, teamCopyCols[j]);
                        }
                    }
                }

                if ((paramId != TESTUSER_ID || prevSubmitted || params.submit) && sessionEntries && adminPaced)
                    returnInfo['adminPaced'] = adminPaced;

		// Return updated timestamp
		returnInfo.timestamp = ('Timestamp' in columnIndex) ? rowValues[columnIndex['Timestamp']-1].getTime() : null;
		
		returnValues = getRow ? rowValues : [];

		if (!adminUser && (!gradeDate || !rowValues[submitTimestampCol-1])) {
		    // If session not graded/submitted, blank out grade-related columns
		    for (var j=fieldsMin; j < returnValues.length; j++) {
			if (!columnHeaders[j].match(/_response$/) && !columnHeaders[j].match(/_explain$/) && !columnHeaders[j].match(/_plugin$/))
			    returnValues[j] = null;
		    }
		} else if (!adminUser && gradeDate) {
		    returnInfo.gradeDate = gradeDate;
		}

                if (getRow && createRow && discussableSession && dueDate) {
		    // Accessing submitted discussable session
                    returnInfo['discussStats'] = getDiscussStats(sheetName, userId);
                }

                if (computeTotalScore && getRow) {
                    returnInfo['remoteAnswers'] = sessionAttributes.remoteAnswers;
                }
	    }
	}

        if (sessionEntries && getRow && (allRows || (createRow && paramId == TESTUSER_ID))) {
            // Getting all session rows or test user row (with creation); return related sheet names
            returnInfo['sheetsAvailable'] = [];
            for (var j=0; j<RELATED_SHEETS.length; j++) {
                if (getSheet(sheetName+'-'+RELATED_SHEETS[j])) {
                    returnInfo['sheetsAvailable'].push(RELATED_SHEETS[j]);
                }
            }
        }

	if (completeActions.length) {
	    returnInfo.refreshSheets = returnInfo.refreshSheets.concat(actionHandler(completeActions.join(','), sheetName));
	}

	// return success results
	trackCall(0, 'success');
	return {"result":"success", "value": returnValues, "headers": returnHeaders,
		"info": returnInfo,
		"messages": returnMessages.join('\n')};
    } catch(err){
	// if error return this
	trackCall(0, 'error: '+err);
	return {"result":"error", "error": ''+err, "errtrace": ''+(err.stack||''), "value": null,
		"info": returnInfo,
		"messages": returnMessages.join('\n')};
    } finally { //release lock
	lock.releaseLock();
    }
}


function handleProxyUpdates(data, create, returnMessages) {
    var refreshSheets = []
    var updateErrors = [];
    for (var isheet=0; isheet<data.length; isheet++) {
	var updateSheetName   = data[isheet][0];
	var proxyActions      = data[isheet][1];
	var modifiedHeaders   = data[isheet][2];
	var updateHeaders     = data[isheet][3];
	var updateLastRow     = data[isheet][4];
	var updateAllKeys     = data[isheet][5];
	var updateInsertNames = data[isheet][6];
	var updateCols        = data[isheet][7];
	var updateInsertRows  = data[isheet][8];
	var updateRows        = data[isheet][9];

	var debugMsg = 'Debug::updateSheet, actions, modHeaders, headers, updateAllKeys, insertNames, updatecols, ninserts, nupdates: '+updateSheetName+', '+proxyActions+', '+modifiedHeaders+', '+updateHeaders+', '+updateAllKeys+', '+updateInsertNames+', '+updateCols+', '+updateInsertRows.length+', '+updateRows.length;
	trackCall(1, debugMsg);
	//returnMessages.push(debugMsg);

	try {
	    var updateSheet = getSheet(updateSheetName);
	    if (!updateSheet) {
		if (create)
		    updateSheet = createSheet(updateSheetName, updateHeaders);
		else
		    throw("Error:PROXY_MISSING_SHEET:Sheet not found: '"+updateSheetName+"'");
	    }

	    trackCall(1, 'updateSheet: start total_col='+TOTAL_COLUMN+', '+ProxyCacheRange+', '+updateSheetName+', '+updateSheet.getLastRow()+', '+updateSheet.getLastColumn());

	    var temHeaders = updateSheet.getSheetValues(1, 1, 1, updateSheet.getLastColumn())[0];

	    if (modifiedHeaders) {
		// Modify headers
		if (updateHeaders.length > temHeaders.length)
		    updateSheet.insertColumnsAfter(temHeaders.length, updateHeaders.length - temHeaders.length);

		else if (updateHeaders.length < temHeaders.length)
		    updateSheet.deleteColumns(updateHeaders.length+1, temHeaders.length - updateHeaders.length);

		updateSheet.getRange(1, 1, 1, updateHeaders.length).setValues([updateHeaders]);

	    } else {
		if (updateHeaders.length != temHeaders.length)
		    throw("Error:PROXY_HEADER_COUNT:Number of headers does not equal that present in sheet '"+updateSheetName+"'; delete it or edit headers.");

		for (var m=0; m<updateHeaders.length; m++) {
		    if (updateHeaders[m] != temHeaders[m])
			throw("Error:PROXY_HEADER_NAMES:Column header mismatch: Expected "+updateHeaders[m]+" but found "+temHeaders[m]+" in sheet '"+updateSheetName+"'");
		}
	    }
	    var allColNums = [];
	    for (var m=0; m<updateHeaders.length; m++)
		allColNums.push(m+1);

	    if (updateAllKeys === null) {
		// Update non-keyed sheet

		if (updateInsertNames.length)
		    throw('Error: Update cannot insert rows for non-keyed sheet '+updateSheetName);

		if (updateSheet.getLastRow() > updateLastRow) {
		    // Delete excess rows
		    updateSheet.deleteRows(updateLastRow+1, updateSheet.getLastRow()-updateLastRow);

		} else if (updateLastRow > updateSheet.getMaxRows()) {
		    // Insert extra rows
		    updateSheet.insertRowsAfter(updateSheet.getMaxRows(), updateLastRow-updateSheet.getMaxRows());
		}

		for (var krow=0; krow<updateRows.length; krow++) {
		    var rowNums = updateRows[krow][0];
		    var rowCols = updateRows[krow][1];
		    var rowSel  = updateRows[krow][2];

		    var nUpdateCols = updateHeaders.length;
		    var nUpdateRows = rowSel.length;

		    if (rowCols)
			throw('Error::Update must include all columns for non-keyed sheet '+updateSheetName);

		    if (rowNums.length != nUpdateRows)
			throw('Error:PROXY_UPDATE_NUMS:No. of ids '+rowNums.length+' differs from no. of rows '+nUpdateRows+' for sheet '+updateSheetName);

		    // Parse time strings in update values
		    for (var mcol=0; mcol<nUpdateCols; mcol++) {

			if (timeColumn(updateHeaders[mcol])) {

			    for (var mrow=0; mrow<nUpdateRows; mrow++) {
				if (rowSel[mrow][mcol]) {
				    try { rowSel[mrow][mcol] = createDate(rowSel[mrow][mcol]); } catch (err) { }
				}
			    }
			}
		    }
		    updateSheet.getRange(rowNums[0], 1, nUpdateRows, nUpdateCols).setValues(rowSel);
		}

	    } else {
		// Update keyed sheet

		var lastRowNum = updateSheet.getLastRow();
		// NOTE: Do not directly use .getLastRow() after this until row deletion/insertion is complete
		// The array formula may temporarirly generate additional rows until updated
		// (Also, sometimes .getLastRow() does not immediately respond to inserted rows)
		
		if (lastRowNum < 1)
		    throw('Error:PROXY_DATA_ROWS:Sheet has no data rows: '+updateSheetName);

		var updateColumnIndex = indexColumns(updateSheet);
		var idCol = updateColumnIndex['id'];
		var nameCol = updateColumnIndex['name'] || idCol;
		var totalCol = updateColumnIndex['q_total'];
		var deletedRows = 0;
		var insertedRows = 0;
		var updateKeysObj = {};
		for (var k=0; k < updateAllKeys.length; k++)
		    updateKeysObj[updateAllKeys[k]] = k+1;

		var headerOffset = 1;
		var idValues = updateSheet.getSheetValues(1+headerOffset, idCol, lastRowNum-headerOffset, 1);
		var nameValues = updateSheet.getSheetValues(1+headerOffset, nameCol, lastRowNum-headerOffset, 1);

		var updateStickyRows = lastRowNum;
		if (lastRowNum > 1) {
		    // Determine number of sticky rows (header row plus any rows with no ids)
		    for (var k=0; k < idValues.length; k++) {
			// Locate first non-null key
			if (idValues[k][0]) {
			    updateStickyRows = k+headerOffset;
			    break;
			}
		    }

		    ///trackCall(1, 'updateSheet: ids ['+idValues.join(',')+']');
		    var deletedIds = [];
		    for (var rowNum=lastRowNum; rowNum > updateStickyRows; rowNum--) {
			// Delete rows for which keys are not found (backwards)
			var idValue = idValues[rowNum-1-headerOffset][0];
			if (!(idValue in updateKeysObj)) {
			    updateSheet.deleteRow(rowNum);
			    deletedRows += 1;
			    deletedIds.push(idValue);
			}
		    }

		    if (deletedIds.length)
			trackCall(1, 'updateSheet: deleted ids '+deletedIds.length+' ['+deletedIds.join(',')+']');
		}
		lastRowNum = lastRowNum - deletedRows;

		if (updateStickyRows > headerOffset || deletedRows) {
		    // Refresh row ids and names
		    idValues = updateSheet.getSheetValues(1+updateStickyRows, idCol, lastRowNum-updateStickyRows, 1);
		    nameValues = updateSheet.getSheetValues(1+updateStickyRows, nameCol, lastRowNum-updateStickyRows, 1);
		}

		if (updateInsertNames.length) {
		    var idRow = {}
		    for (var jrow=0; jrow<idValues.length; jrow++)
			idRow[idValues[jrow][0]] = jrow+1+updateStickyRows;

		    var startRow = 0;
		    var rowCount = 0;
		    for (var kinsert=0; kinsert<=updateInsertNames.length; kinsert++) {
			// NOTE: Loop termination condition is UNUSUAL
			// Check if row to be inserted is pre-existing row
			var preRow = (kinsert<updateInsertNames.length) ? idRow[updateInsertNames[kinsert][1]] : 0;
			if (preRow && rowCount && preRow == startRow+rowCount) {
			    // Contiguous block
			    rowCount += 1;
			    continue;
			}
			if (rowCount) {
			    // Overwrite contiguous "insert" block
			    updateSheet.getRange(startRow, 1, rowCount, updateHeaders.length).setValues(updateInsertRows.slice(kinsert-rowCount,kinsert));
			    trackCall(2, updateSheetName+':insertoverwrite '+' '+startRow+' '+rowCount);
			    startRow = 0;
			    rowCount = 0;
			}
			if (preRow) {
			    // New block
			    startRow = preRow;
			    rowCount = 1;
			}
		    }

		    var jinsert = 0;
		    for (var jrow=0; jrow<idValues.length; jrow++) {
			var prevCount = 0;
			var insertCount = 0;

			for (var kinsert=jinsert; kinsert<updateInsertNames.length; kinsert++) {
			    if (idRow[updateInsertNames[kinsert][1]])  {
				// Skip pre-existing row (handled earlier)
				prevCount += 1;
				break;
			    }

			    if (updateInsertNames[kinsert][0] < nameValues[jrow][0] || (updateInsertNames[kinsert][0] == nameValues[jrow][0] && updateInsertNames[kinsert][1] < idValues[jrow][0]) ) {
				// New row to be inserted (should be located before current row)
				insertCount += 1;
			    } else {
				break;
			    }
			}
			if (insertCount) {
			    var beforeRow = jrow+1+insertedRows+updateStickyRows;
			    updateSheet.insertRowsBefore(beforeRow, insertCount);
			    updateSheet.getRange(beforeRow, 1, insertCount, updateHeaders.length).setValues(updateInsertRows.slice(jinsert,jinsert+insertCount));
			    trackCall(2, updateSheetName+':insertbefore '+' '+beforeRow+' '+insertCount);

			    insertedRows += insertCount;
			    jinsert += insertCount;
			}
			jinsert += prevCount;
			if (jinsert >= updateInsertNames.length)
			    break;
		    }

		    if (jinsert < updateInsertNames.length) {
			var afterRow = idValues.length+insertedRows+updateStickyRows;
			var insertCount = updateInsertNames.length-jinsert;
			insertedRows += insertCount;
			var temInsertCount = afterRow+insertCount - updateSheet.getMaxRows();
			if (temInsertCount > 0)
			    updateSheet.insertRowsAfter(afterRow, temInsertCount);
			updateSheet.getRange(afterRow+1, 1, insertCount, updateHeaders.length).setValues(updateInsertRows.slice(jinsert,jinsert+insertCount));
			trackCall(1, updateSheetName+':afterRow '+afterRow+' '+insertCount);
		    }
		}

		lastRowNum += insertedRows;
		if (insertedRows) {
		    // Refresh row ids and names
		    idValues = updateSheet.getSheetValues(1+updateStickyRows, idCol, lastRowNum-updateStickyRows, 1);
		    nameValues = updateSheet.getSheetValues(1+updateStickyRows, nameCol, lastRowNum-updateStickyRows, 1);
		}

		trackCall(2, updateSheetName+':ids ['+updateAllKeys.join(',')+'], ['+idValues.join(',')+'] '+lastRowNum+' '+updateStickyRows);

		if (updateAllKeys.length !=  idValues.length)
		    throw('Error:PROXY_UPDATE_MISMATCH:Mismatched id count '+updateAllKeys.length+' vs. '+idValues.length+' in sheet '+updateSheetName);

		// Check that row ids match and names are in order
		var modRowIndex = {};
		for (var mrow=0; mrow<idValues.length; mrow++) {
		    modRowIndex[idValues[mrow][0]] = mrow + 1 + updateStickyRows;

		    if (updateAllKeys[mrow] != idValues[mrow][0]) {
			throw('Error:PROXY_UPDATE_MISMATCH:Mismatched row ids '+updateAllKeys[mrow]+' vs. '+idValues[mrow][0]+' in row '+(mrow+updateStickyRows)+' sheet '+updateSheetName);
		    }

		    if ((deletedRows || insertedRows) && mrow && (nameValues[mrow-1][0] > nameValues[mrow][0]  || (nameValues[mrow-1][0] == nameValues[mrow][0] && idValues[mrow-1][0] > idValues[mrow][0])))
			throw('Error:PROXY_UPDATE_ORDER:Out of sequence name/id '+nameValues[mrow-1][0]+' >= '+nameValues[mrow][0])

		}

		trackCall(2, updateSheetName+':deleteinsert -'+deletedRows+', +'+insertedRows);

		var modBlocks = [];
		var maxEndCol = 0;
		for (var krow=0; krow<updateRows.length; krow++) {
		    // Update rows with pre-existing or new keys
		    var rowPartial = !!updateRows[krow][1];

		    var rowIds = updateRows[krow][0];
		    var rowCols = updateRows[krow][1] || allColNums;
		    var rowSel = updateRows[krow][2];

		    var firstUpdateCol = rowCols[0];
		    var lastUpdateCol = rowCols.slice(-1)[0];
		    var nUpdateCols = rowCols.length;
		    var nUpdateRows = rowSel.length;

		    if (rowIds.length != nUpdateRows)
			throw('Error:PROXY_PARTIAL_IDS:No. of ids '+rowIds.length+' differs from no. of rows '+nUpdateRows);

		    // Parse time strings in update values
		    for (var mcol=0; mcol<nUpdateCols; mcol++) {

			if (timeColumn(updateHeaders[rowCols[mcol]-1])) {

			    for (var mrow=0; mrow<nUpdateRows; mrow++) {
				if (rowSel[mrow][mcol]) {
				    try { rowSel[mrow][mcol] = createDate(rowSel[mrow][mcol]); } catch (err) { }
				}
			    }
			}
		    }

		    // Pre-existing row(s)
		    var modStartRow = modRowIndex[rowIds[0]];
		    if (!modStartRow)
			throw('Error:PROXY_UPDATE_ERROR: Inconsistency error: start row id '+rowIds[0]+' not found!');

		    if (rowPartial) {
			// Pre-existing rows (partial update)
			var pStartCol = rowCols[0];
			var pEndCol = rowCols[nUpdateCols-1];

			var checkIdOffset = rowCols.indexOf(idCol);

			var totalColFormulas = null;
			if (!TOTAL_COLUMN && totalCol && totalCol >= pStartCol && totalCol <= pEndCol) {
			    // Total column within range; get formula values
			    totalColFormulas = updateSheet.getRange(modStartRow, totalCol, nUpdateRows, 1).getFormulas();
			}

			// Update block
			var modRange = updateSheet.getRange(modStartRow, pStartCol, nUpdateRows, pEndCol-pStartCol+1);
			var modVals = modRange.getValues();

			for (var mrow=0; mrow < nUpdateRows; mrow++) {
			    var modRow = modVals[mrow];
			    var newRow = rowSel[mrow];

			    if (checkIdOffset >= 0 && newRow[checkIdOffset] != modRow[idCol-pStartCol])
				throw('Error:PROXY_PARTIAL_UPDATE: New id '+newRow[checkIdOffset]+' differs from old id '+modRow[idCol-pStartCol]+' in sheet '+updateSheetName);

			    for (var mcol=0; mcol<nUpdateCols; mcol++) {
				modRow[ rowCols[mcol]-pStartCol ] = newRow[mcol];
			    }

			    if (totalColFormulas) {
				// Do not overwrite old totalCol formula value for pre-existing row (formula updated by updateTotalFormula)
				modRow[totalCol-pStartCol] = totalColFormulas[mrow][0];
			    }
			}
			modRange.setValues(modVals);
			trackCall(2, updateSheetName+':partial '+modStartRow+' '+nUpdateRows+' '+pStartCol+' '+pEndCol);

		    } else {
			// Pre-existing row (full update)
			if (nUpdateRows > 1)
			    throw('Error:PROXY_PARTIAL_UPDATE:Unable to update multiple ids from '+rowIds[0]+' in sheet '+updateSheetName);
			var curRow = rowSel[0];
			var prevVals = updateSheet.getRange(modStartRow, 1, 1, curRow.length).getValues()[0];

			if (!TOTAL_COLUMN && totalCol) {
			    // Do not overwrite old totalCol formula value for pre-existing row (formula updated by updateTotalFormula)
			    prevVals[totalCol-1] = updateSheet.getRange(modStartRow, totalCol, 1, 1).getFormula();
			    curRow[totalCol-1] = prevVals[totalCol-1];
			}

			var diffStartCol = 1;
			var diffEndCol = 0;
			for (var mcol=0; mcol<curRow.length; mcol++) {
			    if (timeColumn(updateHeaders[mcol])) {
				var diff = !timeEqual(prevVals[mcol], curRow[mcol]);
			    } else {
				var diff = (prevVals[mcol] !== curRow[mcol]);
			    }
			    if (diff) {
				diffEndCol = mcol+1;
			    } else {
				if (diffStartCol == mcol+1)
				    diffStartCol += 1;
			    }
			}

			// Only update range of values that have changed (for efficiency)
			if (diffEndCol >= diffStartCol) {
			    maxEndCol = Math.max(maxEndCol, diffEndCol);
			    modBlocks.push([modStartRow, diffStartCol, diffEndCol, curRow.slice(diffStartCol-1, diffEndCol)]);
			}
		    }

		    //returnMessages.push('Debug::updateRow: '+modRow+', '+curRow);
		}

		if (modBlocks.length) {
		    // Carry out updates in contiguous rectangular blocks, sorting numerically (for full row updates only)
		    modBlocks.sort(numSort);

		    var startRow = 0;
		    var endRow = 0;
		    var startCol = 0;
		    var endCol = 0;
		    var blockRowVals = [];
		    for (var k=0; k<modBlocks.length; k++) {
			var row = modBlocks[k];
			if (blockRowVals.length && (endRow+1 != row[0] || startCol != row[1] || endCol != row[2])) {

			    trackCall(2, updateSheetName+':block '+startRow+' '+endRow+' '+startCol+' '+endCol);

			    updateSheet.getRange(startRow, startCol, endRow-startRow+1, endCol-startCol+1).setValues(blockRowVals);
			    blockRowVals = [];
			}
			// Contiguous rectangular block to be updated
			if (!blockRowVals.length) {
			    startRow = row[0];
			    startCol = row[1];
			    endCol = row[2];
			}
			blockRowVals.push(row[3]);
			endRow = row[0];
		    }

		    if (blockRowVals.length) {
			trackCall(2, updateSheetName+':block '+startRow+' '+endRow+' '+startCol+' '+endCol);
			updateSheet.getRange(startRow, startCol, endRow-startRow+1, endCol-startCol+1).setValues(blockRowVals);
		    }

		}
		trackCall(2, updateSheetName+':end');

		if (!TOTAL_COLUMN && totalCol && (deletedRows || insertedRows))
		    updateTotalFormula(updateSheet, lastRowNum);

		if (proxyActions) {
		    // Perform actions after cache updates have been applied
		    try {
			refreshSheets = actionHandler(proxyActions, updateSheetName);
		    } catch(err) {
			updateErrors.push([updateSheetName, "Error:ACTION:Failed proxy action(s) "+proxyActions+' for sheet '+updateSheetName+': '+err, ''+(err.stack||'')]);
		    }
		}

	    }
	} catch(err) {
	    var errMsg = ''+err;
	    ///if (errMsg.match(/^Error:PROXY_/))
	    updateErrors.push([updateSheetName, errMsg, ''+(err.stack||'')]);
	    ///else
	    ///throw(errMsg);
	}
    }
    return [refreshSheets, updateErrors];
}

function getSessionNames() {
    var indexSheet = getSheet(INDEX_SHEET);
    if (!indexSheet)
	throw('Session index sheet not found: '+INDEX_SHEET);

    return getColumns('id', indexSheet);
}

var LCRandom = (function() {
  // Set to values from http://en.wikipedia.org/wiki/Numerical_Recipes
      // m is basically chosen to be large (as it is the max period)
      // and for its relationships to a and c
  var nbytes = 4;
  var sequences = {};
  var m = Math.pow(2,nbytes*8),
      // a - 1 should be divisible by prime factors of m
      a = 1664525,
      // c and m should be co-prime
      c = 1013904223;
  function makeSeed(val) {
      return val ? (val % m) : Math.round(Math.random() * m);
  }
  function setSeed(seedValue) {
      // Start new random number sequence using seed value as the label
      // or a new random seed, if seed value is null
      var label = seedValue || '';
      sequences[label] = makeSeed(seedValue);
      return label;
  }
  function uniform(seedValue) {
      // define the recurrence relationship
      var label = seedValue || '';
      if (!(label in sequences))
	  throw('Random number generator not initialized properly:'+label);
      sequences[label] = (a * sequences[label] + c) % m;
      // return a float in [0, 1) 
      // if sequences[label] = m then sequences[label] / m = 0 therefore (sequences[label] % m) / m < 1 always
      return sequences[label] / m;
  }
  return {
    makeSeed: makeSeed,

    setSeed: setSeed,

    setSeedMD5: function(seedKey, labelStr) {  // NOT USED YET
	// Set seed to HMAC of labelStr and seedKey
	return setSeed( parseInt(md5(labelStr, ''+seedKey).slice(0,nbytes*2), 16) );
    },
    randomNumber: function(seedValue, min, max) {
	// Equally probable integer values between min and max (inclusive)
	// If min is omitted, equally probable integer values between 1 and max
	// If both omitted, value uniformly distributed between 0.0 and 1.0 (<1.0)
	if (!isNumber(min))
	    return uniform(seedValue);
	if (!isNumber(max)) {
	    max = min;
	    min = 1;
	}
	return Math.min(max, Math.floor( min + (max-min+1)*uniform(seedValue) ));
    }
  };
}());


var RandomChoiceOffset = 1;
function makeRandomChoiceSeed(randomSeed) {
    return LCRandom.makeSeed(RandomChoiceOffset+randomSeed);
}

function makeRandomFunction(seed) {
    LCRandom.setSeed(seed);
    return LCRandom.randomNumber.bind(null, seed);
}

function letterFromIndex(n) {
    return String.fromCharCode('A'.charCodeAt(0) + n);
}

function shuffleArray(array, randFunc) {
    // Durstenfeld shuffle
    for (var i = array.length - 1; i > 0; i--) {
        var j = randFunc ? randFunc(0, i) : Math.floor(Math.random() * (i + 1));
        var temp = array[i];
        array[i] = array[j];
        array[j] = temp;
    }
    return array;
}

function randomLetters(n, noshuffle, randFunc) {
    var letters = [];
    for (var i=0; i < n; i++)
	letters.push( letterFromIndex(i) );

    var nmix = Math.max(0, n - noshuffle);
    if (nmix > 1) {
        var cmix = letters.slice(0,nmix);
	shuffleArray(cmix, randFunc);
        letters = cmix.concat(letters.slice(nmix));
    }

    return letters.join('');
}

function createSession(sessionName, params, questions, retakes, randomSeed) {
    var persistPlugins = {};
    for (var j=0; j<params.plugins.length; j++)
	persistPlugins[params.plugins[j]] = {};

    if (!randomSeed)
        randomSeed = LCRandom.makeSeed();

    var qshuffle = null;
    if (questions && params['features'].shuffle_choice) {
        var randFunc = makeRandomFunction(makeRandomChoiceSeed(randomSeed));
        qshuffle = {};
        for (var qno=1; qno < questions.length+1; qno++) {
            var choices = questions[qno-1].choices || 0;
            var noshuffle = questions[qno-1].noshuffle || 0;
            if (choices) {
                qshuffle[qno] = randFunc(0,1) + randomLetters(choices, noshuffle, randFunc);
            }
        }
    }

    return {'version': params.sessionVersion,
	    'revision': params.sessionRevision,
	    'paced': params.paceLevel || 0,
	    'submitted': null,
	    'displayName': '',
	    'source': '',
	    'team': '',
	    'lateToken': '',
	    'lastSlide': 0,
	    'retakes': retakes || '',
	    'randomSeed': randomSeed, // Save random seed
            'expiryTime': Date.now() + 180*86400*1000,   // 180 day lifetime
            'startTime': Date.now(),
            'lastTime': 0,
            'lastTries': 0,
            'remainingTries': 0,
            'tryDelay': 0,
	    'showTime': null,
            'questionShuffle': qshuffle,
            'questionsAttempted': {},
	    'hintsUsed': {},
	    'plugins': persistPlugins
	   };

}

function createSessionRow(sessionName, fieldsMin, params, questions, userId, displayName, email, altid, source, retakes, randomSeed) {
    var headers = params.sessionFields.concat(params.gradeFields);
    var idCol = headers.indexOf('id') + 1;
    var nameCol = headers.indexOf('name') + 1;
    var emailCol = headers.indexOf('email') + 1;
    var altidCol = headers.indexOf('altid') + 1;
    var session = createSession(sessionName, params, questions, retakes, randomSeed);
    var rowVals = [];
    for (var j=0; j<headers.length; j++) {
	rowVals[j] = '';
	var header = headers[j];
	if (header in session && COPY_HEADERS.indexOf(header) >= 0)
	    rowVals[j] = session[header];
    }
    rowVals[headers.indexOf('source')] = source || '';
    rowVals[headers.indexOf('session_hidden')] = orderedStringify(session);

    var rosterSheet = getSheet(ROSTER_SHEET);
    if (rosterSheet) {
	var rosterValues = getRosterEntry(userId);

	if (rosterValues) {
	    for (var j=0; j<MIN_HEADERS.length; j++) {
		if (rosterValues[MIN_HEADERS[j]])
		    rowValues[j] = rosterValues[MIN_HEADERS[j]];
	    }
	}
    }

    // Management fields
    rowVals[idCol-1] = userId;

    if (!rowVals[nameCol-1]) {
	if (!displayName)
	    throw('Name parameter must be specified to create row');
	rowVals[nameCol-1] = displayName;
    }

    if (!rowVals[emailCol-1] && email)
	rowVals[emailCol-1] = email;

    if (!rowVals[altidCol-1] && altid)
	rowVals[altidCol-1] = altid;
    
    return rowVals;
}
    
function getUserRow(sessionName, userId, displayName, opts) {
    var token = genAuthToken(Settings['auth_key'], userId);
    var getParams = {'id': userId, 'token': token,'sheet': sessionName,
		     'name': displayName, 'get': '1'};
    if (opts) {
	var keys = Object.keys(opts);
	for (var j=0; j<keys.length; j++)
	    getParams[keys[j]] = opts[keys[j]];
    }

    return sheetAction(getParams);
}

////// Utility functions

function str(x) { return x+''; }

function isNumber(x) { return !!(x+'') && !isNaN(x+''); }

function parseNumber(x) {
    try {
	if (!isNumber(x))
	    return null;
	if (typeof x == 'string') {
	    var retval = parseFloat(x);
	    return isNaN(retval) ? null : retval;
	}
	if (!isNaN(x))
	    return x || 0;
    } catch(err) {
    }
    return null;
}

function isArray(a) {
    return Array.isArray(a);
};

function isObject(a) { // Works for object literals only (not custom objects, Date etc.)
    return (!!a) && (a.constructor === Object);
};


function cmp(a,b) { if (a == b) return 0; else return (a > b) ? 1 : -1; }

function keyCmp(a,b) {
    // Compare keys, with numeric keys always being less than non-numeric keys
    if (isNumber(a) && !isNumber(b))
	return -1;
    if (!isNumber(a) && isNumber(b))
	return 1;
    if (a == b) return 0; else return (a > b) ? 1 : -1;
}

function sortObject(obj) {
    return Object.keys(obj).sort(keyCmp).reduce(function (result, key) {
        result[key] = obj[key];
        return result;
    }, {});
}

function orderedReplacer(key, value) {
    if (!key && isObject(value))
	return sortObject(value);
    else
	return value;
}

function orderedStringify(value, space) {
    return orderedStringify(value, orderedReplacer, space);
}

function normalizeText(s) {
   // Lowercase, replace single/double quotes with null, all other non-alphanumerics with spaces,
   // replace 'a', 'an', 'the' with space, and then normalize spaces
    return (''+s).toLowerCase().replace(/['"]/g,'').replace(/\b(a|an|the) /g, ' ').replace(/[_\W]/g,' ').replace(/\s+/g, ' ').trim();
}

function bin2hex(array) {
    return array.map(function(b) {return ("0" + ((b < 0 && b + 256) || b).toString(16)).substr(-2)}).join("");
}

function digestHex(s, n) {
    return bin2hex(Utilities.computeDigest(DIGEST_ALGORITHM, s)).slice(0, n||TRUNCATE_DIGEST);
}

function splitToken(token) {
    var match = RegExp('^(.+):([^:]+)$').exec(token);
    if (!match)
	throw('Invalid HMAC token; no colon');    
    return [match[1], match[2]];
}

function createDate(date) {
    // Ensure that UTC date string ends in :00.000Z (needed to workaround bug in Google Apps)
    if (typeof date === 'string') {
	if (!date)
	    return '';
	if (date.toLowerCase() == FUTURE_DATE)
            return FUTURE_DATE;
	if (date.slice(-1) == 'Z') {
	    if (date.length == 17)      // yyyy-mm-ddThh:mmZ
		date = date.slice(0,-1) + ':00.000Z';
	    else if (date.length == 20) // yyyy-mm-ddThh:mm:ssZ
		date = date.slice(0,-1) + '.000Z';
	    else if (date.length > 24) // yyyy-mm-ddThh:mm:ss.mmmZ
		date = date.slice(0,23) + 'Z';
	}
    }
    var d = new Date(date);
    if (!d || !d.getTime || isNaN(d.getTime()))
	return '';
    else
	return d;
}

function getNewDueDate(userId, siteName, sessionName, lateToken) {
    var comps = splitToken(lateToken);
    var dateStr = comps[0];
    var tokenStr = comps[1];
    if (genLateToken(Settings['auth_key'], userId, siteName, sessionName, dateStr) == lateToken) {
        return createDate(dateStr);  // Date format: '1995-12-17T03:24Z'
    } else {
        return null;
    }
}
    
function timeColumn(header) {
    return header.slice(-4).toLowerCase() == 'date' || header.slice(-4).toLowerCase() == 'time' || header.slice(-9) == 'Timestamp';
}

function timeEqual(a, b) {
    // Compare timestamps (to within a second); also handle special value 'future'
    if (!a && !b)
	return true;
    if ((typeof a) != (typeof b))
	return false
    if (typeof a == 'string')
	return a == b;
    if (a && b)
	return a.toISOString().slice(0,19) == b.toISOString().slice(0,19);
    return false;
}

function parseInput(value, headerName) {
    // Parse input date strings
    if (value && timeColumn(headerName)) {
	try { return createDate(value); } catch (err) { }
    }
    return value;
}

function genAuthPrefix(userId, role, sites) {
    return ':' + userId + ':' + (role||'') + ':' + (sites||'');
}

function genAuthToken(key, userId, role, sites, prefixed) {
    var prefix = genAuthPrefix(userId, role, sites);
    var token = genHmacToken(key, prefix);
    return prefixed ? (prefix+':'+token) : token;
}

function genHmacToken(key, message) {
    var rawHMAC = Utilities.computeHmacSignature(HMAC_ALGORITHM,
						 message, key,
						 Utilities.Charset.US_ASCII);
    return Utilities.base64Encode(rawHMAC).slice(0,TRUNCATE_DIGEST);
}

function genLateToken(key, userId, siteName, sessionName, dateStr) {
    // Use UTC date string of the form '1995-12-17T03:24' (append Z for UTC time)
    if (dateStr.slice(-1) != 'Z') {  // Convert local time to UTC
	var date = createDate(dateStr+'Z');
	// Adjust for local time zone
	date.setTime( date.getTime() + date.getTimezoneOffset()*60*1000 );
	dateStr = date.toISOString().slice(0,16)+'Z';
    }
    return dateStr+':'+genHmacToken(key, 'late:'+userId+':'+siteName+':'+sessionName+':'+dateStr);
}

function validateHMAC(token, key) {
    // Validates HMAC token of the form message:signature
    var comps = splitToken(token);
    var message = comps[0];
    var signature = comps[1];
    return genHmacToken(key, message) == signature;
}

function getSheet(sheetName) {
    // Return sheet in current document, if present.
    var doc = getDoc();

    return doc.getSheetByName(sheetName);
}

function deleteSheet(sheetName) {
    var temSheet = getSheet(sheetName);
    if (!temSheet)
	return false;
    var doc = getDoc();
    doc.deleteSheet(temSheet);
    return true;
}

function createSheet(sheetName, headers, overwrite) {
    if (!headers) {
	throw("Must specify headers to create sheet "+sheetName);
    }

    var doc = getDoc();
    var sheet = doc.getSheetByName(sheetName);

    if (!sheet) {
	sheet = doc.insertSheet(sheetName);
	if (sheet.getMaxRows() > 50)
	    sheet.deleteRows(51, sheet.getMaxRows()-50);
    } else if (overwrite) {
	sheet.clear();
    } else {
	throw('Cannot overwrite sheet '+sheetName);
    }

    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
    sheet.getRange('1:1').setFontWeight('bold');

    for (var j=0; j<headers.length; j++) {
	if (headers[j].slice(-6).toLowerCase() == 'hidden')
	    sheet.hideColumns(j+1);
	if (headers[j].slice(-4).toLowerCase() == 'date' || headers[j].slice(-4).toLowerCase() == 'time') {
	    ///var c = colIndexToChar(j+1);
	    ///sheet.getRange(c+'2:'+c).setNumberFormat("yyyy-MM-ddTHH:mmZ");
	}
    }

    if (sheetName == INDEX_SHEET) {
	var protection = sheet.protect().setDescription('protected');
	protection.setUnprotectedRanges([sheet.getRange('E2:F')]);
	protection.setDomainEdit(false);
    }

    return sheet;
}
	    
function colIndexToChar(col) {
    var suffix = (col - 1) % 26;
    var prefix = (col - 1 - suffix) / 26;
    var c = String.fromCharCode('A'.charCodeAt(0) + suffix);
    if (prefix)
        c = String.fromCharCode('A'.charCodeAt(0) + prefix - 1) + c;
    return c;
}

function indexColumns(sheet) {
    var columnHeaders = sheet.getSheetValues(1, 1, 1, sheet.getLastColumn())[0];
    var columnIndex = {};
    for (var j=0; j<columnHeaders.length; j++)
	columnIndex[columnHeaders[j]] = j+1;
    return columnIndex;
}

function indexRows(sheet, indexCol, startRow) {
    // startRow defaults to 2
    startRow = startRow || 2;
    var rowIndex = {};
    var nRows = sheet.getLastRow()-startRow+1;
    if (nRows > 0) {
	var rowIds = sheet.getSheetValues(startRow, indexCol, nRows, 1);
	for (var j=0; j<rowIds.length; j++)
	    rowIndex[rowIds[j][0]] = j+startRow;
    }
    return rowIndex;
}

function getColumns(header, sheet, colCount, startRow) {
    startRow = startRow || 2;
    var colIndex = indexColumns(sheet);
    if (!(header in colIndex))
	throw('Column '+header+' not found in sheet '+sheetName);
    if (colCount && colCount > 1) {
	// Multiple columns (list of lists)
	return sheet.getSheetValues(startRow, colIndex[header], sheet.getLastRow()-startRow+1, colCount)
    } else {
	// Single column
	var vals = sheet.getSheetValues(startRow, colIndex[header], sheet.getLastRow()-startRow+1, 1);
	var retvals = [];
	for (var j=0; j<vals.length; j++)
	    retvals.push(vals[j][0]);
	return retvals;
    }
}

function getColumnMax(sheet, startRow, colNum) {
    var values = sheet.getSheetValues(startRow, colNum, sheet.getLastRow()-startRow+1, 1);
    var maxVal = 0;
    for (var j=0; j < values.length; j++) {
        if (values[j][0]) {
            maxVal = Math.max(maxVal, parseInt(values[j][0]));
        }
    }
    return maxVal;
}

function lookupRowIndex(idValue, sheet, startRow) {
    // Return row number for idValue in sheet or return 0
    // startRow defaults to 2
    startRow = startRow || 2;
    var nRows = sheet.getLastRow()-startRow+1;
    if (!nRows)
	return 0;
    var rowIds = sheet.getSheetValues(startRow, indexColumns(sheet)['id'], nRows, 1);
    for (var j=0; j<rowIds.length; j++) {
	if (idValue == rowIds[j][0])
	    return j+startRow;
    }
    return 0;
}

function lookupValues(idValue, colNames, sheetName, listReturn, blankValues) {
    // Return parameters in list colNames for idValue from sheet
    // If blankValues, return blanks for columns not found
    var indexSheet = getSheet(sheetName);
    if (!indexSheet)
	throw('Index sheet '+sheetName+' not found');
    var indexColIndex = indexColumns(indexSheet);
    var indexRowIndex = indexRows(indexSheet, indexColIndex['id'], 2);
    var sessionRow = indexRowIndex[idValue];
    if (!sessionRow)
	throw('ID value '+idValue+' not found in index sheet '+sheetName)
    var retVals = {};
    var listVals = [];
    for (var j=0; j < colNames.length; j++) {
	var colValue = '';
	if (colNames[j] in indexColIndex) {
	    colValue = indexSheet.getSheetValues(sessionRow, indexColIndex[colNames[j]], 1, 1)[0][0];
	} else if (!blankValues) {
	    throw('Column '+colNames[j]+' not found in index sheet '+sheetName);
	}
	retVals[colNames[j]] = colValue;
	listVals.push(retVals[colNames[j]]);
    }
    return listReturn ? listVals : retVals;
}

function setValue(idValue, colName, colValue, sheetName) {
    // Set parameter in colName for idValue in sheet
    var indexSheet = getSheet(sheetName);
    if (!indexSheet)
	throw('Index sheet '+sheetName+' not found');
    var indexColIndex = indexColumns(indexSheet);
    var indexRowIndex = indexRows(indexSheet, indexColIndex['id'], 2);
    var sessionRow = indexRowIndex[idValue];
    if (!sessionRow)
	throw('ID value '+idValue+' not found in index sheet '+sheetName)
    if (!(colName in indexColIndex))
        throw('Column '+colName+' not found in index sheet '+sheetName);

    indexSheet.getRange(sessionRow, indexColIndex[colName], 1, 1).setValue(colValue);
}

function locateNewRow(newName, newId, nameValues, idValues) {
    // Return row number before which new name/id combination should be inserted
    for (var j=0; j<nameValues.length; j++) {
	if (nameValues[j][0] > newName || (nameValues[j][0] == newName && idValues[j][0] > newId)) {
	    // Sort by name and then by id (blank names will be first)
	    return j+1;
	}
    }
    return nameValues.length+1;
}

function lookupRoster(field, userId) {
    var rosterSheet = getSheet(ROSTER_SHEET);
    if (!rosterSheet) {
        return null;
    }

    var colIndex = indexColumns(rosterSheet);
    if (!colIndex[field]) {
        return null;
    }

    if (userId) {
        var rowIndex = indexRows(rosterSheet, colIndex['id'], 2);
        if (!rowIndex[userId]) {
            return null;
        }
        return lookupValues(userId, [field], ROSTER_SHEET, true)[0];
    }

    var idVals = getColumns('id', rosterSheet, 1, 2);
    var fieldVals = getColumns(field, rosterSheet, 1, 2);
    var fieldDict = {};
    for (var j=0; j < idVals.length; j++) {
        fieldDict[idVals[j]] = fieldVals[j];
    }
    return fieldDict;
}

function safeName(s, capitalize) {
    s = s.replace(/[^A-Za-z0-9-]/g, '_');
    if (s && capitalize)
	return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
    else
	return s;
}

function getDiscussStats(sessionName, userId) {
    // Returns per slide discussion stats { slideNum: [nPosts, unreadPosts, ...}
    var sheetName = sessionName+'-discuss';
    var discussSheet = getSheet(sheetName);
    var discussStats = {};
    if (!discussSheet) {
        return discussStats;
    }

    var discussRow = lookupRowIndex(DISCUSS_ID, discussSheet);
    if (!discussRow) {
        throw('Row with id '+DISCUSS_ID+' not found in sheet '+sheetName);
    }
    var userRow = lookupRowIndex(userId, discussSheet);
    if (!userRow) {
        throw('User with id '+userId+' not found in sheet '+sheetName);
    }

    var ncols = discussSheet.getLastColumn();
    var headers = discussSheet.getSheetValues(1, 1, 1, ncols)[0];
    var topVals = discussSheet.getSheetValues(discussRow, 1, 1, ncols)[0];
    var userVals = discussSheet.getSheetValues(userRow, 1, 1, ncols)[0];
    for (var j=0; j<ncols; j++) {
        var amatch = AXS_RE.match(headers[j]);
        if (!amatch || !topVals[j]) {
            continue;
        }
        if (j == ncols-1 || headers[j+1] != 'discuss'+amatch[1]) {
            continue;
        }
        var slideNum = parseInt(amatch[1]);
        discussStats[slideNum] = [topVals[j], topVals[j]-(userVals[j] || 0)];
    }

    return discussStats;
}

function getDiscussPosts(sessionName, slideNum, userId) {
    // Return sorted list of discussion posts [ [postNum, userId, userName, postTime, unreadFlag, postText] ]
    var sheetName = sessionName+'-discuss';
    var discussSheet = getSheet(sheetName);
    if (!discussSheet) {
        throw('Discuss sheet '+sessionName+'-discuss not found');
    }
    var colIndex = indexColumns(discussSheet);
    var axsColName = 'access' + zeroPad(slideNum,3);
    var axsCol = colIndex[axsColName];
    if (!axsCol) {
        return [];
    }

    if (userId) {
        // Update last read post
        var lastPost = lookupValues(DISCUSS_ID, [axsColName], sheetName, true)[0];
        var lastReadPost = lookupValues(userId, [axsColName], sheetName, true)[0] || 0;

        if (lastReadPost < lastPost) {
            setValue(userId, axsColName, lastPost, sheetName);
        }
    } else {
        lastReadPost = 0;
    }

    var idVals = getColumns('id', discussSheet);
    var nameVals = getColumns('name', discussSheet);
    var colVals = getColumns('discuss'+zeroPad(slideNum,3), discussSheet);
    var allPosts = [];
    for (var j=0; j<colVals.length; j++) {
        if (!idVals[j] || (idVals[j].match(/^_/) && idVals[j] != TESTUSER_ID)) {
            continue;
        }
        var userPosts = ('\n'+colVals[j]).split('\nPost:').slice(1);
        for (var k=0; k<userPosts.length; k++) {
            var pmatch = POST_NUM_RE.exec(userPosts[k]);
            if (pmatch) {
                var postNumber = parseInt(pmatch[1]);
                var postTimeStr = pmatch[2];
                var unreadFlag = userId ? postNumber > lastReadPost : false;
                var text = pmatch[3].trim()+'\n';
                if (text.slice(0,DELETED_POST.length) == DELETED_POST) {
                    // Hide text from deleted messages
                    text = DELETED_POST;
                }
                allPosts.push([postNumber, idVals[j], nameVals[j], postTimeStr, unreadFlag, text]);
            }
        }
    }

    allPosts.sort(numSort);  //  (sorting numerically)
    return allPosts;
}

function teamCopy(sessionSheet, numStickyRows, userRow, teamCol, copyCol) {
    // Copy column value from user row to entire team
    var nRows = sessionSheet.getLastRow()-numStickyRows;
    var teamValues = sessionSheet.getSheetValues(1+numStickyRows, teamCol, nRows, 1);
    var colRange = sessionSheet.getRange(1+numStickyRows, copyCol, nRows, 1);
    var colValues = colRange.getValues();
    var teamName = teamValues[userRow-numStickyRows-1][0];
    var copyValue = colValues[userRow-numStickyRows-1][0];
    if (!teamName) {
        return;
    }
    for (var j=0; j < colValues.length; j++) {
        if (teamValues[j][0] == teamName) {
            colValues[j][0] = copyValue;
        }
    }
    colRange.setValues(colValues);
}

function makeShortNames(nameMap, first) {
    // Make short versions of names from dict of the form {id: 'Last, First ...', ...}
    // If first, use first name as prefix, rather than last name
    // Returns map of id->shortName
    var prefixDict = {};
    var suffixesDict = {};
    var keys = Object.keys(nameMap);
    for (var j=0; j<keys.length; j++) {
	var idValue = keys[j];
	var name = nameMap[idValue];
	var ncomps = name.split(',');
	var lastName = ncomps[0].trim();
	var firstmiddle = (ncomps.length > 0) ? ncomps[1].trim() : '';
        var fcomps = firstmiddle.split(/\s+/);
        if (first) {
            // For Firstname, try suffixes in following order: middle_initials+Lastname
            var firstName = fcomps[0] || idValue;
            var suffix = lastName;
	    for (var k=1; k<fcomps.length; k++)
                suffix = fcomps[k].slice(0,1).toUpperCase() + suffix;
	    if (!(firstName in prefixDict))
		prefixDict[firstName] = [];
            prefixDict[firstName].push(idValue);
            suffixesDict[idValue] = suffix;
        } else {
            // For Lastname, try suffixes in following order: initials, first/middle names
            if (!lastName)
                lastName = idValue;
	    var initials = '';
	    for (var k=0; k<fcomps.length; k++)
                initials += fcomps[k].slice(0,1).toUpperCase() ;
	    if (!(lastName in prefixDict))
		prefixDict[lastName] = [];
            prefixDict[lastName].push(idValue);
            suffixesDict[idValue] = [initials, firstmiddle];
        }
    }

    var shortMap = {};
    var prefixes = Object.keys(prefixDict);
    for (var m=0; m<prefixes.length; m++) {
	var prefix = prefixes[m];
	var idValues = prefixDict[prefix];
        var unique = null;
        for (var j=0; j < (first ? 1 : 2); j++) {
	    var suffixes = [];
	    var maxlen = 0;
	    for (var k=0; k < idValues.length; k++) {
		var suffix = suffixesDict[idValues[k]][j];
		maxlen = Math.max(maxlen, suffix.length);
		suffixes.push(suffix);
	    }
            for (var k=0; k < maxlen+1; k++) {
		var truncObj = {};
		for (var l=0; l < suffixes.length; l++)
		    truncObj[suffixes[l].slice(0,k)] = 1;

                if (suffixes.length == Object.keys(truncObj).length) {
                    // Suffixes uniquely map id for this truncation
                    unique = [j, k];
                    break;
                }
            }
            if (unique) {
                break;
            }
        }
        for (var j=0; j<idValues.length; j++) {
	    var idValue = idValues[j];
            if (unique) {
                shortMap[idValue] = prefix + suffixesDict[idValue][unique[0]].slice(0,unique[1]);
            } else {
                shortMap[idValue] = prefix + '-' + idValue;
            }
        }
    }

    return shortMap;
}

function notify(message, title) {
    SpreadsheetApp.getActiveSpreadsheet().toast(message, title||'');
}

function getPrompt(title, message) {
    var ui = SpreadsheetApp.getUi();
    var response = ui.prompt(title||'', message||'', ui.ButtonSet.YES_NO);
    
    if (response.getSelectedButton() == ui.Button.YES) {
	return response.getResponseText().trim() || '';
    } else if (response.getSelectedButton() == ui.Button.NO) {
	return null;
    } else {
	return null;
    }
}

function getSessionName(prompt) {
    // Returns current slidoc session name or prompts for one
    try {
	// Check if active sheet is a slidoc sheet
	var sessionName = SpreadsheetApp.getActiveSheet().getName();
	var sessionEntries = lookupValues(sessionName, ['scoreWeight'], INDEX_SHEET);
	return sessionName;
    } catch(err) {
	if (!prompt)
	    return null;
	return getPrompt('Slidoc', 'Enter session name');
    }
}

function getNormalUserRow(sessionSheet, sessionStartRow) {
    // Returns starting row number for rows with non-special users (i.e., names not starting with # and id's not starting with _)
    var normalRow = sessionStartRow;

    var sessionColIndex = indexColumns(sessionSheet);
    var nids = sessionSheet.getLastRow()-sessionStartRow+1;
    if (nids) {
	var temIds = sessionSheet.getSheetValues(sessionStartRow, sessionColIndex['id'], nids, 1);
	var temNames = sessionSheet.getSheetValues(sessionStartRow, sessionColIndex['name'], nids, 1);
	for (var j=0; j<nids; j++) {
	    // Skip any initial row(s) in the roster with test user or ID/names starting with underscore/hash
	    // when computing averages and other stats
	    if (temIds[j][0] == TESTUSER_ID || temIds[j][0].match(/^_/) || temNames[j][0].match(/^#/))
		normalRow += 1;
	    else
		break;
	}
    }
    return normalRow;
}

function updateColumnAvg(sheet, colNum, avgRow, startRow, countBlanks) {
    var avgCell = sheet.getRange(avgRow, colNum, 1, 1);
    if (ACTION_FORMULAS) {
	var avgFormula = '=AVERAGE('+colIndexToChar(colNum)+'$'+startRow+':'+colIndexToChar(colNum)+')';
	avgCell.setValue(avgFormula);
	return;
    }
    var nRows = sheet.getLastRow()-startRow+1;
    if (!nRows)
	return;
    var colVals = sheet.getSheetValues(startRow, colNum, nRows, 1);
    var accum = 0.0;
    var count = nRows;
    for (var j=0; j<nRows; j++) {
	if (isNumber(colVals[j][0])) {
	    accum += colVals[j][0];
	} else if (!countBlanks) {
	    count -= 1;
	}
    }
    if (count) {
	avgCell.setValue(accum/count);
    } else {
	avgCell.setValue('');
    }
}

function updateAnswers(sessionName, create) {
    try {
	var sessionSheet = getSheetCache(sessionName);
	if (!sessionSheet)
	    throw('Sheet not found: '+sessionName);
	if (!sessionSheet.getLastColumn())
	    throw('No columns in sheet: '+sessionName);

	var answerSheetName = sessionName+'-answers';
	var answerSheet = getSheet(answerSheetName);
	if (!answerSheet && !create)
	    return '';
	
	var sessionColIndex = indexColumns(sessionSheet);
	var sessionColHeaders = sessionSheet.getSheetValues(1, 1, 1, sessionSheet.getLastColumn())[0];

	var sessionEntries = lookupValues(sessionName, ['attributes', 'questions'], INDEX_SHEET);
	var sessionAttributes = JSON.parse(sessionEntries.attributes);
	var questions = JSON.parse(sessionEntries.questions);
	var qtypes = [];
	var answers = [];
	for (var j=0; j<questions.length; j++) {
	    qtypes.push(questions[j].qtype||'');
	    answers.push(questions[j].correct);
	}

	// Copy columns from session sheet
	var sessionCopyCols = ['name', 'id', 'Timestamp'];
	var answerHeaders = sessionCopyCols.concat([]);
	var baseCols = answerHeaders.length;

	var respCols = [];
	var extraCols = ['expect', 'score', 'plugin', 'hints'];
	for (var j=0; j<qtypes.length; j++) {
	    var qprefix = 'q'+str(j+1);
	    var pluginMatch = PLUGIN_RE.exec(answers[j] || '');
	    var pluginAction = pluginMatch ? pluginMatch[3] : '';
	    var respColName = qprefix;
	    if (answers[j] && pluginAction != 'expect') {
		if (qtypes[j] == 'choice')
		    respColName += '_'+answers[j];
		else if (qtypes[j] == 'number')
		    respColName += '_'+answers[j].replace(' +/- ','_pm_').replace('+/-','_pm_').replace('%','pct').replace(' ','_');
	    }
	    answerHeaders.push(respColName);
	    respCols.push(answerHeaders.length);
	    if (pluginAction == 'expect')
		answerHeaders.push(qprefix+'_expect');
	    if (answers[j] || pluginAction == 'response')
		answerHeaders.push(qprefix+'_score');
	    if (pluginAction == 'response')
		answerHeaders.push(qprefix+'_plugin');
	    if (sessionAttributes.hints && sessionAttributes.hints[qprefix])
		answerHeaders.push(qprefix+'_hints');
	}

	// Session sheet columns
	var sessionStartRow = SESSION_START_ROW;

	// Answers sheet columns
	var answerAvgRow = 2;
	var answerStartRow = 3;

	// Session answers headers

	// New answers sheet
	answerSheet = createSheet(answerSheetName, answerHeaders, true);
	var ansColIndex = indexColumns(answerSheet);

	answerSheet.getRange(str(answerAvgRow)+':'+str(answerAvgRow)).setFontStyle('italic');
	answerSheet.getRange(answerAvgRow, ansColIndex['id'], 1, 1).setValues([[AVERAGE_ID]]);
	answerSheet.getRange(answerAvgRow, ansColIndex['Timestamp'], 1, 1).setValues([[new Date()]]);

	var avgStartRow = answerStartRow + getNormalUserRow(sessionSheet, sessionStartRow) - sessionStartRow;
	
	// Number of ids
	var nids = sessionSheet.getLastRow()-sessionStartRow+1;

	// Copy session values
	for (var j=0; j<sessionCopyCols.length; j++) {
	    var colHeader = sessionCopyCols[j];
	    var sessionCol = sessionColIndex[colHeader];
	    var ansCol = ansColIndex[colHeader];
	    answerSheet.getRange(answerStartRow, ansCol, nids, 1).setValues(sessionSheet.getSheetValues(sessionStartRow, sessionCol, nids, 1));
	}

	// Get hidden session values
	var hiddenSessionCol = sessionColIndex['session_hidden'];
	var hiddenVals = sessionSheet.getSheetValues(sessionStartRow, hiddenSessionCol, nids, 1);
	var qRows = [];

	for (var j=0; j<nids; j++) {
	    var rowValues = sessionSheet.getSheetValues(j+sessionStartRow, 1, 1, sessionColHeaders.length)[0];
	    var savedSession = unpackSession(sessionColHeaders, rowValues);
	    var qAttempted = savedSession.questionsAttempted;
	    var qHints = savedSession.hintsUsed;
	    var scores = tallyScores(questions, savedSession.questionsAttempted, savedSession.hintsUsed, sessionAttributes.params, sessionAttributes.remoteAnswers);

	    var rowVals = [];
	    for (var k=0; k<answerHeaders.length; k++)
		rowVals.push('');

	    for (var k=0; k<questions.length; k++) {
		var qno = k+1;
		if (qAttempted[qno]) {
		    var qprefix = 'q'+str(qno);
		    // Copy responses
		    rowVals[respCols[qno-1]-1] = (qAttempted[qno].response || '');
		    if (qAttempted[qno].explain)
			rowVals[respCols[qno-1]-1] += '\nEXPLANATION: ' + qAttempted[qno].explain;
		    // Copy extras
		    for (var m=0; m<extraCols.length; m++) {
			var attr = extraCols[m];
			var qcolName = qprefix+'_'+attr;
			if (qcolName in ansColIndex) {
			    if (attr == 'hints') {
				rowVals[ansColIndex[qcolName]-1] = qHints[qno] || '';
			    } else if (attr == 'score') {
				rowVals[ansColIndex[qcolName]-1] = scores.qscores[qno-1] || 0;
			    } else if (attr in qAttempted[qno]) {
				rowVals[ansColIndex[qcolName]-1] = (qAttempted[qno][attr]===null) ? '': qAttempted[qno][attr]
			    }
			}
		    }
		}
	    }
	    qRows.push(rowVals.slice(baseCols));
	}
	answerSheet.getRange(answerStartRow, baseCols+1, nids, answerHeaders.length-baseCols).setValues(qRows);

	for (var ansCol=baseCols+1; ansCol<=answerHeaders.length; ansCol++) {
	    if (answerHeaders[ansCol-1].slice(-6) == '_score') {
		answerSheet.getRange(answerAvgRow, ansCol, 1, 1).setNumberFormat('0.###');
		updateColumnAvg(answerSheet, ansCol, answerAvgRow, avgStartRow);
	    }
	}
    } finally {
    }
    return answerSheetName;
}


function updateCorrect(sessionName, create) {
    try {
	var sessionSheet = getSheetCache(sessionName);
	if (!sessionSheet)
	    throw('Sheet not found: '+sessionName);
	if (!sessionSheet.getLastColumn())
	    throw('No columns in sheet: '+sessionName);

	var correctSheetName = sessionName+'-correct';
	var correctSheet = getSheet(correctSheetName);
	if (!correctSheet && !create)
	    return '';

	var sessionColIndex = indexColumns(sessionSheet);
	var sessionColHeaders = sessionSheet.getSheetValues(1, 1, 1, sessionSheet.getLastColumn())[0];

	var sessionEntries = lookupValues(sessionName, ['attributes', 'questions'], INDEX_SHEET);
	var sessionAttributes = JSON.parse(sessionEntries.attributes);
	var questions = JSON.parse(sessionEntries.questions);
	var qtypes = [];
	var answers = [];
	for (var j=0; j<questions.length; j++) {
	    qtypes.push(questions[j].qtype||'');
	    answers.push(questions[j].correct);
	}

	// Copy columns from session sheet
	var sessionCopyCols = ['name', 'id', 'Timestamp'];
	var correctHeaders = sessionCopyCols.concat(['randomSeed']);
	var baseCols = correctHeaders.length;

	for (var j=0; j<questions.length; j++) {
	    correctHeaders.push('q'+str(j+1));
	}

	// Session sheet columns
	var sessionStartRow = SESSION_START_ROW;

	// Correct sheet columns
	var correctStartRow = 3;

	// New correct sheet
	correctSheet = createSheet(correctSheetName, correctHeaders, true);
	var corrColIndex = indexColumns(correctSheet);

	correctSheet.getRange('2:2').setFontStyle('italic');
	correctSheet.getRange(2, corrColIndex['id'], 1, 1).setValues([[AVERAGE_ID]]);
	correctSheet.getRange(2, corrColIndex['Timestamp'], 1, 1).setValues([[new Date()]]);

	// Number of ids
	var nids = sessionSheet.getLastRow()-sessionStartRow+1;

	// Copy session values
	for (var j=0; j<sessionCopyCols.length; j++) {
	    var colHeader = sessionCopyCols[j];
	    var sessionCol = sessionColIndex[colHeader];
	    var corrCol = corrColIndex[colHeader];
	    correctSheet.getRange(correctStartRow, corrCol, nids, 1).setValues(sessionSheet.getSheetValues(sessionStartRow, sessionCol, nids, 1));
	}

	// Get hidden session values
	var hiddenSessionCol = sessionColIndex['session_hidden'];
	var hiddenVals = sessionSheet.getSheetValues(sessionStartRow, hiddenSessionCol, nids, 1);
	var qRows = [];
	var randomSeeds = []

	for (var j=0; j<nids; j++) {
	    var rowValues = sessionSheet.getSheetValues(j+sessionStartRow, 1, 1, sessionColHeaders.length)[0];
	    var savedSession = unpackSession(sessionColHeaders, rowValues);
	    var qAttempted = savedSession.questionsAttempted;
	    var qShuffle = savedSession.questionShuffle;
	    randomSeeds.push([savedSession.randomSeed]);

	    var rowVals = [];

	    for (var k=0; k<questions.length; k++) {
		var qno = k+1;
		var correctAns = answers[k];
		if (qno in qShuffle && correctAns) {
		    var m = qShuffle[qno].indexOf(correctAns.toUpperCase())
		    if (m > 0)
			correctAns = String.fromCharCode('A'.charCodeAt(0)+m-1);
		    else
			correctAns = 'X';
		} else if (qAttempted.expect) {
		    correctAns = qAttempted.expect;
		} else if (qAttempted.pluginResp && 'correctAnswer' in qAttempted.pluginResp) {
		    correctAns = qAttempted.pluginResp.correctAnswer;
		}
		rowVals.push(correctAns)
	    }
	    qRows.push(rowVals);

	}
	correctSheet.getRange(correctStartRow, baseCols+1, nids, questions.length).setValues(qRows);
	correctSheet.getRange(correctStartRow, corrColIndex['randomSeed'], nids, 1).setValues(randomSeeds);
    } finally {
    }
    return correctSheetName;
}

function updateStats(sessionName, create) {
    try {
	loadSettings();
	var sessionSheet = getSheetCache(sessionName);
	if (!sessionSheet)
	    throw('Sheet not found '+sessionName);
	if (!sessionSheet.getLastColumn())
	    throw('No columns in sheet '+sessionName);

	var statSheetName = sessionName+'-stats';
	var statSheet = getSheet(statSheetName);
	if (!statSheet && !create)
	    return '';

	var sessionColIndex = indexColumns(sessionSheet);
	var sessionColHeaders = sessionSheet.getSheetValues(1, 1, 1, sessionSheet.getLastColumn())[0];

	// Session sheet columns
	var sessionStartRow = SESSION_START_ROW;
	var nids = sessionSheet.getLastRow()-sessionStartRow+1;

	var sessionEntries = lookupValues(sessionName, ['attributes', 'questions', 'questionConcepts', 'primary_qconcepts', 'secondary_qconcepts'], INDEX_SHEET);
	var sessionAttributes = JSON.parse(sessionEntries.attributes);
	var questions = JSON.parse(sessionEntries.questions);
	var questionConcepts = JSON.parse(sessionEntries.questionConcepts);
	var p_concepts = sessionEntries.primary_qconcepts ? sessionEntries.primary_qconcepts.split('; ') : [];
	var s_concepts = sessionEntries.secondary_qconcepts ? sessionEntries.secondary_qconcepts.split('; ') : [];
	var allQuestionConcepts = [p_concepts, s_concepts];
	 
	// Session stats headers
	var sessionCopyCols = ['name', 'id', 'Timestamp', 'lateToken', 'lastSlide'];
	var statExtraCols = ['weightedCorrect', 'correct', 'count', 'skipped']

	var statHeaders = sessionCopyCols.concat(statExtraCols);
	for (var j=0; j<p_concepts.length; j++)
	    statHeaders.push('p:'+p_concepts[j]);
	for (var j=0; j<s_concepts.length; j++)
	    statHeaders.push('s:'+s_concepts[j]);
	var nconcepts = p_concepts.length + s_concepts.length;

	// Stats sheet columns
	var statAvgRow = 2;
	var statStartRow = 3; // Leave blank row for formulas
	var statQuestionCol = sessionCopyCols.length+1;
	var nqstats = statExtraCols.length;
	var statConceptsCol = statQuestionCol + nqstats;

	var avgStartRow = statStartRow + getNormalUserRow(sessionSheet, sessionStartRow) - sessionStartRow;

	// New stat sheet
	statSheet = createSheet(statSheetName, statHeaders, true);
	statSheet.getRange(1, 1, 1, statHeaders.length).setWrap(true);

	statSheet.getRange(statAvgRow, sessionCopyCols.length+1, 1, statHeaders.length-sessionCopyCols.length).setNumberFormat('0.###');

	var statColIndex = indexColumns(statSheet);
	statSheet.getRange(statAvgRow, statColIndex['id'], 1, 1).setValues([[AVERAGE_ID]]);
	statSheet.getRange(statAvgRow, statColIndex['Timestamp'], 1, 1).setValues([[new Date()]]);
	statSheet.getRange(str(statAvgRow)+':'+str(statAvgRow)).setFontStyle('italic');

	for (var j=0; j<sessionCopyCols.length; j++) {
	    var colHeader = sessionCopyCols[j];
	    var sessionCol = sessionColIndex[colHeader];
	    var statCol = statColIndex[colHeader];
	    statSheet.getRange(statStartRow, statCol, nids, 1).setValues(sessionSheet.getSheetValues(sessionStartRow, sessionCol, nids, 1));
	}

	var hiddenSessionCol = sessionColIndex['session_hidden'];
	var hiddenVals = sessionSheet.getSheetValues(sessionStartRow, hiddenSessionCol, nids, 1);
	var questionTallies = [];
	var conceptTallies = [];
	var nullConcepts = [];
	for (var j=0; j<nconcepts; j++)
	    nullConcepts.push('');

	for (var j=0; j<nids; j++) {
	    var rowValues = sessionSheet.getSheetValues(j+sessionStartRow, 1, 1, sessionColHeaders.length)[0];
	    var savedSession = unpackSession(sessionColHeaders, rowValues);
	    var scores = tallyScores(questions, savedSession.questionsAttempted, savedSession.hintsUsed, sessionAttributes.params, sessionAttributes.remoteAnswers);

	    questionTallies.push([scores.weightedCorrect, scores.questionsCorrect, scores.questionsCount, scores.questionsSkipped]);

	    var qscores = scores.qscores;
	    var missedConcepts = trackConcepts(scores.qscores, questionConcepts, allQuestionConcepts);
	    if (missedConcepts[0].length || missedConcepts[1].length) {
		var missedFraction = [];
		for (var m=0; m<missedConcepts.length; m++)
		    for (var k=0; k<missedConcepts[m].length; k++)
			missedFraction.push(missedConcepts[m][k][0]/(1.0*Math.max(1,missedConcepts[m][k][1])));
		conceptTallies.push(missedFraction);
	    } else {
		conceptTallies.push(nullConcepts);
	    }
	}
	statSheet.getRange(statStartRow, statQuestionCol, nids, nqstats).setValues(questionTallies);
	if (nconcepts)
	    statSheet.getRange(statStartRow, statConceptsCol, nids, nconcepts).setValues(conceptTallies);

	for (var avgCol=sessionCopyCols.length+1; avgCol<=statHeaders.length; avgCol++) {
	    updateColumnAvg(statSheet, avgCol, statAvgRow, avgStartRow);
	}
    } finally {
    }

    return statSheetName;
}


function trackConcepts(qscores, questionConcepts, allQuestionConcepts) {
    // Track missed concepts:  missedConcepts = [ [ [missed,total], [missed,total], ...], [...] ]
    var missedConcepts = [ [], [] ];
    if (allQuestionConcepts.length != 2)
	return missedConcepts;

    for (var m=0; m<2; m++) {
	for (var k=0; k<allQuestionConcepts[m].length; k++) {
	    missedConcepts[m].push([0,0]);
	}
    }

    for (var qnumber=1; qnumber<=qscores.length; qnumber++) {
	var qConcepts = questionConcepts[qnumber-1];
	if (qscores[qnumber-1] === null || !qConcepts.length || (!qConcepts[0].length && !qConcepts[1].length))
	    continue;
	var missed = qscores[qnumber-1] < 1;

	for (var m=0; m<2; m++) {
            // Primary/secondary concept
	    for (var j=0; j<qConcepts[m].length; j++) {
		for (var k=0; k < allQuestionConcepts[m].length; k++) {
		    if (qConcepts[m][j] == allQuestionConcepts[m][k]) {
			if (missed)
			    missedConcepts[m][k][0] += 1;    // Missed count
			missedConcepts[m][k][1] += 1;        // Attempted count
		    }
		}
	    }
	}
    }
    return missedConcepts;
}

function gradesFormula(columnHeaders, startCol, lastRow) {
    // Return total grades formula (with @ for row number) || null string
    // If lastRow, return array formula for range 2:lastRow
    if (columnHeaders.indexOf('q_total') < 0)
        return '';

    var totalCells = [];
    for (var j=startCol-1; j < columnHeaders.length; j++) {
	var columnHeader = columnHeaders[j];
        var hmatch = QFIELD_RE.exec(columnHeader);
	if (columnHeader == 'q_scores' || columnHeader == 'q_other' || (hmatch && hmatch[2] == 'grade')) {
            // Grade value to summed
	    if (lastRow)
		totalCells.push(colIndexToChar(j+1) + '2:' + colIndexToChar(j+1) + lastRow);
	    else
		totalCells.push(colIndexToChar(j+1) + '@');
        }
    }
    if (!totalCells.length)
	return '';
    // Computed admin column to hold sum of all grades
    if (lastRow)
	return '=arrayformula('+totalCells.join('+')+')';
    else
	return '=' + totalCells.join('+');
}

function updateTotalFormula(modSheet, nRows) {
    if (TOTAL_COLUMN)  // Totals handled by proxy
	return;
    var columnHeaders = modSheet.getSheetValues(1, 1, 1, modSheet.getLastColumn())[0];
    var columnIndex = indexColumns(modSheet);
    var totalCol = columnIndex['q_total'];
    if (!totalCol || nRows < 2)
	return;
    var totalGradesFormula = gradesFormula(columnHeaders, totalCol+1, nRows);
    var maxTotalRange = modSheet.getRange(2, totalCol, 1, 1);
    var oldVal = maxTotalRange.getFormula();
    if (oldVal != totalGradesFormula)
	maxTotalRange.setValue(totalGradesFormula);
}

function updateTotalScores(modSheet, sessionAttributes, questions, force, startRow, nRows) {
    // If not force, only update non-blank entries
    // Return number of rows updated
    if (!questions) {
        return 0;
    }
    var columnHeaders = modSheet.getSheetValues(1, 1, 1, modSheet.getLastColumn())[0];
    var columnIndex = indexColumns(modSheet);
    var nUpdates = 0;
    var startRow = startRow || 2;
    var nRows = nRows || modSheet.getLastRow()-startRow+1;;
    if (nRows > 0) {
        // Update total scores
        var idVals = modSheet.getSheetValues(startRow, columnIndex['id'], nRows, 1);
        var scoreValues = modSheet.getSheetValues(startRow, columnIndex['q_scores'], nRows, 1);
        for (var k=0; k < nRows; k++) {
            if (idVals[k][0] != MAXSCORE_ID && (force || scoreValues[k][0] != '')) {
		var temRowVals = modSheet.getSheetValues(startRow+k, 1, 1, columnHeaders.length)[0];
		var savedSession = unpackSession(columnHeaders, temRowVals);
		var newScore = '';
		if (savedSession && Object.keys(savedSession.questionsAttempted).length) {
		    var scores = tallyScores(questions, savedSession['questionsAttempted'], savedSession['hintsUsed'], sessionAttributes['params'], sessionAttributes['remoteAnswers']);
		    newScore = scores.weightedCorrect || '';
		}
		if (scoreValues[k][0] != newScore) {
                    modSheet.getRange(startRow+k, columnIndex['q_scores'], 1, 1).setValues([[newScore]]);
		    nUpdates += 1;
		}
	    }
	}
    }
    return nUpdates;
}


function clearQuestionResponses(sessionName, questionNumber, userId) {
    var sessionSheet = getSheet(sessionName);
    if (!sessionSheet) {
        throw('Session '+sessionName+' not found');
    }

    var columnHeaders = sessionSheet.getSheetValues(1, 1, 1, sessionSheet.getLastColumn())[0];
    var columnIndex = indexColumns(sessionSheet);

    if (userId) {
        var idRowIndex = indexRows(sessionSheet, columnIndex['id']);
        var startRow = idRowIndex[userId];
        if (!startRow) {
            throw('User id '+userId+' not found in session '+sessionName);
        }
        var nRows = 1;
    } else {
        startRow = 3;
        var nRows = sessionSheet.getLastRow()-startRow+1;
    }

    var submitTimestampCol = columnIndex.submitTimestamp;
    var submits = sessionSheet.getSheetValues(startRow, submitTimestampCol, nRows, 1);
    for (var j=0; j<submits.length; j++) {
        if (submits[j][0]) {
            throw('Cannot clear question response for submitted sessions');
        }
    }

    var blanks = [];
    for (var k=0; k<nRows; k++) {
        blanks.push(['']);
    }

    var qprefix = 'q'+(questionNumber);
    var clearedResponse = false;
    for (var j=0; j<columnHeaders.length; j++) {
        var header = columnHeaders[j];
        if (header.split('_')[0] == qprefix) {
            clearedResponse = true;
            sessionSheet.getRange(startRow, j+1, nRows, 1).setValues(blanks);
        }
    }

    if (!clearedResponse) {
        var sessionCol = columnIndex.session_hidden;
        for (var k=0; k<nRows; k++) {
            var sessionRange = sessionSheet.getRange(k+startRow, sessionCol, 1, 1);
            var session_hidden = sessionRange.getValue();
            if (!session_hidden) {
                continue;
            }
            var session = loadSession(session_hidden);
            if ('questionsAttempted' in session && questionNumber in session['questionsAttempted']) {
		clearedResponse = true;
                delete session['questionsAttempted'][questionNumber];
                sessionRange.setValue(orderedStringify(session));
            }
        }
    }

    if (clearedResponse) {
	// Update total score and answer stats
	var sessionEntries = lookupValues(sessionName, ['questions', 'attributes'], INDEX_SHEET);
	var sessionAttributes = JSON.parse(sessionEntries['attributes']);
	var questions = JSON.parse(sessionEntries['questions']);
	updateTotalScores(sessionSheet, sessionAttributes, questions, true, startRow, nRows);
	return true;
    } else {
	return false;
    }
}


function createQuestionAttempted(response) {
    return {'response': response || ''};
}

function loadSession(session_json) {
    return JSON.parse(session_json);
}

function unpackSession(headers, row) {
    // Unpacks hidden session object and adds response/explain fields from sheet row, as needed
    var session_hidden = row[headers.indexOf('session_hidden')];
    if (!session_hidden)
	return null;
    if (session_hidden.charAt(0) != '{')
	session_hidden = Utilities.newBlob(Utilities.base64Decode(session_hidden)).getDataAsString();
    var session = loadSession(session_hidden);

    for (var j=0; j<headers.length; j++) {
	var header = headers[j];
	if (header == 'name')
	    session.displayName = row[j];
	if (COPY_HEADERS.indexOf(header) >= 0)
	    session[header] = (header == 'lastSlide') ? (row[j] || 0) : (row[j] || '');
	else if (row[j]) {
	    var hmatch = QFIELD_RE.exec(header);
	    if (hmatch && (hmatch[2] == 'response' || hmatch[2] == 'explain' || hmatch[2] == 'plugin')) {
		// Copy only response/explain/plugin field to session
		var qnumber = parseInt(hmatch[1]);
		if (hmatch[2] == 'response') {
		    if (!row[j]) {
			// Null row entry deletes attempt
			if (qnumber in session.questionsAttempted)
			    delete session.questionsAttempted[qnumber];
		    } else {
			if (!(qnumber in session.questionsAttempted))
			    session.questionsAttempted[qnumber] = createQuestionAttempted();
			// SKIP_ANSWER implies null answer attempt
			session.questionsAttempted[qnumber][hmatch[2]] = (row[j] == SKIP_ANSWER) ? '' : row[j];
		    }
		} else if (qnumber in session.questionsAttempted) {
		    // Explanation/plugin (ignored if no attempt)
		    if (hmatch[2] == 'plugin') {
			if (row[j])
			    session.questionsAttempted[qnumber][hmatch[2]] = JSON.parse(row[j]);
		    } else {
			session.questionsAttempted[qnumber][hmatch[2]] = row[j];
		    }
		}
	    }
	}
    }
    return session;
}

function splitNumericAnswer(corrAnswer) {
    // Return [answer|null, error|null]
    if (!corrAnswer)
	return [null, 0.0];
    var comps = corrAnswer.split('+/-');
    var corrValue = parseNumber(comps[0]);
    var corrError = 0.0;
    if (corrValue != null && comps.length > 1) {
	comps[1] = comps[1].trim();
	if (comps[1].slice(-1) == '%') {
	    corrError = parseNumber(comps[1].slice(0,-1));
	    if (corrError && corrError > 0)
		corrError = (corrError/100.0)*corrValue;
	} else {
	    corrError = parseNumber(comps[1]);
	}
    }
    if (corrError)
	corrError = Math.abs(corrError);
    return [corrValue, corrError];
}


function scoreAnswer(response, qtype, corrAnswer) {
    // Handle answer types: choice, number, text

    if (!corrAnswer)
        return null;

    if (!response)
	return 0;

    var respValue = null;

    // Check response against correct answer
    var qscore = 0;
    if (qtype == 'number') {
        // Check if numeric answer is correct
	respValue = parseNumber(response);
	var corrComps = splitNumericAnswer(corrAnswer);

        if (respValue != null && corrComps[0] != null && corrComps[1] != null) {
            qscore = (Math.abs(respValue-corrComps[0]) <= 1.001*corrComps[1]) ? 1 : 0;
        } else if (corrComps[0] == null) {
            qscore = null;
	    if (corrAnswer)
		throw('scoreAnswer: Error in correct numeric answer:'+corrAnswer);
        } else if (corrComps[1] == null) {
            qscore = null;
            throw('scoreAnswer: Error in correct numeric error:'+corrAnswer);
        }
    } else {
        // Check if non-numeric answer is correct (all spaces are removed before comparison)
	response = '' + str(response);
        var normResp = response.trim().toLowerCase();
	// For choice, allow multiple correct answers (to fix grading problems)
        var correctOptions = (qtype == 'choice') ? corrAnswer.split('') : corrAnswer.split(' OR ');
        for (var j=0; j<correctOptions.length; j++) {
            var normCorr = correctOptions[j].trim().toLowerCase().replace(/\s+/g,' ');
            if (normCorr.indexOf(' ') > 0) {
                // Correct answer has space(s); compare using normalized spaces
                qscore = (normResp.replace(/\s+/g,' ') == normCorr) ? 1 : 0;
            } else {
                // Strip all spaces from response
                qscore = (normResp.replace(/\s+/g,'') == normCorr) ? 1 : 0;
            }
            if (qscore) {
                break;
            }
        }
    }

    return qscore;
}

function tallyScores(questions, questionsAttempted, hintsUsed, params, remoteAnswers) {
    var skipAhead = 'skip_ahead' in params.features;

    var questionsCount = 0;
    var weightedCount = 0;
    var questionsCorrect = 0;
    var weightedCorrect = 0;
    var questionsSkipped = 0;

    var correctSequence = 0;
    var lastSkipRef = '';

    var skipToSlide = 0;
    var prevQuestionSlide = -1;

    var qscores = [];
    for (var j=0; j<questions.length; j++) {
        var qnumber = j+1;
        var qAttempted = questionsAttempted[qnumber];
        if (!qAttempted && params.paceLevel >= QUESTION_PACE) {
            // Process answers only in sequence
            break;
        }

        var questionAttrs = questions[j];
        var slideNum = questionAttrs.slide;
        if (!qAttempted || slideNum < skipToSlide) {
            // Unattempted or skipped
            qscores.push(null);
            continue;
        }

	if (qAttempted.plugin) {
	    var qscore = parseNumber(qAttempted.plugin.score);
	} else {
	    var correctAns = qAttempted.expect || questionAttrs.correct || '';
            if (!correctAns && remoteAnswers && remoteAnswers.length)
		correctAns = remoteAnswers[qnumber-1];

            var qscore = scoreAnswer(qAttempted.response, questionAttrs.qtype, correctAns);
	}

        qscores.push(qscore);
        var qSkipCount = 0;
        var qSkipWeight = 0;

        // Check for skipped questions
        if (skipAhead && qscore == 1 && !hintsUsed[qnumber] && !qAttempted.retries) {
            // Correct answer (without hints and retries)
            if (slideNum > prevQuestionSlide+1) {
                // Question  not part of sequence
                correctSequence = 1;
            } else if (correctSequence > 0) {
                // Question part of correct sequence
                correctSequence += 1;
            }
        } else {
            // Wrong/partially correct answer or no skipAhead
            correctSequence = 0;
        }

        prevQuestionSlide = slideNum;

        lastSkipRef = '';
        if (correctSequence && params.paceLevel == QUESTION_PACE) {
            var skip = questionAttrs.skip;
            if (skip && skip[0] > slideNum) {
                // Skip ahead
                skipToSlide = skip[0];

                // Give credit for all skipped questions
                qSkipCount = skip[1];
                qSkipWeight = skip[2];
                lastSkipRef = skip[3];
	    }
        }

        // Keep score for this question
        var qWeight = questionAttrs.weight || 0;
        questionsSkipped += qSkipCount;
        questionsCount += 1 + qSkipCount;
        weightedCount += qWeight + qSkipWeight;

        var effectiveScore = (parseNumber(qscore) != null) ? qscore : 1;   // Give full credit to unscored answers

        if (params.participationCredit) {
            // Full participation credit simply for attempting question (lateCredit applied in sheet)
            effectiveScore = 1;

        } else if (hintsUsed[qnumber] && questionAttrs.hints && questionAttrs.hints.length) {
	    if (hintsUsed[qnumber] > questionAttrs.hints.length)
		throw('Internal Error: Inconsistent hint count');
	    for (var j=0; j<hintsUsed[qnumber]; j++)
		effectiveScore -= Math.abs(questionAttrs.hints[j]);
	}

        if (effectiveScore > 0) {
            questionsCorrect += 1 + qSkipCount;
            weightedCorrect += effectiveScore*qWeight + qSkipWeight;
        }
    }

    return { 'questionsCount': questionsCount, 'weightedCount': weightedCount,
             'questionsCorrect': questionsCorrect, 'weightedCorrect': weightedCorrect,
             'questionsSkipped': questionsSkipped, 'correctSequence': correctSequence, 'skipToSlide': skipToSlide,
             'correctSequence': correctSequence, 'lastSkipRef': lastSkipRef, 'qscores': qscores};
}

function emailTokens() {
    // Send authentication tokens
    var doc = getDoc();
    loadSettings();
    var rosterSheet = getSheet(ROSTER_SHEET);
    if (!rosterSheet)
	throw('Roster sheet '+ROSTER_SHEET+' not found!');
    var userId = getPrompt('Email authentication tokens', "userID, or 'all'");
    if (!userId)
	return;
    var emailList;
    if (userId != 'all') {
	emailList = [ [userId, lookupValues(userId,['email'],ROSTER_SHEET,true)[0] ] ];
    } else {
	emailList = getColumns('id', rosterSheet, 2);
    }
    for (var j=0; j<emailList.length; j++)
	if (emailList[j][1].trim() && emailList[j][1].indexOf('@') <= 0)
	    throw("Invalid email address '"+emailList[j][1]+"' for userID '"+emailList[j][0]+"'");

    var subject;
    if (Settings['site_name'])
	subject = 'Authentication token for '+Settings['site_name'];
    else
	subject = 'Slidoc authentication token';

    var emails = [];
    for (var j=0; j<emailList.length; j++) {
	if (!emailList[j][1].trim())
	    continue;
	var username = emailList[j][0];
	var token = genAuthToken(Settings['auth_key'], emailList[j][0]);

	var message = 'Authentication token for userID '+username+' is '+token;
	if (Settings['server_url'])
	    message += "\n\nAuthenticated link to website: "+Settings['server_url']+"/_auth/login/?username="+encodeURIComponent(username)+"&token="+encodeURIComponent(token);
	message += "\n\nRetain this email for future use, or save userID and token in a secure location. Do not share token with anyone else.";

	MailApp.sendEmail(emailList[j][1], subject, message);
	emails.push(emailList[j][1]);
    }

    notify('Emailed '+emails.length+' token(s) to '+emails.join(', '));
}


function emailLateToken() {
    // Send late token to user
    createLateToken();
}

function insertLateToken() {
    // Insert late token in session
    createLateToken(true);
}

function createLateToken(insert) {
    var doc = getDoc();
    loadSettings();
    var sessionName = getSessionName();
    if (sessionName) {
	var userId = getPrompt('Email late submission token for session '+sessionName, "userID");
	if (!userId)
	    return;
    } else {
	var text = getPrompt('Email late submission token', "userID, session");
	if (!text)
	    return;
	var comps = text.trim().split(/\s*,\s*/);
	var userId = comps[0];
	sessionName = comps[1];
    }
    var sessionSheet = getSheet(sessionName);
    if (!sessionSheet)
	throw('Session '+sessionName+' not found!');

    var displayName = '';
    var email = '';
    var rosterSheet = getSheet(ROSTER_SHEET);
    if (rosterSheet) {
	displayName = lookupValues(userId, ['name'], ROSTER_SHEET, true)[0];
	email = lookupValues(userId, ['email'], ROSTER_SHEET, true)[0];
    }

    if (!displayName)
	displayName = getPrompt('Enter name (Last, First) user '+userId, 'Name');

    var dateStr = getPrompt('New submission date/time', "'yyyy-mm-ddTmm:hh' (or 'yyyy-mm-dd', implying 'T23:59')");
    if (!dateStr)
	return;
    if (dateStr.indexOf('T') < 0)
	dateStr += 'T23:59';

    var token = genLateToken(Settings['auth_key'], userId, Settings['site_name'], sessionName, dateStr);

    var subject = 'Late submission for '+sessionName;
    var message;
    if (insert) {
	var numStickyRows = 1;
	var userRow = lookupRowIndex(userId, sessionSheet, numStickyRows+1);
	if (userRow) {
	    sessionSheet.getRange(userRow, indexColumns(sessionSheet)['lateToken'], 1, 1).setValue(token);
	} else {
	    var retval = getUserRow(sessionName, userId, displayName, {'create': '1', 'late': token});
	    if (retval.result != 'success')
		throw('Error in creating session for user '+userId+': '+retval.error);
	    userRow = lookupRowIndex(userId, sessionSheet, numStickyRows+1);
	}

	if (Settings['site_name'])
	    subject = 'Late submission allowed for '+Settings['site_name'];
	message = 'Late submission allowed for userID '+userId+' in session '+sessionName+'. New due date is  '+dateStr;
    } else {
	if (Settings['site_name'])
	    subject = 'Late submission token for '+Settings['site_name'];
	message = 'Late submission token for userID '+userId+' and session '+sessionName+' is '+token;
    }

    var	note = 'Late submission on '+dateStr+' authorized for user '+userId+'.';
    if (email && email.indexOf('@') > 0) {
	MailApp.sendEmail(email, subject, message);
	note += ' Emailed notification to '+email;
    } else if (insert) {
	throw("Invalid email address '"+email+"' for userID '"+userId+"'");
    }
    notify(note);
}


function updateTotalSession() {
    // Update scores sheet for current session
    return updateSession(updateTotalAux);
}

function updateTotalAux(sheetName, create) {
    if (sheetName == 'all')
	var sessionNames = getSessionNames();
    else
	sessionNames = [sheetName];
    for (var j=0; j<sessionNames.length; j++) {
	var sessionName = sessionNames[j];
	var sessionEntries = lookupValues(sessionName, ['dueDate', 'gradeDate', 'paceLevel', 'adminPaced', 'otherWeight', 'fieldsMin', 'questions', 'attributes'], INDEX_SHEET);
	var sessionAttributes = JSON.parse(sessionEntries.attributes)
	var questions = JSON.parse(sessionEntries.questions);
	var sessionSheet = getSheet(sessionName);
	updateTotalScores(sessionSheet, sessionAttributes, questions, true);
	updateTotalFormula(sessionSheet, sessionSheet.getLastRow());
    }
    notify('Updated totals for sessions: '+sessionNames.join(', '), 'Slidoc Totals');
}

function actionHandler(actions, sheetName, create) {
    var sessions = sheetName ? [sheetName] : getSessionNames();
    var actionList = actions.split(',');
    var refreshSheets = []
    for (var k=0; k<actionList.length; k++) {
	var action = actionList[k];
	trackCall(2, 'actionHandler: '+action);
	if (action == 'answer_stats') {
	    for (var j=0; j<sessions.length; j++) {
		updateAnswers(sessions[j], create);
		updateStats(sessions[j], create);
		refreshSheets.push(sessions[j]+'-answers');
		refreshSheets.push(sessions[j]+'-stats');
	    }
	} else if (action == 'correct') {
	    for (var j=0; j<sessions.length; j++) {
		updateCorrect(sessions[j], create);
		refreshSheets.push(sessions[j]+'-correct');
	    }
	} else if (action == 'gradebook') {
	    var retval = updateScores(sessions, create);
	    if (!retval.length && sessions.length)
		throw('Error:ACTION:Failed to update gradebook for session(s) '+sessions);
	    refreshSheets.push(SCORES_SHEET);
	} else {
	    throw('Error:ACTION:Invalid action '+action+' for session(s) '+sessions);
	}
    }
    return refreshSheets;
}


function updateSession(actionFunc) {
    // Update action for current session

    var sessionName = getSessionName(true);

    var lock = LockService.getPublicLock();
    lock.waitLock(30000);  // wait 30 seconds before conceding defeat.

    try {
	loadSettings();
	if (sessionName != 'all') {
	    var sessionSheet = getSheet(sessionName);
	    if (!sessionSheet)
		throw('Sheet not found: '+sessionName);
	    if (!sessionSheet.getLastColumn())
		throw('No columns in sheet: '+sessionName);
	    if (sessionSheet.getLastRow() < 2)
		throw('No data rows in sheet: '+sessionName);
	}
	return actionFunc(sessionName, true);
    } finally { //release lock
	lock.releaseLock();
    }

}

function sessionAnswerSheet() {
    // Create session answers sheet
    var sheetName = updateSession(updateAnswers);
    notify('Created sheet :'+sheetName, 'Slidoc Answers');
}

function sessionCorrectSheet() {
    // Create session correct sheet
    var sheetName = updateSession(updateCorrect);
    notify('Created sheet :'+sheetName, 'Slidoc Correct');
}

function sessionStatSheet() {
    // Create session stats sheet
    var sheetName = updateSession(updateStats);
    notify('Created sheet :'+sheetName, 'Slidoc Stats');
}

function updateScoreSession() {
    // Update scores sheet for current session
    ///startCallTracking(2, {}, 'SCORES');
    retval = updateSession(updateScoreAux);
    ///trackCall(0, 'success');
    return retval;
}

function updateScoreAux(sessionName, create) {
    var updatedNames = updateScores([sessionName], create||false, true);
    if (updatedNames && updatedNames.length)
	notify('Updated scores for session '+sessionName, 'Slidoc Scores');
    else
	notify('Failed to update scores for session '+sessionName+'. Ensure that grades are released and session weight is not zero', 'Slidoc Scores');
    return updatedNames;
}

function updateScoreAll() {
    // Update scores sheet for all sessions alread-posted

    var lock = LockService.getPublicLock();
    lock.waitLock(30000);  // wait 30 seconds before conceding defeat.

    try {
	loadSettings();
	var updatedNames = updateScores(getSessionNames(), false, true);
	notify("Updated scores for sessions: "+updatedNames.join(', '), 'Slidoc Scores');
    } catch(err) {
	SpreadsheetApp.getUi().alert(''+err);
    } finally { //release lock
	lock.releaseLock();
    }

}

var AGGREGATE_COL_RE = /\b(_\w+)_(avg|normavg|sum)(_(\d+))?$/i;

function updateScores(sessionNames, create, interactive) {
    // Update scores sheet for sessions in list
    // Returns list of updated sessions

    try {
	var scoreSheet = getSheet(SCORES_SHEET);

	if (!create) {
	    // Refresh only already posted sessions
	    if (!scoreSheet)
		return [];
	    var temColIndex = indexColumns(scoreSheet);
	    var curSessions = [];
	    for (var j=0; j<sessionNames.length; j++) {
		if (temColIndex['_'+sessionNames[j]])
		    curSessions.push(sessionNames[j]);
	    }
	    if (!curSessions.length)
		return [];
	    sessionNames = curSessions;
	}

	var totalFormula = Settings['total_formula'] || '';
	var gradingScale = Settings['grading_scale'] || '';
	var aggregateColumns = [];
	var aggregateParams = {};
	var totalFormulaStr = '';
	if (totalFormula) {
	    totalFormulaStr = totalFormula.replace(/\b(_\w+)_(avg|normavg|sum)_(\d+)\b/gi,'$1').replace(/(\b_)/g,'');
	    var comps = totalFormula.split('+');
	    for (var j=0; j<comps.length; j++) {
		/// Example: 0.4*_Assignment_avg_1+0.5*_Quiz_sum+0.1*_Extra01
		var cmatch = AGGREGATE_COL_RE.exec(comps[j].trim());
		if (cmatch) {
		    var agName = cmatch[0];
		    var agPrefix = cmatch[1];
		    var agType = cmatch[2];
		    aggregateParams[agName] = {prefix:agPrefix, type:agType, drop:parseNumber(cmatch[4]) || 0};
		    aggregateColumns.push(agName);
		}
	    }
	}
	var gradeCutoffs = [];
	var gradePercent = false;
	if (gradingScale) {
	    var comps = gradingScale.split(',');
	    for (var j=0; j<comps.length; j++) {
		var gComps = comps[j].trim().split(':');
		if (gComps.length < 3)
		    throw('Invalid grading scale (expect A:90:4, ...): '+gradingScale);
		var letter = gComps[0].trim().toUpperCase();
		var cutoffStr = gComps[1].trim();
		var numValueStr = gComps[2].trim();
		if (cutoffStr.slice(-1) == '%') {
		    cutoffStr = cutoffStr.slice(0,-1).trim();
		    gradePercent = true;
		}
		if (!letter || !isNumber(cutoffStr) || !isNumber(numValueStr))
		    throw('Invalid grading scale (expect A:90:4, ...): '+gradingScale);

		gradeCutoffs.push([parseNumber(cutoffStr), letter, parseNumber(numValueStr)]);
	    }
	    gradeCutoffs.sort(numSort);  //  (sorting numerically)
	    gradeCutoffs.reverse();
	}
	var indexSheet = getSheet(INDEX_SHEET);
	if (!indexSheet) {
	    SpreadsheetApp.getUi().alert('Sheet not found: '+INDEX_SHEET);
	}
	var validNames = [];
	var validSheet = null;
	for (var m=0; m<sessionNames.length; m++) {
	    // Ensure all sessions exist
	    var sessionName = sessionNames[m];
	    var sessionSheet = getSheet(sessionName);
	    if (!sessionSheet) {
		SpreadsheetApp.getUi().alert('Sheet not found: '+sessionName);
	    } else if (!sessionSheet.getLastColumn()) {
		SpreadsheetApp.getUi().alert('No columns in sheet '+sessionName);
	    } else if (sessionSheet.getLastRow() < 2) {
		SpreadsheetApp.getUi().alert('No data rows in sheet '+sessionName);
	    } else {
		validNames.push(sessionName);
		validSheet = sessionSheet;
	    }
	}

	if (!validSheet)
	    throw('No valid session sheet');
	if (!SESSION_MAXSCORE_ROW)
	    throw('Must set SESSION_MAXSCORE_ROW to create/refresh sheet'+SCORES_SHEET)

	var rosterStartRow = ROSTER_START_ROW;
	var sessionStartRow = SESSION_START_ROW;
	var rescaleRow   = 2;
	var timestampRow = 3;
	var scoreAvgRow  = 4;
	var maxWeightOrigRow = 5;
	var maxWeightRow = 6;
	var userStartRow = 7;
	var numFormatRow = timestampRow + 1;
	var scoreStartRow = maxWeightRow;
	var avgStartRow = userStartRow;

	// Copy user info from roster
	var userInfoSheet = getSheetCache(ROSTER_SHEET);
	var infoStartRow = rosterStartRow;
	if (!userInfoSheet)  {              // Copy user info from last valid session
	    userInfoSheet = validSheet;
	    infoStartRow = sessionStartRow;
	}
	var nUserIds = userInfoSheet.getLastRow()-infoStartRow+1;
	var idCol = MIN_HEADERS.indexOf('id')+1;

	// New score sheet
	var extraHeaders = ['total', 'grade', 'numGrade'];
	var scoreHeaders = MIN_HEADERS.concat(extraHeaders);
	if (!scoreSheet) {
	    // Create session score sheet
	    var temHeaders = userInfoSheet.getSheetValues(1, 1, 1, MIN_HEADERS.length)[0].concat(extraHeaders);
	    scoreSheet = createSheet(SCORES_SHEET, temHeaders);

	    // Score sheet headers
	    scoreSheet.getRange(rescaleRow, idCol, 1, 1).setValues([[RESCALE_ID]]);
	    scoreSheet.getRange(timestampRow, idCol, 1, 1).setValues([[TIMESTAMP_ID]]);
	    scoreSheet.getRange(scoreAvgRow, idCol, 1, 1).setValues([[AVERAGE_ID]]);
	    scoreSheet.getRange(str(rescaleRow)+':'+str(scoreAvgRow)).setFontStyle('italic');

	    scoreSheet.getRange(maxWeightOrigRow, idCol, 1, 1).setValues([[MAXSCOREORIG_ID]]);
	    scoreSheet.getRange(maxWeightRow, idCol, 1, 1).setValues([[MAXSCORE_ID]]);
	    scoreSheet.getRange(maxWeightOrigRow+':'+maxWeightRow).setFontWeight('bold');

	    // Insert user info
	    if (nUserIds)
		scoreSheet.getRange(userStartRow, 1, nUserIds, MIN_HEADERS.length).setValues(userInfoSheet.getSheetValues(infoStartRow, 1, nUserIds, MIN_HEADERS.length));
	} else {
	    // Update session score sheet
	    var nPrevIds = scoreSheet.getLastRow()-userStartRow+1;
	    if (nUserIds != nPrevIds)
		throw('Number of ids in score sheet ('+nPrevIds+') does not match that in roster/session ('+nUserIds+'); re-create score sheet');
	    if (nUserIds) {
		var infoIds = userInfoSheet.getSheetValues(infoStartRow, idCol, nUserIds, 1);
		var prevIds = scoreSheet.getSheetValues(userStartRow, idCol, nUserIds, 1);
		for (var j=0; j<nUserIds; j++) {
		    // Check that prior IDs match
		    if (prevIds[j] && prevIds[j] != infoIds[j][0])
			throw('Id mismatch in row '+(userStartRow+j)+' of score sheet: expected '+infoIds[j][0]+' but found '+prevIds[j]+'; fix it or re-create score sheet');
		}

		// Update user info (other than ID)
		scoreSheet.getRange(userStartRow, 1, nUserIds, MIN_HEADERS.length).setValues(userInfoSheet.getSheetValues(infoStartRow, 1, nUserIds, MIN_HEADERS.length));
	    }
	}

	if (nUserIds) {
	    // Skip any initial row(s) in the roster with test user or IDs/names starting with underscore/hash
	    // when computing averages and other stats
	    var temIds = userInfoSheet.getSheetValues(infoStartRow, idCol, nUserIds, 1);
	    var temNames = userInfoSheet.getSheetValues(infoStartRow, MIN_HEADERS.indexOf('name')+1, nUserIds, 1);
	    for (var j=0; j<nUserIds; j++) {
		if (temIds[j][0] == TESTUSER_ID || temIds[j][0].match(/^\_/) || temNames[j][0].match(/^#/))
		    avgStartRow += 1;
		else
		    break;
	    }
	}

	var updatedNames = [];
	var curDate = new Date();
	for (var iSession=0; iSession<validNames.length; iSession++) {
	    var sessionName = validNames[iSession];
	    var sessionSheet = getSheet(sessionName);
	    var sessionColIndex = indexColumns(sessionSheet);
	    var sessionColHeaders = sessionSheet.getSheetValues(1, 1, 1, sessionSheet.getLastColumn())[0];

	    var sessionEntries = lookupValues(sessionName, ['gradeDate', 'paceLevel', 'sessionWeight', 'sessionRescale', 'scoreWeight', 'gradeWeight', 'otherWeight', 'attributes', 'questions'], INDEX_SHEET);
            var sessionAttributes = JSON.parse(sessionEntries.attributes);
	    var questions = JSON.parse(sessionEntries.questions);
	    var gradeDate = sessionEntries.gradeDate || null;
	    var paceLevel = parseNumber(sessionEntries.paceLevel) || 0;
	    var sessionWeight = isNumber(sessionEntries.sessionWeight) ? parseNumber(sessionEntries.sessionWeight) : null;
	    var sessionRescale = sessionEntries.sessionRescale || '';
	    var scoreWeight = parseNumber(sessionEntries.scoreWeight) || 0;
	    var gradeWeight = parseNumber(sessionEntries.gradeWeight) || 0;
	    var otherWeight = parseNumber(sessionEntries.otherWeight) || 0;
	    var maxWeight = scoreWeight + gradeWeight + otherWeight;
	    if (sessionAttributes.params.participationCredit && sessionAttributes.params.participationCredit > 1)
		maxWeight = 1;

	    if (!paceLevel)
		continue;

	    // Update total scores
	    updateTotalScores(sessionSheet, sessionAttributes, questions, true);

	    // Update answers/stats sheets (if already present)
	    try {
		updateAnswers(sessionName);
	    } catch(err) {
		if (interactive)
		    notify('Error in updating answers sheet for '+sessionName+': '+err, 'Slidoc Answers');
	    }

	    try {
		updateStats(sessionName);
	    } catch(err) {
		if (interactive)
		    notify('Error in updating stats sheet for '+sessionName+': '+err, 'Slidoc Stats');
	    }

	    if (sessionWeight !== null && !sessionWeight) // Skip if zero sessionWeight
		continue;
	    if (gradeWeight && !gradeDate)   // Wait for session to be graded
		continue;
	    updatedNames.push(sessionName);

	    var rescaleOps = [];
	    if (sessionRescale) {
		var comps = sessionRescale.split(',');
		for (var j=0; j<comps.length; j++) {
		    var rmatch = comps[j].trim().match(/([<+*\/^])([-0-9.eE]+)/);
		    if (!rmatch)
			throw('Invalid rescaling operation: '+comps[j]);
		    if (rmatch[1] == '^' && j > 0)
			throw('Power rescaling ^ must be first operation: '+sessionRescale);
		    rescaleOps.push([rmatch[1], rmatch[2]]);
		}
	    }
	    // Session sheet columns
	    var scoreColHeaders = scoreSheet.getSheetValues(1, 1, 1, scoreSheet.getLastColumn())[0];
	    var scoreColIndex = indexColumns(scoreSheet);
	    var sessionColName = '_'+sessionName;
	    var scoreSessionCol;
	    if (sessionColName in scoreColIndex) {
		scoreSessionCol = scoreColIndex[sessionColName];
	    } else {
		scoreSessionCol = scoreColHeaders.length+1;

		for (var jcol=1; jcol<=scoreColHeaders.length; jcol++) {
		    var colHeader = scoreColHeaders[jcol-1];
		    if (scoreHeaders.indexOf(colHeader) == -1 && colHeader.slice(0,1) == '_') {
			// Session header column
			var cmatch = AGGREGATE_COL_RE.exec(colHeader);
			var cprefix = cmatch ? cmatch[1] : colHeader;
			if (sessionName < cprefix.slice(1)) {
			    // Insert new session column in sorted order
			    scoreSheet.insertColumnBefore(jcol);
			    scoreSessionCol = jcol;
			    break;
			} else {
			    // Prepare to insert after
			    scoreSessionCol = jcol+1;
			}
		    }
		}
		scoreSheet.getRange(1, scoreSessionCol, 1, 1).setValues([[sessionColName]]);

		var c = colIndexToChar( scoreSessionCol );
		scoreSheet.getRange(c+numFormatRow+':'+c).setNumberFormat('0.##');
	    }

	    var colChar = colIndexToChar( scoreSessionCol );

	    var sessionIdCol = sessionColIndex['id'];
	    var sessionIdColChar = colIndexToChar( sessionIdCol );

	    var scoreIdCol = scoreColIndex['id'];
	    var scoreIdColChar = colIndexToChar( scoreIdCol );

	    var nids = scoreSheet.getLastRow()-scoreStartRow+1;
	    var scoreIdVals = scoreSheet.getSheetValues(scoreStartRow, scoreIdCol, nids, 1);

            //Logger.log('scoreSession: '+sessionName+' '+sessionRescale+' '+nids);
	    var lookupStartRow = sessionStartRow-1;
	    function vlookup(colName, scoreRowIndex) {
		var idCell = '$'+scoreIdColChar+scoreRowIndex;
		var nameCol = sessionColIndex[colName];
		var nameColChar = colIndexToChar( nameCol );
		var sessionRange = "'"+sessionName+"'!$"+sessionIdColChar+"$"+lookupStartRow+":$"+nameColChar;
		return 'VLOOKUP(' + idCell + ', ' + sessionRange + ', '+(nameCol-sessionIdCol+1)+', false)';
	    }
	    function rescaleScore(formula, maxCell) {
		// Rescale score
		for (var iscale=0; iscale < rescaleOps.length; iscale++) {
		    var op = rescaleOps[iscale][0];
		    var val = rescaleOps[iscale][1];
		    if (op == '^') {
			// Power rescale does not alter orig max score, but must be first op
			formula = maxCell+'*POWER(MIN(1,('+formula+')/'+maxCell+'),'+val+')';
			if (iscale)
			    throw('Power rescaling ^ must be first operation');
		    } else if (op == '*') {
			formula = '('+val+'*'+formula+')';
		    } else if (op == '+') {
			formula = '('+val+'+'+formula+')';
		    } else if (op == '/') {
			formula = '('+formula+'/'+val+')';
		    } else if (op == '<') {
			formula = 'MIN('+val+','+formula+')';
		    }
		}
		return formula;
	    }

	    var scoreFormulas = [];

	    var maxWeightOrigFormula = vlookup('q_total', maxWeightRow);
	    scoreSheet.getRange(maxWeightOrigRow, scoreSessionCol, 1, 1).setValues([['='+maxWeightOrigFormula]]);
	    if (sessionRescale && rescaleRow)
		scoreSheet.getRange(rescaleRow, scoreSessionCol, 1, 1).setValues([[sessionRescale]]);

	    scoreSheet.getRange(timestampRow, scoreSessionCol, 1, 1).setValues([[curDate]]);

	    for (var j=0; j<nids; j++) {
		var rowId = scoreIdVals[j];
		var formula = null;
		var lookupFormula = vlookup('q_total', j+scoreStartRow);
		if (sessionAttributes.params.participationCredit && sessionAttributes.params.participationCredit > 1) {
		    // Per session participation credit
		    lookupFormula = 'IF(ISERROR('+lookupFormula+'),0,1)';
		}
		
		var lateToken = vlookup('lateToken', j+scoreStartRow);
		var rescaledScore = lookupFormula;
		if (sessionRescale) {
		    var maxCell = colChar+'$'+maxWeightOrigRow;
		    rescaledScore = rescaleScore(rescaledScore, maxCell);
		}
		var adjScore = '';
		if (sessionAttributes.params.lateCredit) {
		    adjScore = 'IF('+lateToken+'="'+LATE_SUBMIT+'", '+sessionAttributes.params.lateCredit+', 1)*( '+rescaledScore+' )';
		} else {
		    adjScore = 'IF('+lateToken+'="'+LATE_SUBMIT+'", 0, '+rescaledScore+ ' )';
		}
		adjScore = 'IFERROR('+adjScore+',0)';
		if (sessionWeight)
		    adjScore = sessionWeight + '*' + adjScore;
		scoreFormulas.push(['='+adjScore]);
	    }

	    var averageFormula = sessionAttributes.params.participationCredit ? '=AVERAGE('+colChar+avgStartRow+':'+colChar+')' : '=AVERAGEIF('+colChar+avgStartRow+':'+colChar+',">0")';
	    scoreSheet.getRange(scoreAvgRow, scoreSessionCol, 1, 1).setValues([[averageFormula]]);

	    if (scoreFormulas.length)
		scoreSheet.getRange(scoreStartRow, scoreSessionCol, nids, 1).setValues(scoreFormulas);

	    setValue(sessionName, 'gradeDate', curDate, INDEX_SHEET);
	}

	var scoreColIndex = indexColumns(scoreSheet);
	var nids = scoreSheet.getLastRow()-scoreStartRow+1;
	var scoreTotalCol = scoreColIndex['total'];
	var scoreGradeCol = scoreColIndex['grade'];
	var scoreNumGradeCol = scoreColIndex['numGrade'];
	var colChar = colIndexToChar(scoreTotalCol);
	scoreSheet.getRange(colChar+'2'+':'+colChar).setNumberFormat('0.###');
	if (rescaleRow)
	    scoreSheet.getRange(rescaleRow, scoreTotalCol, 1, 1).setValues([[totalFormulaStr]]);
	scoreSheet.getRange(timestampRow, scoreTotalCol, 1, 1).setValues([[curDate]]);

	// Delete unused aggregate columns
	var scoreColHeaders = scoreSheet.getSheetValues(1, 1, 1, scoreSheet.getLastColumn())[0];
	for (var jcol=scoreColHeaders.length; jcol>=1; jcol--) {
	    var colHeader = scoreColHeaders[jcol-1];
	    if (AGGREGATE_COL_RE.exec(colHeader)) {
		if (!(colHeader in aggregateParams))
		    scoreSheet.deleteColumns(jcol, 1);
	    }
	}
	    
	var agSumFormula = 'SUM(%range)';
	var agDropFormula = '-IFERROR(SMALL(%range,%drop),0)';  // Need IFERROR in case there aren't enough numeric values to drop
	for (var j=0; j<aggregateColumns.length; j++) {
	    // Insert aggregate column
	    var scoreColHeaders = scoreSheet.getSheetValues(1, 1, 1, scoreSheet.getLastColumn())[0];
	    var agName = aggregateColumns[j];
	    var agParams = aggregateParams[agName];
	    if (scoreColHeaders.indexOf(agName) >= 0) // Column already inserted
		continue;
	    for (var jcol=1; jcol<=scoreColHeaders.length; jcol++) {
		var colHeader = scoreColHeaders[jcol-1];
		if (scoreHeaders.indexOf(colHeader) >= 0)
		    continue;
		if (agParams.prefix == colHeader)
		    throw("Invalid column name for aggregation '"+colHeader+"'; name must end in digit");
		if (agParams.prefix < colHeader)
		    break;
	    }
	    // Insert aggregate column before columns to be averaged
	    scoreSheet.insertColumnBefore(jcol);
	    var colChar = colIndexToChar( jcol );
	    scoreSheet.getRange(1, jcol, 1, 1).setValues([[agName]]);
	    scoreSheet.getRange(colChar+numFormatRow+':'+colChar).setNumberFormat('0.##');
	}
	// Re-index
	var scoreColIndex = indexColumns(scoreSheet);
	    
	var maxWeights = scoreSheet.getSheetValues(maxWeightRow, 1, 1, scoreSheet.getLastColumn())[0];
	var scoreColHeaders = scoreSheet.getSheetValues(1, 1, 1, scoreSheet.getLastColumn())[0];
	for (var j=0; j<aggregateColumns.length; j++) {
	    var agName = aggregateColumns[j];
	    var agParams = aggregateParams[agName];
	    var agCol = scoreColIndex[agName];
	    var colChar = colIndexToChar( agCol );
	    totalFormula = totalFormula.replace(agName, colChar+'@');
	    var agColMax = agCol;
	    var agMaxWeight = null;
	    var agMaxWeightMismatch = false;
	    for (var kcol=agCol+1; kcol<=scoreColHeaders.length; kcol++) {
		// Find last column to aggregate
		if (scoreColHeaders[kcol-1].slice(0,agParams.prefix.length) != agParams.prefix)
		    break;
		agColMax = kcol;
		if (agMaxWeight == null)
		    agMaxWeight = maxWeights[kcol-1];
		else if (agMaxWeight != maxWeights[kcol-1])
		    agMaxWeightMismatch = true;
	    }
	    var agFormula = '';
	    var agAverage = '';
	    var dropScores = 0;
	    if (agColMax > agCol) {
		// Aggregate columns
		dropScores = Math.min(agColMax-agCol-1, agParams.drop);
		var agRangeStr = colIndexToChar(agCol+1)+'@:'+colIndexToChar(agColMax)+'@';
		var agMaxRangeStr = colIndexToChar(agCol+1)+'$'+maxWeightRow+':'+colIndexToChar(agColMax)+'$'+maxWeightRow;
		agFormula = agSumFormula.replace(/%range/g, agRangeStr);
		for (var kdrop=0; kdrop < dropScores; kdrop++) // Drop n lowest scores
		    agFormula += agDropFormula.replace(/%range/g, agRangeStr).replace(/%drop/g, ''+(kdrop+1));
		if (agParams.type.toLowerCase() == 'avg') {
		    // Average
		    if (agMaxWeightMismatch)
			throw('All max weights should be identical to aggregate column '+agName+' in session '+sessionName);
		    if (dropScores)
			agFormula = '(' + agFormula + ')/(COLUMNS(' + agRangeStr + ')-'+dropScores+')';
		    else
			agFormula = agFormula + '/COLUMNS(' + agRangeStr + ')';
		} else if (agParams.type.toLowerCase() == 'normavg') {
		    // Normalized average
		    if (dropScores)
			throw('Cannot drop lowest values when computing normalized average for aggregate column '+agName+' in session '+sessionName);
		    agFormula = agFormula + '/'+agSumFormula.replace(/%range/g, agMaxRangeStr);
		}
	    }
	    if (agFormula) {
	        agFormula = '=' + agFormula;
		if (scoreAvgRow)
		    agAverage = '=AVERAGEIF('+colChar+avgStartRow+':'+colChar+',">0")';
	    }
	    insertColumnFormulas(scoreSheet, agFormula, agCol, scoreStartRow, scoreAvgRow);
	    if (dropScores && rescaleRow)
		scoreSheet.getRange(rescaleRow, agCol, 1, 1).setValues([['dropped '+dropScores]]);
	    scoreSheet.getRange(timestampRow, agCol, 1, 1).setValues([[curDate]]);

	}
	var scoreColHeaders = scoreSheet.getSheetValues(1, 1, 1, scoreSheet.getLastColumn())[0];
	for (var jcol=scoreColHeaders.length; jcol >= 1; jcol--) {
	    // Substitute sessionName columns in totalFormula (loop in reverse to handle specific names first)
	    var colHeader = scoreColHeaders[jcol-1];
	    if (scoreHeaders.indexOf(colHeader) >= 0 || colHeader.charAt(0) != '_')
		continue;
	    if (totalFormula.indexOf(colHeader) >= 0)
		totalFormula = totalFormula.replace(colHeader, colIndexToChar(jcol)+'@');
	}
	insertColumnFormulas(scoreSheet, totalFormula ? '='+totalFormula : '', scoreTotalCol, scoreStartRow, scoreAvgRow);
	if (gradeCutoffs.length) {
	    var totalVals = scoreSheet.getSheetValues(scoreStartRow, scoreTotalCol, nids, 1);
	    var maxTotal = totalVals[maxWeightRow-scoreStartRow][0];
	    var gradeVals = [];
	    var numVals = [];
	    for (var j=0; j<nids; j++) {
		var gradeVal = '';
		var numVal = '';
		if (maxTotal && isNumber(totalVals[j][0])) {
		    var totalVal = parseNumber(totalVals[j][0]);
		    if (gradePercent)
			totalVal = 100*(totalVal/maxTotal);
		    for (var k=0; k<gradeCutoffs.length; k++) {
			if (totalVal >= gradeCutoffs[k][0]) {
			    gradeVal = gradeCutoffs[k][1];
			    numVal = gradeCutoffs[k][2];
			    break;
			}
		    }
		}
		gradeVals.push( [[gradeVal]] );
		numVals.push( [[numVal]] );
	    }
	    scoreSheet.getRange(scoreStartRow, scoreGradeCol, nids, 1).setValues(gradeVals);
	    scoreSheet.getRange(scoreStartRow, scoreNumGradeCol, nids, 1).setValues(numVals);

	    var colChar = colIndexToChar( scoreNumGradeCol );
	    var numGradeAvgFormula = '=AVERAGEIF('+colChar+avgStartRow+':'+colChar+',">0")';
	    scoreSheet.getRange(scoreAvgRow, scoreNumGradeCol, 1, 1).setValues([[numGradeAvgFormula]]);
	}
    } finally {
    }

    return updatedNames;
}

function insertColumnFormulas(sheet, formula, insertCol, startRow, extraRow) {
    // Insert column of formulas, replacing @ with row number
    var cellFormulas = [];
    var maxRows = sheet.getLastRow();
    for (var jRow=startRow; jRow<=maxRows; jRow++)
	cellFormulas.push([formula.replace(/@/g,''+jRow)]);
    sheet.getRange(startRow, insertCol, maxRows-startRow+1, 1).setValues(cellFormulas);
    if (extraRow)
	sheet.getRange(extraRow, insertCol, 1, 1).setValues([[formula.replace(/@/g,''+extraRow)]]);
}

function smallBlank(values, n) {
    // Returns the n-th smallest value in a list of values, treating blanks as zeros (NOT USED)
    var minVals = [];
    for (var j=0; j<values.length; j++) {
	var row = values[j];
	for (var k=0; k<row.length; k++) {
	    var rowVal = isNumber(row[k]) ? row[k] : 0;
	    if (minVals.length < n || rowVal < minVals[0]) {
		var insertOffset = minVals.length;
		for (var m=0; m<minVals.length; m++) {
		    if (rowVal >= minVals[m]) {
			insertOffset = m;
			break;
		    }
		}
		minVals.splice(insertOffset,0,rowVal);
		if (minVals.length > n)
		    minVals.splice(0,1);
	    }
	}
    }
    if (minVals.length == n)
	return minVals[0];
    else
	return 0;
}

function MigrateAll() {
    // Migrate sessions

    var lock = LockService.getPublicLock();
    lock.waitLock(30000);  // wait 30 seconds before conceding defeat.

    try {
	var doc = getDoc();
	var newDocName = doc.getName()+'_migrated';
	var altRoster = "altroster_slidoc";
	var newDoc = SpreadsheetApp.create(newDocName);
	var copySheets = [SETTINGS_SHEET, INDEX_SHEET, altRoster || ROSTER_SHEET];
	for (var j=0; j<copySheets.length; j++) {
	    var oldSheet = getSheet(copySheets[j]);
	    if (oldSheet) {
		var newSheet = oldSheet.copyTo(newDoc);
		if (copySheets[j] == altRoster) {
		    newSheet.setName(ROSTER_SHEET);
		    newSheet.deleteColumns(1, 1);
		} else {
		    newSheet.setName(copySheets[j]);
		}
		if (copySheets[j] == INDEX_SHEET)
		    var indexSheet = newSheet;
	    }
	}
	var newFields = [ [11, 'retakes'] ]; // (insertAfterCol, header) Must be listed right to left
	var pacedCols = ['q_total', 'q_scores', 'q_other', 'q_comments'];
	var indexColIndex = indexColumns(indexSheet);
	var indexRowIndex = indexRows(indexSheet, indexColIndex['id'], 2);
	var sessionNames = getSessionNames();
	for (var j=0; j<sessionNames.length; j++) {
	    MigrateSession0968a(sessionNames[j], newFields, pacedCols, newDoc, altRoster);
	    var sessionRow = indexRowIndex[sessionNames[j]];
	    var fieldsMin = indexSheet.getSheetValues(sessionRow, indexColIndex['fieldsMin'], 1, 1)[0][0];
	    indexSheet.getRange(sessionRow, indexColIndex['fieldsMin'], 1, 1).setValue(fieldsMin+newFields.length);
	}

	indexSheet.deleteColumns(indexColIndex['postDate'], 1);
	
	notify("Migrated sessions: "+sessionNames.join(', '), 'Slidoc Migrate');
    } catch(err) {
	SpreadsheetApp.getUi().alert(''+err);
    } finally { //release lock
	lock.releaseLock();
    }
}

function MigrateSession0968a(sessionName, newFields, pacedCols, newDoc, altRoster) {
    var oldSheet = getSheet(sessionName);
    
    var newSheet = oldSheet.copyTo(newDoc);
    newSheet.setName(sessionName);
    var headers = newSheet.getSheetValues(1, 1, 1, newSheet.getLastColumn())[0];
    for (var j=0; j<headers.length; j++) {
	if (headers[j].slice(-6).toLowerCase() == 'hidden')
	    newSheet.hideColumns(j+1);
    }
    var idCol = 1 + headers.indexOf('id');
    var gradesCol = 1 + headers.indexOf('q_grades');

    if (altRoster) {
	// alt headers: origid, name, id, email, altid
	// Replace first 4 columns in sessions with info from alt roster
	var startRow = 2;
	var origIdCol = 1;
	var nCopy = 4;
	var altRosterSheet = getSheet(altRoster);
	var altVals = altRosterSheet.getSheetValues(startRow, origIdCol, altRosterSheet.getLastRow()-startRow+1, 1+nCopy);
	var altIndex = {};
	for (var j=0; j<altVals.length; j++) {
	    // Orig ID in first column
	    altIndex[altVals[j][0]] = j+1;
	}
	var nRows = newSheet.getLastRow()-startRow+1;
	var idCol = 2;
	var origIdVals = newSheet.getSheetValues(startRow, idCol, nRows, 1);
	for (var j=origIdVals.length-1; j>=0; j--) {
	    if (origIdVals[j] == MAXSCORE_ID)
		continue;
	    var altRow = altIndex[origIdVals[j][0]];
	    if (altRow) {
		newSheet.getRange(startRow+j, 1, 1, nCopy).setValues([altVals[altRow-1].slice(1,1+nCopy)]);
	    } else {
		newSheet.deleteRow(startRow+j)
	    }
	}
    }

    var sessionEntries = lookupValues(sessionName, ['paceLevel', 'fieldsMin', 'scoreWeight', 'gradeWeight', 'otherWeight', 'attributes', 'questions', 'questionConcepts'], INDEX_SHEET);
    var sessionAttributes = JSON.parse(sessionEntries.attributes);
    var questions = JSON.parse(sessionEntries.questions);
    var questionConcepts = JSON.parse(sessionEntries.questionConcepts);
    var delCols = [];
    if (gradesCol)
	delCols.push(gradesCol)
    for (var qno=questions.length; qno>=1; qno--) {
	var shareCol    = 1 + headers.indexOf('q'+qno+'_share');
	var voteCol     = 1 + headers.indexOf('q'+qno+'_vote');
	var commentsCol = 1 + headers.indexOf('q'+qno+'_comments');
	if (shareCol)
	    delCols.push(shareCol);
	if (voteCol)
	    delCols.push(voteCol);
	if (commentsCol && !('gweight' in questions[qno-1]))
	    delCols.push(commentsCol);
    }
    delCols.sort(numSort); //  (sorting numerically)
    delCols.reverse();
    Logger.log('MigrateSession0968a: '+sessionName+' '+delCols);
    for (var j=0; j<delCols.length; j++)
	newSheet.deleteColumns(delCols[j], 1);

    if (sessionEntries.paceLevel) {
	var nCols = pacedCols.length;
	newSheet.insertColumnsAfter(sessionEntries.fieldsMin, nCols);
	newSheet.getRange(1, sessionEntries.fieldsMin+1, 1, nCols).setValues([pacedCols]);
	newSheet.getRange(2, sessionEntries.fieldsMin+2, 1, 2).setValues([[sessionEntries.scoreWeight||0, sessionEntries.otherWeight||0]]);
    }
    
    for (var j=0; j<newFields.length; j++) {
	newSheet.insertColumnsAfter(newFields[j][0], 1);
	newSheet.getRange(1, newFields[j][0]+1, 1, 1).setValues([[newFields[j][1]]]);
    }
    return newSheet;
}

