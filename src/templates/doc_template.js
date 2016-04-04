// Template file 

var Slidoc = {};
Slidoc.params = JSON.parse(atob('%(js_params)s'));

(function(Slidoc) {

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
           break;
       case 35:  // End
           Slidoc.slideViewGo(false, getVisibleSlides().length);
           break;
       case 36:  // Home
           Slidoc.slideViewGo(false, 1);
           break;
       case 37:  // Left arrow
           Slidoc.slideViewGo(false);
           break;
       case 38: // Up arrow
           break;
       case 39: // Right arrow
           Slidoc.slideViewGo(true);
           break;
       case 40: // Down arrow
           break;
   }
};

function slidocReady(event) {
   console.log("slidocReady:");

   Slidoc.chainQuery = '';
   Slidoc.showAll = false;
   Slidoc.slideView = 0;
   Slidoc.curChapterId = '';

   Slidoc.delay = {interval: null, timeout: null};

   Slidoc.paced = (Slidoc.params.paceDelay !== null);
   Slidoc.session = null;
   var sessionName = Slidoc.params.filename;
   if (Slidoc.paced) {
      // Paced named session
      Slidoc.session = slidocGet('session');
      if (Slidoc.session && Slidoc.session.sessionName != sessionName) {
         if (window.confirm('Discard previous session '+Slidoc.session.sessionName+'?')) {
            Slidoc.session = null;
         } else {
            document.body.text = 'Cancelled page load';
            return false;
         }
      }
   } else {
      // Unnamed session
      sessionName = '';
   }
   if (!Slidoc.session) {
      // New paced session
      Slidoc.session = {sessionName: sessionName,
                        lastSlide: 1,
                        lastTime: 0,
                        lastTries: 0,
                        questionsCount: 0,
                        questionsCorrect: 0,
                        questionsAttempted: {}
                       };
   }

   if (Slidoc.paced) {
     Slidoc.go("#slidoc01-01", false, true);
     Slidoc.slideViewStart();
     return;
   }
   Slidoc.chainUpdate(location.search);
   var toc_elem = document.getElementById("slidoc00");
   if (toc_elem) Slidoc.go(location.hash || "#slidoc00", false, true);
}

function slidocPut(key, obj) {
   window.localStorage['slidoc_'+key] = JSON.stringify(obj);
}

function slidocDel(key) {
   delete window.localStorage['slidoc_'+key];
}

