// JS include file for Google services
// Before including this script, define CLIENT_ID, API_KEY, LOGIN_BUTTON_ID, AUTH_CALLBACK and
//   function onGoogleAPILoad() { GService.onGoogleAPILoad(); }
// After this script, include script with src="https://apis.google.com/js/client.js?onload=onGoogleAPILoad"

var TRUNCATE_DIGEST = 8;
var MAXSCORE_ID = '_max_score';

function genHmacToken(key, message) {
    // Generates token using HMAC key
    return btoa(md5(message, key, true)).slice(0,TRUNCATE_DIGEST);
}

function genAuthPrefix(userId, role, sites) {
    return ':' + userId + ':' + (role||'') + ':' + (sites||'');
}

function genAuthToken(key, userId, role, sites, prefixed) {
    var prefix = genAuthPrefix(userId, role, sites);
    var token = genHmacToken(key, prefix);
    return prefixed ? (prefix+':'+token) : token;
}


function genLateToken(key, user_id, site_name, session_name, date_str) {
    // Use UTC date string of the form '1995-12-17T03:24' (append Z for UTC time)
    var date = new Date(date_str);
    if (date_str.slice(-1) != 'Z') {  // Convert local time to UTC
	date.setTime( date.getTime() + date.getTimezoneOffset()*60*1000 );
	date_str = date.toISOString().slice(0,16)+'Z';
    }
    return date_str+':'+genHmacToken(key, 'late:'+user_id+':'+site_name+':'+session_name+':'+date_str);
}

var GService = {};

function GServiceJSONP(callback_index, json_text) {
    GService.handleJSONP(callback_index, json_text);
}

