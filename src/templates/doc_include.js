// JS include file for slidoc

///////////////////////////////
// Section 1: Configuration
///////////////////////////////

var Slidoc = {};  // External object

Slidoc.PluginDefs = {};    // JS plugin definitions
Slidoc.Plugins = {};       // Plugin global and slide instances
Slidoc.PluginManager = {}; // JS plugins manager
Slidoc.Random = null;
Slidoc.version = '';

///UNCOMMENT: (function(Slidoc) {

var MAX_INC_LEVEL = 9;            // Max. incremental display level
var MIN_ANSWER_NOTES_DELAY = 5;   // Minimum delay (sec) when displaying notes after answering question
var MAX_SYS_ERROR_RETRIES = 5;    // Maximum number of system error retries

var CACHE_GRADING = true; // If true, cache all rows for grading

var QTYPE_RE    = /^([a-zA-Z][\w-]*)(\/(.*))?$/;
var FORMULA_RE  = /^(.*)=\s*([^;]+)(;;\s*([()eE0-9.*+/-]*))?\s*$/
var QFIELD_RE   = /^q(\d+)_([a-z]+)$/;
var SLIDE_ID_RE = /(slidoc(\d+))(-(\d+))?$/;

var COPY_HEADERS = ['source', 'team', 'lateToken', 'lastSlide', 'retakes'];

var BASIC_PACE    = 1;
var QUESTION_PACE = 2;
var ADMIN_PACE    = 3;

Slidoc.PluginManager.BASIC_PACE    = 1;  // Move to Slidoc.BASIC_PACE ...?
Slidoc.PluginManager.QUESTION_PACE = 2;
Slidoc.PluginManager.ADMIN_PACE    = 3;

var SKIP_ANSWER = 'skip';

var LATE_SUBMIT = 'late';

var SYMS = {correctMark: '&#x2714;', partcorrectMark: '&#x2611;', wrongMark: '&#x2718;', anyMark: '&#9083;', xBoxMark: '&#8999;',
	    xMark: '&#x2A2F', letters: '&#x1f520;'};

var uagent = navigator.userAgent.toLowerCase();
var isSafari = (/safari/.test(uagent) && !/chrome/.test(uagent));
var isHeadless = /Qt/.test(navigator.userAgent) ; // Detects "headless" wkhtmltopdf browser
var useJSONP = (location.protocol == 'file:' || isSafari) && !isHeadless;

if (!Function.prototype.bind) {
  // bind implementation for old WebKit used by wkhtmltopdf
  Function.prototype.bind = function(oThis) {
    if (typeof this !== 'function') {
      // closest thing possible to the ECMAScript 5
      // internal IsCallable function
      throw new TypeError('Function.prototype.bind - what is trying to be bound is not callable');
    }

    var aArgs   = Array.prototype.slice.call(arguments, 1),
        fToBind = this,
        fNOP    = function() {},
        fBound  = function() {
          return fToBind.apply(this instanceof fNOP && oThis
                 ? this
                 : oThis,
                 aArgs.concat(Array.prototype.slice.call(arguments)));
        };

    fNOP.prototype = this.prototype;
    fBound.prototype = new fNOP();

    return fBound;
  };
}

function getParameter(name, number, queryStr) {
   // Set number to true, if expecting an integer value. Returns null if valid parameter is not present.
   // If queryStr is specified, it is used instead of location.search
   var match = RegExp('[?&]'+name+'=([^&]*)').exec(queryStr || window.location.search);
   if (!match)
      return null;
   var value = decodeURIComponent(match[1].replace(/\+/g, ' '));
   if (number) {
       try { value = parseInt(value); } catch (err) { value = null };
   }
   return value;
}

/////////////////////////////////////
// Section 2: Global initialization
/////////////////////////////////////

var Sliobj = {}; // Internal object
Sliobj.remoteVersion = '';
Sliobj.logSheet = null;

Sliobj.params = JS_PARAMS_OBJ;
Slidoc.version = JS_PARAMS_OBJ.version || '';

Sliobj.sitePrefix = Sliobj.params.siteName ? '/'+Sliobj.params.siteName : '';
Sliobj.sessionName = Sliobj.params.paceLevel ? Sliobj.params.fileName : '';
Sliobj.sessionLabel = (!Sliobj.params.fileName && Sliobj.params.sessionType) ? Sliobj.params.sessionType+'/index' : Sliobj.params.fileName;

Sliobj.gradeFieldsObj = {};
for (var j=0; j<Sliobj.params.gradeFields.length; j++)
    Sliobj.gradeFieldsObj[Sliobj.params.gradeFields[j]] = 1;

Sliobj.ajaxRequestActive = null;
Sliobj.interactiveMessages = [];

Sliobj.showHiddenSlides = false;
Sliobj.interactiveMode = false;
Sliobj.interactiveSlide = false;
Sliobj.gradableState = null;
Sliobj.firstTime = true;
Sliobj.closePopup = null;
Sliobj.popupEvent = '';
Sliobj.popupQueue = [];
Sliobj.activePlugins = {};
Sliobj.pluginNames = [];
Sliobj.setupPluginDict = null;
Sliobj.setupPluginList = [];
Sliobj.globalPluginDict = null;
Sliobj.globalPluginList = [];
Sliobj.slidePluginDict = null;
Sliobj.slidePluginList = {};
Sliobj.answerPlugins = null;
Sliobj.incrementPlugins = {};
Sliobj.buttonPlugins = null;
Sliobj.delaySec = null;
Sliobj.scores = null;
Sliobj.liveResponses = {};
Sliobj.choiceBlockHTML = {};

Sliobj.origSlideText = null;

Sliobj.testOverride = null;

Sliobj.errorRetries = 0;

Sliobj.seedOffset = {randomChoice: 1, randomParams: 2, plugins: 1000};  // Used to offset the session randomSeed to generate new seeds

////////////////////////////////
// Section 3: Scripted testing
////////////////////////////////

Sliobj.testScript = null;
Sliobj.testStep = getParameter('teststep');

Slidoc.enableTesting = function(activeScript, scripts) {
    if (Slidoc.TestScript)
	Sliobj.testScript = new Slidoc.TestScript(activeScript, scripts);
}
Slidoc.reportTestAction = function (actionName) {
    if (Sliobj.testScript)
	return Sliobj.testScript.reportTestAction(actionName);
    return null;
}
Slidoc.testingActive = function () {
    return Sliobj.testScript && Sliobj.testScript.activeScript;
}
Slidoc.advanceStep = function () {
    if (Sliobj.testStep && Sliobj.testScript && Sliobj.testScript.stepEvent)
	return Sliobj.testScript.advanceStep();
    return false;
}

///////////////////////////////
// Section 4: Console logging
///////////////////////////////

Sliobj.logMax = 200;
Sliobj.logQueue = [];
Sliobj.logRe = null;

Slidoc.logMatch = function (regexp) {
    Sliobj.logRe = regexp || null;
}

Slidoc.logDump = function (regexp) {
    for (var j=0; j<Sliobj.logQueue.length; j++) {
	// Cannot use JSON.stringify(args) due to possible circular references
	var args = [''+Sliobj.logQueue[j]];
	if (!regexp || regexp.exec(args[0])) {
	    args[0] = (regexp ? '+ ':'- ') + args[0];
	    console.log.apply(console, args);
	}
    }
    if (!regexp)
	Sliobj.logQueue = [];
}

Slidoc.logRecursive = 0;

Slidoc.log = function() {
    if (isHeadless) {
	var msg = '';
	for (var j=0; j<arguments.length; j++)
	    msg += arguments[j];
	console.log(msg);
	return;
    }
    var debugging = Sliobj.params.debug || Sliobj.gradableState || getUserId() == Sliobj.params.testUserId;
    if (debugging) {
	console.log.apply(console, arguments);
    }
    
    var args = Array.prototype.slice.call(arguments);
    var match   = /^([\.\w]+)(:\s*|\s+|$)(ERROR|WARNING)?/i.exec(''+arguments[0]);
    var errMsg  = match && match[3] && match[3].toUpperCase() == 'ERROR';
    var warnMsg = match && match[3] && match[3].toUpperCase() == 'WARNING';

    if (errMsg && !Slidoc.logRecursive && Sliobj.params.remoteLogLevel >= 1) {
	// Cannot use JSON.stringify(args) due to possible circular references
	Slidoc.logRecursive += 1;
	Slidoc.remoteLog(match[1], 'ERROR', ''+args, '');
	Slidoc.logRecursive -= 1;
    }
    
    if (debugging)
	return;

    if (errMsg) {
	Slidoc.logDump();
    } else  {
	Sliobj.logQueue.push(''+args);
	if (Sliobj.logQueue.length > Sliobj.logMax)
	    Sliobj.logQueue.shift();
    }
    if ( (Sliobj.logRe && Sliobj.logRe.exec(''+arguments[0])) || !match || errMsg || warnMsg)
	console.log.apply(console, arguments);
}

/////////////////////////////////////////
// Section 5: Remote spreadsheet access
/////////////////////////////////////////

Slidoc.sheetIsLocked = function () {
    if (window.GService)
	return GService.sheetIsLocked();
    else
	return '';
}

Sliobj.sheets = {};

function getSheet(name) {
    if (!window.GService)
	return null;
    
    if (Sliobj.sheets[name])
	return Sliobj.sheets[name];

    var fields = Sliobj.params.sessionFields;
    if (name == Sliobj.params.fileName)
	fields = fields.concat(Sliobj.params.gradeFields);
    try {
	Sliobj.sheets[name] = new GService.GoogleSheet(Sliobj.params.gd_sheet_url, name,
						       Sliobj.params.sessionFields.slice(0,4),
						       Sliobj.params.sessionFields.slice(4).concat(Sliobj.params.gradeFields),
						       useJSONP);
    } catch(err) {
	sessionAbort(''+err, err.stack);
    }
    return Sliobj.sheets[name];
}


function setupCache(auth, callback) {
    // Cache all rows for grading
    Slidoc.log('setupCache:', auth);
    var gsheet = getSheet(Sliobj.sessionName);
    function allCallback(allRows, retStatus) {
	Slidoc.log('allCallback:', allRows, retStatus);
	if (!retStatus)
	    throw('Null retStatus in setupCache.allCallback');
	if (Sliobj.params.paceLevel >= ADMIN_PACE && retStatus.info.adminPaced)
	    Sliobj.adminPaced = retStatus.info.adminPaced;
	if (retStatus.info.maxLastSlide)
	    Sliobj.maxLastSlide = Math.min(retStatus.info.maxLastSlide, Sliobj.params.pacedSlides);
	if (retStatus.info.remoteAnswers)
	    Sliobj.remoteAnswers = retStatus.info.remoteAnswers;
	if (retStatus.info.sessionFileKey)
	    Sliobj.sessionFileKey = retStatus.info.sessionFileKey;
	if (retStatus.info.sheetsAvailable)
	    Sliobj.sheetsAvailable = retStatus.info.sheetsAvailable;
	if (allRows) {
	    gsheet.initCache(allRows);
	    GService.gprofile.auth.validated = 'allCallback';
	    if (callback) {
		var roster = gsheet.getRoster();
		if (!roster.length) {
		    sessionAbort('No users available for session '+Sliobj.sessionName);
		}
		Sliobj.userList = [];
		Sliobj.userGrades = {};
		for (var j=0; j<roster.length; j++) {
		    var id = roster[j][1];
		    var rowObj = allRows[id];
		    Sliobj.userList.push(id);
		    Sliobj.userGrades[id] = {index: j+1, name: roster[j][0], team: roster[j][2], submitted:null, grading: null,
					     gradeDisp: computeGrade(id, true)};
		}

		var userId = auth.id;
		if (userId && !(userId in Sliobj.userGrades)) {
		    //alert('Error: userID '+userId+' not found for this session');
		    userId = '';
		}
		if (!userId)  // Pick the first userID
		    userId = Sliobj.userList[0];
		Sliobj.gradingUser = Sliobj.userGrades[userId].index;
		
		var switchElem = document.getElementById('slidoc-switch-user');
		if (switchElem && roster.length) {
		    for (var j=0; j<roster.length; j++) {
			var option = document.createElement("option");
			option.id = 'slidoc-switch-user-'+(j+1);
			option.value = roster[j][1];
			option.text = (j+1)+'. '+roster[j][0];
			switchElem.appendChild(option);
			if (option.value == userId)
			    option.selected = true;
		    }
		    switchElem.onchange = switchUser;
		}
		selectUser(auth, callback);
		for (var j=0; j<Sliobj.userList.length; j++)
		    gsheet.getRow(Sliobj.userList[j], {}, checkGradingCallback.bind(null, Sliobj.userList[j]));
		if (Sliobj.gradingUser == 1)
		    Slidoc.nextUser(true, true);
	    }
	} else {
	    var err_msg = 'Failed to setup Google Docs cache: ' + (retStatus ? retStatus.error : '');
	    alert(err_msg);
	    sessionAbort(err_msg);
	}
    }
    try {
	gsheet.getAll(allCallback);
    } catch(err) {
	sessionAbort(''+err, err.stack);
    }
}

Slidoc.remoteLog = function (funcName, msgType, msg, msgTrace) {
    try {
	if (Sliobj.logSheet)
	    Sliobj.logSheet.putRow({id: GService.gprofile.auth.id, name: GService.gprofile.auth.id,
				    browser: navigator.userAgent, file: Sliobj.params.fileName, function: funcName||'',
				    type: msgType||'', message: msg||'', trace: msgTrace||'' },
				    {log: 1} );
    } catch (err) {
	console.log('Slidoc.remoteLog: ERROR in putRow '+err);
    }
}

var sessionAborted = false;
function sessionAbort(err_msg, err_trace) {
    console.log('sessionAbort', '', err_msg, err_trace||'');
    Slidoc.remoteLog('sessionAbort', '', err_msg, err_trace||'');
    if (sessionAborted)
	return;
    sessionAborted = true;
    localDel('auth');
    try { slidesVisible(false); } catch(err) {}
    alert((Sliobj.params.debug ? 'DEBUG: ':'')+err_msg);

    if (!Sliobj.reloadCheck && Slidoc.serverCookie) {
	if (!Sliobj.params.debug || window.confirm('Log out user?'))
	    location.href = Slidoc.logoutURL;
    }
    var html = '<a href="/">Main</a><p></p><b>Error: <pre>'+escapeHtml(err_msg)+'</pre>';
    if (Sliobj.previewState)
	html += '<p></p><a href="'+(Sliobj.params.siteName?'/'+Sliobj.params.siteName:'')+'/_discard?modified='+Sliobj.previewModified+'">Discard preview</a>';
    if (!Sliobj.params.gd_sheet_url)
	html += '<p></p><a href="/?reset=1">Reset</a>';
    document.body.innerHTML = html;
}

function loadPath(newPath, newHash) {  // newHash, if specified, should include '#' prefix
    // Force reload of path, even if it is the same as current path
    if (location.pathname == newPath) {
	if (newHash)
	    location.hash = newHash;
	location.reload(true);
    } else {
	window.location = newPath + (newHash || '');
    }
}

function sessionReload(msg) {
    if (window.GService)
	GService.closeWS(msg);
    if (window.confirm(msg))
	location.reload(true);
}

function abortOnError(boundFunc) {
    // Usage: abortOnError(func.bind(null, arg1, arg2, ...))
    try {
	return boundFunc();
    } catch(err) {
	console.log("abortOnError: ERROR", err, err.stack);
	sessionAbort('abortOnError: '+err, err.stack);
    }
}

//////////////////////////////////
// Section 6: Local data storage
//////////////////////////////////


function localPut(key, obj) {
    if (window.localStorage)
	window.localStorage['slidoc_'+key] = JSON.stringify(obj);
}

function localDel(key) {
    if (window.localStorage)
	delete window.localStorage['slidoc_'+key];
}

function localGet(key) {
   try {
      return JSON.parse(window.localStorage['slidoc_'+key]);
   } catch(err) {
     return null;
   }
}

//////////////////////////////////////////////////////
// Section 7: Cookie and query parameter processing
//////////////////////////////////////////////////////

function getCookieValue(a, stripQuote) {
    var b = document.cookie.match('(^|;)\\s*' + a + '\\s*=\\s*([^;]+)');
    var c = b ? b.pop() : '';
    return stripQuote ? c.replace(/"/g,'') : c;
}

function getSiteRole(siteName, siteRoles, checkIfGuest) {
    // Return role for site or null
    var scomps = siteRoles.split(',');
    for (var j=0; j<scomps.length; j++) {
	var smatch = /^([^\+]+)(\+(\w+))?$/.exec(scomps[j]);
	if (smatch && smatch[1] == siteName) {
	    return checkIfGuest ? 'guest' : (smatch[3] || '');
	}
    }
    return null;
}

function getUserRole(checkIfGuest) {
    var userRole = '';
    if (window.GService && GService.gprofile && GService.gprofile.auth)
	userRole = GService.gprofile.auth.authRole;
    else if (Slidoc.serverCookie && Slidoc.serverCookie.siteRole)
	userRole = Slidoc.serverCookie.siteRole;
    else if (Slidoc.serverCookie && Slidoc.serverCookie.sites && checkIfGuest && getSiteRole(Sliobj.params.siteName, Slidoc.serverCookie.sites, true))
	userRole = 'guest';
    return userRole;
}

function getServerCookie() {
    var slidocCookie = getCookieValue(Sliobj.params.userCookiePrefix, true);
    if (!slidocCookie)
	return null;
    
    var comps = slidocCookie.split(":");
    for (var j=0; j<comps.length; j++)
	comps[j] = decodeURIComponent(comps[j]);
    var retval = {user:   comps[0],
		  role:   comps.length > 1 ? comps[1] : '',
		  sites:  comps.length > 2 ? comps[2] : '',
		  token:  comps.length > 3 ? comps[3] : ''
	     };

    retval.siteRole = retval.role;
    if (!retval.siteRole && Sliobj.params.siteName && retval.sites) {
	retval.siteRole = getSiteRole(Sliobj.params.siteName, retval.sites) || '';
    }

    if (comps.length > 4 && comps[4]) {
	try {
	    retval.data = JSON.parse(atob(comps[4]));
	} catch(err) {
	    Slidoc.log('getServerCookie: ERROR '+err);
	    retval.data = {}
	}
    }
    retval.name = retval.data.name || '';
    retval.email = retval.data.email || '';
    retval.altid = retval.data.altid || '';
    return retval;
}

function getSiteCookie() {
    var siteCookie = getCookieValue(Sliobj.params.siteCookiePrefix+'_'+Sliobj.params.siteName, true);
    if (!siteCookie)
	return {};

    try {
	return JSON.parse(atob(decodeURIComponent(siteCookie)));
    } catch(err) {
	Slidoc.log('getSiteCookie: ERROR '+err);
	return {};
    }
}


Slidoc.imageLink = '';

Sliobj.serverData = {};
Slidoc.serverCookie = getServerCookie();
if (Slidoc.serverCookie) {
    Sliobj.serverData = Slidoc.serverCookie.data || {};
}
Slidoc.siteCookie = getSiteCookie();

Slidoc.PluginManager.sitePrefix = Sliobj.sitePrefix;
Slidoc.PluginManager.pluginDataPath = Slidoc.siteCookie.pluginDataPath || '';

// Locked view: for lockdown browser mode
Sliobj.lockedView = !!Sliobj.serverData.locked_access;

Sliobj.batchMode = Sliobj.serverData.batch ? true : isHeadless;

// Assessment view: for printing exams
Sliobj.assessmentView = false;
if (getParameter('print')) {
    if (Sliobj.batchMode) {
	Sliobj.assessmentView = true;
    } else if (!Sliobj.params.gd_sheet_url && (!Slidoc.serverCookie || Slidoc.serverCookie.siteRole)) {
	Sliobj.assessmentView = true;
    }
}

Slidoc.websocketPath = '';
if (Sliobj.params.gd_sheet_url && Sliobj.params.gd_sheet_url.slice(0,1) == '/') {
    // Proxy URL
    if (Slidoc.serverCookie) {
	Slidoc.websocketPath = Sliobj.params.gd_sheet_url+location.pathname+'?version='+Slidoc.version;
    } else {
	sessionAbort('Error: File must be served from proxy server for websocket authentication');
    }
}

Slidoc.logoutURL = "/_auth/logout/";
Slidoc.getParameter = getParameter;

function resetLocalSession() {
    localDel('auth');
    var sessionObj = localGet('sessions');
    try { delete sessionObj[Sliobj.params.fileName] } catch(err) {}
    localPut('sessions', sessionObj);
}

var resetParam = getParameter('reset');
if (resetParam) {
    if (resetParam == 'all' && window.confirm('Reset all local sessions?')) {
	localDel('auth');
	localDel('sessions');
	alert('All local sessions reset');
	location = location.href.split('?')[0];
    } else if (window.confirm('Reset session '+Sliobj.params.fileName+'?')) {
	resetLocalSession();
	location = location.href.split('?')[0];
    }
}

///////////////////////////////
/// Section 8: Document ready
///////////////////////////////

document.onreadystatechange = function(event) {
    Slidoc.log('onreadystatechange:', document.readyState);
    // !Sliobj.params.fileName => index file; load, but do not execute JS
    if (document.readyState != "interactive" || !document.body)
	return;
    Slidoc.pageSetup();
    if (!Sliobj.params.fileName || (Sliobj.params.fileName == 'index' && !Sliobj.previewState)) {
	// Just a simple web page
	toggleClass(true, 'slidoc-simple-view');
	if (Sliobj.params.gd_sheet_url || getServerCookie())
	    toggleClass(true, 'slidoc-remote-view');
	return;
    }
    Slidoc.reportTestAction('ready');
    return abortOnError(onreadystateaux);
}

    
var PagedownConverter = null;
function onreadystateaux() {
    Slidoc.log('onreadystateaux:');
    if (window.GService)
	GService.setEventReceiverWS(Sliobj.eventReceiver);
    setupPlugins();
    if (window.Markdown) {
	PagedownConverter = new Markdown.getSanitizingConverter();
	if (Markdown.Extra) // Need to install https://github.com/jmcmanus/pagedown-extra
	    Markdown.Extra.init(PagedownConverter, {extensions: ["fenced_code_gfm"]});

	// Need latest version of Markdown for hooks
	PagedownConverter.hooks.chain("preSpanGamut", MDPreSpanGamut);
	PagedownConverter.hooks.chain("preBlockGamut", MDPreBlockGamut);
    }

    // Typeset MathJax after plugin setup
    if (!('immediate_math' in Sliobj.params.features) && window.MathJax)
	MathJax.Hub.Queue(["Typeset", MathJax.Hub]);

    if (Sliobj.params.gd_client_id) {
	// Google client load will authenticate
    } else if (Sliobj.params.gd_sheet_url || (window.GService && Slidoc.serverCookie)) {
	var localAuth = localGet('auth');
	if (localAuth && !Slidoc.serverCookie) {
	    Slidoc.showPopup('Accessing Google Docs ...', null, null, 1000);
	    GService.gprofile.auth = localAuth;
	    Slidoc.slidocReady(localAuth);
	} else {
	    if (!Slidoc.serverCookie)
		Slidoc.reportTestAction('loginPrompt');
	    GService.gprofile.promptUserInfo(Sliobj.params.siteName, Sliobj.params.fileName, Sliobj.previewState||Sliobj.testScript, Sliobj.params.authType);
	}
    } else {
	Slidoc.slidocReady(null);
    }
}

Sliobj.previewState = false;
Sliobj.previewModified = 0;
Sliobj.updateView = false;
Sliobj.imageDropSetup = false;

Slidoc.pageSetup = function() {
    Slidoc.log("pageSetup:", Sliobj.reloadCheck, location.hash, getParameter('update'));

    if (Sliobj.reloadCheck) {
	if (getParameter('remoteupload')) {
	    var uploadButton = document.getElementById('slidoc-upload-button');
	    if (uploadButton)
		uploadButton.style.display = null;
	}
	setTimeout(reloadCheckFunc, 1000);
	Sliobj.updateView = true;
	Slidoc.localMessages(true);
    }

    var match = location.pathname.match(/\/_preview\b/);
    if (match) {
	Sliobj.previewState = true;
	var labelElem = document.getElementById('slidoc-preview-label');
	if (labelElem)
	    labelElem.textContent = 'Previewing '+Sliobj.sessionLabel;
	previewMessages(true);
	if (!Sliobj.params.fileName)
	    toggleClass(true, 'slidoc-preview-view');
	Sliobj.previewModified = parseNumber(getParameter('modified')) || 0;

	if (!Sliobj.previewModified) {
	    var acceptButton = document.getElementById('slidoc-preview-accept');
	    if (acceptButton) acceptButton.style.display = 'none';
	    var discardButton = document.getElementById('slidoc-preview-discard');
	    if (discardButton) discardButton.style.display = 'none';
	} else {
	    var closeButton = document.getElementById('slidoc-preview-close');
	    if (closeButton) closeButton.style.display = 'none';
	}

	if (getParameter('update')) {
	    Sliobj.updateView = true;
	    if (!Sliobj.params.fileName)
		toggleClass(true, 'slidoc-update-view');
	    imageDropState(true);
	    Slidoc.classDisplay('slidoc-edit-update', 'none');
	}
    }

    function userStatusAux(retval, errmsg) {
	Slidoc.log('userStatusAux:', retval, errmsg);
	if (retval && Slidoc.serverCookie && Slidoc.serverCookie.siteRole == Sliobj.params.adminRole) {
	    var statusElem = document.getElementById('slidoc-test-status');
	    if (statusElem) {
		if (!Sliobj.previewState && retval.previewingSession && retval.previewingSession != Sliobj.sessionName) {
		    statusElem.style.display = null;
		    statusElem.innerHTML = 'Preview <a href="'+Sliobj.sitePrefix+'/_preview/index.html">'+retval.previewingSession+'</a>';
		}
	    }
	}
    }
    if (Slidoc.serverCookie)
	Slidoc.ajaxRequest('GET', Sliobj.sitePrefix + '/_user_status', {}, userStatusAux, true);

    if (gradingAccess()) {
	toggleClass(true, 'slidoc-restricted-view'); // Only for simple pages; for sessions all views will be cleared by slidocReady
	var restrictedElems = document.getElementsByClassName('slidoc-restrictedonly');
	[].forEach.call(restrictedElems, function(elem) { elem.style.display = null; });
    }

    if (Slidoc.siteCookie) {
	if (!Slidoc.siteCookie.editable) {
	    var editIcons = document.getElementsByClassName('slidoc-edit-icon');
	    [].forEach.call(editIcons, function(elem) { elem.style.display = 'none'; });
	}
	if (Slidoc.siteCookie.gradebook) {
	    var gradesButton = document.getElementById('slidoc-grades-button');
	    if (gradesButton)
		gradesButton.style.display = null;
	    var gradeElem = document.getElementById('gradelink');
	    if (gradeElem)
		gradeElem.style.display = null;
	}
	if (Slidoc.siteCookie.files) {
	    var filesElem = document.getElementById('fileslink');
	    if (filesElem)
		filesElem.style.display = null;
	}
    }

    var loadElem = document.getElementById("slidoc-init-load");
    if (loadElem)
	loadElem.style.display = 'none';
    var topnavElem = document.getElementById("slidoc-topnav");
    var contentsButton = document.getElementById("slidoc-contents-button");
    if (contentsButton && !topnavElem)
	contentsButton.style.display = null;

    if (Slidoc.serverCookie && Slidoc.serverCookie.siteRole == Sliobj.params.adminRole) {
	var dashElem = document.getElementById('dashlink');
	if (dashElem) {
	    dashElem.style.display = null;
	    var dashEditElem = document.getElementById('dashlinkedit');
	    if (dashEditElem) {
		var fname = Sliobj.params.fileName;
		if (!fname) {
		    var match = location.pathname.match(/\/(\w+)\/index.html$/);
		    if (match)
			fname = match[1]+'00';
		}
		if (fname)
		    dashEditElem.href = Sliobj.sitePrefix + '/_edit/' + fname;
		else
		    dashEditElem.style.display = 'none';
	    }
	}
    }
    var indexElems = document.getElementsByClassName('slidoc-index-entry');
    for (var j=0; j<indexElems.length; j++) {
	var elem = indexElems[j];
	var releaseTime = parseNumber(elem.dataset.release) || 0;
	var dueTime = parseNumber(elem.dataset.due || 0);
	var curTime = (new Date()).getTime() / 1000;
	if (releaseTime && curTime < releaseTime) {
	    elem.classList.add('slidoc-index-entry-prerelease')
	} else if (dueTime) {
	    if (curTime < dueTime)
		elem.classList.add('slidoc-index-entry-active');
	    else
		elem.classList.add('slidoc-index-entry-expired');
	}
    }
    document.addEventListener('webkitfullscreenchange', fullscreenHandler, false);
    document.addEventListener('mozfullscreenchange', fullscreenHandler, false);
    document.addEventListener('fullscreenchange', fullscreenHandler, false);

    var draggables = document.getElementsByClassName('slidoc-toggle-draggable');
    [].forEach.call(draggables, function(draggable) {
	draggable.addEventListener('dragstart', handleEditDragStart, false);
	draggable.addEventListener('dragend', handleEditDragEnd, false);
    });

    var togglebars = document.getElementsByClassName('slidoc-togglebar');
    [].forEach.call(togglebars, function(togglebar) {
	togglebar.addEventListener('dragenter', handleEditDragEnter, false);
	togglebar.addEventListener('dragover', handleEditDragOver, false);
	togglebar.addEventListener('dragleave', handleEditDragLeave, false);
	togglebar.addEventListener('drop', handleEditDrop, false);
    });
}

function addImageDropHandlers(imageDrop) {
    imageDrop.addEventListener('dragenter', handleImageDragEnter, false);
    imageDrop.addEventListener('dragover', handleImageDragOver, false);
    imageDrop.addEventListener('dragleave', handleImageDragLeave, false);
    imageDrop.addEventListener('drop', handleImageDrop, false);
}

function imageDropState(active, slideId) {
    Slidoc.log("imageDropState:", active, slideId);
    var containerElem = document.getElementById(slideId ? slideId+'-togglebar-edit-img' : 'slidoc-imgupload-container');
    if (containerElem)
	containerElem.style.display = active ? null : 'none';

    if (!Sliobj.imageDropSetup) {
	Sliobj.imageDropSetup = true;
	var imageDrops = document.getElementsByClassName('slidoc-img-drop');
	[].forEach.call(imageDrops, addImageDropHandlers);
    }
}

var handleEditDragSlideNumber = 0;

function handleEditDragStart(evt) {
    ///console.log('handleEditDragStart: ', evt, evt.dataTransfer);
    toggleClass(true, 'slidoc-dragdrop-view');

    var params = {slide: this.dataset.slide, session: Sliobj.params.fileName, siteName: Sliobj.params.siteName}
    evt.dataTransfer.effectAllowed = 'move';
    evt.dataTransfer.setData('application/json', JSON.stringify(params));
    handleEditDragSlideNumber = parseInt(this.dataset.slide);
}

function handleEditDragEnd(evt) {
    ///console.log('handleEditDragEnd: ', evt);
    toggleClass(false, 'slidoc-dragdrop-view');
    handleEditDragSlideNumber = 0;
    var togglebars = document.getElementsByClassName('slidoc-togglebar');
    [].forEach.call(togglebars, function(togglebar) {
    });
}

function handleEditDragEnter(evt) {
    if (!handleEditDragSlideNumber || parseInt(this.dataset.slide) < handleEditDragSlideNumber)
	this.classList.add('slidoc-dragovertop');
    else if (parseInt(this.dataset.slide) > handleEditDragSlideNumber)
	this.classList.add('slidoc-dragoverbottom');
}

function handleEditDragLeave(evt) {
    this.classList.remove('slidoc-dragovertop');
    this.classList.remove('slidoc-dragoverbottom');
}

function handleEditDragOver(evt) {
    if (evt.stopPropagation) evt.stopPropagation();
    if (evt.preventDefault) evt.preventDefault();

    evt.dataTransfer.dropEffect = 'move'; 
    return false;
}

function handleEditDrop(evt) {
    if (evt.stopPropagation) evt.stopPropagation();
    if (evt.preventDefault) evt.preventDefault();

    if (Sliobj.reloadCheck) {
	alert('Slide drag-drop not implemented for local preview');
	return;
    }

    try {
	var params = JSON.parse(evt.dataTransfer.getData('application/json'));
    } catch(err) {
	alert('Edit drop error: '+err);
	return;
    }

    Slidoc.log('handleEditDrop: ', params);

    var sourceNum = params.slide;
    var fromSession = params.session;
    var fromSite = params.siteName;
    var destNum = parseInt(this.dataset.slide);
    if (sourceNum != destNum || fromSession != Sliobj.params.fileName || fromSite != Sliobj.params.siteName)
	Slidoc.slideMove(this, sourceNum, destNum, fromSession, fromSite);
    return false;
}

function handleImageDragEnter(evt) {
    this.classList.add('slidoc-dragover');
}

function handleImageDragLeave(evt) {
    this.classList.remove('slidoc-dragover');
}

function handleImageDragOver(evt) {
    if (evt.stopPropagation) evt.stopPropagation();
    if (evt.preventDefault) evt.preventDefault();

    evt.dataTransfer.dropEffect = 'copy'; 
    return false;
}

function handleImageDrop(evt) {
    if (evt.stopPropagation) evt.stopPropagation();
    if (evt.preventDefault) evt.preventDefault();

    this.classList.remove('slidoc-dragover');
    Slidoc.log('handleImageDrop: ', this, evt);

    var dropElem = this;

    var imageFile = '';
    var imageExtn = '';
    var slideId = '';
    var imageElem = null;
    if (this.tagName == 'IMG') {
	if (!window.confirm('Replace '+this.src+'?'))
	    return false;

	imageElem = this;
	imageFile = this.src.split('/').slice(-1)[0];
	imageExtn = imageFile.split('.').slice(-1)[0];
    } else {
        slideId = this.dataset.slideId ||'';
    }

    var files = evt.dataTransfer.files;
    if (!files) {
	alert('Expecting file drop');
	return false;
    }

    var fileProps = checkFileUpload(files, /^image\//);
    Slidoc.log('handleImageDrop: ', slideId, dropElem, fileProps);

    var imageHead = '';
    if (fileProps) {
	imageHead = fileProps.head;
	if (imageExtn && imageExtn != fileProps.extension) {
	    alert('Cannot overwrite image with different image format; upload as new image');
	    return false;
	}
	function handleImageDropAux(result, errMsg) {
	    Slidoc.log('handleImageDropAux: ', slideId, imageElem, result, errMsg);
	    if (!result) {
		alert('Error in uploading image :'+errMsg);
		return false;
	    }
	    if (imageElem && (imageElem.classList.contains('slidoc-img') || imageElem.classList.contains('slidoc-imgdisp')) ) {
		// Reload image
		imageElem.src = imageElem.src;
	    } else {
		// Display uploadable image
		var imagePath = '_images/'+result.imageFile;
		Slidoc.imageLink = '![' + imageHead + '](' + imagePath + ')';

		imagePath = Sliobj.params.fileName + imagePath
		if (!Sliobj.previewState) {
		    imagePath = '/_preview/'+imagePath;
		    if (Sliobj.params.siteName)
			imagePath = '/' + Sliobj.params.siteName + imagePath;
		}
		var dropParent = dropElem.parentNode;
		var newImg = document.createElement('img');
		newImg.className = 'slidoc-imgdisp slidoc-imgupload-imgdisp slidoc-img-drop';
		newImg.src = imagePath;
		dropParent.appendChild(newImg);
		addImageDropHandlers(newImg);

		var newLabel = document.createElement('code');
		newLabel.className = 'slidoc-imgupload-imglink';
		newLabel.textContent = Slidoc.imageLink
		dropParent.appendChild(newLabel);

		dropParent.appendChild(document.createElement('br'));

		// Append image link to edit textarea (if present)
		if (slideId) {
		    var areaElem = document.getElementById(slideId+'-togglebar-edit-area');
		    if (areaElem) {
			areaElem.value += '\n\n' + Slidoc.imageLink + '\n\n';
			scrollTextArea(areaElem);
		    }
		}
	    }
	}
	var params = {sessionname: Sliobj.params.fileName, imagefile: imageFile};
	var autoElem = document.getElementById((slideId||'slidoc')+'-upload-img-autonumber');
	if (autoElem && autoElem.checked)
	    params.autonumber = 1;

	Slidoc.ajaxUpload(Sliobj.sitePrefix + '/_imageupload', fileProps.file, params, handleImageDropAux, true);
    }

    return false;
}

//////////////////////////////////
// Section 8b: Preview functions
//////////////////////////////////

Slidoc.accordionView = function(active, show) {
    Slidoc.log('accordionView: ', active, show);
    if (!document.body.classList.contains('slidoc-collapsible-view'))
	return;

    if (Sliobj.session && Sliobj.session.paced >= QUESTION_PACE)
	setupOverride('Enable test user override to display all slides?', Sliobj.previewState);

    var allSlides = document.getElementsByClassName('slidoc-slide');
    for (var j=0; j<allSlides.length; j++) {
	var togglebar = document.getElementById(allSlides[j].id+'-togglebar');
	if (setupOverride()) {
	    // Display all slides
	    allSlides[j].style.display = null;
	    if (togglebar)
		togglebar.style.display = null;
	} else if (allSlides[j].style.display == 'none') {
	    continue;
	}
	toggleClass(active && !show, 'slidoc-toggle-hide', allSlides[j]);
	if (togglebar)
	    toggleClass(active && !show, 'slidoc-toggle-hide', togglebar);

	var topToggleHeader = document.getElementById(allSlides[j].id+'-toptoggle-header');
	var slideToggleFooter = getSlideFooter(allSlides[j].id);
	if (active && topToggleHeader && slideToggleFooter && slideToggleFooter.textContent)
	    topToggleHeader.innerHTML = slideToggleFooter.innerHTML;
    }
    toggleClass(active, 'slidoc-accordion-view');
}

Slidoc.accordionToggle = function(slideId, show) {
    var slideElem = document.getElementById(slideId);
    var togglebar = document.getElementById(slideId+'-togglebar');

    toggleClass(!show, 'slidoc-toggle-hide', slideElem);
    if (togglebar)
	toggleClass(!show, 'slidoc-toggle-hide', togglebar);

    // Hide/display slides below without headers
    var toggleFooters = document.getElementsByClassName(slideId+'-footer-toggle');
    for (var j=0; j<toggleFooters.length; j++) {
	var smatch = /^(.*)-footer-toggle$/.exec(toggleFooters[j].id);
	var temSlideId = smatch[1];
	if (smatch) {
	    var temSlideElem = document.getElementById(temSlideId);
	    if (temSlideElem)
		toggleClass(!show, 'slidoc-toggle-hide', temSlideElem);
	    var tembar = document.getElementById(temSlideId+'-togglebar');
	    if (tembar)
		toggleClass(!show, 'slidoc-toggle-hide', tembar);
	}
    }
}

function checkActiveEdit(noAlert) {
    var allContainers = document.getElementsByClassName('slidoc-togglebar-edit');
    
    for (var j=0; j<allContainers.length; j++) {
	if (allContainers[j].style.display != 'none') {
	    setTimeout(function(){allContainers[j].scrollIntoView(true);}, 200);
	    if (!noAlert)
		alert('Another slide edit in progress; please save/discard it first.');
	    return true;
	}
    }
    return false;
}

Slidoc.slideDiscuss = function(action, slideId) {
    Slidoc.log('slideDiscuss:', action, slideId);
    var slideNum = parseSlideId(slideId)[2];
    var userId = getUserId();
    if (action == 'show') {
	Sliobj.discussSheet.actions('discuss_posts', {id: userId, sheet:Sliobj.sessionName, slide: slideNum}, slideDiscussShowCallback.bind(null, userId, slideId));
    } else {
	var colName = 'discuss' + zeroPad(slideNum, 3);
	var textareaElem = document.getElementById(slideId+'-discuss-textarea');
	var textValue = textareaElem.value;
	if (action == 'preview') {
            var renderElem = document.getElementById(slideId+'-discuss-render');
	    renderElem.innerHTML = MDConverter(textValue, true);
	    if (window.MathJax)
		MathJax.Hub.Queue(["Typeset", MathJax.Hub, renderElem.id]);
	} else if (action == 'post') {
	    var updates = {id: userId};
	    updates[colName] = textValue;
	    Sliobj.discussSheet.updateRow(updates, {}, slideDiscussUpdateCallback.bind(null, userId, slideId));
	}
    }
}

Slidoc.deletePost = function(slideId, postNum) {
    Slidoc.log('deletePost:', slideId, postNum);
    if (!window.confirm('Delete discussion post?'))
	return false;
    var slideNum = parseSlideId(slideId)[2];
    var colName = 'discuss' + zeroPad(slideNum, 3);
    var userId = getUserId();
    var updates = {id: userId};
    updates[colName] = 'delete:' + postNum;
    Sliobj.discussSheet.updateRow(updates, {}, slideDiscussUpdateCallback.bind(null, userId, slideId));
}

function slideDiscussUpdateCallback(userId, slideId, result, retStatus) {
    Slidoc.log('slideDiscussUpdateCallback:', userId, slideId, result, retStatus);
    if (!result) {
	alert('Error in discussion post: '+(retStatus?retStatus.error:''));
	return;
    }
    displayDiscussion(userId, slideId, retStatus.info.discussPosts);
    var textareaElem = document.getElementById(slideId+'-discuss-textarea');
    textareaElem.value = '';
}

function slideDiscussShowCallback(userId, slideId, result, retStatus) {
    Slidoc.log('slideDiscussShowCallback:', userId, slideId, result, retStatus);
    displayDiscussion(userId, slideId, result);
}

function displayDiscussion(userId, slideId, posts) {
    var html = '';
    var unreadId = '';
    for (var j=0; j<posts.length; j++) {
	var row = posts[j];  // [postNum, userId, userName, postTime, unreadFlag, postText]
	var postId = slideId+'-post'+zeroPad(row[0],3);
	var postName = (row[1] == Sliobj.params.testUserId) ? 'Instructor' : row[2];
        var highlight = '*';
	if (row[4]) {
	    // Unread
            highlight = '**';
	    if (!unreadId)
		unreadId = postId;
	}
	html += '<p id="'+postId+'">'
	html += MDConverter(highlight+postName+highlight+': '+row[5], true); // Last,First: Text
	html += '<br><em class="slidoc-discuss-post-timestamp">'+row[3]+'</em>';  // Time
	if ((userId == row[1] || userId == Sliobj.params.testUserId) && !row[5].match(/\s*\(deleted/))
	    html += ' <span class="slidoc-clickable slidoc-discuss-post-delete" onclick="Slidoc.deletePost('+"'"+slideId+"',"+row[0]+');">&#x1F5D1;</span>'
	html += '</p>'
    }
    var containerElem = document.getElementById(slideId+'-discuss-container');
    containerElem.style.display = null;
    var postsElem = document.getElementById(slideId+'-discuss-posts');
    postsElem.innerHTML = html;
    if (window.MathJax)
	MathJax.Hub.Queue(["Typeset", MathJax.Hub, postsElem.id]);

    var showElem = document.getElementById(slideId+'-discuss-show');
    if (showElem)
	showElem.classList.add('slidoc-discuss-displayed');
    var countElem = document.getElementById(slideId+'-discuss-count');
    var toggleElem = document.getElementById(slideId+'-toptoggle-discuss');
    if (countElem && countElem.textContent)
	countElem.textContent = countElem.textContent.split('(')[0];
    if (toggleElem)
	toggleElem.classList.remove('slidoc-discuss-unread');
    if (unreadId)
	setTimeout(function(){document.getElementById(unreadId).scrollIntoView(true); }, 200);
}

function discussUnread() {
    if (!Sliobj.discussStats)
	return 0;
    var keys = Object.keys(Sliobj.discussStats);
    var count = 0;
    for (var j=0; j<keys.length; j++) {
	if (Sliobj.discussStats[keys[j]][1])
	    count += 1;
    }
    return count;
}

function displayDiscussStats() {
    if (!Sliobj.discussStats)
	return;
    Slidoc.log('displayDiscussStats:', Sliobj.discussStats);
    var slides = getVisibleSlides();
    for (var j=0; j<slides.length; j++) {
	var slideId = slides[j].id;
	var slideNum = parseSlideId(slideId)[2];
	if (Sliobj.params.discussSlides.indexOf(slideNum) < 0)
	    continue;
	if (slideNum in Sliobj.discussStats) {
	    var stat = Sliobj.discussStats[slideNum];
	} else {
	    var stat = [0, 0];  // [nPosts, nUnread]
	}
	var footerElem = document.getElementById(slideId+'-discuss-footer');
	var countElem = document.getElementById(slideId+'-discuss-count');
	var toggleElem = document.getElementById(slideId+'-toptoggle-discuss');
	if (footerElem)
	    footerElem.style.display = null;
	if (countElem && stat[0])
	    countElem.textContent = stat[1] ? stat[0]+'('+stat[1]+')' : stat[0];
	if (toggleElem) {
	    toggleElem.style.display = null;
	    if (stat[0]) {
		toggleElem.classList.add('slidoc-discuss-available');
		if (stat[1])
		    toggleElem.classList.add('slidoc-discuss-unread');
	    }
	}
    }
}

Slidoc.slideEditMenu = function() {
    Slidoc.log('slideEditMenu:');
    var html = '<h3>Edit menu</h3>\n';
    html += '<ul>\n';
    if (Sliobj.currentSlide) {
	var slideId = Slidoc.getCurrentSlideId();
	html += '<li><span class="slidoc-clickable " onclick="'+"Slidoc.slideEdit('edit','"+slideId+"');"+'">Edit current slide</span></li><p></p>\n';
	if (Sliobj.params.paceLevel >= ADMIN_PACE) {
	    html += '<li><span class="slidoc-clickable " onclick="'+"Slidoc.slideEdit('delete','"+slideId+"');"+'">Delete current slide</span></li><p></p>\n';
	    html += '<li><span class="slidoc-clickable " onclick="'+"Slidoc.slideEdit('rollover','"+slideId+"');"+'">Rollover remaining slides to next session</span></li><p></p>\n';
	}
	html += '<li><span class="slidoc-clickable " onclick="'+"Slidoc.slideEdit('truncate','"+slideId+"');"+'">Truncate remaining slides</span></li><p></p><hr>\n';
    }
    html += '<li><span class="slidoc-clickable " onclick="'+"Slidoc.slideEdit('edit');"+'">Edit all slides</span></li><p></p>\n';
    html += '<li><span class="slidoc-clickable " onclick="'+"Slidoc.slideEdit('startpreview');"+'">Preview all slides</span></li>\n';
    html += '</ul>';
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    Slidoc.showPopup(html);
}

Slidoc.confirmLoad = function(path, msg) {
    if (window.confirm(msg || 'Confirm action?'))
	window.location = path;
}

Slidoc.dateLoad = function(prompt, loadPath) {
    var html = escapeHtml(prompt) + ' <input id="slidoc-dateload" type="datetime-local" value="">\n';
    html += '<span class="slidoc-clickable" onclick="document.getElementById('+"'slidoc-dateload'"+').value='+"''"+';">Blank</span>\n';
    html += '<p></p><span class="slidoc-clickable" onclick="Slidoc.dateLoadAux('+"'"+loadPath+"'"+');">Confirm</span>';
    Slidoc.showPopup(html);
    var dateElem = document.getElementById('slidoc-dateload');
    if (dateElem)
	dateElem.value = Slidoc.toLocalISOString(null, true) + 'T00:00';
}

Slidoc.dateLoadAux = function(loadPath) {
    var url = loadPath;
    var dateElem = document.getElementById('slidoc-dateload');
    if (dateElem && dateElem.value)
	url += '?releasedate=' + encodeURIComponent(dateElem.value);
    window.location = url;
}

Slidoc.assessmentMenu = function () {
    var adminAccess = Slidoc.serverCookie && Slidoc.serverCookie.siteRole == Sliobj.params.adminRole;
    var html = '<h3>Assessment menu</h3>\n';
    html += '<ul>\n';
    if (Sliobj.gradableState || !Sliobj.params.gd_sheet_url) {
	html += '<li><span class="slidoc-clickable" onclick="Slidoc.toggleAssessment();">'+(Sliobj.assessmentView?'End':'Begin')+' print view</span></li>\n';
	html += '<hr>';
    }

    if (Sliobj.params.gd_sheet_url) {
	var prefillUrl = Sliobj.sitePrefix+'/_prefill/'+Sliobj.params.fileName;
	html += '<li>' + clickableSpan('Prefill user info', "Slidoc.confirmLoad('"+prefillUrl+"','Prefill user info?');", !adminAccess) + '</li>\n';

	if (Sliobj.gradableState) {
	    html += '<hr>';
	    html += '<li>' + clickableLink('Import responses', Sliobj.sitePrefix+'/_import/'+Sliobj.params.fileName, !adminAccess) + '</li>\n';

	    var create = !(Sliobj.sheetsAvailable && Sliobj.sheetsAvailable.indexOf('answers') >= 0 && Sliobj.sheetsAvailable.indexOf('stats') >= 0);
	    html += '<li>' + clickableSpan((create?'Create':'Update')+' session answers/stats', "Slidoc.sessionActions('answer_stats');") + '</li>\n';

	    var create = !(Sliobj.sheetsAvailable && Sliobj.sheetsAvailable.indexOf('correct') >= 0);
	    html += '<li>' + clickableSpan((create?'Create':'Update')+' correct answer key', "Slidoc.sessionActions('correct');") + '</li>\n';

	    var disabled = !(Sliobj.sheetsAvailable && Sliobj.sheetsAvailable.indexOf('stats') >= 0);
	    html += '<li>' + clickableSpan('View response statistics', "Slidoc.showStats();", disabled) + '</li>\n';
	    html += '<li>' + clickableSpan('View correct answer key', "Slidoc.viewSheet('"+Sliobj.sessionName+"_correct');", !adminAccess) + '</li>';
            html += '<hr>';
	    html += '<li>' + clickableSpan('View session scores', "Slidoc.viewSheet('"+Sliobj.sessionName+"');", !adminAccess) + '</li>';
	    if (!Sliobj.gradeDateStr)
		html += '<li>' + clickableSpan('Release grades to students', "Slidoc.releaseGrades();" ) + '</li>';
	    else
		html += 'Grades released to students on '+Sliobj.gradeDateStr+'<br>';
	}
	html += '<li><a class="slidoc-clickable" href="'+ Sliobj.sitePrefix + '/_submissions/' + Sliobj.sessionName + '">View submissions</a></li>\n';
	var disabled = adminAccess && !(Sliobj.sheetsAvailable && Sliobj.sheetsAvailable.indexOf('answers') >= 0);
	html += '<li>' + clickableSpan('View question difficulty', "Slidoc.showQDiff();", disabled) + '</li>\n';
    }
    html += '</ul>';
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    Slidoc.showPopup(html);
}

function winURL(win) {
    // Returns window HREF (without hash), or null string on error
    if (!win)
       return '';
    try {
        return (win.location.origin == "null" ? 'about:' : win.location.origin) + win.location.pathname +
win.location.search;
    } catch (err) {
        return '';
    }
}

function checkPreviewWin() {
   var url = winURL(Sliobj.previewWin);
   if (!url)
      Sliobj.previewWin = null;
   return url;
}

Sliobj.previewWin = null;

function openWin(url, name) {
   // Open named window, if not already open
   // For previously open window with different url, switch to blank url
   var win = window.open("", name);

   if (win) {
      var utemp = winURL(win);
      console.log("openWin", utemp, ' URL:', url, win);
      if (utemp != url && utemp != 'about:blank')
         win.location.href = 'about:blank';
   } else {
      win = window.open(url, name);
      win.focus();
   }
   return win;
}

Slidoc.slideEdit = function(action, slideId) {
    Slidoc.log('slideEdit:', action, slideId);
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    if (!slideId) {
	if (checkActiveEdit())
	    return;
	var url = Sliobj.sitePrefix+ ((action == 'startpreview')?'/_startpreview/':'/_edit/') + Sliobj.params.fileName;
	loadPath(url);
	return;
    }
    var slideNum = parseSlideId(slideId)[2];
    var editContainer = document.getElementById(slideId+'-togglebar-edit');
    var editArea = document.getElementById(slideId+'-togglebar-edit-area');
    var statusElem = document.getElementById(slideId+'-togglebar-edit-status');
    var params = {slide: slideNum, sessionname: Sliobj.params.fileName, sessiontype: Sliobj.params.sessionType};
    statusElem.textContent = '';

    if (action == 'clear') {
	editArea.value = '';

    } else if (action == 'discard') {
	var unchanged = (Sliobj.origSlideText === editArea.value);
	var unsaved = (Sliobj.origSlideText !== null);
	if (!unchanged && !window.confirm('Discard edits?'))
	    return;
        resizeImageClear(slideId);
	imageDropState(false, slideId);
	editContainer.style.display = 'none';
	editArea.value = '';
	Sliobj.origSlideText = null;
	if (unchanged || unsaved)
	    return;

	if (Sliobj.previewWin) {
	    Sliobj.previewWin.close();
	    Sliobj.previewWin = null;
	}
	if (Sliobj.previewState)
	    window.location = Sliobj.sitePrefix + '/_discard';
	else
	    Slidoc.ajaxRequest('GET', Sliobj.sitePrefix + '/_discard', {}, null, true);

    } else if (action == 'open' || action == 'update' || action == 'insert' || action == 'save' || action == 'delete' || action == 'rollover' || action == 'truncate') {
	params.sessiontext = editArea.value;
	Sliobj.origSlideText = null;  // Changes are being saved as preview

	if (!Sliobj.previewState && (action == 'open' || action == 'update' || action == 'insert'))
	    params.update = '1';
	if (action == 'delete')
	    params.deleteslide = 'delete';
	if (action == 'rollover')
	    params.rollover = 'rollover';
	if (action == 'truncate')
	    params.truncate = 'truncate';

	// Window opening must be triggered by user input
	var previewPath = Sliobj.sitePrefix+'/_preview/index.html';
	var previewURL = location.origin+previewPath+'?update=1#'+slideId;
	if (action == 'save' && !Sliobj.previewState && !Sliobj.gradableState) // Redisplay slide if admin editing
	    previewPath += '?slideid='+slideId;

	if (!Sliobj.previewState && (action == 'open' || (!checkPreviewWin() && (action == 'update' || action == 'insert')) ) ) {
	    var winName = Sliobj.params.siteName+'_preview';
	    if (window.name == winName)
		winName += '2';

	    if (!window.confirm('This will open a separate "live" preview window, which can be updated automatically. If you do not want live preview in a separate window, cancel now and use Save to preview in this window. (You can use Control-Enter keystoke to trigger live updates, Shift-Enter to save, and Alt-Enter to copy image links.)')) {
		return false;
	    }

	    Sliobj.previewWin = openWin(previewURL, winName);
	}

	if (checkPreviewWin() && !Sliobj.previewWin.Slidoc && Sliobj.previewWin.document)
	    Sliobj.previewWin.document.body.textContent = 'Processing ...';

	function slideSaveAux(result, errMsg) {
	    Slidoc.log('slideSaveAux:', previewPath, slideId, result, errMsg);
	    if (Sliobj.closePopup)
		Sliobj.closePopup();
	    var msg = '';
	    if (!result) {
		msg = errMsg || 'Error in updating/saving edits';
	    } else if (result.result == 'error') {
		msg = result.error;
	    }
	    if (msg) {
		if (!params.sessionmodify && msg.indexOf('MODIFY_SESSION') >=0) {
		    params.sessionmodify = 'yes';
		    if (window.confirm(msg+'\n\n Retry save with modify_session switch enabled?')) {
			if (window.confirm('CONFIRM that you want to modify the number/order of questions?'))
			    Slidoc.ajaxRequest('POST', Sliobj.sitePrefix + '/_edit', params, slideSaveAux, true);
		    }
		} else {
		    statusElem.textContent = msg;
		    if (Sliobj.previewWin) {
			Sliobj.previewWin.Slidoc = null;
			Sliobj.previewWin.document.body.textContent = msg;
		    }
		    alert(msg);
		}
		return;
	    }

	    if (action == 'insert') {
		resizeImageClear(slideId);
		imageDropState(true, slideId);  // Preview state required for image uploads
		setTimeout(function(){alert('To insert new images, drag-and-drop them into box below text edit area'+(Sliobj.previewState?'':', then update preview')+'. To overwrite old images, simply drop new image over old image in preview.'); }, 200);
	    }

	    if (action == 'open' || action == 'update'|| action == 'insert') {
		if (!Sliobj.previewState && checkPreviewWin()) {
                    if (checkPreviewWin() == 'about:blank') {
			Sliobj.previewWin.location = previewURL;
		    } else if (!Sliobj.params.fileName || !Sliobj.previewWin.Slidoc) {
			// Only reload for "simple pages" like ToC. Session pages will be automatically reloaded via websocket
			Sliobj.previewWin.location.reload(true);
		    }
		    statusElem.textContent = 'Updated preview window';
		}
	    } else {
		if (checkPreviewWin())
		    Sliobj.previewWin.close();
		Sliobj.previewWin = null;
		loadPath(previewPath, statefulHash(slideId));
	    }
	}
	Slidoc.ajaxRequest('POST', Sliobj.sitePrefix + '/_edit', params, slideSaveAux, true);
	Slidoc.showPopup('Saving edits...');

    } else if (action == 'edit') {
	if (checkActiveEdit())
	    return;

	params.start = '1';
	
	function slideEditAux(result, errMsg) {
	    if (!result || !('slideText' in result)) {
		var altErr = (result && result.error) ? result.error : '';
		alert('Error in editing slide :'+(errMsg||altErr));
		return;
	    }
	    editContainer.style.display = null;
	    editArea.value = result.slideText;
	    Sliobj.origSlideText = editArea.value;
	    scrollTextArea(editArea);
	    resizeImageSetup(slideId);
	}
	Slidoc.ajaxRequest('GET', Sliobj.sitePrefix + '/_edit', params, slideEditAux, true);
    }
}

var resizeImageCounter = 0;

function resizeImageSetup(slideId) {
    var slideImageElems = document.getElementsByClassName(slideId+'-img');
    [].forEach.call(slideImageElems, function(imageElem) {
        if (imageElem.clientWidth) {
            try{ resizeImage(imageElem, slideId); } catch(err) {}
        } else {
            imageElem.onload = function() { resizeImage(imageElem, slideId); };
        }
    });
}

function resizeImageClear(slideId) {
    var slideImageElems = document.getElementsByClassName(slideId+'-img');
    [].forEach.call(slideImageElems, function(imageElem) {
        if (imageElem.style.display)
            imageElem.style.display = null;
    });
    var resizeElems = document.getElementsByClassName('slidoc-image-resize');
    [].forEach.call(resizeElems, function(elem) {
       elem.parentNode.removeChild(elem);
    });
}

function resizeImage(imageElem, slideId) {
    var areaElem = document.getElementById(slideId+'-togglebar-edit-area');
    if (!areaElem)
        return;

    var divId = 'slidoc-image-resize-div' + (++resizeImageCounter);
    var imgId = divId+'-img';
    var origWidth = imageElem.clientWidth;
    var origHeight = imageElem.clientHeight;
    var origAspRatio = origHeight/origWidth;
    var naturalAspRatio = imageElem.naturalHeight / imageElem.naturalWidth;
    var preserveAspRatio = true;
    if (Math.abs(naturalAspRatio - origAspRatio) > 0.05)
        preserveAspRatio = false;
    if (imageElem.style['object-fit'])
        preserveAspRatio = false;

    var html = '<div class="slidoc-image-resize" id="'+divId+'" style="display:inline-block; padding-right:5px; padding-bottom:5px; overflow:hidden; width:'+origWidth+'px;';
    if (preserveAspRatio)
        html += ' resize:horizontal;">';
    else
        html += ' height:'+origHeight+'; resize:both;">';

    html += '<img id="'+imgId+'" src="'+imageElem.src+'" style="width:100%;';
    if (preserveAspRatio)
        html += ' height:auto;';
    else
        html += ' height:100%;';
    if (imageElem.style)
        html += ' '+imageElem.style.cssText;
    html += '"></div>';

    imageElem.insertAdjacentHTML('afterend', html);
    imageElem.style.display = 'none';

    var divElem = document.getElementById(divId);
    var innerImageElem = document.getElementById(imgId);
    var fname = imageElem.src.split('/').slice(-1)[0];
    var fregex = "^ *!\\[(.*)\\]\\((" + fname + "|.*/" + fname + ")( '(.*)'|"+' "(.*)"'+")? *\\) *$";
    var fimage = new RegExp(fregex, "m");

    var mutationHandler = null;
    var observer = new MutationObserver(function(mutations) {
        if (mutationHandler)
            clearTimeout(mutationHandler);

        var shiftKey = shiftKeyDown;
        mutationHandler = setTimeout( function(mutations) {
            mutationHandler = null;
            if (shiftKey && !divElem.style.height  && divElem.style.width && divElem.style.width.match(/px$/)) {
                // Stop preserving aspect ratio
                divElem.style.height = (origAspRatio*divElem.style.width.slice(0,-2))+'px';
                divElem.style.resize = 'both';
                innerImageElem.style.height = '100%';
            }

            var areaElem = document.getElementById(slideId+'-togglebar-edit-area');
            if (!areaElem)
                return;

            var val = areaElem.value;
            val = val.replace(fimage, function(matched, p1, p2, p3, offset, s) {
                if (p3) {
                    if (p3.match(/width=\d+/)) {
                        p3 = p3.replace(/width=\d+/, 'width='+divElem.clientWidth);
                    } else {
                        p3 = p3.slice(0,-1) + ' width=' + divElem.clientWidth + p3.slice(-1);
                    }
                    if (p3.match(/height=\d+/)) {
                        p3 = p3.replace(/height=\d+/, 'height='+divElem.clientHeight);
                    } else {
                        p3 = p3.slice(0,-1) + ' height=' + divElem.clientHeight + p3.slice(-1);
                    }
                    var line = "![" + p1 + "](" + p2 + p3 + ")"; 
                } else {
                    var line = "![" + p1 + "](" + p2 + " 'width=" + divElem.clientWidth + " height=" + divElem.clientHeight + "')"; 
                }
                return line;
            });
            areaElem.value = val;

        }, 200);
    });

    observer.observe(divElem, { attributes: true });
}


Slidoc.slideMove = function(dropElem, sourceNum, destNum, fromSession, fromSite) {
    Slidoc.log('slideMove', dropElem, sourceNum, destNum, fromSession, fromSite);
    if (checkActiveEdit()) {
	dropElem.classList.remove('slidoc-dragovertop');
	dropElem.classList.remove('slidoc-dragoverbottom');
	return;
    }
    function slideMoveAux(result, errMsg) {
	if (!result) {
	    alert('Error in moving slide :'+errMsg);
	    dropElem.classList.remove('slidoc-dragovertop');
	    dropElem.classList.remove('slidoc-dragoverbottom');
	    return;
	}
	loadPath(Sliobj.sitePrefix + '/_preview/index.html', '#--');
    }
    var params = {slide: sourceNum, move: destNum, sessionname: Sliobj.params.fileName,
		  fromsession: fromSession, sessiontext: ''};
    params.fromsite = (fromSite != Sliobj.params.siteName) ? fromSite : '';
    Slidoc.ajaxRequest('POST', Sliobj.sitePrefix + '/_edit', params, slideMoveAux, true);
}

Slidoc.previewAction = function (action) {
    if (action == 'messages') {
	previewMessages();
	return;
    }
    if (checkActiveEdit())
	return;

    if (action == 'discard') {
	if (!window.confirm('Discard all changes?'))
	    return;

    } else if (action == 'accept') {
	if (Sliobj.previewState) {
	    if (Sliobj.params.overwrite) {
		if (!window.confirm('Accepting changes will overwrite previous version. Proceed?'))
		    return;
	    }
	    action = 'accept';
	} else {
	    action = 'preview/index.html';
	}
    }
    var url = Sliobj.sitePrefix + '/_' + action + '?modified=' + Sliobj.previewModified;
    if (action == 'accept' && getParameter('slideid'))
	url += '&slideid=' + getParameter('slideid');

    window.location = url;
}

function previewMessages(optional) {
    function previewMessagesAux(retval, errmsg) {
	if (retval == null) {
	    if (errmsg)
		alert(errmsg);
	    return;
	}
	if (optional) {
	    if (retval.trim()) {
		document.getElementById('slidoc-preview-messages').classList.add('slidoc-amber');
	    }
	    return;
	}
	var messageText = retval.trim() || 'No messages';
	var messageHtml = (messageText.charAt(0) == '<') ? messageText : '<pre>'+messageText+'\n</pre>\n';
	Slidoc.showPopup(messageHtml, null, true);
    }
    Slidoc.ajaxRequest('GET', Sliobj.sitePrefix + '/_preview/_messages', {}, previewMessagesAux);
}

Slidoc.ajaxRequest = function (method, url, data, callback, json, nolog) {
    // data = {key: value, ...}
    // callback(result_obj, optional_err_msg)

    var XHR = new XMLHttpRequest();

    XHR.onreadystatechange = function () {
	var DONE = 4; // readyState 4 means the request is done.
	var OK = 200; // status 200 is a successful return.
	if (XHR.readyState === DONE) {
	    Sliobj.ajaxRequestActive = null;
	    var retval = null;
	    var msg = '';
            if (XHR.status === OK) {
		if (!nolog)
		    Slidoc.log('ajaxRequest.OK: '+XHR.status, XHR.responseText.slice(0,200));
		if (json) {
		    if (XHR.getResponseHeader('Content-Type') !== 'application/json') {
			msg = 'Expected application/json response but received '+XHR.getResponseHeader('Content-Type')+' from '+url;
			if (!nolog)
			    Slidoc.log(msg);
		    } else {
			try {
			    retval = JSON.parse(XHR.responseText);
			} catch (err) {
			    msg = 'JSON parsing error';
			    if (!nolog)
				Slidoc.log(msg, err, XHR.responseText);
			}
		    }
		} else {
		    retval = XHR.responseText;
		}
            } else {
		msg = XHR.responseText+' (status='+XHR.status+ ')'
		if (!msg.match(/^error/i))
		    msg = 'Error in web request: ' + msg;
		if (!nolog)
		    Slidoc.log('ajaxRequest.Error: ', msg);
            }
	    if (callback)
		callback(retval, msg);
	}
    };

    var urlEncodedData = null;
    if (data && !(data instanceof FormData)) {
	// Encoded key=value pairs
	var urlEncodedDataPairs = [];
	for (var name in data) {
	    urlEncodedDataPairs.push(encodeURIComponent(name) + '=' + encodeURIComponent(data[name]));
	}

	// Replaces encoded spaces with plus symbol to mimic form behavior
	urlEncodedData = urlEncodedDataPairs.join('&').replace(/%20/g, '+');
    }

    if (!nolog)
	Slidoc.log('ajaxRequest.send:', method, (urlEncodedData?urlEncodedData.length:0), url);

    if (method == 'GET') {
	if (urlEncodedData)
	    XHR.open('GET', url+'?'+urlEncodedData);
	else
	    XHR.open('GET', url);
	XHR.send();
    } else {
	// Form data POST request
	XHR.open('POST', url);
	if (data instanceof FormData) {
	    XHR.send(data);
	} else {
	    XHR.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
	    XHR.setRequestHeader('Content-Length', urlEncodedData.length);

	    XHR.send(urlEncodedData);
	}
    }
    Sliobj.ajaxRequestActive = XHR;
}


Slidoc.ajaxUpload = function(url, file, params, callback, json) {
    var formData = new FormData();
    for (var name in params)
	formData.append(name, params[name]);
    formData.append("upload", file);
    Slidoc.ajaxRequest('POST', url, formData, callback, json);
}

function checkFileUpload(files, mimeRegex, extensionList) {
    if (files.length != 1) {
	alert("Please select a single file");
	return null;
    }

    var file = files[0];
    var filename = file.name;
    var fcomps = filename.split('.');
    var extn = (fcomps.length > 1) ? fcomps[fcomps.length-1].toLowerCase() : '';
    var head = extn ? fcomps.slice(0,-1).join('.') : filename;

    if (!(mimeRegex && file.type && file.type.search(mimeRegex) >= 0) &&
	!(extensionList && extn && extensionList.indexOf(extn.toLowerCase()) >= 0) ) {
	var errMsg = 'Invalid file type; expecting';
	if (mimeRegex)
	    errMsg += ' ' + mimeRegex;
	if (extensionList)
	    errMsg += ' ' + extensionList;
	alert(errMsg);
	return null;
    }
    return {file:file, filename:filename, head:head, extension:extn, mimeType:file.type}
}

/////////////////////////////////////
// Section 8c: Timed sessions
/////////////////////////////////////

Sliobj.timedSecLeft = 0;
Sliobj.timedEndTime = 0;
Sliobj.timedClose = null;
Sliobj.timedTick = null;

function timedInit(remainingSec) {
    Slidoc.log('timedInit:', remainingSec);
    if (Sliobj.timedClose)
	return;

    Sliobj.timedEndTime = Date.now() + remainingSec*1000;

    if (remainingSec*1000 < Math.pow(2,31))  // ms value >= 2^31 result in immediate exection
	Sliobj.timedClose = setTimeout(timedCloseFunc, remainingSec*1000);

    var delaySec = 0.2;
    if (remainingSec > 2*60*60) {
        // Display timer only if 2 hours or less left
	delaySec = remainingSec - 2*60*60;
	var timeElem = document.getElementById('slidoc-timed-value');
	if (timeElem && Sliobj.dueDate) {
	    toggleClass(true, 'slidoc-timed-view');
	    timeElem.textContent = 'due: '+Slidoc.toLocalISOString(Sliobj.dueDate);
	}
    }
    if (delaySec*1000 < Math.pow(2,31))
	Sliobj.timedTick = setTimeout(timedProgressFunc, delaySec*1000);

    window.addEventListener('beforeunload', function (evt) {
	if (!Sliobj.timedClose)
	    return;
	var confirmationMessage = 'Are you sure you want leave this timed session without submitting?';

	evt.returnValue = confirmationMessage;
	return confirmationMessage;
    });
}

function timedCloseFunc() {
    Slidoc.log('timedCloseFunc:');
    if (!Sliobj.timedClose)
	return;
    Sliobj.timedClose = null;

    // Only auto-submit for timed sessions to avoid overload at dueTime
    // (All non-timed sessions will be auto-submitted by proxy when Grading User accesses them.)
    if (Sliobj.params.timedSec && !Sliobj.session.submitted)
	Slidoc.submitClick(null, false, true);
}

function timedProgressFunc() {
    if (!Sliobj.timedTick)
	return;
    Sliobj.timedTick = null;

    toggleClass(true, 'slidoc-timed-view');

    var secsLeft = Math.floor((Sliobj.timedEndTime - Date.now())/1000);
    var timeElem = document.getElementById('slidoc-timed-value');
    var unitsElem = document.getElementById('slidoc-timed-units');
    ///Slidoc.log('timedProgressFunc:', secsLeft);

    var delaySec = 0;
    if (!Sliobj.timedClose || secsLeft <= 0) {
	timeElem.textContent = '0';
	unitsElem.textContent = 'sec left';

	unitsElem.classList.remove('slidoc-gray');
	unitsElem.classList.remove('slidoc-amber');
	unitsElem.classList.add('slidoc-red');

    } else if (secsLeft > 180) {
	var minsLeft = Math.floor(secsLeft/60);
	timeElem.textContent = ''+minsLeft;
	unitsElem.textContent = 'min left';
	delaySec = 30;

    } else if (secsLeft > 60) {
	timeElem.textContent = ''+(10*Math.floor(secsLeft/10));
	unitsElem.textContent = 'sec left';
	unitsElem.classList.add('slidoc-gray');
	delaySec = 5;

    } else {
	timeElem.textContent = ''+secsLeft;
	unitsElem.textContent = 'sec left';
	unitsElem.classList.remove('slidoc-gray');
	unitsElem.classList.add('slidoc-amber');
	delaySec = 0.5;
    }
    if (delaySec)
	Sliobj.timedTick = setTimeout(timedProgressFunc, delaySec*1000);
}

/////////////////////////////////////
// Section 8d: Reload/upload/unload
/////////////////////////////////////

function restoreScroll() {
    // hash = '#--' for collapsed view
    //        '#--slidoc01-03' for collapsed with one slide open
    //        '#-slidoc01-04' for document view, scrolled to slide
    //        '#-1234' for document view, scrolled to particular location
    Slidoc.log('restoreScroll:', location.hash);
    if (location.hash.slice(0,2) != '#-')
	return;

    var hashVal = location.hash.slice(2);
    if (hashVal.slice(0,1) == '-') {
	hashVal = hashVal.slice(1);
	Slidoc.accordionView(true, false);  // Requires collapsible view to be set
	if (hashVal.match(/^slidoc/))
	    Slidoc.accordionToggle(hashVal, true);
    }

    var scrollVal = parseNumber(hashVal);
    if (scrollVal) {
	window.scrollTo(0,scrollVal);
    } else if (hashVal) {
	location.hash = '#' + hashVal;
    }
}

function statefulHash(slideId) {
    var temHash = slideId || '';
    if (!Sliobj.currentSlide && temHash) {
	temHash = '-' + temHash;
	if (document.body.classList.contains('slidoc-accordion-view'))
	    temHash = '-' + temHash;
    }
    return temHash ? '#' + temHash : '';
}

function statefulReload(slideNum) {
    var hashVal = '';
    if (slideNum) {
	var visibleSlides = getVisibleSlides();
	if (visibleSlides && visibleSlides.length) {
	    var firstSlideId = visibleSlides[0].id;
	    var chapter_id = parseSlideId(firstSlideId)[0];
	    var slide_id = chapter_id + '-' + zeroPad(slideNum, 2);
	    hashVal = statefulHash(slide_id);
	}
    }
    if (!hashVal && !Sliobj.currentSlide) {
	 hashVal = '#-'+window.scrollY;
    }
    if (hashVal)
	location.hash = hashVal;
    location.reload(true);
}

function reloadCheckFunc() {
    function reloadCheckAux(result, errMsg) {
	if (result == null) {
	    document.getElementById('slidoc-localpreview-status').textContent = ' PREVIEW ENDED';
	    console.log(errMsg);
	    return;
	}

	if (result.match(/^error/i)) {
	    // Error message
	    console.log(result);
	    document.getElementById('slidoc-localpreview-status').textContent = ' '+result;
	} else if (result && result.trim()) {
	    // Reload
	    statefulReload(Sliobj.currentSlide);
	    return;
	}
	setTimeout(reloadCheckFunc, 333);
    }
    Slidoc.ajaxRequest('GET', '/_reloadcheck?token='+Sliobj.reloadCheck, {}, reloadCheckAux, false, true);
}

Sliobj.reloadCheck = (location.hostname == 'localhost') ? getParameter('reloadcheck') : '';
Slidoc.remoteUpload = function() {
    window.location = '/_remoteupload?token='+Sliobj.reloadCheck;
}
if (Sliobj.reloadCheck) {
    resetLocalSession();
}

Slidoc.localMessages = function(optional) {
    function localMessagesAux(retval, errmsg) {
	if (retval == null) {
	    if (errmsg)
		alert(errmsg);
	    return;
	}
	if (optional) {
	    if (retval.trim()) {
		document.getElementById('slidoc-log-button').classList.add('slidoc-amber');
	    }
	    return;
	}
	var messageText = retval.trim() || 'No messages';
	var messageHtml = (messageText.charAt(0) == '<') ? messageText : '<pre>'+messageText+'\n</pre>\n';
	if (!optional)
	    Slidoc.showPopup(messageHtml, null, true);
    }
    Slidoc.ajaxRequest('GET', '/_messages?token='+Sliobj.reloadCheck, {}, localMessagesAux);
}

//////////////////////////////////
// Section 9: Utility functions
//////////////////////////////////

function isNumber(x) { return !!(x+'') && !isNaN(x+''); }

function parseNumber(x) {
    try {
	if (!isNumber(x))
	    return null;
	if (typeof x == 'string') {
	    var retval = parseFloat(x);
	    return isNaN(retval) ? null : retval;
	}
	if (!isNaN(x))
	    return x || 0;
    } catch(err) {
    }
    return null;
}

Slidoc.parseNumber = parseNumber;

function parseDate(dateStr) {
    if (!dateStr || !(''+dateStr).trim())
	return null;
    if (dateStr == 'GRADING')
	return '(NOT YET)';
    try {
	var obj = new Date(dateStr);
	if (!isNaN(obj.getTime()))
	    return obj;
    } catch(err) {
    }
    return null;
}

function isArray(a) {
    return Array.isArray(a);
};

function isObject(a) { // Works for object literals only (not custom objects, Date etc.)
    return (!!a) && (a.constructor === Object);
};


function cmp(a,b) { if (a == b) return 0; else return (a > b) ? 1 : -1; }

function keyCmp(a,b) {
    // Compare keys, with numeric keys always being less than non-numeric keys
    if (isNumber(a) && !isNumber(b))
	return -1;
    if (!isNumber(a) && isNumber(b))
	return 1;
    if (a == b) return 0; else return (a > b) ? 1 : -1;
}

function sortObject(obj) {
    return Object.keys(obj).sort(keyCmp).reduce(function (result, key) {
        result[key] = obj[key];
        return result;
    }, {});
}

function orderedReplacer(key, value) {
    if (!key && isObject(value))
	return sortObject(value);
    else
	return value;
}

Slidoc.orderedStringify = function (value, space) {
    return JSON.stringify(value, orderedReplacer, space);
}

function formatNum(format, value) {
    // format = formatted_number OR 01*10**(-1)+/-range
    // * is replaced by the 'times' symbol and ** by superscripting
    // Leading zero forces scaled exponential display (with fixed exponent)
    // Range portion is ignored
    if ((typeof value) != 'number')
	return value;
    if (format.indexOf('+/-') >= 0)
	format = format.split('+/-')[0];
    var fmatch = format.match(/^[+-]?([\d.]+)([eE]([+-]?\d+)|\*10\*\*(\d+|\(([+-]?\d+)\)))?$/);
    if (!fmatch)
	return value+'';
    var num = fmatch[1];
    var exp = fmatch[2];
    var comps = num.split('.');
    var nprec = (comps.length < 2) ? 0 : comps[1].length;
    if (!exp)
	return value.toFixed(nprec)

    if (num.charAt(0) == '0') {
	// Scaled exponent
	try {
	    var expValue = fmatch[5] || fmatch[4] || fmatch[3];
	    var scaled = (value / Math.pow(10, expValue)).toFixed(nprec)
	    if (exp.charAt(0).toLowerCase() == 'e')
		return scaled + exp.charAt(0) + expValue;
	    else
		return scaled + '&times;10<sup>' + expValue + '</sup>';
	} catch(err) {
	}
    }
    var retval = value.toExponential(nprec);
    var comps = retval.split(/[eE]/);
    if (comps.length != 2)
	return retval;
    if (exp.charAt(0).toLowerCase() == 'e')
	return comps[0] + exp.charAt(0) + comps[1];

    if (comps[1].charAt(0) == '+')
	comps[1] = comps[1].slice(1);
    return comps[0] + '&times;10<sup>' + comps[1] + '</sup>';
}

Slidoc.formatNum = formatNum;

function flexFixed(num, prec) {
    // Return integer string or prec-digit fractional decimal string (default 2)
    var prec = prec || 2;
    var numStr = ''+num;
    if (numStr.indexOf('.') >= 0 && (numStr.length - numStr.indexOf('.')) > prec)
	return num.toFixed(prec);
    else
	return numStr;
}

function zeroPad(num, pad) {
    // Pad num with zeros to make pad digits
    var maxInt = Math.pow(10, pad);
    if (num >= maxInt)
	return ''+num;
    else
	return ((''+maxInt).slice(1)+num).slice(-pad);
}

function letterFromIndex(n) {
    return String.fromCharCode('A'.charCodeAt(0) + n);
}

function shuffleArray(array, randFunc) {
    // Durstenfeld shuffle
    for (var i = array.length - 1; i > 0; i--) {
        var j = randFunc ? randFunc(0, i) : Math.floor(Math.random() * (i + 1));
        var temp = array[i];
        array[i] = array[j];
        array[j] = temp;
    }
    return array;
}

function randomLetters(n, noshuffle, randFunc) {
    var letters = [];
    for (var i=0; i < n; i++)
	letters.push( letterFromIndex(i) );

    var nmix = Math.max(0, n - noshuffle);
    if (nmix > 1) {
        var cmix = letters.slice(0,nmix);
	shuffleArray(cmix, randFunc);
        letters = cmix.concat(letters.slice(nmix));
    }

    return letters.join('');
}

function choiceShuffle(letters, shuffle) {
    // Shuffle choice letter using string shuffle: choiceShuffle('B', '1DCBA') -> 'C'
    if (!shuffle)
	return letters;
    var shuffled = '';
    for (var j=0; j<letters.length; j++)
	shuffled += (shuffle.indexOf(letters[j]) > 0) ? letterFromIndex(shuffle.indexOf(letters[j])-1) : letters[j];
    return shuffled;
}

function escapeHtml(unsafe) {
    unsafe = unsafe || '';
    return unsafe
         .replace(/&/g, "&amp;")
         .replace(/</g, "&lt;")
         .replace(/>/g, "&gt;");
}

Slidoc.escapeHtml = escapeHtml;
Slidoc.PluginManager.escapeHtml = escapeHtml;

function unescapeAngles(text) {
    return text.replace(/&lt;/g, '<').replace(/&gt;/g, '>');
}

function copyAttributes(oldObj, newObj, excludeAttributes) {
    newObj = newObj || {};
    var keys = Object.keys(oldObj);
    for (var j=0; j<keys.length; j++) {
	var key = keys[j];
	if (excludeAttributes && excludeAttributes.indexOf(key) >= 0)
	    continue;
	newObj[key] = oldObj[key];
    }
    return newObj;
}

function object2Class(obj, excludeAttributes) {
    var anonFunc = function () {};
    copyAttributes(obj, anonFunc.prototype, excludeAttributes);
    return anonFunc;
}

function toggleClass(add, className, element) {
    element = element || document.body;
    if (add)
	element.classList.add(className);
    else
	element.classList.remove(className);
}

function toggleClassAll(add, className, allClassName) {
    var elems = document.getElementsByClassName(allClassName);
    for (var j=0; j<elems.length; j++)
	toggleClass(add, className, elems[j]);
}

function hideClass(className, hide) {
    var elems = document.getElementsByClassName(className);
    for (var j=0; j<elems.length; j++)
	elems[j].style.display = hide ? 'none' : null;
}

function getFullsScreenElement() {
    return document.fullscreenElement || document.mozFullScreenElement || document.webkitFullscreenElement;
}
function fullscreenHandler() {
    var fullscreenElement = getFullsScreenElement();
    //Slidoc.log("fullscreenHandler:", !!fullscreenElement);
    toggleClass(fullscreenElement, 'slidoc-fullscreen-view');
}

Slidoc.docFullScreen = function (exit) {
    if (exit)
	Slidoc.exitFullscreen();
    else if (getFullsScreenElement())
	Slidoc.exitFullscreen();
    else
	requestFullscreen(document.documentElement);
}

function requestFullscreen(element) {
  Slidoc.log("requestFullscreen:");
  if (element.requestFullscreen) {
    element.requestFullscreen();
  } else if (element.mozRequestFullScreen) {
    element.mozRequestFullScreen();
  } else if (element.webkitRequestFullscreen) {
    element.webkitRequestFullscreen();
  } else if (element.msRequestFullscreen) {
    element.msRequestFullscreen();
  }
}

Slidoc.exitFullscreen = function() {
  Slidoc.log("exitFullscreen:");
  if (document.exitFullscreen) {
    document.exitFullscreen();
  } else if (document.mozCancelFullScreen) {
    document.mozCancelFullScreen();
  } else if (document.webkitExitFullscreen) {
    document.webkitExitFullscreen();
  } else if (document.msExitFullscreen) {
    document.msExitFullscreen();
  }
}


Slidoc.toLocalISOString = function (dateObj, dateOnly) {
    var date = dateObj ? (new Date(dateObj)) : (new Date());
    date.setTime( date.getTime() - date.getTimezoneOffset()*60*1000 );
    return dateOnly ? date.toISOString().slice(0,10) : date.toISOString().slice(0,16);
}

Slidoc.makeShortNames = function (nameMap, first) {
    // Make short versions of names from dict of the form {id: 'Last, First ...', ...}
    // If first, use first name as prefix, rather than last name
    // Returns map of id->shortName
    var prefixDict = {};
    var suffixesDict = {};
    var keys = Object.keys(nameMap);
    for (var j=0; j<keys.length; j++) {
	var idValue = keys[j];
	var name = nameMap[idValue];
	var ncomps = name.split(',');
	var lastName = ncomps[0].trim();
	var firstmiddle = (ncomps.length > 0) ? ncomps[1].trim() : '';
        var fcomps = firstmiddle.split(/\s+/);
        if (first) {
            // For Firstname, try suffixes in following order: middle_initials+Lastname
            var firstName = fcomps[0] || idValue;
            var suffix = lastName;
	    for (var k=1; k<fcomps.length; k++)
                suffix = fcomps[k].slice(0,1).toUpperCase() + suffix;
	    if (!(firstName in prefixDict))
		prefixDict[firstName] = [];
            prefixDict[firstName].push(idValue);
            suffixesDict[idValue] = suffix;
        } else {
            // For Lastname, try suffixes in following order: initials, first/middle names
            if (!lastName)
                lastName = idValue;
	    var initials = '';
	    for (var k=0; k<fcomps.length; k++)
                initials += fcomps[k].slice(0,1).toUpperCase() ;
	    if (!(lastName in prefixDict))
		prefixDict[lastName] = [];
            prefixDict[lastName].push(idValue);
            suffixesDict[idValue] = [initials, firstmiddle];
        }
    }

    var shortMap = {};
    var prefixes = Object.keys(prefixDict);
    for (var m=0; m<prefixes.length; m++) {
	var prefix = prefixes[m];
	var idValues = prefixDict[prefix];
        var unique = null;
        for (var j=0; j < (first ? 1 : 2); j++) {
	    var suffixes = [];
	    var maxlen = 0;
	    for (var k=0; k < idValues.length; k++) {
		var suffix = suffixesDict[idValues[k]][j];
		maxlen = Math.max(maxlen, suffix.length);
		suffixes.push(suffix);
	    }
            for (var k=0; k < maxlen+1; k++) {
		var truncObj = {};
		for (var l=0; l < suffixes.length; l++)
		    truncObj[suffixes[l].slice(0,k)] = 1;

                if (suffixes.length == Object.keys(truncObj).length) {
                    // Suffixes uniquely map id for this truncation
                    unique = [j, k];
                    break;
                }
            }
            if (unique) {
                break;
            }
        }
        for (var j=0; j<idValues.length; j++) {
	    var idValue = idValues[j];
            if (unique) {
                shortMap[idValue] = prefix + suffixesDict[idValue][unique[0]].slice(0,unique[1]);
            } else {
                shortMap[idValue] = prefix + '-' + idValue;
            }
        }
    }

    return shortMap;
}


Slidoc.switchNav = function () {
    var elem = document.getElementById("slidoc-topnav");
    if (elem.classList.contains("slidoc-responsive")) {
	elem.classList.remove("slidoc-responsive");
    } else {
        elem.classList.add("slidoc-responsive");
    }
}

Slidoc.userLogout = function () {
    if (!window.confirm('Do want to logout user '+(window.GService ? GService.gprofile.auth.id : '')+'?'))
	return false;
    localDel('auth');
    sessionAbort('Logged out');
}

Slidoc.userLogin = function (msg, retryCall) {
    Slidoc.log('Slidoc.userLogin:', msg, retryCall);
    if (Slidoc.serverCookie)
	sessionAbort(msg || 'Error in authentication');
    else
	GService.gprofile.promptUserInfo(Sliobj.params.siteName, Sliobj.params.fileName, false, GService.gprofile.auth.type, GService.gprofile.auth.id, msg||'', Slidoc.userLoginCallback.bind(null, retryCall||null));
}

Slidoc.userLoginCallback = function (retryCall, auth) {
    Slidoc.log('Slidoc.userLoginCallback:', auth);

    if (auth) {
	if (auth.remember)
	    localPut('auth', auth);
	else
	    localDel('auth');
	if (retryCall) {
	    GService.gprofile.auth.token = auth.token;
	    retryCall();
	} else {
	    location.reload(true);
	}
    } else {
	localDel('auth');
	sessionAbort('Logged out');
    }
}

function retakesRemaining() {
    if (!Sliobj.params.maxRetakes || !Sliobj.session || Sliobj.session.submitted)
	return 0;
    var retakesCount = Sliobj.session.retakes ? Sliobj.session.retakes.split(',').length : 0;
    return Sliobj.params.maxRetakes - retakesCount;
}

Slidoc.resetPaced = function (delRow) {
    Slidoc.log('Slidoc.resetPaced:', delRow);
    var label = delRow ? 'delete' : 'reset';
    var userId = getUserId();

    if ((delRow || !retakesRemaining()) && Sliobj.params.gd_sheet_url) {
	if (!Sliobj.gradableState && userId != Sliobj.params.testUserId) {
	    alert('Unable to '+label+' session linked to Google Docs');
	    return false;
	}
    }

    if (!Slidoc.testingActive() && !window.confirm('Confirm that you want to completely '+label+' all answers/scores for user '+userId+' in session '+Sliobj.sessionName+'?'))
	return false;
    
    if (Sliobj.params.gd_sheet_url) {
	if (!delRow && Sliobj.params.paceLevel >= ADMIN_PACE && Sliobj.session.submitted) {
	    alert('Cannot reset submitted instructor-paced session');
	    return false;
	}

	if (!Slidoc.testingActive() && !window.confirm('Re-confirm session '+label+' for user '+userId+'?'))
	    return false;
	var gsheet = getSheet(Sliobj.sessionName);

	if (delRow) {
	    gsheet.delRow(userId, resetSessionCallback.bind(null, delRow));
	} else {
	    gsheet.getRow(userId, {resetrow: 1}, resetSessionCallback.bind(null, delRow));
	}

    } else {
	if (delRow) {
	    var sessionObj = localGet('sessions');
	    delete sessionObj[Sliobj.params.fileName];
	    localPut('sessions', sessionObj);
	} else {
	    Sliobj.session = createSession();
	    Sliobj.feedback = null;
	    sessionPut();
	}
	if (!Slidoc.testingActive())
	    location.reload(true);
    }

}

function resetSessionCallback(delRow, result, retStatus) {
    Slidoc.log('resetSessionCallback:', delRow, result, retStatus);
    if (!result) {
	alert('Error in resetting session: '+retStatus.error);
    } if (delRow) {
	alert('Session has been deleted');
	window.location = Sliobj.sitePrefix || '/';
    } else {
	sessionReload('Session has been reset. Reload page to restart?');
    }
}

Slidoc.showConcepts = function (submitMsg) {
    var firstSlideId = getVisibleSlides()[0].id;
    var attr_vals = getChapterAttrs(firstSlideId);
    var chapter_id = parseSlideId(firstSlideId)[0];
    var questionConcepts = [];
    for (var j=0; j<attr_vals.length; j++) {
	var question_attrs = attr_vals[j];
	var slide_id = chapter_id + '-' + zeroPad(question_attrs.slide, 2);
	var concept_elem = document.getElementById(slide_id+"-concepts");
	var qConcepts = [[], []];
	if (concept_elem) {
	    var comps = concept_elem.textContent.trim().split(':');
	    for (var m=0; m<Math.min(2,comps.length); m++) {
		if (comps[m].trim()) {
		    var subcomps = comps[m].trim().split(';');
		    for (var k=0; k<subcomps.length; k++) {
			if (subcomps[k].trim())
			    qConcepts[m].push(subcomps[k].trim().toLowerCase());
		    }
		}
	    }
	}
	questionConcepts.push(qConcepts);
    }
    var missedConcepts = trackConcepts(Sliobj.scores.qscores, questionConcepts, Sliobj.allQuestionConcepts)

    var html = '';

    if (Sliobj.params.questionsMax) {
	html += 'Questions answered: '+Sliobj.scores.questionsCount;
	if (!controlledPace())
	    html += '/'+(Sliobj.params.questionsMax-Sliobj.params.disabledCount);
	html += '<br>\n';
    }

    if (!displayAfterGrading()) {
	// No need to wait until grading to display automatic scores
	if (Sliobj.params.totalWeight > Sliobj.params.scoreWeight) {
	    // There are manually graded questions
	    if (Sliobj.feedback && isNumber(Sliobj.feedback.q_total)) {
		// DIsplay total grade
		var feedbackGrade = parseNumber(Sliobj.feedback.q_total);
		html += 'Total grade: '+feedbackGrade+'/'+Sliobj.params.totalWeight+'<br>';
		
		if (Sliobj.gradableState) {
		    var userId = getUserId();
		    var computedGrade = computeGrade(userId);
		    if (computedGrade != null && Math.abs(feedbackGrade - parseNumber(computedGrade)) > 0.01) {
			alert('Warning: Inconsistent re-computed total grade: q_total!='+computedGrade)
		    }
		}
	    } else if (Sliobj.params.scoreWeight) {
		// Display autoscore, if available
		var scoreValue = null
		if (Sliobj.feedback && isNumber(Sliobj.feedback.q_scores)) {
		    scoreValue = Sliobj.feedback.q_scores;

		    if (Sliobj.gradableState) {
			if (Sliobj.scores.weightedCorrect != null && Math.abs(scoreValue - parseNumber(Sliobj.scores.weightedCorrect)) > 0.01) {
			    alert('Warning: Inconsistent re-computed weighted score: q_score!='+Sliobj.scores.weightedCorrect)
			}
		    }
		} else if (Sliobj.session.submitted) {
		    scoreValue = Sliobj.scores.weightedCorrect;
		}
		if (scoreValue != null)
		    html += 'Weighted autoscore portion only: '+scoreValue+' (out of '+Sliobj.params.scoreWeight+')<br>';
	    }
	} else if (Sliobj.session.submitted && Sliobj.params.scoreWeight) {
	    // Submitted autoscored session
	    html += 'Weighted autoscore: '+Sliobj.scores.weightedCorrect+' (out of '+Sliobj.params.scoreWeight+')<br>\n';
	}

	if (!controlledPace() && Sliobj.session.submitted && Sliobj.allQuestionConcepts.length) {
	    html += '<p></p>';
	    var labels = ['<h3>Primary concepts missed</h3>', '<h3>Secondary concepts missed</h3>'];
	    for (var m=0; m<labels.length; m++)
		html += labels[m]+conceptStats(Sliobj.allQuestionConcepts[m], missedConcepts[m])+'<p></p>';
	}
    }

    if (submitMsg) {
	html = submitMsg + '<p></p>' + html;
    } else {
	if (!html)
	    html += Sliobj.session.lastSlide ? '(Not tracking question concepts!)' : '(Question concepts tracked only in paced mode!)';
	html = '<b>Answer scores</b><p></p>' + html;
    }
    
    Slidoc.showPopup(html);
}

Slidoc.prevUser = function () {
    if (!Sliobj.gradingUser)
	return;
    Slidoc.nextUser(false);
}

Slidoc.slideViewAdvance = function () {
    if ('incremental_slides' in Sliobj.params.features && Sliobj.maxIncrement && Sliobj.curIncrement < Sliobj.maxIncrement)
	Slidoc.slideViewIncrement();
    else
	Slidoc.slideViewGo(true);
}

Slidoc.slideViewIncrement = function () {
    //console.log('Slidoc.slideViewIncrement: ', Sliobj.curIncrement, Sliobj.maxIncrement);
    if (Sliobj.gradingUser) {
	Slidoc.nextUser(true);
	return;
    }
    if (!Sliobj.currentSlide)
        return;

    var slide_id = Slidoc.getCurrentSlideId();
    if (slide_id in Sliobj.incrementPlugins) {
	Slidoc.PluginManager.invoke(Sliobj.incrementPlugins[slide_id], 'incrementSlide');
	return;
    }
    
    if (!Sliobj.maxIncrement || !('incremental_slides' in Sliobj.params.features))
        return;

    if (Sliobj.curIncrement < Sliobj.maxIncrement) {
	Sliobj.curIncrement += 1;
        document.body.classList.add('slidoc-display-incremental'+Sliobj.curIncrement);
    }
    if (Sliobj.curIncrement == Sliobj.maxIncrement)
	toggleClass(false, 'slidoc-incremental-view');

    return false;
}

function clickableSpan(text, jsCode, disabled) {
    return '<span ' + (disabled ? 'class="slidoc-disabled"' : 'class="slidoc-clickable" onclick="'+jsCode+'"') + '>' + text + '</span>';
}

function clickableLink(text, url, disabled) {
    if (disabled)
	return clickableSpan(text, '', disabled);
    else
	return '<a class="slidoc-clickable" href="'+url+'">' + text + '</a>';
}

///////////////////////////////
// Section 10: Help display
///////////////////////////////

Slidoc.viewHelp = function () {
    var html = '<b>Help Info</b><p></p>\n';
    var hr = '<tr><td colspan="2"><hr></td></tr>';
    var docsPrefix = '_docs';
    if (!Sliobj.sessionName)
	docsPrefix = '/' + docsPrefix;
    else if (Sliobj.previewState)
	docsPrefix = '../' + Sliobj.sessionName + '/' + docsPrefix;
    else
	docsPrefix = Sliobj.sessionName + '/' + docsPrefix;

    html += '<table class="slidoc-slide-help-table">';
    html += formatHelp('Navigating documents', docsPrefix+'/NavigationHelp.html');
    if (gradingAccess()) {
	html += '<tr><td>&nbsp;</td></tr>';
	html += formatHelp('Adaptive rubrics', docsPrefix+'/AdaptiveRubrics.html');
	html += formatHelp('Randomized exams', docsPrefix+'/RandomizedExams.html');
    }
    html += '</table>';
    Slidoc.showPopup(html);
}

function formatHelp(label, link) {
    return '<tr><td><a class="slidoc-clickable" href="'+link+'" target="_blank">' + label + '</a></td></tr>';
}

var Slide_help_list_a = [
    ['q, Escape',           'exit',  'exit slide mode'],
    ['h, Home, Fn&#9668;',  'home',  'home (first) slide'],
    ['e, End, Fn&#9658;',   'end',   'end (last) slide']
];

var Slide_help_list_b = [
    ['i, &#9660;',          'i',     'incremental item'],
    ['f',                   'f',     'fullscreen mode'],
    ['g',                   'g',     'navigation help'],
    ['t',                   't',     'table of contents'],
    ['m',                   'm',     'missed question concepts']
];

Slidoc.viewNavHelp = function () {
    var html = '<b>Navigation commands</b><p></p>\n';
    var hr = '<tr><td colspan="3"><hr></td></tr>';
    var userId = getUserId();
    html += '<table class="slidoc-slide-help-table">';
    html += formatNavHelp(['Key', '', 'Action']);
    if (Sliobj.currentSlide) {
	for (var j=0; j<Slide_help_list_a.length; j++)
	    html += formatNavHelp(Slide_help_list_a[j]);
	html += formatNavHelp(['p, &#9668;',          'left',  'previous slide']);
	html += formatNavHelp(['n, &#9658;, space',   'right', 'next slide']);
	for (var j=0; j<Slide_help_list_b.length; j++)
	    html += formatNavHelp(Slide_help_list_b[j]);
    } else if (Sliobj.params.fileName) {
	html += formatNavHelp(['&#9668;',   'left',  'collapse']);
	html += formatNavHelp(['&#9658;',   'right', 'uncollapse']);
	html += formatNavHelp(['Escape', 'unesc', 'enter slide mode']);
    }
    html += '</table>';
    Slidoc.showPopup(html);
}

function formatNavHelp(help_entry) {  // help_entry = [keyboard_shortcuts, key_code, description]
    return '<tr><td>' + help_entry[0] + '</td><td><span class="slidoc-clickable" onclick="Slidoc.handleKey('+ "'"+help_entry[1]+"'"+ ');">' + help_entry[2] + '</span></td></tr>';
}

var Slide_view_handlers = {
    'esc':   function() { Slidoc.slideViewEnd(); },
    'q':     function() { Slidoc.slideViewEnd(); },
    'exit':  function() { Slidoc.slideViewEnd(); },
    'home':  function() { Slidoc.slideViewGo(false, 1); },
    'h':     function() { Slidoc.slideViewGo(false, 1); },
    'end':   function() { Slidoc.slideViewGoLast(); },
    'e':     function() { Slidoc.slideViewGoLast(); },
    'left':  function() { Slidoc.slideViewGo(false); },
    'p':     function() { Slidoc.slideViewGo(false); },
    'right': function() { Slidoc.slideViewAdvance(); },
    'n':     function() { Slidoc.slideViewAdvance(); },
    'space': function() { Slidoc.slideViewAdvance(); },
    'up':    function() { Slidoc.prevUser(); },
    'down':  function() { Slidoc.slideViewIncrement(); },
    'i':     function() { Slidoc.slideViewIncrement(); },
    'f':     function() { Slidoc.docFullScreen(); },
    'g':     function() { Slidoc.viewNavHelp(); },
    't':     function() { Slidoc.contentsDisplay(); },
    'm':     function() { Slidoc.showConcepts(); },
    'reset': function() { Slidoc.resetPaced(); }
}

var Key_codes = {
    27: 'esc',
    32: 'space',
    35: 'end',
    36: 'home',
    37: 'left',
    38: 'up',
    39: 'right',
    40: 'down',
    68: 'd',
    69: 'e',
    70: 'f',
    71: 'g',
    72: 'h',
    73: 'i',
    77: 'm',
    78: 'n',
    80: 'p',
    81: 'q',
    83: 's',
    84: 't'
};

function scrollTextArea(areaElem, top) {
    setTimeout(function() {
	if (top) {
	    areaElem.style.height = areaElem.scrollHeight + 12 + 'px';
	    areaElem.scrollIntoView(true);
	} else {
	    areaElem.scrollTop = areaElem.scrollHeight;
	    areaElem.style.height = areaElem.scrollHeight + 12 + 'px';
	}
	areaElem.focus();
    }, 200);
}

var shiftKeyDown = false;
document.onkeyup = function(evt) {
    //Slidoc.log('document.onkeyup:', evt);
    if (evt.keyCode == 16)
	shiftKeyDown = false;
}

document.onkeydown = function(evt) {
    //Slidoc.log('document.onkeydown:', evt);
    if (evt.keyCode == 16)
	shiftKeyDown = true;

    if (!Sliobj.currentSlide && (evt.keyCode == 32 || evt.keyCode > 44))
	return;  // Handle printable input normally (for non-slide view)

    var nodeName = evt.target.nodeName.toLowerCase();
    if ((nodeName == 'input' || nodeName == 'textarea') && evt.keyCode >= 32)
	return;  // Disable arrow key handling for input/textarea

    if (nodeName == 'textarea' && (evt.keyCode == 10 || evt.keyCode == 13)) {
	if (evt.ctrlKey) {
	    // Control-Enter
	    if (Sliobj.previewWin && Sliobj.currentSlide) {
		// Preview updating
		evt.stopPropagation();
		evt.preventDefault();
		Slidoc.slideEdit('update', Slidoc.getCurrentSlideId());
		return false;
	    }
	} else if (evt.shiftKey) {
	    // Shift-Enter
	    if (checkActiveEdit(true)) {
		// Preview saving
		evt.stopPropagation();
		evt.preventDefault();
		Slidoc.slideEdit('save', Slidoc.getCurrentSlideId());
		return false;
	    }
	} else if (evt.altKey) {
	    // Alt-Enter
	    // Append image link to end of text area
	    if (Slidoc.imageLink) {
		evt.target.value += '\n\n' + Slidoc.imageLink;
		scrollTextArea(evt.target);
	    } else if (Sliobj.previewWin && Sliobj.previewWin.Slidoc && Sliobj.previewWin.Slidoc.imageLink) {
		evt.target.value += '\n\n' + Sliobj.previewWin.Slidoc.imageLink;
		scrollTextArea(evt.target);
	    }
	}
    }

    if (!(evt.keyCode in Key_codes))
	return;

    return Slidoc.handleKey(Key_codes[evt.keyCode]);
}

Slidoc.handleKey = function (keyName, swipe) {
    Slidoc.log('Slidoc.handleKey:', keyName, swipe);
    if (keyName == 'right' && Slidoc.advanceStep())
	return false;

    if (Sliobj.closePopup) {
	Sliobj.closePopup();
	if (keyName == 'esc' || keyName == 'g' || keyName == 'm' || keyName == 'q' || keyName == 't')
	    return false;
    }

    if (Sliobj.currentSlide) {
	if (!(keyName in Slide_view_handlers))
	    return;
	Slide_view_handlers[keyName]();
	return false;

    } else if (Sliobj.chainActive) {
	if (keyName == 'left')  { Sliobj.chainActive[0](); return false; }
	if (keyName == 'esc')   { Sliobj.chainActive[1](); return false; }
	if (keyName == 'right') { Sliobj.chainActive[2](); return false; }

    } else if (Sliobj.assessmentView && keyName == 'down') {
	window.print();
	if (Sliobj.gradableState)
	    Slidoc.nextUser(true);
    } else {
	if (keyName == 'esc' || keyName == 'unesc')   { Slidoc.slideViewStart(); return false; }

	if (keyName == 'reset') { Slidoc.resetPaced(); return false; }
	
	if (keyName == 'left' && !swipe) { Slidoc.accordionView(true); return false; }
	if (keyName == 'right' && !swipe) { Slidoc.accordionView(false); return false; }
	
	if (Sliobj.curChapterId) {
	    var chapNum = parseSlideId(Sliobj.curChapterId)[1];
	    var chapters = document.getElementsByClassName('slidoc-reg-chapter');
	    if (keyName == 'left'  && chapNum > 1)  { goSlide('#slidoc'+zeroPad(chapNum-1,2)+'-01'); return false; }
	    if (keyName == 'right' && chapNum < chapters.length)  { goSlide('#slidoc'+zeroPad(chapNum+1,2)+'-01'); return false; }
	}
    }
	
   return;
};

Slidoc.inputKeyDown = function (evt) {
    Slidoc.log('Slidoc.inputKeyDown', evt.keyCode, evt.target, evt.target.id);
    if (evt.keyCode == 13) {
	var inputElem = document.getElementById(evt.target.id.replace('-input', '-click'));
	inputElem.onclick();
	evt.target.blur();
    }
}

function parseSlideId(slideId) {
    // Return chapterId, chapter number, slide number (or 0)
    var match = SLIDE_ID_RE.exec(slideId);
    if (match)
	return [match[1], parseInt(match[2]), match[4] ? parseInt(match[4]) : 0];
    var chapters = document.getElementsByClassName('slidoc-reg-chapter');

    if (slideId.slice(0,20) == 'slidoc-index-concept')
	return ['slidoc'+zeroPad(chapters.length+1,2), chapters.length+1, 0];

    if (slideId.slice(0,21) == 'slidoc-qindex-concept')
	return ['slidoc'+zeroPad(chapters.length+2,2), chapters.length+2, 0];
    
    return [null, 0, 0];
}

function parseElem(elemId) {
    try {
	var elem = document.getElementById(elemId);
	if (elem && elem.textContent) {
	    return JSON.parse(atob(elem.textContent));
	}
    } catch (err) {Slidoc.log('parseElem: Error in parsing '+elemId+' JSON/Base64'); }
    return null;
}

function getChapterAttrs(slide_id) {
    var chapter_id = parseSlideId(slide_id)[0];
    return chapter_id ? parseElem(chapter_id+'-01-attrs') : null;
}

function getQuestionNumber(slide_id) {
    var answerElem = document.getElementById(slide_id+'-answer-prefix');
    return answerElem ? parseInt(answerElem.dataset.qnumber) : 0;
}

function getQuestionAttrs(slide_id) {
    var question_number = getQuestionNumber(slide_id);
    if (!question_number)
	return null;
    var attr_vals = getChapterAttrs(slide_id);
    return attr_vals ? attr_vals[question_number-1] : null;
}

function showDialog(action, testEvent, prompt, value) {
    Slidoc.log('showDialog:', action, testEvent, prompt, value);
    var testValue = Slidoc.reportTestAction(testEvent);
    if (testValue !== null) {
	if (!Sliobj.testStep)
	    return testValue;
	value = testValue
    }
    switch (action) {
    case 'alert':
	return alert(prompt);
    case 'confirm':
	return window.confirm(prompt);
    case 'prompt':
	return window.prompt(prompt, value||'');
    default:
	return alert('INTERNAL ERROR: Unknown dialog action '+action+': '+prompt);
    }
}

////////////////////////
// Section 10b: Events
////////////////////////

Slidoc.sendEvent = function (eventType, eventName) // Extra Args
{
    if (Sliobj.previewState || Sliobj.updateView)  // Do not transmit events when previewing
	return;
    var extraArgs = Array.prototype.slice.call(arguments).slice(2);
    Slidoc.log('Slidoc.sendEvent:', eventType, eventName, extraArgs);
    GService.sendEventWS('', eventType, eventName, extraArgs);
}

Sliobj.eventReceiver = function(eventMessage) {
    Slidoc.log('Sliobj.eventReceiver:', eventMessage);
    var eventSource = eventMessage[0];
    var eventName = eventMessage[1];
    var eventArgs = eventMessage[2];

    if (eventName.indexOf('.') > 0) {
	// Plugin method; ignore if not on last paced slide
	if (!Sliobj.currentSlide || !Sliobj.session || Sliobj.currentSlide != Sliobj.session.lastSlide) {
	    Slidoc.log('Sliobj.eventReceiver: IGNORED PLUGIN EVENT');
	    return;
	}
	var comps = eventName.split('.');
	var pluginName = comps[0];
	var pluginMethodName = comps[1];
	var slide_id = (comps.length > 2) ? comps[2] : ''; // '' slide_id => session plugin
	if (!Sliobj.slidePluginList[slide_id]) {
	    Slidoc.log('Sliobj.eventReceiver: No plugins loaded for slide '+slide_id);
	    return;
	}
	for (var j=0; j<Sliobj.slidePluginList[slide_id].length; j++) {
	    if (Sliobj.slidePluginList[slide_id][j].name == pluginName)
		Slidoc.PluginManager.invoke.apply(null, [Sliobj.slidePluginList[slide_id][j], pluginMethodName].concat(eventArgs));
	}

    } else if (eventName == 'ReloadPage') {
	statefulReload(eventArgs.length ? eventArgs[0] : '');

    } else if (eventName == 'InteractiveMessage') {
	console.log('InteractiveMessage:', eventArgs[0]);
	Sliobj.interactiveMessages.unshift(eventArgs[0]);
	if (Sliobj.interactiveMessages.length > 100)
	    delete Sliobj.interactiveMessages[100];
	if (Sliobj.closePopup)
	    Sliobj.closePopup(null, eventName);

    } else if (eventName == 'LiveResponse') {
	if (!(eventArgs[0] in Sliobj.liveResponses))
	    Sliobj.liveResponses[eventArgs[0]] = [];
	Sliobj.liveResponses[eventArgs[0]][eventSource] = eventArgs.slice(1);
	if (Sliobj.closePopup)
	    Sliobj.closePopup(null, eventName);
	    
    } else if (eventName == 'AdminPacedForceAnswer') {
	if (controlledPace() && !Sliobj.session.questionsAttempted[eventArgs[0]]) {
	    // Force answer to unanswered question
	    var slide_id = eventArgs[1];
	    var ansElem = document.getElementById(slide_id+'-answer-click');
	    if (ansElem)
		Slidoc.answerClick(ansElem, slide_id, 'controlled');
	}
    } else if (eventName == 'AdminPacedAdvance') {
	if (controlledPace()) {
	    Sliobj.adminPaced = Math.max(eventArgs[0]||0, Sliobj.adminPaced);

	    if (Sliobj.session.paced && !Sliobj.session.submitted && Sliobj.adminPaced == Sliobj.session.lastSlide+1 && Sliobj.currentSlide == Sliobj.session.lastSlide) {
		// Advance if viewing last slide (if question has been attempted)
		if (Sliobj.questionSlide && !Sliobj.session.questionsAttempted[Sliobj.questionSlide.qnumber] && Sliobj.session.remainingTries)
		    alert('Please answer question to proceed');
		else
		    Slidoc.slideViewGo(true, Sliobj.session.lastSlide+1);  // visible slides list has been updated
	    }
	}
	Slidoc.reportTestAction('AdminPacedAdvance');
    }
}

Slidoc.interact = function() {
    var html = '<b>Interactivity</b><p></p>\n';
    if (!isController() || !Sliobj.session) {
	html += 'Interactivity only available for admin-paced sessions';
    } else if (Sliobj.session.submitted) {
	html += 'Interactivity not available for submitted sessions';
    } else {
	var siteTwitter = Sliobj.serverData.site_twitter || '';
	var interactURL = location.protocol+'//'+location.host+'/send';
	html += '<span class="slidoc-clickable" onclick="Slidoc.toggleInteract();">'+(Sliobj.interactiveMode?'End':'Begin')+' interact mode</span><p></p>';
	html += 'To interact:<ul>';
	if (siteTwitter.match(/^@/)) {
	    html += '<li>Tweet or text 40404: <code>'+siteTwitter+' answer</code></li>';
	} else if (siteTwitter) {
	    html += '<li>Text 40404: <code>d '+siteTwitter+' answer</code></li>';
	    html += '<li>Twitter direct message @'+siteTwitter+': <code>answer</code></li>';
	}
	html += '<li><a href="'+interactURL+'" target="_blank"><code>'+interactURL+'</code></a></li>';
	html += '<li><a href="'+Sliobj.sitePrefix+'/_interactcode" target="_blank"><b>QR code</b></a></li>';
	html += '</ul>';
	html += clickableSpan('Live message display', 'interactiveMessageDisplay();', !Sliobj.interactiveMode)+'<p></p>';
    }
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    Slidoc.showPopup(html);
}

Slidoc.rollbackInteractive = function() {
    if (!window.confirm('Rollback interactive session to last answered question slide (or start slide)?'))
	return;
    GService.requestWS('rollback', [], rollbackCallback);
}

function rollbackCallback(retObj, errMsg) {
    Slidoc.log('rollbackCallback:', retObj, errMsg);
    var msg = '';
    if (retObj && retObj.result == 'success') {
	msg = 'Interactive session has been rolledback. Reload page.';
    } else {
	if (retObj && retObj.error) {
	    msg += retObj.error;
	}
	if (errMsg) {
	    msg += retObj.error;
	}
    }
    alert(msg || 'Unknown error in rollback');
}

Slidoc.resetQuestion = function(userId) {
    var slide_id = Slidoc.getCurrentSlideId();
    if (!slide_id) {
	alert('No current slide');
	return;
    }
    var question_number = getQuestionNumber(slide_id);
    if (!question_number) {
	alert('Not a question slide');
    }

    if (Sliobj.session && Sliobj.session.submitted && Sliobj.session.submitted != 'GRADING') {
	alert('Must unsubmit session(s) before resetting response to questions');
	return;
    }
    if (!window.confirm('Reset (erase) '+(userId||'all users')+' response to question '+question_number+'?'))
	return;
    
    if (Sliobj.currentSlide == Sliobj.session.lastSlide && Sliobj.params.paceLevel >= ADMIN_PACE) {
	// AdminPaced last slide; no need to confirm twice
    } else {
    if (!window.confirm('Resetting question '+question_number+' is not reversible. Proceed anyway?'))
	return;
    }
    GService.requestWS('reset_question', [question_number, userId||''], resetQCallback);
}

function resetQCallback(retObj, errMsg) {
    Slidoc.log('resetQCallback:', retObj, errMsg);
    var msg = '';
    if (retObj && retObj.result == 'success') {
	msg = 'Question has been successfully reset. Reload page.';
    } else {
	if (retObj && retObj.error) {
	    msg += retObj.error;
	}
	if (errMsg) {
	    msg += retObj.error;
	}
    }
    alert(msg || 'Unknown error in question reset');
}

Slidoc.toggleInteract = function () {
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    Sliobj.interactiveMode = !Sliobj.interactiveMode;
    toggleClass(Sliobj.interactiveMode, 'slidoc-interact-view');
    enableInteract(Sliobj.interactiveMode);
}

function enableInteract(active) {
    Slidoc.log('enableInteract:', active, Sliobj.interactiveSlide, Sliobj.session.lastSlide);
    if (!active) {
	if (Sliobj.interactiveSlide) {
	    Sliobj.interactiveSlide = false;
	    GService.requestWS('interact', ['end', '', null, ''], interactCallback);
	}
	return;
    }
    if (!isController() || Sliobj.session.submitted || Sliobj.interactiveSlide)
	return;

    var lastSlideId = getVisibleSlides()[Sliobj.session.lastSlide-1].id;
    var qattrs = getQuestionAttrs(lastSlideId);
    if (qattrs && qattrs.qnumber in Sliobj.session.questionsAttempted)
	qattrs = null;

    if (!qattrs)
	return;
    
    // Start 'interact' for unanswered question slides only
    Sliobj.interactiveSlide = true;
    GService.requestWS('interact', ['start', lastSlideId, qattrs, !!Sliobj.params.features.rollback_interact], interactCallback);

    // Note: Closing websocket will disable interactivity
}

function interactCallback() {
    Slidoc.log('interactCallback:');
}


Slidoc.hideSlides = function() {
    // Toggle explicitly hidden slides
    if (getUserId() != Sliobj.params.testUserId)
	return false;
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    Sliobj.showHiddenSlides = !Sliobj.showHiddenSlides;
    toggleClass(Sliobj.showHiddenSlides, 'slidoc-showhidden-view');
}

////////////////////////
// Section 11: Plugins
////////////////////////

function setupPlugins() {
    Slidoc.log('setupPlugins:');
    Sliobj.activePlugins = {};
    Sliobj.pluginNames = [];
    Sliobj.setupPluginDict = {};
    Sliobj.setupPluginList = [];
    var allContent = document.getElementsByClassName('slidoc-plugin-content');
    for (var j=0; j<allContent.length; j++) {
	var pluginName = allContent[j].dataset.plugin;
	var slide_id = allContent[j].dataset.slideId;
	var args = decodeURIComponent(allContent[j].dataset.args || '');
	var button = decodeURIComponent(allContent[j].dataset.button || '');
	var pluginDefName = pluginName.split('-')[0];
	if (!(pluginDefName in Slidoc.PluginDefs)) {
	    sessionAbort('ERROR Plugin '+pluginDefName+' not defined properly; check for syntax error messages in Javascript console');
	}
	if (!(pluginName in Sliobj.activePlugins)) {
	    Sliobj.pluginNames.push(pluginName);
	    Sliobj.activePlugins[pluginName] = {randomOffset: Sliobj.pluginNames.length, args: {}, firstSlide: slide_id, button: {} };
	}
	Sliobj.activePlugins[pluginName].args[slide_id] = args;
	Sliobj.activePlugins[pluginName].button[slide_id] = button;
    }
    for (var j=0; j<Sliobj.pluginNames.length; j++) {
	var pluginName = Sliobj.pluginNames[j];
	var pluginInstance = createPluginInstance(pluginName, true);
	Sliobj.setupPluginDict[pluginName] = pluginInstance;
	Sliobj.setupPluginList.push(pluginInstance);
	Slidoc.PluginManager.optCall.apply(null, [pluginInstance, 'initSetup']);
    }
}

Slidoc.PluginManager.optCall = function (pluginInstance, action) //... extra arguments
{
    if (action in pluginInstance)
	return Slidoc.PluginManager.invoke.apply(null, arguments);
    else
	return null;	 
}

Slidoc.PluginMethod = function (pluginName, slide_id, action) //... extra arguments
{
    var extraArgs = Array.prototype.slice.call(arguments).slice(3);
    Slidoc.log('Slidoc.PluginMethod:', pluginName, slide_id, action, extraArgs);
    var pluginDefName = pluginName.split('-')[0];
    var globalInstance = Sliobj.globalPluginDict[pluginDefName];
    if (!globalInstance) {
	Slidoc.log("Slidoc.PluginMethod: ERROR Plugin "+pluginDefName+" not activated");
	return;
    }

    if (!slide_id) {
	var pluginInstance = globalInstance;
    } else {
	if (!Sliobj.slidePluginDict[slide_id] || !Sliobj.slidePluginDict[slide_id][pluginName]) {
	    Slidoc.log("Slidoc.PluginMethod: ERROR Plugin "+pluginName+" instance not found for slide '"+slide_id+"'");
	    return;
	}
	pluginInstance = Sliobj.slidePluginDict[slide_id][pluginName];
    }
    return Slidoc.PluginManager.invoke.apply(null, [pluginInstance, action].concat(extraArgs));
}

Slidoc.PluginManager.invoke = function (pluginInstance, action) //... extra arguments
{   // action == 'initSetup' initial setup after document is ready; may insert/modify DOM elements
    // action == 'initGlobal' resets global plugin properties for all slides (called at start/switch of session)
    // action == 'init' resets plugin properties for each slide (called at start/switch of session)
    // action == 'display' displays recorded user response (called at start/switch of session for each question)
    // action == 'disable' disables plugin (after user response has been recorded)
    // action == 'expect' returns expected correct answer (OBSOLETE)
    // action == 'response' records user response and uses callback to return a pluginResp object of the form:
    //    {name:pluginName, score:1/0/0.75/.../null, invalid: invalid_msg, output:output, tests:0/1/2}

    var extraArgs = Array.prototype.slice.call(arguments).slice(2);
    if (action != 'init')
	Slidoc.log('Slidoc.PluginManager.invoke:', pluginInstance, action, extraArgs);

    if (!(action in pluginInstance)) {
	Slidoc.log('ERROR Plugin action '+pluginInstance.name+'.'+action+' not defined');
	return null;
    }

    try {
	return pluginInstance[action].apply(pluginInstance, extraArgs);
    } catch(err) {
	sessionAbort('ERROR in invoking plugin '+pluginInstance.name+'.'+action+': '+err, err.stack);
    }
}

Slidoc.PluginManager.remoteCall = function (pluginName, pluginMethod, callback) { // Extra args
    Slidoc.log('Slidoc.PluginManager.remoteCall:', pluginName, pluginMethod);
    if (!Slidoc.websocketPath) {
	alert('Remote calling '+pluginName+'.'+pluginMethod+' only works with websocket connections');
	return;
    }
    var data = [pluginName, pluginMethod];
    for (var j=3; j<arguments.length; j++)
	data.push(arguments[j]);
    GService.requestWS('plugin', data, callback);
}

Slidoc.PluginManager.shareReady = function(share, qnumber) {
    if (share == 'after_answering' && Slidoc.PluginManager.answered(qnumber))
	return true;
    if (Slidoc.PluginManager.submitted())
	return (share == 'after_answering' ||
	        (share == 'after_due_date' && Slidoc.PluginManager.pastDueDate()) ||
	        (share == 'after_grading' && Slidoc.PluginManager.graded())
	       );
    else
	return false;
}

Slidoc.PluginManager.pastDueDate = function() {
    if (!Sliobj.session)
	return null;
    var dueDate = parseDate(Sliobj.dueDate) || parseDate(Sliobj.session ? Sliobj.session.lateToken : '') || parseDate(Sliobj.params.dueDate);
    return dueDate && ((new Date()) > dueDate);
}

Slidoc.PluginManager.getLiveResponses = function(qnumber) {
    return Sliobj.liveResponses[qnumber] || null;
}

Slidoc.PluginManager.getFileKey = function(filename, teamResponse) {
    if (Sliobj.sessionFileKey) {
	return Slidoc.genFileKey(Sliobj.sessionFileKey, filename,);
    } else if (teamResponse) {
	if (Sliobj.teamFileKey)
	    return Slidoc.genFileKey(Sliobj.teamFileKey, filename);
    } else {
	if (Sliobj.userFileKey)
	    return Slidoc.genFileKey(Sliobj.userFileKey, filename);
    }
    return '';
}

Slidoc.PluginManager.disable = function(pluginName, slide_id, displayCorrect) {
    Slidoc.log('Slidoc.PluginManager.disable:', pluginName, slide_id, displayCorrect);
    Slidoc.PluginMethod(pluginName, slide_id, 'disable', displayCorrect);
    // Switch to answered slide view if not printing exam
    var slideElem = document.getElementById(slide_id);
    if (!Sliobj.assessmentView && slideElem)
	slideElem.classList.add('slidoc-answercomplete-slideview');
}

Slidoc.PluginManager.adminAccess = function() {
    return !Sliobj.params.gd_sheet_url || Sliobj.fullAccess;
}

Slidoc.PluginManager.graded = function() {
    return Sliobj.gradeDateStr;
}

Slidoc.PluginManager.submitted = function() {
    return Sliobj.session && Sliobj.session.submitted;
}

Slidoc.PluginManager.answered = function(qnumber) {
    return Sliobj.session && Sliobj.session.questionsAttempted[qnumber];
}

Slidoc.PluginManager.previewStatus = function() {
    return Sliobj.previewState || Sliobj.reloadCheck;
}

Slidoc.PluginManager.lateSession = function() {
    return Sliobj.session.lateToken == LATE_SUBMIT;
}

Slidoc.PluginManager.teamName = function() {
    return Sliobj.session ? (Sliobj.session.team || '') : '';
}

Slidoc.PluginManager.saveSession = function() {
    if (!Sliobj.session.paced || Sliobj.session.submitted)
	return;
    sessionPut();
}


Slidoc.PluginManager.splitNumericAnswer = function(corrAnswer) {
    // Return [answer|null, error|null]
    if (!corrAnswer)
	return [null, 0.0];
    var comps = corrAnswer.split('+/-');
    var corrValue = parseNumber(comps[0]);
    var corrError = 0.0;
    if (corrValue != null && comps.length > 1) {
	comps[1] = comps[1].trim();
	if (comps[1].slice(-1) == '%') {
	    corrError = parseNumber(comps[1].slice(0,-1));
	    if (corrError && corrError > 0)
		corrError = (corrError/100.0)*corrValue;
	} else {
	    corrError = parseNumber(comps[1]);
	}
    }
    if (corrError)
	corrError = Math.abs(corrError);
    return [corrValue, corrError];
}

function evalPluginArgs(pluginName, argStr, slide_id) {
    // Evaluates plugin init args in appropriate context
    if (!argStr)
	return [];
    try {
	Slidoc.log('evalPluginArgs:', pluginName, argStr, slide_id, getSlideParams(slide_id));
	var argVals = evalExpr(getSlideParams(slide_id), '['+argStr+']');
	return argVals;
    } catch (err) {
	var errMsg = 'evalPluginArgs: ERROR in init('+argStr+') arguments for plugin '+pluginName+' in '+slide_id+': '+err;
	Slidoc.log(errMsg);
	alert(errMsg);
	return [argStr];
    }
}

function createPluginInstance(pluginName, nosession, slide_id, slideData, slideParams) {
    ///Slidoc.log('createPluginInstance:', pluginName, nosession, slide_id, slideParams);
    var pluginDefName = pluginName.split('-')[0];
    var pluginDef = Slidoc.PluginDefs[pluginDefName];
    if (!pluginDef) {
	Slidoc.log('ERROR Plugin '+pluginDefName+' not found');
	return;
    }

    var defCopy;
    if (nosession)
	defCopy = pluginDef.setup || {};
    else if (!slide_id)
	defCopy = pluginDef.global || {};
    else
	defCopy = copyAttributes(pluginDef, ['setup', 'global']);
    defCopy.name = pluginName;
    defCopy.pluginLabel = 'slidoc-plugin-'+pluginName;
    defCopy.slideData = slideData || null;

    defCopy.initArgs = [];
    if (slide_id) {
	if (pluginName == 'Params') {
	    var footer_elem = getSlideFooter(slide_id);
	    if (footer_elem && footer_elem.dataset.functionCount && Sliobj.params.paramFunctions) {
		defCopy.initArgs = [ Sliobj.params.paramFunctions.slice(0,footer_elem.dataset.functionCount) ];
	    }
	} else {
	    defCopy.initArgs = evalPluginArgs(pluginName, Sliobj.activePlugins[pluginName].args[slide_id], slide_id);
	}
    }

    var auth = window.GService && GService.gprofile && GService.gprofile.auth;
    defCopy.userId = auth ? auth.id : null;
    defCopy.displayName = auth ? auth.displayName : null;
    defCopy.gradableState = Sliobj.gradableState;
    defCopy.testUser = (getUserId() == Sliobj.params.testUserId);
    defCopy.sessionName = Sliobj.sessionName;

    defCopy.remoteCall = Slidoc.PluginManager.remoteCall.bind(null, pluginName);

    var prefix = 'plugin_'+pluginName+'_';
    var paramKeys = Object.keys(Sliobj.params);
    defCopy.params = {};
    for (var j=0; j< paramKeys.length; j++) {
	if (paramKeys[j].slice(0,prefix.length) == prefix) {
	    defCopy.params[paramKeys[j].slice(prefix.length)] = Sliobj.params[paramKeys[j]];
	}
    }

    if (nosession) {
	defCopy.setup = null;
	defCopy.global = null;
	defCopy.persist = null;
	defCopy.paced = 0;
    } else {
	defCopy.setup = Sliobj.setupPluginDict[pluginName];

	if (!(pluginName in Sliobj.session.plugins))
	    Slidoc.log('ERROR: Persistent plugin store not found for plugin '+pluginName);
	
	defCopy.persist = Sliobj.session.plugins[pluginName];
	defCopy.paced = Sliobj.session.paced;

	var randomOffset = Sliobj.session.randomSeed + Sliobj.seedOffset.plugins + Sliobj.activePlugins[pluginName].randomOffset;
	if (!slide_id) {
	    // Global seed for all instances of the plugin
	    defCopy.global = null;
	    defCopy.slideId = '';
	    defCopy.slideParams = null;
	    defCopy.randomSeed = Slidoc.Random.makeSeed(randomOffset);
	    defCopy.randomNumber = makeRandomFunction(defCopy.randomSeed);
	} else {
	    // Seed for each slide instance of the plugin
	    defCopy.global = Sliobj.globalPluginDict[pluginName];
	    defCopy.slideId = slide_id;
	    defCopy.slideParams = slideParams || {};
	    var comps = parseSlideId(slide_id);
	    defCopy.randomSeed = Slidoc.Random.makeSeed(randomOffset + 256*((1+comps[1])*256 + comps[2]));
	    defCopy.randomNumber = makeRandomFunction(defCopy.randomSeed);
	    defCopy.pluginId = slide_id + '-plugin-' + pluginName;
	    defCopy.qattributes = getQuestionAttrs(slide_id);
	    defCopy.correctAnswer = null;
	    defCopy.questionAlternative = null;
	    if (defCopy.qattributes && defCopy.qattributes.qnumber) {
		if (Sliobj.session.questionShuffle)
		    defCopy.questionAlternative = Sliobj.session.questionShuffle[defCopy.qattributes.qnumber] ? Sliobj.session.questionShuffle[defCopy.qattributes.qnumber].charAt(0) : null;
		if (defCopy.qattributes.correct) {
		    // Correct answer: ans+/-err=plugin.response();;format
		    var comps = defCopy.qattributes.correct.split('=');
		    if (comps[0].trim()) {
			defCopy.correctAnswer = comps[0].trim();
		    } else {
			comps = defCopy.qattributes.correct.split(';;');
			if (comps.length > 1 && comps[1].trim())
			    defCopy.correctAnswer = comps[1].trim();
		    }
		}
	    }
	}
    }
    var pluginClass = object2Class(defCopy);
    var pluginInstance = new pluginClass();

    return pluginInstance;
}

//////////////////////////////////
// Section 12: Helper functions
//////////////////////////////////

var TRUNCATE_DIGEST = 12;
var TRUNCATE_HMAC = 12;
var DIGEST_ALGORITHM = 'sha256';  // 'md5' or 'sha256'

function urlsafe_b64encode(s) {
    return btoa(s).replace(/\+/g,'-').replace(/\//g,'_');
}

function urlsafe_b64decode(s) {
    return atob(s.replace(/-/g,'+').replace(/_/g,'/'));
}

Slidoc.genHmacToken = function (key, message) {
    // Generates token using HMAC key
    if (DIGEST_ALGORITHM == 'md5') {
	var hmac_bytes = md5(message, key, true);
    } else if (DIGEST_ALGORITHM == 'sha256') {
	var shaObj = new jsSHA("SHA-256", "TEXT");
	shaObj.setHMACKey(key, "TEXT");
	shaObj.update(message);
	hmac_bytes = shaObj.getHMAC("BYTES");
    } else {
	throw('Unknown digest algorithm: '+DIGEST_ALGORITHM);
    }
    return urlsafe_b64encode(hmac_bytes).slice(0,TRUNCATE_HMAC);
}

function genAuthPrefix(userId, role, sites) {
    return ':' + userId + ':' + (role||'') + ':' + (sites||'');
}

Slidoc.genAuthToken = function (key, userId, role, sites, prefixed) {
    var prefix = genAuthPrefix(userId, role, sites);
    var token = Slidoc.genHmacToken(key, prefix);
    return prefixed ? (prefix+':'+token) : token;
}

Slidoc.genLateToken = function (key, user_id, site_name, session_name, date_str) {
    // Use UTC date string of the form '1995-12-17T03:24' (append Z for UTC time)
    var date = new Date(date_str);
    if (date_str.slice(-1) != 'Z') {  // Convert local time to UTC
	date.setTime( date.getTime() + date.getTimezoneOffset()*60*1000 );
	date_str = date.toISOString().slice(0,16)+'Z';
    }
    return date_str+':'+Slidoc.genHmacToken(key, 'late:'+user_id+':'+site_name+':'+session_name+':'+date_str);
}

Slidoc.genFileKey = function (key, filename, prefix) {
    var salt = Math.round(Math.random() * 100000000);
    var match = key.match(/^([su]+-)(\d\d\d\d-\d\d-\d\d-)?/);
    if (match) {
	if (match[2])
	    salt = match[2] + salt;
	salt = match[1] + salt;
    }
    return encodeURIComponent(salt+':' + Slidoc.genHmacToken(key, salt+':'+filename) );
}

function clearAnswerElements() {
    Slidoc.log('clearAnswerElements:');
    var slides = document.getElementsByClassName('slidoc-slide');
    var suffixes = Object.keys(Sliobj.params.answer_elements);
    for (var k=0; k<slides.length; k++) {
	for (var j=0; j<suffixes.length; j++) {
	    var ansElem = document.getElementById(slides[k].id+suffixes[j]);
	    if (ansElem) {
		if (Sliobj.params.answer_elements[suffixes[j]]) {
		    ansElem.value = '';
		    ansElem.disabled = null;
		} else {
		    ansElem.innerHTML = '';
		}
	    }
	}
    }
    var hintElems = document.getElementsByClassName('slidoc-question-hint');
    for (var j=0; j<hintElems.length; j++)
	hintElems[j].classList.remove('slidoc-clickable-noclick');
}

function setAnswerElement(slide_id, suffix, textValue, htmlValue) {
    // Safely set value/content of answer element in slide_id with suffix
    if (!(suffix in Sliobj.params.answer_elements)) {
	Slidoc.log("setAnswerElement: ERROR Invalid suffix '"+suffix+"'");
	return false;
    }
    var ansElem = document.getElementById(slide_id+suffix);
    if (!ansElem) {
	Slidoc.log("setAnswerElement: ERROR Element '"+slide_id+suffix+"' not found!");
	return false;
    }
    if (Sliobj.params.answer_elements[suffix])
	ansElem.value = textValue || '';
    else if (htmlValue)
	ansElem.innerHTML = htmlValue;
    else
	ansElem.textContent = textValue;
}

function switchUser() {
    ///console.log('switchUser:', this.options.length, this.selectedIndex);
    var userId = this.options[this.selectedIndex].value;
    Sliobj.gradingUser = Sliobj.userGrades[userId].index;
    Slidoc.log('switchUser:', userId);
    //selectUser(GService.gprofile.auth, slidocReadyAux1);
    selectUser(GService.gprofile.auth);
}

Slidoc.switchToUser = function(userId) {
    if (!(userId in Sliobj.userGrades))
	return;
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    Sliobj.gradingUser = Sliobj.userGrades[userId].index;
    var option = document.getElementById('slidoc-switch-user-'+Sliobj.gradingUser);
    if (option)
	option.selected = true;
    selectUser(GService.gprofile.auth);
}

function selectUser(auth, callback) {
    var userId = Sliobj.userList[Sliobj.gradingUser-1];
    Slidoc.log('selectUser:', auth, userId);
    if (!auth.graderKey) {
	sessionAbort('Only grader can pick user');
    }
    GService.switchUser(auth, userId);

    if (callback) {
	callback(auth);  // Usually callback slidocReadyAux1
    } else {
	var gsheet = getSheet(Sliobj.sessionName);
	gsheet.getRow(userId, {}, selectUserCallback.bind(null, auth, userId));
    }
}

function selectUserCallback(auth, userId, result, retStatus) {
    Slidoc.log('selectUserCallback:', auth, userId, result, retStatus);
    if (!result) {
	sessionAbort('ERROR in selectUserCallback: '+ retStatus.error);
    }
    Slidoc.reportTestAction('selectUser');
    var unpacked = unpackSession(result);
    Sliobj.session = unpacked.session;
    if (Sliobj.session.displayName)
	auth.displayName = Sliobj.session.displayName;
    Sliobj.feedback = unpacked.feedback || null;
    Sliobj.userGrades[userId].gradeDisp = computeGrade(userId, true);
    Sliobj.score = null;
    scoreSession(Sliobj.session);
    Slidoc.showScore();
    Sliobj.userGrades[userId].weightedCorrect = Sliobj.scores.weightedCorrect;
    if (Sliobj.userGrades[userId].gradeDisp) {
	updateGradingStatus(userId);
    }
    prepGradeSession(Sliobj.session);
    initSessionPlugins(Sliobj.session);
    showSubmitted();
    dispUserInfo(userId, Sliobj.userGrades[userId].name);
    preAnswer();
}

function dispUserInfo(userId, dispName) {
    var infoElem = document.getElementById('slidoc-session-info');
    var footerElem = document.getElementById('slidoc-body-footer');
    if (Sliobj.assessmentView) {
	if (infoElem)
	    infoElem.textContent = (dispName || userId);
	if (footerElem)
	    footerElem.innerHTML = '<p></p><p></p><em>Seed: '+Sliobj.session.randomSeed+'</em>';

	var ncomps = dispName.split(',');
	var username = ncomps[0].trim();
	if (ncomps.length > 1)
	    username += '-'+ncomps[1].trim();
	username = username.replace(/ /g,'-').replace(/\./g,'').toLowerCase();
	document.title = (username || userId)+'-'+Sliobj.sessionName;
    } else {
	if (infoElem)
	    infoElem.textContent = '';
    }
}

Slidoc.nextUser = function (forward, first, needGradingOnly) {
    if (!Sliobj.gradingUser)
	return;
    if (first && nextUserAux(Sliobj.gradingUser, needGradingOnly))
	return;
    if (forward) {
	for (var j=Sliobj.gradingUser+1; j <= Sliobj.userList.length; j++) {
	    if (nextUserAux(j, needGradingOnly))
		return;
	}
    } else {
	for (var j=Sliobj.gradingUser-1; j >= 1; j--) {
	    if (nextUserAux(j, needGradingOnly))
		return;
	}
    }
}

function nextUserAux(gradingUser, needGradingOnly) {
    Slidoc.log('nextUserAux:', gradingUser, needGradingOnly);
    var option = document.getElementById('slidoc-switch-user-'+gradingUser);
    if (!option || (needGradingOnly && option.dataset.nograding))
	return false;
    option.selected = true;
    Sliobj.gradingUser = gradingUser;
    //selectUser(GService.gprofile.auth, slidocReadyAux1);
    selectUser(GService.gprofile.auth);
    return true;
}

Slidoc.linkTwitter = function () {
    if (!Sliobj.params.gd_sheet_url)
	return;
    var value = window.prompt('Twitter Name:');
    if (!value || !value.trim())
	return;
    var twitterName = value.trim();
    if (!Sliobj.closePopup)
	Slidoc.showPopup('Linking twitter name @'+twitterName+' ...');
    Slidoc.ajaxRequest('GET', Sliobj.sitePrefix + '/_user_twitterlink/'+twitterName, {json: 1}, linkTwitterCallback.bind(null, twitterName), true);
}

function linkTwitterCallback(twitterName, result, errMsg) {
    console.log('linkTwitterCallback', result, errMsg);
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    if (!result) {
	alert('Error in linking @'+twitterName+' :'+errMsg);
	return;
    }
    if (result.result != 'success') {
	alert('Error in linking @'+twitterName+' :'+result.error);
	return;
    }
    var value = window.prompt('You should have received a validation code via Direct Message for @'+twitterName+'. Please enter the code:');
    if (!value || !value.trim())
	return;
    Slidoc.ajaxRequest('GET', Sliobj.sitePrefix + '/_user_twitterverify/'+value, {json: 1}, linkVerifyCallback.bind(null, twitterName), true);
}

function linkVerifyCallback(twitterName, result, errMsg) {
    console.log('linkVerifyCallback', result, errMsg);
    if (!result) {
	alert('Error in verifying @'+twitterName+' :'+errMsg);
	return;
    }
    if (result.result != 'success') {
	alert('Error in verifying @'+twitterName+' :'+result.error);
	return;
    }
    if (result.message) {
	alert(result.message);
    } else {
	Slidoc.userProfile();
    }
}

Slidoc.showQDiff = function () {
    if (!Sliobj.params.gd_sheet_url)
	return;
    if (!Sliobj.closePopup)
	Slidoc.showPopup('Retrieving answer stats...');
    Slidoc.ajaxRequest('GET', Sliobj.sitePrefix + '/_user_qstats/'+Sliobj.sessionName, {json: 1}, showQDiffCallback, true);
}

function showQDiffCallback(result, errMsg) {
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    if (!result) {
	alert('Error in retrieving answer stats :'+errMsg);
	return;
    }
    if (result.result != 'success') {
	alert('Error in retrieving answer stats :'+result.error);
	return;
    }
    var firstSlideId = getVisibleSlides()[0].id;
    var attr_vals = getChapterAttrs(firstSlideId);
    var chapter_id = parseSlideId(firstSlideId)[0];
    var html = '<h2>Question correct response rate</h2><p></p>';
    html += '<table>\n';
    for (var j=0; j < result.qcorrect.length; j++) {
	var qno = result.qcorrect[j][1];
	var question_attrs = attr_vals[qno-1];
	var slide_id = chapter_id + '-' + zeroPad(question_attrs.slide, 2);
	var footer_elem = getSlideFooter(slide_id);
	var concept_elem = document.getElementById(slide_id+'-concepts');
	var header = 'slide';
	var tags = ''
	if (footer_elem)
	    header = footer_elem.textContent;
	if (concept_elem)
	    tags = ' [' + concept_elem.textContent.trim() + ']';
	html += '<tr><td>'+(result.qcorrect[j][0]*100).toFixed(0)+'%:</td><td><span class="slidoc-clickable" onClick="Slidoc.slideViewGo(true,'+question_attrs.slide+');">'+header+'</span></td><td>'+tags+'</td></tr>\n';
    }
    html += '</table>\n';
    Slidoc.showPopup(html, '', true);
}

Slidoc.showStats = function () {
    if (!Sliobj.params.gd_sheet_url)
	return;
    if (!Sliobj.closePopup)
	Slidoc.showPopup('Retrieving response stats...');
    Sliobj.statSheet.getRow('_average', {getheaders: 1}, showStatsCallback);
}

var TAG_RE = /^(p|s):(.*)$/;
function showStatsCallback(result, retStatus) {
    Slidoc.log('showStatsCallback:', result, retStatus);
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    if (!result) {
	alert('No stats found for session '+Sliobj.sessionName);
	return;
    }
    var headers = retStatus.info.headers;
    var tags = [[], []];
    var tallies = [[], []];
    for (var j=0; j<headers.length; j++) {
	var header = headers[j];
	var tmatch = TAG_RE.exec(header);
	if (!tmatch)
	    continue;
	if (tmatch[1] == 'p') {
	    tags[0].push(tmatch[2]);
	    tallies[0].push([result[header], 0]);
	} else {
	    tags[1].push(tmatch[2]);
	    tallies[1].push([result[header], 0]);
	}
    }
    var html = '<h3>Average response stats</h3><p></p>';
    html += 'Correct response: '+result['correct'].toFixed(2)+'<br>';
    html += 'Weighted score: '+result['weightedCorrect'].toFixed(2)+'<br>';
    html += 'Answered: '+result['count'].toFixed(2)+'<br>';
    html += 'Skipped: '+result['skipped'].toFixed(2)+'<br>';
    var labels = ['<hr><h3>Primary concepts missed</h3>', '<hr><h3>Secondary concepts missed</h3>'];
    for (var m=0; m<2; m++)
	html += labels[m]+conceptStats(tags[m], tallies[m])+'<p></p>';
    Slidoc.showPopup(html);
}

Slidoc.showGrades = function () {
    if (!Sliobj.params.gd_sheet_url) {
	window.location = Sliobj.sitePrefix + '/_user_grades';
	return;
    }
    if (!Sliobj.closePopup)
	Slidoc.showPopup('Looking up gradebook...');
    var userId = getUserId();
    Sliobj.gradeSheet.getRow(userId, {getstats: 1}, showGradesCallback.bind(null, userId));
}

var AGGREGATE_COL_RE = /\b(_\w+)_(avg|normavg|sum)(_(\d+))?$/i

function showGradesCallback(userId, result, retStatus) {
    Slidoc.log('showGradesCallback:', userId, result, retStatus);
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    if (!result) {
	if (retStatus.error && retStatus.error.match(/^Error:UNAVAILABLE:/))
	    alert('Gradebook temporarily not available');
	else
	    alert('No grades found for user '+userId);
	return;
    }
    var sessionKeys = [];
    var keys = Object.keys(result);
    for (var j=0; j<keys.length; j++) {
	if (keys[j].slice(0,1) == '_')
	    sessionKeys.push(keys[j]);
    }
    sessionKeys.sort( function(a,b){return cmp(a.replace(AGGREGATE_COL_RE,'$1'),b.replace(AGGREGATE_COL_RE,'$1'));});
    var html = '<b>Gradebook</b><br><em>User</em>: '+userId+' ('+(retStatus.info.lastUpdate||'').slice(0,10)+')<p></p>';
    var dClass = ' class="slidoc-disabled" ';
    if (result.total) {
	var disabled = (!retStatus.info.lastUpdate || !retStatus.info.gradebookRelease || retStatus.info.gradebookRelease.indexOf('cumulative_total') < 0);
	html += '<div '+(disabled?dClass:'')+'><em>Weighted total</em>: <b>'+result.total.toFixed(2)+'</b>';
	var totalIndex = retStatus.info.headers.indexOf('total');
	if (retStatus.info.maxScores && retStatus.info.maxScores[totalIndex])
	    html += ' out of '+retStatus.info.maxScores[totalIndex].toFixed(2);
	if (retStatus.info.averages && retStatus.info.averages[totalIndex])
	    html += ' (average='+retStatus.info.averages[totalIndex].toFixed(2)+')';
	if (retStatus.info.rescale && retStatus.info.rescale[totalIndex])
	    html += '&nbsp;&nbsp;&nbsp;Weighting= '+retStatus.info.rescale[totalIndex].replace(/\+/g,' + ');
	html += '</div>';

	if (result.grade) {
	    disabled = (!retStatus.info.lastUpdate || !retStatus.info.gradebookRelease || retStatus.info.gradebookRelease.indexOf('cumulative_grade') < 0);
	    html += '<p></p><div '+(disabled?dClass:'')+'><em>Potential grade</em>: '+result.grade+'<br>(This is a tentative grade estimate based on the performance so far; the final grade may be different, depending upon any additional credits/corrrections/curving)</div>';
	}
	html += '</div>';
    }
    var prefix = '';
    for (var j=0; j<sessionKeys.length; j++) {
	var sessionName = sessionKeys[j];
	var grade = result[sessionName];
	if (isNumber(grade))
	    grade = grade ? grade.toFixed(2) : 'missed';

	var dispSession = sessionName;
	var amatch = AGGREGATE_COL_RE.exec(sessionName);
	if (amatch) {
	    // Aggregate column
	    prefix = amatch[1];
	    dispSession = prefix+'_'+amatch[2];
	    html += '<p></p>';
	} else {
	    var pmatch = /(_\w*[a-z])(\d+)$/i.exec(sessionName);
	    if (pmatch && pmatch[1] == prefix) {
		// Same session family
		html += '&nbsp;&nbsp;&nbsp;';
	    } else {
		// New session family
		html += '<p></p>';
	    }
	}
	html += '<em>'+dispSession.slice(1) + '</em>: <b>'+ grade +'</b>'
	if (retStatus && retStatus.info && retStatus.info.headers) {
	    var sessionIndex = retStatus.info.headers.indexOf(sessionName);
	    if (retStatus.info.maxScores && retStatus.info.maxScores[sessionIndex])
		html += ' / '+retStatus.info.maxScores[sessionIndex].toFixed(2);
	    if (retStatus.info.rescale) {
		var rescaleDesc = retStatus.info.rescale[sessionIndex];
		if (rescaleDesc) {
		    if (rescaleDesc.match(/drop/i))
			html += ' ['+rescaleDesc+']';
		    else
			html += ' rescaled';
		}
	    }

	    if (retStatus.info.averages) {
		var temAvg = retStatus.info.averages[sessionIndex];
		if (isNumber(temAvg) && temAvg > 1)
		    html += ' (average='+temAvg.toFixed(2)+')';
	    }
	}
	html += '<br>';
    }
    Slidoc.showPopup(html);
}

function interactiveMessageDisplay(eventArgs) {
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    var html = 'Live messages: <p></p>\n';
    html += '<ul class="slidoc-direct-message-list">';
    for (var j=0; j<Sliobj.interactiveMessages.length; j++) {
	var msg = Sliobj.interactiveMessages[j];
	html += '<li><em>'+escapeHtml(msg['name'])+'</em> (<code>@'+escapeHtml(msg['sender'])+'</code>): '+escapeHtml(msg['text'])+'</li>';
    }
    html += '</ul>';
    Slidoc.showPopup(html, null, true, 0, 'InteractiveMessage', interactiveMessageDisplay);
}

Slidoc.userProfile = function() {
    if (!Sliobj.params.gd_sheet_url && !getServerCookie())
	return;
    var userId = getUserId(true);
    if (!userId || !Sliobj.rosterSheet) {
	if (Sliobj.closePopup)
	    Sliobj.closePopup();
	if (!userId) {
	    Slidoc.showPopup('<a href="/_oauth/login?next=' + encodeURIComponent(location.pathname)+'">Login</a>');
	} else {
	    var html = '<b>Profile</b><p></p>';
	    html += 'User: <b>'+userId+'</b><br>';
	    var userRole = getUserRole(true);
	    if (userRole) {
		html += 'Role: '+userRole;
		if (userRole != 'guest')
		    html += ' (<a class="slidoc-clickable"  href="'+Sliobj.sitePrefix+'/_user_plain">Revert to plain/guest user</a>)';
		html += '<br>\n';
	    }
	    html += '(<span class="slidoc-clickable" onclick="Slidoc.userLogout();">Logout</span>)<hr>';
	    Slidoc.showPopup(html);
	}
	return;
    }
    if (!Sliobj.closePopup)
	Slidoc.showPopup('Looking up user info...');
    Sliobj.rosterSheet.getRow(userId, {}, userProfileCallback.bind(null, userId));
}

function userProfileCallback(userId, result, retStatus) {
    Slidoc.log('userProfileCallback:', userId, result, retStatus);
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    var html = '<b>Profile</b><p></p>';
    html += 'User: <b>'+userId+'</b>';
    html += '&nbsp;&nbsp;&nbsp;(<span class="slidoc-clickable" onclick="Slidoc.userLogout();">Logout</span>)<hr>';
    if (result) {
	html += 'Name: '+escapeHtml(result.name)+'<br>\n';
	html += 'Email: '+escapeHtml(result.email)+'<br>\n';
	html += 'Twitter: '+escapeHtml(result.twitter)+' (<span class="slidoc-clickable" onclick="Slidoc.linkTwitter();">Modify</span>)<br>\n';
    } else {
	if (Sliobj.session.displayName)
	    html += 'Name: '+escapeHtml(Sliobj.session.displayName);
	if (Sliobj.session.email)
	    html += ' ('+escapeHtml(Sliobj.session.email)+')';
	html += '<br>\n';
    }
    var userRole = getUserRole(true);
    if (userRole)
	html += 'Role: '+userRole+' (<a class="slidoc-clickable"  href="'+Sliobj.sitePrefix+'/_user_plain">Revert to plain/guest user</a>)<br>\n';

    Slidoc.showPopup(html);
}

Slidoc.manageSession = function() {
    var html = '<b>Settings</b><p></p>';
    var hr = '<tr><td colspan="3"><hr></td></tr>';
    var userId = getUserId();
    var userRole = getUserRole();
    if (userRole)
	html += 'Role: <b>'+userRole+'</b><br>';
    var versionStr = Slidoc.version;
    if (Sliobj.remoteVersion)
	versionStr += ' (remote: '+Sliobj.remoteVersion+')';
    if (Sliobj.sessionName) {
	if (Sliobj.session && Sliobj.session.team)
	    html += 'Team: ' + Sliobj.session.team + '<br>';
	html += '<p></p>Module session: <b>' + Sliobj.sessionName + '</b>';
	if (Sliobj.session && Sliobj.session.revision)
	    html += ', ' + Sliobj.session.revision;
	if (Sliobj.params.questionsMax)
	    html += ' (' + Sliobj.params.questionsMax + ' questions)';
	if (Sliobj.params.gd_sheet_url && Sliobj.session)
	    html += Sliobj.session.submitted ? '<br>Submitted '+parseDate(Sliobj.session.submitted) : '<br>NOT SUBMITTED';
	html += '<br>';
	if (Sliobj.dueDate)
	    html += 'Due: <em>'+Sliobj.dueDate+'</em><br>';
	if (Sliobj.session && Sliobj.params.maxRetakes)
	    html += 'Retakes remaining: <code>'+retakesRemaining()+'</code><br>';
	if (Sliobj.voteDate)
	    html += 'Submit Likes by: <em>'+Sliobj.voteDate+'</em><br>';

    } else {
	if (Slidoc.serverCookie)
	    html += 'User: <b>'+(userId || Slidoc.serverCookie.user)+'</b> (<a class="slidoc-clickable" href="'+Slidoc.logoutURL+'">logout</a>)<br>';
    }

    if (!Sliobj.chainActive && Sliobj.params.paceLevel && !Sliobj.params.timedSec && (!Sliobj.params.gd_sheet_url || retakesRemaining() || Sliobj.fullAccess))
	html += '<br><span class="slidoc-clickable" onclick="Slidoc.resetPaced();">'+'Reset paced session entry'+(retakesRemaining()?' for re-takes':'')+'</span><br>';

    if (!Sliobj.chainActive && Sliobj.params.paceLevel && (!Sliobj.params.gd_sheet_url || Sliobj.fullAccess))
	html += '<br><span class="slidoc-clickable" onclick="Slidoc.resetPaced(true);">Delete paced session entry</span><br>';

    if (Sliobj.fullAccess) {
        html += '<p></p><hr>';
	if (Sliobj.params.hiddenSlides && Sliobj.params.hiddenSlides.length) {
	    html += '<span class="slidoc-clickable" onclick="Slidoc.hideSlides();">'+(Sliobj.showHiddenSlides?'Hide':'Show')+' hidden slides</span><br>';
	}
	if (Sliobj.params.releaseDate) {
	    var dateVal = parseDate(Sliobj.params.releaseDate);
	    if (dateVal)
		html += 'Release date: '+dateVal.toLocaleString()+'<br>';
	    else
		html += 'Release date: '+Sliobj.params.releaseDate+'<br>';
	}
	html += '<a class="slidoc-clickable" href="'+Sliobj.sitePrefix+'/_manage/'+Sliobj.sessionName+'" target="_blank">Manage module session</a>';
	html += '<p></p><a class="slidoc-clickable" target="_blank" href="https://mitotic.github.io/wheel/?session='+Sliobj.params.siteName+'">QWheel</a>';
        html += '<hr>';
    }
    if (Sliobj.fullAccess || (Slidoc.serverCookie && Slidoc.serverCookie.siteRole == Sliobj.params.adminRole)) {
	html += '<p></p><a class="slidoc-clickable" target="_blank" href="'+Sliobj.sitePrefix+'/_dash">Site dashboard</a><br>';
    }

    if (Sliobj.gradableState || !Sliobj.params.gd_sheet_url) {
	html += hr;
	html += '<span class="slidoc-clickable" onclick="Slidoc.toggleAssessment();">'+(Sliobj.assessmentView?'End':'Begin')+' print view</span><br>';
    }

    if (Sliobj.gradableState) {
	html += hr;
	html += 'Session admin:<br><blockquote>\n';
	if (!Sliobj.gradeDateStr)
	    html += '<span class="slidoc-clickable" onclick="Slidoc.releaseGrades();">Release grades to students</span><br>';
	else
	    html += 'Grades released to students on '+Sliobj.gradeDateStr+'<br>';
	html += hr;

	var disabled = !(Sliobj.sheetsAvailable && Sliobj.sheetsAvailable.indexOf('stats') >= 0);
	html += clickableSpan('View response statistics', "Slidoc.showStats();", disabled) + '<br>\n';

	var disabled = !(Sliobj.sheetsAvailable && Sliobj.sheetsAvailable.indexOf('answers') >= 0);
	html += clickableSpan('View question difficulty', "Slidoc.showQDiff();", disabled) + '<br>\n';

	if (Sliobj.fullAccess) {
	    html += hr;
	    var create = !(Sliobj.sheetsAvailable && Sliobj.sheetsAvailable.indexOf('answers') >= 0 && Sliobj.sheetsAvailable.indexOf('stats') >= 0);
	    html += clickableSpan((create?'Create':'Update')+' session answers/stats', "Slidoc.sessionActions('answer_stats');") + '<br>\n';

	    html += 'View session: <span class="slidoc-clickable" onclick="Slidoc.viewSheet('+"'"+Sliobj.sessionName+"_correct'"+');">correct</span> <span class="slidoc-clickable" onclick="Slidoc.viewSheet('+"'"+Sliobj.sessionName+"_answers'"+');">answers</span> <span class="slidoc-clickable" onclick="Slidoc.viewSheet('+"'"+Sliobj.sessionName+"_stats'"+');">stats</span><br>';
	    html += hr;
	    html += '<span class="slidoc-clickable" onclick="Slidoc.sessionActions('+"'gradebook'"+');">Post scores from this session to gradebook</span><br>';
	    html += '<span class="slidoc-clickable" onclick="Slidoc.sessionActions('+"'gradebook', 'all'"+');">Post scores from all sessions to gradebook</span>';
	}
	html += '</blockquote>\n';
    }
    html += '<p></p>Version: ' + versionStr;
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    Slidoc.showPopup(html);
}

Slidoc.sessionActions = function(actions, sessionName, noconfirm) {
    Slidoc.log('Slidoc.sessionActions: ', actions, sessionName);
    if (sessionName == 'all')
	var sheetName = '';
    else
	var sheetName = sessionName || Sliobj.sessionName;
    if (!noconfirm && !window.confirm("Confirm actions '"+actions+"' for session "+(sheetName||'ALL')+'? (may take some time)'))
	return;
    var opts = {sheet: sheetName}
    Sliobj.indexSheet.actions(actions, opts, sheetActionsCallback.bind(null, actions, sheetName));
}

function sheetActionsCallback(actions, sheetName, result, retStatus) {
    Slidoc.log('sheetActionsCallback:', actions, sheetName, result, retStatus);
    var msg = 'actions '+actions+' for sheet '+sheetName;
    if (!result) {
	alert('Error in '+msg+': '+retStatus.error);
	return;
    } else if (actions == 'gradebook') {
	var html = 'Gradebook updated for session '+sheetName+'.<p></p><a href="'+Sliobj.sitePrefix+'/_sheet/grades_slidoc">Download</a> and and print a copy for the records';
	Slidoc.showPopup(html);
    } else {
	alert('Completed '+msg);
    }
}

Slidoc.viewSheet = function(sheetName) {
    Slidoc.log('Slidoc.viewSheet: ', sheetName);
    window.open(Sliobj.sitePrefix+'/_sheet/'+sheetName);
}


//////////////////////////////////////////////////////
// Section 13: Retrieve data needed for session setup
//////////////////////////////////////////////////////

Slidoc.slidocReady = function (auth) {
    Slidoc.log('slidocReady:', auth);
    Sliobj.gradableState = auth && !!auth.graderKey;
    Sliobj.fullAccess = auth && auth.authRole == Sliobj.params.adminUserId;

    Sliobj.adminPaced = 0;      // Set adminPaced for testuser only upon submission
    Sliobj.maxLastSlide = 0;
    Sliobj.userList = null;
    Sliobj.userGrades = null;
    Sliobj.gradingUser = 0;
    Sliobj.indexSheet = null;
    Sliobj.rosterSheet = null;
    Sliobj.gradeSheet = null;
    Sliobj.statSheet = null;
    Sliobj.discussSheet = null;
    Sliobj.dueDate = null;
    Sliobj.gradeDateStr = '';
    Sliobj.remoteAnswers = '';
    Sliobj.userFileKey = '';
    Sliobj.teamFileKey = '';
    Sliobj.sessionFileKey = '';
    Sliobj.discussStats = null;
    Sliobj.sheetsAvailable = null;
    Sliobj.voteDate = null;

    if (Sliobj.params.gd_sheet_url) {
	Sliobj.rosterSheet = new GService.GoogleSheet(Sliobj.params.gd_sheet_url, Sliobj.params.roster_sheet,
						     [], [], useJSONP);
	Sliobj.gradeSheet = new GService.GoogleSheet(Sliobj.params.gd_sheet_url, Sliobj.params.grades_sheet,
						     [], [], useJSONP);
	Sliobj.statSheet = new GService.GoogleSheet(Sliobj.params.gd_sheet_url, Sliobj.params.fileName+'_stats',
						     [], [], useJSONP);
	if (Sliobj.params.discussSlides && Sliobj.params.discussSlides.length) {
	    Sliobj.discussSheet = new GService.GoogleSheet(Sliobj.params.gd_sheet_url, Sliobj.params.fileName+'_discuss',
							   [], [], useJSONP);
	}
    }
    if (Sliobj.gradableState) {
	Sliobj.indexSheet = new GService.GoogleSheet(Sliobj.params.gd_sheet_url, Sliobj.params.index_sheet,
						     Sliobj.params.indexFields.slice(0,2),
						     Sliobj.params.indexFields.slice(2), useJSONP);
	Sliobj.indexSheet.getRow(Sliobj.sessionName, {}, function (result, retStatus) {
	    if (result && result.gradeDate)
		Sliobj.gradeDateStr = result.gradeDate;
	});
    }

    if (Sliobj.params.remoteLogLevel && Sliobj.params.gd_sheet_url && !Sliobj.gradableState) {
	Sliobj.logSheet = new GService.GoogleSheet(Sliobj.params.gd_sheet_url, Sliobj.params.log_sheet,
						     Sliobj.params.logFields.slice(0,2),
						     Sliobj.params.logFields.slice(2), useJSONP);
    }

    if (CACHE_GRADING && Sliobj.gradableState && Sliobj.sessionName) {
	toggleClass(true, 'slidoc-gradable-view');
	setupCache(auth, slidocReadyAux1);
    } else {
	slidocReadyAux1(auth);
    }
}
	

function slidocReadyAux1(auth) {
    Slidoc.log("slidocReadyAux1:", auth);
    return abortOnError(slidocReadyAux2.bind(null, auth));
}

function slidocReadyAux2(auth) {
    Slidoc.log("slidocReadyAux2:", auth);

    if (Sliobj.params.gd_sheet_url && (!auth || !auth.id))
	throw('slidocReadyAux2: Missing/null auth');

    if (Sliobj.closePopup)
	Sliobj.closePopup();
    Sliobj.closePopup = null;
    Sliobj.popupEvent = '';
    Sliobj.popupQueue = [];
    Slidoc.delayIndicator = ('progress_bar' in Sliobj.params.features) ? progressBar : delayElement;

    Sliobj.ChainQuery = '';
    Sliobj.chainActive = null;
    Sliobj.showAll = false;
    Sliobj.curChapterId = '';
    Sliobj.currentSlide = 0;
    Sliobj.questionSlide = null;
    Sliobj.lastInputValue = null;
    Sliobj.maxIncrement = 0;
    Sliobj.curIncrement = 0;
    Sliobj.allQuestionConcepts = [];
    Sliobj.sidebar = false;
    Sliobj.prevSidebar = false;

    Sliobj.session = null;
    Sliobj.feedback = null;
    Sliobj.delayScoring = false;
    Sliobj.hideUnviewedSlides = false;

    Slidoc.Random = LCRandom;
    sessionManage();

    Slidoc.log("slidocReadyAux2:B", Sliobj.sessionName, Sliobj.params.paceLevel);
    if (Sliobj.sessionName) {
	// Paced named session
	if (Sliobj.params.gd_sheet_url && !auth) {
	    sessionAbort('Session aborted. Google Docs authentication error.');
	}

	if (Sliobj.gradableState) {
	    // Retrieve session, possibly from cache (without creating)
	    sessionGet(null, Sliobj.sessionName, {retry: 'ready'}, slidocSetup);
	} else if (Sliobj.params.sessionPrereqs) {
	    // Retrieve prerequisite session(s)
	    var prereqs = Sliobj.params.sessionPrereqs.split(',');
	    sessionGet(null, prereqs[0], {}, slidocReadyPaced.bind(null, prereqs));
	} else {
	    slidocReadyPaced()
	}
    
    } else {
	slidocSetup(createSession());
    }
}

function slidocReadyPaced(prereqs, prevSession, prevFeedback) {
    Slidoc.log('slidocReadyPaced:', prereqs, prevSession, prevFeedback);
    if (prereqs) {
	if (!prevSession) {
	    sessionAbort("Prerequisites: "+prereqs.join(',')+". Error: session '"+prereqs[0]+"' not attempted!");
	}
	if (!prevSession.submitted) {
	    sessionAbort("Prerequisites: "+prereqs.join(',')+". Error: session '"+prereqs[0]+"' not completed!");
	}
	if (prereqs.length > 1) {
	    prereqs = prereqs.slice(1);
	    sessionGet(null, prereqs[0], {}, slidocReadyPaced.bind(null, prereqs));
	    return;
	}
    }

    if (Sliobj.params.timedSec) {

	function slidocTimedGetCallback(temSession, temFeedback) {
	    Slidoc.log('slidocTimedGetCallback:', temSession, temFeedback);

	    if (Sliobj.timedSecLeft && !temSession) {
		
		if (!window.confirm('NOTE: This session is timed. You have '+Sliobj.timedSecLeft+' seconds to complete all answers from the time you start. If you are not ready to start the session, you may cancel now and start later.')) {
		window.location = Sliobj.sitePrefix;
		return;
		}
	    }
	    sessionGet(null, Sliobj.sessionName, {create: true, retry: 'ready'}, slidocSetup);
	}

	sessionGet(null, Sliobj.sessionName, {}, slidocTimedGetCallback);

    } else {
	sessionGet(null, Sliobj.sessionName, {create: true, retry: 'ready'}, slidocSetup);
    }
}

///////////////////////////////
// Section 14: Session setup
///////////////////////////////

function setupOverride(msg, force) {
    if (getUserId() != Sliobj.params.testUserId)
	return false;

    if (Sliobj.testOverride == null && msg)
	Sliobj.testOverride = force || !!window.confirm(msg);
    return Sliobj.testOverride;
}

function getUserId(useCookie) {
    if (window.GService && GService.gprofile && GService.gprofile.auth)
	return GService.gprofile.auth.id;
    else if (location.hostname == 'localhost' && getParameter('reloadcheck'))
	return Sliobj.params.testUserId;
    else if (useCookie && Slidoc.serverCookie && Slidoc.serverCookie.user)
	return Slidoc.serverCookie.user;

    return '';
}

function controlledPace() {
    // If test user has submitted, assume controlledPace
    if (Sliobj.params.paceLevel < ADMIN_PACE)
	return false;
    return getUserId() != Sliobj.params.testUserId || (Sliobj.session && Sliobj.session.submitted);
}

function isController() {
    return Sliobj.params.paceLevel >= ADMIN_PACE && !Sliobj.gradableState && getUserId() == Sliobj.params.testUserId;
}

function gradingAccess() {
    if (!Slidoc.serverCookie)
	return false;
    return Slidoc.serverCookie.siteRole == Sliobj.params.adminRole || Slidoc.serverCookie.siteRole == Sliobj.params.graderRole;
}

function collapsibleAccess() {
    if (getUserId() == Sliobj.params.testUserId)
	return true;
    if ('slides_only' in Sliobj.params.features)
	return false;
    return !Sliobj.params.paceLevel || (Sliobj.session && Sliobj.session.submitted);
}

function allowDelay() {
    return Sliobj.params.paceLevel < ADMIN_PACE || Sliobj.dueDate;
}

function slidocSetup(session, feedback) {
    return abortOnError(slidocSetupAux.bind(null, session, feedback));
}

function slidocSetupAux(session, feedback) {
    Slidoc.log('slidocSetupAux:', session, feedback);
    Sliobj.session = session;
    Sliobj.feedback = feedback || null;
    var unhideChapters = false;

    if (Sliobj.params.showScore && Sliobj.params.showScore != 'after_answering')
	Sliobj.delayScoring = true;

    // Hide unviewed slides for all question-paced sessions, and for non-printable sessions with immediate scoring (in non-preview mode)
    if (!Sliobj.previewState && Sliobj.session && Sliobj.session.paced) {
	if (Sliobj.session.paced >= QUESTION_PACE || (!Sliobj.params.printable && !Sliobj.delayScoring) )
	    Sliobj.hideUnviewedSlides = true;
    }

    if (Sliobj.gradableState && !Sliobj.session) {
	sessionAbort('Admin user: session not found for user');
	return;
    }

    if (Sliobj.session.version != Sliobj.params.sessionVersion) {
	alert('Slidoc: session version mismatch; discarding previous session with version '+Sliobj.session.version);
	Sliobj.session = null;

    } else if (Sliobj.session.revision != Sliobj.params.sessionRevision) {
	alert('Slidoc: Revised session '+Sliobj.params.sessionRevision+' (discarded previous revision '+Sliobj.session.revision+')');
	Sliobj.session = null;

    } else if (!Sliobj.params.paceLevel && Sliobj.session && Sliobj.session.paced) {
	// Pacing cancelled for previously paced session
	Sliobj.session.paced = 0;

    } else if (Sliobj.params.paceLevel && !Sliobj.session.paced) {
	// Pacing completed; no need to hide chapters
	unhideChapters = true;
    }

    if (Sliobj.gradableState) {
	if (!Sliobj.session) {
	    sessionAbort('Admin user: cannot administer null session');
	}
	prepGradeSession(Sliobj.session);
	if (Sliobj.params.paceLevel)
	    unhideChapters = true;
    }    

    var slides = getVisibleSlides();
    if (controlledPace()) {
	// Unhide only admin-paced slides
	for (var j=0; j<visibleSlideCount(); j++)
	    slidesVisible(true, j+1, slides);
    } else if (!Sliobj.batchMode && !Sliobj.assessmentView && Sliobj.hideUnviewedSlides) {
	// Unhide only paced slides
	for (var j=0; j<Sliobj.session.lastSlide; j++)
	    slidesVisible(true, j+1, slides);
    } else {
	// Not paced or admin-paced, or batch/assessment view; unhide all slides
	slidesVisible(true);
    }

    if (!Sliobj.session) {
	// New paced session
	Sliobj.session = createSession();
	Sliobj.feedback = null;
	sessionPut(null, null, {retry: 'new'});
    }

    var sessionElem = document.getElementById("slidoc-session-display");
    if (sessionElem) {
	if (Sliobj.params.fileName && Sliobj.params.fileName != 'index') {
	    if (Sliobj.params.tocFile) {
		var prefix = Sliobj.params.fileName;
		var suffix = '';
		var nmatch = Sliobj.params.fileName.match(/(\d+)$/);
		if (nmatch) {
		    suffix = nmatch[1];
		    prefix = prefix.slice(0,-suffix.length);
		}
		var target = Sliobj.session.submitted ? '' : ' target="_blank"';
		sessionElem.innerHTML = '<a href="'+Sliobj.params.tocFile+'" '+target+'>'+prefix+'</a>'+suffix;
	    } else {
		sessionElem.textContent = Sliobj.params.fileName;
	    }
	} else {
	    sessionElem.textContent = '';
	}
	if (Sliobj.previewState)  // Make element non-clickable during preview
	    sessionElem.textContent = sessionElem.textContent;
    }

    // DOM set-up and clean-up
    Slidoc.breakChain();

    // Remove all global views
    var bodyClasses = document.body.classList;
    for (var j=0; j<bodyClasses.length; j++) {
	if (!bodyClasses[j].match(/-page$/))
	    document.body.classList.remove(bodyClasses[j]);
    }

    Sliobj.showHiddenSlides = false;
    
    // Mark explicitly hidden slides
    var allSlides = getVisibleSlides(true);
    for (var j=0; j<allSlides.length; j++) {
	var footerElem = getSlideFooter(allSlides[j].id);
	if (footerElem.classList.contains('slidoc-slide-hidden'))
	    allSlides[j].classList.add('slidoc-slide-hidden');
    }

    if (Sliobj.session && !Sliobj.session.submitted && Sliobj.params.timedSec && Sliobj.timedSecLeft) {
	timedInit(Sliobj.timedSecLeft);
    }

    // Make slide text unselectable, if slides_only
    if (!Sliobj.gradableState && ('slides_only' in Sliobj.params.features) && getUserId() != Sliobj.params.testUserId)
	document.body.classList.add('slidoc-unselectable');
    
    var chapters = document.getElementsByClassName('slidoc-reg-chapter');
    for (var j=0; j<chapters.length; j++) {
	if (unhideChapters) {
	    chapters[j].style.display =  null;
	} else if (!Sliobj.firstTime) {
	    // Hide all regular chapters at the beginning
	    chapters[j].style.display = 'none';
	}

	var chapter_id = chapters[j].id;
	var attr_vals = getChapterAttrs(chapter_id);
	for (var qnumber=1; qnumber <= attr_vals.length; qnumber++) {
	    // For each question slide
	    var question_attrs = attr_vals[qnumber-1];
	    var slide_id = chapter_id + '-' + zeroPad(question_attrs.slide, 2);
	    var slideElem = document.getElementById(slide_id);

	    if (question_attrs.share) {
		toggleClassAll(!Slidoc.PluginManager.shareReady(question_attrs.share, qnumber), 'slidoc-shareable-hide', slide_id+'-plugin-Share-sharebutton');
	    }

	    if (!Sliobj.firstTime) {
		// Clean-up slide-specific view styles for question slides
		slideElem.classList.remove('slidoc-answered-slideview');
		slideElem.classList.remove('slidoc-grading-slideview');
		slideElem.classList.remove('slidoc-forward-link-allowed');
		var answer_elements = Sliobj.params.answer_elements;
		var keys = Object.keys(answer_elements);
		for (var m=0; m<keys.length; m++) {
		    // Clean up answer elements
		    var ansElem = document.getElementById(slide_id+keys[m]);
		    if (ansElem) {
			if (answer_elements[keys[m]])
			    ansElem.value = '';         // input/textarea
			else
			    ansElem.textContent = '';   // span/div/pre element
		    }
		}
	    }
	}
    }

    // New/restored ression
    Slidoc.reportTestAction('initSession');

    scoreSession(Sliobj.session);
    initSessionPlugins(Sliobj.session);

    if ('assessment' in Sliobj.params.features) {
	var assessElem = document.getElementById('slidoc-assessment-display');
	if (assessElem)
	    assessElem.style.display = null;
    }

    if (Sliobj.assessmentView)
	toggleClass(true, 'slidoc-assessment-view');

    if (Sliobj.lockedView)
	toggleClass(true, 'slidoc-locked-view');

    if (Sliobj.reloadCheck)
	toggleClass(true, 'slidoc-localpreview-view');

    if (Sliobj.updateView)
	toggleClass(true, 'slidoc-update-view');

    if (Sliobj.params.resubmitAnswers)
	toggleClass(true, 'slidoc-resubmit-view');

    if (Sliobj.params.discussSlides && Sliobj.params.discussSlides.length && Sliobj.params.paceLevel >= ADMIN_PACE && Sliobj.session && Sliobj.session.submitted) {
	toggleClass(true, 'slidoc-discuss-view');
	displayDiscussStats();
    }

    if (collapsibleAccess())
	toggleClass(true, 'slidoc-collapsible-view');

    if (Sliobj.previewState)
    	toggleClass(true, 'slidoc-preview-view');

    if (Sliobj.gradableState)
    	toggleClass(true, 'slidoc-gradable-view');

    if (getUserId() == Sliobj.params.testUserId || (Slidoc.serverCookie && Slidoc.serverCookie.siteRole == Sliobj.params.adminRole && (Sliobj.gradableState || !Sliobj.sessionName)) )
	toggleClass(true, 'slidoc-testuser-view');

    if (isController())
    	toggleClass(true, 'slidoc-controller-view');

    if (location.protocol == 'http:' || location.protocol == 'https:')
    	toggleClass(true, 'slidoc-server-view');

    if (Slidoc.serverCookie)
    	toggleClass(true, 'slidoc-proxy-view');

    if (Sliobj.params.gd_sheet_url || getServerCookie())
	toggleClass(true, 'slidoc-remote-view');

    if (Sliobj.scores.questionsCount)
	Slidoc.showScore();

    if (Sliobj.session.submitted || Sliobj.gradableState) // Suppress incremental display
	toggleClass(true, 'slidoc-completed-view');
    
    if (Sliobj.feedback) // If any non-null feedback, activate graded view
	toggleClass(true, 'slidoc-graded-view');

    if (document.getElementById("slidoc-topnav")) {
	//if (document.getElementById("slidoc-slideview-button"))
	//    document.getElementById("slidoc-slideview-button").style.display = 'none';
    }

    showSubmitted();
    setTimeout(showPendingCalls, 2000);

    if (Sliobj.assessmentView && !Sliobj.gradableState) {
	dispUserInfo(getUserId(), Sliobj.session.displayName);
    }

    // Setup completed; branch out
    Sliobj.firstTime = false;
    var toc_elem = document.getElementById("slidoc00");
    if (!toc_elem && Sliobj.session) {
	if (Sliobj.session.paced || Sliobj.session.submitted) {
	    var firstSlideId = getVisibleSlides()[0].id;
	    Sliobj.allQuestionConcepts = parseElem(firstSlideId+'-qconcepts') || [];
	}
	if (Sliobj.session.paced) {
	    Slidoc.startPaced(); // This will call preAnswer later
	    return false;
	}
	preAnswer();
	if (Sliobj.gradableState && Slidoc.testingActive())
	    Slidoc.slideViewStart();
    } else {
	clearAnswerElements();
    }

    // Not paced
    Slidoc.chainUpdate(location.search);
    if (toc_elem) {
	// Table of contents included in file
	var slideHash = (!(Sliobj.session && Sliobj.session.paced) && location.hash) ? location.hash : "#slidoc00";
	if (parseSlideId(slideHash)[0])
	    goSlide(slideHash, false, true);
	if (slideHash.match(/^#slidoc-index-concept/)) {
	    // Directly jump to index element
	    var elem = document.getElementById(slideHash.slice(1));
	    if (elem) {
		elem = elem.firstChild;
		while (elem && elem.tagName != 'A') { elem = elem.nextSibling; }
	    }
	    if (elem && elem.tagName == 'A') {
		if (elem.onclick)
		    setTimeout(function(){ elem.onclick();}, 200);
		else if (elem.href)
		    window.location = elem.href;
	    } else {
		setTimeout(function(){location.hash = slideHash;}, 200);
	    }
	}

	if (chapters && chapters.length == 1 && document.getElementById("slidoc01") && window.matchMedia("screen and (min-width: 800px) and (min-device-width: 960px)").matches) {
	    // Display contents for single chapter with sidebar
	    Slidoc.sidebarDisplay();
	    var toggleElem = document.getElementById("slidoc-toc-chapters-toggle");
	    if (toggleElem && toggleElem.onclick)
		toggleElem.onclick();
	}
    }

    if (location.hash && (Sliobj.updateView || Sliobj.previewState) && (!getUserId() || getUserId() == Sliobj.params.testUserId)) {
	if (location.hash.slice(0,2) == '#-')
	    restoreScroll();
	else if (location.hash.slice(1).match(SLIDE_ID_RE))
	    Slidoc.slideViewStart();
    } else if ('slides_only' in Sliobj.params.features && !Sliobj.assessmentView && !Sliobj.gradableState) {
	Slidoc.slideViewStart();
    }

    ///if (Slidoc.testingActive())
	///Slidoc.slideViewStart();
}

function prepGradeSession(session) {
    // Modify session for grading
    session.paced = 0; // Unpace session, but this update will not be saved to Google Docs
    session.submitted = session.submitted || 'GRADING'; // 'Complete' session, but these updates will not be saved to Google Docs
    session.lastSlide = Sliobj.params.pacedSlides;
}

function getSlideParams(slide_id) {
    var slideParams = {};
    var footer_elem = getSlideFooter(slide_id);
    if (footer_elem && footer_elem.dataset.paramCount && Sliobj.slideParamValues.length) {
	slideParams = copyObj(Sliobj.slideParamValues[footer_elem.dataset.paramCount-1] || {});
    }
    slideParams.$ = Sliobj.slidePluginDict[slide_id]; // Plugins instantiated thus far for slide
    slideParams.$$ = Sliobj.globalPluginDict;         // All global plugin instances
    slideParams.Slidoc = Slidoc;
    slideParams.SlidePlugins = slideParams.$;         // Backward compatibility
    return slideParams;
}

function evalExpr(params, expr) {
    ///Slidoc.log('evalExpr:', params, expr);
    var names = Object.keys(params);
    names.sort();
    var paramVals = [];
    var paramNames = names.join(',');
    for (var j=0; j<names.length; j++)
	paramVals.push(params[names[j]]);

    try {
	var func = new Function(paramNames, 'return '+expr);
    } catch(err) {
	return 'ERROR in expression syntax';
    }
    try {
	return func.apply(null, paramVals);
    } catch (err) {
	return 'ERROR in expression evaluation';
    }
}

function initSessionPlugins(session) {
    // Restore random seed for session
    Slidoc.log('initSessionPlugins:');
    Sliobj.globalPluginDict = {};
    Sliobj.globalPluginList = [];
    Sliobj.slidePluginDict = {};
    Sliobj.slidePluginList = {};
    Sliobj.answerPlugins = {};
    Sliobj.incrementPlugins = {};
    Sliobj.buttonPlugins = {};

    Sliobj.slideParamValues = [];
    if (session.paramValues) {
	var paramsObj = {};
	for (var j=0; j<session.paramValues.length; j++) {
	    var keys = Object.keys(session.paramValues[j]);
	    for (var k=0; k<keys.length; k++)
		paramsObj[keys[k]] = session.paramValues[j][keys[k]];
	    Sliobj.slideParamValues.push( copyObj(paramsObj) );
	}
    }

    Slidoc.Plugins = {};
    Sliobj.globalPluginDict = {};
    Sliobj.globalPluginList = [];
    for (var j=0; j<Sliobj.pluginNames.length; j++) {
	var pluginName = Sliobj.pluginNames[j];
	var pluginInstance = createPluginInstance(pluginName);
	Sliobj.globalPluginDict[pluginName] = pluginInstance;
	Sliobj.globalPluginList.push(pluginInstance);
	if (!(pluginName in Slidoc.Plugins))
	    Slidoc.Plugins[pluginName] = {};
	Slidoc.Plugins[pluginName][''] = pluginInstance;   // '' denotes global instance
	Slidoc.PluginManager.optCall.apply(null, [pluginInstance, 'initGlobal']);
    }

    var allContent = document.getElementsByClassName('slidoc-plugin-content');
    var contentElems = [];
    for (var j=0; j<allContent.length; j++)
	contentElems.push(allContent[j]);

    // Sort plugins in order of occurrence in Markdown text
    // Need to call init method in sequence to preserve global random number generation order
    contentElems.sort( function(a,b){return cmp(a.dataset.number, b.dataset.number);} );

    var slideData = null;
    for (var j=0; j<contentElems.length; j++) {
	var contentElem = contentElems[j];
	var pluginName = contentElem.dataset.plugin;
	var comps = pluginName.split('-');
	var pluginDefName = comps[0];
	var instanceNum = (comps.length > 1) ? (parseNumber(comps[1]) || 0): 0;
	var slide_id = contentElem.dataset.slideId;
	if (!(slide_id in Sliobj.slidePluginList)) {
	    Sliobj.slidePluginDict[slide_id] = {};
	    Sliobj.slidePluginList[slide_id] = [];
	    slideData = {};  // New object to share persistent data for slide
	}

	var slideParams = getSlideParams(slide_id);
	var pluginInstance = createPluginInstance(pluginName, false, slide_id, slideData, slideParams);
	Sliobj.slidePluginDict[slide_id][pluginName] = pluginInstance;
	Sliobj.slidePluginList[slide_id].push(pluginInstance);
	Slidoc.Plugins[pluginName][slide_id] = pluginInstance;
	if ('incrementSlide' in pluginInstance)
	    Sliobj.incrementPlugins[slide_id] = pluginInstance;
	if ('answerSave' in pluginInstance)
	    Sliobj.answerPlugins[slide_id] = pluginInstance;

	if (instanceNum)
	    Sliobj.slidePluginDict[slide_id][pluginDefName][instanceNum] = pluginInstance;
	else
	    pluginInstance[0] = pluginInstance;

	var button = Sliobj.activePlugins[pluginName].button[slide_id];
	if (button)
	    Sliobj.buttonPlugins[slide_id] = pluginInstance;
	Slidoc.PluginManager.optCall.apply(null, [pluginInstance, 'init'].concat(pluginInstance.initArgs));
    }

    expandInlineJS(document);
}

function expandInlineJS(elem, methodName, argVal) {
    Slidoc.log('expandInlineJS:', methodName);
    if (arguments.length < 3)
	argVal = null;
    var jsSpans = elem.getElementsByClassName('slidoc-inline-js');
    for (var j=0; j<jsSpans.length; j++) {
	var jsFunc = jsSpans[j].dataset.slidocJsFunction;
	var comps = jsFunc.split('.');
	var pluginName = comps[0];
	var pluginMethod = comps[1];
	if (methodName && methodName != pluginMethod)
	    continue;

	var slide_id = jsSpans[j].dataset.slideId;
	var jsFormat = jsSpans[j].dataset.slidocJsFormat || '';
	if (pluginName == 'Params') {
	    // Evaluate expression using Params
	    var jsArg = jsSpans[j].dataset.slidocJsArgument || '';
	} else {
	    // Invoke method with single (optional argument)
	    var jsArg = argVal;
	    if (jsArg == null) {
		jsArg = jsSpans[j].dataset.slidocJsArgument || null;
		if (jsArg !== null)
		    try {jsArg = parseInt(jsArg); } catch (err) { jsArg = null; }
	    }
	}
	var val = Slidoc.PluginMethod(pluginName, slide_id, pluginMethod, jsArg);
	if (val != null)
	    jsSpans[j].innerHTML = formatNum(jsFormat, val);
    }
}

Slidoc.pluginButtonClick = function () {
    var slide_id = Slidoc.getCurrentSlideId();
    if (!slide_id)
	return false;
    Slidoc.log('pluginButtonClick:', slide_id);
    if (slide_id in Sliobj.buttonPlugins)
	Slidoc.PluginManager.optCall.apply(null, [Sliobj.buttonPlugins[slide_id], 'buttonClick']);
    return false;
}


Slidoc.fileTypeMap = {
    'application/pdf': 'pdf'
}
Slidoc.makeUserFileSuffix = function(displayName) {
    var match = /^([- #\w]+)(,\s*([A-Z]).*)$/i.exec(displayName||'');
    var suffix = '';
    if (match)
	suffix = match[1].trim().replace('#','').replace(' ','-').toLowerCase() + (match[3] ? '-'+match[3].toLowerCase() : '');
    return suffix || 'user';
}


Slidoc.uploadFile = function() {
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    var html = ['<b>Late file upload:</b> ',
		'Please obtain permission from instructor before uploading files late. Otherwise, late uploads will be ignored.',
	        '<p></p><span id="slidoc-uploadpopup-uploadlabel">Select file or drag-and-drop over button to upload:</span>',
		'<input type="file" id="slidoc-uploadpopup-uploadbutton" class="slidoc-clickable slidoc-button slidoc-plugin-Upload-button slidoc-uploadpopup-uploadbutton" onclick="Slidoc.uploadAction();"></input>'];
    Slidoc.showPopup(html.join(''));

    var filePrefix = 'Late/'+Sliobj.sessionName+'--late-'+Slidoc.makeUserFileSuffix(Sliobj.session.displayName);
    var uploadElem = document.getElementById('slidoc-uploadpopup-uploadbutton');
    uploadElem.addEventListener('change', Slidoc.uploadAction, false);
    Sliobj.uploadHandlerActive = Slidoc.uploadHandler.bind(null, 'Upload', Sliobj.uploadFileCallback, filePrefix, '', null);
}

Sliobj.uploadFileCallback = function(value) {
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    alert('Successfully uploaded file '+value.origName);
}

Sliobj.uploadHandlerActive = null;
Slidoc.uploadAction = function(evt) {
    if (!evt)
	return;
    var handler = Sliobj.uploadHandlerActive;
    Sliobj.uploadHandlerActive = null;
    if (handler)
	handler(evt);
    else
	alert('Error in file upload; no handler');
}

Slidoc.uploadHandler = function(pluginName, uploadCallback, filePrefix, teamName, fileTypes, evt) {
    // uploadCallback({origName:, fileType:, name:, url:, fileKey:})
    Slidoc.log('Slidoc.uploadHandler:', pluginName, !!uploadCallback, filePrefix, teamName, fileTypes, evt);
    if (!evt || !evt.target || !evt.target.files)
	return;
    var files = evt.target.files; // FileList object
    if (files.length != 1) {
	alert("Please select a single file");
	return;
    }
    fileTypes = fileTypes || null;

    var file = files[0];
    var origName = file.name;
    var fcomps = origName.split('.');
    var origExtn = (fcomps.length > 1) ? fcomps[fcomps.length-1] : '';
    var origHead = origExtn ? fcomps.slice(0,-1).join('.') : origName;
    var origType = ((file.type ? Slidoc.fileTypeMap[file.type]:'') || origExtn || 'unknown').toLowerCase();
    if (fileTypes && fileTypes.indexOf(origType) < 0) {
	alert('Invalid file type '+origType+'; expecting one of '+fileTypes);
	return;
    }

    if (filePrefix.match(/^Late/)) {
	var strippedName = origHead.replace(/\W/g,'');
	if (strippedName)
	    filePrefix += '-' + strippedName;
    }

    var fileDesc = origName+', '+file.size+' bytes';
    if (file.lastModifiedDate)
	fileDesc += ', last modified: '+file.lastModifiedDate.toLocaleDateString();

    var dataParams = {filename: origName, mimeType: file.type, filePrefix: filePrefix, userId: getUserId()}
    if (teamName)
	dataParams.teamName = teamName;

    var loadCallback = function(result) {
	if (!result || result.error) {
	    alert('Error in uploading file: '+( (result && result.error) ? result.error : ''));
	    return;
	}
	result.value.origName = origName;
	result.value.fileType = origType;
	uploadCallback(result.value);
    }

    var loadHandler = function(loadEvt) {
	var arrBuffer = loadEvt.target.result;
	Slidoc.log('Slidoc.uploadHandler.loadHandler:', origName, origType, arrBuffer.byteLength);
	Slidoc.PluginManager.remoteCall(pluginName, '_uploadData', loadCallback, dataParams, arrBuffer.byteLength);
	if (!window.GService)
	    alert('No upload service');
	GService.rawWS(arrBuffer);
    };

    var reader = new FileReader();
    reader.onload = loadHandler;
    reader.onerror = function(loadEvt) {
	alert("Failed to read file "+origName+" (code="+loadEvt.target.error.code+")");
    };

    reader.readAsArrayBuffer(file);
}

function responseAvailable(session, qnumber) { // qnumber is optional
    // Returns true value if uploaded files are available for a particular question or for the whole session
    if (qnumber)
	return session.plugins.Upload && session.plugins.Upload[qnumber];
    else
	return session.plugins.Upload && Object.keys(session.plugins.Upload);
}

function checkGradingCallback(userId, result, retStatus) {
    ///Slidoc.log('checkGradingCallback:', userId, result, retStatus);
    if (!result) {
	sessionAbort('ERROR in checkGradingCallback: '+ retStatus.error);
    }
    var unpacked = unpackSession(result);
    checkGradingStatus(userId, unpacked.session, unpacked.feedback);
}

function checkGradingStatus(userId, session, feedback) {
    ///Slidoc.log('checkGradingStatus:', userId);
    if (Sliobj.userGrades[userId].needGrading)
	return;

    if (session.submitted && session.submitted != 'GRADING')
	Sliobj.userGrades[userId].submitted = session.submitted;
    else
	Sliobj.userGrades[userId].submitted = null;
    Sliobj.userGrades[userId].late = (session.lateToken == LATE_SUBMIT);

    // Admin can modify grade columns only for submitted sessions
    var allowGrading = Sliobj.userGrades[userId].submitted;
    Sliobj.userGrades[userId].allowGrading = allowGrading;

    var firstSlideId = getVisibleSlides()[0].id;
    var attr_vals = getChapterAttrs(firstSlideId);
    var chapter_id = parseSlideId(firstSlideId)[0];
    var updates = {id: userId, Timestamp: null};
    var need_grading = {};
    var need_updates = 0;
    for (var qnumber=1; qnumber <= attr_vals.length; qnumber++) {
	var question_attrs = attr_vals[qnumber-1];
	var qfeedback = feedback ? (feedback[qnumber] || null) : null;
	if (qfeedback && qfeedback.grade !== '') // Graded
	    continue;
	// Needs grading
	var gradeField = 'q'+question_attrs.qnumber+'_grade';
	var commentsField = 'q'+question_attrs.qnumber+'_comments';
	if (qnumber in session.questionsAttempted || responseAvailable(session, qnumber)) {
	    // Attempted (or uploaded)
	    if (question_attrs.gweight) {
		// Weighted gradeable question
		need_grading[qnumber] = 1;
	    } else if ('gweight' in question_attrs) {
		// Zero weight gradeable question; set grade to zero to avoid blank cells in computation
		need_updates += 1;
		updates[gradeField] = 0;
	    }
	} else {
	    // Unattempted
	    need_updates += 1;
	    if (question_attrs.slide < Sliobj.maxLastSlide) {
		// set grade to zero to avoid blank cells in computation (not currently used)
		if ('gweight' in question_attrs) {
		    updates[gradeField] = 0;
		    updates[commentsField] = 'Not attempted';
		}
	    }
	}
    }
    ///Slidoc.log('checkGradingStatus:B', need_grading, updates);

    if (!Object.keys(need_grading).length && !Sliobj.userGrades[userId].submitted)
	Sliobj.userGrades[userId].needGrading = null;
    else
	Sliobj.userGrades[userId].needGrading = need_grading;

    updateGradingStatus(userId);

    if (0 && need_updates && allowGrading) {
	// DISABLED: Not needed anymore with arrayformula sum for q_total?
	// Set unattempted grades to zero (to avoid 'undefined' spreadsheet cells)
	// These will be blanked out if user later submits using a late submission token
	var gsheet = getSheet(Sliobj.sessionName);

	try {
	    gsheet.updateRow(updates, {});
	} catch(err) {
	    sessionAbort(''+err, err.stack);
	}
    }
}

function updateGradingStatus(userId) {
    var option = document.getElementById('slidoc-switch-user-'+Sliobj.userGrades[userId].index);
    if (!option)
	return;
    Sliobj.userGrades[userId].gradeDisp = computeGrade(userId, true);
    var text = Sliobj.userGrades[userId].index+'. '+Sliobj.userGrades[userId].name+' ';
    if (Sliobj.userGrades[userId].team)
	text += '('+Sliobj.userGrades[userId].team+') ';
    var html = Sliobj.userGrades[userId].gradeDisp;
    var gradeCount = Sliobj.userGrades[userId].needGrading ? Object.keys(Sliobj.userGrades[userId].needGrading).length : 0;
    if (Sliobj.userGrades[userId].allowGrading && Sliobj.userGrades[userId].needGrading) {
	if (gradeCount)
	    html += SYMS.anyMark + ' ' + gradeCount;
	else
	    html += SYMS.correctMark;
    }

    option.dataset.nograding = (gradeCount && Sliobj.userGrades[userId].allowGrading && !Sliobj.userGrades[userId].late) ? '' : 'nograding';
    option.innerHTML = '';
    option.appendChild(document.createTextNode(text));
    option.innerHTML += html;
}

function scoreSession(session) {
    // Tally of scores
    Slidoc.log('scoreSession:');
    var firstSlideId = getVisibleSlides()[0].id;
    Sliobj.scores = tallyScores(getChapterAttrs(firstSlideId), session.questionsAttempted, session.hintsUsed,
				Sliobj.params, Sliobj.remoteAnswers);
}

Slidoc.toggleAssessment = function () {
    if (Slidoc.serverCookie && !Slidoc.serverCookie.siteRole)
	return;
    if (!Sliobj.params.gd_sheet_url) {
	var href = location.protocol+'//'+location.host+location.pathname;
	if (!Sliobj.assessmentView)
	    href += '?print=1';
	location.href = href;
	return;
    }
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    Sliobj.assessmentView = !Sliobj.assessmentView;
    toggleClass(Sliobj.assessmentView, 'slidoc-assessment-view');
    if (Sliobj.assessmentView) {
	if (Sliobj.currentSlide)
	    Slidoc.slideViewEnd();
	toggleClassAll(false, 'slidoc-answered-slideview', 'slidoc-slide');
	alert('Entered print view. Use Down Arrow to print and advance');
    } else {
	alert('Ended print view.');
    }
    if (Sliobj.gradableState)
	selectUser(GService.gprofile.auth);
}

function preAnswer() {
    // Pre-answer questions (and display notes for those)
    Slidoc.log('preAnswer:');
    var firstSlideId = getVisibleSlides()[0].id;
    var attr_vals = getChapterAttrs(firstSlideId);
    var chapter_id = parseSlideId(firstSlideId)[0];
    clearAnswerElements();

    if ('shuffle_choice' in Sliobj.params.features && Sliobj.session && Sliobj.session.questionShuffle) {
	// Handle choice randomization
	for (var qnumber=1; qnumber <= attr_vals.length; qnumber++) {
	    var question_attrs = attr_vals[qnumber-1];
	    if (!(question_attrs.qtype == 'choice' || question_attrs.qtype == 'multichoice'))
		continue
	    // Choice question
	    var slide_id = chapter_id + '-' + zeroPad(question_attrs.slide, 2);
	    var shuffleStr = Sliobj.session.questionShuffle[qnumber] || '';
	    if (shuffleStr && Sliobj.gradableState && !Sliobj.assessmentView && Sliobj.testOverride) {
		// Do not display shuffled choices for grading; simply display shuffle string
		var shuffleDiv = document.getElementById(slide_id+'-choice-shuffle');
		if (shuffleDiv)
		    shuffleDiv.innerHTML = '<code>(Shuffled: '+shuffleStr+')</code>';
		shuffleStr = '';
	    }
	    shuffleBlock(slide_id, shuffleStr, qnumber);
	}
    }

    if (Sliobj.assessmentView)
	return;

    if (attr_vals.length) {
	// Initialize q_other/q_comments display
	var gradeValue = Sliobj.feedback ? (Sliobj.feedback.q_other || '') : '';
	var commentsValue = Sliobj.feedback ? (Sliobj.feedback.q_comments || '') : '';
	displayRemarks(commentsValue, gradeValue);
    }

    for (var qnumber=1; qnumber <= attr_vals.length; qnumber++) {
	var question_attrs = attr_vals[qnumber-1];
	var slide_id = chapter_id + '-' + zeroPad(question_attrs.slide, 2);

	if (Sliobj.session.hintsUsed && Sliobj.session.hintsUsed[qnumber]) {
	    // Display hints used
	    hintDisplayAux(slide_id, qnumber, Sliobj.session.hintsUsed[qnumber]);
	}

	if (qnumber in Sliobj.session.questionsAttempted) {
	    // Question attempted; display answer
	    var qAttempted = Sliobj.session.questionsAttempted[qnumber];
	    var qfeedback = Sliobj.feedback ? (Sliobj.feedback[qnumber] || null) : null;
	    Slidoc.answerClick(null, slide_id, 'preanswer', qAttempted.response, qAttempted.explain||null, qAttempted.expect||null, qAttempted.plugin||null, qfeedback);
	} else if (Sliobj.gradableState) {
	    // Question not attempted; display null plugin response if grading
	    var qtypeMatch = QTYPE_RE.exec(question_attrs.qtype);
	    if (qtypeMatch && qtypeMatch[2]) {
		var pluginName = qtypeMatch[1];
		Slidoc.PluginMethod(pluginName, slide_id, 'display', '', null);
		Slidoc.PluginManager.disable(pluginName, slide_id);
	    }
	}

    }

    if (Sliobj.session.submitted)
	showCorrectAnswersAfterSubmission();
}

function shuffleBlock(slide_id, shuffleStr, qnumber) {
    var choiceBlock = document.getElementById(slide_id+'-choice-block');
    if (qnumber in Sliobj.choiceBlockHTML)
	choiceBlock.innerHTML = Sliobj.choiceBlockHTML[qnumber]; // Restore original choices
    else
	Sliobj.choiceBlockHTML[qnumber] = choiceBlock.innerHTML; // Save original choices
	
    choiceBlock.dataset.shuffle = '';
    if (!shuffleStr)
	return;
    ///Slidoc.log('shuffleBlock: shuffleStr', slide_id, qnumber, ' ', shuffleStr);
    var childNodes = choiceBlock.childNodes;

    // Start with question key
    var blankKey = ' ';
    var key = blankKey;
    var choiceElems = {}
    choiceElems[blankKey] = [];
    var selAlternative = parseInt(shuffleStr.charAt(0)) || 0;
    for (var i=0; i < childNodes.length; i++) {
	var choiceElem = childNodes[i];
	if (!choiceElem.classList || !choiceElem.classList.contains('slidoc-choice-item'))
	    continue;  // Skip leading chart header div etc.
	var childElem = choiceElem.firstElementChild;
	var spanElem = childElem.firstElementChild;
	if (spanElem && spanElem.classList && spanElem.classList.contains('slidoc-chart-box'))
	    spanElem = spanElem.nextElementSibling;  // Skip leading chart box span

	if (spanElem && spanElem.classList && spanElem.classList.contains('slidoc-choice-inner')) {
	    if (spanElem.dataset.alternative) {
		// Alternative choice/question
		if (parseInt(spanElem.dataset.alternative) == selAlternative) {
		    key = spanElem.dataset.choice || blankKey;
		    choiceElems[key] = [];   // Skip default choice
		} else {
		    key = null;              // Skip alternative choice
		}
	    } else {
		// Default choice/question
		key = spanElem.dataset.choice || blankKey;
		choiceElems[key] = [];
	    }
	}
	if (key)
	    choiceElems[key].push(childElem);
    }

    if (Object.keys(choiceElems).length != shuffleStr.length) {
	Slidoc.log("shuffleBlock: ERROR Incorrect number of choice elements for shuffling in "+qnumber+": Expected "+(shuffleStr.length-1)+" but found "+(Object.keys(choiceElems).length-1));
	return;
    }

    choiceBlock.dataset.shuffle = shuffleStr;
    choiceBlock.innerHTML = '<div id="'+slide_id+'-chart-header" class="slidoc-chart-header" style="display: none;">';
    var key = blankKey;
    for (var i=0; i < choiceElems[key].length; i++)
	choiceBlock.appendChild(choiceElems[key][i]);
    var choiceDup = {};
    for (var j=1; j < shuffleStr.length; j++) {
	key = shuffleStr.charAt(j);
	var choiceText = '';
	var choiceLetter = letterFromIndex(j-1);
	for (var i=0; i < choiceElems[key].length; i++) {
	    var childElem = choiceElems[key][i];
	    var elemText = childElem.textContent;
	    if (i == 0) {
		var spanElem = childElem.firstElementChild;
		if (spanElem && spanElem.classList && spanElem.classList.contains('slidoc-chart-box'))
		    spanElem = spanElem.nextElementSibling;
		if (spanElem)
		    spanElem.textContent = choiceLetter;
	    }
	    choiceBlock.appendChild(childElem);
	    if (childElem.tagName == 'P')
		choiceText += elemText;
	}
	choiceText = choiceText.trim().replace(/\s+/g,' ');
	choiceText = choiceText.replace(/^ *[A-Z]\./i, '.');
	if (choiceText in choiceDup) {
	    var errMsg = 'Please reset session. Question '+qnumber+' has duplicate choices: '+choiceDup[choiceText]+','+choiceLetter+choiceText;
	    var firstSlide = document.getElementById(slide_id.slice(0,-3)+'-01');
	    if (firstSlide) {
		var div = document.createElement('div');
		div.classList.add('slidoc-choice-duplicate-message');
		div.textContent = errMsg;
		firstSlide.insertBefore(div, firstSlide.firstChild);
	    }
	    if (!Sliobj.batchMode)
		alert(errMsg);
	}
	choiceDup[choiceText] = choiceLetter;
    }
}

function displayAfterGrading() {
    // Always display automatic correct answers for submitted and graded sessions (except for locked views)
    return (Sliobj.params.showScore == 'after_grading' || 'remote_answers' in Sliobj.params.features) && (Sliobj.lockedView || !(Sliobj.session && Sliobj.session.submitted && Sliobj.gradeDateStr) );
}

function allowReanswer() {
    return Sliobj.params.resubmitAnswers && !Sliobj.gradableState && Sliobj.delayScoring && !(Sliobj.session && Sliobj.session.submitted);
}

function displayCorrect(qattrs) {
    if (allowReanswer() || displayAfterGrading() || (Sliobj.delayScoring && !(Sliobj.session && Sliobj.session.submitted)) )
	return false;
    // If non-submitted admin-paced and answering question on last slide, do not display correct answer
    if (controlledPace() && Sliobj.session && !Sliobj.session.submitted && Sliobj.session.lastSlide <= qattrs.slide)
	return false;
    return true;
}

function showCorrectAnswersAfterSubmission() {
    Slidoc.log('showCorrectAnswersAfterSubmission:');
    if (displayAfterGrading())
	return;
    var firstSlideId = getVisibleSlides()[0].id;
    var attr_vals = getChapterAttrs(firstSlideId);
    var chapter_id = parseSlideId(firstSlideId)[0];
    for (var qnumber=1; qnumber <= attr_vals.length; qnumber++) {
	if (qnumber in Sliobj.session.questionsAttempted)
	    continue;
	var question_attrs = attr_vals[qnumber-1];
	var slide_id = chapter_id + '-' + zeroPad(question_attrs.slide, 2);
	var qfeedback = Sliobj.feedback ? (Sliobj.feedback[qnumber] || null) : null;
	Slidoc.answerClick(null, slide_id, 'postsubmit', '', '', null, null, qfeedback);
    }
}

/////////////////////////////////////////////
// Section 15: Session data getting/putting
/////////////////////////////////////////////

function makeRandomChoiceSeed(randomSeed) {
    return Slidoc.Random.makeSeed(Sliobj.seedOffset.randomChoice+randomSeed);
}

function makeRandomParamSeed(randomSeed) {
    return Slidoc.Random.makeSeed(Sliobj.seedOffset.randomParams+randomSeed);
}

function makeRandomFunction(seed) {
    Slidoc.Random.setSeed(seed);
    return Slidoc.Random.randomNumber.bind(null, seed);
}


var NUM_RE = /^[+-]?(\d+)(\.\d*)?([eE][+-]?\d+)?$/;
function defaultDelta(minval, maxval, mincount, maxcount) {
    // Return "nice" delta interval (10/5/1/0.5/0.1, ...) for dividing the range minval to maxval
    var minmatch = NUM_RE.exec(minval+'');
    var maxmatch = NUM_RE.exec(maxval+'');
    if (!minmatch || !maxmatch) {
        return mincount;
    }
    var values = [];
    var exponents = [];
    var matches = [minmatch, maxmatch];
    for (var j=0; j<matches.length; j++) {
	var match = matches[j];
        if (!match[2] && !match[3]) {
            values.push( parseInt(match[1]) );
        } else {
            values.push( parseNumber(match[0]) );
        }
        if (match[2]) {
            var exp = -(match[2].length-1);
        } else {
            var num = match[1];
            var exp = 0;
            while (num.slice(-1) == '0') {
                exp += 1;
                num = num.slice(0,-1);
            }
        }
        if (match[3]) {
            exp += parseInt(match[3].slice(1));
        }
        exponents.push(exp);
    }
    var diff = Math.abs(values[1] - values[0]);
    if (!diff) {
        return 1;
    }
    var minexp = Math.min(exponents[0], exponents[1]);
    var delta = 10**minexp;
    var mulfac = 5;

    while ((diff/delta) > maxcount) {
        delta = delta * mulfac;
        mulfac = (mulfac == 5) ? 2 : 5;
    }

    while ((diff/delta) < mincount) {
        mulfac = (mulfac == 5) ? 2 : 5;
        delta = delta / mulfac;
    }
    return delta;
}

function rangeVals(minstr, maxstr, delstr, mincount, maxcount) {
    // Returns range of values from minstr to maxstr, spaced by delstr
    mincount = mincount || 20;
    maxcount = maxcount || 200;
    var minval = parseNumber(minstr);
    var maxval = parseNumber(maxstr);
    if (minval == null || maxval == null) {
        return [];
    }
    if (!delstr) {
        var delta = defaultDelta(minstr, maxstr, mincount, maxcount);
    } else {
        delta = parseNumber(delstr);
    }
    if (!delta || minval > maxval) {
        return [];
    } else if (minval == maxval) {
        return [minval];
    } else {
        var nvals = Math.floor(1.001 + (maxval - minval) / Math.abs(delta));
	var vals = [];
	for (var m=0; m<nvals; m++)
	    vals.push(minval + m*delta);
        return vals;
    }
}

Slidoc.rangeVals = rangeVals;

function createSession(sessionName, retakes, randomSeed) {
    var firstSlideId = getVisibleSlides()[0].id;
    var questions = getChapterAttrs(firstSlideId);

    var persistPlugins = {};
    if (Sliobj.params.plugins) {
	for (var j=0; j<Sliobj.params.plugins.length; j++)
	    persistPlugins[Sliobj.params.plugins[j]] = {};
    }

    if (!randomSeed)
        randomSeed = Slidoc.Random.makeSeed();

    var qshuffle = null;
    if (questions && Sliobj.params['features'].shuffle_choice) {
        var randFunc = makeRandomFunction(makeRandomChoiceSeed(randomSeed));
        qshuffle = {};
        for (var qno=1; qno < questions.length+1; qno++) {
            var choices = questions[qno-1].choices || 0;
            var alternatives = Math.min(9, questions[qno-1].alternatives || 0);
	    var noshuffle = questions[qno-1].noshuffle || 0;

	    if (qno > 1 && questions[qno-1].followup) {
		qshuffle[qno] = qshuffle[qno-1].charAt(0);
	    } else {
		qshuffle[qno] = ''+randFunc(0,alternatives);
	    }
            if (choices) {
                qshuffle[qno] += randomLetters(choices, noshuffle, randFunc);
            }
        }
    }

    var paramValues = null;
    if (Sliobj.params.paramDefinitions && Sliobj.params.paramDefinitions.length) {
	var randFunc = makeRandomFunction(makeRandomParamSeed(randomSeed));
	var paramDefinitions = Sliobj.params.paramDefinitions;
	paramValues = [];
	for (var j=0; j<paramDefinitions.length; j++) {
	    var slideValues = {};
	    try {
		var pcomps = paramDefinitions[j].split(';');
		for (var k=0; k<pcomps.length; k++) {
		    var dcomps = pcomps[k].split('=');
		    var defname  =  dcomps[0];
		    var defrange =  dcomps.slice(1).join('=');
		    var rcomps = defrange.split(':');
		    if (rcomps.length == 1) {
			var vals = [];
			var svals = rcomps[0].split(',');
			for (var m=0; m<svals.length; m++) {
			    var val = parseNumber(svals[m]);
			    if (val !== null)
				vals.push(val);
			}
		    } else {
			var vals = rangeVals(rcomps[0], rcomps[1], (rcomps.length > 2) ? rcomps[2] : '');
		    }
		    if (vals.length) {
			slideValues[defname] = vals[ randFunc(0,vals.length-1) ];
		    }
		}
	    } catch(err) {
	    }
	    paramValues.push(slideValues); 
	}
    }

    return {'version': Sliobj.params.sessionVersion,
	    'revision': Sliobj.params.sessionRevision,
	    'paced': Sliobj.params.paceLevel || 0,
	    'submitted': null,
	    'displayName': '',
	    'source': '',
	    'team': '',
	    'lateToken': '',
	    'lastSlide': 0,
	    'retakes': retakes || '',
	    'randomSeed': randomSeed, // Save random seed
            'expiryTime': Date.now() + 180*86400*1000,  // 180 day lifetime
            'startTime': Date.now(),
            'lastTime': 0,
            'lastTries': 0,
            'remainingTries': 0,
            'tryDelay': 0,
	    'showTime': null,
	    'paramValues': paramValues,
            'questionShuffle': qshuffle,
            'questionsAttempted': {},
	    'hintsUsed': {},
	    'plugins': persistPlugins
	   };
}

function createQuestionAttempted(response) {
    Slidoc.log('createQuestionAttempted:', response);
    return {'response': response || ''};
}

function copyObj(oldObj, excludeAttrs) {
    var newObj = {};
    var keys = Object.keys(oldObj);
    for (var j=0; j<keys.length; j++) {
	if (excludeAttrs && excludeAttrs.indexOf(keys[j]) >= 0)
	    continue;
	newObj[keys[j]] = oldObj[keys[j]];
    }
    return newObj;
}

function computeGrade(userId, breakup) {
    var gsheet = getSheet(Sliobj.sessionName);
    var rowObj = gsheet.getCachedRow(userId);
    var gradeStr = '';
    var q_grades = 0;
    if (rowObj) {
	for (var j=0; j<Sliobj.params.gradeFields.length; j++) {
	    var header = Sliobj.params.gradeFields[j];
	    var hmatch = QFIELD_RE.exec(header);
	    if (hmatch && hmatch[2] == 'grade') {
		q_grades += (parseNumber(rowObj[header]) || 0);
	    }
	}
	var q_scores = rowObj.q_scores||0;
	var q_other = rowObj.q_other||0;
	var tot = q_grades + q_scores + q_other;
	gradeStr += flexFixed(tot);
	if (breakup && (Sliobj.params.scoreWeight || q_other) && q_scores != tot) {
	    gradeStr += ' ('+flexFixed(q_scores);
	    if (q_other)
		gradeStr += ','+flexFixed(q_other);
	    gradeStr += ')';
	}
    }
    return gradeStr;
}

function packSession(session) {
    // Converts session to row for transmission to sheet
    Slidoc.log('packSession:', session);
    var rowObj = {};
    for (var j=0; j<COPY_HEADERS.length; j++) {
	var header = COPY_HEADERS[j];
	if (header in session)
	    rowObj[header] = session[header];  // Note: displayName is not copied
    }
    // Copy session to allow deletion of fields from questionAttempted objects
    var sessionCopy = copyObj(session);
    sessionCopy.questionsAttempted = copyObj(sessionCopy.questionsAttempted);
    var keys = Object.keys(sessionCopy.questionsAttempted);
    for (var j=0; j<keys.length; j++)
	sessionCopy.questionsAttempted[keys[j]] = copyObj(sessionCopy.questionsAttempted[keys[j]]);
    
    for (var j=0; j<Sliobj.params.gradeFields.length; j++) {
	var header = Sliobj.params.gradeFields[j];
	var hmatch = QFIELD_RE.exec(header);
	// For attempted questions, one of response/explain must be non-null
	if (hmatch && (hmatch[2] == 'response' || hmatch[2] == 'explain' || hmatch[2] == 'plugin')) {
	    // Copy only response/explain/plugin field for grading (all others are not updated)
	    var qnumber = parseInt(hmatch[1]);
	    if (qnumber in sessionCopy.questionsAttempted) {
		if (hmatch[2] in sessionCopy.questionsAttempted[qnumber]) {
		    // Copy field to column and delete from session object
		    var rowValue = sessionCopy.questionsAttempted[qnumber][hmatch[2]] || '';
		    // Use SKIP_ANSWER as place holder for null answer attempts in spreadsheet column
		    if (!rowValue && hmatch[2] == 'response')
			rowValue = SKIP_ANSWER;
		    if (rowValue && hmatch[2] == 'plugin')
			rowValue = Slidoc.orderedStringify(rowValue);
		    rowObj[header] = rowValue;

		    delete sessionCopy.questionsAttempted[qnumber][hmatch[2]];

		    if (!Object.keys(sessionCopy.questionsAttempted[qnumber]).length)
			delete sessionCopy.questionsAttempted[qnumber];
		} else {
		    rowObj[header] = '';
		}
	    }
	}
    }
    // Break up Base64 version of object-json into lines (commented out; does not work with JSONP)
    ///var base64str = btoa(Slidoc.orderedStringify(sessionCopy));
    ///var comps = [];
    ///for (var j=0; j < base64str.length; j+=80)
    ///    comps.push(base64str.slice(j,j+80));
    ///comps.join('')+'';
    rowObj.session_hidden = Slidoc.orderedStringify(sessionCopy);
    return rowObj;
}

function unpackSession(row) {
    // Unpacks hidden session object and adds response/explain fields from sheet row, as needed
    // Also returns feedback for session:
    //   {session:, feedback:}
    Slidoc.log('unpackSession:', row);
    var session_hidden = row.session_hidden;
    if (session_hidden.charAt(0) != '{')
	session_hidden = atob(session_hidden);

    var session = JSON.parse(session_hidden);
    session.displayName = row.name || '';
    for (var j=0; j<COPY_HEADERS.length; j++) {
	var header = COPY_HEADERS[j];
	if (header == 'lastSlide')
	    session[header] =  Math.min(row[header] || 0, Sliobj.params.pacedSlides);
	else
	    session[header] = row[header] || '';
    }

    if (row.submitTimestamp) {
	session.submitted = row.submitTimestamp;
	if (!controlledPace())
	    session.lastSlide = Sliobj.params.pacedSlides;
    }

    for (var j=0; j<Sliobj.params.gradeFields.length; j++) {
	var header = Sliobj.params.gradeFields[j];
	if (row[header]) {
	    var hmatch = QFIELD_RE.exec(header);
	    if (hmatch && (hmatch[2] == 'response' || hmatch[2] == 'explain' || hmatch[2] == 'plugin')) {
		// Copy only response/explain/plugin field to session
		var qnumber = parseInt(hmatch[1]);
		if (hmatch[2] == 'response') {
		    if (!row[header]) {
			// Null row entry deletes attempt
			if (qnumber in session.questionsAttempted)
			    delete session.questionsAttempted[qnumber];
		    } else {
			if (!(qnumber in session.questionsAttempted))
			    session.questionsAttempted[qnumber] = createQuestionAttempted();
			// SKIP_ANSWER implies null answer attempt
			session.questionsAttempted[qnumber][hmatch[2]] = (row[header] == SKIP_ANSWER) ? '' : row[header];
		    }
		} else if (qnumber in session.questionsAttempted) {
		    // Explanation/plugin (ignored if no attempt)
		    if (hmatch[2] == 'plugin') {
			if (row[header])
			    session.questionsAttempted[qnumber][hmatch[2]] = JSON.parse(row[header]);
		    } else {
			session.questionsAttempted[qnumber][hmatch[2]] = row[header];
		    }
		}
	    }
	}
    }

    var keys = Object.keys(row);
    var feedback = {};

    var count = 0; // Count of non-null values
    for (var j=0; j<keys.length; j++) {
	var key = keys[j];
	var value = row[key];
	var hmatch = QFIELD_RE.exec(key);
	if (hmatch && hmatch[2] != 'response' && hmatch[2] != 'explain') {
	    // Treat all column headers of the form q1_* as feedback (except for response/explain)
	    var qnumber = parseInt(hmatch[1]);
	    if (!(qnumber in feedback))
		feedback[qnumber] = {};
	    feedback[qnumber][hmatch[2]] = value;
	    if (value != null && value != '')
		count += 1;
	    if (hmatch[2] == 'comments')
		cacheComments(qnumber, row.id, value);
	} else if (isNumber(value) && (key == 'q_total' || key == 'q_scores' || key == 'q_other')) {
	    // Total grade/score/other
	    feedback[key] = value;
	    if (value)
		count += 1;
	} else if (value && key == 'q_comments') {
	    feedback[key] = value;
	    count += 1;
	}
    }

    return {session: session,
	    feedback: count ? feedback : null};
}

var GRADE_COMMENT_RE = /^ *\(([-+]\d+.?\d*)\)(.*)$/;
Sliobj.adaptiveComments = {};

function cacheComments(qnumber, userId, comments, update) {
    if (!('adaptive_rubric' in Sliobj.params.features))
	return true;
    Slidoc.log("cacheComments", qnumber, userId, update);
    if (!(qnumber in Sliobj.adaptiveComments))
	Sliobj.adaptiveComments[qnumber] = {};
    var qComments = Sliobj.adaptiveComments[qnumber];
    if (update) {
	// Erase all previous entries for this user in current question
	var prevLines = Object.keys(qComments);
	for (var j=0; j<prevLines.length; j++) {
	    var qCommentLine = qComments[prevLines[j]];
	    if (userId in qCommentLine.userIds) {
		delete qCommentLine.userIds[userId];
		if (!Object.keys(qCommentLine.userIds).length)
		    delete qComments[prevLines[j]];
	    }
	}
    }
    var lines = (comments||'').split(/\r?\n/);
    for (var j=0; j<lines.length; j++) {
	// Add entries for this user
	var line = lines[j];
	line = line.trim();
	if (!line || line.charAt(0) == '>') // Skip blank and quoted lines
	    continue;
	var cscore = '';
	var cmatch = GRADE_COMMENT_RE.exec(line);
	if (cmatch) {
	    cscore = cmatch[1];
	    line = cmatch[2].trim();
	}
	if (line in qComments) {
	    var qCommentLine = qComments[line];
	    qCommentLine.userIds[userId] = 1;
	    if (qCommentLine.score != null && qCommentLine.score != cscore) {
		if (!qCommentLine.inconsistent)
		    alert('Conflicting scores for comment on question '+qnumber+' for user '+userId+'; previously ('+qCommentLine.score+') but now: \n('+cscore+') '+line+'. \nFix score or change comment slightly.');
		qCommentLine.inconsistent += 1;
	    }
	} else {
	    var qCommentLine = {score: cscore, userIds: {}, inconsistent: 0};
	    qComments[line] = qCommentLine;
	    qCommentLine.userIds[userId] = 1;
	}
    }
    return true;
}

function displayCommentSuggestions(slideId, qnumber) {
    if (!('adaptive_rubric' in Sliobj.params.features))
	return;
    Slidoc.log("displayCommentSuggestions", slideId, qnumber);
    var suggestElem = document.getElementById(slideId+'-comments-suggestions');
    if (!qnumber) {
	if (suggestElem)
	    suggestElem.style.display = 'none';
	return;
    }
    var dispComments = [];
    var qComments = Sliobj.adaptiveComments[qnumber];
    if (qComments) {
	// Sort comment lines by frequency of occurrence
	var lines = Object.keys(qComments);
	for (var j=0; j<lines.length; j++) {
	    var qCommentLine = qComments[lines[j]];
	    var pmatch = lines[j].match(/^([a-zA-Z][\w.-]*):/);
	    var prefix = pmatch ? pmatch[1] : '';   // Prefix is a "word" followed by a colon, e,g, Q.3, Q3, or Part-3
	    // [prefix, occurrences, score, text, inconsistent?]
	    dispComments.push( [prefix, Object.keys(qCommentLine.userIds).length, qCommentLine.score, lines[j], qCommentLine.inconsistent] )
	}

	// Sort by prefix, negative occurrence counts, and then negative absolute score, and then alphabetically
	dispComments.sort( function(a,b){ if (a[0] != b[0]) return cmp(a[0], b[0]); else if (a[1] != b[1]) return cmp(-a[1], -b[1]); else if (a[2] != b[2]) return cmp(-Math.abs(a[2]), -Math.abs(b[2])); else return cmp(a[3].toLowerCase(),b[3].toLowerCase()); } );
    }
    if (suggestElem) {
	var html = ['Suggested comments:<br>\n'];
	for (var j=0; j<dispComments.length; j++) {
	    var cscore = dispComments[j][2] || 0;
	    var clabel = cscore||'';
	    if (dispComments[j][4])
		clabel += '*';      // Inconsistent
	    var lineHtml = '<code><span><span class="slidoc-clickable" onclick="Slidoc.appendComment(this,'+cscore+",'"+slideId+"');"+'">('+clabel+')</span> <span>'+escapeHtml(dispComments[j][3])+'</span></span> [<span class="slidoc-clickable" onclick="Slidoc.trackComment(this,'+qnumber+');">'+(dispComments[j][1])+'</span>]</code><br>\n'
	    html.push(lineHtml);
	}
	suggestElem.innerHTML = html.join('\n');
	suggestElem.style.display = null;
    }
}

Slidoc.gradeMax = function (elem, slideId, gradeStr) {
    Slidoc.log("Slidoc.gradeMax:", elem, slideId, gradeStr);
    var startGrading = !elem || elem.classList.contains('slidoc-gstart-click');
    if (startGrading)
	return;
    var gradeInput = document.getElementById(slideId+'-grade-input');
    if (gradeInput && gradeStr) {
	gradeInput.value = gradeStr.slice(1);
	Slidoc.gradeClick(elem, slideId);
    }
}

Slidoc.appendComment = function (elem, cscore, slideId) {
    Slidoc.log("Slidoc.appendComment", elem, cscore, slideId);
    var questionAttrs = getQuestionAttrs(slideId);
    var maxScore = questionAttrs.gweight||0;
    var gradeElement = document.getElementById(slideId+'-grade-element');
    var gradeInput = document.getElementById(slideId+'-grade-input');
    var commentsArea = document.getElementById(slideId+'-comments-textarea');
    var prevComments = commentsArea.value;
    if (prevComments) {
	if (!prevComments.match(/\n$/))
	    prevComments += '\n';
	prevComments += '\n';
    }
    commentsArea.value = prevComments + (cscore ? elem.parentNode.textContent : elem.parentNode.firstElementChild.nextElementSibling.textContent) + '\n';
    scrollTextArea(commentsArea);
    if (cscore && maxScore) {
	var scoreVal = parseFloat(cscore);
	if (gradeInput.value) {
	    gradeInput.value = '' + parseFloat((parseFloat(gradeInput.value) + scoreVal).toFixed(3));
	} else if (scoreVal < 0) {
	    gradeInput.value = '' + parseFloat((maxScore + scoreVal).toFixed(3));
	} else {
	    gradeInput.value = '' + scoreVal;
	}
    }
}

Slidoc.trackComment = function (elem, qnumber) {
    var qComments = Sliobj.adaptiveComments[qnumber];
    if (!qComments)
	return;
    var line = elem.parentNode.firstElementChild.firstElementChild.nextElementSibling.textContent.trim();
    var qCommentLine = qComments[line];
    if (!qCommentLine) {
	alert('Comment not found: '+line);
	return;
    }
    var userIds = Object.keys(qCommentLine.userIds);
    var html = '<ul class="slidoc-contents-list">\n';
    for (var j=0; j < userIds.length; j++) {
	var userId = userIds[j];
	html += '<li class="slidoc-clickable slidoc-contents-header" onclick="Slidoc.switchToUser('+"'"+userId+"'"+');">'+Sliobj.userGrades[userId].name+'</li>';
    }
    html += '</ul>\n';
    Slidoc.showPopup(html);
}

function showPendingCalls() {
    var hourglasses = '';
    var gsheet = getSheet(Sliobj.sessionName);
    if (gsheet) {
	for (var j=0; j<gsheet.callbackCounter; j++)
	    hourglasses += '&#x29D7;'
    }
    if (Sliobj.ajaxRequestActive)
	hourglasses += '&#x29D6;'
	
    var pendingElem = document.getElementById("slidoc-pending-display");
    if (pendingElem)
	pendingElem.innerHTML = hourglasses;
}

function sessionGetPutAux(prevSession, callType, callback, retryOpts, result, retStatus) {
    // retryOpts = {type: '...', call:, reload: }
    // callback(session, feedback)
    Slidoc.log('Slidoc.sessionGetPutAux: ', prevSession, callType, !!callback, retryOpts.type, !!retryOpts.reload, !!retryOpts.call, result, retStatus);
    var session = null;
    var feedback = null;
    var nullReturn = false;
    var err_msg = retStatus.error || '';
    showPendingCalls();

    if (result) {
	GService.gprofile.auth.validated = 'sessionGetPutAux';
	if (!result.id) {
	    // Null object {} returned, indicating non-presence for get
	    nullReturn = true;
	} else {
	    try {
		var unpacked = unpackSession(result);
		session = unpacked.session;
		feedback = unpacked.feedback;
	    } catch(err) {
		Slidoc.log('Slidoc.sessionGetPutAux: ERROR in parsing session_hidden', err)
		err_msg = 'Parsing error '+err_msg;
	    }
	}

    }
    var parse_msg_re = /^(\w+):(\w*):(.*)$/;
    var match = parse_msg_re.exec(err_msg || '');
    var err_type = match ? match[2] : '';
    var err_info = match ? match[3] : ''
    var remainingSec = 0;
    if (session || nullReturn) {
	// Successful get/put
	if (retryOpts.reload) {
	    location.reload(true);
	    return;
	}
	Sliobj.errorRetries = 0;
	if (retStatus && retStatus.info && retStatus.info.sheet && retStatus.info.sheet == Sliobj.sessionName) {
	    // Update info for currently active session
	    if (retStatus.info.version)
		Sliobj.remoteVersion = retStatus.info.version;

	    if (retStatus.info.proxyError)
		alert(retStatus.info.proxyError);

	    if (retStatus.info.timedSecLeft)
		Sliobj.timedSecLeft = retStatus.info.timedSecLeft;

	    if (retStatus.info.gradeDate)
		Sliobj.gradeDateStr = retStatus.info.gradeDate;

	    if (retStatus.info.remoteAnswers)
		Sliobj.remoteAnswers = retStatus.info.remoteAnswers;

	    if (retStatus.info.userFileKey)
		Sliobj.userFileKey = retStatus.info.userFileKey;

	    if (retStatus.info.teamFileKey)
		Sliobj.teamFileKey = retStatus.info.teamFileKey;

	    if (retStatus.info.discussStats)
		Sliobj.discussStats = retStatus.info.discussStats;

	    if (retStatus.info.sheetsAvailable)
		Sliobj.sheetsAvailable = retStatus.info.sheetsAvailable;

	    if (retStatus.info.voteDate)
		try { Sliobj.voteDate = new Date(retStatus.info.voteDate); } catch(err) { Slidoc.log('sessionGetPutAux: Error VOTE_DATE: '+retStatus.info.voteDate, err); }

	    if (retStatus.info.dueDate) {
		try {
		    Sliobj.dueDate = new Date(retStatus.info.dueDate);
		    remainingSec = Math.floor( (Sliobj.dueDate.getTime() - (new Date()).getTime())/1000 );
		} catch(err) {
		    Slidoc.log('sessionGetPutAux: Error DUE_DATE: '+retStatus.info.dueDate, err);
		}
	    }

	    if (retStatus.info.createRow && Sliobj.params.remoteLogLevel >= 2)
		Slidoc.remoteLog('sessionGet', '', 'createRow', '');

	    var limitSlides = (controlledPace() || (isController() && session && session.submitted));
	    if (retStatus.info.adminPaced && limitSlides) {
		// This should occur before Sliobj.session.lastSlide is set; used by visibleSlideCount
		Sliobj.adminPaced = retStatus.info.adminPaced;
		if (session) {
		    if (session.submitted)
			session.lastSlide = retStatus.info.adminPaced;
		    else
			session.lastSlide = Math.min(session.lastSlide, retStatus.info.adminPaced);
		}
	    }

	    if (retStatus.info.team && Sliobj.session) {
		Sliobj.session.team = retStatus.info.team;
	    }
	    if (retStatus.info.submitTimestamp) {
		if (!Sliobj.session)
		    sessionAbort('Internal error: submit timestamp without session')
		Sliobj.session.submitted = retStatus.info.submitTimestamp;
		if (Sliobj.params.paceLevel >= ADMIN_PACE) {
		    if (retStatus.info.adminPaced)
			Sliobj.adminPaced = retStatus.info.adminPaced;
		    Sliobj.session.lastSlide = visibleSlideCount();
		} else {
		    Sliobj.session.lastSlide = Sliobj.params.pacedSlides;
		}
		toggleClass(true, 'slidoc-submitted-view');
		showCorrectAnswersAfterSubmission();
	    }
	}
	if (retryOpts.type == 'end_paced') {
	    if (Sliobj.session.submitted) {
		showCompletionStatus();
	    } else {
		alert('Error in submitting session; no submit time');
	    }
	    showSubmitted();
	} else if (retryOpts.type == 'ready' && Sliobj.params.gd_sheet_url && !Sliobj.params.gd_client_id) {
	    if (GService.gprofile.auth.remember)
		localPut('auth', GService.gprofile.auth); // Save auth info on successful start
	}

	if (Sliobj.params.paceLevel < ADMIN_PACE && remainingSec > 10) {
	    timedInit(remainingSec);
	}

	if (retStatus && retStatus.messages) {
	    var alerts = [];
	    for (var j=0; j < retStatus.messages.length; j++) {
		var match = parse_msg_re.exec(retStatus.messages[j]);
		var msg_type = match ? match[2] : '';
		if (msg_type == 'NEAR_SUBMIT_DEADLINE' || msg_type == 'PAST_SUBMIT_DEADLINE') {
		    if (session && !session.submitted) {
			alerts.push('<em>Warning:</em><br>'+match[3]);
		    }
		} else if (msg_type == 'INVALID_LATE_TOKEN') {
		    alerts.push('<em>Warning:</em><br>'+match[3]);
		} else if (msg_type == 'FORCED_SUBMISSION') {
		    alerts.push('<em>Warning:</em><br>'+match[3]);
		}
	    }
	    if (alerts.length)
		Slidoc.showPopup(alerts.join('<br>\n'));
	}
	if (callback) {
	    // Successful callback
	    callback(session, feedback);
	    ///Slidoc.reportTestAction(callType+'Session');
	}
	return;

    } else if (retryOpts.call) {
	if (err_msg) {
	    if (Sliobj.errorRetries > MAX_SYS_ERROR_RETRIES) {
		sessionAbort('Too many retries: '+err_msg);
		return;
	    }
	    Sliobj.errorRetries += 1;
	    var prefix = err_type.match(/INVALID_.*TOKEN/) ? 'Invalid token. ' : '';
	    if (err_type == 'NEED_ROSTER_ENTRY') {
		Slidoc.userLogin(err_info+'. Please enter a valid userID (or contact instructor).', retryOpts.call);
		return;

	    } else if (err_type == 'ADMIN_NEW_ROW') {
		alert('Admin user cannot create new session entry for user '+getUserId()+'. Please logout and login again.');
		Slidoc.userLogout();
		return;

	    } else if (err_type == 'INVALID_ADMIN_TOKEN') {
		Slidoc.userLogin('Invalid admin token or key mismatch. Please re-enter', retryOpts.call);
		return;

	    } else if (err_type == 'NEED_TOKEN' || err_type == 'INVALID_TOKEN') {
		Slidoc.userLogin('Invalid username/token or key mismatch. Please re-enter', retryOpts.call);
		return;

	    } else if ((prevSession||retryOpts.type == 'ready') && (err_type == 'PAST_SUBMIT_DEADLINE' || err_type == 'INVALID_LATE_TOKEN')) {
		var temToken = setLateToken(prevSession||Sliobj.session, prefix);
		if (temToken) {
		    retryOpts.call(temToken);
		    return;
		}
	    } else if (retryOpts.type == 'ready' || retryOpts.type == 'new' || retryOpts.type == 'end_paced') {
		var conf_msg = 'Error in saving'+((retryOpts.type == 'end_paced') ? ' completed':'')+' session to Google Docs: '+err_msg+' Retry?';
		if (window.confirm(conf_msg)) {
		    retryOpts.call();
		    return;
		}
	    }
	}
    }
    Slidoc.reportTestAction('ERROR '+err_msg);
    sessionAbort('Error in accessing session info from Google Docs: '+err_msg+' (session aborted)');
}

function setLateToken(session, prefix) {
    Slidoc.log('setLateToken', session, prefix);
    var prompt = (prefix||'The submission deadline has passed.')+" If you have a valid excuse, please request a late submission token from your instructor for user "+GService.gprofile.auth.id+" and session "+Sliobj.sessionName+". Otherwise enter '"+LATE_SUBMIT+"' to proceed with "+(Sliobj.params.lateCredit?'reduced credit.':'no credit.');
    var token = showDialog('prompt', 'lateTokenDialog', prompt);
    token = (token || '').trim();
    if (token == LATE_SUBMIT || token.indexOf(':') > 0) {
	if (session)
	    session.lateToken = token;
	return token;
    }
    sessionAbort('No token or invalid token provided');
    return null;
}

function sessionManage() {
    // Cleanup sessions in local storage
    if (Sliobj.params.gd_sheet_url)
	return;
    var sessionObj = localGet('sessions');
    if (!sessionObj) {
	localPut('sessions', {});
	return;
    }
    var names = Object.keys(sessionObj);
    for (var j=0; j<names.length; j++) {
	// Clear expired sessions
	var curTime = Date.now();
	if (sessionObj[names[j]].expiryTime > curTime)
	    delete sessionObj[names[j]];
    }
}

function sessionGet(userId, sessionName, opts, callback, lateToken) {
    // callback(session, feedback)
    // opts = {create:true/false, retry:str}
    Slidoc.log('sessionGet', userId, sessionName, opts, callback, lateToken);
    opts = opts || {};
    if (Sliobj.params.gd_sheet_url) {
	// Google Docs storage
	var gsheet = getSheet(sessionName);
	// Freeze userId for retry only if validated
	if (!userId && GService.gprofile.auth.validated)
	    userId = GService.gprofile.auth.id;
	var retryOpts = {type: opts.retry||''};
	retryOpts.call = opts.retry ? sessionGet.bind(null, userId, sessionName, opts, callback) : null;
	var getOpts = {};
	if (opts.create) getOpts.create = 1;
	if (lateToken) getOpts.late = lateToken;
	try {
	    gsheet.getRow(userId, getOpts, sessionGetPutAux.bind(null, null, 'get', callback, retryOpts));
	} catch(err) {
	    sessionAbort(''+err, err.stack);
	    return;
	}
	showPendingCalls();
    } else {
	// Local storage
	var sessionObj = localGet('sessions');
	if (!sessionObj) {
	    alert('sessionGet: Error - no session object');
	} else {
	    if (sessionName in sessionObj)
		callback(sessionObj[sessionName]);
	    else
		callback(opts.create ? createSession() : null);
	}
    }
}

function sessionPut(userId, session, opts, callback, lateToken) {
    // Remote saving only happens if session.paced is true or force is true
    // callback(session, feedback)
    // opts = {nooverwrite:, get:, retry:, force:, reload:true/false }
    // If opts.reload, reload on successful put
    // lateToken is not used, but is already set in session, It is provided for compatibility with sessionGet
    Slidoc.log('sessionPut:', userId, Sliobj.sessionName, session, opts, !!callback, lateToken);
    if (Sliobj.gradableState) {
	alert('Internal error: admin user cannot update row');
	return;
    }
    if (!Sliobj.sessionName) {
	if (callback)
	    callback(null);
	return;
    }
    session = session || Sliobj.session;
    opts = opts || {};
    if (Sliobj.params.gd_sheet_url) {
	// Google Docs storage; remote save
	if (!session.paced && !opts.force) {
	    if (callback)
		callback(opts.get ? session : null);
	    return;
	}
	// Freeze userId for retry only if validated
	if (!userId && GService.gprofile.auth.validated)
	    userId = GService.gprofile.auth.id;
	var retryOpts = {type: opts.retry||''};
	if (opts.reload)
	    retryOpts.reload = true;
	retryOpts.call = opts.retry ? sessionPut.bind(null, userId, session, opts, callback) : null;
	var putOpts = {};
	if (userId) putOpts.id = userId;
	if (opts.nooverwrite) putOpts.nooverwrite = 1;
	if (opts.get) putOpts.get = 1;
	if (opts.submit) putOpts.submit = 1;

	var rowObj = packSession(session);
	var gsheet = getSheet(Sliobj.sessionName);
	try {
	    gsheet.authPutRow(rowObj, putOpts, sessionGetPutAux.bind(null, session, 'put', callback||null, retryOpts),
			      false);
	} catch(err) {
	    sessionAbort(''+err, err.stack);
	    return;
	}
	showPendingCalls();

    } else {
	// Local storage
	var sessionObj = localGet('sessions');
	if (!sessionObj) {
	    alert('sessionPut: Error - no session object');
	} else {
	    if (!(Sliobj.sessionName in sessionObj) || !opts.nooverwrite)
		sessionObj[Sliobj.sessionName] = session;
	    localPut('sessions', sessionObj);
	    if (callback)
		callback(opts.get ? sessionObj[Sliobj.sessionName] : null);
	}
    }
}

//////////////////////////////////////
// Section 16: More helper functions
//////////////////////////////////////

function make_id_from_text(text) {
    return text.toLowerCase().trim().replace(/[^-\w\.]+/g, '-').replace(/^[-\.]+/g, '').replace(/[-\.]+$/g, '');
}

function getBaseURL() {
   return location.pathname.split('/').slice(0,-1).join('/');
}

function progressBar(delaySec) {
    // Displays a progress bar
    var interval = 0.05;
    var jmax = delaySec/interval;
    var j = 0;
    var pb_container_elem = document.getElementById('slidoc-progressbar-container');
    var pb_elem = document.getElementById('slidoc-progressbar');
    function clocktick() {
	j += 1;
	pb_elem.style.left = 1.05*Math.ceil(pb_container_elem.offsetWidth*j/jmax);
    }
    var intervalId = setInterval(clocktick, 1000*interval);
    function endInterval() {
	clearInterval(intervalId);
	pb_elem.style.left = pb_container_elem.offsetWidth;
    }
    setTimeout(endInterval, delaySec*1000);
}

function delayElement(delaySec) // ElemendIds to be hidden as extra args
{
    // Displays element after a delay (with 1 second transition afterward)
    var interval = 0.05;
    var transition = 1;
    var jmax = (delaySec+transition)/interval;
    var jtrans = delaySec/interval
    var j = 0;
    var hideElemIds = Array.prototype.slice.call(arguments).slice(1);
    function clocktick() {
	j += 1;
	for (var k=0; k<hideElemIds.length; k++) {
	    var hideElem = document.getElementById(hideElemIds[k]);
	    if (hideElem)
		hideElem.style.opacity = (j < jtrans) ? 0.1 : Math.min(1.0, 0.1+0.9*(j-jtrans)/(jmax-jtrans) );
	}
    }
    var intervalId = setInterval(clocktick, 1000*interval);
    function endInterval() {
	clearInterval(intervalId);
	for (var k=0; k<hideElemIds.length; k++) {
	    var hideElem = document.getElementById(hideElemIds[k]);
	    if (hideElem)
		hideElem.style.opacity = 1.0;
	}
    }
    setTimeout(endInterval, (delaySec+transition)*1000);
}

function slidesVisible(visible, slideNumber, slides) {
    var dispStyle = visible ? null : 'none';
    if (!slideNumber) {
	// All slides (and toggle elements)
	Slidoc.classDisplay('slidoc-slide', dispStyle);
	Slidoc.classDisplay('slidoc-togglebar', dispStyle);
    } else {
	// Selected slide (and toggle element)
	if (!slides)
	    slides = getVisibleSlides();
	if (slideNumber > slides.length)
	    throw('slidesVisible: Not enough slides: '+slideNumber+' > '+slides.length+'; may need to reset this session');
	slides[slideNumber-1].style.display = dispStyle;
	var togglebar = document.getElementById(slides[slideNumber-1].id+'-togglebar');
	if (togglebar)
	    togglebar.style.display = dispStyle;
    }
}

function visibleSlideCount() {
    if (controlledPace() || (isController() && Sliobj.session.submitted) )
	return Math.min(Math.max(1,Sliobj.adminPaced), Sliobj.params.pacedSlides);
    else
	return Sliobj.params.pacedSlides;
}

function getVisibleSlides(getAll) {
   var slideClass = 'slidoc-slide';
   if (Sliobj.curChapterId) {
      var curChap = document.getElementById(Sliobj.curChapterId);
      if (curChap.classList.contains('slidoc-noslide'))
        return null;
      slideClass = Sliobj.curChapterId+'-slide';
   }
    var slideElems = document.getElementsByClassName(slideClass);
    var slides = [];
    for (var j=0; j<slideElems.length; j++)   // Convert NodeList to regular array for slicing
	slides.push(slideElems[j]);

    if (!controlledPace() || getAll)
	return slides;
    else
	return slides.slice(0, visibleSlideCount());
}

function getCurrentlyVisibleSlide(slides) {
    if (!slides)
	return 0;
    for (var j=0; j<slides.length; j++) {
	// Start from currently visible slide
	var topOffset = slides[j].getBoundingClientRect().top;
	if (topOffset >= 0 && topOffset < window.innerHeight) {
            return j+1;
	}
    }
    return 0
}

function getSlideFooter(slide_id) {
    return document.getElementById(slide_id+'-footer-toggle');
}

Slidoc.getCurrentSlideId = function () {
    return Sliobj.currentSlide ? getVisibleSlides()[Sliobj.currentSlide-1].id : ''
}

Slidoc.hide = function (elem, className, action) {
    // Action = '+' show or '-'|'\u2212' (&#8722;) hide or omitted for toggling
    if (!elem) return false;
    if (!className)
	className = elem.id.slice(0,-5) // Strip '-hide' suffice from id
    action = action || elem.textContent;
    if (action.charAt(0) == '+') {
	elem.textContent = elem.textContent.replace('+', '\u2212');
	if (className) Slidoc.classDisplay(className, 'block');
    } else {
	elem.textContent = elem.textContent.replace('\u2212', '+');
	if (className) Slidoc.classDisplay(className, 'none');
    }
    return false;
}

Slidoc.pagesDisplay = function() {
    Slidoc.log('Slidoc.pagesDisplay:');
    var html = '<b>Pages</b><p></p>';
    if (Sliobj.fullAccess)
	html += '<a class="slidoc-clickable" target="_blank" href="'+Sliobj.sitePrefix+'/_dash">Dashboard</a><p></p>';

    if (Sliobj.params.topnavList && Sliobj.params.topnavList.length) {
	html += '<ul>\n';
	for (var j=0; j<Sliobj.params.topnavList.length; j++) {
	    var link = Sliobj.params.topnavList[j][0];
	    var pagename = Sliobj.params.topnavList[j][1];
            if (link.match(/^#/))
		html += '<li><span onclick="Slidoc.go('+link+');">'+pagename+'</span></li>';
	    else
		html += '<li><a href="'+link+'" %s>'+pagename+'</a></li>';
	}
	html += '</ul>\n'
    } else {
	html += '<br><a href="/'+Sliobj.params.siteName+'">'+(Sliobj.params.siteName || '&#8962;')+'</a>\n';
    }
    Slidoc.showPopup(html);
}

Slidoc.contentsDisplay = function() {
    Slidoc.log('Slidoc.contentsDisplay:');
    var prefix = '<b>Contents</b>\n';
    if (!Sliobj.params.fileName) {
	Slidoc.showPopup(prefix);
	return;
    }

    if (Sliobj.sessionName)
	prefix += '<br><b><em>'+Sliobj.sessionName+'</em></b>\n';

    if (!Sliobj.currentSlide && document.getElementById("slidoc00")) {
	Slidoc.sidebarDisplay();
	return;
    }
    var lines = [];
    lines.push('<ul class="slidoc-contents-list">');
    var allSlides = getVisibleSlides(true);
    var nVisible = getVisibleSlides().length;
    if ((Sliobj.session && Sliobj.session.paced) || Sliobj.params.paceLevel >= QUESTION_PACE)
	nVisible = Math.min(nVisible, Math.max(1,Sliobj.session.lastSlide));
    var headers = [];
    for (var j=0; j<allSlides.length; j++) {
	var hidden = (j >= nVisible) && !Sliobj.previewState;  // Do not hide any slides in preview mode
	if (hidden && !isController())  // Skip hidden slides if not adminPaced controller
	    break;
	var explicitlyHidden = allSlides[j].classList.contains('slidoc-slide-hidden');
	if (explicitlyHidden && !Sliobj.fullAccess)  // Only list expclitly hidden slides for admin
	    continue;
	var headerElems = document.getElementsByClassName(allSlides[j].id+'-header');
	var headerText = headerElems.length ? headerElems[0].textContent : '';
	if (!headerText && 'untitled_number' in Sliobj.params.features) {
	    var footerElem = getSlideFooter(allSlides[j].id);
	    if (footerElem)
		headerText = footerElem.textContent;
	}
	if (headerText || !j) {
	    // Slide with header or first slide
	    headerText = headerText || ('Slide '+(j+1));
            var action = '';
	    var classes = 'slidoc-contents-header';
	    if (explicitlyHidden) {
		classes += ' slidoc-contents-explicltlyhiddenslide';
	    } else if (hidden) {
		classes += ' slidoc-contents-hiddenslide';
		if (Sliobj.currentSlide && j+1 == Sliobj.currentSlide+1 && getUserId() == Sliobj.params.testUserId) {
		    classes += ' slidoc-contents-nextslide';
		}
	    } else {
		action = ' onclick="Slidoc.go('+"'#"+allSlides[j].id+"'"+');"';
		classes += ' slidoc-clickable';
		if (Sliobj.currentSlide && j+1 == Sliobj.currentSlide)
		    classes += ' slidoc-contents-currentslide';
	    }
	    if (Sliobj.currentSlide && j+1 == Sliobj.currentSlide+1 && getUserId() == Sliobj.params.testUserId) {
		prefix += '<p></p>Next slide: <b>'+headerText+'</b>\n';
	    }
	    lines.push('<li class="'+classes+'"' + action + '></li>');
	    headers.push(headerText);
	}
    }
    lines.push('</ul>');
    var popupContent = Slidoc.showPopup(prefix+'<hr>Slides:'+lines.join('\n'));
    var listNodes = popupContent.lastElementChild.children;
    for (var j=0; j<listNodes.length; j++)  // Insert slide header names
	listNodes[j].textContent = headers[j];
}

Slidoc.sidebarDisplay = function (elem) {
    if ((Sliobj.session && Sliobj.session.paced) || !document.getElementById("slidoc00"))
	return false;
    if (document.getElementById("slidoc-topnav"))
	return false;

    sidebarDisplayAux(!Sliobj.sidebar)
    var slides = getVisibleSlides();
    var curSlide = getCurrentlyVisibleSlide(slides);

    if (curSlide)
	goSlide('#'+slides[curSlide-1].id);
    else if (Sliobj.curChapterId && Sliobj.curChapterId != 'slidoc00')
	goSlide('#'+Sliobj.curChapterId);
    else
	goSlide('#slidoc01');
}

function sidebarDisplayAux(show) {
    if (Sliobj.session && Sliobj.session.paced)
	return false;
    var toc_elem = document.getElementById("slidoc00");
    if (!toc_elem)
	return;

    Sliobj.sidebar = show;
    toggleClass(Sliobj.sidebar, 'slidoc-sidebar-view');
    if (Sliobj.sidebar)
	toc_elem.style.display =  null;
    else if (Sliobj.curChapterId)
	toc_elem.style.display =  'none';
}

Slidoc.allDisplay = function (elem) {
    // Display all "chapters"
    if (Sliobj.session && Sliobj.session.paced)
	return false;
    Slidoc.hide(elem);
    Sliobj.showAll = !Sliobj.showAll;
    if (Sliobj.showAll) {
	Sliobj.curChapterId = '';
        document.body.classList.add('slidoc-all-view');
	var elements = document.getElementsByClassName('slidoc-container');
	for (var i=0; i < elements.length; i++)
	    elements[i].style.display= null;
    } else {
	goSlide(document.getElementById("slidoc00") ? '#slidoc00' : '#slidoc01-01', false, true);
    }
   return false;
}

Slidoc.classDisplay = function (className, displayValue) {
   // Set/toggle display value for all elements with class
    var elements = document.getElementsByClassName(className);
    for (var i=0; i < elements.length; i++) {
	if (!displayValue && displayValue !== null)
	    elements[i].style.display = (elements[i].style.display == 'none') ? null : 'none';
	else
	    elements[i].style.display = displayValue;
    }
   return false;
}

Slidoc.elemDisplay = function (elemId, displayValue) {
    // Set/toggle display value for element with id (if present)
    var elem = document.getElementById(elemId);
    if (elem) {
	if (!displayValue && displayValue !== null)
	    elem.style.display = (elem.style.display == 'none') ? null : 'none';
	else
	    elem.style.display = displayValue;
    }
   return false;
}

Slidoc.hintDisplay = function (thisElem, slide_id, qnumber, hintNumber) {
    Slidoc.log('Slidoc.hintDisplay:', thisElem, slide_id, qnumber, hintNumber);
    var prevHints = Sliobj.session.hintsUsed[qnumber] || 0;
    if (!Sliobj.session || !Sliobj.session.paced || Sliobj.params.participationCredit) {
	hintDisplayAux(slide_id, qnumber, hintNumber, prevHints);
	return;
    }
    var qAttempted = Sliobj.session.questionsAttempted[qnumber] || null;
    if (!qAttempted) // Update hints used only before answering question
	Sliobj.session.hintsUsed[qnumber] = hintNumber;

    if (!qAttempted)  // Ensure qAttempted has been saved before displaying hint
	sessionPut(null, null, {}, hintCallback.bind(null, slide_id, qnumber, hintNumber, prevHints));
}

function hintCallback(slide_id, qnumber, hintNumber, prevHints, session, feedback) {
    Slidoc.log('hintCallback:', slide_id, qnumber, hintNumber, prevHints, session, feedback);
    hintDisplayAux(slide_id, qnumber, hintNumber, prevHints);
}

function hintDisplayAux(slide_id, qnumber, hintNumber, prevHints) {
    for (var j=(prevHints||0)+1; j<=hintNumber; j++) {
	var idStr = slide_id + '-hint-' + j;
	Slidoc.classDisplay(idStr, 'block');
	var elem = document.getElementById(idStr);
	if (elem)
	    elem.classList.add('slidoc-clickable-noclick');
    }
}

Slidoc.idDisplay = function (idValue, displayValue) {
   // Set display value (string) for element with it
   // If !displayValue, toggle it
    var element = document.getElementById(idValue);
    if (displayValue)
      element.style.display = displayValue;
    else
      element.style.display = (element.style.display=='block') ? 'none' : 'block';
   return false;
}

Slidoc.toggleInlineId = function (idValue) {
   var element = document.getElementById(idValue);
   element.style.display = (element.style.display=='inline') ? 'none' : 'inline';
   return false;
}

Slidoc.toggleInline = function (elem) {
   var elements = elem.children;
   for (var i=0; i < elements.length; i++) {
      elements[i].style.display = (elements[i].style.display=='inline') ? 'none' : 'inline';
   }
   return false;
}

///////////////////////////////
// Section 17: Answering
///////////////////////////////

Slidoc.PluginRetry = function (msg) {
    Slidoc.log('Slidoc.PluginRetry:', msg);
    Sliobj.session.lastTime = Date.now();
    if (Sliobj.params.paceLevel == QUESTION_PACE) {
	document.body.classList.add('slidoc-incorrect-answer-state');
    }
    var after_str = '';
    if (Sliobj.session.tryDelay) {
	Slidoc.delayIndicator(Sliobj.session.tryDelay, slide_id+'-answer-click');
	after_str = ' after '+Sliobj.session.tryDelay+' second(s)';
    }
    Slidoc.showPopup((msg || 'Incorrect.')+'<br> Please re-attempt question'+after_str+'.<br> You have '+Sliobj.session.remainingTries+' try(s) remaining');
    return false;
}

function checkAnswerStatus(setup, slide_id, force, question_attrs, explain) {
    if (!setup && !force && Sliobj.session && Sliobj.session.paced && !Sliobj.currentSlide) {
	alert('To answer questions in paced mode, please switch to slide view (Escape key or Square icon at bottom left)');
	return false;
    }
    var textareaElem = document.getElementById(slide_id+'-answer-textarea');
    if (setup) {
	if (explain != null && textareaElem && question_attrs.explain) {
	    textareaElem.value = explain;
	    renderDisplay(slide_id, '-answer-textarea', '-response-div', !Sliobj.params.features.no_markdown);
	}
    } else if (question_attrs.explain && textareaElem && !textareaElem.value.trim() && getUserId() != Sliobj.params.testUserId) {
	if (force != 'controlled') {
	    if (!force)
		showDialog('alert', 'explainDialog', 'Please provide an explanation for the answer');
	    return false;
	}
    }
    return true;
}

Slidoc.choiceClick = function (elem, slide_id, choice_val) {
    ///Slidoc.log('Slidoc.choiceClick:', slide_id, choice_val);
    if (Slidoc.sheetIsLocked()) {
	alert(Slidoc.sheetIsLocked());
	return;
    }
    var slide_num = parseSlideId(slide_id)[2];
    var question_attrs = getQuestionAttrs(slide_id);
    if (!question_attrs || question_attrs.slide != slide_num)  // Incomplete choice question; ignore
        return false;

    var setup = !elem;
    if (setup || question_attrs.qtype == 'choice') {
	// Clear choices
	var choices = document.getElementsByClassName(slide_id+"-choice");
	for (var i=0; i < choices.length; i++)
	    choices[i].classList.remove("slidoc-choice-selected");
    }

    if (!setup) {
	if (question_attrs.qtype == 'multichoice') {
	    toggleClass(!elem.classList.contains("slidoc-choice-selected"), "slidoc-choice-selected", elem);
	} else {
	    if (Sliobj.session && Sliobj.session.submitted) {
		alert('Already submitted');
		return false;
	    }
	    
	    if (Sliobj.delayScoring && Sliobj.timedEndTime && !Sliobj.timedClose) {
		alert('Time expired');
		return false;
	    }

	    if (question_attrs.explain && allowReanswer()) {
		var textareaElem = document.getElementById(slide_id+'-answer-textarea');
		if (textareaElem && !textareaElem.value.trim() && getUserId() != Sliobj.params.testUserId) {
		    showDialog('alert', 'explainDialog', 'Please provide an explanation for the choice');
		    return false;
		}
	    }

	    elem.classList.add('slidoc-choice-selected');

	    // Immediate answer click for choice questions
	    var ansElem = document.getElementById(slide_id+'-answer-click');
	    if (ansElem && allowReanswer())
		Slidoc.answerClick(ansElem, slide_id, 'choiceclick');
	}
	if (Sliobj.session && question_attrs.team == 'setup')
	    Slidoc.sendEvent(-1, 'LiveResponse', question_attrs.qnumber, elem.dataset.choice, Sliobj.session.displayName);

    } else if (choice_val) {
	// Setup
	var choiceBlock = document.getElementById(slide_id+'-choice-block');
	var shuffleStr = choiceBlock.dataset.shuffle;
	for (var j=0; j<choice_val.length; j++) {
            var setupElem = getChoiceElem(slide_id, choice_val[j], shuffleStr);
            if (setupElem)
		setupElem.classList.add('slidoc-choice-selected');
	}
    }
    return false;
}

function getChoiceElem(slideId, choiceValue, shuffleStr) {
    var elemId = slideId+'-choice-'+choiceValue.toUpperCase();
    var choiceElem = null;
    if (shuffleStr && shuffleStr.charAt(0) != '0')  // Try alt element first
	choiceElem = document.getElementById(elemId + (parseInt(shuffleStr.charAt(0))+1) );
    if (!choiceElem)
	choiceElem = document.getElementById(elemId);
    return choiceElem;
}

function forceQuit(force, msg) {
    if (force)
	return (force != 'controlled');
    alert(msg);
    return true;
}

Slidoc.answerClick = function (elem, slide_id, force, response, explain, expect, pluginResp, qfeedback) {
    // Handle answer types: number, text
    // force: '', 'preanswer', 'postsubmit', 'finalize', 'controlled', 'choiceclick'
    // elem: null for preanswer/postsubmit
    // explain: should be defined or null for preanswer/postsubmit
    // expect: should only be defined for preanswer/postsubmit
    ///Slidoc.log('Slidoc.answerClick:', elem, slide_id, force, response, explain, expect, pluginResp, qfeedback);
    if (Slidoc.sheetIsLocked()) {
	alert(Slidoc.sheetIsLocked());
	return;
    }
    var setup = !elem;
    expect = expect || '';
    var question_attrs = getQuestionAttrs(slide_id);

    if (!checkAnswerStatus(setup, slide_id, force, question_attrs, explain))
	return false;
    if (setup) {
        elem = document.getElementById(slide_id+"-answer-click");
	if (!elem) {
	    Slidoc.log('Slidoc.answerClick: Error - Setup failed for '+slide_id);
	    return false;
	}
       if (qfeedback) {
	   if ('grade' in qfeedback && qfeedback.grade != null) {
	       setAnswerElement(slide_id, "-grade-input", ''+qfeedback.grade);
	       setAnswerElement(slide_id, "-grade-content", ''+qfeedback.grade);
	   }

	   if ('comments' in qfeedback && qfeedback.comments != null) {
	       setAnswerElement(slide_id, "-comments-textarea", qfeedback.comments);
	       setAnswerElement(slide_id, "-comments-content", qfeedback.comments);
	       renderDisplay(slide_id, '-comments-textarea', '-comments-content', true);
	   }
       }
   } else {
       // Not setup
	if (!Slidoc.answerPacedAllow())
	    return false;
       response = '';
    }

    var qtypeMatch = QTYPE_RE.exec(question_attrs.qtype);
    var formulaMatch = FORMULA_RE.exec(question_attrs.correct || '');
    var format = '';
    if (qtypeMatch && qtypeMatch[2]) {
	// Response plugin
	var pluginName = qtypeMatch[1];
	var responded = true;
	if (setup) {
	    Slidoc.PluginMethod(pluginName, slide_id, 'display', response, pluginResp);
	    Slidoc.answerUpdate(setup, slide_id, expect, response, pluginResp);
	} else {
	    responded = Slidoc.PluginMethod(pluginName, slide_id, 'response',
			                    (Sliobj.session.remainingTries > 0),
			 	            Slidoc.answerUpdate.bind(null, setup, slide_id, expect));
	    if (responded && Sliobj.session.remainingTries > 0)
		Sliobj.session.remainingTries -= 1;
	}
	if (responded && (setup || !Sliobj.session || !Sliobj.session.paced || !Sliobj.session.remainingTries))
	    Slidoc.PluginManager.disable(pluginName, slide_id)

	return false;
    } else if (formulaMatch) {
	var formula = formulaMatch[2];
	format = formulaMatch[4] || '';
	var val = Slidoc.PluginMethod('Params', slide_id, 'formula', formula);
	if (val != null) {
	    expect = formatNum(format, val);
	} else {
	    expect = formulaMatch[1].trim();
	}
    }

    if (expect.indexOf('+/-') < 0 && format && format.indexOf('+/-') >= 0) {
	var comps = format.split('+/-');
	format = comps[0];
	expect += '+/-' + comps[1].replace('*10**','e').replace('(','').replace(')','');
    }

    if (question_attrs.qtype.slice(-6) == 'choice') {
	// Choice/Multichoice
	var choices = document.getElementsByClassName(slide_id+"-choice");
	if (setup) {
	    Slidoc.choiceClick(null, slide_id, response);
	} else {
	    response = '';
	    for (var i=0; i < choices.length; i++) {
		if (choices[i].classList.contains("slidoc-choice-selected"))
		    response += choices[i].dataset.choice;
	    }

	    if (Sliobj.session.remainingTries > 0)
		Sliobj.session.remainingTries = 0;   // Only one try for choice response
	}
	    
	// Allow further choice clicking if multi-choice, or choice and preanswer/choiceclick
	var allowChoice = (question_attrs.qtype == 'multichoice') || (force && (force == 'preanswer' || force == 'choiceclick'));
	if (!allowChoice || !allowReanswer() || (Sliobj.session && Sliobj.session.submitted)) {
	    // If not further choice, or no re-answers, or submitted, disable choice clicking
	    for (var i=0; i < choices.length; i++) {
		choices[i].removeAttribute("onclick");
		choices[i].classList.remove("slidoc-clickable");
	    }
	}

	var corr_answer = expect || question_attrs.correct || '';
	if (corr_answer  && corr_answer.indexOf('=') < 0 && displayCorrect(question_attrs)) {
	    var choiceBlock = document.getElementById(slide_id+'-choice-block');
	    var shuffleStr = choiceBlock.dataset.shuffle;
	    for (var j=0; j<corr_answer.length; j++) {
		var corr_choice = getChoiceElem(slide_id, corr_answer[j], shuffleStr);
		if (corr_choice) {
		    // Highlight correct choice only if selected (for pre-quiz)
		    if (!(question_attrs.disabled == 'choice') || corr_choice.classList.contains('slidoc-choice-selected')) {
			corr_choice.style['font-weight'] = 'bold';
			corr_choice.style['color'] = 'green';
		    }
		}
	    }
	}
	if (question_attrs.explain) {
	    var explainElem = document.getElementById(slide_id+'-answer-textarea');
	    if (explainElem && !allowReanswer())
		explainElem.disabled = 'disabled';
	}
    }  else {
	var multiline = question_attrs.qtype.match(/^(text|Code)\//);
	var inpElem = document.getElementById(multiline ? slide_id+'-answer-textarea' : slide_id+'-answer-input');
	if (inpElem) {
	    if (setup) {
		inpElem.value = response;
	    } else {
		response = inpElem.value.trim();
		if (question_attrs.qtype == 'number' && !isNumber(response)) {
		    if (forceQuit(force, 'Expecting a numeric value as answer'))
			return false;
		    response = '';
		} else if (Sliobj.session && Sliobj.session.paced) {
		    if (!response) {
			if (forceQuit(force, 'Expecting a non-null answer'))
			    return false;
			response = '';
		    } else if (Sliobj.session && Sliobj.session.paced && Sliobj.lastInputValue && Sliobj.lastInputValue == response) {
			if (forceQuit(force, 'Please try a different answer this time!'))
			    return false;
		    }
		    Sliobj.lastInputValue = response;
		}
		if (Sliobj.session.remainingTries > 0)
		    Sliobj.session.remainingTries -= 1;
	    }
	    if (setup || !Sliobj.session || !Sliobj.session.paced || !Sliobj.session.remainingTries) {
		if (!allowReanswer())
		    inpElem.disabled = 'disabled';
		if (!multiline)
		    inpElem.value = '';
	    }
	}

    }

    Slidoc.answerUpdate(setup, slide_id, expect, response);
    return false;
}

Slidoc.answerUpdate = function (setup, slide_id, expect, response, pluginResp) {
    // PluginResp: name:'...', score:1/0/null, correctAnswer: 'correct_ans',
    //  invalid: 'invalid_msg', output:'output', tests:0/1/2} The last three are for code execution
    ///Slidoc.log('Slidoc.answerUpdate: ', setup, slide_id, expect, response, pluginResp);
    expect = expect || '';

    if (!setup && Sliobj.session && Sliobj.session.paced)
	Sliobj.session.lastTries += 1;

    var question_attrs = getQuestionAttrs(slide_id);

    var corr_answer      = expect || question_attrs.correct || '';
    var corr_answer_html = expect ? expect : (question_attrs.correct_html || '');
    var dispCorrect = displayCorrect(question_attrs);

    var qscore = null;
    if (pluginResp) {
	qscore = parseNumber(pluginResp.score);
	if (pluginResp.correctAnswer != null)
	    expect = pluginResp.correctAnswer+'';
    } else {
	// Check response against correct answer
	qscore = scoreAnswer(response, question_attrs.qtype, corr_answer);
    }
    if (!setup && isNumber(qscore) && qscore < 1 && Sliobj.session.remainingTries > 0) {
	sessionPut();  // Save try count
	Slidoc.PluginRetry();
	return false;
    }

    // Handle randomized choices
    var disp_response = response;
    var disp_corr_answer = corr_answer;
    var disp_corr_answer_html = corr_answer_html;
    var shuffleStr = '';
    if (question_attrs.qtype == 'choice' || question_attrs.qtype == 'multichoice') {
	var choiceBlock = document.getElementById(slide_id+'-choice-block');
	shuffleStr = choiceBlock.dataset.shuffle;
	if (shuffleStr) {
	    disp_response = choiceShuffle(disp_response, shuffleStr);
	    disp_corr_answer = choiceShuffle(disp_corr_answer, shuffleStr);
	    disp_corr_answer_html = disp_corr_answer;
	}
    } else if (disp_corr_answer.match(/=\w+\.response\(\s*(\d*)\s*\)/)) {
	disp_corr_answer = '';
    }

    // Display correctness of response
    if (dispCorrect) {
	setAnswerElement(slide_id, '-correct-mark', '', qscore === 1 ? ' '+SYMS['correctMark']+'&nbsp;' : '');
	setAnswerElement(slide_id, '-partcorrect-mark', '', (isNumber(qscore) && qscore > 0 && qscore < 1) ? ' '+SYMS['partcorrectMark']+'&nbsp;' : '');
	setAnswerElement(slide_id, '-wrong-mark', '', (qscore === 0) ? ' '+SYMS['wrongMark']+'&nbsp;' : '');
	setAnswerElement(slide_id, '-any-mark', '', !isNumber(qscore) ? '<b>'+SYMS['anyMark']+'</b>' : '');  // Not check mark
    
	// Display correct answer
	setAnswerElement(slide_id, "-answer-correct", disp_corr_answer||'', disp_corr_answer_html);
    }

    var notes_id = slide_id+"-notes";
    var notes_elem = document.getElementById(notes_id);
    if (notes_elem && dispCorrect) {
	// Display of any notes associated with this question
	if (question_attrs.qtype == 'choice') {
	    // Display choice notes
	    var idPrefix = slide_id+'-choice-notes-';
	    var selAlternative = shuffleStr ? (parseInt(shuffleStr.charAt(0)) || 0) : 0;
	    var altSuffix = selAlternative ? (''+(selAlternative+1)) : '';
	    if (selAlternative && document.getElementById(idPrefix+'Q'+altSuffix))
		Slidoc.elemDisplay(idPrefix+'Q'+altSuffix, 'block');
	    else
		Slidoc.elemDisplay(idPrefix+'Q', 'block');

	    if (response) {
		var choiceSuffix = response.toUpperCase();
		var choiceIndex = 1 + choiceSuffix.charCodeAt(0) - 'A'.charCodeAt(0);
		if (choiceIndex > 0) {
		    // Display choice notes

		    // Display alternate notes, if present
		    if (selAlternative && document.getElementById(idPrefix+choiceSuffix+altSuffix))
			Slidoc.elemDisplay(idPrefix+choiceSuffix+altSuffix, 'block');
		    else
			Slidoc.elemDisplay(idPrefix+choiceSuffix, 'block');

		    // Redisplay choiceNotes JS
		    // defining function 'choiceNotes: function(n) {..}' in a plugin allows choice-dependent notes display
		    // (Negative n for alt choice; only works single alternative currently)
		    var elems = document.getElementsByClassName(notes_id);
		    for (var j=0; j<elems.length; j++)
			expandInlineJS(elems[j], 'choiceNotes', (selAlternative ? -choiceIndex : choiceIndex));
		}
	    }
	}
	Slidoc.idDisplay(notes_id);
	notes_elem.style.display = 'inline';
	Slidoc.classDisplay(notes_id, 'block');
	var ansContainer = document.getElementById(slide_id+"-answer-container");
	if (ansContainer)
	    ansContainer.scrollIntoView(true)
    }

    // Switch to answered slide view if not printing exam
    var slideElem = document.getElementById(slide_id);
    if (!Sliobj.assessmentView)
	slideElem.classList.add('slidoc-answered-slideview');

    if (pluginResp)
	Slidoc.PluginManager.disable(pluginResp.name, slide_id, dispCorrect && qscore !== 1);

    // Render text/Code/explanation
    if (question_attrs.qtype.match(/^(text|Code)\//)) {
	renderDisplay(slide_id, '-answer-textarea', '-response-div', usingMarkdown(question_attrs.qtype) && !Sliobj.params.features.no_markdown);
    } else {
	if (question_attrs.explain)
	    renderDisplay(slide_id, '-answer-textarea', '-response-div', !Sliobj.params.features.no_markdown);
	setAnswerElement(slide_id, '-response-span', disp_response);
    }

    if (setup || Sliobj.session.submitted)
	return;

    // Not setup or after submit
    var prevSkipToSlide = Sliobj.scores ? (Sliobj.scores.skipToSlide || 0) : 0;

    // Record attempt and tally up scores
    var explain = '';
    if (question_attrs.explain) {
	var textareaElem = document.getElementById(slide_id+'-answer-textarea');
	explain = textareaElem.value;
    }

    // Save attempt info
    var qAttempted = createQuestionAttempted(response);
    if (explain)
	qAttempted.explain = explain;
    if (pluginResp)
	qAttempted.plugin = pluginResp;
    if (expect)
	qAttempted.expect = expect;
    if (Sliobj.session.lastTries > 1)
	qAttempted.retries = Sliobj.session.lastTries-1;

    Sliobj.session.questionsAttempted[question_attrs.qnumber] = qAttempted;

    // Score newly attempted question (and all others)
    scoreSession(Sliobj.session);

    // Copy non-authoritative score
    if (Sliobj.scores.qscores[question_attrs.qnumber-1] != null)
	Sliobj.session.questionsAttempted[question_attrs.qnumber].temscore = Sliobj.scores.qscores[question_attrs.qnumber-1]

    var slide_num = parseSlideId(slide_id)[2];
    var qnumber = question_attrs.qnumber;

    if (slide_num < prevSkipToSlide) {
	Slidoc.reportTestAction('answerSkip');
    } else {
	toggleClassAll(true, 'slidoc-forward-link-allowed', Sliobj.scores.lastSkipRef);

	if (Sliobj.session && Sliobj.session.paced) {
	    Sliobj.session.remainingTries = 0;
	    document.body.classList.remove('slidoc-expect-answer-state');
	    
	    if ('skip_ahead' in Sliobj.params.features && Sliobj.params.paceLevel == QUESTION_PACE && !Sliobj.scores.correctSequence) 
		document.body.classList.add('slidoc-incorrect-answer-state');
	}

	Slidoc.showScore();
	Slidoc.reportTestAction('answerTally');
    }
    saveSessionAnswered(slide_id, question_attrs);
}

function saveSessionAnswered(slide_id, qattrs) {
    Slidoc.log('saveSessionAnswered:', slide_id);
    if (!Sliobj.session.paced || Sliobj.session.submitted)
	return;
    Sliobj.session.lastTime = Date.now();
    if (isController()) {
	if (Sliobj.interactiveSlide)
	    enableInteract(false);
	Slidoc.sendEvent(-1, 'AdminPacedForceAnswer', qattrs.qnumber, slide_id);

    } else if (!Sliobj.delaySec && Sliobj.params.slideDelay && MIN_ANSWER_NOTES_DELAY && allowDelay()) {
	// Minimum delay to view notes after answering
	var notes_elem = document.getElementById(slide_id+"-notes");
	if (notes_elem && displayCorrect(qattrs)) {
	    Sliobj.delaySec = Math.min(MIN_ANSWER_NOTES_DELAY, Sliobj.params.slideDelay);
	    Slidoc.delayIndicator(Sliobj.delaySec, 'slidoc-slide-nav-prev', 'slidoc-slide-nav-next');
	}
    }
    // Save session
    sessionPut(null, null, {}, slide_id ? saveCallback.bind(null, slide_id, qattrs||null) : null);
}

function saveCallback(slide_id, qattrs, session, feedback) {
    Slidoc.log('saveCallback:', slide_id, qattrs, session, feedback);
    if (slide_id in Sliobj.answerPlugins)
	Slidoc.PluginManager.invoke(Sliobj.answerPlugins[slide_id], 'answerSave');
}

Slidoc.showScore = function () {
    var scoreElem = document.getElementById('slidoc-score-display');
    if (!scoreElem)
	return;
    if (Sliobj.params.questionsMax) {
	if (controlledPace())
	    scoreElem.textContent = Sliobj.scores.questionsCount;
	else if (Sliobj.scores.questionsCount && Sliobj.session.submitted && Sliobj.params.totalWeight == Sliobj.params.scoreWeight && !displayAfterGrading())
	    scoreElem.textContent = flexFixed(Sliobj.scores.weightedCorrect)+' ('+Sliobj.params.scoreWeight+')';
	else
	    scoreElem.textContent = Sliobj.scores.questionsCount+'/'+(Sliobj.params.questionsMax-Sliobj.params.disabledCount);
    } else {
	scoreElem.textContent = '';
    }
}


function usingMarkdown(qtype) {
    if (!qtype)
	return false;
    if (qtype.match(/^Code\//) || qtype.match(/^text\/x-code/))  // Code => no markdown
	return false;
    return qtype.match(/^text\//);   // Text type => markdown
}

function renderDisplay(slide_id, inputSuffix, renderSuffix, renderMarkdown) {
    Slidoc.log("renderDisplay:", slide_id, inputSuffix, renderSuffix, renderMarkdown);
    if (!(inputSuffix in Sliobj.params.answer_elements)) {
	Slidoc.log("renderDisplay: ERROR Invalid suffix '"+inputSuffix+"'");
	return false;
    }
    var inputElem = document.getElementById(slide_id+inputSuffix)
    if (!inputElem) {
	Slidoc.log("renderDisplay: ERROR Element '"+slide_id+inputSuffix+"' not found!");
	return false;
    }

    if (!(renderSuffix in Sliobj.params.answer_elements)) {
	Slidoc.log("renderDisplay: ERROR Invalid suffix '"+renderSuffix+"'");
	return false;
    }
    var renderElem = document.getElementById(slide_id+renderSuffix)
    if (!renderElem) {
	Slidoc.log("renderDisplay: ERROR Element '"+slide_id+renderSuffix+"' not found!");
	return false;
    }

    var textValue = inputElem.value;
    if (textValue && renderMarkdown) {
	renderElem.innerHTML = MDConverter(textValue, true);
	if (window.MathJax)
	    MathJax.Hub.Queue(["Typeset", MathJax.Hub, renderElem.id]);
    } else {
	renderElem.textContent = textValue;
    }
}
    
Slidoc.renderText = function(elem, slide_id) {
    Slidoc.log("Slidoc.renderText:", elem, slide_id);
    if (!slide_id) {
	renderDisplay('slidoc-remarks', '-comments-textarea', '-comments-content', true);
    } else {
	var question_attrs = getQuestionAttrs(slide_id);
	if (Sliobj.gradableState) {
	    renderDisplay(slide_id, '-comments-textarea', '-comments-content', true);
	} else {
	    if (question_attrs.explain) {
		renderDisplay(slide_id, '-answer-textarea', '-response-div', !Sliobj.params.features.no_markdown)
	    } else {
		renderDisplay(slide_id, '-answer-textarea', '-response-div', usingMarkdown(question_attrs.qtype) && !Sliobj.params.features.no_markdown);
	    }
	}
    }
}

////////////////////////////
// Section 17b: Answering2
////////////////////////////


function scoreAnswer(response, qtype, corrAnswer) {
    // Handle answer types: choice, number, text
    // Returns null (unscored), or 0..1
    ///Slidoc.log('Slidoc.scoreAnswer:', response, qtype, corrAnswer);

    if (!corrAnswer)
        return null;

    if (!response)
	return 0;

    var respValue = null;

    // Check response against correct answer
    var qscore = 0;
    if (qtype == 'number') {
        // Check if numeric answer is correct
        respValue = parseNumber(response);
	var corrComps = Slidoc.PluginManager.splitNumericAnswer(corrAnswer);

        if (respValue != null && corrComps[0] != null && corrComps[1] != null) {
            qscore = (Math.abs(respValue-corrComps[0]) <= 1.001*corrComps[1]) ? 1 : 0;
        } else if (corrComps[0] == null) {
            qscore = null;
	    if (corrAnswer)
		Slidoc.log('Slidoc.scoreAnswer: Error in correct numeric answer:'+corrAnswer);
        } else if (corrComps[1] == null) {
            qscore = null;
            Slidoc.log('Slidoc.scoreAnswer: Error in correct numeric error:'+corrAnswer);
        }
    } else {
        // Check if non-numeric answer is correct (all spaces are removed before comparison)
        var normResp = response.trim().toLowerCase();
	// For choice, allow multiple correct answers (to fix grading problems)
	var correctOptions = (qtype == 'choice') ? corrAnswer.split('') : corrAnswer.split(' OR ');
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

function tallyScores(questions, questionsAttempted, hintsUsed, params, remoteAnswers) {
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
        var slideNum = questionAttrs.slide;
        if (!qAttempted || slideNum < skipToSlide) {
            // Unattempted or skipped
            qscores.push(null);
            continue;
        }

	if (qAttempted.plugin) {
	    var qscore = parseNumber(qAttempted.plugin.score);
	} else {
	    var correctAns = qAttempted.expect || questionAttrs.correct || '';
            if (!correctAns && remoteAnswers && remoteAnswers.length)
		correctAns = remoteAnswers[qnumber-1];

            var qscore = scoreAnswer(qAttempted.response, questionAttrs.qtype, correctAns);
	}

        qscores.push(qscore);
        var qSkipCount = 0;
        var qSkipWeight = 0;

        // Check for skipped questions
        if (skipAhead && qscore == 1 && !hintsUsed[qnumber] && !qAttempted.retries) {
            // Correct answer (without hints and retries)
            if (slideNum > prevQuestionSlide+1) {
                // Question not part of sequence
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

        lastSkipRef = '';
        if (correctSequence && params.paceLevel == QUESTION_PACE) {
            var skip = questionAttrs.skip;
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
        questionsSkipped += qSkipCount;
        questionsCount += 1 + qSkipCount;
        weightedCount += qWeight + qSkipWeight;

        var effectiveScore = (parseNumber(qscore) != null) ? qscore : 1;   // Give full credit to unscored answers

        if (params.participationCredit) {
            // Full participation credit simply for attempting question (lateCredit applied in sheet)
            effectiveScore = 1;

        } else if (hintsUsed[qnumber] && questionAttrs.hints && questionAttrs.hints.length) {
	    if (hintsUsed[qnumber] > questionAttrs.hints.length)
		alert('Internal Error: Inconsistent hint count');
	    for (var k=0; k<hintsUsed[qnumber]; k++)
		effectiveScore -= Math.abs(questionAttrs.hints[k]);
	}

	if (questionAttrs.participation)  // Minimum (normalized) score for attempting question
	    effectiveScore = Math.max(effectiveScore, questionAttrs.participation);
	
        if (effectiveScore > 0) {
            questionsCorrect += 1 + qSkipCount;
            weightedCorrect += effectiveScore*qWeight + qSkipWeight;
        }
    }

    return { 'questionsCount': questionsCount, 'weightedCount': weightedCount,
             'questionsCorrect': questionsCorrect, 'weightedCorrect': weightedCorrect,
             'questionsSkipped': questionsSkipped, 'correctSequence': correctSequence, 'skipToSlide': skipToSlide,
             'correctSequence': correctSequence, 'lastSkipRef': lastSkipRef, 'qscores': qscores};
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
	if (qscores[qnumber-1] === null || !qConcepts.length || (!qConcepts[0].length && !qConcepts[1].length))
	    continue;
	var missed = qscores[qnumber-1] < 1;

	for (var m=0; m<2; m++) {
            // Primary/secondary concept
	    for (var j=0; j<qConcepts[m].length; j++) {
		for (var k=0; k < allQuestionConcepts[m].length; k++) {
		    if (qConcepts[m][j] == allQuestionConcepts[m][k]) {
			if (missed)
			    missedConcepts[m][k][0] += 1;    // Missed count
			missedConcepts[m][k][1] += 1;        // Attempted count
		    }
		}
	    }
	}
    }
    return missedConcepts;
}

//////////////////////////
// Section 18: Grading
//////////////////////////

function showSubmitted() {
    toggleClass(!!(Sliobj.session && Sliobj.session.submitted), 'slidoc-submitted-view');

    var submitElem = document.getElementById('slidoc-submit-display');
    if (!submitElem || !Sliobj.params.gd_sheet_url)
	return;
    if (Sliobj.session && Sliobj.session.submitted && Sliobj.session.submitted != 'GRADING') {
	submitElem.innerHTML = (Sliobj.session.lateToken == LATE_SUBMIT) ? 'Submitted late' : 'Submitted';
    } else if (Sliobj.session && (Sliobj.session.paced || Sliobj.session.submitted == 'GRADING')) {
	submitElem.innerHTML = Sliobj.gradableState ? 'Unsubmitted' : ((Sliobj.session.lateToken == LATE_SUBMIT) ? 'Submit late' : 'Submit');
    } else {
	submitElem.innerHTML = '';
    }
}

Slidoc.responseTable = function () {
    Slidoc.log('responseTable:');
    var firstSlideId = getVisibleSlides()[0].id;
    var attr_vals = getChapterAttrs(firstSlideId);
    var chapter_id = parseSlideId(firstSlideId)[0];
    var html = '<b>Responses for session '+Sliobj.sessionName+'</b>';
    html += '<br><em>user:</em> '+getUserId();
    if (Sliobj.session.submitted)
	html += '<br><em>Submitted:</em> '+parseDate(Sliobj.session.submitted);
    html += '<p></p><pre><table class="slidoc-slide-help-table"><tr>';
    
    for (var j=0; j<attr_vals.length; j++) {
	var question_attrs = attr_vals[j];
	var qnumber = j+1;
	var question_attrs = attr_vals[qnumber-1];
	var qAttempted = Sliobj.session.questionsAttempted[qnumber];
	html += '<td>' + zeroPad(qnumber,2) + '. ';
	if (!qAttempted) {
	    // No response
	} else if (question_attrs.qtype == 'choice') {
	    var slide_id = chapter_id + '-' + zeroPad(question_attrs.slide, 2);
	    var shuffleStr = Sliobj.session.questionShuffle[qnumber] || '';
	    var choice = (qAttempted.response && shuffleStr) ? choiceShuffle(qAttempted.response, shuffleStr): qAttempted.response;
	    html += '<b>' + choice + '</b>';
	} else if (question_attrs.qtype == 'number') {
	    html += qAttempted.response;
	} else if (qAttempted.response) {
	    html += '*';
	}
	html += '</td>';
	if (!(qnumber % 5)) {
	    html += '</tr><tr>';
	}
	if (!(qnumber % 20)) {
	    html += '</tr><td>&nbsp;</td><tr>';
	}
    }
    html += '</tr></table></pre>';

    html += '<br><em>Seed:</em> '+Sliobj.session.randomSeed;
    if (Sliobj.lockedView)
	html += '<p></p><span class="slidoc-clickable" onclick="Android.printPage();">Print</span>';
    else
	html += '<p></p><span class="slidoc-clickable" onclick="window.print();">Print</span>';
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    Slidoc.showPopup(html, null, 'printable');
}

Slidoc.submitStatus = function () {
    Slidoc.log('Slidoc.submitStatus: ');
    var html = '<b>Submit status</b><p></p>\n';
    if (Sliobj.session.submitted) {
	html += 'User '+GService.gprofile.auth.id+' submitted session to Google Docs on '+ parseDate(Sliobj.session.submitted);
	if (Sliobj.session.lateToken == LATE_SUBMIT)
	    html += ' (LATE)';
    } else {
	html += 'Session not submitted.'
	if (!Sliobj.gradableState) {
	    var incomplete = Sliobj.session.lastSlide < getVisibleSlides().length;
	    html += '<ul>';
	    if (incomplete)
		html += '<li><span class="slidoc-clickable" onclick="Slidoc.saveClick();">Save session</span></li><p></p>'
	    html += '<li><span class="slidoc-clickable" onclick="Slidoc.submitClick();">Submit session</span>'+(incomplete ? ' (without reaching the last slide)':'')+'</li>'
	    html += '</ul>';
	    if (Sliobj.dueDate)
		html += 'Due: <em>'+Sliobj.dueDate+'</em><br>';
	    if (Sliobj.session && Sliobj.params.maxRetakes && !Sliobj.params.timedSec) {
		html += 'Retakes remaining: <code>'+retakesRemaining()+'</code><br>';
		if (retakesRemaining())
		    html += '<span class="slidoc-clickable" onclick="Slidoc.resetPaced();">Reset paced session for re-takes</span><br>'
	    }
	}
    }
    if (Sliobj.session && Object.keys(Sliobj.session.questionsAttempted).length)
	html += '<p></p><span class="slidoc-clickable" onclick="Slidoc.responseTable();">Table of responses</span>';

    if (Sliobj.gradableState || getUserId() == Sliobj.params.testUserId) {
	var userId = getUserId() || '';
	if (!Sliobj.gradableState)
	    userId = '';
        var disabled = (!Sliobj.currentSlide || !Sliobj.questionSlide || !userId);
	html += '<p></p>' + clickableSpan('Reset '+(userId?'user':'ALL')+' responses to current question',
			  	       "Slidoc.resetQuestion('"+"'"+userId+"'"+"');", disabled) + '<br>';
	html += '<p></p>' + clickableSpan('Rollback interactive portion of session',
	  	  		          "Slidoc.rollbackInteractive();", !(Sliobj.interactiveSlide && Sliobj.params.features.rollback_interact)) + '<br>';
    }

    if (Sliobj.session.submitted || Sliobj.gradableState)
	html += '<br><span class="slidoc-clickable" onclick="Slidoc.uploadFile();">Late file upload</span>';

    if (Sliobj.gradableState) {
	if (Sliobj.session.submitted && Sliobj.session.submitted != 'GRADING') {
	    html += '<hr><span class="slidoc-clickable" onclick="Slidoc.forceSubmit(false);">Unsubmit session for user (and clear late token)</span>';
	} else {
	    html += '<hr><span class="slidoc-clickable" onclick="Slidoc.forceSubmit(true);">Force submit session for user</span><br>';
	}
	html += '<hr><span class="slidoc-clickable" onclick="Slidoc.forceSubmitAll(true);">Force submit session for ALL users</span>';
	html += '<hr><span class="slidoc-clickable" onclick="Slidoc.forceSubmitAll(false);">Unsubmit session for ALL users (and clear late token)</span>';

	if (Sliobj.gradeDateStr) {
	    html += '<hr>Grades released to students at '+Sliobj.gradeDateStr;
	    html += '<hr><span class="slidoc-clickable" onclick="Slidoc.releaseGrades('+"'undo'"+');">Unrelease grades to students</span>';
	} else {
	    html += '<hr><span class="slidoc-clickable" onclick="Slidoc.releaseGrades();">Release grades to students</span>';
	}
    }
    Slidoc.showPopup(html);
}

Slidoc.forceSubmitAll = function(submitAction) {
    var modIds = [];
    for (var j=0; j<Sliobj.userList.length; j++) {
	var userId = Sliobj.userList[j];
	var submitted = Sliobj.userGrades[userId].submitted && Sliobj.userGrades[userId].submitted != 'GRADING';
	if (submitAction && !submitted)
	    modIds.push(userId);
	else if (!submitAction && submitted)
	    modIds.push(userId);
    }
    if (!modIds.length) {
	alert('No '+(submitAction?'unsubmitted':'submitted') +' users!');
	return;
    }

    if (!submitAction && Slidoc.PluginManager.pastDueDate()) {
	alert('Cannot unsubmit when there may be past due entries (due to auto-submission for grading). Please remove/change session due date');
	return;
    }
	
    if (!window.confirm('Force '+(submitAction?'submit':'unsubmit')+' for '+modIds.length+' users: '+modIds.join(',')))
	return;
    var remainingCount = modIds.length;
    var errorCount = 0;
    var pendingElem = document.getElementById("slidoc-pending-display");
    if (pendingElem)
	pendingElem.textContent = 'Remaining '+remainingCount;
    function forceSubmitAllCallback(result, retStatus) {
	remainingCount -= 1;
	var msg = 'Remaining '+remainingCount;
	if (!result)
	    errorCount += 1;
	if (!errorCount)
	    msg += ' ('+errorCount+' errors)';
	if (pendingElem)
	    pendingElem.textContent = msg;
	if (!remainingCount) {
	    sessionReload('Reload after completing force submit/unsubmit'+(errorCount ? ' ('+errorCount+' errors)': '')+'?');
	}
    }
    var gsheet = getSheet(Sliobj.sessionName);
    for (var j=0; j<modIds.length; j++)
	gsheet.updateRow({id: modIds[j], submitTimestamp: (submitAction ? null : '')}, {}, forceSubmitAllCallback);
}

Slidoc.forceSubmit = function(submit) {
    var userId = getUserId();
    var name = (Sliobj.userGrades && Sliobj.userGrades[userId]) ? Sliobj.userGrades[userId].name : userId;
    var msg = submit ? 'Force submission of session for '+name : 'Unsubmit session for '+name;
    if (!window.confirm(msg+'?'))
	return;
    var gsheet = getSheet(Sliobj.sessionName);
    var updates = {id: userId};
    updates.submitTimestamp = submit ? null : '';
    gsheet.updateRow(updates, {}, forceSubmitCallback);
}

function forceSubmitCallback() {
    sessionReload('Submit status changed. Reload page to restart?');
}

Slidoc.saveClick = function() {
    Slidoc.log('Slidoc.saveClick:');
    sessionPut(null, null, {}, saveClickCallback);
}

function saveClickCallback(session, feedback) {
    Slidoc.log('Slidoc.saveClickCallback:', session, feedback);
}
	
Slidoc.submitClick = function(elem, noFinalize, force) {
    // Submit session after finalizing answers with checked choices and entered input values
    Slidoc.log('Slidoc.submitClick:', elem, noFinalize, force);
    if (Sliobj.closePopup)
	Sliobj.closePopup();

    if (!Sliobj.session || !Sliobj.session.paced || Sliobj.session.submitted) {
	if (!force)
	    alert('Session appears to be already submitted');
	return;
    }

    if (controlledPace() && !Sliobj.dueDate) {
	alert('Cannot submit active instructor-paced session');
	return;
    }

    var prompt = '';
    if (Sliobj.scores.questionsCount < Sliobj.params.questionsMax)
	prompt = 'You have only answered '+Sliobj.scores.questionsCount+' of '+Sliobj.params.questionsMax+' questions. Do you wish to proceed with submission?'

    var finalize_answers = [];
    if (prompt && !noFinalize) {
	// Check for selected, but not finalized, answers
	var firstSlideId = getVisibleSlides()[0].id;
	var chapter_id = parseSlideId(firstSlideId)[0];
	var attr_vals = getChapterAttrs(firstSlideId);

	var unanswered = 0;
	for (var qnumber=1; qnumber <= attr_vals.length; qnumber++) {
	    var question_attrs = attr_vals[qnumber-1];
	    var slide_id = chapter_id + '-' + zeroPad(question_attrs.slide, 2);
	    if (qnumber in Sliobj.session.questionsAttempted)
		continue

	    // Unattempted question
	    var response = '';
	    var qtypeMatch = QTYPE_RE.exec(question_attrs.qtype);
	    if (qtypeMatch && qtypeMatch[2]) {
		// Response plugin
		response = responseAvailable(Sliobj.session, qnumber);
	    } else if (question_attrs.qtype.slice(-6) == 'choice') {
		var choices = document.getElementsByClassName(slide_id+"-choice");
	    	for (var i=0; i < choices.length; i++) {
		    if (choices[i].classList.contains("slidoc-choice-selected"))
			response += choices[i].dataset.choice;
		}
	    } else {
		var multiline = question_attrs.qtype.match(/^(text|Code)\//);
		var inpElem = document.getElementById(multiline ? slide_id+'-answer-textarea' : slide_id+'-answer-input');
		if (inpElem)
		    response = inpElem.value.trim();
	    }
	    var textareaElem = document.getElementById(slide_id+'-answer-textarea');
	    var ansElem = document.getElementById(slide_id+'-answer-click');
	    if (question_attrs.explain && textareaElem && !textareaElem.value.trim())
		// No explanation provided; ignore response
		response = ''
	    if (response && ansElem)
		finalize_answers.push([ansElem, slide_id]);
	    else
		unanswered += 1;
	}
	if (unanswered && unanswered > Sliobj.params.disabledCount)
	    prompt = 'There are '+(unanswered-Sliobj.params.disabledCount)+' unanswered questions. Do you still wish to proceed with submission?';
	else
	    prompt = '';
    }

    if (!force && prompt) {
	if (!showDialog('confirm', 'submitDialog', prompt))
	    return;
    }

    for (var j=0; j<finalize_answers.length; j++)
	Slidoc.answerClick(finalize_answers[j][0], finalize_answers[j][1], 'finalize');

    Slidoc.endPaced();

    var submitElems = document.getElementsByClassName('slidoc-plugin-Submit-button');
    for (var j=0; j<submitElems.length; j++)
	submitElems[j].disabled = 'disabled';
}

Slidoc.releaseGrades = function (undo) {
    Slidoc.log('Slidoc.releaseGrades: ', undo);
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    if (!window.confirm('Confirm '+(undo?'UNRELEASING':'releasing')+' grades to students?'))
	return;
    
    var updates = {id: Sliobj.sessionName, gradeDate: (undo ? '':(new Date())) };
    Sliobj.indexSheet.updateRow(updates, {}, releaseGradesCallback.bind(null, (undo ? '': Slidoc.toLocalISOString(updates.gradeDate)) ));
}

function releaseGradesCallback(gradeDateStr, result, retStatus) {
    Slidoc.log('releaseGradesCallback:', gradeDateStr, result, retStatus);
    if (result) {
	Sliobj.gradeDateStr = gradeDateStr;
	if (gradeDateStr) {
	    var msg = 'Grade Date updated in index sheet '+Sliobj.params.index_sheet+' to release grades to students.';

	    if (Sliobj.params.features.share_answers) {
		msg += ' Answer stats being updated.';
		Slidoc.sessionActions('answer_stats', '', true);
	    }
		
	    if (Slidoc.siteCookie.gradebook) {
		if (window.confirm(msg+' Also copy grades to gradebook?'))
		    Slidoc.sessionActions('gradebook');
	    } else {
		alert(msg);
	    }
	} else {
	    alert('Unreleased grades');
	}

    } else {
	alert('Error: Failed to update Grade Date in index sheet '+Sliobj.params.index_sheet+'; grades not released to students ('+retStatus.error+')');
    }
}

function conceptStats(tags, tallies) {
    var tagTallies = [];
    for (var j=0; j<tags.length; j++) {
	tagTallies.push([tags[j], tallies[j][0], tallies[j][1]]);
    }
    tagTallies.sort(function(a,b){return cmp(-a[1], -b[1]) || cmp(a[2], b[2]) || cmp(a[0].toLowerCase(), b[0].toLowerCase());});

    var html = '<table class="slidoc-missed-concepts-table">';
    for (var j=0; j<tagTallies.length; j++) {
	if (!tagTallies[j][1])
	    continue;
	var tagId = 'slidoc-index-concept-' + make_id_from_text(tagTallies[j][0]);
	var tagTally = tagTallies[j][2] ? (tagTallies[j][1]+'/'+tagTallies[j][2]) : ((100*tagTallies[j][1]).toFixed(0)+'%');
	var tagLink = Sliobj.params.conceptIndexFile ? ('<a href="'+Sliobj.params.conceptIndexFile+'#'+tagId+'" target="_blank">'+tagTallies[j][0]+'</a>') : ('<b>'+tagTallies[j][0]+'</b>');
	html += '<tr><td>'+tagLink+':</td><td>'+tagTally+'</td></tr>';
    }
    html += '</table>';
    return html;
}

Slidoc.quoteText = function(elem, slide_id) {
    // Pre-fill comments area with indented response (as for email)
    Slidoc.log("Slidoc.quoteText:", elem, slide_id);
    var commentsArea = document.getElementById(slide_id+'-comments-textarea');
    var textareaElem = document.getElementById(slide_id+'-answer-textarea');
    commentsArea.value += textareaElem.value.replace(/(^|\n)(?=.)/g, '\n> ');
}

Slidoc.gradeClick = function (elem, slide_id) {
    Slidoc.log("Slidoc.gradeClick:", elem, slide_id);
    if (Slidoc.sheetIsLocked()) {
	alert(Slidoc.sheetIsLocked());
	return;
    }

    var userId = GService.gprofile.auth.id;
    if (!Sliobj.userGrades[userId].allowGrading) {
	alert('User '+userId+' must submit before session can be graded');
	return;
    } else if (Sliobj.userGrades[userId].late && !Sliobj.userGrades[userId].allowLateGrading) {
	if (!window.confirm('Late submission. Do you still want to grade it?'))
	    return;
	Sliobj.userGrades[userId].allowLateGrading = 1;
    }

    var question_attrs = getQuestionAttrs(slide_id);
    var gradeInput = document.getElementById(slide_id+'-grade-input');
    var commentsArea = document.getElementById(slide_id+'-comments-textarea');
    if (!elem && gradeInput.value)  // Grading already completed; do not automatically start
	return false;
    if (!question_attrs.gweight)
	gradeInput.disabled = 'disabled';

    var startGrading = !elem || elem.classList.contains('slidoc-gstart-click');
    if (!startGrading) {
	var gradeValue = gradeInput.value.trim();

	if (parseNumber(gradeValue) && parseNumber(gradeValue) > (question_attrs.gweight||0)) {
	    if (!window.confirm('Entering grade '+gradeValue+' that exceeds the maximum '+(question_attrs.gweight||0)+'. Proceed anyway?'))
		return;
	}
	var commentsValue = commentsArea.value.trim();
	var status = cacheComments(question_attrs.qnumber, userId, commentsValue, true);
	if (!status)
	    return;
    }
    toggleClass(startGrading, 'slidoc-grading-slideview', document.getElementById(slide_id));
    if (startGrading) {
	if (!commentsArea.value && 'quote_response' in Sliobj.params.features)
	    Slidoc.quoteText(null, slide_id);
	var ansContainer = document.getElementById(slide_id+"-answer-container");
	var gradeElement = document.getElementById(slide_id+'-grade-element');
	var scrollElement = ansContainer || gradeElement;
	setTimeout(function(){if (scrollElement) scrollElement.scrollIntoView(true); gradeInput.focus();}, 200);
	Slidoc.reportTestAction('gradeStart');
	displayCommentSuggestions(slide_id, question_attrs.qnumber);
    } else {
	displayCommentSuggestions(slide_id);

	setAnswerElement(slide_id, '-grade-content', gradeValue);
	renderDisplay(slide_id, '-comments-textarea', '-comments-content', true);

	var gradeField = 'q'+question_attrs.qnumber+'_grade';
	var commentsField = 'q'+question_attrs.qnumber+'_comments';
	if (!(gradeField in Sliobj.gradeFieldsObj))
	    Slidoc.log('Slidoc.gradeClick: ERROR grade field '+gradeField+' not found in sheet');
	var updates = {id: userId};
	if (question_attrs.gweight)
	    updates[gradeField] = (parseNumber(gradeValue) == null) ? '' : parseNumber(gradeValue);
	updates[commentsField] = commentsValue;
	var teamUpdate = '';
	if (question_attrs.team == 'response' && Sliobj.session.team)
	    teamUpdate = Sliobj.session.team;
	gradeUpdate(slide_id, question_attrs.qnumber, teamUpdate, updates);
    }
}

function gradeUpdate(slide_id, qnumber, teamUpdate, updates, callback) {
    Slidoc.log('gradeUpdate: ', slide_id, qnumber, teamUpdate, updates, !!callback);
    var updateObj = copyAttributes(updates);
    updateObj.Timestamp = null;  // Ensure that Timestamp is updated

    var gsheet = getSheet(Sliobj.sessionName);
    var retryOpts = {type: 'gradeUpdate'};
    retryOpts.call = gradeUpdate.bind(null, qnumber, updates, callback);

    try {
	gsheet.updateRow(updateObj, {team: !!teamUpdate}, sessionGetPutAux.bind(null, null, 'update',
		   gradeUpdateAux.bind(null, updateObj.id, slide_id, qnumber, teamUpdate, callback), retryOpts) );
    } catch(err) {
	sessionAbort(''+err, err.stack);
	return;
    }

    showPendingCalls();
    
    if (gsheet.pendingUpdates > 1)
	return;

    if (!Slidoc.testingActive()) {
	// Move on to next user needing grading if slideshow mode, else to next question
	var nextUserSlide = '';
	if (Sliobj.currentSlide) {
	    nextUserSlide = slide_id;
	} else {
	    var attr_vals = getChapterAttrs(slide_id);
	    while (qnumber < attr_vals.length) {
		// Go to next question slide that needs grading
		qnumber += 1;
		var question_attrs = attr_vals[qnumber-1];
		if (!question_attrs.gweight)
		    continue;
		var qfeedback = Sliobj.feedback ? (Sliobj.feedback[qnumber] || null) : null;
		if (qfeedback && (isNumber(qfeedback.grade) || qfeedback.comments))
		    break;
		var new_slide = parseSlideId(slide_id)[0]+'-'+zeroPad(question_attrs.slide,2);
		goSlide('#'+new_slide);
		setTimeout(function(){Slidoc.gradeClick(null, new_slide);}, 200);
	    }
	    if (qnumber == attr_vals.length) // Move to first question for next user
		nextUserSlide = parseSlideId(slide_id)[0]+'-'+zeroPad(attr_vals[0].slide,2);
	}
	if (nextUserSlide && (Sliobj.gradingUser < Sliobj.userList.length)) {
	    Slidoc.nextUser(true, false, true);
	    setTimeout(function(){Slidoc.gradeClick(null, nextUserSlide);}, 200);
	}
    }
}

function gradeUpdateAux(userId, slide_id, qnumber, teamUpdate, callback, result, retStatus) {
    Slidoc.log('gradeUpdateAux: ', userId, slide_id, qnumber, teamUpdate, !!callback, result, retStatus);
    delete Sliobj.userGrades[userId].needGrading[qnumber];
    updateGradingStatus(userId);
    if (teamUpdate) {
	for (var j=0; j<Sliobj.userList.length; j++) {
	    var id = Sliobj.userList[j];
	    if (id != userId && Sliobj.userGrades[id].team == teamUpdate)
		updateGradingStatus(id);
	}
    }
    Slidoc.reportTestAction('gradeUpdate');
}


function displayRemarks(commentsValue, gradeValue) {
    Slidoc.log('displayRemarks: ', commentsValue, gradeValue);
    var gradeInput = document.getElementById('slidoc-remarks-input');
    var gradeDisplay = document.getElementById('slidoc-remarks-content');
    var commentsArea = document.getElementById('slidoc-remarks-comments-textarea');
    var commentsDisplay = document.getElementById('slidoc-remarks-comments-content');

    if (gradeInput)
	gradeInput.value = gradeValue || '';
    if (gradeDisplay) {
	gradeDisplay.style.display = gradeValue ? null : 'none';
	gradeDisplay.textContent = gradeValue ? ('Extra points: '+gradeValue) : '';
    }
    if (commentsArea) {
	commentsArea.value = commentsValue || '';
	if (commentsDisplay) {
	    commentsDisplay.style.display = commentsValue ? null : 'none';
	    renderDisplay('slidoc-remarks', '-comments-textarea', '-comments-content', true);
	}
    }
}

Slidoc.remarksClick = function (elem) {
    Slidoc.log("Slidoc.remarksClick:", elem);
    if (Slidoc.sheetIsLocked()) {
	alert(Slidoc.sheetIsLocked());
	return;
    }

    var userId = GService.gprofile.auth.id;
    if (!Sliobj.userGrades[userId].allowGrading) {
	alert('User '+userId+' must submit before session can be graded');
	return;
    } else if (Sliobj.userGrades[userId].late) {
	if (!window.confirm('Late submission. Do you still want to grade it?'))
	    return;
    }

    var remarksStart = document.getElementById('slidoc-remarks-start-click');
    var remarksEdit = document.getElementById('slidoc-remarks-edit');
    var gradeInput = document.getElementById('slidoc-remarks-input');
    var gradeDisplay = document.getElementById('slidoc-remarks-content');
    var commentsArea = document.getElementById('slidoc-remarks-comments-textarea');
    var commentsDisplay = document.getElementById('slidoc-remarks-comments-content');

    var startGrading = !remarksStart.style.display;
    if (startGrading) {
	remarksStart.style.display = 'none';
	remarksEdit.style.display = null;
	gradeDisplay.style.display = 'none';
	commentsDisplay.style.display = null;
    } else {
	remarksStart.style.display = null;
	remarksEdit.style.display = 'none';
	var gradeValue = gradeInput.value.trim();
	var commentsValue = commentsArea.value.trim();
	displayRemarks(commentsValue, gradeValue);

	var gradeField = 'q_other';
	var commentsField = 'q_comments';
	if (!(gradeField in Sliobj.gradeFieldsObj))
	    Slidoc.log('Slidoc.remarksClick: ERROR grade field '+gradeField+' not found in sheet');
	var updates = {id: userId};
	updates[gradeField] = (parseNumber(gradeValue) == null) ? '' : parseNumber(gradeValue);
	updates[commentsField] = commentsValue;
	remarksUpdate(updates);
    }
}

function remarksUpdate(updates, callback) {
    Slidoc.log('remarksUpdate: ', updates, !!callback);
    var updateObj = copyAttributes(updates);
    updateObj.Timestamp = null;  // Ensure that Timestamp is updated

    var gsheet = getSheet(Sliobj.sessionName);
    var retryOpts = {type: 'gradeUpdate'};
    retryOpts.call = remarksUpdate.bind(null, updates, callback);

    try {
	gsheet.updateRow(updateObj, {}, sessionGetPutAux.bind(null, null, 'update',
		   remarksUpdateAux.bind(null, updateObj.id, callback), retryOpts) );
    } catch(err) {
	sessionAbort(''+err, err.stack);
	return;
    }

    showPendingCalls();
    
    if (gsheet.pendingUpdates > 1)
	return;
}

function remarksUpdateAux(userId, callback, result, retStatus) {
    Slidoc.log('remarksUpdateAux: ', userId, !!callback, result, retStatus);
    Slidoc.reportTestAction('remarksUpdate');
}

/////////////////////////////////////////
// Section 19: Paced session management
/////////////////////////////////////////

Slidoc.startPaced = function () {
    Slidoc.log('Slidoc.startPaced: ', location.hash);
    Sliobj.delaySec = null;

    var firstSlideId = getVisibleSlides()[0].id;

    Slidoc.hide(document.getElementById(firstSlideId+'-hidenotes'), 'slidoc-notes', '-'); // Hide notes for slide view
    Slidoc.classDisplay('slidoc-question-notes', 'none'); // Hide notes toggle for pacing
    preAnswer();

    var curDate = new Date();
    if (!Sliobj.session.submitted && Sliobj.dueDate && curDate > Sliobj.dueDate && Sliobj.session.lateToken != LATE_SUBMIT) {
	sessionAbort('ERROR: Unsubmitted session past submit deadline '+Sliobj.sessionName+' (due: '+Sliobj.dueDate+')');
	return;
    }

    document.body.classList.add('slidoc-paced-view');
    if (Sliobj.params.paceLevel && ('slides_only' in Sliobj.params.features))
	document.body.classList.add('slidoc-strict-paced-view');

    // Allow forward link only if no try requirement
    toggleClassAll(Sliobj.params.paceLevel < QUESTION_PACE, 'slidoc-forward-link-allowed', 'slidoc-forward-link');

    var unreadCount = discussUnread();
    
    if (Sliobj.session && Sliobj.session.submitted) {
    var startMsg = 'Reviewing submitted paced session '+Sliobj.sessionName+'<br>';
    if (unreadCount)
	startMsg += '&nbsp;&nbsp;<em>There are '+unreadCount+' slides with UNREAD discussions.</em><br>';
    } else {
    var startMsg = 'Starting'+((Sliobj.params.paceLevel && ('slides_only' in Sliobj.params.features))?' strictly':'')+' paced session '+Sliobj.sessionName+':<br>';
    if (Sliobj.timedSecLeft)
	startMsg += '&nbsp;&nbsp;<b>You have  '+Sliobj.timedSecLeft+' seconds left to complete this session.</b><br>';
    if (!('slides_only' in Sliobj.params.features))
	startMsg += '&nbsp;&nbsp;<em>You may switch between slide and document views using Escape key or Square icon at bottom left.</em><br>';
    if (Sliobj.params.questionsMax)
	startMsg += '&nbsp;&nbsp;<em>There are '+Sliobj.params.questionsMax+' questions.</em><br>';
    if (Sliobj.params.gd_sheet_url) {
	startMsg += '&nbsp;&nbsp;<em>Answers will be automatically saved after each answered question.</em><br>';
	if (Sliobj.params.slideDelay)
	    startMsg += '&nbsp;&nbsp;<em>If you plan to continue on a different computer, remember to explicitly save the session before leaving this computer (to avoid delays on previously viewed slides).</em><br>';
	if (retakesRemaining())
	    startMsg += '&nbsp;&nbsp;<b>You may re-take this '+retakesRemaining()+' more time(s).</b><br>';
	else if (Sliobj.params.maxRetakes)
	    startMsg += '&nbsp;&nbsp;<b>No more re-takes available.</b><br>';
    }
    startMsg += '<ul>';
    if (Sliobj.params.slideDelay && allowDelay())
	startMsg += '<li>'+Sliobj.params.slideDelay+' sec delay between slides</li>';
    startMsg += '</ul>';
    }

    if (!Sliobj.batchMode && !Sliobj.updateView && (!Sliobj.previewState || !location.hash || location.hash.slice(1).match(/-01$/)))
	Slidoc.showPopup(startMsg);

    var chapterId = parseSlideId(firstSlideId)[0];
    if (!singleChapterView(chapterId))
	alert('INTERNAL ERROR: Unable to display chapter for paced mode');

    if ((Sliobj.updateView || Sliobj.previewState) && location.hash && location.hash.slice(0,2) == '#-') {
	// Unhide all slides
	slidesVisible(true);
	restoreScroll();
    } else if (!Sliobj.batchMode && !Sliobj.assessmentView) {
	Slidoc.slideViewStart();
    }
}

Slidoc.endPaced = function (reload) {
    Sliobj.timedClose = null;
    Sliobj.delaySec = null;
    Slidoc.log('Slidoc.endPaced: ');
    if (!Sliobj.params.gd_sheet_url)       // For remote sessions, successful submission will complete session
	Sliobj.session.submitted = ''+(new Date());
    ///if (Sliobj.params.paceLevel <= BASIC_PACE) {
	// If pace can end, unpace
	///document.body.classList.remove('slidoc-paced-view');
	///Sliobj.session.paced = 0;
    ///}
    Slidoc.reportTestAction('endPaced');
    if (Sliobj.interactiveSlide)
	enableInteract(false);
    sessionPut(null, null, {force: true, retry: 'end_paced', submit: true, reload: !!reload});
    showCompletionStatus();
    var answerElems = document.getElementsByClassName('slidoc-answer-button');
    for (var j=0; j<answerElems.length; j++)
	answerElems[j].disabled = 'disabled';
}

Slidoc.answerPacedAllow = function () {
    if (!Sliobj.session || !Sliobj.session.paced)
	return true;

    if (Sliobj.session.tryDelay && Sliobj.session.lastTries > 0) {
	var delta = (Date.now() - Sliobj.session.lastTime)/1000;
	if (delta < Sliobj.session.tryDelay) {
	    alert('Please wait '+ Math.ceil(Sliobj.session.tryDelay-delta) + ' second(s) to answer again');
	    return false;
	}
    }
    return true;
}

function showCompletionStatus() {
    var msg = '<b>Paced session completed.</b><br>';
    if (Sliobj.params.gd_sheet_url) {
	if (Sliobj.session.submitted) {
	    if (Sliobj.closePopup) {
		// Re-display popup
		Sliobj.closePopup();
		msg += 'Completed session <b>submitted successfully</b> to Google Docs at '+parseDate(Sliobj.session.submitted)+'<br>';
		if (!Sliobj.session.paced)
		    msg += 'You may now exit slide view and access this document normally.<br>';
	    } else {
		alert('Completed session submitted successfully to Google Docs at '+parseDate(Sliobj.session.submitted));
		return;
	    }
	} else  {
	    msg += 'Do not close this popup. Wait for confirmation that session has been submitted to Google Docs<br>';
	}
    } else if (!Sliobj.session.paced) {
	msg += 'You may now exit slide view and access this document normally.<br>';
    }
    Slidoc.showConcepts(msg);
}

//////////////////////////////////////
// Section 20: Slide view management
//////////////////////////////////////


Slidoc.slideViewStart = function () {
   if (Sliobj.currentSlide) 
      return false;
   Sliobj.prevSidebar = Sliobj.sidebar;
    if (Sliobj.sidebar) {
	Slidoc.sidebarDisplay();
    }
   var slides = getVisibleSlides();
   if (!slides)
       return false;
   var firstSlideId = slides[0].id;
   Slidoc.breakChain();

   var startSlide = getCurrentlyVisibleSlide(slides) || 1;
    if ((Sliobj.previewState || Sliobj.updateView) && location.hash && location.hash.slice(1).match(SLIDE_ID_RE)) {
	startSlide = Math.min(slides.length, parseSlideId(location.hash.slice(1))[2]);
    } else if (Sliobj.updateView) {
	startSlide = 1;
   } else if (Sliobj.session && Sliobj.session.paced) {
       startSlide = Sliobj.session.submitted ? 1 : (Sliobj.session.lastSlide || 1); 
   } else {
       // Hide notes (for paced view, this is handled earlier)
       Slidoc.hide(document.getElementById(firstSlideId+'-hidenotes'), 'slidoc-notes', '-');
   }
    var chapterId = parseSlideId(firstSlideId)[0];
    var contentElems = document.getElementsByClassName('slidoc-chapter-toc-hide');
    for (var j=0; j<contentElems.length; j++)
	Slidoc.hide(contentElems[j], null, '-');

    document.body.classList.add('slidoc-slide-view');

    Slidoc.slideViewGo(false, startSlide, true);
    Slidoc.reportTestAction('initSlideView');
    return false;
}

Slidoc.slideViewEnd = function() {
    if (!Sliobj.gradableState && ('slides_only' in Sliobj.params.features)) {
	if (!setupOverride('Enable test user override to avoid slides_only restriction?')) {
	    var msgStr = 'This session can only be viewed as slides';
	    alert(msgStr);
	    return false;
	}
    }

    if (!Sliobj.currentSlide)
	return false;

    var slides = getVisibleSlides();

    var prev_slide_id = slides[Sliobj.currentSlide-1].id;
    if (prev_slide_id in Sliobj.slidePluginList) {
	for (var j=0; j<Sliobj.slidePluginList[prev_slide_id].length; j++)
	    Slidoc.PluginManager.optCall(Sliobj.slidePluginList[prev_slide_id][j], 'leaveSlide');
    }

    if (!setupOverride() && Sliobj.hideUnviewedSlides) {
	// Unhide only viewed slides
	for (var j=0; j<Sliobj.session.lastSlide; j++)
	    slidesVisible(true, j+1, slides);
    } else {
	// Unhide all slides
	slidesVisible(true);
	Slidoc.classDisplay('slidoc-notes', 'block');
	var contElems = document.getElementsByClassName('slidoc-chapter-toc-hide');
	for (var j=0; j<contElems.length; j++)
	    Slidoc.hide(contElems[j], null, '+');
    }

    document.body.classList.remove('slidoc-slide-view');
    document.body.classList.remove('slidoc-incremental-view');
    for (var j=1; j<=MAX_INC_LEVEL; j++)
	document.body.classList.remove('slidoc-display-incremental'+j);
    Sliobj.maxIncrement = 0;
    Sliobj.curIncrement = 0;

    if (slides && Sliobj.currentSlide > 0 && Sliobj.currentSlide <= slides.length) {
       location.href = '#'+slides[Sliobj.currentSlide-1].id;
    }
    Sliobj.currentSlide = 0;
    Sliobj.questionSlide = null;

    var pluginButton = document.getElementById("slidoc-button-plugin");
    pluginButton.innerHTML = '';
    pluginButton.style.display = 'none';
    
    if (Sliobj.prevSidebar) {
	Sliobj.prevSidebar = false;
	Slidoc.sidebarDisplay();
    }
   return false;
}

Slidoc.slideViewGoLast = function () {
    if (Sliobj.session && Sliobj.session.paced) {
	Slidoc.slideViewGo(false, Sliobj.session.lastSlide);
    } else {
	var slides = getVisibleSlides();
	Slidoc.slideViewGo(false, slides.length);
    }
    return false;
}

Slidoc.slideViewGo = function (forward, slide_num, start) {
    var slides = getVisibleSlides();
    Slidoc.log('Slidoc.slideViewGo:', forward, slide_num, slides.length, Sliobj.session ? Sliobj.session.lastSlide : -1);
    var prev_slide_id = Sliobj.currentSlide ? slides[Sliobj.currentSlide-1].id : null;
    if (!start) {
	if (!Sliobj.currentSlide) {
	    Slidoc.log('Slidoc.slideViewGo: ERROR not in slide view to go to slide '+slide_num);
	    return false;
	}
	if (!slide_num)
	    slide_num = forward ? Sliobj.currentSlide+1 : Sliobj.currentSlide-1;
	if (prev_slide_id in Sliobj.slidePluginList) {
	    for (var j=0; j<Sliobj.slidePluginList[prev_slide_id].length; j++)
		Slidoc.PluginManager.optCall(Sliobj.slidePluginList[prev_slide_id][j], 'leaveSlide');
	}
    } else if (!slide_num) {
	return false;
    }
    var backward = (slide_num < Sliobj.currentSlide);

    if (!slides || slide_num < 1 || slide_num > slides.length)
	return false;

    while (slides[slide_num-1].classList.contains('slidoc-slide-hidden') && !Sliobj.showHiddenSlides) {
	// Skip explicitly hidden slides
	if (slide_num <= 1 || slide_num >= slides.length)
	    return false;
	if (backward)
	    slide_num -= 1;
	else
	    slide_num += 1;
    }

    if (Sliobj.session && Sliobj.session.paced && Sliobj.params.paceLevel >= QUESTION_PACE && slide_num > Sliobj.session.lastSlide+1 && slide_num > Sliobj.scores.skipToSlide) {
	// Advance one slide at a time
	var reloadSkip = (location.hostname == 'localhost' && Sliobj.reloadCheck);
	    
	if (!reloadSkip && !Sliobj.previewState && !setupOverride('Enable test user override to skip ahead?')) {
	    showDialog('alert', 'skipAheadDialog', 'Must have answered the recent batch of questions correctly to jump ahead in paced mode');
	    return false;
	}
    }

    var slide_id = slides[slide_num-1].id;
    var question_attrs = getQuestionAttrs(slide_id);  // New slide
    Sliobj.lastInputValue = null;

    if (Sliobj.session && Sliobj.session.paced && slide_num > Sliobj.session.lastSlide) {
	// Advancing to next (or later) paced slide; update session parameters
	Slidoc.log('Slidoc.slideViewGo:B', slide_num, Sliobj.session.lastSlide);

	if (Sliobj.questionSlide && !Sliobj.session.questionsAttempted[Sliobj.questionSlide.qnumber] && Sliobj.session.remainingTries) {
	    // Current (not new) slide is question slide
	    if (isController() && prev_slide_id) {
		if (!window.confirm("Finalize question and proceed?"))
		    return false;
		var ansElem = document.getElementById(prev_slide_id+'-answer-click');
		if (ansElem)
		    Slidoc.answerClick(ansElem, prev_slide_id, 'controlled');
	    } else  {
		if (!setupOverride('Enable test user override to proceed without answering?')) {
		    var tryCount = (Sliobj.questionSlide.qtype=='choice') ? 1 : Sliobj.session.remainingTries;
		    var prompt = 'Please answer before proceeding.'
		    if (tryCount > 1)
			prompt += 'You have '+tryCount+' try(s)';

		    showDialog('alert', 'requireAnswerDialog', prompt);
		    return false;
		}
	    }

	} else if (Sliobj.delaySec) {
	    // Current (not new) slide has delay
	    var delta = (Date.now() - Sliobj.session.lastTime)/1000;
	    if (delta < Sliobj.delaySec) {
		alert('Please wait '+ Math.ceil(Sliobj.delaySec-delta) + ' second(s)');
		return false;
	    }
	}

	if (Sliobj.interactiveSlide)
	    enableInteract(false);

	if (0 && !controlledPace() && (slide_num == slides.length && Sliobj.params.paceLevel == BASIC_PACE && Sliobj.scores.questionsCount < Sliobj.params.questionsMax)) {
	    // To last slide (DISABLED: no auto submit for BASIC PACE)
	    var prompt = 'You have only answered '+Sliobj.scores.questionsCount+' of '+Sliobj.params.questionsMax+' questions. Do you wish to go to the last slide and end the paced session?';
	    if (!showDialog('confirm', 'lastSlideDialog', prompt))
		return false;
	}

        // Update session for new slide
	Sliobj.session.lastSlide = slide_num; 
	Sliobj.session.lastTime = Date.now();
	Sliobj.questionSlide = question_attrs;

	var curTime = Date.now();
	if (slide_num == 1 && Sliobj.params.paceLevel == ADMIN_PACE)
	    // initTime: show_start_time (offset)
	    // forward: [[slide1_start_offset, slide2_end_offset], ...] for forward navigation times
	    // back: [[[back_slide_num, time_offset], ...], ...] for backward navigation during paced show
	    Sliobj.session.showTime = {initTime: curTime, forward:[], back: []};

	if (Sliobj.session.showTime) {
	    var showTime = Sliobj.session.showTime;
	    var offsetTime = curTime-showTime.initTime;
	    if (slide_num > 1)
		showTime.forward.slice(-1)[0][1] = offsetTime;
	    showTime.forward.push( [offsetTime, 0] );
	    showTime.back.push( [] );
	}

	Sliobj.session.lastTries = 0;
	Sliobj.session.remainingTries = 0;
	Sliobj.session.tryDelay = 0;
	if (Sliobj.questionSlide && !Sliobj.session.questionsAttempted[Sliobj.questionSlide.qnumber]) {
	    if (Sliobj.params.paceLevel >= QUESTION_PACE)  {
		// Non-zero remaining tries only for QUESTION_PACE or greater
		if (Sliobj.params.paceLevel == QUESTION_PACE && question_attrs.retry) {
		    // Multiple tries only allowed for QUESTION_PACE
		    Sliobj.session.remainingTries = 1+question_attrs.retry[0];
		    Sliobj.session.tryDelay = question_attrs.retry[1];
		} else {
		    Sliobj.session.remainingTries = 1;
		}
	    }
        }

	var pluginButton = document.getElementById("slidoc-button-plugin");
	if (slide_id in Sliobj.buttonPlugins) {
	    pluginButton.innerHTML = Sliobj.activePlugins[Sliobj.buttonPlugins[slide_id].name].button[slide_id]
	    pluginButton.style.display = null;
	} else {
	    pluginButton.innerHTML = '';
	    pluginButton.style.display = 'none';
	}
	Sliobj.delaySec = null;
	if (allowDelay()) {
	    if (slide_id in Sliobj.slidePluginList) {
		for (var j=0; j<Sliobj.slidePluginList[slide_id].length; j++) {
		    var delaySec = Slidoc.PluginManager.optCall(Sliobj.slidePluginList[slide_id][j], 'enterSlide', true, backward);
		    if (delaySec != null)
			Sliobj.delaySec = delaySec;
		}
	    }

	    if (Sliobj.delaySec == null && !Sliobj.questionSlide) // Default delay only for non-question slides
		Sliobj.delaySec = Sliobj.params.slideDelay;
	    if (Sliobj.delaySec)
		Slidoc.delayIndicator(Sliobj.delaySec, 'slidoc-slide-nav-prev', 'slidoc-slide-nav-next');
	}

	Slidoc.log('Slidoc.slideViewGo:C', Sliobj.session.lastSlide, slides.length, controlledPace());
	if (Sliobj.params.paceLevel == QUESTION_PACE && !Sliobj.session.submitted && Sliobj.session.lastSlide == slides.length && !retakesRemaining()) {
	    // Auto-submit on last slide for question-pacing only with no retakes
	    Slidoc.endPaced();

	} else if (Sliobj.sessionName && !Sliobj.params.gd_sheet_url) {
	    // Not last slide; save updated session (if not transient and not remote)
	    sessionPut();

	} else if (isController()) {
	    // Not last slide for test user in admin-paced; save lastSlide value
	    sessionPut();
	    if (Sliobj.interactiveMode)
		enableInteract(true);
	}

	if (isController()) {
	    if (Sliobj.session.lastSlide > 1)
		Slidoc.sendEvent(-1, 'AdminPacedAdvance', Sliobj.session.lastSlide);
	}
    } else {
	if (Sliobj.session && Sliobj.session.paced && slide_num < Sliobj.session.lastSlide && !Sliobj.questionSlide && Sliobj.delaySec) {
	    // Not last paced slide, not question slide, delay active
	    var delta = (Date.now() - Sliobj.session.lastTime)/1000;
	    if (delta < Sliobj.delaySec) {
		alert('Please wait '+ Math.ceil(Sliobj.delaySec-delta) + ' second(s)');
		return false;
	    }
	}
	if (Sliobj.session && Sliobj.session.paced && Sliobj.session.showTime)
	    Sliobj.session.showTime.back.slice(-1)[0].push( [slide_num, Date.now()-Sliobj.session.showTime.initTime] );

	Sliobj.questionSlide = question_attrs;
	if (slide_id in Sliobj.slidePluginList) {
	    for (var j=0; j<Sliobj.slidePluginList[slide_id].length; j++)
		Slidoc.PluginManager.optCall(Sliobj.slidePluginList[slide_id][j], 'enterSlide', false, backward);
	}
    }

    if (Sliobj.session && Sliobj.session.paced) {
	toggleClass(Sliobj.questionSlide && Sliobj.params.paceLevel == QUESTION_PACE && !Sliobj.scores.correctSequence, 'slidoc-incorrect-answer-state');
	toggleClass(slide_num == Sliobj.session.lastSlide, 'slidoc-paced-last-slide');
	toggleClass(Sliobj.session.remainingTries, 'slidoc-expect-answer-state');
    }
    if (Sliobj.scores)
	toggleClass(slide_num < Sliobj.scores.skipToSlide, 'slidoc-skip-optional-slide');

    var prev_elem = document.getElementById('slidoc-slide-nav-prev');
    var next_elem = document.getElementById('slidoc-slide-nav-next');
    prev_elem.style.visibility = (slide_num == 1) ? 'hidden' : 'visible';
    next_elem.style.visibility = (slide_num == slides.length) ? 'hidden' : 'visible';

    var actual_slide_num = 0;
    var actual_slide_total = 0;
    for (var j=0; j<slides.length; j++) {
	if (Sliobj.showHiddenSlides || !slides[j].classList.contains('slidoc-slide-hidden')) {
	    // Count only slides not explicitly hidden
	    actual_slide_total += 1;
	    if (j+1 <= slide_num)
		actual_slide_num += 1;
	}
    }

    var counterElem = document.getElementById('slidoc-slide-nav-counter');
    counterElem.textContent = ((actual_slide_total <= 9) ? actual_slide_num : zeroPad(actual_slide_num,2))+'/'+actual_slide_total;
    if (actual_slide_total < slides.length && getUserId() == Sliobj.params.testUserId)
	counterElem.textContent += '*';

    Slidoc.log('Slidoc.slideViewGo:D', slide_num, slides[slide_num-1]);
    Sliobj.maxIncrement = 0;
    Sliobj.curIncrement = 0;
    if ('incremental_slides' in Sliobj.params.features && (!Sliobj.session || !Sliobj.session.paced || (!Sliobj.session.submitted && Sliobj.session.lastSlide == slide_num)) ) {
	// Incremental display only applied to last slide for unsubmitted paced sessions
	for (var j=1; j<=MAX_INC_LEVEL; j++) {
	    if (slides[slide_num-1].querySelector('.slidoc-incremental'+j)) {
		Sliobj.maxIncrement = j;
		toggleClass(backward, 'slidoc-display-incremental'+j);
		if (Sliobj.currentSlide > slide_num) {
		    Sliobj.curIncrement = j;
		}
	    }
	}
	toggleClass(Sliobj.curIncrement < Sliobj.maxIncrement, 'slidoc-incremental-view');
    } else {
	toggleClass(slide_id in Sliobj.incrementPlugins, 'slidoc-incremental-view');
    }

    slidesVisible(true, slide_num, slides);
    for (var i=0; i<slides.length; i++) {
	if (i != slide_num-1) slidesVisible(false, i+1, slides);
    }
    Sliobj.currentSlide = slide_num;
    location.href = '#'+slides[Sliobj.currentSlide-1].id;

    var inputElem = document.getElementById(slides[Sliobj.currentSlide-1].id+'-answer-input');
    window.scrollTo(0,1);
    if (inputElem) setTimeout(function(){inputElem.focus();}, 50);
    return false;
}

Slidoc.breakChain = function () {
   // Hide any current chain link
   var tagid = location.hash.substr(1);
   var ichain_elem = document.getElementById(tagid+"-ichain");
   if (ichain_elem)
       ichain_elem.style.display = 'none';
}

function singleChapterView(newChapterId) {
    if (newChapterId == Sliobj.curChapterId)
	return true;
    // Switch chapter
    if (!Sliobj.curChapterId) {
	// Switch to single chapter view
	document.body.classList.remove('slidoc-all-view');
    } else if (Sliobj.session && Sliobj.session.paced) {
	alert('Slidoc: InternalError: cannot switch chapters in paced mode');
	return false;
    }
    var newChapterElem = document.getElementById(newChapterId);
    if (!newChapterElem) {
        Slidoc.log('goSlide: Error - unable to find chapter:', newChapterId);
        return false;
    }
    Sliobj.curChapterId = newChapterId;
    var chapters = document.getElementsByClassName('slidoc-container');
    Slidoc.log('singleChapterView:', newChapterId, chapters.length);
    for (var i=0; i < chapters.length; i++) {
	if (!Sliobj.sidebar || !chapters[i].classList.contains('slidoc-toc-container'))
	    chapters[i].style.display = (chapters[i].id == newChapterId) ? null : 'none';
    }
    return true;
}

Slidoc.go = function (slideHash, chained) {
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    return goSlide(slideHash, chained);
}

function goSlide(slideHash, chained, singleChapter) {
   // Scroll to slide with slideHash, hiding current chapter and opening new one
   // If chained, hide previous link and set up new link
    Slidoc.log("goSlide:", slideHash, chained);
    if (Sliobj.session && Sliobj.session.paced && ('slides_only' in Sliobj.params.features) && !Sliobj.currentSlide && !singleChapter && (getUserId() != Sliobj.params.testUserId)) {
	alert('Slidoc: InternalError: strict paced mode without slideView');
	return false;
    }
    if (!slideHash) {
	if (Sliobj.currentSlide) {
	    Slidoc.slideViewGo(false, 1);
	} else {
	    location.hash = Sliobj.curChapterId ? '#'+Sliobj.curChapterId+'-01' : '#slidoc01-01';
	    window.scrollTo(0,1);
        }
	return false;
    }

    var slideId = slideHash.substr(1);
    var tocSlide = slideId.match(/^slidoc00/);
    if (Sliobj.sidebar && tocSlide)
	sidebarDisplayAux(false); // Hide sidebar to show TOC

   var goElement = document.getElementById(slideId);
   Slidoc.log('goSlide:B ', slideId, chained, goElement);
   if (!goElement) {
      Slidoc.log('goSlide: Error - unable to find element', slideHash);
      return false;
   }

   Slidoc.breakChain();
   if (!chained) {
       // End chain
       Sliobj.ChainQuery = '';
       Sliobj.chainActive = null;
   }

    // Locate reference
    var match = /slidoc-ref-(.*)$/.exec(slideId);
    Slidoc.log('goSlide:C ', match, slideId);
    if (match) {
        // Find slide containing reference
        if (!goElement.dataset || !goElement.dataset.slideId) {
            Slidoc.log('goSlide: Error - unable to find slide containing header:', slideHash);
            return false;
        }
	slideId = goElement.dataset.slideId;
	slideHash = '#'+slideId;
	Slidoc.log('goSlide:D ', slideHash);
    }

    if (Sliobj.curChapterId || singleChapter) {
	// Display only chapter containing slide
	var newChapterId = parseSlideId(slideId)[0];
	if (!newChapterId) {
            Slidoc.log('goSlide: Error - invalid hash, not slide or chapter', slideHash);
            return false;
	}
	if (!singleChapterView(newChapterId))
	    return false;
    }

   if (Sliobj.currentSlide) {
      var slides = getVisibleSlides();
      for (var i=0; i<slides.length; i++) {
         if (slides[i].id == slideId) {
           Slidoc.slideViewGo(false, i+1);
           return false;
         }
      }
      Slidoc.log('goSlide: Error - slideshow slide not in view:', slideId);
      return false;

   } else if (Sliobj.session && Sliobj.session.paced) {
       var slide_num = parseSlideId(slideId)[2];
       if (!slide_num || slide_num > Sliobj.session.lastSlide) {
	   Slidoc.log('goSlide: Warning - Paced slide not reached:', slide_num, Sliobj.session.lastSlide);
	   return false;
       }
   }

   Slidoc.log('goSlide:F ', slideHash);
   location.hash = slideHash;

   if (chained && Sliobj.ChainQuery)  // Set up new chain link
       Slidoc.chainUpdate(Sliobj.ChainQuery);

   goElement.scrollIntoView(true); // Redundant?

    if (!tocSlide && !Sliobj.currentSlide && !(Sliobj.session && Sliobj.session.paced) && !Sliobj.sidebar && !Sliobj.showedFirstSideBar &&
	window.matchMedia("screen and (min-width: 800px) and (min-device-width: 960px)").matches) {
	// Non-slide/nonpaced scroll view; show sidebar once to make user aware of sidebar
	Sliobj.showedFirstSideBar = true;
	Slidoc.sidebarDisplay();
    }

   return false;
}

////////////////////////////////////////////
// Section 21: Concept link chain handlers
////////////////////////////////////////////


Slidoc.chainLink = function (newindex, queryStr, urlPath) {
   // Returns next/prev chain URL: /(prefix)(newtag0).html?index=1&taglist=...#newtag1
   // tag = fsuffix#id
   // If not urlPath, return the new query string+hash (without the path)
   Slidoc.log("Slidoc.chainLink:", newindex, queryStr, urlPath);
   var tagindex = getParameter('tagindex', true, queryStr);
   var taglist = (getParameter('taglist', false, queryStr) || '').split(";");
   var curcomps = taglist[tagindex-1].split("#");
   var newcomps = taglist[newindex-1].split("#");
   var newQuery = queryStr.replace('index='+tagindex, 'index='+newindex);
   if (!urlPath) {
       return newQuery + '#' + newcomps[1];
   }
   var suffix = ".html";
   var prefix = urlPath.substr(0, urlPath.length-(curcomps[0]+suffix).length);
   return prefix + newcomps[0] + suffix + newQuery + '#' + newcomps[1];
}

Slidoc.chainURL = function (newindex) {
   // Return URL to load next link in concept chain
   Slidoc.log("Slidoc.chainURL:", newindex);
   return Slidoc.chainLink(newindex, location.search, location.pathname);
}

Slidoc.chainNav = function (newindex) {
   // Navigate to next link in concept chain
   Slidoc.log("Slidoc.chainNav:", newindex);
   if (!Sliobj.ChainQuery)
      return false;
   var comps = Slidoc.chainLink(newindex, Sliobj.ChainQuery).split('#');
   Sliobj.ChainQuery = comps[0];
   goSlide('#'+comps[1], true);
    Slidoc.log("Slidoc.chainNav:B", location.hash);
   return false;
}

Slidoc.chainStart = function (queryStr, slideHash) {
   // Go to first link in concept chain
    Slidoc.log("Slidoc.chainStart:", slideHash, queryStr);
    Sliobj.ChainQuery = queryStr;
    goSlide(slideHash, true);
    return false;
}

Slidoc.chainUpdate = function (queryStr) {
    queryStr = queryStr || location.search;
    var tagid = location.hash.substr(1);
    Slidoc.log("Slidoc.chainUpdate:", queryStr, tagid);

    var ichain_elem = document.getElementById(tagid+"-ichain");
    if (!ichain_elem)
       return false;

    var tagindex = getParameter('tagindex', true, queryStr);
    Slidoc.log("Slidoc.chainUpdate:B", tagindex);
    if (!tagindex)
      return false;

    var tagconcept = getParameter('tagconcept', false, queryStr) || '';
    var tagconceptref = getParameter('tagconceptref', false, queryStr) || '';
    var taglist = (getParameter('taglist', false, queryStr) || '').split(";");

    var conceptFunc = null;
    var prevFunc = null;
    var nextFunc = null;
    if (tagindex) {
        ichain_elem.style.display = 'block';
        var concept_elem = document.getElementById(tagid+"-ichain-concept");
        concept_elem.textContent = tagconcept;
        if (Sliobj.ChainQuery) {
	    conceptFunc = function() {goSlide(tagconceptref);}
            concept_elem.onclick = conceptFunc;
        } else {
	    var conceptURL = getBaseURL()+'/'+tagconceptref;
	    conceptFunc = function() { window.location = conceptURL; }
            concept_elem.href = conceptURL;
        }
        var prev_elem = document.getElementById(tagid+"-ichain-prev");
        prev_elem.style.visibility = (tagindex == 1) ? 'hidden' : 'visible';
        if (tagindex > 1) {
           if (Sliobj.ChainQuery) {
	       prevFunc = function() {Slidoc.chainNav(tagindex-1);}
               prev_elem.onclick = prevFunc;
           } else {
	       var prevURL = Slidoc.chainURL(tagindex-1);
	       prevFunc = function() { window.location = prevURL; }
               prev_elem.href = prevURL;
           }
        }
        var next_elem = document.getElementById(tagid+"-ichain-next");
        next_elem.style.visibility = (tagindex == taglist.length) ? 'hidden' : 'visible';
        if (tagindex < taglist.length) {
           if (Sliobj.ChainQuery) {
	       nextFunc = function() {Slidoc.chainNav(tagindex+1);}
               next_elem.onclick = nextFunc;
           } else {
	       var nextURL = Slidoc.chainURL(tagindex+1);
	       nextFunc = function() { window.location = nextURL; }
               next_elem.href = nextURL;
           }
        }
    }
    Sliobj.chainActive = [prevFunc, conceptFunc, nextFunc];
    Slidoc.log("Slidoc.chainUpdate:D", location.hash);
}

// Popup: http://www.loginradius.com/engineering/simple-popup-tutorial/
Slidoc.closeAllPopups = function () {
    if (Sliobj.closePopup)
	Sliobj.closePopup();
}
Slidoc.showPopup = function (innerHTML, divElemId, wide, autoCloseMillisec, popupEvent, closeCallback) {
    // Only one of innerHTML or divElemId needs to be non-null
    if (Slidoc.testingActive()) {
	if (Sliobj.testScript.stepEvent) {
	    Sliobj.testScript.showStatus('X to advance');
	} else {
	    autoCloseMillisec = 500;
	}
    }
    if (Sliobj.closePopup) {
	Slidoc.log('Slidoc.showPopup: Popup already open');
	if (!autoCloseMillisec)
	    Sliobj.popupQueue.push([innerHTML||null, divElemId||null, wide||null]);
	return null;
    }

    if (!divElemId) divElemId = 'slidoc-generic-popup';
    var divElem = document.getElementById(divElemId);
    toggleClass(!!wide, 'slidoc-wide-popup', divElem);

    var closeElem = document.getElementById(divElem.id+'-close');
    var overlayElem = document.getElementById('slidoc-generic-overlay');
    var contentElem = null;
    if (!overlayElem) {
	alert('slidoc: INTERNAL ERROR - no overlay for popup ');
    } else if (!divElem) {
	alert('slidoc: INTERNAL ERROR - no div for popup'+divElemId);
    } else if (!closeElem) {
	alert('slidoc: INTERNAL ERROR - no close for popup'+divElemId);
    } else {
	if (innerHTML) {
	    contentElem = document.getElementById(divElem.id+'-content')
	    if (contentElem)
		contentElem.innerHTML = innerHTML;
	    else
		alert('slidoc: INTERNAL ERROR - no content for popup'+divElemId)
	}
	overlayElem.style.display = 'block';
	divElem.style.display = 'block';

	Sliobj.popupEvent = popupEvent || '';
	Sliobj.closePopup = function (evt, closeEvent, closeArg) {
	    // closeCallback is called with closeArg, if closeEvent matches popupEvent
	    overlayElem.style.display = 'none';
	    divElem.style.display = 'none';
	    var matchEvent = closeEvent && (closeEvent == Sliobj.popupEvent);
	    Sliobj.popupEvent = '';
	    Sliobj.closePopup = null;
	    if (!evt) {
		Sliobj.popupQueue = [];
	    } else {
		if (Sliobj.popupQueue && Sliobj.popupQueue.length) {
		    var args = Sliobj.popupQueue.shift();
		    Slidoc.showPopup(args[0], args[1], args[2]);
		}
	    }
	    if (closeCallback && matchEvent) {
		try { closeCallback(closeArg || null); } catch (err) {Slidoc.log('Sliobj.closePopup: ERROR '+err);}
	    }
	    Slidoc.advanceStep();
	}
	
	closeElem.onclick = Sliobj.closePopup;
	///overlayElem.onclick = Sliobj.closePopup;
	if (autoCloseMillisec)
	    setTimeout(Sliobj.closePopup, autoCloseMillisec);
    }
    toggleClass((wide == 'printable'), 'slidoc-printable-overlay', overlayElem);
    window.scrollTo(0,1);
    return contentElem;
}

Slidoc.showPopupOptions = function(prefixHTML, optionListHTML, suffixHTML, callback) {
    // Show list of options as popup, with callback(n) invoked on select.
    // n >= 1 for selection, or null if popup is closed
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    var lines = [prefixHTML || ''];
    lines.push('<p></p><ul class="slidoc-popup-option-list">');
    for (var j=0; j<optionListHTML.length; j++)
	lines.push('<li class="slidoc-popup-option-list-element slidoc-clickable" onclick="Slidoc.selectPopupOption('+(j+1)+');">'+optionListHTML[j]+'</li><p></p>');
    lines.push('</ul>');
    lines.push(suffixHTML || '');
    Slidoc.showPopup(lines.join('\n'), null, false, 0, 'PopupOptions', callback||null);
}

Slidoc.selectPopupOption = function(closeArg) {
    Slidoc.log('Slidoc.selectPopupOption:', closeArg);
    if (Sliobj.closePopup)
	Sliobj.closePopup(null, 'PopupOptions', closeArg||null);
}

Slidoc.showPopupWithList = function(prefixHTML, listElems, lastMarkdown) {
    // Show popup ending with a tabular list [ [html, insertText1, insertText2, ...], ... ]
    // Safely populate list with plain text, or Markdown (last column only, if !no_markdown)
    //Slidoc.log('showPopupWithList:', listElems, lastMarkdown);
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    if (Sliobj.params.features.no_markdown)
	lastMarkdown = false;
    var lines = [prefixHTML || ''];
    lines.push('<ul class="slidoc-popup-with-list">');
    for (var j=0; j<listElems.length; j++)
	lines.push('<li class="slidoc-plugin-Share-li">'+listElems[j][0]+'</li>');
    lines.push('</ul>');

    var popupContent = Slidoc.showPopup(lines.join('\n'), null, true);
    var listNodes = popupContent.lastElementChild.children;
    for (var j=0; j<listElems.length; j++) {
	var childNodes = listNodes[j].children;
	var curElems = listElems[j];
	for (var k=1; k<curElems.length; k++) {
	    if (!curElems[k])
		continue;
	    if (k == curElems.length-1 && lastMarkdown && window.PagedownConverter)
		childNodes[k-1].innerHTML = MDConverter(curElems[k], true);
	    else
		childNodes[k-1].textContent = curElems[k];
	}
    }
    if (lastMarkdown && window.MathJax)
	MathJax.Hub.Queue(["Typeset", MathJax.Hub, popupContent.id]);
}

Slidoc.wordCloud = function(textList, options) {
    if (!window.WCloud) {
	alert('WCloud module not loaded!');
	return;
    }
    Slidoc.log('Slidoc.wordCloud:', textList.length);
    Slidoc.showPopup('<div id="slidoc-wcloud-container"><br><br><br><br><br><br><br><br><br><br><br><br><br><br><br><br><br><br><br><br><br><br><br><br></div>', null, true);
    WCloud.createCloud(document.getElementById("slidoc-wcloud-container"), textList);
}

Slidoc.shareCloud = function() {
    if (!Sliobj.closePopup)
	return;
    Slidoc.log('Slidoc.shareCloud:');
    var popupElem = document.getElementById('slidoc-generic-popup-content');
    var elems = popupElem.getElementsByClassName('slidoc-plugin-Share-li');
    var textList = [];
    for (var j=0; j<elems.length; j++) {
	textList.push(elems[j].textContent);
    }
    Sliobj.closePopup();
    Slidoc.wordCloud(textList);
}

//////////////////////////////////
// Section 22: Pagedown helpers
//////////////////////////////////

function MDEscapeInlineLatex(whole, inner) {
    // Escape special characters in inline formulas (from Markdown processing)
    return "\\\\(" + inner.replace(/\*/g, "\\*").replace(/\_/g, "\\_") + "\\\\)";
}

function MDEscapeInlineTex(whole, p1, p2, p3) {
    // Escape special characters in inline formulas (from Markdown processing)
    return p1+"$" + (p2+p3).replace(/\*/g, "\\*").replace(/\_/g, "\\_") + "$";
}

function MDPreSpanGamut(text, runSpanGamut, texMath) {
    text = text.replace(/\\\((.+?)\\\)/g, MDEscapeInlineLatex);
    if (texMath || 'tex_math' in Sliobj.params.features)
	text = text.replace(/(^|[^\\\$])\$(?!\$)(.*?)([^\\\n\$])\$(?!\$)/g, MDEscapeInlineTex);
    return text;
}

function MDPreSpanTest() {
    var inOut = [ ['$_$', '$\\_$'],
		  ['$*$', '$\\*$'],
		  ['$$*$', '$$*$'],
		  ['$*$$', '$*$$'],
		  ['$*\\$*$', '$\\*\\$\\*$'],
		  ['$*\\$', '$*\\$'],
		  ['\\$*$', '\\$*$'],
		  ['$*\n$', '$*\n$'],
		  ['$\\alpha*$*', '$\\alpha\\*$*'],
		  ['$$', '$$'],
		];
    for (var j=0; j<inOut.length; j++) {
	var out = MDPreSpanGamut(inOut[j][0], null, true);
	if (out != inOut[j][1])
	    alert(" Error j="+j+": MDPreSpantest('"+inOut[j][0]+"') yields '"+out+"', but expected '"+inOut[j][1]+"'");
    }
}

function MDEscapeBlock(whole, inner) {
        return "<blockquote>"+whole+"</blockquote>\n";
}

function MDPreBlockGamut(text, runBlockGamut) {
    return text.replace(/^ {0,3}\\\[ *\n((?:.*?\n)+?) {0,3}\\\] *$/gm, MDEscapeBlock).replace(/^ {0,3}~D~D *\n((?:.*?\n)+?) {0,3}~D~D *$/gm, MDEscapeBlock)
}

function MDConverter(mdText, stripOuter) {
    var html = window.PagedownConverter ? window.PagedownConverter.makeHtml(mdText) : '<pre>'+escapeHtml(mdText)+'</pre>';
    if (stripOuter && html.substr(0,3) == "<p>" && html.substr(html.length-4) == "</p>") {
	    html = html.substr(3, html.length-7);
    }
    return html.replace(/<a href=([^> ]+)>/g, '<a href=$1 target="_blank">');
}

////////////////////////////////////////////////////////////
// Section 23: Linear Congruential Random Number Generator
//  https://gist.github.com/Protonk/5367430
////////////////////////////////////////////////////////////

var LCRandom = (function() {
  // Set to values from http://en.wikipedia.org/wiki/Numerical_Recipes
      // m is basically chosen to be large (as it is the max period)
      // and for its relationships to a and c
  var nbytes = 4;
  var sequences = {};
  var m = Math.pow(2,nbytes*8),
      // a - 1 should be divisible by m's prime factors
      a = 1664525,
      // c and m should be co-prime
      c = 1013904223;
  function makeSeed(val) {
      return val ? (val % m) : Math.round(Math.random() * m);
  }
  function setSeed(seedValue) {
      // Start new random number sequence using seed value as the label
      // or a new random seed, if seed value is null
      var label = seedValue || '';
      sequences[label] = makeSeed(seedValue);
      return label;
  }
  function uniform(seedValue) {
      // define the recurrence relationship
      var label = seedValue || '';
      if (!(label in sequences))
	  throw('Random number generator not initialized properly:'+label);
      sequences[label] = (a * sequences[label] + c) % m;
      // return a float in [0, 1) 
      // if sequences[label] = m then sequences[label] / m = 0 therefore (sequences[label] % m) / m < 1 always
      return sequences[label] / m;
  }
  return {
    makeSeed: makeSeed,

    setSeed: setSeed,

    randomNumber: function(seedValue, min, max) {
	// Equally probable integer values between min and max (inclusive)
	// If min is omitted, equally probable integer values between 1 and max
	// If both omitted, value uniformly distributed between 0.0 and 1.0 (<1.0)
	if (!isNumber(min))
	    return uniform(seedValue);
	if (!isNumber(max)) {
	    max = min;
	    min = 1;
	}
	return Math.min(max, Math.floor( min + (max-min+1)*uniform(seedValue) ));
    }
  };
}());

/////////////////////////////////////////////////////////////////////////
// Section 24: Detect swipe events
// Modified from https://blog.mobiscroll.com/working-with-touch-events/
/////////////////////////////////////////////////////////////////////////

var touchStart,
    touchAction,
    touchDiffX,
    touchDiffY,
    touchEndX,
    touchEndY,
    touchScroll,
    touchSort,
    touchStartX,
    touchStartY,
    touchSwipe,
    sortTimer;

function getCoord(evt, c) {
    return /touch/.test(evt.type) ? (evt.originalEvent || evt).changedTouches[0]['page' + c] : evt['page' + c];
}

function testTouch(evt) {
    if (evt.type == 'touchstart') {
        touchStart = true;
    } else if (touchStart) {
        touchStart = false;
        return false;
    }
    return true;
}
 
function onTouchStart(evt) {
    Slidoc.log('onTouchStart:');
    if (testTouch(evt) && !touchAction) {
        touchAction = true;

        touchStartX = getCoord(evt, 'X');
        touchStartY = getCoord(evt, 'Y');
        touchDiffX = 0;
        touchDiffY = 0;
 
        sortTimer = setTimeout(function () {
            ///touchSort = true;  // Commented out (no sort events)
        }, 200);
 
        if (evt.type == 'mousedown') {
	    document.addEventListener('mousemove', onTouchMove);
	    document.addEventListener('mouseup', onTouchEnd);
        }
    }
}

var scrollThresholdY = 15;   // Try 10, 15, ...
var swipeThresholdX = 7;     // Try 7, ...
 
function onTouchMove(evt) {
    if (touchAction) {
        touchEndX = getCoord(evt, 'X');
        touchEndY = getCoord(evt, 'Y');
        touchDiffX = touchEndX - touchStartX;
        touchDiffY = touchEndY - touchStartY;
        Slidoc.log('onTouchMove: dx, dy, sort, swipe, scroll', touchDiffX, touchDiffY, touchSort, touchSwipe, touchScroll);
 
        if (!touchSort && !touchSwipe && !touchScroll) {
            if (Math.abs(touchDiffY) > scrollThresholdY && Math.abs(touchDiffY) > 0.5*Math.abs(touchDiffX)) { // It's a scroll
                touchScroll = true;
            } else if (Math.abs(touchDiffX) > swipeThresholdX) { // It's a swipe
                touchSwipe = true;
            }
        }
 
        if (touchSwipe) {
            evt.preventDefault(); // Kill page scroll
            // Handle swipe
            // ...
        }
 
        if (touchSort) {
            evt.preventDefault(); // Kill page scroll
            // Handle sort
            // ....
        }
 
        if (Math.abs(touchDiffX) > 5 || Math.abs(touchDiffY) > 5) {
            clearTimeout(sortTimer);
        }
    }
}
 
function onTouchEnd(evt) {
    Slidoc.log('onTouchEnd: dx, dy, sort, swipe, scroll, action', touchDiffX, touchDiffY, touchSort, touchSwipe, touchScroll, touchAction);
    if (touchAction) {
        touchAction = false;
 
        if (touchSwipe) {
            // Handle swipe end
            if ( touchDiffX > 0 ) {
		/* right swipe (leftward motion) */
		Slidoc.handleKey('left', true);
            } else {
		/* left swipe (right motion) */ 
		Slidoc.handleKey('right', true);
	    }
        } else if (touchSort) {
            // Handle sort end
            // ...
        } else if (!touchScroll && Math.abs(touchDiffX) < 5 && Math.abs(touchDiffY) < 5) { // Tap
            ///if (evt.type === 'touchend') { // Prevent phantom clicks
            ///    evt.preventDefault();
            ///}
            // Handle tap
            // ...
        }
 
        touchSwipe = false;
        touchSort = false;
        touchScroll = false;
 
        clearTimeout(sortTimer);
 
        if (evt.type == 'mouseup') {
	    document.removeEventListener('mousemove', onTouchMove);
	    document.removeEventListener('mouseup', onTouchEnd);
        }
    }
}

var useAltTouchHandler = true;

if (useAltTouchHandler) {
    // Alternate touch handler
    document.addEventListener('touchstart', onTouchStart, false);      
    ///document.addEventListener('mousedown', onTouchStart, false);  // Detecting mouse triggers swipes during copy operation
    document.addEventListener('touchmove', onTouchMove, false);
    document.addEventListener('touchend', onTouchEnd, false);
    document.addEventListener('touchcancel', onTouchEnd, false);
} else {
    // Primary touch handler
    document.addEventListener('touchstart', handleTouchStart, false);        
    document.addEventListener('touchmove', handleTouchMove, false);
    document.addEventListener('touchend', handleTouchEnd, false);
}

// http://stackoverflow.com/questions/2264072/detect-a-finger-swipe-through-javascript-on-the-iphone-and-android

var swipeThreshold = 30;
var xDown = null;                                                        
var yDown = null;                                                        
var xDiff = 0;
var yDiff = 0;

function handleTouchStart(evt) {                                         
    xDown = evt.touches[0].clientX;                                      
    yDown = evt.touches[0].clientY;                                      
};                                                

function handleTouchMove(evt) {
    if (!xDown || !yDown) {
        return;
    }

    var xUp = evt.touches[0].clientX;                                    
    var yUp = evt.touches[0].clientY;

    xDiff = xDown - xUp;
    yDiff = yDown - yUp;
    return;
}

function handleTouchEnd(evt) {
    if (!xDiff && !yDiff)
	return;

    if ( Math.abs( xDiff ) > Math.abs( yDiff ) ) { /* Slope */
	if (Math.abs(xDiff) < swipeThreshold) {
	    /* ignore */
        } else if ( xDiff > 0 ) {
            /* left swipe (right motion) */ 
            return Slidoc.handleKey('right', true);
        } else {
            /* right swipe (leftward motion) */
            return Slidoc.handleKey('left', true);
        }                       
    } else {
	if (Math.abs(yDiff) < swipeThreshold) {
	    /* ignore */
        } else if ( yDiff > 0 ) {
            /* up swipe (downward motion) */ 
        } else { 
            /* down swipe (upward motion) */
        }                                                                 
    }
    /* reset values */
    xDown = null;
    yDown = null;                                             
    xDiff = 0;
    yDiff = 0;
    return;
};

///UNCOMMENT: })(Slidoc);
