Discuss = {
    // Discuss plugin
    global: {
	initGlobal: function(discussParams) {
	    Slidoc.log('Slidoc.Plugins.Discuss.initGlobal:', discussParams);
	    this.discussParams = discussParams;
	    if (!window.GService)
		return;
	    this.discussSheet = new GService.GoogleSheet(this.discussParams.gd_sheet_url, this.sessionName+'_discuss',
							 [], [], false);
	    this.topElem = document.getElementById('slidoc-discuss-display');
	},

	unread: function() {
	    if (!this.discussParams.stats)
		return 0;
	    var sessionStats = this.discussParams.stats.sessions[this.sessionName] || {};
	    var discussNums = Object.keys(sessionStats);
	    var count = 0;
	    for (var j=0; j<discussNums.length; j++) {
		var teamNames = Object.keys(sessionStats[discussNums[j]]);
		for (var k=0; k<teamNames.length; k++) {
		    if (sessionStats[discussNums[j]][teamNames[k]][1])
			count += 1;
		}
	    }
	    return count;
	},

	relayCall: function(isAdmin, fromUser, methodName) // Extra args
	{
	    var extraArgs = Array.prototype.slice.call(arguments).slice(3);
	    Slidoc.log('Slidoc.Plugins.Discuss.relayCall:', isAdmin, fromUser, methodName, extraArgs);

	    if (methodName == 'postNotify' && isAdmin)
		return this[methodName].apply(this, [fromUser].concat(extraArgs));

	    throw('Discuss.js: Denied access to relay method '+methodName);
	},

	parsePost: function(post) {
	    var POST_PREFIX_RE = /^Post:([\w-]*)\|(\d+)\|([,\w-]*)\|([-\d:T]+)([\s\S]*)$/;
	    var pmatch = post.match(POST_PREFIX_RE);
	    if (!pmatch)
		return null;
	    var state = {};
	    var scomps = pmatch[3].split(',');
	    for (var j=0; j<scomps.length; j++)
		state[scomps[j]] = 1;
	    var comps = {team: pmatch[1], number: parseInt(pmatch[2]), state: state, date: pmatch[4], text: pmatch[5].trim()};
	    return comps;
	},

	postNotify: function(userId, discussNum, closed, postMsg, userName, teamName, newPost) {
	    Slidoc.log('Slidoc.Plugins.Discuss.postNotify:', userId, discussNum, closed, postMsg, userName, teamName, newPost);
	    if (!discussNum)
		return;
	    var slideNum = this.discussParams.discussSlides[discussNum-1].slide;
	    var slidePlugin = Slidoc.Plugins[this.name][Slidoc.makeSlideId(slideNum)];
	    if (!slidePlugin)
		return;
	    if (newPost) {
		var postComps = this.parsePost(newPost);
		if (postComps) {
		    slidePlugin.unreadPost = true;
		    slidePlugin.activeUsers[userId] = new Date();
		    if (this.topElem && slideNum != Slidoc.PluginManager.getCurrentSlide())
			this.topElem.classList.add('slidoc-plugin-Discuss-unread');

		    var teamName = postComps.team; // Redundant, since teamName is also an argument
		    var row = [teamName, postComps.number, postComps.state, userId, userName, postComps.date, true, postComps.text];
		    var postElem = slidePlugin.displayPost(row);
		    if (postElem) {
			Slidoc.renderMath(postElem);
			if (slidePlugin.textareaElem && slidePlugin.textareaElem.value) {
			    window.scrollTo(0,document.body.scrollHeight);
			    setTimeout(function(){window.scrollTo(0,document.body.scrollHeight);}, 10);
			}
		    }
		}
	    }
	    slidePlugin.setClosedState(!closed);
	    if (!closed && slidePlugin.footerElem)
		slidePlugin.footerElem.style.display = null;
	    if ((postMsg == 'new' || postMsg == 'teamgen') && slidePlugin.containerElem.style.display) {
		// Discussion not open; notify availability
		if (slidePlugin.showElem)
		    slidePlugin.showElem.classList.add('slidoc-plugin-Discuss-unread');
		if (slidePlugin.toggleElem)
		    slidePlugin.toggleElem.classList.add('slidoc-plugin-Discuss-unread');
	    }
	}
    },

    init: function() {
	Slidoc.log('Slidoc.Plugins.Discuss.init:', this.global);
	if (!window.GService || !this.global.discussParams.stats || !this.global.discussParams.stats.sessions)
	    return;
	var sessionStats = this.global.discussParams.stats.sessions[this.sessionName] || {};
	this.discussNum = 0;
	this.discussSlideParams = {};
	for (var j=0; j<this.global.discussParams.discussSlides.length; j++) {
	    if (this.global.discussParams.discussSlides[j].slide == this.slideNumber) {
		this.discussNum = j+1;
		this.discussSlideParams = this.global.discussParams.discussSlides[j];
		break;
	    }
	}
	if (!this.discussNum)
	    return;

	this.adminUser = (this.userId == Slidoc.testUserId);
	this.unreadPost = false;
	this.activeUsers = {};
	
	if (this.discussNum in sessionStats) {
	    var discussStats = sessionStats[this.discussNum];
	} else {
	    discussStats = {};
	}

	this.closedFlag = false;

	this.containerElem = document.getElementById(this.pluginId+'-container');
	this.postContainerElem = document.getElementById(this.pluginId+'-post-container');
	this.selectElem = document.getElementById(this.pluginId+'-select-post-team');
	this.labelElem  = document.getElementById(this.pluginId+'-label');
	this.closeElem  = document.getElementById(this.pluginId+'-close');
	this.postsElem  = document.getElementById(this.pluginId+'-posts');
	this.showElem   = document.getElementById(this.pluginId+'-show');
	this.footerElem = document.getElementById(this.pluginId+'-footer');
	this.countElem  = document.getElementById(this.pluginId+'-count');
	this.textareaElem = document.getElementById(this.pluginId+'-textarea');
	this.renderElem = document.getElementById(this.pluginId+'-render');

	if (this.discussSlideParams.maxchars)
	    this.textareaElem.setAttribute('maxlength', this.discussSlideParams.maxchars);

	if (this.adminUser)
	    this.closeElem.style.display = null;

	this.toggleElem = document.getElementById(this.slideId+'-toptoggle-discuss');

	var nPosts = 0;
	var nUnread = 0;
	if (discussStats.teams) {
	    var teamNames = Object.keys(discussStats.teams);
	    teamNames.sort();
	    for (var iteam=0; iteam<teamNames.length; iteam++) {
		var teamName = teamNames[iteam];
		var teamStats = discussStats.teams[teamName];
		nPosts += teamStats[0];
		nUnread += teamStats[1];
	    }
	}

	this.postsElem.innerHTML = '';

	var hideDiscuss = this.paced == Slidoc.PluginManager.ADMIN_PACE && !this.adminUser && !nPosts && (!('closed' in discussStats) || discussStats.closed);
	if (this.footerElem)
	    this.footerElem.style.display = hideDiscuss ? 'none' : null;
	if (this.showElem && nUnread)
	    this.showElem.classList.add('slidoc-plugin-Discuss-unread');
	if (this.countElem && nPosts)
	    this.countElem.textContent = nUnread ? nPosts+' posts ('+nUnread+' unread)' : nPosts+' posts';
	if (this.toggleElem)
	    this.toggleElem.style.display = null;

	if (nPosts) {
	    if (this.toggleElem)
		this.toggleElem.classList.add('slidoc-plugin-Discuss-available');
	    if (nUnread) {
		this.unreadPost = true;
		this.toggleElem.classList.add('slidoc-plugin-Discuss-unread');
		if (this.global.topElem)
		    this.global.topElem.classList.add('slidoc-plugin-Discuss-unread');
	    }
	}

	if (!Slidoc.PluginManager.previewStatus() && this.global.discussParams.discussSlides[this.discussNum-1].gdoc)
	    setTimeout(this.slideDiscuss.bind(this, 'show'), 300);
    },

    relayCall: function(isAdmin, fromUser, methodName) // Extra args
    {
	var extraArgs = Array.prototype.slice.call(arguments).slice(3);
	Slidoc.log('Slidoc.Plugins.Discuss.relayCall.slide:', isAdmin, fromUser, methodName, extraArgs);

	if (methodName == 'activeNotify')
	    return this[methodName].apply(this, [fromUser].concat(extraArgs));

	throw('Discuss.js: Denied access to relay method '+methodName);
	},

    enterSlide: function(paceStart, backward){
	console.log('Slidoc.Plugins.Discuss.enterSlide:', paceStart, backward, this.unreadPost);
	if (this.global.topElem && this.unreadPost)
	    this.global.topElem.classList.remove('slidoc-plugin-Discuss-unread');
	this.unreadPost = false;
	return 0;
    },

    slideDiscuss: function(action) {
	// action: 'show' or 'preview' or 'post'
	Slidoc.log('Slidoc.Plugins.Discuss.slideDiscuss:', action);
	if (this.discussNum <= 0)
	    return false;

	if (action == 'show') {
	    this.global.discussSheet.actions('discuss_posts', {id: this.userId, sheet:this.sessionName, discuss: this.discussNum}, this.showCallback.bind(this));
	} else {
	    var colName = 'discuss' + Slidoc.zeroPad(this.discussNum, 3);
	    var textValue = this.textareaElem.value;
	    if (action == 'preview') {
		this.renderElem.innerHTML = Slidoc.MDConverter(textValue, true);
		Slidoc.renderMath(this.renderElem);
	    } else if (action == 'post') {
		if (!textValue.trim()) {
		    alert('No text to post!');
		    return;
		}
		var updates = {id: this.userId};
		updates[colName] = textValue;
		var params = {};
		if (this.selectElem.options && this.selectElem.options.length) {
		    var teamName = this.selectElem.options[this.selectElem.selectedIndex].value;
		    if (!teamName) {
			alert('Please select team to post to');
			return
		    }
		    params['team'] = teamName;
		}
		this.global.discussSheet.updateRow(updates, params, this.updateCallback.bind(this));
	    }
	}
    },

    deletePost: function(postNum, userTeam, userId) {
	Slidoc.log('Slidoc.Plugins.Discuss.deletePost:', postNum, userTeam, userId);
	if (this.discussNum <= 0)
	    return false;
	if (!window.confirm('Delete discussion post?'))
	    return false;
	var colName = 'discuss' + Slidoc.zeroPad(this.discussNum, 3);
	var updates = {id: userId};
	var postTeam = userTeam || '';
	updates[colName] = 'delete:' + postTeam + ':' + Slidoc.zeroPad(postNum, 3);
	var opts = {};
	if (userId != this.userId)
	    opts.admin = 1;
	this.global.discussSheet.updateRow(updates, opts, this.updateCallback.bind(this));
    },

    updateCallback: function(result, retStatus) {
	Slidoc.log('Slidoc.Plugins.Discuss.updateCallback:', result, retStatus);
	if (!result) {
	    alert('Error in discussion post: '+(retStatus?retStatus.error:''));
	    return;
	}
	this.displayDiscussion(retStatus.info.discussPosts, true);
	this.textareaElem.value = '';
	this.renderElem.innerHTML = '';
    },

    flagPost: function(postNum, userTeam, userId, unflag) {
	Slidoc.log('Slidoc.Plugins.Discuss.flagPost:', postNum, userTeam, userId, unflag);
	if (this.discussNum <= 0)
	    return false;
	if (!window.confirm(unflag ? 'Flag discussion post for offensive content?' : 'Unflag post?'))
	    return false;
	if (!unflag) {
	    if (!window.confirm('You should only flag posts for offensive content, not simply because you disagree with it. If you flag this post, it will be no longer be visible and the instructor will be informed of your action. Do you wish to proceed?'))
		return false;
	}
	var params = {session: this.sessionName, discussion: this.discussNum, team: userTeam||'', post:postNum,
		      posterid: userId};
	if (unflag)
	    params.unflag = 1;
	Slidoc.ajaxRequest('GET', Slidoc.PluginManager.sitePrefix + '/_user_flag', params, this.flagPostCallback.bind(this), true);
    },

    flagPostCallback: function(retObj, errMsg) {
	Slidoc.log('Slidoc.Plugins.Discuss.flagPostCallback:', retObj, errMsg);
	if (!retObj || retObj.result != 'success') {
	    alert('Error in flag/unflag post: '+(retObj?retObj.error:'')+'; '+errMsg);
	    return;
	}
	this.displayDiscussion(retObj.discussPosts, true);
    },

    closeDiscussion: function() {
	Slidoc.log('Slidoc.Plugins.Discuss.closeDiscussion:');
	if (this.discussNum <= 0)
	    return false;
	if (!window.confirm((this.closedFlag?'Re-open':'Close')+' discussion?'))
	    return false;
	var params = {session: this.sessionName, discussion: this.discussNum};
	if (this.closedFlag)
	    params.reopen = 1;
	Slidoc.ajaxRequest('GET', Slidoc.PluginManager.sitePrefix + '/_user_discussclose', params, this.closeDiscussionCallback.bind(this, this.closedFlag), true);
    },

    closeDiscussionCallback: function(reopen, retObj, errMsg) {
	Slidoc.log('Slidoc.Plugins.Discuss.closeDiscussionCallback:', reopen, retObj, errMsg);
	if (!retObj || retObj.result != 'success') {
	    alert('Error in closing discussion: '+(retObj?retObj.error:'')+'; '+errMsg);
	    return;
	}
    },

    setClosedState: function(opened) {
	this.closedFlag = !opened;
	this.closeElem.textContent = this.closedFlag ? 'Open discussion' : 'Close discussion';
	this.postContainerElem.style.display = this.closedFlag ? 'none' : null;
    },

    showCallback: function(result, retStatus) {
	Slidoc.log('Slidoc.Plugins.Discuss.showCallback:', result, retStatus);
	if (!result) {
	    alert('Error in discussion show: '+(retStatus?retStatus.error:''));
	    return;
	}
	var postInfo = result;
	this.displayDiscussion(postInfo);
	if (this.countElem)
	    this.countElem.textContent = postInfo[2].length ? postInfo[2].length+' posts' : '';
    },

    displayPost: function(row) {
	// row = [userTeam, postNum, postState, userId, userName, postTime, unreadFlag, postText]
	// Return html and also set this.unreadId
	var userTeam   = row[0];
	var postNum    = row[1];
	var postState  = row[2];
	var userId     = row[3];
	var userName   = row[4];
	var postTime   = row[5];
	var unreadPost = row[6];
	var postText   = row[7];

	var postId = this.slideId+'-'+userTeam+'post'+Slidoc.zeroPad(postNum,3);
	var postName = (userId == Slidoc.testUserId) ? 'Instructor' : Slidoc.makeShortFirst(userName);
	var postDate = new Date(postTime);
	if (!postDate) {
	    var timestamp = postDate;
	} else {
	    var opts = {month: 'short', day: 'numeric', hour:'numeric', minute:'numeric' };
	    if (postDate.getFullYear() != (new Date()).getFullYear() )
		opts.year = 'numeric';
	    timestamp = postDate.toLocaleString(navigator.language, opts);
	}
        var highlight = '*';
	if (unreadPost) {
	    // Unread
	    highlight = '**';
	    if (!this.unreadId)
		this.unreadId = postId;
	}
	var html = Slidoc.MDConverter(highlight+postName+highlight+': '+postText, true); // user name
	html = html.replace(/ ([\w.+-]+@[\w.-]+\b)/g, ' <a href="mailto:$1" target="_blank">$1</a>');

	html += '<br><em class="slidoc-plugin-Discuss-post-timestamp">'+timestamp+'</em>';  // Time

	var flagged = postState.flagged;
	if (!postState.deleted) {
	    if (this.adminUser || (!flagged && this.userId == userId))
		html += ' <span class="slidoc-clickable slidoc-plugin-Discuss-post-delete" onclick="Slidoc.Plugins['+"'"+this.name+"']['"+this.slideId+"'"+'].deletePost('+postNum+",'"+userTeam+"','"+userId+"'"+');">&#x1F5D1;</span>';

	    if (!flagged && !this.adminUser && userId != this.userId && userId != Slidoc.testUserId)
		html += ' <span class="slidoc-clickable slidoc-plugin-Discuss-post-flag" onclick="Slidoc.Plugins['+"'"+this.name+"']['"+this.slideId+"'"+'].flagPost('+postNum+",'"+userTeam+"','"+userId+"'"+');">&#9872;</span>';

	    if (flagged && this.adminUser)
		html += ' <span class="slidoc-clickable slidoc-plugin-Discuss-post-unflag" onclick="Slidoc.Plugins['+"'"+this.name+"']['"+this.slideId+"'"+'].flagPost('+postNum+",'"+userTeam+"','"+userId+"'"+', true);">&#9873;</span>';
	}

	var elem = document.createElement('p');
	elem.id = postId;
	elem.innerHTML = html;

	this.postTeamElem = document.getElementById(this.pluginId+'-posts-team' + userTeam)
	if (this.postTeamElem)
	    this.postTeamElem.appendChild(elem);
	this.labelElem.innerHTML = '';
	return elem;
    },

    activeNotify: function(fromUser, action, discussNum) {
	Slidoc.log('Discuss.activeNotify:', fromUser, action, discussNum);
	if (action === 'displayDiscussion') {
	    // Note that action is set to 'activeNotify' to prevent looping
	    Slidoc.sendEvent(fromUser, -1, 'Discuss.activeNotify.'+this.slideNumber, 'activeNotify', this.discussNum);
	    this.activeUsers[fromUser] = new Date();
	}
    },

    displayDiscussion: function(postInfo, update) {
	if (!update && !this.containerElem.style.display) {
	    // Collapse display
	    this.containerElem.style.display = 'none';
	    return;
	}
	this.closedFlag = postInfo[0];
	var teamNames = postInfo[1];
	var posts = postInfo[2];
	if (!update) // If update, postNotify has been sent
	    Slidoc.sendEvent('', -1, 'Discuss.activeNotify.'+this.slideNumber, 'displayDiscussion', this.discussNum);

	this.closeElem.textContent = this.closedFlag ? 'Open discussion' : 'Close discussion';
	this.postContainerElem.style.display = this.closedFlag ? 'none' : null;

	this.unreadId = '';
	if (this.postsElem) {
	    this.postsElem.innerHTML = '';
	    if (teamNames.length < 2) {
		this.selectElem.style.display = 'none';
		this.selectElem.innerHTML = '';
	    } else {
		this.selectElem.style.display = null;
		this.selectElem.innerHTML = '<option value="">Select team:</option>';
	    }
	    for (var iteam=0; iteam<teamNames.length; iteam++) {
		var teamName = teamNames[iteam];
		var divElem = document.createElement('div');
		divElem.id = this.pluginId+'-posts-team' + teamName;
		if (teamName)
		    divElem.innerHTML = '<hr><em>'+Slidoc.escapeHtml(teamName)+'</em><br>';
		this.postsElem.appendChild(divElem);
		if (teamNames.length >= 2) {
		    var option = document.createElement('option');
		    option.id = this.pluginId+'-select-team' + teamName;
		    option.value = teamName;
		    option.text = teamName;
		    this.selectElem.appendChild(option);
		}
	    }

	    this.labelElem.innerHTML = '<code>No posts yet</code>';
	    if (posts.length) {
		for (var j=0; j<posts.length; j++)
		    this.displayPost(posts[j]);
		Slidoc.renderMath(this.postsElem);
	    }
	}

	this.containerElem.style.display = null;

	if (this.showElem) {
	    this.showElem.classList.add('slidoc-plugin-Discuss-displayed');
	    this.showElem.classList.remove('slidoc-plugin-Discuss-unread');
	}
	if (this.countElem && this.countElem.textContent)
	    this.countElem.textContent = this.countElem.textContent.split('(')[0];
	if (this.toggleElem)
	    this.toggleElem.classList.remove('slidoc-plugin-Discuss-unread');
	if (this.global.topElem)
	    this.global.topElem.classList.remove('slidoc-plugin-Discuss-unread');

	if (this.unreadId) {
	    var unreadId = this.unreadId;
	    setTimeout(function(){document.getElementById(unreadId).scrollIntoView(true); }, 200);
	}
    }
};

