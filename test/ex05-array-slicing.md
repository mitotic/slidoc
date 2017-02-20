# Slicing and dicing: extracting portions of multi-dimensional data

- Datasets are multi-dimensional

 - Three spatial dimensions: longitude, latitude, time

 - Fourth dimension: time

- Interested only in a subset of data

Notes: We live in a 3-dimensional world and measurements made in our
world often produce 3-dimensional data. On a global scale, the three
spatial dimensions are longitude (east-west direction), latitude
(north-south direction) and altitude (up-down direction). If
measurements are made over time, this adds a fourth dimension.

Altough data may be collected over a large domain, often we may be
interested in analyzing or visualizing only a small portion of the data for a
particular project. In this case, we need to extract a small portion
from the full dataset, i.e., we need a *subset* of the data.

The `numpy` package, which extends python's list data structure by
supporting multi-dimensional arrays, provides powerful operations
known as *slicing* to extract subsets of data. Slicing in `numpy` uses
essentially the same range notation as slicing operations of
1-dimensional python lists and strings, but extends it to many
dimensions.

---

## Python slicing rules

- Indices are counted starting from `0`

- Endpoint index `n` of a range `m:n` is excluded

- In a range `m:n`, `m` may be omittied if it is zero and `n` may be
  mitted if it equals the length of the list


First, we review python's list indexing and slicing
operations. Consider the following list:

```
x = [1, 2, 3, 4, 5, 6]
print 'List x=', x
print 'The length of list x is', len(x)
```

```nb_output
List x= [1, 2, 3, 4, 5, 6]
The length of list x is 6
```

The built-in function `len` returns the length of a list.

```
print x[1], x[5], x[-1], x[-2], x[2:5], len(x[2:5])
```

```nb_output
2 6 6 5 [3, 4, 5] 3
```


`x[1]` refers to the second element of the list (because python list
index values start at zero).

Negative index values may be used to count in reverse from the end of
the list. The last element can be referred to as `x[5]` or as
`x[-1]`. The last-but-one element will be `x[-2]`

`x[2:5]` refers to the slice from the third to the fifth elements,
i.e., `[3,4,5]` but excluding the sixth element, because python ranges
always *exclude* the final value. If the first index if a range is
`0`, it can be omitted. The length of `x[2:5]` is `3`.

If the last index equals the length the list (`6`, in this case), it
too may be omitted. Negative indices may also be used to count
backwards from the end of the list. This means that the following are
equivalent:

- `x[0:2]` or `x[:2]`

- `x[2:6]` or `x[2:]`

- `x[0:6]` or `x[:]`

Note that `:` refers to a slice extending over the whole
dimension. Thus `x[:]` is a copy of the list `x` containing the same
elements. For a one-dimensional list, this notation is only used to
make a copy of the list. However, it plays a more important role in
multi-dimensional arrays to be discussed later.


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

Tags: slicing, index; array, index; list, index

Notes: Since python list indices start at `0`, the fourth element is
actually `y[3]`. This may seem a bit confusing at first, but you will
get used to it!



---

Consider the list

    y = [1, 4, 9, 16, 25, 36, 49, 64]

What is the notation for the last element of list `y`?

Answer: `y[7]` OR `y[-1]`

Tags: slicing, index; array, index; list, index 

Notes: There are eight elements in the list. Both `y[7]` and `y[-1]`
refer to the last element, with the latter notation counting backwards
from the end. The negative notation is very useful for a dynamically
created list, where you do not know the length before hand.

To refer to the last element, `y[-1]` is  more convenient than
`y[len(y)-1]`, which involves using the length function to extract the last
element of a dynamically created list.

---

Consider the list

    y = [1, 4, 9, 16, 25, 36, 49, 64]

What is the notation for the slice of list `y` consisting of elements
`[25, 36, 49]`?

A.. `y[3:5]`

B.. `y[4:6]`

C.. `y[5:7]`

D.. `y[4:7]`

E.. `y[5:8]`

Answer: D

Tags: slicing, range; array, slice

Notes: Note that `y[4:7]` includes elements `y[4]` through `y[6]`, but not
`y[7]`.


---

Consider the list

    y = [1, 4, 9, 16, 25, 36, 49, 64]

