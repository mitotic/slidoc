// slidoc_sheets.js: Google Sheets add-on to interact with Slidoc documents

var VERSION = '0.97.0g';

var DEFAULT_SETTINGS = [ ['auth_key', 'testkey', 'Secret value for secure administrative access (obtain from proxy for multi-site setup)'],

			 ['server_url', '', 'Base URL of server (if any); e.g., http://example.com'],
			 [],
                         ['site_name', '', 'Site name, e.g., calc101, for multi-site setup (must match proxy)'],
			 ['site_label', 'Site name', 'Site label, e.g., Calculus 101'],
			 ['site_title', 'Site description', 'Descriptive site title'],
			 ['site_restricted', '', 'Restrict site access to admins only'],
                         ['twitter_config', '', 'Twitter stream config: username,consumer_key,consumer_secret,access_key,access_secret'],
			 [],
			 ['admin_users', '', 'User IDs or email addresses with admin access'],
			 ['grader_users', '', 'User IDs or email addresses with grader access'],
			 ['guest_users', '', 'User IDs or email addresses with guest access'],
			 [],
			 ['thaw_date', '', 'Date after which all session releases must start'],
			 ['freeze_date', '', 'Date when all user modifications are disabled'],
			 ['require_login_token', 'require', 'Non-null string for true'],
			 ['require_late_token', 'require', 'Non-null string for true'],
			 ['share_averages', 'require', 'Non-null string for true'],
		         ['total_formula', '', 'Formula for total column, e.g., 0.4*_Assignment_avg_1+0.5*_Quiz_sum+10*_Test_normavg+0.1*_Extra01'],
			 ['grading_scale', '', 'A:90%:4,B:80%:3,C:70%:2,D:60%:1,F:0%:0'] // Or A:180:4,B:160:3,...
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

// Define document IDs to create/access roster/scores/answers/stats/log sheet in separate documents
// e.g., {roster_slidoc: 'ID1', scores_slidoc: 'ID2', answers_slidoc: 'ID3', stats_slidoc: 'ID4', slidoc_log: 'ID5'}
var ALT_DOC_IDS = { };

var ADMIN_ROLE = 'admin';
var GRADER_ROLE = 'grader';

var ADMINUSER_ID = 'admin';
var MAXSCORE_ID = '_max_score';
var MAXSCOREORIG_ID = '_max_score_orig';
var AVERAGE_ID = '_average';
var RESCALE_ID = '_rescale';
var TESTUSER_ID = '_test_user';

var MIN_HEADERS = ['name', 'id', 'email', 'altid'];
var COPY_HEADERS = ['source', 'team', 'lateToken', 'lastSlide', 'retakes'];

var TESTUSER_ROSTER = ['#user, test', TESTUSER_ID, '', ''];

var SETTINGS_SHEET = 'settings_slidoc';
var INDEX_SHEET = 'sessions_slidoc';
var ROSTER_SHEET = 'roster_slidoc';
var SCORES_SHEET = 'scores_slidoc';

var ANSWERS_DOC = 'answers_slidoc';
var STATS_DOC = 'stats_slidoc';

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

function loadSettings() {
    var settingsSheet = getSheet(SETTINGS_SHEET);
    if (!settingsSheet)
	throw('loadSettings: Sheet '+SETTINGS_SHEET+' not found!');
    var settingsData = settingsSheet.getSheetValues(2, 1, settingsSheet.getLastRow()-1, 2);
    for (var j=0; j<settingsData.length; j++) {
	if (!settingsData[j].length || !settingsData[j][0].trim())
	    continue;
	var settingsValue = (settingsData[j].length > 1) ? settingsData[j][1] : '';
	if (typeof settingsValue == 'string')
	    settingsValue = settingsValue.trim();
	else if (settingsValue)                    // null, false, or 0 become null string
	    settingsValue = '' + settingsValue;
	else
	    settingsValue = '';
	Settings[settingsData[j][0].trim()] = settingsValue;
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
	return lookupValues(userId, MIN_HEADERS, ROSTER_SHEET, true);
    } catch(err) {
	if (isSpecialUser(userId))
	    return ['#'+userId+', '+userId, userId, '', ''];
	throw("Error:NEED_ROSTER_ENTRY:userID '"+userId+"' not found in roster");
    }
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
    // action: ''|'answers'|'stats'|'scores'
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
    try {
	loadSettings();

	var freezeDate = createDate(Settings['freeze_date']) || null;

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

	var action = params.action || '';
	var proxy = params.proxy || '';
	var sheetName = params.sheet || '';
	if (!action && !proxy && !sheetName)
	    throw('Error:SHEETNAME:No sheet name specified');

	// Read-only sheets
	var protectedSheet = (sheetName.match(/_slidoc$/) && sheetName != ROSTER_SHEET && sheetName != INDEX_SHEET) || sheetName.match(/-answers$/) || sheetName.match(/-stats$/);

	// Admin-only access sheets (ROSTER_SHEET modifications will be restricted later)
	var restrictedSheet = (sheetName.match(/_slidoc$/) && sheetName != ROSTER_SHEET && sheetName != SCORES_SHEET);

	var loggingSheet = sheetName.match(/_log$/);

	if (params.action) {
	    if (!adminUser)
		throw("Error:ACTION:Must be admin user to perform action on sheet "+sheetName);
	    if (protectedSheet || restrictedSheet || loggingSheet)
		throw('Error:ACTION:Action not allowed for sheet '+sheetName);
	    var sessions = sheetName ? [sheetName] : getSessionNames();
	    if (params.action == 'answers') {
		for (var j=0; j<sessions.length; j++)
		    updateAnswers(sessions[j]);
	    } else if (params.action == 'stats') {
		for (var j=0; j<sessions.length; j++)
		    updateStats(sessions[j]);
	    } else if (params.action == 'scores') {
		var retval = updateScores(sessions);
		if (sheetName && !retval.length)
		    throw('Error:ACTION:Failed to update score for sheet '+sheetName);
	    } else {
		throw('Error:ACTION:Invalid action '+params.action+' for sheet '+sheetName);
	    }
	    return {"result": "success", "value": [], "headers": [],
		    "info": [], "messages": ""};
	}

	var sessionEntries = null;
	var sessionAttributes = null;
	var questions = null;
	var paceLevel = null;
	var adminPaced = null;
	var dueDate = null;
	var gradeDate = null;
	var voteDate = null;
	var computeTotalScore = false;
	var curDate = new Date();

	if (proxy && adminUser != ADMIN_ROLE)
	    throw("Error::Must be admin user for proxy access to sheet '"+sheetName+"'");

        if (sheetName == SETTINGS_SHEET && adminUser != ADMIN_ROLE)
            throw('Error::Must be admin user to access settings')

	if (restrictedSheet && !adminUser)
	    throw("Error::Must be admin/grader user to access restricted sheet '"+sheetName+"'");

	var rosterValues = [];
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

	if (proxy && params.get && params.all) {
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

	} else if (proxy && params.allupdates) {
	    // Update multiple sheets from proxy
	    returnValues = [];
	    returnInfo.updateErrors = [];
	    var data = JSON.parse(params.data);
	    for (var j=0; j<data.length; j++) {
		var updateSheetName = data[j][0];
		var updateHeaders = data[j][1];
		var updateKeys = data[j][2];
		var updateRows = data[j][3];
		//returnMessages.push('Debug::updateSheet, keys, rows: '+updateSheetName+', '+updateKeys+', '+updateRows.length);

		try {
		    var updateSheet = getSheet(updateSheetName);
		    if (!updateSheet) {
			if (params.create)
			    updateSheet = createSheet(updateSheetName, updateHeaders);
			else
			    throw("Error:PROXY_MISSING_SHEET:Sheet not found: '"+updateSheetName+"'");
		    }

		    var temHeaders = updateSheet.getSheetValues(1, 1, 1, updateSheet.getLastColumn())[0];
		    if (updateHeaders.length != temHeaders.length)
			throw("Error:PROXY_HEADER_COUNT:Number of headers does not equal that present in sheet '"+updateSheetName+"'; delete it or edit headers.");
		    for (var m=0; m<updateHeaders.length; m++) {
			if (updateHeaders[m] != temHeaders[m])
			    throw("Error:PROXY_HEADER_NAMES:Column header mismatch: Expected "+updateHeaders[m]+" but found "+temHeaders[m]+" in sheet '"+updateSheetName+"'");
		    }

		    if (updateKeys === null) {
			// Update non-keyed sheet
			for (var k=0; k<updateRows.length; k++) {
			    var rowNum = updateRows[k][0];
			    var rowVals = updateRows[k][1];
			    var lastRowNum = updateSheet.getLastRow();
			    for (var m=0; m<rowVals.length; m++)
				rowVals[m] = parseInput(rowVals[m], updateHeaders[m]);

			    if (rowNum > lastRowNum)
				updateSheet.insertRowBefore(lastRowNum+1)
			    updateSheet.getRange(rowNum, 1, 1, rowVals.length).setValues([rowVals]);
			}
		    } else {
			// Update keyed sheet
			var lastRowNum = updateSheet.getLastRow();
			if (lastRowNum < 1)
			    throw("Error:PROXY_DATA_ROWS:Sheet has no data rows '"+updateSheetName+"'");

			var updateColumnIndex = indexColumns(updateSheet);
			var idCol = updateColumnIndex['id'];
			var nameCol = updateColumnIndex['name'] || idCol;
			var totalCol = updateColumnIndex['q_total'];
			var deletedRows = 0;
			var insertedRows = 0;

			var updateStickyRows = lastRowNum;
			if (lastRowNum > 1) {
			    var keys = updateSheet.getSheetValues(2, idCol, lastRowNum-1, 1);

			    // Determine number of sticky rows
			    for (var k=0; k < keys.length; k++) {
				// Locate first non-null key
				if (keys[k][0]) {
				    updateStickyRows = k+1;
				    break
				}
			    }
			    for (var rowNum=lastRowNum; rowNum > updateStickyRows; rowNum--) {
				// Delete rows for which keys are not found (backwards)
				if (!(keys[rowNum-2][0] in updateKeys)) {
				    updateSheet.deleteRow(rowNum);
				    deletedRows += 1;
				}
			    }
			}

			for (var k=0; k<updateRows.length; k++) {
			    // Update rows with pre-existing or new keys
			    var rowId = updateRows[k][0];
			    var rowVals = updateRows[k][1];
			    var temIndexRow = indexRows(updateSheet, idCol, updateStickyRows+1);
			    var modRow = temIndexRow[rowId];
			    if (!modRow) {
				if (rowId == MAXSCORE_ID || updateSheet.getLastRow() == updateStickyRows) {
				    // MaxScore or no rows
				    modRow = updateStickyRows+1;
				} else if (rowId == TESTUSER_ID) {
				    // Test user always appears after max score
				    modRow = temIndexRow[MAXSCORE_ID] ? temIndexRow[MAXSCORE_ID]+1 : updateStickyRows+1;
				} else {
				    var idValues = updateSheet.getSheetValues(1+updateStickyRows, idCol, updateSheet.getLastRow()-updateStickyRows, 1);
				    var nameValues = updateSheet.getSheetValues(1+updateStickyRows, nameCol, updateSheet.getLastRow()-updateStickyRows, 1);
				    modRow = updateStickyRows + locateNewRow(rowVals[nameCol-1], rowId, nameValues, idValues, TESTUSER_ID);
				}
				updateSheet.insertRowBefore(modRow);
				insertedRows += 1;
			    } else {
				// Pre-existing row
				if (totalCol) {
				    // Do not overwrite old totalCol formula value
				    rowVals[totalCol-1] = updateSheet.getRange(modRow, totalCol, 1, 1).getFormula();
				}
			    }
			    for (var m=0; m<rowVals.length; m++)
				rowVals[m] = parseInput(rowVals[m], updateHeaders[m]);

			    updateSheet.getRange(modRow, 1, 1, rowVals.length).setValues([rowVals]);
			    //returnMessages.push('Debug::updateRow: '+modRow+', '+rowId+', '+rowVals);
			}
			if (totalCol && (deletedRows || insertedRows))
			    updateTotalFormula(updateSheet, lastRowNum+insertedRows-deletedRows);
		    }
		} catch(err) {
		    var errMsg = ''+err;
		    ///if (errMsg.match(/^Error:PROXY_/))
			returnInfo.updateErrors.push([updateSheetName, errMsg]);
		    ///else
			///throw(errMsg);
		}
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

	    if (!restrictedSheet && !protectedSheet && !loggingSheet && sheetName != ROSTER_SHEET && getSheet(INDEX_SHEET)) {
		// Indexed session
		sessionEntries = lookupValues(sheetName, ['dueDate', 'gradeDate', 'paceLevel', 'adminPaced', 'scoreWeight', 'gradeWeight', 'otherWeight', 'fieldsMin', 'questions', 'attributes'], INDEX_SHEET);
		sessionAttributes = JSON.parse(sessionEntries.attributes);
		questions = JSON.parse(sessionEntries.questions);
		paceLevel = parseNumber(sessionEntries.paceLevel) || 0;
		adminPaced = sessionEntries.adminPaced;
		dueDate = sessionEntries.dueDate;
		gradeDate = sessionEntries.gradeDate;
		voteDate = sessionAttributes.params.plugin_share_voteDate ? createDate(sessionAttributes.params.plugin_share_voteDate) : null;

		if (sessionAttributes['params']['features'].delay_answers || sessionAttributes['params']['features'].remote_answers) {
                    // Delayed or remote answers; compute total score only after grading
                    computeTotalScore = gradeDate;
                } else {
                    computeTotalScore = true;
                }
	    }

	    // Check parameter consistency
	    var getRow = params.get || '';
	    var getShare = params.getshare || '';
	    var allRows = params.all || '';
	    var createRow = params.create || '';
	    var seedRow = adminUser ? (params.seed || null) : null;
	    var nooverwriteRow = params.nooverwrite || '';
	    var delRow = params.delrow || '';
	    var resetRow = params.resetrow || '';
	    var importSession = params.import || '';
	    
	    var columnHeaders = modSheet.getSheetValues(1, 1, 1, modSheet.getLastColumn())[0];
	    var columnIndex = indexColumns(modSheet);
	    
	    var selectedUpdates = params.update ? JSON.parse(params.update) : null;
	    var rowUpdates = params.row ? JSON.parse(params.row) : null;

            if (readOnlyAccess) {
                if (delRow || resetRow || selectedUpdates || (rowUpdates && !nooverwriteRow)) {
                    throw('Error::Admin user '+origUser+' cannot modify row for user '+paramId);
                }
            }

	    if (headers) {
		var modifyStartCol = params.modify ? parseInt(params.modify) : 0;
		if (modifyStartCol) {
                    if (!sessionEntries || !rowUpdates || rowUpdates[columnIndex['id']-1] != MAXSCORE_ID)
			throw("Error::Must be updating max scores row to modify headers in sheet "+sheetName);
                    var checkCols = modifyStartCol-1;
		} else {
                    if (headers.length != columnHeaders.length)
			throw("Error::Number of headers does not match that present in sheet '"+sheetName+"'; delete it or modify headers.");
                    var checkCols = columnHeaders.length;
		}

		for (var j=0; j< checkCols; j++) {
                    if (headers[j] != columnHeaders[j]) {
			throw("Error::Column header mismatch: Expected "+headers[j]+" but found "+columnHeaders[j]+" in sheet '"+sheetName+"'; delete it or modify headers.")
                    }
		}
		if (modifyStartCol) {
		    // Updating maxscore row; modify headers if needed
                    var startRow = 2;
                    var nRows = modSheet.getLastRow()-startRow+1;
		    var idValues = null;
                    if (nRows)
			idValues = modSheet.getSheetValues(startRow, columnIndex['id'], nRows, 1);
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
					    throw( "Error:TRUNCATE_ERROR:Cannot truncate non-empty column "+(startCol+j)+" ("+columnHeaders[startCol+j-1]+") in sheet "+sheetName );
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

		    if (computeTotalScore) {
			updateTotalScores(modSheet, sessionAttributes, questions, true);
		    }
		    updateTotalFormula(modSheet, modSheet.getLastRow());
		}

	    }
	    
	    var userId = null;
	    var displayName = null;

	    var voteSubmission = '';
            var alterSubmission = false;
            var twitterSetting = false;
	    if (!rowUpdates && selectedUpdates && selectedUpdates.length == 2 && selectedUpdates[0][0] == 'id') {
		if (selectedUpdates[1][0].match(/_vote$/) && sessionAttributes.shareAnswers) {
		    var qprefix = selectedUpdates[1][0].split('_')[0];
		    voteSubmission = sessionAttributes.shareAnswers[qprefix] ? (sessionAttributes.shareAnswers[qprefix].share||'') : '';
		}

		if (selectedUpdates[1][0] == 'submitTimestamp')
		    alterSubmission = true;

		if (selectedUpdates[1][0] == 'twitter' && sheetName == ROSTER_SHEET)
		    twitterSetting = true;
	    }

	    if (!adminUser && selectedUpdates && !voteSubmission && !twitterSetting)
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
                    // Force submit all non-sticky rows past effective due date
                    var idCol = columnIndex.id;
                    var submitCol = columnIndex.submitTimestamp;
                    var lateTokenCol = columnIndex.lateToken;
                    var allValues = modSheet.getSheetValues(1+numStickyRows, 1, modSheet.getLastRow()-numStickyRows, columnHeaders.length);
                    for (var j=0; j<allValues.length; j++) {
                        if (allValues[j][submitCol-1] || allValues[j][idCol-1] == MAXSCORE_ID) {
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
                            modSheet.setSheetValues(j+1+numStickyRows, submitCol, 1, 1, [[curDate]]);
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
	    //returnMessages.push('Debug::userRow, userid, rosterValues: '+userRow+', '+userId+', '+rosterValues);
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
		    if (savedSession && Object.keys(savedSession.questionsAttempted).length) {
			var scores = tallyScores(questions, savedSession['questionsAttempted'], savedSession['hintsUsed'], sessionAttributes['params'], sessionAttributes['remoteAnswers']);
			var lastTake = ''+(scores.weightedCorrect || 0);
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
		    for (var j=0; j<columnHeaders.length; j++)
			rowUpdates.push(null);
		}
	    }

	    if (!adminUser && freezeDate && curDate.getTime() > freezeDate.getTime() && (newRow || rowUpdates || selectedUpdates))
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

	    } else if (newRow && selectedUpdates) {
		throw('Error::Selected updates cannot be applied to new row');
	    } else {
		var pastSubmitDeadline = false;
		var forceSubmission = false;
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

                    if (dueDate && !prevSubmitted && !voteSubmission && !alterSubmission && userId != MAXSCORE_ID) {
                        // Check if past submission deadline
                        var lateToken = '';
			var curTime = curDate.getTime();
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
                                    forceSubmission = true;
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
                    if (userId == MAXSCORE_ID) {
			userRow = numStickyRows+1;
                    } else if (userId == TESTUSER_ID && !loggingSheet) {
                        // Test user always appears after max score
			var maxScoreRow = lookupRowIndex(MAXSCORE_ID, modSheet, numStickyRows+1);
                        userRow = maxScoreRow ? maxScoreRow+1 : numStickyRows+1
		    } else if (numRows > numStickyRows && !loggingSheet) {
			var displayNames = modSheet.getSheetValues(1+numStickyRows, columnIndex['name'], numRows-numStickyRows, 1);
			var userIds = modSheet.getSheetValues(1+numStickyRows, columnIndex['id'], numRows-numStickyRows, 1);
			userRow = numStickyRows + locateNewRow(displayName, userId, displayNames, userIds, TESTUSER_ID);
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
			    if (userId == MAXSCORE_ID && totalCol)
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

		    if (scoresCol && sessionEntries && parseNumber(sessionEntries.scoreWeight)) {
			if (userId != MAXSCORE_ID && computeTotalScore) {
			    // Tally user scores
			    var savedSession = unpackSession(columnHeaders, rowValues);
			    if (savedSession && Object.keys(savedSession.questionsAttempted).length) {
				var scores = tallyScores(questions, savedSession.questionsAttempted, savedSession.hintsUsed, sessionAttributes.params, sessionAttributes.remoteAnswers);
				rowValues[scoresCol-1] = scores.weightedCorrect || '';
			    }
			}
		    }
		    // Copy user info from roster (if available)
		    for (var j=0; j<rosterValues.length; j++)
			rowValues[j] = rosterValues[j];

		    //returnMessages.push("Debug:ROW_VALUES:"+rowValues);
		    // Save updated row
		    userRange.setValues([rowValues]);

                    if (paramId == TESTUSER_ID && sessionEntries && adminPaced) {
                        var lastSlideCol = columnIndex['lastSlide'];
                        if (lastSlideCol && rowValues[lastSlideCol-1]) {
                            // Copy test user last slide number as new adminPaced value
                            setValue(sheetName, 'adminPaced', rowValues[lastSlideCol-1], INDEX_SHEET);
                        }
                        if (params.submit) {
                            // Use test user submission time as due date for admin-paced sessions
			    var submitTimetamp = rowValues[submitTimestampCol-1];
                            setValue(sheetName, 'dueDate', submitTimetamp, INDEX_SHEET);
                            var idColValues = getColumns('id', modSheet, 1, 1+numStickyRows);
                            var initColValues = getColumns('initTimestamp', modSheet, 1, 1+numStickyRows);
                            for (var j=0; j < idColValues.length; j++) {
                                // Submit all other users who have started a session
                                if (initColValues[j] && idColValues[j] && idColValues != TESTUSER_ID && idColValues[j] != MAXSCORE_ID) {
                                    setValue(idColValues[j], 'submitTimestamp', submitTimetamp, sheetName);
                                }
                            }
                        }
                    }

		} else if (selectedUpdates) {
		    // Update selected row values
		    // Timestamp is updated only if specified in list
		    if (!forceSubmission && !voteSubmission && !twitterSetting) {
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
                            if (forceSubmission) {
				modValue = curDate;
			    } else if (alterSubmission) {
                                if (colValue == null) {
                                    modValue = curDate;
                                } else if (colValue) {
                                    modValue = createDate(colValue);
                                } else {
                                    // Unsubmit if blank value (also clear lateToken)
                                    modValue = '';
                                    modSheet.getRange(userRow, columnIndex['lateToken'], 1, 1).setValues([[ '' ]]);
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
					rowValues[otherCol-1] = ''+(parseInt(rowValues[otherCol-1] || 0) + (qshare.voteWeight || 0));
					modSheet.getRange(userRow, otherCol, 1, 1).setValues([[ rowValues[otherCol-1] ]])
				    }
				}
				modValue = colValue;
			    }
			} else if (colValue == null) {
			    // Do not modify field
			} else if (MIN_HEADERS.indexOf(colHeader) == -1 && colHeader.slice(-9) != 'Timestamp') {
			    // Update row values for header (except for id, name, email, altid, *Timestamp)
			    if (!restrictedSheet && !twitterSetting && !importSession && (headerColumn <= fieldsMin || !/^q\d+_(comments|grade)$/.exec(colHeader)) )
				throw("Error::Cannot selectively update user-defined column '"+colHeader+"' in sheet '"+sheetName+"'");
			    var hmatch = QFIELD_RE.exec(colHeader);
                            if (hmatch && (hmatch[2] == 'grade' || hmatch[2] == 'comments')) {
                                var qno = parseInt(hmatch[1]);
                                if (rowValues[teamCol-1] && questions && qno <= questions.length && questions[qno-1].team == 'response') {
                                    // Broadcast grade/comments to all team members
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

                if ((paramId != TESTUSER_ID || prevSubmitted) && sessionEntries && adminPaced)
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

                if (computeTotalScore && getRow) {
                    returnInfo['remoteAnswers'] = sessionAttributes.remoteAnswers;
                }
	    }
	}

	// return success results
	return {"result":"success", "value": returnValues, "headers": returnHeaders,
		"info": returnInfo,
		"messages": returnMessages.join('\n')};
    } catch(err){
	// if error return this
	return {"result":"error", "error": ''+err, "value": null,
		"info": returnInfo,
		"messages": returnMessages.join('\n')};
    } finally { //release lock
	lock.releaseLock();
    }
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
    rowVals[headers.indexOf('session_hidden')] = JSON.stringify(session);

    var rosterSheet = getSheet(ROSTER_SHEET);
    if (rosterSheet) {
	var rosterValues = getRosterEntry(userId);

	for (var j=0; j<rosterValues.length; j++) {
	    if (rosterValues[j])
		rowVals[j] = rosterValues[j];
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
    
function parseInput(value, headerName) {
    // Parse input date strings
    if (value && (headerName.slice(-4).toLowerCase() == 'date' || headerName.slice(-4).toLowerCase() == 'time' || headerName.slice(-9) == 'Timestamp')) {
	try { return createDate(value); } catch (err) { }
    }
    return value;
}

function genAuthPrefix(userId, role, sites) {
    return ':' + userId + ':' + (role||'') + ':' + (sites||'');
}

function getAuthToken(key, userId, role, sites, prefixed) {
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

function getSheet(sheetName, docName, create) {
    // Return sheet in external document, or in current document. If create, create as needed.
    var docId = ALT_DOC_IDS[docName||''] || ALT_DOC_IDS[sheetName] || null;
    var doc = docId ? SpreadsheetApp.openById(docId) : null;
    if (!doc)
	doc = getDoc();

    var sheet = doc.getSheetByName(sheetName);
    if (!sheet && create)
	sheet = doc.insertSheet(sheetName);
    return sheet;
}

function deleteSheet(sheetName) {
    var temSheet = getSheet(sheetName);
    if (!temSheet)
	return false;
    var doc = getDoc();
    doc.deleteSheet(temSheet);
    return true;
}

function createSheet(sheetName, headers) {
    var sheet = getSheet(sheetName, null, true);
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

function lookupValues(idValue, colNames, sheetName, listReturn) {
    // Return parameters in list colNames for idValue from sheet
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
	if (!(colNames[j] in indexColIndex))
	    throw('Column '+colNames[j]+' not found in index sheet '+sheetName);
	retVals[colNames[j]] = indexSheet.getSheetValues(sessionRow, indexColIndex[colNames[j]], 1, 1)[0][0];
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

function locateNewRow(newName, newId, nameValues, idValues, skipId) {
    // Return row number before which new name/id combination should be inserted
    for (var j=0; j<nameValues.length; j++) {
	if (skipId && skipId == idValues[j][0])
	    continue;
	if (nameValues[j][0] > newName || (nameValues[j][0] == newName && idValues[j][0] > newId)) {
	    // Sort by name and then by id
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
	return actionFunc(sessionName);
    } finally { //release lock
	lock.releaseLock();
    }

}

function sessionAnswerSheet() {
    // Create session answers sheet
    var sheetName = updateSession(updateAnswers);
    notify('Created sheet :'+sheetName, 'Slidoc Answers');
}

function updateAnswers(sessionName) {
    try {
	var sessionSheet = getSheet(sessionName);
	if (!sessionSheet)
	    throw('Sheet not found: '+sessionName);
	if (!sessionSheet.getLastColumn())
	    throw('No columns in sheet: '+sessionName);

	var sessionColIndex = indexColumns(sessionSheet);
	var sessionColHeaders = sessionSheet.getSheetValues(1, 1, 1, sessionSheet.getLastColumn())[0];

	var sessionEntries = lookupValues(sessionName, ['attributes', 'questions'], INDEX_SHEET);
	var sessionAttributes = JSON.parse(sessionEntries.attributes);
	var questions = JSON.parse(sessionEntries.questions);
	var qtypes = [];
	var answers = [];
	for (var j=0; j<questions.length; j++) {
	    qtypes[j] = questions[j].qtype||'';
	    answers[j] = questions[j].correct;
	}

	// Copy first two columns from session sheet
	var copyCols = 2;
	var answerHeaders = sessionSheet.getSheetValues(1, 1, 1, copyCols)[0];

	var respCols = [];
	var extraCols = ['expect', 'score', 'plugin', 'hints'];
	for (var j=0; j<qtypes.length; j++) {
	    var qprefix = 'q'+(j+1);
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
	//Logger.log('ansHeaders: '+answerHeaders);
	var ansHeaderCols = {};
	for (var j=0; j<answerHeaders.length; j++)
	    ansHeaderCols[answerHeaders[j]] = j+1;

	// Session sheet columns
	var sessionStartRow = SESSION_START_ROW;

	// Answers sheet columns
	var answerStartRow = 3;

	// Session answers headers

	// New answers sheet
	var answerSheetName = sessionName+'-answers';
	var answerSheet = getSheet(answerSheetName, ANSWERS_DOC, true);
	answerSheet.clear()
	var answerHeaderRange = answerSheet.getRange(1, 1, 1, answerHeaders.length);
	answerHeaderRange.setValues([answerHeaders]);
	answerHeaderRange.setWrap(true);
	answerSheet.getRange('1:1').setFontWeight('bold');
	answerSheet.getRange('2:2').setFontStyle('italic');
	answerSheet.getRange(2, ansHeaderCols['id'], 1, 1).setValues([[AVERAGE_ID]]);

	for (var ansCol=copyCols+1; ansCol<=answerHeaders.length; ansCol++) {
	    if (answerHeaders[ansCol-1].slice(-6) == '_score') {
		var ansAvgRange = answerSheet.getRange(2, ansCol, 1, 1);
		ansAvgRange.setNumberFormat('0.###');
		ansAvgRange.setValues([['=AVERAGE('+colIndexToChar(ansCol)+'$'+answerStartRow+':'+colIndexToChar(ansCol)+')']]);
	    }
	}

	// Number of ids
	var nids = sessionSheet.getLastRow()-sessionStartRow+1;

	answerSheet.getRange(answerStartRow, 1, nids, copyCols).setValues(sessionSheet.getSheetValues(sessionStartRow, 1, nids, copyCols));

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
		    var qprefix = 'q'+qno;
		    // Copy responses
		    rowVals[respCols[qno-1]-1] = (qAttempted[qno].response || '');
		    if (qAttempted[qno].explain)
			rowVals[respCols[qno-1]-1] += '\nEXPLANATION: ' + qAttempted[qno].explain;
		    // Copy extras
		    for (var m=0; m<extraCols.length; m++) {
			var attr = extraCols[m];
			var qcolName = qprefix+'_'+attr;
			if (qcolName in ansHeaderCols) {
			    if (attr == 'hints') {
				rowVals[ansHeaderCols[qcolName]-1] = qHints[qno] || '';
			    } else if (attr == 'score') {
				rowVals[ansHeaderCols[qcolName]-1] = scores.qscores[qno-1] || 0;
			    } else if (attr in qAttempted[qno]) {
				rowVals[ansHeaderCols[qcolName]-1] = (qAttempted[qno][attr]===null) ? '': qAttempted[qno][attr]
			    }
			}
		    }
		}
	    }
	    qRows.push(rowVals.slice(copyCols));

	}
	answerSheet.getRange(answerStartRow, copyCols+1, nids, answerHeaders.length-copyCols).setValues(qRows);
    } finally {
    }
    return answerSheetName;
}


function sessionCorrectSheet() {
    // Create session correct sheet
    var sheetName = updateSession(updateCorrect);
    notify('Created sheet :'+sheetName, 'Slidoc Correct');
}

function updateCorrect(sessionName) {
    try {
	var sessionSheet = getSheet(sessionName);
	if (!sessionSheet)
	    throw('Sheet not found: '+sessionName);
	if (!sessionSheet.getLastColumn())
	    throw('No columns in sheet: '+sessionName);

	var sessionColIndex = indexColumns(sessionSheet);
	var sessionColHeaders = sessionSheet.getSheetValues(1, 1, 1, sessionSheet.getLastColumn())[0];

	var sessionEntries = lookupValues(sessionName, ['attributes', 'questions'], INDEX_SHEET);
	var sessionAttributes = JSON.parse(sessionEntries.attributes);
	var questions = JSON.parse(sessionEntries.questions);
	var qtypes = [];
	var answers = [];
	for (var j=0; j<questions.length; j++) {
	    qtypes[j] = questions[j].qtype||'';
	    answers[j] = questions[j].correct;
	}

	// Copy first two columns from session sheet
	var copyCols = 2;
	var correctHeaders = sessionSheet.getSheetValues(1, 1, 1, copyCols)[0];

	for (var j=0; j<questions.length; j++) {
	    correctHeaders.push('q'+(j+1));
	}

	// Session sheet columns
	var sessionStartRow = SESSION_START_ROW;

	// Correct sheet columns
	var correctStartRow = 2;

	// New correct sheet
	var correctSheetName = sessionName+'-correct';
	var correctSheet = getSheet(correctSheetName, '', true);
	correctSheet.clear()
	var correctHeaderRange = correctSheet.getRange(1, 1, 1, correctHeaders.length);
	correctHeaderRange.setValues([correctHeaders]);
	correctHeaderRange.setWrap(true);
	correctSheet.getRange('1:1').setFontWeight('bold');

	// Number of ids
	var nids = sessionSheet.getLastRow()-sessionStartRow+1;

	correctSheet.getRange(correctStartRow, 1, nids, copyCols).setValues(sessionSheet.getSheetValues(sessionStartRow, 1, nids, copyCols));

	// Get hidden session values
	var hiddenSessionCol = sessionColIndex['session_hidden'];
	var hiddenVals = sessionSheet.getSheetValues(sessionStartRow, hiddenSessionCol, nids, 1);
	var qRows = [];

	for (var j=0; j<nids; j++) {
	    var rowValues = sessionSheet.getSheetValues(j+sessionStartRow, 1, 1, sessionColHeaders.length)[0];
	    var savedSession = unpackSession(sessionColHeaders, rowValues);
	    var qAttempted = savedSession.questionsAttempted;
	    var qShuffle = savedSession.questionShuffle;

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
	correctSheet.getRange(correctStartRow, copyCols+1, nids, questions.length).setValues(qRows);
    } finally {
    }
    return correctSheetName;
}

function sessionStatSheet() {
    // Create session stats sheet
    var sheetName = updateSession(updateStats);
    notify('Created sheet :'+sheetName, 'Slidoc Stats');
}

function updateStats(sessionName) {
    try {
	loadSettings();
	var sessionSheet = getSheet(sessionName);
	if (!sessionSheet)
	    throw('Sheet not found '+sessionName);
	if (!sessionSheet.getLastColumn())
	    throw('No columns in sheet '+sessionName);

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

	var statHeaders = sessionCopyCols.concat(statExtraCols) ;
	for (var j=0; j<p_concepts.length; j++)
	    statHeaders.push('p:'+p_concepts[j]);
	for (var j=0; j<s_concepts.length; j++)
	    statHeaders.push('s:'+s_concepts[j]);
	var nconcepts = p_concepts.length + s_concepts.length;

	// Stats sheet columns
	var statStartRow = 3; // Leave blank row for formulas
	var statQuestionCol = sessionCopyCols.length+1;
	var nqstats = statExtraCols.length;
	var statConceptsCol = statQuestionCol + nqstats;

	var avgStartRow = statStartRow;
	if (nids) {
	    var temIds = sessionSheet.getSheetValues(sessionStartRow, sessionColIndex['id'], nids, 1);
	    var temNames = sessionSheet.getSheetValues(sessionStartRow, sessionColIndex['name'], nids, 1);
	    for (var j=0; j<nids; j++) {
		// Skip any initial row(s) in the roster with test user or ID/names starting with underscore/hash
		// when computing averages and other stats
		if (temIds[j][0] == TESTUSER_ID || temIds[j][0].match(/^_/) || temNames[j][0].match(/^#/))
		    avgStartRow += 1;
		else
		    break;
	    }
	}

	// New stat sheet
	var statSheetName = sessionName+'-stats';
	var statSheet = getSheet(statSheetName, STATS_DOC, true);
	statSheet.clear()
	var statHeaderRange = statSheet.getRange(1, 1, 1, statHeaders.length);
	statHeaderRange.setValues([statHeaders]);
	statHeaderRange.setWrap(true);
	statSheet.getRange('1:1').setFontWeight('bold');
	var statAvgList = [];
	for (var avgCol=sessionCopyCols.length+1; avgCol<=statHeaders.length; avgCol++)
	    statAvgList.push('=AVERAGE('+colIndexToChar(avgCol)+'$'+avgStartRow+':'+colIndexToChar(avgCol)+')');
	var statAvgRange = statSheet.getRange(2, sessionCopyCols.length+1, 1, statHeaders.length-sessionCopyCols.length);
	statAvgRange.setValues([statAvgList]);
	statAvgRange.setNumberFormat('0.###');

	var statColIndex = indexColumns(statSheet);
	statSheet.getRange(2, statColIndex['id'], 1, 1).setValues([[AVERAGE_ID]]);
	statSheet.getRange('2:2').setFontStyle('italic');

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
	for (var j=0; j<nconcepts; j++) nullConcepts.push('');

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
			missedFraction.push(missedConcepts[m][k][0]/Math.max(1,missedConcepts[m][k][1]));
		conceptTallies.push(missedFraction);
	    } else {
		conceptTallies.push(nullConcepts);
	    }
	}
	statSheet.getRange(statStartRow, statQuestionCol, nids, nqstats).setValues(questionTallies);
	if (nconcepts)
	    statSheet.getRange(statStartRow, statConceptsCol, nids, nconcepts).setValues(conceptTallies);
    } finally {
    }

    return statSheetName;
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

function updateTotalScores(modSheet, sessionAttributes, questions, force) {
    // If not force, only update non-blank entries
    var startRow = 2;
    var nRows = modSheet.getLastRow()-startRow+1;
    var columnHeaders = modSheet.getSheetValues(1, 1, 1, modSheet.getLastColumn())[0];
    var columnIndex = indexColumns(modSheet);
    if (nRows) {
        // Update total scores
        var idVals = modSheet.getSheetValues(startRow, columnIndex['id'], nRows, 1);
        var scoreRange = modSheet.getRange(startRow, columnIndex['q_scores'], nRows, 1);
        var scoreValues = scoreRange.getValues();
        for (var k=0; k < nRows; k++) {
            if (idVals[k][0] != MAXSCORE_ID && questions && (force || scoreValues[k][0] != '')) {
		var temRowVals = modSheet.getSheetValues(startRow+k, 1, 1, columnHeaders.length)[0];
		var savedSession = unpackSession(columnHeaders, temRowVals);
		if (savedSession && Object.keys(savedSession.questionsAttempted).length) {
		    var scores = tallyScores(questions, savedSession['questionsAttempted'], savedSession['hintsUsed'], sessionAttributes['params'], sessionAttributes['remoteAnswers']);
		    scoreValues[k][0] = scores.weightedCorrect || '';
                } else {
		    scoreValues[k][0] = '';
		}
	    }
	}
        scoreRange.setValues(scoreValues);
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
	response = '' + response;
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

function trackConcepts(qscores, questionConcepts, allQuestionConcepts) {
    // Track missed concepts:  missedConcepts = [ [ [missed,total], [missed,total], ...], [...] ]
    var missedConcepts = [ [], [] ];
    if (allQuestionConcepts.length != 2)
	return;
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

function updateTotalAux(sheetName) {
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

function updateScoreSession() {
    // Update scores sheet for current session
    return updateSession(updateScoreAux);
}

function updateScoreAux(sessionName) {
    var updatedNames = updateScores([sessionName], true);
    if (updatedNames && updatedNames.length)
	notify('Updated scores for session '+sessionName, 'Slidoc Scores');
    else
	notify('Failed to update scores for session '+sessionName+'. Ensure that grades are released and session weight is not zero', 'Slidoc Scores');
    return updatedNames;
}

function updateScoreAll() {
    // Update scores sheet for all sessions

    var lock = LockService.getPublicLock();
    lock.waitLock(30000);  // wait 30 seconds before conceding defeat.

    try {
	loadSettings();
	var sessionNames = getSessionNames();
	var scoreSheet = getSheet(SCORES_SHEET);
	if (scoreSheet) {
	    // Refresh only posted sessions
	    var scoreColIndex = indexColumns(scoreSheet);
	    var curSessions = [];
	    for (var j=0; j<sessionNames.length; j++) {
		if (scoreColIndex['_'+sessionNames[j]])
		    curSessions.push(sessionNames[j]);
	    }
	    sessionNames = curSessions;
	}

	var updatedNames = updateScores(sessionNames, true);
	notify("Updated scores for sessions: "+updatedNames.join(', '), 'Slidoc Scores');
    } catch(err) {
	SpreadsheetApp.getUi().alert(''+err);
    } finally { //release lock
	lock.releaseLock();
    }

}

var AGGREGATE_COL_RE = /\b(_\w+)_(avg|normavg|sum)(_(\d+))?$/i;

function updateScores(sessionNames, interactive) {
    // Update scores sheet for sessions in list
    // Returns list of updated sessions

    try {
	var totalFormula = Settings['total_formula'] || '';
	var gradingScale = Settings['grading_scale'] || '';
	var aggregateColumns = [];
	var aggregateParams = {};
	var totalFormulaStr = '';
	if (totalFormula) {
	    totalFormulaStr = totalFormula.replace(/\b_(avg|normavg|sum)_(\d+)\b/gi,'_$1').replace(/(\b_)/g,'');
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
	    gradeCutoffs.sort();
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
	var scoreAvgRow  = 3;
	var maxWeightOrigRow = 4;
	var maxWeightRow = 5;
	var userStartRow = 6;
	var numFormatRow = rescaleRow + 1;
	var scoreStartRow = maxWeightRow;
	var avgStartRow = userStartRow;

	// Copy user info from roster
	var userInfoSheet = getSheet(ROSTER_SHEET);
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
	var scoreSheetName = SCORES_SHEET;
	var scoreSheet = getSheet(scoreSheetName);
	if (!scoreSheet) {
	    // Create session score sheet
	    scoreSheet = getSheet(scoreSheetName, null, true);

	    // Score sheet headers
	    scoreSheet.getRange(1, 1, 1, MIN_HEADERS.length).setValues(userInfoSheet.getSheetValues(1, 1, 1, MIN_HEADERS.length));
	    scoreSheet.getRange(1, MIN_HEADERS.length+1, 1, extraHeaders.length).setValues([extraHeaders]);
	    scoreSheet.getRange('1:1').setFontWeight('bold');

	    scoreSheet.getRange(rescaleRow, idCol, 1, 1).setValues([[RESCALE_ID]]);
	    scoreSheet.getRange(scoreAvgRow, idCol, 1, 1).setValues([[AVERAGE_ID]]);
	    scoreSheet.getRange(rescaleRow+':'+scoreAvgRow).setFontStyle('italic');

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
		throw('Number of ids in score sheet ('+nPrevIds+') does not that in roster/session ('+nUserIds+'); re-create score sheet');
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
	    var sessionRowIndex = indexRows(sessionSheet, sessionColIndex['id'], 2);
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
	    var ansName = sessionName+'-answers';
	    if (getSheet(ansName)) {
		try {
		    deleteSheet(ansName);
		    updateAnswers(sessionName);
		} catch(err) {
		    if (interactive)
			notify('Error in updating sheet '+ansName+': '+err, 'Slidoc Answers');
		}
	    }

	    var statsName = sessionName+'-stats';
	    if (getSheet(statsName)) {
		try {
		    deleteSheet(statsName);
		    updateStats(sessionName);
		} catch(err) {
		    if (interactive)
			notify('Error in updating sheet '+statsName+': '+err, 'Slidoc Stats');
		}
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
	    var lateCol = sessionColIndex['lateToken'];

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
    delCols.sort();
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

