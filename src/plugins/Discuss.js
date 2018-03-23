Discuss = {
    // Discuss plugin
    global: {
	initGlobal: function(discussParams) {
	    Slidoc.log('Slidoc.Plugins.Discuss.initGlobal:', discussParams);
	    this.discussParams = discussParams;
	    this.discussSheet = new GService.GoogleSheet(this.discussParams.gd_sheet_url, this.sessionName+'_discuss',
							 [], [], false);
	    this.topElem = document.getElementById('slidoc-discuss-display');
	},

	unread: function() {
	    if (!this.discussParams.stats)
		return 0;
	    var sessionStats = this.discussParams.stats || {};
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

	postNotify: function(userId, userName, teamName, discussNum, newPost) {
	    Slidoc.log('Slidoc.Plugins.Discuss.postNotify:', userId, userName, teamName, discussNum, newPost);
	    if (!discussNum)
		return;
	    var slideNum = this.discussParams.discussSlides[discussNum-1].slide;
	    var slidePlugin = Slidoc.Plugins[this.name][Slidoc.makeSlideId(slideNum)];
	    if (!slidePlugin)
		return;
	    var POST_PREFIX_RE = /^Post:([\w-]*):(\d+):([-\d:T]+)\s+(.*)$/;
	    var match = newPost.match(POST_PREFIX_RE);
	    if (!match)
		return;
	    slidePlugin.unreadPost = true;
	    slidePlugin.activeUsers[userId] = new Date();
	    if (this.topElem && slideNum != Slidoc.PluginManager.getCurrentSlide())
		this.topElem.classList.add('slidoc-plugin-Discuss-unread');

	    var teamName = match[1]; // Redundant, since teamName is also an argument
	    var row = [match[1], parseInt(match[2]), userId, userName, match[3], true, match[4]];
	    var postElem = slidePlugin.displayPost(row);
	    if (postElem) {
		Slidoc.renderMath(postElem);
		if (slidePlugin.textareaElem && slidePlugin.textareaElem.value) {
		    window.scrollTo(0,document.body.scrollHeight);
		    setTimeout(function(){window.scrollTo(0,document.body.scrollHeight);}, 10);
		}
	    }
	    if (slidePlugin.containerElem.style.display) {
		// Discussion not open; notify unread
		if (slidePlugin.showElem)
		    slidePlugin.showElem.classList.add('slidoc-plugin-Discuss-unread');
		if (slidePlugin.toggleElem)
		    slidePlugin.toggleElem.classList.add('slidoc-plugin-Discuss-unread');
	    }
	}
    },

    init: function() {
	Slidoc.log('Slidoc.Plugins.Discuss.init:', this.global);
	if (!this.global.discussParams.stats)
	    return;
	var sessionStats = this.global.discussParams.stats || {};
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

	this.unreadPost = false;
	this.activeUsers = {};
	
	if (this.discussNum in sessionStats) {
	    var discussStats = sessionStats[this.discussNum];
	} else {
	    discussStats = {};
	    var stat = [0, 0];  // [nPosts, nUnread]
	}

	this.containerElem = document.getElementById(this.pluginId+'-container');
	this.selectElem = document.getElementById(this.pluginId+'-select-post-team');
	this.labelElem  = document.getElementById(this.pluginId+'-label');
	this.postsElem  = document.getElementById(this.pluginId+'-posts');
	this.showElem   = document.getElementById(this.pluginId+'-show');
	this.footerElem = document.getElementById(this.pluginId+'-footer');
	this.countElem  = document.getElementById(this.pluginId+'-count');
	this.textareaElem = document.getElementById(this.pluginId+'-textarea');

	if (this.discussSlideParams.maxchars)
	    this.textareaElem.setAttribute('maxlength', this.discussSlideParams.maxchars);

	this.toggleElem = document.getElementById(this.slideId+'-toptoggle-discuss');

	var teamNames = Object.keys(discussStats);
	teamNames.sort();
	var nPosts = 0;
	var nUnread = 0;
	this.postsElem.innerHTML = '';
	for (var iteam=0; iteam<teamNames.length; iteam++) {
	    var teamName = teamNames[iteam];
	    var teamStats = discussStats[teamName];
	    nPosts += teamStats[0];
	    nUnread += teamStats[1];
	}

	if (this.footerElem)
	    this.footerElem.style.display = null;
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
		var renderElem = document.getElementById(this.pluginId+'-render');
		renderElem.innerHTML = Slidoc.MDConverter(textValue, true);
		Slidoc.renderMath(renderElem);
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
	    this.countElem.textContent = postInfo[1].length ? postInfo[1].length+' posts' : '';
    },

    displayPost: function(row) {
	// row = [userTeam, postNum, userId, userName, postTime, unreadFlag, postText]
	// Return html and also set this.unreadId
	var userTeam = row[0];
	var postNum = row[1];
	var userId = row[2];
	var userName = row[3];
	var postTime = row[4];
	var unreadPost = row[5];
	var postText = row[6];

	var postId = this.slideId+'-'+userTeam+'post'+Slidoc.zeroPad(postNum,3);
	var postName = (userId == this.global.discussParams.testUserId) ? 'Instructor' : Slidoc.makeShortFirst(userName);
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
	var html = '';
	html += Slidoc.MDConverter(highlight+postName+highlight+': '+postText, true); // user name
	html += '<br><em class="slidoc-plugin-Discuss-post-timestamp">'+timestamp+'</em>';  // Time
	if ((this.userId == userId || this.userId == this.global.discussParams.testUserId) && !postText.match(/\s*\(deleted/))
	    html += ' <span class="slidoc-clickable slidoc-plugin-Discuss-post-delete" onclick="Slidoc.Plugins['+"'"+this.name+"']['"+this.slideId+"'"+'].deletePost('+postNum+",'"+userTeam+"','"+userId+"'"+');">&#x1F5D1;</span>';

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
	var teamNames = postInfo[0];
	var posts = postInfo[1];
	if (!update) // If update, postNotify has been sent
	    Slidoc.sendEvent('', -1, 'Discuss.activeNotify.'+this.slideNumber, 'displayDiscussion', this.discussNum);

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
    <select id="%(pluginId)s-select-post-team" class="slidoc-plugin-Discuss-post-team"></select>
    <button id="%(pluginId)s-post" class="slidoc-plugin-Discuss-post" onclick="Slidoc.Plugins['%(pluginName)s']['%(pluginSlideId)s'].slideDiscuss('post');">Post</button>
    <br>
    <textarea id="%(pluginId)s-textarea" class="slidoc-plugin-Discuss-textarea" maxlength="140"></textarea>
    <div><button id="%(pluginId)s-preview" class="slidoc-plugin-Discuss-preview" onclick="Slidoc.Plugins['%(pluginName)s']['%(pluginSlideId)s'].slideDiscuss('preview');">Preview</button></div>
    <br><div id="%(pluginId)s-render" class="slidoc-plugin-Discuss-render"></div>
  </div>
</div>
*/
