// http://railsrescue.com/blog/2015-05-28-step-by-step-setup-to-send-form-data-to-google-sheets/
// https://gist.github.com/mhawksey/1276293

// Sending form data to Google Sheets
//  1. Navigate to drive.google.com and click on NEW > Google Sheets to create a new Sheet.
//     Enter column headings in the first row.
//
//  2. Click on Tools > Script Editor, creating the script Code.gs.
//     Overwrite the template code with this code and Save.
//
//  3. Run > setup. Click on the right-pointing triangle to its left to run this function.
//     It should show 'Running function setup’ and then put up a dialog 'Authorization Required’.
//     Click on Continue. In the next dialog 'Request for permission - Formscript would like to’ click on Accept.
//
//  4. In the menus click on File > Manage Versions… We must save a version of the script for it to be called.
//     In the box labeled 'Describe what has changed’ type 'Initial version’ and click on 'Save New Version’, then on 'OK’.
//
//  5. Resources > Current project’s triggers.
//     In this dialog click on 'No triggers set up. Click here to add one now’.
//     In the dropdowns select 'doPost’, 'From spreadsheet’, and 'On form submit’, then click on 'Save’.
// 
//  6. click on Publish > Deploy as web app… For 'Who has access to the app:’ select 'Anyone, even anonymous’.
//     Leave 'Execute the app as:’ set to 'Me’ and Project Version to '1’. Click the 'Deploy’ button.
//    - enter Project Version name and click 'Save New Version'
//
//  7. This project is now deployed as a web app. Copy the 'Current web app URL' from the dialog,
//     and paste it in your form/script action.
//
//  8. Insert column names on your destination sheet matching the parameter names of the data you are passing in (exactly matching case)

var HMAC_KEY = 'testkey';   // Set this value for secure administrative access to session index

var REQUIRE_LOGIN_TOKEN = true;
var REQUIRE_LATE_TOKEN = true;

