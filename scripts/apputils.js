// Google Apps script for Slidoc utility functions
// https://script.google.com

var SLIDOC_SHARED_ROOT = 'slidoc_shared';

function doGet(evt) {
    return doBoth(evt);
}

function doPost(evt) {
    return doBoth(evt, true);
}

function doBoth(evt, postMethod) {
    try {
	var params = evt.parameter;
	Logger.log(params);
	var retval = null;
	var action = params.action;
	if (!action)
	    throw('No action specified');
	if (action == 'mail_send') {
	    retval = sendMail(params);
	} else if (action.match(/^file_/)) {
	    retval = sharedFile(params);
	} else {
	    throw('Invalid action: '+params.action);
	}
	var retobj = {'result':'success', 'value': retval};

    } catch(err) {
	Logger.log(err);
	retobj = {'result':'error', 'error': err+'', 'errtrace': ''+(err.stack||''),
		  'data':JSON.stringify(params)};
    }
    return ContentService.createTextOutput(JSON.stringify(retobj)).setMimeType(ContentService.MimeType.JSON);
}

function sendMail(params) {
    // params:
    //   to: dest@example.com
    //   subject:
    //   content:
    // Returns informative message
    var toAddr = params.to;
    var subject = params.subject || '';
    var content = params.content || '';
    MailApp.sendEmail(toAddr, subject, content);
    return 'Sent mail to '+toAddr;
}

function sharedFile(params) {
    // Create/delete/lock shared Docs in My Drive/slidoc_shared
    // params:
    // action: file_create/file_delete/file_lock
    // path: domain/site/session/session_team1
    //    OR domain/site/session/
    //    (paths ending in / are treated as folders)
    // type: 'text' (default)
    // content: text
    // editors: a@b.c,...
    // Return file Id for file_create, or informative message otherwise
    var filePath = params.path;
    var pathComps = (SLIDOC_SHARED_ROOT+'/'+filePath).split('/');

    var parentFolder = DriveApp.getRootFolder();
    for (var j=0; j<pathComps.length-1; j++) {
	if (!pathComps[j])
	    continue;
	try {
	    var innerFolder = parentFolder.getFoldersByName(pathComps[j]).next();
	    var innerName = innerFolder.getName(); // Needed to trigger error
	    parentFolder = innerFolder;
	} catch(err) {
	    parentFolder = parentFolder.createFolder(pathComps[j]);
	}
    }

    var mimeType = MimeType.PLAIN_TEXT;
    if (params.type) {
	// Implement different file types here
    }
    var lastPathComp = pathComps[pathComps.length-1];
    var msg = '';
    var action = params.action;
    if (action == 'file_create') {
	if (!lastPathComp)
	    throw('createdoc: No file name');
	var fileContent = params.content || '';
	var fileEditors = params.editors;

	try {
	    // Look for existing document
	    var newFile = parentFolder.getFilesByName(lastPathComp).next();
	    var fileId = newFile.getId(); // Needed to trigger error
	} catch(err) {
	    // Create new document
	    var newDoc = DocumentApp.create(lastPathComp);
	    if (fileEditors) {
		newDoc.addEditors(fileEditors.split(','));
	    }
	    fileId = newDoc.getId();
	    newFile = DriveApp.getFileById(fileId);
	    parentFolder.addFile(newFile);
	    DriveApp.getRootFolder().removeFile(newFile);
	    if (fileContent) {
		try {
		    var docText = newDoc.getBody().editAsText();
		    docText.appendText(fileContent);
		} catch(err2) {
		}
	    }
	    ///newFile.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.EDIT);
	}
	newFile.setShareableByEditors(false);
	return fileId;

    } else if (action == 'file_delete' || action == 'file_lock') {
	if (lastPathComp) {
	    // Select named file
	    var fileList = parentFolder.getFilesByName(lastPathComp);
	} else if (pathComps.length > 1) {
	    // Path ends in '/'
	    if (action == 'file_delete') {
		// Delete entire folder
		fileList = null;
		parentFolder.setTrashed(true)
	    } else {
		// Select all files in folder to lock
		fileList = parentFolder.getFiles();
	    }
	} else {
	    throw('No files for '+action+' operation');
	}
	var fileNames = [];
	var editorNames = [];
	while (fileList && fileList.hasNext()) {
	    var nextFile = fileList.next();
	    fileNames.push(nextFile.getName());
	    if (action == 'file_delete') {
		nextFile.setTrashed(true);
	    } else if (action == 'file_lock') {
		var editors = nextFile.getEditors();
		for (var k=0; k<editors.length; k++) {
		    var nextEditor = editors[k];
		    editorNames.push(nextEditor.getEmail());
		    nextFile.removeEditor(nextEditor);
		    nextFile.addViewer(nextEditor);
		}
	    nextFile.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
	    }
	}
	return action + ' files '+ fileNames.join(',') + ' ' + editorNames.join(',');
    } else {
	throw('Invalid file action '+action);
    }
 
}
