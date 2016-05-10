// Create sheet with scores for all sessions
// To install this script:
// Click on Tools > Script Editor, creating the script Scoresheet.gs.
//     Overwrite the template code with this code and Save.
//
// Use the menu item "Update scores for session" to run this script and update score for a particular session
// in the 'scores' sheet (which is automatically created, if need be)
//
// You may also create the 'scores' sheet yourself:
//   - Put headers in the first row. The first four are usually 'name', 'id', 'email', 'user'
//   - 'id' is the only required column, which should be unique for each user and used to index sessions
//   - Any custom header names should begin with an underscore, to avoid being mistaken for session names

var SCRIPT_PROP = PropertiesService.getScriptProperties(); // new property service

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

	var sessionParams = getSessionParams(sessionName, ['questionsMax']);
	var questionsMax = 0;
	try { questionsMax = parseInt(sessionParams.questionsMax); } catch(err) {}

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
	    if (questionsMax)
		scoreFormulas.push(['=IF('+vlookup('lateToken', j+scoreStartRow)+'="none", "", '+ vlookup('sessionScore', j+scoreStartRow) + ')']);
	}

	scoreSheet.getRange(scoreStartRow, scoreSessionCol, nids, 1).setValues(scoreFormulas)


    } finally { //release lock
	lock.releaseLock();
    }
}

function colIndexToChar(col) {
    return String.fromCharCode('A'.charCodeAt(0) + (col-1) );
}
