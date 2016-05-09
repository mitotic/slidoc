// Create sheet with grades for all sessions
// To install this script:
// Click on Tools > Script Editor, creating the script Gradesheet.gs.
//     Overwrite the template code with this code and Save.

var SCRIPT_PROP = PropertiesService.getScriptProperties(); // new property service

function updateGradeSheet() {
    // Update grades sheet

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

	var sessionStartRow = 2;
	var gradeStartRow = 3; // Leave blank row for formulas

	// New grade sheet
	var gradeSheetName = 'grades';
	gradeSheet = doc.getSheetByName(gradeSheetName);
	if (!gradeSheet) {
	    gradeSheet = doc.insertSheet(gradeSheetName);
	    // Session grades headers
	    var gradeHeaders = ['name', 'id', 'email', 'user'];

	    var nidsSession = sessionSheet.getLastRow()-sessionStartRow+1;
	    gradeSheet.getRange(1, 1, 1, gradeHeaders.length).setValues(sessionSheet.getSheetValues(1, 1, 1, gradeHeaders.length));
	    gradeSheet.getRange(gradeStartRow, 1, nidsSession, gradeHeaders.length).setValues(sessionSheet.getSheetValues(sessionStartRow, 1, nidsSession, gradeHeaders.length));
	}

	// Session sheet columns
	var idCol = sessionColIndex['id'];
	var lateCol = sessionColIndex['lateToken'];
	var countCol = sessionColIndex['questionsCount'];
	var correctCol = sessionColIndex['questionsCorrect'];

	var idColChar = colIndexToChar( idCol );
	var correctColChar = colIndexToChar( correctCol );

	var gradeColHeaders = gradeSheet.getSheetValues(1, 1, 1, gradeSheet.getLastColumn())[0];
	var gradeColIndex = indexColumns(gradeSheet);
	var gradeSessionCol;
	if (sessionName in gradeColIndex) {
	    gradeSessionCol = gradeColIndex[sessionName];
	} else {
	    gradeSessionCol = gradeColHeaders.length + 1;
	    gradeSheet.getRange(1, gradeSessionCol, 1, 1).setValues([[sessionName]]);
	}
	var nids = gradeSheet.getLastRow()-gradeStartRow+1;

	var formula1 = 'VLOOKUP($'+idColChar;
	var formula2 = ','+sessionName+'!$'+idColChar+'$'+sessionStartRow+':$'+correctColChar+',';
	var formula3 = ',false)'
	var gradeFormulas = [];
	for (var j=0; j<nids; j++) {
	    gradeFormulas.push(['='+formula1+(j+gradeStartRow)+formula2+(correctCol-idCol+1)+formula3]);
	}

	gradeSheet.getRange(gradeStartRow, gradeSessionCol, nids, 1).setValues(gradeFormulas)


    } finally { //release lock
	lock.releaseLock();
    }
}

function colIndexToChar(col) {
    return String.fromCharCode('A'.charCodeAt(0) + (col-1) );
}
