Code = {
    // Code execution and testing plugin
    // Invoke as Answer: Code/python OR Code/javascript OR Code/test
    setup: { initSetup: function() {Slidoc.log('Slidoc.Plugins.Code.setup.initSetup:');},
	   },

    global: { initGlobal: function() {Slidoc.log('Slidoc.Plugins.Code.global.initGlobal:');}
	   },

    init: function () {
	Slidoc.log('Slidoc.Plugins.Code.init:');
	var textAreaElem = document.getElementById(this.pluginId+'-textarea');
	if (textAreaElem && this.qattributes.fillable)
	    textAreaElem.style.display = 'none';
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
	this.displayInput(response || '');
	codeResponseCallback.bind(this)(false, null, response, pluginResp);
    },

    displayInput: function (inputValue) {
	Slidoc.log('Slidoc.Plugins.Code.displayInput:', this);
	var lines = inputValue.split('\n');
	var html = [];
	for (var j=0; j<lines.length; j++) {
	    if (lines[j] || j < lines.length-1)
		html.push('<code>'+lines[j]+'</code>');
	}
	var inputElem = document.getElementById(this.pluginId+'-input');
	if (inputElem)
	    inputElem.innerHTML = html.join('\n');
    },

    response: function (retry, callback) {
	Slidoc.log('Slidoc.Plugins.Code.response:', this, retry, !!callback);
	var inputValue = this.getInput(this.pluginId);
	this.displayInput(inputValue);
	checkCode(this.name, this.slideId+'', this.qattributes, inputValue, false,
		  codeResponseCallback.bind(this, retry, callback, inputValue) );
    },

    checkCode: function (elem) {
	Slidoc.log('Slidoc.Plugins.Code.checkCode:', elem);
	var inputValue = this.getInput(this.pluginId);
	this.displayInput(inputValue);
	checkCode(this.name, this.slideId+'', this.qattributes, inputValue, true,
		  checkCodeCallback.bind(this) );
    },

    getInput: function (pluginId) {
	var fillableElem = document.getElementById(this.slideId+'-block-fillable');
	if (fillableElem) {
	    var inputElems = fillableElem.getElementsByClassName('slidoc-fillable-input');
	    [].forEach.call(inputElems, function(elem) { elem.textContent = elem.value; });
	    return fillableElem.textContent;
	}
	var textareaElem = document.getElementById(pluginId+'-textarea');
	return textareaElem.value;
    }
}

function checkCodeCallback(pluginResp) {
    Slidoc.log('checkCodeCallback:', this, pluginResp)
    var outputElem = document.getElementById(this.pluginId+'-output');
    var ntest = this.qattributes.test ? this.qattributes.test.length : 0;
    var nhide = this.qattributes.hiddentest || 0;
    var msg = '';
    var output = pluginResp.output || '';
    if (pluginResp.invalid) {
	msg = 'Syntax/runtime error! \n'+pluginResp.invalid;
	output += renderCode(pluginResp.invalid.trim(), '', 'slidoc-code-invalid');
    } else if (pluginResp.score === 0) {
	msg = 'All checks failed';
    } else if (pluginResp.score === 1) {
	msg = nhide ? 'First ' + pluginResp.tests + ' checks passed!' : 'All checks passed!';
    } else {
	msg = 'Some checks failed!';
    }
    //Slidoc.showPopup(msg);
    output += renderCode(msg, '', 'slidoc-code-status');
    outputElem.innerHTML = output;
}

function codeResponseCallback(retry, callback, response, pluginResp) {
    Slidoc.log('codeResponseCallback:', this, retry, !!callback, response, pluginResp)
    var outputElem = document.getElementById(this.pluginId+'-output');
    var output = pluginResp.output || '';
    if (pluginResp) {
	var ntest = this.qattributes.test ? this.qattributes.test.length : 0;
	var nhide = this.qattributes.hiddentest || 0;
	if (pluginResp.invalid) {
	    output += renderCode(pluginResp.invalid.trim(), '', 'slidoc-code-invalid');
	} else if (pluginResp.score === 1) {
	    output += renderCode('All checks passed!', '', 'slidoc-code-status');
	} else if (isNumber(pluginResp.score)) {
	    if (retry && nhide) {
		// Retry only if hidden tests present
		var msg;
		if (pluginResp.tests > 0)
		    msg = (ntest - pluginResp.tests)+' checks failed!';
		else
		    msg = 'All checks failed';
		Slidoc.PluginRetry(msg);
		return;
	    }
	}
    }
    if (pluginResp.score !== null)
	output += renderCode('Score = '+pluginResp.score, '');
    outputElem.innerHTML = output;
    if (callback)
	callback(response, pluginResp);
}

