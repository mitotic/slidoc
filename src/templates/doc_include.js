// JS include file for slidoc

///////////////////////////////
// Section 1: Configuration
///////////////////////////////

var Slidoc = {};  // External object

Slidoc.PluginDefs = {};    // JS plugin definitions
Slidoc.PluginManager = {}; // JS plugins manager
Slidoc.Plugins = null;     // JS plugin instances
Slidoc.Random = null;

///UNCOMMENT: (function(Slidoc) {

var MAX_INC_LEVEL = 9;            // Max. incremental display level
var MIN_ANSWER_NOTES_DELAY = 5;   // Minimum delay (sec) when displaying notes after answering question
var MAX_SYS_ERROR_RETRIES = 5;    // Maximum number of system error retries

var CACHE_GRADING = true; // If true, cache all rows for grading

var PLUGIN_RE = /^(.*)=\s*(\w+)\.(expect|response)\(\s*(\d*)\s*\)$/;
var QFIELD_RE = /^q(\d+)_([a-z]+)$/;

var BASIC_PACE    = 1;
var QUESTION_PACE = 2;
var ADMIN_PACE    = 3;

Slidoc.PluginManager.BASIC_PACE    = 1;  // Move to Slidoc.BASIC_PACE ...?
Slidoc.PluginManager.QUESTION_PACE = 2;
Slidoc.PluginManager.ADMIN_PACE    = 3;

var SKIP_ANSWER = 'skip';

var LATE_SUBMIT = 'late';
var PARTIAL_SUBMIT = 'partial';

var SYMS = {correctMark: '&#x2714;', partcorrectMark: '&#x2611;', wrongMark: '&#x2718;', anyMark: '&#9083;', xBoxMark: '&#8999;',
	    xMark: '&#x2A2F'};

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

/////////////////////////////////////
// Section 2: Global initialization
/////////////////////////////////////

var Sliobj = {}; // Internal object
Sliobj.logSheet = null;

Sliobj.params = JS_PARAMS_OBJ;
Sliobj.sessionName = Sliobj.params.paceLevel ? Sliobj.params.fileName : '';

Sliobj.gradeFieldsObj = {};
for (var j=0; j<Sliobj.params.gradeFields.length; j++)
    Sliobj.gradeFieldsObj[Sliobj.params.gradeFields[j]] = 1;

Sliobj.interactive = false;
Sliobj.adminState = null;
Sliobj.firstTime = true;
Sliobj.closePopup = null;
Sliobj.popupEvent = '';
Sliobj.activePlugins = {};
Sliobj.pluginList = [];
Sliobj.pluginSetup = null;
Sliobj.slidePlugins = null;
Sliobj.answerPlugins = null;
Sliobj.incrementPlugins = null;
Sliobj.buttonPlugins = null;
Sliobj.delaySec = null;
Sliobj.scores = null;
Sliobj.liveResponses = {};

Sliobj.errorRetries = 0;

Sliobj.seedOffset = {randomChoice: 1, plugins: 1000};  // Used to offset the session randomSeed to generate new seeds

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
    var debugging = Sliobj.params.debug || Sliobj.adminState || getUserId() == Sliobj.params.testUserId;
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
	if (Sliobj.params.paceLevel >= ADMIN_PACE && retStatus.info.adminPaced)
	    Sliobj.adminPaced = retStatus.info.adminPaced;
	if (retStatus.info.maxLastSlide)
	    Sliobj.maxLastSlide = retStatus.info.maxLastSlide;
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
		    Sliobj.userList.push(id);
		    Sliobj.userGrades[id] = {index: j+1, name: roster[j][0], team: roster[j][2], submitted:null, grading: null};
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
    Slidoc.remoteLog('sessionAbort', '', err_msg, err_trace);
    if (sessionAborted)
	return;
    sessionAborted = true;
    localDel('auth');
    try { Slidoc.classDisplay('slidoc-slide', 'none'); } catch(err) {}
    alert((Sliobj.params.debug ? 'DEBUG: ':'')+err_msg);
    if (!Sliobj.params.debug)
	document.body.textContent = err_msg + ' (reload page to restart)   '+(err_trace || '');

    if (getServerCookie()) {
	if (!Sliobj.params.debug || window.confirm('Log out user?'))
	    location.href = Slidoc.logoutURL;
    }

    throw(err_msg);
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
    if (!isHeadless)
	window.localStorage['slidoc_'+key] = JSON.stringify(obj);
}

