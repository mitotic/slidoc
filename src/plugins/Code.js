Code = {
    // Code execution and testing plugin
    // Invoke as Answer: Code/python OR Code/javascript OR Code/test
    setup: { initSetup: function() {Slidoc.log('Slidoc.Plugins.Code.setup.initSetup:');},
	   },

    global: { initGlobal: function() {Slidoc.log('Slidoc.Plugins.Code.global.initGlobal:');}
	   },

    init: function () {
	Slidoc.log('Slidoc.Plugins.Code.init:');
    },

    disable: function (displayCorrect) {
	Slidoc.log('Slidoc.Plugins.Code.disable:', displayCorrect);
	var textAreaElem = document.getElementById(this.pluginId+'-textarea');
	var checkButton = document.getElementById(this.pluginId+'-check-button');
	textAreaElem.disabled = 'disabled';
	checkButton.style.display = 'none';
    },

    display: function (response, pluginResp) {
	Slidoc.log('Slidoc.Plugins.Code.display:', this, response, pluginResp);
	var textareaElem = document.getElementById(this.pluginId+'-textarea');
	textareaElem.value = response || '';
	codeResponseCallback.bind(this)(false, null, response, pluginResp);
    },

    response: function (retry, callback) {
	Slidoc.log('Slidoc.Plugins.Code.response:', this, retry, !!callback);
	var inputValue = this.getInput(this.pluginId);
	checkCode(this.name, this.slideId+'', this.qattributes, inputValue, false,
		  codeResponseCallback.bind(this, retry, callback, inputValue) );
    },

    checkCode: function (elem) {
	Slidoc.log('Slidoc.Plugins.Code.checkCode:', elem);
	checkCode(this.name, this.slideId+'', this.qattributes, this.getInput(this.pluginId), true,
		  checkCodeCallback.bind(this) );
    },

    getInput: function (pluginId) {
	var textareaElem = document.getElementById(pluginId+'-textarea');
	return textareaElem.value;
    }
}

function checkCodeCallback(pluginResp) {
    Slidoc.log('checkCodeCallback:', this, pluginResp)
    var outputElem = document.getElementById(this.pluginId+'-output');
    var ntest = this.qattributes.test ? this.qattributes.test.length : 0;
    var msg = 'Checked';
    var code_msg = msg;
    if (pluginResp.invalid) {
	msg = 'Syntax/runtime error!';
	code_msg = 'Error output:\n'+pluginResp.invalid;
    } else if (pluginResp.score < 1) {
	if (ntest > 1)
	    msg = pluginResp.score ? 'First check failed partially!' : ' First check failed!';
	else
	    msg = pluginResp.score ? 'Partially incorrect output!' : 'Incorrect output!';
	code_msg = 'Incorrect output:\n'+pluginResp.output;
    } else if (pluginResp.score === 1) {
	msg = (ntest > 1) ? 'First check passed!' : 'Valid output!';
	code_msg = msg;
    }
    outputElem.textContent = code_msg;
    Slidoc.showPopup(msg);
}

function codeResponseCallback(retry, callback, response, pluginResp) {
    Slidoc.log('codeResponseCallback:', this, retry, !!callback, response, pluginResp)
    var outputElem = document.getElementById(this.pluginId+'-output');
    if (pluginResp) {
	var ntest = this.qattributes.test ? this.qattributes.test.length : 0;
	var code_msg = '';
	if (pluginResp.invalid) {
	    code_msg = 'Error output:\n'+pluginResp.invalid;
	} else if (pluginResp.score === 1) {
	    code_msg = (pluginResp.tests > 1) ? 'Second check passed!' : 'Valid output';
	} else if (isNumber(pluginResp.score)) {

	    if (retry && ntest > 1) {
		// Retry only if second check is present
		var msg;
		if (pluginResp.tests > 0)
		    msg = pluginResp.score ? 'Second check failed partially!' : ' Second check failed!';
		else
		    msg = (pluginResp.score ? 'Partially incorrect output!' : 'Incorrect output!')+pluginResp.output;
		Slidoc.PluginRetry(msg);
		return;
	    }

	    code_msg = 'Incorrect output:\n'+pluginResp.output;
	} else {
	    code_msg = 'Output:\n'+(pluginResp.output || '');
	}
	outputElem.textContent = code_msg;
    }
    if (callback)
	callback(response, pluginResp);
}

