// Create sheet with session statistics
// To install this script:
// Click on Tools > Script Editor, creating the script Stats.gs.
//     Overwrite the template code with this code and Save.
// Resources > Current project’s triggers.
//     In the dropdowns select 'onOpen’, 'From spreadsheet’, and 'On Open’, then click on 'Save’.

var SCRIPT_PROP = PropertiesService.getScriptProperties(); // new property service

 // The onOpen function is executed automatically every time a Spreadsheet is loaded
 function onOpen() {
   var ss = SpreadsheetApp.getActiveSpreadsheet();
   var menuEntries = [];
   menuEntries.push({name: "Generate session stats", functionName: "sessionStatsSheet"});
   menuEntries.push(null); // line separator

   ss.addMenu("Slidoc", menuEntries);
 }
 

function sessionStatsSheet() {
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
    var indexSheet = doc.getSheetByName('slidoc_sessions');
    if (!indexSheet)
	throw('Index sheet slidoc_sessions not found');
    var indexColIndex = indexColumns(indexSheet);
    var indexRowIndex = indexRows(indexSheet, indexColIndex['id'], 2);
    var sessionRow = indexRowIndex[sessionName];
    var retVals = {};
    for (var j=0; j < colNames.length; j++) {
	retVals[colNames[j]] = indexSheet.getSheetValues(sessionRow, indexColIndex[colNames[j]], 1, 1)[0][0];
    }
    return retVals;
}
