code = {

    setup: { initSetup: function() {Slidoc.log('SlidocPlugins.code.setup.initSetup:');},
	     initSetupSlide: function(slideId) {Slidoc.log('SlidocPlugins.code.setup.initSetupSlide:', slideId);}
	   },

    global: { initGlobal: function() {Slidoc.log('SlidocPlugins.code.global.initGlobal:');}
	   },

    disable: function() {
	Slidoc.log('SlidocPlugins.code.disable:');
	var textAreaElem = document.getElementById(this.pluginId+'-textarea');
	var checkButton = document.getElementById(this.pluginId+'-check-button');
	textAreaElem.disabled = 'disabled';
	checkButton.style.display = 'none';
    },

    display: function (response, pluginResp) {
	Slidoc.log('SlidocPlugins.code.display:', this, response, pluginResp);
	var textareaElem = document.getElementById(this.pluginId+'-textarea');
	textareaElem.value = response || '';
	codeResponseCallback.bind(this)(false, null, response, pluginResp);
    },

    response: function (retry, callback) {
	Slidoc.log('SlidocPlugins.code.response:', this, retry, !!callback);
	var inputValue = this.getInput(this.pluginId);
	checkCode(this.slideId+'', this.qattributes, inputValue, false,
		  codeResponseCallback.bind(this, retry, callback, inputValue) );
    },

    checkCode: function (elem) {
	Slidoc.log('SlidocPlugins.code.checkCode:', elem);
	checkCode(this.slideId+'', this.qattributes, this.getInput(this.pluginId), true,
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
		SlidocPluginManager.retryAnswer(msg);
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

function checkCode(slide_id, question_attrs, user_code, checkOnly, callback) {
    // Execute code and compare output to expected output
    // callback( {name:'code', score:1/0/null, invalid: invalid_msg, output:output, tests:0/1/2} )
    // invalid_msg => syntax error when executing user code
    Slidoc.log('checkCode:', slide_id, question_attrs, user_code, checkOnly);

    if (!question_attrs.test || !question_attrs.output) {
	Slidoc.log('checkCode: Error - Test/output code checks not found in '+slide_id);
	return callback( {name:'code', score:null, invalid:'', output:'Not checked', tests:0} );
    }

    var codeType = question_attrs.qtype;

    var codeCells = [];
    if (question_attrs.input) {
	for (var j=1; j<=question_attrs.input; j++) {
	    // Execute all input cells
	    var inputCell = document.getElementById('slidoc-block-input-'+j);
	    if (!inputCell) {
		Slidoc.log('checkCode: Error - Input cell '+j+' not found in '+slide_id);
		return callback({name:'code', score:null, invalid:'', output:'Missing input cell'+j, tests:0});
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
	    return callback({name:'code', score:0, invalid:stderr, output:'', tests:(index>0)?(index-1):0});
	}
	if (index > 0 && !score) {
	    Slidoc.log('checkCodeAux: Error in test cell in '+slide_id, msg);
	    // Do not display actual second check output (to avoid leaking test details)
	    var outmsg = (index == 1) ? stdout : 'Second check failed!'
	    return callback({name:'code', score:score, invalid:'', output:outmsg, tests:index-1});
	}

	// Execute test code
	while (index < ntest) {
	    var testCell = document.getElementById('slidoc-block-test-'+question_attrs.test[index]);
	    if (!testCell) {
		Slidoc.log('checkCodeAux: Error - Test cell '+question_attrs.test[index]+' not found in '+slide_id);
		return callback({name:'code', score:null, invalid:'', output:'Missing test cell'+(index+1), tests:index});
	    }
	    var testCode = testCell.textContent.trim();
	    
	    var outputCell = document.getElementById('slidoc-block-output-'+question_attrs.output[index]);
	    if (!outputCell) {
		Slidoc.log('checkCodeAux: Error - Test output cell '+question_attrs.output[index]+' not found in '+slide_id);
		return callback({name:'code', score:null, invalid:'', output:'Missing test output'+(index+1), tests:index});
	    }
	    var expectOutput = outputCell.textContent.trim();
	    
	    return execCode(codeType, codeCells.concat(testCode).join('\n\n'), expectOutput, checkCodeAux.bind(null, index+1, 'test code'+index));
	}
	return callback({name:'code', score:(ntest?1:null), invalid:'', output:'', tests:ntest});
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

    if (codeType == 'text/x-test') {
	if (code.indexOf('Syntax error') > -1)
	    callback(null, null, 'Syntax error');
	else if (code.indexOf('Semantic error') > -1)
	    callback(expect ? 0 : null, 'Incorrect output', '');
	else if (expect)
	    callback((expect == 'Correct output')?1:0, 'Correct output', '');
	else
	    callback(null, 'Correct output', '');
    } else if (codeType == 'text/x-python') {
	if (!window.Sk) {
	    alert('Error: Skulpt module not loaded');
	    return;
	}
	skRunit(code, execCodeOut.bind(null, expect, callback), execCodeErr.bind(null, callback));
    } else if (codeType == 'text/x-javascript') {
	execJS(code, execCodeOut.bind(null, expect, callback), execCodeErr.bind(null, callback));
    }
}

function execCodeOut(expect, callback, text) {
    Slidoc.log('execCodeOut:', expect, text);
    var score = expect ? ((expect.trim() == text.trim())?1:0) : '';
    callback(score, text, '');
}

function execCodeErr(callback, err) {
    Slidoc.log('execCodeErr:', err);
    callback(null, '', err.toString());
}


/*
PluginHead:
<style>
.%(plugin_label)s-textarea,
  .%(plugin_label)s-check-button {display: block;}
.%(plugin_label)s-output { opacity: 0.7; }
</style>

PluginBody:
<button id="%(plugin_id)s-check-button" class="slidoc-clickable %(plugin_label)s-check-button" onclick="SlidocPluginManager.action('%(plugin_name)s','checkCode','%(plugin_slide_id)s',this);">Check</button>
<textarea id="%(plugin_id)s-textarea" class="%(plugin_label)s-textarea" cols="60" rows="5"></textarea>
<pre><code id="%(plugin_id)s-output" class="%(plugin_label)s-output"></code></pre>
*/
