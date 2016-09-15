// slidoc_sheets.js: Google Sheets add-on to interact with Slidoc documents

var AUTH_KEY = 'testkey';   // Set this value for secure administrative access to session index
var VERSION = '0.96.3f';

var SITE_LABEL = '';        // Site label, e.g., 'calc101'
var SITE_URL = '';          // URL of website (if any); e.g., 'http://example.com'

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
//  3. Edit the following parameters in this script (see below):
//       AUTH_KEY  set to your secret key string (also used in the --auth_key=... option)
//       REQUIRE_LOGIN_TOKEN to true, if users need a login token.
//       REQUIRE_LATE_TOKEN to true, if users need a late submission token.
//       (These tokens can be generated using the command sliauth.py)
//
//  4. Run > setup. Click on the right-pointing triangle to its left to run this function.
//     It should show 'Running function setup’ and then put up a dialog 'Authorization Required’.
//     Click on Continue.
//     In the next dialog select 'Review permissions'
//     When you see 'Slidoc would would like to manage spreadsheets ... data ...’ click on Allow.
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
//  There can be zero or more additional rows with special display names starting with a hyphen.
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

var REQUIRE_LOGIN_TOKEN = true;
var REQUIRE_LATE_TOKEN = true;
var SHARE_AVERAGES = false;

// Define document IDs to create/access roster/scores/answers/stats/log sheet in separate documents
// e.g., {roster_slidoc: 'ID1', scores_slidoc: 'ID2', answers_slidoc: 'ID3', stats_slidoc: 'ID4', slidoc_log: 'ID5'}
var ALT_DOC_IDS = { };

var ADMINUSER_ID = 'admin';
var MAXSCORE_ID = '_max_score';
var AVERAGE_ID = '_average';
var TESTUSER_ID = '_test_user';

var MIN_HEADERS = ['name', 'id', 'email', 'altid'];
var TESTUSER_ROSTER = ['-user, -test', TESTUSER_ID, '', ''];

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
var PARTIAL_SUBMIT = 'partial';

var TRUNCATE_DIGEST = 8;
var DIGEST_ALGORITHM = Utilities.DigestAlgorithm.MD5;
var HMAC_ALGORITHM   = Utilities.MacAlgorithm.HMAC_MD5;

var PLUGIN_RE = /^(.*)=\s*(\w+)\.(expect|response)\(\s*\)$/;
var QFIELD_RE = /^q(\d+)_([a-z]+)$/;

var SCRIPT_PROP = PropertiesService.getScriptProperties(); // new property service

// The onOpen function is executed automatically every time a Spreadsheet is loaded
function onOpen() {
   var ss = SpreadsheetApp.getActiveSpreadsheet();
   var menuEntries = [];
   menuEntries.push({name: "Display session answers", functionName: "sessionAnswerSheet"});
   menuEntries.push({name: "Display session statistics", functionName: "sessionStatSheet"});
   menuEntries.push(null); // line separator
   menuEntries.push({name: "Update scores for all sessions", functionName: "updateScoreSheet"});
   menuEntries.push(null); // line separator
   menuEntries.push({name: "Email authentication tokens", functionName: "emailTokens"});
   menuEntries.push({name: "Email late token", functionName: "emailLateToken"});

   ss.addMenu("Slidoc", menuEntries);
}

