<!--slidoc-defaults --pace=1 --features=grade_response,quote_response --revision=abc1 -->
# Test grading/explain options

<script>
var TestScripts = {};
TestScripts.basic = [
  ['-ready'],
  ['+loginPrompt', 0, 500, 'login'],
  ['+lateTokenDialog', 0, 0, 'lateToken', ['none']],
  ['initSession', 0, 0, 'reset'],
  ['initSlideView', 2, 500, 'textarea', ['My **answer1**']],
  ['answerTally', 4, 500, 'input', [5.5, 'My *explanation1*']],
  ['answerTally', 5, 500, 'submitSession'],
  ['+lastSlideDialog', 0, 0, 'dialogReturn', [true]],
  ['endPaced', 0, 0, 'end']
  ];
TestScripts.grader = [
  ['-ready'],
  ['+loginPrompt', 0, 500, 'login'],
  ['initSession', 0, 0, 'switchUser', [0]],
  ['-selectUser'],
  ['initSlideView', 2, 500, 'gradeStart'],
  ['gradeStart',   0, 500, 'gradeUpdate', [3.1416, 'My comments1']],
  ['gradeUpdate', 0, 0, 'switchUser', [1]],
  ['selectUser',  0, 500, 'gradeStart'],
  ['gradeStart',  0, 500, 'gradeUpdate', [1.67, 'My comments2']],
  ['gradeUpdate', 0, 0, 'end']
  ];
Slidoc.enableTesting(Slidoc.getParameter('testscript')||'', TestScripts);
</script>

---

## Simple function code (question)

Write a python function to add two numbers.

Paste sample code:

test **bold** and  \(\alpha = \frac{1}{\beta}\)

\[\alpha = \frac{1}{\beta}\]

Answer: text/markdown; weight=0,5

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

---


## Simple numeric question

Provide a numeric answer.

Answer: 1.5 +/- 0.5; explain=markdown; weight=0,5

Concepts: questions, text response 

---

Last slide
