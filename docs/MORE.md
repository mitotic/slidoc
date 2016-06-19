<!--slidoc-defaults -->
# Slidoc: Additional documentation

- Plugins

- Scripted testing

---

## Plugins

Define plugins as a pseudo-Javascript block, with additional HTML
incorporated in comments.

```
PluginDef: name = {
// Javascript function definitions
init: function() {...},
...
}

// Additional Javascript in anonymous namespace

/* PluginHead:

PluginBody:

*/
PluginEnd: name
```

The `name` object is attached to a global object `SlidocPlugins` as
follows:

```
<script>(function() {
SlidocPlugins.name = {
// Javascript function definitions
...
}
// Additional Javascript in anonymous namespace
})();
</script>
```

`PluginHead` and `PluginBody` are optional, and are not needed for simple
formula plugins. These contain HTML with python-style format strings
of the form `%(plugin_*)s` to customize element IDs. The following
formats are subsituted:

> `plugin_slide_id`: `slidoc01-01`

> `plugin_name`: `name`

> `plugin_label`: `slidoc-plugin-name`

> `plugin_id`: `slidoc01-01-plugin-name`

> `plugin_args`: argument string

See `test/ex01-basic.md` and `test/ex06-d3js.md`
for simple examples. For a more complex example, see
`plugins/code.js`, which implements a pre-defined plugin.

---

## Plugin object instances

Three types of objects are instantiated using `SlidocPlugins.name` as
the prototype:

1. `setup` objects: Instantiated once after document is ready

2. `global` objects: Instantiated after session has been
created/retrieved, and also after user switching (when grading)

3. `slide` objects: Instantiated for each slide where plugin is
embedded, after the `global` object has been instantiated.

The `this` object for each instance contains the following pre-defined
attributes:

> `this.name`: plugin name

> `this.adminState`: *true* if grading

> `this.sessionName`: session name

> `this.pluginArgs`: object with slideId as keys and arguments from
> embedded plugin in the slide as values, e.g.,
> `{'slidoc01-03':[arg1, arg2, ...], ...}`
> (These are the same arguments that are used
> for calling `init` method of slide instances.)

The following are defined only for global and slide instances:

> `this.setup`:  setup instance

> `this.persist`: plugin-specific saved data for sessions

> `this.randomSeed`: slide-specific random seed (session-specific for global instances)

> `this.randomNumber`: random number generator using this seed
 
The following are defined only for slide instances:

> `this.global`: global instance

> `this.slideId`: `slidoc01-01`

> `this.pluginId`: `slidoc-01-01-plugin-name`

> `this.qattributes`: question attributes objects (for question slides)

Use `this.randomNumber()` to generate uniform random number between 0
and 1.  Use `this.randomNumber(min, max)` to pick equally probable
integer values between min and max (inclusive). Using these random
number generators ensures that randomized questions are reproducible
for the same session. The session would need to be reset to generate a
different set of questions. For non-paced sessions, reloading the web
page will automatically reset the session. Paced sessions will need to
be reset explicitly.

The following methods are automatically called for plugin instances;

> `initSetup()`: when setup instance is inititiated (after document
is ready). May insert/modify DOM and plugin content.

> `initGlobal()`: when the global instance is instantiated (at start of
session or user switching)

> `init(args)`: when the slide instance is instantiated

The slide-specific `init` will be called in a deterministic order, to
preserve the sequence in which global random generators may be called.

The following methods may be defined for plugins, as needed:

> `expect`: returns expected correct answer (for formula plugins)

> `display`: displays previously recorded user response (called at start/switch of session for each question)

> `disable`: disables plugin (after user response has been recorded)

> `response`: records and returns user response

> `enterSlide(paceStart)`: entering slide; returns paceDelay (in seconds) or null to use default (if paceStart only).

> `leaveSlide()`: leaving slide

---

## Embedding plugins

