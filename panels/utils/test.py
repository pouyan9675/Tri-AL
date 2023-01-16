import customize


names = [name for name in dir(customize.Functions) if not name.startswith('__')] # excluding system functions
functions = [f for f in names if callable(getattr(customize.Functions, f))]
functions = [getattr(customize.Functions, f) for f in functions]

# print(functions)

for f in functions:
    print(f.column)
    data = {'Age' : 20, 'Sample' : 'Text'}
    f(data)