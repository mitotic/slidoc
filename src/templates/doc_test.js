// Code for test scripts
// Use slidoc.py --test_script to load testing module
// Use URL query options to activate testing:
//    ?testscript=basic/...    # testing script name
//    &teststep=1              # step-wise testing
//    &testuser=admin/aaa/...  # login user name
//    &testtoken=key/token     # login key/token
//
//  Sample script in *.md files:
//  Script entries of the form ['expectedEvent', slide_number or 0, delay_msec or 0, 'action', [arg1, arg2, ...]]
//    Prefix '+' for expected events indicates optional event (may not be reported)
//    Prefix '-' for expected events indicates skipped event (no action to be performed)
//
// var TestScripts = {};
// TestScripts.basic = [
//   ['ready'],
//   ['+loginPrompt', 0, 500, 'login'],
//   ['+lateTokenPrompt', 0, 0, 'lateToken', ['none']],
//   ['initSession', 0, 0, 'reset'],
//   ['initSlideView', 2, 500, 'choice', ['D']],
//   ['answerTally', 3, 500, 'input', [5.5]],
//   ['answerTally', 11, 0, 'next'],
//   ['endPaced', 0, 0, 'end']
//  ];
//
// Slidoc.enableTesting(Slidoc.getParameter('testscript')||'', TestScripts);
//

function TestScript(activeScript, scripts) {
    this.activeScript = activeScript || '';
    this.scripts = scripts || {};
    if (this.activeScript && !(this.activeScript in this.scripts))
	alert("Test script '"+this.activeScript+"' not found!");
    this.curstep = 0;
}

Slidoc.TestScript = TestScript;

TestScript.prototype.advanceStep = function () {
    console.log('TestScript.advanceStep:');
    var stepEvent = this.stepEvent;
    if (!stepEvent)
	return false;
    Slidoc.closeAllPopups();
    this.stepEvent = null;
    stepEvent();
    this.showStatus();
    return true;
}

TestScript.prototype.showStatus = function (state) {
    var statusElem = document.getElementById('slidoc-test-status');
    if (!statusElem)
	return;
    if (state == 'done') {
	statusElem.style.display = 'none';
	return;
    }
    if (this.curstep == 0)
	statusElem.style.display = null;
    statusElem.textContent = 'Test '+this.curstep+(state ? ': '+state: '');
}

TestScript.prototype.reportEvent = function (eventName) {
    if (!this.activeScript)
	return null;
    if (this.stepEvent)
	this.advanceStep();

    console.log('TestScript.reportEvent: ', this.curstep, eventName);
    var curScript = this.scripts[this.activeScript];
    while (this.curstep < curScript.length) {
	var expectEvent = curScript[this.curstep][0];
	var prefix = expectEvent.slice(0,1); // + => optional action; - => no action (ignore)
	if (prefix != '+' && prefix != '-')
	    prefix = '';
	var expectName = prefix ? expectEvent.slice(1) : expectEvent;
	if (eventName == expectName) {
	    if (prefix != '-') // Handle matched event
		break;
	    // Skip matched event
	    this.curstep++;
	    return null;
	}
	if (eventName != expectName && !prefix) // Event mismatch
	    break;
	this.curstep++;
    }
    console.log('TestScript.reportEvent2: ', this.curstep, expectName);
    if (this.curstep >= curScript.length) {
	this.activeScript = '';
	alert("TestScript "+this.activeScript+" completed all steps");
	this.showStatus('done');
	return null;
    }
    if (eventName != expectName) {
	this.activeScript = '';
	alert("TestScript ERROR: Expected event '"+expectName+"' but encountered '"+eventName+"'");
	return null;
    }
    var commands = curScript[this.curstep];
    var slideNum = commands[1];
    var delay = commands[2];
    var action = commands[3];
    this.showStatus();
    this.curstep++;
    console.log('TestScript.reportEvent3: ', this.curstep);
    if (slideNum) {
	if (!Slidoc.getCurrentSlideId())
	    Slidoc.slideViewStart();
	Slidoc.slideViewGo(true, slideNum);
    }
    var stepEvent = this.eventAction.bind(this, commands);
    if (Slidoc.getParameter('teststep') && (action == 'advance') ) {
	this.stepEvent = stepEvent;
	this.showStatus('\u25BA to advance');
	return null;
    } else if (delay) {
	setTimeout(stepEvent, delay);
	return null;
    } else {
	return stepEvent();
    }
}

