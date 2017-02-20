<!--slidoc-defaults --pace=2 --slide_delay=5 -->

# Introduction to `xarray` and `netCDF`

This tutorial contains an interactive introduction to `xarray`, the
python package for manipulation N-dimensional data arrays with
metadata.

`xarray` will be used to read and manipulate data from a
netCDF file.

Tags: xarray

## History

[xarray](http://xarray.pydata.org/en/stable/index.html)

- Previously called `xray`

- Developed by the [The Climate Corporation](http://climate.com) in 2014.

- Inspired by `pandas`


[pandas](http://pandas.pydata.org):

- *Python Data Analysis* library.

- Originally developed for use in the financial industry

- Provides versatile indexing and spreadsheet-like capabilities for
analyzing tabular data.

Tags: xarray, history

---

## xarray

- A `pandas`-like package for multi-dimensional arrays in the physical sciences

- Like an *in-memory representation* of a netCDF File

A netCDF file dimensions, coordinate variables, data variables, and attributes.

`xarray` deals with with main object types:

 - `DataSet`, which corresponds to a whole netCDF file

 - `DataArray`, which corresponds to a single variable in the netCDF file


Tags: xarray, overview

---


## DataArray and Dataset

A `DataArray` is like a `numpy` array with metadata like dimension labels. It has the
following properties:

    values, dims, coords, attrs


A `DataSet` is a dictionary of `DataArray` objects. It is like an
in-memory representation of a netCDF file.

![img](http://xarray.pydata.org/en/stable/_images/dataset-diagram.png)


Tags: xarray, DataArray; xarray, DataSet

---

## Creating a DataArray

Using the `xr.DataArray()` constructor, you can create a data array
from a list, a list of lists, or a `numpy` array.

    # Create DataArray from a random 2x3 numpy array
    arr_from_np_array = xr.DataArray(np.random.randn(2, 3))
	arr_from_np_array

    list_array = [ [1, 2, 3], [4, 5, 6] ]
    arr_from_list = xr.DataArray(list_array)
	arr_from_list

Try out the above commands in a Notebook cell.

Tags: xarray, create

---

In the previous code example, what is the name of the second dimension of `arr_from_list`?

Answer: dim_1

Tags: xarray, create DataArray; xarray, dimensions

Notes: Typing `arr_from_list` produces the following output:

    <xarray.DataArray (dim_0: 2, dim_1: 3)>
    array([[1, 2, 3],
           [4, 5, 6]])
    Coordinates:
      * dim_0    (dim_0) int64 0 1
      * dim_1    (dim_1) int64 0 1 2

`xarray` assigns default names to dimensions of the form
`dim_0`, `dim_1`, etc.

---

## Dimensions

You can explicitly specify the names for the dimensions

    # Temperature values for four times in a day 0, 6, 12, 18 hours 
    # At two locations: 'inside', 'outside'
	data = [ [ 3

Tags: xarray, dimensions

---

## Indexing a DataArray

- Positional: `rain[4,:]` like for `numpy` arrays

- Using coordinate labels: `rain['May']`

- Using dimension names: `rain.sel(time=slice('Mar', 'Jun'))` or `rain.isel(time=slice(2, 5))`


---

## xarray and netCDF files

[Tutorial](http://nbviewer.jupyter.org/github/nicolasfauchereau/metocean/blob/master/notebooks/xray.ipynb)

```
dset = xray.open_dataset('air.mon.ltm.nc')

dset
```

---

Download the file `air.mon.ltm.nc` from
[pyintro.org](http://pyintro.org) using the following code:

    import urllib
	urllib.urlretrieve('http://pyintro.org/static/atmo321/data/air.mon.ltm.nc', 'air.mon.ltm.nc')

This will save the file to the folder where your Jupyter notebooks are
saved. Check that it `air.mon.ltm.nc` appears in the Notebook Dashboard.

---

Open the file using `xray` as follows:

```
dset = xray.open_dataset('air.mon.ltm.nc')

dset
```

This created a `Dataset` object containing all the data and metadata
from the netCDF file.

---

Now you will need to answer a few questions on the topic of metatadata. If you
answer them all correctly using a single attempt, you may proceed to the
next topic. If you miss any of them, you will need to review
additional material on this topic and answer additional questions.

---

Question 1a

Answer: correct

---

Question 1b

Answer: correct

---

Question 1c

Answer: text

Notes: If you answered the previous set of questions all correctly,
you may proceed directly to [Topic 2](#)


---

## Review portion

More stuff here

---


Question 1e

Answer: text

---


Question 1d

Answer: text

---

## Topic 2


---

more stuff


---

more 
