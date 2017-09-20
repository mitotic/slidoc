<!--slidoc-defaults --pace=1 --features=grade_response -->
# Test code execution

Test file

<script>
var TestScripts = {};
TestScripts.basic = [
  ['-ready'],
  ['+loginPrompt', 0, 500, 'login'],
  ['+lateTokenPrompt', 0, 0, 'lateToken', ['none']],
  ['initSession', 0, 0, 'reset'],
  ['initSlideView', 2, 500, 'code', ['def sq(x):\n  return x**2\n']],
  ['answerTally', 3, 500, 'code', ['def sq(x):\n  return x**2\n']],
  ['answerTally', 0, 0, 'end']
  ];
Slidoc.enableTesting(Slidoc.getParameter('testscript')||'', TestScripts);
</script>

---

## Python function, single check (plugin)

Write a function `sq(x)` that returns the square of `x`.

```
def sq(x):
    ...

```

Test it using the following call:

```python_test
print sq(2.5)
```

to produce the following output:

```nb_output
6.25
```

Answer: Code/python

---

## Python function, double check

Write a function `sq(x)` that returns the square of `x`.

```
def sq(x):
    ...

```

Test it using the following call:

```python_test
print sq(2.5)
```

to produce the following output:

```nb_output
6.25
```

```python_test
# Additional tests
print sq(3.5)
```

```nb_output
12.25
```

Answer: Code/python

---

## Python function, solution provided

Write a function `sq(x)` that returns the square of `x`.

```
def sq(x):
    ...

```

Test it using the following call:

```python_test
print sq(2.5)
```

to produce the following output:

```nb_output
6.25
```

```python_test_hidden
# Additional tests
print sq(3.5)
```

```python_solution
# Correct answer
def sq(x):
    return x*x

```

Answer: Code/python

---

## Python function, fillable solution provided

Write a function `sq(x)` that returns the square of `x` by filling in
the blanks in the following piece of code.

```python_fillable
# Correct answer
def sq(x):
    return ``x*x``
```

Use the *Check* button to run the following test on the above
filled-in code:

```python_test
print sq(2.5)
```
which should produce the following output:

```nb_output
6.25
```

```python_test_hidden
# Additional tests
print sq(3.5)
```

When satisfied, use the *Answer* button to record the answer. An
additional hidden test will be carried to further validate the function.

Answer: Code/python

---

## Javscript function, double check

Write a function `sq(x)` that returns the square of `x`.

```javascript
function sq(x) {
    ...
}
```

Test it using the following call:

```javascript_test
sq(2.5)
```

to produce the following output:

```nb_output
6.25
```

```javascript_test
// Additional tests
sq(3.5)
```

```nb_output
12.25
```

Answer: Code/javascript

---

## Prior code 1 and 2

```python_input

Prior code1

```

```python_input

Prior code2

```

---

## Dummy question


```

Enter code using this template

```

```python_test
Test code1
```

```nb_output
Correct output
```

Type `Syntax error` to generate syntax error. 

Type `Semantic error` to generate incorrect output.

Anything else will generate correct output.

Answer: Code/test

---

## Dummy question 2

Simulates semantic error in the test code

```

Enter code using this template

```

```python_test
Test code 2
Semantic error
```

```nb_output
Correct output
```

Type anything to generate incorrect output.

Answer: Code/test

---

## Prior code 3 (with syntax error)

```python_input

Prior code 3
Syntax error

```

---

## Dummy question

Simulates syntax error in prior code

```

Enter code using this template

```

```python_test
Test code 3
```

```nb_output
Correct output
```

Type anything to generate syntax error.

Answer: Code/test

---

## Last slide

