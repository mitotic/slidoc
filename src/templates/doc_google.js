// JS include file for Google services
// Before including this script, define CLIENT_ID, API_KEY, LOGIN_BUTTON_ID, AUTH_CALLBACK and
//   function onGoogleAPILoad() { GService.onGoogleAPILoad(); }
// After this script, include script with src="https://apis.google.com/js/client.js?onload=onGoogleAPILoad"

var TRUNCATE_DIGEST = 8;

function gen_hmac_token(key, message) {
    // Generates token using HMAC key
    return btoa(md5(message, key, true)).slice(0,TRUNCATE_DIGEST);
}

function gen_user_token(key, user_id) {
    // Generates user token using HMAC key
    return gen_hmac_token(key, 'id:'+user_id);
}

function gen_admin_token(key, user_id) {
    // Generates user token using HMAC key
    return gen_hmac_token(key, 'admin:'+user_id);
}

function gen_late_token(key, email, session_name, date_str) {
    // Use date string of the form '1995-12-17T03:24'
    return date_str+':'+gen_hmac_token(key, 'late:'+email+':'+session_name+':'+date_str);
}

var GService = {};

function GServiceJSONP(callback_index, json_text) {
    GService.handleJSONP(callback_index, json_text);
}

(function (GService) {
// http://railsrescue.com/blog/2015-05-28-step-by-step-setup-to-send-form-data-to-google-sheets/

var jsonpCounter = 0;
var jsonpRequests = {};

function requestJSONP(url, queryStr, callback) {
    var suffix = '&prefix=GServiceJSONP';
    if (callback) {
	jsonpCounter += 1;
	jsonpRequests[jsonpCounter] = [callback, url];
	suffix += '&callback='+jsonpCounter;
    }

    url += '?'+queryStr+suffix;
    console.log('requestJSONP:', url);

    var head = document.head;
    var script = document.createElement("script");

    script.setAttribute("src", url);
    head.appendChild(script);
    head.removeChild(script);
}

GService.handleJSONP = function(callback_index, json_obj) {
    console.log('GService.handleJSONP:', callback_index);
    if (!callback_index)
	return;
    if (!(callback_index in jsonpRequests)) {
	console.log('GService.handleJSONP: Error - Invalid JSONP callback index: '+callback_index);
	return;
    }
    var callback = jsonpRequests[callback_index][0];
    delete jsonpRequests[callback_index];
    if (callback)
	callback(json_obj || null);
}
    
function handleCallback(responseText, callback){
    if (!callback)
	return;
    var obj = null;
    var msg = '';
    try {
        obj = JSON.parse(responseText)
    } catch (err) {
        console.log('JSON parsing error:', err, responseText);
        msg = 'JSON parsing error';
    }
    callback(obj, msg);
}

GService.sendData = function (data, url, callback, useJSONP) {
  /// callback(result_obj, optional_err_msg)

  var XHR = new XMLHttpRequest();
  var urlEncodedData = "";
  var urlEncodedDataPairs = [];

  XHR.onreadystatechange = function () {
      var DONE = 4; // readyState 4 means the request is done.
      var OK = 200; // status 200 is a successful return.
      if (XHR.readyState === DONE) {
        if (XHR.status === OK) {
          console.log('XHR: '+XHR.status, XHR.responseText);
	  handleCallback(XHR.responseText, callback);
        } else {
          console.log('XHR Error: '+XHR.status, XHR.responseText);
          if (callback)
              callback(null, 'Error in HTTP request')
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
  console.log('sendData:', urlEncodedData, url, useJSONP);
  // And finally, We send our data.
  XHR.send(urlEncodedData);
}

function GoogleAuth(clientId, apiKey, loginButtonId, authCallback) {
    //Include script src="https://apis.google.com/js/client.js?onload=handleClientLoad"
    // authCallback(this.auth)
    this.clientId = clientId;
    this.apiKey = apiKey;
    this.loginButtonId = loginButtonId;
    this.authCallback = authCallback || null;
    this.scopes = 'https://www.googleapis.com/auth/userinfo.email';
    this.auth = null;
}

GoogleAuth.prototype.onLoad = function () {
    console.log('GoogleAuth.onLoad:');
    gapi.client.setApiKey(this.apiKey);
    window.setTimeout(this.requestAuth.bind(this, true), 5);
}


GoogleAuth.prototype.requestAuth = function (immediate) {
    console.log('GoogleAuth.requestAuth:');
    gapi.auth.authorize({client_id: this.clientId, scope: this.scopes, immediate: immediate},
                        this.onAuth.bind(this));
    return false;
}

GoogleAuth.prototype.onAuth = function (result) {
    console.log('GoogleAuth.onAuth:', result);
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

GoogleAuth.prototype.requestUserInfo = function () {
    console.log('GoogleAuth.requestUserInfo:');
    var req = gapi.client.plus.people.get({userId: 'me'});
    req.execute(this.onUserInfo.bind(this));
}

GoogleAuth.prototype.onUserInfo = function (resp) {
    console.log('GoogleAuth.onUserInfo:', resp);
    if (!resp.emails || !resp.id)
        return;

    for (var j=0; j<resp.emails.length; j++) {
        var email = resp.emails[j];
        if (email.type == 'account') {
            this.auth = {email: email.value.toLowerCase()};
            break;
        }
    }
    if (!this.auth)
        return;
    this.auth.id = resp.id;
    var comps = resp.displayName.split(/\s+/);
    var name = (comps.length > 1) ? comps.slice(-1)+', '+comps.slice(0,-1).join(' ') : resp.displayName;
    this.auth.displayName = name || this.auth.email;
    this.auth.userName = this.auth.email;   // Use lowercased email as user name
    this.auth.token = resp.token || '';
    this.auth.domain = resp.domain || '';
    this.auth.image = (resp.image && resp.image.url) ? resp.image.url : ''; 
    this.auth.adminKey = resp.adminKey || '';
    if (this.authCallback)
	this.authCallback(this.auth);
}

GoogleAuth.prototype.promptUserInfo = function (user, msg, callback) {
    if (user && user.slice(-7) == '@slidoc')
	user = user.slice(0, -7);
    var loginElem = document.getElementById('gdoc-login-popup');
    var loginOverlay = document.getElementById('gdoc-login-overlay');
    var loginUserElem = document.getElementById('gdoc-login-user');
    var loginTokenElem = document.getElementById('gdoc-login-token');
    loginUserElem.value = user || '';
    document.getElementById('gdoc-login-message').textContent = msg || '';

    var gauth = this;
    document.getElementById('gdoc-login-button').onclick = function (evt) {
	loginElem.style.display = 'none';
        loginOverlay.style.display = 'none';
	var loginUser = loginUserElem.value;
	var loginToken = loginTokenElem.value;

	if (!loginUser || !loginUser.trim()) {
	    alert('Please provide user name for login');
	    return false;
	}
	loginUser = loginUser.trim().toLowerCase();

	var email = (loginUser.indexOf('@') >= 0) ? loginUser : loginUser.replace(/[-.,'\s]+/g,'-')+'@slidoc';
	var adminKey = '';
	if (loginToken.slice(0,6) == 'admin:') {
	    // A token of the form 'admin:hmac_key' is used by the admin user to sign on as any user
	    adminKey = loginToken.slice(6);
	    loginToken = gen_admin_token(adminKey, 'admin');
	}
	if (callback)
	    this.authCallback = callback;
	gauth.onUserInfo({adminKey: adminKey, id: email, displayName: loginUser, token: loginToken,
			  emails: [{type: 'account', value:email}] });
    }
	
    loginElem.style.display = 'block';
    loginOverlay.style.display = 'block';
    window.scrollTo(0,0);
}


function GoogleSheet(url, sheetName, fields, useJSONP, id, token, admin) {
    this.url = url;
    this.fields = fields;
    this.sheetName = sheetName;
    this.useJSONP = !!useJSONP;
    this.id = id || '';
    this.token = token || '';
    this.admin = admin || '';
    this.headers = ['name', 'id', 'email', 'user', 'Timestamp'].concat(fields);
    this.created = null;
    this.callbackCounter = 0;
    this.columnIndex = {};
    for (var j=0; j<this.headers.length; j++)
        this.columnIndex[this.headers[j]] = j;
}

GoogleSheet.prototype.send = function(params, callType, callback) {
    params = JSON.parse(JSON.stringify(params));
    if (this.id)
	params.id = this.id;
    if (this.token)
	params.token = this.token;
    if (this.admin)
	params.admin = this.admin;
    GService.sendData(params, this.url, this.callback.bind(this, callType, callback),
		      this.useJSONP);
}
    
GoogleSheet.prototype.callback = function (callbackType, outerCallback, result, err_msg) {
    // outerCallback(obj, err_msg, messages)
    // obj == null on error
    // obj == {} for non-existent row
    // obj == {id: ..., name: ..., } for returned row
    console.log('GoogleSheet: callback', callbackType, result, err_msg);
    this.callbackCounter -= 1;

    if (!result)
        console.log('GoogleSheet: '+callbackType+' callback: ERROR '+err_msg);

    if (callbackType == 'createSheet')
        this.created = result && result.result == 'success';

    if (outerCallback) {
        var retval = null;
	var messages = null;
        if (result) {
	    if (result.result == 'success' && result.row)
		retval = (result.row.length == 0) ? {} : this.row2obj(result.row);

	    else if (result.result == 'error' && result.error)
		err_msg = err_msg ? err_msg + ';' + result.error : result.error;

	    if (result.messages)
		messages = result.messages.split('\n');
	}
        outerCallback(retval, err_msg, messages);
    }
}

GoogleSheet.prototype.row2obj = function(row) {
    if (row.length != this.headers.length) {
        console.log('GoogleSheet: row2obj: row length error: got '+row.length+' but expected '+this.headers.length);
        return null;
    }
    var obj = {};
    for (var j=0; j<row.length; j++)
        obj[this.headers[j]] = row[j];
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

function gdocAbort(msg) {
    document.body.textContent = msg;
    throw('Aborted: '+msg);
}

GoogleSheet.prototype.checkCreated = function () {
    if (!this.created)
        gdocAbort('GoogleSheet: Sheet '+this.sheetName+' not created');
}

GoogleSheet.prototype.createSheet = function (callback) {
    var params = { sheet: this.sheetName, headers: JSON.stringify(this.headers) };
    this.callbackCounter += 1;
    this.send(params, 'createSheet', callback);
}

GoogleSheet.prototype.putRow = function (rowObj, nooverwrite, callback, get, createSheet, retval, err_msg, messages) {
    // Specify get to retrieve the existing/overwritten row.
    // Specify nooverwrite to not overwrite any existing row with same id
    // Get with nooverwrite will return the existing row, or the newly inserted row.
    console.log('GoogleSheet.putRow:', createSheet);
    if (!rowObj.id || !rowObj.name)
        throw('GoogleSheet: Must provide id and name to put row');
    if (createSheet && this.created == null) {
        // Call putRow after creating sheet
        this.createSheet( this.putRow.bind(this, rowObj, nooverwrite, callback, get, null) ); // null needed to prevent looping
        return;
    } else if (err_msg) {
	callback(null, err_msg, messages);
    }
    this.checkCreated();
    var row = this.obj2row(rowObj);
    var params = {sheet: this.sheetName, row: JSON.stringify(row)};
    if (nooverwrite)
        params['nooverwrite'] = '1';
    if (get)
        params['get'] = '1';
    this.callbackCounter += 1;
    this.send(params, 'putRow', callback);
}

GoogleSheet.prototype.updateRow = function (updateObj, callback, get) {
    // Only works with existing rows
    // Specify get to return updated row
    if (!updateObj.id)
        throw('GoogleSheet: Must provide id to update row');
    this.checkCreated();
    var updates = [];
    var keys = Object.keys(updateObj);
    for (var j=0; j<keys.length; j++) {
       var key = keys[j];
       if (!(key in this.columnIndex))
           throw('GoogleSheet: Invalid column header: '+key);
       updates.push( [key, updateObj[key]] );
    }
    var params = {sheet: this.sheetName, id: updateObj.id, get: (get?'1':''), update: JSON.stringify(updates)};
    this.callbackCounter += 1;
    this.send(params, 'updateRow', callback);
}

GoogleSheet.prototype.getRow = function (id, callback, createSheet, retval, err_msg, messages) {
    // callback(obj, err_msg, messages)
    // obj == null on error
    // obj == {} for non-existent row
    // obj == {id: ..., name: ..., } for returned row
    if (!callback)
        throw('GoogleSheet: Must specify callback for getRow');

    if (createSheet && this.created == null) {
        // Call getRow after creating sheet
        this.createSheet( this.getRow.bind(this, id, callback, null) );
        return;
    } else if (err_msg) {
	callback(null, err_msg, messages);
    }
    this.checkCreated();
    var params = {sheet: this.sheetName, id: id, get: '1'};
    this.callbackCounter += 1;
    this.send(params, 'getRow', callback);
}


function GoogleAuthSheet(url, sheetName, fields, auth, useJSONP, adminUser) {
    if (!auth || !auth.id)
	throw('GoogleAuthSheet: Error - auth.id not defined!');
    this.gsheet = new GoogleSheet(url, sheetName, fields, useJSONP, auth.id, auth.token, adminUser);
    this.auth = auth;
    this.admin = adminUser || '';
}

GoogleAuthSheet.prototype.extendObj = function (obj, fullRow) {
    var extObj = {};
    for (var j=0; j < this.gsheet.fields.length; j++) {
        var header = this.gsheet.fields[j];
        if (header in obj)
            extObj[header] = obj[header]
    }
    if ('Timestamp' in obj)
        extObj.Timestamp = obj.Timestamp;
    extObj.id = this.auth.id;
    if (fullRow) {
	extObj.name = this.auth.displayName || '';
	extObj.email = this.auth.email || '';
	extObj.user = this.auth.userName || '';
    }
    return extObj;
}

GoogleAuthSheet.prototype.createSheet = function (callback) {
    return this.gsheet.createSheet(callback);
}

GoogleAuthSheet.prototype.putRow = function (rowObj, nooverwrite, callback, get, createSheet) {
    return this.gsheet.putRow(this.extendObj(rowObj, true), nooverwrite, callback, get, createSheet);
}

GoogleAuthSheet.prototype.updateRow = function (updateObj, callback, get) {
    return this.gsheet.updateRow(this.extendObj(updateObj), callback, get);
}

GoogleAuthSheet.prototype.getRow = function (callback, createSheet) {
    return this.gsheet.getRow(this.auth.id, callback, createSheet);
}

GService.GoogleSheet = GoogleSheet;
GService.GoogleAuthSheet = GoogleAuthSheet;

GService.gauth = new GoogleAuth(CLIENT_ID, API_KEY, LOGIN_BUTTON_ID, AUTH_CALLBACK);

GService.onGoogleAPILoad = function () {
    console.log('GService.onGoogleAPILoad:');
    GService.gauth.onLoad();
}

})(GService, CLIENT_ID, API_KEY, LOGIN_BUTTON_ID, AUTH_CALLBACK);