TestScript.prototype.eventAction = function(commands) {
    var slideNum = commands[1];
    var delay = commands[2];
    var action = commands[3];
    var args = (commands.length > 4) ? commands[4] : null;
    var slide_id = Slidoc.getCurrentSlideId();
    console.log('TestScript.eventAction: ', this.curstep, slideNum, delay, action, args, slide_id);
    try {
	switch (action) {
	case 'login':
	    document.getElementById('gdoc-login-user').value = Slidoc.getParameter('testuser');
	    document.getElementById('gdoc-login-token').value = Slidoc.getParameter('testtoken');
	    if (Slidoc.getParameter('teststep'))
		this.showStatus('Login to advance');
	    else
		document.getElementById('gdoc-login-button').onclick();
	    break;
	case 'lateToken':
	    return args[0];
	case 'reset':
	    Slidoc.resetPaced();   // Does nothing for Google Docs (must delete row in spreadsheet to reset)
	    break;
	case 'choice':
	    if (!slide_id)
		throw('No current slide for choice action');
	    if (Slidoc.getParameter('teststep'))
		this.showStatus('Click choice to advance');
	    else
		document.getElementById(slide_id+'-choice-'+args[0].toUpperCase()).onclick();
	    break;
	case 'input':
	    if (!slide_id)
		throw('No current slide for input action');
	    document.getElementById(slide_id+'-answer-input').value = args[0];
	    if (Slidoc.getParameter('teststep'))
		this.showStatus('Answer to advance');
	    else
		document.getElementById(slide_id+'-answer-click').onclick();
	    break;
	case 'textarea':
	    if (!slide_id)
		throw('No current slide for textarea action');
	    document.getElementById(slide_id+'-answer-textarea').value = args[0];
	    if (Slidoc.getParameter('teststep'))
		this.showStatus('Answer to advance');
	    else
		document.getElementById(slide_id+'-answer-click').onclick();
	    break;
	case 'code':
	    if (!slide_id)
		throw('No current slide for code action');
	    document.getElementById(slide_id+'-plugin-code-textarea').value = args[0];
	    if (Slidoc.getParameter('teststep'))
		this.showStatus('Answer to advance');
	    else
		document.getElementById(slide_id+'-answer-click').onclick();
	    break;
	case 'switchUser':
	    var switchElem = document.getElementById('slidoc-switch-user');
	    switchElem.selectedIndex = args[0];
	    switchUser.bind(switchElem)();
	    break;
	case 'gradeStart':
	    document.getElementById(slide_id+'-gstart-click').onclick();
	    break;
	case 'gradeUpdate':
	    document.getElementById(slide_id+'-grade-input').value = args[0];
	    document.getElementById(slide_id+'-comments-textarea').value = args[1];
	    if (Slidoc.getParameter('teststep'))
		this.showStatus('Save to advance');
	    else
		document.getElementById(slide_id+'-grade-click').onclick();
	    break;
	case 'next':
	    break;
	case 'end':
	default:
	    this.activeScript = '';
	    alert('TestScript terminated with action '+action+' after '+this.curstep+' steps');
	    this.showStatus('done');
	}
    } catch(err) {
	this.activeScript = '';
	console.log('TestScript.eventAction: ERROR '+err, err.stack);
	alert('ERROR in eventAction: '+err);
    }
    return null;
}
    