var PADDING = '<code class="slidoc-code-padding">       </code> ';
var ERROR_PREFIX = '<code class="slidoc-code-error"> Error:</code> ';
var INPUT_PREFIX = '<code class="slidoc-code-input"> Input:</code> ';
var OUTPUT_PREFIX = '<code class="slidoc-code-output">Output:</code> ';
var EXPECT_PREFIX = '<code class="slidoc-code-expect">Expect:</code> ';

function renderCode(text, prefix, classes) {
    // Specify null value for prefix to have padding
    classes = classes || 'slidoc-code-plain';
    var lines = text.split('\n');
    var output = [];
    for (var j=0; j<lines.length; j++) {
	if (lines[j] || j < lines.length-1) {
	    var temPrefix = (j || prefix === null) ? PADDING : prefix;
	    output.push( temPrefix + '<code class="'+classes+'">'+Slidoc.PluginManager.escapeHtml(lines[j])+'</code>\n');
	}
    }
    return output.join('');
}

function checkCode(pluginName, slide_id, question_attrs, user_code, checkOnly, callback) {
    // Execute code and compare output to expected output
    // callback( {name:'Code', score:1/0/null, invalid: invalid_msg, output:output, tests:0/1/2} )
    // invalid_msg => syntax error when executing user code
    Slidoc.log('checkCode:', slide_id, question_attrs, user_code, checkOnly);

    if (!question_attrs.test || !question_attrs.test.length) {
	Slidoc.log('checkCode: Error - Test code checks not found in '+slide_id);
	return callback( {name:pluginName, score:null, invalid:'No checks', output:'', tests:0} );
    }

    var codeType = question_attrs.qtype;

    var codeCells = [];
    var solutionCode = '';
    if (question_attrs.input) {
	for (var j=1; j<=question_attrs.input; j++) {
	    // Execute all input cells
	    var inputText = getCellText(pluginName, slide_id, 'input', j, 0);
	    if (question_attrs.solution && question_attrs.solution == j)
		solutionCode = inputText;
	    else
		codeCells.push(inputText);
	}
    }

    var ntest = question_attrs.test.length;
    var nhide = question_attrs.hiddentest || 0;
    if (checkOnly && nhide && nhide > 1) ntest = Math.min(ntest, nhide-1);
    Slidoc.log('checkCode2:', ntest, nhide)

    function checkCodeAux(testCode, expectOutput, dispOutput, cumScore, index, score, stdout, stderr) {
	Slidoc.log('checkCodeAux:', 'index='+index, testCode, expectOutput, 'dispout=', dispOutput, cumScore, score, 'out=', stdout, 'err=', stderr);
	if (index) {
	    if (!expectOutput) {
		// Solution received
		if (stderr) {
		    Slidoc.log('checkCodeAux: Error in solution', stderr);
		    if (Slidoc.PluginManager.previewStatus())
			dispOutput += renderCode(stderr, ERROR_PREFIX);
		    return callback({name:pluginName, score:cumScore, invalid:'Error in solution', output:dispOutput, tests:Math.max(0,index-1)});
		}
		stdout = stdout.trim();
		if (!stdout) {
		    Slidoc.log('checkCodeAux: Error: No solution output');
		    return callback({name:pluginName, score:cumScore, invalid:'No solution output', output:dispOutput, tests:Math.max(0,index-1)});
		}
		// Note: index not incremented; stdout contains expectOutput
		return checkCodeAux2(user_code, testCode, stdout, dispOutput, cumScore, index);

	    }

	    var hiddenTest = nhide && index >= nhide;

	    if (stderr) {
		Slidoc.log('checkCodeAux: Error', stderr);
		if (!hiddenTest || Slidoc.PluginManager.previewStatus())
		    dispOutput += renderCode(stderr, ERROR_PREFIX);
		return callback({name:pluginName, score:cumScore, invalid:'Error in test '+index, output:dispOutput, tests:Math.max(0,index-1)});
	    }

	    if (!hiddenTest || Slidoc.PluginManager.previewStatus()) {
		// Do not display actual hidden test output (to avoid leaking test details)
		dispOutput += renderCode(testCode.trim(), INPUT_PREFIX);
		dispOutput += renderCode(stdout.trim(), OUTPUT_PREFIX);
		dispOutput += renderCode(expectOutput.trim(), EXPECT_PREFIX, 'slidoc-code-expect');
	    }

	    dispOutput += renderCode((hiddenTest?'Hidden check ':'Check ')+index+': '+((score === 1) ? 'Succeeded' : 'Failed'), '', 'slidoc-code-check')+'\n';

	    cumScore += score || 0;

	    if (index >= ntest) // All checks completed
		return callback({name:pluginName, score:(cumScore/ntest), invalid:'', output:dispOutput, tests:ntest});
	}

	// Execute next test
	var testCode = getCellText(pluginName, slide_id, 'test', question_attrs.test[index], index);
	    
	if (solutionCode)  // Compute expected output
	    return checkCodeAux2(solutionCode, testCode, '', dispOutput, cumScore, index+1, true);
	
	// New expect output
	expectOutput = getCellText(pluginName, slide_id, 'output', question_attrs.output ? question_attrs.output[index] : null, index);
	    
	return checkCodeAux2(user_code, testCode, expectOutput, dispOutput, cumScore, index+1);
    }

    function checkCodeAux2(mainCode, testCode, expectOutput, dispOutput, cumScore, index) {
	Slidoc.log('checkCodeAux2:', testCode, expectOutput, dispOutput, cumScore, index);
	return execCode(codeType, codeCells.concat(mainCode).concat(testCode).join('\n\n'), expectOutput, checkCodeAux.bind(null, testCode, expectOutput, dispOutput, cumScore, index));
    }

    checkCodeAux('', '', '', 0, 0, null, '', '');
}

