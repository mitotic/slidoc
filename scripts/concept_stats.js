// Create sheet with concept statistics

var SCRIPT_PROP = PropertiesService.getScriptProperties(); // new property service

 // The onOpen function is executed automatically every time a Spreadsheet is loaded
 function onOpen() {
   var ss = SpreadsheetApp.getActiveSpreadsheet();
   var menuEntries = [];
   menuEntries.push({name: "Generate concept stats", functionName: "conceptStatsSheet"});
   menuEntries.push(null); // line separator

   ss.addMenu("Slidoc", menuEntries);
 }
 

function conceptStatsSheet() {
    // Create concept stats  sheet

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

	indexSheet = doc.getSheetByName('sessions');
	if (!indexSheet)
	    throw('Index sheet sessions not found');
	var indexColIndex = indexColumns(indexSheet);
	var indexRowIndex = indexRows(indexSheet, indexColIndex['id'], 2);
	var sessionRow = indexRowIndex[sessionName];

	var p_concepts = indexSheet.getSheetValues(sessionRow, indexColIndex['primary_qconcepts'], 1, 1)[0][0].split('; ');
	var s_concepts = indexSheet.getSheetValues(sessionRow, indexColIndex['secondary_qconcepts'], 1, 1)[0][0].split('; ');
	
	// Concept headers
	var statHeaders = ['name', 'id'];
	for (var j=0; j<p_concepts.length; j++)
	    statHeaders.push('p:'+p_concepts[j]);
	for (var j=0; j<s_concepts.length; j++)
	    statHeaders.push('s:'+s_concepts[j]);
	var nconcepts = p_concepts.length + s_concepts.length;

	// New stat sheet
	var statSheetName = sessionName+'-concepts';
	statSheet = doc.getSheetByName(statSheetName);
	if (!statSheet)
	    statSheet = doc.insertSheet(statSheetName);
	statSheet.clear()
	var statHeaderRange = statSheet.getRange(1, 1, 1, statHeaders.length);
	statHeaderRange.setValues([statHeaders]);
	statHeaderRange.setWrap(true);

	var nids = sessionSheet.getLastRow()-1;
	var idCol = sessionColIndex['id'];
	var nameCol = sessionColIndex['name'];
	statSheet.getRange(3, 1, nids, 1).setValues(sessionSheet.getSheetValues(2, nameCol, nids, 1));
	statSheet.getRange(3, 2, nids, 1).setValues(sessionSheet.getSheetValues(2, idCol, nids, 1));
	var hiddenSessionCol = sessionColIndex['session_hidden'];
	var hiddenSessionCol = sessionColIndex['session_hidden'];
	var hiddenVals = sessionSheet.getSheetValues(2, hiddenSessionCol, nids, 1);
	var conceptTallies = [];
	for (var j=0; j<hiddenVals.length; j++) {
	    var jsonSession = Utilities.newBlob(Utilities.base64Decode(hiddenVals[j][0])).getDataAsString();
	    var savedSession = JSON.parse(jsonSession);
	    var missedFraction = [];
	    var missedConcepts = savedSession.missedConcepts;
	    for (var m=0; m<2; m++)
		for (var k=0; k<missedConcepts[m].length; k++)
		    missedFraction.push(missedConcepts[m][k][0]/Math.max(1,missedConcepts[m][k][1]));
	    conceptTallies.push(missedFraction);
	}
	statSheet.getRange(3, 3, conceptTallies.length, nconcepts).setValues(conceptTallies);
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