What is the notation for the slice consisting of just the third
element, `[9]`? (Note that `y[2]` denotes the third element, which is
just the number `9`. It is *not* the slice containing the third
element, which is a list with one element, `[9]`.)

Answer: `y[2:3]`

Tags: slicing, range; array, slice

Notes: `y[2:3]` is a list containing just the element `y[2]`. Its
length will be 1.

---

Consider the list

    y = [1, 4, 9, 16, 25, 36, 49, 64]

What is `len(y[4:4])`?

Answer: 0

Tags: slicing, range; list, empty 

Notes: `y[4:4]` yields a list of length zero, i.e., equivalent to `[]`

---

Consider the list

    y = [1, 4, 9, 16, 25, 36, 49, 64]

What is the notation for the last-but-one element of list `y`, using
negative index notation?

Answer: `y[-2]`

Tags: slicing, index; array, negative index

Notes: Because `y[-1]` is the last element.

---

Consider the list

    y = [1, 4, 9, 16, 25, 36, 49, 64]

What is the notation for the slice consisting of the first 3 elements
of the list?

Answer: `y[0:3]` OR `y[:3]`

Tags: slicing, range; list, empty  
 
Notes: The initial `0` in a slice range can be omitted.

---

Consider the list

    y = [1, 4, 9, 16, 25, 36, 49, 64]

What is the notation for the slice consisting of the last 2 elements
of the list?

Answer: `y[6:8]` OR `y[6:]` OR `y[-2:]`

Tags: slicing, range; array, slicing
 
Notes: The final index in a slice range can be omitted. Negative
indices may sometimes be more convenient. The list `y[-2:]` includes `y[-2]`
and `y[-1]`, i.e., the last two elements.

---

Consider the list

    y = [1, 4, 9, 16, 25, 36, 49, 64]

What is the notation for the slice consisting of all elements of the
list?

Answer: `y[0:8]` OR `y[0:]` OR `y[:8]` OR `y[:]`

Tags: slicing, range; array, slicing
 
Notes: The notation `y[:]` is commonly used to denote a complete slice
of all elements, omitting the starting and ending indices.

---

Consider the list

    y = [1, 4, 9, 16, 25, 36, 49, 64]

What is the notation for the slice consisting of `[25, 36, 49]`, using
only negative indices?

Answer: `y[-4:-1]`

Tags: slicing, range; array, slicing; array, negative index
 
Notes: `y[-4:-1]` includes `y[-4]`, `y[-3]`, and `y[-2]`, but *not*
`y[-1]` (the last element)


If you answered the previous set of questions all correctly, you
have the option of skipping ahead to the next section on
[Two-dimensional arrays](#) anytime. Otherwise, you will need to answer
more practice questions on one-dimensional slicing.

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

Consider the list

    fibonacci = [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]

What notation would you use to refer to the element with value `34`?

Answer: `fibonacci[9]` OR `fibonacci[-1]`

Notes: There are 10 elements in the list `fibonacci`. Therefore, the
last element, which has value `34`, is `fibonacci[9]` (counting from
0). Negative indices start at `-1` for the last element.

---

Consider the list

    fibonacci = [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]

What notation would you use to refer to the element with value `21`?

Answer: `fibonacci[8]` OR `fibonacci[-2]`

Notes: Because it is the 9th element. 

---

Consider the list

    fibonacci = [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]

What notation would you use to refer to the slice `[2, 3, 5, 8]`?

Answer: `fibonacci[3:7]` OR `fibonacci[3:-3]`

Notes: The slice includes the 4th, 5th, 6th and 7th elements.

---

Consider the list

    fibonacci = [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]

What is the length of the slice `fibonacci[1:-1]`?

Answer: 8

Notes: The slice excludes the first (index `0`) and last (index `-1`)
elements of the 10-element list

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


However, lists of lists can be cumbersome and inefficient to work with. A better
option is to use `numpy`, which provides support for arrays with many
dimensions. To generate a `numpy` data array from a list of lists, use
the `np.array()` method.

```
import numpy as np
np_matrix = np.array(matrix)

print np_matrix
```

```nb_output
[[1 2 3]
 [4 5 6]]
```

---

## Indexing 2-dimensional arrays

To select a particular element from a 2-dimensiona
