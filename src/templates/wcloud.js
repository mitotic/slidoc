/*!
 * WordCloud for Slidoc
 *
 * Derived from jQCloud Plugin for jQuery (Version 1.0.2)
 *
 * Copyright 2011, Luca Ongaro
 * Modified by R.Saravanan
 * Licensed under the MIT license.
 *
*/

var WCloud = {};

(function (WCloud) {

WCloud.showCloud = function(thisElem, word_array, options) {
    // word_array = [{text:, weight:]}, ...]
    // options = {width:, height:, center: {x:, y:}, shape: true/false }
    function setAttrs(elem, attrs) {
	var keys = Object.keys(attrs);
	for (var j=0; j<keys.length; j++)
	    elem.setAttribute(keys[j], attrs[keys[j]]);
	return elem;
    }

    function isFunction(functionToCheck) {
	var getType = {};
	return functionToCheck && getType.toString.call(functionToCheck) === '[object Function]';
    }

    function extend(obj, attributes) {
	obj = obj || {};
	var keys = Object.keys(attributes||{});
	for (var j=0; j<keys.length; j++)
	    obj[keys[j]] = attributes[keys[j]];
	return obj;
    }

    // Namespace word ids to avoid collisions between multiple clouds
    var cloud_namespace = thisElem.id || Math.floor((Math.random()*1000000)).toString(36);

    // Default options value
    var set_options = {
      width: thisElem.clientWidth,
      height: thisElem.clientHeight,
      center: {
        x: ((options && options.width) ? options.width : thisElem.clientWidth) / 2.0,
        y: ((options && options.height) ? options.height : thisElem.clientHeight) / 2.0
      },
      delayedMode: word_array.length > 50,
      shape: false, // It defaults to elliptic shape
      encodeURI: true,
      removeOverflowing: true
    };

    options = extend(set_options, options || {});

    // Add the "wcloud" class to the container for easy CSS styling, set container width/height
    thisElem.classList.add("wcloud");
    thisElem.style.width = options.width;
    thisElem.style.height = options.height;

    // Container's CSS position cannot be 'static'
    if (thisElem.style.position === "static") {
      thisElem.style.position = "relative";
    }

    var drawWordCloud = function() {
      // Helper function to test if an element overlaps others
      var hitTest = function(elem, other_elems) {
        // Pairwise overlap detection
        var overlapping = function(a, b) {
          if (Math.abs(2.0*a.offsetLeft + a.offsetWidth - 2.0*b.offsetLeft - b.offsetWidth) < a.offsetWidth + b.offsetWidth) {
            if (Math.abs(2.0*a.offsetTop + a.offsetHeight - 2.0*b.offsetTop - b.offsetHeight) < a.offsetHeight + b.offsetHeight) {
              return true;
            }
          }
          return false;
        };
        var i = 0;
        // Check elements for overlap one by one, stop and return false as soon as an overlap is found
        for(i = 0; i < other_elems.length; i++) {
          if (overlapping(elem, other_elems[i])) {
            return true;
          }
        }
        return false;
      };

      // Make sure every weight is a number before sorting
      for (var i = 0; i < word_array.length; i++) {
        word_array[i].weight = parseFloat(word_array[i].weight, 10);
      }

      // Sort word_array from the word with the highest weight to the one with the lowest
      word_array.sort(function(a, b) { if (a.weight < b.weight) {return 1;} else if (a.weight > b.weight) {return -1;} else {return 0;} });

      var step = (options.shape === "rectangular") ? 18.0 : 2.0,
          already_placed_words = [],
          aspect_ratio = options.width / options.height;

      // Function to draw a word, by moving it in spiral until it finds a suitable empty place. This will be iterated on each word.
      var drawOneWord = function(index, word) {
        // Define the ID attribute of the span that will wrap the word, and the associated jQuery selector string
        var word_id = cloud_namespace + "_word_" + index,
            word_selector = "#" + word_id,
            angle = 6.28 * Math.random(),
            radius = 0.0,

            // Only used if option.shape == 'rectangular'
            steps_in_direction = 0.0,
            quarter_turns = 0.0,

            weight = 5,
            custom_class = "",
            inner_html = "",
            word_span;

        // Extend word html options with defaults
        word.html = extend(word.html, {id: word_id});

        // If custom class was specified, put them into a variable and remove it from html attrs, to avoid overwriting classes set by WordCloud
        if (word.html && word.html["class"]) {
          custom_class = word.html["class"];
          delete word.html["class"];
        }

        // Check if min(weight) > max(weight) otherwise use default
        if (word_array[0].weight > word_array[word_array.length - 1].weight) {
          // Linearly map the original weight to a discrete scale from 1 to 10
          weight = Math.round((word.weight - word_array[word_array.length - 1].weight) /
                              (word_array[0].weight - word_array[word_array.length - 1].weight) * 9.0) + 1;
        }
          word_span = document.createElement('span');
	  setAttrs(word_span, word.html);
	  word_span.classList.add('w' + weight);
	  if (custom_class)
	      word_span.classList.add(custom_class);

        // Append link if word.url attribute was set
        if (word.link) {
          // If link is a string, then use it as the link href
          if (typeof word.link === "string") {
            word.link = {href: word.link};
          }

          // Extend link html options with defaults
          if ( options.encodeURI ) {
            word.link = extend(word.link, { href: encodeURI(word.link.href).replace(/'/g, "%27") });
          }

          inner_html = document.createElement('a');
	  setAttrs(inner_html, word.link);
	  inner_html.textContent = word.text;
        } else {
          inner_html = word.text;
        }
        word_span.appendChild((typeof inner_html == "string") ? document.createTextNode(inner_html) : inner_html);

        // Bind handlers to words
        if (!!word.handlers) {
	    var wkeys = Object.keys(word.handlers)
	    for (var j=0; j<wkeys.length; j++) {
		var prop = wkeys[j];
		if (typeof word.handlers[prop]  === 'function')
		    word_span.addEventListener(prop, word.handlers[prop]);
	    }
        }

        thisElem.appendChild(word_span);

        var width = word_span.clientWidth,
            height = word_span.clientHeight,
            left = options.center.x - width / 2.0,
            top = options.center.y - height / 2.0;

        // Save a reference to the style property, for better performance
        var word_style = word_span.style;
        word_style.position = "absolute";
        word_style.left = left + "px";
        word_style.top = top + "px";

        while(hitTest(word_span, already_placed_words)) {
          // option shape is 'rectangular' so move the word in a rectangular spiral
          if (options.shape === "rectangular") {
            steps_in_direction++;
            if (steps_in_direction * step > (1 + Math.floor(quarter_turns / 2.0)) * step * ((quarter_turns % 4 % 2) === 0 ? 1 : aspect_ratio)) {
              steps_in_direction = 0.0;
              quarter_turns++;
            }
            switch(quarter_turns % 4) {
              case 1:
                left += step * aspect_ratio + Math.random() * 2.0;
                break;
              case 2:
                top -= step + Math.random() * 2.0;
                break;
              case 3:
                left -= step * aspect_ratio + Math.random() * 2.0;
                break;
              case 0:
                top += step + Math.random() * 2.0;
                break;
            }
          } else { // Default settings: elliptic spiral shape
            radius += step;
            angle += (index % 2 === 0 ? 1 : -1)*step;

            left = options.center.x - (width / 2.0) + (radius*Math.cos(angle)) * aspect_ratio;
            top = options.center.y + radius*Math.sin(angle) - (height / 2.0);
          }
          word_style.left = left + "px";
          word_style.top = top + "px";
        }

        // Don't render word if part of it would be outside the container
        if (options.removeOverflowing && (left < 0 || top < 0 || (left + width) > options.width || (top + height) > options.height)) {
	    if (word_span.parentNode)
		word_span.parentNode.removeChild(word_span);
          return;
        }

        already_placed_words.push(word_span);

        // Invoke callback if existing
        if (isFunction(word.afterWordRender)) {
          word.afterWordRender.call(word_span);
        }
      };

      var drawOneWordDelayed = function(index) {
        index = index || 0;
        if (index < word_array.length) {
          drawOneWord(index, word_array[index]);
          setTimeout(function(){drawOneWordDelayed(index + 1);}, 10);
        } else {
          if (isFunction(options.afterCloudRender)) {
            options.afterCloudRender.call(thisElem);
          }
        }
      };

      // Iterate drawOneWord on every word. The way the iteration is done depends on the drawing mode (delayedMode is true or false)
      if (options.delayedMode) {
	  setTimeout(function(){drawOneWordDelayed();}, 20);
      } else {
	  var wkeys = Object.keys(word_array);
	  for (var j=0; j<wkeys.length; j++)
	      drawOneWord(j, word_array[wkeys[j]]);
        if (isFunction(options.afterCloudRender)) {
          options.afterCloudRender.call(thisElem);
        }
      }
    };

    // Delay execution so that the browser can render the page before the computatively intensive word cloud drawing
    setTimeout(function(){drawWordCloud();}, 10);
    return thisElem;
}

var gShortStopWordList = ["i", "a", "about", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "how", " in", "is", "it", "of", "on", "or", "that", "the", "this", "to", "was", "what", "when", "where", " who", "will", "with", "the"];

// Dropped "none" from long stop word list
var gLongStopWordList = ["a", "about", "above", "above", "across", "after", "afterwards", "again", "against", "all", "almost", "alone", "along", "already", "also","although","always","am","among", "amongst", "amoungst", "amount",  "an", "and", "another", "any","anyhow","anyone","anything","anyway", "anywhere", "are", "around", "as",  "at", "back","be","became", "because","become","becomes", "becoming", "been", "before", "beforehand", "behind", "being", "below", "beside", "besides", "between", "beyond", "bill", "both", "bottom","but", "by", "call", "can", "cannot", "cant", "co", "con", "could", "couldnt", "cry", "de", "describe", "detail", "do", "done", "down", "due", "during", "each", "eg", "eight", "either", "eleven","else", "elsewhere", "empty", "enough", "etc", "even", "ever", "every", "everyone", "everything", "everywhere", "except", "few", "fifteen", "fify", "fill", "find", "fire", "first", "five", "for", "former", "formerly", "forty", "found", "four", "from", "front", "full", "further", "get", "give", "go", "had", "has", "hasnt", "have", "he", "hence", "her", "here", "hereafter", "hereby", "herein", "hereupon", "hers", "herself", "him", "himself", "his", "how", "however", "hundred", "ie", "if", "in", "inc", "indeed", "interest", "into", "is", "it", "its", "itself", "keep", "last", "latter", "latterly", "least", "less", "ltd", "made", "many", "may", "me", "meanwhile", "might", "mill", "mine", "more", "moreover", "most", "mostly", "move", "much", "must", "my", "myself", "name", "namely", "neither", "never", "nevertheless", "next", "nine", "no", "nobody", "noone", "nor", "not", "nothing", "now", "nowhere", "of", "off", "often", "on", "once", "one", "only", "onto", "or", "other", "others", "otherwise", "our", "ours", "ourselves", "out", "over", "own","part", "per", "perhaps", "please", "put", "rather", "re", "same", "see", "seem", "seemed", "seeming", "seems", "serious", "several", "she", "should", "show", "side", "since", "sincere", "six", "sixty", "so", "some", "somehow", "someone", "something", "sometime", "sometimes", "somewhere", "still", "such", "system", "take", "ten", "than", "that", "the", "their", "them", "themselves", "then", "thence", "there", "thereafter", "thereby", "therefore", "therein", "thereupon", "these", "they", "thickv", "thin", "third", "this", "those", "though", "three", "through", "throughout", "thru", "thus", "to", "together", "too", "top", "toward", "towards", "twelve", "twenty", "two", "un", "under", "until", "up", "upon", "us", "very", "via", "was", "we", "well", "were", "what", "whatever", "when", "whence", "whenever", "where", "whereafter", "whereas", "whereby", "wherein", "whereupon", "wherever", "whether", "which", "while", "whither", "who", "whoever", "whole", "whom", "whose", "why", "will", "with", "within", "without", "would", "yet", "you", "your", "yours", "yourself", "yourselves", "the"];

var gShortStopWords = {};
for (var j=0; j<gShortStopWordList.length; j++)
    gShortStopWords[gShortStopWordList[j]] = 1;

var gLongStopWords = {};
for (var j=0; j<gLongStopWordList.length; j++)
    gLongStopWords[gLongStopWordList[j]] = 1;

WCloud.createCloud = function(thisElem, text_list, params) {
    // Word cloud
    // text_list: List of text values to be clouded
    // params: [long|short|digit] <list of words to be ignored>
    // Join compound words with "_"
    if (!text_list.length) {
	alert("No data to display as cloud");
	return false;
    }

    var comps = [];
    if (params)
	comps = params.split(/\s+/);

    var minWordLen = 2;
    var stopWords = {};
    var ignoreWords = {};
    stopWords = gLongStopWords;
    for (var j=0; j<comps.length; j++) {
	if (comps[j] == "long") {
	    stopWords = gLongStopWords;
	} else if (comps[j] == "short") {
	    stopWords = gShortStopWords;
        } else {
	    ignoreWords[comps[j].toLowerCase().replace("_", " ")] = 1;
        }
    }

    var word_count = {};

    for (var j=0; j<text_list.length; j++) {
        var resp_text = text_list[j];
	resp_text = resp_text.replace(/__/g, "_").replace(/'/g, "__");           // Dummy comment /'/
	resp_text = resp_text.replace(/\W+/g, " ").replace(/__/g, "'");
	
        var words = resp_text.split(/\s+/);
        for (var k=0; k<words.length; k++) {
	  var word = words[k];
	  if (!word)
	    continue;
	  word = word.replace("_", " ");
          var cloud_word = word.toLowerCase();
	  if (cloud_word.length <= minWordLen || cloud_word in stopWords || cloud_word in ignoreWords)
	    continue;

	  if (cloud_word in word_count) {
	    word_count[cloud_word] += 1;
	  } else {
	    word_count[cloud_word] = 1;
	  }
        }
    }
    
    var word_list = [];
    for (var wrd in word_count) {
      word_list.push({text: wrd, weight: word_count[wrd]});
    }

    WCloud.showCloud(thisElem, word_list)

    return false;
}

})(WCloud);
