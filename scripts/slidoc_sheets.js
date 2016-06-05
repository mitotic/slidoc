// slidoc_sheets.js: Google Sheets add-on to interact with Slidoc documents
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
//       HMAC_KEY  set to your secret key string (also used in the --google_docs=url,hmackey option)
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
//       slidoc.py --google_docs=https://script.google.com/macros/s/..,HMAC_KEY ...
//
//  8. If you make any further changes to this script, Save it and then click on Publish > Deploy as web app…
//       Change Project Version to New and click Update (the web app URL remains the same)
//       (If you changed the menu, you may need to close the spreadsheet and re-open it to see the changes.)
//
// ROSTER
//  You may optionally create a 'roster_slidoc' sheet containing ['name', 'id', 'email', 'altid'] in the first four columns.
//  The 'name', 'email' and 'altid' values will be copied from this column to sesssion sheets (using 'id' as the index).
//  If roster_slidoc sheet is present and user id is not present in it, user will not be allowed to access sessions.
//
// USING THE SLIDOC MENU
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


var HMAC_KEY = 'testkey';   // Set this value for secure administrative access to session index
var ADMIN_USER = 'admin';

var ANSWER_DOC_ID = '';     // Set this for separate answers document
var STAT_DOC_ID   = '';       // Set this for separate stats document

var INDEX_SHEET = 'sessions_slidoc';
var ROSTER_SHEET = 'roster_slidoc';
var SCORES_SHEET = 'scores_slidoc';

var MIN_HEADERS = ['name', 'id', 'email', 'altid'];

var REQUIRE_LOGIN_TOKEN = true;
var REQUIRE_LATE_TOKEN = true;

var TRUNCATE_DIGEST = 8;
var QFIELD_RE = /^q(\d+)_([a-z]+)(_[0-9\.]+)?$/;

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

// If you don't want to expose either GET or POST methods you can comment out the appropriate function
function doGet(evt){
  return handleResponse(evt);
}

function doPost(evt){
  return handleResponse(evt);
}