function localDel(key) {
    if (!isHeadless)
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

function getServerCookie() {
    var slidocCookie = getCookieValue("slidoc_server", true);
    if (!slidocCookie)
	return null;
    
    var comps = slidocCookie.split(":");
    for (var j=0; j<comps.length; j++)
	comps[j] = decodeURIComponent(comps[j]);
    return {user:   comps[0],
	    origid: comps.length > 1 ? comps[1] : '',
	    token:  comps.length > 2 ? comps[2] : '',
     	    name:   comps.length > 3 ? comps[3] : '',
     	    email:  comps.length > 4 ? comps[4] : '',
     	    altid:  comps.length > 5 ? comps[5] : ''
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

Slidoc.websocketPath = '';
if (Sliobj.params.gd_sheet_url && Sliobj.params.gd_sheet_url.slice(0,1) == '/') {
    // Proxy URL
    if (getServerCookie())
	Slidoc.websocketPath = Sliobj.params.gd_sheet_url+location.pathname;
    else
	sessionAbort('Error: File must be served from proxy server for websocket authentication');
}

Slidoc.logoutURL = "/_auth/logout/";
Slidoc.getServerCookie = getServerCookie;
Slidoc.getParameter = getParameter;

var resetParam = getParameter('reset');
if (resetParam) {
    if (resetParam == 'all' && window.confirm('Reset all local sessions?')) {
	localDel('auth');
	localDel('sessions');
	alert('All local sessions reset');
	location = location.href.split('?')[0];
    } else if (window.confirm('Reset session '+Sliobj.params.fileName+'?')) {
	localDel('auth');
	var sessionObj = localGet('sessions');
	delete sessionObj[Sliobj.params.fileName];
	localPut('sessions', sessionObj);
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
    if (document.getElementById("slidoc-contents-button") && !document.getElementById("slidoc-topnav"))
	document.getElementById("slidoc-contents-button").style.display = null;
    if (!Sliobj.params.fileName)   // Just a simple web page
	return;
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
    if (window.MathJax)
	MathJax.Hub.Queue(["Typeset", MathJax.Hub]);

    if (Sliobj.params.gd_client_id) {
	// Google client load will authenticate
    } else if (Sliobj.params.gd_sheet_url) {
	var localAuth = localGet('auth');
	if (localAuth && !getServerCookie()) {
	    Slidoc.showPopup('Accessing Google Docs ...', null, null, 1000);
	    GService.gprofile.auth = localAuth;
	    Slidoc.slidocReady(localAuth);
	} else {
	    if (!getServerCookie())
		Slidoc.reportTestAction('loginPrompt');
	    GService.gprofile.promptUserInfo(Sliobj.params.authType);
	}
    } else {
	Slidoc.slidocReady(null);
    }
}

//////////////////////////////////
// Section 9: Utility functions
//////////////////////////////////

function cmp(a,b) { if (a == b) return 0; else return (a > b) ? 1 : -1; }

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
	return new Date(dateStr);
    } catch(err) {
	return null;
    }
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
    randFunc = randFunc || Math.random;
    for (var i = array.length - 1; i > 0; i--) {
        var j = Math.floor(randFunc() * (i + 1));
        var temp = array[i];
        array[i] = array[j];
        array[j] = temp;
    }
    return array;
}

function randomLetters(n, randFunc) {
    var letters = [];
    for (var i=0; i < n; i++)
	letters[i] = letterFromIndex(i);
    shuffleArray(letters, randFunc);
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
    return unsafe
         .replace(/&/g, "&amp;")
         .replace(/</g, "&lt;")
         .replace(/>/g, "&gt;");
}

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

function requestFullscreen(element) {
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

function exitFullscreen() {
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

Slidoc.docFullScreen = function (exit) {
    if (exit)
	exitFullscreen();
    else
	requestFullscreen(document.documentElement);
}

Slidoc.switchNav = function () {
    var elem = document.getElementById("slidoc-topnav");
    if (elem.className === "slidoc-topnav") {
        elem.className += " slidoc-responsive";
    } else {
        elem.className = "slidoc-topnav";
    }
}

Slidoc.userLogout = function () {
    if (!window.confirm('Do want to logout user '+GService.gprofile.auth.id+'?'))
	return false;
    localDel('auth');
    sessionAbort('Logged out');
}

Slidoc.userLogin = function (msg, retryCall) {
    Slidoc.log('Slidoc.userLogin:', msg, retryCall);
    if (getServerCookie())
	sessionAbort(msg || 'Error in authentication');
    else
	GService.gprofile.promptUserInfo(GService.gprofile.auth.type, GService.gprofile.auth.id, msg||'', Slidoc.userLoginCallback.bind(null, retryCall||null));
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

Slidoc.resetPaced = function () {
    Slidoc.log('Slidoc.resetPaced:');
    var userId = window.GService && GService.gprofile && GService.gprofile.auth && GService.gprofile.auth.id;
    if (!Slidoc.testingActive() && !window.confirm('Confirm that you want to completely delete all answers/scores for user '+userId+' in session '+Sliobj.sessionName+'?'))
	return false;

    if (Sliobj.params.gd_sheet_url) {
	if (!Sliobj.adminState && userId != Sliobj.params.testUserId) {
	    alert('Unable to reset session linked to Google Docs');
	    return false;
	}

	if (Sliobj.params.paceLevel >= ADMIN_PACE && Sliobj.session.submitted) {
	    alert('Cannot reset submitted instructor-paced session');
	    return false;
	}

	if (!Slidoc.testingActive() && !window.confirm('Re-confirm session reset for user '+userId+'?'))
	    return false;
	var gsheet = getSheet(Sliobj.sessionName);
	gsheet.delRow(userId, resetSessionCallback); // Will reload page after delete

    } else {
	Sliobj.session = createSession();
	Sliobj.feedback = null;
	sessionPut();
    }

    if (!Slidoc.testingActive())
	location.reload(true);
}

function resetSessionCallback() {
    Slidoc.log('resetSessionCallback:');
    location.reload(true);
}

Slidoc.showConcepts = function (msg) {
    var firstSlideId = getVisibleSlides()[0].id;
    var attr_vals = getChapterAttrs(firstSlideId);
    var chapter_id = parseSlideId(firstSlideId)[0];
    var questionConcepts = [];
    for (var j=0; j<attr_vals.length; j++) {
	var question_attrs = attr_vals[j];
	var slide_id = chapter_id + '-' + zeroPad(question_attrs.slide, 2);
	var concept_elem = document.getElementById(slide_id+"-concepts");
	questionConcepts.push( concept_elem ? concept_elem.textContent.trim().split('; ') : [] );
    }
    var missedConcepts = trackConcepts(Sliobj.scores.qscores, questionConcepts, Sliobj.allQuestionConcepts)

    var html = msg || '';
    if (Sliobj.allQuestionConcepts.length && !controlledPace()) {
	html += '<b>Question Concepts</b><br>';
	var labels = ['Primary concepts missed', 'Secondary concepts missed'];
	for (var m=0; m<labels.length; m++)
	    html += labels[m]+conceptStats(Sliobj.allQuestionConcepts[m], missedConcepts[m])+'<p></p>';
    }
    Slidoc.showPopup(html || (Sliobj.session.lastSlide ? 'Not tracking concepts!' : 'Concepts tracked only in paced mode!') );
}

Slidoc.prevUser = function () {
    if (!Sliobj.gradingUser)
	return;
    Slidoc.nextUser(false);
}

Slidoc.slideViewIncrement = function () {
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

///////////////////////////////
// Section 10: Help display
///////////////////////////////

var Slide_help_list = [
    ['q, Escape',           'exit',  'exit slide mode'],
    ['h, Home, Fn&#9668;',  'home',  'home (first) slide'],
    ['e, End, Fn&#9658;',   'end',   'end (last) slide'],
    ['p, &#9668;',          'left',  'previous slide'],
    ['n, &#9658;, space',   'right', 'next slide'],
    ['i, &#9660;',          'i',     'incremental item'],
    ['f',                   'f',     'fullscreen mode'],
    ['m',                   'm',     'missed question concepts'],
    ['?',                   'qmark', 'help']
    ]

Slidoc.viewHelp = function () {
    var html = '';
    var hr = '<tr><td colspan="3"><hr></td></tr>';
    var userId = window.GService && GService.gprofile && GService.gprofile.auth && GService.gprofile.auth.id;
    if (Sliobj.sessionName) {
	if (userId)
	    html += 'User: <b>'+userId+'</b> (<span class="slidoc-clickable" onclick="Slidoc.userLogout();">logout</span>)<br>';
	if (Sliobj.session && Sliobj.session.team)
	    html += 'Team: ' + Sliobj.session.team + '<br>';
	html += '<p></p>Session: <b>' + Sliobj.sessionName + '</b>';
	if (Sliobj.session && Sliobj.session.revision)
	    html += ', ' + Sliobj.session.revision;
	if (Sliobj.params.questionsMax)
	    html += ' (' + Sliobj.params.questionsMax + ' questions)';
	if (Sliobj.params.gd_sheet_url && Sliobj.session)
	    html += Sliobj.session.submitted ? ', Submitted '+parseDate(Sliobj.session.submitted) : ', NOT SUBMITTED';
	html += '<br>';
	if (Sliobj.dueDate)
	    html += 'Due: <em>'+Sliobj.dueDate+'</em><br>';
	if (Sliobj.voteDate)
	    html += 'Submit Likes by: <em>'+Sliobj.voteDate+'</em><br>';
	if (Sliobj.params.gradeWeight && Sliobj.feedback && 'q_grades' in Sliobj.feedback && Sliobj.feedback.q_grades != null)
	    html += 'Grades: '+Sliobj.feedback.q_grades+'/'+Sliobj.params.gradeWeight+'<br>';
    } else {
	var cookieUserInfo = getServerCookie();
	if (cookieUserInfo)
	    html += 'User: <b>'+cookieUserInfo.user+'</b> (<a class="slidoc-clickable" href="'+Slidoc.logoutURL+'">logout</a>)<br>';
    }
    html += '<table class="slidoc-slide-help-table">';
    if (!Sliobj.chainActive && Sliobj.params.paceLevel && (!Sliobj.params.gd_sheet_url || userId == Sliobj.params.testUserId || Sliobj.adminState))
	html += formatHelp(['', 'reset', 'Reset paced session']) + hr;

    if (userId == Sliobj.params.testUserId || Sliobj.adminState)
	html += '<p></p><a class="slidoc-clickable" target="_blank" href="/_dash">Dashboard</a><br>';
    else if (Sliobj.params.gd_sheet_url)
	html += '<p></p><span class="slidoc-clickable" onclick="Slidoc.showGrades();">View gradebook</span><p></p>';

    if (Sliobj.currentSlide) {
	for (var j=0; j<Slide_help_list.length; j++)
	    html += formatHelp(Slide_help_list[j]);
    } else if (Sliobj.params.fileName) {
	html += formatHelp(['Escape', 'unesc', 'enter slide mode']);
    }
    html += '</table>';
    Slidoc.showPopup(html);
}

function formatHelp(help_entry) {  // help_entry = [keyboard_shortcuts, key_code, description]
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
    'right': function() { Slidoc.slideViewGo(true); },
    'n':     function() { Slidoc.slideViewGo(true); },
    'space': function() { Slidoc.slideViewGo(true); },
    'up':    Slidoc.prevUser,
    'down':  Slidoc.slideViewIncrement,
    'i':     Slidoc.slideViewIncrement,
    'f':     Slidoc.docFullScreen,
    'm':     Slidoc.showConcepts,
    'qmark': Slidoc.viewHelp,
    'reset': Slidoc.resetPaced
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
    67: 'c',
    68: 'd',
    69: 'e',
    70: 'f',
    72: 'h',
    73: 'i',
    77: 'm',
    78: 'n',
    80: 'p',
    81: 'q',
    83: 's',
   191: 'qmark'
};

document.onkeydown = function(evt) {
    //Slidoc.log('document.onkeydown:', evt);
    if ((!Sliobj.currentSlide || Sliobj.questionSlide) && (evt.keyCode == 32 || evt.keyCode > 44))
	return;  // Handle printable input normally (non-slide view or question slide)

    var nodeName = evt.target.nodeName.toLowerCase();
    if ((nodeName == 'input' || nodeName == 'textarea') && evt.keyCode >= 32)
	return;  // Disable arrow key handling for input/textarea

    if (!(evt.keyCode in Key_codes))
	return;

    return Slidoc.handleKey(Key_codes[evt.keyCode]);
}

Slidoc.handleKey = function (keyName) {
    Slidoc.log('Slidoc.handleKey:', keyName);
    if (keyName == 'right' && Slidoc.advanceStep())
	return false;

    if (Sliobj.closePopup) {
	Sliobj.closePopup();
	if (keyName == 'esc' || keyName == 'q')
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

    } else {
	if (keyName == 'esc' || keyName == 'unesc')   { Slidoc.slideViewStart(); return false; }

	if (keyName == 'reset') { Slidoc.resetPaced(); return false; }
	
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
    var match = /(slidoc(\d+))(-(\d+))?$/.exec(slideId);
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
	if (!Sliobj.slidePlugins[slide_id]) {
	    Slidoc.log('Sliobj.eventReceiver: No plugins loaded for slide '+slide_id);
	    return;
	}
	for (var j=0; j<Sliobj.slidePlugins[slide_id].length; j++) {
	    if (Sliobj.slidePlugins[slide_id][j].name == pluginName)
		Slidoc.PluginManager.invoke.apply(null, [Sliobj.slidePlugins[slide_id][j], pluginMethodName].concat(eventArgs));
	}

    } else if (eventName == 'LiveResponse') {
	if (!(eventArgs[0] in Sliobj.liveResponses))
	    Sliobj.liveResponses[eventArgs[0]] = [];
	Sliobj.liveResponses[eventArgs[0]][eventSource] = eventArgs.slice(1);
	if (eventName == Sliobj.popupEvent && Sliobj.closePopup)
	    Sliobj.closePopup(true, eventName);
	    
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
    if (!isController() || Sliobj.session.submitted)
	return;
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    interactAux(!Sliobj.interactive);
}

function interactAux(active) {
    Slidoc.log('interactAux:', active, Sliobj.session.lastSlide);
    Sliobj.interactive = active;
    toggleClass(active, 'slidoc-interact-view');
    if (!Sliobj.interactive) {
	GService.requestWS('interact', ['', null], interactCallback);
	return;
    }
    if (!isController() || Sliobj.session.submitted)
	return;
    var lastSlideId = getVisibleSlides()[Sliobj.session.lastSlide-1].id;
    var qattrs = getQuestionAttrs(lastSlideId);
    if (qattrs && qattrs.qnumber in Sliobj.session.questionsAttempted)
	qattrs = null;
    GService.requestWS('interact', [lastSlideId, qattrs], interactCallback);
}

function interactCallback() {
    Slidoc.log('interactCallback:');
}

////////////////////////
// Section 11: Plugins
////////////////////////

function setupPlugins() {
    Slidoc.log('setupPlugins:');
    Sliobj.pluginSetup = {};
    Sliobj.activePlugins = {};
    Sliobj.pluginList = [];
    var allContent = document.getElementsByClassName('slidoc-plugin-content');
    for (var j=0; j<allContent.length; j++) {
	var pluginName = allContent[j].dataset.plugin;
	var slide_id = allContent[j].dataset.slideId;
	var args = decodeURIComponent(allContent[j].dataset.args || '');
	var button = decodeURIComponent(allContent[j].dataset.button || '');
	if (!(pluginName in Slidoc.PluginDefs)) {
	    // Look for plugin definition with trailing digit stripped out from name
	    if (isNumber(pluginName.slice(-1)) && (pluginName.slice(0,-1) in Slidoc.PluginDefs))
		Slidoc.PluginDefs[pluginName] = Slidoc.PluginDefs[pluginName.slice(0,-1)];
	    else
		sessionAbort('ERROR Plugin '+pluginName+' not defined properly; check for syntax error messages in Javascript console');
	}
	if (!(pluginName in Sliobj.activePlugins)) {
	    Sliobj.pluginList.push(pluginName);
	    Sliobj.activePlugins[pluginName] = {number: Sliobj.pluginList.length, args: {}, firstSlide: slide_id, button: {} };
	}
	Sliobj.activePlugins[pluginName].args[slide_id] = args;
	Sliobj.activePlugins[pluginName].button[slide_id] = button;
    }
    for (var j=0; j<Sliobj.pluginList.length; j++) {
	var pluginInstance = createPluginInstance(Sliobj.pluginList[j], true);
	Slidoc.PluginManager.optCall.apply(null, [pluginInstance, 'initSetup'].concat(pluginInstance.initArgs));
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
    if (!(pluginName in Slidoc.Plugins)) {
	Slidoc.log("Slidoc.PluginMethod: ERROR Plugin "+pluginName+" not activated");
	return;
    }

    var pluginInstance = Slidoc.Plugins[pluginName][slide_id || ''];
    if (!pluginInstance) {
	Slidoc.log("Slidoc.PluginMethod: ERROR Plugin "+pluginName+" instance not found for slide '"+slide_id+"'");
	return;
    }

    return Slidoc.PluginManager.invoke.apply(null, [pluginInstance, action].concat(extraArgs));
}

Slidoc.PluginManager.invoke = function (pluginInstance, action) //... extra arguments
{   // action == 'initSetup' initial setup after document is ready; may insert/modify DOM elements
    // action == 'initGlobal' resets global plugin properties for all slides (called at start/switch of session)
    // action == 'init' resets plugin properties for each slide (called at start/switch of session)
    // action == 'display' displays recorded user response (called at start/switch of session for each question)
    // action == 'disable' disables plugin (after user response has been recorded)
    // action == 'expect' returns expected correct answer
    // action == 'response' records user response and uses callback to return a pluginResp object of the form:
    //    {name:pluginName, score:1/0/0.75/.../null, invalid: invalid_msg, output:output, tests:0/1/2}

    var extraArgs = Array.prototype.slice.call(arguments).slice(2);
    Slidoc.log('Slidoc.PluginManager.invoke:', pluginInstance, action, extraArgs);

    if (!(action in pluginInstance)) {
	Slidoc.log('ERROR Plugin action '+pluginInstance.name+'.'+action+' not defined');
	return;
    }

    try {
	return pluginInstance[action].apply(pluginInstance, extraArgs);
    } catch(err) {
	sessionAbort('ERROR in invoking plugin '+pluginInstance.name+'.'+action+': '+err, err.stack);
    }
}

Slidoc.PluginManager.remoteCall = function (pluginName, pluginMethod, callback) { // Extra args
    Slidoc.log('Slidoc.PluginManager.remoteCall:',pluginName, pluginMethod);
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

Slidoc.PluginManager.graded = function() {
    return Sliobj.gradeDateStr;
}

Slidoc.PluginManager.submitted = function() {
    return Sliobj.session && Sliobj.session.submitted;
}

Slidoc.PluginManager.answered = function(qnumber) {
    return Sliobj.session && Sliobj.session.questionsAttempted[qnumber];
}

Slidoc.PluginManager.lateSession = function() {
    return Sliobj.session.lateToken == LATE_SUBMIT || Sliobj.session.lateToken == PARTIAL_SUBMIT;
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
    if (!argStr || !slide_id)
	return [];
    try {
	Slidoc.log('evalPluginArgs:', pluginName, argStr, slide_id);
	var pluginList = Sliobj.slidePlugins[slide_id]; // Plugins instantiated in the slide so far
	var SlidePlugins = {};
	for (var j=0; j<pluginList.length; j++)
	    SlidePlugins[pluginList[j].name] = pluginList[j];
	var argVals = eval('['+argStr+']');
	return argVals;
    } catch (err) {
	var errMsg = 'evalPluginArgs: ERROR in init('+argStr+') arguments for plugin '+pluginName+' in '+slide_id+': '+err;
	Slidoc.log(errMsg);
	alert(errMsg);
	return [argStr];
    }
}

function createPluginInstance(pluginName, nosession, slide_id, slideData) {
    Slidoc.log('createPluginInstance:', pluginName, nosession, slide_id);
    var pluginDef = Slidoc.PluginDefs[pluginName];
    if (!pluginDef) {
	Slidoc.log('ERROR Plugin '+pluginName+' not found; define using PluginDef/PluginEndDef');
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

    // Provide init args from first slide (as a string) where plugin occurs for initSetup/initGlobal
    if (slide_id)
	defCopy.initArgs = evalPluginArgs(pluginName, Sliobj.activePlugins[pluginName].args[slide_id], slide_id);
    else
	defCopy.initArgs = [ Sliobj.activePlugins[pluginName].args[ Sliobj.activePlugins[pluginName].firstSlide ] ];

    var auth = window.GService && GService.gprofile && GService.gprofile.auth;
    defCopy.userId = auth ? auth.id : null;
    defCopy.displayName = auth ? auth.displayName : null;
    defCopy.adminState = Sliobj.adminState;
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
	defCopy.setup = Sliobj.pluginSetup[pluginName];

	if (!(pluginName in Slidoc.Plugins))
	    Slidoc.Plugins[pluginName] = {};

	if (!(pluginName in Sliobj.session.plugins))
	    Slidoc.log('ERROR: Persistent plugin store not found for plugin '+pluginName);
	
	defCopy.persist = Sliobj.session.plugins[pluginName];
	defCopy.paced = Sliobj.session.paced;

	var pluginNumber = Sliobj.activePlugins[pluginName].number;
	if (!slide_id) {
	    // Global seed for all instances of the plugin
	    defCopy.global = null;
	    defCopy.slideId = '';
	    defCopy.randomSeed = getRandomSeed(Sliobj.seedOffset.plugins + pluginNumber);
	    defCopy.randomNumber = makeRandomFunction(defCopy.randomSeed);
	} else {
	    // Seed for each slide instance of the plugin
	    defCopy.global = Slidoc.Plugins[pluginName][''];
	    defCopy.slideId = slide_id;
	    var comps = parseSlideId(slide_id);
	    defCopy.randomSeed = getRandomSeed(Sliobj.seedOffset.plugins + pluginNumber + 256*((1+comps[1])*256 + comps[2]));
	    defCopy.randomNumber = makeRandomFunction(defCopy.randomSeed);
	    defCopy.pluginId = slide_id + '-plugin-' + pluginName;
	    defCopy.qattributes = getQuestionAttrs(slide_id);
	    defCopy.correctAnswer = null;
	    if (defCopy.qattributes && defCopy.qattributes.correct) {
		// Correct answer: ans+/-err=plugin.response()
		var comps = defCopy.qattributes.correct.split('=');
		defCopy.correctAnswer = comps[0];
	    }
	}
    }
    var pluginClass = object2Class(defCopy);
    var pluginInstance = new pluginClass();
    if (nosession)
	Sliobj.pluginSetup[pluginName] = pluginInstance;
    else if (!slide_id)
	Slidoc.Plugins[pluginName][''] = pluginInstance;
    else
	Slidoc.Plugins[pluginName][slide_id] = pluginInstance;

    return pluginInstance;
}

//////////////////////////////////
// Section 12: Helper functions
//////////////////////////////////

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
    if (!auth.adminKey) {
	sessionAbort('Only admin can pick user');
    }
    GService.switchUser(auth, userId);

    if (callback) {
	callback(auth);  // Usually callback slidocReadyAux1
    } else {
	var gsheet = getSheet(Sliobj.sessionName);
	gsheet.getRow(userId, {}, selectUserCallback.bind(null, userId));
    }
}

function selectUserCallback(userId, result, retStatus) {
    Slidoc.log('selectUserCallback:', userId, result, retStatus);
    if (!result) {
	sessionAbort('ERROR in selectUserCallback: '+ retStatus.error);
    }
    Slidoc.reportTestAction('selectUser');
    var unpacked = unpackSession(result);
    Sliobj.session = unpacked.session;
    Sliobj.feedback = unpacked.feedback || null;
    Sliobj.score = null;
    scoreSession(Sliobj.session);
    Slidoc.showScore();
    Sliobj.userGrades[userId].weightedCorrect = Sliobj.scores.weightedCorrect;
    if (Sliobj.scores.weightedCorrect)
	updateGradingStatus(userId);
    prepGradeSession(Sliobj.session);
    initSessionPlugins(Sliobj.session);
    showSubmitted();
    preAnswer();
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

Slidoc.showGrades = function () {
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    var userId = GService.gprofile.auth.id;
    Sliobj.scoreSheet.getRow(userId, {getstats: 1}, showGradesCallback.bind(null, userId));
}

function showGradesCallback(userId, result, retStatus) {
    Slidoc.log('showGradesCallback:', userId, result, retStatus);
    if (!result) {
	alert('No grades found for user '+userId);
	return;
    }
    var sessionKeys = [];
    var keys = Object.keys(result);
    for (var j=0; j<keys.length; j++) {
	if (keys[j].slice(0,1) == '_')
	    sessionKeys.push(keys[j]);
    }
    sessionKeys.sort();
    var html = 'Grades for user <b>'+userId+'</b><p></p>';
    if (result.sessionCount)
	html += 'Session count: <b>'+result.sessionCount+'</b><p></p>';
    if (result.weightedTotal)
	html += 'Weighted total: <b>'+result.weightedTotal+'</b><br>';
    for (var j=0; j<sessionKeys.length; j++) {
	var grade = result[sessionKeys[j]];
	if (isNumber(grade))
	    grade = grade.toFixed(2);
	html += '&nbsp;&nbsp;&nbsp;' + sessionKeys[j].slice(1) + ': <b>'+ (grade == ''?'missed':grade) +'</b>'
	if (retStatus && retStatus.info && retStatus.info.headers) {
	    var sessionIndex = retStatus.info.headers.indexOf(sessionKeys[j]);
	    if (retStatus.info.curve && retStatus.info.curve[sessionIndex].charAt(0) == '^')
		html += ' curved out of 100';
	    else if (retStatus.info.maxScores)
		html += ' out of '+retStatus.info.maxScores[sessionIndex];

	    if (retStatus.info.averages) {
		var temAvg = retStatus.info.averages[sessionIndex];
		if (isNumber(temAvg))
		    html += ' (average='+temAvg.toFixed(2)+')';
	    }
	}
	html += '<br>';
    }
    Slidoc.showPopup(html);
}

//////////////////////////////////////////////////////
// Section 13: Retrieve data needed for session setup
//////////////////////////////////////////////////////

Slidoc.slidocReady = function (auth) {
    Slidoc.log('slidocReady:', auth);
    Sliobj.adminState = auth && !!auth.adminKey;
    Sliobj.adminPaced = 0;
    Sliobj.maxLastSlide = 0;
    Sliobj.userList = null;
    Sliobj.userGrades = null;
    Sliobj.gradingUser = 0;
    Sliobj.indexSheet = null;
    Sliobj.scoreSheet = null;
    Sliobj.dueDate = null;
    Sliobj.gradeDateStr = '';
    Sliobj.voteDate = null;

    if (Sliobj.params.gd_sheet_url)
	Sliobj.scoreSheet = new GService.GoogleSheet(Sliobj.params.gd_sheet_url, Sliobj.params.score_sheet,
						     [], [], useJSONP);
    if (Sliobj.adminState) {
	Sliobj.indexSheet = new GService.GoogleSheet(Sliobj.params.gd_sheet_url, Sliobj.params.index_sheet,
						     Sliobj.params.indexFields.slice(0,2),
						     Sliobj.params.indexFields.slice(2), useJSONP);
	Sliobj.indexSheet.getRow(Sliobj.sessionName, {}, function (result, retStatus) {
	    if (result && result.gradeDate)
		Sliobj.gradeDateStr = result.gradeDate;
	});
    }

    if (Sliobj.params.remoteLogLevel && Sliobj.params.gd_sheet_url && !Sliobj.adminState) {
	Sliobj.logSheet = new GService.GoogleSheet(Sliobj.params.gd_sheet_url, Sliobj.params.log_sheet,
						     Sliobj.params.logFields.slice(0,2),
						     Sliobj.params.logFields.slice(2), useJSONP);
    }

    if (CACHE_GRADING && Sliobj.adminState && Sliobj.sessionName) {
	toggleClass(true, 'slidoc-admin-view');
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
	Sliobj.closePopup(true);
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

    Slidoc.Random = LCRandom;
    sessionManage();

    Slidoc.log("slidocReadyAux2:B", Sliobj.sessionName, Sliobj.params.paceLevel);
    if (Sliobj.sessionName) {
	// Paced named session
	if (Sliobj.params.gd_sheet_url && !auth) {
	    sessionAbort('Session aborted. Google Docs authentication error.');
	}

	if (Sliobj.adminState) {
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

    sessionGet(null, Sliobj.sessionName, {create: true, retry: 'ready'}, slidocSetup);
}

///////////////////////////////
// Section 14: Session setup
///////////////////////////////

function getUserId() {
    return window.GService && GService.gprofile && GService.gprofile.auth && GService.gprofile.auth.id;
}

function controlledPace() {
    // If test user has submitted, assume controlledPace
    return (Sliobj.params.paceLevel >= ADMIN_PACE && (getUserId() != Sliobj.params.testUserId || (Sliobj.session && Sliobj.session.submitted)));
}

function isController() {
    return (Sliobj.params.paceLevel >= ADMIN_PACE && !Sliobj.adminState && getUserId() == Sliobj.params.testUserId);
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

    if (Sliobj.adminState && !Sliobj.session) {
	sessionAbort('Admin user: session not found for user');
    }

    if (Sliobj.session.version != Sliobj.params.sessionVersion) {
	alert('Slidoc: session version mismatch; discarding previous session with version '+Sliobj.session.version);
	Sliobj.session = null;

    } else if (Sliobj.session.revision != Sliobj.params.sessionRevision) {
	alert('Slidoc: Revised session '+Sliobj.params.sessionRevision+' (discarded previous revision '+Sliobj.session.revision+')');
	Sliobj.session = null;

    } else if (!Sliobj.params.paceLevel && Sliobj.session.paced) {
	// Pacing cancelled for previously paced session
	Sliobj.session.paced = 0;

    } else if (Sliobj.params.paceLevel && !Sliobj.session.paced) {
	// Pacing completed; no need to hide chapters
	unhideChapters = true;
    }

    if (Sliobj.adminState) {
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
	    slides[j].style.display = 'block';
    } else if (Sliobj.session.paced >= QUESTION_PACE || (Sliobj.session.paced && !Sliobj.params.printable)) {
	// Unhide only paced slides
	for (var j=0; j<Sliobj.session.lastSlide; j++)
	    slides[j].style.display = 'block';
    } else {
	// Not paced or admin-paced; unhide all slides
	Slidoc.classDisplay('slidoc-slide', 'block');
    }

    if (!Sliobj.session) {
	// New paced session
	Sliobj.session = createSession();
	Sliobj.feedback = null;
	sessionPut(null, null, {retry: 'new'});
    }

    // DOM set-up and clean-up
    Slidoc.breakChain();

    // Remove all global views
    var bodyClasses = document.body.classList;
    for (var j=0; j<bodyClasses.length; j++)
	document.body.classList.remove(bodyClasses[j]);

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

    if (Sliobj.adminState)
    	toggleClass(true, 'slidoc-admin-view');

    if (Sliobj.params.gd_sheet_url)
	toggleClass(true, 'slidoc-remote-view');

    if (Sliobj.scores.questionsCount)
	Slidoc.showScore();

    if (Sliobj.session.submitted || Sliobj.adminState) // Suppress incremental display
	toggleClass(true, 'slidoc-completed-view');
    
    if (Sliobj.feedback) // If any non-null feedback, activate graded view
	toggleClass(true, 'slidoc-graded-view');

    if (document.getElementById("slidoc-topnav")) {
	//if (document.getElementById("slidoc-slideview-button"))
	//    document.getElementById("slidoc-slideview-button").style.display = 'none';
    }

    showSubmitted();

    // Setup completed; branch out
    Sliobj.firstTime = false;
    var toc_elem = document.getElementById("slidoc00");
    if (!toc_elem && Sliobj.session) {
	if (Sliobj.session.paced || Sliobj.session.submitted) {
	    var firstSlideId = getVisibleSlides()[0].id;
	    Sliobj.allQuestionConcepts = parseElem(firstSlideId+'-qconcepts') || [];
	}
	if (!isHeadless && Sliobj.session.paced) {
	    Slidoc.startPaced(); // This will call preAnswer later
	    return false;
	}
	preAnswer();
	if (isHeadless) {
	    // WORKAROUND: seems to fix wkhtmltopdf 'infinite' looping
	    var slideElems = document.getElementsByClassName('slidoc-slide');
	    for (var j=0; j<slideElems.length; j++)
		slideElems[j].classList.add('slidoc-answered-slideview');
	}
	if (Sliobj.adminState && Slidoc.testingActive())
	    Slidoc.slideViewStart();
    } else {
	clearAnswerElements();
    }

    // Not paced
    Slidoc.chainUpdate(location.search);
    if (toc_elem) {
	// Table of contents included in file
	var slideHash = (!Sliobj.session.paced && location.hash) ? location.hash : "#slidoc00";
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

    if ('slides_only' in Sliobj.params.features)
	Slidoc.slideViewStart();

    ///if (Slidoc.testingActive())
	///Slidoc.slideViewStart();
}

function prepGradeSession(session) {
    // Modify session for grading
    session.paced = 0; // Unpace session, but this update will not be saved to Google Docs
    session.submitted = session.submitted || 'GRADING'; // 'Complete' session, but these updates will not be saved to Google Docs
    session.lastSlide = Sliobj.params.pacedSlides;
}

function initSessionPlugins(session) {
    // Restore random seed for session
    Slidoc.log('initSessionPlugins:');
    Sliobj.slidePlugins = {};
    Sliobj.answerPlugins = {};
    Sliobj.incrementPlugins = {};
    Sliobj.buttonPlugins = {};
    Slidoc.Plugins = {};

    Sliobj.slidePlugins[''] = [];
    for (var j=0; j<Sliobj.pluginList.length; j++) {
	var pluginName = Sliobj.pluginList[j];
	var pluginInstance = createPluginInstance(pluginName);
	Sliobj.slidePlugins[''].push(pluginInstance);   // Use '' as slide_id for session plugins
	Slidoc.PluginManager.optCall.apply(null, [pluginInstance, 'initGlobal'].concat(pluginInstance.initArgs));
    }

    // Sort plugin content elements in order of occurrence
    // Need to call init method in sequence to preserve global random number generation order
    var allContent = document.getElementsByClassName('slidoc-plugin-content');
    var contentElems = [];
    for (var j=0; j<allContent.length; j++)
	contentElems.push(allContent[j]);

    contentElems.sort( function(a,b){return cmp(a.dataset.number, b.dataset.number);} );    

    var slideData = null;
    for (var j=0; j<contentElems.length; j++) {
	var contentElem = contentElems[j];
	var pluginName = contentElem.dataset.plugin;
	var slide_id = contentElem.dataset.slideId;
	if (!(slide_id in Sliobj.slidePlugins)) {
	    Sliobj.slidePlugins[slide_id] = [];
	    slideData = {};  // New object to share persistent data for slide
	}
	var pluginInstance = createPluginInstance(pluginName, false, slide_id, slideData);
	Sliobj.slidePlugins[slide_id].push(pluginInstance);
	if ('incrementSlide' in pluginInstance)
	    Sliobj.incrementPlugins[slide_id] = pluginInstance;
	if ('answerSave' in pluginInstance)
	    Sliobj.answerPlugins[slide_id] = pluginInstance;

	var button = Sliobj.activePlugins[pluginName].button[slide_id];
	if (button)
	    Sliobj.buttonPlugins[slide_id] = pluginInstance;
	Slidoc.PluginManager.optCall.apply(null, [pluginInstance, 'init'].concat(pluginInstance.initArgs));
    }
    expandInlineJS(document);
}

function expandInlineJS(elem, methodName, argVal) {
    Slidoc.log('expandInlineJS:', methodName);
    var jsSpans = elem.getElementsByClassName('slidoc-inline-js');
    for (var j=0; j<jsSpans.length; j++) {
	var jsFunc = jsSpans[j].dataset.slidocJsFunction;
	var jsArg = argVal || null;
	if (jsArg == null) {
	    jsArg = jsSpans[j].dataset.slidocJsArgument || null;
	    if (jsArg !== null)
		try {jsArg = parseInt(jsArg); } catch (err) { jsArg = null; }
	}
	var slide_id = '';
	for (var k=0; k<jsSpans[j].classList.length; k++) {
	    var refmatch = /slidoc-inline-js-in-(.*)$/.exec(jsSpans[j].classList[k]);
	    if (refmatch) {
		slide_id = refmatch[1];
		break;
	    }
	}
	var comps = jsFunc.split('.');
	if (!methodName || methodName == comps[1]) {
	    var val = Slidoc.PluginMethod(comps[0], slide_id, comps[1], jsArg);
	    if (val != null)
		jsSpans[j].innerHTML = val;
	}
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

function responseAvailable(session, qnumber) { // qnumber is optional
    // Returns true value if uploaded files are available for a particular question or for the whole session
    if (qnumber)
	return session.plugins.Upload && session.plugins.Upload[qnumber];
    else
	return session.plugins.Upload && Object.keys(session.plugins.Upload);
}

function checkGradingCallback(userId, result, retStatus) {
    Slidoc.log('checkGradingCallback:', userId, result, retStatus);
    if (!result) {
	sessionAbort('ERROR in checkGradingCallback: '+ retStatus.error);
    }
    var unpacked = unpackSession(result);
    checkGradingStatus(userId, unpacked.session, unpacked.feedback);
}

function checkGradingStatus(userId, session, feedback) {
    Slidoc.log('checkGradingStatus:', userId);
    if (Sliobj.userGrades[userId].needGrading)
	return;

    if (session.submitted && session.submitted != 'GRADING')
	Sliobj.userGrades[userId].submitted = session.submitted;
    else
	Sliobj.userGrades[userId].submitted = null;

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
		// set grade to zero to avoid blank cells in computation
		if ('gweight' in question_attrs)
		    updates[gradeField] = 0;

		if (question_attrs.qtype.match(/^(text|Code)\//) || question_attrs.explain)
		    updates[commentsField] = 'Not attempted';
	    }
	}
    }
    Slidoc.log('checkGradingStatus:B', need_grading, updates);

    if (!Object.keys(need_grading).length && !Sliobj.userGrades[userId].submitted)
	Sliobj.userGrades[userId].needGrading = null;
    else
	Sliobj.userGrades[userId].needGrading = need_grading;

    // Admin can modify grade columns only for submitted sessions before 'effective' due date
    // and only for non-late submissions thereafter
    var allowGrading = Sliobj.userGrades[userId].submitted || (Slidoc.PluginManager.pastDueDate() && Sliobj.session.lateToken != LATE_SUBMIT);

    Sliobj.userGrades[userId].allowGrading = allowGrading;

    updateGradingStatus(userId);

    if (need_updates && allowGrading) {
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
    var text = Sliobj.userGrades[userId].index+'. '+Sliobj.userGrades[userId].name+' ';
    if (Sliobj.userGrades[userId].team)
	text += '('+Sliobj.userGrades[userId].team+') ';
    var html = ''
    var gradeCount = Sliobj.userGrades[userId].needGrading ? Object.keys(Sliobj.userGrades[userId].needGrading).length : 0;
    if (Sliobj.userGrades[userId].needGrading) {
	if (Sliobj.userGrades[userId].submitted)
	    html += gradeCount ? (gradeCount+' '+SYMS.anyMark) : SYMS.correctMark;
	else if (Sliobj.userGrades[userId].allowGrading)
	    html += gradeCount ? (gradeCount+' '+SYMS.xMark) : SYMS.correctMark;
	else
	    html += gradeCount
    }
    if (Sliobj.userGrades[userId].weightedCorrect)
	html += ' (' + Sliobj.userGrades[userId].weightedCorrect + ')';

    option.dataset.nograding = (Sliobj.userGrades[userId].allowGrading && gradeCount) ? '' : 'nograding';
    option.innerHTML = '';
    option.appendChild(document.createTextNode(text));
    option.innerHTML += html;
}

function scoreSession(session) {
    // Tally of scores
    Slidoc.log('scoreSession:');
    var firstSlideId = getVisibleSlides()[0].id;
    Sliobj.scores = tallyScores(getChapterAttrs(firstSlideId), session.questionsAttempted, session.hintsUsed,
				Sliobj.params);
}

function preAnswer() {
    // Pre-answer questions (and display notes for those)
    Slidoc.log('preAnswer:');
    var firstSlideId = getVisibleSlides()[0].id;
    var attr_vals = getChapterAttrs(firstSlideId);
    var chapter_id = parseSlideId(firstSlideId)[0];
    clearAnswerElements();

    if ('randomize_choice' in Sliobj.params.features && Sliobj.session) {
	// Handle choice randomization
	var newShuffle = {};
	var qShuffle = Sliobj.session.questionShuffle || null;
	var randFunc = makeRandomFunction(getRandomSeed(Sliobj.seedOffset.randomChoice));
	for (var qnumber=1; qnumber <= attr_vals.length; qnumber++) {
	    var question_attrs = attr_vals[qnumber-1];
	    if (!(question_attrs.qtype == 'choice' || question_attrs.qtype == 'multichoice'))
		continue
	    // Choice question
	    var slide_id = chapter_id + '-' + zeroPad(question_attrs.slide, 2);
	    var shuffleStr = qShuffle ? (qShuffle[qnumber]||'') : '';
	    if (Sliobj.adminState) {
		if (shuffleStr) {
		    var shuffleDiv = document.getElementById(slide_id+'-choice-shuffle');
		    if (shuffleDiv)
			shuffleDiv.innerHTML = '<code>(Shuffled: '+shuffleStr+')</code>';
		}
		
	    } else if (!qShuffle) {
		// Randomize choice
		var choices = document.getElementsByClassName(slide_id+"-choice-elem");
		shuffleStr = Math.floor(2*randFunc());
		shuffleStr += randomLetters(choices.length, randFunc);
		newShuffle[qnumber] = shuffleStr;
	    }
	    shuffleBlock(slide_id, shuffleStr)
	}
	if (Object.keys(newShuffle).length) {
	    Sliobj.session.questionShuffle = newShuffle;
	    Slidoc.PluginManager.saveSession();
	}
    }

    var keys = Object.keys(Sliobj.session.questionsAttempted);
    for (var j=0; j<keys.length; j++) {
	var qnumber = keys[j];
	var question_attrs = attr_vals[qnumber-1];
	var qAttempted = Sliobj.session.questionsAttempted[qnumber];
	var qfeedback = Sliobj.feedback ? (Sliobj.feedback[qnumber] || null) : null;
	var slide_id = chapter_id + '-' + zeroPad(question_attrs.slide, 2);
	Slidoc.answerClick(null, slide_id, 'setup', qAttempted.response, qAttempted.explain||null, qAttempted.plugin||null, qfeedback);
    }

    for (var qnumber=1; qnumber <= attr_vals.length; qnumber++) {
	if (Sliobj.session.hintsUsed && Sliobj.session.hintsUsed[qnumber]) {
	    var question_attrs = attr_vals[qnumber-1];
	    var slide_id = chapter_id + '-' + zeroPad(question_attrs.slide, 2);
	    hintDisplayAux(slide_id, qnumber, Sliobj.session.hintsUsed[qnumber]);
	}
    }

    if (Sliobj.session.submitted)
	showCorrectAnswersAfterSubmission();
}

function shuffleBlock(slide_id, shuffleStr) {
    var choiceBlock = document.getElementById(slide_id+'-choice-block');
    choiceBlock.dataset.shuffle = '';
    // Do not shuffle if adminState
    if (!shuffleStr || Sliobj.adminState)
	return;
    Slidoc.log('shuffleBlock: shuffleStr', slide_id, shuffleStr);
    var childNodes = choiceBlock.childNodes;
    var blankKey = ' ';
    var key = blankKey;
    var choiceElems = {}
    choiceElems[blankKey] = [];
    var altChoice = shuffleStr.charAt(0) != '0';
    for (var i=0; i < childNodes.length; i++) {
	var childElem = childNodes[i];
	if (childElem.classList && childElem.classList.contains('slidoc-chart-header'))
	    continue;  // Skip leading chart header div
	var spanElem = childElem.firstElementChild;
	if (spanElem && spanElem.classList && spanElem.classList.contains('slidoc-chart-box'))
	    spanElem = spanElem.nextElementSibling;  // Skip leading chart box span
	if (spanElem && spanElem.classList) {
	    var classList = spanElem.classList;
	    if (classList.contains('slidoc-choice-elem-alt') || classList.contains('slidoc-choice-question-alt')) {
		// Alternative choice
		if (altChoice)
		    choiceElems[key] = [];   // Skip first choice
		else
		    key = null;              // Skip alternative choice
	    } else if (classList.contains('slidoc-choice-elem')) {
		// First choice
		key = spanElem.dataset.choice;
		choiceElems[key] = [];
	    }
	}
	if (key)
	    choiceElems[key].push(childElem);
    }

    if (Object.keys(choiceElems).length != shuffleStr.length) {
	Slidoc.log("slidocSetupAux: ERROR Incorrect number of choice elements for shuffling: Expected "+(shuffleStr.length-1)+" but found "+(Object.keys(choiceElems).length-1));
	return;
    }

    choiceBlock.dataset.shuffle = shuffleStr;
    choiceBlock.innerHTML = '<div id="'+slide_id+'-chart-header" class="slidoc-chart-header" style="display: none;">';
    var key = blankKey;
    for (var i=0; i < choiceElems[key].length; i++)
	choiceBlock.appendChild(choiceElems[key][i]);
    for (var j=1; j < shuffleStr.length; j++) {
	key = shuffleStr.charAt(j);
	for (var i=0; i < choiceElems[key].length; i++) {
	    if (i == 0) {
		var spanElem = choiceElems[key][i].firstElementChild;
		if (spanElem && spanElem.classList && spanElem.classList.contains('slidoc-chart-box'))
		    spanElem = spanElem.nextElementSibling;
		if (spanElem)
		    spanElem.textContent = letterFromIndex(j-1);
	    }
	    choiceBlock.appendChild(choiceElems[key][i]);
	}
    }
}

function delayAnswers() {
    // Always display correct answers for submitted and graded sessions
    return ('delay_answers' in Sliobj.params.features) && !(Sliobj.session && Sliobj.session.submitted && Sliobj.gradeDateStr);
}

function displayCorrect(qattrs) {
    if (delayAnswers())
	return false;
    // If non-submitted admin-paced and answering question on last slide, do not display correct answer
    if (controlledPace() && Sliobj.session && !Sliobj.session.submitted && Sliobj.session.lastSlide <= qattrs.slide)
	return false;
    return true;
}

function showCorrectAnswersAfterSubmission() {
    Slidoc.log('showCorrectAnswersAfterSubmission:');
    if (delayAnswers())
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
	Slidoc.answerClick(null, slide_id, 'submit', '', '', null, qfeedback);
    }
}

/////////////////////////////////////////////
// Section 15: Session data getting/putting
/////////////////////////////////////////////

function getRandomSeed(offset) {
    return (Sliobj.session.randomSeed+offset) % Math.pow(2,4*8);
}

function makeRandomFunction(seed) {
    Slidoc.Random.setSeed(seed);
    return Slidoc.Random.randomNumber.bind(null, seed);
}

function createSession() {
    var persistPlugins = {};
    if (Sliobj.params.plugins) {
	for (var j=0; j<Sliobj.params.plugins.length; j++)
	    persistPlugins[Sliobj.params.plugins[j]] = {};
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
	    'randomSeed': Slidoc.Random.getRandomSeed(), // Save random seed
            'expiryTime': Date.now() + 180*86400*1000,  // 180 day lifetime
            'startTime': Date.now(),
            'lastTime': 0,
            'lastTries': 0,
            'remainingTries': 0,
            'tryDelay': 0,
	    'showTime': null,
            'questionShuffle': null,
            'questionsAttempted': {},
	    'hintsUsed': {},
	    'plugins': persistPlugins
	   };
}

function createQuestionAttempted(response) {
    Slidoc.log('createQuestionAttempted:', response);
    return {'response': response||''};
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

function packSession(session) {
    // Converts session to row for transmission to sheet
    Slidoc.log('packSession:', session);
    var rowObj = {};
    for (var j=0; j<Sliobj.params.sessionFields.length; j++) {
	var header = Sliobj.params.sessionFields[j];
	if (!header.match(/_hidden$/) && !header.match(/Timestamp$/)) {
	    if (header in session)
		rowObj[header] = session[header];
	}
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
			rowValue = JSON.stringify(rowValue);
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
    ///var base64str = btoa(JSON.stringify(sessionCopy));
    ///var comps = [];
    ///for (var j=0; j < base64str.length; j+=80)
    ///    comps.push(base64str.slice(j,j+80));
    ///comps.join('')+'';
    rowObj.session_hidden = JSON.stringify(sessionCopy);
    return rowObj;
}

function unpackSession(row) {
    // Unpacks hidden session object and adds response/explain fields from sheet row, as needed
    // Also returns feedback for session:
    //   {session:, feedback:}
    Slidoc.log('unpackSession:', row);
    var session_hidden = row.session_hidden.replace(/\s+/g, '');
    if (session_hidden.charAt(0) != '{')
	session_hidden = atob(session_hidden);

    var session = JSON.parse(session_hidden);
    session.displayName = row.name || '';
    session.source = row.source || '';
    session.team = row.team || '';
    session.lateToken = row.lateToken || '';
    session.lastSlide = row.lastSlide || 0;

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
	} else if (key == 'q_grades' && isNumber(value)) {
	    // Total grade
	    feedback.q_grades = value;
	    if (value)
		count += 1;
	}
    }

    return {session: session,
	    feedback: count ? feedback : null};
}

var GRADE_COMMENT_RE = /^ *\(([-+]\d+.?\d*)\)(.*)$/;
Sliobj.adaptiveComments = {};

function cacheComments(qnumber, userId, comments, update) {
    if (!('adaptive_grading' in Sliobj.params.features))
	return;
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
    var lines = comments.split(/\r?\n/);
    for (var j=0; j<lines.length; j++) {
	// Add entries for this user
	var line = lines[j];
	line = line.trim();
	if (!line)
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
		alert("Conflicting scores for comment on question "+qnumber+" response: previously '"+qCommentLine.score+"' but now '"+cscore+"': "+line);
		qCommentLine.score = null;
	    }
	} else {
	    var qCommentLine = {score: cscore, userIds: {}};
	    qComments[line] = qCommentLine;
	    qCommentLine.userIds[userId] = 1;
	}
    }
}

function displayCommentSuggestions(slideId, qnumber) {
    if (!('adaptive_grading' in Sliobj.params.features))
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
	    dispComments.push( [Object.keys(qCommentLine.userIds).length, lines[j], qCommentLine.score] )
	}
	// Sort by negative counts
	dispComments.sort( function(a,b){if (a[0] == b[0]) return cmp(a[1].toLowerCase(),b[1].toLowerCase());
					 else return cmp(-a[0], -b[0]); } );
    }
    if (suggestElem) {
	var html = ['Suggested comments:<br>\n'];
	for (var j=0; j<dispComments.length; j++) {
	    var cscore = dispComments[j][2] || 0;
	    html.push( '<code><span><span class="slidoc-clickable" onclick="Slidoc.appendComment(this,'+cscore+",'"+slideId+"');"+'">('+(cscore||'')+')</span> <span>'+escapeHtml(dispComments[j][1])+'</span></span> [<span class="slidoc-clickable" onclick="Slidoc.trackComment(this,'+qnumber+');">'+(dispComments[j][0])+'</span>]</code><br>\n' );
	}
	suggestElem.innerHTML = html.join('\n');
	suggestElem.style.display = null;
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
    if (prevComments && !/\n$/.exec(prevComments))
	prevComments += '\n';
    commentsArea.value = prevComments + (cscore ? elem.parentNode.textContent : elem.parentNode.firstElementChild.nextElementSibling.textContent);
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
    var pendingElem = document.getElementById("slidoc-pending-display");
    pendingElem.innerHTML = hourglasses;
}

function sessionGetPutAux(prevSession, callType, callback, retryCall, retryType, result, retStatus) {
    Slidoc.log('Slidoc.sessionGetPutAux: ', prevSession, callType, !!callback, !!retryCall, retryType, result, retStatus);
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
    if (session || nullReturn) {
	Sliobj.errorRetries = 0;
	if (retStatus && retStatus.info) {
	    if (retStatus.info.gradeDate)
		Sliobj.gradeDateStr = retStatus.info.gradeDate;

	    if (retStatus.info.voteDate)
		try { Sliobj.voteDate = new Date(retStatus.info.voteDate); } catch(err) { Slidoc.log('sessionGetPutAux: Error VOTE_DATE: '+retStatus.info.voteDate, err); }

	    if (retStatus.info.dueDate)
		try { Sliobj.dueDate = new Date(retStatus.info.dueDate); } catch(err) { Slidoc.log('sessionGetPutAux: Error DUE_DATE: '+retStatus.info.dueDate, err); }

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
		if (!Sliobj.session && window.confirm('Internal error in submit timestamp'))
		    sessionAbort('Internal error in submit timestamp')
		Sliobj.session.submitted = retStatus.info.submitTimestamp;
		if (Sliobj.params.paceLevel >= ADMIN_PACE) {
		    if (retStatus.info.adminPaced)
			Sliobj.adminPaced = retStatus.info.adminPaced;
		    Sliobj.session.lastSlide = visibleSlideCount();
		} else {
		    Sliobj.session.lastSlide = Sliobj.params.pacedSlides;
		}
		showCorrectAnswersAfterSubmission();
		if (Sliobj.session.lateToken == PARTIAL_SUBMIT && window.confirm('Partial submission; reload page for accurate scores'))
		    location.reload(true);
	    }
	}
	if (retryType == 'end_paced') {
	    if (Sliobj.session.submitted) {
		showCompletionStatus();
	    } else {
		alert('Error in submitting session; no submit time');
	    }
	    showSubmitted();
	} else if (retryType == 'ready' && Sliobj.params.gd_sheet_url && !Sliobj.params.gd_client_id) {
	    if (GService.gprofile.auth.remember)
		localPut('auth', GService.gprofile.auth); // Save auth info on successful start
	}

	if (retStatus && retStatus.messages) {
	    var alerts = [];
	    for (var j=0; j < retStatus.messages.length; j++) {
		var match = parse_msg_re.exec(retStatus.messages[j]);
		var msg_type = match ? match[2] : '';
		if (msg_type == 'PARTIAL_SUBMISSION') {
		    alerts.push('<em>Warning:</em><br>'+match[3]+'. Reloading page');
		    location.reload(true);
		} else if (msg_type == 'NEAR_SUBMIT_DEADLINE' || msg_type == 'PAST_SUBMIT_DEADLINE') {
		    if (session && !session.submitted)
			alerts.push('<em>Warning:</em><br>'+match[3]);
		} else if (msg_type == 'INVALID_LATE_TOKEN') {
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

    } else if (retryCall) {
	if (err_msg) {
	    if (Sliobj.errorRetries > MAX_SYS_ERROR_RETRIES) {
		sessionAbort('Too many retries: '+err_msg);
		return;
	    }
	    Sliobj.errorRetries += 1;
	    var prefix = err_type.match(/INVALID_.*TOKEN/) ? 'Invalid token. ' : '';
	    if (err_type == 'NEED_ROSTER_ENTRY') {
		Slidoc.userLogin(err_info+'. Please enter a valid userID (or contact instructor).', retryCall);
		return;
	    } else if (err_type == 'INVALID_ADMIN_TOKEN') {
		Slidoc.userLogin('Invalid admin token or key mismatch. Please re-enter', retryCall);
		return;

	    } else if (err_type == 'NEED_TOKEN' || err_type == 'INVALID_TOKEN') {
		Slidoc.userLogin('Invalid username/token or key mismatch. Please re-enter', retryCall);
		return;

	    } else if ((prevSession||retryType == 'ready') && (err_type == 'PAST_SUBMIT_DEADLINE' || err_type == 'INVALID_LATE_TOKEN')) {
		var temToken = setLateToken(prevSession||Sliobj.session, prefix);
		if (temToken) {
		    retryCall(temToken);
		    return;
		}
	    } else if (retryType == 'ready' || retryType == 'new' || retryType == 'end_paced') {
		var conf_msg = 'Error in saving'+((retryType == 'end_paced') ? ' completed':'')+' session to Google Docs: '+err_msg+' Retry?';
		if (window.confirm(conf_msg)) {
		    retryCall();
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
    var prompt = (prefix||'The submission deadline has passed.')+" If you have a valid excuse, please request late submission authorization for user "+GService.gprofile.auth.id+" and session "+Sliobj.sessionName+" from your instructor. Otherwise ";
    if (Sliobj.params.paceLevel && session && (Object.keys(session.questionsAttempted).length || responseAvailable(session)))
	prompt += "enter '"+PARTIAL_SUBMIT+"' to submit and view correct answers.";
    else
	prompt += "enter '"+LATE_SUBMIT+"' to submit late (with reduced or no credit).";
    var token = showDialog('prompt', 'lateTokenDialog', prompt);
    token = (token || '').trim();
    if (token == PARTIAL_SUBMIT || token == LATE_SUBMIT || token.indexOf(':') > 0) {
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
	var retryCall = opts.retry ? sessionGet.bind(null, userId, sessionName, opts, callback) : null;
	var getOpts = {};
	if (opts.create) getOpts.create = 1;
	if (lateToken) getOpts.late = lateToken;
	try {
	    gsheet.getRow(userId, getOpts, sessionGetPutAux.bind(null, null, 'get', callback, retryCall, opts.retry||''));
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
    // opts = {nooverwrite:, get:, retry:, force: }
    // lateToken is not used, but is already set in session, It is provided for compatibility with sessionGet
    Slidoc.log('sessionPut:', userId, Sliobj.sessionName, session, opts, !!callback, lateToken);
    if (Sliobj.adminState) {
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
	var retryCall = opts.retry ? sessionPut.bind(null, userId, session, opts, callback) : null;
	var putOpts = {};
	if (userId) putOpts.id = userId;
	if (opts.nooverwrite) putOpts.nooverwrite = 1;
	if (opts.get) putOpts.get = 1;
	if (opts.submit) putOpts.submit = 1;

	var rowObj = packSession(session);
	var gsheet = getSheet(Sliobj.sessionName);
	try {
	    gsheet.authPutRow(rowObj, putOpts, sessionGetPutAux.bind(null, session, 'put', callback||null, retryCall, opts.retry||''),
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
   return (location.pathname.slice(-1)=='/') ? location.pathname : location.pathname.split('/').slice(0,-1).join('/');
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

function visibleSlideCount() {
    if (controlledPace() || (isController() && Sliobj.session.submitted) )
	return Math.min(Math.max(1,Sliobj.adminPaced), Sliobj.params.pacedSlides);
    else
	return Sliobj.params.pacedSlides;
}

function getVisibleSlides() {
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

    if (!controlledPace())
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

Slidoc.contentsDisplay = function() {
    Slidoc.log('Slidoc.contentsDisplay:');
    if (!Sliobj.params.fileName) {
	Slidoc.showPopup('<a href="/">Home</a>')
	return;
    }

    if (!Sliobj.currentSlide && document.getElementById("slidoc00")) {
	Slidoc.sidebarDisplay();
	return;
    }
    var lines = ['<a href="/">Home</a>\n'];
    lines.push('<ul class="slidoc-contents-list">');
    var slideElems = getVisibleSlides();
    var nSlides = slideElems.length;
    if (Sliobj.session.paced || Sliobj.params.paceLevel >= QUESTION_PACE)
	nSlides = Math.min(nSlides, Math.max(1,Sliobj.session.lastSlide));
    var headers = [];
    for (var j=0; j<nSlides; j++) {
	var headerElems = document.getElementsByClassName(slideElems[j].id+'-header');
	if (headerElems.length || !j) {
	    // Slide with header or first slide
	    lines.push('<li class="slidoc-clickable slidoc-contents-header" onclick="Slidoc.go('+"'#"+slideElems[j].id+"'"+');"></li>');
	    headers.push(headerElems.length ? headerElems[0].textContent : 'Slide 1');
	}
	
    }
    lines.push('</ul>');
    var popupContent = Slidoc.showPopup(lines.join('\n'));
    var listNodes = popupContent.lastElementChild.children;
    for (var j=0; j<listNodes.length; j++)
	listNodes[j].textContent = headers[j];
}

Slidoc.sidebarDisplay = function (elem) {
    if (Sliobj.session.paced || !document.getElementById("slidoc00"))
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
    if (Sliobj.session.paced)
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
    if (Sliobj.session.paced)
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
   // Set display value (string) for all elements with class
   // If !displayValue, toggle it
   var elements = document.getElementsByClassName(className);
   for (var i=0; i < elements.length; i++) {
     if (displayValue)
         elements[i].style.display = displayValue;
     else
         elements[i].style.display = (elements[i].style.display=='none') ? 'block' : 'none';
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
    if (!setup && !force && Sliobj.session.paced && !Sliobj.currentSlide) {
	alert('To answer questions in paced mode, please switch to slide view (Escape key or Square icon at bottom left)');
	return false;
    }
    var textareaElem = document.getElementById(slide_id+'-answer-textarea');
    if (setup) {
	if (explain != null && textareaElem && question_attrs.explain) {
	    textareaElem.value = explain;
	    renderDisplay(slide_id, '-answer-textarea', '-response-div', question_attrs.explain == 'markdown');
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
    Slidoc.log('Slidoc.choiceClick:', slide_id, choice_val);
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
	if (question_attrs.qtype == 'multichoice')
	    toggleClass(!elem.classList.contains("slidoc-choice-selected"), "slidoc-choice-selected", elem);
	else
	    elem.classList.add('slidoc-choice-selected');
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
    if (shuffleStr && shuffleStr.charAt(0) == '1')  // Try alt element first
	choiceElem = document.getElementById(elemId+'-alt');
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

Slidoc.answerClick = function (elem, slide_id, force, response, explain, pluginResp, qfeedback) {
    // Handle answer types: number, text
    // force: '', 'setup', 'submit, 'finalize', 'controlled'
    Slidoc.log('Slidoc.answerClick:', elem, slide_id, force, response, explain, pluginResp, qfeedback);
    if (Slidoc.sheetIsLocked()) {
	alert(Slidoc.sheetIsLocked());
	return;
    }
    var question_attrs = getQuestionAttrs(slide_id);

    var setup = !elem;

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

    var pluginMatch = PLUGIN_RE.exec(question_attrs.correct || '');
    if (pluginMatch && pluginMatch[3] == 'response') {
	var pluginName = pluginMatch[2];
	if (setup) {
	    Slidoc.PluginMethod(pluginName, slide_id, 'display', response, pluginResp);
	    Slidoc.answerUpdate(setup, slide_id, response, pluginResp);
	} else {
	    if (Sliobj.session.remainingTries > 0)
		Sliobj.session.remainingTries -= 1;

	    var responseArg = pluginMatch[4] ? parseInt(pluginMatch[4]) : null;
	    Slidoc.PluginMethod(pluginName, slide_id, 'response',
				(Sliobj.session.remainingTries > 0),
				Slidoc.answerUpdate.bind(null, setup, slide_id),
			        responseArg);
	}
	if (setup || !Sliobj.session.paced || !Sliobj.session.remainingTries)
	    Slidoc.PluginMethod(pluginName, slide_id, 'disable');

	return false;
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
	for (var i=0; i < choices.length; i++) {
	    choices[i].removeAttribute("onclick");
	    choices[i].classList.remove("slidoc-clickable");
	}

	Slidoc.log("Slidoc.answerClick:choice", response);
	var corr_answer = question_attrs.correct;
	if (corr_answer && displayCorrect(question_attrs)) {
	    var choiceBlock = document.getElementById(slide_id+'-choice-block');
	    var shuffleStr = choiceBlock.dataset.shuffle;
	    for (var j=0; j<corr_answer.length; j++) {
		var corr_choice = getChoiceElem(slide_id, corr_answer[j], shuffleStr);
		if (corr_choice) {
		    corr_choice.style['font-weight'] = 'bold';
		}
	    }
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
		} else if (Sliobj.session.paced) {
		    if (!response) {
			if (forceQuit(force, 'Expecting a non-null answer'))
			    return false;
			response = '';
		    } else if (Sliobj.session.paced && Sliobj.lastInputValue && Sliobj.lastInputValue == response) {
			if (forceQuit(force, 'Please try a different answer this time!'))
			    return false;
		    }
		    Sliobj.lastInputValue = response;
		}
		if (Sliobj.session.remainingTries > 0)
		    Sliobj.session.remainingTries -= 1;
	    }
	    if (setup || !Sliobj.session.paced || !Sliobj.session.remainingTries)
		inpElem.disabled = 'disabled';
	}

    }

    Slidoc.answerUpdate(setup, slide_id, response);
    return false;
}

Slidoc.answerUpdate = function (setup, slide_id, response, pluginResp) {
    // PluginResp: name:'...', score:1/0/null, correctAnswer: 'correct_ans',
    //  invalid: 'invalid_msg', output:'output', tests:0/1/2} The last three are for code execution
    Slidoc.log('Slidoc.answerUpdate: ', setup, slide_id, response, pluginResp);

    if (!setup && Sliobj.session.paced)
	Sliobj.session.lastTries += 1;

    var qscore = null;
    var question_attrs = getQuestionAttrs(slide_id);

    var corr_answer      = question_attrs.correct || '';
    var corr_answer_html = question_attrs.html || '';
    var dispCorrect = displayCorrect(question_attrs);

    Slidoc.log('Slidoc.answerUpdate:', slide_id);

    var expect = '';
    var qscore = null;
    if (pluginResp) {
	qscore = parseNumber(pluginResp.score);
	if (pluginResp.correctAnswer != null)
	    expect = pluginResp.correctAnswer+'';
    } else {
	var pluginMatch = PLUGIN_RE.exec(corr_answer);
	if (pluginMatch && pluginMatch[3] == 'expect') {
	    var pluginName = pluginMatch[2];
	    var expectArg = pluginMatch[4] ? parseInt(pluginMatch[4]) : null;
	    var val = Slidoc.PluginMethod(pluginName, slide_id, 'expect', expectArg);
	    if (val != null) {
		corr_answer = val+'';
		corr_answer_html = '<code>'+corr_answer+'</code>';
		expect = corr_answer;
	    } else {
		corr_answer = pluginMatch[1].trim();
	    }
	}
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
    var shuffleStr = '';
    if (question_attrs.qtype == 'choice' || question_attrs.qtype == 'multichoice') {
	var choiceBlock = document.getElementById(slide_id+'-choice-block');
	shuffleStr = choiceBlock.dataset.shuffle;
	if (shuffleStr) {
	    disp_response = choiceShuffle(disp_response, shuffleStr);
	    disp_corr_answer = choiceShuffle(disp_corr_answer, shuffleStr);
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
	setAnswerElement(slide_id, "-answer-correct", disp_corr_answer||'', corr_answer_html);
    }

    var notes_id = slide_id+"-notes";
    var notes_elem = document.getElementById(notes_id);
    if (notes_elem && dispCorrect) {
	// Display of any notes associated with this question
	if (question_attrs.qtype == 'choice' && response) {
	    var choiceIndex = 1 + response.toUpperCase().charCodeAt(0) - 'A'.charCodeAt(0);
	    if (choiceIndex > 0) {
		// Display choice notes
		var choiceNotesId = slide_id+"-choice-notes-"+response.toUpperCase();
		Slidoc.classDisplay(choiceNotesId, 'block');
		// Redisplay choiceNotes JS
		var elems = document.getElementsByClassName(notes_id);
		for (var j=0; j<elems.length; j++)
		    expandInlineJS(elems[j], 'choiceNotes', choiceIndex);
	    }
	}
	Slidoc.idDisplay(notes_id);
	notes_elem.style.display = 'inline';
	Slidoc.classDisplay(notes_id, 'block');
	ansContainer = document.getElementById(slide_id+"-answer-container");
	if (ansContainer)
	    ansContainer.scrollIntoView(true)
    }

    // Question has been answered
    var slideElem = document.getElementById(slide_id);
    slideElem.classList.add('slidoc-answered-slideview');

    if (pluginResp)
	Slidoc.PluginMethod(pluginResp.name, slide_id, 'disable', dispCorrect && qscore !== 1);

    if (question_attrs.qtype.match(/^(text|Code)\//)) {
	renderDisplay(slide_id, '-answer-textarea', '-response-div', question_attrs.qtype.slice(-8) == 'markdown');
    } else {
	if (question_attrs.explain)
	    renderDisplay(slide_id, '-answer-textarea', '-response-div', question_attrs.explain == 'markdown');
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

	if (Sliobj.session.paced) {
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
	if (Sliobj.interactive)
	    interactAux(true);
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

function saveCallback(slide_id, qattrs, result, retStatus) {
    Slidoc.log('saveCallback:', slide_id, qattrs, result, retStatus);
    if (slide_id in Sliobj.answerPlugins)
	Slidoc.PluginManager.invoke(Sliobj.answerPlugins[slide_id], 'answerSave');
}

Slidoc.showScore = function () {
    var scoreElem = document.getElementById('slidoc-score-display');
    if (!scoreElem)
	return;
    if (Sliobj.scores.questionsCount) {
	if (controlledPace())
	    scoreElem.textContent = Sliobj.scores.questionsCount;
	else if (Sliobj.session.submitted && Sliobj.params.scoreWeight && !delayAnswers())
	    scoreElem.textContent = Sliobj.scores.weightedCorrect+' ('+Sliobj.params.scoreWeight+')';
	else
	    scoreElem.textContent = Sliobj.scores.questionsCount+'/'+Sliobj.params.questionsMax;
    } else {
	scoreElem.textContent = '';
    }
}

function renderDisplay(slide_id, inputSuffix, renderSuffix, renderMarkdown) {
    Slidoc.log("Slidoc.renderDisplay:", slide_id, inputSuffix, renderSuffix, renderMarkdown);
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
    if (renderMarkdown) {
	renderElem.innerHTML = MDConverter(textValue, true);
	if (window.MathJax)
	    MathJax.Hub.Queue(["Typeset", MathJax.Hub, renderElem.id]);
    } else {
	renderElem.textContent = textValue;
    }
}
    
Slidoc.renderText = function(elem, slide_id) {
    Slidoc.log("Slidoc.renderText:", elem, slide_id);
    var question_attrs = getQuestionAttrs(slide_id);
    if (Sliobj.adminState) {
	renderDisplay(slide_id, '-comments-textarea', '-comments-content', true);
    } else {
	if (question_attrs.explain) {
	    renderDisplay(slide_id, '-answer-textarea', '-response-div', question_attrs.explain.slice(-8) == 'markdown')
	} else {
	    renderDisplay(slide_id, '-answer-textarea', '-response-div', question_attrs.qtype.slice(-8) == 'markdown');
	}
    }
}

////////////////////////////
// Section 17b: Answering2
////////////////////////////


function scoreAnswer(response, qtype, corrAnswer) {
    // Handle answer types: choice, number, text
    // Returns null (unscored), or 0..1
    Slidoc.log('Slidoc.scoreAnswer:', response, qtype, corrAnswer);

    if (!corrAnswer)
        return null;

    if (!response)
	return 0;

    var respValue = null;
    var qscore = null;

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
            Slidoc.log('Slidoc.scoreAnswer: Error in correct numeric error:'+corrAnswer)
        }
    } else {
        // Check if non-numeric answer is correct (all spaces are removed before comparison)
        var normResp = response.trim().toLowerCase();
	// For choice, allow multiple correct answers (to fix grading problems)
        var correctOptions = corrAnswer.split( (qtype == 'choice') ? '' : ' OR ');
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

function tallyScores(questions, questionsAttempted, hintsUsed, params) {
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
        var slideNum = questionAttrs['slide'];
        if (!qAttempted || slideNum < skipToSlide) {
            // Unattempted || skipped
            qscores.push(null);
            continue;
        }

	if (qAttempted.plugin)
	    var qscore = parseNumber(qAttempted.plugin.score);
	else
            var qscore = scoreAnswer(qAttempted.response, questionAttrs.qtype,
			 	     (qAttempted.expect || questionAttrs.correct || ''));

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

        lastSkipRef = ''
        if (correctSequence && params.paceLevel == QUESTION_PACE) {
            skip = questionAttrs.skip;
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
        questionsSkipped += qSkipCount
        questionsCount += 1 + qSkipCount
        weightedCount += qWeight + qSkipWeight

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

        if (effectiveScore > 0) {
            questionsCorrect += 1 + qSkipCount;
            weightedCorrect += effectiveScore*qWeight + qSkipWeight;
        }
    }

    return { questionsCount: questionsCount, weightedCount: weightedCount,
             questionsCorrect: questionsCorrect, weightedCorrect: weightedCorrect,
             questionsSkipped: questionsSkipped, correctSequence: correctSequence, skipToSlide: skipToSlide,
             correctSequence: correctSequence, lastSkipRef: lastSkipRef, qscores: qscores};
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
	if (qscores[qnumber-1] === null || !qConcepts.length)
	    continue;
	var missed = qscores[qnumber-1] < 1;

	var primaryOffset = 1;
	for (var j=0;j<qConcepts.length;j++) {
            if (!qConcepts[j].trim()) {
		primaryOffset = j;
		break;
            }
	}

	for (var j=0;j<qConcepts.length;j++) {
            if (!qConcepts[j].trim()) {
		continue;
            }
            var m = (j < primaryOffset) ? 0 : 1;   // Primary/secondary concept
            for (var k=0; k < allQuestionConcepts[m].length; k++) {
		if (qConcepts[j] == allQuestionConcepts[m][k]) {
                    if (missed)
			missedConcepts[m][k][0] += 1;    // Missed count
                    missedConcepts[m][k][1] += 1;        // Attempted count
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
    var submitElem = document.getElementById('slidoc-submit-display');
    if (!submitElem || !Sliobj.params.gd_sheet_url)
	return;
    if (Sliobj.session && Sliobj.session.submitted && Sliobj.session.submitted != 'GRADING') {
	submitElem.innerHTML = (Sliobj.session.lateToken == LATE_SUBMIT) ? 'Late submission' : 'Submitted';
    } else if (Sliobj.session && (Sliobj.session.paced || Sliobj.session.submitted == 'GRADING')) {
	submitElem.innerHTML = Sliobj.adminState ? 'Unsubmitted' : ((Sliobj.session.lateToken == LATE_SUBMIT) ? 'SUBMIT LATE' : 'SUBMIT');
    } else {
	submitElem.innerHTML = '';
    }
}

Slidoc.submitStatus = function () {
    Slidoc.log('Slidoc.submitStatus: ');
    var html = '';
    if (Sliobj.session.submitted) {
	html += 'User '+GService.gprofile.auth.id+' submitted session to Google Docs on '+ parseDate(Sliobj.session.submitted);
	if (Sliobj.session.lateToken == PARTIAL_SUBMIT)
	    html += ' (PARTIAL)';
	else if (Sliobj.session.lateToken == LATE_SUBMIT)
	    html += ' (UNEXCUSED LATE)';
	else if (Sliobj.session.lateToken)
	    html += ' EXCUSED LATE';
    } else {
	var html = 'Session not submitted.'
	if (!Sliobj.adminState) {
	    var incomplete = Sliobj.session.lastSlide < getVisibleSlides().length;
	    html += '<ul>';
	    if (incomplete)
		html += '<li><span class="slidoc-clickable" onclick="Slidoc.saveClick();">Save session</span></li><p></p>'
	    html += '<li><span class="slidoc-clickable" onclick="Slidoc.submitClick();">Submit session</span>'+(incomplete ? ' (without reaching the last slide)':'')+'</li>'
	    html += '</ul>';

	    if (isController()) {
		html += '<hr>';
		html += '<li><span class="slidoc-clickable" onclick="Slidoc.interact();">'+(Sliobj.interactive?'End':'Begin')+' interact mode</span></li><p></p>'
	    }
	}
    }
    if (Sliobj.params.gd_sheet_url && getUserId() != Sliobj.params.testUserId)
	html += '<p></p><span class="slidoc-clickable" onclick="Slidoc.showGrades();">View gradebook</span>';

    if (Sliobj.adminState) {
	if (Sliobj.session.submitted && Sliobj.session.submitted != 'GRADING')
	    html += '<hr><span class="slidoc-clickable" onclick="Slidoc.forceSubmit(false);">Unsubmit session for user (and clear late token)</span>';
	else
	    html += '<hr><span class="slidoc-clickable" onclick="Slidoc.forceSubmit(true);">Force submit session for user</span>';
	if (Sliobj.gradeDateStr)
	    html += '<hr>Grades released to students at '+Sliobj.gradeDateStr;
	else
	    html += '<hr><span class="slidoc-clickable" onclick="Slidoc.releaseGrades();">Release grades to students</span>';
    }
    Slidoc.showPopup(html);
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
    alert('Reloading after submit status change');
    location.reload(true);
}

Slidoc.saveClick = function() {
    Slidoc.log('Slidoc.saveClick:');
    sessionPut(null, null, {}, saveClickCallback);
}

function saveClickCallback(result, retStatus) {
    if (!result)
	alert('Error in saving session: '+retStatus.error);
}
	
Slidoc.submitClick = function(elem, noFinalize) {
    // Submit session after finalizing answers with checked choices and entered input values
    Slidoc.log('Slidoc.submitClick:', elem, noFinalize);
    if (Sliobj.closePopup)
	Sliobj.closePopup();

    if (!Sliobj.session || !Sliobj.session.paced || Sliobj.session.submitted) {
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
	    var pluginMatch = PLUGIN_RE.exec(question_attrs.correct || '');
	    if (pluginMatch && pluginMatch[3] == 'response') {
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
	if (unanswered)
	    prompt = 'There are '+unanswered+' unanswered questions. Do you still wish to proceed with submission?';
	else
	    prompt = '';
    }

    if (prompt) {
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

Slidoc.releaseGrades = function () {
    Slidoc.log('Slidoc.releaseGrades: ');
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    if (!window.confirm('Confirm releasing grades to students?'))
	return;
    
    var updates = {id: Sliobj.sessionName, gradeDate: new Date()};
    Sliobj.indexSheet.updateRow(updates, {}, releaseGradesCallback.bind(null, updates.gradeDate.toISOString()));
}

function releaseGradesCallback(gradeDateStr, result, retStatus){
    Slidoc.log('releaseGradesCallback:', result, retStatus);
    if (result) {
	Sliobj.gradeDateStr = gradeDateStr;
	alert('Grade Date updated in index sheet '+Sliobj.params.index_sheet+' to release grades to students');
    } else {
	alert('Error: Failed to update Grade Date in index sheet '+Sliobj.params.index_sheet+'; grades not released to students ('+retStatus.error+')');
    }
}

function conceptStats(tags, tallies) {
    var scores = [];
    for (var j=0; j<tags.length; j++) {
	scores.push([tags[j], tallies[j][0], tallies[j][1]]);
    }
    scores.sort(function(a,b){return cmp(b[1]/Math.max(1,b[2]), a[1]/Math.max(1,a[2])) || cmp(a[0].toLowerCase(), b[0].toLowerCase());});

    var html = '<table class="slidoc-missed-concepts-table">';
    for (var j=0; j<scores.length; j++) {
	var tagId = 'slidoc-index-concept-' + make_id_from_text(scores[j][0]);
	html += '<tr><td><a href="'+Sliobj.params.conceptIndexFile+'#'+tagId+'" target="_blank">'+scores[j][0]+'</a>:</td><td>'+scores[j][1]+'/'+scores[j][2]+'</td></tr>';
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
	alert('ERROR: Grading currently not permitted for user '+userId);
	return;
    }

    var question_attrs = getQuestionAttrs(slide_id);
    var gradeInput = document.getElementById(slide_id+'-grade-input');
    var commentsArea = document.getElementById(slide_id+'-comments-textarea');
    if (!elem && gradeInput.value)  // Grading already completed; do not automatically start
	return false;
    if (!question_attrs.gweight)
	gradeInput.disabled = 'disabled';

    var startGrading = !elem || elem.classList.contains('slidoc-gstart-click');
    toggleClass(startGrading, 'slidoc-grading-slideview', document.getElementById(slide_id));
    if (startGrading) {
	if (!commentsArea.value && 'quote_response' in Sliobj.params.features)
	    Slidoc.quoteText(null, slide_id);
	var gradeElement = document.getElementById(slide_id+'-grade-element');
	setTimeout(function(){if (gradeElement) gradeElement.scrollIntoView(true); gradeInput.focus();}, 200);
	Slidoc.reportTestAction('gradeStart');
	displayCommentSuggestions(slide_id, question_attrs.qnumber);
    } else {
	displayCommentSuggestions(slide_id);
	var gradeValue = gradeInput.value.trim();

	if (gradeValue && gradeValue > (question_attrs.gweight||0)) {
	    if (!window.confirm('Entering grade '+gradeValue+' that exceeds the maximum '+(question_attrs.gweight||0)+'. Proceed anyway?'))
		return;
	}
	var commentsValue = commentsArea.value.trim();
	setAnswerElement(slide_id, '-grade-content', gradeValue);
	renderDisplay(slide_id, '-comments-textarea', '-comments-content', true)

	var gradeField = 'q'+question_attrs.qnumber+'_grade';
	var commentsField = 'q'+question_attrs.qnumber+'_comments';
	if (!(gradeField in Sliobj.gradeFieldsObj))
	    Slidoc.log('Slidoc.gradeClick: ERROR grade field '+gradeField+' not found in sheet');
	var updates = {id: userId};
	if (question_attrs.gweight)
	    updates[gradeField] = gradeValue;
	updates[commentsField] = commentsValue;
	cacheComments(question_attrs.qnumber, userId, commentsValue, true);
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
    var retryCall = gradeUpdate.bind(null, qnumber, updates, callback);

    try {
	gsheet.updateRow(updateObj, {team: !!teamUpdate}, sessionGetPutAux.bind(null, null, 'update',
		   gradeUpdateAux.bind(null, updateObj.id, slide_id, qnumber, teamUpdate, callback), retryCall, 'gradeUpdate') );
    } catch(err) {
	sessionAbort(''+err, err.stack);
	return;
    }

    showPendingCalls();
    
    if (gsheet.pendingUpdates > 1)
	return;

    if (!Slidoc.testingActive()) {
	// Move on to next user needing grading if slideshow mode, else to next question
	if (Sliobj.currentSlide) {
	    if (Sliobj.gradingUser < Sliobj.userList.length) {
		Slidoc.nextUser(true, false, true);
		setTimeout(function(){Slidoc.gradeClick(null, slide_id);}, 200);
	    }
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

/////////////////////////////////////////
// Section 19: Paced session management
/////////////////////////////////////////

Slidoc.startPaced = function () {
    Slidoc.log('Slidoc.startPaced: ');
    Sliobj.delaySec = null;

    var firstSlideId = getVisibleSlides()[0].id;

    Slidoc.hide(document.getElementById(firstSlideId+'-hidenotes'), 'slidoc-notes', '-'); // Hide notes for slide view
    Slidoc.classDisplay('slidoc-question-notes', 'none'); // Hide notes toggle for pacing
    preAnswer();

    var curDate = new Date();
    if (!Sliobj.session.submitted && Sliobj.dueDate && curDate > Sliobj.dueDate && Sliobj.session.lateToken != LATE_SUBMIT) {
	// Past submit deadline; force partial or late submit if not submitted
	if (setLateToken(Sliobj.session) == PARTIAL_SUBMIT)
	    Slidoc.endPaced();
	else
	    sessionPut();
	return;
    }

    document.body.classList.add('slidoc-paced-view');
    if (Sliobj.params.paceLevel && ('slides_only' in Sliobj.params.features))
	document.body.classList.add('slidoc-strict-paced-view');
    // Allow forward link only if no try requirement
    toggleClassAll(Sliobj.params.paceLevel < QUESTION_PACE, 'slidoc-forward-link-allowed', 'slidoc-forward-link');

    if (Sliobj.session && Sliobj.session.submitted) {
    var startMsg = 'Reviewing submitted paced session '+Sliobj.sessionName+'<br>';
    } else {
    var startMsg = 'Starting'+((Sliobj.params.paceLevel && ('slides_only' in Sliobj.params.features))?' strictly':'')+' paced session '+Sliobj.sessionName+':<br>';
    if (!('slides_only' in Sliobj.params.features))
	startMsg += '&nbsp;&nbsp;<em>You may switch between slide and document views using Escape key or Square icon at bottom left.</em><br>';
    if (Sliobj.params.questionsMax)
	startMsg += '&nbsp;&nbsp;<em>There are '+Sliobj.params.questionsMax+' questions.</em><br>';
    if (Sliobj.params.gd_sheet_url) {
	startMsg += '&nbsp;&nbsp;<em>Answers will be automatically saved after each answered question.</em><br>';
	if (Sliobj.params.slideDelay)
	    startMsg += '&nbsp;&nbsp;<em>If you plan to continue on a different computer, remember to explicitly save the session before leaving this computer (to avoid delays on previously viewed slides).</em><br>';
    }
    startMsg += '<ul>';
    if (Sliobj.params.slideDelay && allowDelay())
	startMsg += '<li>'+Sliobj.params.slideDelay+' sec delay between slides</li>';
    startMsg += '</ul>';
    }

    Slidoc.showPopup(startMsg);

    var chapterId = parseSlideId(firstSlideId)[0];
    if (!singleChapterView(chapterId))
	alert('INTERNAL ERROR: Unable to display chapter for paced mode');
    Slidoc.slideViewStart();
}

Slidoc.endPaced = function () {
    Sliobj.delaySec = null;
    Slidoc.log('Slidoc.endPaced: ');
    if (!Sliobj.params.gd_sheet_url)       // For remote sessions, successful submission will complete session
	Sliobj.session.submitted = ''+(new Date());
    if (Sliobj.params.paceLevel <= BASIC_PACE) {
	// If pace can end, unpace
	document.body.classList.remove('slidoc-paced-view');
	Sliobj.session.paced = 0;
    }
    Slidoc.reportTestAction('endPaced');
    if (Sliobj.interactive)
	interactAux(false);
    sessionPut(null, null, {force: true, retry: 'end_paced', submit: true});
    showCompletionStatus();
    var answerElems = document.getElementsByClassName('slidoc-answer-button');
    for (var j=0; j<answerElems.length; j++)
	answerElems[j].disabled = 'disabled';
}

Slidoc.answerPacedAllow = function () {
    if (!Sliobj.session.paced)
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
		Sliobj.closePopup(true);
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

   var startSlide;
   if (Sliobj.session.paced) {
       startSlide = Sliobj.session.submitted ? 1 : (Sliobj.session.lastSlide || 1); 
   } else {
       startSlide = getCurrentlyVisibleSlide(slides) || 1;
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
    if (!Sliobj.adminState && ('slides_only' in Sliobj.params.features)) {
	var msgStr = 'Cannot exit slide view when in restricted mode';
	alert(msgStr);
	return false;
    }

    if (!Sliobj.currentSlide)
	return false;

    var slides = getVisibleSlides();

    var prev_slide_id = slides[Sliobj.currentSlide-1].id;
    if (prev_slide_id in Sliobj.slidePlugins) {
	for (var j=0; j<Sliobj.slidePlugins[prev_slide_id].length; j++)
	    Slidoc.PluginManager.optCall(Sliobj.slidePlugins[prev_slide_id][j], 'leaveSlide');
    }

    if (Sliobj.session.paced >= QUESTION_PACE || (Sliobj.session.paced && !Sliobj.params.printable)) {
	// Unhide only viewed slides
	for (var j=0; j<Sliobj.session.lastSlide; j++)
	    slides[j].style.display = 'block';
    } else {
	Slidoc.classDisplay('slidoc-slide', 'block');
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
    if (Sliobj.session.paced) {
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
    if (!start) {
	if (!Sliobj.currentSlide) {
	    Slidoc.log('Slidoc.slideViewGo: ERROR not in slide view to go to slide '+slide_num);
	    return false;
	}
	if (!slide_num)
	    slide_num = forward ? Sliobj.currentSlide+1 : Sliobj.currentSlide-1;
	var prev_slide_id = slides[Sliobj.currentSlide-1].id;
	if (prev_slide_id in Sliobj.slidePlugins) {
	    for (var j=0; j<Sliobj.slidePlugins[prev_slide_id].length; j++)
		Slidoc.PluginManager.optCall(Sliobj.slidePlugins[prev_slide_id][j], 'leaveSlide');
	}
    } else if (!slide_num) {
	return false;
    }
    var backward = (slide_num < Sliobj.currentSlide);

    if (!slides || slide_num < 1 || slide_num > slides.length)
	return false;

    if (Sliobj.session.paced && Sliobj.params.paceLevel >= QUESTION_PACE && slide_num > Sliobj.session.lastSlide+1 && slide_num > Sliobj.scores.skipToSlide) {
	// Advance one slide at a time
	showDialog('alert', 'skipAheadDialog', 'Must have answered the recent batch of questions correctly to jump ahead in paced mode');
	return false;
    }

    var slide_id = slides[slide_num-1].id;
    var question_attrs = getQuestionAttrs(slide_id);  // New slide
    Sliobj.lastInputValue = null;

    if (Sliobj.session.paced && slide_num > Sliobj.session.lastSlide) {
	// Advancing to next (or later) paced slide; update session parameters
	Slidoc.log('Slidoc.slideViewGo:B', slide_num, Sliobj.session.lastSlide);

	if (Sliobj.questionSlide && !Sliobj.session.questionsAttempted[Sliobj.questionSlide.qnumber] && Sliobj.session.remainingTries) {
	    // Current (not new) slide is question slide
	    var tryCount =  (Sliobj.questionSlide.qtype=='choice') ? 1 : Sliobj.session.remainingTries;
	    var prompt = 'Please answer before proceeding.'
	    if (tryCount > 1)
		prompt += 'You have '+tryCount+' try(s)';
	    showDialog('alert', 'requireAnswerDialog', prompt);
	    return false;
	} else if (Sliobj.delaySec) {
	    // Current (not new) slide has delay
	    var delta = (Date.now() - Sliobj.session.lastTime)/1000;
	    if (delta < Sliobj.delaySec) {
		alert('Please wait '+ Math.ceil(Sliobj.delaySec-delta) + ' second(s)');
		return false;
	    }
	}

	if (!controlledPace() && (slide_num == slides.length && Sliobj.params.paceLevel >= QUESTION_PACE && Sliobj.scores.questionsCount < Sliobj.params.questionsMax)) {
	    // To last slide
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
	    if (slide_id in Sliobj.slidePlugins) {
		for (var j=0; j<Sliobj.slidePlugins[slide_id].length; j++) {
		    var delaySec = Slidoc.PluginManager.optCall(Sliobj.slidePlugins[slide_id][j], 'enterSlide', true, backward);
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
	if (Sliobj.session.lastSlide == slides.length && Sliobj.params.paceLevel >= QUESTION_PACE) {
	    // Last slide (with question-pacing); if admin-paced, save only if test user
	    if (!controlledPace())
		Slidoc.endPaced();

	} else if (Sliobj.sessionName && !Sliobj.params.gd_sheet_url) {
	    // Not last slide; save updated session (if not transient and not remote)
	    sessionPut();
	} else if (isController()) {
	    // Not last slide for test user in admin-paced; save lastSlide value
	    if (Sliobj.interactive)
		interactAux(true);
	    sessionPut();
	    if (Sliobj.session.lastSlide > 1)
		Slidoc.sendEvent(-1, 'AdminPacedAdvance', Sliobj.session.lastSlide);
	}
    } else {
	if (Sliobj.session.paced && slide_num < Sliobj.session.lastSlide && !Sliobj.questionSlide && Sliobj.delaySec) {
	    // Not last paced slide, not question slide, delay active
	    var delta = (Date.now() - Sliobj.session.lastTime)/1000;
	    if (delta < Sliobj.delaySec) {
		alert('Please wait '+ Math.ceil(Sliobj.delaySec-delta) + ' second(s)');
		return false;
	    }
	}
	if (Sliobj.session.paced && Sliobj.session.showTime)
	    Sliobj.session.showTime.back.slice(-1)[0].push( [slide_num, Date.now()-Sliobj.session.showTime.initTime] );

	Sliobj.questionSlide = question_attrs;
	if (slide_id in Sliobj.slidePlugins) {
	    for (var j=0; j<Sliobj.slidePlugins[slide_id].length; j++)
		Slidoc.PluginManager.optCall(Sliobj.slidePlugins[slide_id][j], 'enterSlide', false, backward);
	}
    }

    if (Sliobj.session.paced) {
	toggleClass(Sliobj.questionSlide && Sliobj.params.paceLevel == QUESTION_PACE && !Sliobj.scores.correctSequence, 'slidoc-incorrect-answer-state');
	toggleClass(slide_num == Sliobj.session.lastSlide, 'slidoc-paced-last-slide');
	toggleClass(Sliobj.session.remainingTries, 'slidoc-expect-answer-state');
    }
    toggleClass(slide_num < Sliobj.scores.skipToSlide, 'slidoc-skip-optional-slide');

    var prev_elem = document.getElementById('slidoc-slide-nav-prev');
    var next_elem = document.getElementById('slidoc-slide-nav-next');
    prev_elem.style.visibility = (slide_num == 1) ? 'hidden' : 'visible';
    next_elem.style.visibility = (slide_num == slides.length) ? 'hidden' : 'visible';
    var counterElem = document.getElementById('slidoc-slide-nav-counter');
    counterElem.textContent = ((slides.length <= 9) ? slide_num : zeroPad(slide_num,2))+'/'+slides.length;

    Slidoc.log('Slidoc.slideViewGo:D', slide_num, slides[slide_num-1]);
    Sliobj.maxIncrement = 0;
    Sliobj.curIncrement = 0;
    if ('incremental_slides' in Sliobj.params.features && (!Sliobj.session || (!Sliobj.session.submitted && Sliobj.session.lastSlide == slide_num))) {
	// Incremental display only applied to last slide for unsubmitted sessions
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

    slides[slide_num-1].style.display = 'block';
    for (var i=0; i<slides.length; i++) {
	if (i != slide_num-1) slides[i].style.display = 'none';
    }
    Sliobj.currentSlide = slide_num;
    location.href = '#'+slides[Sliobj.currentSlide-1].id;

    var inputElem = document.getElementById(slides[Sliobj.currentSlide-1].id+'-answer-input');
    if (inputElem) setTimeout(function(){inputElem.focus();}, 200);
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
    } else if (Sliobj.session.paced) {
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
    return goSlide(slideHash, chained);
}

function goSlide(slideHash, chained, singleChapter) {
   // Scroll to slide with slideHash, hiding current chapter and opening new one
   // If chained, hide previous link and set up new link
    Slidoc.log("goSlide:", slideHash, chained);
    if (Sliobj.session.paced && ('slides_only' in Sliobj.params.features) && !Sliobj.currentSlide && !singleChapter) {
	alert('Slidoc: InternalError: strict paced mode without slideView');
	return false;
    }
    if (!slideHash) {
	if (Sliobj.currentSlide) {
	    Slidoc.slideViewGo(false, 1);
	} else {
	    location.hash = Sliobj.curChapterId ? '#'+Sliobj.curChapterId+'-01' : '#slidoc01-01';
	    window.scrollTo(0,0);
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
	slideId = '';
        for (var i=0; i<goElement.classList.length; i++) {
	    var refmatch = /slidoc-referable-in-(.*)$/.exec(goElement.classList[i]);
	    if (refmatch) {
		slideId = refmatch[1];
		slideHash = '#'+slideId;
                Slidoc.log('goSlide:D ', slideHash);
		break;
	    }
	}
        if (!slideId) {
            Slidoc.log('goSlide: Error - unable to find slide containing header:', slideHash);
            return false;
        }
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

   } else if (Sliobj.session.paced) {
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

    if (!tocSlide && !Sliobj.currentSlide && !Sliobj.session.paced && !Sliobj.sidebar && !Sliobj.showedFirstSideBar &&
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
	Sliobj.closePopup(true);
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
	    Sliobj.popupQueue.push([innerHTML||null, divElemId||null]);
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
	Sliobj.closePopup = function (closeAll, closeArg) {
	    overlayElem.style.display = 'none';
	    divElem.style.display = 'none';
	    Sliobj.popupEvent = '';
	    Sliobj.closePopup = null;
	    if (closeAll) {
		Sliobj.popupQueue = [];
	    } else {
		if (Sliobj.popupQueue && Sliobj.popupQueue.length) {
		    var args = Sliobj.popupQueue.shift();
		    Slidoc.showPopup(args[0], args[1]);
		}
	    }
	    if (closeCallback) {
		try { closeCallback(closeArg || null); } catch (err) {Slidoc.log('Sliobj.closePopup: ERROR '+err);}
	    }
	    Slidoc.advanceStep();
	}
	
	closeElem.onclick = Sliobj.closePopup;
	if (autoCloseMillisec)
	    setTimeout(Sliobj.closePopup, autoCloseMillisec);
    }
    window.scrollTo(0,0);
    return contentElem;
}

Slidoc.showPopupOptions = function(prefixHTML, optionListHTML, suffixHTML, callback) {
    // Show list of options as popup, with callback(n) invoked on select.
    // n >= 1 for selection, or null if popup is closed
    if (Sliobj.closePopup)
	Sliobj.closePopup(true);
    var lines = [prefixHTML || ''];
    lines.push('<p></p><ul class="slidoc-popup-option-list">');
    for (var j=0; j<optionListHTML.length; j++)
	lines.push('<li class="slidoc-popup-option-list-element slidoc-clickable" onclick="Slidoc.selectPopupOption('+(j+1)+');">'+optionListHTML[j]+'</li><p></p>');
    lines.push('</ul>');
    lines.push(suffixHTML || '');
    Slidoc.showPopup(lines.join('\n'), null, false, 0, '', callback||null);
}

Slidoc.selectPopupOption = function(closeArg) {
    Slidoc.log('Slidoc.selectPopupOption:', closeArg);
    if (Sliobj.closePopup)
	Sliobj.closePopup(true, closeArg||null);
}

Slidoc.showPopupWithList = function(prefixHTML, listElems, lastMarkdown) {
    // Show popup ending with a tabular list [ [html, insertText1, insertText2, ...], ... ]
    // Safely populate list with plain text, or Markdown (last column only)
    //Slidoc.log('showPopupWithList:', listElems, lastMarkdown);
    if (Sliobj.closePopup)
	Sliobj.closePopup(true);
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
	    if (k == curElems.length-1 && lastMarkdown && window.MDConverter)
		childNodes[k-1].innerHTML = MDConverter(curElems[k], true);
	    else
		childNodes[k-1].textContent = curElems[k];
	}
    }
    if (lastMarkdown && window.MathJax)
	MathJax.Hub.Queue(["Typeset", MathJax.Hub, popupContent.id]);
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
    var html = PagedownConverter ? PagedownConverter.makeHtml(mdText) : '<pre>'+escapeHtml(mdText)+'</pre>';
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
  function initSequence(seedValue) {
      // Start new random number sequence using seed value as the label
      var label = seedValue || '';
      sequences[label] = seedValue || Math.round(Math.random() * m);
      return label;
  }
  function uniform(seedValue) {
      // define the recurrence relationship
      var label = seedValue || '';
      if (!(label in sequences))
	  throw('Random number generator not initialized properly');
      sequences[label] = (a * sequences[label] + c) % m;
      // return a float in [0, 1) 
      // if sequences[label] = m then sequences[label] / m = 0 therefore (sequences[label] % m) / m < 1 always
      return sequences[label] / m;
  }
  return {
    getRandomSeed: function() {
	return Math.round(Math.random() * m);
    },
    setSeed: function(val) {
	// Set seed to val, or a random number if val is null
	return initSequence(val);
    },
    setSeedMD5: function(seedKey, labelStr) {  // NOTE USED YET
	// Set seed to HMAC of labelStr and seedKey
	return initSequence( parseInt(md5(labelStr, ''+seedKey).slice(0,nbytes*2), 16) );
    },
    randomNumber: function(seedValue, min, max) {
	// Equally probable integer values between min and max (inclusive)
	// If min is omitted, equally probable integer values between 1 and max
	// If both omitted, value uniformly distributed between 0.0 and 1.0 (<1.0)
	if (!isNumber(min))
	    return uniform(seedValue);
	else {
	    if (!isNumber(max)) {
		max = min;
		min = 1;
	    }
	    return Math.min(max, Math.floor( min + (max-min+1)*uniform(seedValue) ));
	}
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
    touchSwipe;

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
		Slidoc.handleKey('left');
            } else {
		/* left swipe (right motion) */ 
		Slidoc.handleKey('right');
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
            return Slidoc.handleKey('right');
        } else {
            /* right swipe (leftward motion) */
            return Slidoc.handleKey('left');
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