(function (GService) {
// http://railsrescue.com/blog/2015-05-28-step-by-step-setup-to-send-form-data-to-google-sheets/

var jsonpCounter = 0;
var jsonpReceived = 0;
var jsonpRequests = {};

function requestJSONP(url, queryStr, callback) {
    var suffix = '&prefix=GServiceJSONP';
    if (callback) {
	jsonpCounter += 1;
	jsonpRequests[jsonpCounter] = [callback, url];
	suffix += '&callback='+jsonpCounter;
    }

    url += '?'+queryStr+suffix;
    Slidoc.log('requestJSONP:', url);

    var head = document.head;
    var script = document.createElement("script");

    script.setAttribute("src", url);
    head.appendChild(script);
    head.removeChild(script);
}

GService.handleJSONP = function(callback_index, json_obj) {
    Slidoc.log('GService.handleJSONP:', callback_index);
    if (!callback_index)
	return;
    if (!(callback_index in jsonpRequests)) {
	Slidoc.log('GService.handleJSONP: Error - Invalid JSONP callback index: '+callback_index);
	return;
    }
    var outOfSequence = (callback_index != jsonpReceived+1);
    jsonpReceived = Math.max(callback_index, jsonpReceived);
    var callback = jsonpRequests[callback_index][0];
    delete jsonpRequests[callback_index];
    if (callback)
	callback(json_obj || null, '', outOfSequence);
}

var wsock = {};

wsock.sessionVersion = 0;

function initWebsocket() {
    wsock.counter = 0;
    wsock.received = 0;
    wsock.requests = {};

    wsock.connection = null;
    wsock.opened = false;
    wsock.locked = '';
    wsock.closed = '';
    wsock.buffer = [];
    wsock.eventReceiver = null;
}

initWebsocket();

GService.openWebsocket = function (wsPath) {
    var wsUrl = ((location.protocol === "https:") ? "wss://" : "ws://") + location.host + wsPath;
    Slidoc.log('GService.openWebsocket:', wsUrl);

    wsock.connection = new WebSocket(wsUrl);

    wsock.connection.onopen = function() {
	Slidoc.log('GService.ws.onopen:');
	wsock.opened = true;
    }

    wsock.connection.onerror = function (error) {
	Slidoc.log('GService.ws.onerror: Error', error);
	alert('Failed to open websocket: '+error);
	document.body.textContent = 'Connection error for websocket URL '+wsUrl+'. Reload page to restart';
    }

    wsock.connection.onclose = function (evt) {
	Slidoc.log('GService.ws.onclose:', wsock.closed);
	if (wsock.closed)  // Deliberate close
	    return;
	// Auto-close on timeout; reconnect if needed
	initWebsocket();
    }

    wsock.connection.onmessage = function(evt) {
	try {
	    var msgObj = JSON.parse(evt.data);
	} catch (err) {
            Slidoc.log('GService.ws.onmessage: Websocket JSON parsing error:', err, evt.data);
	    return;
	}
	var callback_index = msgObj[0];
	var callback_method = msgObj[1];
	var callback_args = msgObj[2];
	
	Slidoc.log('GService.ws.onmessage:', callback_index, callback_method, callback_args);

	if (!callback_index) {
	    try {
		if (callback_method == 'session_version') {
		    if (wsock.sessionVersion && wsock.sessionVersion != callback_args[0]) {
			GService.closeWS('Session version is out of date. Please reload ('+callback_args[0]+')', 'Please reload page to access latest session');
		    } else {
			wsock.sessionVersion = callback_args[0];

			// Flush message buffer
			while (wsock.buffer.length > 0)
			    wsock.connection.send( GService.stringifyWS(wsock.buffer.shift()) );
		    }

		} else if (callback_method == 'lock') {
		    wsock.locked = callback_args[0]; // Null string to unlock
		    if (callback_args[1]) {
			Slidoc.closeAllPopups();
			Slidoc.showPopup(Slidoc.escapeHtml(callback_args[0] || 'Reload page?'), null, false, 0, 'lockReload',
					 function() {location.reload(true)});
		    }
		} else if (callback_method == 'close') {
		    GService.closeWS(callback_args[0], callback_args[1]);
		} else if (callback_method == 'event') {
		    if (wsock.eventReceiver)
			wsock.eventReceiver(callback_args);
		    else
			Slidoc.log('GService.ws.onmessage: ERROR Ignored event; no receiver '+callback_args[0]);
		}
	    } catch (err) {
		Slidoc.log('GService.ws.onmessage: Error in invoking method '+callback_method+': '+err);
	    }
	    return;
	}

	if (!(callback_index in wsock.requests)) {
	    Slidoc.log('GService.ws.onmessage: Error - Invalid WS callback index: '+callback_index);
	    return;
	}
	var outOfSequence = (callback_index != wsock.received+1);
	wsock.received = Math.max(callback_index, wsock.received);
	var callback = wsock.requests[callback_index][0];
	delete wsock.requests[callback_index];
	if (callback)
	    callback(callback_args || null, '', outOfSequence);
    }
}

GService.closeWS = function (closeMsg, dispMsg) {
    if (dispMsg) {
	Slidoc.closeAllPopups();
	Slidoc.showPopup(Slidoc.escapeHtml(dispMsg));
    }
    if (wsock.closed)
	return;
    Slidoc.log('GService.closeWS:', closeMsg);
    wsock.closed = closeMsg || 'Connection closed. Reload page to restart.';
    wsock.connection.close();
}

GService.stringifyWS = function (message) {
    if (Array.isArray(message)) // Pre-pend session version
	return JSON.stringify( [wsock.sessionVersion].concat(message) );
    else
	return message;
}
    
GService.rawWS = function (message) {
    if (wsock.closed) {
	alert(wsock.closed);
	return;
    }
    if (wsock.opened) {
	wsock.connection.send( GService.stringifyWS(message) );
    } else {
	if (!wsock.connection)
	    GService.openWebsocket(Slidoc.websocketPath);
	wsock.buffer.push(message);
    }
}

GService.requestWS = function (callType, data, callback) {
    if (data.write && wsock.locked) {
	alert(wsock.locked);
	return;
    }
    var callbackIndex = 0;
    if (callback) {
	wsock.counter += 1;
	callbackIndex = wsock.counter;
	wsock.requests[wsock.counter] = [callback];
    }
    GService.rawWS( [callbackIndex, callType, data] );
}

GService.setEventReceiverWS = function (eventReceiver) {
    wsock.eventReceiver = eventReceiver;
}
    
GService.sendEventWS = function (target, eventType, eventName, args) {
    GService.requestWS('event', [target, eventType, eventName, args]);
}

function handleCallback(responseText, callback, outOfSequence) {
    if (!callback)
	return;
    var obj = null;
    var msg = '';
    try {
        obj = JSON.parse(responseText)
    } catch (err) {
        Slidoc.log('JSON parsing error:', err, responseText);
        msg = 'JSON parsing error';
    }
    callback(obj, msg, outOfSequence);
}
    
var sendDataCounter = 0;
var receiveDataCounter = 0;

GService.sendData = function (data, url, callback, useJSONP) {
  /// callback(result_obj, optional_err_msg)

  if (data.modify || (data.actions && data.actions == 'gradebook')) {
      // Workaround for passthru actions; this could be done without a GSheet
      if (url.match(/_websocket$/))
	  url = url.replace(/_websocket$/, '_proxy');
  } else if (Slidoc.websocketPath) {
      GService.requestWS('proxy', data, callback);
      return;
  }

  var XHR = new XMLHttpRequest();
  var urlEncodedData = "";
  var urlEncodedDataPairs = [];

  sendDataCounter += 1;
  var currentDataCounter = sendDataCounter;
  XHR.onreadystatechange = function () {
      var DONE = 4; // readyState 4 means the request is done.
      var OK = 200; // status 200 is a successful return.
      if (XHR.readyState === DONE) {
	var outOfSequence = (currentDataCounter != receiveDataCounter+1);
        receiveDataCounter = Math.max(currentDataCounter, receiveDataCounter);
        if (XHR.status === OK) {
          Slidoc.log('XHR: '+XHR.status, XHR.responseText);
	  handleCallback(XHR.responseText, callback, outOfSequence);
        } else {
          Slidoc.log('XHR Error: '+XHR.status, XHR.responseText);
          if (callback)
              callback(null, 'Error in HTTP request', outOfSequence)
        }
      }
  };

  // Encoded key=value pairs
    for (var name in data) {
    urlEncodedDataPairs.push(encodeURIComponent(name) + '=' + encodeURIComponent(data[name]));
  }
  // Replaces encoded spaces with plus symbol to mimic form behavior
  urlEncodedData = urlEncodedDataPairs.join('&').replace(/%20/g, '+');

  if (useJSONP) {
      requestJSONP(url, urlEncodedData, callback);
      return;
  }

  // We setup our request
  XHR.open('POST', url);

  // We add the required HTTP header to handle a form data POST request
  XHR.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
  XHR.setRequestHeader('Content-Length', urlEncodedData.length);
  Slidoc.log('sendData:', urlEncodedData, url, useJSONP);
  // And finally, We send our data.
  XHR.send(urlEncodedData);
}

function GoogleProfile(clientId, apiKey, loginButtonId, authCallback) {
    //Include script src="https://apis.google.com/js/client.js?onload=handleClientLoad"
    // authCallback(this.auth)
    this.clientId = clientId;
    this.apiKey = apiKey;
    this.loginButtonId = loginButtonId;
    this.authCallback = authCallback || null;
    this.scopes = 'https://www.googleapis.com/auth/userinfo.email';
    this.auth = null;
}

GoogleProfile.prototype.onLoad = function () {
    Slidoc.log('GoogleProfile.onLoad:');
    gapi.client.setApiKey(this.apiKey);
    window.setTimeout(this.requestAuth.bind(this, true), 5);
}


GoogleProfile.prototype.requestAuth = function (immediate) {
    Slidoc.log('GoogleProfile.requestAuth:');
    gapi.auth.authorize({client_id: this.clientId, scope: this.scopes, immediate: immediate},
                        this.onAuth.bind(this));
    return false;
}

GoogleProfile.prototype.onAuth = function (result) {
    Slidoc.log('GoogleProfile.onAuth:', result);
    var loginButton = document.getElementById(this.loginButtonId);
    if (!loginButton) {
        alert('No login button');
        return;
    }
    if (result && !result.error) {
        // Authenticated
        loginButton.style.display = 'none';
        gapi.client.load('plus', 'v1', this.requestUserInfo.bind(this));
    } else {
        // Need to authenticate
	loginButton.style.display = 'block';
        loginButton.onclick = this.requestAuth.bind(this, false);
        alert('Please login to proceed');
    }
}

GoogleProfile.prototype.requestUserInfo = function () {
    Slidoc.log('GoogleProfile.requestUserInfo:');
    var req = gapi.client.plus.people.get({userId: 'me'});
    req.execute(this.onUserInfo.bind(this));
}

GoogleProfile.prototype.onUserInfo = function (resp) {
    Slidoc.log('GoogleProfile.onUserInfo:', resp);
    if (!resp.emails) {
	alert('GAuth: ERROR no emails specified');
        return;
    }

    var email = '';
    for (var j=0; j<resp.emails.length; j++) {
        var email = resp.emails[j];
        if (email.type == 'account') {
	    email = email.value.toLowerCase()
            break;
        }
    }
    if (!resp.graderKey && !resp.id && !email) {
	alert('GAuth: ERROR no user id or email specified');
        return;
    }

    this.auth = {};
    this.auth.email = email;
    this.auth.type = resp.authType || '';
    this.auth.id = resp.id || email;
    this.auth.origid = resp.origid || '';
    this.auth.altid = resp.altid ||'';

    var name = resp.displayName;
    if (name.indexOf(',') < 0) {
	// No commas in name; re-order as Lastname, Firstname(s)
	var comps = name.split(/\s+/);
	if (comps.length > 1)
	    name = comps.slice(-1)+', '+comps.slice(0,-1).join(' ');
    }

    this.auth.displayName = name || this.auth.id || this.auth.email;
    this.auth.token = resp.token || '';
    this.auth.domain = resp.domain || '';
    this.auth.image = (resp.image && resp.image.url) ? resp.image.url : ''; 
    this.auth.graderKey = resp.graderKey || '';
    this.auth.authRole = resp.authRole || '';
    this.auth.remember = resp.remember || false;
    this.auth.validated = null;

    if (this.authCallback)
	this.authCallback(this.auth);
}

GoogleProfile.prototype.receiveUserInfo = function (authType, userInfo, loginRemember, callback) {
    var loginUser = userInfo.user;
    var email = userInfo.email || ( (loginUser.indexOf('@')>0) ? loginUser : '' );
    if (callback)
	this.authCallback = callback;
    this.onUserInfo({id: loginUser,
		     origid: userInfo.origid||'',
		     token: userInfo.token,
		     graderKey: userInfo.graderKey||'',
		     authRole: userInfo.authRole||'',
		     displayName: userInfo.name || loginUser,
		     authType: authType,
		     emails: [{type: 'account', value: email}],
		     altid: userInfo.altid||'',
		     remember: !!loginRemember});
}
	
GoogleProfile.prototype.promptUserInfo = function (siteName, sessionName, testMode, authType, user, msg, callback) {
    var sitePrefix = siteName ? '/'+siteName : '';
    var cookieInfo = Slidoc.serverCookie;
    if (!authType && !cookieInfo) {
	var randStr = Math.random().toString(16).slice(2);
	this.receiveUserInfo(authType, {user: 'anon'+randStr, name: 'User Anon'+randStr}, false, callback);
	return;
    }
    if (cookieInfo) {
	if (user || msg || callback || !cookieInfo.user || !cookieInfo.token) {
	    // Re-do authentication to update cookie
	    var urlPath = location.pathname;
	    if (location.search)
		urlPath += location.search;
	    if (location.hash)
		urlPath += location.hash;
	    var href = "/_auth/login/?next="+encodeURIComponent(urlPath);
	    if (msg)
		href += "&error="+encodeURIComponent(msg);
	    location.href = href;
	    return;
	} else {
	    // Use user/token from cookie
	    var userName = cookieInfo.user;
	    var userRole = cookieInfo.role;
	    var userSites = cookieInfo.sites;
	    var userToken = cookieInfo.token;
	    var siteRole = cookieInfo.siteRole;
	    var userData = cookieInfo.data || {};

	    var displayName = userData.name || '';
	    var userEmail = userData.email || '';
	    var userAltid = userData.altid || '';


	    var adminToken = ':'+userName+':'+userRole+':'+userSites+':'+userToken;
	    var regularUserToken = userToken;
	    if (userRole || userSites)
		regularUserToken = userName+adminToken;

	    console.log("promptUserInfo:", testMode, userName, userRole, userSites);
	    var adminUser   = 1;
	    var graderUser  = 2;
	    var normalUser  = 3;
	    var userIds     = ['_test_user',                   '_grader',              userName,                      ''];
	    var userTokens  = ['_test_user'+adminToken,       adminToken,              regularUserToken,      adminToken];
	    var graderKeys  = ['',                            adminToken,              '',                            ''];
	    var authRoles   = [siteRole,                        siteRole,              '',                            ''];
	    var userOptions = ['Admin view (for live testing/pacing)', 'Grader view (for printing/grading)', 'Normal user ('+userName+')', 'Another user (read-only)'];

	    var gprofile = this;
  	    function pickRole(indx) {
		if (!userIds[indx-1]) {
		    userIds[indx-1] = window.prompt('User id:');
		    if (!userIds[indx-1])
			return;
		    userTokens[indx-1] = userIds[indx-1] + userTokens[indx-1];
		    displayName = userIds[indx-1]+' ALT';
		    userEmail = ''
		    userAltid = '';
		}
		var userParams = {
		    user: userIds[indx-1],
		    token: userTokens[indx-1],
		    graderKey: graderKeys[indx-1],
		    authRole: authRoles[indx-1],
		    origid: userName,
		    name: displayName,
		    email: userEmail,
		    altid: userAltid}
		gprofile.receiveUserInfo(authType, userParams, false, callback);
	    }

	    var userOffset;
	    function optCallback(selOption) {
		Slidoc.log('GoogleProfile.promptUserInfo.optCallback:', selOption);
		var indx = userOffset + Math.min(userOptions.length-userOffset, Math.max(1, selOption||0));
		pickRole(indx);
	    }

	    if (!getParameter('grading')) {
		// For non-grading mode, test user if admin else normal user otherwise
		pickRole( (siteRole == 'admin') ? adminUser : normalUser)
	    } else if (siteRole && (testMode || userData.batch)) {
		// For test/batch mode, test user if admin else grader
		pickRole( (siteRole == 'admin') ? adminUser : graderUser)
	    } else if (siteRole == 'admin') {
		userOffset = 0;
		Slidoc.showPopupOptions('Select role:', userOptions.slice(userOffset),
					'<p></p><a href="'+sitePrefix+'/_manage/'+sessionName+'">Manage session '+sessionName+'</a>'+
					'<br><a href="'+sitePrefix+'/_dash">Dashboard</a>',
					optCallback);
	    } else if (siteRole == 'grader') {
		userOffset = graderUser-1;
		Slidoc.showPopupOptions('Select role:', userOptions.slice(userOffset,-1),
					'', optCallback);
	    } else {
		// Normal user
		pickRole(normalUser)
	    }
	    return;
	}
    }
    var loginElem = document.getElementById('gdoc-login-popup');
    var loginOverlay = document.getElementById('gdoc-login-overlay');
    var loginUserElem = document.getElementById('gdoc-login-user');
    var loginTokenElem = document.getElementById('gdoc-login-token');
    var loginRememberElem = document.getElementById('gdoc-login-remember');
    loginUserElem.value = user || '';
    loginRememberElem.checked =  !!GService.gprofile.auth && GService.gprofile.auth.remember;
    document.getElementById('gdoc-login-message').textContent = msg || '';

    var gprofile = this; // Because 'this' is re-bound on callback
    document.getElementById('gdoc-login-button').onclick = function (evt) {
	loginElem.style.display = 'none';
        loginOverlay.style.display = 'none';
	var loginUser = loginUserElem.value.trim().toLowerCase();
	var loginToken = loginTokenElem.value.trim();

	if (!loginUser) {
	    alert('Please provide user name for login');
	    return false;
	}

	if (!loginToken) {
	    alert('Please provide token for login');
	    return false;
	}
	gprofile.receiveUserInfo(authType, {user: loginUser,
					    token: loginToken,
					    name: loginUser},
					    loginRememberElem.checked, callback);
    }
    loginElem.style.display = 'block';
    loginOverlay.style.display = 'block';
    window.scrollTo(0,0);
}

function GoogleSheet(url, sheetName, preHeaders, fields, useJSONP) {
    if (!url)
	throw('Error: Null Google Sheet URL');
    this.url = url;
    this.sheetName = sheetName;
    this.preHeaders = preHeaders || [];
    this.fields = fields || [];
    this.headers = this.preHeaders.concat(this.fields);
    this.useJSONP = !!useJSONP;
    this.callbackCounter = 0;
    this.pendingUpdates = 0;
    this.userUpdateCounter = {};
    this.columnIndex = {};
    this.timestamps = {};
    this.cacheAll = null;
    this.roster = null;
    for (var j=0; j<this.headers.length; j++)
        this.columnIndex[this.headers[j]] = j;
}

GoogleSheet.prototype.send = function(params, callType, callback) {
    params = JSON.parse(JSON.stringify(params));
    params.version = Slidoc.version;

    if (!params.id && GService.gprofile.auth.id)
	params.id = GService.gprofile.auth.id;

    if (GService.gprofile.auth.token)
	params.token = GService.gprofile.auth.token;

    if (GService.gprofile.auth.graderKey)
	params.admin = GService.gprofile.auth.origid;

    if (callType != 'actions')
	params.sheet = this.sheetName;

    var userId = params.id||null;

    if (!this.headers.length)
	params.getheaders = 1;

    // Pretend voting is not 'writing'
    if ( (callType == 'putRow' && !params.nooverwrite) ||
	 (callType == 'updateRow' && !params.vote) ||
	 (callType == 'getRow' && params.resetrow) )
	params.write = 1;

    if (params.create) {
	if (GService.gprofile.auth.displayName)
	    params.name = GService.gprofile.auth.displayName;

	if (GService.gprofile.auth.email)
	    params.email = GService.gprofile.auth.email;

	if (GService.gprofile.auth.altid)
	    params.altid = GService.gprofile.auth.altid;
    }

    GService.sendData(params, this.url, this.callback.bind(this, userId, callType, callback),
		      this.useJSONP);
}

GoogleSheet.prototype.callback = function (userId, callbackType, outerCallback, result, err_msg, outOfSequence) {
    // outerCallback(obj, {error: err_msg, messages: messages})
    // obj == null on error
    // obj == {} for non-existent row
    // obj == {id: ..., name: ..., } for returned row
    Slidoc.log('GoogleSheet: callback', this.callbackCounter, userId, callbackType, result, err_msg, outOfSequence);
    this.callbackCounter -= 1;

    if (callbackType == 'putRow' || callbackType == 'updateRow') {
	this.pendingUpdates -= 1;
	if (userId && userId in this.userUpdateCounter)
	    this.userUpdateCounter[userId] -= 1;
    }

    if (!result)
        Slidoc.log('GoogleSheet: ERROR in '+callbackType+' callback: '+err_msg);

    var retval = null;
    var retStatus = {error: '', info: null, messages: null};
    if (result) {
	try {
	    if (result.result == 'success' && result.value) {
		if (callbackType == 'getAll') {
		    retval = {};
		    for (var j=0; j<result.value.length; j++) {
			var row = result.value[j];
			if (row.length) {
			    var rowObj = this.row2obj(row);
			    retval[rowObj.id] = rowObj;
			}
		    }

		} else if (callbackType == 'getShare') {
		    if (result.headers) {
			retval = {};
			for (var i=0; i<result.headers.length; i++)
			    retval[result.headers[i]] = [];
			for (var j=0; j<result.value.length; j++) {
			    var row = result.value[j];
			    for (var i=0; i<row.length; i++)
				retval[result.headers[i]].push(row[i]);
			}
		    }

		} else if (callbackType == 'actions') {
		    retval = result.value;
		} else {
		    retval = (result.value.length == 0) ? {} : this.row2obj(result.value, result.headers);
		}

		retStatus.info = result.info || {};
		if (result.headers)
		    retStatus.info.headers = result.headers;

		if (userId) {
		    if (!outOfSequence && retStatus.info.prevTimestamp && this.timestamps[userId] && this.timestamps[userId].time && Math.floor(retStatus.info.prevTimestamp) != Math.floor(this.timestamps[userId].time)) {
			var errMsg = 'GoogleSheet: ERROR Timestamp mismatch; expected '+this.timestamps[userId].time+'/'+this.timestamps[userId].type+' but received '+retStatus.info.prevTimestamp+'/'+callbackType+'. Conflicting modifications from another active browser session?';
			console.log(errMsg);
			if (!Slidoc.websocketPath) {
			    retval = null;
			    retStatus.error = errMsg;
			}
		    }
		    if (retStatus.info.timestamp)                 // Update timestamp for user
			this.timestamps[userId] = {time: Math.max(retStatus.info.timestamp, (this.timestamps[userId] && this.timestamps[userId].time) || 0), type:callbackType};
		}

	    } else if (result.result == 'error' && result.error) {
		retStatus.error = err_msg ? err_msg + ';' + result.error : result.error;
	    }

	    if (result.messages)
		retStatus.messages = result.messages.split('\n');
	} catch(err) {
	    retval = null;
	    retStatus.error = 'GoogleSheet: ERROR in GoogleSheet.callback: '+err;
	    Slidoc.log(retStatus.error);
	}
    }
	
    if (outerCallback) {
        outerCallback(retval, retStatus);
    }
}

GoogleSheet.prototype.row2obj = function(row, headers) {
    headers = headers || this.headers;
    if (row.length != headers.length)
	throw('GoogleSheet: row2obj - ERROR Incorrect number of row values received from Google Sheet: expected '+headers.length+' but got '+row.length+' (Enable grade_response feature for extra grading columns?)');

    var obj = {};
    for (var j=0; j<row.length; j++)
        obj[headers[j]] = row[j];
    return obj;
}

GoogleSheet.prototype.obj2row = function(obj) {
    var row = [];
    var keys = Object.keys(obj);
    for (var j=0; j<this.headers.length; j++) {
        row.push(null);
    }
    for (var j=0; j<keys.length; j++) {
       var key = keys[j];
       if (!(key in this.columnIndex))
           throw('GoogleSheet: Invalid column header: '+key);
       row[this.columnIndex[key]] = obj[key];
    }
    return row;
}

GoogleSheet.prototype.actions = function (actions, opts, callback) {
    // Workaround for passthru actions; this could be done without a GSheet
    var params = {actions: actions};
    var keys = Object.keys(opts);
    for (var j=0; j<keys.length; j++) {
	var key = keys[j];
	params[key] = opts[key];
    }
    this.callbackCounter += 1;
    this.send(params, 'actions', callback);
}

GoogleSheet.prototype.createSheet = function (callback) {
    var params = { headers: JSON.stringify(this.headers) };
    this.callbackCounter += 1;
    this.send(params, 'createSheet', callback);
}

GoogleSheet.prototype.putRow = function (rowObj, opts, callback) {
    // opts = {get:, id:, nooverwrite:, submit:}
    // Specify opts.id to override id
    // Specify opts.get to retrieve the existing/overwritten row.
    // Specify opts.nooverwrite to not overwrite any existing row with same id
    // Specify opts.submit to update submitTimestamp
    // opts.get with opts.nooverwrite will return the existing row, or the newly inserted row.
    if (!opts.log)
	Slidoc.log('GoogleSheet.putRow:', rowObj, opts);

    if (!rowObj.id || (opts.nooverwrite && !rowObj.name))
        throw('GoogleSheet.putRow: Must provide id and name to put row');

    if (this.cacheAll)
        throw('GoogleSheet.putRow: Cannot putRow when caching');

    var row = this.obj2row(rowObj);
    var params = {row: JSON.stringify(row)};
    if (opts.id)
        params.id = opts.id;
    if (opts.get)
        params.get = '1';
    if (opts.nooverwrite)
        params.nooverwrite = '1';
    if (opts.submit)
        params.submit = '1';

    this.putSend(rowObj.id, params, 'putRow', callback);
}

GoogleSheet.prototype.putSend = function (userId, params, callType, callback) {
    if (!(userId in this.userUpdateCounter))
	this.userUpdateCounter[userId] = 0;
    
    if (!this.userUpdateCounter[userId] && this.timestamps[userId] && this.timestamps[userId].time)  // Send timestamp if no pending updates
	params.timestamp = this.timestamps[userId].time;

    this.userUpdateCounter[userId] += 1;

    this.pendingUpdates += 1;
    this.callbackCounter += 1;
    this.send(params, callType, callback);
}
    
GoogleSheet.prototype.authPutRow = function (rowObj, opts, callback, createSheet, retval, retStatus) {
    // opts = {get:, id:, nooverwrite:, submit:}
    // Fills in id, name etc. from GService.gprofile.auth before calling putRow
    Slidoc.log('GoogleSheet.authPutRow:', opts, !!callback, createSheet, retval, retStatus);
    if (createSheet) {
        // Call authPutRow after creating sheet
        this.createSheet( this.authPutRow.bind(this, rowObj, opts, callback, null) ); // createSheet=null needed to prevent looping
        return;
    } else if (retStatus && retStatus.error) {
	callback(null, retStatus);
	return;
    }

    var extObj = {};
    for (var j=0; j < this.fields.length; j++) {
        var header = this.fields[j];
        if (header in rowObj)
            extObj[header] = rowObj[header]
    }
    var auth = GService.gprofile.auth;
    extObj.id = opts.id || auth.id;
    if (opts.nooverwrite) {
	// Creating/reading row, but not updating it; copy management fields
	extObj.name = auth.displayName || '';
	for (var j=2; j<this.preHeaders.length; j++)
	    extObj[this.preHeaders[j]] = auth[this.preHeaders[j]] || '';
    }
    return this.putRow(extObj, opts, callback);
}

GoogleSheet.prototype.updateRow = function (updateObj, opts, callback) {
    // Only works with existing rows
    // Specify get to return updated row
    // opts = {get:}
    Slidoc.log('GoogleSheet.updateRow:', updateObj, opts);
    if (!updateObj.id)
        throw('GoogleSheet.updateRow: Must provide id to update row');

    var userIds = [];
    var cachedRow = null;
    if ('submitTimestamp' in updateObj) {
	// Note: If submit status is changed, cache becomes invalid
	this.cacheAll = null;
    } else if (this.cacheAll) {
	// Update headers in cached copy
	userIds = Object.keys(this.cacheAll);
	cachedRow = this.cacheAll[updateObj.id];
	if (!cachedRow)
	    throw("GoogleSheet.updateRow: id '"+updateObj.id+"'not found in cache");
    }

    var updates = [];
    if (this.headers.length) {
	for (var j=0; j<this.headers.length; j++) {
	    var key = this.headers[j];
	    if (key in updateObj) {
		updates.push( [key, updateObj[key]] );
		if (cachedRow && key != 'id' && key != 'Timestamp' && key in cachedRow) {
		    // Update cached row
		    cachedRow[key] = updateObj[key]
		    if (opts.team && cachedRow.team && key.match(/(_grade|_comments)$/)) {
			// Broadcast grade/comments to all team members in cache (to mirror what happens in the spreadsheet)
			for (var k=0; k<userIds.length; k++) {
			    var userId = userIds[k];
			    if (userId != updateObj.id && this.cacheAll[userId].team == cachedRow.team)
				this.cacheAll[userId][key] = cachedRow[key];
			}
		    }
		}
	    }
	}
	if (updates.length < Object.keys(updateObj).length)
            throw('GoogleSheet.updateRow: Invalid column header(s) found in row updates: '+Object.keys(updateObj));
    } else {
	var keys = Object.keys(updateObj);
	if (keys.length != 2)
            throw('GoogleSheet.updateRow: Only single column can be updated if no headers: '+Object.keys(updateObj));
	updates.push( ['id', updateObj.id] );
	for (var j=0; j<keys.length; j++) {
	    if (keys[j] != 'id')
		updates.push([ keys[j], updateObj[keys[j]] ]);
	}
    }

    var params = {id: updateObj.id, update: JSON.stringify(updates)};
    if (opts.get)
        params.get = '1';

    if (updates.length == 2 && updates[0][0] == 'id' && updates[1][0].slice(-5) == 'vote')
	params.vote = '1';

    this.putSend(updateObj.id, params, 'updateRow', callback);
}

GoogleSheet.prototype.delRow = function (id, callback) {
    // If !id, GService.gprofile.auth.id is used
    // callback(result, retStatus)
    // result == null on error
    // result == {} on success
    Slidoc.log('GoogleSheet.delRow:', id, !!callback);

    if (!id) id = GService.gprofile.auth.id;

    if (!id)
        throw('GoogleSheet.delRow: Null id for delRow');
    if (!callback)
        throw('GoogleSheet.delRow: Must specify callback for delRow');

    var params = {id: id, delrow: '1'};
    this.callbackCounter += 1;

    try {
	this.send(params, 'delRow', callback);
    } finally {
	// If deleting when caching, reload page
	if (this.cacheAll)
	    location.reload(true)
    }
}

GoogleSheet.prototype.getRow = function (id, opts, callback) {
    // If !id, GService.gprofile.auth.id is used
    // Specify opts.create to create new row
    // Specify opts.getheaders to get headers
    // Specify opts.getstats to getstats
    // Specify opts.late for late token in new row
    // Specify opts.resetrow for to reset row (for retakes etc.)
    // callback(result, retStatus)
    // result == null on error
    // result == {} for non-existent row
    // result == {id: ..., name: ..., } for returned row
    Slidoc.log('GoogleSheet.getRow:', id, !!callback);

    if (!id) id = GService.gprofile.auth.id;

    if (!id)
        throw('GoogleSheet.getRow: Null id for getRow');
    if (!callback)
        throw('GoogleSheet.getRow: Must specify callback for getRow');

    if (opts.resetrow) {
	// Note: If resetting row, cache becomes invalid
	this.cacheAll = null;
    } else if (this.cacheAll) {
	if (id in this.cacheAll)
	    callback(this.cacheAll[id], {error: '', messages: ['Info:FROM_CACHE:']});
	else
	    callback(null, {error: "id '"+id+"' not found in cache", messages: []});
	return;
    }

    var params = {id: id, get: '1'};
    if (opts.create)
	params.create = 'browser';
    if (opts.getheaders)
	params.getheaders = opts.getheaders;
    if (opts.getstats)
	params.getstats = opts.getstats;
    if (opts.late)
	params.late = opts.late;
    if (opts.resetrow)
	params.resetrow = opts.resetrow;
    this.callbackCounter += 1;
    this.send(params, 'getRow', callback);
}

GoogleSheet.prototype.getShare = function (colPrefix, adminState, callback) {
    // callback(result, retStatus)
    // result == null on error
    // result == {} for non-existent row
    // result == {id: ..., name: ..., } for returned row
    Slidoc.log('GoogleSheet.getShare:', colPrefix, !!callback);

    var id = adminState ? 'admin' :  GService.gprofile.auth.id;

    if (!callback)
        throw('GoogleSheet.getShare: Must specify callback for getShare');

    // Need to check cache, if not sharing
    var params = {id: id, getshare: colPrefix};
    this.callbackCounter += 1;
    this.send(params, 'getShare', callback);
}

GoogleSheet.prototype.getAll = function (callback) {
    // callback(result, retStatus)
    // result == null on error
    // result == {} for empty sheet
    // result == {id: {id: ..., name: ..., }} for returned rows
    if (!callback)
        throw('GoogleSheet: Must specify callback for getAll');

    var params = {all: '1', get: '1'};
    this.callbackCounter += 1;
    this.send(params, 'getAll', callback);
}

GoogleSheet.prototype.getRoster = function() {
    return this.roster;
}

GoogleSheet.prototype.initCache = function(allRows) {
    this.cacheAll = allRows;
    var ids = Object.keys(allRows);
    this.roster = [];
    for (var j=0; j<ids.length; j++) {
	if (ids[j] && ids[j] != MAXSCORE_ID) {
	    var rowObj = allRows[ids[j]];
	    if (rowObj.name && rowObj.Timestamp) {
		this.roster.push([rowObj.name, ids[j], rowObj.team||'']);
		this.timestamps[ids[j]] = {time:(new Date(rowObj.Timestamp)).getTime(), type:'initCache'};
	    }
	}
    }
    this.roster.sort(function(a,b){ if (a[0] != b[0]) {return (a[0] > b[0]) ? 1 : -1} else {return (a[1] > b[1]) ? 1 : -1}});
    Slidoc.log('GoogleSheet.initCache:', this.roster);
}

GoogleSheet.prototype.getCachedRow = function(userId) {
    return this.cacheAll[userId] || null;
}
    
GService.sheetIsLocked = function () {
    if (Slidoc.websocketPath)
	return wsock.locked;
    else
	return '';
}

GService.switchUser = function (auth, userId, switchUserToken) {
    if (!auth.graderKey)
	throw('Only grader can switch user');
    auth.displayName = userId;
    auth.id = userId;
    auth.email = (userId.indexOf('@')>0) ? userId : '';
    auth.altid = '';
    if (switchUserToken)
	auth.token = userId+auth.graderKey;
}
    
GService.GoogleSheet = GoogleSheet;

GService.gprofile = new GoogleProfile(CLIENT_ID, API_KEY, LOGIN_BUTTON_ID, AUTH_CALLBACK);

GService.onGoogleAPILoad = function () {
    Slidoc.log('GService.onGoogleAPILoad:');
    GService.gprofile.onLoad();
}

})(GService, CLIENT_ID, API_KEY, LOGIN_BUTTON_ID, AUTH_CALLBACK);
