// Create sheet with session answers
// To install this script:
// Click on Tools > Script Editor, creating the script Answers.gs.
//     Overwrite the template code with this code and Save.
//
// Use the menu item "Display session answers" to run this script and create/overwrite the sheet
// 'sessionName-answers' displaying all the answers


var SCRIPT_PROP = PropertiesService.getScriptProperties(); // new property service

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
	var extraCols = ['expect', 'correct', 'text'];
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
