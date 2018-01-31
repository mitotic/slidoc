Share = {
    // Simple share plugin

    init: function() {
	///Slidoc.log('Slidoc.Plugins.Share.init:', this);
	this.shareElem = document.getElementById(this.pluginId+'-sharebutton');
	this.countElem = document.getElementById(this.pluginId+'-sharecount');
	this.detailsElem = document.getElementById(this.pluginId+'-sharedetails');
	this.finalizeElem = document.getElementById(this.pluginId+'-sharefinalize');
	this.respondersElem = document.getElementById(this.pluginId+'-shareresponders');

	var manage = (this.paced == Slidoc.PluginManager.ADMIN_PACE && (this.gradableState || this.testUser));
	toggleClass(!manage, 'slidoc-shareable-hide', this.countElem);

	if (!manage)
	    this.detailsElem.style.display = 'none';
	else
	    toggleClass(false, 'slidoc-shareable-hide', this.detailsElem);

	toggleClass(!manage && !Slidoc.PluginManager.shareReady(this.qattributes.share, this.qattributes.qnumber), 'slidoc-shareable-hide', this.shareElem);

	this.countElem.textContent = manage ? '(?)' : '';
	this.respondersElem.textContent = '';

	this.respErrors = null;
	if (manage)
	    this.detailsElem.style.display = 'none';
	this.responseTally = null;
    },

    answerSave: function () {
	Slidoc.log('Slidoc.Plugins.Share.answerSave:', this.paced);
	if (Slidoc.PluginManager.previewStatus())
	    return;
	if (this.paced == Slidoc.PluginManager.ADMIN_PACE) {
	    if (!Slidoc.PluginManager.isController())
		Slidoc.sendEvent(3, 'Share.answerSave.'+this.slideId, this.qattributes.qnumber, null);
	    else if (this.qattributes.share == 'after_answering')
		this.getResponses(true);
	} else {
	    if (this.qattributes.share != 'after_answering' || !window.GService)
		return;
	    this.getResponses(true);
	    toggleClass(false, 'slidoc-shareable-hide', this.shareElem);
	}
    },

    answerNotify: function (qnumber, respErrors) {
	Slidoc.log('Slidoc.Plugins.Share.answerNotify:', qnumber, respErrors);
	if (this.testUser) {
	    if (qnumber == this.qattributes.qnumber && !Slidoc.PluginManager.answered(this.qattributes.qnumber)) {
		if (respErrors)
		    this.respErrors = respErrors;
		this.getResponses(false);
	    }
	} else {
	    if (this.qattributes.share == 'after_answering')
		toggleClass(false, 'slidoc-shareable-hide', this.shareElem);
	}
    },

    enterSlide: function(paceStart, backward){
	console.log('Slidoc.Plugins.Share.enterSlide:', paceStart, backward);
	if (!backward && Slidoc.PluginManager.autoInteractMode())
	    this.showDetails(true);
	return 0;
    },

    showDetails: function (show) {
	Slidoc.log('Slidoc.Plugins.Share.showDetails:', show);
	if (this.detailsElem.style.display || show) {
	    this.detailsElem.style.display = null;
	    this.getResponses(false);
	} else {
	    this.detailsElem.style.display = 'none';
	}
    },

    finalizeShare: function () {
	Slidoc.log('Slidoc.Plugins.Share.finalizeShare:');
	if (this.paced == Slidoc.PluginManager.ADMIN_PACE) {
	    if (this.testUser && !Slidoc.PluginManager.answered(this.qattributes.qnumber))
		Slidoc.sendEvent(-1, 'AdminPacedForceAnswer', this.qattributes.qnumber, this.slideId);
	    toggleClass(true, 'slidoc-shareable-hide', this.finalizeElem);
	}
	this.getResponses(true);
    },

    displayShare: function (eventArg) {
	Slidoc.log('Slidoc.Plugins.Share.displayShare:', eventArg);
	if (this.qattributes.team == 'setup' && this.testUser && !Slidoc.PluginManager.answered(this.qattributes.qnumber)) {
	    var liveResponses = Slidoc.PluginManager.getLiveResponses(this.qattributes.qnumber);
	    var respIds = Object.keys(liveResponses || {});
	    var html = 'Live responses:<p></p>\n';
	    if (!respIds.length) {
		html += '(None so far!)';
	    } else {
		html += '<ul>\n';
		var responseLists = {};
		var nameMap = {};
		for (var j=0; j<respIds.length; j++) {
		    var respId = respIds[j];       // Responder ID
		    var message = liveResponses[respId];
		    var respVal = message[0];      // Response value
		    nameMap[respId] = message[1];  // Responder display name
		    if (!(respVal in responseLists))
			responseLists[respVal] = [];
		    responseLists[respVal].push(respId);
		}
		if (this.qattributes.team == 'setup')
		    nameMap = Slidoc.makeShortNames(nameMap);
		var responses = Object.keys(responseLists);
		responses.sort();
		for (var j=0; j<responses.length; j++) {
		    var respList = responseLists[responses[j]];
		    html += '<li>'+responses[j]+': ';
		    if (this.qattributes.team != 'setup') {
			html += respList.length+'</li>\n';
		    } else {
			var respNames = [];
			for (var k=0; k<respList.length; k++) {
			    var respId = respList[k];
			    if (nameMap[respId])
				respNames.push(nameMap[respId]);
			    else
				respNames.push(respId);
			}
			respNames.sort();
			html += respNames.join('; ')+'</li>\n';
		    }
		}
		html += '</ul>\n';
	    }
	    Slidoc.showPopup(html, null, true, 0, 'LiveResponse', this.displayShare.bind(this));
	} else {
	    this.getResponses(true);
	}
    },

    getResponses: function (display) {
	Slidoc.log('Slidoc.Plugins.Share.getResponses:', display);
	if (!this.qattributes.share || !window.GService)
	    return;
	this.nCols = 1;
	if (this.qattributes.explain)
	    this.nCols += 1;
	if (this.qattributes.share == 'vote')
	    this.nCols += 1;
	var colPrefix = 'q'+this.qattributes.qnumber;
	var gsheet = getSheet(this.sessionName);
	gsheet.getShare(colPrefix, this.gradableState, this.responseCallback.bind(this, display));
    },

    responseCallback: function (display, result, retStatus) {
	Slidoc.log('Slidoc.Plugins.Share.responseCallback:', display, result, retStatus);
	if (!result && !retStatus)
	    return;
	if (retStatus.error) {
	    var err_match = retStatus.error.match(/^Error:(\w*):(.*)$/);
	    if (err_match)
		alert(err_match[2]);
	    else
		alert(retStatus.error);
	    return;
	}
	var prefix = 'q'+this.qattributes.qnumber+'_';
	var responseHeader = prefix + 'response';
	var explainHeader = prefix + 'explain';

	var responderList = [];
	var responderMap = {};
	var temObj = {};
	if (retStatus.info && retStatus.info.responders) {
	    for (var j=0; j<retStatus.info.responders.length; j++) {
		var responder = retStatus.info.responders[j];
		if (responder.indexOf('/') > 0) {
		    var comps = responder.split('/');
		    var respId = comps[0];
		    responder = comps[1];  // Short responder name
		    var ncomps = comps[2].split(',');  // Comma-separated name
		    if (ncomps.length > 1 && ncomps[1].trim())
                        var respName = ncomps[1].trim().split(' ')[0] + ' ' + ncomps[0];  // First Last
                    else
			respName = comps[2];
		    responderMap[respId] = responder+'/'+respName;
		}
		temObj[responder] = 1;
		if (this.respErrors && responder in this.respErrors)
		    responderList.push(responder+'*');
		else
		    responderList.push(responder);
	    }
	}

	if (this.respErrors) {
	    var keys = Object.keys(this.respErrors);
	    for (var j=0; j<keys.length; j++) {
		if (!(keys[j] in temObj))
		    responderList.push(keys[j]+'**');
	    }
	}

	responderList.sort();

	this.countElem.textContent = '('+responderList.length+')';
	this.respondersElem.innerHTML = '';
	for (var j=0; j<responderList.length; j++) {
	    var responder = responderList[j];
	    var spanElem = document.createElement("span");
	    spanElem.classList.add('slidoc-plugin-Share-responder');
	    if (responder.slice(-2) == '**') {
		spanElem.classList.add('slidoc-plugin-Share-responder-invalid');
		spanElem.textContent = responder.slice(0,-2);
	    } else if (responder.slice(-1) == '*') {
		spanElem.classList.add('slidoc-plugin-Share-responder-repeat');
		spanElem.textContent = responder.slice(0,-1);
	    } else {
		spanElem.classList.add('slidoc-plugin-Share-responder-valid');
		spanElem.textContent = responder;
	    }
	    this.respondersElem.appendChild(spanElem);
	    if (this.qattributes.team == 'setup')
		this.respondersElem.appendChild(document.createElement("br"));
	}
	    
	if (!display)
	    return;

	var checkResp = [];
	var testShare = this.gradableState || (this.testUser && (Slidoc.PluginManager.submitted() || Slidoc.PluginManager.answered(this.qattributes.qnumber)) );
	if (this.correctAnswer && (testShare || Slidoc.PluginManager.shareReady(this.qattributes.share, this.qattributes.qnumber)) ) {
	    // Display correct answer
	    if (this.qattributes.qtype == 'number') {
		var corrComps = Slidoc.PluginManager.splitNumericAnswer(this.correctAnswer);
		if (corrComps[0] != null && corrComps[1] != null)
		    checkResp = corrComps;
		else
		    Slidoc.log('Share.responseCallback: Error in correct numeric answer:'+this.correctAnswer);
	    } else if (this.qattributes.qtype == 'choice') {
		checkResp = [this.correctAnswer];
	    }
	}

	function checkIfCorrect(respVal) {
	    if (checkResp.length == 1) {
		return (checkResp[0].indexOf(respVal) >= 0);
	    } else if (checkResp.length == 2) {
		try {
		    return (Math.abs(parseFloat(respVal) - checkResp[0]) <= 1.001*checkResp[1]); 
		} catch(err) {
		    Slidoc.log('Share.responseCallback: Error - invalid numeric response:'+respVal);
		    return null;
		}
	    } else {
		return null;
	    }
	}

	Slidoc.log('Slidoc.Plugins.Share.responseCallback2:', this.qattributes.vote, this.correctAnswer, checkResp);

	var codeResp = (this.qattributes.qtype == 'text/x-code'	|| this.qattributes.qtype.match(/^Code\//));
	var nResp = result[responseHeader].length;
	if (this.qattributes.qtype == 'number' || this.qattributes.qtype == 'choice') { 
	    // Count choice/numeric answers
	    this.responseTally = [];
	    var prevResp = null;
	    var respCount = 0;
	    var explanations = [];
	    var names = [];
	    for (var j=0; j<nResp; j++) {
		var respId = result['id'][j];
		var respVal = result[responseHeader][j];
		if (Slidoc.parseNumber(respVal) == null)
		    respVal = respVal.toUpperCase();
		if (respCount && respVal != prevResp) {
		    this.responseTally.push([prevResp, checkIfCorrect(prevResp), respCount, explanations, names]);
		    respCount = 0;
		    explanations = [];
		    names = [];
		}
		respCount += 1;
		names.push(responderMap[respId] || respId);
		if (result[explainHeader] && result[explainHeader][j])
		    explanations.push(''+result[explainHeader][j]);  // Convert to string
		prevResp = respVal;
	    }
	    if (respCount)
		this.responseTally.push([prevResp, checkIfCorrect(prevResp), respCount, explanations, names]);

	    Slidoc.log('Slidoc.Plugins.Share.responseCallback3:', this.responseTally.length, this.responseTally);
	    if (this.qattributes.qtype == 'number' && !this.qattributes.vote) {
		// No voting; display sorted numeric responses
		// (If voting, this display will be suppressed)
		var lines = ['Numeric responses:\n'];
		lines.push('<br><em class="slidoc-text-orange">Click on the bars to see explanations/ask follow-up questions</em>\n');
		lines.push('<p></p><ul>\n');
		for (var j=0; j<this.responseTally.length; j++) {
		    var percent = Math.round(100*this.responseTally[j][2]/nResp)+'%';
		    var label = this.responseTally[j][0] + ' ('+this.responseTally[j][2]+')';
		    var color = 'slidoc-bar-'+(this.responseTally[j][1] ? 'green' : 'orange')
		    lines.push( ('<li class="slidoc-numeric-chart"><span class="slidoc-chart-box %(id)s-chart-box"><span id="%(id)s-chartbar-%(index)s" class="%(id)s-chartbar slidoc-chart-bar '+color+'" onclick="Slidoc.PluginMethod('+"'Share', '%(id)s', 'shareExplain'"+', %(index)s);" style="width: %(percent)s;">'+label+'</span></span></li>\n').replace(/%\(id\)s/g,this.slideId).replace(/%\(index\)s/g,''+(j+1)).replace(/%\(percent\)s/g,percent) );
		}
		lines.push('</ul>\n');
		var popupContent = Slidoc.showPopup(lines.join('\n'), null, true);
		return;

	    } else if (this.qattributes.qtype == 'choice') {
		// Display choice responses inline (both for voting and non-voting cases)
		var chartHeader = document.getElementById(this.slideId+'-chart-header');
		if (chartHeader) {
		    chartHeader.innerHTML = '<em>Click on the bars to see explanations/ask follow-up questions</em>';
		    chartHeader.style.display = null;
		}

		var boxes = document.getElementsByClassName(this.slideId+'-chart-box');
		for (var j=0; j<boxes.length; j++)
		    boxes[j].style.display = null;

		var bars = document.getElementsByClassName(this.slideId+'-chartbar');
		for (var j=0; j<bars.length; j++) {
		    bars[j].textContent = '';
		    bars[j].style.width = '0%';
		}

		var choiceBlock = document.getElementById(this.slideId+'-choice-block');
		var shuffleStr = choiceBlock.dataset.shuffle;
		for (var j=0; j<this.responseTally.length; j++) {
		    var choice = this.responseTally[j][0].toUpperCase();
		    var dispChoice = choice;
		    if (shuffleStr) {
			var k = shuffleStr.indexOf(choice);
			dispChoice = (k>=1) ? String.fromCharCode('A'.charCodeAt(0) + k-1) : '';
		    }
		    var percent = Math.round(100*this.responseTally[j][2]/nResp)+'%';
		    var bar = document.getElementById(this.slideId+'-chartbar-'+choice);
		    if (bar) {
			bar.textContent = dispChoice+': '+this.responseTally[j][2];
			bar.style.width = percent;
			bar.classList.remove('slidoc-bar-orange');
			bar.classList.remove('slidoc-bar-green');
			bar.classList.add('slidoc-bar-'+(this.responseTally[j][1] ? 'green' : 'orange'));
		    }
		}
		if (!this.qattributes.vote)
		    return;
	    }
	} else if (!this.qattributes.vote) {
	    // Not choice/number question and not voting; display responses
	    var lines = [];
	    for (var j=0; j<nResp; j++) {
		lines.push([(codeResp ? '<pre class="slidoc-plugin-Share-resp"></pre>' : '<span class="slidoc-plugin-Share-resp"></span>'), ''+result[responseHeader][j]]); // Convert to string
	    }
	    Slidoc.showPopupWithList('Responses &nbsp;<a class="slidoc-clickable" onclick="Slidoc.shareCloud();">&#x2601;</a>:<p></p>\n', lines, !codeResp);
	    return;
	}

	// Voting
	var lines = [];

	if (retStatus.info && retStatus.info.voteDate) {
	    var voteDate = retStatus.info.voteDate;
	    try { voteDate = new Date(voteDate); } catch(err) {  }
	    lines.push('Submit Likes by: '+voteDate+'<p></p>')
	}
	lines.push(result[explainHeader] ? 'Explanations:<br>' : 'Responses:<br>');
	this.voteCodes = retStatus.info.vote ? retStatus.info.vote.split(',') : ['', ''];

	var ulistCorr = [];
	var ulistOther = [];
	for (var j=0; j<nResp; j++) {
	    var respVal = result[responseHeader][j];
	    var isCorrect = checkIfCorrect(respVal);
	    var correctResp = isCorrect ? '1' : '0';
	    var line = '';

	    // Column 1: upvote button
	    var voteCode = result[prefix+'share'][j];
	    if (voteCode)
		line += '<a href="javascript:void(0);" data-correct-resp="'+correctResp+'" class="slidoc-plugin-Share-votebutton slidoc-plugin-Share-votebutton-'+voteCode+'" onclick="Slidoc.Plugins.'+this.name+"['"+this.slideId+"'].upVote('"+voteCode+"', this)"+';">&#x1f44d</a> &nbsp;'
	    else
		line += '<a href="javascript:void(0);" class="slidoc-plugin-Share-votebutton-disabled">&#x1f44d</a> &nbsp;'

	    // Column 2: vote count
	    if (result[prefix+'vote'] && result[prefix+'vote'][j] !== null)
		line += '[<code class="slidoc-plugin-Share-vote">'+(1000+parseInt(result[prefix+'vote'][j])).toString().slice(-3)+'</code>]&nbsp;';
	    else
		line += '<code></code>';

	    // Column 3 (fill in with response/explanation)
	    line += '<code class="slidoc-plugin-Share-prefix'+(isCorrect ? '-correct' : '')+'"></code>';
	    var prefixVal = '';
	    var suffixVal = ''+respVal; // Convert to string
	    if (result[explainHeader] || checkResp.length) {
		line += ': ';
		prefixVal = ''+respVal; // Convert to string
		suffixVal = result[explainHeader] ? ''+result[explainHeader][j] : '';
	    }

	    // Column 4 (fill in with response/explanation)
	    line += codeResp ? '<pre class="slidoc-plugin-Share-resp"></pre>' : '<span class="slidoc-plugin-Share-resp"></span>'

            // Columns 1, 2, 3, 4
	    var comp = [line, null, null, prefixVal, suffixVal];
	    if (isCorrect)
		ulistCorr.push(comp);
	    else
		ulistOther.push(comp);
	}

	Slidoc.showPopupWithList(lines.join('\n'), ulistCorr.concat(ulistOther), !codeResp || result[explainHeader]);

	for (var k=0; k<this.voteCodes.length; k++) {
	    if (!this.voteCodes[k])
		continue;
	    var elems = document.getElementsByClassName('slidoc-plugin-Share-votebutton-'+this.voteCodes[k]);
	    for (var j=0; j<elems.length; j++)
		elems[j].classList.add('slidoc-plugin-Share-votebutton-activated');
	}
    },

    shareExplain: function(val) {
	Slidoc.log('Slidoc.Plugins.Share.shareExplain:', val, this.responseTally);
	if (!this.responseTally )
	    return;
	var index = 0;
	if (this.qattributes.qtype == 'number') {
	    index = val;
	} else {
	    for (var j=0; j<this.responseTally.length; j++) {
		if (this.responseTally[j][0] == val) {
		    index = j+1;
		    break;
		}
	    }
	}
	Slidoc.log('Slidoc.Plugins.Share.shareExplain2:', index);
	if (!index || index > this.responseTally.length)
	    return;
	var respTally = this.responseTally[index-1];

	var wheelURL = '';
	if (respTally[4] && respTally[4].length) {
	    var titleStr = this.sessionName+', Q'+this.qattributes.qnumber+': response='+respTally[0];
	    var qwheel_link = 'https://mitotic.github.io/wheel/?session=' + encodeURIComponent(this.siteName+'_'+this.sessionName) + '&title=' + encodeURIComponent(titleStr);
	    var nameList = respTally[4].join(';');
	    if (respTally[4].length == 1)
		nameList += ';';
            var qwheel_new = qwheel_link + '&names=' + encodeURIComponent(nameList);
	    wheelURL = '<a class="slidoc-clickable" target="_blank" href="'+qwheel_new+'">&#x1F3B2;</a>&nbsp;\n';
	}

	var lines = [];
	for (var j=0; j<respTally[3].length; j++)
	    lines.push([ '<span class="slidoc-plugin-Share-resp"></span>', respTally[3][j] ]);
	Slidoc.showPopupWithList(wheelURL+'Explanations for answer '+respTally[0]+' &nbsp;<a class="slidoc-clickable" onclick="Slidoc.shareCloud();">&#x2601;</a>:<p></p>\n', lines, true);
    },

    upVote: function (voteCode, elem) {
	Slidoc.log('Slidoc.Plugins.Share.upVote:', voteCode);
	var prefix = 'q'+this.qattributes.qnumber+'_';
	if (!voteCode) {
	    alert('Nothing to vote for!');
	    return;
	}
	if (elem.dataset.correctResp == "1")
	    this.voteCodes = [this.voteCodes[0], voteCode];
	else
	    this.voteCodes = [voteCode, this.voteCodes[1]];

	var elems = document.getElementsByClassName('slidoc-plugin-Share-votebutton');
	for (var j=0; j<elems.length; j++) {
	    if (elems[j].dataset.correctResp == elem.dataset.correctResp)
		elems[j].classList.remove('slidoc-plugin-Share-votebutton-activated');
	}

	elem.classList.add('slidoc-plugin-Share-votebutton-clicked');
	var updates = {id: GService.gprofile.auth.id};
	updates[prefix+'vote'] = this.voteCodes.join(',');
	var gsheet = getSheet(this.sessionName);
	gsheet.updateRow(updates, {}, this.upVoteCallback.bind(this, voteCode));
    },

    upVoteCallback: function (voteCode, result, retStatus) {
	Slidoc.log('Slidoc.Plugins.Share.upVoteCallback:', voteCode, result, retStatus);
	if (!result)
	    return;
	var elems = document.getElementsByClassName('slidoc-plugin-Share-votebutton-'+voteCode);
	for (var j=0; j<elems.length; j++) {
	    elems[j].classList.remove('slidoc-plugin-Share-votebutton-clicked');
	    elems[j].classList.add('slidoc-plugin-Share-votebutton-activated');
	}
    }
};

/* HEAD:
   <style>
.slidoc-plugin-Share-responder {
    display: inline-block;
    padding: 0.25em 0.5em;
    border: 2px solid;
    text-align: center;
    background-color: #e3e3e3; /* very light gray */
}

.slidoc-plugin-Share-responder-valid { background-color: #ffcc00; }
.slidoc-plugin-Share-responder-invalid { background-color: red; }
.slidoc-plugin-Share-responder-repeat { background-color: orange; }

.slidoc-plugin-Share-list {
  list-style-type: none;
}
.slidoc-plugin-Share-prefix-correct {
  font-weight: bold;
  color: green;
}
.slidoc-plugin-Share-votebutton,
  .slidoc-plugin-Share-votebutton-disabled {
  color: #2980B9;
  opacity: 0.4;
}
.slidoc-plugin-Share-votebutton.slidoc-plugin-Share-votebutton-activated {
  opacity: 1.0;
}
.slidoc-plugin-Share-votebutton-clicked {
  background-color: red;
}
.slidoc-plugin-Share-votebutton-disabled {
  visibility: hidden;
}
pre.slidoc-plugin-Share-responders {
    -moz-tab-size:    4;
    -o-tab-size:      4;
    tab-size:         4;
    -moz-white-space: pre-wrap;
    -o-white-space:   pre-wrap;
    white-space:      pre-wrap;
    font-size: 90%;
}
   </style>
   BODY:
   <input type="button" id="%(pluginId)s-sharebutton" 
   class="slidoc-clickable slidoc-button slidoc-plugin-Share-button %(pluginId)s-sharebutton slidoc-shareable-hide slidoc-nolocked slidoc-noprint"
   value="View all responses"
   onclick="Slidoc.Plugins['%(pluginName)s']['%(pluginSlideId)s'].displayShare();"></input>
   <span id="%(pluginId)s-sharecount" class="slidoc-clickable slidoc-plugin-Share-count %(pluginId)s-sharecount slidoc-shareable-hide" onclick="Slidoc.Plugins['%(pluginName)s']['%(pluginSlideId)s'].showDetails();"></span>
   <div id="%(pluginId)s-sharedetails" class="slidoc-plugin-Share-details %(pluginId)s-sharedetails slidoc-shareable-hide">
     <input type="button" id="%(pluginId)s-sharefinalize" class="slidoc-clickable slidoc-button" value="Finalize"
     onclick="Slidoc.Plugins['%(pluginName)s']['%(pluginSlideId)s'].finalizeShare();"></input>
     <pre id="%(pluginId)s-shareresponders" class="slidoc-plugin-Share-responders %(pluginId)s-shareresponders"><pre>
   </div>
*/
