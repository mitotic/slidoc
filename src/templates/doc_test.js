// Code for test scripts
// Use slidoc.py --test_script to load testing module
// Use URL query options to activate testing:
//    ?testscript=basic/...    # testing script name
//    &teststep=1              # step-wise testing
//    &testuser=admin/aaa/...  # login user name
//    &testkey=key OR testtoken=token # login key/token (token automatically generated from testkey)
//
//  Sample script in *.md files:
//  Script entries of the form ['expectedEvent', slide_number or 0, delay_msec or 0, 'action', [arg1, arg2, ...]]
//    Prefix '+' for expected events indicates optional event (may not be reported)
//    Prefix '-' for expected events indicates skipped event (no action to be performed)
//
// Events:
//   autoEvent: Automatically fires after action for current event is completed
//   end: Ends testing
//   nextEvent: Fired by next action
//   resumeEvent: Fired by button click
//
// Actions:
//  next: Schedule nextEvent after delay (default 500ms)
//  pause: No action, but display message. Usually hit Resume button to generate resumeEvent
//  wait: No action (wait for some other event to fire)
//
// var TestScripts = {};
// TestScripts.basic = [
//   ['ready'],
//   ['+loginPrompt', 0, 500, 'login'],
//   ['+lateTokenPrompt', 0, 0, 'lateToken', ['none']],
//   ['initSession', 0, 0, 'reset'],
//   ['initSlideView', 2, 500, 'choice', ['D']],
//   ['answerTally', 3, 500, 'input', [5.5]],
//   ['answerTally', 11, 0, 'wait'],
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
    Slidoc.log('TestScript.advanceStep:');
    var stepEvent = this.stepEvent;
    if (!stepEvent)
	return false;
    Slidoc.closeAllPopups();
    this.stepEvent = null;
    stepEvent();
    this.showStatus();
    return true;
}

TestScript.prototype.showStatus = function (state, pause) {
    var statusElem = document.getElementById('slidoc-test-status');
    var resumeElem = document.getElementById('slidoc-test-resume');
    if (!statusElem)
	return;
    if (resumeElem)
	resumeElem.style.display = pause ? null : 'none';
    if (state == 'done') {
	statusElem.style.display = 'none';
	return;
    }
    var msg = 'Test '+this.curstep+' ';
    if (state) {
	msg += ': ' + state
    } else {
	var curScript = this.scripts[this.activeScript];
	if (this.curstep < curScript.length) {
	    if (curScript[this.curstep] === undefined)
		alert('TestScript.showStatus: ERROR Step '+this.curstep+' in script '+this.activeScript+' is undefined!');
	    msg += '> '+curScript[this.curstep][0];
	} else {
	    msg += '> END';
	}
    }
    
    statusElem.style.display = null;
    statusElem.textContent = msg;
}

