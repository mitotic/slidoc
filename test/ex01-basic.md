<!--slidoc-defaults --pace=1 --features=grade_response,quote_response -->
# Basic questions

Slidoc supports a simple format for framing interactive questions.
For multiple-choice questions, the format is similar to the
[Aiken format](https://docs.moodle.org/24/en/Aiken_format) used by
Learning Management Systems like Moodle. For numeric response
questions, formulas (similar to Excel macros) may be used to randomize
the question (see [Interactive numerical response question](#)). Text
response ("essay") questions are also supported.

The next slide contains a multiple choice question that uses the `A.. `
notation allowing interactive response. (The space after the `..` is
required.) Click on a choice to view the correct answer.

Concepts: questions, interactive: questions, multiple-choice;
questions, numeric response; questions, formulas; questions, text
response

<script>
var choices = ['A', 'B', 'C', 'D'];
function randChoice() {return choices[Math.floor(Math.random()*choices.length)];}
var TestScripts = {};
TestScripts.basic = [
  ['-ready'],
  ['+loginPrompt', 0, 500, 'login'],
  ['+lateTokenDialog', 0, 0, 'lateToken', ['none']],
  ['initSession', 0, 0, 'reset'],
  ['initSlideView', 2, 500, 'choice', [randChoice(), 'Just because ...']],
  ['answerTally', 3, 500, 'choice', [randChoice(), 'C']],
  ['answerTally', 4, 500, 'input', [5.5]],
  ['answerTally', 5, 500, 'input', ['T. Rex']],
  ['answerTally', 6, 500, 'input', ['100, 35,0, -40']],
  ['answerTally', 7, 500, 'textarea', ['def add(a,b):\n    return a+b\n']],
  ['answerTally', 9, 500, 'choice', [randChoice()]],
  ['answerTally', 10, 500, 'input', [42, 'According to Douglas Adams']],
  ['answerTally', 11, 500, 'input', ['To be ...']],
  ['answerTally', 13, 0, 'submitSession'],
  ['+lastSlideDialog', 0, 0, 'dialogReturn', [true]],
  ['endPaced', 0, 0, 'end']
  ];
Slidoc.enableTesting(Slidoc.getParameter('testscript')||'', TestScripts);
</script>

---

In Shakespeare's play *Hamlet*, the protagonist agonizes over
answering a multiple-choice question. What choice does he agonize
over?

A.. Letter A

B*.. Letter B

C.. Letter C

D.. Letter D

Answer: ;explain

Concepts: questions, interactive: questions, multiple-choice

Notes:

    To be or not to be-that is the question:
    Whether 'tis nobler in the mind to suffer
    The slings and arrows of outrageous fortune,
    Or to take arms against a sea of troubles,
    And, by opposing, end them. 

---

Which of the following are plays by Shakespeare?

A.. Love's labor won

B.. Love's labor lost

C.. Henry V

D.. Richard VIII

Answer: BC

Concepts: questions, multichoice

Notes:

Multiple selections can be specified in the Answer: line

---

## Interactive numerical response question

What is the square root of `=SqrtTest.number(1);6.25`?

PluginDef: SqrtTest = {
// Sample code for embedding Javascript formulas ("macros") in questions and answers.
// Plugin object SqrtTest is automatically attached to global object SlidocPlugins
// Special function init is called for each slide. 
// Define formulas as functions in the plugin object.
// Special function expect should return the expected answer. 
// Use this.pluginId for a slide-specific ID.
// Use this.randomNumber() to generate uniform random number between 0 and 1.
// Use this.randomNumber(min, max) to pick equally probable integer values between min and max (inclusive).
// (Random number choices will only change if the session is reset.)
// Define any persistent objects after the plugin object (in an anonymous namespace). 
//
    init: function(label, value) {
	    console.log('SqrtTest.init:', this.pluginId, label, value);
  	    // Pick a random integer between 2 and 19, and then divide by 2 
	    var randInt = this.randomNumber(2,19);
	    this.chosenNumber = (0.5*randInt).toFixed(1);
    },

    number: function(n) {
	    console.log('SqrtTest.number:', n, this.pluginId, randVals[this.pluginId]);
	    return (this.chosenNumber*this.chosenNumber).toFixed(2);
    },

    expect: function() {
	    console.log('SqrtTest.expect:', this.pluginId, this.chosenNumber);
	    return this.chosenNumber+' +/- '+'0.1';
    }
}
var randVals = {}; // Optional persistent object
PluginEndDef: SqrtTest

=SqrtTest('Slide label', 3.1416)

Answer: 2.5 +/- 0.1=SqrtTest.expect()

Concepts: questions, numeric response: questions, formulas; questions, randomized

Notes: An optional error range may be provided after `+/-`.

Embedded javascript functions may be used as formulas, using the notation

    `=plugin_name.function_name()`

To display a default reference value, append it, separated by a
semicolon (`;`). View the raw Markdown text for this document to see
the embedded javascript code that randomizes the question.


---

## Text response

The dinosaur named tyrant lizard is more commonly known as?

Answer: T.Rex OR T Rex OR T-Rex OR Tyrannosaurus Rex

Concepts: questions, text response

Notes: The upper-case OR is used to separate correct answer options,
which are not case-sensitive. If a correct answer option includes a
space (e.g., `T Rex`, it is compared to the user response with
normalized spaces, i.e, `T Rex` would be considered correct, but not
`TRex`. If the correct answer option does not include a space, such as
the answer to a coding question, then all spaces are stripped from the
user response before comparison, i.e., `T.Rex` and `T. Rex` would be
considered correct.

---

## Text response 2

Convert the following temperature values from &deg;F to &deg;C:

    212, 95, 32, -40

Enter only the integer portion of the &deg;C values (i.e., no decimal
points), separated by commas, as your answer. For example,

    1, 2, -4, 5
 
Answer: 100,35,0,-40

Note: Do not include any spaces in the correct answer; otherwise
spaces will be expected in the user response.

---

## Simple function code (question)

Write a python function to add two numbers.

Answer: text/x-code; weight=1,4

Concepts: questions, text response 

Notes: This is an example of an open-ended text answer question.

---

### Simple function code answer

The answer

```
def add(a, b):
    c = a + b
    return c
```

Notes: The above function accepts two arguments and returns the sum of
the two arguments.

--

This is an example to test hiding of answer slides.

---

## Open multiple choice question

What is the best way to deal with climate change?

A.. Mitigation

B.. Adaptation

C.. Geoengineering

D.. Move to Mars

Answer: choice

Notes: If no correct answer is provided, all answers are scored as
being correct.

---

## Open numeric response question

What number is the answer to the Ultimate Question of Life, the Universe and Everything?

Answer: number; explain=markdown; weight=0,2

Notes: All answers are assumed correct.

---

## Open text response question

To be or not to be - that is the question. What is the answer?

Answer: text

Notes: All answers are assumed correct.

---

### Open text response question answer

Solution to open response question

Notes: Notes on answer to
open response question


---

## Last slide

End of session
