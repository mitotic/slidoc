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

var MAX_INC_LEVEL = 9; // Max. incremental display level

var CACHE_GRADING = true; // If true, cache all rows for grading

var QFIELD_RE = /^q(\d+)_([a-z]+)$/;

var SYMS = {correctMark: '&#x2714;', partcorrectMark: '&#x2611;', wrongMark: '&#x2718;', anyMark: '&#9083;', xBoxMark: '&#8999;'};

var uagent = navigator.userAgent.toLowerCase();
var isSafari = (/safari/.test(uagent) && !/chrome/.test(uagent));
var useJSONP = (location.protocol == 'file:' || isSafari);

/////////////////////////////////////
// Section 2: Global initialization
/////////////////////////////////////

var Sliobj = {}; // Internal object
Sliobj.debugging = true;
Sliobj.logSheet = null;

Sliobj.params = JS_PARAMS_OBJ;
Sliobj.sessionName = Sliobj.params.paceLevel ? Sliobj.params.fileName : '';

Sliobj.gradeFieldsObj = {};
for (var j=0; j<Sliobj.params.gradeFields.length; j++)
    Sliobj.gradeFieldsObj[Sliobj.params.gradeFields[j]] = 1;

Sliobj.adminState = null;
Sliobj.firstTime = true;
Sliobj.closePopup = null;
Sliobj.activePlugins = {};
Sliobj.pluginList = [];
Sliobj.pluginSetup = null;
Sliobj.slidePlugins = null;
Sliobj.incrementPlugins = null;
Sliobj.buttonPlugins = null;
Sliobj.delaySec = null;

////////////////////////////////
// Section 3: Scripted testing
////////////////////////////////

Sliobj.testScript = null;
Sliobj.testStep = getParameter('teststep');

Slidoc.enableTesting = function(activeScript, scripts) {
    if (Slidoc.TestScript)
	Sliobj.testScript = new Slidoc.TestScript(activeScript, scripts);
}
Slidoc.reportEvent = function (eventName) {
    if (Sliobj.testScript)
	return Sliobj.testScript.reportEvent(eventName);
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
	var args = JSON.parse(Sliobj.logQueue[j]);
	if (!regexp || regexp.exec(args[0])) {
	    args[0] = (regexp ? '+ ':'- ') + args[0];
	    console.log.apply(console, args);
	}
    }
    if (!regexp)
	Sliobj.logQueue = [];
}

Slidoc.log = function() {
    if (Sliobj.debugging) {
	console.log.apply(console, arguments);
	return;
    }
    
    var args = Array.prototype.slice.call(arguments);
    var match = /^([\.\w]+)(:\s*|\s+|$)(ERROR|WARNING)?/i.exec(''+arguments[0]);
    if (match && match[3] && match[3].toUpperCase() == 'ERROR') {
	Slidoc.logDump();
	if (Sliobj.params.remoteLogLevel > 1)
	    Slidoc.remoteLog(match[1], 'ERROR', JSON.stringify(args), '');
    } else {
	Sliobj.logQueue.push(JSON.stringify(args));
	if (Sliobj.logQueue.length > Sliobj.logMax)
	    Sliobj.logQueue.shift();
    }
    if ( (Sliobj.logRe && Sliobj.logRe.exec(''+arguments[0])) || !match ||
		    (match && match[3] && (match[3].toUpperCase() == 'ERROR' || match[3].toUpperCase() == 'WARNING')) )
	console.log.apply(console, arguments);
}

/////////////////////////////////////////
// Section 5: Remote spreadsheet access
/////////////////////////////////////////

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
		    Sliobj.userGrades[id] = {index: j+1, name: roster[j][0], grading: null};
		}

		var userId = auth.id;
		if (userId && !(userId in Sliobj.userGrades)) {
		    alert('Error: userID '+userId+' not found for this session');
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
		    gsheet.getRow(Sliobj.userList[j], checkGradingCallback.bind(null, Sliobj.userList[j]));
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
    if (Sliobj.logSheet)
	Sliobj.logSheet.putRow({id: GService.gprofile.auth.id, name: GService.gprofile.auth.id,
				browser: navigator.userAgent, file: Sliobj.params.fileName, function: funcName||'',
				type: msgType||'', message: msg||'', trace: msgTrace||'' },
			       {} );
}