TestScript.prototype.reportTestAction = function (eventName) {
    if (!this.activeScript)
	return null;
    if (this.stepEvent)
	this.advanceStep();

    Slidoc.log('TestScript.reportTestAction: ', this.curstep, eventName);
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
    Slidoc.log('TestScript.reportTestAction:B ', this.curstep, expectName, this.activeScript);
    if (this.curstep >= curScript.length) {
	this.terminate('')
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
    this.curstep++;
    this.showStatus();

    if (slideNum) {
	if (!Slidoc.getCurrentSlideId())
	    Slidoc.slideViewStart();
	Slidoc.slideViewGo(true, slideNum);
    }
    var stepEvent = this.eventAction.bind(this, commands);
    var retval = null;
    if (Slidoc.getParameter('teststep')) {
	this.stepEvent = stepEvent;
	this.showStatus('\u25BA to advance');
    } else if (delay) {
	setTimeout(stepEvent, delay);
    } else {
	retval = stepEvent();
    }
    if (this.curstep < curScript.length && curScript[this.curstep][0] == 'autoEvent')
	setTimeout(this.reportTestAction.bind(this, 'autoEvent'), 0);
    return retval;
}

TestScript.prototype.terminate = function(lastAction) {
    this.activeScript = '';
    this.showStatus('done');
    Slidoc.showPopup('<pre>TestScript terminated with action '+lastAction+' after '+this.curstep+' steps</pre>');
}

TestScript.prototype.eventAction = function(commands) {
    var slideNum = commands[1];
    var delay = commands[2];
    var action = commands[3];
    var args = (commands.length > 4) && commands[4].length ? commands[4] : null;
    var slide_id = Slidoc.getCurrentSlideId();
    Slidoc.log('TestScript.eventAction: ', this.curstep, slideNum, delay, action, args, slide_id);
    try {
	var testuser  = Slidoc.getParameter('testuser') || '';
	var testkey   = Slidoc.getParameter('testkey') || '';
	var testtoken = Slidoc.getParameter('testtoken') || '';
	if (testkey && !testtoken)
	    testtoken = (testuser == 'admin') ? testkey : gen_user_token(testkey, testuser);
	var testlate  = Slidoc.getParameter('testlate') || '';

	switch (action) {
	case 'login':
	    document.getElementById('gdoc-login-user').value = testuser;
	    document.getElementById('gdoc-login-token').value = testtoken;
	    if (Slidoc.getParameter('teststep'))
		this.showStatus('Login to advance');
	    else
		document.getElementById('gdoc-login-button').onclick();
	    break;
	case 'lateToken':
	    var value = args ? args[0] : '';
	    if (testlate && (testlate.length < 5 || testlate.length > 18)) {
		return testlate;
	    } else if (testkey) {
		var date = testlate;
		if (!date && value && !isNaN(value))
		    date = value;
		if (date && !isNaN(date)) {
		    // Advance current date by date days
		    var newDate = new Date();
		    newDate.setDate(newDate.getDate() + date);
		    date = newDate.toISOString().slice(0,16);
		}
		if (date)
		    value = gen_late_token(testkey, GService.gprofile.auth.id, Sliobj.sessionName, date);
	    }
	    return value;
	case 'dialogReturn':
	    if (Slidoc.getParameter('teststep') || !args)
		this.showStatus('Click button to advance');
	    return args ? args[0] : null;
	case 'reset':
	    Slidoc.resetPaced();   // Does nothing for Google Docs (must delete row in spreadsheet to reset)
	    break;
	case 'choice':
	case 'choiceSel':
	    if (!slide_id)
		throw('No current slide for choice action');
	    if (Slidoc.getParameter('teststep') || !args) {
		this.showStatus('Click choice(s) and Answer to advance');
	    } else {
		if (args) {
		    for (var j=0; j<args.length; j++) {
			if (args[j].length == 1)
			    document.getElementById(slide_id+'-choice-'+args[j].toUpperCase()).onclick();
			else
			    document.getElementById(slide_id+'-answer-textarea').value = args[j]; // Explain
		    }
		}
		if (action != 'choiceSel')
		    document.getElementById(slide_id+'-answer-click').onclick();
	    }
	    break;
	case 'input':
	    if (!slide_id)
		throw('No current slide for input action');
	    document.getElementById(slide_id+'-answer-input').value = args ? args[0] : '';
	    if (args && args.length > 1)
		document.getElementById(slide_id+'-answer-textarea').value = args[1]; // Explain

	    if (Slidoc.getParameter('teststep'))
		this.showStatus('Answer to advance');
	    else
		document.getElementById(slide_id+'-answer-click').onclick();
	    break;
	case 'textarea':
	    if (!slide_id)
		throw('No current slide for textarea action');
	    document.getElementById(slide_id+'-answer-textarea').value = args ? args[0] : '';
	    if (Slidoc.getParameter('teststep'))
		this.showStatus('Answer to advance');
	    else
		document.getElementById(slide_id+'-answer-click').onclick();
	    break;
	case 'code':
	    if (!slide_id)
		throw('No current slide for code action');
	    document.getElementById(slide_id+'-plugin-Code-textarea').value = args ? args[0] : '';
	    if (Slidoc.getParameter('teststep'))
		this.showStatus('Answer to advance');
	    else
		document.getElementById(slide_id+'-answer-click').onclick();
	    break;
	case 'submitSession':
	    document.getElementById(slide_id+'-plugin-Submit-submitbutton').onclick();
	    break;
	case 'switchUser':
	    var switchElem = document.getElementById('slidoc-switch-user');
	    switchElem.selectedIndex = args ? args[0] : 0;
	    switchUser.bind(switchElem)();
	    break;
	case 'gradeStart':
	    document.getElementById(slide_id+'-gstart-click').onclick();
	    break;
	case 'gradeUpdate':
	    document.getElementById(slide_id+'-grade-input').value = args ? args[0] : '';
	    document.getElementById(slide_id+'-comments-textarea').value = args && args.length > 1 ? args[1] : '';
	    if (Slidoc.getParameter('teststep'))
		this.showStatus('Save to advance');
	    else
		document.getElementById(slide_id+'-grade-click').onclick();
	    break;
	case 'finalizeShare':
	    var finalizeButton = document.getElementById(slide_id+'-plugin-Share-sharefinalize');
	    if (finalizeButton)
		finalizeButton.onclick();
	    break;
	case 'next':
	    setTimeout(Slidoc.reportTestAction.bind(null, 'nextEvent'), args ? args[0] : 500);
	    break;
	case 'pause':
	    this.showStatus(args ? args[0] : 'Click Resume button to proceed', true)
	    break;
	case 'wait':
	    break;
	case 'end':
	default:
	    this.terminate(action);
	}
    } catch(err) {
	this.activeScript = '';
	Slidoc.log('TestScript.eventAction: ERROR '+err, err.stack);
	alert('ERROR in eventAction: '+err);
    }
    return null;
}
    
