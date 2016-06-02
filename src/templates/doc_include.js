// JS include file for slidoc

var Slidoc = {};  // External object

var SlidocPlugins = {}; // JS plugins
var SlidocPluginManager = {}; // JS plugins manager
var SlidocRandom = null;

///UNCOMMENT: (function(Slidoc) {

var MAX_INC_LEVEL = 9; // Max. incremental display level

var CACHE_GRADING = true; // If true, cache all rows for grading

var QFIELD_RE = /^q(\d+)_([a-z]+)(_[0-9\.]+)?$/;

var SYMS = {correctMark: '&#x2714;', partcorrectMark: '&#x2611;', wrongMark: '&#x2718;', anyMark: '&#9083;', xBoxMark: '&#8999;'};

var uagent = navigator.userAgent.toLowerCase();
var isSafari = (/safari/.test(uagent) && !/chrome/.test(uagent));
var useJSONP = (location.protocol == 'file:' || (isSafari && location.hostname.toLowerCase() == 'localhost') );

var Sliobj = {}; // Internal object
Sliobj.params = JS_PARAMS_OBJ;
Sliobj.sessionName = Sliobj.params.paceLevel ? Sliobj.params.sessionName : '';

Sliobj.gradeFieldsObj = {};
for (var j=0; j<Sliobj.params.gradeFields.length; j++)
    Sliobj.gradeFieldsObj[Sliobj.params.gradeFields[j]] = 1;

Sliobj.adminState = null;
Sliobj.firstTime = true;
Sliobj.closePopup = null;
Sliobj.activePlugins = {};
Sliobj.pluginList = [];
Sliobj.pluginData = null;

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
    var args = Array.prototype.slice.call(arguments);
    var match = /^([\.\w]+)(:\s*|\s+|$)(ERROR|WARNING)?/i.exec(''+arguments[0]);
    if (match && match[3] && match[3].toUpperCase() == 'ERROR') {
	Slidoc.logDump();
    } else {
	Sliobj.logQueue.push(JSON.stringify(args));
	if (Sliobj.logQueue.length > Sliobj.logMax)
	    Sliobj.logQueue.shift();
    }
    if ( (Sliobj.logRe && Sliobj.logRe.exec(''+arguments[0])) || !match ||
		    (match && match[3] && (match[3].toUpperCase() == 'ERROR' || match[3].toUpperCase() == 'WARNING')) )
	console.log.apply(console, arguments);
}

Sliobj.sheets = {};
function getSheet(name) {
    if (Sliobj.sheets[name])
	return Sliobj.sheets[name];

    var fields = Sliobj.params.sessionFields;
    if (name == Sliobj.params.sessionName)
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
		    alert('Error: user ID '+userId+' not found for this session');
		    userId = '';
		}
		if (!userId)  // Pick the first user ID
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

var debugAbort = true;
var sessionAborted = false;
function sessionAbort(err_msg, err_trace) {
    if (sessionAborted)
	return;
    sessionAborted = true;
    localDel('auth');
    try { Slidoc.classDisplay('slidoc-slide', 'none'); } catch(err) {}
    alert((debugAbort ? 'DEBUG: ':'')+err_msg);
    if (!debugAbort)
	document.body.textContent = err_msg + ' (reload page to restart)   '+(err_trace || '');
    throw(err_msg);
}

function abortOnError(boundFunc) {
    // Usage: abortOnError(func.bind(null, arg1, arg2, ...))
    try {
	return boundFunc();
    } catch(err) {
	console.log("abortOnError: ERROR", err, err.stack);
	sessionAbort('abortOnError: ERROR '+err, err.stack);
    }
}

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

function getParameter(name, number, queryStr) {
   // Set number to true, if expecting an integer value. Returns null if valid parameter is not present.
   // If queryStr is specified, it is used instead of location.search
   var match = RegExp('[?&]'+name+'=([^&]*)').exec(queryStr || window.location.search);
   if (!match)
      return null;
   var value = decodeURIComponent(match[1].replace(/\+/g, ' '));
   if (number) {
       try { value = parseInt(value); } catch(err) { value = null };
   }
   return value;
}

Slidoc.getParameter = getParameter;

var resetParam = getParameter('reset');
if (resetParam) {
    if (resetParam == 'all' && window.confirm('Reset all local sessions?')) {
	localDel('auth');
	localDel('sessions');
	alert('All local sessions reset');
	location = location.href.split('?')[0];
    } else if (window.confirm('Reset session '+Sliobj.params.sessionName+'?')) {
	localDel('auth');
	var sessionObj = localGet('sessions');
	delete sessionObj[Sliobj.params.sessionName];
	localPut('sessions', sessionObj);
	location = location.href.split('?')[0];
    }
}

document.onreadystatechange = function(event) {
    Slidoc.log('onreadystatechange:', document.readyState);
    if (document.readyState != "interactive" || !document.body)
	return;
    Slidoc.reportEvent('ready');
    return abortOnError(onreadystateaux);
}

