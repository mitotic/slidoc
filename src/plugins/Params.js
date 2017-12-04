Params = {
    // Parameter formula plugin

    init: function() {
	Slidoc.log('Slidoc.Plugins.Params.init:', this);
	var paramsObj = this.slideParams;
	var names = Object.keys(paramsObj);
	names.sort();
	this.paramVals = [];
	for (var j=0; j<names.length; j++)
	    this.paramVals.push(paramsObj[names[j]]);
	this.paramNames = names.join(',');
    },

    formula: function (expr) {
	Slidoc.log('Slidoc.Plugins.Params.formula:', this, expr);
	try {
	    var func = new Function(this.paramNames, 'return '+expr);
	} catch(err) {
	    return 'ERROR in formula syntax';
	}
	try {
	    return func.apply(null, this.paramVals);
	} catch (err) {
	    return 'ERROR in formula evaluation';
	}
    }
};

/* HEAD:
   BODY:
*/
