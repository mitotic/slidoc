Share = {
    // Simple share plugin

    init: function() {
	Slidoc.log('Slidoc.Plugins.Share.init:', this);
	this.shareElem = document.getElementById(this.pluginId+'-sharebutton');
	if (this.adminState)
	    toggleClass(false, 'slidoc-shareable-hide', this.shareElem);
    },

    answerSave: function () {
	Slidoc.log('Slidoc.Plugins.Share.answerSave:');
	if (this.qattributes.share != 'after_submission' || !window.GService)
	    return;
	this.getResponses();
	toggleClass(false, 'slidoc-shareable-hide', this.shareElem);
    },

    getResponses: function () {
	Slidoc.log('Slidoc.Plugins.Share.getResponses:');
	if (!this.qattributes.share)
	    return;
	this.nCols = 1;
	if (this.qattributes.explain)
	    this.nCols += 1;
	if (this.qattributes.share == 'vote')
	    this.nCols += 1;
	var colPrefix = 'q'+this.qattributes.qnumber;
	var gsheet = getSheet(Sliobj.sessionName);
	gsheet.getShare(colPrefix, this.adminState, this.responseCallback.bind(this));
    },

    responseCallback: function (result, retStatus) {
	Slidoc.log('Slidoc.Plugins.Share.responseCallback:', result, retStatus);
	if (!result || !retStatus)
	    return;
	var prefix = 'q'+this.qattributes.qnumber+'_';
	var nRows = result[prefix+'response'].length;
	var lines = [];

	if (retStatus.info && retStatus.info.voteDate) {
	    var voteDate = retStatus.info.voteDate;
	    try { voteDate = new Date(voteDate); } catch(err) {  }
	    lines.push('Submit Likes by: '+voteDate+'<p></p>')
	}
	
	lines.push(result[prefix+'explain'] ? 'Explanations:<br>' : 'Responses:<br>');
	this.voteCodes = retStatus.info.vote ? retStatus.info.vote.split(',') : ['', ''];

	var checkResp = [];
	if (result[prefix+'explain'] && this.qattributes.correct) {
	    if (this.qattributes.qtype == 'number') {
		var corrValue = null;
		var corrError = 0.0;
		try {
		    var comps = this.qattributes.correct.split('+/-');
		    corrValue = parseFloat(comps[0]);
		    if (comps.length > 1)
			corrError = parseFloat(comps[1]);
		    if (!isNaN(corrValue) && !isNaN(corrError))
			checkResp = [corrValue, corrError];
		} catch(err) {Slidoc.log('Share.responseCallback: Error in correct numeric answer:'+this.qattributes.correct);}
	    } else if (this.qattributes.correct.length == 1) {
		checkResp = [this.qattributes.correct];
	    }
	}

	Slidoc.log('Slidoc.Plugins.Share.responseCallback2:', checkResp);
	var ulistCorr = [];
	var ulistOther = [];
	for (var j=0; j<nRows; j++) {
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
	    if (result[prefix+'explain']) {
		line += ': ';
		prefixVal = respVal;
		suffixVal = result[prefix+'explain'][j];
	    }
	    line += '<span class="slidoc-plugin-Share-resp"></span>'
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

	    // response/explanation in span element
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

    displayShare: function () {
	Slidoc.log('Slidoc.Plugins.Share.displayShare:');
	this.getResponses();
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
   </style>
   PluginBody:
   <input type="button" id="%(pluginId)s-sharebutton" 
   class="slidoc-clickable slidoc-button slidoc-plugin-Share-button %(pluginId)s-sharebutton slidoc-shareable-hide"
   value="View all responses"
   onclick="Slidoc.Plugins['%(pluginName)s']['%(pluginSlideId)s'].displayShare(this);"></input>
*/