function handleResponse(evt) {
    // Return value is null on error and a list on success.
    // The list contains updated row values if get=true; otherwise it is just an empty list.
    // PARAMETERS
    // sheet: 'sheet name' (required)
    // headers: ['name', 'id', 'email', 'altid', 'Timestamp', 'initTimestamp', 'submitTimestamp', 'field1', ...] (name and id required for sheet creation)
    // name: sortable name, usually 'Last name, First M.' (required if creating a row, and row parameter is not specified)
    // id: unique id number or lowercase email (required if creating or updating a row, and row parameter is not specified)
    // email: optional
    // altid: alternate, perhaps numeric, id (optional, used for information only)
    // update: [('field1', 'val1'), ...] (list of fields+values to be updated, excluding the unique field 'id')
    // If the special name initTimestamp occurs in the list, the timestamp is initialized when the row is added.
    // If the special name Timestamp occurs in the list, the timestamp is automatically updated on each write.
    // row: ['name_value', 'id_value', 'email_value', 'altid_value', null, null, null, 'field1_value', ...]
    //       null value implies no update (except for Timestamp)
    // get: true to retrieve row (id must be specified) (otherwise only [] is returned on success)
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
    var returnInfo = {};
    var returnMessages = [];
    var jsonPrefix = '';
    var jsonSuffix = '';
    var mimeType = ContentService.MimeType.JSON;
    try {
	var params = evt.parameter;

	if (params.prefix) {
	    jsonPrefix = params.prefix + '(' + (params.callback || '0') + ', ';
            jsonSuffix = ')';
	    mimeType = ContentService.MimeType.JAVASCRIPT;
	}

	var sheetName = params.sheet;
	if (!sheetName)
	    throw('Error:SHEETNAME::No sheet name specified');

	var restrictedSheet = (sheetName == INDEX_SHEET);
	var loggingSheet = (sheetName.slice(-4) == '_log');
	var adminUser = '';
	var authUser = '';
	var doc = SpreadsheetApp.openById(SCRIPT_PROP.getProperty("key"));
	if (params.admin) {
	    if (!params.token)
		throw('Error:NEED_ADMIN_TOKEN:Need token for admin authentication');
	    if (!validateHMAC('admin:'+params.admin+':'+params.token, HMAC_KEY))
		throw("Error:INVALID_ADMIN_TOKEN:Invalid token for authenticating admin user '"+params.admin+"'");
	    adminUser = params.admin;
	} else if (REQUIRE_LOGIN_TOKEN) {
	    if (!params.id)
		throw('Error:NEED_ID:Need id for authentication');
	    if (!params.token)
		throw('Error:NEED_TOKEN:Need token for id authentication');
	    if (!validateHMAC('id:'+params.id+':'+params.token, HMAC_KEY))
		throw("Error:INVALID_TOKEN:Invalid token for authenticating id '"+params.id+"'");
	    authUser = params.id;
	}

	if (restrictedSheet) {
	    if (!adminUser)
		throw("Error::Must be admin user to access sheet '"+sheetName+"'");
	}

	var rosterValues = [];
	var rosterSheet = doc.getSheetByName(ROSTER_SHEET);
	if (rosterSheet && !adminUser) {
	    // Check user access
	    if (!params.id)
		throw('Error:NEED_ID:Must specify user id to lookup roster')
	    try {
		// Copy user info from roster
		rosterValues = lookupValues(params.id, MIN_HEADERS, ROSTER_SHEET, true);
	    } catch(err) {
		throw("Error:NEED_ROSTER_ENTRY:User id '"+params.id+"' not found in roster");
	    }
	}

	// Check parameter consistency
	var headers = params.headers ? JSON.parse(params.headers) : null;

	var sheet = doc.getSheetByName(sheetName);
	if (!sheet) {
	    // Create new sheet
	    if (!headers)
		throw("Error::Headers must be specified for new sheet '"+sheetName+"'");
	    doc.insertSheet(sheetName);
	    sheet = doc.getSheetByName(sheetName);
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
	    if (restrictedSheet) {
		var protection = sheet.protect().setDescription('protected');
		protection.setUnprotectedRanges([sheet.getRange('E2:F')]);
		protection.setDomainEdit(false);
	    }
	}

	if (!sheet.getLastColumn())
	    throw("Error::No columns in sheet '"+sheetName+"'");

	var columnHeaders = sheet.getSheetValues(1, 1, 1, sheet.getLastColumn())[0];
	var columnIndex = indexColumns(sheet);

	if (headers) {
	    if (headers.length > columnHeaders.length)
		throw("Error::Number of headers exceeds that present in sheet '"+sheetName+"'");
	    for (var j=0; j<headers.length; j++) {
		if (headers[j] != columnHeaders[j])
		    throw("Error::Column header mismatch: Expected "+headers[j]+" but found "+columnHeaders[j]+" in sheet '"+sheetName+"'; delete it or edit headers.");
	    }
	}

	var getRow = params.get || '';
	var allRows = params.all || '';
	var nooverwriteRow = params.nooverwrite || '';

	var selectedUpdates = params.update ? JSON.parse(params.update) : null;
	var rowUpdates = params.row ? JSON.parse(params.row) : null;

	var userId = null;
	var displayName = null;

	if (!adminUser && selectedUpdates)
	    throw("Error::Only admin user allowed to make selected updates to sheet '"+sheetName+"'");

	returnInfo.timestamp = null;
	var numStickyRows = 1;  // Headers etc.

	if (!rowUpdates && !selectedUpdates && !getRow) {
	    // No row updates/gets
	    returnValues = [];
	} else if (getRow && allRows) {
	    // Get all rows and columns
	    if (sheet.getLastRow() > numStickyRows)
		returnValues = sheet.getRange(1+numStickyRows, 1, sheet.getLastRow()-numStickyRows, columnHeaders.length).getValues();
	    else
		returnValues = [];
	} else {
	    if (rowUpdates && selectedUpdates) {
		throw('Error::Cannot specify both rowUpdates and selectedUpdates');
	    } else if (rowUpdates) {
		if (rowUpdates.length > columnHeaders.length)
		    throw("Error::row_headers length exceeds no. of columns in sheet '"+sheetName+"'");


		userId = rowUpdates[columnIndex['id']-1] || null;
		displayName = rowUpdates[columnIndex['name']-1] || null;

		// Security check
		if (params.id && params.id != userId)
		    throw("Error::Mismatch between params.id '%s' and userId in row '%s'" % (params.id, userId))
		if (params.name && params.name != displayName)
		    throw("Error::Mismatch between params.name '%s' and displayName in row '%s'" % (params.name, displayName))
	    } else {
		userId = params.id || null;
	    }

	    if (!userId)
		throw('Error::User id must be specified for updates/gets');
	    var userRow = -1;
	    if (sheet.getLastRow() > numStickyRows && !loggingSheet) {
		// Locate ID row (except for log files)
		var ids = sheet.getSheetValues(1+numStickyRows, columnIndex['id'], sheet.getLastRow()-numStickyRows, 1);
		for (var j=0; j<ids.length; j++) {
		    // Unique ID
		    if (ids[j][0] == userId) {
			userRow = j+1+numStickyRows;
			break;
		    }
		}
	    }
	    //returnMessages.push('Debug::userRow, userid, rosterValues: '+userRow+', '+userId+', '+rosterValues);
	    var newRow = (userRow < 0);

	    if (adminUser && !restrictedSheet && newRow)
		throw("Error::Admin user not allowed to create new row in sheet '"+sheetName+"'");

	    if (newRow && getRow && !rowUpdates) {
		// Row does not exist; return empty list
		returnValues = [];

	    } else if (newRow && selectedUpdates) {
		throw('Error::Selected updates cannot be applied to new row');
	    } else {
		var curDate = new Date();
		var allowLateMods = !REQUIRE_LATE_TOKEN;
		var pastSubmitDeadline = false;
		var partialSubmission = false;
		var dueDate = null;
		var gradeDate = null;
		var fieldsMin = columnHeaders.length;
		if (!restrictedSheet && !loggingSheet && doc.getSheetByName(INDEX_SHEET)) {
		    // Session parameters
		    var sessionParams = lookupValues(sheetName, ['dueDate', 'gradeDate', 'fieldsMin'], INDEX_SHEET);
		    dueDate = sessionParams.dueDate;
		    gradeDate = sessionParams.gradeDate;
		    fieldsMin = sessionParams.fieldsMin;

		    if (dueDate && !adminUser) {
			// Check if past submission deadline
			var lateTokenCol = columnIndex['lateToken'];
			var lateToken = null;
			if (lateTokenCol) {
			    lateToken = (rowUpdates && rowUpdates.length >= lateTokenCol) ? (rowUpdates[lateTokenCol-1] || null) : null;
			    if (!lateToken && !newRow)
				lateToken = sheet.getRange(userRow, lateTokenCol, 1, 1).getValues()[0][0] || null;
			}

			var curTime = curDate.getTime();
			pastSubmitDeadline = (dueDate && curTime > dueDate.getTime())
			if (!allowLateMods && pastSubmitDeadline && lateToken) {
			    if (lateToken == 'partial' && !newRow && rowUpdates) {
				partialSubmission = true;
				rowUpdates = null;
				selectedUpdates = [ ['Timestamp', null], ['submitTimestamp', null], ['lateToken', lateToken] ];
				returnMessages.push("Warning:PARTIAL_SUBMISSION:Partial submission by user '"+(displayName||"")+"' to session '"+sheetName+"'");
			    } else if (lateToken == 'none') {
				// Late submission without token
				allowLateMods = true;
			    } else {
				var comps = splitToken(lateToken);
				var dateStr = comps[0];
				var tokenStr = comps[1];
				if (genLateToken(HMAC_KEY, userId, sheetName, dateStr) == lateToken) {
				    dueDate = createDate(dateStr); // Date format: '1995-12-17T03:24Z'
				    pastSubmitDeadline = (curTime > dueDate.getTime());
				} else {
				    returnMessages.push("Warning:INVALID_LATE_TOKEN:Invalid token for late submission by user '"+(displayName||"")+"' to session '"+sheetName+"'");
				}
			    }
			}
			returnInfo.dueDate = dueDate;
			if (!allowLateMods && !partialSubmission) {
			    if (pastSubmitDeadline) {
				    if (newRow || selectedUpdates || (rowUpdates && !nooverwriteRow)) {
					// Creating/modifying row; require valid lateToken
					if (!lateToken)
					    throw("Error:PAST_SUBMIT_DEADLINE:Past submit deadline ("+dueDate+") for session '"+sheetName+"'. (If valid excuse, request late submission token.)")
					else
					    throw("Error:INVALID_LATE_TOKEN:Invalid token for late submission to session '"+sheetName+"'");
				    } else {
					returnMessages.push("Warning:PAST_SUBMIT_DEADLINE:Past submit deadline ("+dueDate+") for session '"+sheetName+"'. (If valid excuse, request late submission token.)");
				    }
			    } else if ( (dueDate.getTime() - curTime) < 2*60*60*1000) {
				returnMessages.push("Warning:NEAR_SUBMIT_DEADLINE:Nearing submit deadline ("+dueDate+") for session '"+sheetName+"'.");
			    }
			}
		    }
		}

		if (newRow) {
		    // New user; insert row in sorted order of name (except for log files)
		    if (!displayName || !rowUpdates)
			throw('Error::User name and row parameters required to create a new row for id '+userId+' in sheet '+sheetName);

		    userRow = sheet.getLastRow()+1;
		    if (sheet.getLastRow() > numStickyRows && !loggingSheet) {
			var names = sheet.getSheetValues(1+numStickyRows, columnIndex['name'], sheet.getLastRow()-numStickyRows, 1);
			for (var j=0; j<names.length; j++) {
			    if (names[j][0] > displayName) {
				userRow = j+1+numStickyRows
				break;
			    }
			}
		    }
		    sheet.insertRowBefore(userRow);
		} else if (rowUpdates && nooverwriteRow) {
		    if (getRow) {
			// Simply return existing row
			rowUpdates = null;
		    } else {
			throw('Error::Do not specify nooverwrite=1 to overwrite existing rows');
		    }
		}

		var maxCol = rowUpdates ? rowUpdates.length : columnHeaders.length;
		var totalCol = (columnHeaders.length > fieldsMin && columnHeaders[fieldsMin].slice(0,8) == 'q_grades') ? fieldsMin+1 : 0;
		var userRange = sheet.getRange(userRow, 1, 1, maxCol);
		var rowValues = userRange.getValues()[0];

		returnInfo.timestamp = ('Timestamp' in columnIndex && rowValues[columnIndex['Timestamp']-1]) ? rowValues[columnIndex['Timestamp']-1].getTime() : null;
		if (returnInfo.timestamp && params.timestamp && parseNumber(params.timestamp) && returnInfo.timestamp > parseNumber(params.timestamp))
		    throw('Error::Row timestamp too old by '+Math.ceil((returnInfo.timestamp-parseNumber(params.timestamp))/1000)+' seconds. Conflicting modifications from another active browser session?');

		if (rowUpdates) {
		    // Update all non-null and non-id row values
		    // Timestamp is always updated, unless it is specified by admin
		    if (adminUser && !restrictedSheet)
			throw("Error::Admin user not allowed to update full rows in sheet '"+sheetName+"'");

		    if (rowUpdates.length > fieldsMin) {
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
			returnMessages.push("Debug::"+nonNullExtraColumn+Object.keys(adminColumns)+'=' + totalCells.join('+'));
		    }

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
			} else if (colValue == null) {
			    // Do not modify field
			} else if (newRow || (MIN_HEADERS.indexOf(colHeader) == -1 && colHeader.slice(-9) != 'Timestamp') ) {
			    // Id, name, email, altid, *Timestamp cannot be updated programmatically
			    // (If necessary to change name manually, then re-sort manually)
			    if (colHeader.slice(-4).toLowerCase() == 'date' || colHeader.slice(-4).toLowerCase() == 'time') {
				try { rowValues[j] = createDate(colValue); } catch (err) { }
			    } else {
				rowValues[j] = colValue;
			    }
			} else {
			    if (rowValues[j] !== colValue)
				throw("Error::Cannot modify column '"+colHeader+"'. Specify as 'null'");
			}
		    }

		    // Copy user info from roster (if available)
		    for (var j=0; j<rosterValues.length; j++)
			rowValues[j] = rosterValues[j];

		    // Save updated row
		    userRange.setValues([rowValues]);

		} else if (selectedUpdates) {
		    // Update selected row values
		    // Timestamp is updated only if specified in list
		    if (!adminUser && !partialSubmission)
			throw("Error::Only admin user allowed to make selected updates to sheet '"+sheetName+"'");

		    for (var j=0; j<selectedUpdates.length; j++) {
			var colHeader = selectedUpdates[j][0];
			var colValue = selectedUpdates[j][1];
			
			if (!(colHeader in columnIndex))
			    throw("Error::Field "+colHeader+" not found in sheet '"+sheetName+"'");

			var headerColumn = columnIndex[colHeader];
			var modValue = null;

			if (colHeader == 'Timestamp') {
			    // Timestamp is always updated, unless it is explicitly specified by admin
			    if (adminUser && colValue) {
				try { modValue = createDate(colValue); } catch (err) {}
			    } else {
				modValue = curDate;
			    }
			} else if (colHeader == 'submitTimestamp') {
			    if (partialSubmission) {
				modValue = curDate;
				returnInfo.submitTimestamp = curDate;
			    }
			} else if (colValue == null) {
			    // Do not modify field
			} else if (MIN_HEADERS.indexOf(colHeader) == -1 && colHeader.slice(-9) != 'Timestamp') {
			    // Update row values for header (except for id, name, email, altid, *Timestamp)
			    if (!restrictedSheet && (headerColumn <= fieldsMin || !/^q\d+_(comments|grade_[0-9.]+)$/.exec(colHeader)) )
				throw("Error::admin user may not update user-defined column '"+colHeader+"' in sheet '"+sheetName+"'");

			    if (colHeader.slice(-4).toLowerCase() == 'date' || colHeader.slice(-4).toLowerCase() == 'time') {
				try { colValue = createDate(colValue); } catch (err) {}
			    }
			    modValue = colValue;
			} else {
			    if (rowValues[headerColumn-1] !== colValue)
				throw("Error::Cannot modify column '"+colHeader+"'. Specify as 'null'");
			}
			if (modValue !== null) {
			    rowValues[headerColumn-1] = modValue;
			    sheet.getRange(userRow, headerColumn, 1, 1).setValues([[ rowValues[headerColumn-1] ]]);
			}
		    }

		}
		
		// Return updated timestamp
		returnInfo.timestamp = ('Timestamp' in columnIndex) ? rowValues[columnIndex['Timestamp']-1].getTime() : null;
		
		returnValues = getRow ? rowValues : [];

		if (!adminUser && !gradeDate && returnValues.length > fieldsMin) {
		    // If session not graded, nullify columns to be graded
		    for (var j=fieldsMin; j < columnHeaders.length; j++)
			returnValues[j] = null;
		}
	    }
	}

	// return json success results
	return ContentService
            .createTextOutput(jsonPrefix+JSON.stringify({"result":"success", "value": returnValues, "info": returnInfo,
							 "messages": returnMessages.join('\n')})+jsonSuffix)
            .setMimeType(mimeType);
    } catch(err){
	// if error return this
	return ContentService
            .createTextOutput(jsonPrefix+JSON.stringify({"result":"error", "error": ''+err, "value": null,
							 "messages": returnMessages.join('\n')})+jsonSuffix)
            .setMimeType(mimeType);
    } finally { //release lock
	lock.releaseLock();
    }
}

