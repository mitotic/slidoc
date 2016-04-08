// JS include file for slidoc

var Slidoc = {};  // External object

///UNCOMMENT: (function(Slidoc) {

var Sliobj = {}; // Internal object

Sliobj.params = JS_PARAMS_OBJ;

Sliobj.lastInputValue = null;

document.onreadystatechange = function(event) {
    console.log('onreadystatechange:', document.readyState);
    if (document.readyState != "interactive")
      return;
    try {
       slidocReady();
    } catch(err) {console.log("slidocReady: ERROR", err, err.stack);}
}

document.onkeydown = function(evt) {
   if (!Slidoc.slideView)
     return;
   switch (evt.keyCode) {
       case 27:  // Escape
           Slidoc.slideViewEnd();
           return false;
       case 35:  // End
           Slidoc.slideViewGo(false, getVisibleSlides().length);
           return false;
       case 36:  // Home
           Slidoc.slideViewGo(false, 1);
           return false;
       case 37:  // Left arrow
           Slidoc.slideViewGo(false);
           return false;
       case 38: // Up arrow
           break;
       case 39: // Right arrow
           Slidoc.slideViewGo(true);
           break;
       case 40: // Down arrow
           break;
   }
   return;
};

Slidoc.inputKeyDown = function (evt) {
    console.log('Slidoc.inputKeyDown', evt.keyCode, evt.target, evt.target.id);
    if (evt.keyCode == 13) {
	var inputElem = document.getElementById(evt.target.id.replace('-input', '-ansclick'));
	inputElem.onclick();
    }
}

function slidocReady(event) {
    console.log("slidocReady:");
    sessionManage();

    Slidoc.chainQuery = '';
    Slidoc.showAll = false;
    Slidoc.slideView = 0;
    Slidoc.curChapterId = '';

    Slidoc.delay = {interval: null, timeout: null};

    var pacedSession = (Sliobj.params.paceOpen !== null);
    Sliobj.session = null;
    Sliobj.sessionName = Sliobj.params.filename;
    if (pacedSession) {
	// Paced named session
	Sliobj.session = sessionGet(Sliobj.sessionName);
    } else {
	// Unnamed session
	Sliobj.sessionName = '';
    }
    if (!Sliobj.session) {
	// New paced session
	Sliobj.session = sessionCreate(pacedSession, Sliobj.params.paceOpen);
	sessionPut(Sliobj.sessionName, Sliobj.session);
    }

   if (Sliobj.session.paced) {
     Slidoc.startPaced();
     return false;
   }
   Slidoc.chainUpdate(location.search);
   var toc_elem = document.getElementById("slidoc00");
   if (toc_elem) goToSlide(location.hash || "#slidoc00", false, true);
}

function sessionCreate(paced, paceOpen) {
    return {paced: paced || false,
	    paceOpen: paceOpen || 0,
            expiryTime: Date.now() + 180*86400,    // 180 day lifetime
	    lastSlide: 0,
            lastTime: 0,
            lastTries: 0,
            remainingTries: 0,
            lastAnswerCorrect: false,
	    questionSlide: '',
            questionsCount: 0,
            questionsCorrect: 0,
            questionsAttempted: {}
	   };
}