function checkPlugins() {
    Slidoc.log('checkPlugins:');
    Sliobj.activePlugins = {};
    Sliobj.pluginList = [];
    var allBodies = document.getElementsByClassName('slidoc-plugin-body');
    for (var j=0; j<allBodies.length; j++) {
	var pluginName = allBodies[j].dataset.plugin;
	if (!(pluginName in SlidocPlugins))
	    sessionAbort('ERROR Plugin '+pluginName+' not defined properly; check for syntax errors');
	if (!(pluginName in Sliobj.activePlugins)) {
	    Sliobj.pluginList.push(pluginName);
	    Sliobj.activePlugins[pluginName] = Sliobj.pluginList.length;
	}

	var slide_id = allBodies[j].dataset.slideId;
	if (SlidocPluginManager.hasAction(pluginName, 'create'))
	    SlidocPluginManager.call(pluginName, 'create', slide_id);
    }
}

var PagedownConverter = null;
function onreadystateaux() {
    Slidoc.log('onreadystateaux:');
    checkPlugins();
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
	if (localAuth) {
	    Slidoc.showPopup('Accessing Google Docs ...', null, 1000);
	    GService.gprofile.auth = localAuth;
	    Slidoc.slidocReady(localAuth);
	} else {
	    Slidoc.reportEvent('loginPrompt');
	    GService.gprofile.promptUserInfo();
	}
    } else {
	Slidoc.slidocReady(null);
    }
}

function isNumber(x) { return !isNaN(x); }

function zeroPad(num, pad) {
    // Pad num with zeros to make pad digits
    var maxInt = Math.pow(10, pad);
    if (num >= maxInt)
	return ''+num;
    else
	return ((''+maxInt).slice(1)+num).slice(-pad);
}

function unescapeAngles(text) {
    return text.replace('&lt;', '<').replace('&gt;', '>')
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
    if (!Sliobj.testScript && !window.confirm('Do want to completely delete all answers/scores for this session and start over?'))
	return false;
    Sliobj.session = sessionCreate();
    Sliobj.feedback = null;
    sessionPut();
    if (!Slidoc.testingActive())
	location.reload(true);
}

