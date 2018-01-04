Params = {
    // Parameter formula plugin

    init: function(paramFunctions) {
	Slidoc.log('Slidoc.Plugins.Params.init:');
	//Slidoc.log('Slidoc.Plugins.Params.init2:', this.slideParams, paramFunctions);
	var paramsObj = this.slideParams;
	var names = Object.keys(paramsObj);
	names.sort();
	this.paramVals = [];
	for (var j=0; j<names.length; j++)
	    this.paramVals.push(paramsObj[names[j]]);
	this.paramNames = names.join(',');

	if (paramFunctions) {
	    var funcNames = [];
	    var funcDefs = [];
	    for (var j=0; j<paramFunctions.length; j++) {
		var funcName = paramFunctions[j][0];
		if (funcName in paramsObj)
		    continue;
		var k = funcNames.indexOf(funcName);
		if (k < 0) {
		    funcNames.push(funcName);
		    k = funcNames.length-1;
		}
		// Later defs override earlier defs
		funcDefs[k] = paramFunctions[j][1];
	    }
	    for (var j=0; j<funcNames.length; j++) {
		var funcName = funcNames[j];
		// Evaluate function definition
		var funcDef = this.formula(funcDefs[j]);
		if (typeof x == 'string')
		    funcDef = function() { return 'Params function '+funcName+' '+x; };
		this.paramVals.push(funcDef);
		if (this.paramNames)
		    this.paramNames += ',';
		this.paramNames += funcName;
	    }
	}
    },

    formula: function (expr) {
	Slidoc.log('Slidoc.Plugins.Params.formula:', this, expr);
	try {
	    var func = new Function(this.paramNames, 'return '+expr);
	} catch(err) {
	    var msg = 'ERROR in formula syntax';
	    if (Slidoc.PluginManager.adminAccess())
		msg += ' { '+expr+' }: ' + err;
	    return msg;
	}
	try {
	    return func.apply(null, this.paramVals);
	} catch (err) {
	    var msg = 'ERROR in formula evaluation';
	    if (Slidoc.PluginManager.adminAccess())
		msg += ' { '+expr+' }: ' + err;
	    return msg;
	}
    }
};

/* HEAD:
   BODY:
*/
