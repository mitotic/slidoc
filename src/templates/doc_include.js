// JS include file for slidoc

var Slidoc = {};  // External object

///UNCOMMENT: (function(Slidoc) {

var MAX_INC_LEVEL = 9; // Max. incremental display level

var Sliobj = {}; // Internal object

Sliobj.params = JS_PARAMS_OBJ;

Sliobj.closePopup = null;

var uagent = navigator.userAgent.toLowerCase();
var isSafari = (/safari/.test(uagent) && !/chrome/.test(uagent));

document.onreadystatechange = function(event) {
    console.log('onreadystatechange:', document.readyState);
    if (document.readyState != "interactive")
      return;
    try {
	if (Sliobj.params.gd_sheet_url)
	    document.body.classList.add('slidoc-remote-view');

	if (Sliobj.params.gd_client_id) {
	    // Google client load will authenticate
	} else if (Sliobj.params.gd_sheet_url) {
	    GService.gauth.promptUserInfo();
	} else {
	    Slidoc.slidocReady(null);
	}
    } catch(err) {console.log("slidocReady: ERROR", err, err.stack);}
}


function toggleClass(add, className, element) {
    element = element || document.body;
    if (add)
	element.classList.add(className);
    else
	element.classList.remove(className);
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

Slidoc.resetPaced = function () {
    if (Sliobj.params.gd_sheet_url) {
	alert('Cannot reset session linked to Google Docs');
	return false;
    }
    if (!window.confirm('Do want to completely delete all answers/scores for this session and start over?'))
	return false;
    Sliobj.session = sessionCreate(Sliobj.session.paced);
    sessionPut();
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

Slidoc.slideViewIncrement = function () {
    if (!Sliobj.currentSlide || !Sliobj.maxIncrement || !('incremental' in Sliobj.params.features))
        return;

    if (Sliobj.curIncrement < Sliobj.maxIncrement) {
	Sliobj.curIncrement += 1;
        document.body.classList.add('slidoc-display-incremental'+Sliobj.curIncrement);
    } else {
	toggleClass(false, 'slidoc-incremental-view');
    }
    return false;
}

var Key_codes = {
    27: 'esc',
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

var Slide_help_list = [
    ['q, Escape',           'exit',  'enter/exit slide mode'],
    ['h, Home, Fn&#9668;',  'home',  'home (first) slide'],
    ['e, End, Fn&#9658;',   'end',   'end (last) slide'],
    ['p, &#9668;',          'left',  'previous slide'],
    ['n, &#9658;',          'right', 'next slide'],
    ['i, &#9660;',          'i',     'incremental item'],
    ['f',                   'f',     'fullscreen mode'],
    ['m',                   'm',     'missed question concepts'],
    ['?',                   'qmark', 'help']
    ]

Slidoc.slideViewHelp = function () {
    var html = '<b>Help</b><table class="slidoc-slide-help-table">';
    var help_list = Slide_help_list.slice();
    if (Sliobj.session.paced && !Sliobj.params.gd_sheet_url) {
	html += '<tr><td colspan="3"><hr></td></tr>';
	help_list.splice(0,0,['', 'reset', 'Reset paced session'], ['', '', '']);
    }

    for (var j=0; j<help_list.length; j++) {
	var x = help_list[j];
	if (x[1])
	    html += '<tr><td>' + x[0] + '</td><td><span class="slidoc-clickable" onclick="Slidoc.handleKey('+ "'"+x[1]+"'"+ ');">' + x[2] + '</span></td></tr>';
	else
	    html += '<tr><td colspan="3"><hr></td></tr>';
    }
    html += '</table>';
    Slidoc.showPopup(html);
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
    'down':  Slidoc.slideViewIncrement,
    'i':     Slidoc.slideViewIncrement,
    'f':     Slidoc.docFullScreen,
    'm':     Slidoc.showConcepts,
    'qmark': Slidoc.slideViewHelp,
    'reset': Slidoc.resetPaced
}

document.onkeydown = function(evt) {
    if ((!Sliobj.currentSlide || Sliobj.questionSlide) && evt.keyCode > 44)
	return;  // Handle printable input normally

    if (!(evt.keyCode in Key_codes))
	return;

    return Slidoc.handleKey(Key_codes[evt.keyCode]);
}

Slidoc.handleKey = function (keyName) {
    console.log('Slidoc.handleKey:', keyName);
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

    } else if (Sliobj.curChapterId) {
	var chapNum = parseSlideId(Sliobj.curChapterId)[1];
	var chapters = document.getElementsByClassName('slidoc-reg-chapter');
	if (keyName == 'left'  && chapNum > 1)  { goSlide('#slidoc'+('00'+(chapNum-1)).slice(-2)+'-01'); return false; }
	if (keyName == 'right' && chapNum < chapters.length)  { goSlide('#slidoc'+('00'+(chapNum+1)).slice(-2)+'-01'); return false; }
	if (keyName == 'esc')   { Slidoc.slideViewStart(); return false; }

    } else {
	if (keyName == 'esc')   { Slidoc.slideViewStart(); return false; }
    }
	
   return;
};

Slidoc.inputKeyDown = function (evt) {
    console.log('Slidoc.inputKeyDown', evt.keyCode, evt.target, evt.target.id);
    if (evt.keyCode == 13) {
	var inputElem = document.getElementById(evt.target.id.replace('-ansinput', '-ansclick'));
	inputElem.onclick();
    }
}

function parseSlideId(slideId) {
    // Return chapterId, chapter number, slide number (or 0)
    var match = RegExp('(slidoc(\\d+))(-(\\d+))?$').exec(slideId);
    if (!match) return [null, 0, 0];
    return [match[1], parseInt(match[2]), match[4] ? parseInt(match[4]) : 0];
}

function parseElem(elemId) {
    try {
	var elem = document.getElementById(elemId);
	if (elem && elem.textContent) {
	    return JSON.parse(atob(elem.textContent));
	}
    } catch (err) {console.log('parseElem: '+elemId+' JSON/Base64 parse error'); }
    return null;
}

Slidoc.slidocReady = function (auth) {
    console.log("Slidoc.slidocReady:", auth);
    sessionManage();

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

    var paceParam = (Sliobj.params.paceStrict !== null);
    Sliobj.sessionName = paceParam ? Sliobj.params.filename : '';

    var newSession = sessionCreate(paceParam);

    console.log("Slidoc.slidocReady2:", Sliobj.sessionName, paceParam);
    if (Sliobj.sessionName) {
	// Paced named session
	if (Sliobj.params.gd_sheet_url && !auth) {
	    sessionAbort('Session aborted. Google Docs authentication error.');
	    return false;
	}
	sessionPut(newSession, slidocReadyAux, {nooverwrite: true, get: true, createSheet: true});
    } else {
	slidocReadyAux(newSession);
    }
}

function slidocReadyAux(session) {
    console.log('slidocReadyAux:', session);
    Sliobj.session = session;
    var paceParam = (Sliobj.params.paceStrict !== null);

    if (Sliobj.session.version != Sliobj.params.sessionVersion) {
	alert('Slidoc: session version mismatch; discarding previous session with version '+Sliobj.session.version);
	Sliobj.session = null;
    } else if (Sliobj.session.revision != Sliobj.params.sessionRevision) {
	alert('Slidoc: Revised session '+Sliobj.params.sessionRevision+' (discarded previous revision '+Sliobj.session.revision+')');
	Sliobj.session = null;

    } else if (!paceParam && Sliobj.session.paced) {
	// Pacing cancelled
	Sliobj.session.paced = false;

    } else if (paceParam && !Sliobj.session.paced) {
	// Pacing completed
	var chapters = document.getElementsByClassName('slidoc-reg-chapter');
	for (var j=0; j<chapters.length; j++)
	    chapters[j].style.display = null;
    }

    if (!Sliobj.session) {
	// New paced session
	Sliobj.session = sessionCreate(paceParam);
	sessionPut();
    }

    if (Sliobj.session.questionsCount)
	Slidoc.showScore();

    var toc_elem = document.getElementById("slidoc00");
    if (!toc_elem && Sliobj.session.paced) {
	Slidoc.startPaced();
	return false;
    }
    Slidoc.chainUpdate(location.search);
    if (toc_elem) {
	var slideHash = (!Sliobj.session.paced && location.hash) ? location.hash : "#slidoc00";
	goSlide(slideHash, false, true);
	if (document.getElementById("slidoc01") && window.matchMedia("screen and (min-width: 800px) and (min-device-width: 960px)").matches)
	    Slidoc.sidebarDisplay()
    }
}

function sessionCreate(paced) {
    return {version: Sliobj.params.sessionVersion,
	    revision: Sliobj.params.sessionRevision,
	    paced: paced || false,
	    paceStrict: Sliobj.params.paceStrict || 0,
            expiryTime: Date.now() + 180*86400,    // 180 day lifetime
            startTime: Date.now(),
            lastTime: 0,
	    lastSlide: 0,
            lastTries: 0,
            remainingTries: 0,
            lastAnswersCorrect: 0,
	    questionsMax: 0,
            questionsCount: 0,
            questionsCorrect: 0,
            questionsAttempted: {},
            missedConcepts: []
	   };
}

var Auth_sheet = null;
var Session_fields = ['startTime', 'lastSlide', 'questionsCount', 'questionsCorrect', 'session_hidden'];

function sessionAbort(err_msg) {
    Slidoc.classDisplay('slidoc-slide', 'none');
    alert(err_msg);
}

function sessionGetPutAux(callback, result, err_msg) {
    console.log('Slidoc.sessionGetPutAux: ', callback, result, err_msg);
    var session = null;
    if (!result) {
	console.log('Slidoc.sessionGetPutAux: ERROR '+err_msg, result);
    } else if (!result.id) {
	if (callback)
	    callback(null);
	return;
    } else {
	try {
	    session = JSON.parse( atob(result.session_hidden.replace(/\s+/, '')) );
	} catch(err) {
	    console.log('Slidoc.sessionGetPutAux: ERROR in parsing session_hidden', err)
	    err_msg = 'Parsing error';
	}
    }

    if (session) {
	if (callback)
	    callback(session);
    } else {
	sessionAbort('Session aborted. Error in accessing session info from Google Docs: '+err_msg);
    }
}

function sessionManage() {
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

function setupAuthSheet(name) {
    if (!Auth_sheet) {
	var useJSONP = (location.protocol == 'file:' || (isSafari && location.hostname.toLowerCase() == 'localhost') );
	Auth_sheet = new GService.GoogleAuthSheet(Sliobj.params.gd_sheet_url, name, Session_fields,
						  GService.gauth.auth, useJSONP);
    }
}

function sessionGet(name, callback) {
    if (Sliobj.params.gd_sheet_url) {
	// Google Docs storage
	setupAuthSheet(name);
	Auth_sheet.getRow(sessionGetPutAux.bind(null, callback), true);
    } else {
	// Local storage
	var sessionObj = localGet('sessions');
	if (!sessionObj) {
	    alert('sessionGet: Error - no session object');
	} else {
	    if (name in sessionObj)
		callback(sessionObj[name]);
	    else
		callback(null);
	}
    }
}

function sessionPut(session, callback, opts) {
    // Remote saving only happens if session.paced is true or force is true
    // opts = {nooverwrite:, get: , createSheet:, force: }
    console.log("sessionPut:", Sliobj.sessionName, session, callback, opts);
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
	var rowObj = {};
	for (var j=0; j<Session_fields.length; j++) {
	    var header = Session_fields[j];
	    if (header.slice(0,6) != 'hidden') {
		rowObj[header] = session[header];
	    }
	}
	var base64str = btoa(JSON.stringify(session));
        // Break up Base64 version of object-json into lines (commnted out; does not work with JSONP)
	///var comps = [];
	///for (var j=0; j < base64str.length; j+=80)
	///    comps.push(base64str.slice(j,j+80));
	///comps.join('')+'';
	rowObj.session_hidden = base64str;
	setupAuthSheet(Sliobj.sessionName);
	Auth_sheet.putRow(rowObj, !!opts.nooverwrite, sessionGetPutAux.bind(null, callback||null), !!opts.get, !!opts.createSheet);

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

function make_id_from_text(text) {
    return text.toLowerCase().trim().replace(/[^-\w\.]+/, '-').replace(/^[-\.]+/, '').replace(/[-\.]+$/, '');
}

function getBaseURL() {
   return (location.pathname.slice(-1)=='/') ? location.pathname : location.pathname.split('/').slice(0,-1).join('/');
}

function getParameter(name, number, queryStr) {
   // Set number to true, if expecting an integer value. Returns null if valid parameter is not present.
   // If queryStr is specified, it is used instead of location.search
   var match = RegExp('[?&]' + name + '=([^&]*)').exec(queryStr || window.location.search);
   if (!match)
      return null;
   var value = decodeURIComponent(match[1].replace(/\+/g, ' '));
   if (number) {
       try { value = parseInt(value); } catch(err) { value = null };
   }
   return value;
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
	for (var i = 0; i < elements.length; ++i)
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
   for (var i = 0; i < elements.length; ++i) {
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
   for (var i = 0; i < elements.length; ++i) {
      elements[i].style.display = (elements[i].style.display=='inline') ? 'none' : 'inline';
   }
   return false;
}

Slidoc.answerClick = function (elem, question_number, slide_id, answer_type, response) {
   // Handle answer types: number, text
   console.log("Slidoc.answerClick:", elem, slide_id, question_number, answer_type, response);
   var setup = !elem;
    if (!setup && Sliobj.session.paced && !Sliobj.currentSlide) {
	alert('Please switch to slide view to answer questions in paced mode');
	return false;
    }
   if (setup) {
        elem = document.getElementById(slide_id+"-ansclick");
	if (!elem) {
	    console.log('Slidoc.answerClick: Setup failed for '+slide_id);
	    return false;
	}
   } else {
       // Not setup
	if (!Slidoc.answerPacedAllow())
	    return false;
       response = '';
    }
   Slidoc.toggleInline(elem);
   var inputElem = document.getElementById(slide_id+'-ansinput');
   if (inputElem) {
       if (setup) {
	   inputElem.value = response;
       } else {
	   response = inputElem.value.trim();
	   if (answer_type == 'number' && isNaN(response)) {
	       alert('Expecting a numeric value as answer');
	       return false;
	   } else if (Sliobj.session.paced) {
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
       if (setup || !Sliobj.session.paced || Sliobj.session.remainingTries == 1)
	   inputElem.disabled = 'disabled';
    }

    if (!setup && Sliobj.session.remainingTries > 0)
	Sliobj.session.remainingTries -= 1;
    Slidoc.answerUpdate(setup, question_number, slide_id, answer_type, response);
    return false;
}

Slidoc.choiceClick = function (elem, question_number, slide_id, choice_val) {
   console.log("Slidoc.choiceClick:", question_number, slide_id, choice_val);
   var setup = !elem;
    if (!setup && Sliobj.session.paced && !Sliobj.currentSlide) {
	alert('Please switch to slide view to answer questions in paced mode');
	return false;
    }
   if (setup) {
	var elemId = slide_id+'-choice-'+choice_val
	elem = document.getElementById(elemId);
	if (!elem) {
	    console.log('Slidoc.choiceClick: Setup failed for '+elemId);
	    return false;
	}
    } else {
	// Not setup
	if (!Slidoc.answerPacedAllow())
	return false;
    }

   elem.style['text-decoration'] = 'line-through';
   var choices = document.getElementsByClassName(slide_id+"-choice");
   for (var i = 0; i < choices.length; ++i) {
      choices[i].removeAttribute("onclick");
      choices[i].classList.remove("slidoc-clickable");
   }

   var chapter_id = parseSlideId(slide_id)[0];
   console.log("Slidoc.choiceClick2:", chapter_id);

   if (chapter_id) {
       var attr_vals = parseElem(chapter_id+'-01-attrs');
       if (attr_vals) {
	   var corr_answer = attr_vals[question_number-1][1];
	   if (corr_answer) {
               var corr_choice = document.getElementById(slide_id+"-choice-"+corr_answer);
               if (corr_choice) {
		   corr_choice.style['text-decoration'] = '';
		   corr_choice.style['font-weight'] = 'bold';
               }
	   }
       }
   }

    if (!setup && Sliobj.session.remainingTries > 0)
	Sliobj.session.remainingTries = 0;   // Only one try for choice response
    Slidoc.answerUpdate(setup, question_number, slide_id, 'choice', choice_val);
    return false;
}

Slidoc.answerUpdate = function (setup, question_number, slide_id, resp_type, response) {
    console.log('Slidoc.answerUpdate: ', setup, question_number, slide_id, resp_type, response);

    if (!setup && Sliobj.session.paced)
	Sliobj.session.lastTries += 1;

   var is_correct = true;
   var chapter_id = parseSlideId(slide_id)[0];
   console.log("Slidoc.answerUpdate2:", chapter_id);

   if (chapter_id) {
      var attr_vals = parseElem(chapter_id+'-01-attrs');
      if (attr_vals) {
	var corr_answer = attr_vals[question_number-1][1];
	console.log('Slidoc.answerUpdate:corr', corr_answer);
	if (corr_answer) {
	    // Check response against correct answer
	    is_correct = false;
	    if (resp_type == 'number') {
		// Check if numeric answer is correct
		var corr_value = null;
		var corr_error = 0.0;
		try {
		    var comps = corr_answer.split('+/-');
		    corr_value = parseFloat(comps[0]);
		    if (comps.length > 1)
			corr_error = parseFloat(comps[1]);
		} catch(err) {console.log('Slidoc.answerUpdate: Error in correct numeric answer:'+corr_answer);}
		var resp_value = null;
		try {
		    resp_value = parseFloat(response);
		} catch(err) {console.log('Slidoc.answerUpdate: Error - invalid numeric response:'+response);}

		if (corr_value !== null && resp_value != null)
		    is_correct = Math.abs(resp_value - corr_value) <= 1.001*corr_error;
	    } else {
		// Check if non-numeric answer is correct (all spaces are removed before comparison)
		var norm_resp = response.trim().toLowerCase();
		var correct_options = corr_answer.split(' OR ');
		for (var k=0; k < correct_options.length; k++) {
		    var norm_corr = correct_options[k].trim().toLowerCase().replace(/\s+/, ' ');
		    if (norm_corr.indexOf(' ') > 0) {
			// Correct answer has space(s); compare using normalized spaces
			is_correct = (norm_resp.replace(/\s+/, ' ') == norm_corr);
		    } else {
			// Strip all spaces from response
			is_correct = (norm_resp.replace(/\s+/, '') == norm_corr);
		    }
		    if (is_correct)
			break;
		}
	    }
	     
	    if (!setup && !is_correct && Sliobj.session.remainingTries > 0) {
		// Re-try answer
		Sliobj.session.lastTime = Date.now();
		Sliobj.session.lastAnswersCorrect = -1;   // Incorrect answer
		document.body.classList.add('slidoc-incorrect-answer-state');
		var after_str = '';
		if (Sliobj.params.tryDelay) {
		    Slidoc.delayIndicator(Sliobj.params.tryDelay, slide_id+'-ansclick');
		    after_str = ' after '+Sliobj.params.tryDelay+' second(s)';
		}
		Slidoc.showPopup('Incorrect.<br> Please re-attempt question'+after_str+'.<br> You have '+Sliobj.session.remainingTries+' try(s) remaining');
		return false;
	    }
	    // Display correctness of response
	    if (is_correct) {
		var cmark_elem = document.getElementById(slide_id+"-correct-mark");
		if (cmark_elem)
		    cmark_elem.innerHTML = " &#x2714;&nbsp;";
	    } else {
		var wmark_elem = document.getElementById(slide_id+"-wrong-mark");
		wmark_elem.innerHTML = " &#x2718;&nbsp;";
	    }
	}
	// Display correct answer
	var corr_elem = document.getElementById(slide_id+"-correct");
        if (corr_elem) {
	    if (corr_answer)
		corr_elem.textContent = corr_answer;
	    else
		corr_elem.innerHTML = '<b>&#9083;</b>'; // Not check mark
	    corr_elem.style.display = 'inline';
	}
      }
   }

    var ans_elem = document.getElementById(slide_id+"-answer");
    if (ans_elem) ans_elem.style.display = 'inline';

    var click_elem = document.getElementById(slide_id+"-ansclick");
    var prefix_elem = document.getElementById(slide_id+"-ansprefix");
    if (click_elem) click_elem.style.display = 'none';
    if (prefix_elem) prefix_elem.style.display = 'inline';

    var notes_id = slide_id+"-notes";
    var notes_elem = document.getElementById(notes_id);
    if (notes_elem) {
	// Display of any notes associated with this question
	Slidoc.idDisplay(notes_id);
	notes_elem.style.display = 'inline';
	Slidoc.classDisplay(notes_id, 'block');
    }

   if (!setup)
       Slidoc.answerTally(is_correct, question_number, slide_id, resp_type, response);
}

Slidoc.answerTally = function (is_correct, question_number, slide_id, resp_type, response) {
   console.log('Slidoc.answerTally: ', is_correct, question_number, slide_id, resp_type, response);
   Sliobj.session.questionsAttempted[question_number] = [slide_id, resp_type, response];

    // Keep score
    Sliobj.session.questionsCount += 1;
    if (is_correct)
        Sliobj.session.questionsCorrect += 1;
    Slidoc.showScore();

    if (Sliobj.session.paced && Sliobj.questionConcepts.length > 0) {
	// Track missed concepts
	var concept_elem = document.getElementById(slide_id+"-concepts");
	var concepts = concept_elem ? concept_elem.textContent.split('; ') : ['null'];
	var miss_count = is_correct ? 0 : 1;
	
	for (var j=0; j<concepts.length; j++) {
	    if (concepts[j] == 'null')
		continue;
	    var m = (j == 0) ? 0 : 1;   // Primary/secondary concept
	    for (var k=0; k<Sliobj.questionConcepts[m].length; k++) {
		if (concepts[j] == Sliobj.questionConcepts[m][k]) {
		    Sliobj.session.missedConcepts[m][k][0] += miss_count; //Missed count
		    Sliobj.session.missedConcepts[m][k][1] += 1;   //Attempted count
		}
	    }
	}
    }

    if (Sliobj.session.paced) {
	Sliobj.session.remainingTries = 0;
	document.body.classList.remove('slidoc-expect-answer-state');
	if (is_correct && Sliobj.session.lastAnswersCorrect >= 0) {
	    // 1 => Current sequence of "correct" answers
	    Sliobj.session.lastAnswersCorrect = 1;
	} else {
            // -1 => Current sequence with at least one incorrect answer
	    Sliobj.session.lastAnswersCorrect = -1;
	    document.body.classList.add('slidoc-incorrect-answer-state');
	}
	Sliobj.session.lastTime = Date.now();
        if (!Sliobj.params.gd_sheet_url || Sliobj.params.paceDelay || Sliobj.params.tryCount)
	    sessionPut();
    }
}

Slidoc.showScore = function () {
    var scoreElem = document.getElementById('slidoc-score-display');
    if (scoreElem && Sliobj.session.questionsCount)
	scoreElem.textContent = Sliobj.session.questionsCorrect+'/'+Sliobj.session.questionsCount;
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
	html += '<tr><td>'+scores[j][0]+':</td><td>'+scores[j][1]+'/'+scores[j][2]+'</td></tr>';
    }
    html += '</table>';
    return html;
}

Slidoc.startPaced = function () {
    console.log('Slidoc.startPaced: ');
    var firstSlideId = getVisibleSlides()[0].id;
    var qConcepts = parseElem(firstSlideId+'-qconcepts');
    Sliobj.questionConcepts = qConcepts || [];

    if (!Sliobj.session.lastSlide) {
	// Start of session
	var attr_vals = parseElem(firstSlideId+'-attrs');
	Sliobj.session.questionsMax = attr_vals ? attr_vals.length : 0;

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

    Slidoc.classDisplay('slidoc-question-notes', 'none');
    for (var qnumber in Sliobj.session.questionsAttempted) {
	// Pre-answer questions
	if (Sliobj.session.questionsAttempted.hasOwnProperty(qnumber)) {
	    var qentry = Sliobj.session.questionsAttempted[qnumber];
	    if (qentry[1] == 'choice') {
		Slidoc.choiceClick(null, qnumber, qentry[0], qentry[2]);
	    } else {
		Slidoc.answerClick(null, qnumber, qentry[0], qentry[1], qentry[2]);
	    }
	}
    }
    document.body.classList.add('slidoc-paced-view');
    if (Sliobj.session.paceStrict)
	document.body.classList.add('slidoc-strict-paced-view');

    var startMsg = 'Starting'+(Sliobj.session.paceStrict?' strictly':'')+' paced slideshow '+Sliobj.sessionName+':<br>';
    if (Sliobj.session.questionsMax)
	startMsg += '&nbsp;&nbsp;<em>There are '+Sliobj.session.questionsMax+' questions.</em><br>';
    if (Sliobj.params.gd_sheet_url) {
	if (Sliobj.params.paceDelay || Sliobj.params.tryCount)
	    startMsg += '&nbsp;&nbsp;<em>Session stats will be submitted after each answered question.</em><br>';
	else
	    startMsg += '&nbsp;&nbsp;<em>Session stats will only be submitted when you reach the last slide.</em><br>';
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
    console.log('Slidoc.endPaced: ');
    if (!Sliobj.session.paceStrict) {
	// If pace can end, unpace
	document.body.classList.remove('slidoc-paced-view');
	Sliobj.session.paced = false;
    }
    sessionPut(null, null, {force: true});
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
   }
    var chapterId = parseSlideId(firstSlideId)[0];
    var contElems = document.getElementsByClassName('slidoc-chapter-toc-hide');
    for (var j=0; j<contElems.length; j++)
	Slidoc.hide(contElems[j], null, '-');

   Slidoc.hide(document.getElementById(firstSlideId+'-hidenotes'), 'slidoc-notes', '-');
   document.body.classList.add('slidoc-slide-view');

   Slidoc.slideViewGo(false, Sliobj.currentSlide);
   return false;
}

Slidoc.slideViewEnd = function() {
    if (Sliobj.session.paced && Sliobj.session.paceStrict) {
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
   console.log('Slidoc.slideViewGo:', forward, slide_num);
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

    if (Sliobj.session.paced && slide_num > Sliobj.session.lastSlide+1 && Sliobj.session.lastAnswersCorrect <= 0) {
	// Advance one slide at a time
	alert('Must have answered the recent batch of questions correctly to jump ahead in paced mode');
	return false;
    }

    var answerType = document.getElementById(slides[slide_num-1].id+'-anstype');
    Sliobj.questionSlide = answerType ? answerType.textContent : '';
    Sliobj.lastInputValue = null;

    if (Sliobj.session.paced && slide_num > Sliobj.session.lastSlide) {
	// Advancing to next (or later) paced slide; update session parameters
	console.log('Slidoc.slideViewGo2:', slide_num, Sliobj.session.lastSlide);
	if (slide_num == slides.length && Sliobj.params.gd_sheet_url && !Sliobj.params.tryCount && Sliobj.session.questionsCount < Sliobj.session.questionsMax) {
	    if (!window.confirm('You have only answered '+Sliobj.session.questionsCount+' of '+Sliobj.session.questionsMax+' questions. Do you wish to go to the last slide and end the paced session?'))
		return false;
	}
	if (Sliobj.questionSlide && Sliobj.session.remainingTries) {
	    var tryCount =  (Sliobj.questionSlide=='choice') ? 1 : Sliobj.session.remainingTries;
	    alert('Please answer before proceeding. You have '+tryCount+' try(s)');
	    return false;
	} else if (!Sliobj.questionSlide && Sliobj.params.paceDelay) {
	    var delta = (Date.now() - Sliobj.session.lastTime)/1000;
	    if (delta < Sliobj.params.paceDelay) {
		alert('Please wait '+ Math.ceil(Sliobj.params.paceDelay-delta) + ' second(s)');
		return false;
	    }
	}
        // Update session for new slide
	Sliobj.session.lastSlide = slide_num; 
	Sliobj.session.lastTime = Date.now();

	Sliobj.session.lastTries = 0;
	if (Sliobj.questionSlide) {
	    if (Sliobj.session.lastAnswersCorrect != 1 && Sliobj.session.lastAnswersCorrect != -1)
		Sliobj.session.lastAnswersCorrect = 0;
	    Sliobj.session.remainingTries = Sliobj.params.tryCount;
	} else {
            // 2 => Last sequence of questions was answered correctly
	    Sliobj.session.lastAnswersCorrect = (Sliobj.session.lastAnswersCorrect > 0) ? 2 : 0;
	    Sliobj.session.remainingTries = 0;
	    if (Sliobj.params.paceDelay)
		Slidoc.delayIndicator(Sliobj.params.paceDelay, 'slidoc-slide-nav-next');
        }

	if (Sliobj.session.lastSlide == slides.length) {
	    // Last slide
	    Slidoc.endPaced();
	    var msg = '<b>Paced session completed.</b><br>';
	    if (Sliobj.params.gd_sheet_url)
		msg += 'Session stats will be submitted to Google Docs.<br>';
	    if (!Sliobj.session.paced)
		msg += 'You may now exit the slideshow and access this document normally.<br>';
	    Slidoc.showConcepts(msg);

	} else if (Sliobj.sessionName && !Sliobj.params.gd_sheet_url) {
	    // Not last slide; save updated session (if not transient and not remote)
	    sessionPut();
	}
    }

    if (Sliobj.session.paced) {
	toggleClass(Sliobj.session.lastAnswersCorrect < 0, 'slidoc-incorrect-answer-state');
	toggleClass(slide_num == Sliobj.session.lastSlide, 'slidoc-paced-last-slide');
	toggleClass(Sliobj.session.remainingTries, 'slidoc-expect-answer-state');
    }

    var prev_elem = document.getElementById('slidoc-slide-nav-prev');
    var next_elem = document.getElementById('slidoc-slide-nav-next');
    prev_elem.style.visibility = (slide_num == 1) ? 'hidden' : 'visible';
    next_elem.style.visibility = (slide_num == slides.length) ? 'hidden' : 'visible';

    console.log('Slidoc.slideViewGo3:', slide_num, slides[slide_num-1]);
    Sliobj.maxIncrement = 0;
    Sliobj.curIncrement = 0;
    if ('incremental' in Sliobj.params.features) {
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
    for (var i=0; i<slides.length; ++i) {
	if (i != slide_num-1) slides[i].style.display = 'none';
    }
    Sliobj.currentSlide = slide_num;
    location.href = '#'+slides[Sliobj.currentSlide-1].id;

    var inputElem = document.getElementById(slides[Sliobj.currentSlide-1].id+'-ansinput');
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
    console.log("goSlide:", slideHash, chained);
    if (Sliobj.session.paced && Sliobj.session.paceStrict && !Sliobj.currentSlide && !singleChapter) {
	alert('Slidoc: InternalError: strict paced mode witout slideView');
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
   console.log('goSlide2: ', slideId, chained, goElement);
   if (!goElement) {
      console.log('goSlide: Error - unable to find element', slideHash);
      return false;
   }

   Slidoc.breakChain();
   if (!chained) {
       // End chain
       Sliobj.ChainQuery = '';
       Sliobj.chainActive = null;
   }

    // Locate reference
    var match = RegExp('slidoc-ref-(.*)$').exec(slideId);
    console.log('goSlide2a: ', match, slideId);
    if (match) {
        // Find slide containing reference
	slideId = '';
        for (var i=0; i<goElement.classList.length; ++i) {
	    var refmatch = RegExp('slidoc-referable-in-(.*)$').exec(goElement.classList[i]);
	    if (refmatch) {
		slideId = refmatch[1];
		slideHash = '#'+slideId;
                console.log('goSlide2b: ', slideHash);
		break;
	    }
	}
        if (!slideId) {
            console.log('goSlide: Error - unable to find slide containing header:', slideHash);
            return false;
        }
    }

    if (Sliobj.curChapterId || singleChapter) {
	// Display only chapter containing slide
	var newChapterId = parseSlideId(slideId.slice(0,8))[0];
	if (!newChapterId) {
            console.log('goSlide: Error - invalid hash, not slide or chapter', slideHash);
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
               console.log('goSlide: Error - unable to find chapter:', newChapterId);
               return false;
           }
           Sliobj.curChapterId = newChapterId;
           var chapters = document.getElementsByClassName('slidoc-container');
           console.log('goSlide3: ', newChapterId, chapters.length);
           for (var i = 0; i < chapters.length; ++i) {
	       if (!Sliobj.sidebar || !chapters[i].classList.contains('slidoc-toc-container'))
		   chapters[i].style.display = (chapters[i].id == newChapterId) ? null : 'none';
           }
       }
    }

   if (Sliobj.currentSlide) {
      var slides = getVisibleSlides();
      for (var i=0; i<slides.length; ++i) {
         if (slides[i].id == slideId) {
           Slidoc.slideViewGo(false, i+1);
           return false;
         }
      }
      console.log('goSlide: Error - slideshow slide not in view:', slideId);
      return false;

   } else if (Sliobj.session.paced) {
	var slide_num = parseSlideId(slideId.slice(0,8))[2];
       if (slide_num > Sliobj.session.lastSlide) {
	   console.log('goSlide: Error - paced slide not reached:', slideId);
	   return false;
       }
   }

   console.log('goSlide4: ', slideHash);
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
   console.log("Slidoc.chainLink:", newindex, queryStr, urlPath);
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
   console.log("Slidoc.chainURL:", newindex);
   return Slidoc.chainLink(newindex, location.search, location.pathname);
}

Slidoc.chainNav = function (newindex) {
   // Navigate to next link in concept chain
   console.log("Slidoc.chainNav:", newindex);
   if (!Sliobj.ChainQuery)
      return false;
   var comps = Slidoc.chainLink(newindex, Sliobj.ChainQuery).split('#');
   Sliobj.ChainQuery = comps[0];
   goSlide('#'+comps[1], true);
    console.log("Slidoc.chainNav2:", location.hash);
   return false;
}

Slidoc.chainStart = function (queryStr, slideHash) {
   // Go to first link in concept chain
    console.log("Slidoc.chainStart:", slideHash, queryStr);
    Sliobj.ChainQuery = queryStr;
    goSlide(slideHash, true);
    return false;
}

Slidoc.chainUpdate = function (queryStr) {
    queryStr = queryStr || location.search;
    var tagid = location.hash.substr(1);
    console.log("Slidoc.chainUpdate:", queryStr, tagid);

    var ichain_elem = document.getElementById(tagid+"-ichain");
    if (!ichain_elem)
       return false;

    var tagindex = getParameter('tagindex', true, queryStr);
    console.log("Slidoc.chainUpdate2:", tagindex);
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
        concept_elem.text = tagconcept;
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
    console.log("Slidoc.chainUpdate:4", location.hash);
}

// Popup: http://www.loginradius.com/engineering/simple-popup-tutorial/

Slidoc.showPopup = function (innerHTML, divElemId) {
    // Only one of innerHTML or divElemId needs to be non-null
    if (Sliobj.closePopup) {
	console.log('Slidoc.showPopup: Popup already open');
	return;
    }

    if (!divElemId) divElemId = 'slidoc-generic-popup';
    var divElem = document.getElementById(divElemId);
    var closeElem = document.getElementById(divElem.id+'-close');
    var overlayElem = document.getElementById('slidoc-popup-overlay');
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

	Sliobj.closePopup = function () {
	    overlayElem.style.display = 'none';
	    divElem.style.display = 'none';
	    Sliobj.closePopup = null;
	}
	
	closeElem.onclick = Sliobj.closePopup;
    }
}

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
    console.log('onTouchStart:');
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
        console.log('onTouchMove: dx, dy, sort, swipe, scroll', touchDiffX, touchDiffY, touchSort, touchSwipe, touchScroll);
 
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
    console.log('onTouchEnd: dx, dy, sort, swipe, scroll, action', touchDiffX, touchDiffY, touchSort, touchSwipe, touchScroll, touchAction);
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