function checkCode(pluginName, slide_id, question_attrs, user_code, checkOnly, callback) {
    // Execute code and compare output to expected output
    // callback( {name:'Code', score:1/0/null, invalid: invalid_msg, output:output, tests:0/1/2} )
    // invalid_msg => syntax error when executing user code
    Slidoc.log('checkCode:', slide_id, question_attrs, user_code, checkOnly);

    if (!question_attrs.test || !question_attrs.output) {
	Slidoc.log('checkCode: Error - Test/output code checks not found in '+slide_id);
	return callback( {name:pluginName, score:null, invalid:'', output:'Not checked', tests:0} );
    }

    var codeType = question_attrs.qtype;

    var codeCells = [];
    if (question_attrs.input) {
	for (var j=1; j<=question_attrs.input; j++) {
	    // Execute all input cells
	    var inputCell = document.getElementById('slidoc-block-input-'+j);
	    if (!inputCell) {
		Slidoc.log('checkCode: Error - Input cell '+j+' not found in '+slide_id);
		return callback({name:pluginName, score:null, invalid:'', output:'Missing input cell'+j, tests:0});
	    }
	    codeCells.push( inputCell.textContent.trim() );
	}
    }

    codeCells.push(user_code);
    var ntest = question_attrs.test.length;
    if (checkOnly) ntest = Math.min(ntest, 1);

    function checkCodeAux(index, msg, score, stdout, stderr) {
	Slidoc.log('checkCodeAux:', index, msg, score, stdout, stderr);
	if (stderr) {
	    Slidoc.log('checkCodeAux: Error', msg, stderr);
	    return callback({name:pluginName, score:0, invalid:stderr, output:'', tests:(index>0)?(index-1):0});
	}
	if (index > 0 && !score) {
	    Slidoc.log('checkCodeAux: Error in test cell in '+slide_id, msg);
	    // Do not display actual second check output (to avoid leaking test details)
	    var outmsg = (index == 1) ? stdout : 'Second check failed!'
	    return callback({name:pluginName, score:score, invalid:'', output:outmsg, tests:index-1});
	}

	// Execute test code
	while (index < ntest) {
	    var testCell = document.getElementById('slidoc-block-test-'+question_attrs.test[index]);
	    if (!testCell) {
		Slidoc.log('checkCodeAux: Error - Test cell '+question_attrs.test[index]+' not found in '+slide_id);
		return callback({name:pluginName, score:null, invalid:'', output:'Missing test cell'+(index+1), tests:index});
	    }
	    var testCode = testCell.textContent.trim();
	    
	    var outputCell = document.getElementById('slidoc-block-output-'+question_attrs.output[index]);
	    if (!outputCell) {
		Slidoc.log('checkCodeAux: Error - Test output cell '+question_attrs.output[index]+' not found in '+slide_id);
		return callback({name:pluginName, score:null, invalid:'', output:'Missing test output'+(index+1), tests:index});
	    }
	    var expectOutput = outputCell.textContent.trim();
	    
	    return execCode(codeType, codeCells.concat(testCode).join('\n\n'), expectOutput, checkCodeAux.bind(null, index+1, 'test code'+index));
	}
	return callback({name:pluginName, score:(ntest?1:null), invalid:'', output:'', tests:ntest});
    }

    checkCodeAux(0, '', null, '', '');
}


// Javascript code execution
var consoleOut = function() {};
if (window.console && window.console.log)
    consoleOut = function() {window.console.log.apply(window.console, arguments)};

function execJS(code, outCallback, errCallback) {
    // Evaluate JS expression
    try {
	outCallback(''+eval(code));
    } catch(err) {
	errCallback(''+err);
    }
}

// Skulpt python code exection
function skBuiltinRead(x) {
    if (Sk.builtinFiles === undefined || Sk.builtinFiles["files"][x] === undefined)
            throw "File not found: '" + x + "'";
    return Sk.builtinFiles["files"][x];
}

