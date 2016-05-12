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
// USING THE SLIDOC MENU
//  - "Display session answers" to create/overwrite the sheet
//    'sessionName-answers' displaying all the answers
//
//  - "Display session statistics" to create/overwrite the sheet
//    'sessionName-stats' displaying session statistics
//
//  - "Update scores for session" to update score for a particular session
//    in the 'scores' sheet (which is automatically created, if need be)
//
// You may also create the 'scores' sheet yourself:
//   - Put headers in the first row. The first four are usually 'name', 'id', 'email', 'user'
//   - 'id' is the only required column, which should be unique for each user and used to index sessions
//   - Any custom header names should begin with an underscore, to avoid being mistaken for session names.
//   - "Update scores for session" menu action will only update session columns with lookup formulas.
//   - If you add new user rows, then you could simply copy the lookup formula from existing rows.


var HMAC_KEY = 'testkey';   // Set this value for secure administrative access to session index
var ADMIN_USER = 'admin';
var INDEX_SHEET = 'slidoc_sessions';

var REQUIRE_LOGIN_TOKEN = true;
var REQUIRE_LATE_TOKEN = true;

var TRUNCATE_DIGEST = 8;

var SCRIPT_PROP = PropertiesService.getScriptProperties(); // new property service

// The onOpen function is executed automatically every time a Spreadsheet is loaded
function onOpen() {
   var ss = SpreadsheetApp.getActiveSpreadsheet();
   var menuEntries = [];
   menuEntries.push({name: "Display session answers", functionName: "sessionAnswerSheet"});
   menuEntries.push({name: "Display session statistics", functionName: "sessionStatSheet"});
   menuEntries.push(null); // line separator
   menuEntries.push({name: "Update scores for session", functionName: "updateScoreSheet"});

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
    // headers: ['name', 'id', 'email', 'user', 'Timestamp', 'initTimestamp', 'field2', ...] (name and id required for sheet creation)
    // name: sortable name, usually 'Last name, First M.' (required if creating a row, and row parameter is not specified)
    // id: unique id number or lowercase email (required if creating or updating a row, and row parameter is not specified)
    // user: unique user name (or just copy of the email address)
    // update: [('field1', 'val1'), ...] (list of fields+values to be updated, excluding the unique field 'id')
    // If the special name initTimestamp occurs in the list, the timestamp is initialized when the row is added.
    // If the special name Timestamp occurs in the list, the timestamp is automatically updated on each write.
    // row: ['name_value', 'id_value', 'email_value', 'user_value', null, null, 'field1_value', ...]
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
	    throw('No sheet name specified');

	var validUserToken = '';
	var doc = SpreadsheetApp.openById(SCRIPT_PROP.getProperty("key"));
	if (sheetName == INDEX_SHEET || REQUIRE_LOGIN_TOKEN) {
	    // Restricted sheet/login required
	    if (!params.user)
		throw('Need user name and token for authentication');
	    if (!params.token)
		throw('Need token for authentication');
	    if (!validateHMAC(params.user+':'+params.token, HMAC_KEY))
		throw('Invalid token for authenticating user '+params.user);
	    validUserToken = params.user;
	}
	if (sheetName == INDEX_SHEET) {
	    // Restricted sheet
	    if (params.user != ADMIN_USER)
		throw('Invalid user '+params.user+' for sheet '+sheetName);
	}

	// Check parameter consistency
	var headers = params.headers ? JSON.parse(params.headers) : null;

	var sheet = doc.getSheetByName(sheetName);
	if (!sheet) {
	    // Create new sheet
	    if (!headers)
		throw('Headers must be specified for new sheet '+sheetName);
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
	    if (sheetName == INDEX_SHEET) {
		var protection = sheet.protect().setDescription('protected');
		protection.setUnprotectedRanges([sheet.getRange('E2:F')]);
		protection.setDomainEdit(false);
	    }
	}

	if (!sheet.getLastColumn())
	    throw('No columns in sheet '+sheetName);

	var columnHeaders = sheet.getSheetValues(1, 1, 1, sheet.getLastColumn())[0];
	var columnIndex = indexColumns(sheet);

	if (headers) {
	    if (headers.length > columnHeaders.length)
		throw('Number of headers exceeds that present in sheet '+sheetName);
	    for (var j=0; j<headers.length; j++) {
		if (headers[j] != columnHeaders[j])
		    throw('Column header mismatch: Expected '+headers[j]+' but found '+columnHeaders[j]+' in sheet '+sheetName+'; delete it or edit headers.');
	    }
	}

	var selectedUpdates = params.update ? JSON.parse(params.update) : null;
	var rowUpdates = params.row ? JSON.parse(params.row) : null;

	var getRow = params.get || '';
	var nooverwriteRow = params.nooverwrite || '';

	var userId = null;
	var userName = null;

	if (!rowUpdates && !selectedUpdates && !getRow) {
	    // No row updates
	    returnValues = [];
	} else {
	    if (rowUpdates && selectedUpdates) {
		throw('Cannot specify both rowUpdates and selectedUpdates');
	    } else if (rowUpdates) {
		if (rowUpdates.length > columnHeaders.length)
		    throw('row_headers length exceeds no. of columns in sheet');

		userId = rowUpdates[columnIndex['id']-1] || null;
		userName = rowUpdates[columnIndex['name']-1] || null;
	    } else {
		userId = params.id || null;
		userName = params.name || null;
	    }

	    if (!userId)
		throw('User id must be specified for updates/gets');

	    var numStickyRows = 1;  // Headers etc.
	    var ids = sheet.getSheetValues(1+numStickyRows, columnIndex['id'], sheet.getLastRow(), 1);
	    var userRow = -1;
            for (var j=0; j<ids.length; j++) {
		// Unique ID
		if (ids[j][0] == userId) {
		    userRow = j+1+numStickyRows;
		    break;
		}
	    }
	    //returnMessages.push('DEBUG:userRow, userid: '+userRow+', '+userId);
	    var newRow = (userRow < 0);
	    if (newRow && getRow && !rowUpdates) {
		// Row does not exist; return empty list
		returnValues = [];

	    } else {
		var curDate = new Date();
		var allowLateMods = !REQUIRE_LATE_TOKEN;
		var pastSubmitDeadline = false;
		var dueDate = null;
		var gradeDate = null;
		var fieldsMin = columnHeaders.length;
		if (sheetName != INDEX_SHEET && doc.getSheetByName(INDEX_SHEET)) {
		    // Session parameters
		    var sessionParams = getSessionParams(sheetName, ['dueDate', 'gradeDate', 'fieldsMin']);
		    dueDate = sessionParams.dueDate;
		    gradeDate = sessionParams.gradeDate;
		    fieldsMin = sessionParams.fieldsMin;

		    // Check if past submission deadline
		    var lateToken = (rowUpdates && columnIndex['lateToken']) ? (rowUpdates[columnIndex['lateToken']-1] || null) : null;
		    if (dueDate) {
			var curTime = curDate.getTime();
			pastSubmitDeadline = (dueDate && curTime > dueDate.getTime())
			if (!allowLateMods && pastSubmitDeadline && lateToken) {
			    if (lateToken == 'none') {
				// Late submission without token
				allowLateMods = true;
			    } else if (validateHMAC(params.user+':'+sheetName+':'+lateToken, HMAC_KEY)) {
				dueDate = createDate(splitToken(lateToken)[0]); // Date format: '1995-12-17T03:24Z'
				pastSubmitDeadline = (curTime > dueDate.getTime());
			    } else {
				returnMessages.push('Warning: Invalid token for late submission by user '+params.user+' to session '+sheetName);
			    }
			}
			if (!allowLateMods) {
			    if (pastSubmitDeadline) {
				    if (newRow || selectedUpdates || (rowUpdates && !nooverwriteRow)) {
					// Creating/modifying row; require valid lateToken
					if (!lateToken)
					    throw('Past submit deadline ('+dueDate+') for session '+sheetName+'. (If valid excuse, request late submission token.)')
					else
					    throw('Invalid token for late submission to session '+sheetName);
				    } else {
					returnMessages.push('Warning: Past submit deadline ('+dueDate+') for session '+sheetName+'. (If valid excuse, request authorization token.)');
				    }
			    } else if ( (dueDate.getTime() - curTime) < 2*60*60*1000) {
				returnMessages.push('Warning: Nearing submit deadline ('+dueDate+') for session '+sheetName+'.');
			    }
			}
		    }
		}

		if (newRow) {
		    // New user; insert row in sorted order of name
		    if (!userName || !rowUpdates)
			throw('User name and row parameters required to create a new row for id '+userId);

		    var names = sheet.getSheetValues(1+numStickyRows, columnIndex['name'], sheet.getLastRow(), 1);
		    userRow = sheet.getLastRow()+1;
		    for (var j=0; j<names.length; j++) {
			if (names[j][0] > userName) {
			    userRow = j+1+numStickyRows
			    break;
			}
		    }
		    sheet.insertRowBefore(userRow);
		} else if (rowUpdates && nooverwriteRow) {
		    if (getRow) {
			// Simply return existing row
			rowUpdates = null;
		    } else {
			throw('Do not specify nooverwrite=1 to overwrite existing rows');
		    }
		}

		var maxCol = rowUpdates ? rowUpdates.length : columnHeaders.length;
		var userRange = sheet.getRange(userRow, 1, 1, maxCol);
		var rowValues = userRange.getValues()[0];
	    
		if (rowUpdates) {
		    // Update all non-null and non-id row values
		    // Timestamp is always updated, unless it is specified by admin
		    if (rowUpdates.length > fieldsMin) {
			// Check if there are any non-null values for grade columns
			var nonNullGradeColumn = false;
			for (var j=fieldsMin; j < columnHeaders.length; j++) {
			    if (rowUpdates[j] != null) {
				nonNullGradeColumn = true;
				break;
			    }
			}
			if (nonNullGradeColumn) {
			    // Blank out non-response/explain grade columns if any grade column is non-null
			    for (var j=fieldsMin; j < columnHeaders.length; j++) {
				if (columnHeaders[j].slice(-9) != '_response' && columnHeaders[j].slice(-8) != '_explain')
				    rowUpdates[j] = '';
			    }
			}
			if (columnHeaders[fieldsMin].slice(0,8) == 'q_grades') {
			    // Column to hold sum of all grades
			    var gradedCells = [];
			    for (var j=fieldsMin+1; j < columnHeaders.length; j++) {
				if (/^q(\d+)_grade/.exec(columnHeaders[j]))
				    gradedCells.push(colIndexToChar(j+1) + userRow);
			    }
			    rowUpdates[fieldsMin] = gradedCells.length ? ('=' + gradedCells.join('+')) : '';
			}
		    }
		    for (var j=0; j<rowUpdates.length; j++) {
			var colHeader = columnHeaders[j];
			var colValue = rowUpdates[j];
			if (colHeader == 'Timestamp' && (colValue == null || validUserToken != ADMIN_USER)) {
			    // Timestamp is always updated, unless it is specified by admin
			    rowValues[j] = curDate;
			} else if (colHeader == 'initTimestamp' && newRow) {
			    rowValues[j] = curDate;
			} else if (colValue == null) {
			    // Do not modify field
			} else if (newRow || (colHeader != 'id' && colHeader != 'name' && colHeader != 'initTimestamp') ) {
			    // Id, name, initTimestamp cannot be updated programmatically
			    // (If necessary to change name manually, then re-sort manually)
			    if (colHeader == 'Timestamp' || colHeader.slice(-4).toLowerCase() == 'date' || colHeader.slice(-4).toLowerCase() == 'time') {
				try { colValue = createDate(colValue); } catch (err) {}
			    }
			    rowValues[j] = colValue;
			}
		    }

		} else if (selectedUpdates) {
		    // Update selected row values
		    // Timestamp is updated only if specified in list
		    for (var j=0; j<selectedUpdates.length; j++) {
			var colHeader = selectedUpdates[j][0];
			var colValue = selectedUpdates[j][1];
			
			if (!(colHeader in columnIndex))
			    throw('Field '+colHeader+' not found in sheet');

			var headerColumn = columnIndex[colHeader];
			if (headerColumn > fieldsMin) // Cannot selectively update grade columns
			    continue;
			if (colHeader == 'Timestamp' && (colValue == null || validUserToken != ADMIN_USER)) {
			    // Timestamp is always updated, unless it is specified by admin
			    rowValues[headerColumn-1] = curDate;
			} else if (colValue == null) {
			    // Do not modify field
			} else if (colHeader != 'id' && colHeader != 'name' && colHeader != 'initTimestamp') {
			    // Update row values for header (except for id, name, initTimestamp)
			    if (colHeader == 'Timestamp' || colHeader.slice(-4).toLowerCase() == 'date' || colHeader.slice(-4).toLowerCase() == 'time') {
				try { colValue = createDate(colValue); } catch (err) {}
			    }
			    rowValues[headerColumn-1] = colValue;
			}
		    }
		}
		
		// Save updated row
		if (rowUpdates || selectedUpdates)
		    userRange.setValues([rowValues]);
		returnValues = getRow ? rowValues : [];

		if (!gradeDate && returnValues.length > fieldsMin) {
		    // If session not graded, nullify columns to be graded
		    for (var j=fieldsMin; j < columnHeaders.length; j++)
			returnValues[j] = null;
		}
	    }
	}

	// return json success results
	return ContentService
            .createTextOutput(jsonPrefix+JSON.stringify({"result":"success", "row": returnValues, "messages": returnMessages.join('\n')})+jsonSuffix)
            .setMimeType(mimeType);
    } catch(err){
	// if error return this
	return ContentService
            .createTextOutput(jsonPrefix+JSON.stringify({"result":"error", "error": ''+err, "row": null, "messages": returnMessages.join('\n')})+jsonSuffix)
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

function validateHMAC(token, key) {
    // Validates HMAC token of the form message:signature
    var comps = splitToken(token);
    var message = comps[0];
    var signature = comps[1];
    var rawHMAC = Utilities.computeHmacSignature(Utilities.MacAlgorithm.HMAC_MD5,
						 message, key,
						 Utilities.Charset.US_ASCII);
    var encodedHMAC = Utilities.base64Encode(rawHMAC)
    return signature == encodedHMAC.slice(0,TRUNCATE_DIGEST);
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

function getSessionParams(sessionName, colNames) {
    // Return parameters in list colNames for sessionName from slidoc_sessions sheet
    var doc = SpreadsheetApp.openById(SCRIPT_PROP.getProperty("key"));
    var indexSheet = doc.getSheetByName(INDEX_SHEET);
    if (!indexSheet)
	throw('Index sheet slidoc_sessions not found');
    var indexColIndex = indexColumns(indexSheet);
    var indexRowIndex = indexRows(indexSheet, indexColIndex['id'], 2);
    var sessionRow = indexRowIndex[sessionName];
    var retVals = {};
    for (var j=0; j < colNames.length; j++) {
	if (!(colNames[j] in indexColIndex))
	    throw('Column '+colNames[j]+' not found in session index');
	retVals[colNames[j]] = indexSheet.getSheetValues(sessionRow, indexColIndex[colNames[j]], 1, 1)[0][0];
    }
    return retVals;
}

function sessionAnswerSheet() {
    // Create session answers sheet

    var ui = SpreadsheetApp.getUi();
    var response = ui.prompt('Enter session name', ui.ButtonSet.YES_NO);

    if (response.getSelectedButton() == ui.Button.YES) {
	var sessionName = response.getResponseText();
	if (!sessionName)
	    return;
    } else if (response.getSelectedButton() == ui.Button.NO) {
	return;
    } else {
	return;
    }
 
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

	var sessionParams = getSessionParams(sessionName, ['questions', 'answers']);
	var questions = sessionParams.questions.split(',');
	var answers = sessionParams.answers.split('|');

	// Copy first two columns from session sheet
	var copyCols = 2;
	var answerHeaders = sessionSheet.getSheetValues(1, 1, 1, copyCols)[0];

	var respCols = [];
	var extraCols = ['expect', 'correct', 'test'];
	for (var j=0; j<questions.length; j++) {
	    var qprefix = 'q'+(j+1);
	    var testCode = (questions[j].slice(0,10) == 'text/code=');
	    var inlineJS = /^=(\w+)\(\)/.exec(answers[j]);
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
	    if (answers[j] || testCode)
		answerHeaders.push(qprefix+'_correct');
	    if (testCode)
		answerHeaders.push(qprefix+'_test');
	}
	Logger.log('ansHeaders: '+answerHeaders);
	var ansHeaderCols = {};
	for (var j=0; j<answerHeaders.length; j++)
	    ansHeaderCols[answerHeaders[j]] = j+1;
	 
	// Session answers headers

	// New answers sheet
	var answerSheetName = sessionName+'-answers';
	var answerSheet = doc.getSheetByName(answerSheetName);
	if (!answerSheet)
	    answerSheet = doc.insertSheet(answerSheetName);
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
}


function sessionStatSheet() {
    // Create session stats sheet

    var ui = SpreadsheetApp.getUi();
    var response = ui.prompt('Enter session name', ui.ButtonSet.YES_NO);

    if (response.getSelectedButton() == ui.Button.YES) {
	var sessionName = response.getResponseText();
	if (!sessionName)
	    return;
    } else if (response.getSelectedButton() == ui.Button.NO) {
	return;
    } else {
	return;
    }
 
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

	var sessionParams = getSessionParams(sessionName, ['primary_qconcepts', 'secondary_qconcepts']);
	var p_concepts = sessionParams.primary_qconcepts.split('; ');
	var s_concepts = sessionParams.secondary_qconcepts.split('; ');
	 
	// Session stats headers
	var statHeaders = ['name', 'id', 'Timestamp', 'lateToken', 'lastSlide', 'correct', 'count', 'skipped'];
	for (var j=0; j<p_concepts.length; j++)
	    statHeaders.push('p:'+p_concepts[j]);
	for (var j=0; j<s_concepts.length; j++)
	    statHeaders.push('s:'+s_concepts[j]);
	var nconcepts = p_concepts.length + s_concepts.length;

	// New stat sheet
	var statSheetName = sessionName+'-stats';
	statSheet = doc.getSheetByName(statSheetName);
	if (!statSheet)
	    statSheet = doc.insertSheet(statSheetName);
	statSheet.clear()
	var statHeaderRange = statSheet.getRange(1, 1, 1, statHeaders.length);
	statHeaderRange.setValues([statHeaders]);
	statHeaderRange.setWrap(true);
	statSheet.getRange('1:1').setFontWeight('bold');

	// Session sheet columns
	var startRow = 2;
	var nids = sessionSheet.getLastRow()-1;
	var idCol = sessionColIndex['id'];
	var nameCol = sessionColIndex['name'];
	var timeCol = sessionColIndex['Timestamp'];
	var lateCol = sessionColIndex['lateToken'];
	var lastCol = sessionColIndex['lastSlide'];

	// Stats sheet columns
	var statStartRow = 3; // Leave blank row for formulas
	var statNameCol = 1;
	var statIdCol = 2;
	var statTimeCol = 3;
	var statLateCol = 4;
	var statLastCol = 5;
	var statQuestionCol = 6;
	var nqstats = 3
	var statConceptsCol = statQuestionCol + nqstats;

	statSheet.getRange(statStartRow, statNameCol, nids, 1).setValues(sessionSheet.getSheetValues(startRow, nameCol, nids, 1));
	statSheet.getRange(statStartRow,   statIdCol, nids, 1).setValues(sessionSheet.getSheetValues(startRow,   idCol, nids, 1));
	statSheet.getRange(statStartRow, statTimeCol, nids, 1).setValues(sessionSheet.getSheetValues(startRow, timeCol, nids, 1));
	statSheet.getRange(statStartRow, statLateCol, nids, 1).setValues(sessionSheet.getSheetValues(startRow, lateCol, nids, 1));
	statSheet.getRange(statStartRow, statLastCol, nids, 1).setValues(sessionSheet.getSheetValues(startRow, lastCol, nids, 1));

	var hiddenSessionCol = sessionColIndex['session_hidden'];
	var hiddenVals = sessionSheet.getSheetValues(startRow, hiddenSessionCol, nids, 1);
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
}


function updateScoreSheet() {
    // Update scores sheet

    var ui = SpreadsheetApp.getUi();
    var response = ui.prompt('Enter session name', ui.ButtonSet.YES_NO);

    if (response.getSelectedButton() == ui.Button.YES) {
	var sessionName = response.getResponseText();
	if (!sessionName)
	    return;
    } else if (response.getSelectedButton() == ui.Button.NO) {
	return;
    } else {
	return;
    }
 
    var lock = LockService.getPublicLock();
    lock.waitLock(30000);  // wait 30 seconds before conceding defeat.

    try {
	var doc = SpreadsheetApp.openById(SCRIPT_PROP.getProperty("key"));
	var sessionSheet = doc.getSheetByName(sessionName);
	if (!sessionSheet)
	    throw('Sheet not found '+sessionName);
	if (!sessionSheet.getLastColumn())
	    throw('No columns in sheet '+sessionName);
	if (sessionSheet.getLastRow() < 2)
	    throw('No data rows in sheet '+sessionName);

	var sessionColIndex = indexColumns(sessionSheet);

	var sessionParams = getSessionParams(sessionName, ['scoreWeight', 'gradeWeight']);
	var scoreWeight = parseNumber(sessionParams.scoreWeight) || 0;
	var gradeWeight = parseNumber(sessionParams.gradeWeight) || 0;

	var sessionStartRow = 2;
	var scoreStartRow = 2;

	// New score sheet
	var scoreHeaders = ['name', 'id', 'email', 'user'];
	var scoreSheetName = 'scores';
	scoreSheet = doc.getSheetByName(scoreSheetName);
	if (!scoreSheet) {
	    scoreSheet = doc.insertSheet(scoreSheetName);
	    // Session scores headers

	    var nidsSession = sessionSheet.getLastRow()-sessionStartRow+1;
	    scoreSheet.getRange(1, 1, 1, scoreHeaders.length).setValues(sessionSheet.getSheetValues(1, 1, 1, scoreHeaders.length));
	    scoreSheet.getRange(scoreStartRow, 1, nidsSession, scoreHeaders.length).setValues(sessionSheet.getSheetValues(sessionStartRow, 1, nidsSession, scoreHeaders.length));
	    scoreSheet.getRange('1:1').setFontWeight('bold');
	}

	// Session sheet columns
	var idCol = sessionColIndex['id'];
	var lateCol = sessionColIndex['lateToken'];
	var correctCol = sessionColIndex['questionsCorrect'];

	var idColChar = colIndexToChar( idCol );
	var correctColChar = colIndexToChar( correctCol );

	var scoreColHeaders = scoreSheet.getSheetValues(1, 1, 1, scoreSheet.getLastColumn())[0];
	var scoreColIndex = indexColumns(scoreSheet);
	var scoreSessionCol;
	if (sessionName in scoreColIndex) {
	    scoreSessionCol = scoreColIndex[sessionName];
	} else {
	    scoreSessionCol = 0;
	    for (var jcol=1; jcol<=scoreColHeaders.length; jcol++) {
		var colHeader = scoreColHeaders[jcol-1];
		if (colHeader != 'name' && colHeader != 'id' && colHeader != 'email' && colHeader != 'user' &&
		    colHeader.slice(0,1) != '_' && sessionName < colHeader) {
		    // Insert new session columns in sorted order
		    scoreSheet.insertColumnBefore(jcol);
		    scoreSessionCol = jcol;
		    break;
		}
	    }
	    if (!scoreSessionCol)
		scoreSessionCol = scoreColHeaders.length + 1;
	    scoreSheet.getRange(1, scoreSessionCol, 1, 1).setValues([[sessionName]]);

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
		scoreFormulas.push(['=IF('+vlookup('lateToken', j+scoreStartRow)+'="none", "", ('+scoreWeight+'*'+ vlookup('sessionScore', j+scoreStartRow)+'+100*'+vlookup('q_grades_'+gradeWeight, j+scoreStartRow)+')/('+scoreWeight+'+'+gradeWeight + ') )']);
	    } else if (scoreWeight) {
		scoreFormulas.push(['=IF('+vlookup('lateToken', j+scoreStartRow)+'="none", "", '+ vlookup('sessionScore', j+scoreStartRow) + ')']);
	    }
	}

	if (scoreFormulas.length)
	    scoreSheet.getRange(scoreStartRow, scoreSessionCol, nids, 1).setValues(scoreFormulas)


    } finally { //release lock
	lock.releaseLock();
    }
}