function getCellText(pluginName, slide_id, cellType, cellNumber, testIndex) {
    var cellElem = cellNumber ? document.getElementById('slidoc-block-'+cellType+'-'+cellNumber) : null;
    var cellText = cellElem ? cellElem.textContent.trim() : '';
    if (cellText)
	return cellText;

    Slidoc.log('getCellText: Error - Code '+cellType+' cell #'+cellNumber+' not found or blank in '+slide_id);
    return callback({name:pluginName, score:null, invalid:'', output:'Missing/blank '+cellType+'cell #'+(testIndex ? testIndex+1 : cellNumber), tests:testIndex});
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
    var score = expect ? scoreCodeOutput(expect, text) : null;
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


/* HEAD: ^(javascript|python|test)$
<style>
.%(pluginLabel)s-textarea,
  .%(pluginLabel)s-check-button {display: block;}

.%(pluginLabel)s-input { font-size: 0.8em; }
.%(pluginLabel)s-input  { counter-reset: line; }
.%(pluginLabel)s-input code { counter-increment: line; padding-left: 5px;}
.%(pluginLabel)s-input code:before {
  content: counter(line, decimal-leading-zero) ": ";
  -webkit-user-select: none;
}

.%(pluginLabel)s-output { font-size: 0.7em; }
</style>

BODY:
<textarea id="%(pluginId)s-textarea" class="%(pluginLabel)s-textarea" cols="60" rows="5"></textarea>
<button id="%(pluginId)s-check-button" class="slidoc-clickable %(pluginLabel)s-check-button" onclick="Slidoc.PluginMethod('%(pluginName)s','%(pluginSlideId)s','checkCode',this);">Check</button>
<pre id="%(pluginId)s-input" class="%(pluginLabel)s-input"></pre>
<pre id="%(pluginId)s-output" class="%(pluginLabel)s-output"></pre>
*/