var sessionAborted = false;
function sessionAbort(err_msg, err_trace) {
    Slidoc.remoteLog('sessionAbort', '', err_msg, err_trace);
    if (sessionAborted)
	return;
    sessionAborted = true;
    localDel('auth');
    try { Slidoc.classDisplay('slidoc-slide', 'none'); } catch(err) {}
    alert((Sliobj.debugging ? 'DEBUG: ':'')+err_msg);
    if (!Sliobj.debugging)
	document.body.textContent = err_msg + ' (reload page to restart)   '+(err_trace || '');

    if (getServerCookie()) {
	if (!Sliobj.debugging || window.confirm('Log out user?'))
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
   window.localStorage['slidoc_'+key] = JSON.stringify(obj);
}

function localDel(key) {
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
    return {user: comps[0], token: comps.length > 1 ? comps[1] : '',
     	                     name: comps.length > 2 ? decodeURIComponent(comps[2]) : ''};
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
    if (document.readyState != "interactive" || !document.body || !Sliobj.params.fileName)
	return;
    Slidoc.reportEvent('ready');
    return abortOnError(onreadystateaux);
}

var PagedownConverter = null;
function onreadystateaux() {
    Slidoc.log('onreadystateaux:');
    setupPlugins();
    if (window.Markdown) {
	PagedownConverter = new Markdown.getSanitizingConverter();
	if (Markdown.Extra) // Need to install https://github.com/jmcmanus/pagedown-extra
	    Markdown.Extra.init(PagedownConverter, {extensions: ["fenced_code_gfm"]});

	// Need latest version of Markdown for hooks
	PagedownConverter.hooks.chain("preSpanGamut", MDPreSpanGamut);
	PagedownConverter.hooks.chain("preBlockGamut", MDPreBlockGamut);
    }

    if (Sliobj.params.gd_client_id) {
	// Google client load will authenticate
    } else if (Sliobj.params.gd_sheet_url) {
	var localAuth = localGet('auth');
	if (localAuth && !getServerCookie()) {
	    Slidoc.showPopup('Accessing Google Docs ...', null, 1000);
	    GService.gprofile.auth = localAuth;
	    Slidoc.slidocReady(localAuth);
	} else {
	    if (!getServerCookie())
		Slidoc.reportEvent('loginPrompt');
	    GService.gprofile.promptUserInfo();
	}
    } else {
	Slidoc.slidocReady(null);
    }
}

//////////////////////////////////
// Section 9: Utility functions
//////////////////////////////////

function isNumber(x) { return !!(x+'') && !isNaN(x+''); }

function zeroPad(num, pad) {
    // Pad num with zeros to make pad digits
    var maxInt = Math.pow(10, pad);
    if (num >= maxInt)
	return ''+num;
    else
	return ((''+maxInt).slice(1)+num).slice(-pad);
}

function letterFromIndex(n) {
    return String.fromCharCode('A'.charCodeAt(0) + n)
}

function shuffleArray(array) {
    for (var i = array.length - 1; i > 0; i--) {
        var j = Math.floor(Math.random() * (i + 1));
        var temp = array[i];
        array[i] = array[j];
        array[j] = temp;
    }
    return array;
}

function randomLetters(n) {
    var letters = [];
    for (var i=0; i < n; i++)
	letters[i] = letterFromIndex(i);
    shuffleArray(letters);
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
    return text.replace('&lt;', '<').replace('&gt;', '>')
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

Slidoc.userLogin = function () {
    Slidoc.log('Slidoc.userLogin:');
    GService.gprofile.promptUserInfo(GService.gprofile.auth.id, '', Slidoc.userLoginCallback.bind(null, null));
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
    if (Sliobj.params.gd_sheet_url) {
	if (!Slidoc.testingActive())
	    alert('Cannot reset session linked to Google Docs');
	return false;
    }
    if (!Slidoc.testingActive() && !window.confirm('Do want to completely delete all answers/scores for this session and start over?'))
	return false;
    Sliobj.session = sessionCreate();
    Sliobj.feedback = null;
    sessionPut();
    if (!Slidoc.testingActive())
	location.reload(true);
}

Slidoc.showConcepts = function (msg) {
    if (!displayCorrect())
	return;
    var html = msg || '';
    if (!msg && Sliobj.params.gd_sheet_url)
	html += 'Click <span class="slidoc-clickable" onclick="Slidoc.showGrades();">here</span> to view other scores/grades<p></p>'
    if (Sliobj.questionConcepts.length) {
	html += '<b>Question Concepts</b><br>';
	var labels = ['Primary concepts missed', 'Secondary concepts missed'];
	for (var m=0; m<labels.length; m++)
	    html += labels[m]+conceptStats(Sliobj.questionConcepts[m], Sliobj.session.missedConcepts[m])+'<p></p>';
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
    if (Sliobj.sessionName) {
	if (window.GService && GService.gprofile && GService.gprofile.auth)
	    html += 'User: <b>'+GService.gprofile.auth.id+'</b> (<span class="slidoc-clickable" onclick="Slidoc.userLogout();">logout</span>)<br>';
	html += 'Session: <b>' + Sliobj.sessionName + '</b>';
	if (Sliobj.session && Sliobj.session.revision)
	    html += ', ' + Sliobj.session.revision;
	if (Sliobj.params.questionsMax)
	    html += ' (' + Sliobj.params.questionsMax + ' questions)';
	if (Sliobj.params.gd_sheet_url && Sliobj.session)
	    html += Sliobj.session.submitted ? ', Submitted '+Sliobj.session.submitted : ', NOT SUBMITTED';
	html += '<br>';
	if (Sliobj.dueDate)
	    html += 'Due: <em>'+Sliobj.dueDate+'</em><br>';
	if (Sliobj.params.gradeWeight && Sliobj.feedback && 'q_grades' in Sliobj.feedback && Sliobj.feedback.q_grades != null)
	    html += 'Grades: '+Sliobj.feedback.q_grades+'/'+Sliobj.params.gradeWeight+'<br>';
    } else {
	var cookieUserInfo = getServerCookie();
	if (cookieUserInfo)
	    html += 'User: <b>'+cookieUserInfo.user+'</b> (<a class="slidoc-clickable" href="'+Slidoc.logoutURL+'">logout</a>)<br>';
    }
    html += '<table class="slidoc-slide-help-table">';
    if (Sliobj.params.paceLevel && !Sliobj.params.gd_sheet_url && !Sliobj.chainActive)
	html += formatHelp(['', 'reset', 'Reset paced session']) + hr;

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
    var testValue = Slidoc.reportEvent(testEvent);
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
	    Sliobj.activePlugins[pluginName] = {number: Sliobj.pluginList.length, args: {}, button: {} };
	}
	Sliobj.activePlugins[pluginName].args[slide_id] = args;
	Sliobj.activePlugins[pluginName].button[slide_id] = button;
    }
    for (var j=0; j<Sliobj.pluginList.length; j++) {
	var pluginInstance = createPluginInstance(Sliobj.pluginList[j], true);
	Slidoc.PluginManager.optCall(pluginInstance, 'initSetup');
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
    if (!(pluginName in Slidoc.Plugins))
	throw('INTERNAL ERROR Plugin '+pluginName+' not activated');

    var pluginInstance = Slidoc.Plugins[pluginName][slide_id || ''];
    if (!pluginInstance)
	throw('INTERNAL ERROR Plugin '+pluginName+" instance not found for slide '"+slide_id+"'");

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

    if (!(action in pluginInstance))
	throw('ERROR Plugin action '+pluginInstance.name+'.'+action+' not defined');

    try {
	return pluginInstance[action].apply(pluginInstance, extraArgs);
    } catch(err) {
	sessionAbort('ERROR in invoking plugin '+pluginInstance.name+'.'+action+': '+err, err.stack);
    }
}

function evalPluginArgs(pluginName, argStr, slide_id) {
    // Evaluates plugin init args in appropriate context
    if (!argStr || !slide_id)
	return [];
    try {
	var pluginList = Sliobj.slidePlugins[slide_id]; // Plugins instantiated in the slide so far
	var plugins = {};
	for (var j=0; j<pluginList.length; j++)
	    plugins[pluginList[j].name] = pluginList[j];
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
    if (!pluginDef)
	throw('ERROR Plugin '+pluginName+' not found; define using PluginDef/PluginEndDef');

    var defCopy;
    if (nosession)
	defCopy = pluginDef.setup || {};
    else if (!slide_id)
	defCopy = pluginDef.global || {};
    else
	defCopy = copyAttributes(pluginDef, ['setup', 'global']);
    defCopy.name = pluginName;
    defCopy.adminState = Sliobj.adminState;
    defCopy.sessionName = Sliobj.sessionName;
    defCopy.initArgs = slide_id ? evalPluginArgs(pluginName, Sliobj.activePlugins[pluginName].args[slide_id], slide_id) : [];
    defCopy.slideData = slideData || null;
    if (nosession) {
	defCopy.setup = null;
	defCopy.global = null;
	defCopy.persist = null;
    } else {
	defCopy.setup = Sliobj.pluginSetup[pluginName];

	if (!(pluginName in Slidoc.Plugins))
	    Slidoc.Plugins[pluginName] = {};

	if (!(pluginName in Sliobj.session.plugins))
	    Sliobj.session.plugins[pluginName] = {};

	defCopy.persist = Sliobj.session.plugins[pluginName];

	if (!slide_id) {
	    // Global seed for all instances of the plugin
	    defCopy.global = null;
	    defCopy.slideId = '';
	    defCopy.randomSeed = Sliobj.session.randomSeed + Sliobj.activePlugins[pluginName].number;
	    defCopy.randomNumber = Slidoc.Random.randomNumber.bind(null, defCopy.randomSeed);
	} else {
	    // Seed for each slide instance of the plugin
	    defCopy.global = Slidoc.Plugins[pluginName][''];
	    defCopy.slideId = slide_id;
	    var comps = parseSlideId(slide_id);
	    defCopy.randomSeed = defCopy.global.randomSeed + 256*((1+comps[1])*256 + comps[2]);
	    defCopy.randomNumber = Slidoc.Random.randomNumber.bind(null, defCopy.randomSeed);
	    defCopy.pluginId = slide_id + '-plugin-' + pluginName;
	    defCopy.qattributes = getQuestionAttrs(slide_id);
	    defCopy.answer = null;
	    if (defCopy.qattributes && defCopy.qattributes.correct) {
		// Correct answer: plugin.response();ans+/-err
		var comps = defCopy.qattributes.correct.split(';');
		defCopy.answer = (comps.length == 1) ? comps[0] : comps.slice(1).join(';');
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

function selectUser(auth, callback) {
    var userId = Sliobj.userList[Sliobj.gradingUser-1];
    Slidoc.log('selectUser:', auth, userId);
    if (!auth.adminKey) {
	sessionAbort('Only admin can pick user');
    }
    auth.displayName = userId;
    auth.id = userId;
    auth.email = (userId.indexOf('@')>0) ? userId : '';
    auth.altid = '';

    if (callback) {
	callback(auth);  // Usually callback slidocReadyAux1
    } else {
	var gsheet = getSheet(Sliobj.sessionName);
	gsheet.getRow(userId, selectUserCallback.bind(null, userId));
    }
}

function selectUserCallback(userId, result, retStatus) {
    Slidoc.log('selectUserCallback:', userId, result, retStatus);
    if (!result) {
	sessionAbort('ERROR in selectUserCallback: '+ retStatus.error);
    }
    Slidoc.reportEvent('selectUser');
    var unpacked = unpackSession(result);
    Sliobj.session = unpacked.session;
    Sliobj.feedback = unpacked.feedback || null;
    prepGradeSession(Sliobj.session);
    initSessionPlugins(Sliobj.session);
    showSubmitted();
    preAnswer();
}

Slidoc.nextUser = function (forward) {
    if (!Sliobj.gradingUser)
	return;
    if (!forward && Sliobj.gradingUser > 1)
	Sliobj.gradingUser -= 1;
    else if (forward && Sliobj.gradingUser < Sliobj.userList.length)
	Sliobj.gradingUser += 1;
    else
	return;
    var option = document.getElementById('slidoc-switch-user-'+Sliobj.gradingUser);
    if (option)
	option.selected = true;
    //selectUser(GService.gprofile.auth, slidocReadyAux1);
    selectUser(GService.gprofile.auth);
}

Slidoc.showGrades = function () {
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    var userId = GService.gprofile.auth.id;
    Sliobj.scoreSheet.getRow(userId, showGradesCallback.bind(null, userId));
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
	html += 'Session count: <b>'+result.sessionCount+'</b><br>';
    if (result.weightedTotal)
	html += 'Weighted total: <b>'+result.weightedTotal+'</b><br>';
    for (var j=0; j<sessionKeys.length; j++) {
	html += '&nbsp;&nbsp;&nbsp;' + sessionKeys[j].slice(1) + ': <b>'+ result[sessionKeys[j]]+'</b>'
	if (retStatus && retStatus.info && retStatus.info.headers) {
	    if (retStatus.info.maxScores)
		html += ' / '+retStatus.info.maxScores[retStatus.info.headers.indexOf(sessionKeys[j])];
	    if (retStatus.info.averages) {
		var temAvg = retStatus.info.averages[retStatus.info.headers.indexOf(sessionKeys[j])];
		if (isNumber(temAvg))
		    html += ' (average='+temAvg+')';
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
    Sliobj.userList = null;
    Sliobj.userGrades = null;
    Sliobj.gradingUser = 0;
    Sliobj.indexSheet = null;
    Sliobj.scoreSheet = null;
    Sliobj.dueDate = null;
    Sliobj.gradeDateStr = '';

    if (Sliobj.params.gd_sheet_url)
	Sliobj.scoreSheet = new GService.GoogleSheet(Sliobj.params.gd_sheet_url, Sliobj.params.score_sheet,
						     [], [], useJSONP);
    if (Sliobj.adminState) {
	Sliobj.indexSheet = new GService.GoogleSheet(Sliobj.params.gd_sheet_url, Sliobj.params.index_sheet,
						     Sliobj.params.indexFields.slice(0,2),
						     Sliobj.params.indexFields.slice(2), useJSONP);
	Sliobj.indexSheet.getRow(Sliobj.sessionName, function (result, retStatus) {
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
    Sliobj.questionConcepts = [];
    Sliobj.sidebar = false;
    Sliobj.prevSidebar = false;

    Sliobj.session = null;
    Sliobj.feedback = null;

    Slidoc.Random = LCRandom;
    sessionManage();

    var newSession = sessionCreate();

    Slidoc.log("slidocReadyAux2:B", Sliobj.sessionName, Sliobj.params.paceLevel);
    if (Sliobj.sessionName) {
	// Paced named session
	if (Sliobj.params.gd_sheet_url && !auth) {
	    sessionAbort('Session aborted. Google Docs authentication error.');
	}

	if (Sliobj.adminState) {
	    // Retrieve session, possibly from cache (without creating)
	    sessionGet(null, Sliobj.sessionName, slidocSetup, 'ready')
	} else if (Sliobj.params.sessionPrereqs) {
	    // Retrieve prerequisite session(s)
	    var prereqs = Sliobj.params.sessionPrereqs.split(',');
	    sessionGet(null, prereqs[0], slidocReadyPaced.bind(null, newSession, prereqs));
	} else {
	    slidocReadyPaced(newSession)
	}
    
    } else {
	slidocSetup(newSession);
    }
}

function slidocReadyPaced(newSession, prereqs, prevSession, prevFeedback) {
    Slidoc.log('slidocReadyPaced:', newSession, prereqs, prevSession, prevFeedback);
    if (prereqs) {
	if (!prevSession) {
	    sessionAbort("Prerequisites: "+prereqs.join(',')+". Error: session '"+prereqs[0]+"' not attempted!");
	}
	if (!prevSession.submitted) {
	    sessionAbort("Prerequisites: "+prereqs.join(',')+". Error: session '"+prereqs[0]+"' not completed!");
	}
	if (prereqs.length > 1) {
	    prereqs = prereqs.slice(1);
	    sessionGet(null, prereqs[0], slidocReadyPaced.bind(null, newSession, prereqs));
	    return;
	}
    }
	
    sessionPut(null, newSession, {nooverwrite: true, get: true, retry: 'ready'}, slidocSetup);
}

///////////////////////////////
// Section 14: Session setup
///////////////////////////////


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
	Sliobj.session.paced = false;

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

    if (!Sliobj.session) {
	// New paced session
	Sliobj.session = sessionCreate();
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
	for (var k=0; k<attr_vals.length; k++) {
	    // For each question slide
	    var question_attrs = attr_vals[k];
	    var slide_id = chapter_id + '-' + zeroPad(question_attrs.slide, 2);
	    var slideElem = document.getElementById(slide_id);

	    // Hide grade entry for questions with zero grade weight (workaround for Weight: being parsed after Answer:)
	    toggleClass(!question_attrs.gweight, 'slidoc-nogradeelement', slideElem);
	    var suffixElem = document.getElementById(slide_id+'-gradesuffix')
	    if (suffixElem && question_attrs.gweight)
		suffixElem.textContent = '/'+question_attrs.gweight;

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
    Slidoc.reportEvent('initSession');

    initSessionPlugins(Sliobj.session);

    if (Sliobj.adminState)
    	toggleClass(true, 'slidoc-admin-view');

    if (Sliobj.params.gd_sheet_url)
	toggleClass(true, 'slidoc-remote-view');

    if (Sliobj.session.questionsCount)
	Slidoc.showScore();

    if (Sliobj.session.submitted || Sliobj.adminState) // Suppress incremental display
	toggleClass(true, 'slidoc-completed-view');
    
    if (Sliobj.feedback) // If any non-null feedback, activate graded view
	toggleClass(true, 'slidoc-graded-view');

    showSubmitted();

    // Setup completed; branch out
    Sliobj.firstTime = false;
    var toc_elem = document.getElementById("slidoc00");
    if (!toc_elem && Sliobj.session) {
	if (Sliobj.session.paced || Sliobj.session.submitted) {
	    var firstSlideId = getVisibleSlides()[0].id;
	    Sliobj.questionConcepts = parseElem(firstSlideId+'-qconcepts') || [];
	}
	if (Sliobj.session.paced) {
	    Slidoc.startPaced(); // This will call preAnswer later
	    return false;
	}
	preAnswer();
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
	if (slideHash.slice(0,21) == '#slidoc-index-concept') {
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
	if (document.getElementById("slidoc-sidebar-button"))
	    document.getElementById("slidoc-sidebar-button").style.display = null;

	if (document.getElementById("slidoc01") && window.matchMedia("screen and (min-width: 800px) and (min-device-width: 960px)").matches) {
	    Slidoc.sidebarDisplay();
	    if (chapters && chapters.length == 1) {
		// Display contents for single chapter
		var toggleElem = document.getElementById("slidoc-toc-chapters-toggle");
		if (toggleElem && toggleElem.onclick)
		    toggleElem.onclick();
	    }
	}
    }

    ///if (Slidoc.testingActive())
	///Slidoc.slideViewStart();
}

function prepGradeSession(session) {
    // Modify session for grading
    session.paced = false; // Unpace session, but this update will not be saved to Google Docs
    session.submitted = session.submitted || 'GRADING'; // Complete session, but these updates will not be saved to Google Docs
    session.lastSlide = Sliobj.params.pacedSlides;
}

function initSessionPlugins(session) {
    // Restore random seed for session
    Slidoc.log('initSessionPlugins:');
    Sliobj.slidePlugins = {};
    Sliobj.incrementPlugins = {};
    Sliobj.buttonPlugins = {};
    Slidoc.Plugins = {};
    for (var j=0; j<Sliobj.pluginList.length; j++) {
	var pluginName = Sliobj.pluginList[j];
	var pluginInstance = createPluginInstance(pluginName);
	Slidoc.Random.setSeed(pluginInstance.randomSeed);
	Slidoc.PluginManager.optCall(pluginInstance, 'initGlobal');
    }

    // Sort plugin content elements in order of occurrence
    // Need to call init method in sequence to preserve global random number generation order
    var allContent = document.getElementsByClassName('slidoc-plugin-content');
    var contentElems = [];
    for (var j=0; j<allContent.length; j++)
	contentElems.push(allContent[j]);

    contentElems.sort(function(a,b){if (a.dataset.number == b.dataset.number) return 0; else (a.dataset.number > b.dataset.number) ? 1 : -1;});    

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
	Slidoc.Random.setSeed(pluginInstance.randomSeed);
	var button = Sliobj.activePlugins[pluginName].button[slide_id];
	if (button)
	    Sliobj.buttonPlugins[slide_id] = pluginInstance;
	Slidoc.PluginManager.optCall.apply(null, [pluginInstance, 'init'].concat(pluginInstance.initArgs));
    }

    var jsSpans = document.getElementsByClassName('slidoc-inline-js');
    for (var j=0; j<jsSpans.length; j++) {
	var jsFunc = jsSpans[j].dataset.slidocJsFunction;
	var jsArg = jsSpans[j].dataset.slidocJsArgument || null;
	if (jsArg !== null)
	    try {jsArg = parseInt(jsArg); } catch (err) { jsArg = null; }
	var slide_id = '';
	for (var k=0; k<jsSpans[j].classList.length; k++) {
	    var refmatch = /slidoc-inline-js-in-(.*)$/.exec(jsSpans[j].classList[k]);
	    if (refmatch) {
		slide_id = refmatch[1];
		break;
	    }
	}
	var comps = jsFunc.split('.');
	var val = Slidoc.PluginMethod(comps[0], slide_id, comps[1], jsArg);
	if (val)
	    jsSpans[j].innerHTML = val;
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
    if (Sliobj.userGrades[userId].grading)
	return;
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
	if (qnumber in session.questionsAttempted) {
	    need_grading[qnumber] = 1;
	} else {
	    // Unattempted
	    need_updates += 1;
	    if (question_attrs.gweight) {
		var gradeField = 'q'+question_attrs.qnumber+'_grade';
		updates[gradeField] = 0;
	    }
	    if (question_attrs.qtype.slice(0,5) == 'text/' || question_attrs.explain) {
		var commentsField = 'q'+question_attrs.qnumber+'_comments';
		updates[commentsField] = 'Not attempted';
	    }
	}
    }
    Slidoc.log('checkGradingStatus:B', need_grading, updates);

    Sliobj.userGrades[userId].grading = need_grading;
    updateGradingStatus(userId);

    if (need_updates) {
	// Set unattempted grades to zero
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
    var count = Object.keys(Sliobj.userGrades[userId].grading).length;
    var c = count || '\u2714';
    if (option)
	option.text = Sliobj.userGrades[userId].index+'. '+Sliobj.userGrades[userId].name+' '+c;
}

function preAnswer() {
    // Pre-answer questions (and display notes for those)
    Slidoc.log('preAnswer:');
    var firstSlideId = getVisibleSlides()[0].id;
    var attr_vals = getChapterAttrs(firstSlideId);
    var chapter_id = parseSlideId(firstSlideId)[0];
    clearAnswerElements();

    if ('randomize_choice' in Sliobj.params.features) {
	// Handle choice randomization
	for (var qnumber=1; qnumber <= attr_vals.length; qnumber++) {
	    var question_attrs = attr_vals[qnumber-1];
	    if (!(question_attrs.qtype == 'choice' || question_attrs.qtype == 'multichoice'))
		continue;
	    var slide_id = chapter_id + '-' + zeroPad(question_attrs.slide, 2);
	    var qAttempted = Sliobj.session.questionsAttempted[qnumber] || null;
	    var shuffleStr = qAttempted ? qAttempted.shuffle : '';
	    if (Sliobj.adminState) {
		if (shuffleStr) {
		    var shuffleDiv = document.getElementById(slide_id+'-choice-shuffle');
		    if (shuffleDiv)
			shuffleDiv.innerHTML = '<code>(Shuffled: '+shuffleStr+')</code>';
		}

	    } else if (!shuffleStr && !qAttempted && Sliobj.session.paced) {
		// Randomize choice
		var choices = document.getElementsByClassName(slide_id+"-choice-elem");
		shuffleStr = Math.floor(2*Math.random()) + randomLetters(choices.length);
	    }
	    shuffleBlock(slide_id, shuffleStr)
	}
    }

    var keys = Object.keys(Sliobj.session.questionsAttempted);
    for (var j=0; j<keys.length; j++) {
	var qnumber = keys[j];
	var qAttempted = Sliobj.session.questionsAttempted[qnumber];
	var qfeedback = Sliobj.feedback ? (Sliobj.feedback[qnumber] || null) : null;
	var slide_id = chapter_id + '-' + zeroPad(qAttempted.slide, 2);
	Slidoc.answerClick(null, slide_id, qAttempted.response, qAttempted.explain||null, qAttempted.plugin, qfeedback);
    }

    if (Sliobj.session.submitted)
	showCorrectAnswers();
}

function shuffleBlock(slide_id, shuffleStr) {
    var choiceBlock = document.getElementById(slide_id+'-choice-block');
    choiceBlock.dataset.shuffle = '';
    if (!shuffleStr || Sliobj.adminState)
	return;
    //Slidoc.log('shuffleBlock: shuffleStr', slide_id, shuffleStr);
    var childNodes = choiceBlock.childNodes;
    var blankKey = ' ';
    var key = blankKey;
    var choiceElems = {}
    choiceElems[blankKey] = [];
    var altChoice = shuffleStr.charAt(0) != '0';
    for (var i=0; i < childNodes.length; i++) {
	var childElem = childNodes[i];
	if (childElem.firstElementChild && childElem.firstElementChild.classList.contains('slidoc-choice')) {
	    if (key == childElem.firstElementChild.dataset.choice && childElem.firstElementChild.classList.contains('slidoc-choice-elem-alt')) {
		// Alternative choice
		if (altChoice)
		    choiceElems[key] = [];   // Skip first choice
		else
		    key = null;  // Skip alternative choice
	    } else {
		// First choice
		key = childElem.firstElementChild.dataset.choice;
		choiceElems[key] = [];
	    }
	}
	if (key)
	    choiceElems[key].push(childElem)
    }

    if (Object.keys(choiceElems).length != shuffleStr.length) {
	Slidoc.log("slidocSetupAux: ERROR Incorrect number of choice elements for shuffling: Expected "+(shuffleStr.length-1)+" but found "+(Object.keys(choiceElems).length-1));
	return;
    }

    choiceBlock.dataset.shuffle = shuffleStr;
    choiceBlock.innerHTML = '';
    var key = blankKey;
    for (var i=0; i < choiceElems[key].length; i++)
	choiceBlock.appendChild(choiceElems[key][i]);
    for (var j=1; j < shuffleStr.length; j++) {
	key = shuffleStr.charAt(j);
	for (var i=0; i < choiceElems[key].length; i++) {
	    if (i == 0)
		choiceElems[key][i].firstElementChild.textContent = letterFromIndex(j-1);
	    choiceBlock.appendChild(choiceElems[key][i]);
	}
    }
}

function displayCorrect() {
    // Always display correct answers for submitted and graded sessions
    return !('delay_answers' in Sliobj.params.features) || (Sliobj.session && Sliobj.session.submitted && Sliobj.gradeDateStr);
}

function showCorrectAnswers() {
    Slidoc.log('showCorrectAnswers:');
    if (!displayCorrect())
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
	Slidoc.answerClick(null, slide_id, '', question_attrs.explain, null, qfeedback);
    }
}

/////////////////////////////////////////////
// Section 15: Session data getting/putting
/////////////////////////////////////////////

function sessionCreate() {
    var randomSeed = Slidoc.Random.getRandomSeed();
    return {version: Sliobj.params.sessionVersion,
	    revision: Sliobj.params.sessionRevision,
	    paced: Sliobj.params.paceLevel > 0,
	    submitted: null,
	    lateToken: '',
	    paceLevel: Sliobj.params.paceLevel || 0,
	    randomSeed: randomSeed,                   // Save random seed
            expiryTime: Date.now() + 180*86400*1000,  // 180 day lifetime
            startTime: Date.now(),
            lastTime: 0,
	    lastSlide: 0,
            lastTries: 0,
            remainingTries: 0,
            lastAnswersCorrect: 0,
            skipToSlide: 0,
            questionsCount: 0,
            questionsCorrect: 0,
            questionsSkipped: 0,
            weightedCount: 0,
            weightedCorrect: 0,
            questionsAttempted: {},
	    plugins: {},
            missedConcepts: []
	   };
}

function unpackSession(row) {
    var result = {};
    // Unpack hidden session
    result.session = JSON.parse( atob(row.session_hidden.replace(/\s+/, '')) );
    result.session.lateToken = row.lateToken || '';
    if (row.submitTimestamp) {
	result.session.submitted = row.submitTimestamp;
	result.session.lastSlide = Sliobj.params.pacedSlides;
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
	} else if (key == 'q_grades' && isNumber(value)) {
	    // Total grade
	    feedback.q_grades = value;
	    if (value)
		count += 1;
	}
    }

    result.feedback = count ? feedback : null;
    return result;
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

function sessionGetPutAux(callType, callback, retryCall, retryType, result, retStatus) {
    // For sessionPut, session should be bound to this function as 'this'
    Slidoc.log('Slidoc.sessionGetPutAux: ', callType, !!callback, !!retryCall, retryType, result, retStatus);
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

	if (retStatus && retStatus.info) {
	    if (retStatus.info.gradeDate)
		Sliobj.gradeDateStr = retStatus.info.gradeDate;
	    if (retStatus.info.dueDate)
		try { Sliobj.dueDate = new Date(retStatus.info.dueDate); } catch(err) { Slidoc.log('sessionGetPutAux: Error DUE_DATE: '+retStatus.info.dueDate, err); }
	    if (retStatus.info.submitTimestamp) {
		Sliobj.session.submitted = retStatus.info.submitTimestamp;
		Sliobj.session.lastSlide = Sliobj.params.pacedSlides;
		showCorrectAnswers();
		if (Sliobj.session.lateToken == 'partial' && window.confirm('Partial submission; reload page for accurate scores'))
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
		    alerts.push('<em>Warning:</em><br>'+err_info+'. Reloading page');
		    location.reload(true);
		} else if (msg_type == 'NEAR_SUBMIT_DEADLINE' || msg_type == 'PAST_SUBMIT_DEADLINE') {
		    if (session && !session.submitted)
			alerts.push('<em>Warning:</em><br>'+err_info);
		} else if (msg_type == 'INVALID_LATE_TOKEN') {
		    alerts.push('<em>Warning:</em><br>'+err_info);
		}
	    }
	    if (alerts.length)
		Slidoc.showPopup(alerts.join('<br>\n'));
	}
	if (callback) {
	    // Successful callback
	    callback(session, feedback);
	    ///Slidoc.reportEvent(callType+'Session');
	}
	return;

    } else if (retryCall) {
	if (err_msg) {
	    var prefix = (err_msg.indexOf('Invalid token') > -1) ? 'Invalid token. ' : '';
	    if (err_type == 'NEED_ROSTER_ENTRY') {
		GService.gprofile.promptUserInfo(GService.gprofile.auth.id,
					      err_info+'. Please enter a valid userID (or contact instuctor).',
					      Slidoc.userLoginCallback.bind(null, retryCall));
		return;
	    } else if (err_type == 'INVALID_ADMIN_TOKEN') {
		GService.gprofile.promptUserInfo(GService.gprofile.auth.id,
					      'Invalid admin token. Please re-enter',
					      Slidoc.userLoginCallback.bind(null, retryCall));
		return;

	    } else if (err_type == 'NEED_TOKEN' || err_type == 'INVALID_TOKEN') {
		GService.gprofile.promptUserInfo(GService.gprofile.auth.id,
					      'Invalid username/token. Please re-enter',
					      Slidoc.userLoginCallback.bind(null, retryCall));
		return;

	    } else if (this && (err_type == 'PAST_SUBMIT_DEADLINE' || err_type == 'INVALID_LATE_TOKEN')) {
		var prompt = prefix+"Enter late submission token, if you have one, for user "+GService.gprofile.auth.id+" and session "+Sliobj.sessionName+". Otherwise ";
		if (Sliobj.params.tryCount && Sliobj.session && Object.keys(Sliobj.session.questionsAttempted).length)
		    prompt += "enter 'partial' to submit and view correct answers.";
		else
		    prompt += "enter 'none' to submit late without credit.";
		var token = showDialog('prompt', 'lateTokenDialog', prompt);
		if (token && token.trim()) {
		    this.lateToken = token.trim();
		    retryCall();
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
    Slidoc.reportEvent('ERROR '+err_msg);
    sessionAbort('Error in accessing session info from Google Docs: '+err_msg+' (session aborted)');
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
	var curTime = Date.now()
	if (sessionObj[names[j]].expiryTime > curTime)
	    delete sessionObj[names[j]];
    }
}

function sessionGet(userId, sessionName, callback, retry) {
    // callback(session, feedback)
    if (Sliobj.params.gd_sheet_url) {
	// Google Docs storage
	var gsheet = getSheet(sessionName);
	// Freeze userId for retry only if validated
	if (!userId && GService.gprofile.auth.validated)
	    userId = GService.gprofile.auth.id;
	var retryCall = retry ? sessionGet.bind(null, userId, sessionName, callback, retry) : null;
	try {
	    gsheet.getRow(userId, sessionGetPutAux.bind(null, 'get', callback, retryCall, retry||''));
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
		callback(null);
	}
    }
}

function sessionPut(userId, session, opts, callback) {
    // Remote saving only happens if session.paced is true or force is true
    // callback(session, feedback)
    // opts = {nooverwrite:, get:, force: }
    Slidoc.log('sessionPut:', userId, Sliobj.sessionName, session, !!callback, opts);
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

	var rowObj = {};
	for (var j=0; j<Sliobj.params.sessionFields.length; j++) {
	    var header = Sliobj.params.sessionFields[j];
	    if (header.slice(0,7) != '_hidden' && header.slice(-9) != 'Timestamp') {
		rowObj[header] = session[header];
	    }
	}
	for (var j=0; j<Sliobj.params.gradeFields.length; j++) {
	    var header = Sliobj.params.gradeFields[j];
	    var hmatch = QFIELD_RE.exec(header);
	    if (hmatch && (hmatch[2] == 'response' || hmatch[2] == 'explain')) {
		// Copy only response/explain field for grading (all others are not updated)
		var qnumber = parseInt(hmatch[1]);
		if (qnumber in session.questionsAttempted) {
		    rowObj[header] = session.questionsAttempted[qnumber][hmatch[2]] || '';
		}
	    }
	}

	var base64str = btoa(JSON.stringify(session));
        // Break up Base64 version of object-json into lines (commnted out; does not work with JSONP)
	///var comps = [];
	///for (var j=0; j < base64str.length; j+=80)
	///    comps.push(base64str.slice(j,j+80));
	///comps.join('')+'';
	rowObj.session_hidden = base64str;
	var gsheet = getSheet(Sliobj.sessionName);
	// Bind session to this in sessionGetPutAux
	try {
	    gsheet.authPutRow(rowObj, putOpts, sessionGetPutAux.bind(session, 'put', callback||null, retryCall, opts.retry||''),
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
    return text.toLowerCase().trim().replace(/[^-\w\.]+/, '-').replace(/^[-\.]+/, '').replace(/[-\.]+$/, '');
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

function getVisibleSlides() {
   var slideClass = 'slidoc-slide';
   if (Sliobj.curChapterId) {
      var curChap = document.getElementById(Sliobj.curChapterId);
      if (curChap.classList.contains('slidoc-noslide'))
        return null;
      slideClass = Sliobj.curChapterId+'-slide';
   }
   return document.getElementsByClassName(slideClass);
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

Slidoc.sidebarDisplay = function (elem) {
    if (Sliobj.session.paced)
	return false;
    var toc_elem = document.getElementById("slidoc00");
    if (!toc_elem)
	return;
    var slides = getVisibleSlides();
    var curSlide = getCurrentlyVisibleSlide(slides);

    Sliobj.sidebar = !Sliobj.sidebar;
    toggleClass(Sliobj.sidebar, 'slidoc-sidebar-view');
    if (Sliobj.sidebar)
	toc_elem.style.display =  null;
    else if (Sliobj.curChapterId)
	toc_elem.style.display =  'none';

    if (curSlide)
	goSlide('#'+slides[curSlide-1].id);
    else if (Sliobj.curChapterId && Sliobj.curChapterId != 'slidoc00')
	goSlide('#'+Sliobj.curChapterId);
    else
	goSlide('#slidoc01');
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
        elements[i].style.display = (elements[i].style.display=='none') ? 'block' : 'none'
   }
   return false;
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
    if (Sliobj.params.tryCount) {
	Sliobj.session.lastAnswersCorrect = -2;   // Incorrect answer
	document.body.classList.add('slidoc-incorrect-answer-state');
    }
    var after_str = '';
    if (Sliobj.params.tryDelay) {
	Slidoc.delayIndicator(Sliobj.params.tryDelay, slide_id+'-answer-click');
	after_str = ' after '+Sliobj.params.tryDelay+' second(s)';
    }
    Slidoc.showPopup((msg || 'Incorrect.')+'<br> Please re-attempt question'+after_str+'.<br> You have '+Sliobj.session.remainingTries+' try(s) remaining');
    return false;
}

function checkAnswerStatus(setup, slide_id, question_attrs, explain) {
    if (!setup && Sliobj.session.paced && !Sliobj.currentSlide) {
	alert('Please switch to slide view to answer questions in paced mode');
	return false;
    }
    var textareaElem = document.getElementById(slide_id+'-answer-textarea');
    if (setup) {
	if (explain != null && textareaElem && question_attrs.explain) {
	    textareaElem.value = explain;
	    renderDisplay(slide_id, '-answer-textarea', '-response-div', question_attrs.explain == 'markdown');
	}
    } else if (question_attrs.explain && textareaElem && !textareaElem.value.trim()) {
	showDialog('alert', 'explainDialog', 'Please provide an explanation for the answer');
	return false;
    }
    return true;
}

Slidoc.choiceClick = function (elem, slide_id, choice_val) {
   Slidoc.log('Slidoc.choiceClick:', slide_id, choice_val);
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
    } else if (choice_val) {
	// Setup
	var choiceBlock = document.getElementById(slide_id+'-choice-block');
	var shuffleStr = choiceBlock.dataset.shuffle;
	for (var j=0; j<choice_val.length; j++) {
            var elemId = slide_id+'-choice-'+choice_val[j];
	    if (shuffleStr && shuffleStr.charAt(0) == '1')
		elemId += '-alt';
            var setupElem = document.getElementById(elemId);
            if (!setupElem) {
		Slidoc.log('Slidoc.choiceClick: Error - Setup failed for choice element '+elemId);
		return false;
            }
	    setupElem.classList.add('slidoc-choice-selected');
	}
    }
    return false;
}

Slidoc.answerClick = function (elem, slide_id, response, explain, pluginResp, qfeedback) {
   // Handle answer types: number, text
    Slidoc.log('Slidoc.answerClick:', elem, slide_id, response, explain, pluginResp, qfeedback);
    var question_attrs = getQuestionAttrs(slide_id);

    var setup = !elem;
    var checkOnly = elem && elem.classList.contains('slidoc-check-button');

    if (!checkAnswerStatus(setup, slide_id, question_attrs, explain))
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
	if (!checkOnly && !Slidoc.answerPacedAllow())
	    return false;
       response = '';
    }

    var pluginMatch = /^(\w+)\.response\(\)(;(.+))?$/.exec(question_attrs.correct || '');
    if (pluginMatch) {
	var pluginName = pluginMatch[1];
	if (setup) {
	    Slidoc.PluginMethod(pluginName, slide_id, 'display', response, pluginResp);
	    Slidoc.answerUpdate(setup, slide_id, false, response, pluginResp);
	} else {
	    if (Sliobj.session.remainingTries > 0)
		Sliobj.session.remainingTries -= 1;

	    var retryMsg = Slidoc.PluginMethod(pluginName, slide_id, 'response',
				      (Sliobj.session.remainingTries > 0),
				      Slidoc.answerUpdate.bind(null, setup, slide_id, false));
	    if (retryMsg)
		Slidoc.PluginRetry(retryMsg);
	}
	if (!checkOnly && (setup || !Sliobj.session.paced || Sliobj.session.remainingTries == 1))
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
	if (corr_answer && displayCorrect()) {
	    var choiceBlock = document.getElementById(slide_id+'-choice-block');
	    var shuffleStr = choiceBlock.dataset.shuffle;
	    for (var j=0; j<corr_answer.length; j++) {
		var elemId = slide_id+'-choice-'+corr_answer[j];
		if (shuffleStr && shuffleStr.charAt(0) == '1')
		    elemId += '-alt';
		var corr_choice = document.getElementById(elemId);
		if (corr_choice) {
		    corr_choice.style['font-weight'] = 'bold';
		}
	    }
	}
    }  else {
	var multiline = question_attrs.qtype.slice(0,5) == 'text/';
	var inpElem = document.getElementById(multiline ? slide_id+'-answer-textarea' : slide_id+'-answer-input');
	if (inpElem) {
	    if (setup) {
		inpElem.value = response;
	    } else {
		response = inpElem.value.trim();
		if (question_attrs.qtype == 'number' && !isNumber(response)) {
		    alert('Expecting a numeric value as answer');
		    return false;
		} else if (Sliobj.session.paced && !checkOnly) {
		    if (!response) {
			alert('Expecting a non-null answer');
			return false;
		    } else if (Sliobj.session.paced && Sliobj.lastInputValue && Sliobj.lastInputValue == response) {
			alert('Please try a different answer this time!');
			return false;
		    }
		    Sliobj.lastInputValue = response;
		}
	    }
	    if (!checkOnly && (setup || !Sliobj.session.paced || Sliobj.session.remainingTries == 1))
		inpElem.disabled = 'disabled';
	}

	if (!setup && !checkOnly && Sliobj.session.remainingTries > 0)
	    Sliobj.session.remainingTries -= 1;
    }

    Slidoc.answerUpdate(setup, slide_id, checkOnly, response);
    return false;
}

Slidoc.answerUpdate = function (setup, slide_id, checkOnly, response, pluginResp) {
    Slidoc.log('Slidoc.answerUpdate: ', setup, slide_id, checkOnly, response, pluginResp);

    if (!setup && Sliobj.session.paced)
	Sliobj.session.lastTries += 1;

    var qscore = null;
    var question_attrs = getQuestionAttrs(slide_id);

    var corr_answer      = question_attrs.correct || '';
    var corr_answer_html = question_attrs.html || '';

    Slidoc.log('Slidoc.answerUpdate:', slide_id);

    if (pluginResp) {
	qscore = isNumber(pluginResp.score) ? pluginResp.score : null;
	corr_answer = (isNumber(pluginResp.answer) || pluginResp.answer) ? pluginResp.answer : '';
    } else {
	var pluginMatch = /^(\w+)\.expect\(\)(;(.+))?$/.exec(corr_answer);
	if (pluginMatch) {
	    var pluginName = pluginMatch[1];
	    var val = Slidoc.PluginMethod(pluginName, slide_id, 'expect');
	    if (val) {
		corr_answer = val;
		corr_answer_html = '<code>'+corr_answer+'</code>';
	    } else {
		corr_answer = pluginMatch[3] ? pluginMatch[3] : '';
	    }
	}
	if (corr_answer) {
	    // Check response against correct answer
	    qscore = 0;
	    if (question_attrs.qtype == 'number') {
		// Check if numeric answer is correct
		var corr_value = null;
		var corr_error = 0.0;
		try {
		    var comps = corr_answer.split('+/-');
		    corr_value = parseFloat(comps[0]);
		    if (comps.length > 1)
			corr_error = parseFloat(comps[1]);
		} catch(err) {Slidoc.log('Slidoc.answerUpdate: Error in correct numeric answer:'+corr_answer);}
		var resp_value = null;
		try {
		    resp_value = parseFloat(response);
		} catch(err) {Slidoc.log('Slidoc.answerUpdate: Error - invalid numeric response:'+response);}
		
		if (corr_value !== null && resp_value != null)
		    qscore = (Math.abs(resp_value - corr_value) <= 1.001*corr_error) ? 1 : 0;
	    } else {
		// Check if non-numeric answer is correct (all spaces are removed before comparison)
		var norm_resp = response.trim().toLowerCase();
		var correct_options = corr_answer.split(' OR ');
		for (var k=0; k < correct_options.length; k++) {
		    var norm_corr = correct_options[k].trim().toLowerCase().replace(/\s+/, ' ');
		    if (norm_corr.indexOf(' ') > 0) {
			// Correct answer has space(s); compare using normalized spaces
			qscore = (norm_resp.replace(/\s+/, ' ') == norm_corr) ? 1 : 0;
		    } else {
			// Strip all spaces from response
			qscore = (norm_resp.replace(/\s+/, '') == norm_corr) ? 1 : 0;
		    }
		    if (qscore)
			break;
		}
	    }
	    if (!setup && isNumber(qscore) && qscore < 1 && Sliobj.session.remainingTries > 0) {
	        Slidoc.PluginRetry();
	        return false;
	    }
	}
    }

    // Handle randomized choices
    var disp_response = response;
    var disp_corr_answer = corr_answer;
    var shuffleStr = '';
    if (question_attrs.qtype == 'choice' || question_attrs.qtype == 'multichoice') {
	var choiceBlock = document.getElementById(slide_id+'-choice-block');
	shuffleStr = choiceBlock.dataset.shuffle;
	if (shuffleStr) {
	    disp_response = choiceShuffle(response, shuffleStr);
	    disp_corr_answer = choiceShuffle(corr_answer, shuffleStr);
	}
    }

    // Display correctness of response
    if (displayCorrect()) {
	setAnswerElement(slide_id, '-correct-mark', '', qscore === 1 ? ' '+SYMS['correctMark']+'&nbsp;' : '');
	setAnswerElement(slide_id, '-partcorrect-mark', '', (isNumber(qscore) && qscore > 0 && qscore < 1) ? ' '+SYMS['partcorrectMark']+'&nbsp;' : '');
	setAnswerElement(slide_id, '-wrong-mark', '', (qscore === 0) ? ' '+SYMS['wrongMark']+'&nbsp;' : '');
	setAnswerElement(slide_id, '-any-mark', '', !isNumber(qscore) ? '<b>'+SYMS['anyMark']+'</b>' : '');  // Not check mark
    
	// Display correct answer
	setAnswerElement(slide_id, "-answer-correct", disp_corr_answer||'', corr_answer_html);
    }

    var notes_id = slide_id+"-notes";
    var notes_elem = document.getElementById(notes_id);
    if (notes_elem && displayCorrect()) {
	// Display of any notes associated with this question
	Slidoc.idDisplay(notes_id);
	notes_elem.style.display = 'inline';
	Slidoc.classDisplay(notes_id, 'block');
    }

    // Question has been answered
    var slideElem = document.getElementById(slide_id);
    slideElem.classList.add('slidoc-answered-slideview');

    if (pluginResp)
	Slidoc.PluginMethod(pluginResp.name, slide_id, 'disable', displayCorrect() && qscore !== 1);

    if (question_attrs.qtype.slice(0,5) == 'text/') {
	renderDisplay(slide_id, '-answer-textarea', '-response-div', question_attrs.qtype.slice(-8) == 'markdown');
    } else {
	if (question_attrs.explain)
	    renderDisplay(slide_id, '-answer-textarea', '-response-div', question_attrs.explain == 'markdown');
	setAnswerElement(slide_id, '-response-span', disp_response);
    }

    if (!setup) {
	var explain = '';
	if (question_attrs.explain) {
	    var textareaElem = document.getElementById(slide_id+'-answer-textarea');
	    explain = textareaElem.value;
	}
	Sliobj.session.questionsAttempted[question_attrs.qnumber] = {slide: parseSlideId(slide_id)[2],
							      resp_type: question_attrs.qtype,
							      response: response,
							      explain: explain,
							      shuffle: shuffleStr,
							      plugin: pluginResp||null,
							      expect: corr_answer,
							      score: isNumber(qscore) ? qscore : null};
	Slidoc.answerTally(qscore, slide_id, question_attrs);
    }
}


Slidoc.answerTally = function (qscore, slide_id, question_attrs) {
    Slidoc.log('Slidoc.answerTally: ', qscore, slide_id, question_attrs);

    var slide_num = parseSlideId(slide_id)[2];
    if (slide_num < Sliobj.session.skipToSlide) {
	Slidoc.reportEvent('answerSkip');
	saveSession();
	return;
    }

    var qSkipfac = 1;
    var qWeight = question_attrs.weight;

    var skip = question_attrs.skip || null;
    if (Sliobj.session.paced) {
	Sliobj.session.remainingTries = 0;
	document.body.classList.remove('slidoc-expect-answer-state');
	if (Sliobj.params.tryCount) {
	    if (qscore === 1 && Sliobj.session.lastAnswersCorrect >= 0) {
		// 2 => Current sequence of "correct" answers
		if (skip && skip[0] > slide_num) {
		    // Skip ahead
		    Sliobj.session.lastAnswersCorrect = 1;
		    Sliobj.session.skipToSlide = skip[0];

		    // Give credit for all skipped questions
		    qSkipfac += skip[1];
		    qWeight += skip[2]
		    Sliobj.session.questionsSkipped += skip[1];

		    if (skip[3]) // Re-enable forward links for this slide
			toggleClassAll(true, 'slidoc-forward-link-allowed', skip[3]);
		} else {
		    // No skipping
		    Sliobj.session.lastAnswersCorrect = 2;
		}
	    } else {
		// -2 => Current sequence with at least one incorrect answer
		Sliobj.session.lastAnswersCorrect = -2;
		document.body.classList.add('slidoc-incorrect-answer-state');
	    }
	}
    }

    // Keep score
    Sliobj.session.questionsCount += qSkipfac;
    Sliobj.session.weightedCount += qWeight;
    var effectiveScore = isNumber(qscore) ? qscore : 1;   // Give full credit to unscored answers
    if (effectiveScore) {
        Sliobj.session.questionsCorrect += qSkipfac;
        Sliobj.session.weightedCorrect += effectiveScore*qWeight;
    }
    Slidoc.showScore();
    Slidoc.reportEvent('answerTally');
    
    if (Sliobj.session.paced && Sliobj.questionConcepts.length > 0) {
	// Track missed concepts
	var concept_elem = document.getElementById(slide_id+"-concepts");
	var concepts = concept_elem ? concept_elem.textContent.split('; ') : ['null'];
	var miss_count = (!isNumber(qscore) || qscore === 1) ? 0 : 1;
	
	for (var j=0; j<concepts.length; j++) {
	    var m = (j == 0) ? 0 : 1;   // Primary/secondary concept
	    for (var k=0; k<Sliobj.questionConcepts[m].length; k++) {
		if (concepts[j] == Sliobj.questionConcepts[m][k]) {
		    Sliobj.session.missedConcepts[m][k][0] += miss_count; //Missed count
		    Sliobj.session.missedConcepts[m][k][1] += 1;   //Attempted count
		}
	    }
	}
    }
    saveSession();
}

function saveSession() {
    if (!Sliobj.session.paced || Sliobj.session.submitted)
	return;
    Sliobj.session.lastTime = Date.now();
    if (!Sliobj.params.gd_sheet_url || Sliobj.params.tryCount)
	sessionPut();
}

Slidoc.showScore = function () {
    var scoreElem = document.getElementById('slidoc-score-display');
    if (!scoreElem)
	return;
    if (Sliobj.session.questionsCount) {
	if (Sliobj.session.submitted && Sliobj.params.scoreWeight && displayCorrect())
	    scoreElem.textContent = Sliobj.session.weightedCorrect+' ('+Sliobj.params.scoreWeight+')';
	else
	    scoreElem.textContent = Sliobj.session.questionsCount+'/'+Sliobj.params.questionsMax;
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

//////////////////////////
// Section 18: Grading
//////////////////////////

function showSubmitted() {
    var submitElem = document.getElementById('slidoc-submit-display');
    if (!submitElem || !Sliobj.params.gd_sheet_url)
	return;
    if (Sliobj.session.submitted) {
	submitElem.innerHTML = (Sliobj.session.lateToken == 'none') ? SYMS['xBoxMark'] : SYMS['correctMark'];
    } else {
	submitElem.innerHTML = Sliobj.session.submitted ? SYMS['wrongMark'] : SYMS['anyMark'];
    }
}

Slidoc.submitStatus = function () {
    Slidoc.log('Slidoc.submitStatus: ');
    var html = '';
    if (Sliobj.session.submitted) {
	html += 'User '+GService.gprofile.auth.id+' submitted session to Google Docs on '+ Sliobj.session.submitted;
	if (Sliobj.session.lateToken)
	    html += ' LATE';
	if (Sliobj.session.lateToken == 'none')
	    html += ' (NO CREDIT)';
    } else {
	var html = 'Session not submitted.'
	if (!Sliobj.adminState)
	    html += ' Click <span class="slidoc-clickable" onclick="Slidoc.submitSession();">here</span> to submit session'+((Sliobj.session.lastSlide < getVisibleSlides().length) ? ' without reaching the last slide':'');
    }
    if (Sliobj.adminState) {
	if (Sliobj.gradeDateStr)
	    html += '<hr>Grades released to students at '+Sliobj.gradeDateStr;
	else
	    html += '<hr><span class="slidoc-clickable" onclick="Slidoc.releaseGrades();">Release grades to students</span';
    }
    Slidoc.showPopup(html);
}

Slidoc.submitSession = function () {
    Slidoc.log('Slidoc.submitSession: ');
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    if (!showDialog('confirm', 'submitDialog', 'Do you really want to submit session without reaching the last slide?'))
	return;
    Slidoc.endPaced();
}

Slidoc.releaseGrades = function () {
    Slidoc.log('Slidoc.releaseGrades: ');
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    if (!window.confirm('Confirm releasing grades to students?'))
	return;
    
    var updates = {id: Sliobj.sessionName, gradeDate: new Date()};
    Sliobj.indexSheet.updateRow(updates, {}, releaseGradesCallback);
}

function releaseGradesCallback(result, retStatus){
    Slidoc.log('releaseGradesCallback:', result, retStatus);
    if (result)
	alert('Grade Date updated in index sheet '+Sliobj.params.index_sheet+' to release grades to students');
    else
	alert('Error: Failed to update Grade Date in index sheet '+Sliobj.params.index_sheet+'; grades not released to students ('+retStatus.error+')');
}

function conceptStats(tags, tallies) {
    var scores = [];
    for (var j=0; j<tags.length; j++) {
	scores.push([tags[j], tallies[j][0], tallies[j][1]]);
    }
    function cmp(a,b) { if (a == b) return 0; else return (a > b) ? 1 : -1;}
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

    var gradeInput = document.getElementById(slide_id+'-grade-input');
    var commentsArea = document.getElementById(slide_id+'-comments-textarea');
    if (!elem && gradeInput.value)  // Grading already completed; do not automatically start
	return false;

    var startGrading = !elem || elem.classList.contains('slidoc-gstart-click');
    toggleClass(startGrading, 'slidoc-grading-slideview', document.getElementById(slide_id));
    if (startGrading) {
	if (!commentsArea.value && 'quote_response' in Sliobj.params.features)
	    Slidoc.quoteText(null, slide_id);
	setTimeout(function(){gradeInput.focus();}, 200);
	Slidoc.reportEvent('gradeStart');
    } else {
	var question_attrs = getQuestionAttrs(slide_id);
	var gradeValue = gradeInput.value.trim();
	var commentsValue = commentsArea.value.trim();
	setAnswerElement(slide_id, '-grade-content', gradeValue);
	renderDisplay(slide_id, '-comments-textarea', '-comments-content', true)

	var gradeField = 'q'+question_attrs.qnumber+'_grade';
	var commentsField = 'q'+question_attrs.qnumber+'_comments';
	if (!(gradeField in Sliobj.gradeFieldsObj))
	    Slidoc.log('Slidoc.gradeClick: ERROR grade field '+gradeField+' not found in sheet');
	var updates = {id: GService.gprofile.auth.id};
	updates[gradeField] = gradeValue;
	updates[commentsField] = commentsValue;
	gradeUpdate(slide_id, question_attrs.qnumber, updates);
    }
}

function gradeUpdate(slide_id, qnumber, updates, callback) {
    Slidoc.log('gradeUpdate: ', slide_id, qnumber, updates, !!callback);
    var updateObj = copyAttributes(updates);
    updateObj.Timestamp = null;  // Ensure that Timestamp is updated

    var gsheet = getSheet(Sliobj.sessionName);
    var retryCall = gradeUpdate.bind(null, qnumber, updates, callback);

    try {
	gsheet.updateRow(updateObj, {}, sessionGetPutAux.bind(null, 'update',
 		         gradeUpdateAux.bind(null, updateObj.id, slide_id, qnumber, callback), retryCall, 'gradeUpdate') );
    } catch(err) {
	sessionAbort(''+err, err.stack);
	return;
    }

    showPendingCalls();
    
    if (gsheet.pendingUpdates > 1)
	return;

    if (!Slidoc.testingActive()) {
	// Move on to next user if slideshow mode, else to next question
	if (Sliobj.currentSlide) {
	    if (Sliobj.gradingUser < Sliobj.userList.length) {
		Slidoc.nextUser(true);
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

function gradeUpdateAux(userId, slide_id, qnumber, callback, result, retStatus) {
    Slidoc.log('gradeUpdateAux: ', userId, slide_id, qnumber, !!callback, result, retStatus);
    delete Sliobj.userGrades[userId].grading[qnumber];
    updateGradingStatus(userId);
    Slidoc.reportEvent('gradeUpdate');
}

/////////////////////////////////////////
// Section 19: Paced session management
/////////////////////////////////////////

Slidoc.startPaced = function () {
    Slidoc.log('Slidoc.startPaced: ');
    Sliobj.delaySec = null;

    var firstSlideId = getVisibleSlides()[0].id;

    if (!Sliobj.session.lastSlide) {
	// Start of session
	if (Sliobj.questionConcepts.length > 0) {
	    Sliobj.session.missedConcepts = [ [], [] ];
	    for (var m=0; m<2; m++) {
		for (var k=0; k<Sliobj.questionConcepts[m].length; k++) {
		    Sliobj.session.missedConcepts[m].push([0,0]);
		}
	    }
	} else {
	    Sliobj.session.missedConcepts = [];
	}
    } else {
	if (Sliobj.session.missedConcepts.length > 0 && Sliobj.questionConcepts.length > 0 &&
	    (Sliobj.session.missedConcepts[0].length != Sliobj.questionConcepts[0].length ||
	     Sliobj.session.missedConcepts[1].length != Sliobj.questionConcepts[1].length) )
	    alert('ERROR: Mismatch between question concepts and missed concepts length (reset session, if possible)');
    }

    Slidoc.hide(document.getElementById(firstSlideId+'-hidenotes'), 'slidoc-notes', '-'); // Hide notes for slide view
    Slidoc.classDisplay('slidoc-question-notes', 'none'); // Hide notes toggle for pacing
    preAnswer();

    var curDate = new Date();
    if (Sliobj.dueDate && curDate > Sliobj.dueDate && Sliobj.session.lateToken != 'none') {
	// Past submit deadline
	if (!Sliobj.session.submitted && Sliobj.params.tryCount) {
	    Slidoc.endPaced();
	    return;
	}
    }

    document.body.classList.add('slidoc-paced-view');
    if (Sliobj.session.paceLevel > 1)
	document.body.classList.add('slidoc-strict-paced-view');
    // Allow forward link only if no try requirement
    toggleClassAll(!Sliobj.params.tryCount, 'slidoc-forward-link-allowed', 'slidoc-forward-link');

    var startMsg = 'Starting'+((Sliobj.session.paceLevel>1)?' strictly':'')+' paced slideshow '+Sliobj.sessionName+':<br>';
    if (Sliobj.params.questionsMax)
	startMsg += '&nbsp;&nbsp;<em>There are '+Sliobj.params.questionsMax+' questions.</em><br>';
    if (Sliobj.params.gd_sheet_url) {
	if (Sliobj.params.tryCount)
	    startMsg += '&nbsp;&nbsp;<em>Answers will be submitted after each answered question.</em><br>';
	else
	    startMsg += '&nbsp;&nbsp;<em>Answers will only be submitted when you reach the last slide.&nbsp;&nbsp;<br>If you do not complete and move to a different computer, you will have to start over again.</em><br>';
    }
    startMsg += '<ul>';
    if (Sliobj.params.paceDelay)
	startMsg += '<li>'+Sliobj.params.paceDelay+' sec delay between slides</li>';
    if (Sliobj.params.tryCount == 1)
	startMsg += '<li>'+Sliobj.params.tryCount+' attempt for each question</li>';
    if (Sliobj.params.tryCount > 1)
	startMsg += '<li>'+Sliobj.params.tryCount+' attempts for non-choice questions</li>';
    if (Sliobj.params.tryDelay)
	startMsg += '<li>'+Sliobj.params.tryDelay+' sec delay between attempts</li>';
    startMsg += '</ul>';
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
    if (Sliobj.session.paceLevel <= 1) {
	// If pace can end, unpace
	document.body.classList.remove('slidoc-paced-view');
	Sliobj.session.paced = false;
    }
    Slidoc.reportEvent('endPaced');
    sessionPut(null, null, {force: true, retry: 'end_paced', submit: true});
    showCompletionStatus();
}

Slidoc.answerPacedAllow = function () {
    if (!Sliobj.session.paced)
	return true;

    if (Sliobj.params.tryDelay && Sliobj.session.lastTries > 0) {
	var delta = (Date.now() - Sliobj.session.lastTime)/1000;
	if (delta < Sliobj.params.tryDelay) {
	    alert('Please wait '+ Math.ceil(Sliobj.params.tryDelay-delta) + ' second(s) to answer again');
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
		msg += 'Completed session <b>submitted successfully</b> to Google Docs at '+Sliobj.session.submitted+'<br>';
		if (!Sliobj.session.paced)
		    msg += 'You may now exit the slideshow and access this document normally.<br>';
	    } else {
		alert('Completed session submitted successfully to Google Docs at '+Sliobj.session.submitted);
		return;
	    }
	} else  {
	    msg += 'Do not close this popup. Wait for confirmation that session has been submitted to Google Docs<br>';
	}
    } else if (!Sliobj.session.paced) {
	msg += 'You may now exit the slideshow and access this document normally.<br>';
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
       startSlide = Sliobj.session.lastSlide || 1; 
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
    Slidoc.reportEvent('initSlideView');
    return false;
}

Slidoc.slideViewEnd = function() {
    if (Sliobj.session.paced && Sliobj.session.paceLevel > 1) {
	var msgStr = 'Cannot exit slide view when in strictly paced mode';
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

    if (Sliobj.session.paced) {
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
    Sliobj.questionSlide = '';

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
    Slidoc.log('Slidoc.slideViewGo:', forward, slide_num);
    var slides = getVisibleSlides();
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

    if (Sliobj.session.paced && Sliobj.params.tryCount && slide_num > Sliobj.session.lastSlide+1 && slide_num > Sliobj.session.skipToSlide) {
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
	if (slide_num == slides.length && Sliobj.session.questionsCount < Sliobj.params.questionsMax) {
	    var prompt = 'You have only answered '+Sliobj.session.questionsCount+' of '+Sliobj.params.questionsMax+' questions. Do you wish to go to the last slide and end the paced session?';
	    if (!showDialog('confirm', 'lastSlideDialog', prompt))
		return false;
	}
	if (Sliobj.questionSlide && Sliobj.session.remainingTries) {
	    // Current (not new) slide is question slide
	    var tryCount =  (Sliobj.questionSlide=='choice') ? 1 : Sliobj.session.remainingTries;
	    var prompt = 'Please answer before proceeding. You have '+tryCount+' try(s)';
	    showDialog('alert', 'requireAnswerDialog', prompt);
	    return false;
	} else if (!Sliobj.questionSlide && Sliobj.delaySec) {
	    // Current (not new) slide is not question slide; has delay
	    var delta = (Date.now() - Sliobj.session.lastTime)/1000;
	    if (delta < Sliobj.delaySec) {
		alert('Please wait '+ Math.ceil(Sliobj.delaySec-delta) + ' second(s)');
		return false;
	    }
	}
        // Update session for new slide
	Sliobj.session.lastSlide = slide_num; 
	Sliobj.session.lastTime = Date.now();
	Sliobj.questionSlide = question_attrs ? question_attrs.qtype : '';

	Sliobj.session.lastTries = 0;
	if (Sliobj.questionSlide) {
	    if (Sliobj.session.lastAnswersCorrect != 2 && Sliobj.session.lastAnswersCorrect != -2) // New seq. of questions
		Sliobj.session.lastAnswersCorrect = 0;
	    Sliobj.session.remainingTries = Sliobj.params.tryCount;
	} else {
            // 1 => Last sequence of questions was answered correctly
	    Sliobj.session.lastAnswersCorrect = (Sliobj.session.lastAnswersCorrect > 0) ? 1 : -1;
	    Sliobj.session.remainingTries = 0;
        }

	Sliobj.delaySec = null;
	var pluginButton = document.getElementById("slidoc-button-plugin");
	if (slide_id in Sliobj.buttonPlugins) {
	    pluginButton.innerHTML = Sliobj.activePlugins[Sliobj.buttonPlugins[slide_id].name].button[slide_id]
	    pluginButton.style.display = null;
	} else {
	    pluginButton.innerHTML = '';
	    pluginButton.style.display = 'none';
	}
	if (slide_id in Sliobj.slidePlugins) {
	    for (var j=0; j<Sliobj.slidePlugins[slide_id].length; j++) {
		var delaySec = Slidoc.PluginManager.optCall(Sliobj.slidePlugins[slide_id][j], 'enterSlide', true, backward);
		if (delaySec != null)
		    Sliobj.delaySec = delaySec;
	    }
	}

	if (Sliobj.delaySec == null && !Sliobj.questionSlide) // Default delay only for non-question slides
	    Sliobj.delaySec = Sliobj.params.paceDelay;
	if (Sliobj.delaySec)
	    Slidoc.delayIndicator(Sliobj.delaySec, 'slidoc-slide-nav-prev', 'slidoc-slide-nav-next');

	if (Sliobj.session.lastSlide == slides.length) {
	    // Last slide
	    Slidoc.endPaced();

	} else if (Sliobj.sessionName && !Sliobj.params.gd_sheet_url) {
	    // Not last slide; save updated session (if not transient and not remote)
	    sessionPut();
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
	Sliobj.questionSlide = question_attrs ? question_attrs.qtype : '';
	if (slide_id in Sliobj.slidePlugins) {
	    for (var j=0; j<Sliobj.slidePlugins[slide_id].length; j++)
		Slidoc.PluginManager.optCall(Sliobj.slidePlugins[slide_id][j], 'enterSlide', false, backward);
	}
    }

    if (Sliobj.session.paced) {
	toggleClass(Sliobj.params.tryCount && Sliobj.session.lastAnswersCorrect < 0, 'slidoc-incorrect-answer-state');
	toggleClass(slide_num == Sliobj.session.lastSlide, 'slidoc-paced-last-slide');
	toggleClass(Sliobj.session.remainingTries, 'slidoc-expect-answer-state');
    }
    toggleClass(slide_num < Sliobj.session.skipToSlide, 'slidoc-skip-optional-slide');

    var prev_elem = document.getElementById('slidoc-slide-nav-prev');
    var next_elem = document.getElementById('slidoc-slide-nav-next');
    prev_elem.style.visibility = (slide_num == 1) ? 'hidden' : 'visible';
    next_elem.style.visibility = (slide_num == slides.length) ? 'hidden' : 'visible';
    var counterElem = document.getElementById('slidoc-slide-nav-counter');
    counterElem.textContent = ((slides.length <= 9) ? slide_num : zeroPad(slide_num,2))+'/'+slides.length;

    Slidoc.log('Slidoc.slideViewGo:C', slide_num, slides[slide_num-1]);
    Sliobj.maxIncrement = 0;
    Sliobj.curIncrement = 0;
    if ('incremental_slides' in Sliobj.params.features) {
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
    if (Sliobj.session.paced && Sliobj.session.paceLevel > 1 && !Sliobj.currentSlide && !singleChapter) {
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
    if (Sliobj.sidebar && slideId.slice(0,8) == 'slidoc00')
	slideId = 'slidoc01-01';

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
Slidoc.showPopup = function (innerHTML, divElemId, autoCloseMillisec) {
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
	return;
    }

    if (!divElemId) divElemId = 'slidoc-generic-popup';
    var divElem = document.getElementById(divElemId);
    var closeElem = document.getElementById(divElem.id+'-close');
    var overlayElem = document.getElementById('slidoc-generic-overlay');
    if (!overlayElem) {
	alert('slidoc: INTERNAL ERROR - no overlay for popup ');
    } else if (!divElem) {
	alert('slidoc: INTERNAL ERROR - no div for popup'+divElemId);
    } else if (!closeElem) {
	alert('slidoc: INTERNAL ERROR - no close for popup'+divElemId);
    } else {
	if (innerHTML) {
	    var contentElem = document.getElementById(divElem.id+'-content')
	    if (contentElem)
		contentElem.innerHTML = innerHTML;
	    else
		alert('slidoc: INTERNAL ERROR - no content for popup'+divElemId)
	}
	overlayElem.style.display = 'block';
	divElem.style.display = 'block';

	Sliobj.closePopup = function (closeAll) {
	    overlayElem.style.display = 'none';
	    divElem.style.display = 'none';
	    Sliobj.closePopup = null;
	    if (closeAll) {
		Sliobj.popupQueue = [];
	    } else {
		if (Sliobj.popupQueue && Sliobj.popupQueue.length) {
		    var args = Sliobj.popupQueue.shift();
		    Slidoc.showPopup(args[0], args[1]);
		}
	    }
	    Slidoc.advanceStep();
	}
	
	closeElem.onclick = Sliobj.closePopup;
	if (autoCloseMillisec)
	    setTimeout(Sliobj.closePopup, autoCloseMillisec);
    }
    window.scrollTo(0,0);
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