function sessionManage() {
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

function sessionGet(name) {
    var sessionObj = localGet('sessions');
    if (!sessionObj) {
	alert('sessionGet: Error - no session object');
    } else {
	if (name in sessionObj)
	    return sessionObj[name];
	else
	    return null;
    }
}

function sessionPut(name, obj) {
    if (!name)
	return;
    var sessionObj = localGet('sessions');
    if (!sessionObj) {
	alert('sessionPut: Error - no session object');
    } else {
	sessionObj[name] = obj;
	localPut('sessions', sessionObj);
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

function hourglass(delaySec) {
    var interval = 0.05;
    var jmax = delaySec/interval;
    var j = 0;
    var hg_container_elem = document.getElementById('slidoc-hourglass-container');
    var hg_elem = document.getElementById('slidoc-hourglass');
    function hourglass() {
	j += 1;
	hg_elem.style.left = 1.05*Math.ceil(hg_container_elem.offsetWidth*j/jmax);
    }
    var intervalId = setInterval(hourglass, 1000*interval);
    function endInterval() {
	clearInterval(intervalId);
	hg_elem.style.left = hg_container_elem.offsetWidth;
    }
    setTimeout(endInterval, delaySec*1000);
}

function getVisibleSlides() {
   var slideClass = 'slidoc-slide';
   if (Slidoc.curChapterId) {
      var curChap = document.getElementById(Slidoc.curChapterId);
      if (curChap.classList.contains('slidoc-noslide'))
        return null;
      slideClass = Slidoc.curChapterId+'-slide';
   }
   return document.getElementsByClassName(slideClass);
}

Slidoc.hide = function (elem, className, action) {
   // Action = 'Hide' or 'Show' or omitted for toggling
   if (!elem) return false;
   action = action || elem.textContent;
   if (action.charAt(0) == 'H') {
      elem.textContent = elem.textContent.replace('Hide', 'Show');
      if (className) Slidoc.classDisplay(className, 'none');
   } else {
      elem.textContent = elem.textContent.replace('Show', 'Hide');
      if (className) Slidoc.classDisplay(className, 'block');
   }
   return false;
}

Slidoc.allDisplay = function (elem) {
   // Display all "chapters"
   Slidoc.hide(elem);
   Slidoc.showAll = !Slidoc.showAll;
   var elements = document.getElementsByClassName('slidoc-container');
   for (var i = 0; i < elements.length; ++i) {
      elements[i].style.display= Slidoc.showAll ? null : 'none';
   }
    if (Slidoc.showAll) {
	Slidoc.curChapterId = '';
        document.body.classList.add('slidoc-all-view');
    } else {
        document.body.classList.remove('slidoc-all-view');
	goToSlide('#slidoc00', false, true);
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
   console.log("Slidoc.answerClick:", elem, slide_id, question_number, answer_type, response);
   var setup = !elem;
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
   var inputElem = document.getElementById(slide_id+'-input');
   if (inputElem) {
       if (setup) {
	   inputElem.value = response;
       } else {
	   response = inputElem.value.trim();
	   if (answer_type == 'number' && isNaN(response)) {
	       alert('Expecting a numeric value as answer');
	       return false;
	   } else if (Sliobj.session.paced) {
	       if (!response && Sliobj.session.remainingTries > 0) {
		   alert('Expecting a non-null answer');
		   return false;
	       } else if (Sliobj.lastInputValue && Sliobj.lastInputValue == response) {
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

   var corr_elem = document.getElementById(slide_id+"-correct");
   console.log("Slidoc.choiceClick2:", corr_elem);

   if (corr_elem) {
      var corr_answer = corr_elem.textContent;
      console.log('Slidoc.choiceClick:corr', corr_answer);
      if (corr_answer) {
          var corr_choice = document.getElementById(slide_id+"-choice-"+corr_answer);
          if (corr_choice) {
              corr_choice.style['text-decoration'] = '';
              corr_choice.style['font-weight'] = 'bold';
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

    if (!setup && Sliobj.paced)
	Sliobj.session.lastTries += 1
    var corr_elem = document.getElementById(slide_id+"-correct");
    console.log("Slidoc.answerUpdate2:", corr_elem);

    var is_correct = null;
    if (corr_elem) {
	var corr_answer = corr_elem.textContent;
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
		var after_str = '';
		if (Sliobj.params.tryDelay) {
		    hourglass(Sliobj.params.tryDelay);
		    after_str = ' after '+Sliobj.params.tryDelay+' seconds';
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
	corr_elem.style.display = 'inline';
    }

    var ans_elem = document.getElementById(slide_id+"-answer");
    if (ans_elem) ans_elem.style.display = 'inline';

    var click_elem = document.getElementById(slide_id+"-ansclick");
    if (click_elem) click_elem.style.display = 'inline';
    if (click_elem) click_elem.classList.remove('slidoc-clickable');

    var concept_elem = document.getElementById(slide_id+"-concepts");
    var concept_list = concept_elem ? concept_elem.textContent.split('; ') : ';';

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

    if (is_correct !== null) {
	// Keep score
	Sliobj.session.questionsCount += 1;
	if (is_correct)
            Sliobj.session.questionsCorrect += 1;
	Slidoc.showScore();
    }
    if (Sliobj.session.paced) {
	Sliobj.session.remainingTries = 0;
	if (is_correct) {
	    Sliobj.session.lastAnswerCorrect = true;
	}
	Sliobj.session.lastTime = Date.now();
	sessionPut(Sliobj.sessionName, Sliobj.session);
    }
}

Slidoc.showScore = function () {
    var scoreElem = document.getElementById('slidoc-score-display');
    if (scoreElem && Sliobj.session.questionsCount)
	scoreElem.textContent = Sliobj.session.questionsCorrect+'/'+Sliobj.session.questionsCount;
}

Slidoc.resetPaced = function () {
    if (!window.confirm('Do want to completely delete all answers/scores for this session and start over?'))
	return false;
    Sliobj.session = sessionCreate(Sliobj.session.paced, Sliobj.session.paceOpen);
    sessionPut(Sliobj.sessionName, Sliobj.session);
    location.reload(true);
}

Slidoc.startPaced = function () {
    console.log('Slidoc.startPaced: ');
    if (!Sliobj.session.lastSlide) {
	var alertStr = 'Starting paced slideshow '+Sliobj.sessionName+':<ul>';
	if (Sliobj.params.paceDelay)
	    alertStr += '<li>'+Sliobj.params.paceDelay+' sec delay between slides</li>';
	if (Sliobj.params.tryCount)
	    alertStr += '<li>'+Sliobj.params.tryCount+' attempts for non-choice questions</li>';
	if (Sliobj.params.tryDelay)
	    alertStr += '<li>'+Sliobj.params.tryDelay+' sec delay between attempts</li>';
        alertStr += '</ul>';
	Slidoc.showPopup(alertStr);
    }
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
    if (Sliobj.session.questionsCount)
	Slidoc.showScore();

    document.body.classList.add('slidoc-paced-view');
    goToSlide("#slidoc01-01", false, true);
    Slidoc.slideViewStart();
}

Slidoc.endPaced = function () {
    console.log('Slidoc.endPaced: ');
    if (Sliobs.session.paceOpen) {
	// If open session, unpace
	document.body.classList.remove('slidoc-paced-view');
	Sliobj.session.paced = false;
    }
}

Slidoc.answerPacedAllow = function () {
    if (!Sliobj.session.paced)
	return true;

    if (Sliobj.params.tryDelay && Sliobj.session.lastTries > 0) {
	var delta = (Date.now() - Sliobj.session.lastTime)/1000;
	if (delta < Sliobj.params.tryDelay) {
	    alert('Please wait '+ Math.ceil(Sliobj.params.tryDelay-delta) + ' seconds to answer again');
	    return false;
	}
    }
    return true;
}

Slidoc.slideViewStart = function () {
   if (Slidoc.slideView) 
      return false;
   var slides = getVisibleSlides();
   if (!slides)
      return false;
   Slidoc.breakChain();

   if (Sliobj.session.paced) {
       Slidoc.slideView = Sliobj.session.lastSlide || 1; 
   } else {
       Slidoc.slideView = 1;
       for (var i=0; i<slides.length; ++i) {
	   // Start from currently visible slide
	   var topOffset = slides[i].getBoundingClientRect().top;
	   if (topOffset >= 0 && topOffset < window.innerHeight) {
               Slidoc.slideView = i+1;
               break;
	   }
       }
   }
   Slidoc.classDisplay('slidoc-toc', 'none');
   Slidoc.hide(document.getElementById(slides[0].id+'-hidenotes'), 'slidoc-notes', 'Hide');
   document.body.classList.add('slidoc-slide-view');

   Slidoc.slideViewGo(false, Slidoc.slideView);
   return false;
}

Slidoc.slideViewEnd = function() {
   if (Sliobj.session.paced) {
      alert('Paced mode');
      return false;
   }
   document.body.classList.remove('slidoc-slide-view');
   Slidoc.classDisplay('slidoc-slide', 'block');
   Slidoc.classDisplay('slidoc-notes', 'block');
   Slidoc.classDisplay('slidoc-toc', 'block');
   var slides = getVisibleSlides();
   if (slides && Slidoc.slideView > 0 && Slidoc.slideView <= slides.length) {
     location.href = '#'+slides[Slidoc.slideView-1].id;
   }
   Slidoc.slideView = 0;
   return false;
}

Slidoc.slideViewGo = function (forward, slide_num) {
   console.log('Slidoc.slideViewGo:', forward, slide_num);
   if (!Slidoc.slideView)
      return false;

    var slides = getVisibleSlides();
    if (slide_num) {
	slide_num = Math.min(slide_num, slides.length);
    } else {
	slide_num = forward ? Slidoc.slideView+1 : Slidoc.slideView-1;
    }
   if (!slides || slide_num < 1 || slide_num > slides.length)
      return false;

    if (Sliobj.session.paced) {
	console.log('Slidoc.slideViewGo2:', slide_num, Sliobj.session.lastSlide);
        if (slide_num > Sliobj.session.lastSlide) {
	    // Advancing to next paced slide

	    if (Sliobj.session.questionSlide && Sliobj.session.remainingTries) {
		var tryCount =  (Sliobj.session.questionSlide=='choice') ? 1 : Sliobj.session.remainingTries;
		alert('Please answer before proceeding. You have '+tryCount+' try(s)');
		return false;
	    } else if (!Sliobj.session.questionSlide && Sliobj.params.paceDelay) {
		var delta = (Date.now() - Sliobj.session.lastTime)/1000;
		if (delta < Sliobj.params.paceDelay) {
		    alert('Please wait '+ Math.ceil(Sliobj.params.paceDelay-delta) + ' seconds');
		    return false;
		}
	    }
            // Update session for new slide
	    slide_num = Sliobj.session.lastSlide+1;
	    Sliobj.session.lastSlide = slide_num; 
	    Sliobj.session.lastTime = Date.now();

	    Sliobj.session.lastTries = 0;
	    Sliobj.lastInputValue = null;
	    var answerElem = document.getElementById(slides[slide_num-1].id+'-answer');
	    if (answerElem) {
		Sliobj.session.questionSlide = document.getElementById(slides[slide_num-1].id+'-choice-A') ? 'choice' : 'other';
		Sliobj.session.lastAnswerCorrect = false;
		Sliobj.session.remainingTries = Sliobj.params.tryCount;
	    } else {
		Sliobj.session.questionSlide = '';
		Sliobj.session.remainingTries = 0;
		if (Sliobj.params.paceDelay)
		    hourglass(Sliobj.params.paceDelay);
            }

	    if (Sliobj.session.lastSlide == slides.length) {
		Slidoc.endPaced();
	    }
	    // Save updated session (if not transient)
	    sessionPut(Sliobj.sessionName, Sliobj.session);
	}
    }

    var prev_elem = document.getElementById('slidoc-slide-nav-prev');
    var next_elem = document.getElementById('slidoc-slide-nav-next');
    prev_elem.style.visibility = (slide_num == 1) ? 'hidden' : 'visible';
    next_elem.style.visibility = (slide_num == slides.length) ? 'hidden' : 'visible';

    console.log('Slidoc.slideViewGo3:', slide_num, slides[slide_num-1]);
    slides[slide_num-1].style.display = 'block';
    for (var i=0; i<slides.length; ++i) {
	if (i != slide_num-1) slides[i].style.display = 'none';
    }
    Slidoc.slideView = slide_num;
    location.href = '#'+slides[Slidoc.slideView-1].id;

    var inputElem = document.getElementById(slides[Slidoc.slideView-1].id+'-input');
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
    return goToSlide(slideHash, chained);
}

function goToSlide(slideHash, chained, force) {
   // Scroll to slide with slideHash, hiding current chapter and opening new one
   // If chained, hide previous link and set up new link
   console.log("goToSlide:", slideHash, chained);
    if (Sliobj.session.paced && slideHash && !force && !Sliobj.session.lastAnswerCorrect) {
	console.log("goToSlide: Error - paced mode");
	return false;
    }
    if (!slideHash) {
	if (Slidoc.slideView) {
	    Slidoc.slideViewGo(false, 1);
	} else {
	    location.hash = Slidoc.curChapterId ? '#'+Slidoc.curChapterId+'-01' : '#slidoc01-01';
	    window.scrollTo(0,0);
        }
	return false;
    }

   var slideId = slideHash.substr(1);
   var goElement = document.getElementById(slideId);
   console.log('goToSlide2: ', slideId, chained, goElement);
   if (!goElement) {
      console.log('goToSlide: Error - unable to find element', slideHash);
      return false;
   }
   Slidoc.breakChain();
   if (!chained) {
       // End chain
       Slidoc.chainQuery = '';
   }

   if (Slidoc.curChapterId || Slidoc.slideView || force) {
      // Displaying single chapter or slide show
      var match = RegExp('slidoc-ref-(.*)$').exec(slideId);
      console.log('goToSlide2a: ', match, slideId);
      if (match) {
         // Find slide containing header
	 slideId = '';
         for (var i=0; i<goElement.classList.length; ++i) {
	     var refmatch = RegExp('slidoc-referable-in-(.*)$').exec(goElement.classList[i]);
	     if (refmatch) {
		 slideId = refmatch[1];
		 slideHash = '#'+slideId;
                 console.log('goToSlide2b: ', slideHash);
		 break;
	     }
	 }
         if (!slideId) {
            console.log('goToSlide: Error - unable to find slide containing header:', slideHash);
            return false;
         }
      }
   }
   if (Slidoc.curChapterId || force) {
      var match = RegExp('slidoc(\\d+)(-.*)?$').exec(slideId);
      if (!match) {
          console.log('goToSlide: Error - invalid hash, not slide or chapter', slideHash);
         return false;
      }
      // Display only chapter containing slide
      var newChapterId = 'slidoc'+match[1];
      if (newChapterId != Slidoc.curChapterId || force) {
         var newChapterElem = document.getElementById(newChapterId);
         if (!newChapterElem) {
            console.log('goToSlide: Error - unable to find chapter:', newChapterId);
            return false;
         }
         Slidoc.curChapterId = newChapterId;
         var chapters = document.getElementsByClassName('slidoc-container');
         console.log('goToSlide3: ', newChapterId, chapters.length);
         for (var i = 0; i < chapters.length; ++i) {
            chapters[i].style.display = (chapters[i].id == newChapterId) ? 'block' : 'none';
         }
      }
   }
   if (Slidoc.slideView) {
      var slides = getVisibleSlides();
      for (var i=0; i<slides.length; ++i) {
         if (slides[i].id == slideId) {
           Slidoc.slideViewGo(false, i+1);
           return false;
         }
      }
      console.log('goToSlide: Error - slideshow slide not in view:', slideId);
      return false;
   }

   console.log('goToSlide4: ', slideHash);
   location.hash = slideHash;

   if (chained && Slidoc.chainQuery)  // Set up new chain link
       Slidoc.chainUpdate(Slidoc.chainQuery);

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
   if (!Slidoc.chainQuery)
      return false;
   var comps = Slidoc.chainLink(newindex, Slidoc.chainQuery).split('#');
   Slidoc.chainQuery = comps[0];
   goToSlide('#'+comps[1], true);
console.log("Slidoc.chainNav2:", location.hash);
   return false;
}

Slidoc.chainStart = function (queryStr, slideHash) {
   // Go to first link in concept chain
   console.log("Slidoc.chainStart:", slideHash, queryStr);
   Slidoc.chainQuery = queryStr;
   goToSlide(slideHash, true);
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

    if (tagindex) {
        ichain_elem.style.display = 'block';
        var concept_elem = document.getElementById(tagid+"-ichain-concept");
        concept_elem.text = tagconcept;
        if (Slidoc.chainQuery) {
            concept_elem.onclick = function() {goToSlide(tagconceptref);}
        } else {
            concept_elem.href = getBaseURL()+'/'+tagconceptref;
        }
        var prev_elem = document.getElementById(tagid+"-ichain-prev");
        prev_elem.style.visibility = (tagindex == 1) ? 'hidden' : 'visible';
        if (tagindex > 1) {
           if (Slidoc.chainQuery) {
              prev_elem.onclick = function() {Slidoc.chainNav(tagindex-1);}
           } else {
              prev_elem.href = Slidoc.chainURL(tagindex-1);
           }
        }
        var next_elem = document.getElementById(tagid+"-ichain-next");
        next_elem.style.visibility = (tagindex == taglist.length) ? 'hidden' : 'visible';
        if (tagindex < taglist.length) {
           if (Slidoc.chainQuery) {
              next_elem.onclick = function() {Slidoc.chainNav(tagindex+1);}
           } else {
              next_elem.href = Slidoc.chainURL(tagindex+1);
           }
        }
    }
console.log("Slidoc.chainUpdate:4", location.hash);
}

// Popup: http://www.loginradius.com/engineering/simple-popup-tutorial/

Slidoc.showPopup = function (innerHTML, divElemId) {
    // Only one of innerHTML or divElemId needs to be non-null
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

	closeElem.onclick = function () {
	    overlayElem.style.display = 'none';
	    divElem.style.display = 'none';
	}
    }
}

// Detect swipe events
// http://stackoverflow.com/questions/2264072/detect-a-finger-swipe-through-javascript-on-the-iphone-and-android
document.addEventListener('touchstart', handleTouchStart, false);        
document.addEventListener('touchmove', handleTouchMove, false);

var xDown = null;                                                        
var yDown = null;                                                        

function handleTouchStart(evt) {                                         
    xDown = evt.touches[0].clientX;                                      
    yDown = evt.touches[0].clientY;                                      
};                                                

function handleTouchMove(evt) {
    if ( ! xDown || ! yDown ) {
        return;
    }

    var xUp = evt.touches[0].clientX;                                    
    var yUp = evt.touches[0].clientY;

    var xDiff = xDown - xUp;
    var yDiff = yDown - yUp;

    if ( Math.abs( xDiff ) > Math.abs( yDiff ) ) {/*most significant*/
        if ( xDiff > 0 ) {
            /* left swipe (right motion) */ 
           Slidoc.slideViewGo(true);
        } else {
            /* right swipe (leftward motion) */
           Slidoc.slideViewGo(false);
        }                       
    } else {
        if ( yDiff > 0 ) {
            /* up swipe */ 
        } else { 
            /* down swipe */
        }                                                                 
    }
    /* reset values */
    xDown = null;
    yDown = null;                                             
};
    
///UNCOMMENT: })(Slidoc);