function setup() {
    var doc = SpreadsheetApp.getActiveSpreadsheet();
    SCRIPT_PROP.setProperty("key", doc.getId());
}

function parseNumber(x) {
    try {
	var retval;
	if (!isNaN(x))
	    return x;
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
    }
    return new Date(date);
}

function genHmacToken(key, message) {
    var rawHMAC = Utilities.computeHmacSignature(Utilities.MacAlgorithm.HMAC_MD5,
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
    var rowIds = sheet.getSheetValues(startRow, indexCol, sheet.getLastRow()-startRow+1, 1);
    var rowIndex = {};
    for (var j=0; j<rowIds.length; j++)
	rowIndex[rowIds[j][0]] = j+startRow;
    return rowIndex;
}

function getColumns(header, sheetName, colCount, skipRows) {
    skipRows = skipRows || 1;
    var doc = SpreadsheetApp.openById(SCRIPT_PROP.getProperty("key"));
    var sheet = doc.getSheetByName(sheetName);
    var colIndex = indexColumns(sheet);
    if (!(header in colIndex))
	throw('Column '+header+' not found in sheet '+sheetName);
    if (colCount && colCount > 1) {
	// Multiple columns (list of lists)
	return sheet.getSheetValues(1+skipRows, colIndex[header], sheet.getLastRow()-skipRows, colCount)
    } else {
	// Single column
	var vals = sheet.getSheetValues(1+skipRows, colIndex[header], sheet.getLastRow()-skipRows, 1);
	var retvals = [];
	for (var j=0; j<vals.length; j++)
	    retvals.push(vals[j][0]);
	return retvals;
    }
}

function lookupValues(idValue, colNames, sheetName, listReturn) {
    // Return parameters in list colNames for idValue from sessions_slidoc sheet
    var doc = SpreadsheetApp.openById(SCRIPT_PROP.getProperty("key"));
    var indexSheet = doc.getSheetByName(sheetName);
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
	var sessionParams = lookupValues(sessionName, ['scoreWeight'], INDEX_SHEET);
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
	var doc = SpreadsheetApp.openById(SCRIPT_PROP.getProperty("key"));
	var sessionSheet = doc.getSheetByName(sessionName);
	if (!sessionSheet)
	    throw('Sheet not found: '+sessionName);
	if (!sessionSheet.getLastColumn())
	    throw('No columns in sheet: '+sessionName);

	var sessionColIndex = indexColumns(sessionSheet);

	var sessionParams = lookupValues(sessionName, ['questions', 'answers'], INDEX_SHEET);
	var questions = sessionParams.questions.split(',');
	var answers = sessionParams.answers.split('|');

	// Copy first two columns from session sheet
	var copyCols = 2;
	var answerHeaders = sessionSheet.getSheetValues(1, 1, 1, copyCols)[0];

	var respCols = [];
	var extraCols = ['expect', 'score', 'plugin'];
	for (var j=0; j<questions.length; j++) {
	    var qprefix = 'q'+(j+1);
	    var pluginResponse = /^(\w+).response()\(\)/.exec(answers[j]);
	    var inlineJS = /^(\w+).expect()\(\)/.exec(answers[j]);
	    var respColName = qprefix;
	    if (answers[j] && !inlineJS) {
		if (questions[j] == 'choice')
		    respColName += '_'+answers[j];
		else if (questions[j] == 'number')
		    respColName += '_'+answers[j].replace(' +/- ','_pm_').replace('+/-','_pm_').replace(' ','_');
	    }
	    answerHeaders.push(respColName);
	    respCols.push(answerHeaders.length);
	    if (inlineJS)
		answerHeaders.push(qprefix+'_expect');
	    if (answers[j] || pluginResponse)
		answerHeaders.push(qprefix+'_score');
	    if (pluginResponse)
		answerHeaders.push(qprefix+'_plugin');
	}
	Logger.log('ansHeaders: '+answerHeaders);
	var ansHeaderCols = {};
	for (var j=0; j<answerHeaders.length; j++)
	    ansHeaderCols[answerHeaders[j]] = j+1;

	var outDoc = null;
	if (ANSWER_DOC_ID)
	    outDoc = SpreadsheetApp.openById(ANSWER_DOC_ID);
	if (!outDoc)
	    outDoc = doc;

	// Session answers headers

	// New answers sheet
	var answerSheetName = sessionName+'-answers';
	var answerSheet = outDoc.getSheetByName(answerSheetName);
	if (!answerSheet)
	    answerSheet = outDoc.insertSheet(answerSheetName);
	answerSheet.clear()
	var answerHeaderRange = answerSheet.getRange(1, 1, 1, answerHeaders.length);
	answerHeaderRange.setValues([answerHeaders]);
	answerHeaderRange.setWrap(true);
	answerSheet.getRange('1:1').setFontWeight('bold');

	// Session sheet columns
	var startRow = 2;

	// Answers sheet columns
	var answerStartRow = 2;

	// Number of ids
	var nids = sessionSheet.getLastRow()-1;

	answerSheet.getRange(answerStartRow, 1, nids, copyCols).setValues(sessionSheet.getSheetValues(startRow, 1, nids, copyCols));

	// Get hidden session values
	var hiddenSessionCol = sessionColIndex['session_hidden'];
	var hiddenVals = sessionSheet.getSheetValues(startRow, hiddenSessionCol, nids, 1);
	var qRows = [];

	for (var j=0; j<nids; j++) {
	    var jsonSession = Utilities.newBlob(Utilities.base64Decode(hiddenVals[j][0])).getDataAsString();
	    var savedSession = JSON.parse(jsonSession);
	    var qAttempted = savedSession.questionsAttempted;

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
			if ((qprefix+'_'+attr) in ansHeaderCols && attr in qAttempted[qno])
			    rowVals[ansHeaderCols[qprefix+'_'+attr]-1] = (qAttempted[qno][attr]===null) ? '': qAttempted[qno][attr];
		    }
		}
	    }
	    qRows.push(rowVals.slice(copyCols));

	}
	answerSheet.getRange(answerStartRow, copyCols+1, nids, answerHeaders.length-copyCols).setValues(qRows);
    } finally { //release lock
	lock.releaseLock();
    }

    notify('Created sheet '+outDoc.getName()+'!'+answerSheetName, 'Slidoc Answers');
}