var TRUNCATE_DIGEST = 8;
var SCRIPT_PROP = PropertiesService.getScriptProperties(); // new property service
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
    // headers: ['name', 'id', 'email', 'Timestamp', 'field1', ...] (name and id required for sheet creation)
    // update: [('field1', 'val1'), ...] (list of fields+values to be updated, excluding the unique field 'id')
    // If the special name Timestamp occurs in the list, the timestamp is automatically updated.
    // row: ['name_value', 'id_value', 'email_value', null, 'field1_value', ...]
    //       null value implies no update (except for Timestamp)
    // get: true to retrieve row (id must be specified) (otherwise only [] is returned on success)
    // id: unique id  (required if creating or updating a row, and row parameter is not specified)
    // name: sortable name (required if creating a row, and row parameter is not specified)
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
	var allowLateMods = !REQUIRE_LATE_TOKEN;
	var pastSubmitDeadline = false;
	var dueDate = null;
	var doc = SpreadsheetApp.openById(SCRIPT_PROP.getProperty("key"));
	if (sheetName == 'slidoc_sessions' || REQUIRE_LOGIN_TOKEN) {
	    // Restricted sheet/login required
	    if (!params.user)
		throw('Need user name and token for authentication');
	    if (!params.token)
		throw('Need token for authentication');
	    if (!validateHMAC(params.user+':'+params.token, HMAC_KEY))
		throw('Invalid token for authenticating user '+params.user);
	    validUserToken = params.user;
	}
	if (sheetName == 'slidoc_sessions') {
	    // Restricted sheet
	    if (params.user != 'admin')
		throw('Invalid user '+params.user+' for sheet '+sheetName);
	} else if (doc.getSheetByName('slidoc_sessions')) {
	    // Creating/updating row in session; check if past submission deadline
	    var sessionParams = getSessionParams(sheetName, ['dueDate']);
	    dueDate = sessionParams.dueDate;
	    if (dueDate) {
		var curTime = (new Date()).getTime();
		pastSubmitDeadline = (dueDate && curTime > dueDate.getTime())
		if (!allowLateMods && pastSubmitDeadline && params.writetoken) {
		    if (params.writetoken.slice(0,4).toLowerCase() == 'none') {
			// Late submission without token
			allowLateMods = true;
		    } else if (validateHMAC(params.user+':'+sheetName+':'+params.writetoken, HMAC_KEY)) {
			dueDate = createDate(splitToken(params.writetoken)[0]); // Date format: '1995-12-17T03:24Z'
			pastSubmitDeadline = (curTime > dueDate.getTime());
		    } else {
			returnMessages.push('Warning: Invalid token for late submission by user '+params.user+' to session '+sheetName);
		    }
		}
		if (!allowLateMods) {
		    if (pastSubmitDeadline) {
			returnMessages.push('Warning: Past submit deadline ('+dueDate+') for session '+sheetName+'. (If valid excuse, request authorization token.)');
		    } else if ( (dueDate.getTime() - curTime) < 2*60*60*1000) {
			returnMessages.push('Warning: Nearing submit deadline ('+dueDate+') for session '+sheetName+'.');
		    }
		}
	    }
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
	    for (var j=0; j<headers.length; j++) {
		if (headers[j].slice(-6).toLowerCase() == 'hidden')
		    sheet.hideColumns(j+1);
	    }
	}

	if (!sheet.getLastColumn())
	    throw('No columns in sheet '+sheetName);

	var columnHeaders = sheet.getSheetValues(1, 1, 1, sheet.getLastColumn())[0];
	var columnIndex = {};
	for (var j=0; j<columnHeaders.length; j++)
	    columnIndex[columnHeaders[j]] = j;

	if (headers) {
	    if (headers.length > columnHeaders.length)
		throw('Number of headers exceeds that present in sheet '+sheetName);
	    for (var j=0; j<headers.length; j++) {
		if (headers[j] != columnHeaders[j])
		    throw('Column header mismatch: '+headers[j]+' vs. '+columnHeaders[j]+' in sheet '+sheetName);
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

		userId = rowUpdates[columnIndex['id']] || null;
		userName = rowUpdates[columnIndex['name']] || null;
	    } else {
		userId = params.id || null;
		userName = params.name || null;
	    }

	    if (!userId)
		throw('User id must be specified for updates/gets');

	    var numStickyRows = 1;  // Headers etc.
	    var ids = sheet.getSheetValues(1+numStickyRows, columnIndex['id']+1, sheet.getLastRow(), 1);
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

	    } else if (!allowLateMods && pastSubmitDeadline && (newRow || selectedUpdates || (rowUpdates && !nooverwriteRow)) ) {
		// Creating/modifying row; require 
		if (!params.writetoken)
		    throw('Past submit deadline ('+dueDate+') for session '+sheetName+'. (If valid excuse, request late submission token.)')
		else
		    throw('Invalid token for late submission to session '+sheetName);

	    } else {
		if (newRow) {
		    // New user; insert row in sorted order of name
		    if (!userName || !rowUpdates)
			throw('User name and row parameters required to create a new row for id '+userId);

		    var names = sheet.getSheetValues(1+numStickyRows, columnIndex['name']+1, sheet.getLastRow(), 1);
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
		    // Timestamp is always updated, unless it is specified
		    for (var j=0; j<rowUpdates.length; j++) {
			var colHeader = columnHeaders[j];
			var colValue = rowUpdates[j];
			if (colValue == null) {
			    if (colHeader == 'Timestamp')
				rowValues[j] = new Date();
			} else if (newRow || (colHeader != 'id' && colHeader != 'name') ) {
			    // Id and name cannot be updated programmatically
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
			if (colValue == null) {
			    if (colHeader == "Timestamp")
				rowValues[headerColumn] =  new Date();
			} else if (colHeader != 'id' && colHeader != 'name') {
			    // Update row values for header (except for id and name)
			    if (colHeader == 'Timestamp' || colHeader.slice(-4).toLowerCase() == 'date' || colHeader.slice(-4).toLowerCase() == 'time') {
				try { colValue = createDate(colValue); } catch (err) {}
			    }
			    rowValues[headerColumn] = colValue;
			}
		    }
		}
		
		// Save updated row
		if (rowUpdates || selectedUpdates)
		    userRange.setValues([rowValues]);
		returnValues = getRow ? rowValues : [];
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

function splitToken(token) {
    var match = RegExp('^(.+):([^:]+)$').exec(token);
    if (!match)
	throw('Invalid HMAC token; no colon');    
    return [match[1], match[2]];
}

function createDate(dateStr) {
    // Ensure that UTC date string ends in :00.000Z (needed to workaround bug in Google Apps)
    if (dateStr.slice(-1) == 'Z') {
	if (dateStr.length == 17)      // yyyy-mm-ddThh:mmZ
	    dateStr = dateStr.slice(0,-1) + ':00.000Z';
	else if (dateStr.length == 20) // yyyy-mm-ddThh:mm:ssZ
	    dateStr = dateStr.slice(0,-1) + '.000Z';
    }
    return new Date(dateStr);
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

