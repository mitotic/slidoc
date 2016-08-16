Share = {
    // Simple share plugin

    init: function() {
	Slidoc.log('Slidoc.Plugins.Share.init:', this);
	this.votebutton = document.getElementById(this.pluginId+'-votebutton');
	this.votebutton.style.display = null;
    },

    answerSave: function () {
	Slidoc.log('Slidoc.Plugins.Share.answerSave:');
	if (this.qattributes.share != 'after_submission' || !window.GService)
	    return;
	this.getResponses();
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
	gsheet.getCols(colPrefix, this.responseCallback.bind(this));
    },

    responseCallback: function (result, retStatus) {
	Slidoc.log('Slidoc.Plugins.Share.responseCallback:', result, retStatus);
	if (!result || !retStatus)
	    return;
	var prefix = 'q'+this.qattributes.qnumber+'_';
	var nRows = result[prefix+'response'].length;
	var lines = ['Responses:<br><ul class="slidoc-plugin-share-list">'];
	var myVote = retStatus.info.vote || '';
	for (var j=0; j<nRows; j++) {
	    var line = '<li>';
	    if (result[prefix+'share']) {
		var voteCode = result[prefix+'share'][j];
		if (voteCode)
		    line += '<a href="javascript:void(0);" class="slidoc-plugin-share-votebutton slidoc-plugin-share-votebutton-'+voteCode+'" onclick="Slidoc.Plugins.'+this.name+"['"+this.slideId+"'].upVote('"+voteCode+"', this)"+';">&#x1f44d</a> &nbsp;'
		else
		    line += '<a href="javascript:void(0);" class="slidoc-plugin-share-votebutton-disabled">&#x1f44d</a> &nbsp;'
	    }
	    if (result[prefix+'vote'] && result[prefix+'vote'][j] !== null)
		line += '[<code>'+(1000+parseInt(result[prefix+'vote'][j])).toString().slice(-3)+'</code>]&nbsp;';
	    if (result[prefix+'explain'])
		line += '<code>'+result[prefix+'response'][j]+'</code>: ' + result[prefix+'explain'][j];
	    else
		line += result[prefix+'response'][j];
	    line += '</li>';
	    lines.push(line);
	}
	lines.push('</ul>');
	Slidoc.showPopup(lines.join('\n'), null, true);
	if (myVote) {
	    var elems = document.getElementsByClassName('slidoc-plugin-share-votebutton-'+myVote);
	    for (var j=0; j<elems.length; j++)
		elems[j].classList.add('slidoc-plugin-share-votebutton-activated');
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
	var elems = document.getElementsByClassName('slidoc-plugin-share-votebutton');
	for (var j=0; j<elems.length; j++)
	    elems[j].classList.remove('slidoc-plugin-share-votebutton-activated');

	if (elem)
	    elem.classList.add('slidoc-plugin-share-votebutton-clicked');
	var updates = {id: GService.gprofile.auth.id};
	updates[prefix+'vote'] = voteCode;
	var gsheet = getSheet(Sliobj.sessionName);
	gsheet.updateRow(updates, {}, this.upVoteCallback.bind(this, voteCode));
    },

    upVoteCallback: function (voteCode, result, retStatus) {
	Slidoc.log('Slidoc.Plugins.Share.upVoteCallback:', voteCode, result, retStatus);
	if (!result)
	    return;
	var elems = document.getElementsByClassName('slidoc-plugin-share-votebutton-'+voteCode);
	for (var j=0; j<elems.length; j++) {
	    elems[j].classList.remove('slidoc-plugin-share-votebutton-clicked');
	    elems[j].classList.add('slidoc-plugin-share-votebutton-activated');
	}
    }
};

/* PluginHead:
   <style>
.slidoc-plugin-share-list {
  list-style-type: none;
}
.slidoc-plugin-share-votebutton,
  .slidoc-plugin-share-votebutton-disabled {
  color: #2980B9;
  opacity: 0.4;
}
.slidoc-plugin-share-votebutton.slidoc-plugin-share-votebutton-activated {
  opacity: 1.0;
}
.slidoc-plugin-share-votebutton-clicked {
  background-color: red;
}
.slidoc-plugin-share-votebutton-disabled {
  visibility: hidden;
}
   </style>
   PluginBody:
   <input type="button" id="%(pluginId)s-sharebutton"  class="slidoc-plugin-share-button" value="Share"
   onclick="Slidoc.Plugins['%(pluginName)s']['%(pluginSlideId)s'].displayShare(this);"></input>
   <br>
   <input type="button" id="%(pluginId)s-votebutton"  class="slidoc-plugin-share-button" value="Vote"
   onclick="Slidoc.Plugins['%(pluginName)s']['%(pluginSlideId)s'].upVote(this);" style="display: none;"></input>
*/