function sessionStatSheet() {
    // Create session stats sheet

    var sessionName = getSessionName(true);

    var lock = LockService.getPublicLock();
    lock.waitLock(30000);  // wait 30 seconds before conceding defeat.

    try {
	var doc = SpreadsheetApp.openById(SCRIPT_PROP.getProperty("key"));
	var sessionSheet = doc.getSheetByName(sessionName);
	if (!sessionSheet)
	    throw('Sheet not found '+sessionName);
	if (!sessionSheet.getLastColumn())
	    throw('No columns in sheet '+sessionName);

	var sessionColIndex = indexColumns(sessionSheet);

	// Session sheet columns
	var sessionStartRow = 2;
	var nids = sessionSheet.getLastRow()-1;

	var sessionParams = lookupValues(sessionName, ['primary_qconcepts', 'secondary_qconcepts'], INDEX_SHEET);
	var p_concepts = sessionParams.primary_qconcepts ? sessionParams.primary_qconcepts.split('; ') : [];
	var s_concepts = sessionParams.secondary_qconcepts ? sessionParams.secondary_qconcepts.split('; ') : [];
	 
	// Session stats headers
	var sessionCopyCols = ['name', 'id', 'Timestamp', 'lateToken', 'lastSlide'];
	var statExtraCols = ['correct', 'count', 'skipped']

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

	var outDoc = null;
	if (STAT_DOC_ID)
	    outDoc = SpreadsheetApp.openById(STAT_DOC_ID);
	if (!outDoc)
	    outDoc = doc;

	// New stat sheet
	var statSheetName = sessionName+'-stats';
	statSheet = outDoc.getSheetByName(statSheetName);
	if (!statSheet)
	    statSheet = outDoc.insertSheet(statSheetName);
	statSheet.clear()
	var statHeaderRange = statSheet.getRange(1, 1, 1, statHeaders.length);
	statHeaderRange.setValues([statHeaders]);
	statHeaderRange.setWrap(true);
	statSheet.getRange('1:1').setFontWeight('bold');

	var statColIndex = indexColumns(statSheet);

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
	    var jsonSession = Utilities.newBlob(Utilities.base64Decode(hiddenVals[j][0])).getDataAsString();
	    var savedSession = JSON.parse(jsonSession);
	    questionTallies.push([savedSession.questionsCorrect, savedSession.questionsCount, savedSession.questionsSkipped]);

	    var missedConcepts = savedSession.missedConcepts;
	    if (missedConcepts.length) {
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

    notify('Created sheet '+outDoc.getName()+'!'+statSheetName, 'Slidoc Stats');
}

function emailTokens() {
    // Send authentication tokens
    var doc = SpreadsheetApp.openById(SCRIPT_PROP.getProperty("key"));
    var rosterSheet = doc.getSheetByName(ROSTER_SHEET);
    if (!rosterSheet)
	throw('Roster sheet '+ROSTER_SHEET+' not found!');
    var userId = getPrompt('Email authentication tokens', "User id, or 'all'");
    if (!userId)
	return;
    var emailList;
    if (userId != 'all') {
	emailList = [ [userId, lookupValues(userId,['email'],ROSTER_SHEET,true)[0] ] ];
    } else {
	emailList = getColumns('id', ROSTER_SHEET, 2);
    }
    for (var j=0; j<emailList.length; j++)
	if (emailList[j][1].indexOf('@') <= 0)
	    throw("Invalid email address '"+emailList[j][1]+"' for user ID '"+emailList[j][0]+"'");

    var subject = 'Slidoc authentication token';
    var emails = [];
    for (var j=0; j<emailList.length; j++) {
	var token = genUserToken(HMAC_KEY, emailList[j][0]);
	var message = 'Authentication token for user ID '+emailList[j][0]+' is '+token;
	MailApp.sendEmail(emailList[j][1], subject, message);
	emails.push(emailList[j][1]);
    }

    notify('Emailed '+emails.length+' token(s) to '+emails.join(', '));
}


function emailLateToken() {
    // Send late token
    var doc = SpreadsheetApp.openById(SCRIPT_PROP.getProperty("key"));
    var rosterSheet = doc.getSheetByName(ROSTER_SHEET);
    if (!rosterSheet)
	throw('Roster sheet '+ROSTER_SHEET+' not found!');

    var sessionName = getSessionName();
    if (sessionName) {
	var userId = getPrompt('Email late submission token for session '+sessionName, "UserID");
	if (!userId)
	    return;
    } else {
	var text = getPrompt('Email late submission token', "UserID, session");
	if (!text)
	    return;
	var comps = text.trim().split(/\s*,\s*/);
	var userId = comps[0];
	sessionName = comps[1];
    }
    var email = lookupValues(userId,['email'], ROSTER_SHEET, true)[0];
    if (email.indexOf('@') <= 0)
	throw("Invalid email address '"+email+"' for user ID '"+userId+"'");

    var dateStr = getPrompt('New submission date/time', "'yyyy-mm-ddTmm:hh' (or 'yyyy-mm-dd', implying 'T23:59')");
    if (!dateStr)
	return;
    if (dateStr.indexOf('T') < 0)
	dateStr += 'T23:59';

    var subject = 'Slidoc late submission token';
    var token = genLateToken(HMAC_KEY, userId, sessionName, dateStr);
    var message = 'Late submission token for user ID '+userId+' and session '+sessionName+' is '+token;
    MailApp.sendEmail(email, subject, message);

    notify('Emailed late submission token to '+userId+' <'+email+'>');
}


function updateScoreSheet() {
    // Update scores sheet

    var lock = LockService.getPublicLock();
    lock.waitLock(30000);  // wait 30 seconds before conceding defeat.

    try {
	var doc = SpreadsheetApp.openById(SCRIPT_PROP.getProperty("key"));

	var sessionNames = getColumns('id', INDEX_SHEET);
	var validNames = [];
	var validSheet = null;
	for (var m=0; m<sessionNames.length; m++) {
	    // Ensure all sessions exist
	    var sessionName = sessionNames[m];
	    var sessionSheet = doc.getSheetByName(sessionName);
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

	var sessionStartRow = 2;
	var scoreStartRow = 2;

	// New score sheet
	var scoreSheetName = SCORES_SHEET;
	scoreSheet = doc.getSheetByName(scoreSheetName);
	if (!scoreSheet) {
	    // Create session score sheet
	    scoreSheet = doc.insertSheet(scoreSheetName);
	    // Copy user info from roster
	    var userInfoSheet = doc.getSheetByName(ROSTER_SHEET);
	    if (!userInfoSheet)  // Copy user info from last valid session
		userInfoSheet = validSheet;
	    var nidsSession = userInfoSheet.getLastRow()-sessionStartRow+1;
	    scoreSheet.getRange(1, 1, 1, MIN_HEADERS.length).setValues(userInfoSheet.getSheetValues(1, 1, 1, MIN_HEADERS.length));

	    scoreSheet.getRange(scoreStartRow, 1, nidsSession, MIN_HEADERS.length).setValues(userInfoSheet.getSheetValues(sessionStartRow, 1, nidsSession, MIN_HEADERS.length));
	    scoreSheet.getRange('1:1').setFontWeight('bold');
	}

	for (var m=0; m<validNames.length; m++) {
	    var sessionName = validNames[m];
	    var sessionSheet = doc.getSheetByName(sessionName);
	    var sessionColIndex = indexColumns(sessionSheet);

	    var sessionParams = lookupValues(sessionName, ['scoreWeight', 'gradeWeight'], INDEX_SHEET);
	    var scoreWeight = parseNumber(sessionParams.scoreWeight) || 0;
	    var gradeWeight = parseNumber(sessionParams.gradeWeight) || 0;


	    // Session sheet columns
	    var idCol = sessionColIndex['id'];
	    var lateCol = sessionColIndex['lateToken'];
	    var correctCol = sessionColIndex['questionsCorrect'];

	    var idColChar = colIndexToChar( idCol );
	    var correctColChar = colIndexToChar( correctCol );

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
		    if (MIN_HEADERS.indexOf(colHeader) == -1 && colHeader.slice(0,1) == '_') {
			// Session header column
			if (sessionName < colHeader) {
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
		scoreSheet.getRange(c+scoreStartRow+':'+c).setNumberFormat('0.00');
	    }

	    var nids = scoreSheet.getLastRow()-scoreStartRow+1;

	    var idCol = sessionColIndex['id'];
	    var idColChar = colIndexToChar( idCol );
	    function vlookup(colName, scoreRowIndex) {
		var nameCol = sessionColIndex[colName];
		var nameColChar = colIndexToChar( nameCol );
		var sessionRange = sessionName+'!$'+idColChar+'$'+sessionStartRow+':$'+nameColChar;
		return 'VLOOKUP($'+idColChar+scoreRowIndex+', ' + sessionRange + ', '+(nameCol-idCol+1)+', false)';
	    }

	    var scoreFormulas = [];
	    for (var j=0; j<nids; j++) {
		if (gradeWeight) {
		    scoreFormulas.push(['=IF('+vlookup('lateToken', j+scoreStartRow)+'="none", "", ('+vlookup('weightedCorrect', j+scoreStartRow)+'+'+vlookup('q_grades_'+gradeWeight, j+scoreStartRow)+')/('+scoreWeight+'+'+gradeWeight + ') )']);
		} else if (scoreWeight) {
		    scoreFormulas.push(['=IF('+vlookup('lateToken', j+scoreStartRow)+'="none", "", '+ vlookup('weightedCorrect', j+scoreStartRow) + ')']);
		}
	    }
	    
	    if (scoreFormulas.length)
		scoreSheet.getRange(scoreStartRow, scoreSessionCol, nids, 1).setValues(scoreFormulas)
	}

    } finally { //release lock
	lock.releaseLock();
    }

    notify("Update "+SCORES_SHEET+" for sessions "+validNames.join(', '), 'Slidoc Scores');
}
