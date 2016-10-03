<!--slidoc-defaults --pace=2 --features=assessment,skip_ahead-->
# Testing adaptive assignments

- Datasets are multi-dimensional

 - Three spatial dimensions: longitude, latitude, time

 - Fourth dimension: time

- Interested only in a subset of data

<script>
var TestScripts = {};
// basic: Answer all questions correctly
// NOTE: Skip-ahead only works for tryCount > 0
TestScripts.basic = [
  ['-ready'],
  ['+loginPrompt', 0, 500, 'login'],
  ['+lateTokenDialog', 0, 0, 'lateToken', ['none']],
  ['initSession', 0, 0, 'reset'],
  ['initSlideView', 2, 500, 'choice', ['B']],
  ['answerTally', 3, 500, 'input', ['y[-1]']],
  ['+answerSkip', 5, 500, 'choice', ['E']],         // For pace=2
  ['+answerTally', 5, 500, 'choice', ['E']],        // For pace=1 
  ['+answerSkip', 6, 500, 'input', ['fibonacci[0]']],
  ['+answerTally', 6, 500, 'input', ['fibonacci[0]']],
  ['+answerSkip', 7, 0, 'next'],
  ['+answerTally', 7, 0, 'next'],
  ['nextEvent', 8, 0, 'wait'],
  ['endPaced', 0, 0, 'end']
  ];
// expert: Skip after first two questions
TestScripts.expert = [
  ['-ready'],
  ['+loginPrompt', 0, 500, 'login'],
  ['+lateTokenDialog', 0, 0, 'lateToken', ['none']],
  ['initSession', 0, 0, 'reset'],
  ['initSlideView', 2, 500, 'choice', ['B']],
  ['answerTally', 3, 500, 'input', ['y[-1]']],
  ['answerTally', 7, 0, 'next'],
  ['nextEvent', 8, 0, 'wait'],
  ['endPaced', 0, 0, 'end']
  ];
// novice: Answer first question incorrectly and then all other questions correctly
TestScripts.novice = [
  ['-ready'],
  ['+loginPrompt', 0, 500, 'login'],
  ['+lateTokenDialog', 0, 0, 'lateToken', ['none']],
  ['initSession', 0, 0, 'reset'],
  ['initSlideView', 2, 500, 'choice', ['D']],
  ['answerTally', 3, 500, 'input', ['y[-1]']],
  ['answerTally', 4, 500, 'next'],
  ['nextEvent', 5, 500, 'choice', ['E']],
  ['answerTally', 6, 500, 'input', ['fibonacci[0]']],
  ['answerTally', 7, 0, 'next'],
  ['nextEvent', 8, 0, 'wait'],
  ['endPaced', 0, 0, 'end']
  ];
Slidoc.enableTesting(Slidoc.getParameter('testscript')||'', TestScripts);
</script>

---

Consider the list

    y = [1, 4, 9, 16, 25, 36, 49, 64]

What is the notation for the fourth element of the list `y`, i.e.,
corresponding to the value `16`?

A.. `y[2]`

B.. `y[3]`

C.. `y[4]`

D.. `y[5]`

E.. `y[6]`


Answer: B

Concepts: arrays, slicing; array, index; list, index

Notes: Since python list indices start at `0`, the fourth element is
actually `y[3]`. This may seem a bit confusing at first, but you will
get used to it!



---

Consider the list

    y = [1, 4, 9, 16, 25, 36, 49, 64]

What is the notation for the last element of list `y`?

Answer: `y[7]` OR `y[-1]`

Concepts: slicing, index; array, index; list, index 

Notes: There are eight elements in the list. Both `y[7]` and `y[-1]`
refer to the last element, with the latter notation counting backwards
from the end. The negative notation is very useful for a dynamically
created list, where you do not know the length before hand.

To refer to the last element, `y[-1]` is  more convenient than
`y[len(y)-1]`, which involves using the length function to extract the last
element of a dynamically created list.

If you answered the previous set of questions all correctly, you
have the option of skipping ahead to the next section on
[Two-dimensional arrays](#) anytime. Otherwise, you will need to answer
more practice questions on one-dimensional slicing.

---

More review material

---

Consider the list

    fibonacci = [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]

What notation would you use to refer to the element with value `13`?

A.. `fibonacci[6]`

B.. `fibonacci[3]`

C.. `fibonacci[5]`

D.. `fibonacci[4]`

E.. `fibonacci[7]`

Answer: E

Notes: Because `13` is the 8th element of the list.

---

Consider the list

    fibonacci = [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]

What notation would you use to refer to the element with value `0`?

Answer: `fibonacci[0]`

Notes: Remember, python list indices start at `0`.


---

## Two-dimensional arrays

Often, we need to represent two-dimensional data in the computer. A
simple example is a spreadsheet, with rows and columns. In science and
engineering, one often deals with a matrix of data values, with rows
and columns. Here's a 2x3 matrix, with 2 rows and 3 columns:

    1  2  3
    4  5  6

In standard Python, this can be represented as a list of lists:

```
matrix = [ [1, 2, 3],
           [4, 5, 6] ]

print matrix
```

```nb_output
[[1, 2, 3], [4, 5, 6]]
```

---

Last slide
