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
	    var sessionStats = this.discussParams.stats[''] || {};
	    var keys = Object.keys(sessionStats);
	    var count = 0;
	    for (var j=0; j<keys.length; j++) {
		if (sessionStats[keys[j]][1])
		    count += 1;
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

	postNotify: function(userId, userName, discussNum, newPost) {
	    Slidoc.log('Slidoc.Plugins.Discuss.postNotify:', userId, userName, discussNum, newPost);
	    var slideNum = this.discussParams.discussSlides[discussNum-1];
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

	    var teamName = match[1];
	    var row = [parseInt(match[2]), userId, userName, match[3], true, match[4]];
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
	var sessionStats = this.global.discussParams.stats[''] || {};
	this.discussNum = 1+this.global.discussParams.discussSlides.indexOf(this.slideNumber);
	if (this.discussNum <= 0)
	    return;

	this.unreadPost = false;
	this.activeUsers = {};
	
	if (this.discussNum in sessionStats) {
	    var stat = sessionStats[this.discussNum];
	} else {
	    var stat = [0, 0];  // [nPosts, nUnread]
	}

	this.containerElem = document.getElementById(this.pluginId+'-container');
	this.postsElem  = document.getElementById(this.pluginId+'-posts');
	this.showElem   = document.getElementById(this.pluginId+'-show');
	this.footerElem = document.getElementById(this.pluginId+'-footer');
	this.countElem  = document.getElementById(this.pluginId+'-count');
	this.textareaElem = document.getElementById(this.pluginId+'-textarea');

	this.toggleElem = document.getElementById(this.slideId+'-toptoggle-discuss');

	if (this.footerElem)
	    this.footerElem.style.display = null;
	if (this.showElem && stat[1])
	    this.showElem.classList.add('slidoc-plugin-Discuss-unread');
	if (this.countElem && stat[0])
	    this.countElem.textContent = stat[1] ? stat[0]+' posts ('+stat[1]+' unread)' : stat[0]+' posts';
	if (this.toggleElem)
	    this.toggleElem.style.display = null;

	if (stat[0]) {
	    if (this.toggleElem)
		this.toggleElem.classList.add('slidoc-plugin-Discuss-available');
	    if (stat[1]) {
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
		this.global.discussSheet.updateRow(updates, {}, this.updateCallback.bind(this));
	    }
	}
    },

    deletePost: function(postNum, userId) {
	Slidoc.log('Slidoc.Plugins.Discuss.deletePost:', postNum, userId);
	if (this.discussNum <= 0)
	    return false;
	if (!window.confirm('Delete discussion post?'))
	    return false;
	var colName = 'discuss' + Slidoc.zeroPad(this.discussNum, 3);
	var updates = {id: userId};
	var postTeam = '';
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
	var posts = result;
	this.displayDiscussion(posts);
	if (this.countElem)
	    this.countElem.textContent = posts.length ? posts.length+' posts' : '';
    },

    displayPost: function(row) {
	// row = [postNum, userId, userName, postTime, unreadFlag, postText]
	// Return html and also set this.unreadId
	var postId = this.slideId+'-post'+Slidoc.zeroPad(row[0],3);
	var postName = (row[1] == this.global.discussParams.testUserId) ? 'Instructor' : Slidoc.makeShortFirst(row[2]);
	var postDate = new Date(row[3]);
	if (!postDate) {
	    var timestamp = row[3];
	} else {
	    var opts = {month: 'short', day: 'numeric', hour:'numeric', minute:'numeric' };
	    if (postDate.getFullYear() != (new Date()).getFullYear() )
		opts.year = 'numeric';
	    timestamp = postDate.toLocaleString(navigator.language, opts);
	}
        var highlight = '*';
	if (row[4]) {
	    // Unread
	    highlight = '**';
	    if (!this.unreadId)
		this.unreadId = postId;
	}
	var html = '';
	html += Slidoc.MDConverter(highlight+postName+highlight+': '+row[5], true); // user name
	html += '<br><em class="slidoc-plugin-Discuss-post-timestamp">'+timestamp+'</em>';  // Time
	if ((this.userId == row[1] || this.userId == this.global.discussParams.testUserId) && !row[5].match(/\s*\(deleted/))
	    html += ' <span class="slidoc-clickable slidoc-plugin-Discuss-post-delete" onclick="Slidoc.Plugins['+"'"+this.name+"']['"+this.slideId+"'"+'].deletePost('+row[0]+",'"+row[1]+"'"+');">&#x1F5D1;</span>'

	var elem = document.createElement('p');
	elem.id = postId;
	elem.innerHTML = html;

	if (this.postsElem)
	    this.postsElem.appendChild(elem);
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

    displayDiscussion: function(posts, update) {
	if (!update && !this.containerElem.style.display) {
	    // Collapse display
	    this.containerElem.style.display = 'none';
	    return;
	}
	if (!update) // If update, postNotify have been sent
	    Slidoc.sendEvent('', -1, 'Discuss.activeNotify.'+this.slideNumber, 'displayDiscussion', this.discussNum);
	this.unreadId = '';
	if (this.postsElem) {
	    if (posts.length) {
		this.postsElem.innerHTML = '';
		for (var j=0; j<posts.length; j++)
		    this.displayPost(posts[j]);
		Slidoc.renderMath(this.postsElem);
	    } else {
		this.postsElem.innerHTML = '<code>No posts yet</code>';
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
    <div id="%(pluginId)s-posts" class="slidoc-plugin-Discuss-posts"></div>
    <div><button id="%(pluginId)s-post" class="slidoc-plugin-Discuss-post" onclick="Slidoc.Plugins['%(pluginName)s']['%(pluginSlideId)s'].slideDiscuss('post');">Post</button></div>
    <textarea id="%(pluginId)s-textarea" class="slidoc-plugin-Discuss-textarea" maxlength="80"></textarea>
    <div><button id="%(pluginId)s-preview" class="slidoc-plugin-Discuss-preview" onclick="Slidoc.Plugins['%(pluginName)s']['%(pluginSlideId)s'].slideDiscuss('preview');">Preview</button></div>
    <br><div id="%(pluginId)s-render" class="slidoc-plugin-Discuss-render"></div>
  </div>
</div>
*/
