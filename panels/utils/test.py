from panels.utils.customize import Functions


names = [name for name in dir(Functions) if not name.startswith('__')] # excluding system functions
functions = [f for f in names if callable(getattr(Functions, f))]
functions = [getattr(Functions, f) for f in functions]

# print(functions)

for f in functions:
    print(f.column)
    data = {'Age' : 20, 'Sample' : 'Text'}
    f(data)