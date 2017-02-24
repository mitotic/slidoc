ChartistPanel = {
    // Data plotting plugin

    init: function(plotObj) {
	// plotObj = {traces: [{x:[...], y:[...]}, layout: {xaxis: {...}, yaxis: {..}}, annotate: text} }
	Slidoc.log('Slidoc.Plugins.ChartistPanel.init:', arguments, this.slideData);
	this.chart = new Chartist.Line('#'+this.slideId+'-plot', {
            labels: plotObj.traces[0].x,
            series: [plotObj.traces[0].y] });

	this.slideData.plot = this;
    },

    updateTrace: function(newX, newY, name, n) {
        if (newX === null || newY === null)
	    return;
	this.chart.update({ labels: newX,
                            series: [newY] });
    },

    addTrace: function (newX, newY, name, lineStyle, color) {
    },

    updateAxisRange: function (axis, autorange) {
    },

    updateAnnotation: function (text) {
    }
}

/* HEAD:
   <link rel="stylesheet" href="https://cdn.jsdelivr.net/chartist.js/latest/chartist.min.css">
   <script src="https://cdn.jsdelivr.net/chartist.js/latest/chartist.min.js"></script>
   BODY:
   <div id="%(pluginSlideId)s-plot" style="width:600px;height:250px;"></div>
*/