/* HEAD:
   <style>
.slidoc-plugin-Discuss-displayed.slidoc-plugin-Discuss-unread,
  .slidoc-plugin-Discuss-unread { background: red; text-decoration: underline; }
.slidoc-plugin-Discuss-available { background: green; }
.slidoc-plugin-Discuss-displayed { background: green; }

.slidoc-plugin-Discuss-posts { margin-left: 2em; }
.slidoc-plugin-Discuss-post-timestamp { font-size: 60%; }
.slidoc-plugin-Discuss-post-delete { font-size: 60%; }

.slidoc-plugin-Discuss-post-unflag { background: red; }

.slidoc-plugin-Discuss-textarea { width: 80%; }
   </style>
   BODY:
<div id="%(pluginId)s-footer" class="slidoc-plugin-Discuss-footer slidoc-full-block slidoc-discussonly slidoc-noprint" style="display:none;">
  <span id="%(pluginId)s-show" class="slidoc-plugin-Discuss-show slidoc-clickable" onclick="Slidoc.Plugins['%(pluginName)s']['%(pluginSlideId)s'].slideDiscuss('show');">&#x1F4AC;</span>
  <span id="%(pluginId)s-count" class="slidoc-plugin-Discuss-count"></span>
  <div id="%(pluginId)s-container" class="slidoc-plugin-Discuss-container" style="display: none;">
    <div id="%(pluginId)s-label" class="slidoc-plugin-Discuss-label"></div>
    <div id="%(pluginId)s-posts" class="slidoc-plugin-Discuss-posts"></div>
    <hr>
    <div id="%(pluginId)s-post-container">
      <select id="%(pluginId)s-select-post-team" class="slidoc-plugin-Discuss-post-team"></select>
      <button id="%(pluginId)s-post" class="slidoc-plugin-Discuss-post" onclick="Slidoc.Plugins['%(pluginName)s']['%(pluginSlideId)s'].slideDiscuss('post');">Post</button>
      <br>
      <textarea id="%(pluginId)s-textarea" class="slidoc-plugin-Discuss-textarea" maxlength="280"></textarea>
      <div><button id="%(pluginId)s-preview" class="slidoc-plugin-Discuss-preview" onclick="Slidoc.Plugins['%(pluginName)s']['%(pluginSlideId)s'].slideDiscuss('preview');">Preview</button></div>
      <br><div id="%(pluginId)s-render" class="slidoc-plugin-Discuss-render"></div>
    </div>
    <div id="%(pluginId)s-close" class="slidoc-clickable slidoc-plugin-Discuss-close" onclick="Slidoc.Plugins['%(pluginName)s']['%(pluginSlideId)s'].closeDiscussion();" style="display:none;"></div>
  </div>
</div>
*/