Once defined, plugins may be embedded in one or more slides by
invoking the `init` method, with optional arguments, as follows:

```
=name.init(arguments)
```

OR

```
PluginBegin: name.init(arguments)
text content
PluginEnd: name
```

This embeds the PluginBody HTML at this location, in a `div` with `id`
set to `plugin_id-body`, using templating to change element IDs. Any
text content between PluginBegin/PluginEnd is available in a `div`
with `id` set to `plugin_id-content` (for the plugin to re-format
during the `setup` instantiation.) The optional `arguments`, which
must all be in the same line, are supplied to the `init` call for
slide instances.

Alternatively, using `name.expect()` or `name.response()` as the
correct answer automatically embeds the plugin before the Answer (if
it has not been explicitly embedded before.)

---

## Formula plugins

Anywhere within Markdown text, any functions attached to plugins
embedded in the slide may be invoked using Excel-like backtick-equals
notations:

    `=plugin_name.func()`

This substitutes the return value from the function `func` attached to
the slide instance of the plugin. An optional non-negative integer
argument may be present. (`func` would always be called after
the `init` call.)

The correct answer can also be provided by a formula:

    Answer: plugin_name.expect();number

with the answer type appended after a semicolon (`;`).

Simple formula-subsitution plugins usually define `init` and `expect`
(returning the correct answer) and at least one other function
returning a subsitution value (see `test/ex01-basic.md`).


---

## Response plugins

Response plugins interact with the users and capture the response to a
question. They appears in the Answer portion of the slide.

    Answer: plugin_name.response();text/x-python

The `response` method uses callback to return the user response (as a
string) and an optional `pluginResp` object of the form:
`{name:pluginName, score:1/0/0.75/.../null, invalid: invalid_msg,
output:output, tests:0/1/2}`

`score` may be any value between `0.0` and `1.0`. A `null` value for
`score` implies no grading for the question. (The `score` will be
multiplied by the score weight for the question when computing the
cumulative score.) `invalid` is used to record syntax/runtime error
messages. `output` records valid (but possibly incorrect) output from
code testing. `tests` indicates whether zero, primary (output visible
to user), or secondary (output invisible to user) testing of code
output was carried out.

See `plugins/code.js` for an example of a response plugin.

---

## Scripted testing

Use options `--test_script --pace=1` for scripted testing. (For
adaptive documents, use `--pace=1,0,1`).

Use query options of the form:

    name.html?testscript=basic&teststep=1&testuser=aaa&testkey=key

to trigger testing. `testscript` is the name of the script to run,
`testuser` is login id (which would be `admin` for grading). `testkey`
is the HMAC key (a `testtoken` may also be provided instead.)
`teststep=1` enables stepwise testing, requiring user interaction.

At the beginning of the document to tested, include a script element of
of the form:

```
<script>
var TestScripts = {};
TestScripts.basic = [
  ['-ready'],
  ['+loginPrompt', 0, 500, 'login'],
  ['+lateTokenDialog', 0, 0, 'lateToken', ['none']],
  ['initSession', 0, 0, 'reset'],
  ['initSlideView', 2, 500, 'choice', ['D']],
  ['answerTally', 3, 500, 'input', [5.5]],
  ['answerTally', 11, 0, 'wait'],
  ['lastSlideDialog', 0, 0, 'dialogReturn', [true]],
  ['endPaced', 0, 0, 'end']
  ];
Slidoc.enableTesting(Slidoc.getParameter('testscript')||'', TestScripts);
</script>
```

The entry format is
`['expectedEvent', slide_number or 0, delay_msec or 0, 'action', [arg1, arg2, ...]]`,
with

> Prefix `+` for expected events indicates optional event (may not be reported)

> Prefix `-` for expected events indicates skipped event (no action to be performed)

See `test/ex??-*.md` for examples. See
`TestScript.prototype.eventAction` in `doc_test.js` for more testing
actions.



