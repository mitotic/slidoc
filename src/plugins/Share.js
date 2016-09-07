Share = {
    // Simple share plugin

    init: function() {
	Slidoc.log('Slidoc.Plugins.Share.init:', this);
	this.shareElem = document.getElementById(this.pluginId+'-sharebutton');
	this.countElem = document.getElementById(this.pluginId+'-sharecount');
	this.detailsElem = document.getElementById(this.pluginId+'-sharedetails');
	this.respondersElem = document.getElementById(this.pluginId+'-shareresponders');
	var manage = (this.paced == 3 && (this.adminState || this.testUser));
	toggleClass(!manage, 'slidoc-shareable-hide', this.shareElem);
	toggleClass(!manage, 'slidoc-shareable-hide', this.countElem);
	toggleClass(!manage, 'slidoc-shareable-hide', this.detailsElem);
	this.countElem.textContent = manage ? '(?)' : '';
	this.respondersElem.textContent = '';
	if (manage)
	    this.detailsElem.style.display = 'none';
    },

    answerSave: function () {
	Slidoc.log('Slidoc.Plugins.Share.answerSave:', this.paced);
	if (this.paced == 3) {
	    Slidoc.sendEvent(2, 'Share.answerNotify.'+this.slideId, this.qattributes.qnumber);
	} else {
	    if (this.qattributes.share != 'after_submission' || !window.GService)
		return;
	    this.getResponses(true);
	    toggleClass(false, 'slidoc-shareable-hide', this.shareElem);
	}
    },

    answerNotify: function (qnumber) {
	Slidoc.log('Slidoc.Plugins.Share.answerNotify:');
	if (this.testUser) {
	    if (qnumber == this.qattributes.qnumber && !Slidoc.PluginManager.answered[this.qattributes.qnumber])
		this.getResponses(false);
	} else {
	    if (this.qattributes.share == 'after_submission')
		toggleClass(false, 'slidoc-shareable-hide', this.shareElem);
	}
    },

    showDetails: function () {
	Slidoc.log('Slidoc.Plugins.Share.showDetails:');
	if (this.detailsElem.style.display) {
	    this.detailsElem.style.display = null;
	    this.getResponses(false);
	} else {
	    this.detailsElem.style.display = 'none';
	}
    },

    finalizeShare: function () {
	Slidoc.log('Slidoc.Plugins.Share.finalizeShare:');
	if (this.paced == 3) {
	    if (this.testUser && !Slidoc.PluginManager.answered(this.qattributes.qnumber))
		Slidoc.sendEvent(-1, 'AdminPacedForceAnswer', this.qattributes.qnumber, this.slideId);
	}
	this.getResponses(true);
    },

    displayShare: function () {
	Slidoc.log('Slidoc.Plugins.Share.displayShare:');
	this.getResponses(true);
    },

    getResponses: function (display) {
	Slidoc.log('Slidoc.Plugins.Share.getResponses:', display);
	if (!this.qattributes.share)
	    return;
	this.nCols = 1;
	if (this.qattributes.explain)
	    this.nCols += 1;
	if (this.qattributes.share == 'vote')
	    this.nCols += 1;
	var colPrefix = 'q'+this.qattributes.qnumber;
	var gsheet = getSheet(Sliobj.sessionName);
	gsheet.getShare(colPrefix, this.adminState, this.responseCallback.bind(this, display));
    },

    responseCallback: function (display, result, retStatus) {
	Slidoc.log('Slidoc.Plugins.Share.responseCallback:', display, result, retStatus);
	if (!result || !retStatus)
	    return;
	var prefix = 'q'+this.qattributes.qnumber+'_';

	if (retStatus.info && retStatus.info.responders) {
	    this.countElem.textContent = '('+retStatus.info.responders.length+')';
	    this.respondersElem.textContent = retStatus.info.responders.join('\t');
	}
	    
	if (!display)
	    return;

	var lines = [];

	if (retStatus.info && retStatus.info.voteDate) {
	    var voteDate = retStatus.info.voteDate;
	    try { voteDate = new Date(voteDate); } catch(err) {  }
	    lines.push('Submit Likes by: '+voteDate+'<p></p>')
	}
	
	lines.push(result[prefix+'explain'] ? 'Explanations:<br>' : 'Responses:<br>');
	this.voteCodes = retStatus.info.vote ? retStatus.info.vote.split(',') : ['', ''];

	var checkResp = [];
	if (this.correctAnswer) {
	    if (this.qattributes.qtype == 'number') {
		var corrValue = null;
		var corrError = 0.0;
		try {
		    var comps = this.correctAnswer.split('+/-');
		    corrValue = parseFloat(comps[0]);
		    if (comps.length > 1)
			corrError = parseFloat(comps[1]);
		    if (!isNaN(corrValue) && !isNaN(corrError))
			checkResp = [corrValue, corrError];
		} catch(err) {Slidoc.log('Share.responseCallback: Error in correct numeric answer:'+this.correctAnswer);}
	    } else if (this.correctAnswer.length == 1) {
		checkResp = [this.correctAnswer];
	    }
	}

	Slidoc.log('Slidoc.Plugins.Share.responseCallback2:', this.correctAnswer, checkResp);
	var ulistCorr = [];
	var ulistOther = [];
	for (var j=0; j<result[prefix+'response'].length; j++) {
	    var respVal = result[prefix+'response'][j];
	    var isCorrect = false;
	    if (checkResp.length == 1) {
		isCorrect = (checkResp[0] == respVal);
	    } else if (checkResp.length == 2) {
		try {
		    isCorrect = (Math.abs(parseFloat(respVal) - checkResp[0]) <= 1.001*checkResp[1]); 
		} catch(err) {Slidoc.log('Share.responseCallback: Error - invalid numeric response:'+respVal);}
	    }
	    var correctResp = isCorrect ? '1' : '0';
	    var line = '<li class="slidoc-plugin-Share-li">';
	    if (result[prefix+'share']) {
		var voteCode = result[prefix+'share'][j];
		if (voteCode)
		    line += '<a href="javascript:void(0);" data-correct-resp="'+correctResp+'" class="slidoc-plugin-Share-votebutton slidoc-plugin-Share-votebutton-'+voteCode+'" onclick="Slidoc.Plugins.'+this.name+"['"+this.slideId+"'].upVote('"+voteCode+"', this)"+';">&#x1f44d</a> &nbsp;'
		else
		    line += '<a href="javascript:void(0);" class="slidoc-plugin-Share-votebutton-disabled">&#x1f44d</a> &nbsp;'
	    } else {
		line += '<span></span>';
	    }
	    if (result[prefix+'vote'] && result[prefix+'vote'][j] !== null)
		line += '[<code class="slidoc-plugin-Share-vote">'+(1000+parseInt(result[prefix+'vote'][j])).toString().slice(-3)+'</code>]&nbsp;';
	    else
		line += '<code></code>';

	    line += '<code class="slidoc-plugin-Share-prefix'+(isCorrect ? '-correct' : '')+'"></code>';
	    var prefixVal = '';
	    var suffixVal = respVal;
	    if (result[prefix+'explain'] || checkResp.length) {
		line += ': ';
		prefixVal = respVal;
		suffixVal = result[prefix+'explain'] ? result[prefix+'explain'][j] : '';
	    }
	    line += (this.qattributes.qtype == 'text/x-code') ? '<pre class="slidoc-plugin-Share-resp"></pre>' : '<span class="slidoc-plugin-Share-resp"></span>'
	    line += '</li>';
	    if (isCorrect)
		ulistCorr.push([line, prefixVal, suffixVal]);
	    else
		ulistOther.push([line, prefixVal, suffixVal]);
	}

	var ulistAll = ulistCorr.concat(ulistOther);
	lines.push('<ul class="slidoc-plugin-Share-list">');
	for (var j=0; j<ulistAll.length; j++)
	    lines.push(ulistAll[j][0]);
	lines.push('</ul>');

	var popupContent = Slidoc.showPopup(lines.join('\n'), null, true);
	var listNodes = popupContent.lastElementChild.children;
	for (var j=0; j<ulistAll.length; j++) {
	    var childNodes = listNodes[j].children;
	     // answer in code element
	    childNodes[2].textContent = ulistAll[j][1];

	    // response/explanation in pre/span element
	    if (this.qattributes.explain == 'markdown' && window.MDConverter) 
		childNodes[3].innerHTML = MDConverter(ulistAll[j][2], true); 
	    else
		childNodes[3].textContent = ulistAll[j][2];
	}
	if (this.qattributes.explain == 'markdown' && window.MathJax)
	    MathJax.Hub.Queue(["Typeset", MathJax.Hub, popupContent.id]);

	for (var k=0; k<this.voteCodes.length; k++) {
	    if (!this.voteCodes[k])
		continue;
	    var elems = document.getElementsByClassName('slidoc-plugin-Share-votebutton-'+this.voteCodes[k]);
	    for (var j=0; j<elems.length; j++)
		elems[j].classList.add('slidoc-plugin-Share-votebutton-activated');
	}
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
	var gsheet = getSheet(Sliobj.sessionName);
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

/* PluginHead:
   <style>
.slidoc-plugin-Share-list {
  list-style-type: none;
}
.slidoc-plugin-Share-prefix-correct {
  font-weight: bold;
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
}
   </style>
   PluginBody:
   <input type="button" id="%(pluginId)s-sharebutton" 
   class="slidoc-clickable slidoc-button slidoc-plugin-Share-button %(pluginId)s-sharebutton slidoc-shareable-hide"
   value="View all responses"
   onclick="Slidoc.Plugins['%(pluginName)s']['%(pluginSlideId)s'].displayShare();"></input>
   <span id="%(pluginId)s-sharecount" class="slidoc-clickable slidoc-plugin-Share-count %(pluginId)s-sharecount slidoc-shareable-hide" onclick="Slidoc.Plugins['%(pluginName)s']['%(pluginSlideId)s'].showDetails();"></span>
   <div id="%(pluginId)s-sharedetails" class="slidoc-plugin-Share-details %(pluginId)s-sharedetails slidoc-shareable-hide">
     <input type="button" id="%(pluginId)s-sharefinalize" class="slidoc-clickable slidoc-button" value="Finalize"
     onclick="Slidoc.Plugins['%(pluginName)s']['%(pluginSlideId)s'].finalizeShare();"></input>
     <pre id="%(pluginId)s-shareresponders" class="slidoc-plugin-Share-responders %(pluginId)s-shareresponders"><pre>
   </div>
*/