function skRunit(code, outCallback, errCallback) { 
    var skOutBuffer = [];
    function skOutf(text) { 
	Slidoc.log('skOutf:', text, skOutBuffer);
	skOutBuffer.push(text);
    } 

    Sk.pre = "output";
    Sk.configure({output:skOutf, read:skBuiltinRead}); 
    //(Sk.TurtleGraphics || (Sk.TurtleGraphics = {})).target = 'mycanvas';
    var myPromise = Sk.misceval.asyncToPromise(function() {
	return Sk.importMainWithBody("<stdin>", false, code, true);
    });
    myPromise.then(function(mod) {
	Slidoc.log('skSuccess:', 'success', skOutBuffer);
	outCallback(skOutBuffer.join(''));
	skOutBuffer = [];
    },
    function(err) {
         Slidoc.log('skErr:', err.toString());
	 errCallback(err);
    });
}

function execCode(codeType, code, expect, callback) {
    // callback(score, stdout, stderr)
    // stderr => syntax error (score == null)
    // If !expect then score == null
    // Otherwise score = 1 for (expect == stdout), 0 otherwise
    Slidoc.log('execCode:', codeType, code, expect);

    if (codeType == 'Code/test') {
	if (code.indexOf('Syntax error') > -1)
	    callback(null, null, 'Syntax error');
	else if (code.indexOf('Semantic error') > -1)
	    callback(expect ? 0 : null, 'Incorrect output', '');
	else if (expect)
	    callback((expect == 'Correct output')?1:0, 'Correct output', '');
	else
	    callback(null, 'Correct output', '');
    } else if (codeType == 'Code/python') {
	if (!window.Sk) {
	    alert('Error: Skulpt module not loaded');
	    return;
	}
	skRunit(code, execCodeOut.bind(null, expect, callback), execCodeErr.bind(null, callback));
    } else if (codeType == 'Code/javascript') {
	execJS(code, execCodeOut.bind(null, expect, callback), execCodeErr.bind(null, callback));
    }
}

function execCodeOut(expect, callback, text) {
    Slidoc.log('execCodeOut:', expect, text);
    var score = scoreCodeOutput(expect, text);
    callback(score, text.trim(), '');
}

function scoreCodeOutput(expect, response) {
    // Compares space-separated list of text and/or numeric output from code to expected values (to within 0.01%)
    expect = expect.trim().toLowerCase();
    response = response.trim().toLowerCase();
    if (!expect)
	return '';

    var expectComps, responseComps;
    if (expect.indexOf(' ') > 0) {
	// Normalize spaces
	expect = expect.replace(/\s+/g,' ');
	response = response.replace(/\s+/g,' ');
	expectComps = expect.split(/\s+/);
	responseComps = response.split(/\s+/);
    } else {
	// Strip all spaces from response
	response = response.replace(/\s+/g,'');
	expectComps = [expect];
	responseComps = [response];
    }
    if (expectComps.length != responseComps.length)
	return 0;
    for (var j=0; j<expectComps.length; j++) {
	var expNum = Slidoc.parseNumber(expectComps[j]);
	if (expNum == null) {
	    // Compare text
	    if (expectComps[j] != responseComps[j])
		return 0;
	} else {
	    // Expecting the correct number (within 0.01%)
	    var epsilon = 0.0001*Math.abs(expNum ? expNum : 1);
	    var respNum = Slidoc.parseNumber(responseComps[j]);
	    
	    if (respNum == null || Math.abs(respNum-expNum) > epsilon)
		return 0;
	}
    }
    return 1;
}


function execCodeErr(callback, err) {
    Slidoc.log('execCodeErr:', err);
    callback(null, '', err.toString());
}


/* PluginHead: ^(javascript|python|test)$
<style>
.%(pluginLabel)s-textarea,
  .%(pluginLabel)s-check-button {display: block;}
.%(pluginLabel)s-output { opacity: 0.7; }
</style>

PluginBody:
<button id="%(pluginId)s-check-button" class="slidoc-clickable %(pluginLabel)s-check-button" onclick="Slidoc.PluginMethod('%(pluginName)s','%(pluginSlideId)s','checkCode',this);">Check</button>
<textarea id="%(pluginId)s-textarea" class="%(pluginLabel)s-textarea" cols="60" rows="5"></textarea>
<pre><code id="%(pluginId)s-output" class="%(pluginLabel)s-output"></code></pre>
*/