function slidocGet(key) {
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
	Slidoc.go('#slidoc00', false, true);
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
        elements[i].style.display = (elements[i].style.display=='block') ? 'none' : 'block'
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

Slidoc.choiceClick = function (elem, slide_id, question_number, choice_val) {
   console.log("Slidoc.choiceClick:", slide_id, question_number, choice_val);
   if (question_number in Slidoc.session.questionsAttempted)
      return false;
   Slidoc.session.questionsAttempted[question_number] = choice_val;

   elem.style['text-decoration'] = 'line-through';
   var choices = document.getElementsByClassName(slide_id+"-choice");
   for (var i = 0; i < choices.length; ++i) {
      choices[i].removeAttribute("onclick");
      choices[i].classList.remove("slidoc-clickable");
   }
   var notes_id = slide_id+"-notes";
   Slidoc.idDisplay(notes_id);
   var notes_elem = document.getElementById(notes_id);
   if (notes_elem) notes_elem.style.display = 'inline';
   var concept_elem = document.getElementById(slide_id+"-concepts");
   var concept_list = concept_elem ? concept_elem.textContent.split('; ') : ';';
   var ans_elem = document.getElementById(slide_id+"-answer");
   if (ans_elem) ans_elem.style.display = 'inline';
   var corr_elem = document.getElementById(slide_id+"-correct");
   console.log("Slidoc.choiceClickb:", corr_elem);
   if (corr_elem) {
      var corr_answer = corr_elem.textContent;
      console.log('Slidoc.choiceClick:corr', corr_answer, concept_list);
      if (corr_answer) {
          Slidoc.session.questionsCount += 1;
          var corr_choice = document.getElementById(slide_id+"-choice-"+corr_answer);
          if (corr_choice) {
           corr_choice.style['text-decoration'] = '';
           corr_choice.style['font-weight'] = 'bold';
         }
         var resp_elem = document.getElementById(slide_id+"-resp");
         if (resp_elem && choice_val) {
            if (choice_val == corr_answer)  {
               Slidoc.session.questionsCorrect += 1;
               resp_elem.innerHTML = " &#x2714;&nbsp; ("+Slidoc.session.questionsCorrect+"/"+Slidoc.session.questionsCount+")";
            } else {
               resp_elem.innerHTML = " &#x2718;&nbsp; ("+Slidoc.session.questionsCorrect+"/"+Slidoc.session.questionsCount+")";
            }
          }
       }
   }
   return false;
}

Slidoc.answerClick = function (elem, slide_id, question_number, choice_type) {
   console.log("Slidoc.answerClick:", slide_id, choice_type);
   Slidoc.toggleInline(elem);
   if (choice_type) {
      var notes_id = slide_id+"-notes";
      var notes_link = document.getElementById(notes_id);
      if (notes_link) {
          // Display any notes associated with this question
          notes_link.style.display = "inline";
          Slidoc.idDisplay(notes_id);
      }
   }
   return false;
}

Slidoc.slideViewStart = function () {
   if (Slidoc.slideView) 
      return false;
   var slides = getVisibleSlides();
   if (!slides)
      return false;
   Slidoc.breakChain();

   if (Slidoc.paced) {
       Slidoc.slideView = Slidoc.session.lastSlide; 
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
   Slidoc.hide(document.getElementById(slides[0].id+'-hidenotes'), 'slidoc-notes', 'Hide');
   document.body.classList.add('slidoc-slide-view');

   Slidoc.slideViewGo(false, Slidoc.slideView);
   return false;
}

Slidoc.slideViewEnd = function() {
   if (Slidoc.paced) {
      alert('Paced mode');
      return false;
   }
   document.body.classList.remove('slidoc-slide-view');
   Slidoc.classDisplay('slidoc-slide', 'block');
   Slidoc.classDisplay('slidoc-notes', 'block');
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

    if (Slidoc.paced) {
	console.log('Slidoc.slideViewGo2:', Slidoc.params.paceDelay, slide_num, Slidoc.session.lastSlide);
	if (Slidoc.params.paceDelay && slide_num > Slidoc.session.lastSlide) {
	    var delta = (Date.now() - Slidoc.session.lastTime)/1000;
	    if (delta < Slidoc.params.paceDelay) {
		alert('Please wait '+ Math.ceil(Slidoc.params.paceDelay-delta) + ' seconds');
		return false;
	    }
	}
	slide_num = Math.min(slide_num, Slidoc.session.lastSlide+1);
	Slidoc.session.lastSlide = Math.max(Slidoc.session.lastSlide, slide_num);
	Slidoc.session.lastTime = Date.now();
	if (Slidoc.session.sessionName) {
	    // Save updated session
	    slidocPut('session', Slidoc.session);
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
   return false;
}

Slidoc.breakChain = function () {
   // Hide any current chain link
   var tagid = location.hash.substr(1);
   var ichain_elem = document.getElementById(tagid+"-ichain");
   if (ichain_elem)
       ichain_elem.style.display = 'none';
}

Slidoc.go = function (slideHash, chained, firstChapter) {
   // Scroll to slide with slideHash, hiding current chapter and opening new one
   // If chained, hide previous link and set up new link
   console.log("Slidoc.go:", slideHash, chained);
   var slideId = slideHash.substr(1);
   var goElement = document.getElementById(slideId);
   console.log('Slidoc.go2: ', slideId, chained, goElement);
   if (!goElement) {
      console.log('Slidoc.go: Error - unable to find element', slideHash);
      return false;
   }
   Slidoc.breakChain();
   if (!chained) {
       // End chain
       Slidoc.chainQuery = '';
   }

   if (Slidoc.curChapterId || Slidoc.slideView || firstChapter) {
      // Displaying single chapter or slide show
      var match = RegExp('slidoc-ref-(.*)$').exec(slideId);
      console.log('Slidoc.go2a: ', match, slideId);
      if (match) {
         // Find slide containing header
	 slideId = '';
         for (var i=0; i<goElement.classList.length; ++i) {
	     var refmatch = RegExp('slidoc-referable-in-(.*)$').exec(goElement.classList[i]);
	     if (refmatch) {
		 slideId = refmatch[1];
		 slideHash = '#'+slideId;
                 console.log('Slidoc.go2b: ', slideHash);
		 break;
	     }
	 }
         if (!slideId) {
            console.log('Slidoc.go: Error - unable to find slide containing header:', slideHash);
            return false;
         }
      }
   }
   if (Slidoc.curChapterId || firstChapter) {
      var match = RegExp('slidoc(\\d+)(-.*)?$').exec(slideId);
      if (!match) {
          console.log('Slidoc.go: Error - invalid hash, not slide or chapter', slideHash);
         return false;
      }
      // Display only chapter containing slide
      var newChapterId = 'slidoc'+match[1];
      if (newChapterId != Slidoc.curChapterId || firstChapter) {
         var newChapterElem = document.getElementById(newChapterId);
         if (!newChapterElem) {
            console.log('Slidoc.go: Error - unable to find chapter:', newChapterId);
            return false;
         }
         Slidoc.curChapterId = newChapterId;
         var chapters = document.getElementsByClassName('slidoc-container');
         console.log('Slidoc.go3: ', newChapterId, chapters.length);
         for (var i = 0; i < chapters.length; ++i) {
            chapters[i].style.display = (chapters[i].id == newChapterId) ? 'block' : 'none';
         }
      }
   }
   if (Slidoc.slideView) {
      var slides = getVisibleSlides();
      for (var i=0; i<slides.length; ++i) {
         if (slides[i].id == slideId) {
           console.log('Slidoc.go4: ', location.hash);
           Slidoc.slideViewGo(false, i+1);
           console.log('Slidoc.go4b: ', location.hash);
           return false;
         }
      }
      console.log('Slidoc.go: Error - slideshow slide not in view:', slideId);
      return false;
   }

   console.log('Slidoc.go4: ', slideHash);
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
   Slidoc.go('#'+comps[1], true);
console.log("Slidoc.chainNav2:", location.hash);
   return false;
}

Slidoc.chainStart = function (queryStr, slideHash) {
   // Go to first link in concept chain
   console.log("Slidoc.chainStart:", slideHash, queryStr);
   Slidoc.chainQuery = queryStr;
   Slidoc.go(slideHash, true);
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
            concept_elem.onclick = function() {Slidoc.go(tagconceptref);}
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
    
})(Slidoc);
