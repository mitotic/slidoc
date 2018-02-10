Discuss = {
    // Discuss plugin
    global: {
	initGlobal: function(discussParams) {
	    Slidoc.log('Slidoc.Plugins.Discuss.initGlobal:', discussParams);
	    this.discussParams = discussParams;
	    this.discussSheet = new GService.GoogleSheet(this.discussParams.gd_sheet_url, this.sessionName+'_discuss',
							 [], [], false);
	},

	unread: function() {
	    if (!this.discussParams.stats)
		return 0;
	    var keys = Object.keys(this.discussParams.stats);
	    var count = 0;
	    for (var j=0; j<keys.length; j++) {
		if (this.discussParams.stats[keys[j]][1])
		    count += 1;
	    }
	    return count;
	}
    },

    init: function() {
	Slidoc.log('Slidoc.Plugins.Discuss.init:', this.global);
	if (!this.global.discussParams.stats)
	    return;
	var slideNum = parseSlideId(this.slideId)[2];
	var discussNum = 1+this.global.discussParams.discussSlides.indexOf(slideNum);
	if (discussNum <= 0)
	    return;
	if (discussNum in this.global.discussParams.stats) {
	    var stat = this.global.discussParams.stats[discussNum];
	} else {
	    var stat = [0, 0];  // [nPosts, nUnread]
	}
	var footerElem = document.getElementById(this.pluginId+'-footer');
	var showElem = document.getElementById(this.pluginId+'-show');
	var countElem = document.getElementById(this.pluginId+'-count');
	var toggleElem = document.getElementById(this.slideId+'-toptoggle-discuss');
	if (footerElem)
	    footerElem.style.display = null;
	if (showElem && stat[1])
	    showElem.classList.add('slidoc-plugin-Discuss-unread');
	if (countElem && stat[0])
	    countElem.textContent = stat[1] ? stat[0]+' posts ('+stat[1]+' unread)' : stat[0]+' posts';
	if (toggleElem) {
	    toggleElem.style.display = null;
	    if (stat[0]) {
		toggleElem.classList.add('slidoc-discuss-available');
		if (stat[1])
		    toggleElem.classList.add('slidoc-discuss-unread');
	    }
	}
    },

    slideDiscuss: function(action) {
	Slidoc.log('Slidoc.Plugins.Discuss.slideDiscuss:', action);
	var slideNum = parseSlideId(this.slideId)[2];
	var discussNum = 1+this.global.discussParams.discussSlides.indexOf(slideNum);
	if (discussNum <= 0)
	    return false;

	if (action == 'show') {
	    this.global.discussSheet.actions('discuss_posts', {id: this.userId, sheet:this.sessionName, discuss: discussNum}, this.showCallback.bind(this));
	} else {
	    var colName = 'discuss' + Slidoc.zeroPad(discussNum, 3);
	    var textareaElem = document.getElementById(this.pluginId+'-textarea');
	    var textValue = textareaElem.value;
	    if (action == 'preview') {
		var renderElem = document.getElementById(this.pluginId+'-render');
		renderElem.innerHTML = Slidoc.MDConverter(textValue, true);
		Slidoc.renderMath(renderElem);
	    } else if (action == 'post') {
		var updates = {id: this.userId};
		updates[colName] = textValue;
		this.global.discussSheet.updateRow(updates, {}, this.updateCallback.bind(this));
	    }
	}
    },

    deletePost: function(postNum, userId) {
	Slidoc.log('Slidoc.Plugins.Discuss.deletePost:', postNum, userId);
	var slideNum = parseSlideId(this.slideId)[2];
	var discussNum = 1+this.global.discussParams.discussSlides.indexOf(slideNum);
	if (discussNum <= 0)
	    return false;
	if (!window.confirm('Delete discussion post?'))
	    return false;
	var colName = 'discuss' + Slidoc.zeroPad(discussNum, 3);
	var updates = {id: userId};
	updates[colName] = 'delete:' + Slidoc.zeroPad(postNum, 3);
	this.global.discussSheet.updateRow(updates, {admin:1}, this.updateCallback.bind(this));
    },

    updateCallback: function(result, retStatus) {
	Slidoc.log('Slidoc.Plugins.Discuss.updateCallback:', result, retStatus);
	if (!result) {
	    alert('Error in discussion post: '+(retStatus?retStatus.error:''));
	    return;
	}
	this.displayDiscussion(retStatus.info.discussPosts);
	var textareaElem = document.getElementById(this.pluginId+'-textarea');
	textareaElem.value = '';
    },

    showCallback: function(result, retStatus) {
	Slidoc.log('Slidoc.Plugins.Discuss.showCallback:', result, retStatus);
	if (!result) {
	    alert('Error in discussion show: '+(retStatus?retStatus.error:''));
	    return;
	}
	this.displayDiscussion(result);
    },

    displayDiscussion: function(posts) {
	var html = '';
	var unreadId = '';
	for (var j=0; j<posts.length; j++) {
	    var row = posts[j];  // [postNum, userId, userName, postTime, unreadFlag, postText]
	    var postId = this.slideId+'-post'+Slidoc.zeroPad(row[0],3);
	    var postName = (row[1] == this.global.discussParams.testUserId) ? 'Instructor' : row[2];
            var highlight = '*';
	    if (row[4]) {
		// Unread
		highlight = '**';
		if (!unreadId)
		    unreadId = postId;
	    }
	    html += '<p id="'+postId+'">'
	    html += Slidoc.MDConverter(highlight+postName+highlight+': '+row[5], true); // Last,First: Text
	    html += '<br><em class="slidoc-plugin-Discuss-post-timestamp">'+row[3]+'</em>';  // Time
	    if ((this.userId == row[1] || this.userId == this.global.discussParams.testUserId) && !row[5].match(/\s*\(deleted/))
		html += ' <span class="slidoc-clickable slidoc-plugin-Discuss-post-delete" onclick="Slidoc.Plugins['+"'"+this.name+"']['"+this.slideId+"'"+'].deletePost('+row[0]+",'"+row[1]+"'"+');">&#x1F5D1;</span>'
	    html += '</p>'
	}
	var containerElem = document.getElementById(this.pluginId+'-container');
	containerElem.style.display = null;
	var postsElem = document.getElementById(this.pluginId+'-posts');
	postsElem.innerHTML = html;
	Slidoc.renderMath(postsElem);

	var showElem = document.getElementById(this.pluginId+'-show');
	if (showElem)
	    showElem.classList.add('slidoc-plugin-Discuss-displayed');
	var countElem = document.getElementById(this.pluginId+'-count');
	var toggleElem = document.getElementById(this.slideId+'-toptoggle-discuss');
	if (countElem && countElem.textContent)
	    countElem.textContent = countElem.textContent.split('(')[0];
	if (toggleElem)
	    toggleElem.classList.remove('slidoc-discuss-unread');
	if (unreadId)
	    setTimeout(function(){document.getElementById(unreadId).scrollIntoView(true); }, 200);
    }
};

/* HEAD:
   <style>
.slidoc-plugin-Discuss-unread { background: red; }
.slidoc-plugin-Discuss-displayed { background: green; }

.slidoc-plugin-Discuss-posts { margin-left: 2em; }
.slidoc-plugin-Discuss-post-timestamp { font-size: 60%; }
.slidoc-plugin-Discuss-post-delete { font-size: 60%; }
   </style>
   BODY:
<div id="%(pluginId)s-footer" class="slidoc-plugin-Discuss-footer slidoc-full-block slidoc-discussonly slidoc-noprint" style="display:none;">
  <span id="%(pluginId)s-show" class="slidoc-plugin-Discuss-show slidoc-clickable" onclick="Slidoc.Plugins['%(pluginName)s']['%(pluginSlideId)s'].slideDiscuss('show');">&#x1F4AC;</span>
  <span id="%(pluginId)s-count" class="slidoc-plugin-Discuss-count"></span>
  <div id="%(pluginId)s-container" class="slidoc-plugin-Discuss-container" style="display: none;">
    <div id="%(pluginId)s-posts" class="slidoc-plugin-Discuss-posts"></div>
    <div><button id="%(pluginId)s-post" class="slidoc-plugin-Discuss-post" onclick="Slidoc.Plugins['%(pluginName)s']['%(pluginSlideId)s'].slideDiscuss('post');">Post</button></div>
    <textarea id="%(pluginId)s-textarea" class="slidoc-plugin-Discuss-textarea"></textarea>
    <div><button id="%(pluginId)s-preview" class="slidoc-plugin-Discuss-preview" onclick="Slidoc.Plugins['%(pluginName)s']['%(pluginSlideId)s'].slideDiscuss('preview');">Preview</button></div>
    <br><div id="%(pluginId)s-render" class="slidoc-plugin-Discuss-render"></div>
  </div>
</div>
*/