Slidoc.showConcepts = function (msg) {
    var html = msg || '';
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
    if (!Sliobj.currentSlide || !Sliobj.maxIncrement || !('incremental_slides' in Sliobj.params.features))
        return;

    if (Sliobj.curIncrement < Sliobj.maxIncrement) {
	Sliobj.curIncrement += 1;
        document.body.classList.add('slidoc-display-incremental'+Sliobj.curIncrement);
    }
    if (Sliobj.curIncrement == Sliobj.maxIncrement)
	toggleClass(false, 'slidoc-incremental-view');

    return false;
}

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
	if (Sliobj.params.gd_sheet_url && GService.gprofile && GService.gprofile.auth)
	    html += 'User: <b>'+GService.gprofile.auth.id+'</b> (<span class="slidoc-clickable" onclick="Slidoc.userLogout();">logout</span>)<br>';
	html += 'Session: <b>' + Sliobj.sessionName + '</b>';
	if (Sliobj.session.revision)
	    html += ', ' + Sliobj.session.revision;
	if (Sliobj.params.questionsMax)
	    html += ' (' + Sliobj.params.questionsMax + ' questions)';
	if (Sliobj.params.gd_sheet_url)
	    html += Sliobj.session.submitted ? ', Submitted '+Sliobj.session.submitted : ', NOT SUBMITTED';
	html += '<br>';
	if (Sliobj.dueDate)
	    html += 'Due: <em>'+Sliobj.dueDate+'</em><br>';
	if (Sliobj.params.gradeWeight && Sliobj.feedback && 'q_grades' in Sliobj.feedback && Sliobj.feedback.q_grades != null)
	    html += 'Grades: '+Sliobj.feedback.q_grades+'/'+Sliobj.params.gradeWeight+'<br>';
    }
    html += '<table class="slidoc-slide-help-table">';
    if (Sliobj.params.paceLevel && !Sliobj.params.gd_sheet_url && !Sliobj.chainActive)
	html += formatHelp(['', 'reset', 'Reset paced session']) + hr;

    if (Sliobj.currentSlide) {
	for (var j=0; j<Slide_help_list.length; j++)
	    html += formatHelp(Slide_help_list[j]);
    } else {
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

SlidocPluginManager.hasAction = function (pluginName, action) {
    var pluginDef = SlidocPlugins[pluginName];
    if (!pluginDef)
	throw('ERROR Plugin '+pluginName+' not found; define using PluginDef/PluginEnd');
    return action in pluginDef;
}

function makePluginThis(pluginName, slide_id, nosession) {
    Slidoc.log('makePluginThis:', pluginName, slide_id, nosession);
    var pluginDef = SlidocPlugins[pluginName];
    if (!pluginDef)
	throw('ERROR Plugin '+pluginName+' not found; define using PluginDef/PluginEnd');

    var qattributes = slide_id ? getQuestionAttrs(slide_id) : null;
    var pluginId = slide_id ? (slide_id + '-plugin-' + pluginName) : '';
    var pluginThis = {adminState: Sliobj.adminState,
		      sessionName: Sliobj.sessionName,
		      slideId: slide_id || '',
		      pluginId: pluginId,
		      qattributes: qattributes || null,
		      def: pluginDef,
		      global: null,
		      persist: null};
    if (!nosession) {
	if (!(pluginName in Sliobj.session.plugins))
	    Sliobj.session.plugins[pluginName] = {};
	pluginThis.persist = Sliobj.session.plugins[pluginName];

	if (!slide_id) {
	    // Global seed for all instances of the plugin
	    pluginThis.randomSeed = Sliobj.session.randomSeed + Sliobj.activePlugins[pluginName];
	    pluginThis.randomNumber = SlidocRandom.randomNumber.bind(null, pluginThis.randomSeed);
	} else {
	    // Seed for each slide instance of the plugin
	    pluginThis.global = Sliobj.pluginData[pluginName][''];
	    var comps = parseSlideId(slide_id);
	    pluginThis.randomSeed = pluginThis.global.randomSeed + 256*((1+comps[1])*256 + comps[2]);
	    pluginThis.randomNumber = SlidocRandom.randomNumber.bind(null, pluginThis.randomSeed);
	}

    }
    return pluginThis;
}

SlidocPluginManager.call = function (pluginName, action, slide_id) //... extra arguments
{   // action == 'create' inserts/modified DOM elements called per slide after document is ready
    // action == 'globalInit' resets global plugin properties for all slides (called at start/switch of session)
    // action == 'init' resets plugin properties for each slide (called at start/switch of session)
    // action == 'display' displays recorded user response (called at start/switch of session for each question)
    // action == 'disable' disables plugin (after user response has been recorded)
    // action == 'expect' returns expected correct answer
    // action == 'response' records user response and uses callback to return a pluginResp object of the form:
    //    {name:pluginName, score:1/0/0.75/.../null, invalid: invalid_msg, output:output, tests:0/1/2}
    var extraArgs = Array.prototype.slice.call(arguments).slice(3);
    Slidoc.log('SlidocPluginManager.call:', pluginName, action, slide_id, extraArgs);
    var pluginThis = (action == 'create') ? makePluginThis(pluginName, '', true) : Sliobj.pluginData[pluginName][slide_id || ''];
    if (!(action in pluginThis.def))
	throw('ERROR Action '+action+' not defined for plugin '+pluginName+' not found');

    if (!(pluginName in Sliobj.activePlugins))
	throw('INTERNAL ERROR Plugin '+pluginName+' not activated');

    try {
	return SlidocPlugins[pluginName][action].apply(pluginThis, extraArgs);
    } catch(err) {
	sessionAbort('ERROR in calling plugin '+pluginName+'.'+action+': '+err, err.stack);
    }
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


Slidoc.slidocReady = function (auth) {
    Slidoc.log('slidocReady:', auth);
    Sliobj.adminState = auth && !!auth.adminKey;
    Sliobj.userList = null;
    Sliobj.userGrades = null;
    Sliobj.gradingUser = 0;
    Sliobj.indexSheet = null;
    Sliobj.gradeDate = '';

    if (Sliobj.adminState) {
	Sliobj.indexSheet = new GService.GoogleSheet(Sliobj.params.gd_sheet_url, Sliobj.params.index_sheet,
						     Sliobj.params.indexFields.slice(0,2),
						     Sliobj.params.indexFields.slice(2), useJSONP);
	Sliobj.indexSheet.getRow(Sliobj.sessionName, function (result, retStatus) {
	    if (result && result.gradeDate)
		Sliobj.gradeDate = result.gradeDate;
	});
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
    Sliobj.dueDate = null;
    Sliobj.sidebar = false;
    Sliobj.prevSidebar = false;

    Sliobj.session = null;
    Sliobj.feedback = null;

    SlidocRandom = LCRandom;
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
	    toggleClass(!question_attrs.gweight, 'slidoc-nogradediv', slideElem);
	    var suffixElem = document.getElementById(slide_id+'-gradesuffix')
	    if (suffixElem && question_attrs.gweight)
		suffixElem.textContent = '/'+question_attrs.gweight;

	    if (!Sliobj.firstTime) {
		// Clean-up slide-specific view styles for question slides
		slideElem.classList.remove('slidoc-answered-view');
		slideElem.classList.remove('slidoc-grading-view');
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
	} else {
	    preAnswer();
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
    Sliobj.pluginData = {};
    for (var j=0; j<Sliobj.pluginList.length; j++) {
	var pluginName = Sliobj.pluginList[j];
	var pluginThis = makePluginThis(pluginName);
	Sliobj.pluginData[pluginName] = {};
	Sliobj.pluginData[pluginName][''] = pluginThis;
	SlidocRandom.setSeed(pluginThis.globalSeed);
	if (SlidocPluginManager.hasAction(pluginName, 'globalInit'))
	    SlidocPluginManager.call(pluginName, 'globalInit');
    }

    var allBodies = document.getElementsByClassName('slidoc-plugin-body');
    var allBodyIds = [];
    for (var j=0; j<allBodies.length; j++)
	allBodyIds.push(allBodies[j].id);
    allBodyIds.sort();   // Need to call init method in sequence to preserve global random number generation order
    for (var j=0; j<allBodyIds.length; j++) {
	var bodyElem = document.getElementById(allBodyIds[j]);
	var pluginName = bodyElem.dataset.plugin;
	var slide_id = bodyElem.dataset.slideId;
	var pluginThis = makePluginThis(pluginName, slide_id);
	Sliobj.pluginData[pluginName][slide_id] = pluginThis;
	SlidocRandom.setSeed(pluginThis.randomSeed);
	if (SlidocPluginManager.hasAction(pluginName, 'init'))
	    SlidocPluginManager.call(pluginName, 'init', slide_id);
    }


    var jsSpans = document.getElementsByClassName('slidoc-inline-js');
    for (var j=0; j<jsSpans.length; j++) {
	var jsFunc = jsSpans[j].dataset.slidocJsFunction;
	var slide_id = '';
	for (var k=0; k<jsSpans[j].classList.length; k++) {
	    var refmatch = /slidoc-inline-js-in-(.*)$/.exec(jsSpans[j].classList[k]);
	    if (refmatch) {
		slide_id = refmatch[1];
		break;
	    }
	}
	var comps = jsFunc.split('.');
	var val = SlidocPluginManager.call(comps[0], comps[1], slide_id);
	if (val)
	    jsSpans[j].innerHTML = val;
    }
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
		var gradeField = 'q'+question_attrs.qnumber+'_grade_'+question_attrs.gweight;
		updates[gradeField] = 0;
	    }
	    var commentsField = 'q'+question_attrs.qnumber+'_comments';
	    updates[commentsField] = 'Not attempted';
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
    var chapter_id = parseSlideId(firstSlideId)[0];
    clearAnswerElements();
    var keys = Object.keys(Sliobj.session.questionsAttempted);
    for (var j=0; j<keys.length; j++) {
	var qnumber = keys[j];
	var qentry = Sliobj.session.questionsAttempted[qnumber];
	var qfeedback = Sliobj.feedback ? (Sliobj.feedback[qnumber] || null) : null;
	var slide_id = chapter_id + '-' + zeroPad(qentry.slide, 2);
	if (qentry.resp_type == 'choice') {
	    Slidoc.choiceClick(null, slide_id, qentry.response, qentry.explain||null, qfeedback);
	} else {
	    Slidoc.answerClick(null, slide_id, qentry.response, qentry.explain||null, qentry.plugin, qfeedback);
	}
    }
    if (Sliobj.session.submitted)
	showCorrectAnswers();
}

function showCorrectAnswers() {
    Slidoc.log('showCorrectAnswers:');
    var firstSlideId = getVisibleSlides()[0].id;
    var attr_vals = getChapterAttrs(firstSlideId);
    var chapter_id = parseSlideId(firstSlideId)[0];
    for (var qnumber=1; qnumber <= attr_vals.length; qnumber++) {
	if (qnumber in Sliobj.session.questionsAttempted)
	    continue;
	var question_attrs = attr_vals[qnumber-1];
	var slide_id = chapter_id + '-' + zeroPad(question_attrs.slide, 2);
	var qfeedback = Sliobj.feedback ? (Sliobj.feedback[qnumber] || null) : null;
	if (question_attrs.qtype == 'choice') {
		Slidoc.choiceClick(null, slide_id, '', question_attrs.explain, qfeedback);
	    } else {
		Slidoc.answerClick(null, slide_id, '', question_attrs.explain, null, qfeedback);
	    }
    }
}

function sessionCreate() {
    var randomSeed = SlidocRandom.getRandomSeed();
    return {version: Sliobj.params.sessionVersion,
	    revision: Sliobj.params.sessionRevision,
	    paced: Sliobj.params.paceLevel > 0,
	    submitted: null,
	    lateToken: '',
	    paceLevel: Sliobj.params.paceLevel || 0,
	    randomSeed: randomSeed,        // Save random seed
            expiryTime: Date.now() + 180*86400,    // 180 day lifetime
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
	} else if (/^q_grades/.exec(key) && isNumber(value)) {
	    // Total grade
	    feedback.q_grades = value;
	    if (value)
		count += 1;
	}
    }

    result.feedback = count ? feedback : null;
    return result;
}

function sessionGetPutAux(callType, callback, retryCall, retryType, result, retStatus) {
    // For sessionPut, session should be bound to this function as 'this'
    Slidoc.log('Slidoc.sessionGetPutAux: ', callType, !!callback, !!retryCall, retryType, result, retStatus);
    var session = null;
    var feedback = null;
    var nullReturn = false;
    var err_msg = retStatus.error || '';
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
	    if (retStatus.info.dueDate)
		try { Sliobj.dueDate = new Date(retStatus.info.dueDate); } catch(err) { Slidoc.log('sessionGetPutAux: Error DUE_DATE: '+retStatus.info.dueDate, err); }
	    if (retStatus.info.submitTimestamp) {
		Sliobj.session.submitted = retStatus.info.submitTimestamp;
		Sliobj.session.lastSlide = Sliobj.params.pacedSlides;
		showCorrectAnswers();
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
					      err_info+'. Please re-enter or request access.',
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
		if (Sliobj.params.tryCount && Object.keys(Sliobj.session.questionsAttempted).length)
		    prompt += "enter 'partial' to submit and view correct answers.";
		else
		    prompt += "enter 'none' to submit late without credit.";
		var testToken = Slidoc.reportEvent('lateTokenPrompt');
		var token = testToken || window.prompt(prompt);
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
	}
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
	}

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

function delayElement(delaySec, elementId) {
    // Displays element after a delay (with 1 second transition afterward)
    var interval = 0.05;
    var transition = 1;
    var jmax = (delaySec+transition)/interval;
    var jtrans = delaySec/interval
    var j = 0;
    var hideElem = document.getElementById(elementId);
    function clocktick() {
	j += 1;
	hideElem.style.opacity = (j < jtrans) ? 0.1 : Math.min(1.0, 0.1+0.9*(j-jtrans)/(jmax-jtrans) );
    }
    var intervalId = setInterval(clocktick, 1000*interval);
    function endInterval() {
	clearInterval(intervalId);
	hideElem.style.opacity = 1.0;
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

SlidocPluginManager.retryAnswer = function (msg) {
    Slidoc.log('SlidocPluginManager.retryAnswer:', msg);
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
	alert('Please provide an explanation for the answer');
	return false;
    }
    return true;
}

Slidoc.choiceClick = function (elem, slide_id, choice_val, explain, qfeedback) {
   Slidoc.log('Slidoc.choiceClick:', slide_id, choice_val, explain, qfeedback);
    var slide_num = parseSlideId(slide_id)[2];
    var question_attrs = getQuestionAttrs(slide_id);
    if (!question_attrs || question_attrs.slide != slide_num)  // Incomplete choice question; ignore
	return false;

   var setup = !elem;
    if (!checkAnswerStatus(setup, slide_id, question_attrs, explain))
	return false;
    if (setup) {
	if (choice_val) {
	    var elemId = slide_id+'-choice-'+choice_val
	    elem = document.getElementById(elemId);
	    if (!elem) {
		Slidoc.log('Slidoc.choiceClick: Error - Setup failed for '+elemId);
		return false;
	    }
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
    }

    if (elem)
	elem.style['text-decoration'] = 'line-through';
   var choices = document.getElementsByClassName(slide_id+"-choice");
   for (var i=0; i < choices.length; i++) {
      choices[i].removeAttribute("onclick");
      choices[i].classList.remove("slidoc-clickable");
   }

    Slidoc.log("Slidoc.choiceClick:B", slide_num);
    var corr_answer = question_attrs.correct;
    if (corr_answer) {
        var corr_choice = document.getElementById(slide_id+"-choice-"+corr_answer);
        if (corr_choice) {
	    corr_choice.style['text-decoration'] = '';
	    corr_choice.style['font-weight'] = 'bold';
        }
    }

    if (!setup && Sliobj.session.remainingTries > 0)
	Sliobj.session.remainingTries = 0;   // Only one try for choice response
    Slidoc.answerUpdate(setup, slide_id, false, choice_val);
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
	    SlidocPluginManager.call(pluginName, 'display', slide_id, response, pluginResp);
	    Slidoc.answerUpdate(setup, slide_id, false, response, pluginResp);
	} else {
	    if (Sliobj.session.remainingTries > 0)
		Sliobj.session.remainingTries -= 1;

	    var retryMsg = SlidocPluginManager.call(pluginName, 'response', slide_id,
				      (Sliobj.session.remainingTries > 0),
				      Slidoc.answerUpdate.bind(null, setup, slide_id, false));
	    if (retryMsg)
		SlidocPluginManager.retryAnswer(retryMsg);
	}
	if (!checkOnly && (setup || !Sliobj.session.paced || Sliobj.session.remainingTries == 1))
	    SlidocPluginManager.call(pluginName, 'disable', slide_id);

    }  else {
	var multiline = question_attrs.qtype.slice(0,5) == 'text/';
	var inpElem = document.getElementById(multiline ? slide_id+'-answer-textarea' : slide_id+'-answer-input');
	if (inpElem) {
	    if (setup) {
		inpElem.value = response;
	    } else {
		response = inpElem.value.trim();
		if (question_attrs.qtype == 'number' && isNaN(response)) {
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

    var callUpdate = Slidoc.answerUpdate.bind(null, setup, slide_id, checkOnly, response);
    if (setup && pluginResp) {
	callUpdate(pluginResp);
    } else if (question_attrs.qtype != 'text/x-code' && question_attrs.qtype.slice(0,7) == 'text/x-') {
	checkCode(slide_id, question_attrs, response, checkOnly, callUpdate);
    } else {
	callUpdate();
    }
    }
    return false;
}

Slidoc.answerUpdate = function (setup, slide_id, checkOnly, response, pluginResp) {
    Slidoc.log('Slidoc.answerUpdate: ', setup, slide_id, checkOnly, response, pluginResp);

    if (!setup && Sliobj.session.paced)
	Sliobj.session.lastTries += 1;

    var qscore = '';
    var question_attrs = getQuestionAttrs(slide_id);

    var corr_answer      = question_attrs.correct || '';
    var corr_answer_html = question_attrs.html || '';

    Slidoc.log('Slidoc.answerUpdate:', slide_id);

    if (pluginResp) {
	qscore = pluginResp.score;
	corr_answer = '';
    } else {
	var pluginMatch = /^(\w+)\.expect\(\)(;(.+))?$/.exec(corr_answer);
	if (pluginMatch) {
	    var pluginName = pluginMatch[1];
	    var val = SlidocPluginManager.call(pluginName, 'expect', slide_id);
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
	        SlidocPluginManager.retryAnswer();
	        return false;
	    }
	}
    }
    // Display correctness of response
    setAnswerElement(slide_id, '-correct-mark', '', qscore === 1 ? ' '+SYMS['correctMark']+'&nbsp;' : '');
    setAnswerElement(slide_id, '-partcorrect-mark', '', (isNumber(qscore) && qscore > 0 && qscore < 1) ? ' '+SYMS['partcorrectMark']+'&nbsp;' : '');
    setAnswerElement(slide_id, '-wrong-mark', '', (qscore === 0) ? ' '+SYMS['wrongMark']+'&nbsp;' : '');
    setAnswerElement(slide_id, '-any-mark', '', isNaN(qscore) ? '<b>'+SYMS['anyMark']+'</b>' : '');  // Not check mark
    
    // Display correct answer
    setAnswerElement(slide_id, "-answer-correct", corr_answer||'', corr_answer_html);

    var notes_id = slide_id+"-notes";
    var notes_elem = document.getElementById(notes_id);
    if (notes_elem) {
	// Display of any notes associated with this question
	Slidoc.idDisplay(notes_id);
	notes_elem.style.display = 'inline';
	Slidoc.classDisplay(notes_id, 'block');
    }

    // Question has been answered
    var slideElem = document.getElementById(slide_id);
    slideElem.classList.add('slidoc-answered-view');

    if (pluginResp)
	SlidocPluginManager.call(pluginResp.name, 'disable', slide_id);

    if (question_attrs.qtype.slice(0,5) == 'text/') {
	renderDisplay(slide_id, '-answer-textarea', '-response-div', question_attrs.qtype.slice(-8) == 'markdown');
    } else {
	if (question_attrs.explain)
	    renderDisplay(slide_id, '-answer-textarea', '-response-div', question_attrs.explain == 'markdown');
	setAnswerElement(slide_id, '-response-span', response);
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
							      plugin: pluginResp||null,
							      expect: corr_answer,
							      score: isNaN(qscore) ? '': qscore};
	Slidoc.answerTally(qscore, slide_id, question_attrs);
    }
}


Slidoc.answerTally = function (qscore, slide_id, question_attrs) {
    Slidoc.log('Slidoc.answerTally: ', qscore, slide_id, question_attrs);

    Slidoc.reportEvent('answerTally');
    
    var slide_num = parseSlideId(slide_id)[2];
    if (slide_num < Sliobj.session.skipToSlide) {
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
    if (qscore) {
        Sliobj.session.questionsCorrect += qSkipfac;
        Sliobj.session.weightedCorrect += qscore*qWeight;
    }
    Slidoc.showScore();

    if (Sliobj.session.paced && Sliobj.questionConcepts.length > 0) {
	// Track missed concepts
	var concept_elem = document.getElementById(slide_id+"-concepts");
	var concepts = concept_elem ? concept_elem.textContent.split('; ') : ['null'];
	var miss_count = (isNaN(qscore) || qscore === 1) ? 0 : 1;
	
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
    if (!Sliobj.session.paced)
	return;
    Sliobj.session.lastTime = Date.now();
    if (!Sliobj.params.gd_sheet_url || Sliobj.params.paceDelay || Sliobj.params.tryCount)
	sessionPut();
}

Slidoc.showScore = function () {
    var scoreElem = document.getElementById('slidoc-score-display');
    if (!scoreElem)
	return;
    if (Sliobj.session.questionsCount) {
	if (Sliobj.session.submitted && Sliobj.params.scoreWeight)
	    scoreElem.textContent = Sliobj.session.weightedCorrect+' ('+Sliobj.params.scoreWeight+')';
	else
	    scoreElem.textContent = Sliobj.session.questionsCount+'/'+Sliobj.params.questionsMax;
    } else {
	scoreElem.textContent = '';
    }
}

function renderDisplay(slide_id, inputSuffix, renderSuffix, renderMarkdown) {
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
	var html = 'Session '+(Sliobj.session.submitted ? 'completed, but':'')+' not submitted.'
	if (!Sliobj.adminState)
	    html += ' Click <span class="slidoc-clickable" onclick="Slidoc.submitSession();">here</span> to submit session'+((Sliobj.session.lastSlide < getVisibleSlides().length) ? ' without reaching the last slide':'');
    }
    if (Sliobj.adminState) {
	if (Sliobj.gradeDate)
	    html += '<hr>Grades released to students at '+Sliobj.gradeDate;
	else
	    html += '<hr><span class="slidoc-clickable" onclick="Slidoc.releaseGrades();">Release grades to students</span';
    }
    Slidoc.showPopup(html);
}

Slidoc.submitSession = function () {
    Slidoc.log('Slidoc.submitSession: ');
    if (Sliobj.closePopup)
	Sliobj.closePopup();
    if (!window.confirm('Do you really want to submit session without reaching the last slide?'))
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
    toggleClass(startGrading, 'slidoc-grading-view', document.getElementById(slide_id));
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

	var gradeField = 'q'+question_attrs.qnumber+'_grade_'+question_attrs.gweight;
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
    var updateObj = {};
    var keys = Object.keys(updates);
    for (var j=0; j<keys.length; j++)
	updateObj[keys[j]] = updates[keys[j]];
    updateObj.Timestamp = null;  // Ensure that Timestamp is updated

    var gsheet = getSheet(Sliobj.sessionName);
    var retryCall = gradeUpdate.bind(null, qnumber, updates, callback);

    try {
	gsheet.updateRow(updateObj, {}, sessionGetPutAux.bind(null, 'update',
 		         gradeUpdateAux.bind(null, updateObj.id, slide_id, qnumber, callback), retryCall, 'gradeUpdate') );
    } catch(err) {
	sessionAbort(''+err, err.stack);
    }
}

function gradeUpdateAux(userId, slide_id, qnumber, callback, result, retStatus) {
    Slidoc.log('gradeUpdateAux: ', userId, slide_id, qnumber, !!callback, result, retStatus);
    Slidoc.reportEvent('gradeUpdate');
    if (!Slidoc.testingActive()) {
    // Move on to next user if slideshow mode, else to next question
	if (Sliobj.currentSlide) {
	    if (Sliobj.gradingUser < Sliobj.userList.length) {
		Slidoc.nextUser(true);
		setTimeout(function(){Slidoc.gradeClick(null, slide_id);}, 200);
	    }
	} else {
	    var attr_vals = getChapterAttrs(slide_id);
	    if (qnumber < attr_vals.length) {
		// Go to next question slide
		var new_slide = parseSlideId(slide_id)[0]+'-'+zeroPad(attr_vals[qnumber].slide,2);
		goSlide('#'+new_slide);
		setTimeout(function(){Slidoc.gradeClick(null, new_slide);}, 200);
	    }
	}
    }
    delete Sliobj.userGrades[userId].grading[qnumber];
    updateGradingStatus(userId);
}

Slidoc.startPaced = function () {
    Slidoc.log('Slidoc.startPaced: ');

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
    if (Sliobj.dueDate && curDate > Sliobj.dueDate) {
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
	if (Sliobj.params.paceDelay || Sliobj.params.tryCount)
	    startMsg += '&nbsp;&nbsp;<em>Answers will be submitted after each answered question.</em><br>';
	else
	    startMsg += '&nbsp;&nbsp;<em>Answers will only be submitted when you reach the last slide.&nbsp;&nbsp;<br>If you do not complete and move to a different computer, you will have to start over again.</em><br>';
    }
    startMsg += '<ul>';
    if (Sliobj.params.paceDelay)
	startMsg += '<li>'+Sliobj.params.paceDelay+' sec delay between slides</li>';
    if (Sliobj.params.tryCount)
	startMsg += '<li>'+Sliobj.params.tryCount+' attempt(s) for non-choice questions</li>';
    if (Sliobj.params.tryDelay)
	startMsg += '<li>'+Sliobj.params.tryDelay+' sec delay between attempts</li>';
    startMsg += '</ul>';
    Slidoc.showPopup(startMsg);

    goSlide('#'+firstSlideId, false, true);
    Slidoc.slideViewStart();
}

Slidoc.endPaced = function () {
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

   if (Sliobj.session.paced) {
       Sliobj.currentSlide = Sliobj.session.lastSlide || 1; 
   } else {
       Sliobj.currentSlide = getCurrentlyVisibleSlide(slides) || 1;
       // Hide notes (for paced view, this is handled earlier)
       Slidoc.hide(document.getElementById(firstSlideId+'-hidenotes'), 'slidoc-notes', '-');
   }
    var chapterId = parseSlideId(firstSlideId)[0];
    var contentElems = document.getElementsByClassName('slidoc-chapter-toc-hide');
    for (var j=0; j<contentElems.length; j++)
	Slidoc.hide(contentElems[j], null, '-');

   document.body.classList.add('slidoc-slide-view');

   Slidoc.slideViewGo(false, Sliobj.currentSlide);
   Slidoc.reportEvent('initSlideView');
   return false;
}

Slidoc.slideViewEnd = function() {
    if (Sliobj.session.paced && Sliobj.session.paceLevel > 1) {
	var msgStr = 'Cannot exit slide view when in strictly paced mode';
	alert(msgStr);
	return false;
    }
    var slides = getVisibleSlides();

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

Slidoc.slideViewGo = function (forward, slide_num) {
   Slidoc.log('Slidoc.slideViewGo:', forward, slide_num);
   if (!Sliobj.currentSlide)
      return false;

    var slides = getVisibleSlides();
    if (slide_num) {
	slide_num = Math.min(slide_num, slides.length);
    } else {
	slide_num = forward ? Sliobj.currentSlide+1 : Sliobj.currentSlide-1;
    }
   if (!slides || slide_num < 1 || slide_num > slides.length)
      return false;

    if (Sliobj.session.paced && Sliobj.params.tryCount && slide_num > Sliobj.session.lastSlide+1 && slide_num > Sliobj.session.skipToSlide) {
	// Advance one slide at a time
	alert('Must have answered the recent batch of questions correctly to jump ahead in paced mode');
	return false;
    }

    var question_attrs = getQuestionAttrs(slides[slide_num-1].id);  // New slide
    Sliobj.lastInputValue = null;

    if (Sliobj.session.paced && slide_num > Sliobj.session.lastSlide) {
	// Advancing to next (or later) paced slide; update session parameters
	Slidoc.log('Slidoc.slideViewGo:B', slide_num, Sliobj.session.lastSlide);
	if (slide_num == slides.length && Sliobj.session.questionsCount < Sliobj.params.questionsMax) {
	    if (!Slidoc.testingActive() && !window.confirm('You have only answered '+Sliobj.session.questionsCount+' of '+Sliobj.params.questionsMax+' questions. Do you wish to go to the last slide and end the paced session?'))
		return false;
	}
	if (Sliobj.questionSlide && Sliobj.session.remainingTries) {
	    // Current (not new) slide is question slide
	    var tryCount =  (Sliobj.questionSlide=='choice') ? 1 : Sliobj.session.remainingTries;
	    alert('Please answer before proceeding. You have '+tryCount+' try(s)');
	    return false;
	} else if (!Sliobj.questionSlide && Sliobj.params.paceDelay) {
	    // Current (not new) slide is not question slide
	    var delta = (Date.now() - Sliobj.session.lastTime)/1000;
	    if (delta < Sliobj.params.paceDelay) {
		alert('Please wait '+ Math.ceil(Sliobj.params.paceDelay-delta) + ' second(s)');
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
	    if (Sliobj.params.paceDelay)
		Slidoc.delayIndicator(Sliobj.params.paceDelay, 'slidoc-slide-nav-next');
        }

	if (Sliobj.session.lastSlide == slides.length) {
	    // Last slide
	    Slidoc.endPaced();

	} else if (Sliobj.sessionName && !Sliobj.params.gd_sheet_url) {
	    // Not last slide; save updated session (if not transient and not remote)
	    sessionPut();
	}
    } else {
	Sliobj.questionSlide = question_attrs ? question_attrs.qtype : '';
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
		toggleClass(Sliobj.currentSlide > slide_num, 'slidoc-display-incremental'+j);
		if (Sliobj.currentSlide > slide_num) {
		    Sliobj.curIncrement = j;
		}
	    }
	}
	toggleClass(Sliobj.curIncrement < Sliobj.maxIncrement, 'slidoc-incremental-view');
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
       if (newChapterId != Sliobj.curChapterId) {
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
           Slidoc.log('goSlide:E ', newChapterId, chapters.length);
           for (var i=0; i < chapters.length; i++) {
	       if (!Sliobj.sidebar || !chapters[i].classList.contains('slidoc-toc-container'))
		   chapters[i].style.display = (chapters[i].id == newChapterId) ? null : 'none';
           }
       }
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
	   Slidoc.log('goSlide: Error - paced slide not reached:', slide_num, slideId);
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

// Pagedown helpers

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
    var html = PagedownConverter.makeHtml(mdText);
    if (stripOuter && html.substr(0,3) == "<p>" && html.substr(html.length-4) == "</p>") {
	    html = html.substr(3, html.length-7);
    }
    return html.replace(/<a href=([^> ]+)>/g, '<a href=$1 target="_blank">');
}


// Linear Congruential Random Number Generator  https://gist.github.com/Protonk/5367430
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
	if (isNaN(min))
	    return uniform(seedValue);
	else {
	    if (isNaN(max)) {
		max = min;
		min = 1;
	    }
	    return Math.min(max, Math.floor( min + (max-min+1)*uniform(seedValue) ));
	}
    }
  };
}());


// Detect swipe events
// Modified from https://blog.mobiscroll.com/working-with-touch-events/

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