function setup() {
    var doc = SpreadsheetApp.getActiveSpreadsheet();
    SCRIPT_PROP.setProperty("key", doc.getId());
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
    // sheet: 'sheet name' (required)
    // admin: admin user name (optional)
    // token: authentication token
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
    // create: 1 to create and initialize non-existent rows (for get/put)
    // late: lateToken (set when creating row)
    // Can add row with fewer columns than already present.
    // This allows user to add additional columns without affecting script actions.
    // (User added columns are returned on gets and selective updates, but not row updates.)
    
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
	var adminUser = '';
	var paramId = params.id || '';

	if (params.admin) {
	    if (!params.token)
		throw('Error:NEED_ADMIN_TOKEN:Need token for admin authentication');
	    if (!validateHMAC('admin:'+params.admin+':'+params.token, AUTH_KEY))
		throw("Error:INVALID_ADMIN_TOKEN:Invalid token for authenticating admin user '"+params.admin+"'");
	    adminUser = params.admin;
	} else if (REQUIRE_LOGIN_TOKEN) {
	    if (!paramId)
		throw('Error:NEED_ID:Need id for authentication');
	    if (!params.token)
		throw('Error:NEED_TOKEN:Need token for id authentication');
	    if (!validateHMAC('id:'+paramId+':'+params.token, AUTH_KEY))
		throw("Error:INVALID_TOKEN:Invalid token for authenticating id '"+paramId+"'");
	}

	var proxy = params.proxy || '';
	var sheetName = params.sheet || '';
	if (!proxy && !sheetName)
	    throw('Error:SHEETNAME:No sheet name specified');

	var protectedSheet = (sheetName == SCORES_SHEET);
	var restrictedSheet = (sheetName.slice(-7) == '_slidoc') && !protectedSheet;
	var loggingSheet = (sheetName.slice(-4) == '_log');
	var sessionEntries = null;
	var sessionAttributes = null;
	var paceLevel = null;
	var adminPaced = null;
	var dueDate = null;
	var gradeDate = null;
	var voteDate = null;
	var curDate = new Date();

	if (proxy && !adminUser)
	    throw("Error::Must be admin user for proxy access to sheet '"+sheetName+"'");
	if (restrictedSheet && !adminUser)
	    throw("Error::Must be admin user to access restricted sheet '"+sheetName+"'");

	var rosterValues = [];
	var rosterSheet = getSheet(ROSTER_SHEET);
	if (rosterSheet && !adminUser) {
	    // Check user access
	    if (!paramId)
		throw('Error:NEED_ID:Must specify userID to lookup roster')
	    try {
		// Copy user info from roster
		if (paramId == TESTUSER_ID)
                    rosterValues = TESTUSER_ROSTER;
		else
		    rosterValues = lookupValues(paramId, MIN_HEADERS, ROSTER_SHEET, true);
	    } catch(err) {
		throw("Error:NEED_ROSTER_ENTRY:userID '"+paramId+"' not found in roster");
	    }
	}

	returnInfo.prevTimestamp = null;
	returnInfo.timestamp = null;

	if (proxy && params.get && params.all) {
	    // Return all sheet values to proxy
	    var modSheet = getSheet(sheetName);
	    if (!modSheet)
		throw("Error:NOSHEET:Sheet '"+sheetName+"' not found");
	    returnValues = modSheet.getSheetValues(1, 1, modSheet.getLastRow(), modSheet.getLastColumn());

	} else if (proxy && params.allupdates) {
	    // Update multiple sheets from proxy
	    returnValues = [];
	    var data = JSON.parse(params.data);
	    for (var j=0; j<data.length; j++) {
		var updateSheetName = data[j][0];
		var updateHeaders = data[j][1];
		var updateKeys = data[j][2];
		var updateRows = data[j][3];
		//returnMessages.push('Debug::updateSheet, keys, rows: '+updateSheetName+', '+updateKeys+', '+updateRows.length);

		var updateSheet = getSheet(updateSheetName);
		if (!updateSheet) {
		    if (params.create)
			updateSheet = createSheet(updateSheetName, updateHeaders);
		    else
			throw("Error::Sheet not found: '"+updateSheetName+"'");
		}

		var temHeaders = updateSheet.getSheetValues(1, 1, 1, updateSheet.getLastColumn())[0];
		if (updateHeaders.length > temHeaders.length)
		    throw("Error::Number of headers exceeds that present in sheet '"+updateSheetName+"'; delete it or edit headers.");
		for (var m=0; m<updateHeaders.length; m++) {
		    if (updateHeaders[m] != temHeaders[m])
			throw("Error::Column header mismatch: Expected "+updateHeaders[m]+" but found "+temHeaders[m]+" in sheet '"+updateSheetName+"'");
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
			throw("Error::Sheet has no data rows '"+updateSheetName+"'");

		    var updateColumnIndex = indexColumns(updateSheet);
		    var idCol = updateColumnIndex['id'];
		    var nameCol = updateColumnIndex['name'] || idCol;

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
			    if (!(keys[rowNum-2][0] in updateKeys))
				updateSheet.deleteRow(rowNum);
			}
			var idValues = updateSheet.getSheetValues(1+updateStickyRows, idCol, updateSheet.getLastRow()-updateStickyRows, 1);
			var nameValues = updateSheet.getSheetValues(1+updateStickyRows, nameCol, updateSheet.getLastRow()-updateStickyRows, 1);
		    } else {
			var idValues = [];
			var nameValues = [];
		    }
		    var temIndexRow = indexRows(updateSheet, idCol, updateStickyRows+1);

		    for (var k=0; k<updateRows.length; k++) {
			// Update rows with pre-existing or new keys
			var rowId = updateRows[k][0];
			var rowVals = updateRows[k][1];
			var modRow = temIndexRow[rowId];
			if (!modRow) {
			    if (rowId == MAXSCORE_ID) {
				modRow = updateStickyRows+1;
			    } else if (rowId == TESTUSER_ID) {
				// Test user always appears after max score
				modRow = temIndexRow[MAXSCORE_ID] ? temIndexRow[MAXSCORE_ID]+1 : updateStickyRows+1;
			    } else {
				modRow = updateStickyRows + locateNewRow(rowVals[nameCol-1], rowId, nameValues, idValues, TESTUSER_ID);
			    }
			    updateSheet.insertRowBefore(modRow);
			}
			for (var m=0; m<rowVals.length; m++)
			    rowVals[m] = parseInput(rowVals[m], updateHeaders[m]);

			updateSheet.getRange(modRow, 1, 1, rowVals.length).setValues([rowVals]);
			//returnMessages.push('Debug::updateRow: '+modRow+', '+rowVals);
		    }
		}
	    }
	} else {
	    // Update/access single sheet

	    if (!restrictedSheet && !protectedSheet && !loggingSheet && getSheet(INDEX_SHEET)) {
		// Indexed session
		sessionEntries = lookupValues(sheetName, ['dueDate', 'gradeDate', 'paceLevel', 'adminPaced', 'otherWeight', 'fieldsMin', 'attributes'], INDEX_SHEET);
		sessionAttributes = JSON.parse(sessionEntries.attributes);
		paceLevel = sessionEntries.paceLevel;
		adminPaced = sessionEntries.adminPaced;
		dueDate = sessionEntries.dueDate;
		gradeDate = sessionEntries.gradeDate;
		voteDate = sessionAttributes.params.plugin_share_voteDate ? createDate(sessionAttributes.params.plugin_share_voteDate) : null;
	    }

	    // Check parameter consistency
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
	    
	    var columnHeaders = modSheet.getSheetValues(1, 1, 1, modSheet.getLastColumn())[0];
	    var columnIndex = indexColumns(modSheet);
	    
	    if (headers) {
		if (headers.length > columnHeaders.length)
		    throw("Error::Number of headers exceeds that present in sheet '"+sheetName+"'; delete it or edit headers.");
		for (var j=0; j<headers.length; j++) {
		    if (headers[j] != columnHeaders[j])
			throw("Error::Column header mismatch: Expected "+headers[j]+" but found "+columnHeaders[j]+" in sheet '"+sheetName+"'; delete it or edit headers.");
		}
	    }
	    
	    var getRow = params.get || '';
	    var getShare = params.getshare || '';
	    var allRows = params.all || '';
	    var createRow = params.create || '';
	    var nooverwriteRow = params.nooverwrite || '';
	    var delRow = params.delrow || '';
	    
	    var selectedUpdates = params.update ? JSON.parse(params.update) : null;
	    var rowUpdates = params.row ? JSON.parse(params.row) : null;

	    var userId = null;
	    var displayName = null;

	    var voteSubmission = '';
	    if (!rowUpdates && selectedUpdates && selectedUpdates.length == 2 && selectedUpdates[0][0] == 'id' && selectedUpdates[1][0].match(/_vote$/) && sessionAttributes.shareAnswers) {
		var qno = selectedUpdates[1][0].split('_')[0];
		voteSubmission = sessionAttributes.shareAnswers[qno] ? (sessionAttributes.shareAnswers[qno].share||'') : '';
	    }

	    if (!adminUser && selectedUpdates && !voteSubmission)
		throw("Error::Only admin user allowed to make selected updates to sheet '"+sheetName+"'");

	    if (protectedSheet && (rowUpdates || selectedUpdates) )
		throw("Error::Cannot modify protected sheet '"+sheetName+"'")

	    var numStickyRows = 1;  // Headers etc.

	    if (getRow && params.getheaders) {
		returnHeaders = columnHeaders;
		try {
		    var temIndexRow = indexRows(modSheet, indexColumns(modSheet)['id'], 2);
		    if (temIndexRow[MAXSCORE_ID])
			returnInfo.maxScores = modSheet.getSheetValues(temIndexRow[MAXSCORE_ID], 1, 1, columnHeaders.length)[0];
		    if (SHARE_AVERAGES && temIndexRow[AVERAGE_ID])
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
            var delRowCOl = lookupRowIndex(paramId, modSheet, 2);
            if (delRowCOl)
                modSheet.deleteRow(delRowCOl);
            returnValues = [];
	} else if (!rowUpdates && !selectedUpdates && !getRow && !getShare) {
	    // No row updates/gets
	    returnValues = [];
	} else if (getRow && allRows) {
	    // Get all rows and columns
	    if (modSheet.getLastRow() > numStickyRows)
		returnValues = modSheet.getSheetValues(1+numStickyRows, 1, modSheet.getLastRow()-numStickyRows, columnHeaders.length);
	    else
		returnValues = [];
	    if (sessionEntries && adminPaced)
                returnInfo['adminPaced'] = adminPaced;
	} else if (getShare) {
	    // Return adjacent columns (if permitted by session index and corresponding user entry is non-null)
	    if (!sessionAttributes || !sessionAttributes.shareAnswers)
		throw('Error::Denied access to answers of session '+sheetName);
	    var shareParams = sessionAttributes.shareAnswers[getShare];
	    if (!shareParams || !shareParams.share)
		throw('Error::Sharing not enabled for '+getShare+' of session '+sheetName);

	    if (shareParams.vote && voteDate)
		returnInfo.voteDate = voteDate;

	    if (!adminUser && shareParams.share == 'after_grading' && !gradeDate) {
		returnMessages.push("Warning:SHARE_AFTER_GRADING:");
		returnValues = [];
	    } else if (!adminUser && shareParams.share == 'after_due_date' && (!dueDate || dueDate.getTime() > curDate.getTime())) {
		returnMessages.push("Warning:SHARE_AFTER_DUE_DATE:");
		returnValues = [];
	    } else if (modSheet.getLastRow() <= numStickyRows) {
		returnMessages.push("Warning:SHARE_NO_ROWS:");
		returnValues = [];
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

		var idValues     = modSheet.getSheetValues(1+numStickyRows, columnIndex['id'], nRows, 1)
		var timeValues   = modSheet.getSheetValues(1+numStickyRows, columnIndex['Timestamp'], nRows, 1);
		var submitValues = modSheet.getSheetValues(1+numStickyRows, columnIndex['submitTimestamp'], nRows, 1);
		var lateValues   = modSheet.getSheetValues(1+numStickyRows, columnIndex['lateToken'], nRows, 1);

                var curUserVals = null;
                var testUserVals = null;
                for (var j=0; j<nRows; j++) {
                    if (idValues[j][0] == paramId)
                        curUserVals = shareSubrow[j];
                    else if (idValues[j][0] == TESTUSER_ID)
                        testUserVals = shareSubrow[j];
		}
                if (!curUserVals && !adminUser)
                    throw('Error::Sheet has no row for user '+paramId+' to share in session '+sheetName);

                if (adminUser || paramId == TESTUSER_ID) {
                    returnInfo.responders = [];
                    for (var j=0; j<nRows; j++) {
                        if (shareSubrow[j][0] && idValues[j][0] != TESTUSER_ID)
                            returnInfo.responders.push(idValues[j][0]);
		    }
                    returnInfo.responders.sort();
		}

		var votingCompleted = voteDate && voteDate.getTime() < curDate.getTime();
		var voteParam = shareParams.vote;
		var tallyVotes = voteParam && (adminUser || voteParam == 'show_live' || (voteParam == 'show_completed' && votingCompleted));

		var userResponded = curUserVals && curUserVals[0] && (!explainOffset || curUserVals[explainOffset]);

                if (!adminUser && paramId != TESTUSER_ID && shareParams['share'] == 'after_answering') {
		    if (!userResponded)
			throw('Error::User '+paramId+' must respond to question '+getShare+' before sharing in session '+sheetName);
		    if (paceLevel == ADMIN_PACE && (!testUserVals || !testUserVals[0]))
			throw('Error::Instructor must respond to question '+getShare+' before sharing in session '+sheetName);
		}
		var disableVoting = false;

		// If test/admin user, or current user has provided no response/no explanation, disallow voting
		if (paramId == TESTUSER_ID || !userResponded)
		    disableVoting = true;

		// If voting not enabled or voting completed, disallow  voting.
		if (!voteParam || votingCompleted)
		    disableVoting = true;

		if (voteOffset) {
		    // Return user's vote codes
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

		if (shareOffset) {
		    if (curUserVals) {
			returnInfo.share = disableVoting ? '' : curUserVals[shareOffset];
			// Disable self voting
			curUserVals[shareOffset] = '';
		    }
		    if (disableVoting) {
			// This needs to be done after vote tallying, because vote codes are cleared
			for (var j=0; j<nRows; j++)
			    shareSubrow[j][shareOffset] = '';
		    }
		}

                var sortVotes = tallyVotes && (votingCompleted || adminUser || (voteParam == 'show_live' && paramId == TESTUSER_ID));
                var respCount = {};
		var sortVals = [];
		for (var j=0; j<nRows; j++) {
                    if (idValues[j][0] == TESTUSER_ID) {
                        // Ignore test user response
                        continue
                    }
		    // Use earlier of submit time or timestamp to sort
		    var timeVal = submitValues[j][0] || timeValues[j][0];
		    timeVal = timeVal ? timeVal.getTime() : 0;

		    // Skip incomplete/late submissions (but allow partials)
		    if (!timeVal || (lateValues[j][0] && lateValues[j][0] != PARTIAL_SUBMIT))
			continue;
		    if (!shareSubrow[j][0] || (explainOffset && !shareSubrow[j][1]))
			continue;

                    var respVal = shareSubrow[j][0];
                    if (respVal in respCount) {
                        respCount[respVal] += 1;
                    } else {
                        respCount[respVal] = 1;
                    }
                    if (parseNumber(respVal) != null) {
                        var respSort = parseNumber(respVal);
                    } else {
                        var respSort = respVal;
                    }

                    if (sortVotes) {
                        // Sort by (-) vote tally && then by response
                        sortVals.push( [-shareSubrow[j][voteOffset], respSort, j])
                    } else if (explainOffset) {
                        // Sort by response value && then time
                        sortVals.push( [respSort, timeVal, j] )
                    } else {
                        // Sort by time && then response value
                        sortVals.push( [timeVal, respSort, j])
                    }
		}
		sortVals.sort();

		//returnMessages.push('Debug::getShare: '+nCols+', '+nRows+', ['+curUserVals+']');
		returnValues = [];
		for (var j=0; j<sortVals.length; j++) {
		    var subrow = shareSubrow[sortVals[j][2]];
		    if (!(subrow[0] in respCount))
                        continue;
		    if (respCount[subrow[0]] > 1) {
                        // Response occurs multiple times
                        var newSubrow = [subrow[0]+' ('+respCount[subrow[0]]+')'].concat(subrow.slice(1));
                    } else {
			var newSubrow = subrow;
		    }
                    delete respCount[subrow[0]];
                    returnValues.push( newSubrow );
		}
	    }
	} else {
	    if (rowUpdates && selectedUpdates) {
		throw('Error::Cannot specify both rowUpdates and selectedUpdates');
	    } else if (rowUpdates) {
		if (rowUpdates.length > columnHeaders.length)
		    throw("Error::row_headers length exceeds no. of columns in sheet '"+sheetName+"'; delete it or edit headers.");

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

	    if (adminUser && !restrictedSheet && newRow && userId != MAXSCORE_ID)
		throw("Error::Admin user not allowed to create new row in sheet '"+sheetName+"'");

	    if (newRow && !rowUpdates && createRow) {
		// Initialize new row
		if (sessionEntries) {
		    rowUpdates = createSessionRow(sheetName, sessionEntries.fieldsMin, sessionAttributes.params,
						  userId, params.name, params.email, params.altid);
		    displayName = rowUpdates[columnIndex['name']-1] || '';
		    if (params.late && columnIndex['lateToken'])
			rowUpdates[columnIndex['lateToken']-1] = params.late;
		} else {
		    rowUpdates = [];
		    for (var j=0; j<columnHeaders.length; j++)
			rowUpdates[j] = null;
		}
	    }

	    if (newRow && getRow && !rowUpdates) {
		// Row does not exist; return empty list
		returnValues = [];

	    } else if (newRow && selectedUpdates) {
		throw('Error::Selected updates cannot be applied to new row');
	    } else {
		var pastSubmitDeadline = false;
		var partialSubmission = false;
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

		    if (dueDate && !prevSubmitted && !voteSubmission) {
			// Check if past submission deadline
			var lateTokenCol = columnIndex['lateToken'];
			var lateToken = null;
			var lateDueDate = null;
			if (lateTokenCol) {
			    lateToken = (rowUpdates && rowUpdates.length >= lateTokenCol) ? (rowUpdates[lateTokenCol-1] || null) : null;
			    if (!lateToken && !newRow)
				lateToken = modSheet.getRange(userRow, lateTokenCol, 1, 1).getValues()[0][0] || null;
			    if (lateToken && lateToken.indexOf(':') > 0) {
				var comps = splitToken(lateToken);
				var dateStr = comps[0];
				var tokenStr = comps[1];
				if (genLateToken(AUTH_KEY, userId, sheetName, dateStr) == lateToken) {
				    lateDueDate = true;
				    dueDate = createDate(dateStr); // Date format: '1995-12-17T03:24Z'
				} else {
				    returnMessages.push("Warning:INVALID_LATE_TOKEN:Invalid token "+lateToken+" for late submission by user '"+(displayName||"")+"' to session '"+sheetName+"'");
				}
			    }
			}

			returnInfo.dueDate = dueDate; // May have been updated

			var curTime = curDate.getTime();
			pastSubmitDeadline = (dueDate && curTime > dueDate.getTime())
			var allowLateMods = !REQUIRE_LATE_TOKEN || adminUser;
			if (!allowLateMods && pastSubmitDeadline && lateToken) {
			    if (lateToken == PARTIAL_SUBMIT) {
				if (newRow || !rowUpdates)
				    throw("Error::Partial submission only works for pre-existing rows");
                                if (sessionAttributes.params.participationCredit)
                                    throw("Error::Partial submission not allowed for participation credit")

				partialSubmission = true;
				rowUpdates = null;
				selectedUpdates = [ ['Timestamp', null], ['submitTimestamp', null], ['lateToken', lateToken] ];
				returnMessages.push("Warning:PARTIAL_SUBMISSION:Partial submission by user '"+(displayName||"")+"' to session '"+sheetName+"'");
			    } else if (lateToken == LATE_SUBMIT) {
				// Late submission for reduced/no credit
				allowLateMods = true;
			    } else if (!lateDueDate) {
                                // Invalid token
                                returnMessages.push("Warning:INVALID_LATE_TOKEN:Invalid token '"+lateToken+"' for late submission by user '"+(displayName||"")+"' to session '"+sheetName+"'");
			    }
			}
			if (!allowLateMods && !partialSubmission) {
			    if (pastSubmitDeadline) {
				    if (newRow || selectedUpdates || (rowUpdates && !nooverwriteRow)) {
					// Creating/modifying row; require valid lateToken
					if (!lateToken)
					    throw("Error:PAST_SUBMIT_DEADLINE:Past submit deadline ("+dueDate+") for session '"+sheetName+"'.")
					else
					    throw("Error:INVALID_LATE_TOKEN:Invalid token for late submission to session '"+sheetName+"'");
				    } else {
					returnMessages.push("Warning:PAST_SUBMIT_DEADLINE:Past submit deadline ("+dueDate+") for session '"+sheetName+"'. ");
				    }
			    } else if ( (dueDate.getTime() - curTime) < 2*60*60*1000) {
				returnMessages.push("Warning:NEAR_SUBMIT_DEADLINE:Nearing submit deadline ("+dueDate+") for session '"+sheetName+"'.");
			    }
			}
		    }
		}

		if (newRow) {
		    // New user; insert row in sorted order of name (except for log files)
		    if ((userId != MAXSCORE_ID && !displayName) || !rowUpdates)
			throw('Error::User name and row parameters required to create a new row for id '+userId+' in sheet '+sheetName);
                    if (userId == MAXSCORE_ID) {
			userRow = numStickyRows+1;
                    } else if (userId == TESTUSER_ID && !loggingSheet) {
                        // Test user always appears after max score
			var maxScoreRow = lookupRowIndex(MAXSCORE_ID, modSheet, numStickyRows+1);
                        userRow = maxScoreRow ? maxScoreRow+1 : numStickyRows+1
		    } else if (modSheet.getLastRow() > numStickyRows && !loggingSheet) {
			var displayNames = modSheet.getSheetValues(1+numStickyRows, columnIndex['name'], modSheet.getLastRow()-numStickyRows, 1);
			var userIds = modSheet.getSheetValues(1+numStickyRows, columnIndex['id'], modSheet.getLastRow()-numStickyRows, 1);
			userRow = numStickyRows + locateNewRow(displayName, userId, displayNames, userIds, TESTUSER_ID);
		    } else {
			userRow = modSheet.getLastRow()+1;
		    }
		    modSheet.insertRowBefore(userRow);
		} else if (rowUpdates && nooverwriteRow) {
		    if (getRow) {
			// Simply return existing row
			rowUpdates = null;
		    } else {
			throw('Error::Do not specify nooverwrite=1 to overwrite existing rows');
		    }
		}

		var maxCol = rowUpdates ? rowUpdates.length : columnHeaders.length;
		var totalCol = (columnHeaders.length > fieldsMin && columnHeaders[fieldsMin] == 'q_grades') ? fieldsMin+1 : 0;
		var userRange = modSheet.getRange(userRow, 1, 1, maxCol);
		var rowValues = userRange.getValues()[0];

		returnInfo.prevTimestamp = ('Timestamp' in columnIndex && rowValues[columnIndex['Timestamp']-1]) ? rowValues[columnIndex['Timestamp']-1].getTime() : null;
		if (returnInfo.prevTimestamp && params.timestamp && parseNumber(params.timestamp) && returnInfo.prevTimestamp > parseNumber(params.timestamp))
		    throw('Error::Row timestamp too old by '+Math.ceil((returnInfo.prevTimestamp-parseNumber(params.timestamp))/1000)+' seconds. Conflicting modifications from another active browser session?');

		if (rowUpdates) {
		    // Update all non-null and non-id row values
		    // Timestamp is always updated, unless it is specified by admin
		    if (adminUser && sessionEntries && userId != MAXSCORE_ID)
			throw("Error::Admin user not allowed to update full rows in sheet '"+sheetName+"'");

		    if (submitTimestampCol && rowUpdates[submitTimestampCol-1])
			throw("Error::Submitted session cannot be re-submitted for sheet '"+sheetName+"'");

		    if (!adminUser && rowUpdates.length > fieldsMin) {
			// Check if there are any user provided non-null values for "extra" columns (i.e., response/explain values)
			var nonNullExtraColumn = false;
			var totalCells = [];
			var adminColumns = {};
			for (var j=fieldsMin; j < columnHeaders.length; j++) {
			    if (rowUpdates[j] != null)
				nonNullExtraColumn = true;
			    var hmatch = QFIELD_RE.exec(columnHeaders[j]);
			    if (hmatch && hmatch[2] == 'grade') // Grade value to summed
				totalCells.push(colIndexToChar(j+1) + userRow);
			    if (!hmatch || (hmatch[2] != 'response' && hmatch[2] != 'explain')) // Non-response/explain admin column
				adminColumns[columnHeaders[j]] = 1;
			}
			if (nonNullExtraColumn) {
			    // Blank out admin columns if any extra column is non-null
			    // Failsafe: ensures admin-entered grades will be blanked out if response/explain are updated
			    for (var j=fieldsMin; j < columnHeaders.length; j++) {
				if (columnHeaders[j] in adminColumns)
				    rowUpdates[j] = '';
			    }
			}
			if (totalCol && totalCells.length) {
			    // Computed admin column to hold sum of all grades
			    rowUpdates[totalCol-1] = ( '=' + totalCells.join('+') );
			}
			//returnMessages.push("Debug::"+nonNullExtraColumn+Object.keys(adminColumns)+'=' + totalCells.join('+'));
		    }
		    //returnMessages.push("Debug:ROW_UPDATES:"+rowUpdates);
		    for (var j=0; j<rowUpdates.length; j++) {
			var colHeader = columnHeaders[j];
			var colValue = rowUpdates[j];
			if (colHeader == 'Timestamp') {
			    // Timestamp is always updated, unless it is explicitly specified by admin
			    if (adminUser && colValue) {
				try { rowValues[j] = createDate(colValue); } catch (err) {}
			    } else {
				rowValues[j] = curDate;
			    }
			} else if (colHeader == 'initTimestamp' && newRow) {
			    rowValues[j] = curDate;
			} else if (colHeader == 'submitTimestamp' && params.submit) {
			    rowValues[j] = curDate;
			    returnInfo.submitTimestamp = curDate;
			} else if (colHeader.slice(-6) == '_share') {
			    // Generate share value by computing message digest of 'response [: explain]'
			    if (j >= 1 && rowValues[j-1] && columnHeaders[j-1].slice(-9) == '_response') {
				rowValues[j] = digestHex(normalizeText(rowValues[j-1]));
			    } else if (j >= 2 && rowValues[j-1] && columnHeaders[j-1].slice(-8) == '_explain' && columnHeaders[j-2].slice(-9) == '_response') {
				rowValues[j] = digestHex(rowValues[j-1]+': '+normalizeText(rowValues[j-2]));
			    } else {
				rowValues[j] = '';
			    }
			} else if (colValue == null) {
			    // Do not modify field
			} else if (newRow || (MIN_HEADERS.indexOf(colHeader) == -1 && colHeader.slice(-9) != 'Timestamp') ) {
			    // Id, name, email, altid, *Timestamp cannot be updated programmatically
			    // (If necessary to change name manually, then re-sort manually)
			    rowValues[j] = parseInput(colValue, colHeader);
			} else {
			    if (rowValues[j] !== colValue)
				throw("Error::Cannot modify column '"+colHeader+"'. Specify as 'null'");
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
                            setValue(sheetName, 'dueDate', curDate, INDEX_SHEET);
                            var idColValues = getColumns('id', modSheet, 1, 1+numStickyRows);
                            var initColValues = getColumns('initTimestamp', modSheet, 1, 1+numStickyRows);
                            for (var j=0; j < idColValues.length; j++) {
                                // Submit all other users who have started a session
                                if (initColValues[j] && idColValues[j] && idColValues != TESTUSER_ID && idColValues[j] != MAXSCORE_ID) {
                                    setValue(idColValues[j], 'submitTimestamp', curDate, sheetName);
                                }
                            }
                        }
                    }

		} else if (selectedUpdates) {
		    // Update selected row values
		    // Timestamp is updated only if specified in list
		    if (!voteSubmission && !partialSubmission) {
			if (!adminUser)
			    throw("Error::Only admin user allowed to make selected updates to sheet '"+sheetName+"'");

			if (sessionEntries) {
			    // Admin can modify grade columns only for submitted sessions before 'effective' due date
			    // and only for non-late submissions thereafter
			    var allowGrading = prevSubmitted || (pastSubmitDeadline && lateToken != LATE_SUBMIT);
			    if (!allowGrading)
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
				try { modValue = createDate(colValue); } catch (err) {}
			    } else {
				modValue = curDate;
			    }
			} else if (colHeader == 'submitTimestamp') {
			    if (partialSubmission) {
				modValue = curDate;
				returnInfo.submitTimestamp = curDate;
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
			    if (!restrictedSheet && !partialSubmission && (headerColumn <= fieldsMin || !/^q\d+_(comments|grade)$/.exec(colHeader)) )
				throw("Error::Cannot selectively update user-defined column '"+colHeader+"' in sheet '"+sheetName+"'");
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
		
                if ((paramId != TESTUSER_ID || prevSubmitted) && sessionEntries && adminPaced)
                    returnInfo['adminPaced'] = adminPaced;

		// Return updated timestamp
		returnInfo.timestamp = ('Timestamp' in columnIndex) ? rowValues[columnIndex['Timestamp']-1].getTime() : null;
		
		returnValues = getRow ? rowValues : [];

		if (!adminUser && !gradeDate && returnValues.length > fieldsMin) {
		    // If session not graded, nullify columns to be graded
		    for (var j=fieldsMin; j < columnHeaders.length; j++) {
			if (!columnHeaders[j].match(/_response$/) && !columnHeaders[j].match(/_explain$/))
			    returnValues[j] = null;
		    }
		} else if (!adminUser && gradeDate) {
		    returnInfo.gradeDate = gradeDate;
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

function getRandomSeed() {
    return Math.round(Math.random() * Math.pow(2,32));
}

function createSession(sessionName, params) {
    var persistPlugins = {};
    for (var j=0; j<params.plugins.length; j++)
	persistPlugins[params.plugins[j]] = {};

    return {'version': params.sessionVersion,
	    'revision': params.sessionRevision,
	    'paced': params.paceLevel || 0,
	    'submitted': null,
	    'lateToken': '',
	    'lastSlide': 0,
	    'randomSeed': getRandomSeed(),              // Save random seed
            'expiryTime': Date.now() + 180*86400*1000,  // 180 day lifetime
            'startTime': Date.now(),
            'lastTime': 0,
            'lastTries': 0,
            'remainingTries': 0,
            'tryDelay': 0,
	    'showTime': null,
            'questionsAttempted': {},
	    'hintsUsed': {},
	    'plugins': persistPlugins
	   };

}

function createSessionRow(sessionName, fieldsMin, params, userId, displayName, email, altid) {
    var headers = params.sessionFields.concat(params.gradeFields);
    var idCol = headers.indexOf('id') + 1;
    var nameCol = headers.indexOf('name') + 1;
    var emailCol = headers.indexOf('email') + 1;
    var altidCol = headers.indexOf('altid') + 1;
    var session = createSession(sessionName, params);
    var rowVals = [];
    for (var j=0; j<headers.length; j++) {
	var header = headers[j];
	rowVals[j] = null;
	if (!header.match(/_hidden$/) && !header.match(/Timestamp$/)) {
	    if (header in session)
		rowVals[j] = session[header];
	}
    }
    rowVals[headers.indexOf('session_hidden')] = JSON.stringify(session);

    var rosterSheet = getSheet(ROSTER_SHEET);
    if (rosterSheet) {
	var rosterVals = lookupValues(userId, MIN_HEADERS, ROSTER_SHEET, true);
	if (!rosterVals)
	    throw('User ID '+userId+' not found in roster');

	for (var j=0; j<rosterVals.length; j++) {
	    if (rosterVals[j])
		rowVals[j] = rosterVals[j];
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
    var token = genUserToken(AUTH_KEY, userId);
    var getParams = {'id': userId, 'token': token,'sheet': sessionName,
		     'name': displayName, 'get': '1'};
    if (opts) {
	var keys = Object.keys(opts);
	for (var j=0; j<keys.length; j++)
	    getParams[keys[j]] = opts[keys[j]];
    }

    return sheetAction(getParams);
}

////// Utilitye functions

function isNumber(x) { return !!(x+'') && !isNaN(x+''); }

function parseNumber(x) {
    try {
	var retval;
	if (!isNumber(x))
	    return null;
	if (!isNaN(x))
	    return x || 0;
	if (/^[\+\-]?\d+$/.exec()) {
	    retval = parseInt(x);
	} else {
            retval = parseFloat(x);
	}
	return isNaN(retval) ? null : retval;
    } catch(err) {
        return null;
    }
}

function normalizeText(s) {
   // Lowercase, replace '" with null, all other non-alphanumerics with spaces,
   // replace 'a', 'an', 'the' with space, and then normalize spaces
    return s.toLowerCase().replace(/['"]/g,'').replace(/\b(a|an|the) /g, ' ').replace(/[_\W]/g,' ').replace(/\s+/g, ' ').trim();
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
    if (typeof date === 'string' && date.slice(-1) == 'Z') {
	if (date.length == 17)      // yyyy-mm-ddThh:mmZ
	    date = date.slice(0,-1) + ':00.000Z';
	else if (date.length == 20) // yyyy-mm-ddThh:mm:ssZ
	    date = date.slice(0,-1) + '.000Z';
	else if (date.length > 24) // yyyy-mm-ddThh:mm:ss.mmmZ
	    date = date.slice(0,23) + 'Z';
    }
    return new Date(date);
}

function parseInput(value, headerName) {
    // Parse input date strings
    if (value && (headerName.slice(-4).toLowerCase() == 'date' || headerName.slice(-4).toLowerCase() == 'time' || headerName.slice(-9) == 'Timestamp')) {
	try { return createDate(value); } catch (err) { }
    }
    return value;
}


function genHmacToken(key, message) {
    var rawHMAC = Utilities.computeHmacSignature(HMAC_ALGORITHM,
						 message, key,
						 Utilities.Charset.US_ASCII);
    return Utilities.base64Encode(rawHMAC).slice(0,TRUNCATE_DIGEST);
}

function genUserToken(key, userId) {
    // Generates user token using HMAC key
    return genHmacToken(key, 'id:'+userId);
}

function genLateToken(key, userId, sessionName, dateStr) {
    // Use UTC date string of the form '1995-12-17T03:24' (append Z for UTC time)
    if (dateStr.slice(-1) != 'Z') {  // Convert local time to UTC
	var date = createDate(dateStr+'Z');
	// Adjust for local time zone
	date.setTime( date.getTime() + date.getTimezoneOffset()*60*1000 );
	dateStr = date.toISOString().slice(0,16)+'Z';
    }
    return dateStr+':'+genHmacToken(key, 'late:'+userId+':'+sessionName+':'+dateStr);
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
	doc = SpreadsheetApp.openById(SCRIPT_PROP.getProperty("key"));

    var sheet = doc.getSheetByName(sheetName);
    if (!sheet && create)
	sheet = doc.insertSheet(sheetName);
    return sheet;
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
    return String.fromCharCode('A'.charCodeAt(0) + (col-1) );
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

function sessionAnswerSheet() {
    // Create session answers sheet

    var sessionName = getSessionName(true);

    var lock = LockService.getPublicLock();
    lock.waitLock(30000);  // wait 30 seconds before conceding defeat.

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
	var extraCols = ['expect', 'temscore', 'plugin', 'hints'];
	for (var j=0; j<qtypes.length; j++) {
	    var qprefix = 'q'+(j+1);
	    var pluginMatch = PLUGIN_RE.exec(answers[j] || '');
	    var pluginAction = pluginMatch ? pluginMatch[3] : '';
	    var respColName = qprefix;
	    if (answers[j] && pluginAction != 'expect') {
		if (qtypes[j] == 'choice')
		    respColName += '_'+answers[j];
		else if (qtypes[j] == 'number')
		    respColName += '_'+answers[j].replace(' +/- ','_pm_').replace('+/-','_pm_').replace(' ','_');
	    }
	    answerHeaders.push(respColName);
	    respCols.push(answerHeaders.length);
	    if (pluginAction == 'expect')
		answerHeaders.push(qprefix+'_expect');
	    if (answers[j] || pluginAction == 'response')
		answerHeaders.push(qprefix+'_temscore');
	    if (pluginAction == 'response')
		answerHeaders.push(qprefix+'_plugin');
	    if (sessionAttributes.hints && sessionAttributes.hints[qprefix])
		answerHeaders.push(qprefix+'_hints');
	}
	Logger.log('ansHeaders: '+answerHeaders);
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
	    if (answerHeaders[ansCol-1].slice(-9) == '_temscore') {
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
    } finally { //release lock
	lock.releaseLock();
    }

    notify('Created sheet '+answerSheet.getParent().getName()+':'+answerSheetName, 'Slidoc Answers');
}


function sessionStatSheet() {
    // Create session stats sheet

    var sessionName = getSessionName(true);

    var lock = LockService.getPublicLock();
    lock.waitLock(30000);  // wait 30 seconds before conceding defeat.

    try {
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
		// Skip any initial row(s) in the roster with test user or IDs/names starting with hyphen
		// when computing averages and other stats
		if (temIds[j][0] == TESTUSER_ID || temIds[j][0].match(/^\-/) || temNames[j][0].match(/^\-/))
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
	    var scores = tallyScores(questions, savedSession.questionsAttempted, savedSession.hintsUsed, sessionAttributes.params);

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
    } finally { //release lock
	lock.releaseLock();
    }

    notify('Created sheet '+statSheet.getParent().getName()+':'+statSheetName, 'Slidoc Stats');
}

function createQuestionAttempted(response, explain) {
    // response field should always be present, non-null for attempted questions
    var qAttempted = {response: response||''};
    if (explain)
	qAttempted.explain = explain;
    return qAttempted;
}

function unpackSession(headers, row) {
    // Unpacks hidden session object and adds response/explain fields from sheet row, as needed
    var session_hidden = row[headers.indexOf('session_hidden')];
    if (!session_hidden)
	return null;
    if (session_hidden.charAt(0) != '{')
	session_hidden = Utilities.newBlob(Utilities.base64Decode(session_hidden)).getDataAsString();
    var session = JSON.parse(session_hidden);

    for (var j=0; j<headers.length; j++) {
	var header = headers[j];
	if (header == 'lateToken')
	    session.lateToken = row[j];
	else if (header == 'lastSlide')
	    session.lastSlide = row[j];
	else if (row[j]) {
	    var hmatch = QFIELD_RE.exec(header);
	    if (hmatch && (hmatch[2] == 'response' || hmatch[2] == 'explain')) {
		// Copy only response/explain field to session
		var qnumber = parseInt(hmatch[1]);
		if (!(qnumber in session.questionsAttempted))
		    session.questionsAttempted[qnumber] = createQuestionAttempted();
		session.questionsAttempted[qnumber][hmatch[2]] = row[j];
	    }
	}
    }
    return session;
}

function scoreAnswer(response, qtype, corrAnswer) {
    // Handle answer types: choice, number, text

    if (!corrAnswer)
        return null;

    if (response == SKIP_ANSWER)
	return 0;

    var respValue = null;
    var qscore = null;

    // Check response against correct answer
    var qscore = 0;
    if (qtype == 'number') {
        // Check if numeric answer is correct
        var corrValue = null;
        var corrError = 0.0;
        var comps = corrAnswer.split('+/-');
        var corrValue = parseNumber(comps[0]);
        if (corrValue == null) {
            qscore = null;
            throw('Slidoc.scoreAnswer: Error in correct numeric answer:'+comps[0]);
        }
        if (comps.length > 1) {
            corrError = parseNumber(comps[1]);
            if (corrError == null) {
                qscore = null;
                throw('Slidoc.scoreAnswer: Error in correct numeric error:'+comps[1])
            }
        }
        respValue = parseNumber(response);

        if (respValue != null && corrValue != null && corrError != null) {
            qscore = (Math.abs(respValue-corrValue) <= 1.001*corrError) ? 1 : 0;
        }
    } else {
        // Check if non-numeric answer is correct (all spaces are removed before comparison)
        var normResp = response.trim().toLowerCase();
	// For choice, allow multiple correct answers (to fix grading problems)
        var correctOptions = corrAnswer.split( (qtype == 'choice') ? '' : ' OR ');
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

function tallyScores(questions, questionsAttempted, hintsUsed, params) {
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
        var slideNum = questionAttrs['slide'];
        if (!qAttempted || slideNum < skipToSlide) {
            // Unattempted || skipped
            qscores.push(null);
            continue;
        }

	if (qAttempted.pluginResp)
	    var qscore = parseNumber(qAttempted.pluginResp.score);
	else
            var qscore = scoreAnswer(qAttempted.response, questionAttrs.qtype,
			 	     (qAttempted.expect || questionAttrs.correct || ''));

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

        lastSkipRef = ''
        if (correctSequence && params.paceLevel == QUESTION_PACE) {
            skip = questionAttrs.skip;
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
        questionsSkipped += qSkipCount
        questionsCount += 1 + qSkipCount
        weightedCount += qWeight + qSkipWeight

        var effectiveScore = (parseNumber(qscore) != null) ? qscore : 1;   // Give full credit to unscored answers

        if (params.participationCredit) {
            // Full participation credit simply for attempting question (lateCredit applied in sheet)
            effectiveScore = 1;

        } else if (hintsUsed[qnumber] && questionAttrs.hints && questionAttrs.hints.length) {
	    if (hintsUsed[qnumber] > questionAttrs.hints.length)
		alert('Internal Error: Inconsistent hint count');
	    for (var j=0; j<hintsUsed[qnumber]; j++)
		effectiveScore -= Math.abs(questionAttrs.hints[j]);
	}

        if (effectiveScore > 0) {
            questionsCorrect += 1 + qSkipCount;
            weightedCorrect += effectiveScore*qWeight + qSkipWeight;
        }
    }

    return { questionsCount: questionsCount, weightedCount: weightedCount,
             questionsCorrect: questionsCorrect, weightedCorrect: weightedCorrect,
             questionsSkipped: questionsSkipped, correctSequence: correctSequence, skipToSlide: skipToSlide,
             correctSequence: correctSequence, lastSkipRef: lastSkipRef, qscores: qscores};
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
	if (qscores[qnumber-1] === null || !qConcepts.length)
	    continue;
	var missed = qscores[qnumber-1] < 1;

	var primaryOffset = 1;
	for (var j=0;j<qConcepts.length;j++) {
            if (!qConcepts[j].trim()) {
		primaryOffset = j;
		break;
            }
	}

	for (var j=0;j<qConcepts.length;j++) {
            if (!qConcepts[j].trim()) {
		continue;
            }
            var m = (j < primaryOffset) ? 0 : 1;   // Primary/secondary concept
            for (var k=0; k < allQuestionConcepts[m].length; k++) {
		if (qConcepts[j] == allQuestionConcepts[m][k]) {
                    if (missed)
			missedConcepts[m][k][0] += 1;    // Missed count
                    missedConcepts[m][k][1] += 1;        // Attempted count
		}
	    }
	}
    }
    return missedConcepts;
}

function emailTokens() {
    // Send authentication tokens
    var doc = SpreadsheetApp.openById(SCRIPT_PROP.getProperty("key"));
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
    if (SITE_LABEL)
	subject = 'Authentication token for '+SITE_LABEL;
    else
	subject = 'Slidoc authentication token';

    var emails = [];
    for (var j=0; j<emailList.length; j++) {
	if (!emailList[j][1].trim())
	    continue;
	var username = emailList[j][0];
	var token = genUserToken(AUTH_KEY, emailList[j][0]);

	var message = 'Authentication token for userID '+username+' is '+token;
	if (SITE_URL)
	    message += "\n\nAuthenticated link to website: "+SITE_URL+"/_auth/login/?username="+encodeURIComponent(username)+"&token="+encodeURIComponent(token);
	message += "\n\nRetain this email for future use, or save userID and token in a secure location. Do not share token with anyone else.";

	MailApp.sendEmail(emailList[j][1], subject, message);
	emails.push(emailList[j][1]);
    }

    notify('Emailed '+emails.length+' token(s) to '+emails.join(', '));
}


function emailLateToken() {
    // Send late token
    var doc = SpreadsheetApp.openById(SCRIPT_PROP.getProperty("key"));
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

    var numStickyRows = 1;
    var userRow = lookupRowIndex(userId, sessionSheet, numStickyRows+1);
    if (!userRow) {
	var retval = getUserRow(sessionName, userId, displayName, {'create': '1'});
	if (retval.result != 'success')
	    throw('Error in creating session for user '+userId+': '+retval.error);
	userRow = lookupRowIndex(userId, sessionSheet, numStickyRows+1);
    }

    var dateStr = getPrompt('New submission date/time', "'yyyy-mm-ddTmm:hh' (or 'yyyy-mm-dd', implying 'T23:59')");
    if (!dateStr)
	return;
    if (dateStr.indexOf('T') < 0)
	dateStr += 'T23:59';

    var token = genLateToken(AUTH_KEY, userId, sessionName, dateStr);
    sessionSheet.getRange(userRow, indexColumns(sessionSheet)['lateToken'], 1, 1).setValue(token);

    var note = 'Late submission on '+dateStr+' authorized for user '+userId+'.';
    if (email && email.indexOf('@') > 0) {
	var subject;
	if (SITE_LABEL)
	    subject = 'Late submission allowed for '+SITE_LABEL;
	else
	    subject = 'Late submission for '+sessionName;

	var message = 'Late submission allowed for userID '+userId+' in session '+sessionName+'. New due date is  '+dateStr;
	MailApp.sendEmail(email, subject, message);

	note += ' Emailed notification to '+email;
    }
    notify(note);
}

function updateScoreSheet() {
    // Update scores sheet

    var lock = LockService.getPublicLock();
    lock.waitLock(30000);  // wait 30 seconds before conceding defeat.

    try {
	var indexSheet = getSheet(INDEX_SHEET);
	if (!indexSheet) {
	    SpreadsheetApp.getUi().alert('Sheet not found: '+INDEX_SHEET);
	}
	var sessionNames = getColumns('id', indexSheet);
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

	var rosterStartRow = ROSTER_START_ROW;
	var sessionStartRow = SESSION_START_ROW;
	var scoreStartRow = 3;
	var scoreAvgRow = (scoreStartRow > 2) ? scoreStartRow-1 : 0;
	var nonmaxStartRow = SESSION_MAXSCORE_ROW ? scoreStartRow+1 : scoreStartRow;
	var avgStartRow = nonmaxStartRow;

	// New score sheet
	var extraHeaders = ['weightedTotal', 'rawTotal', 'sessionCount'];
	var scoreHeaders = MIN_HEADERS.concat(extraHeaders);
	var scoreSheetName = SCORES_SHEET;
	scoreSheet = getSheet(scoreSheetName);
	if (!scoreSheet) {
	    // Create session score sheet
	    scoreSheet = getSheet(scoreSheetName, null, true);
	    // Copy user info from roster
	    var userInfoSheet = getSheet(ROSTER_SHEET);
	    var startRow = rosterStartRow;
	    if (!userInfoSheet)  {              // Copy user info from last valid session
		userInfoSheet = validSheet;
		startRow = sessionStartRow;
	    }

	    // Score sheet headers
	    scoreSheet.getRange(1, 1, 1, MIN_HEADERS.length).setValues(userInfoSheet.getSheetValues(1, 1, 1, MIN_HEADERS.length));
	    scoreSheet.getRange(1, MIN_HEADERS.length+1, 1, extraHeaders.length).setValues([extraHeaders]);
	    scoreSheet.getRange('1:1').setFontWeight('bold');

	    var idCol = MIN_HEADERS.indexOf('id')+1;
	    if (scoreAvgRow) {
		scoreSheet.getRange(scoreAvgRow, idCol, 1, 1).setValues([[AVERAGE_ID]]);
		scoreSheet.getRange(scoreAvgRow+':'+scoreAvgRow).setFontStyle('italic');
	    }

	    if (SESSION_MAXSCORE_ROW) {
		scoreSheet.getRange(scoreStartRow, idCol, 1, 1).setValues([[MAXSCORE_ID]]);
		scoreSheet.getRange(scoreStartRow+':'+scoreStartRow).setFontWeight('bold');
	    }

	    var nUserIds = userInfoSheet.getLastRow()-startRow+1;
	    var nPrevIds = scoreSheet.getLastRow()-nonmaxStartRow+1;
	    if (nUserIds) {
		var temIds = userInfoSheet.getSheetValues(startRow, idCol, nUserIds, 1);
		var temNames = userInfoSheet.getSheetValues(startRow, MIN_HEADERS.indexOf('name')+1, nUserIds, 1);
		for (var j=0; j<nUserIds; j++) {
		    // Skip any initial row(s) in the roster with test user or IDs/names starting with hyphen
		    // when computing averages and other stats
		    if (temIds[j][0] == TESTUSER_ID || temIds[j][0].match(/^\-/) || temNames[j][0].match(/^\-/))
			avgStartRow += 1;
		    else
			break;
		}

		for (var j=0; j<nUserIds; j++) {
		    // Check that prior IDs match
		    var prevId = scoreSheet.getRange(nonmaxStartRow+j, idCol, 1, 1)[0][0];
		    if (prevId && prevId != temIds[j][0])
			throw('Id mismatch in row '+(nonmaxStartRow+j)+' of score sheet: expected '+temIds[j][0]+' but found '+prevId+'; fix it or re-create score sheet');
		}

		scoreSheet.getRange(nonmaxStartRow, 1, nUserIds, MIN_HEADERS.length).setValues(userInfoSheet.getSheetValues(startRow, 1, nUserIds, MIN_HEADERS.length));

		// Clear any 'excess' prior ID values
		for (var j=nUserIds; j<nPrevIds; j++)
		    scoreSheet.getRange(nonmaxStartRow+j, idCol, 1, 1).setValue('');
	    }
	}

	var rawTotal = [];
	var sessionCount = [];
	var weightedTotal = [];
	var updatedNames = [];
	for (var m=0; m<validNames.length; m++) {
	    var sessionName = validNames[m];
	    var sessionSheet = getSheet(sessionName);
	    var sessionColIndex = indexColumns(sessionSheet);
	    var sessionRowIndex = indexRows(sessionSheet, sessionColIndex['id'], 2);
	    var sessionColHeaders = sessionSheet.getSheetValues(1, 1, 1, sessionSheet.getLastColumn())[0];

	    var sessionEntries = lookupValues(sessionName, ['gradeDate', 'sessionWeight', 'scoreWeight', 'gradeWeight', 'otherWeight', 'attributes', 'questions'], INDEX_SHEET);
            var sessionAttributes = JSON.parse(sessionEntries.attributes);
	    var questions = JSON.parse(sessionEntries.questions);
	    var gradeDate = parseNumber(sessionEntries.gradeDate) || null;
	    var sessionWeight = parseNumber(sessionEntries.sessionWeight) || 0;
	    var scoreWeight = parseNumber(sessionEntries.scoreWeight) || 0;
	    var gradeWeight = parseNumber(sessionEntries.gradeWeight) || 0;
	    var otherWeight = parseNumber(sessionEntries.otherWeight) || 0;

	    if (gradeWeight && !gradeDate)   // Wait for session to be graded
		continue;
	    updatedNames.push(sessionName);

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
			if (sessionName < colHeader.slice(1)) {
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
		scoreSheet.getRange(c+'2:'+c).setNumberFormat('0.##');
	    }

	    var colChar = colIndexToChar( scoreSessionCol );
	    rawTotal.push(colChar+'@');
	    sessionCount.push('IF('+colChar+'@="",0,1)');
	    if (sessionWeight)
		weightedTotal.push(sessionWeight+'*'+colChar+'@');

	    var sessionIdCol = sessionColIndex['id'];
	    var sessionIdColChar = colIndexToChar( sessionIdCol );

	    var scoreIdCol = scoreColIndex['id'];
	    var scoreIdColChar = colIndexToChar( scoreIdCol );

	    var nids = scoreSheet.getLastRow()-scoreStartRow+1;
	    var scoreIdVals = scoreSheet.getSheetValues(scoreStartRow, scoreIdCol, nids, 1);

	    var lookupStartRow = SESSION_MAXSCORE_ROW ? sessionStartRow-1 : sessionStartRow;
	    function vlookup(colName, scoreRowIndex) {
		var nameCol = sessionColIndex[colName];
		var nameColChar = colIndexToChar( nameCol );
		var sessionRange = "'"+sessionName+"'!$"+sessionIdColChar+"$"+lookupStartRow+":$"+nameColChar;
		return 'VLOOKUP($'+scoreIdColChar+scoreRowIndex+', ' + sessionRange + ', '+(nameCol-sessionIdCol+1)+', false)';
	    }

	    var scoreFormulas = [];
	    for (var j=0; j<nids; j++) {
		var lookups = [];
		if (scoreWeight) {
		    // Tally scores
		    var rowId = scoreIdVals[j];
		    if (rowId == MAXSCORE_ID) {
			lookups.push( scoreWeight );
		    } else {
			var rowValues = sessionSheet.getSheetValues(sessionRowIndex[rowId], 1, 1, sessionColHeaders.length)[0];
			var savedSession = unpackSession(sessionColHeaders, rowValues);
			if (savedSession) {
			    var scores = tallyScores(questions, savedSession.questionsAttempted, savedSession.hintsUsed, sessionAttributes.params);
			    lookups.push( scores.weightedCorrect );
			}
		    }
		}
		if (gradeWeight)
		    lookups.push( vlookup('q_grades', j+scoreStartRow) );
		if (otherWeight)
		    lookups.push( vlookup('q_other', j+scoreStartRow) );
		
		if (lookups.length) {
		    var lateToken = vlookup('lateToken', j+scoreStartRow);
		    var cumScore = lookups.join('+');
		    var combinedScore = '';
		    if (sessionAttributes.params.lateCredit) {
			combinedScore = 'IF('+lateToken+'="'+LATE_SUBMIT+'", '+sessionAttributes.params.lateCredit+', 1)*( '+cumScore+' )';
		    } else {
			combinedScore = 'IF('+lateToken+'="'+LATE_SUBMIT+'", "", '+cumScore+ ' )';
		    }
		    scoreFormulas.push(['=IFERROR('+combinedScore+')']);
		}
	    }

	    if (scoreAvgRow)
		scoreSheet.getRange(scoreAvgRow, scoreSessionCol, 1, 1).setValues([['=AVERAGE('+colChar+avgStartRow+':'+colChar+')']]);
	    if (scoreFormulas.length)
		scoreSheet.getRange(scoreStartRow, scoreSessionCol, nids, 1).setValues(scoreFormulas);
	}

	var scoreRawCol = scoreColIndex['rawTotal'];
	var scoreSessionCountCol = scoreColIndex['sessionCount'];
	var scoreWeightedCol = scoreColIndex['weightedTotal'];
	var rawFormat = rawTotal.length ? '='+rawTotal.join('+') : '';
	var sessionCountFormat = sessionCount.length ? '='+sessionCount.join('+') : '';
	var weightedFormat = weightedTotal.length ? '='+weightedTotal.join('+') : '';
	var rawFormulas = [];
	var sessionCountFormulas = [];
	var weightedFormulas = [];
	for (var j=0; j<nids; j++) {
	    rawFormulas.push([rawFormat.replace(/@/g,''+(j+scoreStartRow))]);
	    sessionCountFormulas.push([sessionCountFormat.replace(/@/g,''+(j+scoreStartRow))]);
	    weightedFormulas.push([weightedFormat.replace(/@/g,''+(j+scoreStartRow))]);
	}
	scoreSheet.getRange(scoreStartRow, scoreRawCol, nids, 1).setValues(rawFormulas);
	scoreSheet.getRange(scoreStartRow, scoreSessionCountCol, nids, 1).setValues(sessionCountFormulas);
	scoreSheet.getRange(scoreStartRow, scoreWeightedCol, nids, 1).setValues(weightedFormulas);

    } finally { //release lock
	lock.releaseLock();
    }

    notify("Updated "+scoreSheetName+" for sessions "+updatedNames.join(', '), 'Slidoc Scores');
}
